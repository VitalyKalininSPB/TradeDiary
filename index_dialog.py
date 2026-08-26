# -*- coding: utf-8 -*-
"""US index dashboard: S&P 500 and NASDAQ 100 charts.

Reuses the FRED fetch + SQLite cache machinery from macro_dialog, so the same
macro_cache.db stores both the macro indicators and the two index series.
"""
import datetime

import requests

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QLabel, QApplication)
from PySide6.QtCore import Qt

from macro_dialog import _IndicatorTab, _fred, _load_cached, _save_cached

_TXT = '#dcdce0'

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
                dates, values = _series(tab.series_id)
                note = '{:,} points, {}..{}'.format(
                    len(values), dates[0].isoformat(), dates[-1].isoformat())
            except Exception as e:  # noqa: BLE001 - surfacing fetch errors
                dates, values, note = [], [], 'Error: {}'.format(e)
            tab.set_data(dates, values, note)
        self.reloadButton.setEnabled(True)
