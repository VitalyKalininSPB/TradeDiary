# -*- coding: utf-8 -*-
"""Macroeconomic dashboard for the US market.

Shows the most important US macro indicators (from FRED, no API key required)
each on its own tab. FRED series are cached in an SQLite DB so reopening the
dialog or hitting Reload does not re-download everything every time; a cached
series is re-fetched only after CACHE_TTL.
"""
import datetime
import json
import os
import sqlite3
import bisect
import csv
import math

import numpy as np
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter

import requests

from pivots import pivot_indices
from yield_curve import YIELD_CURVE_SERIES, _YieldCurveTab, compute_ntfs_series
from credit_spread import CreditSpreadTab
from vix_tab import VixTab
from mlrci import MlrcTab, compute_mlrci, compute_net_liquidity
import nfib

from matplotlib.collections import PolyCollection

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QWidget, QLabel, QComboBox, QApplication,
                               QMessageBox, QScrollBar, QCheckBox,
                               QPushButton, QFileDialog)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap

_BG = '#1e1f24'
_TXT = '#dcdce0'
_GRID = '#43464f'

# FRED series: (id, tab title, plot label, y-label, color, ru description).
INDICATORS = [
    ('GDPC1',    'Real GDP (GDPC1)',       'Real GDP',
                 'US$ bn (chained 2017)',  '#90caf9',
                 'Рост экономики страны, выпуск товаров и услуг'),
    ('CPIAUCSL', 'Inflation / CPI (CPIAUCSL)', 'Headline CPI index',
                 'Index (1982-1984 = 100)', '#ffd54f',
                 'Инфляция — скорость роста потребительских цен'),
    ('UNRATE',   'Unemployment (UNRATE)',  'Unemployment rate',
                 'Percent',                '#80a9ff',
                 'Доля безработных в рабочей силе'),
    ('FEDFUNDS', 'Fed Funds Rate (FEDFUNDS)', 'Federal funds effective rate',
                 'Percent',                '#ef9a9a',
                 'Ключевая ставка ФРС, стоимость денег'),
    ('PAYEMS',   'Non-Farm Payrolls (PAYEMS)', 'Total non-farm employment',
                 'Thousands of persons',   '#a5d6a7',
                 'Число рабочих мест вне сельского хозяйства'),
    ('UMCSENT',  'Michigan Consumer Sentiment (UMCSENT)',
                 'Michigan consumer sentiment index',
                 'Index (1966Q1 = 100)',   '#ce93d8',
                 'Уверенность американских потребителей в экономике'),
    ('CP',       'Corporate Profits (CP)', 'Corporate Profits After Tax',
                 'US$ bn',                 '#fff59d',
                 'Разворот корпоративных прибылей в отчёте ВВП (BEA) происходит '
                 'за 2–3 квартала до того, как прибыль на акцию (EPS) компаний '
                 'S&P 500 начнёт падать. Если ВВП показывает стагнацию прибылей '
                 'в экономике — это сигнал к будущей распродаже на рынке акций.'),
    ('PERMIT',   'Building Permits (PERMIT)', 'Building Permits',
                 'Thousands of Units',  '#80cbc4',
                 'Разрешения на строительство жилья (Census Bureau) — опережающий '
                 'индикатор жилищного сектора и состояния экономики'),
]

# Buffett indicator = market value of US corporate equities / nominal GDP.
# Wilshire index data was removed from FRED in 2024, so the numerator is the
# Fed's own "Market Value of Equities Outstanding" (NCBEILQ027S, $ millions)
# from the Integrated Macroeconomic Accounts; GDP is the quarterly nominal
# series ($ billions). Ratio -> percent: millions / (billions*1000) * 100.
_BUFFETT_ID = 'BUFFETT'
_BUFFETT_CAP_ID = 'NCBEILQ027S'
_BUFFETT_GDP_ID = 'GDP'

# ISM Manufacturing/Services PMI: FRED removed the series (manufacturing data
# ends 2016), the DBnomics mirror stopped updating and ism_web closes to
# automated access (403). Data is loaded manually from a CSV exported via an AI
# assistant (see _build_ism_prompt -> _*_PROMPT; cached with no TTL in _load_ism).
_ISM_ID = 'ISM_PMI'
_ISM_NAME = 'ISM Manufacturing PMI'
_ISM_SERVICES_ID = 'ISM_SERVICES'
_ISM_SERVICES_NAME = 'ISM Services PMI'


def _build_ism_prompt(name, context, period='2000-01-01'):
    """Prompt that asks an assistant to dump the full ISM PMI series as CSV.

    The assistant cannot write files, so it emits a date,value CSV block that the
    user saves to disk and imports through the tab's Load button.
    """
    return (
        'Ты — эксперт по индексу деловой активности {ctx} '
        '({name}; >50 = расширение, <50 = сокращение).\n\n'
        'Задача: выгрузить ПОЛНЫЙ исторический ряд {name} одним CSV-блоком. '
        'Никаких пояснений, вступлений или «...».\n\n'
        'Формат — одна строка на месяц, разделитель запятая:\n'
        'date,value\n'
        '{period},49.3\n'
        '2000-02-01,50.9\n\n'
        'Требования:\n'
        '1. date — ISO YYYY-MM-DD, первый день месяца.\n'
        '2. value — индекс, одно десятичное через точку (или NA, если значение '
        'не подтверждено).\n'
        '3. Период: с {period} по последний опубликованный месяц; без пропусков.\n'
        '4. Источник — официальный сезонно скорректированный {name}; сверь по '
        'нескольким источникам (Reuters / пресс-релизы ISM).\n'
        '5. Если ответ не помещается целиком — продолжай в следующем сообщении с '
        'точного места обрыва, не повторяя уже выданные строки.\n'
        '6. Не выдумывай значения: неподтверждённое → NA (строку с датой всё '
        'равно оставь).\n\n'
        'Верни ТОЛЬКО CSV-блок.'
    ).format(name=name, ctx=context, period=period)


_ISM_PROMPT = _build_ism_prompt(_ISM_NAME, 'в обрабатывающей промышленности США')
_ISM_SERVICES_PROMPT = _build_ism_prompt(_ISM_SERVICES_NAME, 'в сфере услуг США')

_NFIB_ID = 'NFIB_COMPOSITE'
_NFIB_NAME = 'NFIB Composite (leading indicators)'
_NFIB_START_YEAR = 1986  # NFIB SBET data available from 1986 on the API

# Series that have no machine source and are imported manually (Load button).
_MANUAL_IDS = (_ISM_ID, _ISM_SERVICES_ID)

# Cleveland Fed ex-ante (expected) real interest rate, 10-year horizon. A
# model-based real rate (nominal yields minus model-implied expected inflation,
# excluding commodity-price noise and short-term trader panic), published on
# FRED as a plain series. Its turning points are the Buy/Sell S&P signal tab.
_REAL_RATE_ID = 'REAINTRATREARAT10Y'

_PERIODS = [('1Y', 365), ('5Y', 5 * 365), ('10Y', 10 * 365), ('Max', None)]

# Data-unit -> scrollbar-integer scaling (QScrollBar is int-only).
_SCROLL_SCALE = 100

# How long a cached FRED series is considered fresh (FRED datasets update
# monthly/quarterly, so a daily TTL is more than enough).
CACHE_TTL_HOURS = 24 * 1

_CACHE_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DB = os.path.join(_CACHE_DIR, 'macro_cache.db')


def _conn():
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS macro_series ("
        "series_id TEXT PRIMARY KEY, data TEXT NOT NULL, fetched_at TEXT NOT NULL)")
    return conn


