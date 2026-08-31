# -*- coding: utf-8 -*-
from urllib.parse import quote_plus

from PySide6 import QtWidgets
from PySide6.QtCore import Qt, QRectF, QRect, QPoint, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen,
                           QPainterPath, QPixmap)
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QWidget, QFrame, QTextEdit)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - fallback
    QWebEngineView = None

GOAT_IMAGE = '/home/vitaly/Downloads/advice_goat.png'

STAGES = ['Management Operation Plan (MOP)', 'KPI', 'Board of directors']

GOAT_IMAGE = '/home/vitaly/Downloads/advice_goat.png'


class GoatAssistant(QWidget):
    """Frameless side popup with the advice goat and a bubble phrase (like Clippy)."""

    _PHASE_DONE_TEXT = 'Отлично! Ты проанализировал {ticker}'

    _MAX_TEXT_W = 220
    _BUBBLE_PAD = 16

    def __init__(self, ticker, parent=None, advice=None, auto_hide_ms=0):
        super().__init__(parent)
        self._src = QPixmap(GOAT_IMAGE)
        if self._src.isNull():
            self._src = QPixmap(1, 1)
        if advice:
            self._quote = advice
        else:
            self._quote = self._PHASE_DONE_TEXT.format(ticker=ticker or 'stock')
        if auto_hide_ms > 0:
            QTimer.singleShot(auto_hide_ms, self.close)

        target_h = 220
        self._pixmap = self._src.scaledToHeight(
            target_h, Qt.TransformationMode.SmoothTransformation)
        self._font = QFont('Sans', 12)
        self._font.setBold(True)
        fm = QFontMetrics(self._font)
        bound = fm.boundingRect(
            QRect(0, 0, self._MAX_TEXT_W, 10000),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            | Qt.TextFlag.TextWordWrap,
            self._quote)
        self._text_w = max(bound.width(), self._MAX_TEXT_W)
        self._text_h = max(bound.height(), 1)
        self._text_rect = QRect(0, 0, self._text_w, self._text_h)
        self._bubble_w = max(self._text_w + 2 * self._BUBBLE_PAD, 160)
        self._bubble_h = max(self._text_h + 2 * self._BUBBLE_PAD, 70)
        gap = 14
        self.setFixedSize(self._bubble_w + gap + self._pixmap.width(),
                          max(self._bubble_h, self._pixmap.height()))
        self.setWindowFlags(Qt.WindowType.Tool
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._place(parent)

    def _place(self, parent=None):
        """Anchor to the bottom-right corner of the screen, not the window.

        The bubble sits to the left of the goat, so placing the right edge of
        the widget against the screen's right edge keeps the phrase visible.
        """
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() - 8
        y = screen.bottom() - self.height() - 8
        self.move(x, y)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._drawBubble(p)
        bx = self.width() - self._pixmap.width()
        by = max(6, (self.height() - self._pixmap.height()) // 2)
        p.drawPixmap(bx, by, self._pixmap)
        p.end()

    def _drawBubble(self, p):
        goat_x = self.width() - self._pixmap.width()
        rect = QRect(8, 8, self._bubble_w, self._bubble_h)

        # Mouth anchor measured on the original 677x369 image, scaled to display.
        mouth_x = 214 * self._pixmap.width() / 677.0
        mouth_y = 115 * self._pixmap.height() / 369.0
        goat_y = max(6, (self.height() - self._pixmap.height()) // 2)
        tip = QPoint(int(goat_x + mouth_x), int(goat_y + mouth_y))

        bubble = QPainterPath()
        bubble.addRoundedRect(rect, 16, 16)
        tail = QPainterPath()
        tail.moveTo(rect.right() - 12, rect.top() + 16)
        tail.lineTo(tip.x(), tip.y())
        tail.lineTo(rect.right(), rect.bottom() - 18)
        tail.closeSubpath()
        bubble = bubble.united(tail)

        p.setPen(QPen(QColor(120, 96, 10), 2))
        p.setBrush(QColor(255, 236, 148))
        p.drawPath(bubble)
        p.setPen(QColor(60, 45, 5))
        p.setFont(self._font)
        p.drawText(self._text_rect.translated(8 + self._BUBBLE_PAD,
                                              8 + self._BUBBLE_PAD),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
                   | Qt.TextFlag.TextWordWrap,
                   self._quote)

_CHIP_CURRENT = ('color: #1e1f24; background-color: #f0c14b; border: 1px solid #ffd76e; '
                 'border-radius: 12px; padding: 6px 16px; font-weight: bold; font-size: 13px;')
_CHIP_DONE = ('color: #7fe0a0; background-color: #1f3a2a; border: 1px solid #2c5a3d; '
              'border-radius: 12px; padding: 6px 16px; font-weight: bold; font-size: 13px;')
_CHIP_UPCOMING = ('color: #9aa0aa; background-color: #26272e; border: 1px solid #3a3c46; '
                  'border-radius: 12px; padding: 6px 16px; font-size: 13px;')


class StageScale(QWidget):
    """Horizontal pill-based scale highlighting the current stage."""

    def __init__(self, stages, parent=None):
        super().__init__(parent)
        self._stages = list(stages)
        self._chips = []
        self._arrows = []

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for i, name in enumerate(self._stages):
            chip = QLabel(name)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(chip)
            self._chips.append(chip)
            if i < len(self._stages) - 1:
                arrow = QLabel('\u279C')
                arrow.setStyleSheet('color: #6a6d78; font-size: 14px;')
                row.addWidget(arrow)
                self._arrows.append(arrow)
        row.addStretch(1)
        self.setStyleSheet('background: transparent;')
        self.hide()

    def set_stage(self, idx):
        for i, chip in enumerate(self._chips):
            if i == idx:
                chip.setStyleSheet(_CHIP_CURRENT)
            elif i < idx:
                chip.setText('\u2713 ' + self._stages[i])
                chip.setStyleSheet(_CHIP_DONE)
            else:
                chip.setText(self._stages[i])
                chip.setStyleSheet(_CHIP_UPCOMING)
            chip.setFixedHeight(30)
        self.show()

    def mark_all_done(self):
        for i, chip in enumerate(self._chips):
            chip.setText('\u2713 ' + self._stages[i])
            chip.setStyleSheet(_CHIP_DONE)
            chip.setFixedHeight(30)
        self.show()


class StarRating(QWidget):
    """Clickable 0..5 star rating control."""

    MAX_STARS = 5

    ratingChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rating = 0
        self.setMinimumSize(190, 40)
        self.setMouseTracking(True)

    def rating(self):
        return self._rating

    def setRating(self, value):
        self._rating = max(0, min(int(value), self.MAX_STARS))
        self.update()

    def _starRect(self, i):
        size = 30
        gap = 4
        return QRectF(i * (size + gap), 4, size, size)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(QFont('Sans', 20))
        for i in range(self.MAX_STARS):
            filled = i < self._rating
            color = QColor(255, 200, 40) if filled else QColor(75, 78, 90)
            p.setPen(QPen(color))
            p.drawText(self._starRect(i), Qt.AlignmentFlag.AlignCenter,
                       '\u2605' if filled else '\u2606')
        p.end()

    def _ratingForPos(self, x):
        size, gap = 30, 4
        idx = int(x // (size + gap))
        return max(0, min(idx + 1, self.MAX_STARS))

    def mousePressEvent(self, event):
        self.setRating(self._ratingForPos(event.position().x()))
        self.ratingChanged.emit(self._rating)


class QualitativeAssessmentDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Qualitative Assessment')
        self.showMaximized()

        self._current_stage = -1
        self._ratings = [0, 0, 0]
        self._notes = ['', '', '']

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        self._build_header(root)
        self._build_scale(root)
        self._build_webview(root)
        self._build_bottom(root)

        self.beginButton.clicked.connect(self._begin_assessment)
        self.nextButton.clicked.connect(self._next_stage)
        self.nextButton.setEnabled(False)
        self.notesButton.clicked.connect(self._open_notes)
        self.notesButton.setEnabled(False)
        self.starRating.ratingChanged.connect(self._on_rating_changed)

    # ------------------------------------------------------------------ UI
    def _build_header(self, root):
        row = QHBoxLayout()
        lbl = QLabel('Ticker:')
        self.tickerEdit = QLineEdit()
        self.tickerEdit.setFixedHeight(28)
        self.beginButton = QPushButton('Begin assessment')
        row.addWidget(lbl)
        row.addWidget(self.tickerEdit, 1)
        row.addWidget(self.beginButton)
        root.addLayout(row)

    def _build_scale(self, root):
        self.scale = StageScale(STAGES)
        root.addWidget(self.scale)

    def _build_webview(self, root):
        if QWebEngineView is None:
            self.webView = QLabel('QtWebEngine is not available.')
            root.addWidget(self.webView, 1)
            return
        self.webView = QWebEngineView()
        root.addWidget(self.webView, 1)

    def _build_bottom(self, root):
        row = QHBoxLayout()
        row.addStretch(1)
        rating_lbl = QLabel('Rating (0-5):')
        self.starRating = StarRating()
        self.notesButton = QPushButton('Notes')
        self.notesButton.setMinimumWidth(80)
        self.nextButton = QPushButton('Next')
        self.nextButton.setMinimumWidth(110)
        row.addWidget(rating_lbl)
        row.addWidget(self.starRating)
        row.addSpacing(20)
        row.addWidget(self.notesButton)
        row.addWidget(self.nextButton)
        root.addLayout(row)

    # ------------------------------------------------------------- helpers
    def _plans(self, ticker):
        return ['{} {}'.format(s, ticker).strip() for s in STAGES]

    # --------------------------------------------------------------- flow
    def _show_goat(self):
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
        self._goat = GoatAssistant(self._ticker, self)
        self._goat.show()

    def closeEvent(self, event):
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
        super().closeEvent(event)

    def _on_rating_changed(self, value):
        if 0 <= self._current_stage < len(STAGES):
            self._ratings[self._current_stage] = value

    def _begin_assessment(self):
        self._ticker = self.tickerEdit.text().strip()
        self._plans_list = self._plans(self._ticker or 'stock')
        self._current_stage = -1
        self._ratings = [0, 0, 0]
        self._notes = ['', '', '']
        self.nextButton.setEnabled(True)
        self.notesButton.setEnabled(True)
        self.starRating.setEnabled(True)
        self._next_stage()

    def _open_notes(self):
        if not (0 <= self._current_stage < len(STAGES)):
            return
        dlg = QDialog(self)
        dlg.setWindowTitle('Notes - {}'.format(STAGES[self._current_stage]))
        dlg.setMinimumSize(420, 260)
        lay = QVBoxLayout(dlg)
        editor = QTextEdit()
        editor.setText(self._notes[self._current_stage])
        lay.addWidget(editor)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok = QPushButton('OK')
        ok.clicked.connect(dlg.accept)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)
        if dlg.exec() == QDialog.Accepted:
            self._notes[self._current_stage] = editor.toPlainText()

    def _stats_html(self):
        rows = []
        total = 0
        for i, name in enumerate(STAGES):
            rating = self._ratings[i]
            total += rating
            note = self._notes[i].strip()
            note_html = '<br><i>Notes:</i> {}'.format(note) if note else ''
            rows.append('<tr><td>{}</td><td style="text-align:center">{}'
                        '/5</td>'
                        '<td style="text-align:left">{}</td></tr>'
                        .format(name, rating, note_html))
        body = ''.join(rows)
        avg = total / len(STAGES) if STAGES else 0
        ticker = self._ticker or 'stock'
        return (
            '<h2>Assessment statistics</h2>'
            '<p>Ticker: <b>{}</b></p>'
            '<table cellpadding="8" cellspacing="0" border="1" '
            'style="border-collapse:collapse" width="100%">'
            '<tr><th>Stage</th><th>Rating</th><th>Notes</th></tr>{}</table>'
            '<p>Average: <b>{:.2f} / 5</b></p>'
            '<p>Total: <b>{}</b> / {}</p>'
        ).format(ticker, body, avg, total,
                 len(STAGES) * StarRating.MAX_STARS)

    def _next_stage(self):
        self._current_stage += 1
        if self._current_stage >= len(STAGES):
            self.nextButton.setEnabled(False)
            self.nextButton.setText('Next')
            self.scale.mark_all_done()
            if QWebEngineView is not None:
                self.webView.setHtml(self._stats_html())
            self._show_goat()
            return
        self.scale.set_stage(self._current_stage)
        self.starRating.setRating(0)
        query = self._plans_list[self._current_stage]
        self.nextButton.setText(
            'Finish' if self._current_stage == len(STAGES) - 1 else 'Next')
        if QWebEngineView is not None:
            url = 'https://www.google.com/search?q=' + quote_plus(query) + '&udm=50'
            self.webView.load(url)
