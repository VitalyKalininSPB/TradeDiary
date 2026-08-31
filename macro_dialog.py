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

from matplotlib.collections import PolyCollection

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QWidget, QLabel, QComboBox, QApplication,
                               QMessageBox, QScrollBar, QCheckBox)
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
]

# Buffett indicator = market value of US corporate equities / nominal GDP.
# Wilshire index data was removed from FRED in 2024, so the numerator is the
# Fed's own "Market Value of Equities Outstanding" (NCBEILQ027S, $ millions)
# from the Integrated Macroeconomic Accounts; GDP is the quarterly nominal
# series ($ billions). Ratio -> percent: millions / (billions*1000) * 100.
_BUFFETT_ID = 'BUFFETT'
_BUFFETT_CAP_ID = 'NCBEILQ027S'
_BUFFETT_GDP_ID = 'GDP'

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


def _load_ntfs(series_id):
    """NTFS (Engstrom-Sharpe near-term forward spread) series for the yield tab.

    Computed from the cached FRED yields (DTB3, DGS6MO, DGS1, DGS2), so it
    belongs on the background loader thread, never the UI thread.
    """
    series = {sid: _fred(sid) for sid in ('DTB3', 'DGS6MO', 'DGS1', 'DGS2')}
    return compute_ntfs_series(series)


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
                 pivot_kwargs=None, explain=''):
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
        root.addLayout(bar)

        if description:
            self.descLabel = QLabel(description)
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
                note = '{:,} points, {}..{}'.format(
                    len(values), dates[0].isoformat(), dates[-1].isoformat())
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
        for series_id, title, plot_label, ylabel, color, desc in INDICATORS:
            is_gdp = (series_id == 'GDPC1')
            tab = _IndicatorTab(series_id, plot_label, ylabel, color, desc,
                                self, show_phase=is_gdp,
                                show_late_cycle=is_gdp)
            if is_gdp:
                tab._phase_fn = _gdp_phase
                self._gdp_tab = tab
            self.tabs.addTab(tab, title)
            self._widgets.append(tab)

        # Real-rate signal tab (Cleveland Fed ex-ante real rate), placed right
        # after Real GDP. Its turning points drive the Buy/Sell S&P signal.
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
        self.tabs.insertTab(1, realrate, 'Real Interest Rate (Ex-Ante)')
        self._widgets.append(realrate)
        self._realrate_tab = realrate

        buffett = _IndicatorTab(
            _BUFFETT_ID, 'Buffett indicator', 'Percent', '#ffab91',
            'Соотношение капитализации американского рынка к ВВП', self)
        buffett.descLabel.setText(
            'Индикатор Баффета — капитализация американского рынка к ВВП: '
            '<100% — рынок дешевле экономики, >100% — дороже.')
        self.tabs.addTab(buffett, 'Buffett Indicator')
        self._widgets.append(buffett)
        self._buffett_tab = buffett

        # Yield-curve tab at fixed position 3 (0-based index 2): term structure
        # (3M-30Y) with historical snapshots, so steepening/flattening/inversion
        # is visible.
        self._yield_tab = _YieldCurveTab(self)
        self.tabs.insertTab(2, self._yield_tab, 'Yield Curve')
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
        if series_id == _REAL_RATE_ID:
            self._yield_tab.set_real_rate(dates, values)
        if series_id in self._yield_tab.series_ids:
            self._yield_tab.set_series(series_id, dates, values)
            return
        for tab in self._widgets:
            if tab.series_id == series_id:
                tab.set_data(dates, values, note)
                if series_id == _BUFFETT_ID:
                    self._update_buffett_hint(values)
                return

    def _update_buffett_hint(self, values):
        latest = values[-1] if values else None
        text, warning = buffett_hint(latest)
        color = '#ef5350' if warning else _TXT
        self._buffett_tab.set_hint(text, color)

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
        loaders = {_BUFFETT_ID: _load_buffett}
        items = [(t.series_id, loaders.get(t.series_id, _fred))
                 for t in self._widgets]
        items.extend((sid, _fred) for sid, _lbl, _years in YIELD_CURVE_SERIES)
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
