# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'editdeal.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QDialog,
    QDialogButtonBox, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QTextEdit, QWidget)

class Ui_Deal(object):
    def setupUi(self, Deal):
        if not Deal.objectName():
            Deal.setObjectName(u"Deal")
        Deal.resize(1190, 722)
        self.label_3 = QLabel(Deal)
        self.label_3.setObjectName(u"label_3")
        self.label_3.setGeometry(QRect(5, 122, 91, 17))
        self.takeprofitEdit = QLineEdit(Deal)
        self.takeprofitEdit.setObjectName(u"takeprofitEdit")
        self.takeprofitEdit.setEnabled(False)
        self.takeprofitEdit.setGeometry(QRect(310, 221, 71, 25))
        self.takeprofitEdit.setAutoFillBackground(False)
        self.takeprofitEdit.setReadOnly(True)
        self.label = QLabel(Deal)
        self.label.setObjectName(u"label")
        self.label.setGeometry(QRect(5, 9, 81, 17))
        self.label_4 = QLabel(Deal)
        self.label_4.setObjectName(u"label_4")
        self.label_4.setGeometry(QRect(5, 162, 121, 17))
        self.label_5 = QLabel(Deal)
        self.label_5.setObjectName(u"label_5")
        self.label_5.setGeometry(QRect(10, 225, 111, 17))
        self.priceEdit = QLineEdit(Deal)
        self.priceEdit.setObjectName(u"priceEdit")
        self.priceEdit.setEnabled(True)
        self.priceEdit.setGeometry(QRect(115, 119, 111, 25))
        self.priceEdit.setReadOnly(False)
        self.ticketEdit = QLineEdit(Deal)
        self.ticketEdit.setObjectName(u"ticketEdit")
        self.ticketEdit.setEnabled(False)
        self.ticketEdit.setGeometry(QRect(115, 51, 113, 25))
        self.ticketEdit.setReadOnly(True)
        self.openDateLabel = QLabel(Deal)
        self.openDateLabel.setObjectName(u"openDateLabel")
        self.openDateLabel.setGeometry(QRect(95, 9, 250, 17))
        self.label_7 = QLabel(Deal)
        self.label_7.setObjectName(u"label_7")
        self.label_7.setGeometry(QRect(22, 54, 67, 17))
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        self.label_7.setFont(font)
        self.buttonBox_2 = QDialogButtonBox(Deal)
        self.buttonBox_2.setObjectName(u"buttonBox_2")
        self.buttonBox_2.setGeometry(QRect(10, 675, 341, 32))
        self.buttonBox_2.setOrientation(Qt.Horizontal)
        self.buttonBox_2.setStandardButtons(QDialogButtonBox.Cancel|QDialogButtonBox.Ok)
        self.amountEdit = QLineEdit(Deal)
        self.amountEdit.setObjectName(u"amountEdit")
        self.amountEdit.setEnabled(False)
        self.amountEdit.setGeometry(QRect(115, 156, 113, 25))
        self.amountEdit.setReadOnly(False)
        self.stoplossEdit = QLineEdit(Deal)
        self.stoplossEdit.setObjectName(u"stoplossEdit")
        self.stoplossEdit.setEnabled(False)
        self.stoplossEdit.setGeometry(QRect(120, 221, 71, 25))
        self.stoplossEdit.setReadOnly(True)
        self.label_6 = QLabel(Deal)
        self.label_6.setObjectName(u"label_6")
        self.label_6.setGeometry(QRect(200, 225, 111, 17))
        self.label_9 = QLabel(Deal)
        self.label_9.setObjectName(u"label_9")
        self.label_9.setGeometry(QRect(12, 273, 101, 17))
        self.tradesystemList = QComboBox(Deal)
        self.tradesystemList.addItem("")
        self.tradesystemList.addItem("")
        self.tradesystemList.setObjectName(u"tradesystemList")
        self.tradesystemList.setEnabled(False)
        self.tradesystemList.setGeometry(QRect(138, 268, 241, 25))
        self.closeDealButton = QPushButton(Deal)
        self.closeDealButton.setObjectName(u"closeDealButton")
        self.closeDealButton.setGeometry(QRect(300, 52, 89, 81))
        self.whatsNextEdit = QTextEdit(Deal)
        self.whatsNextEdit.setObjectName(u"whatsNextEdit")
        self.whatsNextEdit.setGeometry(QRect(12, 335, 371, 70))
        self.label_2 = QLabel(Deal)
        self.label_2.setObjectName(u"label_2")
        self.label_2.setGeometry(QRect(10, 315, 161, 17))
        self.label_8 = QLabel(Deal)
        self.label_8.setObjectName(u"label_8")
        self.label_8.setGeometry(QRect(10, 415, 67, 17))
        self.notesEdit = QTextEdit(Deal)
        self.notesEdit.setObjectName(u"notesEdit")
        self.notesEdit.setGeometry(QRect(10, 435, 371, 211))
        self.label_55 = QLabel(Deal)
        self.label_55.setObjectName(u"label_55")
        self.label_55.setGeometry(QRect(6, 16, 101, 40))
        self.closeDateLabel = QLabel(Deal)
        self.closeDateLabel.setObjectName(u"closeDateLabel")
        self.closeDateLabel.setGeometry(QRect(96, 16, 270, 40))
        self.label_10 = QLabel(Deal)
        self.label_10.setObjectName(u"label_10")
        self.label_10.setGeometry(QRect(5, 92, 91, 17))
        self.initpriceEdit = QLineEdit(Deal)
        self.initpriceEdit.setObjectName(u"initpriceEdit")
        self.initpriceEdit.setEnabled(False)
        self.initpriceEdit.setGeometry(QRect(115, 89, 111, 25))
        self.initpriceEdit.setReadOnly(False)

        self.retranslateUi(Deal)

        QMetaObject.connectSlotsByName(Deal)
    # setupUi

    def retranslateUi(self, Deal):
        Deal.setWindowTitle(QCoreApplication.translate("Deal", u"Dialog", None))
        self.label_3.setText(QCoreApplication.translate("Deal", u"Stock Price:", None))
        self.label.setText(QCoreApplication.translate("Deal", u"Open Date:", None))
        self.label_4.setText(QCoreApplication.translate("Deal", u"Stocks Amount", None))
        self.label_5.setText(QCoreApplication.translate("Deal", u"Stop Loss:", None))
        self.openDateLabel.setText(QCoreApplication.translate("Deal", u"TextLabel", None))
        self.label_7.setText(QCoreApplication.translate("Deal", u"Ticker:", None))
        self.label_6.setText(QCoreApplication.translate("Deal", u"Take Profit:", None))
        self.label_9.setText(QCoreApplication.translate("Deal", u"Trade System:", None))
        self.tradesystemList.setItemText(0, QCoreApplication.translate("Deal", u"Average MA", None))
        self.tradesystemList.setItemText(1, QCoreApplication.translate("Deal", u"MACD", None))

        self.closeDealButton.setText(QCoreApplication.translate("Deal", u"Close Deal", None))
        self.label_2.setText(QCoreApplication.translate("Deal", u"What's happen next:", None))
        self.label_8.setText(QCoreApplication.translate("Deal", u"Notes:", None))
        self.label_55.setText(QCoreApplication.translate("Deal", u"Close Date:", None))
        self.closeDateLabel.setText(QCoreApplication.translate("Deal", u"TextLabel", None))
        self.label_10.setText(QCoreApplication.translate("Deal", u"Init Price:", None))
        self.initpriceEdit.setText(QCoreApplication.translate("Deal", u"Initial Price", None))
    # retranslateUi

