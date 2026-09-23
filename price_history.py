# -*- coding: utf-8 -*-
"""SQLite cache of historical prices + correlation computation.

History is backfilled when a ticker enters the portfolio (not on matrix view).
WINDOW_DAYS controls how many recent trading points are kept per asset.
"""
import os
import sqlite3
import datetime
import time
import logging
import requests

import numpy as np

import futures
import markets

log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'price_history.db')

# Trading days of history returned for correlation (configurable).
WINDOW_DAYS = 90

# Max natural days of cached daily history per asset (used by the MA chart).
CHART_DAYS = 730  # ~2 years, free scrolling on the moving-average chart.

# Buffer multiplier for natural days -> a bit more than trading days to
# absorb weekends and exchange holidays.
_DAY_BUF = 2.5

_UA = {'User-Agent': 'Mozilla/5.0'}


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS price_history ("
        "ticker TEXT NOT NULL, date TEXT NOT NULL, price REAL NOT NULL, "
        "PRIMARY KEY (ticker, date))")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ohlc_history ("
        "ticker TEXT NOT NULL, date TEXT NOT NULL, "
        "open REAL, high REAL, low REAL, close REAL NOT NULL, "
        "PRIMARY KEY (ticker, date))")
    return conn


def save_prices(ticker, series, keep=CHART_DAYS):
    """series: iterable of (date_str, price). Upserts and trims to `keep` days."""
    conn = _conn()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO price_history (ticker, date, price) VALUES (?,?,?)",
            [(ticker, d, float(p)) for d, p in series])
        conn.commit()
    finally:
        conn.close()
    _trim(ticker, keep)


def _trim(ticker, keep=CHART_DAYS, table='price_history'):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT date FROM {} WHERE ticker=? ORDER BY date DESC".format(table),
            (ticker,)).fetchall()
        if len(rows) > keep:
            cutoff = rows[keep][0]
            conn.execute("DELETE FROM {} WHERE ticker=? AND date<?".format(table),
                         (ticker, cutoff))
            conn.commit()
    finally:
        conn.close()


