# This Python file uses the following encoding: utf-8
import sys
import os
import logging


from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import QApplication
from qt_loader import loadUi

from EditDealDialog import EditDealDialog

from DealDialog import DealDialog
from DealDialog import DirectionType
from DealDialog import FutureUtil

from deals import Deal, Direction, trade_system_name
from persistence import load as load_diary, save as save_diary
import risk
import markets
import price_history
import simple_mode_settings
import portfolio_context
import risk_settings

log = logging.getLogger(__name__)

class TableModel(QtCore.QAbstractTableModel):

    header_labels = ['Ticker',\
            'Price', \
            'Amount', \
            'Open At', \
            'InitPrice', \
            'TP', \
            'SL', \
            'System', \
            'Result', \
            'Close At', \
            'What\'s next', \
            'Notes', \
            'Chart', \
            'Candles', \
            'Delete']

    # Имена атрибутов Deal для колонок 0..11 (12/13/14 — кнопки).
    _COL_ATTRS = ['ticker', 'stock_price', 'amount', 'open_date', 'init_price',
                  'take_profit', 'stop_loss', 'trade_system', 'result',
                  'close_date', 'whats_next', 'notes']

    def __init__(self, data):
        super(TableModel, self).__init__()
        self._data = data

    def data(self, index, role):
        deal = self._data[index.row()]
        col = index.column()
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if col == 7:
                return trade_system_name(deal.trade_system)
            if col in (12, 13, 14):
                return ''
            return getattr(deal, self._COL_ATTRS[col])
        if role == QtCore.Qt.ItemDataRole.BackgroundRole:
            if deal.init_price > deal.stock_price:
                return QtGui.QBrush(QtGui.QColor(42, 106, 64))
            elif deal.init_price < deal.stock_price:
                return QtGui.QBrush(QtGui.QColor(140, 46, 46))
            else:
                return QtGui.QBrush(QtGui.QColor(28, 29, 34))
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            if deal.init_price != deal.stock_price:
                return QtGui.QBrush(QtGui.QColor(255, 255, 255))

    def setData(self, data):
        self._data = data
        return True

    def rowCount(self, index):
        # The length of the outer list.
        return len(self._data)

    def columnCount(self, index):
        return len(self.header_labels)

    def removeRows(self, row, count, parent=QtCore.QModelIndex()):
        if row < 0 or row + count > len(self._data):
            return False
        self.beginRemoveRows(parent, row, row + count - 1)
        del self._data[row:row + count]
        self.endRemoveRows()
        return True


    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if role == QtCore.Qt.ItemDataRole.DisplayRole and orientation == QtCore.Qt.Orientation.Horizontal:
            return self.header_labels[section]
        return QtCore.QAbstractTableModel.headerData(self, section, orientation, role)


