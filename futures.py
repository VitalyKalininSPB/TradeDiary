# -*- coding: utf-8 -*-
"""Фьючерсы FORTS (Мосбиржа): спецификация контракта и денежная математика.

Чистый модуль (requests, без Qt). Первая поддерживаемая база — **Brent (BR)**.

Как устроен фьючерс BR на Мосбирже:
  * котировка — USD за баррель (например, 95.87);
  * 1 контракт = 10 баррелей (`LOTVOLUME`);
  * расчёты в рублях: стоимость шага цены `STEPPRICE` (₽) за `MINSTEP` ($);
    стоимость 1 пункта цены = STEPPRICE / MINSTEP (≈ 10 bbl × курс USD/RUB);
  * при открытии позиции блокируется гарантийное обеспечение (ГО,
    `INITIALMARGIN`, ₽ на контракт), а не полная стоимость контракта;
  * месячные контракты: `BR-11.26` (SHORTNAME) = `BRX6` (SECID).

Тикер сделки хранится как SHORTNAME (`BR-11.26`) — он читаемый и совпадает с
прежней конвенцией `FutureUtil` («БАЗА-ММ.ГГ»). Вводить можно `BR` (ближайший
неистёкший контракт), `BR-11.26`, `BRX6` в любом регистре.

Денежные формулы (в рублях, qty — число контрактов):
  pnl       = (exit − entry) × point_value × qty × (+1 LONG / −1 SHORT)
  risk      = |entry − stop| × point_value × qty
  notional  = price × point_value × qty
  margin    = initial_margin × qty
"""
import datetime
import logging
import math
import re
import threading
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

ISS = 'https://iss.moex.com/iss/engines/futures/markets/forts'

# Базовые активы, для которых включена поддержка в форме сделки.
SUPPORTED_ASSETS = {
    'BR': 'Brent',
}

# Предупреждение, если до последнего дня торгов осталось меньше N дней.
EXPIRY_WARN_DAYS = 5

SPEC_TTL_SECONDS = 300

# Месячные коды фьючерсов (F=янв … Z=дек).
MONTH_CODES = 'FGHJKMNQUVXZ'

_SHORT_RE = re.compile(r'^([A-Z0-9]+)-(\d{1,2})\.(\d{2})$')


@dataclass
class FutureSpec:
    """Спецификация одного фьючерсного контракта FORTS."""
    secid: str = ''            # BRX6
    shortname: str = ''        # BR-11.26
    asset: str = ''            # BR
    last_trade_date: str = ''  # ISO 2026-11-02
    min_step: float = 0.0      # 0.01 $
    step_price: float = 0.0    # 8.40657 ₽ за шаг
    initial_margin: float = 0.0  # ГО, ₽ на контракт
    lot_volume: int = 0        # 10 баррелей
    last: float = 0.0          # последняя цена ($/bbl), 0 если нет сделок
    settle: float = 0.0        # расчётная цена текущей сессии / предыдущей

    @property
    def point_value(self):
        """Стоимость изменения цены на 1.0 (₽ на контракт)."""
        return point_value(self.min_step, self.step_price)

    @property
    def price(self):
        """Лучшая доступная цена: last → settle."""
        return self.last or self.settle or 0.0

    def days_to_expiry(self, today=None):
        return days_to_expiry(self.last_trade_date, today)


# ------------------------------------------------------------------- math

def point_value(min_step, step_price):
    """₽ за 1.0 изменения цены на контракт. 0 при некорректном шаге."""
    if not min_step or min_step <= 0 or step_price is None:
        return 0.0
    return float(step_price) / float(min_step)


def _sign(direction):
    d = getattr(direction, 'value', direction)
    return -1.0 if str(d).upper() == 'SHORT' else 1.0


def pnl_rub(entry, exit_price, qty, direction, pv):
    """Результат позиции в рублях (вариационная маржа, накопленная)."""
    return (float(exit_price) - float(entry)) * float(pv) * float(qty) * _sign(direction)


def risk_rub(entry, stop, qty, pv):
    """Риск до стопа в рублях."""
    return abs(float(entry) - float(stop)) * float(pv) * float(qty)


def notional_rub(price, qty, pv):
    """Номинальная стоимость позиции в рублях."""
    return float(price) * float(pv) * float(qty)


def margin_rub(qty, initial_margin):
    """Заблокированное ГО в рублях."""
    return float(initial_margin) * float(qty)


def contracts_from_notional(desired_usd, price, pv, usd_rate):
    """Число контрактов из желаемого номинала в USD: floor(desired / notional_1)."""
    if desired_usd is None or desired_usd <= 0:
        return None
    if not price or not pv or not usd_rate:
        return 0
    one_usd = price * pv / usd_rate
    if one_usd <= 0:
        return 0
    return math.floor(desired_usd / one_usd)


def days_to_expiry(last_trade_date, today=None):
    """Календарных дней до последнего дня торгов (None, если даты нет)."""
    if not last_trade_date:
        return None
    try:
        d = datetime.date.fromisoformat(str(last_trade_date)[:10])
    except ValueError:
        return None
    today = today or datetime.date.today()
    return (d - today).days


