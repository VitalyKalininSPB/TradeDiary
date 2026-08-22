# -*- coding: utf-8 -*-
"""Moving-average chart for a single ticker.

Shows price with SMA20/SMA50, marks golden/death crosses and highlights the
deal's hold period. Scrolls freely over up to ~2 years of cached history.
"""
import datetime

import numpy as np
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.dates import DateFormatter

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QComboBox)
from PySide6.QtCore import Qt

import price_history

SHORT_MA = 20
LONG_MA = 50

_BG = '#1e1f24'
_TXT = '#dcdce0'
_GRID = '#43464f'
_PRICE = '#90caf9'
_MA_S = '#ffd54f'
_MA_L = '#80a9ff'


def _smooth(dates, prices, window):
    """Simple moving average aligned to the input grid (NaN until warmup)."""
    if len(prices) < window:
        return np.full(len(prices), np.nan)
    out = np.full(len(prices), np.nan)
    cum = np.cumsum(np.insert(prices, 0, 0.0))
    out[window - 1:] = (cum[window:] - cum[:-window]) / window
    return out


def _crosses(short, long):
    """Indices where short crosses long. Returns (deaths, goldens)."""
    diff = np.asarray(short) - np.asarray(long)
    deaths, goldens = [], []
    for i in range(1, len(diff)):
        if np.isnan(diff[i]) or np.isnan(diff[i - 1]):
            continue
        if diff[i - 1] > 0 >= diff[i]:
            deaths.append(i)
        elif diff[i - 1] < 0 <= diff[i]:
            goldens.append(i)
    return deaths, goldens


