# This Python file uses the following encoding: utf-8
from PySide6.QtWidgets import QApplication, QDialog
from PySide6 import QtCore, QtGui, QtWidgets
from qt_loader import loadUi

from deals import Deal

from enum import Enum
from datetime import datetime

class EditDealDialog(QDialog):
    def __init__(self):
        super().__init__()
        loadUi("editdeal.ui", self)
        self.buttonBox_2.accepted.connect(self.okPressed)
        self.buttonBox_2.rejected.connect(self.cancelPressed)
        self.openDate = datetime.now()
        self.openDateLabel.setText(self.openDate.strftime("%d/%m/%Y %H:%M"))
        self.closeDealButton.clicked.connect(self.closeDealClicked)


    def setData(self, deal, balance):
        self._balance = balance

        self.deal = deal
        self.ticketEdit.setText(self.deal.ticker)
        self.initpriceEdit.setText(str(self.deal.init_price))
        self.priceEdit.setText(str(self.deal.stock_price))
        self.priceEdit.setEnabled(not self.deal.close_date)
        self.amountEdit.setText(str(self.deal.amount))
        self.openDateLabel.setText(self.deal.open_date)
        self.closeDateLabel.setText(self.deal.close_date)
        self.takeprofitEdit.setText(str(self.deal.take_profit))
        self.stoplossEdit.setText(str(self.deal.stop_loss))
        try:
            idx = int(self.deal.trade_system or 0)
        except (TypeError, ValueError):
            idx = 0
        self.tradesystemList.setCurrentIndex(idx)
        if not self.deal.close_date:
            self.tradesystemList.setEnabled(True)
        self.whatsNextEdit.setText(self.deal.whats_next)
        self.notesEdit.setText(self.deal.notes)

        if not self.deal.close_date:
            self.closeDealButton.setEnabled(True)
        else:
            self.closeDealButton.setEnabled(False)

        print("Balance === " + str(self._balance))

    def okPressed(self):
        print('Accept')
        self.deal.stock_price = float(self.priceEdit.text()) if self.priceEdit.text() else self.deal.stock_price
        self.deal.trade_system = self.tradesystemList.currentIndex()
        self.deal.close_date = self.closeDateLabel.text()
        self.deal.whats_next = self.whatsNextEdit.toPlainText()
        self.deal.notes = self.notesEdit.toPlainText()
        self.accept()

    def cancelPressed(self):
        print('Reject')
        self.reject()

    def closeDealClicked(self):
        print('Accept')
        closeDate = datetime.now()
        self.closeDateLabel.setText(closeDate.strftime("%d/%m/%Y %H:%M"))
        self.deal.close_date = self.closeDateLabel.text()
        self.accept()
