# -*- coding: utf-8 -*-
"""Technical timing для Simple Mode (без Qt).

Чистый модуль: по дневным ценам считает SMA50/SMA200, RSI(14) (Wilder),
MACD(12,26,9) и статус готовности к входу по стороне идеи (long/short).

Философия (см. рекомендации):
  - Technical timing НЕ ищет идеальный вход. Он только не даёт открыть Long
    в явно плохой технической ситуации и Short в явно опасной.
  - RSI / растянутость НЕ блокируют вход: при READY это лишь мягкое
    предупреждение (жёлтая строка / подсказка козы).
  - Три статуса: READY TO CONSIDER ENTRY / WAIT / REASSESS.
  - Статус не зависит от катализатора (тот виден отдельно в Watchlist).

Модель статуса (детерминированная):
  Для long конфликты: цена < SMA200; death cross (SMA50 < SMA200);
  MACD bearish (line < signal). Для short — зеркально.
  0 конфликтов -> READY; 1 -> WAIT; 2-3 -> REASSESS; мало данных -> no_data.

Хранение: SQLite `technical_timing.db`, kv (ticker, direction) -> json.
Паттерн БД — как catalyst.py / earnings_cache.db. TTL 24 часа.
Цены берутся из price_history.db (ensure/fetch в фоновом потоке через
compute_fresh; на UI-потоке модуль только читает кэш и считает по ряду).
"""
import datetime
import json
import os
import sqlite3

import markets
import price_history

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DIR, 'technical_timing.db')

# Пороги-константы (эвристики v1, как в simple_mode.py).
_RSI_OVERBOUGHT = 70.0
_RSI_OVERSOLD = 30.0
_MIN_POINTS = 220        # нужно для SMA200 + MACD (примерно год дневных цен)
_TTL_HOURS = 24          # срок жизни кэшированного результата
_PRICE_STALE_DAYS = 4    # цены старше -> перезагружать в фоне

_STATUS_TXT = {
    'ready': 'READY TO CONSIDER ENTRY',
    'wait': 'WAIT',
    'reassess': 'REASSESS',
    'no_data': 'Нет данных',
}
_STATUS_COLOR = {
    'ready': '#81c784',
    'wait': '#f0c14b',
    'reassess': '#ef5350',
    'no_data': '#9aa0aa',
}

_BAND_RU = {
    'overbought': 'overbought',
    'oversold': 'oversold',
    'neutral': 'neutral',
}
_MACD_RU = {'bullish': 'Bullish', 'bearish': 'Bearish'}

_NO_DATA_REASON = ('Недостаточно истории цен (нужно ~{} торговых дней) — '
                   'технический статус не рассчитан.'.format(_MIN_POINTS))


# ---------------------------------------------------------------------------
# Индикаторы (чистая математика, только стандартная библиотека)
# ---------------------------------------------------------------------------

