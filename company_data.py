# -*- coding: utf-8 -*-
"""Динамические метрики компаний для company-level screener.

Данные (кэш SQLite `sector_quant.db`, TTL 24ч — не чаще раза в день):
- net margin (TTM) и YoY-изменение маржи — из SSR-блока `summary:{...}`
  страницы stockanalysis.com/stocks/{ticker}/ (netIncome/revenue + их YoY growth);
- доходности 1м/1г — из Yahoo chart API (range=1y), как в markets.py.

Бенчмарк сектора (benchmarkReturn1m/1y) берётся из последнего sector-результата.
Если живые метрики недоступны — fallback на статический company_fixture.
"""
import datetime
import os
import re
import sqlite3

import requests

import company_fixture

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DIR, 'sector_quant.db')

TTL_HOURS = 24
_UA = {'User-Agent': 'TradeDiary/1.1 (company-metrics; ti-diary-user@localhost)'}


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS company_metrics ("
        "ticker TEXT PRIMARY KEY, sector TEXT NOT NULL, "
        "net_margin REAL, net_margin_yoy REAL, "
        "return_1m REAL, return_1y REAL, forward_pe REAL, "
        "eps_growth REAL, fetched_at TEXT NOT NULL)")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(company_metrics)")}
    if cols and 'forward_pe' not in cols:
        conn.execute("ALTER TABLE company_metrics ADD COLUMN forward_pe REAL")
    if cols and 'eps_growth' not in cols:
        conn.execute("ALTER TABLE company_metrics ADD COLUMN eps_growth REAL")
    if cols and 'revenue_growth' not in cols:
        conn.execute("ALTER TABLE company_metrics ADD COLUMN revenue_growth REAL")
    return conn


def _grab(pattern, text):
    m = re.search(pattern, text)
    return m.group(1) if m else None


def _parse_abbrev(s):
    """'302.97B' -> 3.0297e11. Handles $ , and T/B/M/K suffixes."""
    if not s:
        return None
    s = s.strip().replace('$', '').replace(',', '')
    mult = 1.0
    if s and s[-1] in 'TBMK':
        mult = {'T': 1e12, 'B': 1e9, 'M': 1e6, 'K': 1e3}[s[-1]]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


# ------------------------------------------------------------------- fetch
def fetch_company_metrics(ticker):
    """Живые метрики компании. None, если не хватает обязательных полей.

    Возвращает dict {net_margin, net_margin_yoy, return_1m, return_1y,
    forward_pe}. forward_pe и net_margin_yoy могут быть None (опционально).
    """
    sa = _stockanalysis_metrics(ticker)
    yh = _yahoo_returns(ticker)
    if not sa or not yh:
        return None
    net_margin, yoy = sa['net_margin'], sa['net_margin_yoy']
    ret_1m, ret_1y = yh
    if net_margin is None or ret_1m is None or ret_1y is None:
        return None
    return {'net_margin': net_margin, 'net_margin_yoy': yoy,
            'return_1m': ret_1m, 'return_1y': ret_1y,
            'forward_pe': sa['forward_pe'], 'eps_growth': sa['eps_growth'],
            'revenue_growth': sa['revenue_growth']}


def _stockanalysis_metrics(ticker):
    """Net margin TTM + YoY (pp) из SSR-блока summary:{...}."""
    r = requests.get('https://stockanalysis.com/stocks/{}/'.format(
        ticker.lower()), headers=_UA, timeout=25)
    r.raise_for_status()
    html = r.text
    m = re.search(r'summary:\{text:"(?:[^"\\]|\\.)*?"\}(.*?),description:',
                  html, re.DOTALL)
    block = m.group(1) if m else html
    revenue = _parse_abbrev(_grab(r'revenue:"([^"]+)"', block))
    net_income = _parse_abbrev(_grab(r'netIncome:"([^"]+)"', block))
    if not revenue or not net_income:
        return None
    margin = net_income / revenue * 100.0
    yoy = None
    ni_g = _grab(r'netIncomeGrowth:(-?[0-9.]+)', block)
    rev_g = _grab(r'revenueGrowth:(-?[0-9.]+)', block)
    if ni_g is not None and rev_g is not None:
        try:
            ni_g, rev_g = float(ni_g), float(rev_g)
            if rev_g > -100.0 and ni_g > -100.0:
                rev_prev = revenue / (1.0 + rev_g / 100.0)
                ni_prev = net_income / (1.0 + ni_g / 100.0)
                if rev_prev > 0 and ni_prev > 0:
                    yoy = margin - (ni_prev / rev_prev * 100.0)
        except (ValueError, ZeroDivisionError):
            yoy = None
    forward_pe = None
    pe_raw = _grab(r'forwardPE:"([^"]+)"', block)
    if pe_raw:
        try:
            pe = float(pe_raw.replace(',', ''))
            if pe == pe and pe > 0:
                forward_pe = pe
        except ValueError:
            forward_pe = None
    eps_growth = None
    eg_raw = _grab(r'epsGrowth:(-?[0-9.]+)', block)
    if eg_raw:
        try:
            eg = float(eg_raw)
            if eg == eg:
                eps_growth = eg
        except ValueError:
            eps_growth = None
    revenue_growth = None
    rg_raw = _grab(r'revenueGrowth:(-?[0-9.]+)', block)
    if rg_raw:
        try:
            rg = float(rg_raw)
            if rg == rg and rg > -100.0:
                revenue_growth = rg
        except ValueError:
            revenue_growth = None
    return {'net_margin': margin, 'net_margin_yoy': yoy,
            'forward_pe': forward_pe, 'eps_growth': eps_growth,
            'revenue_growth': revenue_growth}


