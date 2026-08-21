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

import requests, zipfile, io

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
            'Notes']

    def __init__(self, data):
        super(TableModel, self).__init__()
        self._data = data

    def data(self, index, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self._data[index.row()][index.column()]
        if role == QtCore.Qt.ItemDataRole.BackgroundRole:
            if (self._data[index.row()][4] > self._data[index.row()][1]):
                return QtGui.QBrush(QtGui.QColor(128,100,128))
            elif (self._data[index.row()][4] < self._data[index.row()][1]):
                return QtGui.QBrush(QtGui.QColor(100,128,128))
            else:
                return QtGui.QBrush(QtCore.Qt.GlobalColor.white)

    def setData(self, data):
        self._data = data
        return True

    def rowCount(self, index):
        # The length of the outer list.
        return len(self._data)

    def columnCount(self, index):
        # The following takes the first sub-list, and returns
        # the length (only works if all rows are an equal length)
        return len(self._data[0])


    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if role == QtCore.Qt.ItemDataRole.DisplayRole and orientation == QtCore.Qt.Orientation.Horizontal:
            return self.header_labels[section]
        return QtCore.QAbstractTableModel.headerData(self, section, orientation, role)


class TradeDiary(QtWidgets.QMainWindow):
    def __init__(self):
        super(TradeDiary, self).__init__()
        self.load_ui()
        print("UI loaded")
        self.read_data()
        self.model = TableModel(self.data)
        self.tradeTableView.setModel(self.model)
        self.tradeTableView.clicked.connect(self.editClicked)
        self.longButton.clicked.connect(self.longClicked)
        self.shortButton.clicked.connect(self.shortClicked)
        self.updatePricesButton.clicked.connect(self.updatePricesClicked)
        self.show()

    def load_ui(self):
        loadUi("form.ui", self)
        self.resize(1600, 900)

    def read_data(self):
        DOMTree = xml.dom.minidom.parse("diary.xml")
        collection = DOMTree.documentElement

        self.data = []

        balance = collection.getElementsByTagName("balance")
        for b in balance:
            self.balanceEdit.setText(b.getAttribute('value'))

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
                    deal.getAttribute('analysisNotes')]
            self.data.append(row)

    def closeEvent(self,event):
        print("Close event")

        doc = xml.dom.minidom.parseString("<diary/>")
        root = doc.documentElement

        balance = doc.createElement("balance")
        balance.setAttribute("value", self.balanceEdit.text())
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
       dlg.setData(float(self.balanceEdit.text()))
       dlg.setMode(DirectionType.BUY)
       if dlg.exec():
           print("Success!")
           deal = dlg.makeDeal()
           self.data.append(deal.toArray())
           self.tradeTableView.model().layoutChanged.emit()

       else:
           print("Cancel!")

    def shortClicked(self):
      print("Short clicked")
      dlg = DealDialog()
      dlg.setData(float(self.balanceEdit.text()))
      dlg.setMode(DirectionType.SELL)
      if dlg.exec():
          print("Success!")
          deal = dlg.makeDeal()
          self.data.append(deal.toArray())
          self.tradeTableView.model().layoutChanged.emit()

    def editClicked(self, item):
        print("Edit clicked " + str(item.row()))
        dlg = EditDealDialog()
        dlg.setData(self.data[item.row()], float(self.balanceEdit.text()))
        if dlg.exec():
            print("Success!")
            self.data[item.row()][1] = dlg.priceEdit.text()
            self.data[item.row()][9] = dlg.closeDateLabel.text()
            self.data[item.row()][10] = dlg.whatsNextEdit.toPlainText()
            self.data[item.row()][11] = dlg.notesEdit.toPlainText()
            self.tradeTableView.model().layoutChanged.emit()

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


if __name__ == "__main__":
    app = QApplication([])
    widget = TradeDiary()
    widget.show()
    sys.exit(app.exec_())
