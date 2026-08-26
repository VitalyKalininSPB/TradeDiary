# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'form.ui'
##
## Created by: Qt User Interface Compiler version 6.11.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMenuBar, QProgressBar, QPushButton,
    QSizePolicy, QStatusBar, QTableView, QWidget)

class Ui_TradeDiary(object):
    def setupUi(self, TradeDiary):
        if not TradeDiary.objectName():
            TradeDiary.setObjectName(u"TradeDiary")
        TradeDiary.resize(1127, 660)
        self.centralwidget = QWidget(TradeDiary)
        self.centralwidget.setObjectName(u"centralwidget")
        self.equityEdit = QLineEdit(self.centralwidget)
        self.equityEdit.setObjectName(u"equityEdit")
        self.equityEdit.setGeometry(QRect(78, 8, 90, 25))
        self.equityEdit.setReadOnly(True)
        self.equityCurrencyLabel = QLabel(self.centralwidget)
        self.equityCurrencyLabel.setObjectName(u"equityCurrencyLabel")
        self.equityCurrencyLabel.setGeometry(QRect(172, 13, 17, 17))
        self.equityLabel = QLabel(self.centralwidget)
        self.equityLabel.setObjectName(u"equityLabel")
        self.equityLabel.setGeometry(QRect(20, 10, 53, 17))
        self.balanceEdit = QLineEdit(self.centralwidget)
        self.balanceEdit.setObjectName(u"balanceEdit")
        self.balanceEdit.setGeometry(QRect(278, 8, 90, 25))
        self.balanceCurrencyLabel = QLabel(self.centralwidget)
        self.balanceCurrencyLabel.setObjectName(u"balanceCurrencyLabel")
        self.balanceCurrencyLabel.setGeometry(QRect(372, 13, 17, 17))
        self.label = QLabel(self.centralwidget)
        self.label.setObjectName(u"label")
        self.label.setGeometry(QRect(205, 10, 67, 17))
        self.tradeTableView = QTableView(self.centralwidget)
        self.tradeTableView.setObjectName(u"tradeTableView")
        self.tradeTableView.setGeometry(QRect(20, 50, 1091, 501))
        self.tradeTableView.horizontalHeader().setVisible(True)
        self.tradeTableView.horizontalHeader().setCascadingSectionResizes(False)
        self.longButton = QPushButton(self.centralwidget)
        self.longButton.setObjectName(u"longButton")
        self.longButton.setGeometry(QRect(410, 10, 89, 25))
        self.shortButton = QPushButton(self.centralwidget)
        self.shortButton.setObjectName(u"shortButton")
        self.shortButton.setGeometry(QRect(505, 10, 89, 25))
        self.recalcSlTpButton = QPushButton(self.centralwidget)
        self.recalcSlTpButton.setObjectName(u"recalcSlTpButton")
        self.recalcSlTpButton.setGeometry(QRect(604, 10, 110, 25))
        self.dealHistoryButton = QPushButton(self.centralwidget)
        self.dealHistoryButton.setObjectName(u"dealHistoryButton")
        self.dealHistoryButton.setGeometry(QRect(720, 10, 120, 25))
        self.updatePricesButton = QPushButton(self.centralwidget)
        self.updatePricesButton.setObjectName(u"updatePricesButton")
        self.updatePricesButton.setGeometry(QRect(1020, 10, 89, 25))
        self.macroLabel = QLabel(self.centralwidget)
        self.macroLabel.setObjectName(u"macroLabel")
        self.macroLabel.setGeometry(QRect(20, 560, 53, 17))
        self.macroProgressBar = QProgressBar(self.centralwidget)
        self.macroProgressBar.setObjectName(u"macroProgressBar")
        self.macroProgressBar.setGeometry(QRect(78, 556, 300, 25))
        self.macroProgressBar.setMinimum(-10)
        self.macroProgressBar.setMaximum(10)
        self.macroProgressBar.setValue(0)
        self.macroButton = QPushButton(self.centralwidget)
        self.macroButton.setObjectName(u"macroButton")
        self.macroButton.setGeometry(QRect(790, 556, 100, 25))
        self.indexButton = QPushButton(self.centralwidget)
        self.indexButton.setObjectName(u"indexButton")
        self.indexButton.setGeometry(QRect(894, 556, 100, 25))
        self.corrLabel = QLabel(self.centralwidget)
        self.corrLabel.setObjectName(u"corrLabel")
        self.corrLabel.setGeometry(QRect(410, 560, 53, 17))
        self.corrProgressBar = QProgressBar(self.centralwidget)
        self.corrProgressBar.setObjectName(u"corrProgressBar")
        self.corrProgressBar.setGeometry(QRect(468, 556, 300, 25))
        self.corrProgressBar.setMinimum(-100)
        self.corrProgressBar.setMaximum(100)
        self.corrProgressBar.setValue(0)
        self.corrCommentLabel = QLabel(self.centralwidget)
        self.corrCommentLabel.setObjectName(u"corrCommentLabel")
        self.corrCommentLabel.setGeometry(QRect(468, 584, 300, 20))
        self.corrCommentLabel.setAlignment(AlignCenter)
        self.correlationMatrixButton = QPushButton(self.centralwidget)
        self.correlationMatrixButton.setObjectName(u"correlationMatrixButton")
        self.correlationMatrixButton.setGeometry(QRect(20, 590, 220, 25))
        self.clearDbButton = QPushButton(self.centralwidget)
        self.clearDbButton.setObjectName(u"clearDbButton")
        self.clearDbButton.setGeometry(QRect(252, 590, 120, 25))
        self.quantitiveAssessmentButton = QPushButton(self.centralwidget)
        self.quantitiveAssessmentButton.setObjectName(u"quantitiveAssessmentButton")
        self.quantitiveAssessmentButton.setGeometry(QRect(20, 622, 150, 25))
        self.qualitativeAssessmentButton = QPushButton(self.centralwidget)
        self.qualitativeAssessmentButton.setObjectName(u"qualitativeAssessmentButton")
        self.qualitativeAssessmentButton.setGeometry(QRect(180, 622, 150, 25))
        TradeDiary.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(TradeDiary)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1127, 22))
        TradeDiary.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(TradeDiary)
        self.statusbar.setObjectName(u"statusbar")
        TradeDiary.setStatusBar(self.statusbar)

        self.retranslateUi(TradeDiary)

        QMetaObject.connectSlotsByName(TradeDiary)
    # setupUi

    def retranslateUi(self, TradeDiary):
        TradeDiary.setWindowTitle(QCoreApplication.translate("TradeDiary", u"TradeDiary", None))
        self.equityCurrencyLabel.setText(QCoreApplication.translate("TradeDiary", u"$", None))
        self.equityLabel.setText(QCoreApplication.translate("TradeDiary", u"Equity:", None))
        self.balanceCurrencyLabel.setText(QCoreApplication.translate("TradeDiary", u"$", None))
        self.label.setText(QCoreApplication.translate("TradeDiary", u"Balance:", None))
        self.longButton.setText(QCoreApplication.translate("TradeDiary", u"Long", None))
        self.shortButton.setText(QCoreApplication.translate("TradeDiary", u"Short", None))
        self.recalcSlTpButton.setText(QCoreApplication.translate("TradeDiary", u"Recalc SL/TP", None))
        self.dealHistoryButton.setText(QCoreApplication.translate("TradeDiary", u"Deal History", None))
        self.updatePricesButton.setText(QCoreApplication.translate("TradeDiary", u"Update", None))
        self.macroLabel.setText(QCoreApplication.translate("TradeDiary", u"\u041c\u0430\u043a\u0440\u043e:", None))
        self.macroProgressBar.setFormat(QCoreApplication.translate("TradeDiary", u"%v\u00b0", None))
        self.macroButton.setText(QCoreApplication.translate("TradeDiary", u"\u041c\u0430\u043a\u0440\u043e", None))
        self.indexButton.setText(QCoreApplication.translate("TradeDiary", u"\u0418\u043d\u0434\u0435\u043a\u0441\u044b", None))
        self.corrLabel.setText(QCoreApplication.translate("TradeDiary", u"\u041a\u043e\u0440\u0440:", None))
        self.correlationMatrixButton.setText(QCoreApplication.translate("TradeDiary", u"Correlation Matrix", None))
        self.clearDbButton.setText(QCoreApplication.translate("TradeDiary", u"Clear DB", None))
        self.quantitiveAssessmentButton.setText(QCoreApplication.translate("TradeDiary", u"Quant. Assessment", None))
        self.qualitativeAssessmentButton.setText(QCoreApplication.translate("TradeDiary", u"Qual. Assessment", None))
    # retranslateUi