def _yahoo_returns(ticker):
    """(return_1m_pct, return_1y_pct) из дневного графика за 1 год."""
    for host in ('query1', 'query2'):
        try:
            url = ('https://{}.finance.yahoo.com/v8/finance/chart/{}'
                   '?range=1y&interval=1d').format(host, ticker)
            r = requests.get(url, headers=_UA, timeout=20)
            r.raise_for_status()
            result = (r.json().get('chart') or {}).get('result')
            if not result:
                continue
            ts = result[0].get('timestamp') or []
            quote = (result[0].get('indicators') or {}).get('quote', [{}])[0]
            close = quote.get('close') or []
            pairs = [(datetime.date.fromtimestamp(t), c)
                     for t, c in zip(ts, close) if c is not None]
            if len(pairs) < 20:
                continue
            last = pairs[-1][1]
            target = pairs[-1][0] - datetime.timedelta(days=30)
            one_m = None
            for d, c in pairs:
                if d <= target:
                    one_m = c
                else:
                    break
            first = pairs[0][1]
            if one_m and first:
                ret_1m = (last / one_m - 1.0) * 100.0
                ret_1y = (last / first - 1.0) * 100.0
                return ret_1m, ret_1y
        except Exception:  # noqa: BLE001
            continue
    return None


# ------------------------------------------------------------------ cache
def _metrics_cached(ticker):
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT net_margin, net_margin_yoy, return_1m, return_1y, "
            "forward_pe, eps_growth, revenue_growth, fetched_at "
            "FROM company_metrics WHERE ticker=?", (ticker,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        fetched = datetime.datetime.fromisoformat(row[7])
    except ValueError:
        return None
    return {'net_margin': row[0], 'net_margin_yoy': row[1],
            'return_1m': row[2], 'return_1y': row[3],
            'forward_pe': row[4], 'eps_growth': row[5],
            'revenue_growth': row[6], 'fetched_at': fetched}


def _save_metrics(ticker, sector, metrics):
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO company_metrics "
            "(ticker, sector, net_margin, net_margin_yoy, return_1m, "
            "return_1y, forward_pe, eps_growth, revenue_growth, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ticker, sector, metrics['net_margin'], metrics['net_margin_yoy'],
             metrics['return_1m'], metrics['return_1y'],
             metrics['forward_pe'], metrics['eps_growth'],
             metrics.get('revenue_growth'),
             datetime.datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()


def _fresh(m):
    return (datetime.datetime.now() - m['fetched_at']).total_seconds() \
        < TTL_HOURS * 3600


# ------------------------------------------------------------------ inputs
def _sector_result(sector):
    try:
        from sector_quant import load_result
        payload = load_result()
    except Exception:  # noqa: BLE001
        return None
    if not payload:
        return None
    for s in payload.get('sectors', []):
        if s.get('sector') == sector:
            return s
    return None


def _apply_metrics(c, m):
    c = dict(c)
    if m.get('net_margin') is not None:
        c['netMarginPct'] = m['net_margin']
        c['netMarginYoyChangePp'] = m['net_margin_yoy']
        c['return1mPct'] = m['return_1m']
        c['return1yPct'] = m['return_1y']
        c['forwardPE'] = m.get('forward_pe')
        c['forwardEPSGrowth'] = m.get('eps_growth')
        c['revenueGrowthPct'] = m.get('revenue_growth')
    return c


def _apply_benchmark(c, sector_result):
    if sector_result is None:
        return c
    c = dict(c)
    b1m = sector_result.get('mom_1m')
    b1y = sector_result.get('mom_1y')
    if b1m is not None:
        c['benchmarkReturn1mPct'] = b1m
    if b1y is not None:
        c['benchmarkReturn1yPct'] = b1y
    return c


def sector_companies_cached(sector):
    """CompanyQuantInput из кэша (без сети) + benchmark из sector-результата."""
    sr = _sector_result(sector)
    out = []
    for c in company_fixture.companies_for(sector):
        m = _metrics_cached(c['ticker'])
        if m is not None:
            c = _apply_metrics(c, m)
        out.append(_apply_benchmark(c, sr))
    return out


def sector_companies(sector, force=False):
    """CompanyQuantInput, обновляя метрики не чаще раза в день (TTL 24ч).

    Fallback: кэш, затем статический fixture. Фоновая загрузка — сеть/БД.
    """
    sr = _sector_result(sector)
    out = []
    for c in company_fixture.companies_for(sector):
        ticker = c['ticker']
        m = _metrics_cached(ticker)
        if m is not None and (force or _fresh(m)):
            c = _apply_metrics(c, m)
        else:
            try:
                live = fetch_company_metrics(ticker)
                if live:
                    _save_metrics(ticker, sector, live)
                    c = _apply_metrics(c, live)
                elif m is not None:
                    c = _apply_metrics(c, m)
            except Exception as e:  # noqa: BLE001 - keep the fixture fallback
                print('Company metrics {}: {}'.format(ticker, e))
                if m is not None:
                    c = _apply_metrics(c, m)
        out.append(_apply_benchmark(c, sr))
    return out