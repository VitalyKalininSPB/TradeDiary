# -*- coding: utf-8 -*-
"""VIX (CBOE Volatility Index) tab for the macro dashboard.

The index is quoted in points (expected annualized vol %). Historically it is
split into three zones: calm/greed (10-15), normal (15-25) and panic (above
30), drawn as shaded bands and horizontal guide lines. The series comes from
FRED (VIXCLS) and is cached in the shared macro_cache.db by the MacroDialog
loader, so this module only builds the chart widget.
"""
import datetime

import numpy as np
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QComboBox)

_BG = '#1e1f24'
_TXT = '#dcdce0'
_GRID = '#43464f'
_VIX = '#ffb74d'

# Zone boundaries: (from, to, color, label).
_VIX_ZONES = [
    (10.0, 15.0, '#2e7d32', 'Зона спокойствия / Жадности (10–15)'),
    (15.0, 25.0, '#b0bec5', 'Нормальная волатильность (15–25)'),
    (25.0, 30.0, '#f57c00', 'Повышенная тревожность (25–30)'),
    (30.0, 120.0, '#c62828', 'Зона паники и страха (>30)'),
]
_VIX_LINES = (10.0, 15.0, 25.0, 30.0)

_PERIODS = [('6M', 182), ('1Y', 365), ('3Y', 3 * 365), ('5Y', 5 * 365),
            ('Max', None)]


class VixTab(QWidget):
    """VIX chart with calm/normal/panic zones as shaded bands."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series_ids = ['VIXCLS']
        self._dates = []
        self._values = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel('CBOE Volatility Index (VIX)'))
        bar.addStretch(1)
        bar.addWidget(QLabel('Period:'))
        self.periodCombo = QComboBox()
        for name, _days in _PERIODS:
            self.periodCombo.addItem(name)
        self.periodCombo.setCurrentIndex(4)
        self.periodCombo.currentIndexChanged.connect(lambda _i: self._redraw())
        bar.addWidget(self.periodCombo)
        root.addLayout(bar)

        desc = QLabel(
            'Индекс волатильности S&P 500, пункты = ожидаемая годовая '
            'волатильность в %. Зоны: 🟢 10–15 спокойствие/жадность, '
            '⚠️ 15–25 норма, 💥 выше 30 паника и капитуляция.')
        desc.setWordWrap(True)
        desc.setStyleSheet('color: #6a6d78; font-size: 11px;')
        root.addWidget(desc)

        self.fig = Figure(figsize=(9, 5), dpi=100)
        self.fig.patch.set_facecolor(_BG)
        self.canvas = FigureCanvas(self.fig)
        root.addWidget(self.canvas)

        self.zoneLabel = QLabel('')
        self.zoneLabel.setWordWrap(True)
        root.addWidget(self.zoneLabel)

    def set_data(self, dates, values, note=''):
        self._dates = dates
        self._values = values
        self._redraw()

    def _visible(self):
        days = _PERIODS[self.periodCombo.currentIndex()][1]
        dates, values = self._dates, self._values
        if days is not None:
            cutoff = datetime.date.today() - datetime.timedelta(days=days)
            idx = [i for i, d in enumerate(dates) if d >= cutoff]
            if idx:
                return ([dates[i] for i in idx], [values[i] for i in idx])
        return dates, values

    def _redraw(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(_BG)
        if not self._dates:
            ax.text(0.5, 0.5, 'No data for VIXCLS', ha='center', va='center',
                    color=_TXT, transform=ax.transAxes)
            ax.tick_params(colors=_TXT)
            for s in ax.spines.values():
                s.set_color(_GRID)
            self.canvas.draw()
            return

        dates, values = self._visible()
        import matplotlib.dates as mdates
        x = mdates.date2num([datetime.datetime.combine(d, datetime.time())
                             for d in dates])
        y = np.asarray(values, dtype=float)

        # Zone bands (fixed to the visible x range so they stay in view).
        if len(x):
            for lo, hi, color, _lbl in _VIX_ZONES:
                ax.axhspan(lo, hi, xmin=0, xmax=1, color=color, alpha=0.10,
                           zorder=0)
        for level in _VIX_LINES:
            ax.axhline(level, color=_GRID, linewidth=0.8, linestyle='--',
                       alpha=0.8, zorder=0)
        ax.plot(x, y, color=_VIX, linewidth=1.4)

        ax.grid(color=_GRID, linewidth=0.5, alpha=0.4)
        ax.set_ylabel('VIX (points)', color=_TXT)
        ax.set_ylim(0, max(60.0, float(np.nanmax(y)) * 1.1))
        ax.tick_params(colors=_TXT)
        for s in ax.spines.values():
            s.set_color(_GRID)
        loc = AutoDateLocator(minticks=4, maxticks=9)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(ConciseDateFormatter(loc))
        ax.tick_params(axis='x', labelsize=8)
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(30)
            lbl.set_ha('right')

        latest = self._values[-1] if self._values else float('nan')
        ax.set_title('VIX — latest {:.2f}'.format(latest), color=_TXT)
        self._update_zone(latest)
        self.fig.tight_layout()
        self.canvas.draw()

    def _update_zone(self, v):
        if v != v:  # NaN
            self.zoneLabel.setText('')
            return
        if v < 10.0:
            txt, color = ('VIX ниже 10 — экстремальная жадность, рынок '
                          'перегрет.', '#81c784')
        elif v < 15.0:
            txt, color = ('🟢 Зона спокойствия / Жадности (10–15): полный '
                          'штиль, но рынок часто перегрет — теряется '
                          'бдительность.', '#81c784')
        elif v < 25.0:
            txt, color = ('⚠️ Нормальная волатильность (15–25): обычный '
                          'режим, локальные коррекции, риск умеренный.',
                          _TXT)
        elif v < 30.0:
            txt, color = ('Повышенная тревожность (25–30): нервозность '
                          'растёт, готовьтесь к распродажам.', '#ffb74d')
        else:
            txt, color = ('💥 Зона паники и страха (>30): капитуляция и '
                          'массовые распродажи, S&P 500 летит вниз.',
                          '#ef5350')
        self.zoneLabel.setText(txt)
        self.zoneLabel.setStyleSheet(
            'color: {}; font-weight: bold;'.format(color))