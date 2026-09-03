# -*- coding: utf-8 -*-
from PySide6 import QtCore, QtGui, QtWidgets

import sector_quant

_TXT = '#dcdce0'
_TIER_COLORS = {
    'Strong': '#2e7d32',
    'Positive': '#1f6f3f',
    'Neutral': '#3a5a8c',
    'Weak': '#9a6b1f',
    'Negative': '#b71c1c',
    'n/a': '#3a3c46',
}
_STATUS_COLORS = {
    'Confirmed strength': '#2e7d32',
    'Quality under pressure': '#9a6b1f',
    'Price-led recovery': '#3a5a8c',
    'Confirmed weakness': '#b71c1c',
}

_HEADERS = ['Rank', 'Sector', 'Signal', 'Score', 'Next step']

# «Следующий шаг» в главной таблице и развёрнутый текст деталей по статусу.
_NEXT_STEP = {
    'Confirmed strength': 'Приоритет для исследования long-кандидатов',
    'Quality under pressure': 'Наблюдать; проверить расхождение сигналов',
    'Price-led recovery': 'Проверить катализатор',
    'Confirmed weakness': 'Исключить из поиска long-кандидатов',
}
_PRIORITY = {
    'Confirmed strength': 'High',
    'Quality under pressure': 'Medium',
    'Price-led recovery': 'Medium',
    'Confirmed weakness': 'Low',
}
_NEXT_STEP_DETAIL = {
    'Confirmed strength':
        'Посмотреть компании {sector} и выбрать те, у которых качественные '
        'финансовые показатели и нет явных qualitative red flags.',
    'Quality under pressure':
        'Разобраться, почему рынок не поддерживает сильную рентабельность '
        '{sector}: проверьте макро- и секторные факторы, свежие отчёты и guidance.',
    'Price-led recovery':
        'Проверить, действительно ли в {sector} начинается циклическое '
        'улучшение прибыльности (маржа, заказы, guidance).',
    'Confirmed weakness':
        '{sector} пока исключён из поиска long-кандидатов — дождитесь '
        'разворота рентабельности и momentum.',
}


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
    """Sector Quantitative Assessment: 5-column summary (Rank, Sector, Signal,
    Score, Next step) + a detail panel opened by clicking a sector."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Sector Quantitative Assessment')
        self.resize(900, 720)

        root = QtWidgets.QVBoxLayout(self)

        self.infoLabel = QtWidgets.QLabel('Загрузка…')
        self.infoLabel.setStyleSheet('color: {};'.format(_TXT))
        root.addWidget(self.infoLabel)

        self.table = QtWidgets.QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemClicked.connect(self._on_item_clicked)
        root.addWidget(self.table, 3)

        self.detail = QtWidgets.QTextBrowser()
        self.detail.setStyleSheet(
            'background: #1e1f24; color: {}; border: 1px solid #43464f;'
            .format(_TXT))
        self.detail.setOpenExternalLinks(False)
        root.addWidget(self.detail, 2)

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
        self._payload = None
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
        self._payload = payload
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
            st = s.get('status') or {}
            signal = st.get('status', '-')
            vals = [
                s.get('rank') if s.get('rank') is not None else '-',
                s.get('sector', ''),
                signal,
                self._fmt(s.get('score')),
                _NEXT_STEP.get(signal, '-'),
            ]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(str(v))
                if c == 2:
                    color = _STATUS_COLORS.get(signal, _TIER_COLORS['n/a'])
                    item.setBackground(QtGui.QColor(color))
                    item.setForeground(QtGui.QColor('#ffffff'))
                    item.setToolTip(st.get('status_ru', ''))
                elif c == 3:
                    item.setForeground(QtGui.QColor(_TXT))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self._show_details(sectors[0] if sectors else None)

    def _on_item_clicked(self, item):
        if self._payload is None:
            return
        sectors = self._payload.get('sectors', [])
        row = item.row()
        if 0 <= row < len(sectors):
            self._show_details(sectors[row])

    def _show_details(self, s):
        if s is None:
            self.detail.setPlainText('')
            return
        st = s.get('status') or {}
        signal = st.get('status', '-')
        sector = s.get('sector', '')
        rel_pp = s.get('rel_margin_pp')
        if rel_pp is None:
            rel_line = '• Net Margin: {}'.format(self._fmt(s.get('net_margin'), '%'))
        else:
            rel_line = ('• Net Margin: {}, на {:.1f} п.п. {} среднего по '
                        'секторам'.format(
                            self._fmt(s.get('net_margin'), '%'), abs(rel_pp),
                            'выше' if rel_pp >= 0 else 'ниже'))
        lines = [
            '{} — {}'.format(sector, signal),
            '',
            'Score: {}'.format(self._fmt(s.get('score'))),
            'Priority: {}'.format(_PRIORITY.get(signal, '-')),
            '',
            'Почему:',
            rel_line,
            '• Relative Profitability: {:+.2f}'.format(s.get('profit'))
            if s.get('profit') is not None else '• Relative Profitability: -',
            '• Rel Momentum 1M: {:+.1f} п.п.'.format(s.get('rel_mom_1m'))
            if s.get('rel_mom_1m') is not None else '• Rel Momentum 1M: -',
            '• Rel Momentum 1Y: {:+.1f} п.п.'.format(s.get('rel_mom_1y'))
            if s.get('rel_mom_1y') is not None else '• Rel Momentum 1Y: -',
            '• Momentum: {:+.2f}'.format(s.get('momentum'))
            if s.get('momentum') is not None else '• Momentum: -',
            '',
            'Следующий шаг:',
            _NEXT_STEP_DETAIL.get(signal, '-').format(sector=sector),
        ]
        self.detail.setPlainText('\n'.join(lines))

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