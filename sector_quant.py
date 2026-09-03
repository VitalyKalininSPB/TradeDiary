# -*- coding: utf-8 -*-
"""Sector Quantitative Assessment — этап 1 (детерминированный, без LLM).

Данные: ежедневные снапшоты секторов GICS со stockanalysis.com (keyless,
страницы `/stocks/sector/{slug}/`, SSR-блок `stats:{...}`). Снапшоты кэшируются
в SQLite `sector_quant.db`; рейтинг считается в приложении (без LLM).

Рейтинг сектора = 0.6·profit + 0.4·momentum, где:
  profit    — агрегированная прибыль сектора (net margin = netIncome/revenue),
              в кросс-секционном относительном виде (доступен сразу);
  momentum  — относительный momentum сектора (vs среднее по секторам) по 1м и 1г.
Когда накопится история снапшотов (30/90 дней), дополнительно считаются
ревизии прибыли (rev_1m/rev_3m) — они сохраняются в результате, но не нужны
для скоринга, поэтому рейтинг осмысленен с первого запуска.
"""
import datetime
import json
import os
import re
import sqlite3

import requests

# GICS-секторы: (slug на stockanalysis.com, отображаемое имя).
SECTORS = [
    ('technology', 'Technology'),
    ('communication-services', 'Communication Services'),
    ('consumer-discretionary', 'Consumer Discretionary'),
    ('consumer-staples', 'Consumer Staples'),
    ('energy', 'Energy'),
    ('financials', 'Financials'),
    ('healthcare', 'Healthcare'),
    ('industrials', 'Industrials'),
    ('materials', 'Materials'),
    ('real-estate', 'Real Estate'),
    ('utilities', 'Utilities'),
]

_URL = 'https://stockanalysis.com/stocks/sector/{slug}/'
_UA = {'User-Agent': 'TradeDiary/1.1 (sector-quant; ti-diary-user@localhost)'}

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DIR, 'sector_quant.db')

TTL_HOURS = 24
WINDOW_1M_DAYS = 30
WINDOW_3M_DAYS = 90
PRUNE_DAYS = 500

# Прозрачные параметры скоринга.
WEIGHT_PROFIT = 0.6
WEIGHT_MOMENTUM = 0.4
W_1M = 0.6
W_1Y = 0.4
SCALE_PROFIT = 10.0
SCALE_MOM_1M = 10.0
SCALE_MOM_1Y = 20.0

TIER_STRONG = 0.4
TIER_WEAK = -0.4


def _conn():
    conn = sqlite3.connect(DB_PATH)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sector_series)")}
    if cols and not {'revenue', 'ch1y'} <= cols:
        conn.execute("DROP TABLE sector_series")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sector_series ("
        "date TEXT NOT NULL, sector TEXT NOT NULL, "
        "net_income REAL NOT NULL, revenue REAL NOT NULL, "
        "ch1m REAL NOT NULL, ch1y REAL NOT NULL, ch_ytd REAL NOT NULL, "
        "PRIMARY KEY (date, sector))")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sector_quant_results ("
        "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL)")
    return conn


# --------------------------------------------------------------------- fetch
def fetch_sector_stats(slug):
    """Fetch `stats:{...}` aggregate for a sector as a dict. Raises on failure."""
    r = requests.get(_URL.format(slug=slug), headers=_UA, timeout=25)
    r.raise_for_status()
    html = r.text
    m = re.search(r'stats:\{(.*?)\},text:', html, re.DOTALL)
    blob = m.group(1) if m else html
    net = _grab(r'netIncome:([0-9.]+)', blob)
    revenue = _grab(r'revenue:([0-9.]+)', blob)
    ch1m = _grab(r'ch1m:(-?[0-9.]+)', blob)
    ch1y = _grab(r'ch1y:(-?[0-9.]+)', blob)
    ch_ytd = _grab(r'chYTD:(-?[0-9.]+)', blob)
    name = _grab(r'sector_name:"([^"]+)"', blob)
    if (net is None or revenue is None or ch1m is None
            or ch1y is None or ch_ytd is None or name is None):
        raise ValueError('нет блока stats на странице {}'.format(slug))
    net, revenue, ch1m, ch1y, ch_ytd = (float(v) for v in
                                         (net, revenue, ch1m, ch1y, ch_ytd))
    if not all(_finite(v) for v in (net, revenue, ch1m, ch1y, ch_ytd)) \
            or net <= 0 or revenue <= 0:
        raise ValueError('битые значения в блоке stats для {}'.format(slug))
    return {'name': name, 'net_income': net, 'revenue': revenue,
            'ch1m': ch1m, 'ch1y': ch1y, 'ch_ytd': ch_ytd}


def _grab(pattern, text):
    m = re.search(pattern, text)
    return m.group(1) if m else None


def _finite(v):
    return v == v and v not in (float('inf'), float('-inf'))


