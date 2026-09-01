# This Python file uses the following encoding: utf-8
from PySide6.QtWidgets import QApplication, QDialog
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QTimer
from qt_loader import loadUi

from enum import Enum
from datetime import datetime
from dataclasses import dataclass

from deals import Deal, Direction, TRADE_SYSTEMS, trade_system_name
import markets
import logo

class DirectionType(Enum):
    BUY = 1
    SELL = 2

# Совместимость: TRADE_SYSTEMS / trade_system_name теперь живут в deals.py;
# оставляем алиасы, чтобы внешние импорты не падали (см. DealDialog.py выше).

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
            riskPerStock = FutureUtil.convert(self.deal.ticker, self.deal.stock_price-self.deal.stop_loss)
        else:
            riskPerStock = self.deal.stock_price-self.deal.stop_loss

        print("Risk per stock:" + str(riskPerStock))
        print("Maximum risk:" + str(self.balance * 0.02))
        if riskPerStock*self.deal.amount > self.balance * 0.02:
            self.warning = 'Risk is exceeded 2% of balance'
            return False
        else:
            self.warning = ''
            return True

class DealDialog(QDialog):
    def __init__(self):
        super().__init__()
        loadUi("deal.ui", self)
        self._direction = Direction.LONG
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
            self._direction = Direction.LONG
            self.label_5.setText('Stop Loss (<=):')
            self.label_6.setText('Take Profit (>=):')
        else:
            self._direction = Direction.SHORT
            self.label_5.setText('Stop Loss (>=):')
            self.label_6.setText('Take Profit (<=):')

    def makeDeal(self):
        deal = Deal()
        deal.ticker = self.ticketEdit.text()
        deal.stock_price = float(self.priceEdit.text()) if self.priceEdit.text() else 0
        deal.init_price = float(self.priceEdit.text()) if self.priceEdit.text() else 0
        deal.amount = float(self.amountEdit.text()) if self.amountEdit.text() else 0
        deal.stop_loss = float(self.stoplossEdit.text()) if self.stoplossEdit.text() else 0
        deal.take_profit = float(self.takeprofitEdit.text()) if self.takeprofitEdit.text() else 0
        deal.open_date = self.openDateLabel.text()
        deal.currency = getattr(self, '_currency', '') or ''
        deal.trade_system = self.comboBox.currentIndex() if hasattr(self, 'comboBox') else 0
        deal.direction = self._direction
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
            self.priceRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stock_price)))
            return 'Future'
        ticker = self.ticketEdit.text().strip()
        if not ticker:
            self.setLogo('', None)
            return 'Stock'
        market, currency = markets.market_currency(ticker)
        if market is not None:
            self.setCurrency(currency)
            if currency == markets.RUB:
                price = markets.fetch_moex_price(ticker)
            else:
                price = markets.fetch_world_price(ticker)
            if price is not None:
                self.priceEdit.setText(str(price))
        self.setLogo(ticker, market)
        return 'Stock'

    def priceChanged(self):
        print('TickerChanged')
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.setCurrency('')
            self.priceRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stock_price)) + ' RUB')
            return 'Future'
        return 'Stock'

    def stopLossChanged(self):
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.setCurrency('')
            self.stopLossRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stop_loss)) + ' RUB')
            return 'Future'
        return 'Stock'

    def takeProfitChanged(self):
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.setCurrency('')
            self.takeProfitRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.take_profit)) + ' RUB')
            return 'Future'
        return 'Stock'
