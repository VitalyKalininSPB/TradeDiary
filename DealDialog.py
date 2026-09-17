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
import risk_plan
import risk_settings

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
        self.amountEdit.editingFinished.connect(self._on_risk_input_changed)
        self.priceEdit.editingFinished.connect(self._on_risk_input_changed)
        self.stoplossEdit.editingFinished.connect(self._on_risk_input_changed)
        self.desiredNotionalEdit.editingFinished.connect(
            self.desiredNotionalChanged)

        self.openDate = datetime.now()
        self.openDateLabel.setText(self.openDate.strftime("%d/%m/%Y %H:%M"))

        self._equity_usd = 0.0
        self._updating_risk = False
        self._update_risk_plan()

    def setData(self, balance):
        self._balance = balance
        print("Balance === " + str(self._balance))

    def setEquityUsd(self, equity_usd):
        self._equity_usd = float(equity_usd or 0.0)
        self._update_risk_plan()

    # --------------------------------------------------------- risk planning
    def _deal_currency(self):
        return getattr(self, '_currency', '') or ''

    def _usd_rate(self):
        if self._deal_currency() == markets.RUB:
            rate = markets.fetch_usd_rate()
            return rate if rate else 1.0
        return 1.0

    def _update_risk_plan(self):
        """Пересчитать блок «Risk plan» из текущих полей формы."""
        if self._updating_risk:
            return
        try:
            entry = float(self.priceEdit.text()) if self.priceEdit.text() else 0.0
            stop = float(self.stoplossEdit.text()) if self.stoplossEdit.text() else 0.0
            amount = float(self.amountEdit.text()) if self.amountEdit.text() else 0.0
        except ValueError:
            entry = stop = amount = 0.0
        direction = getattr(self, '_direction', Direction.LONG)
        plan = risk_plan.build_risk_plan(
            entry, stop, amount, direction,
            self._equity_usd, usd_rate=self._usd_rate(),
            max_notional_usd=risk_settings.max_notional_per_idea_usd(),
            max_risk_pct=risk_settings.max_risk_per_trade_pct())
        m = plan['metrics']
        sign = markets.CURRENCY_SIGN.get(self._deal_currency(), 'pt')
        self.riskPerShareLabel.setText(
            'Risk per share: {}{:.2f}'.format(sign, m['risk_per_share']))
        self.positionValueLabel.setText(
            'Position value: {}{:,.0f}'.format(sign, m['position_value']))
        if plan['risk_pct'] is not None:
            self.riskAtStopLabel.setText(
                'Risk at stop: {}{:,.0f} ({:.2f}% of equity)'.format(
                    sign, m['risk_at_stop'], plan['risk_pct']))
        else:
            self.riskAtStopLabel.setText(
                'Risk at stop: {}{:,.0f}'.format(sign, m['risk_at_stop']))
        self.stopLossErrorLabel.setText('')
        for b in plan['blockers']:
            if b.startswith('Stop-loss'):
                self.stopLossErrorLabel.setText(b)
                break
        if plan['warnings']:
            self.riskWarnLabel.setText('\n'.join(plan['warnings']))
            self.riskWarnLabel.setStyleSheet('color: #f0c14b;')
        else:
            self.riskWarnLabel.setText('')
            self.riskWarnLabel.setStyleSheet('')

    def _on_risk_input_changed(self):
        self._update_risk_plan()

    def desiredNotionalChanged(self):
        """Пользователь ввёл желаемую сумму в USD -> пересчитать количество."""
        if self._updating_risk:
            return
        try:
            desired = float(self.desiredNotionalEdit.text())
        except ValueError:
            return
        if desired <= 0:
            return
        entry_usd = 0.0
        try:
            entry = float(self.priceEdit.text()) if self.priceEdit.text() else 0.0
            entry_usd = entry / self._usd_rate()
        except (ValueError, ZeroDivisionError):
            entry_usd = 0.0
        qty = risk_plan.quantity_from_notional(desired, entry_usd)
        if qty is None or qty <= 0:
            self._update_risk_plan()
            return
        self._updating_risk = True
        try:
            self.amountEdit.setText(str(qty))
        finally:
            self._updating_risk = False
        self._update_risk_plan()

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
        deal = self.makeDeal()
        self._equity_usd = getattr(self, '_equity_usd', 0.0) or 0.0
        if not FutureUtil.is_future(deal):
            ok, reason = self._assessments_ok()
            if not ok:
                self.infoLabel.setText(
                    reason + '. Сделка запрещена: сначала заверши Quant и '
                    'Qual Assessment для этого тикера.')
                self._show_goat(
                    'Запрет: {} для {}. Сначала заверши Quant и Qual '
                    'Assessment — только потом открывай сделку.'.format(
                        reason, deal.ticker))
                return
        plan = risk_plan.build_risk_plan(
            deal.stock_price, deal.stop_loss, deal.amount,
            deal.direction, self._equity_usd, usd_rate=self._usd_rate(),
            max_notional_usd=risk_settings.max_notional_per_idea_usd(),
            max_risk_pct=risk_settings.max_risk_per_trade_pct())
        if not plan['ok']:
            self.infoLabel.setText('; '.join(plan['blockers']))
            self._update_risk_plan()
            return
        warnings = list(plan['warnings'])
        if warnings:
            self.infoLabel.setText('\n'.join(warnings))
            print('Risk plan warnings')
            choice = QtWidgets.QMessageBox.question(
                self,
                'Risk warning',
                '\n'.join(warnings) + '\n\nDo you want to continue?',
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if choice != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.riskManager = RiskManager()
        self.riskManager.balance = self._balance
        self.riskManager.deal = self.makeDeal()
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

    def _assessments_ok(self):
        """Для сделки нужны оба Assessment: Quant и Qual (в watchlist)."""
        from watchlist import find as watchlist_find
        from watchlist import get_quant, get_qual
        ticker = (self.ticketEdit.text() or '').strip().upper()
        if not ticker:
            return True, ''
        entry = watchlist_find(ticker) or {}
        missing = []
        if get_quant(entry) is None:
            missing.append('Quant')
        if get_qual(entry) is None:
            missing.append('Qual')
        if missing:
            names = ' и '.join(missing)
            return False, 'Не пройден Assessment: {}'.format(names)
        return True, ''

    def _show_goat(self, advice):
        from qualitative_dialog import GoatAssistant
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        if not advice:
            return
        self._goat = GoatAssistant('', self, advice=advice, auto_hide_ms=10000)
        self._goat.show()

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
