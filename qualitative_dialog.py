# -*- coding: utf-8 -*-
import os

from urllib.parse import quote_plus


# Картинка козы. Ищем в repo `assets/`, затем — пользовательский Downloads.
_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
_GOAT_CANDIDATES = [
    os.path.join(_ASSET_DIR, 'advice_goat.png'),
    '/home/vitaly/Downloads/advice_goat.png',
]
GOAT_IMAGE = next((p for p in _GOAT_CANDIDATES if os.path.exists(p)), '')
if not GOAT_IMAGE:
    GOAT_IMAGE = _GOAT_CANDIDATES[0]

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

STAGES = ['Management Operation Plan (MOP)', 'KPI',
          'Management Track Record', 'Board of directors',
          'Insider Stock & Option Ownership',
          'Research Analyst Estimates, Range and Ratings']

# Промт этапа MOP. Показываем как копируемый текст в webview (в URL Google
# поиска длинный русский текст не помещается — кириллица кодируется в 4–6 раз
# длиннее, лимит ~2048 символов).
MOP_PROMPT = """Проведи краткий MOP-анализ компании [ТИКЕР] для горизонта 20–60 торговых дней.

Под MOP понимай публичный Management & Operations Plan: текущие стратегические и операционные приоритеты, распределение ресурсов, guidance, сроки и ключевые инициативы. Не ищи обязательно документ с названием MOP; восстанови план из последних earnings release/call, 10-Q/10-K, investor presentation и официальных заявлений.

Ответь по-русски:
1) 3–5 главных приоритетов компании;
2) конкретные цели, сроки и guidance;
3) что изменилось с прошлого квартала;
4) насколько план реалистичен: Strong/Adequate/Weak;
5) главный фактор, способный повлиять на акцию в ближайшие 20–60 дней.

Отделяй факты от выводов. Для каждого важного факта дай ссылку и дату источника."""

KPI_PROMPT = """Определи ключевые KPI компании [ТИКЕР], которые рынок будет оценивать в следующие 20–60 торговых дней.

Используй последние earnings release/call, filings и investor presentation. Не подменяй KPI общими финансовыми показателями: выбери именно метрики, по которым можно проверить исполнение текущего MOP.

Дай таблицу:
KPI | Последнее значение | Guidance/ожидание | Ближайшая дата обновления | Что будет позитивным сюрпризом | Что будет негативным сюрпризом | Влияние на акции.

В конце назови 3 KPI с наибольшей важностью и объясни, что рынок уже мог заложить в цену. Указывай источники и даты. Пиши по-русски."""

TRACK_RECORD_PROMPT = """Оцени Management Track Record компании [ТИКЕР] за последние 4 квартала для горизонта 20–60 торговых дней.

Проверь обещания CEO и менеджмента: guidance, операционные цели, сроки запусков, маржу, выручку, объёмы, CAPEX, FCF и ключевые KPI — только те показатели, которые компания действительно раскрывала.

Дай таблицу:
Обещание/KPI | Когда заявлено | Срок | Фактический результат | Выполнено/частично/не выполнено | Комментарий.

Затем оцени:
- качество execution: High/Medium/Low;
- качество коммуникации с рынком: High/Medium/Low;
- есть ли повторяющиеся переносы сроков, завышенный guidance или смена приоритетов;
- как этот track record влияет на доверие к ближайшему MOP.

Пиши по-русски, с источниками и датами; отделяй факты от интерпретаций."""

BOARD_PROMPT = """Проведи краткую оценку Board of Directors компании [ТИКЕР] для инвестора с горизонтом 20–60 торговых дней.

Используй последний proxy statement (DEF 14A), 10-K и официальные сообщения. Оцени:
- независимость board;
- концентрацию влияния CEO/основателя;
- релевантность опыта директоров;
- ключевые комитеты: audit, compensation, nomination;
- конфликты интересов, related-party transactions, необычные практики вознаграждения;
- недавние смены директоров, борьбу за контроль, активизм, M&A или иные governance-события.

Итог:
Board quality: Strong/Adequate/Weak.
Есть ли governance-риск для акции в следующие 20–60 дней: да/нет.
Главный вывод в 3 предложениях.

Не перечисляй биографии без связи с рисками или катализаторами. Указывай источники и даты."""

INSIDER_PROMPT = """Проанализируй Insider Stock & Stock Option Ownership компании [ТИКЕР].

Используй последний proxy statement/DEF 14A и актуальные SEC Forms 3, 4 и 5. Разделяй:
- прямое владение акциями;
- RSU/PSU и иные granted/vested awards;
- опционы: число, strike, дата истечения и степень «в деньгах/вне денег», если данные доступны;
- открытые рыночные покупки и продажи;
- продажи из-за налогов, исполнения опционов или заранее утверждённого 10b5-1 plan — не трактуй их автоматически как bearish-сигнал.

Дай таблицу по CEO, CFO, ключевым руководителям и директорам:
Инсайдер | Акции | Опционы/награды | Изменение за 6–12 месяцев | Тип сделки | Интерпретация.

В конце укажи:
1) alignment management с акционерами: High/Medium/Low;
2) есть ли необычный кластер покупок/продаж;
3) значение для акций на горизонте 20–60 дней.

Пиши по-русски, с датами и первоисточниками."""

