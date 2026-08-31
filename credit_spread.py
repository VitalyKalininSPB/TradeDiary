# -*- coding: utf-8 -*-
"""Corporate credit yield vs the 10-year Treasury benchmark.

A single tab for the macro dashboard: the ICE BofA BBB corporate effective
yield (BAMLC0A4CBBBEY) plotted together with the 10Y constant-maturity
Treasury yield (DGS10), so both the absolute yield level and the spread
between the two (the shaded gap) are visible at a glance. Both series are
plain FRED daily series cached in the shared macro_cache.db by the MacroDialog
loader, so this module only builds the chart widget.
"""
import bisect
import datetime
import math

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
_BBB = '#e57373'
_T10 = '#90caf9'

# (FRED series_id, plot label, color).
CREDIT_SERIES = [
    ('BAMLC0A4CBBBEY', 'BBB corporate yield', _BBB),
    ('DGS10', '10Y Treasury', _T10),
]

# Period presets: name -> days back.
_PERIODS = [('6M', 182), ('1Y', 365), ('3Y', 3 * 365), ('Max', None)]


class CreditSpreadTab(QWidget):
    """Corporate BBB yield vs 10Y Treasury, with the spread shaded."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series_ids = [sid for sid, _lbl, _c in CREDIT_SERIES]
        self._data = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel('ICE BofA BBB yield vs 10Y Treasury'))
        bar.addStretch(1)
        bar.addWidget(QLabel('Period:'))
        self.periodCombo = QComboBox()
        for name, _days in _PERIODS:
            self.periodCombo.addItem(name)
        self.periodCombo.setCurrentIndex(3)
        self.periodCombo.currentIndexChanged.connect(lambda _i: self._redraw())
        bar.addWidget(self.periodCombo)
        root.addLayout(bar)

        desc = QLabel(
            'Доходность корпоративных облигаций класса BBB (ICE BofA) и '
            '10-летних казначейских облигаций США. Зазор между линиями — '
            'кредитный спред: чем шире, тем выше кредитный риск и тем '
            'больше рынок сомневается в надёжных компаниях.')
        desc.setWordWrap(True)
        desc.setStyleSheet('color: #6a6d78; font-size: 11px;')
        root.addWidget(desc)

        self.fig = Figure(figsize=(9, 5), dpi=100)
        self.fig.patch.set_facecolor(_BG)
        self.canvas = FigureCanvas(self.fig)
        root.addWidget(self.canvas)

        self.spreadLabel = QLabel('')
        self.spreadLabel.setStyleSheet('color: {}; font-weight: bold;'
                                       .format(_TXT))
        root.addWidget(self.spreadLabel)

    def set_series(self, series_id, dates, values):
        """Feed one series; redraw once data has arrived."""
        self._data[series_id] = (dates, values)
        self._redraw()

    def _latest(self, series_id):
        data = self._data.get(series_id)
        return data[1][-1] if data and data[1] else None

    def _visible(self):
        """(sid, dates, values) restricted to the selected period."""
        days = _PERIODS[self.periodCombo.currentIndex()][1]
        out = []
        for sid, _lbl, _c in CREDIT_SERIES:
            data = self._data.get(sid)
            if not data or not data[0]:
                out.append((sid, [], []))
                continue
            dates, values = data
            if days is not None:
                cutoff = datetime.date.today() - datetime.timedelta(days=days)
                idx = [i for i, d in enumerate(dates) if d >= cutoff]
                if idx:
                    dates = [dates[i] for i in idx]
                    values = [values[i] for i in idx]
            out.append((sid, dates, values))
        return out

    def _aligned(self):
        """(dates, bbb, t10) aligned on the Treasury dates via bisect."""
        t10 = self._data.get('DGS10')
        bbb = self._data.get('BAMLC0A4CBBBEY')
        if not t10 or not bbb:
            return [], [], []
        d10, v10 = t10
        db, vb = bbb
        dates, b, t = [], [], []
        j = 0
        for i, d in enumerate(d10):
            while j + 1 < len(db) and db[j + 1] <= d:
                j += 1
            if j >= len(vb) or db[j] > d or not vb[j] or not v10[i]:
                continue
            dates.append(d)
            b.append(vb[j])
            t.append(v10[i])
        return dates, b, t

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

        import matplotlib.dates as mdates
        dates, b, t = self._aligned()
        if dates:
            x = mdates.date2num([datetime.datetime.combine(d, datetime.time())
                                 for d in dates])
            b = np.asarray(b, dtype=float)
            t = np.asarray(t, dtype=float)
            ax.plot(x, t, color=_T10, linewidth=1.6, label='10Y Treasury')
            ax.plot(x, b, color=_BBB, linewidth=1.6, label='BBB yield')
            ax.fill_between(x, t, b, color=_BBB, alpha=0.12)
        ax.grid(color=_GRID, linewidth=0.5, alpha=0.5)
        ax.set_ylabel('Yield (%)', color=_TXT)
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

        bbb = self._latest('BAMLC0A4CBBBEY')
        t10 = self._latest('DGS10')
        if bbb is not None and t10 is not None:
            sp = bbb - t10
            ax.set_title('BBB yield {:.2f}% vs 10Y {:.2f}% (spread {:.2f}%)'
                         .format(bbb, t10, sp), color=_TXT)
            color = '#ef5350' if sp > 2.0 else _TXT
            self.spreadLabel.setText(
                'Кредитный спред BBB−10Y: {:.2f}%'.format(sp))
            self.spreadLabel.setStyleSheet(
                'color: {}; font-weight: bold;'.format(color))
        elif bbb is not None:
            ax.set_title('BBB yield {:.2f}%'.format(bbb), color=_TXT)
        if dates:
            ax.legend(facecolor=_BG, edgecolor=_GRID, labelcolor=_TXT)
        self.fig.tight_layout()
        self.canvas.draw()