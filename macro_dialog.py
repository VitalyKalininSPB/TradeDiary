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

from matplotlib.collections import PolyCollection

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QWidget, QLabel, QComboBox, QApplication,
                               QMessageBox, QScrollBar)
from PySide6.QtCore import Qt

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
]

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
        dates = [datetime.date.fromisoformat(d) for d in data_json['dates']]
        values = data_json['values']
    except (KeyError, TypeError, ValueError):
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


class _IndicatorTab(QWidget):
    """One tab: a matplotlib chart of a single FRED indicator."""

    def __init__(self, series_id, plot_label, ylabel, color, description='',
                 parent=None):
        super().__init__(parent)
        self.series_id = series_id
        self.plot_label = plot_label
        self.ylabel = ylabel
        self.color = color

        self._dates = []
        self._values = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel(series_id))
        self.noteLabel = QLabel('')
        self.noteLabel.setStyleSheet('color: {};'.format(_TXT))
        bar.addWidget(self.noteLabel, 1)
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

    def _redraw(self):
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

        days = _PERIODS[self.periodCombo.currentIndex()][1]
        if days is not None:
            cutoff = datetime.date.today() - datetime.timedelta(days=days)
            idx = [i for i, d in enumerate(self._dates) if d >= cutoff]
            if idx:
                dates = [self._dates[i] for i in idx]
                values = [self._values[i] for i in idx]
            else:
                dates, values = self._dates, self._values
        else:
            dates, values = self._dates, self._values

        import matplotlib.dates as mdates
        x = mdates.date2num([datetime.datetime.combine(d, datetime.time())
                             for d in dates])
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

        # Restore any interval selection after a redraw (period change etc.).
        if self._sel_a is not None and self._sel_b is not None:
            self._band = ax.axvspan(
                min(self._sel_a, self._sel_b),
                max(self._sel_a, self._sel_b),
                color=self.color, alpha=0.30, linewidth=0, zorder=2)

        self.fig.tight_layout()
        self.canvas.draw()
        self._sync_scrollbar()

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
        for series_id, title, plot_label, ylabel, color, desc in INDICATORS:
            tab = _IndicatorTab(series_id, plot_label, ylabel, color, desc, self)
            self.tabs.addTab(tab, title)
            self._widgets.append(tab)
        root.addWidget(self.tabs, 1)

        self.reloadButton = self._build_footer(root)

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._load_all()
        finally:
            QApplication.restoreOverrideCursor()

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

    def _load_all(self):
        self.reloadButton.setEnabled(False)
        for tab in self._widgets:
            try:
                dates, values = _fred(tab.series_id)
                note = '{:,} points, {}..{}'.format(
                    len(values), dates[0].isoformat(), dates[-1].isoformat())
            except Exception as e:  # noqa: BLE001 - surfacing fetch errors
                dates, values, note = [], [], 'Error: {}'.format(e)
            tab.set_data(dates, values, note)
        self.reloadButton.setEnabled(True)