# -------------------------------------------------------------------- cache
def save_snapshot(slug, stats, date):
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sector_series "
            "(date, sector, net_income, revenue, ch1m, ch1y, ch_ytd) "
            "VALUES (?,?,?,?,?,?,?)",
            (date.isoformat(), slug, stats['net_income'], stats['revenue'],
             stats['ch1m'], stats['ch1y'], stats['ch_ytd']))
        conn.commit()
    finally:
        conn.close()


def has_snapshot(slug, date):
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM sector_series WHERE date=? AND sector=?",
            (date.isoformat(), slug)).fetchone()
    finally:
        conn.close()
    return row is not None


def load_series(slug):
    """All cached snapshots for a sector as
    [(date, net_income, revenue, ch1m, ch1y, ch_ytd)]."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT date, net_income, revenue, ch1m, ch1y, ch_ytd "
            "FROM sector_series WHERE sector=? ORDER BY date", (slug,)).fetchall()
    finally:
        conn.close()
    out = []
    for d, ni, rev, ch1m, ch1y, ytd in rows:
        try:
            date = datetime.date.fromisoformat(d)
        except ValueError:
            continue
        out.append((date, ni, rev, ch1m, ch1y, ytd))
    return out


def prune_old(date):
    """Drop snapshots older than PRUNE_DAYS to keep the DB small."""
    conn = _conn()
    try:
        conn.execute(
            "DELETE FROM sector_series WHERE date < ?",
            ((date - datetime.timedelta(days=PRUNE_DAYS)).isoformat(),))
        conn.commit()
    finally:
        conn.close()


def save_result(payload):
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sector_quant_results "
            "(id, payload, fetched_at) VALUES (1,?,?)",
            (json.dumps(payload, ensure_ascii=False),
             datetime.datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()


def load_result():
    """Last saved payload or None."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT payload FROM sector_quant_results WHERE id=1").fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- scoring
def _latest_at(rows, days_ago):
    """Latest value on or before `today - days_ago`, else None.

    `rows` is a sorted list of (date, value).
    """
    target = datetime.date.today() - datetime.timedelta(days=days_ago)
    best = None
    for d, v in rows:
        if d <= target:
            best = v
        else:
            break
    return best


def _pct_change(new_v, old_v):
    if old_v is None or new_v is None or old_v == 0:
        return None
    return (new_v / old_v - 1.0) * 100.0


def _ch_ytd_3m(ch_ytd_now, row_90d):
    """3-month momentum from the cached chYTD series (None on year reset).

    `row_90d` is (date, ch_ytd_value) ~90 days ago or None. chYTD resets at the
    start of each year, so if the historical row falls in a different calendar
    year the series is not comparable and we return None.
    """
    if row_90d is None:
        return None
    old_date, old_v = row_90d
    if old_date.year != datetime.date.today().year or not old_v:
        return None
    return ((1.0 + ch_ytd_now / 100.0) / (1.0 + old_v / 100.0) - 1.0) * 100.0


def _rel(values_by_slug):
    """Cross-sectional relative metric: value minus the sector mean."""
    present = [v for v in values_by_slug.values() if v is not None]
    mean = sum(present) / len(present) if present else 0.0
    return {slug: (v - mean if v is not None else None)
            for slug, v in values_by_slug.items()}


def _blend(s1, s2, w1, w2):
    """Weighted blend of two scores, renormalized when one is missing."""
    parts = []
    if s1 is not None:
        parts.append((w1, s1))
    if s2 is not None:
        parts.append((w2, s2))
    if not parts:
        return None
    used = sum(w for w, _ in parts)
    return sum(w * s for w, s in parts) / used if used else None


def _tier(score):
    if score is None:
        return 'n/a'
    if score >= TIER_STRONG:
        return 'Strong'
    if score >= 0.0:
        return 'Positive'
    if score > TIER_WEAK:
        return 'Weak'
    return 'Negative'


