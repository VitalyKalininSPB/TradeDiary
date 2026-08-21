# This Python file uses the following encoding: utf-8
from PySide6.QtWidgets import QApplication, QDialog
from PySide6 import QtCore, QtGui, QtWidgets
from qt_loader import loadUi

from DealDialog import Deal

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


    def setData(self, data, balance):
        self._balance = balance

        self.deal = Deal.fromArray(data)
        self.ticketEdit.setText(self.deal.ticker)
        self.initpriceEdit.setText(str(self.deal.initPrice))
        self.priceEdit.setText(str(self.deal.stockPrice))
        self.priceEdit.setEnabled(not self.deal.closeDate)
        self.amountEdit.setText(str(self.deal.stocksAmount))
        self.openDateLabel.setText(self.deal.openDate)
        self.closeDateLabel.setText(self.deal.closeDate)
        self.takeprofitEdit.setText(str(self.deal.takeProfit))
        self.stoplossEdit.setText(str(self.deal.stopLoss))
        #self.tradesystemList.setText(self.deal.tradeSystem)
        self.whatsNextEdit.setText(self.deal.whatsNext)
        self.notesEdit.setText(self.deal.analysisNotes)

        if not self.deal.closeDate:
            self.closeDealButton.setEnabled(True)
        else:
            self.closeDealButton.setEnabled(False)

        print("Balance === " + str(self._balance))

    def okPressed(self):
        print('Accept')
        self.accept()

    def cancelPressed(self):
        print('Reject')
        self.reject()

    def closeDealClicked(self):
        print('Accept')
        closeDate = datetime.now()
        self.closeDateLabel.setText(closeDate.strftime("%d/%m/%Y %H:%M"))
        self.accept()