def load_series(ticker):
    """Return {date_str: price} for a ticker, oldest first order irrelevant."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT date, price FROM price_history WHERE ticker=? ORDER BY date",
            (ticker,)).fetchall()
        return {d: p for d, p in rows}
    finally:
        conn.close()


def clear_db():
    conn = _conn()
    try:
        conn.execute("DELETE FROM price_history")
        conn.commit()
    finally:
        conn.close()


def _drop_today(series):
    today = datetime.date.today().isoformat()
    return {d: p for d, p in series.items() if d != today}


def _fetch_moex_candles(ticker, ndays):
    """Paginate MOEX daily candles, return {date: (open, high, low, close)}.

    Фьючерсы FORTS (BR-11.26 / BRX6) берутся с рынка futures/forts по SECID.
    """
    to = datetime.date.today()
    frm = to - datetime.timedelta(days=int(ndays * _DAY_BUF))
    out = {}
    start = 0
    if futures.is_supported_future(ticker):
        base = futures.ISS
        secid = futures.secid_for(ticker)
    else:
        base = 'https://iss.moex.com/iss/engines/stock/markets/shares'
        secid = ticker
    while True:
        url = ('{}/securities/{}/candles.json?interval=24&from={}&till={}&start={}'
               .format(base, secid, frm, to, start))
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        candles = data.get('candles', {}).get('data', [])
        cols = data.get('candles', {}).get('columns', [])
        bi = cols.index('begin')
        oi = cols.index('open')
        hi = cols.index('high')
        li = cols.index('low')
        ci = cols.index('close')
        for row in candles:
            d = str(row[bi])[:10]
            out[d] = (float(row[oi]), float(row[hi]), float(row[li]), float(row[ci]))
        start += len(candles)
        if len(candles) < 500:
            break
    return out


def _fetch_moex_history(ticker, ndays):
    out = _fetch_moex_candles(ticker, ndays)
    closes = {d: ohlc[3] for d, ohlc in out.items()}
    return _drop_today(closes)


def _fetch_yahoo_history(ticker, ndays):
    period1 = int(time.mktime(
        (datetime.date.today() - datetime.timedelta(days=int(ndays * _DAY_BUF)))
        .timetuple()))
    period2 = int(time.time())
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/{}'
           '?period1={}&period2={}&interval=1d'.format(ticker, period1, period2))
    r = requests.get(url, headers=_UA, timeout=10)
    r.raise_for_status()
    result = r.json()['chart']['result'][0]
    ts = result['timestamp']
    closes = result['indicators']['quote'][0]['close']
    out = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.datetime.fromtimestamp(t, datetime.UTC).strftime('%Y-%m-%d')
        out[d] = float(c)
    return _drop_today(out)


def _fetch_stooq_history(ticker, ndays):
    url = 'https://stooq.com/q/d/l/?s={}.us&i=d'.format(ticker.lower())
    r = requests.get(url, headers=_UA, timeout=10)
    r.raise_for_status()
    out = {}
    for line in r.text.strip().splitlines()[1:]:
        parts = line.split(',')
        if len(parts) < 5:
            continue
        d = parts[0]
        try:
            out[d] = float(parts[4])
        except ValueError:
            continue
    items = sorted(out.items())[-ndays:]
    return _drop_today(dict(items))


def fetch_history(ticker, currency, ndays=CHART_DAYS):
    """Return {date_str: price} for ticker according to its market currency."""
    if currency == markets.RUB:
        return _fetch_moex_history(ticker, ndays)
    try:
        return _fetch_yahoo_history(ticker, ndays)
    except Exception as e:
        log.warning('Yahoo history failed for %s: %s; trying stooq', ticker, e)
        return _fetch_stooq_history(ticker, ndays)


def ensure_history(ticker, currency, want_days=CHART_DAYS):
    """Backfill cached history for a ticker if missing or stale.

    Fetches the full chart depth (~CHART_DAYS) so the moving-average chart has
    ~2 years of data to scroll. No-op when already cached at that depth.
    """
    series = load_series(ticker)
    if len(series) >= want_days:
        return
    try:
        fetched = fetch_history(ticker, currency, want_days)
    except Exception as e:
        log.warning('Failed to fetch history for %s: %s', ticker, e)
        return
    if fetched:
        save_prices(ticker, fetched.items(), keep=CHART_DAYS)


# ---------------------------------------------------------------------------
# OHLC support (used by the candlestick chart). Stored separately so the
# close-only correlation/MA path above is unaffected.
# ---------------------------------------------------------------------------

def _drop_today_ohlc(series):
    today = datetime.date.today().isoformat()
    return {d: v for d, v in series.items() if d != today}


def _fetch_moex_ohlc(ticker, ndays):
    out = _fetch_moex_candles(ticker, ndays)
    return _drop_today_ohlc(out)


def _fetch_yahoo_ohlc(ticker, ndays):
    period1 = int(time.mktime(
        (datetime.date.today() - datetime.timedelta(days=int(ndays * _DAY_BUF)))
        .timetuple()))
    period2 = int(time.time())
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/{}'
           '?period1={}&period2={}&interval=1d'.format(ticker, period1, period2))
    r = requests.get(url, headers=_UA, timeout=10)
    r.raise_for_status()
    result = r.json()['chart']['result'][0]
    ts = result['timestamp']
    quote = result['indicators']['quote'][0]
    out = {}
    for t, o, h, l, c in zip(ts, quote['open'], quote['high'], quote['low'], quote['close']):
        if c is None:
            continue
        d = datetime.datetime.fromtimestamp(t, datetime.UTC).strftime('%Y-%m-%d')
        out[d] = (float(o or c), float(h or c), float(l or c), float(c))
    return _drop_today_ohlc(out)


def _fetch_stooq_ohlc(ticker, ndays):
    url = 'https://stooq.com/q/d/l/?s={}.us&i=d'.format(ticker.lower())
    r = requests.get(url, headers=_UA, timeout=10)
    r.raise_for_status()
    out = {}
    for line in r.text.strip().splitlines()[1:]:
        parts = line.split(',')
        if len(parts) < 5:
            continue
        d = parts[0]
        try:
            cols = [float(x) for x in parts[1:5]]
            out[d] = (cols[0], cols[1], cols[2], cols[3])
        except ValueError:
            continue
    items = sorted(out.items())[-ndays:]
    return _drop_today_ohlc(dict(items))


def fetch_ohlc(ticker, currency, ndays=CHART_DAYS):
    """Return {date_str: (open, high, low, close)} for ticker/currency."""
    if currency == markets.RUB:
        return _fetch_moex_ohlc(ticker, ndays)
    try:
        return _fetch_yahoo_ohlc(ticker, ndays)
    except Exception as e:
        log.warning('Yahoo OHLC failed for %s: %s; trying stooq', ticker, e)
        return _fetch_stooq_ohlc(ticker, ndays)


def save_ohlc(ticker, series, keep=CHART_DAYS):
    conn = _conn()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO ohlc_history (ticker, date, open, high, low, close) "
            "VALUES (?,?,?,?,?,?)",
            [(ticker, d, o, h, l, c) for d, (o, h, l, c) in series])
        conn.commit()
    finally:
        conn.close()
    _trim(ticker, keep, 'ohlc_history')


def load_ohlc(ticker, keep=CHART_DAYS):
    """Return sorted [(date, open, high, low, close)] for a ticker."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT date, open, high, low, close FROM ohlc_history "
            "WHERE ticker=? ORDER BY date", (ticker,)).fetchall()
    finally:
        conn.close()
    if len(rows) > keep:
        rows = rows[-keep:]
    return [(d, float(o), float(h), float(l), float(c)) for d, o, h, l, c in rows]


