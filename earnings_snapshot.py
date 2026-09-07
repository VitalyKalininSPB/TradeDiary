# -*- coding: utf-8 -*-
"""Earnings Snapshot — извлечение последних 4 кварталов из SEC EDGAR XBRL.

Только Quantitative Assessment из официального JSON API SEC:
  - https://www.sec.gov/files/company_tickers.json  (тикер -> CIK)
  - https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json

Не извлекаются guidance, комментарии менеджмента, причины изменений,
производственные/отраслевые KPI, транскрипты и новости.

Правила (см. AGENTS.md -> Earnings Snapshot):
  * потоковые метрики (revenue, net_income, ocf, capex) нормализуются из
    quarterly/YTD(FY) длительностей; YTD сам по себе НЕ принимается как квартал;
  * quarter k выводится как прямой 3M-факт, если он есть, иначе как разность
    накопительных (H1-Q1, 9M-H1, FY-9M);
  * EPS берётся ТОЛЬКО прямым 3M-фактом (EPS не аддитивны);
  * балансовые метрики — point-in-time на конец квартала, без QoQ/YoY;
  * отсутствующая метрика = null/status missing, никогда не 0;
  * для одинакового периода выбирается последний filing (restated).
"""
import datetime
import json
import os
import sqlite3
import threading
import time

import requests

_TODAY = datetime.date.today()

# --------------------------------------------------------------------------
# SEC endpoints / headers / rate limit
# --------------------------------------------------------------------------
_SEC_UA = ('TradeDiary/1.0 (trading-diary project; '
           'contact@example.com)')
_SEC_HEADERS = {
    'User-Agent': _SEC_UA,
    'Accept-Encoding': 'gzip, deflate',
    'Accept': 'application/json',
}
_TICKER_URL = 'https://www.sec.gov/files/company_tickers.json'
_FACTS_URL = 'https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json'
_REQ_INTERVAL = 0.12          # SEC: <= 10 req/s
_TIMEOUT = 30
_N_RETRIES = 3

_CACHE_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DB = os.path.join(_CACHE_DIR, 'earnings_cache.db')
CACHE_TTL_HOURS = 24

MAX_QUARTERS = 4

# --------------------------------------------------------------------------
# XBRL concepts (fallback order)
# --------------------------------------------------------------------------
_FLOW_CONCEPTS = {
    'revenue': [
        'RevenueFromContractWithCustomerExcludingAssessedTax',
        'SalesRevenueNet',
        'Revenues',
        'RevenueFromContractWithCustomerIncludingAssessedTax',
    ],
    'net_income': ['NetIncomeLoss', 'ProfitLoss'],
    'eps': ['EarningsPerShareDiluted'],                       # unit: USD/shares
    'ocf': [
        'NetCashProvidedByUsedInOperatingActivities',
        'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations',
    ],
    'capex': [
        'PaymentsToAcquirePropertyPlantAndEquipment',
        'PaymentsToAcquireProductiveAssets',
        'PaymentsForProceedsFromOtherPropertyPlantAndEquipment',
    ],
}

_CASH_TAGS = [
    'CashAndCashEquivalentsAtCarryingValue',
    'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents',
]

# debt: предпочтение — пара *LeaseObligations*; иначе сумма
# short-term + current-LT + non-current-LT без дублирующих тегов.
_DEBT_LEASE_TAGS = [
    'LongTermDebtAndFinanceLeaseObligationsCurrent',
    'LongTermDebtAndFinanceLeaseObligationsNoncurrent',
]
_DEBT_SHORT_TAGS = ['ShortTermBorrowings', 'ShortTermDebt']
_DEBT_CUR_TAGS = ['LongTermDebtCurrent', 'CurrentPortionOfLongTermDebt']
_DEBT_NONCUR_TAGS = ['LongTermDebtNoncurrent', 'LongTermDebt']

_CORE_METRICS = [
    'revenue', 'net_income', 'diluted_eps', 'ocf', 'capex', 'fcf',
    'cash', 'total_debt', 'net_debt', 'net_margin',
]

_FORM_RANK = {'10-K': 0, '10-Q': 1}


# --------------------------------------------------------------------------
# Network layer (with SEC rate limiting)
# --------------------------------------------------------------------------
_LOCK = threading.Lock()
_LAST_REQUEST = 0.0


