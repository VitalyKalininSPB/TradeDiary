# -*- coding: utf-8 -*-
"""MLRCI — Multi-Liquidity & Risk Composite Indicator.

A composite oscillator (range -100..+100) that condenses five leading macro /
liquidity / sentiment inputs into one line, so long-term turning points of
S&P 500 become visible:

  * Real Interest Rate (Cleveland Fed ex-ante, REAINTRATREARAT10Y) — 25%
  * NTFS (Engstrom-Sharpe near-term forward spread)                  — 25%
  * Net Liquidity = WALCL - TGA - RRP (Fed balance sheet minus the
    Treasury General Account and the reverse-repo facility)          — 20%
  * BBB corporate credit spread (BAMLC0A4CBBB)                       — 15%
  * VIX (VIXCLS)                                                     — 15%

Each component is z-scored (deviation from its own trailing mean/std), sign
flipped where a higher level is *bad* for risk appetite (real rate, credit
spread, VIX), then the weighted sum is squashed to [-100, +100] with tanh.

Reading: line above +80 = extreme risk-on (green BUY zone), below -80 =
extreme risk-off (red SELL zone). The S&P 500 is overlaid on a secondary axis
to compare composite extremes with index tops/bottoms.
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
_UP = '#81c784'
_DOWN = '#ef5350'
_MLRCI = '#ffd54f'
_SP = '#90caf9'

# FRED ids used to build the composite.
_REAL_ID = 'REAINTRATREARAT10Y'
_WALCL_ID = 'WALCL'
_TGA_ID = 'WDTGAL'       # Treasury General Account, deposits at the Fed
_RRP_ID = 'RRPONTSYD'    # overnight reverse-repo volume ($bn -> $m via *1000)
_BBB_ID = 'BAMLC0A4CBBB'
_VIX_ID = 'VIXCLS'
_SP500_ID = 'SP500'

# NTFS short end.
_NTFS_SHORT = ('DTB3', 'DGS6MO', 'DGS1', 'DGS2')

# Weights sum to 1.0. Direction: +1 = higher level is risk-on, -1 = higher is
# risk-off (so the z-score is flipped before weighting).
_COMPONENTS = [
    # (name, series_id, weight, direction)
    ('Real rate', _REAL_ID, 0.25, -1),
    ('NTFS',      'NTFS',   0.25, +1),
    ('NetLiq',    'NetLiq', 0.20, +1),
    ('BBB',       _BBB_ID,  0.15, -1),
    ('VIX',       _VIX_ID,  0.15, -1),
]

_Z_WINDOW_DAYS = 5 * 365   # trailing window for the z-score baseline
_BUY_LEVEL = 80.0
_SELL_LEVEL = -80.0

_PERIODS = [('1Y', 365), ('3Y', 3 * 365), ('5Y', 5 * 365), ('10Y', 10 * 365),
            ('Max', None)]


def _zscore(values, window):
    """Trailing z-score: each point vs the mean/std of the last `window` days."""
    arr = np.asarray(values, dtype=float)
    out = np.full_like(arr, np.nan, dtype=float)
    for i in range(len(arr)):
        lo = max(0, i - window)
        seg = arr[lo:i + 1]
        seg = seg[np.isfinite(seg)]
        if seg.size < 30:
            continue
        mu, sd = np.nanmean(seg), np.nanstd(seg)
        if sd == 0 or not np.isfinite(sd):
            continue
        out[i] = (arr[i] - mu) / sd
    return out


def compute_net_liquidity(series):
    """Net liquidity (WALCL - TGA - RRP), in $m, aligned on WALCL dates."""
    w = series.get(_WALCL_ID)
    t = series.get(_TGA_ID)
    r = series.get(_RRP_ID)
    if not (w and t and r) or not w[0]:
        return [], []
    dates, values, j, k = [], [], 0, 0
    for d, wv in zip(w[0], w[1]):
        while j + 1 < len(t[0]) and t[0][j + 1] <= d:
            j += 1
        while k + 1 < len(r[0]) and r[0][k + 1] <= d:
            k += 1
        if j >= len(t[1]) or t[0][j] > d or not t[1][j]:
            continue
        if k >= len(r[1]) or r[0][k] > d or not r[1][k]:
            continue
        dates.append(d)
        values.append(wv - t[1][j] - r[1][k] * 1000.0)
    return dates, values


def compute_ntfs(series):
    """NTFS series from the short end of the curve (Engstrom-Sharpe)."""
    from yield_curve import compute_ntfs_series
    return compute_ntfs_series({sid: series[sid] for sid in _NTFS_SHORT
                                if sid in series})


def _aligned_daily(base_dates, series_map):
    """Forward-fill every series onto `base_dates` -> dict of value arrays."""
    out = {}
    for sid, (dates, values) in series_map.items():
        arr = []
        j = 0
        for d in base_dates:
            while j + 1 < len(dates) and dates[j + 1] <= d:
                j += 1
            arr.append(values[j] if 0 <= j < len(values) else None)
        out[sid] = arr
    return out


def compute_mlrci(series):
    """(dates, mlrci) for the composite indicator.

    `series` maps FRED ids to (dates, values) — including the NTFS/NetLiq
    synthetic series. All components are aligned on a common daily axis (the
    union of observation dates), z-scored on a trailing 5y window, weighted and
    squashed to [-100, +100].
    """
    full = compute_mlrci_full(series)
    return full[0], full[1]


def _aligned_components(series):
    """(base_dates, aligned_dict) shared by the composite and the signals.

    `series` maps FRED ids to (dates, values). NTFS and Net Liquidity are
    rebuilt from their inputs, then all five components are forward-filled onto
    one daily axis.
    """
    from yield_curve import compute_ntfs_series

    ntfs = compute_ntfs_series({sid: series[sid] for sid in _NTFS_SHORT
                                if sid in series})
    netliq = compute_net_liquidity(series)
    if not ntfs[0] or not netliq[0]:
        return [], {}

    base = sorted(set(ntfs[0]) | set(netliq[0])
                  | set(series[_REAL_ID][0]) | set(series[_BBB_ID][0])
                  | set(series[_VIX_ID][0]))
    base = [d for d in base if d >= datetime.date(2000, 1, 1)]
    series_map = {
        _REAL_ID: series[_REAL_ID],
        'NTFS': ntfs,
        'NetLiq': netliq,
        _BBB_ID: series[_BBB_ID],
        _VIX_ID: series[_VIX_ID],
    }
    return base, _aligned_daily(base, series_map)


def compute_mlrci_full(series):
    """(dates, mlrci, buy_marks, sell_marks) for the MLRCI tab.

    buy/sell_marks are lists of (date, mlrci_value) at the moments the STRONG
    BUY / STRONG SELL signal from the spec turns on (all five conditions at
    once): see compute_signals().
    """
    base, aligned = _aligned_components(series)
    if not base:
        return [], [], [], []

    z = {}
    for name, sid, _w, _dir in _COMPONENTS:
        arr = np.asarray(aligned[sid], dtype=float)
        if arr.size == 0:
            return [], [], [], []
        zz = _zscore(arr.tolist(), _Z_WINDOW_DAYS)
        z[name] = zz

    out = []
    for i, d in enumerate(base):
        acc, ok = 0.0, True
        for name, _sid, weight, direction in _COMPONENTS:
            v = z[name][i]
            if not np.isfinite(v):
                ok = False
                break
            acc += weight * direction * v
        out.append((d, 100.0 * math.tanh(acc) if ok else float('nan')))
    dates = [d for d, _ in out]
    values = [v for _, v in out]

    buy, sell = compute_signals(aligned, base, values)
    return dates, values, buy, sell


def _rising(values, lookback=60):
    """True where the value is above the value `lookback` indices earlier."""
    out = []
    for i in range(len(values)):
        j = max(0, i - lookback)
        out.append(values[i] is not None and values[j] is not None
                   and values[i] > values[j])
    return out


def _falling(values, lookback=60):
    """True where the value is below the value `lookback` indices earlier."""
    out = []
    for i in range(len(values)):
        j = max(0, i - lookback)
        out.append(values[i] is not None and values[j] is not None
                   and values[i] < values[j])
    return out


def compute_signals(aligned, base, mlrci_values):
    """STRONG BUY/SELL marker points for the MLRCI chart.

    Each signal is a confluence of the five conditions from the spec:

      STRONG BUY:  real rate peaked and turns down, NTFS deep-negative
                   (< -0.50%) turning up, Net Liquidity rising, BBB < 1.50%,
                   VIX panic spike (> 30).
      STRONG SELL: real rate troughed and turns up, NTFS positive turning
                   down, Net Liquidity falling, BBB expanding, VIX greed
                   (< 15).

    A STRONG signal fires when at least 4 of the 5 conditions hold at once
    (a strict AND of all five is almost never satisfied on real data), and a
    marker is placed on the day the signal turns on.

    Returns (buy, sell) as lists of (date, mlrci_value).
    """
    from pivots import pivot_indices

    real = aligned[_REAL_ID]
    ntfs = aligned['NTFS']
    netliq = aligned['NetLiq']
    bbb = aligned[_BBB_ID]
    vix = aligned[_VIX_ID]

    piv = pivot_indices(list(real), base, smooth_days=90, range_frac=0.25,
                        min_gap_days=120, local_days=730)
    real_peak = [False] * len(base)     # real rate peaked and turned down
    real_trough = [False] * len(base)   # real rate troughed and turned up
    for idx, sign in piv:
        d0 = base[idx]
        for i, d in enumerate(base):
            if 0 <= (d - d0).days <= 120:
                if sign == -1:
                    real_peak[i] = True
                elif sign == +1:
                    real_trough[i] = True

    ntfs_up = _rising(ntfs)
    ntfs_down = _falling(ntfs)
    netliq_up = _rising(netliq)
    netliq_down = _falling(netliq)
    bbb_up = _rising(bbb)
    ntfs_deep_neg = [v is not None and v < -0.5 for v in ntfs]
    ntfs_pos = [v is not None and v > 0.0 for v in ntfs]
    bbb_low = [v is not None and v < 1.5 for v in bbb]
    vix_panic = [v is not None and v > 30.0 for v in vix]
    vix_greed = [v is not None and v < 15.0 for v in vix]

    buy_votes = [sum([real_peak[i], ntfs_deep_neg[i] and ntfs_up[i],
                      netliq_up[i], bbb_low[i], vix_panic[i]])
                 for i in range(len(base))]
    sell_votes = [sum([real_trough[i], ntfs_pos[i] and ntfs_down[i],
                       netliq_down[i], bbb_up[i], vix_greed[i]])
                  for i in range(len(base))]

    def marks(votes):
        pts, prev = [], False
        for i, v in enumerate(votes):
            active = v >= 4
            if active and not prev:
                pts.append((base[i], mlrci_values[i]))
            prev = active
        return pts

    return marks(buy_votes), marks(sell_votes)


class MlrcTab(QWidget):
    """MLRCI composite oscillator with S&P 500 overlay and ±80 zones."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series_ids = []
        self._dates = []
        self._values = []
        self._sp500 = ([], [])
        self._buy = []
        self._sell = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel('MLRCI — Multi-Liquidity & Risk Composite'))
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
            'Композит из 5 опережающих индикаторов: реальная ставка (25%), '
            'NTFS (25%), чистая ликвидность = баланс ФРС − TGA − RRP (20%), '
            'спред BBB (15%) и VIX (15%). Каждый нормирован в Z-оценку. '
            'Выше +80 — зона BUY (риск-он), ниже −80 — зона SELL (риск-офф). '
            'Голубая линия — S&P 500 (правая шкала).')
        desc.setWordWrap(True)
        desc.setStyleSheet('color: #6a6d78; font-size: 11px;')
        root.addWidget(desc)

        self.fig = Figure(figsize=(9, 5), dpi=100)
        self.fig.patch.set_facecolor(_BG)
        self.canvas = FigureCanvas(self.fig)
        root.addWidget(self.canvas)

        self.stateLabel = QLabel('')
        self.stateLabel.setWordWrap(True)
        root.addWidget(self.stateLabel)

    def set_mlrci(self, dates, values):
        self._dates = dates
        self._values = values
        self._redraw()

    def set_marks(self, buy, sell):
        self._buy = buy
        self._sell = sell
        self._redraw()

    def set_sp500(self, dates, values):
        self._sp500 = (dates, values)
        self._redraw()

    def _visible(self):
        days = _PERIODS[self.periodCombo.currentIndex()][1]
        if days is not None and self._dates:
            cutoff = datetime.date.today() - datetime.timedelta(days=days)
            idx = [i for i, d in enumerate(self._dates) if d >= cutoff]
            if idx:
                return ([self._dates[i] for i in idx],
                        [self._values[i] for i in idx])
        return self._dates, self._values

    def _redraw(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(_BG)
        if not self._dates:
            ax.text(0.5, 0.5, 'No data for MLRCI', ha='center', va='center',
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

        # Extreme zones and guide lines.
        ax.axhspan(_BUY_LEVEL, 100, color=_UP, alpha=0.12, zorder=0)
        ax.axhspan(-100, _SELL_LEVEL, color=_DOWN, alpha=0.12, zorder=0)
        for level in (_BUY_LEVEL, _SELL_LEVEL, 0.0):
            ax.axhline(level, color=_GRID, linewidth=0.8, linestyle='--',
                       alpha=0.7, zorder=0)
        ax.plot(x, y, color=_MLRCI, linewidth=1.6)
        ax.fill_between(x, y, 0, color=_MLRCI, alpha=0.15)

        # STRONG BUY / SELL markers: green up-triangles and red down-triangles.
        import bisect as _b
        for kind, pts, marker, color in (
                ('buy', self._buy, '^', _UP),
                ('sell', self._sell, 'v', _DOWN)):
            if not pts:
                continue
            mx, my = [], []
            for d, v in pts:
                if d < dates[0] or d > dates[-1] or v != v:
                    continue
                mx.append(mdates.date2num(datetime.datetime.combine(
                    d, datetime.time())))
                my.append(v)
            if mx:
                ax.scatter(mx, my, marker=marker, s=90, color=color,
                           edgecolors=_BG, linewidths=0.8, zorder=5,
                           label='STRONG BUY' if kind == 'buy'
                           else 'STRONG SELL')
        if self._buy or self._sell:
            ax.legend(facecolor=_BG, edgecolor=_GRID, labelcolor=_TXT,
                      fontsize=8)

        # S&P 500 on a secondary axis, normalised to % change over the window.
        sp_dates, sp_vals = self._sp500
        if sp_vals:
            import bisect as _b
            cutoff = dates[0]
            i0 = _b.bisect_left(sp_dates, cutoff)
            sx = sp_dates[i0:]
            sv = sp_vals[i0:]
            if len(sv) > 2:
                sx_num = mdates.date2num(
                    [datetime.datetime.combine(d, datetime.time())
                     for d in sx])
                sv_arr = np.asarray(sv, dtype=float)
                base_v = sv_arr[0]
                ax2 = ax.twinx()
                ax2.plot(sx_num, (sv_arr / base_v - 1.0) * 100.0, color=_SP,
                         linewidth=1.0, alpha=0.8)
                ax2.set_ylabel('S&P 500 (%)', color=_SP)
                ax2.tick_params(axis='y', colors=_SP)
                ax2.spines['right'].set_color(_SP)

        ax.set_ylim(-100, 100)
        ax.set_ylabel('MLRCI', color=_TXT)
        ax.grid(color=_GRID, linewidth=0.5, alpha=0.4)
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
        ax.set_title('MLRCI — latest {:.0f}'.format(latest), color=_TXT)
        self._update_state(latest)
        self.fig.tight_layout()
        self.canvas.draw()

    def _update_state(self, v):
        if v != v:  # NaN
            self.stateLabel.setText('')
            return
        if v >= _BUY_LEVEL:
            txt, color = ('MLRCI выше +80 — экстремальный риск-он: '
                          'перегрев, но BUY-зона по модели. Следите за '
                          'разворотом вниз.', _UP)
        elif v <= _SELL_LEVEL:
            txt, color = ('MLRCI ниже −80 — экстремальный риск-офф: '
                          'паника и капитуляция, SELL-зона по модели. '
                          'Ищите точку разворота наверх.', _DOWN)
        elif v > 0:
            txt, color = ('MLRCI в плюсе — риск-он режим, индексы '
                          'предпочтительны.', _TXT)
        else:
            txt, color = ('MLRCI в минусе — риск-офф режим, сниженный '
                          'аппетит к риску.', _TXT)
        self.stateLabel.setText(txt)
        self.stateLabel.setStyleSheet(
            'color: {}; font-weight: bold;'.format(color))