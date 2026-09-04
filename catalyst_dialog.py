# -*- coding: utf-8 -*-
import datetime

from urllib.parse import quote_plus

from PySide6 import QtWidgets

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - fallback
    QWebEngineView = None

# Промт Catalyst. Компактный, чтобы URL Google-поиска помещался в лимит ~2048
# символов (кириллица кодируется в 4-6 раз длиннее).
CATALYST_PROMPT = """Катализаторы [ТИКЕР] на 20–60 торговых дней. Перечисли ближайшие события, способные двинуть акцию: отчётность и guidance, запуск продукта, регуляторное решение, суд, сделка M&A. Для каждого: что именно, дата, как проверить, ожидаемый эффект (+/−) и масштаб. Отметь, что, по-видимому, уже в цене. Выдели один главный катализатор. Ссылки и даты. Пиши по-русски."""

# Шкала оценки катализатора (0-5, как звёзды Qualitative Assessment).
CATALYST_SCALE = """0 — нет катализатора;
1–2 — расплывчатый («когда-нибудь станет лучше»);
3–4 — чёткое событие с датой и ожидаемым эффектом;
5 — близко, проверяемо и не заложено в цену."""

_DIRECTIONS = ['+', '−', '±']

_TXT = '#dcdce0'


class CatalystDialog(QtWidgets.QDialog):
    """Встроенный браузер с Google-поиском катализаторов по тикеру (как MOP)
    + быстрый ввод оценки катализатора в watchlist."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Catalyst')
        self.resize(980, 680)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        row = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel('Ticker:')
        self.tickerEdit = QtWidgets.QLineEdit()
        self.tickerEdit.setFixedHeight(28)
        self.askButton = QtWidgets.QPushButton('Ask')
        row.addWidget(lbl)
        row.addWidget(self.tickerEdit, 1)
        row.addWidget(self.askButton)
        root.addLayout(row)

        if QWebEngineView is None:
            self.webView = QtWidgets.QLabel('QtWebEngine is not available.')
            root.addWidget(self.webView, 1)
        else:
            self.webView = QWebEngineView()
            root.addWidget(self.webView, 1)

        self._build_result_bar(root)

        self.askButton.clicked.connect(self._ask)
        self.tickerEdit.returnPressed.connect(self._ask)
        self.saveButton.clicked.connect(self._save_to_watchlist)
        self.saveButton.setEnabled(False)
        self._ticker = ''
        self._rating = 0

    def _build_result_bar(self, root):
        bar = QtWidgets.QHBoxLayout()
        from qualitative_dialog import StarRating
        rating_lbl = QtWidgets.QLabel('Catalyst (0-5):')
        rating_lbl.setToolTip(CATALYST_SCALE)
        rating_lbl.setStyleSheet('color: {};'.format(_TXT))
        self.starRating = StarRating()
        self.directionCombo = QtWidgets.QComboBox()
        self.directionCombo.addItems(_DIRECTIONS)
        self.noteEdit = QtWidgets.QLineEdit()
        self.noteEdit.setPlaceholderText('Что / когда / как проверить…')
        self.saveButton = QtWidgets.QPushButton('Save to Watchlist')
        bar.addWidget(rating_lbl)
        bar.addWidget(self.starRating)
        bar.addWidget(self.directionCombo)
        bar.addWidget(self.noteEdit, 1)
        bar.addWidget(self.saveButton)
        root.addLayout(bar)
        self.starRating.ratingChanged.connect(self._on_rating_changed)

    def _ask(self):
        self._ticker = self.tickerEdit.text().strip().upper()
        if not self._ticker:
            return
        prompt = CATALYST_PROMPT.replace('[ТИКЕР]', self._ticker)
        if QWebEngineView is not None:
            url = 'https://www.google.com/search?q=' + quote_plus(prompt) + '&udm=50'
            self.webView.load(url)
        self.saveButton.setEnabled(True)

    def _on_rating_changed(self, value):
        self._rating = value

    def _save_to_watchlist(self):
        ticker = self._ticker or self.tickerEdit.text().strip().upper()
        if not ticker:
            return
        snapshot = {'catalyst': self._rating,
                    'catalyst_dir': self.directionCombo.currentText(),
                    'catalyst_note': self.noteEdit.text().strip(),
                    'date': datetime.date.today().isoformat()}
        from watchlist import add as watchlist_add
        from watchlist_dialog import WatchlistEntryDialog
        dlg = WatchlistEntryDialog(ticker=ticker, snapshot=snapshot, parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        res = watchlist_add(v['ticker'], v['status'], v['note'], v['reason'],
                            snapshot=snapshot)
        QtWidgets.QMessageBox.information(
            self, 'Watchlist',
            '{} {} в watchlist (Catalyst {}/5).'.format(
                v['ticker'],
                'добавлен' if res == 'added' else 'обновлён',
                self._rating))