def ensure_ohlc(ticker, currency, want_days=CHART_DAYS):
    rows = load_ohlc(ticker)
    if len(rows) >= want_days:
        return
    try:
        fetched = fetch_ohlc(ticker, currency, want_days)
    except Exception as e:
        log.warning('Failed to fetch OHLC for %s: %s', ticker, e)
        return
    if fetched:
        save_ohlc(ticker, fetched.items(), keep=CHART_DAYS)


def load_recent(ticker, days=WINDOW_DAYS):
    """Return {date_str: price} for the most recent `days` cached points."""
    series = load_series(ticker)
    items = sorted(series.items())
    if len(items) > days:
        items = items[-days:]
    return dict(items)


def _return_matrix(series_list):
    """series_list: list of (ticker, {date: price}). Returns aligned returns array."""
    if len(series_list) < 2:
        return None, series_list[0][0]
    common = None
    for _, s in series_list:
        dates = set(s)
        common = dates if common is None else common & dates
    if not common:
        return None, None
    common = sorted(common)
    prices = np.array([[s[d] for d in common] for _, s in series_list], dtype=float)
    ret = np.diff(prices, axis=1) / prices[:, :-1]
    return ret, np.array([t for t, _ in series_list])


def build_correlation(tickers_currency):
    """Compute pairwise daily-return correlation from cached history.

    tickers_currency: dict ticker -> currency (only open portfolio assets).
    Returns (tickers, corr_matrix, portfolio_corr) where corr_matrix is a numpy
    array (NaN for pairs with too few overlapping returns) and portfolio_corr is
    the USD-value-weighted mean pairwise correlation.
    """
    tickers = list(tickers_currency.keys())
    series_list = []
    for t in tickers:
        ensure_history(t, tickers_currency[t])
        series_list.append((t, load_recent(t, WINDOW_DAYS)))

    if len(tickers) < 2:
        n = len(tickers)
        m = np.full((n, n), np.nan)
        np.fill_diagonal(m, 1.0)
        return np.array(tickers), m, 0.0

    ret, ret_tickers = _return_matrix(series_list)
    if ret is None or ret.shape[1] < 2 or ret.shape[0] < 2:
        return np.array(tickers), np.full((len(tickers), len(tickers)), np.nan), 0.0

    corr = np.corrcoef(ret)
    np.fill_diagonal(corr, 1.0)
    return ret_tickers, corr, corr


def weighted_portfolio_corr(matrix, weights):
    """weights: {ticker: usd_weight}. Returns value-weighted mean pairwise corr."""
    n = len(weights)
    if n < 2:
        return 0.0
    num = 0.0
    den = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            w = weights[i] * weights[j]
            c = matrix[i, j]
            if w > 0 and np.isfinite(c):
                num += w * c
                den += w
    return (num / den) if den > 0 else 0.0
