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
                               QLabel, QComboBox, QTableWidget,
                               QTableWidgetItem, QHeaderView, QSpinBox)
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


def _sma(prices, window):
    return _smooth(prices, prices, window)


def _min_change(prices, i, horizon):
    """Min price change (%) over `horizon` trading days after index i."""
    hi = min(i + horizon, len(prices) - 1)
    window = prices[i:hi + 1]
    return window.min() / prices[i] - 1.0


def analyze_death_crosses(dates, prices, horizons=(5, 10, 20, 50),
                          thresholds=(0.02, 0.03, 0.05, 0.10),
                          short=SHORT_MA, long=LONG_MA):
    """Measure how often a death cross 'came true' for a ticker series.

    A death cross is the close of the day where SHORT crosses below LONG.
    It counts as fulfilled if price dropped by >= threshold within `horizon`
    trading days. Crosses too close to the series end (no full horizon ahead)
    are excluded from the hit rate.
    Returns dict with death indices, a (horizon, threshold) grid, and details
    for the primary (20d / -3%) variant.
    """
    ma_s = _sma(prices, short)
    ma_l = _sma(prices, long)
    deaths = _crosses(ma_s, ma_l)[0]
    n = len(prices)
    last = n - 1

    grid = {}
    for h in horizons:
        for t in thresholds:
            valid = [i for i in deaths if i + h <= last]
            hits = sum(1 for i in valid if _min_change(prices, i, h) <= -t)
            grid[(h, t)] = (hits, len(valid))

    primary_h, primary_t = horizons[2], thresholds[1]  # 20d / 3%
    details = []
    for i in deaths:
        if i + primary_h > last:
            details.append((dates[i], prices[i], None, False, 'short'))
            continue
        chg = _min_change(prices, i, primary_h)
        details.append((dates[i], prices[i], chg, chg <= -primary_t, 'ok'))

    return {'death_indices': deaths, 'grid': grid, 'details': details,
            'primary': (primary_h, primary_t)}


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
        self.analyzeBtn = QPushButton('Анализ крестов смерти')
        self.analyzeBtn.setToolTip('Статистика: как часто крест смерти подтверждался падением цены')
        self.analyzeBtn.clicked.connect(self._show_death_analysis)
        bar.addWidget(self.analyzeBtn)
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

    def _show_death_analysis(self):
        dates = [d for d, _ in self.series]
        prices = np.array([p for _, p in self.series], dtype=float)
        if len(prices) <= max(SHORT_MA, LONG_MA):
            self.hintLabel.setText('Слишком мало данных для анализа')
            return
        res = analyze_death_crosses(dates, prices)
        dlg = DeathCrossDialog(self.ticker, dates, prices, res, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._analysis_dlg = dlg
        dlg.show()

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


_HORIZONS = (5, 10, 20, 50)
_THRESHOLDS = (0.02, 0.03, 0.05, 0.10)


class DeathCrossDialog(QDialog):
    """Report: how often the death cross (SMA20<SMA50) came true for a ticker."""

    def __init__(self, ticker, dates, prices, res, parent=None):
        super().__init__(parent)
        self.ticker = ticker or ''
        self.dates = dates
        self.prices = prices
        self.res = res
        self.setWindowTitle('Анализ крестов смерти — {}'.format(self.ticker))
        self.resize(860, 640)
        self.setStyleSheet(
            'QDialog, QLabel, QSpinBox, QTableWidget {{ color: {t}; background: {b}; }} '
            'QSpinBox {{ color: {t}; background: {g}; border: 1px solid {gr}; }}'
            .format(t=_TXT, b=_BG, g=_GRID, gr=_GRID))

        layout = QVBoxLayout(self)

        head = QHBoxLayout()
        head.addWidget(QLabel('Основной вариант: горизонт'))
        self.hSpin = QSpinBox()
        self.hSpin.setRange(1, 250)
        self.hSpin.setValue(res['primary'][0])
        head.addWidget(self.hSpin)
        head.addWidget(QLabel('дней, спад >='))
        self.tSpin = QSpinBox()
        self.tSpin.setSuffix(' %')
        self.tSpin.setRange(1, 100)
        self.tSpin.setValue(int(res['primary'][1] * 100))
        head.addWidget(self.tSpin)
        self.recalcBtn = QPushButton('Пересчитать')
        self.recalcBtn.clicked.connect(self._recalc)
        head.addWidget(self.recalcBtn)
        head.addStretch(1)
        layout.addLayout(head)

        gridLabel = QLabel('Доля сбывшихся крестов смерти (падавшая цена в течение горизонта):')
        layout.addWidget(gridLabel)
        layout.addWidget(self._build_grid())

        detLabel = QLabel('Детали (основной вариант):')
        layout.addWidget(detLabel)
        layout.addWidget(self._build_details())

        self.totalLabel = QLabel('')
        layout.addWidget(self.totalLabel)

        self._refresh_details()

    def _build_grid(self):
        tab = QTableWidget()
        tab.setColumnCount(len(_THRESHOLDS) + 1)
        tab.setHorizontalHeaderLabels(
            ['Горизонт'] + ['-{}%'.format(int(t * 100)) for t in _THRESHOLDS])
        tab.setRowCount(len(_HORIZONS))
        for r, h in enumerate(_HORIZONS):
            item = QTableWidgetItem('{} дн'.format(h))
            item.setForeground(Qt.GlobalColor.white)
            tab.setItem(r, 0, item)
            for c, th in enumerate(_THRESHOLDS):
                hits, total = self.res['grid'][(h, th)]
                pct = (hits / total * 100) if total else 0
                cell = QTableWidgetItem('{}/{} = {}%'.format(hits, total, round(pct)))
                ok = pct >= 70 and total > 0
                cell.setForeground(Qt.GlobalColor.darkGreen if ok
                                   else Qt.GlobalColor.red)
                tab.setItem(r, c + 1, cell)
        tab.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tab.verticalHeader().setVisible(False)
        tab.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tab.setMaximumHeight(140)
        return tab

    def _build_details(self):
        self.detailsTab = QTableWidget()
        self.detailsTab.setColumnCount(4)
        self.detailsTab.setHorizontalHeaderLabels(
            ['Дата', 'Цена на сигнале', 'Мин. изменение %', 'Статус'])
        self.detailsTab.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.detailsTab.verticalHeader().setVisible(False)
        self.detailsTab.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.detailsTab.setMaximumHeight(230)
        return self.detailsTab

    def _refresh_details(self):
        h, th = self.res['primary']
        self.detailsTab.setRowCount(len(self.res['details']))
        hits = nvalid = 0
        for r, (date, close, min_chg, fulfilled, kind) in enumerate(self.res['details']):
            self.detailsTab.setItem(r, 0, QTableWidgetItem(date))
            self.detailsTab.setItem(r, 1, QTableWidgetItem('{:.2f}'.format(close)))
            if min_chg is None:
                self.detailsTab.setItem(r, 2, QTableWidgetItem('нет данных'))
                self.detailsTab.setItem(
                    r, 3, QTableWidgetItem('нет {} дн впереди'.format(h)))
            else:
                chg_item = QTableWidgetItem('{:+.1f}%'.format(min_chg * 100))
                chg_item.setForeground(Qt.GlobalColor.darkGreen if fulfilled
                                       else Qt.GlobalColor.red)
                self.detailsTab.setItem(r, 2, chg_item)
                status_item = QTableWidgetItem('СБЫЛСЯ' if fulfilled else 'нет')
                status_item.setForeground(Qt.GlobalColor.darkGreen if fulfilled
                                          else Qt.GlobalColor.red)
                self.detailsTab.setItem(r, 3, status_item)
                if fulfilled:
                    hits += 1
                nvalid += 1
        pct = (hits / nvalid * 100) if nvalid else 0
        self.totalLabel.setText(
            'Итог: крестов смерти {} шт, сбывшихся {}/{} = {}% '
            '(горизонт {} дн, спад >= {}%).'.format(
                len(self.res['details']), hits, nvalid, round(pct), h, int(th * 100)))
        return pct

    def _recalc(self):
        h = self.hSpin.value()
        th = self.tSpin.value() / 100.0
        res = analyze_death_crosses(self.dates, self.prices,
                                    horizons=(h,), thresholds=(th,))
        self.res['details'] = res['details']
        self.res['primary'] = (h, th)
        self._refresh_details()
