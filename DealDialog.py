# This Python file uses the following encoding: utf-8
from PySide6.QtWidgets import QApplication, QDialog
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QTimer, QThread, Signal
from qt_loader import loadUi

from enum import Enum
from datetime import datetime
from dataclasses import dataclass

from deals import AssetType, Deal, Direction, TRADE_SYSTEMS, trade_system_name
import futures
import markets
import logo
import risk_plan
import risk_settings
import technical_timing

_TXT = '#dcdce0'
_MUTED = '#9aa0aa'


def _esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;')


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
          if getattr(deal, 'asset_type', None) == AssetType.FUTURE:
              return True
          if futures.is_supported_future(getattr(deal, 'ticker', '')):
              return True
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



class _FutureSpecThread(QThread):
    """Фоновая загрузка спецификации фьючерса с ISS (сеть вне UI-потока)."""
    resolved = Signal(str, object)   # (запрошенный тикер, FutureSpec | None)

    def __init__(self, ticker, parent=None):
        super().__init__(parent)
        self._ticker = ticker

    def run(self):
        spec = None
        try:
            spec = futures.resolve(self._ticker)
            if spec is not None:
                markets.fetch_usd_rate()   # прогреть кэш курса для risk plan
        except Exception:
            spec = None
        self.resolved.emit(self._ticker, spec)