ANALYST_PROMPT = """Проанализируй Research Analyst Estimates, Target Price Range и Ratings по компании [ТИКЕР] для горизонта 20–60 торговых дней.

Используй актуальные доступные данные и укажи дату среза. Собери:
- консенсус по revenue, EPS и ключевым KPI на ближайший квартал и финансовый год;
- изменения оценок за последние 30, 60 и 90 дней;
- число Buy/Hold/Sell, если доступно;
- средний, медианный, минимальный и максимальный target price;
- implied upside/downside от текущей цены;
- последние upgrades/downgrades и причины;
- разброс оценок и главный предмет разногласий аналитиков.

Дай таблицу:
Метрика | Консенсус | Диапазон оценок | Изменение за 30/60/90 дней | Что важно для акции.

В конце ответь:
1) ожидания аналитиков повышаются, стабильны или ухудшаются;
2) какая метрика создаёт наибольший риск earnings surprise;
3) насколько позитивный/негативный сценарий уже отражён в цене;
4) вывод для 20–60 торговых дней: bullish/neutral/bearish.

Не используй target price как самостоятельный сигнал к покупке. Указывай источники и даты."""

# Промты для стадий Qualitative Assessment. Подставляются как полный запрос
# Google-поиска при переходе на стадию.
STAGE_PROMPTS = {
    0: ('MOP', MOP_PROMPT),
    1: ('KPI', KPI_PROMPT),
    2: ('Management Track Record', TRACK_RECORD_PROMPT),
    3: ('Board of Directors', BOARD_PROMPT),
    4: ('Insider Stock & Option Ownership', INSIDER_PROMPT),
    5: ('Research Analyst Estimates, Range and Ratings', ANALYST_PROMPT),
}


class GoatAssistant(QWidget):
    """Frameless side popup with the advice goat and a bubble phrase (like Clippy)."""

    _PHASE_DONE_TEXT = 'Отлично! Ты проанализировал {ticker}'

    _MAX_TEXT_W = 220
    _BUBBLE_PAD = 16

    confirmed = Signal()

    def __init__(self, ticker, parent=None, advice=None, auto_hide_ms=0,
                 ok_button=False):
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
        self._cross_pad = 30 if ok_button else 0
        self._bubble_w += self._cross_pad
        gap = 14
        self.setFixedSize(self._bubble_w + gap + self._pixmap.width(),
                          max(self._bubble_h, self._pixmap.height()))
        self.setWindowFlags(Qt.WindowType.Tool
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if ok_button:
            self._add_close_button()
        self._place(parent)

    def _add_close_button(self):
        btn = QPushButton('\u2715', self)
        btn.setFixedSize(20, 20)
        btn.setStyleSheet(
            'QPushButton { background-color: #2a2b30; color: #ef5350; '
            'border: 1px solid #ef5350; border-radius: 10px; '
            'font-weight: bold; font-size: 13px; }'
            'QPushButton:hover { background-color: #4a2a2e; }')
        btn.move(8 + self._bubble_w - 26, 8)
        btn.setToolTip('Подтвердить прочтение')
        btn.clicked.connect(self._on_ok)
        self._okBtn = btn

    def _on_ok(self):
        self.confirmed.emit()
        self.close()

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
        self._assessment_started = False
        self._ratings = [0] * len(STAGES)
        self._notes = [''] * len(STAGES)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        self._build_header(root)
        self._build_scale(root)
        self._build_webview(root)
        self._build_bottom(root)

        self.beginButton.clicked.connect(self._on_begin_button)
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

    def _on_begin_button(self):
        if self._assessment_started:
            self._add_to_watchlist()
        else:
            self._begin_assessment()

    def _add_to_watchlist(self):
        ticker = self._ticker or ''
        if not ticker:
            return
        import datetime
        from watchlist import add as watchlist_add
        ratings = [r for r in self._ratings if r > 0]
        qual = (sum(ratings) / len(ratings)) if ratings else 0.0
        snapshot = {'qual': round(qual, 2),
                    'date': datetime.date.today().isoformat()}
        from watchlist_dialog import WatchlistEntryDialog
        dlg = WatchlistEntryDialog(ticker=ticker, snapshot=snapshot,
                                   parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        res = watchlist_add(v['ticker'], v['status'], v['note'], v['reason'],
                            snapshot=snapshot)
        self.beginButton.setText('Added to Watchlist')
        self.beginButton.setEnabled(False)
        QtWidgets.QMessageBox.information(
            self, 'Watchlist',
            '{} {} в watchlist (Qual {:.2f}/5).'.format(
                v['ticker'],
                'добавлен' if res == 'added' else 'обновлён', qual))

    def _begin_assessment(self):
        self._ticker = self.tickerEdit.text().strip()
        self._plans_list = self._plans(self._ticker or 'stock')
        self._current_stage = -1
        self._ratings = [0] * len(STAGES)
        self._notes = [''] * len(STAGES)
        self._assessment_started = True
        self.beginButton.setText('Add to Watchlist')
        self.beginButton.setEnabled(False)
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
            self.beginButton.setEnabled(True)
            if QWebEngineView is not None:
                self.webView.setHtml(self._stats_html())
            self._show_goat()
            return
        self.scale.set_stage(self._current_stage)
        self.starRating.setRating(0)
        query = self._plans_list[self._current_stage]
        if self._current_stage in STAGE_PROMPTS:
            _, prompt = STAGE_PROMPTS[self._current_stage]
            query = prompt.replace('[ТИКЕР]', self._ticker or 'N/A')
        self.nextButton.setText(
            'Finish' if self._current_stage == len(STAGES) - 1 else 'Next')
        if QWebEngineView is not None:
            url = 'https://www.google.com/search?q=' + quote_plus(query) + '&udm=50'
            self.webView.load(url)
