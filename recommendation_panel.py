# -*- coding: utf-8 -*-
"""Сворачиваемая панель «Рекомендация» для CompanyScreenDialog.

Свёрнуто — компактная сводка; по клику раскрывается механика
(P/E → forward P/E → EPS growth → peers → revisions) и два 4-столбцовых
графика: сектор/компания × сейчас/форвард для P/E и EPS growth.
"""
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PySide6 import QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

import catalyst
import recommendation
import simple_mode
import simple_mode_settings

_BG = '#1e1f24'
_TXT = '#dcdce0'
_GRID = '#43464f'
_MUTED = '#9aa0aa'
_SECTOR_BAR = '#3a5a8c'
_COMPANY_BAR = '#f0c14b'


def _esc_html(s):
    return s.replace('&', '&amp;').replace('<', '&lt;')


def _card_html_lines(card):
    """Строки Simple-карточки для QLabel (RichText)."""
    lines = []
    if card['sector']:
        lines.append(card['sector'])
    lines += card['facts']
    lines.append(card['catalyst'])
    if card['last_earnings']:
        lines.append(card['last_earnings'])
    lines.append(card['next_earnings'])
    body = '<br>'.join(
        '<span style="color:{0}">{1}</span>'.format(_TXT, _esc_html(l))
        for l in lines)
    return body + '<br><b style="color:{0}">{1}</b>'.format(
        _TXT, _esc_html(card['action']))