def compute_scores(series_map):
    """Rank sectors from cached snapshot series.

    `series_map` is {slug: (name, [(date, net_income, revenue, ch1m, ch1y,
    ch_ytd)])}. Returns a list of result dicts, sorted by score desc.

    The score is meaningful from the first run (no history needed):
      profit    = tanh(rel net margin),  net margin = netIncome/revenue,
                  cross-sectionally relative;
      momentum  = 0.6·tanh(rel ch1m) + 0.4·tanh(rel ch1y), relative to sectors.
    Once enough daily snapshots accumulate, net-income revisions (rev_1m/rev_3m)
    and chYTD-based 3m momentum are computed too and kept in the result.
    """
    import math
    rows_by_slug = {}
    margin_by_slug = {}
    mom_1m_by_slug = {}
    mom_1y_by_slug = {}
    for slug, (name, rows) in series_map.items():
        if not rows:
            continue
        _d, ni, revenue, ch1m, ch1y, ytd = rows[-1]
        margin = (ni / revenue * 100.0) if revenue else None
        ni_1m = _latest_at([(d, v) for d, v, _r, _c, _y, _t in rows],
                           WINDOW_1M_DAYS)
        ni_3m = _latest_at([(d, v) for d, v, _r, _c, _y, _t in rows],
                           WINDOW_3M_DAYS)
        ytd_row = _latest_row([(d, v) for d, _n, _r, _c, _y, v in rows],
                              WINDOW_3M_DAYS)
        rev_1m = _pct_change(ni, ni_1m)
        rev_3m = _pct_change(ni, ni_3m)
        mom_3m = _ch_ytd_3m(ytd, ytd_row)
        rows_by_slug[slug] = (name, ni, revenue, margin, ch1m, ch1y,
                              rev_1m, rev_3m, mom_3m)
        margin_by_slug[slug] = margin
        mom_1m_by_slug[slug] = ch1m
        mom_1y_by_slug[slug] = ch1y

    rel_margin = _rel(margin_by_slug)
    rel_mom_1m = _rel(mom_1m_by_slug)
    rel_mom_1y = _rel(mom_1y_by_slug)

    results = []
    for slug, (name, ni, revenue, margin, ch1m, ch1y, rev_1m, rev_3m,
               mom_3m) in rows_by_slug.items():
        profit = None
        if rel_margin[slug] is not None:
            profit = math.tanh(rel_margin[slug] / SCALE_PROFIT)
        momentum = _blend(
            math.tanh(rel_mom_1m[slug] / SCALE_MOM_1M)
            if rel_mom_1m[slug] is not None else None,
            math.tanh(rel_mom_1y[slug] / SCALE_MOM_1Y)
            if rel_mom_1y[slug] is not None else None,
            W_1M, W_1Y)
        if profit is not None and momentum is not None:
            score = WEIGHT_PROFIT * profit + WEIGHT_MOMENTUM * momentum
        else:
            score = None
        results.append({
            'slug': slug, 'sector': name, 'net_income': ni,
            'revenue': revenue, 'net_margin': margin,
            'rev_1m': rev_1m, 'rev_3m': rev_3m,
            'mom_1m': ch1m, 'mom_1y': ch1y, 'mom_3m': mom_3m,
            'rel_mom_1m': rel_mom_1m[slug], 'rel_mom_1y': rel_mom_1y[slug],
            'profit': profit, 'momentum': momentum,
            'score': score, 'rank': None, 'tier': _tier(score),
        })

    results.sort(key=lambda r: (r['score'] is not None, r['score']),
                 reverse=True)
    scored = [r for r in results if r['score'] is not None]
    for i, r in enumerate(scored, start=1):
        r['rank'] = i
    return results


def _latest_row(rows, days_ago):
    """(date, value) on or before today-days_ago, else None."""
    target = datetime.date.today() - datetime.timedelta(days=days_ago)
    best = None
    for d, v in rows:
        if d <= target:
            best = (d, v)
        else:
            break
    return best


# ------------------------------------------------------------------ run
def run_sector_quant(force=False):
    """Fetch sector snapshots, refresh cache, compute and save the result.

    Runs on a background thread (network + DB). Returns a serializable payload:
    {computed_at, data_date, source, params, errors, sectors}.
    """
    today = datetime.date.today()
    fetched = {}
    errors = []
    for slug, name in SECTORS:
        try:
            if not force and has_snapshot(slug, today):
                continue
            stats = fetch_sector_stats(slug)
            save_snapshot(slug, stats, today)
            fetched[slug] = (name, stats)
        except Exception as e:  # noqa: BLE001 - one bad sector must not kill all
            errors.append('{}: {}'.format(name, e))

    series_map = {}
    for slug, name in SECTORS:
        rows = load_series(slug)
        if rows:
            series_map[slug] = (name, rows)

    if not series_map:
        raise RuntimeError('Нет данных по секторам.\n' + '\n'.join(errors))

    prune_old(today)
    sectors = compute_scores(series_map)
    payload = {
        'computed_at': datetime.datetime.now().isoformat(),
        'data_date': today.isoformat(),
        'source': 'stockanalysis.com',
        'params': {
            'weight_profit': WEIGHT_PROFIT,
            'weight_momentum': WEIGHT_MOMENTUM,
            'w_1m': W_1M, 'w_1y': W_1Y,
            'scale_profit': SCALE_PROFIT,
            'scale_mom_1m': SCALE_MOM_1M, 'scale_mom_1y': SCALE_MOM_1Y,
            'tier_strong': TIER_STRONG, 'tier_weak': TIER_WEAK,
            'window_1m_days': WINDOW_1M_DAYS, 'window_3m_days': WINDOW_3M_DAYS,
        },
        'errors': errors,
        'sectors': sectors,
    }
    save_result(payload)
    return payload