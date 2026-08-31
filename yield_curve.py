# -*- coding: utf-8 -*-
"""US Treasury yield curve tab for the macro dashboard.

Daily Treasury Par Yield Curve Rates (FRED DGS3MO ... DGS30): each maturity is
a plain FRED daily series cached in the shared macro_cache.db by the MacroDialog
loader, so this module only builds the chart widget. The tab plots yield (%)
against the term (log-scaled years) and overlays historical snapshots so the
current curve's shape — steepening, flattening or inversion — is compared with
the recent past at a glance.

The lower panel plots the Near-Term Forward Spread (NTFS) of Engstrom & Sharpe
(the NY Fed's leading indicator): the 3-month rate expected in 18 months minus
the current 3-month rate. With the «Точки перегиба» checkbox on, meaningful
turning points of the NTFS are marked (green = top, risk-on; red = bottom,
risk-off). Together with the 10Y-3M spread exiting inversion and a fresh local
top in the Cleveland ex-ante real rate, the tab raises a "STRONG BUY" S&P 500
signal when the rule fires.
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
                               QComboBox, QCheckBox)

from pivots import pivot_indices

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

# STRONG BUY rule thresholds.
_NTFS_RISE_DAYS = 30             # lookback for "NTFS rising sharply"
_NTFS_RISE_THRESHOLD = 0.15      # +0.15% move in the window counts as sharp
_INVERSION_LOOKBACK = 45         # recent inversion window for the 10Y-3M spread
_REAL_PIVOT_RECENCY_DAYS = 120   # a real-rate turn counts if formed recently

# STRONG SELL rule thresholds.
_NTFS_HIGH_THRESHOLD = 0.50      # NTFS must be above +0.50%
_SPREAD_SETTLE_DAYS = 45         # base spread must stay positive this long

# Pivot parameters shared with the real-rate tab.
_PIVOT_KWARGS = dict(smooth_days=90, range_frac=0.25,
                     min_gap_days=120, local_days=730)


def _ntfs_value(par, cur_3m):
    """Near-term forward spread (Engstrom-Sharpe) from the par curve.

    par maps the bootstrap maturities (years) to par yields (%); cur_3m is the
    current 3-month T-bill yield (FRED DTB3, %). Bootstraps zero-coupon spot
    rates at 1Y/2Y from par bonds (semiannual coupons) plus the 6M bill,
    interpolates the 1.5Y/1.75Y spots and returns the 3-month forward rate
    starting in 18 months minus the current 3-month yield (in percent).
    """
    par = {t: v / 100.0 for t, v in par.items()}
    p6 = 1.0 / (1.0 + par[0.5] * 0.5)
    c1 = par[1.0] / 2.0
    p1 = (1.0 - c1 * p6) / (1.0 + c1)
    z1 = -math.log(p1) / 1.0
    c2 = par[2.0] / 2.0

    def price(z2):
        p2 = math.exp(-z2 * 2.0)
        p15 = math.exp(-((z1 + z2) / 2.0) * 1.5)
        return c2 * p6 + c2 * p1 + c2 * p15 + (1.0 + c2) * p2

    lo, hi = 0.0, 0.5
    for _ in range(120):
        mid = (lo + hi) / 2.0
        if price(mid) > 1.0:
            lo = mid
        else:
            hi = mid
    z2 = (lo + hi) / 2.0
    z15 = (z1 + z2) / 2.0
    z175 = z1 + (z2 - z1) * 0.75
    fwd = (1.75 * z175 - 1.5 * z15) / 0.25
    return (fwd - cur_3m / 100.0) * 100.0


def compute_ntfs_series(series):
    """(dates, values) of the NTFS over the DTB3 series' dates.

    `series` maps the FRED ids to their (dates, values): DTB3 (current 3M),
    DGS6MO, DGS1, DGS2 (par curve for the forward rate). Each date uses the
    last observation on or before it for every maturity, so the output is
    dense even though the inputs differ slightly in release days.
    """
    par_ids = ('DGS6MO', 'DGS1', 'DGS2')
    par_t = (0.5, 1.0, 2.0)
    if not all(sid in series for sid in ('DTB3',) + par_ids):
        return [], []
    out_d, out_v = [], []
    for d in series['DTB3'][0]:
        par, ok = {}, True
        for sid, t in zip(par_ids, par_t):
            dates, values = series[sid]
            i = bisect.bisect_right(dates, d) - 1
            if 0 <= i < len(values) and values[i] is not None:
                par[t] = values[i]
            else:
                ok = False
                break
        if not ok:
            continue
        dates, values = series['DTB3']
        i = bisect.bisect_right(dates, d) - 1
        if not (0 <= i < len(values) and values[i] is not None):
            continue
        out_d.append(d)
        out_v.append(_ntfs_value(par, values[i]))
    return out_d, out_v


class _YieldCurveTab(QWidget):
    """Term-structure chart + NTFS signal panel (yield curve tab)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series_ids = [sid for sid, _lbl, _years in YIELD_CURVE_SERIES]
        self._data = {}
        self._ntfs = None        # (dates, values) computed in the loader thread
        self._real_rate = None   # (dates, values) forwarded from the dialog

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel('US Treasury Constant Maturity Rates'))
        bar.addStretch(1)
        self.pivotCheck = QCheckBox('Точки перегиба')
        self.pivotCheck.setChecked(True)
        self.pivotCheck.setToolTip(
            'По NTFS (форвардный спред 3M через 18 мес): зелёный = локальный '
            'пик → BUY, красный = локальная впадина → SELL')
        self.pivotCheck.toggled.connect(lambda _c: self._redraw())
        bar.addWidget(self.pivotCheck)
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
            'наблюдаемые спреды. Нижний график — NTFS (Engstrom-Sharpe, ФРБ '
            'Нью-Йорка): ожидаемая через 18 мес 3-мес ставка минус текущая.')
        desc.setWordWrap(True)
        desc.setStyleSheet('color: #6a6d78; font-size: 11px;')
        root.addWidget(desc)

        self.fig = Figure(figsize=(9, 6), dpi=100)
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

    def set_ntfs(self, dates, values):
        """Feed the precomputed NTFS series (loaded in the background)."""
        self._ntfs = (dates, values)
        self._redraw()

    def set_real_rate(self, dates, values):
        """Feed the Cleveland ex-ante real rate for the STRONG BUY rule."""
        self._real_rate = (dates, values)
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

    def _spread_series(self, short_id, long_id):
        """(dates, values) of long-short spread aligned on the long series."""
        ds = self._data.get(short_id)
        dl = self._data.get(long_id)
        if not ds or not dl:
            return None, None
        dates_s, vals_s = ds
        dates_l, vals_l = dl
        dates, values, j = [], [], 0
        for i, d in enumerate(dates_l):
            while j + 1 < len(dates_s) and dates_s[j + 1] <= d:
                j += 1
            if j >= len(vals_s) or dates_s[j] > d \
                    or not vals_s[j] or not vals_l[i]:
                continue
            dates.append(d)
            values.append(vals_l[i] - vals_s[j])
        return dates, values

    def _compute_signal(self):
        """Evaluate the STRONG BUY/SELL rules. Returns (buy, sell, conditions)."""
        res = {'spread_exit': False, 'ntfs_rise': False, 'real_top': False,
               'ntfs_high': False, 'spread_positive': False, 'real_bottom': False}
        today = datetime.date.today()

        # STRONG BUY branch.
        dates, values = self._spread_series('DGS3MO', 'DGS10')
        if values:
            cutoff = dates[-1] - datetime.timedelta(days=_INVERSION_LOOKBACK)
            recent = [v for dd, v in zip(dates, values)
                      if dd >= cutoff and v is not None]
            if recent and min(recent) <= 0.0 and values[-1] > 0.0:
                res['spread_exit'] = True

        if self._ntfs and len(self._ntfs[1]) > 1:
            nd, nv = self._ntfs
            target = nd[-1] - datetime.timedelta(days=_NTFS_RISE_DAYS)
            i = bisect.bisect_right(nd, target) - 1
            if 0 <= i < len(nv) and nv[i] is not None and nv[-1] is not None \
                    and nv[-1] - nv[i] > _NTFS_RISE_THRESHOLD:
                res['ntfs_rise'] = True

        if self._real_rate and self._real_rate[0]:
            piv = pivot_indices(self._real_rate[1], self._real_rate[0],
                                **_PIVOT_KWARGS)
            if piv:
                last_idx, last_sign = piv[-1]
                last_date = self._real_rate[0][last_idx]
                if (today - last_date).days <= _REAL_PIVOT_RECENCY_DAYS:
                    if last_sign == -1:
                        res['real_top'] = True
                    elif last_sign == +1:
                        res['real_bottom'] = True

        buy = (res['spread_exit'] and res['ntfs_rise']) or res['real_top']

        # STRONG SELL branch: NTFS > +0.50%, base spread settled positive,
        # real rate made a local minimum and turns up (red marker).
        if self._ntfs and self._ntfs[1] and self._ntfs[1][-1] is not None \
                and self._ntfs[1][-1] > _NTFS_HIGH_THRESHOLD:
            res['ntfs_high'] = True
        for short_id in ('DGS3MO', 'DGS2'):
            sd, sv = self._spread_series(short_id, 'DGS10')
            if sv:
                cutoff = sd[-1] - datetime.timedelta(days=_SPREAD_SETTLE_DAYS)
                recent = [v for dd, v in zip(sd, sv)
                          if dd >= cutoff and v is not None]
                if recent and min(recent) > 0.0:
                    res['spread_positive'] = True
                    break
        sell = (res['ntfs_high'] and res['spread_positive']
                and res['real_bottom'])

        return buy, sell, res

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
        if self._ntfs and self._ntfs[1] and self._ntfs[1][-1] is not None:
            parts.append('NTFS: {:+.2f}%'.format(self._ntfs[1][-1]))

        strong_buy, strong_sell, res = self._compute_signal()
        lines = ['    '.join(parts)]
        if strong_buy:
            reason = ('спред 10Y-3M вышел из инверсии и NTFS резко растёт'
                      if res['spread_exit'] and res['ntfs_rise']
                      else 'локальный пик реальной ставки (зелёный маркер)')
            lines.append('STRONG BUY для S&P 500: {}'.format(reason))
            color = '#81c784'
        elif strong_sell:
            reason = ('NTFS выше +0.50%, базовый спред в плюсе, реальная '
                      'ставка развернулась вверх (красный маркер)')
            lines.append('STRONG SELL для S&P 500: {}'.format(reason))
            color = '#ef5350'
        elif inverted:
            lines.append('Инверсия кривой — исторически риск рецессии')
            color = '#ef5350'
        else:
            color = _TXT
        self.statusLabel.setText('\n'.join(lines))
        self.statusLabel.setStyleSheet(
            'color: {}; font-weight: bold;'.format(color))

    def _redraw(self):
        self.fig.clear()
        has_ntfs = bool(self._ntfs and self._ntfs[0])
        ax = self.fig.add_subplot(211 if has_ntfs else 111)
        ax.set_facecolor(_BG)
        self._draw_curve(ax)
        if has_ntfs:
            ax2 = self.fig.add_subplot(212)
            ax2.set_facecolor(_BG)
            self._draw_ntfs(ax2)
        self.fig.tight_layout()
        self.canvas.draw()
        self._update_status()

    def _draw_curve(self, ax):
        if not self._data:
            ax.text(0.5, 0.5, 'No data', ha='center', va='center',
                    color=_TXT, transform=ax.transAxes)
            ax.tick_params(colors=_TXT)
            for s in ax.spines.values():
                s.set_color(_GRID)
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
            ax.legend(facecolor=_BG, edgecolor=_GRID, labelcolor=_TXT,
                      fontsize=8)

    def _draw_ntfs(self, ax):
        import matplotlib.dates as mdates
        dates, values = self._ntfs
        x = mdates.date2num([datetime.datetime.combine(d, datetime.time())
                             for d in dates])
        y = np.asarray(values, dtype=float)
        ax.plot(x, y, color='#90caf9', linewidth=1.3)
        ax.axhline(0, color=_GRID, linewidth=0.8)
        if self.pivotCheck.isChecked():
            for i, sign in pivot_indices(values, dates, **_PIVOT_KWARGS):
                color = '#81c784' if sign < 0 else '#ef5350'
                ax.scatter(x[i], y[i], s=26, facecolors='none',
                           edgecolors=color, linewidths=1.4, zorder=3)
        if len(x):
            xlo = mdates.date2num(datetime.date.today() -
                                  datetime.timedelta(days=4 * 365))
            ax.set_xlim(xlo, float(x[-1]))
        loc = AutoDateLocator(minticks=4, maxticks=9)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(ConciseDateFormatter(loc))
        ax.tick_params(axis='x', labelsize=8)
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(30)
            lbl.set_ha('right')
        ax.grid(color=_GRID, linewidth=0.5, alpha=0.5)
        ax.set_ylabel('NTFS (%)', color=_TXT)
        ax.tick_params(colors=_TXT)
        for s in ax.spines.values():
            s.set_color(_GRID)
        ax.set_title('NTFS: 3M через 18 мес − текущая 3M (Engstrom-Sharpe)',
                     color=_TXT, fontsize=9)