class RiskManager:
    balance = 0.0
    warning = ''
    usd_rate = 1.0

    def checkRisk(self):

        if getattr(self.deal, 'asset_type', None) == AssetType.FUTURE \
                and self.deal.point_value:
            # ₽ на контракт -> USD, баланс ведётся в USD.
            riskPerStock = futures.risk_rub(
                self.deal.stock_price, self.deal.stop_loss, 1,
                self.deal.point_value) / (self.usd_rate or 1.0)
        elif FutureUtil.is_future(self.deal):
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
        self._future_spec = None
        self._futureThread = None
        self._futureThreads = []
        self._build_future_info()
        self._update_risk_plan()

        self.resize(600, 800)
        self.buttonBox_2.setGeometry(10, 762, 341, 32)
        self._build_tech_context()

    # ---------------------------------------------------------------- futures
    def _build_future_info(self):
        """Строка со спецификацией фьючерса (контракт, пункт, ГО, экспирация)."""
        self.futureInfoLabel = QtWidgets.QLabel('', self)
        self.futureInfoLabel.setGeometry(300, 112, 290, 64)
        self.futureInfoLabel.setWordWrap(True)
        self.futureInfoLabel.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.futureInfoLabel.setStyleSheet(
            'color: {}; font-size: 10px;'.format(_MUTED))
        self.futureInfoLabel.setVisible(False)

    def isFuture(self):
        return self._future_spec is not None

    def _start_future_lookup(self, ticker):
        """Запустить фоновую загрузку спецификации (UI не блокируется)."""
        self.futureInfoLabel.setVisible(True)
        self.futureInfoLabel.setText('Загружаю спецификацию {} с Мосбиржи…'
                                     .format(_esc(ticker.upper())))
        t = _FutureSpecThread(ticker, self)
        t.resolved.connect(self._on_future_resolved)
        self._futureThread = t
        self._futureThreads.append(t)
        t.finished.connect(lambda th=t: self._futureThreads.remove(th)
                           if th in self._futureThreads else None)
        t.start()

    def _on_future_resolved(self, requested, spec):
        # Игнорируем устаревший ответ, если тикер уже сменили.
        current = (self.ticketEdit.text() or '').strip().upper()
        if requested.strip().upper() != current and not (
                spec is not None and current in (spec.secid.upper(),
                                                 spec.shortname.upper())):
            return
        if spec is None:
            self._future_spec = None
            self.futureInfoLabel.setText(
                '<span style="color:#ef5350;">Контракт {} не найден на FORTS '
                '(или нет связи с ISS).</span>'.format(_esc(requested.upper())))
            self._update_risk_plan()
            return
        self._future_spec = spec
        self.ticketEdit.setText(spec.shortname)
        self._currency = markets.RUB   # расчёты по FORTS — в рублях
        for name in ('priceUnitLabel', 'slUnitLabel', 'tpUnitLabel'):
            if hasattr(self, name):
                getattr(self, name).setText('$')
        if spec.price:
            self.priceEdit.setText(str(spec.price))
        self.label_4.setText('Contracts:')
        self.riskPlanGroup.setTitle('Risk plan (futures, per contract)')
        self.setLogo(spec.asset, markets.MOEX)
        self._render_future_info()
        self._refresh_future_rub_labels()
        self._update_risk_plan()
        self.loadTechnicalContext(spec.shortname)

    def _render_future_info(self):
        spec = self._future_spec
        if spec is None:
            return
        name = futures.SUPPORTED_ASSETS.get(spec.asset, spec.asset)
        days = spec.days_to_expiry()
        lines = [
            '<b style="color:{};">{} · {} ({})</b>'.format(
                _TXT, _esc(name), _esc(spec.shortname), _esc(spec.secid)),
            '1 контракт = {} bbl · 1$ цены = {:,.2f} ₽'.format(
                spec.lot_volume, spec.point_value).replace(',', ' '),
            'ГО: {:,.0f} ₽ / контракт'.format(
                spec.initial_margin).replace(',', ' '),
            'Экспирация: {}{}'.format(
                _esc(spec.last_trade_date),
                ' (через {} дн.)'.format(days) if days is not None else ''),
        ]
        blocker, warning = futures.expiry_issue(spec.last_trade_date)
        if blocker or warning:
            lines.append('<span style="color:#f0c14b;">⚠ {}</span>'.format(
                _esc(blocker or warning)))
        self.futureInfoLabel.setText('<br>'.join(lines))

    def _clear_future(self):
        if self._future_spec is None and not self.futureInfoLabel.isVisible():
            return
        self._future_spec = None
        self.futureInfoLabel.setVisible(False)
        self.futureInfoLabel.setText('')
        self.label_4.setText('Amount:')
        self.riskPlanGroup.setTitle('Risk plan')
        for name in ('priceRubLabel', 'stopLossRubLabel', 'takeProfitRubLabel'):
            getattr(self, name).setText('')

    def _rub_per_contract(self, price_text):
        spec = self._future_spec
        try:
            value = float(price_text) if price_text else 0.0
        except ValueError:
            return ''
        if spec is None or value <= 0:
            return ''
        return '{:,.0f} ₽/контр.'.format(value * spec.point_value).replace(',', ' ')

    def _refresh_future_rub_labels(self):
        self.priceRubLabel.setText(self._rub_per_contract(self.priceEdit.text()))
        self.stopLossRubLabel.setText(
            self._rub_per_contract(self.stoplossEdit.text()))
        self.takeProfitRubLabel.setText(
            self._rub_per_contract(self.takeprofitEdit.text()))

    def done(self, result):
        # Потоки должны завершиться до уничтожения диалога.
        for t in list(self._futureThreads):
            if t.isRunning():
                t.wait(5000)
        super().done(result)

    def _build_tech_context(self):
        """Компактный блок «Technical context» (только чтение из БД).

        Позиционируется в свободной области между Risk plan и кнопками;
        deal.ui не трогаем, чтобы не перестраивать абсолютную геометрию.
        """
        self.techGroup = QtWidgets.QGroupBox('Technical context', self)
        self.techGroup.setGeometry(20, 655, 560, 100)
        lay = QtWidgets.QVBoxLayout(self.techGroup)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(4)
        self.techLabel = QtWidgets.QLabel(
            'Технический контекст не рассчитан — добавьте тикер в Watchlist '
            'и откройте «Technical timing».')
        self.techLabel.setWordWrap(True)
        self.techLabel.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.techLabel.setStyleSheet(
            'color: {}; font-size: 10px;'.format(_MUTED))
        lay.addWidget(self.techLabel, 1)
        self.techChartButton = QtWidgets.QPushButton('Chart')
        self.techChartButton.setStyleSheet('QPushButton { font-size: 10px; }')
        self.techChartButton.setCursor(
            QtCore.Qt.CursorShape.PointingHandCursor)
        self.techChartButton.clicked.connect(self._open_tech_chart)
        lay.addWidget(self.techChartButton, 0,
                      QtCore.Qt.AlignmentFlag.AlignRight)
        self._tech_result = None

    def loadTechnicalContext(self, ticker, hint=False):
        """Показать последний рассчитанный Technical timing (без пересчёта).

        Только чтение из кэша — никакой сети и расчётов на UI-потоке.
        `hint=True` (из «Open trade plan») — подсказка козы при мягком
        предупреждении о растянутости.
        """
        ticker = (ticker or '').strip()
        self._tech_result = None
        self.techChartButton.setVisible(False)
        if not ticker:
            self._tech_empty()
            return
        direction = ('short' if getattr(self, '_direction', Direction.LONG)
                     == Direction.SHORT else 'long')
        result = technical_timing.load_timing(ticker, direction) \
            or technical_timing.load_any_timing(ticker)
        if not result or result.get('status') == 'no_data':
            self._tech_empty()
            return
        self._tech_result = result
        self.techChartButton.setVisible(True)
        status = result.get('status') or 'no_data'
        color = result.get('status_color') or _MUTED
        warning = result.get('warning') or ''
        lines = [
            '<b style="color:{0};">{1}</b>'.format(
                color, _esc(result.get('status_txt') or status)),
            'Price vs SMA 200: {} · SMA 50/200: {}'.format(
                _esc(result.get('price_vs_sma200_txt') or '—'),
                _esc(result.get('cross_txt') or '—')),
            'RSI(14): {} · MACD: {}'.format(
                _esc(result.get('rsi_txt') or '—'),
                _esc(result.get('macd_txt') or '—')),
            'Stop reference: {}'.format(
                _esc(result.get('stop_ref') or '—')),
        ]
        if warning:
            lines.append(
                '<span style="color:#f0c14b;">⚠ {}</span>'.format(_esc(warning)))
        self.techLabel.setText('<br>'.join(lines))
        self.techLabel.setStyleSheet(
            'color: {}; font-size: 10px;'.format(_TXT))
        if hint and warning:
            self._show_goat(warning)

    def _tech_empty(self):
        self.techLabel.setText(
            'Технический контекст не рассчитан — добавьте тикер в Watchlist '
            'и откройте «Technical timing».')
        self.techLabel.setStyleSheet(
            'color: {}; font-size: 10px;'.format(_MUTED))

    def _open_tech_chart(self):
        ticker = (self.ticketEdit.text() or '').strip()
        if not ticker:
            return
        from ma_chart_dialog import MAChartDialog
        _market, currency = markets.market_currency(ticker)
        dlg = MAChartDialog(ticker, currency or markets.USD, '', '', self)
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()

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
        spec = getattr(self, '_future_spec', None)
        plan = risk_plan.build_risk_plan(
            entry, stop, amount, direction,
            self._equity_usd, usd_rate=self._usd_rate(),
            max_notional_usd=risk_settings.max_notional_per_idea_usd(),
            max_risk_pct=risk_settings.max_risk_per_trade_pct(),
            multiplier=spec.point_value if spec else 1.0)
        m = plan['metrics']
        sign = markets.CURRENCY_SIGN.get(self._deal_currency(), 'pt')
        if spec is not None:
            margin = futures.margin_rub(amount, spec.initial_margin)
            self.riskPerShareLabel.setText(
                'Risk per contract: {}{:,.0f} · Margin (ГО): {}{:,.0f}'.format(
                    sign, m['risk_per_share'], sign, margin))
        else:
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
            entry = entry_usd = 0.0
        spec = getattr(self, '_future_spec', None)
        if spec is not None:
            qty = futures.contracts_from_notional(
                desired, entry, spec.point_value, self._usd_rate())
        else:
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
        ticker = (self.ticketEdit.text() or '').strip()
        if ticker:
            self.loadTechnicalContext(ticker)

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
        spec = getattr(self, '_future_spec', None)
        if spec is not None:
            deal.asset_type = AssetType.FUTURE
            deal.currency = markets.RUB
            deal.point_value = spec.point_value
            deal.margin = spec.initial_margin
            deal.expiry = spec.last_trade_date
        return deal

    def okPressed(self):
        print('Accept')
        deal = self.makeDeal()
        self._equity_usd = getattr(self, '_equity_usd', 0.0) or 0.0
        if futures.is_supported_future(deal.ticker) and not deal.is_future:
            self.infoLabel.setText(
                'Спецификация фьючерса ещё не загружена — дождитесь данных '
                'Мосбиржи или проверьте тикер.')
            return
        if deal.is_future:
            blocker, _warn = futures.expiry_issue(deal.expiry)
            if blocker:
                self.infoLabel.setText(blocker)
                return
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
            max_risk_pct=risk_settings.max_risk_per_trade_pct(),
            multiplier=deal.point_value if deal.is_future else 1.0)
        if not plan['ok']:
            self.infoLabel.setText('; '.join(plan['blockers']))
            self._update_risk_plan()
            return
        warnings = list(plan['warnings'])
        if deal.is_future:
            _b, exp_warn = futures.expiry_issue(deal.expiry)
            if exp_warn:
                warnings.append(exp_warn)
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
        self.riskManager.usd_rate = self._usd_rate()
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
        ticker = (self.ticketEdit.text() or '').strip()
        spec = self._future_spec
        if spec is not None and ticker.upper() in (spec.secid.upper(),
                                                   spec.shortname.upper()):
            return 'Future'   # уже загружено (например, после setText)
        if futures.is_supported_future(ticker):
            self._future_spec = None
            self._start_future_lookup(ticker)
            return 'Future'
        self._clear_future()
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.setCurrency('')
            self.priceRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stock_price)))
            return 'Future'
        ticker = self.ticketEdit.text().strip()
        if not ticker:
            self.setLogo('', None)
            self.loadTechnicalContext('')
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
        self.loadTechnicalContext(ticker)
        return 'Stock'

    def priceChanged(self):
        if self._future_spec is not None:
            self.priceRubLabel.setText(self._rub_per_contract(self.priceEdit.text()))
            return 'Future'
        print('TickerChanged')
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.setCurrency('')
            self.priceRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stock_price)) + ' RUB')
            return 'Future'
        return 'Stock'

    def stopLossChanged(self):
        if self._future_spec is not None:
            self.stopLossRubLabel.setText(self._rub_per_contract(self.stoplossEdit.text()))
            return 'Future'
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.setCurrency('')
            self.stopLossRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.stop_loss)) + ' RUB')
            return 'Future'
        return 'Stock'

    def takeProfitChanged(self):
        if self._future_spec is not None:
            self.takeProfitRubLabel.setText(self._rub_per_contract(self.takeprofitEdit.text()))
            return 'Future'
        deal = self.makeDeal()
        if FutureUtil.is_future(deal):
            self.setCurrency('')
            self.takeProfitRubLabel.setText(str(FutureUtil.convert(deal.ticker, deal.take_profit)) + ' RUB')
            return 'Future'
        return 'Stock'