def _load_cached(series_id):
    """Return (dates, values) if a fresh-enough cache entry exists, else None."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT data, fetched_at FROM macro_series WHERE series_id=?",
            (series_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    data_json, fetched_at = row
    try:
        fetched = datetime.datetime.fromisoformat(fetched_at)
    except ValueError:
        return None
    age = datetime.datetime.now() - fetched
    if age.total_seconds() > CACHE_TTL_HOURS * 3600:
        return None
    try:
        data = json.loads(data_json)
        dates = [datetime.date.fromisoformat(d) for d in data['dates']]
        values = data['values']
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return dates, values


def _load_any_cached(series_id):
    """Return (dates, values) from the cache regardless of freshness, else None."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT data FROM macro_series WHERE series_id=?",
            (series_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        data = json.loads(row[0])
        dates = [datetime.date.fromisoformat(d) for d in data['dates']]
        values = data['values']
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return dates, values


def _save_cached(series_id, dates, values):
    payload = json.dumps({'dates': [d.isoformat() for d in dates],
                          'values': values})
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO macro_series (series_id, data, fetched_at) "
            "VALUES (?,?,?)",
            (series_id, payload, datetime.datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()


def _fred(series_id):
    """Load a FRED series as (dates, values), using the SQLite cache first.

    Fresh cache is returned instantly; stale-or-missing series are re-fetched
    from FRED and the cache is refreshed. Raises on network failure.
    """
    cached = _load_cached(series_id)
    if cached is not None:
        return cached

    dates, values = _fetch_fred(series_id)
    try:
        _save_cached(series_id, dates, values)
    except Exception as e:  # noqa: BLE001 - cache write must not fail the fetch
        print('Failed to cache {}: {}'.format(series_id, e))
    return dates, values


def _load_ism(series_id):
    """Load a manually-imported ISM PMI series from the cache (no TTL).

    There is no machine source to re-fetch from, so a cached row is always
    served (not expired by CACHE_TTL). Returns ([], []) when nothing was
    imported yet.
    """
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT data FROM macro_series WHERE series_id=?", (series_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return [], []
    try:
        data = json.loads(row[0])
        dates = [datetime.date.fromisoformat(d) for d in data['dates']]
        values = data['values']
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return [], []
    return dates, values


def _load_nfib(series_id):
    """Load the NFIB leading composite as (dates, values), cached with TTL.

    Fresh cache is returned instantly; stale-or-missing data is re-fetched from
    the official NFIB SBET API (see nfib.fetch_components), composited and
    cached. On network failure a stale cache entry is served as a fallback so
    the tab keeps the last good data.
    """
    cached = _load_cached(series_id)
    if cached is not None:
        return cached
    today = datetime.date.today()
    start = datetime.date(_NFIB_START_YEAR, 1, 1)
    try:
        dates, cols = nfib.fetch_components(
            start.year, start.month, today.year, today.month)
        values = nfib.compute_composite(cols)
        if dates and values:
            _save_cached(series_id, dates, values)
            return dates, values
    except Exception as e:  # noqa: BLE001 - network failure fallback
        print('Failed to fetch NFIB composite: {}'.format(e))
    stale = _load_any_cached(series_id)
    if stale is not None:
        return stale
    return [], []


def _parse_ism_csv(path):
    """Parse a `date,value` CSV (as exported by the ISM prompt) into a series.

    Rows are sorted by date ascending; missing/non-numeric values (NA, nan)
    become NaN so the chart shows a gap instead of a bogus point.
    """
    dates, values = [], []
    with open(path, newline='', encoding='utf-8-sig') as f:
        for raw in csv.reader(f):
            if not raw or len(raw) < 2:
                continue
            d_raw = raw[0].strip()
            try:
                d = datetime.date.fromisoformat(d_raw)
            except ValueError:
                continue  # header row or unparseable date
            v_raw = raw[1].strip().replace(',', '').replace('%', '')
            try:
                v = float(v_raw)
            except ValueError:
                v = float('nan')
            dates.append(d)
            values.append(v)
    if dates:
        order = sorted(range(len(dates)), key=lambda i: dates[i])
        dates = [dates[i] for i in order]
        values = [values[i] for i in order]
    return dates, values


def _load_ntfs(series_id):
    """NTFS (Engstrom-Sharpe near-term forward spread) series for the yield tab.

    Computed from the cached FRED yields (DTB3, DGS6MO, DGS1, DGS2), so it
    belongs on the background loader thread, never the UI thread.
    """
    series = {sid: _fred(sid) for sid in ('DTB3', 'DGS6MO', 'DGS1', 'DGS2')}
    return compute_ntfs_series(series)


def _load_mlrci(series_id):
    """MLRCI composite series: fetches all components from cache and computes."""
    from mlrci import (_REAL_ID, _WALCL_ID, _TGA_ID, _RRP_ID,
                       _BBB_ID, _VIX_ID, _NTFS_SHORT)
    series = {}
    for sid in set([_REAL_ID, _WALCL_ID, _TGA_ID, _RRP_ID, _BBB_ID, _VIX_ID]
                   + list(_NTFS_SHORT)):
        series[sid] = _fred(sid)
    return compute_mlrci(series)


def _load_mlrci_marks(series_id):
    """STRONG BUY/SELL marker points for the MLRCI chart.

    Returns (dates, values) where values encode +1 for STRONG BUY and -1 for
    STRONG SELL at the dates the signal turns on. Runs in the background thread.
    """
    from mlrci import (_REAL_ID, _WALCL_ID, _TGA_ID, _RRP_ID,
                       _BBB_ID, _VIX_ID, _NTFS_SHORT, compute_mlrci_full)
    series = {}
    for sid in set([_REAL_ID, _WALCL_ID, _TGA_ID, _RRP_ID, _BBB_ID, _VIX_ID]
                   + list(_NTFS_SHORT)):
        series[sid] = _fred(sid)
    _dates, _values, buy, sell = compute_mlrci_full(series)
    dates = [d for d, _v in buy] + [d for d, _v in sell]
    values = [1] * len(buy) + [-1] * len(sell)
    pairs = sorted(zip(dates, values))
    if pairs:
        return [d for d, _v in pairs], [v for _d, v in pairs]
    return [], []


def _load_buffett(series_id=None):
    """Buffett indicator as (dates, values) in percent, cached like FRED series.

    `series_id` is accepted for uniformity with _fred (ignored here).

    Ratio = market value of US equities (NCBEILQ027S, $m) / nominal GDP ($b),
    sampled at each market-cap observation date using the latest GDP on or
    before it. Fresh cache returned instantly; stale/missing recomputed.
    """
    cached = _load_cached(_BUFFETT_ID)
    if cached is not None:
        return cached

    cap_dates, cap_vals = _fetch_fred(_BUFFETT_CAP_ID)
    gdp_dates, gdp_vals = _fetch_fred(_BUFFETT_GDP_ID)
    dates, values, gdp_idx = [], [], 0
    for d, c in zip(cap_dates, cap_vals):
        while gdp_idx + 1 < len(gdp_dates) and gdp_dates[gdp_idx + 1] <= d:
            gdp_idx += 1
        if gdp_dates[gdp_idx] > d or not gdp_vals[gdp_idx]:
            continue
        dates.append(d)
        values.append(c / gdp_vals[gdp_idx] / 10.0)
    try:
        _save_cached(_BUFFETT_ID, dates, values)
    except Exception as e:  # noqa: BLE001 - cache write must not fail the fetch
        print('Failed to cache {}: {}'.format(_BUFFETT_ID, e))
    return dates, values


def buffett_hint(ratio):
    """Red warning text for the Buffett indicator, or '' when fairly valued.

    ratio is the latest cap/GDP in percent. Returns (text, is_warning).
    """
    if ratio is None:
        return '', False
    if ratio >= 170:
        return ('⚠️ Рынок перегрет ({:.0f}%) — акции сильно дороже экономики, '
                'высокий риск коррекции.'.format(ratio)), True
    if ratio >= 130:
        return ('⚠️ Рынок перегрет ({:.0f}%) — акции дороги относительно '
                'экономики.'.format(ratio)), True
    if ratio >= 110:
        return ('Рынок слегка переоценён ({:.0f}%).'.format(ratio)), False
    if ratio >= 90:
        return ('Рынок справедливо оценён ({:.0f}%).'.format(ratio)), False
    if ratio >= 75:
        return ('⚠️ Рынок близок к недооценке ({:.0f}%).'.format(ratio)), True
    return ('⚠️ Рынок недооценен ({:.0f}%) — акции дёшевы относительно '
            'экономики.'.format(ratio)), True


def _fetch_fred(series_id):
    """Fetch a FRED series as (dates, values). Dies loudly on failure."""
    url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id={}'.format(series_id)
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    lines = r.text.splitlines()
    if not lines or len(lines) < 2:
        raise ValueError('Empty response for series {}'.format(series_id))

    dates, values = [], []
    for raw in lines[1:]:
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split(',')
        if len(parts) < 2:
            break  # trailing remark line ("Copyright" etc.)
        d, v = parts[0].strip(), parts[1].strip()
        if not d or v == '' or v == '.':
            continue
        try:
            dates.append(datetime.datetime.strptime(d, '%Y-%m-%d').date())
            values.append(float(v))
        except ValueError:
            continue
    if not dates:
        raise ValueError('No parseable rows for series {}'.format(series_id))
    return dates, values


# ---------------------------------------------------------------------------
# Macro thermometer scoring.
#
# The bar (range -10..+10) is derived from the cached FRED indices instead of
# a random number. Sign convention: positive = pro-risk ("risk-on"), negative =
# risk-off. Because the FRED data is monthly/quarterly (never daily) and the
# deals are held ~20-60 days, each indicator mixes two components:
#   * momentum  - change over the last ~3 months (fits the holding window),
#   * level     - where the indicator currently sits (plus YoY trend).
# Each component is normalised to [-1, +1] via tanh and the weighted sum is
# mapped onto [-10, +10].
# ---------------------------------------------------------------------------

# Lookback for the short-horizon momentum (approx the 20-60 day hold window).
_MOMENTUM_DAYS = 90
_YOY_DAYS = 365

# (FRED id, weight, level fn, momentum fn) where each fn(value, value_y, value_m)
# -> sub-score in [-1, 1]; value_y/value_m are the values ~1y / ~3m ago (None if
# unavailable). FN_NONE is used as a drop-in ignored feature.
FN_NONE = lambda *_: 0.0


def _gdp_score(v, vy, vm):
    """Real GDP: growth good, recession bad, ~2% neutral (YoY growth %)."""
    if vy:
        return math.tanh((v / vy - 1.0) * 100.0 - 2.0) / 3.0
    return FN_NONE(v, vy, vm)


def _cpi_score(v, vy, vm):
    """Core CPIAUCSL: ~2% inflation neutral, accelerating / deflation bad."""
    if vy:
        yoy = (v / vy - 1.0) * 100.0
        return -math.tanh((yoy - 2.0) / 2.5)
    return FN_NONE(v, vy, vm)


def _unrate_score(v, vy, vm):
    """Unemployment: low level + falling = good, high / rising = bad."""
    level = math.tanh((5.0 - v) / 2.0)
    mom = -math.tanh((v - vm) / 1.5) if (vm and v != vm) else 0.0
    return 0.55 * level + 0.45 * mom


def _fedfunds_score(v, vy, vm):
    """Fed funds: low level + cuts = accommodative, high / hiking = tight."""
    level = math.tanh((2.5 - v) / 3.0)
    mom = -math.tanh((v - vm) / 2.0) if (vm and v != vm) else 0.0
    return 0.6 * level + 0.4 * mom


def _payems_score(v, vy, vm):
    """Non-farm payrolls: steady employment growth supports real economy."""
    if vy:
        yoy = (v / vy - 1.0) * 100.0
        mom = math.tanh((v - vm) / 1000.0) if vm else 0.0
        return 0.7 * math.tanh((yoy - 1.0) / 1.5) + 0.3 * mom
    return FN_NONE(v, vy, vm)


def _umcsent_score(v, vy, vm):
    """Michigan consumer sentiment: high / improving confidence is a tailwind."""
    level = math.tanh((v - 75.0) / 20.0)
    mom = math.tanh((v - vm) / 10.0) if vm else 0.0
    return 0.6 * level + 0.4 * mom


# Each entry: (series_id, weight, score fn). Weights sum to 1 (0..1).
_SCORERS = [
    ('GDPC1',    0.25, _gdp_score),
    ('CPIAUCSL', 0.22, _cpi_score),
    ('UNRATE',   0.18, _unrate_score),
    ('FEDFUNDS', 0.20, _fedfunds_score),
    ('PAYEMS',   0.08, _payems_score),
    ('UMCSENT',  0.07, _umcsent_score),
]


def _at_days_ago(dates, values, days_ago):
    """Value as of ~`days_ago` calendar days, or None if out of range."""
    target = datetime.date.today() - datetime.timedelta(days=days_ago)
    i = bisect.bisect_right(dates, target) - 1
    return values[i] if 0 <= i < len(values) else None


# Market-cycle phases (in the real-economy sense, driven by real GDP): each is a
# (ru name, en name) pair shown in the GDP tab's phase label.
_PHASE_EARLY = ('Ранний рост', 'Early Growth')
_PHASE_MATURE = ('Спелость', 'Maturity')
_PHASE_DECLINE = ('Закат', 'Decline')
_PHASE_RECESSION = ('Рецессия', 'Recession')


def _gdp_phase(dates, values):
    """Classify the market cycle phase from real GDP YoY growth + acceleration.

    Returns a (ru, en) name pair, or None when there is not enough data. Uses the
    YoY growth rate g and its acceleration (change in YoY over the last ~3m):

      * g <= 0             -> Recession (real GDP contracting YoY),
      * g < ~trend, acc>0  -> Early Growth (recovering from a trough, below trend),
      * g > ~trend, acc<0  -> Decline (still positive but decelerating / cooling),
      * otherwise          -> Maturity (solid growth around the trend).
    """
    if not dates or len(values) < 2:
        return None
    v = values[-1]
    vy = _at_days_ago(dates, values, _YOY_DAYS)
    vp = _at_days_ago(dates, values, _MOMENTUM_DAYS)
    vyp = _at_days_ago(dates, values, _YOY_DAYS + _MOMENTUM_DAYS)
    if not all((vy, vp, vyp)) or 0 in (vy, vp, vyp):
        return None
    g = (v / vy - 1.0) * 100.0
    gp = (vp / vyp - 1.0) * 100.0
    accel = g - gp

    if g <= 0.0:
        return _PHASE_RECESSION
    if g < 2.0 and accel > 0.0:
        return _PHASE_EARLY
    if g > 2.5 and accel < 0.0:
        return _PHASE_DECLINE
    return _PHASE_MATURE


# ---------------------------------------------------------------------------
# Late-cycle detection: Gross Private Domestic Investment (GPDI) starts falling
# while consumer credit (CCSA) still holds -> late cycle, a sign the S&P 500 may
# be close to a top. Used by the GDP tab label and the advice goat.
# ---------------------------------------------------------------------------
_LATE_GDPI = 'GPDI'   # Real Gross Private Domestic Investment (chained bn$)
_LATE_CC = 'CCSA'     # Real Consumer Credit Outstanding (chained bn$)


def _late_cycle(values_gdpi, dates_gdpi, values_cc, dates_cc):
    """True when GPDI is falling over the last ~3m while consumer credit holds."""
    if not values_gdpi or not values_cc:
        return False
    g_mom = _at_days_ago(dates_gdpi, values_gdpi, _MOMENTUM_DAYS)
    c_mom = _at_days_ago(dates_cc, values_cc, _MOMENTUM_DAYS)
    if g_mom is None or c_mom is None:
        return False
    return values_gdpi[-1] < g_mom and values_cc[-1] >= c_mom


def late_cycle_signal():
    """Fetch GPDI + consumer credit (cached) and classify the cycle stage.

    Returns (is_late, message). Runs network/cache access, so call it only from
    a background thread (never the UI thread).
    """
    try:
        dg, vg = _fred(_LATE_GDPI)
        dc, vc = _fred(_LATE_CC)
    except Exception as e:  # noqa: BLE001 - a failing fetch must not kill the load
        return False, 'нет данных по компонентам ВВП'
    if _late_cycle(vg, dg, vc, dc):
        return True, ('Инвестиции (GPDI) падают, потребкредит (CCSA) держится — '
                      'поздний цикл')
    return False, ''


def compute_macro_score():
    """Compute the macro thermometer value in [-10, 10] from cached FRED data.

    Returns (score_int, note). score_int is None when no indicator could be
    scored (e.g. cold cache and no network); note carries a human summary and
    the list of indicators included.
    """
    sub_scores, notes = [], []
    for series_id, weight, fn in _SCORERS:
        try:
            dates, values = _fred(series_id)
            v = values[-1]
            vm = _at_days_ago(dates, values, _MOMENTUM_DAYS)
            vy = _at_days_ago(dates, values, _YOY_DAYS)
            s = fn(v, vy, vm)
        except Exception as e:  # noqa: BLE001 - a failing series must not kill the score
            print('Macro score: series {} unavailable ({}).'.format(series_id, e))
            continue
        if math.isnan(s):
            continue
        sub_scores.append((weight, s))
        notes.append(series_id)

    if not sub_scores:
        return None, 'Нет данных — нейтрально.'

    total = sum(w * s for w, s in sub_scores)
    used = sum(w for w, _ in sub_scores)
    avg = total / used if used else 0.0
    avg = max(-1.0, min(1.0, avg))
    score = int(round(avg * 10.0))
    score = max(-10, min(10, score))
    return score, 'по {}: {}'.format(', '.join(notes), avg)


# ---------------------------------------------------------------------------
# Cached macro thermometer result.
#
# Instead of a fragile per-indicator release-day calendar, the score result is
# cached for _SCORE_TTL_HOURS. FRED data is monthly/quarterly, so a ~24h TTL
# refreshes roughly daily and naturally retries the next day — no need to hardcode
# publication dates (which shift for holidays, revisions, weekday rules).
# ---------------------------------------------------------------------------
_SCORE_TTL_HOURS = 24


def _score_conn():
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS macro_score_cache ("
        "id INTEGER PRIMARY KEY, score INTEGER NOT NULL, "
        "note TEXT NOT NULL, fetched_at TEXT NOT NULL)")
    return conn


def _load_score_cached():
    """Return a fresh cached (score, note), or None when stale/missing."""
    conn = _score_conn()
    try:
        row = conn.execute(
            "SELECT score, note, fetched_at FROM macro_score_cache WHERE id=1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    score, note, fetched_at = row
    try:
        age = datetime.datetime.now() - datetime.datetime.fromisoformat(fetched_at)
    except ValueError:
        return None
    if age.total_seconds() > _SCORE_TTL_HOURS * 3600:
        return None
    return score, note


def _save_score_cached(score, note):
    conn = _score_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO macro_score_cache "
            "(id, score, note, fetched_at) VALUES (1,?,?,?)",
            (score, note, datetime.datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()


def compute_macro_score_cached():
    """The thermometer (score, note), from cache; recomputed when stale.

    On load this is a single DB read (fast, no network). The underlying FRED
    series are themselves cached for 24h, so a recompute refetches only stale
    series and happens at most ~once a day.
    """
    cached = _load_score_cached()
    if cached is not None:
        return cached
    score, note = compute_macro_score()
    if score is not None:
        try:
            _save_score_cached(score, note)
        except Exception:  # noqa: BLE001 - cache write must not fail the score
            pass
    return score, note


class _IndicatorTab(QWidget):
    """One tab: a matplotlib chart of a single FRED indicator."""

    def __init__(self, series_id, plot_label, ylabel, color, description='',
                 parent=None, show_regime=False, show_phase=False,
                 show_late_cycle=False, show_pivots=False,
                 pivot_kwargs=None, explain='', show_load_button=False):
        super().__init__(parent)
        self.series_id = series_id
        self.plot_label = plot_label
        self.ylabel = ylabel
        self.color = color
        self._show_regime = show_regime
        self._show_phase = show_phase
        self._show_late_cycle = show_late_cycle
        self._show_pivots = show_pivots
        self._pivot_kwargs = pivot_kwargs or {}
        self._explain = explain
        self.regimeLabel = None
        self.phaseLabel = None
        self.lateCycleLabel = None
        self._regime_fn = None   # (values) -> 'bull'/'bear'/None (plugged by caller)
        self._regime_icon = None  # (name) -> QPixmap or None
        self._phase_fn = None    # (dates, values) -> (ru, en) or None
        self._on_manual_load = None   # () -> None, plugged by caller for the Load button
        self._on_show_prompt = None   # () -> None, plugged by the Prompt button
        self._hline = None   # y-value for a horizontal reference line (e.g. 50 for PMI)
        self._hlines = None  # list of y-values for several reference lines
        self._zones = None   # list of (lo, hi, color) horizontal bands

        self._dates = []
        self._values = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel(series_id))
        if show_regime:
            self.regimeLabel = QLabel('')
            self.regimeLabel.setStyleSheet('color: {}; font-weight: bold;'.format(_TXT))
            bar.addWidget(self.regimeLabel)
        self.noteLabel = QLabel('')
        self.noteLabel.setStyleSheet('color: {};'.format(_TXT))
        bar.addWidget(self.noteLabel, 1)
        self.pivotCheck = QCheckBox('Точки перегиба')
        self.pivotCheck.setChecked(show_pivots)
        self.pivotCheck.setToolTip(
            'Красный = SELL S&P (реальная ставка начала расти), '
            'зелёный = BUY S&P (реальная ставка начала падать)')
        self.pivotCheck.toggled.connect(self._on_pivot_toggled)
        bar.addWidget(self.pivotCheck)
        self._pivot_artists = []
        bar.addWidget(QLabel('Period:'))
        self.periodCombo = QComboBox()
        for name, _days in _PERIODS:
            self.periodCombo.addItem(name)
        self.periodCombo.setCurrentIndex(3)
        self.periodCombo.currentIndexChanged.connect(
            lambda _i: self._redraw())
        bar.addWidget(self.periodCombo)
        if show_load_button:
            self.loadButton = QPushButton('Load')
            self.loadButton.setToolTip(
                'Загрузить данные из CSV, выгруженного ассистентом '
                '(кнопка «Промт»).')
            self.loadButton.clicked.connect(self._on_load_button)
            bar.addWidget(self.loadButton)
            self.promptButton = QPushButton('Промт')
            self.promptButton.setToolTip(
                'Скопировать в буфер обмена промт для выгрузки данных.')
            self.promptButton.clicked.connect(self._on_prompt_button)
            bar.addWidget(self.promptButton)
        root.addLayout(bar)

        if description:
            self.descLabel = QLabel(description)
            self.descLabel.setWordWrap(True)
            self.descLabel.setStyleSheet('color: #6a6d78; font-size: 11px;')
            root.addWidget(self.descLabel)

        self.fig = Figure(figsize=(9, 5), dpi=100)
        self.fig.patch.set_facecolor(_BG)
        self.canvas = FigureCanvas(self.fig)
        root.addWidget(self.canvas)

        self.scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.scroll.setToolTip('Горизонтальный скролл / панорамирование по датам')
        root.addWidget(self.scroll)
        self.scroll.valueChanged.connect(self._on_scrollbar)

        self.hintLabel = QLabel('')
        self.hintLabel.setWordWrap(True)
        self.hintLabel.hide()
        root.addWidget(self.hintLabel)

        if show_phase:
            self.phaseLabel = QLabel('')
            self.phaseLabel.setStyleSheet('color: #ffd54f; font-weight: bold;')
            root.addWidget(self.phaseLabel)

        if show_late_cycle:
            self.lateCycleLabel = QLabel('')
            self.lateCycleLabel.setWordWrap(True)
            self.lateCycleLabel.setStyleSheet('color: #ef9a9a; font-weight: bold;')
            root.addWidget(self.lateCycleLabel)

        if explain:
            self.explainLabel = QLabel(explain)
            self.explainLabel.setWordWrap(True)
            self.explainLabel.setStyleSheet(
                'color: #6a6d78; font-size: 11px; padding-top: 4px;')
            root.addWidget(self.explainLabel)

        # Selection state: interval in date-number coords + the highlight band.
        self._sel_a = None
        self._sel_b = None
        self._dragging = False
        self._band = None
        self._data_x0 = None
        self._data_x1 = None
        self._view_span = None
        self._syncing_scroll = False
        for ev, fn in (('scroll_event', self._on_scroll),
                       ('button_press_event', self._on_press),
                       ('motion_notify_event', self._on_motion),
                       ('button_release_event', self._on_release),
                       ('button_press_event', self._on_double)):
            self.canvas.mpl_connect(ev, fn)

    def set_data(self, dates, values, note=''):
        self._dates = dates
        self._values = values
        self.noteLabel.setText(note)
        self._redraw()

    def set_hint(self, text, color=_TXT):
        """Show a per-tab warning/status hint below the chart (hidden when empty)."""
        if text:
            self.hintLabel.setText(text)
            self.hintLabel.setStyleSheet(
                'color: {}; font-weight: bold; padding-top: 4px;'.format(color))
            self.hintLabel.show()
        else:
            self.hintLabel.setText('')
            self.hintLabel.hide()

    def set_manual_loader(self, fn):
        """Plug a () -> None callback for the Load button."""
        self._on_manual_load = fn

    def set_show_prompt(self, fn):
        """Plug a () -> None callback for the Prompt button."""
        self._on_show_prompt = fn

    def _on_load_button(self):
        if self._on_manual_load is not None:
            self._on_manual_load()

    def _on_prompt_button(self):
        if self._on_show_prompt is not None:
            self._on_show_prompt()

    def _update_regime(self):
        """Set the bull/bear icon + text using the plugged-in functions."""
        if self._regime_fn is None:
            return
        name = self._regime_fn(self._values)
        if not name:
            self.regimeLabel.setPixmap(QPixmap())
            self.regimeLabel.setToolTip('')
            return
        pm = self._regime_icon(name) if self._regime_icon else None
        if pm is not None and not pm.isNull():
            self.regimeLabel.setPixmap(pm)
            self.regimeLabel.setToolTip('Bull market' if name == 'bull'
                                        else 'Bear market')
        else:
            self.regimeLabel.setText('🐂 Bull' if name == 'bull'
                                     else '🐻 Bear')

    def _redraw(self):
        old_xlim = None
        ax_old = self._axis()
        if ax_old is not None and ax_old.lines:
            old_xlim = ax_old.get_xlim()
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(_BG)
        if not self._dates:
            ax.text(0.5, 0.5, 'No data for {}'.format(self.series_id),
                    ha='center', va='center', color=_TXT,
                    transform=ax.transAxes)
            ax.tick_params(colors=_TXT)
            for s in ax.spines.values():
                s.set_color(_GRID)
            self.canvas.draw()
            return

        dates, values = self._visible_data()

        import matplotlib.dates as mdates
        x = mdates.date2num([datetime.datetime.combine(d, datetime.time())
                             for d in dates])
        x_all = x
        y = np.asarray(values, dtype=float)

        keep = ~np.isnan(y)
        x, y = x[keep], np.ma.masked_invalid(y[keep])

        if len(x) > 0:
            self._data_x0 = float(np.nanmin(x))
            self._data_x1 = float(np.nanmax(x))
        else:
            self._data_x0 = self._data_x1 = None

        ax.plot(x, y, color=self.color, linewidth=1.6, drawstyle='steps-post')
        ax.fill_between(x, y, y2=np.nanmin(y), color=self.color, alpha=0.12,
                        step='post')

        self._draw_pivots(ax)

        if self._zones:
            for lo, hi, color in self._zones:
                ax.axhspan(lo, hi, color=color, alpha=0.12, zorder=0)
        levels = (self._hlines if self._hlines else
                  ([self._hline] if self._hline is not None else []))
        for level in levels:
            ax.axhline(level, color='#90a4ae', linewidth=1.0,
                       linestyle='--', alpha=0.85)
            ax.text(0.006, level, '  {}'.format(level),
                    transform=ax.get_yaxis_transform(), color=_TXT,
                    fontsize=8, va='center')

        ax.grid(color=_GRID, linewidth=0.5, alpha=0.5)
        ax.set_ylabel(self.ylabel, color=_TXT)
        ax.tick_params(colors=_TXT)
        for s in ax.spines.values():
            s.set_color(_GRID)

        # Adaptive tick positions with a polite number of labels so dates on the
        # x-axis never clump together, whatever the visible span.
        loc = AutoDateLocator(minticks=4, maxticks=9)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(ConciseDateFormatter(loc))
        ax.tick_params(axis='x', labelsize=8)
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(30)
            lbl.set_ha('right')

        cur = self._values[-1] if self._values else float('nan')
        ax.set_title('{} — latest {:.2f}'.format(self.plot_label, cur),
                     color=_TXT)

        if self._show_regime and self.regimeLabel is not None:
            self._update_regime()

        if self._show_phase and self.phaseLabel is not None:
            self._update_phase()

        # Restore the previous X view (pan/zoom) when the visible data window
        # is unchanged — e.g. toggling pivot markers must not reset the view.
        if old_xlim is not None and self._data_x0 is not None:
            lo, hi = old_xlim
            xlo = min(self._data_x0, self._data_x1)
            xhi = max(self._data_x0, self._data_x1)
            if hi > lo and lo >= xlo and hi <= xhi:
                ax.set_xlim(lo, hi)
                self._fit_y(ax)

        # Restore any interval selection after a redraw (period change etc.).
        if self._sel_a is not None and self._sel_b is not None:
            self._band = ax.axvspan(
                min(self._sel_a, self._sel_b),
                max(self._sel_a, self._sel_b),
                color=self.color, alpha=0.30, linewidth=0, zorder=2)

        self.fig.tight_layout()
        self.canvas.draw()
        self._sync_scrollbar()

    def _visible_data(self):
        """(dates, values) for the currently selected period."""
        days = _PERIODS[self.periodCombo.currentIndex()][1]
        if days is not None:
            cutoff = datetime.date.today() - datetime.timedelta(days=days)
            idx = [i for i, d in enumerate(self._dates) if d >= cutoff]
            if idx:
                return ([self._dates[i] for i in idx],
                        [self._values[i] for i in idx])
        return self._dates, self._values

    def _pivot_marker_data(self):
        """List of (x_num, y_value, color) for the current visible pivots."""
        dates, values = self._visible_data()
        import matplotlib.dates as mdates
        x_all = mdates.date2num([datetime.datetime.combine(d, datetime.time())
                                 for d in dates])
        y = np.asarray(values, dtype=float)
        keep = ~np.isnan(y)
        out = []
        for i, sign in pivot_indices(values, dates, **self._pivot_kwargs):
            if not keep[i]:
                continue
            color = '#81c784' if sign < 0 else '#ef5350'
            out.append((x_all[i], float(values[i]), color))
        return out

    def _clear_pivot_artists(self):
        for a in self._pivot_artists:
            if a.axes is not None:
                a.remove()
        self._pivot_artists = []

    def _draw_pivots(self, ax):
        """(Re)draw pivot markers on `ax` per the current checkbox state."""
        self._clear_pivot_artists()
        if not self.pivotCheck.isChecked():
            return
        for x, yv, color in self._pivot_marker_data():
            sc = ax.scatter(x, yv, s=26, facecolors='none',
                            edgecolors=color, linewidths=1.4, zorder=3)
            self._pivot_artists.append(sc)

    def _on_pivot_toggled(self, _checked):
        """Toggle pivot markers without touching the rest of the chart."""
        ax = self._axis()
        if ax is None:
            return
        self._draw_pivots(ax)
        self.canvas.draw()

    def set_late_cycle(self, is_late, message):
        """Reflect the late-cycle warning (from the dialog's background load)."""
        if not self._show_late_cycle or self.lateCycleLabel is None:
            return
        if is_late:
            self.lateCycleLabel.setText(
                '⚠ Поздний цикл: {}'.format(message))
            self.lateCycleLabel.setToolTip(
                'Инвестиции падают, а потребкредит держится — экономика в позднем '
                'цикле. S&P 500 может вскоре показать пик.')
        else:
            self.lateCycleLabel.setText('')
            self.lateCycleLabel.setToolTip('')

    def _update_phase(self):
        """Set the market-cycle phase label using the plugged-in function."""
        if self._phase_fn is None:
            return
        res = self._phase_fn(self._dates, self._values)
        if not res:
            self.phaseLabel.setText('')
            return
        ru, en = res
        self.phaseLabel.setText('Фаза рынка: {} ({})'.format(ru, en))
        self.phaseLabel.setToolTip(
            'Фаза рыночного цикла по росту реального ВВП (GDPC1)')

    def real_rate_advice(self):
        """Goat text for the Cleveland ex-ante real-rate tab, or ''.

        Four regimes, matching the pivot markers on this tab:
          * fresh local peak in the positive zone turning down -> STRONG BUY,
          * below zero but rising toward it -> STRONG SELL,
          * deep negative -> cheap-money era (supportive),
          * above ~1.50% -> heavy, expensive-money environment.
        """
        if not self._values or not self._dates:
            return ''
        v = self._values[-1]
        last_date = self._dates[-1]

        piv = pivot_indices(self._values, self._dates, **self._pivot_kwargs)
        last_pivot = None
        if piv:
            idx, sign = piv[-1]
            if (last_date - self._dates[idx]).days <= 120:
                last_pivot = (self._values[idx], sign)

        if last_pivot and last_pivot[1] == -1 and last_pivot[0] > 0.0:
            return ('Реальная ставка чертит локальный пик в плюсе и '
                    'разворачивается вниз — ФРС готовится к снижению ставок '
                    '(Pivot). Давление на рынок исчезает: STRONG BUY для '
                    'S&P 500.')

        if v < 0.0:
            mo = _at_days_ago(self._dates, self._values, _MOMENTUM_DAYS)
            if mo is not None and v > mo:
                return ('Реальная ставка разворачивается вверх из минуса к '
                        'нулю — ФРС жёстко поднимает номинальные ставки. '
                        'Деньги дорожают, Big Tech падает: STRONG SELL для '
                        'S&P 500.')
            return ('Реальная ставка в глубоком минусе — деньги '
                    'обесцениваются, сидеть в кэше значит нести убытки. '
                    'Эпоха дешёвых денег: мощные циклы роста S&P 500 '
                    '(как в 2020–2021).')

        if v >= 1.50:
            return ('Реальная ставка выше 1.50% — деньги очень дорогие. '
                    'Компании сворачивают buyback и капзатраты, S&P 500 '
                    'стагнирует или падает.')

        return ''

    def permits_advice(self):
        """Goat text for the Building Permits tab, or ''.

        Permits lead the housing cycle, historically the earliest recession
        precursor. Frame the impact for S&P 500 / NASDAQ rather than
        homebuilders: regimes on YoY growth g and its 3-month acceleration
        accel (same helpers as _gdp_phase).
        """
        if not self._values or not self._dates:
            return ''
        v = self._values[-1]
        vy = _at_days_ago(self._dates, self._values, _YOY_DAYS)
        vp = _at_days_ago(self._dates, self._values, _MOMENTUM_DAYS)
        vyp = _at_days_ago(self._dates, self._values,
                           _YOY_DAYS + _MOMENTUM_DAYS)
        if not all((vy, vp, vyp)) or 0 in (vy, vp, vyp):
            return ''
        g = (v / vy - 1.0) * 100.0
        accel = g - (vp / vyp - 1.0) * 100.0

        if g > 5.0:
            if accel < -4.0:
                return ('Разрешения на стройку всё ещё растут, но темп резко '
                        'падает — жилищный цикл на вершине. S&P 500 получает '
                        'последнюю поддержку циклических секторов; коррекция '
                        'цикликов обычно опережает разворот индекса на 3–6 мес. '
                        'NASDAQ меньше зависит от жилья — за ним следите по '
                        'ставкам.')
            return ('Разрешения на стройку уверенно растут (г/г) — жилищный '
                    'цикл в экспансии, это поддержка для S&P 500: циклические '
                    'сектора тянут индекс вверх. NASDAQ получает попутный '
                    'risk-on, пока ставки не растут.')
        if g < -5.0:
            if accel > 4.0:
                return ('Падение разрешений развернулось вверх — рынок '
                        'закладывает дно жилищного цикла, а следом и дно '
                        'S&P 500 (горизонт 3–6 мес.). Ожидание снижения ставок '
                        'ФРС: NASDAQ (длинная дюрация) обычно опережает S&P 500 '
                        'в этой фазе.')
            return ('Разрешения на стройку падают (г/г) — исторически самый '
                    'ранний предвестник рецессии: S&P 500 под давлением в '
                    'горизонте 6–12 мес. NASDAQ какое-то время держится, но '
                    'падает следом, если ФРС не спешит снижать ставки.')
        if accel > 4.0:
            return ('Разрешения после боковика разворачиваются вверх — лёгкий '
                    'плюс для S&P 500 (оживление цикликов) и NASDAQ (risk-on '
                    'и ставки).')
        if accel < -4.0:
            return ('Разрешения затухают после боковика — риск охлаждения '
                    'экономики: циклические сектора S&P 500 ослабнут первыми; '
                    'NASDAQ устоит, пока ставки не выросли.')
        return ('Разрешения на стройку в боковике (г/г ~0) — нейтрально для '
                'индексов: ни риска рецессии, ни импульса роста. Решающие для '
                'S&P 500 и NASDAQ факторы сейчас — ставки и прибыли.')

    def nfib_advice(self):
        """Goat text for the NFIB leading-composite tab, or ''.

        The composite z-scores six forward-looking NFIB components and squashes
        them to [-100..+100] (see nfib.py). Reading is relative to the recent
        ~5-year baseline: level + momentum, framed for S&P 500 / NASDAQ.
        """
        if not self._values or not self._dates:
            return ''
        v = self._values[-1]
        if v != v:  # NaN
            return ''
        mo = _at_days_ago(self._dates, self._values, _MOMENTUM_DAYS)
        d = (v - mo) if mo is not None and mo == mo else None

        if v > 50.0:
            if d is not None and d < -10.0:
                return ('Композит опережающих NFIB-компонентов в зоне '
                        'оптимизма, но резко разворачивается вниз — вершина '
                        'цикла: циклические сектора S&P 500 ослабнут первыми; '
                        'NASDAQ переоценится позже, через ставки.')
            return ('Малый бизнес смотрит вперёд с оптимизмом (найм, капзатраты, '
                    'запасы, продажи) — экономика в экспансии: поддержка для '
                    'S&P 500. NASDAQ получает попутный risk-on.')
        if v < -50.0:
            if d is not None and d > 10.0:
                return ('Композит опережающих NFIB-компонентов развернулся вверх '
                        'с дна — малый бизнес снова нанимает и инвестирует. '
                        'Дно индексов близко: NASDAQ (длинная дюрация) обычно '
                        'опережает S&P 500 в этой фазе.')
            return ('Малый бизнес ждёт ухудшения и сворачивает найм и капзатраты '
                    '— опережающий сигнал рецессии: S&P 500 под давлением в '
                    'горизонте 6–12 мес. NASDAQ временно держится, но падает '
                    'следом, если ФРС не снижает ставки.')
        if d is not None and d > 10.0:
            return ('Композит набирает силу — малый бизнес оживает: лёгкий плюс '
                    'для S&P 500 и NASDAQ (risk-on).')
        if d is not None and d < -10.0:
            return ('Композит слабеет — малый бизнес осторожничает: риск '
                    'охлаждения, циклические сектора S&P 500 ослабнут первыми; '
                    'NASDAQ устоит, пока ставки не выросли.')
        return ('Композит в нейтрали — малый бизнес без явного направления. '
                'Решающие для S&P 500 и NASDAQ факторы сейчас — ставки и '
                'прибыли.')

    def sentiment_advice(self):
        """Goat text for the Michigan Consumer Sentiment tab, or ''.

        Reference lines on the chart: 80 (strong), 70 (neutral),
        55 (recession zone). Read the level plus 90-day momentum, framed
        for S&P 500 / NASDAQ.
        """
        if not self._values or not self._dates:
            return ''
        v = self._values[-1]
        if v != v:  # NaN
            return ''
        mo = _at_days_ago(self._dates, self._values, _MOMENTUM_DAYS)
        d = (v - mo) if mo is not None and mo == mo else None

        if v >= 80.0:
            if d is not None and d < -5.0:
                return ('Уверенность в зоне оптимизма, но разворачивается '
                        'вниз — потребитель начнёт тормозить траты: S&P 500 '
                        'лишается поддержки расходов, NASDAQ держится на '
                        'ставках.')
            return ('Уверенность выше 80 — уверенные траты, экономика в '
                    'экспансии: поддержка для S&P 500 и NASDAQ (risk-on).')
        if v >= 70.0:
            if d is not None and d < -5.0:
                return ('Уверенность в средней зоне и падает — потребитель '
                        'начинает экономить: циклические сектора S&P 500 '
                        'слабеют первыми, NASDAQ устоит, пока ставки не '
                        'выросли.')
            return ('Уверенность в средней зоне (70–80) — потребитель '
                    'спокоен, без эйфории: нейтрально-позитивно для S&P 500 '
                    'и NASDAQ.')
        if v >= 55.0:
            if d is not None and d > 5.0:
                return ('Уверенность у нижней границы и разворачивается '
                        'вверх — потребитель оживает, дно пессимизма '
                        'пройдено: плюс для S&P 500 в горизонте 3–6 мес.')
            return ('Уверенность ниже 70 — потребитель насторожен: экономика '
                    'замедляется, S&P 500 под давлением; NASDAQ держится, '
                    'пока ставки не растут.')
        if d is not None and d > 5.0:
            return ('Уверенность в зоне рецессии, но резко разворачивается '
                    'вверх — рынок закладывает дно: отскок S&P 500 обычно '
                    'опережает восстановление уверенности на 1–2 квартала.')
        return ('Уверенность ниже 55 — зона рецессии: потребитель зажимает '
                'траты, прибыли компаний под давлением. S&P 500 в горизонте '
                '6–12 мес. рискует следовать за настроениями; NASDAQ отскочит '
                'первым при снижении ставок ФРС.')

    # ------------------------------------------------------------------ aside
    def _sync_scrollbar(self):
        if self._data_x0 is None:
            self._syncing_scroll = True
            self.scroll.setRange(0, 0)
            self._syncing_scroll = False
            return
        ax = self._axis()
        if ax is None:
            return
        lo, hi = ax.get_xlim()
        self._view_span = hi - lo
        full = self._data_x1 - self._data_x0
        page = max(1, int(round(self._view_span * _SCROLL_SCALE)))
        self._syncing_scroll = True
        try:
            self.scroll.setRange(0, int(round(full * _SCROLL_SCALE)))
            self.scroll.setPageStep(page)
            self.scroll.setValue(int(round(lo * _SCROLL_SCALE)))
        finally:
            self._syncing_scroll = False

    def _on_scrollbar(self, value):
        if self._syncing_scroll or self._data_x0 is None or self._view_span is None:
            return
        ax = self._axis()
        if ax is None:
            return
        lo = value / float(_SCROLL_SCALE)
        hi = lo + self._view_span
        data_low, data_high = min(self._data_x0, self._data_x1), max(self._data_x0, self._data_x1)
        if hi > data_high:
            hi = data_high
            lo = hi - self._view_span
        if lo < data_low:
            lo = data_low
            hi = lo + self._view_span
        ax.set_xlim(lo, hi)
        self._fit_y(ax)
        self.canvas.draw()

    def _set_band(self, a, b):
        ax = self._axis()
        if ax is None:
            return
        if self._band is not None and self._band.axes is not None:
            self._band.remove()
        self._band = ax.axvspan(min(a, b), max(a, b), color=self.color,
                                alpha=0.30, linewidth=0, zorder=2)

    def _axis(self):
        return self.fig.axes[0] if self.fig.axes else None

    def _fit_y(self, ax):
        """Rescale the Y axis to the data currently visible in the X window."""
        if not ax.get_lines():
            return
        x = np.asarray(ax.get_lines()[0].get_xdata())
        y = np.ma.filled(ax.get_lines()[0].get_ydata(), np.nan)
        xmin, xmax = ax.get_xlim()
        keep = (x >= xmin) & (x <= xmax) & ~np.isnan(y)
        if keep.sum() < 2:
            return
        with np.errstate(all='ignore'):
            ymin, ymax = np.nanmin(y[keep]), np.nanmax(y[keep])
        span = ymax - ymin
        pad = (span if span > 0 else abs(ymax) or 1.0) * 0.06
        ax.set_ylim(ymin - pad, ymax + pad)
        ax.set_autoscaley_on(False)  # keep it: draw() would otherwise re-autoscale.

    def _on_scroll(self, event):
        ax = self._axis()
        if ax is None or ax.get_xlim()[1] <= ax.get_xlim()[0]:
            return
        base = event.xdata
        if base is None:  # cursor outside the plot area -> zoom around the centre.
            base = (ax.get_xlim()[0] + ax.get_xlim()[1]) / 2.0
        half = (ax.get_xlim()[1] - ax.get_xlim()[0]) / 2.0
        factor = 0.80 if event.step > 0 else 1.25
        ax.set_xlim(base - half * factor, base + half * factor)
        self._fit_y(ax)
        self.canvas.draw()
        self._sync_scrollbar()

    def _on_press(self, event):
        if event.button == 1 and event.inaxes is not None:
            self._dragging = True
            self._sel_a = event.xdata
            self._sel_b = event.xdata
            self._set_band(self._sel_a, self._sel_b)
            self._band.set_alpha(0.5)
            self.canvas.draw()

    def _on_motion(self, event):
        if self._dragging and event.inaxes is not None and event.xdata is not None:
            self._sel_b = event.xdata
            self._set_band(self._sel_a, self._sel_b)
            self.canvas.draw()

    def _on_release(self, event):
        if not self._dragging:
            return
        self._dragging = False
        if self._sel_a is None or self._sel_b is None:
            return
        a, b = min(self._sel_a, self._sel_b), max(self._sel_a, self._sel_b)
        if abs(b - a) < 1e-6:  # a plain click, not a selection
            self._set_band(a, a)
            self.canvas.draw()
            return
        ax = self._axis()
        if ax is not None:
            xmin, xmax = ax.get_xlim()
            pad = (b - a) * 0.06
            ax.set_xlim(max(xmin, a - pad), min(xmax, b + pad))
            self._fit_y(ax)
            ax.figure.canvas.draw()
            self._sync_scrollbar()
        # Selection is applied; drop the highlight so the zoomed-in chart is clean.
        self._sel_a = self._sel_b = None
        if self._band is not None:
            self._band.remove()
            self._band = None
        self.canvas.draw()

    def _on_double(self, event):
        if event.dblclick:
            self._reset_view()

    def _reset_view(self):
        self._sel_a = self._sel_b = None
        if self._band is not None:
            self._band.remove()
            self._band = None
        self._redraw()


class _ChartLoaderThread(QThread):
    """Fetch chart series in the background, emit each row for the UI thread.

    All network / FRED-cache access happens here so the dialog never blocks.
    Emits (series_id, dates, values, note) per series, then load_done.
    """
    row_loaded = Signal(object, object, object, str)
    load_done = Signal()

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self._items = items  # list of (series_id, loader_callable)

    def run(self):
        for series_id, loader in self._items:
            try:
                dates, values = loader(series_id)
                if dates:
                    note = '{:,} points, {}..{}'.format(
                        len(values), dates[0].isoformat(), dates[-1].isoformat())
                else:
                    note = 'no data'
            except Exception as e:  # noqa: BLE001 - surfacing fetch errors
                dates, values, note = [], [], 'Error: {}'.format(e)
            self.row_loaded.emit(series_id, dates, values, note)
        self.load_done.emit()


class MacroDialog(QDialog):
    """Tabs with charts for the five key US macro indicators."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('US Macro Overview')
        self.resize(1040, 700)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        head = QLabel('Key US macroeconomic indicators (source: FRED)')
        head.setStyleSheet('color: {}; font-weight: bold;'.format(_TXT))
        root.addWidget(head)

        self.tabs = QTabWidget()
        self._widgets = []
        self._gdp_tab = None
        self._permits_tab = None
        self._nfib_tab = None
        self._ism_tab = None
        self._ism_services_tab = None
        # Fixed tab order — build every tab widget first, then add them all in
        # one pass. No insertTab position arithmetic, so the layout is static.
        ordered = []

        # 0. MLRCI composite indicator: whole dashboard in one risk oscillator.
        self._mlrci_tab = MlrcTab(self)
        ordered.append(('MLRCI Composite', self._mlrci_tab))

        # 1. Real GDP (GDPC1) with market-cycle phase and late-cycle label, right
        # after MLRCI. The rest of the plain FRED indicators go after the
        # credit-spread block (see below).
        for series_id, title, plot_label, ylabel, color, desc in INDICATORS:
            is_gdp = (series_id == 'GDPC1')
            if not is_gdp:
                continue
            tab = _IndicatorTab(series_id, plot_label, ylabel, color, desc,
                                self, show_phase=True, show_late_cycle=True)
            tab._phase_fn = _gdp_phase
            self._gdp_tab = tab
            ordered.append((title, tab))
            self._widgets.append(tab)

        # 2. Real-rate signal tab (Cleveland Fed ex-ante real rate). Its
        # turning points drive the Buy/Sell S&P signal.
        realrate = _IndicatorTab(
            _REAL_RATE_ID, 'Ex-ante real rate (10Y)', 'Percent', '#ffb74d',
            'Реальная ставка Кливлендского ФРС (модель ex-ante, горизонт 10 лет): '
            'номинальные доходности минус модельная ожидаемая инфляция — без '
            'ценовых шоков сырья и краткосрочной паники трейдеров.', self,
            show_pivots=True,
            pivot_kwargs=dict(smooth_days=90, range_frac=0.25,
                              min_gap_days=120, local_days=730),
            explain='Ожидаемая (ex-ante) реальная процентная ставка Кливлендского '
                    'ФРС: номинальная доходность 10Y за вычетом модельной '
                    'ожидаемой инфляции. В отличие от реализованной ставки '
                    '(номинал − CPI) она не подвержена ценовым шокам сырья и '
                    'краткосрочной панике трейдеров и точнее предсказывает '
                    'развороты S&P 500. Точки перегиба: пик ставки (ставка '
                    'начала падать) → зелёный BUY S&P; впадина (ставка начала '
                    'расти) → красный SELL S&P.')
        ordered.append(('Real Interest Rate (Ex-Ante)', realrate))
        self._widgets.append(realrate)
        self._realrate_tab = realrate

        # 3. Yield curve (3M-30Y) with historical snapshots.
        self._yield_tab = _YieldCurveTab(self)
        ordered.append(('Yield Curve', self._yield_tab))

        # 4. VIX with fear/panic zones.
        self._vix_tab = VixTab(self)
        ordered.append(('VIX (Volatility)', self._vix_tab))

        # 5-6. Credit spreads: BBB and high-yield.
        credit = [
            ('BAMLC0A4CBBB', 'BBB Credit Spread (BAMLC0A4CBBB)',
             'BBB corporate credit spread', 'Percent', '#e57373',
             'Спред доходности корпоративных облигаций класса BBB к '
             'безрисковым казначейским (ICE BofA). BBB — нижняя граница '
             'инвестиционного рейтинга: это надёжные, крупные компании, '
             'которые первыми реагируют на проблемы среди гигантов. '
             'Расширение спреда = рост кредитного риска и распродажа в '
             'корпоративном секторе; сужение = уверенность рынка в '
             'надёжных компаниях.'),
            ('BAMLH0A0HYM2', 'Junk Bonds / High Yield Spread (BAMLH0A0HYM2)',
             'High-yield corporate credit spread', 'Percent', '#ba68c8',
             'Спред «мусорных» (junk / high yield) облигаций компаний с '
             'высокой долговой нагрузкой к безрисковым казначейским '
             '(ICE BofA). Самый чувствительный кредитный индикатор: при '
             'первых признаках стресса инвесторы сбрасывают самые '
             'рискованные бумаги и спред резко расширяется — ранний сигнал '
             'к падению рынка акций; сужение = аппетит к риску.'),
        ]
        for series_id, title, plot_label, ylabel, color, desc in credit:
            tab = _IndicatorTab(series_id, plot_label, ylabel, color, desc,
                                self)
            ordered.append((title, tab))
            self._widgets.append(tab)

        # 7. BBB corporate yield vs 10Y Treasury benchmark.
        self._credit_tab = CreditSpreadTab(self)
        ordered.append(('BBB Yield vs 10Y Treasury', self._credit_tab))

        # Remaining plain FRED indicators (CPI, unemployment, rates, payrolls,
        # consumer sentiment, corporate profits) — after the credit block.
        for series_id, title, plot_label, ylabel, color, desc in INDICATORS:
            if series_id == 'GDPC1':
                continue
            tab = _IndicatorTab(series_id, plot_label, ylabel, color, desc,
                                self)
            if series_id == 'PERMIT':
                self._permits_tab = tab
            elif series_id == 'UMCSENT':
                tab._hlines = [55, 70, 80]
                self._sentiment_tab = tab
            ordered.append((title, tab))
            self._widgets.append(tab)

        # 8. ISM Manufacturing PMI — нет бесплатного машинного источника: FRED
        # убрал ISM в 2016, зеркало DBnomics не обновляется с 08.2025, сайт ISM
        # закрыт (403). Данные выгружаются через ассистента (кнопка «Промт») и
        # подгружаются из CSV кнопкой «Load».
        ism_m = _IndicatorTab(
            _ISM_ID, 'ISM Manufacturing PMI', 'Index (PMI)', '#a5d6a7',
            'Индекс деловой активности в обрабатывающей промышленности США; '
            '>50 — расширение, <50 — сокращение.', self,
            show_load_button=True)
        ism_m._hline = 50
        ism_m.set_manual_loader(
            lambda: self._load_manual_csv(_ISM_ID, ism_m, _ISM_NAME))
        ism_m.set_show_prompt(
            lambda: self._show_manual_prompt(_ISM_NAME, _ISM_PROMPT))
        ism_m.set_hint('Нажмите «Промт» (скопировать запрос в буфер обмена), '
                       'затем «Load» и выберите выгруженный CSV.', '#ef9a9a')
        self._ism_tab = ism_m
        self._widgets.append(ism_m)
        ordered.append(('ISM Manufacturing PMI', ism_m))

        # 9. ISM Services PMI — тот же ручной импорт (см. комментарий выше).
        ism_s = _IndicatorTab(
            _ISM_SERVICES_ID, 'ISM Services PMI', 'Index (PMI)', '#a5d6a7',
            'Индекс деловой активности в сфере услуг США; '
            '>50 — расширение, <50 — сокращение.', self,
            show_load_button=True)
        ism_s._hline = 50
        ism_s.set_manual_loader(
            lambda: self._load_manual_csv(_ISM_SERVICES_ID, ism_s,
                                          _ISM_SERVICES_NAME))
        ism_s.set_show_prompt(
            lambda: self._show_manual_prompt(_ISM_SERVICES_NAME,
                                             _ISM_SERVICES_PROMPT))
        ism_s.set_hint('Нажмите «Промт» (скопировать запрос в буфер обмена), '
                       'затем «Load» и выберите выгруженный CSV.', '#ef9a9a')
        self._ism_services_tab = ism_s
        self._widgets.append(ism_s)
        ordered.append(('ISM Services PMI', ism_s))

        # 10. NFIB composite of leading survey components. FRED не публикует
        # NFIB, поэтому данные тянутся с официального API NFIB SBET (см.
        # nfib.fetch_components) с кэшем по TTL, как остальные FRED-серии.
        # Композит z-скорит 6 опережающих компонентов и сжимает tanh в
        # [-100;+100].
        nfib_tab = _IndicatorTab(
            _NFIB_ID, 'NFIB Composite (leading)', 'Composite [-100..+100]',
            '#4dd0e1',
            'Композит из 6 опережающих компонентов опроса малого бизнеса NFIB: '
            'ожидание роста продаж и деловых условий, планы найма, капзатрат и '
            'запасов, «хорошее время расширяться». Каждый нормирован в '
            'Z-оценку, среднее сжато tanh в [-100;+100]. Выше +50 — малый '
            'бизнес смотрит вперёд оптимистично; ниже −50 — сворачивает '
            'активность.', self)
        nfib_tab._hlines = [-80, 0, 80]
        nfib_tab._zones = [(80, 100, '#81c784'), (-100, -80, '#ef5350')]
        self._nfib_tab = nfib_tab
        self._widgets.append(nfib_tab)
        ordered.append(('NFIB Composite (leading)', nfib_tab))

        # 11. Buffett indicator.
        buffett = _IndicatorTab(
            _BUFFETT_ID, 'Buffett indicator', 'Percent', '#ffab91',
            'Соотношение капитализации американского рынка к ВВП', self)
        buffett.descLabel.setText(
            'Индикатор Баффета — капитализация американского рынка к ВВП: '
            '<100% — рынок дешевле экономики, >100% — дороже.')
        ordered.append(('Buffett Indicator', buffett))
        self._widgets.append(buffett)
        self._buffett_tab = buffett

        for title, tab in ordered:
            self.tabs.addTab(tab, title)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self.reloadButton = self._build_footer(root)

        self._loader = None
        self._load_all()

    def _build_footer(self, root):
        row = QHBoxLayout()
        row.addStretch(1)
        from PySide6.QtWidgets import QPushButton
        reloadBtn = QPushButton('Reload')
        reloadBtn.clicked.connect(self._load_all)
        row.addWidget(reloadBtn)
        closeBtn = QPushButton('Close')
        closeBtn.clicked.connect(self.accept)
        row.addWidget(closeBtn)
        root.addLayout(row)
        return reloadBtn

    def _on_row_loaded(self, series_id, dates, values, note):
        if series_id in (_LATE_GDPI, _LATE_CC):
            self._late_data[series_id] = (dates, values)
            return
        if series_id == 'NTFS':
            self._yield_tab.set_ntfs(dates, values)
            return
        if series_id == 'MLRCI':
            self._mlrci_tab.set_mlrci(dates, values)
            return
        if series_id == 'MLRCI_MARKS':
            buy = [(d, v) for d, v in zip(dates, values) if v == 1]
            sell = [(d, v) for d, v in zip(dates, values) if v == -1]
            self._mlrci_tab.set_marks(buy, sell)
            return
        if series_id == 'SP500':
            self._mlrci_tab.set_sp500(dates, values)
            return
        if series_id == _REAL_RATE_ID:
            self._yield_tab.set_real_rate(dates, values)
        if series_id in self._yield_tab.series_ids:
            self._yield_tab.set_series(series_id, dates, values)
        if series_id in self._credit_tab.series_ids:
            self._credit_tab.set_series(series_id, dates, values)
        if series_id in self._vix_tab.series_ids:
            self._vix_tab.set_data(dates, values, note)
        if series_id in self._yield_tab.series_ids \
                or series_id in self._credit_tab.series_ids \
                or series_id in self._vix_tab.series_ids:
            return
        for tab in self._widgets:
            if tab.series_id == series_id:
                tab.set_data(dates, values, note)
                if series_id == _BUFFETT_ID:
                    self._update_buffett_hint(values)
                if series_id in _MANUAL_IDS and values:
                    tab.set_hint('', '')
                return

    def _update_buffett_hint(self, values):
        latest = values[-1] if values else None
        text, warning = buffett_hint(latest)
        color = '#ef5350' if warning else _TXT
        self._buffett_tab.set_hint(text, color)

    def _show_manual_prompt(self, name, prompt):
        """Copy an export prompt to the clipboard and show it."""
        QApplication.clipboard().setText(prompt)
        QMessageBox.information(
            self, name,
            'Промт для выгрузки данных скопирован в буфер обмена.\n'
            'Вставьте его в ассистент, сохраните ответ в файл CSV и нажмите '
            '«Load».\n\n' + prompt)

    def _load_manual_csv(self, series_id, tab, name):
        """Pick a CSV exported via the prompt and plot + cache the series."""
        if tab is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, 'Загрузить {} (CSV)'.format(name), '',
            'CSV (*.csv);;All files (*)')
        if not path:
            return
        try:
            dates, values = _parse_ism_csv(path)
        except Exception as e:  # noqa: BLE001 - file read failure
            QMessageBox.warning(self, name,
                                'Не удалось прочитать файл:\n{}'.format(e))
            return
        if not dates:
            QMessageBox.warning(
                self, name,
                'Не найдено ни одной строки в формате date,value '
                '(дата YYYY-MM-DD).')
            return
        _save_cached(series_id, dates, values)
        note = '{:,} points, {}..{}'.format(
            len(values), dates[0].isoformat(), dates[-1].isoformat())
        tab.set_data(dates, values, note)
        tab.set_hint('', '')

    def _show_goat(self, advice):
        """Show the goat with `advice` (long enough to read), or hide it."""
        from qualitative_dialog import GoatAssistant
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        if not advice:
            return
        self._goat = GoatAssistant('', self, advice=advice,
                                   auto_hide_ms=20000)
        self._goat.show()

    def _on_tab_changed(self, index):
        """The goat speaks only about the tab the user just switched to.

        On the Yield Curve tab it explains the current curve vs a year ago; on
        the GDP tab it warns about a late cycle when detected. Switching away
        hides the hint so it never lingers over another chart.
        """
        widget = self.tabs.widget(index)
        advice = None
        if widget is self._yield_tab:
            advice = self._yield_tab.curve_comparison_message()
        elif widget is self._realrate_tab:
            advice = self._realrate_tab.real_rate_advice()
        elif widget is self._gdp_tab:
            g = self._late_data.get(_LATE_GDPI)
            c = self._late_data.get(_LATE_CC)
            if g and c and _late_cycle(g[1], g[0], c[1], c[0]):
                advice = ('Инвестиции (GPDI) падают, потребкредит (CCSA) '
                          'держится — поздний цикл: S&P 500 близок к пику. '
                          'Выходите из Tech и Consumer Discretionary в защиту '
                          '(Utilities, Consumer Staples, Healthcare).')
        elif widget is self._permits_tab:
            advice = widget.permits_advice()
        elif widget is self._nfib_tab:
            advice = widget.nfib_advice()
        elif widget is self._sentiment_tab:
            advice = widget.sentiment_advice()
        self._show_goat(advice)

    def closeEvent(self, event):
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
        if self._loader is not None and self._loader.isRunning():
            self._loader.wait(5000)
        super().closeEvent(event)

    def _load_all(self):
        self.reloadButton.setEnabled(False)
        self._late_data = {}
        loaders = {_BUFFETT_ID: _load_buffett,
                   _ISM_ID: _load_ism,
                   _ISM_SERVICES_ID: _load_ism,
                   _NFIB_ID: _load_nfib}
        items = [(t.series_id, loaders.get(t.series_id, _fred))
                 for t in self._widgets]
        items.extend((sid, _fred) for sid, _lbl, _years in YIELD_CURVE_SERIES)
        items.extend((sid, _fred) for sid in self._credit_tab.series_ids)
        items.extend((sid, _fred) for sid in self._vix_tab.series_ids)
        items.append(('MLRCI', _load_mlrci))
        items.append(('MLRCI_MARKS', _load_mlrci_marks))
        items.append(('SP500', _fred))
        items.append(('NTFS', _load_ntfs))
        items.append((_LATE_GDPI, _fred))
        items.append((_LATE_CC, _fred))
        self._loader = _ChartLoaderThread(items, self)
        self._loader.row_loaded.connect(self._on_row_loaded)
        self._loader.load_done.connect(self._on_load_done)
        self._loader.start()

    def _on_load_done(self):
        """Run after the background load: refresh the GDP late-cycle label."""
        self.reloadButton.setEnabled(True)
        if self._gdp_tab is None:
            return
        g = self._late_data.get(_LATE_GDPI)
        c = self._late_data.get(_LATE_CC)
        if g and c:
            is_late = _late_cycle(g[1], g[0], c[1], c[0])
            msg = ('Инвестиции (GPDI) падают, потребкредит (CCSA) держится'
                   if is_late else '')
            self._gdp_tab.set_late_cycle(is_late, msg)
        # The goat speaks on tab switches (see _on_tab_changed), not on load.