class OfficeAssistant(QtWidgets.QWidget):
    """Скрепка Clippy из картинки + жёлтая реплика (ради прикола, без анимации)."""

    def __init__(self, image_path="clippy.png"):
        super(OfficeAssistant, self).__init__(None)
        self._src = QtGui.QPixmap(image_path)
        if self._src.isNull():
            self._src = QtGui.QPixmap(10, 10)

        self._phrases = [
            "Это похоже на сделку?",
            "Осторожнее с рисками!",
            "Вы не забыли сохранить?",
            "Корреляция в норме?",
            "Шорти японскую йену!",
            "Элина, покупай газпром на 650 руб.",
        ]
        self._quote = "\n".join((self._phrases[-1], self._phrases[-2]))

        # Масштаб картинки под разумный размер (целиком на экране).
        target_h = 250
        self._pixmap = self._src.scaledToHeight(
            target_h, QtCore.Qt.TransformationMode.SmoothTransformation)
        bub_w = 420
        bub_h = 120
        self.setFixedSize(bub_w + 18 + self._pixmap.width(),
                          max(bub_h, self._pixmap.height()))

        self.setWindowFlags(QtCore.Qt.WindowType.Tool
                            | QtCore.Qt.WindowType.FramelessWindowHint
                            | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setToolTip("Кликните, чтобы я дал совет.")
        self._place()

    def _place(self):
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() - 8
        y = screen.center().y() - self.height() // 2
        y = max(screen.top() + 4, min(y, screen.bottom() - self.height() - 4))
        self.move(x, y)

    def mousePressEvent(self, event):
        import random
        self._quote = random.choice(self._phrases)
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        if self._quote is not None:
            self._drawBubble(p)

        bx = self.width() - self._pixmap.width() - 6
        by = max(6, (self.height() - self._pixmap.height()) // 2)
        p.drawPixmap(bx, by, self._pixmap)

        p.end()

    def _drawBubble(self, p):
        rect = QtCore.QRect(8, 6, self.width() - self._pixmap.width() - 26 - 16, 120)
        bubble = QtGui.QPainterPath()
        bubble.addRoundedRect(rect, 18, 18)
        tail = QtGui.QPainterPath()
        tail.moveTo(rect.right() - 30, rect.bottom() - 6)
        tail.lineTo(rect.right() + 6, rect.bottom() + 18)
        tail.lineTo(rect.right(), rect.bottom() - 2)
        tail.closeSubpath()
        bubble = bubble.united(tail)
        p.setPen(QtGui.QPen(QtGui.QColor(120, 96, 10), 2))
        p.setBrush(QtGui.QColor(255, 236, 148))
        p.drawPath(bubble)

        p.setPen(QtGui.QColor(60, 45, 5))
        f = QtGui.QFont('Sans', 12)
        f.setBold(True)
        p.setFont(f)
        p.drawText(rect.adjusted(16, 10, -16, -10),
                   QtCore.Qt.AlignmentFlag.AlignCenter, self._quote)


class _MacroRefreshThread(QtCore.QThread):
    """Recompute the macro thermometer and the NASDAQ regime off the UI thread.

    All data fetching happens here (background), so the main window never blocks
    on network or FRED cache refresh. Emits the fresh values back to the UI.
    """
    finished_ok = QtCore.Signal(int, str, str, bool, int)  # score, note, regime, late_cycle, fomc_new

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        from macro_dialog import compute_macro_score_cached, late_cycle_signal
        from index_dialog import _regime_cached
        score, note = 0, 'Нет данных'
        try:
            score, note = compute_macro_score_cached()
            if score is None:
                score, note = 0, 'Нет данных'
        except Exception:  # noqa: BLE001 - the UI must never crash on data issues
            score, note = 0, 'Ошибка расчёта'
        regime = 'neutral'
        try:
            regime = _regime_cached('NASDAQ100')
        except Exception:  # noqa: BLE001
            regime = 'neutral'
        late_cycle = False
        try:
            late_cycle = late_cycle_signal()[0]
        except Exception:  # noqa: BLE001
            late_cycle = False
        fomc_new = 0
        try:
            from fomc import refresh_fomc_if_stale, unread_count
            refresh_fomc_if_stale()
            fomc_new = unread_count()
        except Exception:  # noqa: BLE001
            fomc_new = 0
        self.finished_ok.emit(score, note, regime, late_cycle, fomc_new)


class _QuantAlertThread(QtCore.QThread):
    """Background check for sector signal changes at app startup (≤1 per 3 days)."""

    done = QtCore.Signal()

    def run(self):
        try:
            from quant_alerts import should_startup_check, mark_startup_check
            if should_startup_check():
                from sector_quant import run_sector_quant
                run_sector_quant(force=False)
                mark_startup_check()
        except Exception as e:  # noqa: BLE001 - never break startup
            print('Quant alerts: {}'.format(e))
        self.done.emit()


class _CatalystReminderThread(QtCore.QThread):
    """Background check of catalyst reminders (local SQLite, no network):
    события «за сутки до даты» (и просроченные)."""

    reminders = QtCore.Signal(list)

    def run(self):
        msgs = []
        ids = []
        try:
            import catalyst
            for e in catalyst.due_events():
                msgs.append(catalyst.reminder_text(e))
                ids.append(e['id'])
            if ids:
                catalyst.mark_notified(ids)
        except Exception as e:  # noqa: BLE001 - never break startup
            print('Catalyst reminder: {}'.format(e))
        self.reminders.emit(msgs)


class TradeDiary(QtWidgets.QMainWindow):
    def __init__(self):
        super(TradeDiary, self).__init__()
        self.load_ui()
        log.info("UI loaded")
        self.read_data()
        self.model = TableModel(self.data)
        self.tradeTableView.setModel(self.model)
        self.tradeTableView.clicked.connect(self.editClicked)
        self._chartButtons = []
        self._rebuildChartButtons()
        self.model.modelReset.connect(self._rebuildChartButtons)
        self.tradeTableView.horizontalHeader().setSectionResizeMode(
            12, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.tradeTableView.horizontalHeader().setSectionResizeMode(
            13, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.tradeTableView.horizontalHeader().setSectionResizeMode(
            14, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.longButton.clicked.connect(self.longClicked)
        self.shortButton.clicked.connect(self.shortClicked)
        self.updatePricesButton.clicked.connect(self.updatePricesClicked)
        self.balanceEdit.editingFinished.connect(self.balanceEdited)
        self.recalcBalance()
        self._fomc_new = 0
        self.setupMacro()
        self.setupCorrelation()
        self.quantitiveAssessmentButton.clicked.connect(self.quantitiveAssessmentClicked)
        self.qualitativeAssessmentButton.clicked.connect(self.qualitativeAssessmentClicked)
        self.correlationMatrixButton.clicked.connect(self.correlationMatrixClicked)
        self.macroButton.clicked.connect(self.macroClicked)
        self.indexButton.clicked.connect(self.indexClicked)
        self.commoditiesButton.clicked.connect(self.commoditiesClicked)
        self.statementsButton.clicked.connect(self.statementsClicked)
        self.todayMacroButton.clicked.connect(self.todayMacroClicked)
        self.watchlistButton.clicked.connect(self.watchlistClicked)
        self.clearDbButton.clicked.connect(self.clearDbClicked)
        self.recalcSlTpButton.clicked.connect(self.recalcSlTpClicked)
        self.dealHistoryButton.clicked.connect(self.dealHistoryClicked)
        self.tradeTableView.setColumnWidth(12, 70)
        self.tradeTableView.setColumnWidth(13, 80)
        self.tradeTableView.setColumnWidth(14, 70)
        self.simpleModeButton.toggled.connect(
            simple_mode_settings.set_simple_enabled)
        simple_mode_settings.simple_changed().connect(
            self._on_simple_mode_changed)

    def _on_simple_mode_changed(self, on):
        """Синхронизировать тумблер, если режим поменяли вне главного окна."""
        self.simpleModeButton.setChecked(on)
        if hasattr(self, 'portfolioContextFrame'):
            self.portfolioContextFrame.setVisible(on)

    def _rebuildChartButtons(self):
        for w in self._chartButtons:
            w.setParent(None)
            w.deleteLater()
        self._chartButtons = []
        if not hasattr(self, 'tradeTableView') or self.tradeTableView.model() is None:
            return
        rows = getattr(self, 'data', [])
        for row in range(len(rows)):
            ma_btn = QtWidgets.QPushButton('Chart')
            ma_btn.setFixedSize(62, 24)
            ma_btn.clicked.connect(lambda checked=False, r=row: self.chartClicked(r))
            self.tradeTableView.setIndexWidget(self.model.index(row, 12), ma_btn)
            self._chartButtons.append(ma_btn)

            ca_btn = QtWidgets.QPushButton('Candles')
            ca_btn.setFixedSize(74, 24)
            ca_btn.clicked.connect(lambda checked=False, r=row: self.candlesClicked(r))
            self.tradeTableView.setIndexWidget(self.model.index(row, 13), ca_btn)
            self._chartButtons.append(ca_btn)

            del_btn = QtWidgets.QPushButton('Delete')
            del_btn.setFixedSize(62, 24)
            del_btn.clicked.connect(lambda checked=False, r=row: self.deleteClicked(r))
            self.tradeTableView.setIndexWidget(self.model.index(row, 14), del_btn)
            self._chartButtons.append(del_btn)

    def _openNonModal(self, kind, row):
        """Open a chart dialog non-modally so several can be visible at once."""
        if row >= len(self.data):
            return
        r = self.data[row]
        if kind == 'ma':
            from ma_chart_dialog import MAChartDialog
            dlg = MAChartDialog(str(r[0] or ''), str(r[12] or ''), r[3], r[9], self)
        else:
            from candles_dialog import CandlesDialog
            dlg = CandlesDialog(str(r[0] or ''), str(r[12] or ''), r[3], r[9], self)
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda obj=None, d=dlg: self._dialogs_set().discard(d))
        self._dialogs_set().add(dlg)
        dlg.show()

    def _dialogs_set(self):
        if not hasattr(self, '_open_dialogs'):
            self._open_dialogs = set()
        return self._open_dialogs

    def chartClicked(self, row):
        self._openNonModal('ma', row)

    def candlesClicked(self, row):
        self._openNonModal('candles', row)

    def openTickers(self):
        """Return {ticker: currency} of currently open portfolio positions."""
        out = {}
        for deal in self.data:
            if deal.close_date:
                continue
            ticker = deal.ticker.strip()
            currency = deal.currency.strip() or markets.USD
            if ticker:
                out[ticker] = currency
        return out

    def setupCorrelation(self):
        assets = self.openTickers()
        for ticker, currency in assets.items():
            price_history.ensure_history(ticker, currency)
        self.refreshCorrelation()

    def refreshCorrelation(self):
        assets = self.openTickers()
        tickers, matrix, _ = price_history.build_correlation(assets)
        weights = self._assetWeightsUsd(assets)
        if weights:
            w = [weights.get(str(t), 0.0) for t in tickers]
            corr = price_history.weighted_portfolio_corr(matrix, w)
        else:
            corr = 0.0
        self._portfolio_corr = corr
        self._corr_matrix = matrix
        self._corr_tickers = tickers
        value = int(round(corr * 100))
        self.corrProgressBar.setValue(value)
        r, g, b = self._corrColor(corr)
        text_color = QtGui.QColor(0, 0, 0) if 0.299*r + 0.587*g + 0.114*b > 160 else QtGui.QColor(255, 255, 255)
        self.corrProgressBar.setStyleSheet(
            "QProgressBar {{ color: rgb({}, {}, {}); border: 1px solid gray; text-align: center; }}"
            "QProgressBar::chunk {{ background-color: rgb({}, {}, {}); border-radius: 3px; }}"
            "QProgressBar {{ background-color: rgba(128,128,128,40); }}"
            .format(text_color.red(), text_color.green(), text_color.blue(), r, g, b))
        self.corrProgressBar.setFormat('{:.2f}'.format(corr))
        comment, tip = self._corrFeedback(corr)
        self.corrCommentLabel.setText(comment)
        self.corrCommentLabel.setStyleSheet(
            'color: rgb({}, {}, {}); font-weight: bold;'.format(r, g, b))
        self.corrCommentLabel.setToolTip(tip)
        self.corrProgressBar.setToolTip(
            '{} asset(s), portfolio correlation {:.2f}\n{}'
            .format(len(tickers), corr, tip))
        self._update_portfolio_context()

    def _open_idea_usd_by_ticker(self):
        """Стоимость открытых позиций по тикерам (USD)."""
        rate = markets.fetch_usd_rate()
        usd = {}
        for deal in self.data:
            if deal.close_date:
                continue
            ticker = deal.ticker.strip()
            amount = deal.amount
            price = deal.stock_price
            if not ticker or amount <= 0 or price <= 0:
                continue
            currency = deal.currency.strip() or markets.USD
            if currency == markets.RUB:
                value = price * amount / rate if rate else 0.0
            else:
                value = price * amount
            usd[ticker] = usd.get(ticker, 0.0) + value
        return usd

    def _market_context_text(self):
        """Компактная строка рыночного контекста (информационная)."""
        parts = []
        regime = getattr(self, '_regime_name', None)
        if regime == 'bull':
            parts.append('bull regime')
        elif regime == 'bear':
            parts.append('bear regime')
        else:
            parts.append('neutral')
        if getattr(self, '_late_cycle', False):
            parts.append('late-cycle')
        return 'Market context: ' + ', '.join(parts)

    def _update_portfolio_context(self):
        """Заполнить компактную панель «Portfolio context» (Simple Mode)."""
        if not hasattr(self, 'portfolioContextFrame'):
            return
        usd_by_ticker = self._open_idea_usd_by_ticker()
        open_count = len([t for t in usd_by_ticker if usd_by_ticker[t] > 0])
        ctx = portfolio_context.build_portfolio_context(
            open_count, usd_by_ticker, self.totalEquityUsd(),
            getattr(self, '_portfolio_corr', 0.0))
        lines = []
        if ctx['open_count'] is not None:
            status = ctx['open_status']
            label = {'normal': 'Normal', 'low': 'Info',
                     'review': 'Review'}.get(status, status)
            lines.append('Open ideas: {} (usual range: 5–8) · {}'.format(
                open_count, label))
            if ctx['open_note']:
                lines.append('    ' + ctx['open_note'])
        largest = ctx['largest']
        if largest:
            ticker, value, pct = largest
            pct_txt = ('{:.1f}% of equity'.format(pct)
                       if pct is not None else '—')
            lines.append('Largest idea: {} — ${:,.0f} ({})'.format(
                ticker, value, pct_txt))
        conc = ctx['concentration']
        if conc == 'unknown':
            lines.append('Concentration: —')
        else:
            color = {'normal': '#81c784', 'elevated': '#f0c14b',
                     'high': '#ef5350'}.get(conc, '#dcdce0')
            lines.append('Concentration: <b style="color:{}">{}</b>'.format(
                color, ctx['concentration_ru']))
            if ctx['concentration_note']:
                lines.append('    ' + ctx['concentration_note'])
        lines.append(self._market_context_text())
        self.portfolioContextLabel.setText('<br>'.join(lines))
        self.portfolioContextLabel.setTextFormat(
            QtCore.Qt.TextFormat.RichText)

    def _assetWeightsUsd(self, assets):
        """USD-value-weighted position shares for the given open assets."""
        usd = {}
        for ticker, currency in assets.items():
            value = 0.0
            for deal in self.data:
                if deal.ticker.strip() != ticker:
                    continue
                amount = deal.amount
                price = deal.stock_price
                if currency == markets.RUB:
                    rate = markets.fetch_usd_rate()
                    value += price * amount / rate if rate else 0.0
                else:
                    value += price * amount
            usd[ticker] = value
        total = sum(usd.values())
        if total <= 0:
            return {}
        return {t: v / total for t, v in usd.items()}

    # Correlation "zones" (value-weighted mean pairwise correlation):
    #   below +0.20 -> too conservative (assets barely co-move)
    #   +0.35 ... +0.55 -> "sweet spot" (moderate diversification + cohesion)
    #   above +0.70 -> too risky (assets move together -> concentration risk)
    # Gradients are interpolated between these anchor colors so the bar shows a
    # smooth, readable scale with the good zone clearly green.
    _CORR_ANCHORS = [
        (-1.00, (170, 190, 210)),  # strongly anti-correlated (conservative edge)
        (0.20, (150, 175, 195)),   # start of the "too conservative" band
        (0.30, (120, 190, 120)),   # transition into green
        (0.35, (70, 190, 90)),     # start of the good ("sweet spot") zone
        (0.55, (50, 170, 80)),     # end of the good zone
        (0.65, (210, 160, 60)),    # growing risk -> amber
        (0.70, (230, 90, 40)),     # start of the high-risk band
        (1.00, (220, 40, 40)),     # max concentration risk -> red
    ]

    def _corrColor(self, value):
        anchors = self._CORR_ANCHORS

        def lerp(a, b, t):
            return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

        if value <= anchors[0][0]:
            return anchors[0][1]
        for (x0, c0), (x1, c1) in zip(anchors, anchors[1:]):
            if value <= x1:
                t = (value - x0) / (x1 - x0) if x1 != x0 else 0.0
                return lerp(c0, c1, t)
        return anchors[-1][1]

    def _corrFeedback(self, value):
        # Returns (short comment shown under the thermometer, abstract tooltip).
        if value > 0.70:
            return ('Риск', (
                'Очень высокая корреляция (выше +0.70): активы движутся почти '
                'синхронно. Если рынок падает, весь портфель падает вместе — '
                'высокий риск концентрации, диверсификация почти не работает.'))
        if value >= 0.55:
            return ('Повышенный', (
                'Корреляция выше "золотой зоны" но ещё не в зоне риска '
                '(+0.55...+0.70): активы довольно схожи по динамике, полезно '
                'проверить, нет ли дублирующихся позиций.'))
        if value > 0.35:
            return ('Хорошо', (
                'Корреляция в "золотой зоне" (+0.35...+0.55): активы движутся '
                'умеренно согласованно — баланс между диверсификацией и '
                'устойчивостью портфеля.'))
        if value >= 0.20:
            return ('Нейтрально', (
                'Средняя корреляция (+0.20...+0.35): между зоной риска и '
                'консервативностью — приемлемый уровень разнообразия активов.'))
        return ('Консервативно', (
            'Очень низкая корреляция (ниже +0.20): активы почти не связаны, '
            'портфель сверхдиверсифицирован. Рост одного может не тянуть за '
            'собой остальные — часть потенциальной доходности упускается.'))

    def correlationMatrixClicked(self):
        from correlation_dialog import CorrelationDialog
        tickers = getattr(self, '_corr_tickers', None)
        matrix = getattr(self, '_corr_matrix', None)
        if tickers is None or len(tickers) < 2 or matrix is None:
            QtWidgets.QMessageBox.information(
                self.window(), 'Correlation',
                'Need at least two assets in the portfolio to build a matrix.')
            return
        dlg = CorrelationDialog(tickers, matrix, getattr(self, '_portfolio_corr', 0.0), self)
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda obj=None, d=dlg: self._dialogs_set().discard(d))
        self._dialogs_set().add(dlg)
        dlg.show()

    def macroClicked(self):
        """Open the US macro overview dialog (tabbed indicator charts)."""
        from macro_dialog import MacroDialog
        dlg = MacroDialog(self)
        dlg.destroyed.connect(lambda obj=None, d=dlg: self._dialogs_set().discard(d))
        self._dialogs_set().add(dlg)
        dlg.show()

    def indexClicked(self):
        """Open the US indices overview dialog (tabbed index charts)."""
        from index_dialog import IndexDialog
        dlg = IndexDialog(self)
        dlg.destroyed.connect(lambda obj=None, d=dlg: self._dialogs_set().discard(d))
        self._dialogs_set().add(dlg)
        dlg.show()

    def commoditiesClicked(self):
        """Open the commodities overview dialog (tabbed indicator charts)."""
        from commodities_dialog import CommoditiesDialog
        dlg = CommoditiesDialog(self)
        dlg.destroyed.connect(lambda obj=None, d=dlg: self._dialogs_set().discard(d))
        self._dialogs_set().add(dlg)
        dlg.show()

    def statementsClicked(self):
        """Open the FOMC statements feed dialog."""
        from fomc import StatementsDialog
        dlg = StatementsDialog(self)
        dlg.destroyed.connect(lambda obj=None, d=dlg: self._dialogs_set().discard(d))
        self._dialogs_set().add(dlg)
        dlg.show()

    def todayMacroClicked(self):
        """Open the embedded browser with today's S&P500/NASDAQ macro events."""
        from today_macro_dialog import TodayMacroDialog
        dlg = TodayMacroDialog(self)
        dlg.destroyed.connect(lambda obj=None, d=dlg: self._dialogs_set().discard(d))
        self._dialogs_set().add(dlg)
        dlg.show()

    def clearDbClicked(self):
        ret = QtWidgets.QMessageBox.question(
            self.window(), 'Clear DB',
            'Delete all cached price history? History will be refetched when '
            'tickers are added again.',
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if ret == QtWidgets.QMessageBox.StandardButton.Yes:
            price_history.clear_db()
            self.refreshCorrelation()

    # ТЕРМИНОЛОГИЯ: «градусник» (градусник главного окна / макро температура /
    # thermometer) в промтах и коде — это macroProgressBar + macroRegimeLabel:
    # риск-on/off шкала [-10;+10] из FRED-индикаторов (см. compute_macro_score в
    # macro_dialog.py). Иконка быка/медведя рядом — macroRegimeLabel.
    def setupMacro(self):
        """Render the thermometer from cached data instantly, refresh lazily.

        The score and the bull/bear icon are drawn from their DB caches first
        (no network, no blocking), then a deferred recompute refreshes them if
        they are stale. This keeps window load fast even on refresh days.
        """
        from macro_dialog import _load_score_cached
        from index_dialog import _load_regime_cached

        cached = _load_score_cached()
        if cached is not None:
            self._applyMacro(cached[0], cached[1])
        else:
            self._applyMacro(0, 'загружаются данные…')
        self._applyRegimeIcon(_load_regime_cached('NASDAQ100'))
        self._macroThread = _MacroRefreshThread(self)
        self._macroThread.finished_ok.connect(self._onMacroRefreshed)
        self._macroThread.start()
        self._quantAlertThread = _QuantAlertThread(self)
        self._quantAlertThread.done.connect(self._on_quant_alerts_done)
        self._quantAlertThread.start()
        self._catalystCheckThreads = []
        self._notify_queue = []
        self._active_confirm = None
        self._start_catalyst_check()
        self._catalystTimer = QtCore.QTimer(self)
        self._catalystTimer.timeout.connect(self._start_catalyst_check)
        self._catalystTimer.start(3600000)

    def _start_catalyst_check(self):
        thread = _CatalystReminderThread(self)
        thread.reminders.connect(self._on_catalyst_reminders)
        self._catalystCheckThreads.append(thread)
        thread.finished.connect(
            lambda t=thread: self._catalystCheckThreads.remove(t)
            if t in self._catalystCheckThreads else None)
        thread.start()

    def _on_catalyst_reminders(self, msgs):
        if not msgs:
            return
        for m in msgs:
            self._notify_queue.append((m, True))
        self._flush_notifications()

    def _flush_notifications(self):
        """Показывать уведомления по очереди. Confirm-уведомления (с крестиком)
        блокируют все остальные, пока пользователь не подтвердит прочтение."""
        if getattr(self, '_active_confirm', None) is not None:
            return
        if not self._notify_queue:
            return
        msg, confirm = self._notify_queue.pop(0)
        if confirm:
            self._active_confirm = self._show_goat(msg, confirm=True)
        else:
            self._show_goat(msg, confirm=False, auto_hide_ms=6000)

    def _show_goat(self, advice, confirm=False, auto_hide_ms=0):
        from qualitative_dialog import GoatAssistant
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        self._goat = GoatAssistant('', self, advice=advice,
                                   auto_hide_ms=auto_hide_ms,
                                   ok_button=confirm)
        if confirm:
            self._goat.confirmed.connect(self._on_confirm_dismissed)
        self._goat.show()
        return self._goat

    def _on_confirm_dismissed(self):
        self._active_confirm = None
        if getattr(self, '_goat', None) is not None:
            self._goat.deleteLater()
            self._goat = None
        self._flush_notifications()

    def _on_quant_alerts_done(self):
        self._show_advice_goat()

    def _onMacroRefreshed(self, value, note, regime, late_cycle, fomc_new):
        """Apply background-computed values (runs on the UI thread)."""
        self._late_cycle = late_cycle
        self._fomc_new = fomc_new
        self._applyMacro(value, note)
        self._applyRegimeIcon(regime)
        self._show_advice_goat()

    def _applyMacro(self, value, note):
        self.macroProgressBar.setValue(value)
        self.macroProgressBar.setFormat('{:d}°'.format(value))
        self.macroProgressBar.setToolTip('Макро температура (по FRED): {}'.format(note))
        color = self._macroColor(value)
        r, g, b = color
        text_color = QtGui.QColor(0, 0, 0) if 0.299*r + 0.587*g + 0.114*b > 160 else QtGui.QColor(255, 255, 255)
        self.macroProgressBar.setStyleSheet(
            "QProgressBar {{ color: rgb({}, {}, {}); border: 1px solid gray; text-align: center; }}"
            "QProgressBar::chunk {{ background-color: rgb({}, {}, {}); border-radius: 3px; }}"
            "QProgressBar {{ background-color: rgba(128,128,128,40); }}"
            .format(text_color.red(), text_color.green(), text_color.blue(),
                    r, g, b)
        )

    def _applyRegimeIcon(self, name):
        """Show the bull/bear icon next to the thermometer (NASDAQ regime)."""
        self._regime_name = name or None
        from index_dialog import _regime_icon
        name = name or None
        pm = _regime_icon(name) if name else None
        if pm is not None and not pm.isNull():
            self.macroRegimeLabel.setPixmap(pm)
            self.macroRegimeLabel.setToolTip(
                'Режим рынка по NASDAQ 100 (цена vs 200-SMA): '
                + ('бычий' if name == 'bull' else 'медвежий'))
        else:
            self.macroRegimeLabel.clear()
            self.macroRegimeLabel.setToolTip(
                'Режим рынка по NASDAQ 100 (цена vs 200-SMA): нейтральный')

    def _macroColor(self, value):
        def lerp(a, b, t):
            return int(a + (b - a) * t)
        if value <= 0:
            t = (value + 10) / 10.0
            r = lerp(20, 90, t)
            g = lerp(90, 200, t)
            b = lerp(215, 200, t)
        else:
            t = value / 10.0
            r = lerp(200, 215, t)
            g = lerp(200, 30, t)
            b = lerp(200, 30, t)
        return (r, g, b)

    def load_ui(self):
        loadUi("form.ui", self)
        self.macroRegimeLabel = QtWidgets.QLabel()
        self.macroRegimeLabel.setToolTip('Режим рынка (по макро температуре)')
        self._buildLayout()
        self.resize(1600, 900)
        self.showMaximized()

    def _buildLayout(self):
        """Place widgets in layouts so the deals table stretches with the window."""
        central = self.centralwidget

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        for w in (self.equityLabel, self.equityEdit, self.equityCurrencyLabel,
                  self.label, self.balanceEdit, self.balanceCurrencyLabel):
            top.addWidget(w)
        top.addStretch(1)
        for w in (self.longButton, self.shortButton, self.recalcSlTpButton,
                  self.dealHistoryButton, self.updatePricesButton):
            top.addWidget(w)
        top.addStretch(1)

        self.simpleModeButton = QtWidgets.QPushButton('⚡ Simple Mode')
        self.simpleModeButton.setCheckable(True)
        self.simpleModeButton.setChecked(
            simple_mode_settings.is_simple_enabled())
        self.simpleModeButton.setToolTip(
            'Simple Mode: краткая карточка тикера (вердикт, 3 факта, '
            'качество данных). Выкл. — полный анализ '
            '(P/E, EPS growth, Динамика, Short).')
        self.simpleModeButton.setStyleSheet(
            'QPushButton { font-weight: bold; padding: 3px 12px; }'
            'QPushButton:checked { background-color: #1f6f3f;'
            ' color: #ffffff; border: 1px solid #2e7d32; }')
        top.addWidget(self.simpleModeButton)

        bottom = QtWidgets.QVBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)

        bottom_row1 = QtWidgets.QHBoxLayout()
        bottom_row1.setContentsMargins(0, 0, 0, 0)
        bottom_row1.setSpacing(8)
        for w in (self.macroLabel, self.macroProgressBar, self.macroRegimeLabel,
                  self.macroButton, self.indexButton, self.commoditiesButton,
                  self.statementsButton, self.todayMacroButton,
                  self.corrLabel, self.corrProgressBar, self.corrCommentLabel,
                  self.correlationMatrixButton):
            bottom_row1.addWidget(w)
        bottom_row1.addStretch(1)

        self.portfolioContextFrame = QtWidgets.QFrame()
        self.portfolioContextFrame.setStyleSheet(
            'QFrame { background: #16171b; border: 1px solid #43464f; '
            'border-radius: 6px; }')
        pclay = QtWidgets.QVBoxLayout(self.portfolioContextFrame)
        pclay.setContentsMargins(10, 6, 10, 6)
        pclay.setSpacing(2)
        self.portfolioContextTitle = QtWidgets.QLabel('Portfolio context')
        self.portfolioContextTitle.setStyleSheet(
            'color: #dcdce0; font-weight: bold; font-size: 12px;')
        pclay.addWidget(self.portfolioContextTitle)
        self.portfolioContextLabel = QtWidgets.QLabel('')
        self.portfolioContextLabel.setWordWrap(True)
        self.portfolioContextLabel.setStyleSheet(
            'color: #dcdce0; font-size: 11px;')
        pclay.addWidget(self.portfolioContextLabel)
        self.portfolioContextFrame.setVisible(
            simple_mode_settings.is_simple_enabled())
        bottom_row2 = QtWidgets.QHBoxLayout()
        bottom_row2.setContentsMargins(0, 0, 0, 0)
        bottom_row2.setSpacing(8)
        for w in (self.clearDbButton, self.quantitiveAssessmentButton,
                  self.qualitativeAssessmentButton, self.watchlistButton):
            bottom_row2.addWidget(w)
        bottom_row2.addStretch(1)

        bottom.addLayout(bottom_row1)
        bottom.addWidget(self.portfolioContextFrame)
        bottom.addLayout(bottom_row2)

        v = QtWidgets.QVBoxLayout(central)
        v.setContentsMargins(20, 10, 20, 10)
        v.setSpacing(10)
        v.addLayout(top)
        v.addWidget(self.tradeTableView, 1)
        v.addLayout(bottom)

    def read_data(self):
        self.data, self.base_balance = load_diary()
        self.holdings_usd = 0.0

    def recalcBalance(self):
        self.holdings_usd = 0.0
        rate = markets.fetch_usd_rate()
        for deal in self.data:
            currency = deal.currency
            if currency not in (markets.RUB, markets.USD):
                continue
            if deal.close_date:
                continue
            amount = deal.amount
            price = deal.stock_price
            if amount <= 0 or price <= 0:
                continue
            if currency == markets.RUB:
                if rate:
                    self.holdings_usd += price * amount / rate
            else:
                self.holdings_usd += price * amount
        self.updateBalanceDisplay()
        self._update_portfolio_context()

    def totalEquityUsd(self):
        return self.base_balance + self.holdings_usd

    def updateBalanceDisplay(self):
        self.equityEdit.setText('{:.2f}'.format(self.totalEquityUsd()))
        self.balanceEdit.setText('{:.2f}'.format(self.base_balance))

    def balanceUsd(self):
        text = self.balanceEdit.text().replace('$', '').replace(' ', '').strip()
        try:
            return float(text)
        except ValueError:
            return 0.0

    def balanceEdited(self):
        self.base_balance = self.balanceUsd()
        self.updateBalanceDisplay()

    def closeEvent(self,event):
        log.info("Close event")
        t = getattr(self, '_macroThread', None)
        if t is not None and t.isRunning():
            t.wait(5000)
        for ct in list(getattr(self, '_catalystCheckThreads', [])):
            if ct.isRunning():
                ct.wait(5000)
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()

        save_diary(self.data, self.base_balance)
        event.accept()

    def longClicked(self):
        log.info("Long clicked")
        dlg = DealDialog()
        dlg.setData(self.balanceUsd())
        dlg.setEquityUsd(self.totalEquityUsd())
        dlg.setMode(DirectionType.BUY)
        if dlg.exec():
            log.info("Success!")
            deal = dlg.makeDeal()
            self.debitLong(deal)
            self.data.append(deal)
            self.tradeTableView.model().layoutChanged.emit()
            self.recalcBalance()
            self.onTickerAdded(deal.ticker, deal.currency)
        else:
            log.info("Cancel!")

    def debitLong(self, deal):
        cost_usd = None
        if deal.currency == markets.RUB:
            rate = markets.fetch_usd_rate()
            if rate:
                cost_usd = deal.stock_price * deal.amount / rate
        elif deal.currency == markets.USD:
            cost_usd = deal.stock_price * deal.amount
        if cost_usd is not None:
            self.base_balance -= cost_usd

    def _creditClose(self, deal):
        """Зачислить/списать средства при закрытии сделки.

        LONG — выручка от продажи возвращается на cash (равно стоимости
        позиции + P&L). SHORT — стоимость выкупа списывается с cash.
        История закрытых сделок будет вестись отдельно (вкладка History).
        """
        proceeds_usd = None
        if deal.currency == markets.RUB:
            rate = markets.fetch_usd_rate()
            if rate:
                proceeds_usd = deal.stock_price * deal.amount / rate
        elif deal.currency == markets.USD:
            proceeds_usd = deal.stock_price * deal.amount
        if proceeds_usd is None:
            return
        if deal.direction == Direction.SHORT:
            self.base_balance -= proceeds_usd
        else:
            self.base_balance += proceeds_usd

    def shortClicked(self):
        log.info("Short clicked")
        dlg = DealDialog()
        dlg.setData(self.balanceUsd())
        dlg.setEquityUsd(self.totalEquityUsd())
        dlg.setMode(DirectionType.SELL)
        if dlg.exec():
            log.info("Success!")
            deal = dlg.makeDeal()
            self.data.append(deal)
            self.tradeTableView.model().layoutChanged.emit()
            self.recalcBalance()
            self.onTickerAdded(deal.ticker, deal.currency)

    def onTickerAdded(self, ticker, currency):
        price_history.ensure_history(ticker, currency)
        self.refreshCorrelation()
        self._show_advice_goat()

    _LATE_CYCLE_GOAT_TEXT = (
        'Инвестиции (GPDI) падают, а потребкредит держится — поздний цикл: '
        'S&P 500 близок к пику. Выходите из Tech и Consumer Discretionary, '
        'перекладывайтесь в защиту (Utilities, Consumer Staples, Healthcare).')

    def _show_advice_goat(self):
        if getattr(self, '_active_confirm', None) is not None or self._notify_queue:
            return
        advice = None
        if getattr(self, '_fomc_new', 0):
            advice = ('Глава ФРС сделал заявление: есть непрочитанные заявления '
                      'FOMC. Откройте «Statements», чтобы прочитать.')
        elif getattr(self, '_late_cycle', False):
            advice = self._LATE_CYCLE_GOAT_TEXT
        else:
            from quant_alerts import new_events, mark_all_seen
            events = new_events()
            if events:
                sectors = sum(1 for e in events if e['kind'] == 'sector_signal')
                companies = sum(1 for e in events if e['kind'] == 'company_score')
                parts = []
                if sectors:
                    parts.append('{} секторов изменили сигнал'.format(sectors))
                if companies:
                    parts.append('{} компаний изменили score'.format(companies))
                detail = '\n'.join(e['message'] for e in events[:3])
                advice = ('Quant alerts: {}. {}'.format(
                    ', '.join(parts), detail or ''))
                mark_all_seen()
        if not advice:
            return
        self._show_goat(advice, confirm=False,
                        auto_hide_ms=8000 if 'Quant alerts' in advice else 5000)

    def deleteClicked(self, row):
        if row < 0 or row >= len(self.data):
            return
        ticker = self.data[row].ticker or 'deal'
        ret = QtWidgets.QMessageBox.question(
            self.window(), 'Delete deal',
            'Delete this deal ({} )?'.format(ticker),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if ret != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.model.removeRows(row, 1)
        self._rebuildChartButtons()
        self.recalcBalance()
        self.refreshCorrelation()

    def editClicked(self, item):
        log.info("Edit clicked %s", item.row())
        deal = self.data[item.row()]
        dlg = EditDealDialog()
        dlg.setData(deal, self.balanceUsd())
        if dlg.exec():
            log.info("Success!")
            if deal.close_date:
                self._creditClose(deal)
                self.data.remove(deal)
                self._rebuildChartButtons()
            self.tradeTableView.model().layoutChanged.emit()
            self.recalcBalance()

    def _riskPercentForCorr(self, corr):
        return risk.risk_pct_for_corr(corr)

    def _groupOpenStocks(self):
        """Group open (unclosed) stock positions by ticker.

        Returns a dict ticker -> account with:
          amount       : summed shares across deals
          weightedPrice: price blended across deals (by amount)
          currency     : currency of the ticker
          direction    : deal direction (LONG/SHORT)
          rows         : list of open deals belonging to the ticker
          skipped      : reason string if the group could not be processed
        Deals with non-positive data are collected together (their ticker is
        skipped, reason preserved). Futures are skipped (TODO: pointPrice).
        """
        groups = {}
        for deal in self.data:
            if deal.close_date:                      # закрытая сделка — пропускаем
                continue
            ticker = deal.ticker.strip()
            if FutureUtil.is_future(self._fakeDeal(ticker)):
                groups.setdefault(ticker, {}).setdefault('skipped',
                    'фьючерс, пока не поддерживается')
                continue
            price = deal.stock_price
            amount = deal.amount
            if amount <= 0 or price <= 0:
                groups.setdefault(ticker, {}).setdefault('skipped',
                    'amount/price <= 0')
                continue
            g = groups.setdefault(ticker, {'amount': 0.0,
                                           'weightedPrice': 0.0,
                                           'currency': deal.currency.strip(),
                                           'direction': deal.direction,
                                           'rows': []})
            g['amount'] += amount
            g['weightedPrice'] += price * amount
            g['rows'].append(deal)
        # Взвешенная по объёму цена по каждому тикеру.
        for g in groups.values():
            if g.get('amount', 0) > 0:
                g['weightedPrice'] /= g['amount']
        return groups

    def recalcSlTpClicked(self):
        """Recalculate recommended SL/TP for every open position (by TICKER).

        All open deals of the same ticker are aggregated into one position, so a
        single 2%-style risk budget is applied per ticker rather than per deal
        (no duplicated risk for multiple entries of the same asset). TP is RR:1
        of the resulting risk distance; the computed SL/TP is written back to
        every open deal of that ticker.
        TODO(в GUI): продумать распределение СОВОКУПНОГО риска между разными
        тикерами; фьючерсы (pointPrice) пока не поддерживаются.
        """
        assets = self.openTickers()
        if not assets:
            QtWidgets.QMessageBox.information(
                self.window(), 'Recalc SL/TP',
                'No open positions to recalculate.')
            return

        if simple_mode_settings.is_simple_enabled():
            QtWidgets.QMessageBox.information(
                self.window(), 'Recalc SL/TP',
                'В Simple Mode stop-loss и take-profit задаются вручную — '
                'автоматический пересчёт отключён.')
            return

        equity = self.totalEquityUsd()
        if equity <= 0:
            QtWidgets.QMessageBox.information(
                self.window(), 'Recalc SL/TP',
                'Equity is not positive ({}), cannot size risk.'.format(
                    '{:.2f}'.format(equity)))
            return

        corr = getattr(self, '_portfolio_corr', 0.0)
        risk_pct = self._riskPercentForCorr(corr)
        risk_budget_usd = equity * risk_pct

        groups = self._groupOpenStocks()
        changed_tickers = []
        skipped = []
        for ticker, g in groups.items():
            if g.get('skipped'):
                skipped.append(ticker + ' ({})'.format(g['skipped']))
                continue

            currency = g['currency'] or markets.USD
            # Локальный риск-бюджет в валюте сделки.
            if currency == markets.RUB:
                rate = markets.fetch_usd_rate()
                if not rate:
                    skipped.append(ticker + ' (нет курса USD/RUB)')
                    continue
                budget_local = risk_budget_usd * rate
            else:
                budget_local = risk_budget_usd  # валюту считаем как доллар

            amount = g['amount']
            price = g['weightedPrice']
            risk_per_stock = budget_local / amount
            direction = g['direction']
            if direction == Direction.LONG:
                sl = price - risk_per_stock
                tp = price + risk.RR * risk_per_stock
            else:
                sl = price + risk_per_stock
                tp = price - risk.RR * risk_per_stock

            # Пишем одинаковые SL/TP во все открытые сделки этого тикера.
            for deal in g['rows']:
                deal.stop_loss = sl
                deal.take_profit = tp
            changed_tickers.append(ticker)

        self.tradeTableView.model().layoutChanged.emit()
        self.recalcBalance()

        if changed_tickers:
            QtWidgets.QMessageBox.information(
                self.window(), 'Recalc SL/TP',
                'Recalculated SL/TP for {} ticker(s): {}.\n'
                'Risk used: {:.2f}% of equity (portfolio corr {:.2f}).'
                .format(len(changed_tickers), ', '.join(sorted(changed_tickers)),
                        risk_pct * 100.0, corr)
                + (('\nSkipped: ' + ', '.join(skipped)) if skipped else ''))
        else:
            QtWidgets.QMessageBox.information(
                self.window(), 'Recalc SL/TP',
                'Nothing recalculated.' + ((' Skipped: ' + ', '.join(skipped)) if skipped else ''))

    def quantitiveAssessmentClicked(self):
        from sector_quant_dialog import SectorQuantDialog
        dlg = SectorQuantDialog(self)
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda obj=None, d=dlg: self._dialogs_set().discard(d))
        self._dialogs_set().add(dlg)
        dlg.show()

    def qualitativeAssessmentClicked(self):
        from qualitative_dialog import QualitativeAssessmentDialog
        dlg = QualitativeAssessmentDialog(self)
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda obj=None, d=dlg: self._dialogs_set().discard(d))
        self._dialogs_set().add(dlg)
        dlg.show()

    def watchlistClicked(self):
        """Open the watchlist dialog (tickers added from Qualitative Assessment)."""
        from watchlist_dialog import WatchlistDialog
        dlg = WatchlistDialog(self)
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda obj=None, d=dlg: self._dialogs_set().discard(d))
        self._dialogs_set().add(dlg)
        dlg.show()

    def dealHistoryClicked(self):
        """Open the Deal History window (all deals).

        Currently closes are empty, so fictional history is generated from the
        open positions for a meaningful display.
        TODO(в GUI): убрать генерацию, когда появится настоящая история.
        """
        from deal_history import DealHistoryDialog, generate_fake_history
        open_deals = [d for d in self.data if d.is_open]
        history = self.data + generate_fake_history(open_deals)
        dlg = DealHistoryDialog(history, self)
        dlg.exec()

    def _fakeDeal(self, ticker):
        """Minimal Deal-compatible object so FutureUtil can inspect the ticker."""
        d = Deal()
        d.ticker = ticker
        return d

    @staticmethod
    def _priceStr(value):
        """Format a price for storage (2 decimals)."""
        return '{:.2f}'.format(value)

    def updatePricesClicked(self):
        log.warning("Update prices: устаревший обработчик (URL 2023 г.) — отключён")
        QtWidgets.QMessageBox.information(
            self.window(), 'Update prices',
            'Автообновление котировок временно отключено (устаревшая загрузка). '
            'Цены подтягиваются автоматически при добавлении тикера.')


DARK_QSS = """
QMainWindow, QDialog, QWidget { background-color: #1e1f24; color: #dcdce0; }
QTableView { background-color: #1a1b20; alternate-background-color: #23242b;
             color: #f0f0f4; gridline-color: #464a56;
             selection-background-color: #3d5a80; selection-color: #ffffff; }
QTableView::item { padding: 2px; }
QHeaderView::section { background-color: #33353f; color: #e8e8ee;
                       border: 1px solid #4a4e5a; padding: 4px;
                       font-weight: bold; }
QLineEdit, QPlainTextEdit { background-color: #16171c; color: #e6e6ea;
                            border: 1px solid #3a3c46; border-radius: 3px;
                            selection-background-color: #3d5a80; }
QPushButton { background-color: #30323c; color: #dcdce0; border: 1px solid #43464f;
              border-radius: 4px; padding: 3px 8px; }
QPushButton:hover { background-color: #3a3d49; }
QPushButton:pressed { background-color: #26282f; }
QLabel { color: #dcdce0; }
QProgressBar { text-align: center; border: 1px solid #43464f; border-radius: 4px;
               background-color: #26272e; }
QMenuBar, QStatusBar { background-color: #26272e; color: #dcdce0; }
QMenuBar::item { background: transparent; }
QMenuBar::item:selected { background: #3a3d49; }
QScrollBar:vertical { background: #1e1f24; width: 12px; }
QScrollBar::handle:vertical { background: #3a3c46; border-radius: 6px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background-color: #26272e; color: #e6e6ea; border: 1px solid #43464f; }
"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    widget = TradeDiary()
    widget.show()
    # Скрепка отключена (код сохранён, см. класс OfficeAssistant выше).
    # assistant = OfficeAssistant()
    # assistant.show()
    sys.exit(app.exec_())
