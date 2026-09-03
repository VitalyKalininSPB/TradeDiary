# -*- coding: utf-8 -*-
"""Commodities dashboard: BCOM, copper, oil, gold.

Each commodity gets its own tab (reusing _IndicatorTab from macro_dialog).
BCOM / copper futures / gold futures come from Yahoo Finance (FRED has no
daily series for them); Brent comes from FRED (DCOILBRENTEU, daily). All
series are cached in the shared macro_cache.db, and every tab shows a
goat tip when you switch to it.
"""
import datetime

import requests

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QLabel, QPushButton)
from PySide6.QtCore import Qt

from macro_dialog import (_IndicatorTab, _fred, _load_cached, _save_cached,
                          _at_days_ago, _MOMENTUM_DAYS, _YOY_DAYS,
                          _ChartLoaderThread)

_TXT = '#dcdce0'

# Series entries: (id, tab title, plot label, y-label, color, ru description).
COMMODITIES = [
    ('BCOM',         'Bloomberg Commodity Index (BCOM)',
                     'Bloomberg Commodity Index',
                     'Index',                 '#ffb74d',
                     'Широкий индекс 23 сырьевых фьючерсов (энергетика, металлы, '
                     'сельхоз) — барометр глобального спроса и инфляционного '
                     'давления'),
    ('DCOILBRENTEU', 'Brent Crude (DCOILBRENTEU)',
                     'Brent crude',
                     'US$ / barrel',          '#4dd0e1',
                     'Эталон мировой цены нефти — главный драйвер инфляции '
                     'издержек и покупательной способности потребителя'),
    ('GC=F',         'Gold (GC=F)',
                     'Gold (COMEX futures)',
                     'US$ / troy oz',         '#ffd54f',
                     'Золото — защитный актив: растёт при падении реальных '
                     'ставок и росте неопределённости'),
    ('HG=F',         'Copper (HG=F)',
                     'Copper (COMEX futures)',
                     'US$ / lb',              '#ff7043',
                     '«Доктор Медь» — медь опережает мировую промышленность: '
                     'растёт до подъёма экономики и падает раньше неё'),
]

