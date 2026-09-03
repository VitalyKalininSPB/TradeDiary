# -*- coding: utf-8 -*-
from PySide6 import QtCore, QtGui, QtWidgets

import sector_quant

_BG = '#1e1f24'
_TXT = '#dcdce0'
_TIER_COLORS = {
    'Strong': '#2e7d32',
    'Positive': '#1f6f3f',
    'Weak': '#9a6b1f',
    'Negative': '#b71c1c',
    'n/a': '#3a3c46',
}

_HEADERS = ['Rank', 'Sector', 'Net Margin %', 'Rev 1M %', 'Rev 3M %',
            'Rel Mom 1M %', 'Rel Mom 1Y %', 'Profit', 'Momentum', 'Score',
            'Tier']


class _SectorQuantThread(QtCore.QThread):
    """Fetch sector snapshots, compute and save the rating off the UI thread."""

    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, force, parent=None):
        super().__init__(parent)
        self._force = force

    def run(self):
        try:
            payload = sector_quant.run_sector_quant(force=self._force)
            self.finished.emit(payload)
        except Exception as e:  # noqa: BLE001 - surface the error to the UI
            self.failed.emit(str(e))


class SectorQuantDialog(QtWidgets.QDialog):
    """Sector Quantitative Assessment: ranked GICS sectors by profit revision
    and relative momentum. Draws the last saved result instantly, then
    recomputes in the background (the "GDP-style" cached pattern)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Sector Quantitative Assessment')
        self.resize(1000, 620)

        root = QtWidgets.QVBoxLayout(self)

        self.infoLabel = QtWidgets.QLabel('Загрузка…')
        self.infoLabel.setStyleSheet('color: {};'.format(_TXT))
        root.addWidget(self.infoLabel)

        self.table = QtWidgets.QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        self.refreshButton = QtWidgets.QPushButton('Refresh')
        self.closeButton = QtWidgets.QPushButton('Close')
        row.addWidget(self.refreshButton)
        row.addStretch(1)
        row.addWidget(self.closeButton)
        root.addLayout(row)

        self.refreshButton.clicked.connect(lambda: self._start(force=True))
        self.closeButton.clicked.connect(self.close)

        self._thread = None
        self._load_cached()
        self._start(force=False)

    def _load_cached(self):
        payload = sector_quant.load_result()
        if payload is not None:
            self._render(payload, from_cache=True)

    def _start(self, force):
        if self._thread is not None and self._thread.isRunning():
            return
        self.refreshButton.setEnabled(False)
        self.infoLabel.setText('Загрузка данных по секторам…')
        self._thread = _SectorQuantThread(force, self)
        self._thread.finished.connect(self._on_finished)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_finished(self, payload):
        self.refreshButton.setEnabled(True)
        self._render(payload, from_cache=False)

    def _on_failed(self, error):
        self.refreshButton.setEnabled(True)
        QtWidgets.QMessageBox.warning(
            self, 'Sector Quantitative Assessment', error)
        if not self.table.rowCount():
            self.infoLabel.setText('Нет данных. ' + error)

    def _render(self, payload, from_cache=False):
        sectors = payload.get('sectors', [])
        errors = payload.get('errors', [])
        err_note = ('; без данных: {}'.format(', '.join(errors))) if errors else ''
        status = 'кэш' if from_cache else (payload.get('computed_at') or '')[:16]
        self.infoLabel.setText(
            'Секторов: {} · срез {} · источник {} · расчёт {}{}'.format(
                len(sectors), payload.get('data_date', ''),
                payload.get('source', ''), status, err_note))
        self.table.setRowCount(len(sectors))
        for r, s in enumerate(sectors):
            vals = [
                s.get('rank') if s.get('rank') is not None else '-',
                s.get('sector', ''),
                self._fmt(s.get('net_margin'), '%'),
                self._fmt(s.get('rev_1m'), '%'),
                self._fmt(s.get('rev_3m'), '%'),
                self._fmt(s.get('rel_mom_1m'), '%'),
                self._fmt(s.get('rel_mom_1y'), '%'),
                self._fmt(s.get('profit')),
                self._fmt(s.get('momentum')),
                self._fmt(s.get('score')),
                s.get('tier', ''),
            ]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(str(v))
                if c == 10:
                    color = _TIER_COLORS.get(v, _TIER_COLORS['n/a'])
                    item.setBackground(QtGui.QColor(color))
                    item.setForeground(QtGui.QColor('#ffffff'))
                elif c in (7, 8, 9):
                    item.setForeground(QtGui.QColor(_TXT))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    @staticmethod
    def _fmt(value, suffix=''):
        if value is None:
            return '-'
        if suffix:
            return '{:+.1f}{}'.format(value, suffix)
        return '{:+.2f}'.format(value)

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(5000)
        super().closeEvent(event)