def _get_json(url):
    """GET JSON с rate limiting и ретраями. None при неудаче."""
    global _LAST_REQUEST
    last_err = None
    for attempt in range(_N_RETRIES):
        with _LOCK:
            wait = _REQ_INTERVAL - (time.monotonic() - _LAST_REQUEST)
            if wait > 0:
                time.sleep(wait)
            _LAST_REQUEST = time.monotonic()
        try:
            r = requests.get(url, headers=_SEC_HEADERS, timeout=_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 403:
                last_err = 'SEC rate limit (403)'
                time.sleep(1.0 + attempt)
                continue
            if r.status_code == 404:
                return None
            last_err = 'HTTP {}'.format(r.status_code)
        except requests.RequestException as e:  # noqa: BLE001
            last_err = str(e)
        time.sleep(0.5 * (attempt + 1))
    return None


def _load_cached(key, ttl_hours):
    conn = _conn()
    try:
        row = conn.execute(
            'SELECT val, fetched_at FROM kv WHERE key=?', (key,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    val, fetched = row
    try:
        fetched_dt = datetime.datetime.fromisoformat(fetched)
    except ValueError:
        return None
    age = datetime.datetime.now() - fetched_dt
    if age.total_seconds() > ttl_hours * 3600:
        return None
    return val


def _save_cached(key, val):
    conn = _conn()
    try:
        conn.execute(
            'INSERT OR REPLACE INTO kv (key, val, fetched_at) VALUES (?,?,?)',
            (key, val, datetime.datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()


def _conn():
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute('CREATE TABLE IF NOT EXISTS kv ('
                 'key TEXT PRIMARY KEY, val TEXT NOT NULL, '
                 'fetched_at TEXT NOT NULL)')
    return conn


def cik_for_ticker(ticker):
    """10-символьный CIK по тикеру или None."""
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return None
    cached = _load_cached('ticker_map', CACHE_TTL_HOURS)
    if cached is not None:
        try:
            mapping = json.loads(cached)
        except (TypeError, ValueError, json.JSONDecodeError):
            mapping = None
    else:
        mapping = None
    if mapping is None:
        raw = _get_json(_TICKER_URL)
        if raw is None:
            # Пробуем более старый (всё равно свежий) кэш без TTL
            stale = _load_cached('ticker_map', CACHE_TTL_HOURS * 24 * 7)
            try:
                mapping = json.loads(stale) if stale else None
            except (TypeError, ValueError, json.JSONDecodeError):
                mapping = None
        else:
            mapping = raw
            try:
                _save_cached('ticker_map', json.dumps(raw))
            except Exception as e:  # noqa: BLE001 - cache best-effort
                print('earnings_snapshot: failed to cache ticker map: {}'
                      .format(e))
    if not mapping:
        return None
    for item in mapping.values():
        if str(item.get('ticker', '')).upper() == ticker:
            return '{:010d}'.format(int(item['cik_str']))
    return None


def fetch_company_facts(cik):
    """Company Facts JSON (с кэшем). None при недоступности."""
    if not cik:
        return None
    cik_key = 'facts:{}'.format(cik)
    cached = _load_cached(cik_key, CACHE_TTL_HOURS)
    if cached is not None:
        try:
            return json.loads(cached)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    payload = _get_json(_FACTS_URL.format(int(cik)))
    if payload is None:
        return None
    try:
        _save_cached(cik_key, json.dumps(payload))
    except Exception as e:  # noqa: BLE001 - cache best-effort
        print('earnings_snapshot: failed to cache {}: {}'.format(cik, e))
    return payload


# --------------------------------------------------------------------------
# Pure XBRL parsing (no network)
# --------------------------------------------------------------------------
def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def _duration_class(e):
    """Класс длительности потока по (start, end). None — не классифицировано.

    Q  — одиночный квартал (3 месяца),
    H1 — 6 месяцев,
    9M — 9 месяцев,
    FY — год (10-K).
    """
    start = _parse_date(e.get('start'))
    end = _parse_date(e.get('end'))
    if start is None or end is None or end <= start:
        return None
    days = (end - start).days
    if 55 <= days <= 150:
        return 'Q'
    if 150 < days <= 210:
        return 'H1'
    if 210 < days <= 330:
        return '9M'
    if 330 < days <= 400:
        return 'FY'
    return None


def _better(new, old):
    """True, если entry new предпочтительнее old для (конец квартала, класс)."""
    nr = _FORM_RANK.get(new.get('form'), 2)
    or_ = _FORM_RANK.get(old.get('form'), 2)
    if nr != or_:
        return nr < or_
    return (new.get('filed') or '') > (old.get('filed') or '')


def _pick_best(entries, keyfn):
    """Среди entries выбрать лучший по (form_rank, filed) для каждого keyfn."""
    best = {}
    for e in entries:
        k = keyfn(e)
        if k in best:
            if _better(e, best[k]):
                best[k] = e
        else:
            best[k] = e
    return best


def _tag_entries(gau, tag, unit='USD'):
    node = gau.get(tag)
    if not node:
        return []
    out = []
    for e in node.get('units', {}).get(unit, []):
        e = dict(e)
        e['tag'] = tag
        out.append(e)
    return out


def _culc_fiscal_grid(flow_entries):
    """Глобальная сетка кварталов по концам потоков.

    Returns (ends, end_meta, buckets, fy_end_of) with
      ends:     sorted quarter-end dates (дата-объекты, <= today)
      end_meta: {end: (fy, qi)}
      buckets:  {fy: [ends]} с сортировкой
      fy_of_end: {end: fy}
    """
    ok = []
    for e in flow_entries:
        end = _parse_date(e.get('end'))
        if end is None or end > _TODAY:
            continue
        if e.get('val') is None:
            continue
        if _duration_class(e) is None:
            continue
        ok.append((end, e))
    if not ok:
        return [], {}, {}, {}

    all_ends = sorted({end for end, _ in ok})

    fy_by_end = {}
    for end, e in ok:
        fyv = e.get('fy')
        try:
            fyv = int(fyv)
        except (TypeError, ValueError):
            continue
        cur = fy_by_end.get(end)
        if cur is None or fyv < cur:
            fy_by_end[end] = fyv
    for end in all_ends:
        if end not in fy_by_end:
            fy_by_end[end] = end.year

    buckets = {}
    for end in all_ends:
        buckets.setdefault(fy_by_end[end], []).append(end)
    for ends in buckets.values():
        ends.sort()

    end_meta = {}
    for fy, ends in buckets.items():
        for qi, end in enumerate(ends, 1):
            end_meta[end] = (fy, qi)

    return all_ends, end_meta, buckets, fy_by_end


def _flow_series(entries, grid):
    """Квартальные значения по потоку на основе глобальной GRID.

    Возвращает {(fy, qi): dict(value, status, source_tag, derived)}.
    Сетка (all_ends, end_meta, buckets) вычисляется один раз в
    _culc_fiscal_grid и передаётся, чтобы серии разных метрик совпадали.
    """
    _a, end_meta, buckets, _ = grid
    best = _pick_best(entries, lambda e: (e.get('end'), _duration_class(e)))
    direct = {}
    cum = {}
    for e in best.values():
        end = _parse_date(e.get('end'))
        if end is None:
            continue
        dcls = _duration_class(e)
        if dcls == 'Q':
            direct[end] = e
        elif dcls in ('H1', '9M', 'FY'):
            cum[end] = e

    qvals = {}
    for fy, ends in buckets.items():
        cprev = None
        for end in ends:
            qi = end_meta[end][1]
            d = direct.get(end)
            c = cum.get(end)
            if d is not None:
                val = d['val']
                status, source, derived = 'available', d['tag'], False
            elif c is not None and cprev is not None:
                val = c['val'] - cprev['val']
                status, source, derived = 'derived', c['tag'], True
            else:
                val = None
                status, source, derived = 'missing', None, False
            qvals[(fy, qi)] = {
                'value': val,
                'status': status,
                'source_tag': source,
                'derived': derived,
            }
            # цепочка YTD: для следующего квартала важен накопительный факт
            if c is not None:
                cprev = c
            elif d is not None:
                cprev = d
    return qvals


def _flow_series_exact(entries, grid):
    """Поток, где берётся ТОЛЬКО прямой 3M-факт (для EPS)."""
    _a, end_meta, buckets, _ = grid
    best = _pick_best(entries, lambda e: (e.get('end'), _duration_class(e)))
    direct = {}
    for e in best.values():
        if _duration_class(e) == 'Q':
            direct.setdefault(_parse_date(e.get('end')), e)
    qvals = {}
    for fy, ends in buckets.items():
        for end in ends:
            qi = end_meta[end][1]
            d = direct.get(end)
            if d is not None:
                qvals[(fy, qi)] = {
                    'value': d['val'], 'status': 'available',
                    'source_tag': d['tag'], 'derived': False,
                }
    return qvals


def _instant_map(entries):
    """{end: {'val', 'tag'}} — point-in-time значения, latest filing wins."""
    best = _pick_best(entries, lambda e: e.get('end'))
    out = {}
    for e in best.values():
        end = _parse_date(e.get('end'))
        if end is not None and e.get('val') is not None:
            out[end] = {'val': e['val'], 'tag': e['tag']}
    return out


def _pick_flow_tag(gau, tags, unit, grid, exact=False):
    """Первый тег из fallback-цепочки, покрывающий последние кварталы.

    Предпочитается «чистый» (первичный) концепт: берём первый тег, у которого
    есть данные в последних MAX_QUARTERS кварталах сетки. Только если ни один
    из тегов не покрывает недавние кварталы, выбираем максимум по всей истории.
    """
    _a, end_meta, _b, _f = grid
    grid_keys = sorted(set(end_meta.values()))
    last_keys = set(grid_keys[-MAX_QUARTERS:])
    builder = _flow_series_exact if exact else _flow_series

    best_overall = None
    best_cov = -1
    for tag in tags:
        entries = _tag_entries(gau, tag, unit)
        series = builder(entries, grid)
        recent = sum(1 for k in last_keys
                     if series.get(k, {}).get('value') is not None)
        if recent:
            return tag, entries, series
        cov = sum(1 for k in grid_keys
                  if series.get(k, {}).get('value') is not None)
        if cov > best_cov:
            best_cov = cov
            best_overall = (tag, entries, series)
    return best_overall


# --------------------------------------------------------------------------
# Debt
# --------------------------------------------------------------------------
def _debt_value(debt_maps, end):
    """total_debt на конец квартала. (value, components, status, note)."""
    def gv(tag):
        m = debt_maps.get(tag)
        v = (m or {}).get(end)
        return (v or {}).get('val') if v else None

    lc = gv('LongTermDebtAndFinanceLeaseObligationsCurrent')
    ln = gv('LongTermDebtAndFinanceLeaseObligationsNoncurrent')
    if lc is not None and ln is not None:
        return (lc + ln,
                [('LongTermDebtAndFinanceLeaseObligationsCurrent', lc),
                 ('LongTermDebtAndFinanceLeaseObligationsNoncurrent', ln)],
                'available', 'lease-обязательства могут быть включены')

    def first_present(*tags):
        for tag in tags:
            v = gv(tag)
            if v is not None:
                return tag, v
        return None, None

    short_tag, short = first_present(*_DEBT_SHORT_TAGS)
    curlt_tag, curlt = first_present(*_DEBT_CUR_TAGS)
    noncur_tag, noncur = first_present(*_DEBT_NONCUR_TAGS)

    if noncur_tag is None and (short is None and curlt is None):
        return None, [], 'missing', None

    if noncur_tag == 'LongTermDebt':
        # CRC-кейс: LongTermDebt может включать current portion -> не дублируем.
        parts = []
        if short is not None:
            parts.append((short_tag, short))
        parts.append((noncur_tag, noncur))
        note = 'LongTermDebt может включать current-часть и lease'
        multi = [(t, v) for t, v in parts]
        value = sum(v for _, v in parts)
        status = 'available' if len(parts) >= 2 else 'partial'
        src = '+'.join(t for t, _ in multi)
        return value, multi, status, note

    parts = []
    if short is not None:
        parts.append((short_tag, short))
    if curlt is not None:
        parts.append((curlt_tag, curlt))
    if noncur is not None:
        parts.append((noncur_tag, noncur))
    if not parts:
        return None, [], 'missing', None
    value = sum(v for _, v in parts)
    status = 'available' if len(parts) >= 2 else 'partial'
    return value, parts, status, None


# --------------------------------------------------------------------------
# Main pure computation
# --------------------------------------------------------------------------
def _empty_result(ticker, cik, reason, warnings=None):
    return {
        'ticker': ticker,
        'cik': cik,
        'source': 'SEC EDGAR Company Facts',
        'as_of_filed_date': None,
        'status': 'unavailable',
        'missing_metrics': list(_CORE_METRICS),
        'warnings': [reason] + (warnings or []),
        'derived_metrics': [],
        'source_coverage': {m: 0 for m in _CORE_METRICS},
        'quarters': [],
    }


def compute_snapshot(ticker, cik, facts_doc):
    """Чистый расчёт снапшота из JSON Company Facts (без сети)."""
    warnings = []
    gau = (facts_doc or {}).get('facts', {}).get('us-gaap', {})
    if not gau:
        return _empty_result(ticker, cik,
                             'Company Facts не содержат us-gaap данных')

    # 1. Собрать все кандидат-entries потоков для построения единой сетки.
    flow_entries = []
    for tags, unit in ((_FLOW_CONCEPTS['revenue'], 'USD'),
                       (_FLOW_CONCEPTS['net_income'], 'USD'),
                       (_FLOW_CONCEPTS['eps'], 'USD/shares'),
                       (_FLOW_CONCEPTS['ocf'], 'USD'),
                       (_FLOW_CONCEPTS['capex'], 'USD')):
        for tag in tags:
            for e in _tag_entries(gau, tag, unit):
                flow_entries.append(e)

    all_ends, end_meta, buckets, fy_by_end = _culc_fiscal_grid(flow_entries)
    if not all_ends:
        return _empty_result(ticker, cik,
                             'В Company Facts нет квартальных потоков '
                             'за завершённые периоды', warnings)
    relevant_fys = {end_meta[e][0] for e in all_ends[-MAX_QUARTERS:]}
    lo = min(relevant_fys) - 1
    for fy, ends in buckets.items():
        if fy < lo:
            continue
        if len(ends) != 4:
            warnings.append(
                'Фискальный год {}: найдено {} кварталов '
                '(ожидалось 4)'.format(fy, len(ends)))

    grid = (all_ends, end_meta, buckets, fy_by_end)

    # 2. Потоковые метрики (fallback-тег по покрытию).
    series = {}
    for metric, (tags, unit, exact) in (
            ('revenue', (_FLOW_CONCEPTS['revenue'], 'USD', False)),
            ('net_income', (_FLOW_CONCEPTS['net_income'], 'USD', False)),
            ('eps', (_FLOW_CONCEPTS['eps'], 'USD/shares', True)),
            ('ocf', (_FLOW_CONCEPTS['ocf'], 'USD', False)),
            ('capex', (_FLOW_CONCEPTS['capex'], 'USD', False))):
        entries = []
        for tag in tags:
            entries += _tag_entries(gau, tag, unit)
        tag, _ent, s = _pick_flow_tag(gau, tags, unit, grid, exact=exact)
        series[metric] = s
        if tag is None or not _ent:
            warnings.append('{}: ни один XBRL-тег не найден'.format(metric))
        elif tags.index(tag) > 0:
            warnings.append('{}: использован fallback-тег {}'.format(
                metric, tag))
        elif not exact and not s and _ent:
            warnings.append(
                '{}: только накопительные значения без разрывов '
                '(возможны пропуски)'.format(metric))

    # capex: нормализовать знак (cash outflow может быть отрицательным).
    capex_norm = {}
    for (fy, qi), m in series.get('capex', {}).items():
        entry = dict(m)
        if entry.get('value') is not None and entry['value'] < 0:
            entry['value'] = -entry['value']
            entry['sign_flipped'] = True
        capex_norm[(fy, qi)] = entry
    series['capex'] = capex_norm

    # 3. Балансовые метрики (instant) и их отображение на сетку.
    cash_maps = {}
    for tag in _CASH_TAGS:
        cash_maps[tag] = _instant_map(_tag_entries(gau, tag, 'USD'))
    cash_series = {}
    for end in all_ends:
        entry = _instant_map_of(cash_maps, end)
        if entry is not None:
            cash_series[(fy_by_end[end], end_meta[end][1])] = entry

    debt_maps = {}
    for tag in (_DEBT_LEASE_TAGS + _DEBT_SHORT_TAGS + _DEBT_CUR_TAGS
                + _DEBT_NONCUR_TAGS):
        debt_maps[tag] = _instant_map(_tag_entries(gau, tag, 'USD'))
    debt_series = {}
    for end in all_ends:
        value, comps, status, note = _debt_value(debt_maps, end)
        if value is not None:
            debt_series[(fy_by_end[end], end_meta[end][1])] = {
                'value': value, 'components': comps,
                'source_tag': '+'.join(t for t, _ in comps),
                'source_note': note, 'status': status,
            }

    # 4. Производные метрики по всем концам сетки (для YoY/QoQ вне окна).
    derived = {}
    for end in all_ends:
        key = end_meta[end]
        ocf = series['ocf'].get(key, {}).get('value')
        capex = series['capex'].get(key, {}).get('value')
        if ocf is not None and capex is not None:
            derived[(end, 'fcf')] = ocf - abs(capex)
        rev = series['revenue'].get(key, {}).get('value')
        ni = series['net_income'].get(key, {}).get('value')
        if rev and ni is not None:
            derived[(end, 'net_margin')] = ni / rev
        td = debt_series.get(key, {}).get('value')
        cs = cash_series.get(key)
        if td is not None and cs is not None and cs['val'] is not None:
            derived[(end, 'net_debt')] = td - cs['val']

    return _assemble(ticker, cik, facts_doc, gau, warnings,
                     all_ends, end_meta, buckets, series, cash_series,
                     debt_series, derived)


def _instant_map_of(cash_maps, end):
    """Лучшее cash-значение на конец квартала (prefer чистый cash)."""
    for tag in _CASH_TAGS:
        v = cash_maps[tag].get(end)
        if v is not None:
            if tag == _CASH_TAGS[1]:
                return {'val': v['val'], 'tag': v['tag'],
                        'note': 'может включать restricted cash',
                        'status': 'available'}
            return {'val': v['val'], 'tag': v['tag'],
                    'note': None, 'status': 'available'}
    return None


def _pct(cur, prev):
    if cur is None or prev is None:
        return None
    if prev == 0 or abs(prev) < 1e-9:
        return None
    return (cur / prev - 1.0) * 100.0


def _fmt_metric(spec):
    """Пустой словарь метрики из схемы."""
    if spec.get('kind') == 'flow':
        return {'value': None, 'yoy_pct': None, 'qoq_pct': None,
                'source_tag': None, 'derived': False,
                'status': 'missing'}
    if spec.get('kind') == 'eps':
        return {'value': None, 'yoy_pct': None, 'qoq_pct': None,
                'source_tag': None, 'derived': False,
                'status': 'missing'}
    if spec.get('kind') == 'cash':
        return {'value': None, 'source_tag': None, 'source_note': None,
                'status': 'missing'}
    if spec.get('kind') == 'debt':
        return {'value': None, 'components': [], 'source_tag': None,
                'source_note': None, 'status': 'missing'}


def _assemble(ticker, cik, facts_doc, gau, warnings,
              all_ends, end_meta, buckets, series, cash_series, debt_series,
              derived):
    last_ends = all_ends[-MAX_QUARTERS:]

    # as_of_filed_date: самый свежий filing среди использованных фактов.
    filed_dates = []
    for tag in (sum(_FLOW_CONCEPTS.values(), []) + _CASH_TAGS + _DEBT_LEASE_TAGS
                + _DEBT_SHORT_TAGS + _DEBT_CUR_TAGS + _DEBT_NONCUR_TAGS):
        for u in ('USD', 'USD/shares'):
            for e in _tag_entries(gau, tag, u):
                f = e.get('filed')
                if f:
                    filed_dates.append(f)
    as_of = max(filed_dates) if filed_dates else None

    def lookup(metric, end):
        key = end_meta[end]
        m = series.get(metric, {}).get(key)
        return m

    def prev_end(end):
        idx = all_ends.index(end)
        return all_ends[idx - 1] if idx > 0 else None

    quarters_out = []
    all_values = {m: {} for m in _CORE_METRICS}

    for end in last_ends:
        fy, qi = end_meta[end]
        q = {
            'period_end': end.isoformat(),
            'fiscal_year': fy,
            'fiscal_quarter': qi,
        }
        # предыдущий квартал (для QoQ) и тот же квартал прошлого года (YoY)
        prev = prev_end(end)
        yoy_end = None
        for fy2, ends in buckets.items():
            if fy2 == fy - 1 and len(end_meta) >= 0:
                for e2 in ends:
                    if end_meta[e2][1] == qi:
                        yoy_end = e2
                        break
                break

        # ---- flow-метрики ----
        flow_out = (('revenue', 'flow'), ('net_income', 'flow'),
                    ('diluted_eps', 'eps'), ('ocf', 'flow'),
                    ('capex', 'flow'))
        for out_metric, kind in flow_out:
            metric = 'eps' if out_metric == 'diluted_eps' else out_metric
            spec = {'kind': kind}
            m = _fmt_metric(spec)
            src = lookup(metric, end)
            if src and src.get('value') is not None:
                m['value'] = src['value']
                m['status'] = src['status']
                m['source_tag'] = src.get('source_tag')
                m['derived'] = src.get('derived', False)
                want_yoy = kind in ('flow', 'eps')
                if want_yoy and yoy_end is not None:
                    prev_src = lookup(metric, yoy_end)
                    if prev_src and prev_src.get('value') is not None:
                        m['yoy_pct'] = _pct(m['value'],
                                            prev_src['value'])
                if prev is not None:
                    prev_src = lookup(metric, prev)
                    if prev_src and prev_src.get('value') is not None:
                        m['qoq_pct'] = _pct(m['value'],
                                            prev_src['value'])
            if m['value'] is not None:
                all_values[out_metric][(fy, qi)] = m['value']
            q[out_metric] = m

        # ---- cash / total_debt ----
        m_cash = _fmt_metric({'kind': 'cash'})
        cs = cash_series.get((fy, qi))
        if cs is not None:
            m_cash['value'] = cs['val']
            m_cash['source_tag'] = cs['tag']
            m_cash['source_note'] = cs['note']
            m_cash['status'] = 'available'
            all_values['cash'][(fy, qi)] = cs['val']
            if cs.get('note'):
                warnings_maybe = ('cash: {}'.format(cs['note']))
                if warnings_maybe not in warnings:
                    warnings.append(warnings_maybe)
        q['cash'] = m_cash

        m_debt = _fmt_metric({'kind': 'debt'})
        ds = debt_series.get((fy, qi))
        if ds is not None:
            m_debt['value'] = ds['value']
            m_debt['components'] = [
                {'tag': t, 'value': v} for t, v in ds['components']]
            m_debt['source_tag'] = ds['source_tag']
            m_debt['source_note'] = ds['source_note']
            m_debt['status'] = ds['status']
            all_values['total_debt'][(fy, qi)] = ds['value']
        q['total_debt'] = m_debt

        # ---- derived ----
        m_fcf = {'value': None, 'yoy_pct': None, 'qoq_pct': None,
                 'formula': 'ocf - capex', 'derived': True,
                 'status': 'missing'}
        fcf_val = derived.get((end, 'fcf'))
        if fcf_val is not None:
            m_fcf['value'] = fcf_val
            m_fcf['status'] = 'available'
            all_values['fcf'][(fy, qi)] = fcf_val
            if yoy_end is not None:
                m_fcf['yoy_pct'] = _pct(
                    fcf_val, derived.get((yoy_end, 'fcf')))
            if prev is not None:
                m_fcf['qoq_pct'] = _pct(
                    fcf_val, derived.get((prev, 'fcf')))
        q['fcf'] = m_fcf

        m_nd = {'value': None, 'formula': 'total_debt - cash',
                'derived': True, 'status': 'missing'}
        nd_val = derived.get((end, 'net_debt'))
        if nd_val is not None:
            m_nd['value'] = nd_val
            m_nd['status'] = 'available'
            all_values['net_debt'][(fy, qi)] = nd_val
        q['net_debt'] = m_nd

        m_margin = {'value': None, 'yoy_pp': None, 'qoq_pp': None,
                    'formula': 'net_income / revenue', 'derived': True,
                    'status': 'missing'}
        margin = derived.get((end, 'net_margin'))
        if margin is not None:
            m_margin['value'] = margin
            m_margin['status'] = 'available'
            all_values['net_margin'][(fy, qi)] = margin
            if yoy_end is not None:
                prev_m = derived.get((yoy_end, 'net_margin'))
                if prev_m is not None:
                    m_margin['yoy_pp'] = (margin - prev_m) * 100.0
            if prev is not None:
                prev_m = derived.get((prev, 'net_margin'))
                if prev_m is not None:
                    m_margin['qoq_pp'] = (margin - prev_m) * 100.0
        q['net_margin'] = m_margin

        quarters_out.append(q)

    # ---- общий статус ----
    coverage = {}
    for m in _CORE_METRICS:
        coverage[m] = sum(
            1 for end in last_ends if end_meta[end] in all_values[m])
    status = _overall_status(coverage)
    missing = [m for m in _CORE_METRICS if coverage[m] == 0]
    derived_metrics = sorted({
        m for q in quarters_out for m in _CORE_METRICS
        if q.get(m) and q[m].get('derived')})

    return {
        'ticker': ticker,
        'cik': cik,
        'source': 'SEC EDGAR Company Facts',
        'as_of_filed_date': as_of,
        'status': status,
        'missing_metrics': missing,
        'warnings': warnings,
        'derived_metrics': derived_metrics,
        'source_coverage': coverage,
        'quarters': quarters_out,
    }


def _overall_status(coverage):
    base = ('revenue', 'net_income', 'diluted_eps')
    base_full = all(coverage[m] == MAX_QUARTERS for m in base)
    all_full = all(coverage[m] == MAX_QUARTERS for m in _CORE_METRICS)
    if all_full:
        return 'complete'
    if base_full:
        return 'partial'
    base_hit = sum(coverage[m] for m in base)
    if base_hit >= MAX_QUARTERS * 2:
        return 'partial'
    return 'insufficient'


def net_margin_yoy_from_facts(facts_doc):
    """Net margin YoY (в п.п.) из Company Facts — детерминированный fallback.

    Берёт последний квартал с полными данными (revenue, net_income) и тот же
    квартал прошлого года: net_margin = net_income / revenue, разность в
    процентных пунктах. None, если кварталы несопоставимы.
    """
    gau = (facts_doc or {}).get('facts', {}).get('us-gaap', {})
    if not gau:
        return None
    flow_entries = []
    for tags, unit in ((_FLOW_CONCEPTS['revenue'], 'USD'),
                       (_FLOW_CONCEPTS['net_income'], 'USD')):
        for tag in tags:
            flow_entries += _tag_entries(gau, tag, unit)
    all_ends, end_meta, buckets, fy_by_end = _culc_fiscal_grid(flow_entries)
    if not all_ends:
        return None
    grid = (all_ends, end_meta, buckets, fy_by_end)
    picked_r = _pick_flow_tag(gau, _FLOW_CONCEPTS['revenue'], 'USD', grid)
    picked_n = _pick_flow_tag(gau, _FLOW_CONCEPTS['net_income'], 'USD', grid)
    if picked_r is None or picked_n is None:
        return None
    rev_series = picked_r[2]
    ni_series = picked_n[2]
    if rev_series is None or ni_series is None:
        return None
    for k in reversed(sorted(set(end_meta.values()))):
        fy, qi = k
        r = (rev_series.get(k) or {}).get('value')
        n = (ni_series.get(k) or {}).get('value')
        if r is None or n is None or r == 0:
            continue
        yk = (fy - 1, qi)
        rp = (rev_series.get(yk) or {}).get('value')
        np_ = (ni_series.get(yk) or {}).get('value')
        if rp is None or np_ is None or rp == 0:
            continue
        cur_m = n / r
        prev_m = np_ / rp
        if cur_m == cur_m and prev_m == prev_m:
            return (cur_m - prev_m) * 100.0
    return None


# --------------------------------------------------------------------------
# Orchestration (network + cache)
# --------------------------------------------------------------------------
def build_earnings_snapshot(ticker, use_cache=True):
    """Полный снапшот по тикеру. Возвращает dict (см. compute_snapshot)."""
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return _empty_result(ticker, None, 'Пустой тикер')

    if use_cache:
        cached = _load_cached('snapshot:{}'.format(ticker), CACHE_TTL_HOURS)
        if cached is not None:
            try:
                return json.loads(cached)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass

    cik = cik_for_ticker(ticker)
    if not cik:
        return _empty_result(ticker, None,
                             'CIK не найден для тикера {} в SEC '
                             'company_tickers'.format(ticker))
    facts = fetch_company_facts(cik)
    if facts is None:
        return _empty_result(ticker, cik,
                             'SEC Company Facts недоступны для CIK {}'.format(
                                 cik))
    result = compute_snapshot(ticker, cik, facts)
    if use_cache:
        try:
            _save_cached('snapshot:{}'.format(ticker), json.dumps(result))
        except Exception as e:  # noqa: BLE001 - cache best-effort
            print('earnings_snapshot: failed to cache snapshot: {}'
                  .format(e))
    return result


def net_margin_yoy_for(ticker, use_cache=True):
    """Net margin YoY (в п.п.) из SEC Company Facts (кэш 24ч).

    Возвращает (value, reason): value — None при неудаче; reason None при
    успехе, иначе один из: source_empty (тикер не найден в SEC),
    http_error (факты недоступны), calculation_unavailable (нет сопоставимых
    кварталов).
    """
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return None, 'source_empty'
    if use_cache:
        cached = _load_cached('margin_yoy:{}'.format(ticker), CACHE_TTL_HOURS)
        if cached is not None:
            try:
                return json.loads(cached)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
    cik = cik_for_ticker(ticker)
    if not cik:
        return None, 'source_empty'
    facts = fetch_company_facts(cik)
    if facts is None:
        return None, 'http_error'
    value = net_margin_yoy_from_facts(facts)
    reason = None if value is not None else 'calculation_unavailable'
    if use_cache:
        try:
            _save_cached('margin_yoy:{}'.format(ticker),
                         json.dumps([value, reason]))
        except Exception as e:  # noqa: BLE001 - cache best-effort
            print('earnings_snapshot: failed to cache margin_yoy: {}'
                  .format(e))
    return value, reason


def main():
    """CLI: python earnings_snapshot.py TICKER."""
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'CRC'
    result = build_earnings_snapshot(ticker)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()