# Yahoo symbols for the non-FRED series: series_id -> (yahoo symbol, range).
_YAHOO_SYMBOLS = {
    'BCOM': ('^BCOM', '10y'),
    'HG=F': ('HG=F', '25y'),
    'GC=F': ('GC=F', '25y'),
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
    """Return (dates, values) for a series, routing to Yahoo or FRED."""
    if series_id in _YAHOO_SYMBOLS:
        return _yahoo(series_id)
    return _fred(series_id)


def _yoy(dates, values):
    """YoY growth % for the last point, or None."""
    v = values[-1]
    vy = _at_days_ago(dates, values, _YOY_DAYS)
    return (v / vy - 1.0) * 100.0 if vy else None


def _mom(dates, values):
    """3-month momentum % for the last point, or None."""
    v = values[-1]
    vm = _at_days_ago(dates, values, _MOMENTUM_DAYS)
    return (v / vm - 1.0) * 100.0 if vm else None


def _note(dates, values):
    """Tab note: latest price, YoY change and the covered range."""
    if not values:
        return ''
    parts = ['{:.2f}'.format(values[-1])]
    g = _yoy(dates, values)
    if g is not None:
        parts.append('г/г {:+.1f}%'.format(g))
    parts.append('{}..{}'.format(dates[0].isoformat(), dates[-1].isoformat()))
    return ', '.join(parts)


def bcom_advice(dates, values):
    """Goat text for the Bloomberg Commodity Index tab, or ''."""
    if not values:
        return ''
    g = _yoy(dates, values)
    m = _mom(dates, values)
    if g is None:
        return ''
    if g > 20.0:
        if m is not None and m < -5.0:
            return ('BCOM в плюсе г/г, но за квартал разворачивается вниз — '
                    'сырьевой цикл остывает. Фиксируйте прибыль в циклических '
                    'секторах (Energy, Materials, Industrials) и перекладывайтесь '
                    'в защиту (Utilities, Staples, Healthcare): разворот сырья '
                    'опережает разворот S&P 500 на месяцы.')
        return ('BCOM растёт (г/г +{:.0f}%) — глобальный спрос горячий. '
                'Покупайте/держите циклические сектора (Energy, Materials). Но '
                'ускорение сырья опережает разгон инфляции: поставьте трейлинг-'
                'стоп и следите за ставками ФРС.'.format(g))
    if g < -12.0:
        return ('BCOM глубоко в минусе (г/г {:.0f}%) — спрос на сырьё падает, '
                'впереди замедление экономики. Выходите из циклических секторов '
                'S&P 500, сидите в защите (Utilities, Staples, Healthcare) и кэше. '
                'Не ловите дно сырья раньше разворота индекса.'.format(g))
    if m is not None and m > 8.0:
        return ('BCOM развернулся вверх после боковика — оживление спроса. '
                'Покупайте циклические сектора (Materials, Industrials) — это '
                'ранний сигнал поддержки для S&P 500.')
    if m is not None and m < -8.0:
        return ('BCOM затухает (3 мес {:.0f}%) — спрос остывает. Не наращивайте '
                'циклические позиции, сократите Energy/Materials. NASDAQ держится '
                'дольше, пока ставки не выросли.'.format(m))
    return ('BCOM в боковике — сырьё не диктует направление. Держите позиции, '
            'решения принимайте по ставкам и прибылям, а не по сырью.')


def copper_advice(dates, values):
    """Goat text for the Copper tab, or ''."""
    if not values:
        return ''
    g = _yoy(dates, values)
    m = _mom(dates, values)
    if g is None:
        return ''
    if g > 12.0:
        if m is not None and m < -6.0:
            return ('Медь в плюсе г/г, но за квартал разворачивается вниз — '
                    'промышленный спрос достигает пика. Фиксируйте циклические '
                    'сектора (Materials, Industrials) и перекладывайтесь в '
                    'защиту: коррекция сырьевых циклов опережает разворот '
                    'S&P 500 на 3–6 мес.')
        return ('Медь растёт (г/г +{:.0f}%) — «Доктор Медь» подтверждает '
                'промышленный подъём. Покупайте/держите циклические сектора '
                '(Materials, Industrials); шортить S&P 500 пока рано — медь '
                'разворачивается вниз раньше индекса.'.format(g))
    if g < -8.0:
        return ('Медь падает (г/г {:.0f}%) — «Доктор Медь» предупреждает о '
                'замедлении промышленности. Сокращайте или шортите циклические '
                'сектора, держите кэш или защиту: риск коррекции S&P 500 в '
                'горизонте 3–12 мес.'.format(g))
    if m is not None and m > 6.0:
        return ('Медь развернулась вверх после боковика — спрос оживает '
                '(электрификация, стройка). Покупайте циклические сектора '
                'раньше других: медь опережает индекс.')
    if m is not None and m < -6.0:
        return ('Медь затухает (3 мес {:.0f}%) — спрос остывает без рецессии. '
                'Не наращивайте циклики, сократите позиции в Materials. NASDAQ '
                'устоит, пока ставки не выросли.'.format(m))
    return ('Медь в боковике — промышленный цикл без импульса. Держите позиции, '
            'не принимайте решений по сырью; решают ставки и прибыли.')


def brent_advice(dates, values):
    """Goat text for the Brent tab, or ''."""
    if not values:
        return ''
    v = values[-1]
    g = _yoy(dates, values)
    m = _mom(dates, values)
    if m is None:
        return ''
    if m > 18.0:
        return ('Brent за 3 мес +{:.0f}% — энергетический шок. Покупайте Energy '
                '(XLE) и сокращайте Consumer Discretionary/авиакомпании: дорогое '
                'топливо сжимает их прибыль. Если рост нефти переходит в '
                'headline-инфляцию — ждите risk-off и жёсткую реакцию '
                'ФРС.'.format(m))
    if m < -18.0:
        return ('Brent падает (3 мес {:.0f}%) — дезинфляционный ветер. '
                'Склоняйтесь к risk-on: покупайте растущие сектора и NASDAQ — '
                'у ФРС появляется место для снижения ставок.'.format(m))
    if v > 85.0 and g is not None and g > 15.0:
        return ('Brent дорогая (${:.0f}) и растёт г/г — избегайте Consumer '
                'Discretionary и перевозок, держите Energy. Дорогая нефть '
                'ограничивает смягчение ФРС: следите за ставками.'.format(v))
    return ('Brent в комфортной зоне — нейтрально для рынка. Не принимайте '
            'решений по нефти; важны только резкие движения (шок или обвал).')


def gold_advice(dates, values):
    """Goat text for the Gold tab, or ''."""
    if not values:
        return ''
    v = values[-1]
    m = _mom(dates, values)
    if m is None:
        return ''
    at_high = v >= max(values) * 0.995
    if m > 8.0:
        if at_high:
            return ('Золото на историческом максимуме и растёт — рынок массово '
                    'страхуется. Снизьте риск портфеля, проверьте макро-градусник '
                    'и кредитные спреды; добавьте золото (GLD) как хедж, если '
                    'его ещё нет. Распродажа золота часто совпадает с пиком '
                    'S&P 500.')
        return ('Золото в аптренде (3 мес +{:.0f}%) — неопределённость растёт '
                '(реальные ставки вниз или геополитика). Добавьте золото (GLD) '
                'как хедж и не наращивайте рискованные позиции до прояснения '
                'картины.'.format(m))
    if m < -8.0:
        return ('Золото дешевеет (3 мес {:.0f}%) — реальные ставки высоки или '
                'растут. Избегайте длинных бумаг и NASDAQ (худший сценарий для '
                'дюрации), держите кэш. Покупать длинные облигации или ростовые '
                'акции рано, пока золото не развернулось.'.format(m))
    return ('Золото в боковике — страх умеренный. Держите позиции; следите за '
            'разворотом золота — это ранний признак смены настроений на '
            'рынке.')


class CommoditiesDialog(QDialog):
    """Tabs with charts for the key commodity indicators."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Commodities Overview')
        self.resize(1040, 700)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        head = QLabel('Key commodity indicators '
                      '(BCOM/copper/gold: Yahoo, Brent: FRED)')
        head.setStyleSheet('color: {}; font-weight: bold;'.format(_TXT))
        root.addWidget(head)

        self.tabs = QTabWidget()
        self._widgets = []
        self._bcom_tab = None
        self._copper_tab = None
        self._oil_tab = None
        self._gold_tab = None
        for series_id, title, plot_label, ylabel, color, desc in COMMODITIES:
            tab = _IndicatorTab(series_id, plot_label, ylabel, color, desc, self)
            self.tabs.addTab(tab, title)
            self._widgets.append(tab)
            if series_id == 'BCOM':
                self._bcom_tab = tab
            elif series_id == 'HG=F':
                self._copper_tab = tab
            elif series_id == 'DCOILBRENTEU':
                self._oil_tab = tab
            elif series_id == 'GC=F':
                self._gold_tab = tab
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self.reloadButton = self._build_footer(root)

        self._loader = None
        self._load_all()

    def _build_footer(self, root):
        row = QHBoxLayout()
        row.addStretch(1)
        reloadBtn = QPushButton('Reload')
        reloadBtn.clicked.connect(self._load_all)
        row.addWidget(reloadBtn)
        closeBtn = QPushButton('Close')
        closeBtn.clicked.connect(self.accept)
        row.addWidget(closeBtn)
        root.addLayout(row)
        return reloadBtn

    def _on_row_loaded(self, series_id, dates, values, note):
        for tab in self._widgets:
            if tab.series_id == series_id:
                tab.set_data(dates, values, _note(dates, values))
                return

    def _on_tab_changed(self, index):
        """The goat speaks only about the commodity tab the user switched to."""
        widget = self.tabs.widget(index)
        advice = None
        if widget is self._bcom_tab:
            advice = bcom_advice(widget._dates, widget._values)
        elif widget is self._copper_tab:
            advice = copper_advice(widget._dates, widget._values)
        elif widget is self._oil_tab:
            advice = brent_advice(widget._dates, widget._values)
        elif widget is self._gold_tab:
            advice = gold_advice(widget._dates, widget._values)
        self._show_goat(advice)

    def _show_goat(self, advice):
        """Show the goat with `advice`, or hide it when there is nothing to say."""
        from qualitative_dialog import GoatAssistant
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        if not advice:
            return
        self._goat = GoatAssistant('', self, advice=advice,
                                   auto_hide_ms=20000)
        self._goat.show()

    def _load_all(self):
        self.reloadButton.setEnabled(False)
        items = [(t.series_id, _series) for t in self._widgets]
        self._loader = _ChartLoaderThread(items, self)
        self._loader.row_loaded.connect(self._on_row_loaded)
        self._loader.load_done.connect(
            lambda: self.reloadButton.setEnabled(True))
        self._loader.start()

    def closeEvent(self, event):
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
        if self._loader is not None and self._loader.isRunning():
            self._loader.wait(5000)
        super().closeEvent(event)