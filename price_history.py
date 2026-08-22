# -*- coding: utf-8 -*-
"""SQLite cache of historical prices + correlation computation.

History is backfilled when a ticker enters the portfolio (not on matrix view).
WINDOW_DAYS controls how many recent trading points are kept per asset.
"""
import os
import sqlite3
import datetime
import time
import requests

import numpy as np

import markets

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'price_history.db')

# Trading days of history kept per asset (configurable).
WINDOW_DAYS = 90

# Buffer multiplier for natural days -> a bit more than WINDOW trading days to
# absorb weekends and exchange holidays.
_DAY_BUF = 2.5

_UA = {'User-Agent': 'Mozilla/5.0'}


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS price_history ("
        "ticker TEXT NOT NULL, date TEXT NOT NULL, price REAL NOT NULL, "
        "PRIMARY KEY (ticker, date))")
    return conn


def save_prices(ticker, series):
    """series: iterable of (date_str, price). Upserts and trims to WINDOW_DAYS."""
    conn = _conn()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO price_history (ticker, date, price) VALUES (?,?,?)",
            [(ticker, d, float(p)) for d, p in series])
        conn.commit()
    finally:
        conn.close()
    _trim(ticker)


def _trim(ticker):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT date FROM price_history WHERE ticker=? ORDER BY date DESC",
            (ticker,)).fetchall()
        if len(rows) > WINDOW_DAYS:
            cutoff = rows[WINDOW_DAYS][0]
            conn.execute("DELETE FROM price_history WHERE ticker=? AND date<?",
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


def _fetch_moex_history(ticker, ndays):
    to = datetime.date.today()
    frm = to - datetime.timedelta(days=int(ndays * _DAY_BUF))
    url = ('https://iss.moex.com/iss/engines/stock/markets/shares/'
           'securities/{}/candles.json?interval=24&from={}&till={}'
           .format(ticker, frm, to))
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    candles = data.get('candles', {}).get('data', [])
    cols = data.get('candles', {}).get('columns', [])
    ci = cols.index('close')
    bi = cols.index('begin')
    out = {}
    for row in candles:
        d = str(row[bi])[:10]
        out[d] = float(row[ci])
    return _drop_today(out)


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
        d = datetime.datetime.utcfromtimestamp(t).strftime('%Y-%m-%d')
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


def fetch_history(ticker, currency):
    """Return {date_str: price} for ticker according to its market currency."""
    if currency == markets.RUB:
        return _fetch_moex_history(ticker, WINDOW_DAYS)
    try:
        return _fetch_yahoo_history(ticker, WINDOW_DAYS)
    except Exception as e:
        print('Yahoo history failed for {}: {}; trying stooq'.format(ticker, e))
        return _fetch_stooq_history(ticker, WINDOW_DAYS)


def ensure_history(ticker, currency):
    """Backfill cached history for a ticker if missing or stale. No-op if fresh."""
    series = load_series(ticker)
    if len(series) >= WINDOW_DAYS:
        return
    try:
        fetched = fetch_history(ticker, currency)
    except Exception as e:
        print('Failed to fetch history for {}: {}'.format(ticker, e))
        return
    if fetched:
        save_prices(ticker, fetched.items())


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
        series_list.append((t, load_series(t)))

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
