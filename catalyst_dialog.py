# -*- coding: utf-8 -*-
import datetime

from PySide6 import QtWidgets
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor

import catalyst

# Шкала оценки катализатора (0-5, как звёзды Qualitative Assessment).
CATALYST_SCALE = """Оценка отчётливости события:
0 — нет катализатора;
1–2 — расплывчатый («когда-нибудь станет лучше»);
3–4 — чёткое событие с датой и ожидаемым эффектом;
5 — близко, проверяемо и не заложено в цену."""

_TXT = '#dcdce0'
_RED = '#ef5350'

_EV_HEADERS = ['Дата', 'Балл', 'Напр', 'Описание', 'Ожидание']


def _date_to_q(date_str):
    try:
        d = datetime.date.fromisoformat(date_str)
    except (TypeError, ValueError):
        d = datetime.date.today()
    return QDate(d.year, d.month, d.day)


class CatalystEventDialog(QtWidgets.QDialog):
    """Форма добавления/правки события-катализатора (дата + оценка + ожидание).

    В табе Events watchlist тикер выбирается (options); в CatalystDialog
    тикер фиксирован текущим тикером.
    """

    def __init__(self, parent=None, ticker='', options=None, event=None):
        super().__init__(parent)
        self.setWindowTitle('Catalyst event')
        self.setMinimumWidth(520)

        form = QtWidgets.QFormLayout(self)

        if options:
            self.tickerCombo = QtWidgets.QComboBox()
            self.tickerCombo.setEditable(True)
            self.tickerCombo.addItems([t for t in options if t])
            self.tickerCombo.setCurrentText(ticker or '')
            form.addRow('Ticker:', self.tickerCombo)

        self.dateEdit = QtWidgets.QDateEdit()
        self.dateEdit.setCalendarPopup(True)
        self.dateEdit.setDisplayFormat('yyyy-MM-dd')
        self.dateEdit.setDate(_date_to_q(event['date']) if event
                              else QDate.currentDate().addDays(1))
        form.addRow('Дата:', self.dateEdit)

        from qualitative_dialog import StarRating
        self.starRating = StarRating()
        self.starRating.setRating(event['score'] if event else 0)
        rating_lbl = QtWidgets.QLabel('Оценка (0-5):')
        rating_lbl.setToolTip(CATALYST_SCALE)
        form.addRow(rating_lbl, self.starRating)

        self.directionCombo = QtWidgets.QComboBox()
        self.directionCombo.addItems(catalyst._DIRECTIONS)
        if event:
            self.directionCombo.setCurrentText(event.get('direction') or '+')
        form.addRow('Направление:', self.directionCombo)

        self.descEdit = QtWidgets.QLineEdit()
        self.descEdit.setPlaceholderText('Что за событие…')
        if event:
            self.descEdit.setText(event.get('description') or '')
        form.addRow('Описание:', self.descEdit)

        self.expectEdit = QtWidgets.QTextEdit()
        self.expectEdit.setFixedHeight(72)
        self.expectEdit.setPlaceholderText('Что ожидаем: какой исход/метрика '
                                           'будет позитивным/негативным '
                                           'сюрпризом…')
        if event:
            self.expectEdit.setPlainText(event.get('expectation') or '')
        form.addRow('Ожидание:', self.expectEdit)

        row = QtWidgets.QHBoxLayout()
        ok = QtWidgets.QPushButton('OK')
        cancel = QtWidgets.QPushButton('Cancel')
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        form.addRow(row)

    def values(self):
        ticker = ''
        if hasattr(self, 'tickerCombo'):
            ticker = self.tickerCombo.currentText().strip().upper()
        return {
            'ticker': ticker,
            'date': self.dateEdit.date().toString('yyyy-MM-dd'),
            'score': self.starRating.rating(),
            'direction': self.directionCombo.currentText(),
            'description': self.descEdit.text().strip(),
            'expectation': self.expectEdit.toPlainText().strip(),
        }


