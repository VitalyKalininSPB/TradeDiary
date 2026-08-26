# This Python file uses the following encoding: utf-8
import sys
import os


from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import QApplication
from qt_loader import loadUi

from EditDealDialog import EditDealDialog


from xml.dom.minidom import parse
import xml.dom.minidom

from DealDialog import DealDialog
from DealDialog import Deal
from DealDialog import DirectionType
from DealDialog import FutureUtil
from DealDialog import trade_system_name

import requests, zipfile, io
import markets
import price_history

# ---------------------------------------------------------------------------
# TODO(потом в GUI): константы позиционной риска. Пока захардкожены, вынести в настройки.
# Модель риска: масштабируется от корреляции портфеля (см. корреляционный термометр).
# Bасис 2% в "хорошей" зоне (+0.35..+0.55); при концентрации риск режется, при
# диверсификации повышается. Список — (верхняя граница корреляции, риск на позицию),
# упорядочен по убыванию корреляции; выбирается ПОСЛЕДВИЙ интервал, в который попадает corr.
RISK_BY_CORR = [          # TODO(в GUI): заменить на редактируемую таблицу
    (1.00, 0.010),        # > +0.70 — высокая концентрация: самые низкий риск
    (0.70, 0.015),        # +0.55..+0.70 — повышенный риск
    (0.55, 0.020),        # +0.35..+0.55 — "хорошая" зона: BАСИС 2%
    (0.35, 0.020),        # +0.20..+0.35 — нейтрально
    (0.20, 0.025),        # <= +0.20 — сверхдиверсифицировано: можно больше
]
RR = 2.0                  # TODO(в GUI): соотношение TP:SL (1:2)
# ---------------------------------------------------------------------------

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

    def __init__(self, data):
        super(TableModel, self).__init__()
        self._data = data

    def data(self, index, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            col = index.column()
            if col == 7:
                return trade_system_name(self._data[index.row()][col])
            if col in (12, 13, 14):
                return ''
            return self._data[index.row()][col]
        if role == QtCore.Qt.ItemDataRole.BackgroundRole:
            if (self._data[index.row()][4] > self._data[index.row()][1]):
                return QtGui.QBrush(QtGui.QColor(42, 106, 64))
            elif (self._data[index.row()][4] < self._data[index.row()][1]):
                return QtGui.QBrush(QtGui.QColor(140, 46, 46))
            else:
                return QtGui.QBrush(QtGui.QColor(28, 29, 34))
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            if (self._data[index.row()][4] != self._data[index.row()][1]):
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


class TradeDiary(QtWidgets.QMainWindow):
    def __init__(self):
        super(TradeDiary, self).__init__()
        self.load_ui()
        print("UI loaded")
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
        self.setupMacro()
        self.setupCorrelation()
        self.quantitiveAssessmentButton.clicked.connect(self.quantitiveAssessmentClicked)
        self.qualitativeAssessmentButton.clicked.connect(self.qualitativeAssessmentClicked)
        self.correlationMatrixButton.clicked.connect(self.correlationMatrixClicked)
        self.macroButton.clicked.connect(self.macroClicked)
        self.indexButton.clicked.connect(self.indexClicked)
        self.clearDbButton.clicked.connect(self.clearDbClicked)
        self.recalcSlTpButton.clicked.connect(self.recalcSlTpClicked)
        self.tradeTableView.setColumnWidth(12, 70)
        self.tradeTableView.setColumnWidth(13, 80)
        self.tradeTableView.setColumnWidth(14, 70)

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
        for row in self.data:
            if row[9]:
                continue
            ticker = row[0].strip()
            currency = row[12].strip() or markets.USD
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

    def _assetWeightsUsd(self, assets):
        """USD-value-weighted position shares for the given open assets."""
        usd = {}
        for ticker, currency in assets.items():
            value = 0.0
            for row in self.data:
                if row[0].strip() != ticker:
                    continue
                try:
                    amount = float(row[2] or 0)
                    price = float(row[1] or 0)
                except ValueError:
                    continue
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

    def clearDbClicked(self):
        ret = QtWidgets.QMessageBox.question(
            self.window(), 'Clear DB',
            'Delete all cached price history? History will be refetched when '
            'tickers are added again.',
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if ret == QtWidgets.QMessageBox.StandardButton.Yes:
            price_history.clear_db()
            self.refreshCorrelation()

    def setupMacro(self):
        """Compute the macro thermometer from the cached FRED indices.

        Falls back to a neutral 0 (with an explanatory note) when the data is
        unavailable, instead of a random value. See macro_dialog.compute_macro_score.
        """
        from macro_dialog import compute_macro_score
        try:
            value, note = compute_macro_score()
        except Exception:
            value, note = None, 'Ошибка расчёта'
        if value is None:
            value = 0
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

        bottom = QtWidgets.QVBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)

        bottom_row1 = QtWidgets.QHBoxLayout()
        bottom_row1.setContentsMargins(0, 0, 0, 0)
        bottom_row1.setSpacing(8)
        for w in (self.macroLabel, self.macroProgressBar, self.macroButton,
                  self.indexButton,
                  self.corrLabel, self.corrProgressBar, self.corrCommentLabel,
                  self.correlationMatrixButton):
            bottom_row1.addWidget(w)
        bottom_row1.addStretch(1)

        bottom_row2 = QtWidgets.QHBoxLayout()
        bottom_row2.setContentsMargins(0, 0, 0, 0)
        bottom_row2.setSpacing(8)
        for w in (self.clearDbButton, self.quantitiveAssessmentButton,
                  self.qualitativeAssessmentButton):
            bottom_row2.addWidget(w)
        bottom_row2.addStretch(1)

        bottom.addLayout(bottom_row1)
        bottom.addLayout(bottom_row2)

        v = QtWidgets.QVBoxLayout(central)
        v.setContentsMargins(20, 10, 20, 10)
        v.setSpacing(10)
        v.addLayout(top)
        v.addWidget(self.tradeTableView, 1)
        v.addLayout(bottom)

    def read_data(self):
        DOMTree = xml.dom.minidom.parse("diary.xml")
        collection = DOMTree.documentElement

        self.data = []
        self.base_balance = 0.0
        self.holdings_usd = 0.0

        balance = collection.getElementsByTagName("balance")
        for b in balance:
            try:
                self.base_balance = float(b.getAttribute('value') or 0)
            except ValueError:
                self.base_balance = 0.0

        deals = collection.getElementsByTagName("deal")
        for deal in deals:
            print('Deal')
            print(deal)

            print("Ticker: " + deal.getAttribute('ticker'))

            row = [deal.getAttribute('ticker'),\
                    deal.getAttribute('stockPrice'), \
                    deal.getAttribute('stocksAmount'), \
                    deal.getAttribute('openDate'), \
                    deal.getAttribute('initPrice'), \
                    deal.getAttribute('takeProfit'), \
                    deal.getAttribute('stopLoss'), \
                    deal.getAttribute('tradeSystem'), \
                    deal.getAttribute('result'), \
                    deal.getAttribute('closeDate'), \
                    deal.getAttribute('whatsNext'), \
                    deal.getAttribute('analysisNotes'), \
                    deal.getAttribute('currency')]
            self.data.append(row)

    def recalcBalance(self):
        self.holdings_usd = 0.0
        rate = markets.fetch_usd_rate()
        for row in self.data:
            currency = row[12]
            if currency not in (markets.RUB, markets.USD):
                continue
            if row[9]:
                continue
            try:
                amount = float(row[2] or 0)
                price = float(row[1] or 0)
            except ValueError:
                continue
            if amount <= 0 or price <= 0:
                continue
            if currency == markets.RUB:
                if rate:
                    self.holdings_usd += price * amount / rate
            else:
                self.holdings_usd += price * amount
        self.updateBalanceDisplay()

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
        print("Close event")
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()

        doc = xml.dom.minidom.parseString("<diary/>")
        root = doc.documentElement

        balance = doc.createElement("balance")
        balance.setAttribute("value", str(self.base_balance))
        root.appendChild(balance)

        for row in self.data:
            print('Stock Price for save: ' + str(row[1]))
            print('Init Price for save: ' + str(row[4]))
            deal = doc.createElement("deal")
            deal.setAttribute("ticker", row[0])
            deal.setAttribute("stockPrice", str(row[1]))
            deal.setAttribute("stocksAmount", str(row[2]))
            deal.setAttribute("openDate", row[3])
            deal.setAttribute("initPrice", str(row[4]))
            deal.setAttribute("takeProfit", str(row[5]))
            deal.setAttribute("stopLoss", str(row[6]))
            deal.setAttribute("tradeSystem", str(row[7]))
            deal.setAttribute("result", row[8])
            deal.setAttribute("closeDate", row[9])
            deal.setAttribute("whatsNext", row[10])
            deal.setAttribute("analysisNotes", row[11])
            deal.setAttribute("currency", row[12])
            root.appendChild(deal)

        #print(doc.toprettyxml())
        doc.writexml( open('diary.xml', 'w'),
                      indent="  ",
                      addindent="  ",
                      newl='\n')

        event.accept()

    def longClicked(self):
        print("Long clicked")
        dlg = DealDialog()
        dlg.setData(self.balanceUsd())
        dlg.setMode(DirectionType.BUY)
        if dlg.exec():
            print("Success!")
            deal = dlg.makeDeal()
            self.debitLong(deal)
            self.data.append(deal.toArray())
            self.tradeTableView.model().layoutChanged.emit()
            self.recalcBalance()
            self.onTickerAdded(deal.ticker, deal.currency)
        else:
            print("Cancel!")

    def debitLong(self, deal):
        cost_usd = None
        if deal.currency == markets.RUB:
            rate = markets.fetch_usd_rate()
            if rate:
                cost_usd = deal.stockPrice * deal.stocksAmount / rate
        elif deal.currency == markets.USD:
            cost_usd = deal.stockPrice * deal.stocksAmount
        if cost_usd is not None:
            self.base_balance -= cost_usd

    def shortClicked(self):
        print("Short clicked")
        dlg = DealDialog()
        dlg.setData(self.balanceUsd())
        dlg.setMode(DirectionType.SELL)
        if dlg.exec():
            print("Success!")
            deal = dlg.makeDeal()
            self.data.append(deal.toArray())
            self.tradeTableView.model().layoutChanged.emit()
            self.recalcBalance()
            self.onTickerAdded(deal.ticker, deal.currency)

    def onTickerAdded(self, ticker, currency):
        price_history.ensure_history(ticker, currency)
        self.refreshCorrelation()
        self._show_advice_goat()

    def _show_advice_goat(self):
        from qualitative_dialog import GoatAssistant
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
        self._goat = GoatAssistant('', self,
                                   advice='Балансируйте лонги и шорты в портфеле',
                                   auto_hide_ms=5000)
        self._goat.show()

    def deleteClicked(self, row):
        if row < 0 or row >= len(self.data):
            return
        ticker = str(self.data[row][0] or '') or 'deal'
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
        print("Edit clicked " + str(item.row()))
        dlg = EditDealDialog()
        dlg.setData(self.data[item.row()], self.balanceUsd())
        if dlg.exec():
            print("Success!")
            self.data[item.row()][1] = dlg.priceEdit.text()
            self.data[item.row()][7] = dlg.tradesystemList.currentIndex()
            self.data[item.row()][9] = dlg.closeDateLabel.text()
            self.data[item.row()][10] = dlg.whatsNextEdit.toPlainText()
            self.data[item.row()][11] = dlg.notesEdit.toPlainText()
            self.tradeTableView.model().layoutChanged.emit()
            self.recalcBalance()

    def _riskPercentForCorr(self, corr):
        """Risk per position (%) for the current portfolio correlation.

        Selects the highest interval in RISK_BY_CORR whose upper bound is >= corr,
        i.e. the band the correlation currently falls into.
        TODO(в GUI): этот подбор инф-полем можно перенести в настройки.
        """
        for bound, risk in RISK_BY_CORR:
            if corr <= bound:
                return risk
        return RISK_BY_CORR[-1][1]

    def _dealDirection(self, row):
        """Infer long/short for a deal row. Direction is not stored in the model.

        TODO(в GUI): добавить явное поле direction; пока infer:
          1) по заданному SL (row[6]); 2) иначе по TP (row[5]); 3) иначе Long.
        Returns 'LONG' or 'SHORT'.
        """
        try:
            price = float(row[1] or 0)
        except ValueError:
            price = 0.0

        def _num(idx):
            try:
                return float(row[idx] or 0)
            except ValueError:
                return 0.0

        sl = _num(6)
        if sl != 0:
            return 'SHORT' if sl > price else 'LONG'
        tp = _num(5)
        if tp != 0:
            return 'SHORT' if tp < price else 'LONG'
        return 'LONG'

    def _groupOpenStocks(self):
        """Group open (unclosed) stock positions by ticker.

        Returns a dict ticker -> account with:
          amount      : summed shares across rows
          weightedPrice: price blended across rows (by amount)
          currency     : currency of the ticker
          rows         : list of open data rows belonging to the ticker
          skipped      : reason string if the group could not be processed
        Rows with invalid/non-positive data are collected together (their ticker
        is skipped, reason preserved). Futures are skipped (TODO: pointPrice).
        """
        groups = {}
        for row in self.data:
            if row[9]:                      # закрытая сделка — пропускаем
                continue
            ticker = row[0].strip()
            if FutureUtil.is_future(self._fakeDeal(ticker)):
                groups.setdefault(ticker, {}).setdefault('skipped',
                    'фьючерс, пока не поддерживается')
                continue
            try:
                price = float(row[1] or 0)
                amount = float(row[2] or 0)
            except ValueError:
                groups.setdefault(ticker, {}).setdefault('skipped',
                    'нечисловые данные')
                continue
            if amount <= 0 or price <= 0:
                groups.setdefault(ticker, {}).setdefault('skipped',
                    'amount/price <= 0')
                continue
            g = groups.setdefault(ticker, {'amount': 0.0,
                                           'weightedPrice': 0.0,
                                           'currency': row[12].strip(),
                                           'rows': []})
            g['amount'] += amount
            g['weightedPrice'] += price * amount
            g['rows'].append(row)
        # Взвешенная по объёму цена по каждому тикеру.
        for g in groups.values():
            if g.get('amount', 0) > 0:
                g['weightedPrice'] /= g['amount']
        return groups

    def recalcSlTpClicked(self):
        """Recalculate recommended SL/TP for every open position (by TICKER).

        All open rows of the same ticker are aggregated into one position, so a
        single 2%-style risk budget is applied per ticker rather than per row
        (no duplicated risk for multiple entries of the same asset). TP is RR:1
        of the resulting risk distance; the computed SL/TP is written back to
        every open row of that ticker.
        TODO(в GUI): продумать распределение СОВОКУПНОГО риска между разными
        тикерами; явное поле direction; фьючерсы (pointPrice) пока не поддерживаются.
        """
        assets = self.openTickers()
        if not assets:
            QtWidgets.QMessageBox.information(
                self.window(), 'Recalc SL/TP',
                'No open positions to recalculate.')
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
            direction = self._dealDirection(g['rows'][0])
            if direction == 'LONG':
                sl = price - risk_per_stock
                tp = price + RR * risk_per_stock
            else:
                sl = price + risk_per_stock
                tp = price - RR * risk_per_stock

            # Пишем одинаковые SL/TP во все открытые строки этого тикера.
            for row in g['rows']:
                row[6] = self._priceStr(sl)
                row[5] = self._priceStr(tp)
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
        QtWidgets.QMessageBox.information(
            self.window(), 'Quantitative Assessment',
            'Quantitative assessment placeholder.\n'
            'This is a regular screener, but with hints on which criteria to screen for.')

    def qualitativeAssessmentClicked(self):
        from qualitative_dialog import QualitativeAssessmentDialog
        dlg = QualitativeAssessmentDialog(self)
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
        open_rows = [r for r in self.data if not r[9]]
        history = self.data + generate_fake_history(open_rows)
        dlg = DealHistoryDialog(history, self)
        dlg.exec()

    def _fakeDeal(self, ticker):
        """Minimal Deal-compatible object so FutureUtil can inspect the ticker."""
        from DealDialog import Deal
        d = Deal()
        d.ticker = ticker
        return d

    @staticmethod
    def _priceStr(value):
        """Format a price for storage (2 decimals)."""
        return '{:.2f}'.format(value)

    def updatePricesClicked(self):
        print("Update prices")
        url = 'https://iss.moex.com/iss/downloads/statistics/engines/stock/currentprices/currentprices_main_2023-02-15.xml.zip'
        r = requests.get(url)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        z.extractall("tmp")
        DOMTree = xml.dom.minidom.parse("tmp/currentprices_main_latest.xml")
        collection = DOMTree.documentElement

        currentStocks = {'ALRS':0, 'AFKS':0}
        rows = collection.getElementsByTagName("row")
        for name in currentStocks.keys():
            for row in rows:
                if row.hasAttribute('SECID') and row.getAttribute('SECID') == name:
                    currentStocks[name] = row.getAttribute('CURPRICE')

        print('RES:')
        print(currentStocks)


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
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    widget = TradeDiary()
    widget.show()
    # Скрепка отключена (код сохранён, см. класс OfficeAssistant выше).
    # assistant = OfficeAssistant()
    # assistant.show()
    sys.exit(app.exec_())