class MAChartDialog(QDialog):
    def __init__(self, ticker, currency, open_date='', close_date='', parent=None):
        super().__init__(parent)
        self.ticker = ticker or ''
        self.currency = currency or ''
        self.open_date = open_date or ''
        self.close_date = close_date or ''
        self.setWindowTitle('MA chart — {}'.format(self.ticker))
        self.resize(980, 620)

        _ = price_history.ensure_history(self.ticker, self.currency)
        self.series = _sorted_series(price_history.load_series(self.ticker))

        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        bar.addWidget(QLabel('Window:'))
        self.windowCombo = QComboBox()
        self.windowCombo.addItems(['1M', '3M', '6M', '1Y', 'All (2Y)'])
        self.windowCombo.setCurrentIndex(self.windowCombo.count() - 1)
        self.windowCombo.setToolTip('Window length for display; free panning via toolbar.')
        self.windowCombo.currentIndexChanged.connect(self._redraw)
        bar.addWidget(self.windowCombo)
        self.hintLabel = QLabel('')
        self.hintLabel.setStyleSheet('color: {};'.format(_TXT))
        bar.addWidget(self.hintLabel, 1)
        layout.addLayout(bar)

        self.fig = Figure(figsize=(10, 6), dpi=100)
        self.fig.patch.set_facecolor(_BG)
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        self._redraw()

    def _redraw(self):
        self.fig.clear()
        layout_sel = self.windowCombo.currentText()
        n = _window_size(layout_sel, self.series)

        dates = [d for d, _ in self.series]
        prices = np.array([p for _, p in self.series], dtype=float)
        if len(prices) < LONG_MA:
            ax = self.fig.add_subplot(111)
            ax.set_facecolor(_BG)
            ax.text(0.5, 0.5, 'Not enough history for SMA%02d' % LONG_MA,
                    ha='center', va='center', color=_TXT, transform=ax.transAxes)
            ax.set_xticklabels([])
            ax.set_yticklabels([])
            ax.tick_params(colors=_TXT)
            for s in ax.spines.values():
                s.set_color(_GRID)
            self.canvas.draw()
            return

        # View on the most recent `n` points.
        dates = dates[-n:]
        prices = prices[-n:]
        ma_s = _smooth(prices, prices, SHORT_MA)
        ma_l = _smooth(prices, prices, LONG_MA)

        x = np.arange(len(dates))

        ax = self.fig.add_subplot(111)
        ax.set_facecolor(_BG)
        ax.plot(x, prices, color=_PRICE, linewidth=1.2, label='Close')
        ax.plot(x, ma_s, color=_MA_S, linewidth=1.3, label='SMA%d' % SHORT_MA)
        ax.plot(x, ma_l, color=_MA_L, linewidth=1.4, label='SMA%d' % LONG_MA)
        ax.fill_between(x, ma_s, ma_l, where=ma_s >= ma_l,
                        color='#2e7d32', alpha=0.16, interpolate=True)
        ax.fill_between(x, ma_s, ma_l, where=ma_s < ma_l,
                        color='#c62828', alpha=0.16, interpolate=True)

        # Crosses within the visible window.
        for i in _crosses(ma_s, ma_l)[1]:
            _mark_cross(ax, x[i], prices[i], 'golden')
        for i in _crosses(ma_s, ma_l)[0]:
            _mark_cross(ax, x[i], prices[i], 'death')

        # Deal hold period.
        self._mark_hold(ax, x, dates, prices)

        _tick_dates(ax, x, dates)
        ax.set_ylabel('Price', color=_TXT)
        ax.grid(color=_GRID, linewidth=0.5, alpha=0.5)
        ax.tick_params(colors=_TXT)
        for s in ax.spines.values():
            s.set_color(_GRID)
        ax.legend(loc='best', facecolor=_BG, edgecolor=_GRID, labelcolor=_TXT,
                  fontsize=9)

        self.fig.tight_layout()
        self.canvas.draw()

    def _mark_hold(self, ax, x, dates, prices):
        """Shade the deal hold period and annotate duration."""
        start = _parse_date(self.open_date)
        if start is None:
            return
        end = _parse_date(self.close_date) or datetime.date.today()
        # Map dates onto the x positions in this window.
        lo = hi = None
        for i, d in enumerate(dates):
            d = _parse_date(d)
            if d is None:
                continue
            if lo is None and d >= start:
                lo = i
            if d <= end:
                hi = i
        if lo is None or hi is None or lo > hi:
            return
        ax.axvspan(lo, hi, color='#ffffff', alpha=0.06)
        hold_days = (end - start).days
        ax.annotate(
            'hold {}d'.format(hold_days),
            xy=(hi, prices[lo]),
            xytext=(hi - 5, prices[lo]),
            color='#e6e6ea', fontsize=8,
            ha='right', va='bottom',
            arrowprops=dict(arrowstyle='-', color='#e6e6ea', lw=0.6),
            bbox=dict(boxstyle='round,pad=0.25', fc=_BG, ec=_GRID))


def _mark_cross(ax, x, y, kind):
    color = '#e53935' if kind == 'death' else '#43a047'
    mark = 'x' if kind == 'death' else 'o'
    ax.scatter([x], [y], color=color, zorder=6, s=46, marker=mark)
    ax.axvline(x, color=color, linestyle='--', linewidth=0.8, alpha=0.7, zorder=3)
    label = 'Death Cross' if kind == 'death' else 'Golden Cross'
    ax.annotate(label, xy=(x, y), xytext=(x + 2, y),
                color=color, fontsize=8, va='center',
                bbox=dict(boxstyle='round,pad=0.2', fc=_BG, ec=color))


def _tick_dates(ax, x, dates):
    n = len(dates)
    if n <= 1:
        return
    step = max(1, n // 8)
    ticks = list(range(0, n, step))
    if ticks[-1] != n - 1:
        ticks.append(n - 1)
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i][5:] if len(dates[i]) >= 5 else dates[i]
                        for i in ticks], rotation=0, color=_TXT)


def _window_size(sel, series):
    n = len(series)
    mapping = {'1M': 21, '3M': 63, '6M': 126, '1Y': 252, 'All (2Y)': n}
    return mapping.get(sel, n)


def _sorted_series(series):
    return sorted(series.items(), key=lambda kv: kv[0])


def _parse_date(s):
    if not s:
        return None
    for fmt in ('%d/%m/%Y', '%d/%m/%Y %H:%M', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(str(s), fmt).date()
        except ValueError:
            continue
    return None