class CatalystDialog(QtWidgets.QDialog):
    """Многособытийный менеджер катализаторов по тикеру: таблица событий
    с датами/оценками/ожиданиями, сохранение в watchlist."""

    def __init__(self, parent=None, ticker=''):
        super().__init__(parent)
        self.setWindowTitle('Catalyst')
        self.resize(760, 560)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        row = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel('Ticker:')
        self.tickerEdit = QtWidgets.QLineEdit(ticker or '')
        self.tickerEdit.setReadOnly(True)
        self.tickerEdit.setFixedHeight(28)
        row.addWidget(lbl)
        row.addWidget(self.tickerEdit, 1)
        root.addLayout(row)

        self._build_events(root)

        self.tickerEdit.textChanged.connect(self._load_events)
        self.addButton.clicked.connect(self._add_event)
        self.editButton.clicked.connect(self._edit_event)
        self.deleteButton.clicked.connect(self._delete_event)
        self.saveButton.clicked.connect(self._save_to_watchlist)
        self._events = []
        self._load_events()

    def _ticker(self):
        return self.tickerEdit.text().strip().upper()

    def _build_events(self, root):
        bar = QtWidgets.QHBoxLayout()
        bar_lbl = QtWidgets.QLabel('События:')
        bar_lbl.setStyleSheet('color: {};'.format(_TXT))
        self.addButton = QtWidgets.QPushButton('Add')
        self.editButton = QtWidgets.QPushButton('Edit')
        self.deleteButton = QtWidgets.QPushButton('Delete')
        self.saveButton = QtWidgets.QPushButton('Save to Watchlist')
        bar.addWidget(bar_lbl)
        bar.addSpacing(6)
        bar.addWidget(self.addButton)
        bar.addWidget(self.editButton)
        bar.addWidget(self.deleteButton)
        bar.addStretch(1)
        bar.addWidget(self.saveButton)
        root.addLayout(bar)

        self.table = QtWidgets.QTableWidget(0, len(_EV_HEADERS))
        self.table.setHorizontalHeaderLabels(_EV_HEADERS)
        self.table.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(150)
        self.table.itemDoubleClicked.connect(lambda *_: self._edit_event())
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)

    # ------------------------------------------------------------ данные
    def _load_events(self):
        ticker = self._ticker()
        self._events = catalyst.events_for(ticker)
        self.table.setRowCount(len(self._events))
        today = datetime.date.today().isoformat()
        for r, e in enumerate(self._events):
            vals = [e['date'], str(e['score']), e['direction'],
                    e['description'], e['expectation']]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(v)
                if c == 0 and e['date'] <= today:
                    item.setForeground(QColor(_RED))
                elif c in (1, 2):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    # -------------------------------------------------------------- actions
    def _add_event(self):
        ticker = self._ticker()
        if not ticker:
            QtWidgets.QMessageBox.information(
                self, 'Catalyst', 'Введите тикер.')
            return
        dlg = CatalystEventDialog(parent=self, ticker=ticker)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        v['ticker'] = ticker
        eid = catalyst.add_event(**v)
        if eid is None:
            return
        self._load_events()

    def _edit_event(self):
        row = self.table.currentRow()
        if not (0 <= row < len(self._events)):
            return
        e = self._events[row]
        dlg = CatalystEventDialog(parent=self, ticker=e['ticker'], event=e)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        catalyst.update_event(e['id'], date=v['date'], score=v['score'],
                              direction=v['direction'],
                              description=v['description'],
                              expectation=v['expectation'])
        self._load_events()

    def _delete_event(self):
        row = self.table.currentRow()
        if not (0 <= row < len(self._events)):
            return
        e = self._events[row]
        ret = QtWidgets.QMessageBox.question(
            self, 'Delete event',
            'Удалить событие «{}» ({})?'.format(
                e.get('description') or 'без описания', e['date']),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if ret != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        catalyst.delete_event(e['id'])
        self._load_events()

    def _save_to_watchlist(self):
        ticker = self._ticker()
        if not ticker:
            return
        snapshot = {'date': datetime.date.today().isoformat()}
        summary = catalyst.summary_for(ticker)
        if summary:
            snapshot['catalyst'] = summary
        from watchlist import add as watchlist_add
        from watchlist_dialog import WatchlistEntryDialog
        dlg = WatchlistEntryDialog(ticker=ticker, snapshot=snapshot, parent=self)
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
                ' · {} событий'.format(summary['count']) if summary else ''))