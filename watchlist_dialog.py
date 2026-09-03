# -*- coding: utf-8 -*-
from PySide6 import QtWidgets
from PySide6.QtCore import Qt

import markets
import watchlist


class WatchlistDialog(QtWidgets.QDialog):
    """Список тикеров из watchlist с графиком (как у купленных акций) и удалением."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Watchlist')
        self.resize(460, 420)

        root = QtWidgets.QVBoxLayout(self)
        self.listWidget = QtWidgets.QListWidget()
        self.listWidget.itemDoubleClicked.connect(lambda *_: self._show_chart())
        root.addWidget(self.listWidget, 1)

        row = QtWidgets.QHBoxLayout()
        self.chartButton = QtWidgets.QPushButton('Chart')
        self.removeButton = QtWidgets.QPushButton('Remove')
        self.closeButton = QtWidgets.QPushButton('Close')
        row.addWidget(self.chartButton)
        row.addWidget(self.removeButton)
        row.addStretch(1)
        row.addWidget(self.closeButton)
        root.addLayout(row)

        self.chartButton.clicked.connect(self._show_chart)
        self.removeButton.clicked.connect(self._remove)
        self.closeButton.clicked.connect(self.close)
        self._refresh()

    def _refresh(self):
        self.listWidget.clear()
        for t in watchlist.load():
            self.listWidget.addItem(t)

    def _selected(self):
        item = self.listWidget.currentItem()
        return item.text().strip() if item else ''

    def _show_chart(self):
        ticker = self._selected()
        if not ticker:
            return
        from ma_chart_dialog import MAChartDialog
        try:
            _, currency = markets.market_currency(ticker)
        except Exception:  # noqa: BLE001
            currency = None
        dlg = MAChartDialog(ticker, currency or markets.USD, '', '', self.window())
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        main = self.window()
        if hasattr(main, '_dialogs_set'):
            main._dialogs_set().add(dlg)
            dlg.destroyed.connect(lambda obj=None, d=dlg: main._dialogs_set().discard(d))
        dlg.show()

    def _remove(self):
        ticker = self._selected()
        if not ticker:
            return
        ret = QtWidgets.QMessageBox.question(
            self, 'Remove from Watchlist',
            'Remove {} from watchlist?'.format(ticker),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if ret != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        items = watchlist.load()
        if ticker in items:
            items.remove(ticker)
            watchlist.save(items)
        self._refresh()