def _sma(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _ema_series(values, window):
    """Полный ряд EMA (seed = первое значение). Обычная практика для short."""
    if not values:
        return []
    k = 2.0 / (window + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def _ema(values, window):
    if not values:
        return None
    return _ema_series(values, window)[-1]


def _rsi(closes, period=14):
    """RSI(14) по Wilder. Монотонно вверх -> 100, вниз -> 0, иначе [0;100]."""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(ch if ch > 0 else 0.0)
        losses.append(-ch if ch < 0 else 0.0)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _macd(closes, fast=12, slow=26, signal=9):
    """(macd_line, signal_line, histogram) на последнем баре или (None,...)."""
    if len(closes) < slow + signal:
        return None, None, None
    ef = _ema_series(closes, fast)
    es = _ema_series(closes, slow)
    macd_series = [a - b for a, b in zip(ef, es)]
    sig_series = _ema_series(macd_series, signal)
    macd = macd_series[-1]
    sig = sig_series[-1]
    return macd, sig, macd - sig


def compute_indicators(closes):
    """Все индикаторы одним словарём (closes — список по возрастанию дат)."""
    closes = [float(c) for c in closes]
    price = closes[-1]
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)
    above_sma200 = (price > sma200) if (price is not None
                                        and sma200 is not None) else None
    golden_cross = (sma50 > sma200) if (sma50 is not None
                                        and sma200 is not None) else None
    rsi = _rsi(closes, 14)
    if rsi is None:
        rsi_band = None
    elif rsi >= _RSI_OVERBOUGHT:
        rsi_band = 'overbought'
    elif rsi <= _RSI_OVERSOLD:
        rsi_band = 'oversold'
    else:
        rsi_band = 'neutral'
    macd, macd_signal, macd_hist = _macd(closes, 12, 26, 9)
    macd_state = None
    if macd is not None and macd_signal is not None:
        macd_state = 'bullish' if macd >= macd_signal else 'bearish'
    return {
        'price': price,
        'sma50': sma50,
        'sma200': sma200,
        'above_sma200': above_sma200,
        'golden_cross': golden_cross,
        'rsi': rsi,
        'rsi_band': rsi_band,
        'macd': macd,
        'macd_signal': macd_signal,
        'macd_hist': macd_hist,
        'macd_state': macd_state,
    }


# ---------------------------------------------------------------------------
# Статус (детерминированная логика конфликтов)
# ---------------------------------------------------------------------------

def _conflicts(direction, above_sma200, golden_cross, macd_bull):
    """RU-строки технических конфликтов со стороной идеи (None не считается)."""
    if direction == 'short':
        out = []
        if above_sma200:
            out.append('цена выше SMA 200')
        if golden_cross:
            out.append('golden cross (SMA 50 > SMA 200)')
        if macd_bull:
            out.append('MACD бычий')
        return out
    out = []
    if above_sma200 is False:
        out.append('цена ниже SMA 200')
    if golden_cross is False:
        out.append('death cross (SMA 50 < SMA 200)')
    if macd_bull is False:
        out.append('MACD медвежий')
    return out


def _status_for(n_conflicts):
    if n_conflicts == 0:
        return 'ready'
    if n_conflicts == 1:
        return 'wait'
    return 'reassess'


def _reason(direction, status, conflicts):
    side = 'лонг' if direction == 'long' else 'шорт'
    if status == 'ready':
        return ('Тренд и momentum не создают существенного конфликта с '
                '{}-тезисом.'.format(side))
    joined = ', '.join(conflicts) or 'нет данных'
    if status == 'wait':
        return ('Техническая картина частично противоречит тезису: {}. '
                'Ждать подтверждения — нового cross/MACD или отката к '
                'SMA 200.'.format(joined))
    return ('Техническая картина существенно противоречит тезису: {}. '
            'Прежде чем рассматривать вход, проверить, не изменился ли '
            'фундаментальный тезис.'.format(joined))


def _warning_for(direction, status, rsi_band):
    if status != 'ready':
        return ''
    if direction == 'long' and rsi_band == 'overbought':
        return ('RSI перегрет — акция растянута. Не гнаться за импульсом: '
                'ждать отката или уменьшить позицию.')
    if direction == 'short' and rsi_band == 'oversold':
        return ('RSI перепродан — падение растянуто. Не шортить вдогонку: '
                'ждать отката вверх или уменьшить позицию.')
    return ''


def _fmt(v, nd=2):
    if v is None:
        return None
    return '{:.{}f}'.format(float(v), nd)


def _format_display(res):
    """Заполнить готовые текстовые поля для отображения (без Qt)."""
    price = res.get('price')
    sma50 = res.get('sma50')
    sma200 = res.get('sma200')
    rsi = res.get('rsi')
    band = res.get('rsi_band')
    macd_state = res.get('macd_state')
    above = res.get('above_sma200')
    gc = res.get('golden_cross')

    res['price_txt'] = _fmt(price)
    res['sma50_txt'] = _fmt(sma50)
    res['sma200_txt'] = _fmt(sma200)
    res['price_vs_sma200_txt'] = (
        'Above' if above else 'Below') if above is not None else '—'
    res['cross_txt'] = (
        'Golden Cross active' if gc else 'Death Cross active'
    ) if gc is not None else '—'
    if rsi is None:
        res['rsi_txt'] = '—'
    else:
        res['rsi_txt'] = '{} — {}'.format(
            _fmt(rsi, 0), _BAND_RU.get(band, '—'))
    res['macd_txt'] = _MACD_RU.get(macd_state, '—')
    if res.get('direction') == 'short':
        res['stop_ref'] = ('For Short, review the nearest visible '
                           'resistance.')
    else:
        res['stop_ref'] = ('For Long, review the nearest visible support.')


# ---------------------------------------------------------------------------
# Сборка результата
# ---------------------------------------------------------------------------

def build_timing(ticker, dates, closes, direction='long'):
    """Технический статус по дневным ценам (чистая функция, без сети/БД).

    Возвращает словарь с полями для отображения. direction: 'long'|'short'.
    """
    closes = [float(c) for c in closes]
    dates = list(dates or [])
    base = {
        'ticker': (ticker or '').strip().upper(),
        'direction': direction,
        'computed_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'as_of': dates[-1] if dates else None,
    }
    if len(closes) < _MIN_POINTS:
        res = dict(base)
        res.update({
            'status': 'no_data',
            'status_txt': _STATUS_TXT['no_data'],
            'status_color': _STATUS_COLOR['no_data'],
            'reason': _NO_DATA_REASON,
            'warning': '',
            'conflicts': [],
            'price': closes[-1] if closes else None,
            'sma50': None,
            'sma200': None,
            'above_sma200': None,
            'golden_cross': None,
            'rsi': None,
            'rsi_band': None,
            'macd_state': None,
        })
        _format_display(res)
        return res

    ind = compute_indicators(closes)
    res = dict(base)
    res.update(ind)
    conflicts = _conflicts(direction, ind['above_sma200'], ind['golden_cross'],
                           ind['macd_state'] == 'bullish')
    status = _status_for(len(conflicts))
    res.update({
        'status': status,
        'status_txt': _STATUS_TXT[status],
        'status_color': _STATUS_COLOR[status],
        'reason': _reason(direction, status, conflicts),
        'warning': _warning_for(direction, status, ind['rsi_band']),
        'conflicts': conflicts,
    })
    _format_display(res)
    return res


# ---------------------------------------------------------------------------
# SQLite-кэш
# ---------------------------------------------------------------------------

def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS timing_cache ("
        "ticker TEXT NOT NULL, direction TEXT NOT NULL, "
        "computed_at TEXT NOT NULL, data TEXT NOT NULL, "
        "PRIMARY KEY (ticker, direction))")
    return conn


def save_timing(result):
    if not result or not result.get('ticker'):
        return
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO timing_cache "
            "(ticker, direction, computed_at, data) VALUES (?,?,?,?)",
            (result['ticker'], result.get('direction', 'long'),
             result['computed_at'], json.dumps(result)))
        conn.commit()
    finally:
        conn.close()