def expiry_issue(last_trade_date, today=None):
    """(blocker, warning) по дате экспирации. Каждое — строка или None."""
    days = days_to_expiry(last_trade_date, today)
    if days is None:
        return None, None
    if days < 0:
        return 'Контракт истёк {} — выберите следующий месяц.'.format(
            last_trade_date), None
    if days <= EXPIRY_WARN_DAYS:
        return None, ('До экспирации {} дн. ({}) — подумайте о следующем '
                      'контракте.'.format(days, last_trade_date))
    return None, None


# ----------------------------------------------------------- ticker names

def asset_of(ticker):
    """Базовый актив по вводу: 'BR', 'BR-11.26', 'BRX6' -> 'BR'. Иначе None."""
    t = (ticker or '').strip().upper()
    if not t:
        return None
    if t in SUPPORTED_ASSETS:
        return t
    m = _SHORT_RE.match(t)
    if m and m.group(1) in SUPPORTED_ASSETS:
        return m.group(1)
    # SECID: база(2) + код месяца + цифра года, напр. BRX6.
    if (len(t) == 4 and t[:2] in SUPPORTED_ASSETS
            and t[2] in MONTH_CODES and t[3].isdigit()):
        return t[:2]
    return None


def is_supported_future(ticker):
    return asset_of(ticker) is not None


def shortname_to_secid(shortname):
    """'BR-11.26' -> 'BRX6' (для двухбуквенных баз). None при неверном формате."""
    m = _SHORT_RE.match((shortname or '').strip().upper())
    if not m:
        return None
    base, month, year = m.group(1), int(m.group(2)), m.group(3)
    if not 1 <= month <= 12 or len(base) != 2:
        return None
    return '{}{}{}'.format(base, MONTH_CODES[month - 1], year[-1])


# ------------------------------------------------------------------ fetch

_cache = {}   # asset -> (time, [FutureSpec])
_cache_lock = threading.Lock()


def _table(data, name):
    block = data.get(name, {}) or {}
    cols = block.get('columns', []) or []
    return [dict(zip(cols, row)) for row in block.get('data', []) or []]


def parse_iss(data, asset):
    """Разобрать ответ ISS (securities + marketdata) в список FutureSpec.

    Выделено отдельно ради тестов на синтетических данных.
    """
    md = {r.get('SECID'): r for r in _table(data, 'marketdata')}
    out = []
    for r in _table(data, 'securities'):
        if (r.get('ASSETCODE') or '').upper() != asset:
            continue
        m = md.get(r.get('SECID'), {})
        out.append(FutureSpec(
            secid=r.get('SECID') or '',
            shortname=r.get('SHORTNAME') or '',
            asset=asset,
            last_trade_date=str(r.get('LASTTRADEDATE') or ''),
            min_step=float(r.get('MINSTEP') or 0.0),
            step_price=float(r.get('STEPPRICE') or 0.0),
            initial_margin=float(r.get('INITIALMARGIN') or 0.0),
            lot_volume=int(r.get('LOTVOLUME') or 0),
            last=float(m.get('LAST') or 0.0),
            settle=float(m.get('SETTLEPRICE') or r.get('PREVSETTLEPRICE')
                         or 0.0),
        ))
    out.sort(key=lambda s: s.last_trade_date)
    return out


def fetch_contracts(asset, ttl=SPEC_TTL_SECONDS):
    """Все торгуемые контракты базы (по возрастанию экспирации). Сеть + TTL-кэш.

    При ошибке сети возвращает последний известный список (или []).
    Вызывать только из фонового потока.
    """
    asset = (asset or '').upper()
    with _cache_lock:
        hit = _cache.get(asset)
        if hit and time.time() - hit[0] < ttl:
            return list(hit[1])
    url = ('{}/securities.json?assetcode={}&iss.meta=off'
           '&iss.only=securities,marketdata'.format(ISS, asset))
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        specs = parse_iss(r.json(), asset)
    except Exception as e:
        log.warning('Failed to fetch FORTS contracts for %s: %s', asset, e)
        return list(hit[1]) if hit else []
    with _cache_lock:
        _cache[asset] = (time.time(), specs)
    return list(specs)


def pick_contract(specs, ticker, today=None):
    """Выбрать контракт из списка по вводу пользователя.

    'BR' -> ближайший неистёкший; 'BR-11.26' / 'BRX6' -> точное совпадение.
    """
    t = (ticker or '').strip().upper()
    today = today or datetime.date.today()
    if t in SUPPORTED_ASSETS:
        for s in specs:
            d = days_to_expiry(s.last_trade_date, today)
            if d is None or d >= 0:
                return s
        return None
    for s in specs:
        if t in (s.secid.upper(), s.shortname.upper()):
            return s
    return None


def resolve(ticker):
    """FutureSpec по вводу пользователя или None. Сеть — только из фона."""
    asset = asset_of(ticker)
    if asset is None:
        return None
    return pick_contract(fetch_contracts(asset), ticker)


def secid_for(ticker):
    """SECID для запросов свечей: 'BR-11.26' -> 'BRX6', 'BRX6' -> 'BRX6'."""
    t = (ticker or '').strip().upper()
    if _SHORT_RE.match(t):
        return shortname_to_secid(t)
    return t
