# This Python file uses the following encoding: utf-8
from PySide6.QtWidgets import QApplication, QDialog
from PySide6 import QtCore, QtGui, QtWidgets
from qt_loader import loadUi

from deals import Deal, Direction

from enum import Enum
from datetime import datetime


class EditDealDialog(QDialog):
    """Правка/закрытие ПОЗИЦИИ (одна или несколько сделок одного тикера).

    Показывает усреднённые значения: init price, текущую цену (только чтение),
    суммарное количество, TP/SL. Общие поля (TP/SL, система, заметки) при
    изменении применяются ко ВСЕМ сделкам позиции. Текущую цену править
    нельзя — она обновляется автоматически из рынка.

    Можно закрыть ЧАСТЬ позиции по текущей цене (без TP/SL): для лонга —
    продать, для шорта — выкупить. Продажа применяется СРАЗУ через колбэк
    `on_partial` (main._partial_close), а не по [OK].
    """

    def __init__(self):
        super().__init__()
        loadUi("editdeal.ui", self)
        self.buttonBox_2.accepted.connect(self.okPressed)
        self.buttonBox_2.rejected.connect(self.cancelPressed)
        self.openDate = datetime.now()
        self.openDateLabel.setText(self.openDate.strftime("%d/%m/%Y %H:%M"))
        self.closeDealButton.clicked.connect(self.closeDealClicked)
        self._initial = {}
        self.deals = []
        self._on_partial = None
        self._build_partial_group()

    def _build_partial_group(self):
        self.partialGroup = QtWidgets.QGroupBox('Закрыть часть позиции', self)
        self.partialGroup.setGeometry(430, 40, 360, 150)
        lay = QtWidgets.QVBoxLayout(self.partialGroup)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)
        row = QtWidgets.QHBoxLayout()
        self.partialLabel = QtWidgets.QLabel('Продать:')
        self.partialQty = QtWidgets.QLineEdit()
        self.partialQty.setPlaceholderText('кол-во')
        self.partialButton = QtWidgets.QPushButton('Sell')
        self.partialButton.setToolTip(
            'Закрыть часть позиции по текущей цене (без TP/SL)')
        row.addWidget(self.partialLabel)
        row.addWidget(self.partialQty, 1)
        row.addWidget(self.partialButton)
        lay.addLayout(row)
        self.partialInfo = QtWidgets.QLabel('')
        self.partialInfo.setWordWrap(True)
        self.partialInfo.setStyleSheet('color: #9aa0aa; font-size: 11px;')
        lay.addWidget(self.partialInfo)
        lay.addStretch(1)
        self.partialButton.clicked.connect(self._partial_clicked)

    @staticmethod
    def _to_float(text, default):
        try:
            return float(text)
        except (TypeError, ValueError):
            return default

    def setPosition(self, position, balance, on_partial=None):
        self._balance = balance
        self._on_partial = on_partial
        self.position = position
        self.deals = list(position.deals)
        self.deal = self.deals[0]  # обратная совместимость
        multi = len(self.deals) > 1

        self.setWindowTitle('Edit position — {}'.format(position.ticker))

        self.ticketEdit.setText(position.ticker)
        self.ticketEdit.setReadOnly(True)

        self.initpriceEdit.setText('{:.2f}'.format(position.init_price))
        self.initpriceEdit.setToolTip(
            'Средневзвешенная цена входа по позиции. Изменение применится '
            'ко всем сделкам тикера.')

        self.priceEdit.setText('{:.2f}'.format(position.stock_price))
        self.priceEdit.setEnabled(False)
        self.priceEdit.setToolTip(
            'Текущая цена обновляется автоматически из рынка — вручную '
            'не редактируется.')

        self.amountEdit.setText('{:.2f}'.format(position.amount))
        self.amountEdit.setEnabled(not multi)
        if multi:
            self.amountEdit.setToolTip(
                'Суммарное количество по позиции ({} сделок).'.format(
                    len(self.deals)))

        self.openDateLabel.setText(position.open_date)
        self.closeDateLabel.setText(position.close_date)
        self.takeprofitEdit.setText('{:.2f}'.format(position.take_profit))
        self.stoplossEdit.setText('{:.2f}'.format(position.stop_loss))
        try:
            idx = int(position.trade_system or 0)
        except (TypeError, ValueError):
            idx = 0
        self.tradesystemList.setCurrentIndex(idx)
        self.tradesystemList.setEnabled(not position.close_date)
        self.whatsNextEdit.setText(position.whats_next)
        self.notesEdit.setText(position.notes)

        self.closeDealButton.setEnabled(not position.close_date)

        short = position.direction == Direction.SHORT
        self.partialLabel.setText('Выкупить:' if short else 'Продать:')
        self.partialButton.setText('Buy back' if short else 'Sell')
        self.partialGroup.setVisible(not position.close_date)
        self._remaining = position.amount
        self._update_partial_info()

        self._initial = {
            'init_price': position.init_price,
            'take_profit': position.take_profit,
            'stop_loss': position.stop_loss,
            'trade_system': position.trade_system,
            'whats_next': position.whats_next,
            'notes': position.notes,
        }

    def _update_partial_info(self):
        self.partialInfo.setText(
            'Останется: {:.2f} шт · цена {:.2f}'.format(
                max(self._remaining, 0.0), self.position.stock_price))

    def _partial_clicked(self):
        qty = self._to_float(self.partialQty.text(), None)
        if qty is None or qty <= 0:
            self.partialInfo.setText('Укажите количество больше 0.')
            return
        if qty > self._remaining + 1e-9:
            self.partialInfo.setText(
                'Не больше остатка ({:.2f} шт).'.format(
                    max(self._remaining, 0.0)))
            return
        if self._on_partial is None:
            self.partialInfo.setText('Закрытие части недоступно.')
            return
        # Применяем СРАЗУ (не ждём [OK]) — это рыночная операция.
        remaining = self._on_partial(qty)
        if remaining is not None:
            self._remaining = remaining
        self.deals = [d for d in self.deals if (d.amount or 0) > 0]
        self.amountEdit.setText('{:.2f}'.format(max(self._remaining, 0.0)))
        self.partialQty.clear()
        self._update_partial_info()

    def _apply_common(self):
        """Общие поля применить ко всем сделкам позиции (только изменённые)."""
        init = self._to_float(self.initpriceEdit.text(), None)
        if init is not None and abs(init - self._initial['init_price']) > 1e-9:
            for d in self.deals:
                d.init_price = init

        tp = self._to_float(self.takeprofitEdit.text(), None)
        if tp is not None and abs(tp - self._initial['take_profit']) > 1e-9:
            for d in self.deals:
                d.take_profit = tp

        sl = self._to_float(self.stoplossEdit.text(), None)
        if sl is not None and abs(sl - self._initial['stop_loss']) > 1e-9:
            for d in self.deals:
                d.stop_loss = sl

        idx = self.tradesystemList.currentIndex()
        if idx != self._initial['trade_system']:
            for d in self.deals:
                d.trade_system = idx

        whats_next = self.whatsNextEdit.toPlainText()
        if whats_next != self._initial['whats_next']:
            for d in self.deals:
                d.whats_next = whats_next

        notes = self.notesEdit.toPlainText()
        if notes != self._initial['notes']:
            for d in self.deals:
                d.notes = notes

    def okPressed(self):
        self._apply_common()
        if len(self.deals) == 1 and self.amountEdit.isEnabled():
            amount = self._to_float(self.amountEdit.text(), None)
            if amount is not None:
                self.deals[0].amount = amount
        self.accept()

    def cancelPressed(self):
        self.reject()

    def closeDealClicked(self):
        closeDate = datetime.now()
        self.closeDateLabel.setText(closeDate.strftime("%d/%m/%Y %H:%M"))
        self._apply_common()
        for d in self.deals:
            d.close_date = self.closeDateLabel.text()
        self.accept()