def load_timing(ticker, direction='long'):
    """Результат из кэша для тикера/направления или None."""
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return None
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT data FROM timing_cache WHERE ticker=? AND direction=?",
            (ticker, direction)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return None


def load_any_timing(ticker):
    """Любой (любого направления) свежайший результат для тикера или None."""
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return None
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT data FROM timing_cache WHERE ticker=? "
            "ORDER BY computed_at DESC LIMIT 1", (ticker,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return None


def is_fresh(result, ttl_hours=_TTL_HOURS):
    if not result or not result.get('computed_at'):
        return False
    try:
        computed = datetime.datetime.fromisoformat(result['computed_at'])
    except (TypeError, ValueError):
        return False
    return (datetime.datetime.now() - computed).total_seconds() < ttl_hours * 3600


# ---------------------------------------------------------------------------
# Фоновый пересчёт (только вне UI-потока: сеть/БД-запись здесь)
# ---------------------------------------------------------------------------

def _last_date(series):
    return max(series) if series else None


def _is_price_stale(last_date):
    if not last_date:
        return True
    try:
        d = datetime.date.fromisoformat(last_date)
    except (TypeError, ValueError):
        return True
    return (datetime.date.today() - d).days > _PRICE_STALE_DAYS


def _detect_currency(ticker):
    try:
        _market, currency = markets.market_currency(ticker)
    except Exception:  # pragma: no cover - best-effort
        return None
    return currency


def compute_fresh(ticker, direction='long', ttl_hours=_TTL_HOURS):
    """Пересчитать статус, если кэш устарел. Возвращает результат или None.

    Сеть и запись в БД — только здесь (вызывается из фонового потока).
    Если кэш свежий — возвращает None (ничего не делаем).
    """
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return None
    cached = load_timing(ticker, direction)
    if is_fresh(cached, ttl_hours):
        return None
    series = price_history.load_series(ticker)
    if not series or _is_price_stale(_last_date(series)):
        currency = _detect_currency(ticker)
        if currency is not None:
            try:
                fetched = price_history.fetch_history(ticker, currency)
            except Exception:  # pragma: no cover - best-effort
                fetched = None
            if fetched:
                price_history.save_prices(ticker, fetched.items())
                series = price_history.load_series(ticker)
    if not series:
        return None
    items = sorted(series.items())
    dates = [d for d, _ in items]
    closes = [p for _, p in items]
    result = build_timing(ticker, dates, closes, direction)
    save_timing(result)
    return result