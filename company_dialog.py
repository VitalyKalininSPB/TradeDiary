# -*- coding: utf-8 -*-
from PySide6 import QtCore, QtGui, QtWidgets

import company_data
import company_quant

_TXT = '#dcdce0'
_LABEL_COLORS = {
    company_quant.LABEL_RESEARCH_PRIORITY: '#2e7d32',
    company_quant.LABEL_WATCHLIST: '#3a5a8c',
    company_quant.LABEL_LOW_PRIORITY: '#9a6b1f',
    company_quant.LABEL_INSUFFICIENT: '#5a5d66',
}
_LABEL_RU = {
    company_quant.LABEL_RESEARCH_PRIORITY: 'Приоритет для исследования',
    company_quant.LABEL_WATCHLIST: 'Наблюдать',
    company_quant.LABEL_LOW_PRIORITY: 'Низкий приоритет',
    company_quant.LABEL_INSUFFICIENT: 'Недостаточно данных',
}

_HEADERS = ['Rank', 'Ticker', 'Company', 'Net Margin', 'Net Margin YoY',
            'Rel Momentum 1M', 'Rel Momentum 1Y', 'Company Score',
            'Research status']


class _CompanyDataThread(QtCore.QThread):
    """Обновление живых метрик компаний (не чаще раза в день) в фоне."""

    loaded = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, sector, parent=None):
        super().__init__(parent)
        self._sector = sector

    def run(self):
        try:
            inputs = company_data.sector_companies(self._sector, force=False)
            self.loaded.emit(inputs)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class CompanyScreenDialog(QtWidgets.QDialog):
    """Company screener inside one sector: two lists — long candidates
    (Company Score desc) and short candidates (Company Score asc, weakest
    first). Both use the same neutral metrics; this is not a buy/sell call."""

    def __init__(self, sector, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Companies — {}'.format(sector))
        self.resize(1180, 680)

        root = QtWidgets.QVBoxLayout(self)
        self.infoLabel = QtWidgets.QLabel('')
        self.infoLabel.setStyleSheet('color: {};'.format(_TXT))
        root.addWidget(self.infoLabel)

        self.tabs = QtWidgets.QTabWidget()
        self.longTable = self._make_table()
        self.shortTable = self._make_table()
        self.tabs.addTab(self.longTable, 'Long candidates')
        self.tabs.addTab(self.shortTable, 'Short candidates')
        root.addWidget(self.tabs, 1)

        row = QtWidgets.QHBoxLayout()
        self.watchButton = QtWidgets.QPushButton('Add to watchlist')
        closeButton = QtWidgets.QPushButton('Close')
        row.addWidget(self.watchButton)
        row.addStretch(1)
        row.addWidget(closeButton)
        root.addLayout(row)
        self.watchButton.clicked.connect(self._add_to_watchlist)
        closeButton.clicked.connect(self.close)

        self._sector = sector
        self._thread = None
        self._load()

    def _make_table(self):
        table = QtWidgets.QTableWidget(0, len(_HEADERS))
        table.setHorizontalHeaderLabels(_HEADERS)
        table.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _load(self):
        inputs = company_data.sector_companies_cached(self._sector)
        if not inputs:
            self.infoLabel.setText(
                'Сектор {}: нет данных компаний.'.format(self._sector))
            self.longTable.setRowCount(0)
            self.shortTable.setRowCount(0)
        else:
            self._render(inputs)
        self._start_refresh()

    def _start_refresh(self):
        if self._thread is not None and self._thread.isRunning():
            return
        self._thread = _CompanyDataThread(self._sector, self)
        self._thread.loaded.connect(self._on_loaded)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_loaded(self, inputs):
        self._render(inputs)

    def _on_failed(self, error):
        self.infoLabel.setText(self.infoLabel.text() + ' · ошибка метрик: ' + error)

    def _render(self, inputs):
        rows = company_quant.rank_companies(inputs)
        events = []
        from quant_alerts import check_company_scores
        try:
            events = check_company_scores(inputs)
        except Exception as e:  # noqa: BLE001
            print('Company alerts: {}'.format(e))
        scored = [r for r in rows if r['company_score'] is not None]
        unscored = [r for r in rows if r['company_score'] is None]
        long_rows = sorted(
            [r for r in scored
             if r['label'] in (company_quant.LABEL_RESEARCH_PRIORITY,
                               company_quant.LABEL_WATCHLIST)],
            key=lambda r: r['company_score'], reverse=True)
        short_rows = sorted(
            [r for r in scored
             if r['label'] == company_quant.LABEL_LOW_PRIORITY],
            key=lambda r: r['company_score'])
        for i, r in enumerate(long_rows, start=1):
            r['_long_rank'] = i
        for i, r in enumerate(short_rows, start=1):
            r['_short_rank'] = i
        note = ''
        if events:
            note = ' · {} компаний изменили score'.format(len(events))
        if unscored:
            note += ' · {} без данных'.format(len(unscored))
        self.infoLabel.setText(
            'Сектор {} · Long {} · Short {} · Long = сильные, Short = худшие{}'.format(
                self._sector, len(long_rows), len(short_rows), note))
        if events:
            self._show_goat(
                'Компании изменили score:\n' + '\n'.join(
                    e['message'] for e in events[:4]))
        self._fill(self.longTable, long_rows, '_long_rank')
        self._fill(self.shortTable, short_rows, '_short_rank')

    def _fill(self, table, rows, rank_key):
        table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            label = s.get('label', company_quant.LABEL_INSUFFICIENT)
            vals = [
                s.get(rank_key) if s.get(rank_key) is not None else '-',
                s.get('ticker') or '-',
                s.get('company') or '-',
                self._fmt(s.get('net_margin'), '%'),
                self._fmt(s.get('net_margin_yoy'), 'pp'),
                self._fmt(s.get('rel_momentum_1m'), '%'),
                self._fmt(s.get('rel_momentum_1y'), '%'),
                self._fmt(s.get('score_rounded')),
                label,
            ]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(str(v))
                if c == 8:
                    color = _LABEL_COLORS.get(label, _LABEL_COLORS[
                        company_quant.LABEL_INSUFFICIENT])
                    item.setBackground(QtGui.QColor(color))
                    item.setForeground(QtGui.QColor('#ffffff'))
                    tip = _LABEL_RU.get(label, label)
                    warnings = s.get('warnings') or []
                    if warnings:
                        tip += '\n' + '\n'.join(warnings)
                    item.setToolTip(tip)
                elif c in (4, 5, 6, 7):
                    item.setForeground(QtGui.QColor(_TXT))
                table.setItem(r, c, item)
        table.resizeColumnsToContents()

    def _selected(self):
        table = self.tabs.currentWidget()
        row = table.currentRow()
        if 0 <= row < table.rowCount():
            item = table.item(row, 1)
            return item.text() if item else ''
        return ''

    def _add_to_watchlist(self):
        ticker = self._selected()
        if not ticker:
            return
        table = self.tabs.currentWidget()
        row = table.currentRow()
        score_item = table.item(row, 7)
        quant = None
        if score_item and score_item.text() != '-':
            try:
                quant = float(score_item.text())
            except ValueError:
                quant = None
        snapshot = {'quant': quant, 'quant_sector': self._sector}
        from watchlist import add as watchlist_add
        from watchlist_dialog import WatchlistEntryDialog
        dlg = WatchlistEntryDialog(ticker=ticker, snapshot=snapshot,
                                   parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        res = watchlist_add(v['ticker'], v['status'], v['note'], v['reason'],
                            snapshot=snapshot)
        QtWidgets.QMessageBox.information(
            self, 'Watchlist',
            '{} {} в watchlist{}.'.format(
                v['ticker'],
                'добавлен' if res == 'added' else 'обновлён',
                ' (Quant {:.2f})'.format(quant) if quant is not None else ''))

    @staticmethod
    def _fmt(value, suffix=''):
        if value is None:
            return '-'
        if suffix:
            return '{:+.1f}{}'.format(value, suffix)
        return '{:.2f}'.format(value)

    def _show_goat(self, advice):
        from qualitative_dialog import GoatAssistant
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        if not advice:
            return
        self._goat = GoatAssistant('', self, advice=advice, auto_hide_ms=8000)
        self._goat.show()

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(5000)
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        super().closeEvent(event)