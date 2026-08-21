# This Python file uses the following encoding: utf-8
from PySide6.QtWidgets import QApplication, QDialog
from PySide6 import QtCore, QtGui, QtWidgets
from qt_loader import loadUi

from enum import Enum
from datetime import datetime
from dataclasses import dataclass

class DirectionType(Enum):
    BUY = 1
    SELL = 2

class Deal:
    ticker = ''
    stockPrice = 0
    stocksAmount = 0
    openDate = ''
    initPrice = 0
    takeProfit = 0
    stopLoss = 0
    tradeSystem = 0
    result = 0
    closeDate = ''
    whatsNext = ''
    analysisNotes = ''
    unit = 'pt'

    def toArray(self):
        row = []
        row.append(self.ticker)
        row.append(self.stockPrice)
        row.append(self.stocksAmount)
        row.append(self.openDate)
        row.append(self.initPrice)
        row.append(self.takeProfit)
        row.append(self.stopLoss)
        row.append(self.tradeSystem)
        row.append(self.result)
        row.append(self.closeDate)
        row.append(self.whatsNext)
        row.append(self.analysisNotes)
        return row

    @staticmethod
    def fromArray(array):
        deal = Deal()
        deal.ticker = array[0]
        deal.stockPrice = array[1]
        deal.stocksAmount = array[2]
        deal.openDate = array[3]
        deal.initPrice = array[4]
        deal.takeProfit = array[5]
        deal.stopLoss = array[6]
        deal.tradeSystem = array[7]
        deal.result = array[8]
        deal.closeDate = array[9]
        deal.whatsNext = array[10]
        deal.analysisNotes = array[11]
        return deal

@dataclass
class FutureInfo:
    ticker: str = ''
    pointPrice: float = 0.0


class FutureUtil(object):

      elements = [FutureInfo('NASD',745.89),\
                  FutureInfo('GOLD',1000.1)]
      #futureBases = ['NASD','GOLD','PLD','BR','Si','WHEAT','NG']

      @staticmethod
      def is_future(deal):
          for i in FutureUtil.elements:
              if deal.ticker.startswith(str(i.ticker+'-')):
                  return True
          return False

      @staticmethod
      def convert(ticker, value):
          for i in FutureUtil.elements:
            if ticker.startswith(str(i.ticker+'-')):
                return value*i.pointPrice

          # try exception
          return 0



class RiskManager:
    balance = 0.0
    warning = ''
    def checkRisk(self):

        if FutureUtil.is_future(self.deal):
            riskPerStock = FutureUtil.convert(self.deal.ticker, self.deal.stockPrice-self.deal.stopLoss)
        else:
            riskPerStock = self.deal.stockPrice-self.deal.stopLoss

        print("Risk per stock:" + str(riskPerStock))
        print("Maximum risk:" + str(self.balance * 0.02))
        if riskPerStock*self.deal.stocksAmount > self.balance * 0.02:
            self.warning = 'Risk is exceeded 2% of balance'
            return False
        else:
            self.warning = ''
            return True

class DealDialog(QDialog):
    def __init__(self):
        super().__init__()
        loadUi("deal.ui", self)
        self.buttonBox_2.accepted.connect(self.okPressed)
        self.buttonBox_2.rejected.connect(self.cancelPressed)
        self.ticketEdit.editingFinished.connect(self.tickerChanged)
        self.priceEdit.editingFinished.connect(self.priceChanged)
        self.stoplossEdit.editingFinished.connect(self.stopLossChanged)
        self.takeprofitEdit.editingFinished.connect(self.takeProfitChanged)

        self.openDate = datetime.now()
        self.openDateLabel.setText(self.openDate.strftime("%d/%m/%Y %H:%M"))


    def setData(self, balance):
        self._balance = balance
        print("Balance === " + str(self._balance))

    def setMode(self, mode):
        if mode == DirectionType.BUY:
            self.label_5.setText('Stop Loss (<=):')
            self.label_6.setText('Take Profit (>=):')
        else:
            self.label_5.setText('Stop Loss (>=):')
            self.label_6.setText('Take Profit (<=):')

    def makeDeal(self):
        deal = Deal()
        deal.ticker = self.ticketEdit.text()
        deal.stockPrice = float( self.priceEdit.text() ) if self.priceEdit.text() else 0
        deal.initPrice = float( self.priceEdit.text() ) if self.priceEdit.text() else 0
        deal.stocksAmount = float( self.amountEdit.text() ) if self.amountEdit.text() else 0
        deal.stopLoss = float( self.stoplossEdit.text() ) if self.stoplossEdit.text() else 0
        deal.takeProfit = float( self.takeprofitEdit.text() ) if self.takeprofitEdit.text() else 0
        deal.openDate = self.openDateLabel.text()
        return deal

    def okPressed(self):
        print('Accept')
        self.riskManager = RiskManager()
        self.riskManager.balance = 0 #self._balance
        self.riskManager.deal = self.makeDeal();
        self.riskManager.balance = self._balance
        if self.riskManager.checkRisk():
            self.accept()
        else:
            self.infoLabel.setText(self.riskManager.warning)
            print('Risk is too much')

    def cancelPressed(self):
        print('Reject')
        self.reject()

    def tickerChanged(self):
        print('TickerChanged')
        # ???
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.priceRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stockPrice)))
            return 'Future'
        else:
            return 'Stock'

    def priceChanged(self):
        print('TickerChanged')
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.priceRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stockPrice)) + ' RUB')
            return 'Future'
        else:
            return 'Stock'

    def stopLossChanged(self):
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.stopLossRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stopLoss)) + ' RUB')
            return 'Future'
        else:
            return 'Stock'

    def takeProfitChanged(self):
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.takeProfitRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.takeProfit)) + ' RUB')
            return 'Future'
        else:
            return 'Stock'
