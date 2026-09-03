# -*- coding: utf-8 -*-
from urllib.parse import quote_plus

from PySide6 import QtWidgets

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - fallback
    QWebEngineView = None

# ТЕРМИНОЛОГИЯ: «Today macro» — кнопка в главном окне рядом с Statements:
# открывает встроенный браузер (как в MOP в qualitative_dialog.py) с вопросом
# про важнейшие события для S&P 500 и NASDAQ сегодня.
_QUERY = 'какие важнейшие для S&P500 и NASDAQ события произошли сегодня'


class TodayMacroDialog(QtWidgets.QDialog):
    """Embedded browser with a Google search about today's S&P500/NASDAQ events."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Today macro')
        self.resize(980, 680)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        if QWebEngineView is None:
            lay.addWidget(QtWidgets.QLabel('QtWebEngine is not available.'))
            return
        self.webView = QWebEngineView()
        lay.addWidget(self.webView)
        url = 'https://www.google.com/search?q=' + quote_plus(_QUERY) + '&udm=50'
        self.webView.load(url)