class SimpleModePanel(QtWidgets.QFrame):
    """Простая карточка тикера (Simple Mode): вердикт + 3 факта +
    катализатор + earnings + действие. Разворачивается в полный анализ."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            'SimpleModePanel { background: #16171b; border: 1px solid '
            + _GRID + '; border-radius: 6px; }')
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)

        self._title = QtWidgets.QLabel('')
        self._title.setStyleSheet(
            'color: ' + _TXT + '; font-weight: bold; font-size: 13px;')
        lay.addWidget(self._title)

        self._verdict = QtWidgets.QLabel('')
        self._verdict.setWordWrap(True)
        self._verdict.setStyleSheet(
            'color: #ffffff; font-weight: bold; font-size: 13px;'
            ' padding: 4px 8px; border-radius: 4px;')
        lay.addWidget(self._verdict)

        self._body = QtWidgets.QLabel('')
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setStyleSheet('color: {}; font-size: 12px;'.format(_TXT))
        lay.addWidget(self._body)

    def set_company(self, e):
        card = simple_mode.build_simple_card(
            e, catalyst.summary_for(e.get('ticker') or ''))
        self._title.setText(card['title'])
        self._verdict.setText(card['verdict_ru'])
        self._verdict.setStyleSheet(
            'color: #ffffff; font-weight: bold; font-size: 13px;'
            ' background-color: {}; padding: 4px 8px;'
            ' border-radius: 4px;'.format(card['verdict_color']))
        self._body.setText(_card_html_lines(card))


class RecommendationPanel(QtWidgets.QWidget):
    """Сворачиваемая сводка по компании + раскрываемая механика и графики."""

    def __init__(self, parent=None, start_expanded=False):
        super().__init__(parent)
        self._expanded = start_expanded
        self._title = 'Рекомендация'
        self._e = None

        self.setStyleSheet(
            'RecommendationPanel { background: #16171b; '
            'border: 1px solid ' + _GRID + '; border-radius: 6px; }')
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(6)

        self._header = QtWidgets.QPushButton('')
        self._header.setStyleSheet(
            'QPushButton { background: transparent; border: none; '
            'color: ' + _TXT + '; font-weight: bold; font-size: 13px; '
            'text-align: left; padding: 2px; }'
            'QPushButton:hover { color: #ffffff; }')
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(self._header)

        self._verdict = QtWidgets.QLabel('')
        self._verdict.setWordWrap(True)
        self._verdict.setStyleSheet('color: {}; font-weight: bold;'
                                    ' font-size: 12px;'.format(_TXT))
        root.addWidget(self._verdict)

        self._summary = QtWidgets.QLabel('Выберите компанию.')
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet('color: {}; font-size: 12px;'.format(_TXT))
        root.addWidget(self._summary)

        self._expandedBox = QtWidgets.QWidget()
        exlay = QtWidgets.QVBoxLayout(self._expandedBox)
        exlay.setContentsMargins(0, 0, 0, 0)
        exlay.setSpacing(6)
        self._mech = QtWidgets.QLabel('')
        self._mech.setWordWrap(True)
        self._mech.setStyleSheet('color: {}; font-size: 12px;'.format(_MUTED))
        exlay.addWidget(self._mech)

        self._figure = Figure(figsize=(7.5, 3.1), dpi=100, facecolor=_BG)
        self._ax_pe = self._figure.add_subplot(1, 2, 1)
        self._ax_epsg = self._figure.add_subplot(1, 2, 2)
        for ax in (self._ax_pe, self._ax_epsg):
            ax.set_facecolor(_BG)
            for sp in ax.spines.values():
                sp.set_color(_GRID)
        self._canvas = FigureCanvas(self._figure)
        self._canvas.setMinimumHeight(230)
        exlay.addWidget(self._canvas)
        root.addWidget(self._expandedBox)
        if not self._expanded:
            self._expandedBox.hide()

        self._header.clicked.connect(self._toggle)
        self._update_header()

    # ------------------------------------------------------------ helpers
    def _update_header(self):
        arrow = ' ▾' if self._expanded else ' ▸'
        self._header.setText(self._title + arrow)

    def _toggle(self):
        self._expanded = not self._expanded
        self._expandedBox.setVisible(self._expanded)
        self._update_header()

    def set_company(self, e):
        """Пересобрать панель по ranked-строке компании (None — сброс)."""
        self._e = e
        self._render_body()
        simple_mode_settings.simple_changed().connect(self._on_mode_changed)

    def _on_mode_changed(self, on):
        if self._e is not None:
            self._render_body()

    def _render_body(self):
        e = self._e
        if e is None:
            self._title = 'Рекомендация'
            self._verdict.setText('')
            self._summary.setText('Выберите компанию.')
            self._mech.setText('')
            self._draw_bars(self._ax_pe, 'P/E (×)', [],
                            lambda v: '{:.1f}'.format(v))
            self._draw_bars(self._ax_epsg, 'EPS growth (%)', [],
                            lambda v: '{:+.1f}%'.format(v))
            self._refresh_canvas()
            self._update_header()
            return
        ticker = e.get('ticker') or ''
        self._title = 'Рекомендация' + (' — ' + ticker if ticker else '')
        rec = recommendation.build_recommendation(e)
        if simple_mode_settings.is_simple_enabled():
            card = simple_mode.build_simple_card(
                e, catalyst.summary_for(ticker))
            self._verdict.setText(card['verdict_ru'])
            self._verdict.setStyleSheet(
                'color: {}; font-weight: bold;'
                ' font-size: 12px;'.format(card['verdict_color']))
            self._summary.setTextFormat(Qt.TextFormat.RichText)
            self._summary.setText(_card_html_lines(card))
        else:
            dyn = rec['dynamics']
            self._verdict.setText(dyn['verdict'])
            self._verdict.setStyleSheet(
                'color: {}; font-weight: bold;'
                ' font-size: 12px;'.format(dyn['color']))
            self._summary.setTextFormat(Qt.TextFormat.RichText)
            html = self._summary_html(rec['summary_lines'])
            html += self._short_html(rec['short'])
            self._summary.setText(html)
        self._mech.setText('\n'.join(rec['expanded_lines']))
        self._draw_bars(self._ax_pe, 'P/E (×)', rec['pe_bars'],
                        lambda v: '{:.1f}'.format(v))
        self._draw_bars(self._ax_epsg, 'EPS growth (%)', rec['epsg_bars'],
                        lambda v: '{:+.1f}%'.format(v))
        self._refresh_canvas()
        self._update_header()

    @staticmethod
    def _summary_html(lines):
        def esc(s):
            return s.replace('&', '&amp;').replace('<', '&lt;')
        return '<br>'.join(
            '<span style="color:{0}">{1}</span>'.format(_TXT, esc(line))
            for line in lines)

    @staticmethod
    def _short_html(short):
        if short.get('float_pct') is None:
            return ''
        parts = ['{:.1f}% float'.format(short['float_pct'])]
        if short.get('change_pct') is not None:
            parts.append('изм. {:+.1f}%'.format(short['change_pct']))
        if short.get('ratio') is not None:
            parts.append('{:.1f} дн. на покрытие'.format(short['ratio']))
        if short.get('date'):
            parts.append('данные на {}'.format(short['date']))
        return ('<br><span style="color:{0}">Short interest: '
                '<b>{1}</b> · {2}</span>').format(
                    short['color'], short['status'], ' · '.join(parts))

    def _refresh_canvas(self):
        try:
            self._figure.tight_layout()
        except Exception:  # noqa: BLE001 - layout best-effort
            pass
        self._canvas.draw()

    @staticmethod
    def _draw_bars(ax, title, bars, fmt):
        ax.clear()
        pts = [(label, value) for label, value in bars if value is not None]
        if not pts:
            ax.set_visible(False)
            return
        ax.set_visible(True)
        labels = [label for label, _ in pts]
        vals = [value for _, value in pts]
        x = list(range(len(vals)))
        colors = [_COMPANY_BAR if 'Компания' in label else _SECTOR_BAR
                  for label in labels]
        ax.bar(x, vals, color=colors, width=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha='right', fontsize=7.5)
        ax.tick_params(axis='y', labelsize=7.5, colors=_TXT)
        ax.set_title(title, fontsize=9, color=_TXT)
        for xi, value in zip(x, vals):
            ax.text(xi, value, fmt(value), ha='center', va='bottom',
                    fontsize=7.5, color=_TXT)
        ax.grid(axis='y', color=_GRID, linewidth=0.6, alpha=0.5)
        ax.set_axisbelow(True)


class RecommendationDialog(QtWidgets.QDialog):
    """Сравнение с сектором: 4-столбцовые графики (P/E, EPS growth) по
    вкладкам + рекомендация с объяснениями для продвинутых пользователей."""

    _REV_TXT = {'up': '↑ растут', 'flat': '→ стабильны',
                'down': '↓ снижаются'}

    def __init__(self, e, parent=None):
        super().__init__(parent)
        self._e = e
        self.setWindowTitle('Сравнение с сектором — {}'.format(
            e.get('ticker') or ''))
        self.resize(840, 660)
        root = QtWidgets.QVBoxLayout(self)

        rec = recommendation.build_recommendation(e)

        self._simplePanel = SimpleModePanel()
        self._simplePanel.set_company(e)
        root.addWidget(self._simplePanel)

        self._recBox = self._build_rec_header(root, rec, e)

        sector_known = any(label.startswith('Сектор') and v is not None
                           for label, v in rec['pe_bars'])
        self._sectorNote = None
        if not sector_known:
            note = QtWidgets.QLabel(
                'Сектор вне базы — сравнение с похожими компаниями недоступно.')
            note.setWordWrap(True)
            note.setStyleSheet('color: {}; font-size: 11px;'.format(_MUTED))
            root.addWidget(note)
            self._sectorNote = note

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_tab(
            rec['pe_bars'], 'P/E (×)', lambda v: '{:.1f}'.format(v),
            self._pe_explanation(e)), 'P/E')
        self.tabs.addTab(self._build_tab(
            rec['epsg_bars'], 'EPS growth (%)',
            lambda v: '{:+.1f}%'.format(v), self._epsg_explanation(e, rec)),
            'EPS growth')
        self.tabs.addTab(self._build_dynamics_tab(rec['dynamics'], rec['short']),
                         'Динамика')
        root.addWidget(self.tabs, 1)

        row = QtWidgets.QHBoxLayout()
        self.detailsButton = QtWidgets.QPushButton('Details ▾')
        self.detailsButton.setCheckable(True)
        self.detailsButton.clicked.connect(self._toggle_details)
        row.addWidget(self.detailsButton)
        row.addStretch(1)
        close = QtWidgets.QPushButton('Close')
        close.clicked.connect(self.close)
        row.addWidget(close)
        root.addLayout(row)

        self._details_shown = False
        self._simple = simple_mode_settings.is_simple_enabled()
        self._apply_visible()
        simple_mode_settings.simple_changed().connect(self._on_mode_changed)

    def _apply_visible(self):
        simple = self._simple
        self._simplePanel.setVisible(simple)
        self._recBox.setVisible(not simple)
        if self._sectorNote is not None:
            self._sectorNote.setVisible(not simple)
        self.detailsButton.setVisible(simple)
        self.detailsButton.setChecked(simple and self._details_shown)
        self.detailsButton.setText(
            'Details ▾' if not self._details_shown else 'Details ▴')
        self.tabs.setVisible((not simple) or self._details_shown)

    def _toggle_details(self):
        self._details_shown = not self._details_shown
        self._apply_visible()

    def _on_mode_changed(self, on):
        if on == self._simple:
            return
        self._simple = on
        self._details_shown = False
        self._apply_visible()

    # -------------------------------------------------------------- helpers
    def _build_rec_header(self, root, rec, e):
        box = QtWidgets.QFrame()
        box.setStyleSheet(
            'QFrame { background: #16171b; border: 1px solid ' + _GRID
            + '; border-radius: 6px; }')
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)
        title = QtWidgets.QLabel('Рекомендация')
        title.setStyleSheet('color: ' + _TXT + '; font-weight: bold;'
                            ' font-size: 13px;')
        lay.addWidget(title)
        for line in rec['summary_lines']:
            color = _TXT
            if line.startswith('Статус:'):
                color = self._status_color(rec['status'])
            lbl = QtWidgets.QLabel(line)
            lbl.setStyleSheet('color: {}; font-size: 12px;'.format(color))
            lay.addWidget(lbl)
        if not any(v is not None for _, v in rec['pe_bars']
                   + rec['epsg_bars']):
            hint = QtWidgets.QLabel(
                'Нет данных по оценкам — фоновое обновление метрик ещё не '
                'завершилось. Повторите чуть позже.')
            hint.setWordWrap(True)
            hint.setStyleSheet('color: {};'.format(_MUTED))
            lay.addWidget(hint)
        root.addWidget(box)
        return box

    @staticmethod
    def _status_color(status):
        if not status:
            return _TXT
        if 'подтверждается' in status or 'возможно' in status:
            return '#81c784'
        return '#ef5350'

    def _build_tab(self, bars, title, fmt, explanation):
        tab = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(tab)
        lay.setContentsMargins(8, 8, 8, 8)
        exp = QtWidgets.QLabel(explanation)
        exp.setWordWrap(True)
        exp.setStyleSheet('color: {}; font-size: 12px;'.format(_MUTED))
        lay.addWidget(exp)
        canvas = FigureCanvas(_bars_figure(bars, title, fmt))
        lay.addWidget(canvas, 1)
        return tab

    def _build_dynamics_tab(self, dyn, short):
        """Turnaround vs Value Trap: таблица показателей + вердикт + риск."""
        tab = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        verdict = QtWidgets.QLabel(dyn['verdict'])
        verdict.setStyleSheet('color: {}; font-size: 14px; '
                              'font-weight: bold;'.format(dyn['color']))
        lay.addWidget(verdict)

        if dyn.get('rev_note'):
            note = QtWidgets.QLabel(dyn['rev_note'])
            note.setWordWrap(True)
            note.setStyleSheet('color: {}; font-size: 11px;'.format(_MUTED))
            lay.addWidget(note)

        table = QtWidgets.QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(
            ['Показатель', 'Значение', 'Что это значит'])
        table.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setRowCount(len(dyn['rows']))
        for r, (name, value, meaning) in enumerate(dyn['rows']):
            for c, v in enumerate((name, value, meaning)):
                item = QtWidgets.QTableWidgetItem(str(v))
                item.setForeground(QColor(_TXT))
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        table.setFixedHeight(36 + 28 * len(dyn['rows']))
        lay.addWidget(table)

        if dyn['earnings_days'] is not None:
            if dyn['earnings_days'] >= 0:
                rep = 'Следующая проверка: квартальный отчёт через {} дней.'.format(
                    dyn['earnings_days'])
            else:
                rep = 'Ближайший отчёт был {} дней назад.'.format(
                    -dyn['earnings_days'])
            lbl = QtWidgets.QLabel(rep)
            lbl.setStyleSheet('color: {}; font-size: 12px;'.format(_TXT))
            lay.addWidget(lbl)

        risk = QtWidgets.QLabel(dyn['risk'])
        risk.setWordWrap(True)
        risk.setStyleSheet('color: {}; font-size: 12px;'.format(_MUTED))
        lay.addWidget(risk)
        confirm = QtWidgets.QLabel(dyn['confirm'])
        confirm.setWordWrap(True)
        confirm.setStyleSheet('color: {}; font-size: 12px;'.format(_MUTED))
        lay.addWidget(confirm)

        if short.get('float_pct') is not None:
            sep = QtWidgets.QFrame()
            sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
            sep.setStyleSheet('color: {};'.format(_GRID))
            lay.addWidget(sep)
            parts = ['{:.1f}% float'.format(short['float_pct'])]
            if short.get('change_pct') is not None:
                parts.append('изменение {:+.1f}%'.format(short['change_pct']))
            if short.get('ratio') is not None:
                parts.append('{:.1f} дн. на покрытие'.format(short['ratio']))
            if short.get('date'):
                parts.append('данные на {}'.format(short['date']))
            box = QtWidgets.QFrame()
            box.setStyleSheet('QFrame { background: #16171b; border: 1px solid '
                              + _GRID + '; border-radius: 6px; }')
            blay = QtWidgets.QVBoxLayout(box)
            blay.setContentsMargins(10, 8, 10, 8)
            t = QtWidgets.QLabel('Short interest')
            t.setStyleSheet('color: {}; font-weight: bold; '
                            'font-size: 12px;'.format(_TXT))
            blay.addWidget(t)
            v = QtWidgets.QLabel('{} · {}'.format(short['status'],
                                                  ' · '.join(parts)))
            v.setWordWrap(True)
            v.setStyleSheet('color: {}; font-size: 12px;'.format(
                short['color']))
            blay.addWidget(v)
            lay.addWidget(box)

        lay.addStretch(1)
        return tab

    @staticmethod
    def _pe_explanation(e):
        tp = e.get('trailing_pe')
        fp = e.get('forward_pe')
        stp = e.get('sector_median_trailing_pe')
        sfp = e.get('sector_median_pe')
        pct = e.get('pct_pe')
        lines = []
        if tp is not None:
            lines.append('P/E сейчас (trailing): {:.1f}× — цена / прибыль '
                         'за последние 12 месяцев.'.format(tp))
        if tp is None and e.get('net_margin') is not None \
                and e.get('net_margin') < 0:
            lines.append('«Компания сейчас» отсутствует: за последние 12 '
                         'месяцев убыток (net margin {:+.1f}%), поэтому '
                         'trailing P/E не вычисляется.'.format(
                             e['net_margin']))
        if stp is not None:
            lines.append('Сектор сейчас (медиана): {:.1f}×.'.format(stp))
        if fp is not None:
            lines.append('Forward P/E: {:.1f}× — цена / ожидаемая прибыль '
                         'на следующий год.'.format(fp))
        if sfp is not None:
            lines.append('Сектор форвардный (медиана): {:.1f}×.'.format(sfp))
        if tp is not None and fp is not None and fp > 0:
            lines.append('Разрыв trailing→forward {:+.0f}%: рынок закладывает '
                         'рост/падение EPS.'.format((tp / fp - 1.0) * 100.0))
        if fp is not None and sfp is not None:
            lines.append('Forward P/E к сектору: компания {} средней по '
                         'сектору.'.format('дешевле' if fp < sfp
                                           else 'дороже'))
        if pct is not None:
            lines.append('Оценка: дороже {:.0f}% компаний сектора '
                         '(дешевле {:.0f}%).'.format(pct, 100 - pct))
        if not lines:
            lines.append('Нет данных по P/E.')
        return '\n'.join(lines)

    @staticmethod
    def _epsg_explanation(e, rec):
        feg = e.get('eps_growth')
        sfeg = e.get('sector_median_eps_growth')
        tepsg = e.get('trailing_eps_growth')
        steg = e.get('sector_median_trailing_eps_growth')
        rel = rec['rel']
        lines = []
        if tepsg is not None:
            lines.append('Рост прибыли текущий (YoY): {:+.1f}% — фактический '
                         'за 12 месяцев.'.format(tepsg))
        if tepsg is None and e.get('net_margin') is not None \
                and e.get('net_margin') < 0:
            lines.append('Trailing EPS growth отсутствует: фактическая '
                         'прибыль за 12 месяцев отрицательная ({:+.1f}% '
                         'net margin).'.format(e['net_margin']))
        if steg is not None:
            lines.append('Сектор текущий (медиана): {:+.1f}%.'.format(steg))
        if feg is not None:
            lines.append('Рост прибыли форвардный (YoY): {:+.1f}% — консенсус '
                         'аналитиков на следующий год.'.format(feg))
        if sfeg is not None:
            lines.append('Сектор форвардный (медиана): {:+.1f}%.'.format(sfeg))
        if rel is not None:
            lines.append('Относительный рост к сектору: {:+.1f} п.п. — {} '
                         'среднего по сектору.'.format(
                             rel, 'выше' if rel >= 0 else 'ниже'))
        if rec['revision'] is not None:
            lines.append('Ожидания аналитиков: {} (оценка по разрыву '
                         'trailing↔forward P/E).'.format(
                             RecommendationDialog._REV_TXT[rec['revision']]))
        if rec['status']:
            lines.append('Статус: {}'.format(rec['status']))
        if not lines:
            lines.append('Нет данных по росту прибыли.')
        return '\n'.join(lines)


def _bars_figure(bars, title, fmt):
    """Figure с одним 4-столбцовым графиком (сектор/компания × сейчас/форвард)."""
    fig = Figure(figsize=(7.2, 3.4), dpi=100, facecolor=_BG)
    ax = fig.add_subplot(111)
    ax.set_facecolor(_BG)
    for sp in ax.spines.values():
        sp.set_color(_GRID)
    pts = [(label, value) for label, value in bars if value is not None]
    if not pts:
        ax.text(0.5, 0.5, 'Нет данных', ha='center', va='center',
                color=_TXT, transform=ax.transAxes)
    else:
        labels = [label for label, _ in pts]
        vals = [value for _, value in pts]
        x = list(range(len(vals)))
        colors = [_COMPANY_BAR if 'Компания' in label else _SECTOR_BAR
                  for label in labels]
        ax.bar(x, vals, color=colors, width=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha='right', fontsize=8)
        ax.tick_params(axis='y', labelsize=8, colors=_TXT)
        ax.set_title(title, fontsize=10, color=_TXT)
        for xi, value in zip(x, vals):
            ax.text(xi, value, fmt(value), ha='center', va='bottom',
                    fontsize=8, color=_TXT)
        ax.grid(axis='y', color=_GRID, linewidth=0.6, alpha=0.5)
        ax.set_axisbelow(True)
    try:
        fig.tight_layout()
    except Exception:  # noqa: BLE001 - layout best-effort
        pass
    return fig