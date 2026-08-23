# This Python file uses the following encoding: utf-8
from PySide6.QtWidgets import QApplication, QDialog
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QTimer
from qt_loader import loadUi

from enum import Enum
from datetime import datetime
from dataclasses import dataclass
import markets
import logo

class DirectionType(Enum):
    BUY = 1
    SELL = 2

TRADE_SYSTEMS = ['Average MA', 'MACD']


def trade_system_name(value):
    """Human-readable name for a stored tradeSystem index."""
    try:
        idx = int(value or 0)
    except (TypeError, ValueError):
        idx = 0
    if 0 <= idx < len(TRADE_SYSTEMS):
        return TRADE_SYSTEMS[idx]
    return TRADE_SYSTEMS[0]

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
    currency = ''
    unit = 'pt'

    def toArray(self):
        row = [self.ticker, self.stockPrice, self.stocksAmount, self.openDate,
               self.initPrice, self.takeProfit, self.stopLoss, self.tradeSystem,
               self.result, self.closeDate, self.whatsNext, self.analysisNotes,
               self.currency]
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
        deal.currency = array[12] if len(array) > 12 else ''
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
        self.logoLabel.setFixedSize(48, 48)
        self.logoLabel.setVisible(True)
        self.buttonBox_2.accepted.connect(self.okPressed)
        self.buttonBox_2.rejected.connect(self.cancelPressed)
        self._tickerDebounce = QTimer(self)
        self._tickerDebounce.setSingleShot(True)
        self._tickerDebounce.timeout.connect(self.tickerChanged)
        self.ticketEdit.textEdited.connect(lambda: self._tickerDebounce.start(700))
        self.ticketEdit.returnPressed.connect(self.tickerChanged)
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
        deal.currency = getattr(self, '_currency', '') or ''
        deal.tradeSystem = self.comboBox.currentIndex() if hasattr(self, 'comboBox') else 0
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
            choice = QtWidgets.QMessageBox.question(
                self,
                'Risk warning',
                self.riskManager.warning + '. Do you want to continue?',
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if choice == QtWidgets.QMessageBox.StandardButton.Yes:
                self.accept()

    def cancelPressed(self):
        print('Reject')
        self.reject()

    def setLogo(self, ticker, market=None):
        if not hasattr(self, 'logoLabel'):
            return
        if ticker:
            pm = None
            # MOEX tickers (or unknown ones) -> Wikipedia-based real logo first.
            if market in (None, markets.MOEX):
                pm = logo.moex_logo_pixmap(ticker)
            # World / anything else -> Parqet, falling back to MOEX source too.
            if pm is None and market != markets.MOEX:
                pm = logo.logo_pixmap(ticker)
            # Only show the letter avatar when no real logo was found anywhere.
            if pm is None:
                pm = logo.placeholder_pixmap(ticker)
        else:
            pm = QtGui.QPixmap()
        self.logoLabel.setPixmap(
            pm.scaled(self.logoLabel.size(),
                      QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                      QtCore.Qt.TransformationMode.SmoothTransformation)
            if not pm.isNull() else QtGui.QPixmap())

    def setCurrency(self, currency):
        self._currency = currency
        sign = markets.CURRENCY_SIGN.get(currency, 'pt')
        if hasattr(self, 'priceUnitLabel'):
            self.priceUnitLabel.setText(sign)
        if hasattr(self, 'slUnitLabel'):
            self.slUnitLabel.setText(sign)
        if hasattr(self, 'tpUnitLabel'):
            self.tpUnitLabel.setText(sign)

    def tickerChanged(self):
        print('TickerChanged')
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.setCurrency('')
            self.priceRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stockPrice)))
            return 'Future'
        ticker = self.ticketEdit.text().strip()
        if not ticker:
            self.setLogo('', None)
            return 'Stock'
        market, currency = markets.market_currency(ticker)
        self.setLogo(ticker, market)
        if market is not None:
            self.setCurrency(currency)
            if currency == markets.RUB:
                price = markets.fetch_moex_price(ticker)
            else:
                price = markets.fetch_world_price(ticker)
            if price is not None:
                self.priceEdit.setText(str(price))
        return 'Stock'

    def priceChanged(self):
        print('TickerChanged')
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.setCurrency('')
            self.priceRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stockPrice)) + ' RUB')
            return 'Future'
        return 'Stock'

    def stopLossChanged(self):
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.setCurrency('')
            self.stopLossRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stopLoss)) + ' RUB')
            return 'Future'
        return 'Stock'

    def takeProfitChanged(self):
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.setCurrency('')
            self.takeProfitRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.takeProfit)) + ' RUB')
            return 'Future'
        return 'Stock'
