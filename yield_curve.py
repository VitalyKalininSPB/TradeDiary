# -*- coding: utf-8 -*-
"""US Treasury yield curve tab for the macro dashboard.

Daily Treasury Par Yield Curve Rates (FRED DGS3MO ... DGS30): each maturity is
a plain FRED daily series cached in the shared macro_cache.db by the MacroDialog
loader, so this module only builds the chart widget. The tab plots yield (%)
against the term (log-scaled years) and overlays historical snapshots so the
current curve's shape — steepening, flattening or inversion — is compared with
the recent past at a glance.
"""
import bisect
import datetime
import math

import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QComboBox)

_BG = '#1e1f24'
_TXT = '#dcdce0'
_GRID = '#43464f'

# (FRED series_id, short maturity label, maturity in years). The label is drawn
# on the x-axis, the year value on the (log) axis scale.
YIELD_CURVE_SERIES = [
    ('DGS3MO', '3M', 0.25),
    ('DGS6MO', '6M', 0.5),
    ('DGS1',   '1Y', 1.0),
    ('DGS2',   '2Y', 2.0),
    ('DGS3',   '3Y', 3.0),
    ('DGS5',   '5Y', 5.0),
    ('DGS7',   '7Y', 7.0),
    ('DGS10',  '10Y', 10.0),
    ('DGS20',  '20Y', 20.0),
    ('DGS30',  '30Y', 30.0),
]

# Snapshot presets: name -> days-back offsets drawn as overlaid curves.
_SNAP_SETS = [
    ('Текущая кривая', (0,)),
    ('Текущая + 1 мес', (0, 30)),
    ('Текущая + 3 мес', (0, 90)),
    ('Текущая + 1 год', (0, 365)),
    ('Текущая + 1 год + 3 года', (0, 365, 1095)),
]
_SNAP_COLORS = ('#f5f5f5', '#ffd54f', '#ffab91', '#80a9ff', '#a5d6a7')
_SNAP_STYLES = ('-', '--', '-.', ':', '-.')


class _YieldCurveTab(QWidget):
    """Term-structure chart: yield (%) vs maturity (years, log axis)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series_ids = [sid for sid, _lbl, _years in YIELD_CURVE_SERIES]
        self._data = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel('US Treasury Constant Maturity Rates'))
        bar.addStretch(1)
        bar.addWidget(QLabel('Срезы:'))
        self.snapCombo = QComboBox()
        for name, _offsets in _SNAP_SETS:
            self.snapCombo.addItem(name)
        self.snapCombo.setCurrentIndex(3)
        self.snapCombo.currentIndexChanged.connect(lambda _i: self._redraw())
        bar.addWidget(self.snapCombo)
        root.addLayout(bar)

        desc = QLabel(
            'Доходность казначейских облигаций США по срокам (3M–30Y), '
            'источник FRED. Нормальная кривая растёт вверх — длинные бумаги '
            'дают премию за срок. Инверсия (короткие ставки выше длинных) '
            'исторически предшествует рецессии; 2Y-10Y и 3M-10Y — главные '
            'наблюдаемые спреды.')
        desc.setWordWrap(True)
        desc.setStyleSheet('color: #6a6d78; font-size: 11px;')
        root.addWidget(desc)

        self.fig = Figure(figsize=(9, 5), dpi=100)
        self.fig.patch.set_facecolor(_BG)
        self.canvas = FigureCanvas(self.fig)
        root.addWidget(self.canvas)

        self.statusLabel = QLabel('')
        self.statusLabel.setWordWrap(True)
        root.addWidget(self.statusLabel)

    def set_series(self, series_id, dates, values):
        """Feed one maturity series; redraw once new data has arrived."""
        self._data[series_id] = (dates, values)
        self._redraw()

    def _snapshot(self, days_ago):
        """(years, yields) as of `days_ago`, using the last obs on or before."""
        target = datetime.date.today() - datetime.timedelta(days=days_ago)
        xs, ys = [], []
        for sid, _lbl, years in YIELD_CURVE_SERIES:
            data = self._data.get(sid)
            if not data:
                continue
            dates, values = data
            i = bisect.bisect_right(dates, target) - 1
            if 0 <= i < len(values) and values[i] is not None \
                    and not math.isnan(values[i]):
                xs.append(years)
                ys.append(values[i])
        return xs, ys

    def _latest(self, series_id):
        data = self._data.get(series_id)
        return data[1][-1] if data and data[1] else None

    def _update_status(self):
        s2 = self._latest('DGS2')
        s10 = self._latest('DGS10')
        s3m = self._latest('DGS3MO')
        parts, inverted = [], False
        if s2 is not None and s10 is not None:
            sp = s10 - s2
            parts.append('2Y-10Y: {:+.2f}%'.format(sp))
            inverted = inverted or sp < 0
        if s3m is not None and s10 is not None:
            sp = s10 - s3m
            parts.append('3M-10Y: {:+.2f}%'.format(sp))
            inverted = inverted or sp < 0
        text = '    '.join(parts)
        if inverted:
            text += '  — ⚠ инверсия кривой: исторически риск рецессии'
            color = '#ef5350'
        else:
            color = _TXT
        self.statusLabel.setText(text)
        self.statusLabel.setStyleSheet(
            'color: {}; font-weight: bold;'.format(color))

    def _redraw(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(_BG)
        if not self._data:
            ax.text(0.5, 0.5, 'No data', ha='center', va='center',
                    color=_TXT, transform=ax.transAxes)
            ax.tick_params(colors=_TXT)
            for s in ax.spines.values():
                s.set_color(_GRID)
            self.canvas.draw()
            return

        today = datetime.date.today()
        offsets = _SNAP_SETS[self.snapCombo.currentIndex()][1]
        for idx, days in enumerate(offsets):
            xs, ys = self._snapshot(days)
            if not xs:
                continue
            ax.semilogx(xs, ys, marker='o', markersize=4,
                        color=_SNAP_COLORS[idx % len(_SNAP_COLORS)],
                        linestyle=_SNAP_STYLES[idx % len(_SNAP_STYLES)],
                        linewidth=1.8,
                        label=(today - datetime.timedelta(days=days)).isoformat())
        ax.set_xticks([y for _sid, _lbl, y in YIELD_CURVE_SERIES])
        ax.set_xticklabels([lbl for _sid, lbl, _y in YIELD_CURVE_SERIES])
        ax.set_xlabel('Maturity', color=_TXT)
        ax.set_ylabel('Yield (%)', color=_TXT)
        ax.grid(color=_GRID, linewidth=0.5, alpha=0.5, which='both')
        ax.tick_params(colors=_TXT)
        for s in ax.spines.values():
            s.set_color(_GRID)
        ax.set_title('US Treasury Yield Curve', color=_TXT)
        if len(offsets) > 1:
            ax.legend(facecolor=_BG, edgecolor=_GRID, labelcolor=_TXT)
        self.fig.tight_layout()
        self.canvas.draw()
        self._update_status()