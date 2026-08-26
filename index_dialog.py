# -*- coding: utf-8 -*-
"""US index dashboard: S&P 500 and NASDAQ 100 charts.

Reuses the FRED fetch + SQLite cache machinery from macro_dialog, so the same
macro_cache.db stores both the macro indicators and the two index series.
"""
import datetime
import os

import numpy as np
import requests

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QLabel, QApplication, QSizePolicy)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from macro_dialog import _IndicatorTab, _fred, _load_cached, _save_cached

_TXT = '#dcdce0'

_REGIME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logos')
_SMA_WINDOW = 200
_REGIME_BAND = 0.02  # neutral zone around the SMA before flipping to bull/bear

# Series entries: (id, tab title, plot label, y-label, color, ru description).
# SP500/NASDAQ100 come from FRED; DAX is not on FRED, so it is fetched from
# Yahoo Finance (still cached in the same macro_cache.db).
INDICES = [
    ('NASDAQ100', 'NASDAQ 100 (NASDAQ100)', 'NASDAQ 100',
                 'Index',                 '#80a9ff',
                 'Индекс технологического сектора — рост технологических лидеров'),
    ('SP500',     'S&P 500 (SP500)',      'S&P 500',
                 'Index',                 '#90caf9',
                 'Индекс широкого американского рынка — барометр аппетита к риску'),
    ('DAX',       'DAX (DAX)',            'DAX',
                 'Index',                 '#a5d6a7',
                 'Немецкий индекс голубых фишек — европейский барометр рынка'),
]

# Yahoo symbols for the non-FRED series: series_id -> (yahoo symbol, range).
_YAHOO_SYMBOLS = {
    'DAX': ('^GDAXI', '25y'),
}

# Static hint under the NASDAQ 100 and S&P 500 charts: which index tends to lead
# the other at trend reversals, and by how many weeks.
# TODO(авто): считать «кто опережает на разворотах» и среднее опережение в
# неделях по данным (детекция локальных экстремумов + сопоставление пиков/впадин
# двух серий), а не использовать статичный текст.
_LEAD_SERIES = ('NASDAQ100', 'SP500')
_LEAD_HINT = (
    'NASDAQ 100 обычно опережает S&P 500 на разворотах вниз: вершину формирует '
    'раньше, чем S&P, — в среднем примерно на 2–3 недели. На разворотах вверх '
    '(дна) опережение меньше, порядка 1 недели, и часто развороты идут '
    'синхронно.'
)

# Static hint under the DAX chart, comparing it with NASDAQ 100 and S&P 500.
# Empirically DAX is a "follower": it lags the US indices more often than it
# leads them, and the lead/lag is almost always within a week (often just one
# trading day). NASDAQ 100 turns first most often (especially at tops); the
# DAX–S&P relationship is close to synchronous.
_DAX_HINT = (
    'DAX — преимущественно «догоняющий»: чаще следует за американскими '
    'индексами, чем опережает их. Опережение/запаздывание при разворотах почти '
    'всегда в пределах недели (нередко всего 1 торговый день). Из двух рынков '
    'раньше разворачивается NASDAQ 100 — особенно на вершинах, — а с S&P 500 '
    'связь практически синхронная, систематического опережения нет.'
)


def _yahoo(series_id):
    """Fetch a Yahoo Finance series as (dates, values) with the shared cache."""
    cached = _load_cached(series_id)
    if cached is not None:
        return cached
    symbol, rng = _YAHOO_SYMBOLS[series_id]
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/{}'
           '?range={}&interval=1d'.format(symbol.replace('^', '%5E'), rng))
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
    r.raise_for_status()
    res = r.json()['chart']['result'][0]
    timestamps = res['timestamp']
    closes = res['indicators']['quote'][0]['close']
    dates, values = [], []
    for ts, c in zip(timestamps, closes):
        if c is None:
            continue
        dates.append(datetime.datetime.fromtimestamp(ts, datetime.UTC).date())
        values.append(float(c))
    if not dates:
        raise ValueError('No parseable rows for series {}'.format(series_id))
    try:
        _save_cached(series_id, dates, values)
    except Exception as e:  # noqa: BLE001 - cache write must not fail the fetch
        print('Failed to cache {}: {}'.format(series_id, e))
    return dates, values


def _series(series_id):
    """Return (dates, values) for a series, routing to FRED or Yahoo."""
    if series_id in _YAHOO_SYMBOLS:
        return _yahoo(series_id)
    return _fred(series_id)


def _regime(values):
    """Classify an index regime from price vs its long-term SMA.

    Returns 'bull', 'bear' or None (neutral / not enough data). The SMA window
    and the neutral band are module constants so the icon does not flutter when
    the price hovers right around the average.
    """
    if not values or len(values) < _SMA_WINDOW:
        return None
    arr = np.asarray(values, dtype=float)
    if np.any(np.isnan(arr[-_SMA_WINDOW:])):
        return None
    last = arr[-1]
    sma = arr[-_SMA_WINDOW:].mean()
    if sma == 0:
        return None
    rel = last / sma - 1.0
    if rel > _REGIME_BAND:
        return 'bull'
    if rel < -_REGIME_BAND:
        return 'bear'
    return None


def _regime_icon(name):
    """Load and scale the cached bull/bear PNG, or None when missing."""
    path = os.path.join(_REGIME_DIR, name + '.png')
    pm = QPixmap(path)
    if pm.isNull():
        return None
    return pm.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)


def _hint_label(text):
    """A small muted QLabel that wraps its lines when horizontal space runs out.

    Horizontal size policy is Ignored so the label takes all available width
    (instead of stretching the window to its single-line width) and wordWrap
    breaks the text onto several lines.
    """
    hint = QLabel(text)
    hint.setWordWrap(True)
    hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    hint.setStyleSheet('color: #6a6d78; font-size: 11px;')
    return hint


class IndexDialog(QDialog):
    """Tabs with charts for the main US equity indices."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('US Indices Overview')
        self.resize(1040, 700)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        head = QLabel('US equity indices (source: FRED)')
        head.setStyleSheet('color: {}; font-weight: bold;'.format(_TXT))
        root.addWidget(head)

        self.tabs = QTabWidget()
        self._widgets = []
        for series_id, title, plot_label, ylabel, color, desc in INDICES:
            tab = _IndicatorTab(series_id, plot_label, ylabel, color, desc,
                                self, show_regime=True)
            tab._regime_fn = _regime
            tab._regime_icon = _regime_icon
            self.tabs.addTab(tab, title)
            self._widgets.append(tab)
            if series_id in _LEAD_SERIES:
                tab.layout().addWidget(_hint_label(_LEAD_HINT))
            elif series_id == 'DAX':
                tab.layout().addWidget(_hint_label(_DAX_HINT))
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
                dates, values = _series(tab.series_id)
                note = '{:,} points, {}..{}'.format(
                    len(values), dates[0].isoformat(), dates[-1].isoformat())
            except Exception as e:  # noqa: BLE001 - surfacing fetch errors
                dates, values, note = [], [], 'Error: {}'.format(e)
            tab.set_data(dates, values, note)
        self.reloadButton.setEnabled(True)
