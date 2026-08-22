# -*- coding: utf-8 -*-
"""Candlestick chart for a single ticker over a reasonable interval.

Uses the cached OHLC history. The window selector defaults to a hold-period-like
range (a few months) so the deal is easy to inspect against the candles.
"""
import datetime

import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QComboBox)

import price_history

_BG = '#1e1f24'
_TXT = '#dcdce0'
_GRID = '#43464f'
_UP = '#26a69a'
_DOWN = '#ef5350'
_WICK = _TXT


class CandlesDialog(QDialog):
    def __init__(self, ticker, currency, open_date='', close_date='', parent=None):
        super().__init__(parent)
        self.ticker = ticker or ''
        self.currency = currency or ''
        self.open_date = open_date or ''
        self.close_date = close_date or ''
        self.setWindowTitle('Candles — {}'.format(self.ticker))
        self.resize(980, 620)

        price_history.ensure_ohlc(self.ticker, self.currency)
        self.ohlc = price_history.load_ohlc(self.ticker)

        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        bar.addWidget(QLabel('Interval:'))
        self.intervalCombo = QComboBox()
        self.intervalCombo.addItems(['1M', '3M', '6M', '1Y', '2Y'])
        self.intervalCombo.setCurrentIndex(1)  # 3M default fits ~20-60d deals
        self.intervalCombo.currentIndexChanged.connect(self._redraw)
        bar.addWidget(self.intervalCombo)
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
        sel = self.intervalCombo.currentText()
        n = {'1M': 21, '3M': 63, '6M': 126, '1Y': 252, '2Y': 504}.get(sel, 63)

        data = self.ohlc[-n:]
        if not data:
            ax = self.fig.add_subplot(111)
            ax.set_facecolor(_BG)
            ax.text(0.5, 0.5, 'Not enough OHLC history', ha='center', va='center',
                    color=_TXT, transform=ax.transAxes)
            ax.tick_params(colors=_TXT)
            for s in ax.spines.values():
                s.set_color(_GRID)
            self.canvas.draw()
            return

        dates = [d for d, *_ in data]
        opens = [o for _, o, *_ in data]
        highs = [h for _, _, h, _, _ in data]
        lows = [l for _, _, _, l, _ in data]
        closes = [c for _, _, _, _, c in data]

        ax = self.fig.add_subplot(111)
        ax.set_facecolor(_BG)

        rise = [c >= o for o, c in zip(opens, closes)]
        body = 0.6

        for i in range(len(data)):
            x = i
            color = _UP if rise[i] else _DOWN
            # Wicks.
            ax.plot([x, x], [lows[i], highs[i]], color=_WICK, linewidth=1.0,
                    zorder=1)
            # Body.
            bottom = min(opens[i], closes[i])
            height = max(opens[i], closes[i]) - bottom
            if height <= 0:
                height = max(highs[i] - lows[i], 1e-9) * 0.05
            ax.add_patch(Rectangle((x - body / 2.0, bottom), body, height,
                                   facecolor=color, edgecolor=color,
                                   zorder=2))
        self._mark_hold(ax, dates, highs, lows, data)
        _tick_dates(ax, dates)
        ax.grid(color=_GRID, linewidth=0.5, alpha=0.4)
        ax.set_ylabel('Price', color=_TXT)
        ax.tick_params(colors=_TXT)
        for s in ax.spines.values():
            s.set_color(_GRID)
        self.fig.tight_layout()
        self.canvas.draw()

    def _mark_hold(self, ax, dates, highs, lows, data):
        start = _parse_date(self.open_date)
        if start is None:
            return
        end = _parse_date(self.close_date) or datetime.date.today()
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
        ax.axvspan(lo, hi, color='#ffffff', alpha=0.07)
        hold_days = (end - start).days
        top = max(highs)
        ax.annotate('hold {}d'.format(hold_days), xy=(hi, top),
                    xytext=(lo, top), color='#e6e6ea', fontsize=8,
                    ha='left', va='bottom',
                    bbox=dict(boxstyle='round,pad=0.25', fc=_BG, ec=_GRID))


def _tick_dates(ax, dates):
    n = len(dates)
    if n <= 1:
        return
    step = max(1, n // 9)
    ticks = list(range(0, n, step))
    if ticks[-1] != n - 1:
        ticks.append(n - 1)
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i] for i in ticks], rotation=30,
                       ha='right', fontsize=8, color=_TXT)


def _parse_date(s):
    if not s:
        return None
    for fmt in ('%d/%m/%Y', '%d/%m/%Y %H:%M', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(str(s), fmt).date()
        except ValueError:
            continue
    return None
