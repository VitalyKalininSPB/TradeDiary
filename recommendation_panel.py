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
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut

import catalyst
import earnings_snapshot
import recommendation
import simple_mode
import simple_mode_settings

_BG = '#1e1f24'
_TXT = '#dcdce0'
_GRID = '#43464f'
_MUTED = '#9aa0aa'
_SECTOR_BAR = '#3a5a8c'
_COMPANY_BAR = '#f0c14b'

_PE_ON_PAR_PCT = 5.0   # ±5% к медиане сектора → «на уровне peers»
_PCT_HIGH = 70.0       # pct_pe выше → заметно дороже большинства
_PCT_LOW = 30.0        # pct_pe ниже → заметно дешевле большинства


def _esc_html(s):
    return s.replace('&', '&amp;').replace('<', '&lt;')


def _fmt_pe(v):
    return '{:.1f}×'.format(v) if v is not None else '-'


def _trailing_state(e, key):
    """Состояние колонки «Компания сейчас»: ok / loss / unavailable."""
    if e.get(key) is not None:
        return 'ok'
    margin = e.get('net_margin')
    if margin is not None and margin < 0:
        return 'loss'
    return 'unavailable'


def _make_text_selectable(root):
    """Разрешить выделение и копирование (Ctrl+C) текста во всех QLabel."""
    flags = (Qt.TextInteractionFlag.TextSelectableByMouse
             | Qt.TextInteractionFlag.TextSelectableByKeyboard)
    for label in root.findChildren(QtWidgets.QLabel):
        label.setTextInteractionFlags(flags)


def _install_table_copy(table):
    """Ctrl+C копирует выделенные ячейки QTableWidget как tab-separated текст."""
    shortcut = QShortcut(QKeySequence.Copy, table)
    shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)

    def _copy():
        selected = table.selectedItems()
        if not selected:
            return
        rows = sorted({item.row() for item in selected})
        cols = sorted({item.column() for item in selected})
        cells = {(item.row(), item.column()): item.text()
                 for item in selected}
        text = '\n'.join(
            '\t'.join(cells.get((r, c), '') for c in cols)
            for r in rows)
        QtWidgets.QApplication.clipboard().setText(text)

    shortcut.activated.connect(_copy)


# Блоки статуса данных (ключ data_status → подпись в UI).
_DATA_BLOCKS = [
    ('pe_eps', 'Forward P/E / EPS estimates'),
    ('peers', 'Peers'),
    ('short', 'Short interest'),
    ('surprises', 'Earnings surprises'),
    ('margin', 'Margin trend'),
    ('revision', 'Revisions (analyst estimates)'),
]

_DATA_STATUS_TXT = {
    None: 'Загружено',
    'not_requested': 'Не запрашивалось',
    'http_error': 'HTTP-ошибка источника',
    'rate_limited': 'Лимит запросов источника',
    'parse_error': 'Ошибка разбора ответа',
    'schema_changed': 'Схема страницы источника изменилась',
    'source_empty': 'Источник не вернул данные',
    'calculation_unavailable': 'Расчёт недоступен',
}

_DATA_LOADED_KEYS = {
    'pe_eps': ('forward_pe', 'eps_growth', 'trailing_pe',
               'trailing_eps_growth'),
    'peers': ('sector_median_pe', 'sector_median_eps_growth',
              'sector_median_trailing_pe'),
    'short': ('short_float', 'short_date', 'short_ratio'),
    'surprises': ('surprise_avg',),
    'margin': ('net_margin_yoy',),
}


def _data_status_rows(e):
    """[(Блок, reason)] — статус данных из e['data_status'] (fallback по полям)."""
    ds = dict(e.get('data_status') or {})
    out = []
    for key, label in _DATA_BLOCKS:
        reason = ds.get(key)
        if reason is None and key in _DATA_LOADED_KEYS:
            if any(e.get(k) is not None for k in _DATA_LOADED_KEYS[key]):
                reason = None
            else:
                reason = 'not_requested'
        if key == 'revision' and reason is None:
            reason = 'calculation_unavailable'
        out.append((label, reason))
    return out


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


class _EarningsLoaderThread(QThread):
    """Фоновый загрузчик Earnings Snapshot (данные всегда вне UI-потока)."""

    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, ticker, parent=None):
        super().__init__(parent)
        self._ticker = ticker

    def run(self):
        try:
            snap = earnings_snapshot.build_earnings_snapshot(self._ticker)
            self.loaded.emit(snap)
        except Exception as exc:                    # pragma: no cover
            self.failed.emit(str(exc))


def _usd_M(v):
    return '—' if v is None else '{:.0f}M'.format(v / 1e6)


def _eps_txt(v):
    return '—' if v is None else '{:.2f}'.format(v)


def _margin_txt(v):
    return '—' if v is None else '{:.1f}%'.format(v * 100.0)


class EarningsPanel(QtWidgets.QWidget):
    """Блок «Earnings Snapshot»: последний квартал + раскрытие 4 кварталов.

    Источник — SEC EDGAR (Company Facts), загрузка в фоновом потоке
    (запрещено тянуть сеть на UI-потоке). При status != complete показываем
    заметное предупреждение.
    """

    _STATUS_TXT = {
        'complete': 'Полные данные по 4 кварталам (SEC EDGAR).',
        'partial': 'Данные ограничены: часть отчётных показателей недоступна.',
        'insufficient': 'Данных SEC недостаточно для вывода.',
        'unavailable': 'Тикер не найден в SEC (возможно, не US-listed).',
    }

    _COLS = [
        ('period', 'Квартал'),
        ('revenue', 'Выручка'), ('net_income', 'Net income'),
        ('diluted_eps', 'EPS'), ('ocf', 'OCF'), ('capex', 'Capex'),
        ('fcf', 'FCF'), ('cash', 'Cash'), ('net_debt', 'Net debt'),
        ('net_margin', 'Маржа'),
    ]

    def __init__(self, ticker, parent=None):
        super().__init__(parent)
        self._loader = None
        self._ticker = ''
        self._result = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        head = QtWidgets.QLabel('Earnings Snapshot — SEC EDGAR (XBRL)')
        head.setStyleSheet('color: {}; font-size: 13px; '
                           'font-weight: bold;'.format(_TXT))
        lay.addWidget(head)

        self._statusLbl = QtWidgets.QLabel('Загрузка…')
        self._statusLbl.setStyleSheet(
            'color: {}; font-size: 11px;'.format(_MUTED))
        lay.addWidget(self._statusLbl)

        self._warnLbl = QtWidgets.QLabel('')
        self._warnLbl.setWordWrap(True)
        self._warnLbl.setVisible(False)
        lay.addWidget(self._warnLbl)

        self._summaryLbl = QtWidgets.QLabel('')
        self._summaryLbl.setWordWrap(True)
        self._summaryLbl.setStyleSheet(
            'color: {}; font-size: 12px;'.format(_TXT))
        lay.addWidget(self._summaryLbl)

        self._table = QtWidgets.QTableWidget(0, len(self._COLS))
        self._table.setHorizontalHeaderLabels(
            [c for _, c in self._COLS])
        self._table.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setVisible(False)
        lay.addWidget(self._table, 1)

        row = QtWidgets.QHBoxLayout()
        self._expandBtn = QtWidgets.QPushButton('Показать 4 квартала ▾')
        self._expandBtn.setCheckable(True)
        self._expandBtn.setVisible(False)
        self._expandBtn.clicked.connect(self._toggle_table)
        row.addWidget(self._expandBtn)
        row.addStretch(1)
        refresh = QtWidgets.QPushButton('Обновить')
        refresh.clicked.connect(lambda: self.load(self._ticker))
        row.addWidget(refresh)
        lay.addLayout(row)

        self.load(ticker)

    def _toggle_table(self, checked):
        self._table.setVisible(checked)
        self._expandBtn.setText('Показать 4 квартала ▴' if checked
                                else 'Показать 4 квартала ▾')

    def table(self):
        return self._table

    def load(self, ticker):
        self._ticker = ticker or ''
        self._result = None
        self._statusLbl.setText('Загрузка…')
        self._statusLbl.setStyleSheet(
            'color: {}; font-size: 11px;'.format(_MUTED))
        self._warnLbl.setVisible(False)
        self._summaryLbl.setText('')
        self._table.setRowCount(0)
        self._table.setVisible(False)
        self._expandBtn.setChecked(False)
        self._expandBtn.setVisible(False)
        if self._loader is not None and self._loader.isRunning():
            self._loader.wait(5000)
        if not self._ticker:
            self._show_result(None, 'Нет тикера.')
            return
        loader = _EarningsLoaderThread(self._ticker)
        self._loader = loader
        loader.loaded.connect(self._on_loaded)
        loader.failed.connect(self._on_failed)
        loader.start()

    def shutdown(self):
        """Ждать завершения фонового потока до закрытия окна."""
        if self._loader is not None and self._loader.isRunning():
            self._loader.wait(5000)

    def _on_loaded(self, snap):
        self._result = snap
        status = snap.get('status')
        if status is None:
            self._show_result(snap, 'Некорректный ответ сервиса.')
            return
        status_txt = self._STATUS_TXT.get(status, status)
        warn = ''
        if status == 'partial':
            if snap.get('missing_metrics'):
                warn = ('Часть отчётных показателей недоступна: {}. '
                        'Вывод ограничен.'.format(
                            ', '.join(snap['missing_metrics'])))
            else:
                warn = status_txt
        self._show_result(snap, status_txt, warn=warn)

    def _on_failed(self, msg):
        self._show_result(None, 'Ошибка загрузки: {}'.format(msg))

    def _show_result(self, snap, status_txt, warn=''):
        self._statusLbl.setText(status_txt)
        self._statusLbl.setStyleSheet('color: {}; font-size: 11px;'.format(
            _MUTED if (snap is None or bool(warn)) else _TXT))
        if snap is None or not snap.get('quarters'):
            self._warnLbl.setText(warn or '')
            self._warnLbl.setVisible(bool(warn))
            return

        q = snap['quarters'][-1]
        self._summaryLbl.setText(
            'Последний квартал: <b>Q{} {}</b> ({}): '
            'выручка {}, net&nbsp;income {}, EPS {}, OCF {}, '
            'Capex {}, FCF {}, Net&nbsp;debt {}, маржа {}'.format(
                q['fiscal_quarter'], q['fiscal_year'], q['period_end'],
                _usd_M(q['revenue']['value']),
                _usd_M(q['net_income']['value']),
                _eps_txt(q['diluted_eps']['value']),
                _usd_M(q['ocf']['value']),
                _usd_M(q['capex']['value']),
                _usd_M(q['fcf']['value']),
                _usd_M(q['net_debt']['value']),
                _margin_txt(q['net_margin']['value'])))
        self._summaryLbl.setTextFormat(Qt.TextFormat.RichText)

        rows = snap['quarters']
        self._table.setRowCount(len(rows))
        for r, qq in enumerate(rows):
            for c, (key, _) in enumerate(self._COLS):
                if key == 'period':
                    txt = 'Q{} {}'.format(qq['fiscal_quarter'],
                                          qq['fiscal_year'])
                elif key == 'diluted_eps':
                    txt = _eps_txt(qq[key]['value'])
                elif key == 'net_margin':
                    txt = _margin_txt(qq[key]['value'])
                else:
                    txt = _usd_M(qq[key]['value'])
                item = QtWidgets.QTableWidgetItem(txt)
                item.setForeground(QColor(_TXT))
                self._table.setItem(r, c, item)
        self._table.resizeColumnsToContents()
        self._table.setFixedHeight(40 + 28 * len(rows))
        self._expandBtn.setVisible(len(rows) > 1)

        self._warnLbl.setText(warn)
        self._warnLbl.setVisible(bool(warn))
        if warn:
            self._warnLbl.setStyleSheet(
                'color: #e57373; font-size: 12px; font-weight: bold;')


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
        pe_state = _trailing_state(e, 'trailing_pe')
        if pe_state == 'loss':
            pe_tab = self._build_bridge_tab(e)
        elif pe_state == 'unavailable':
            pe_tab = self._build_unavailable_tab(e, 'Trailing P/E')
        else:
            pe_tab = self._build_tab(
                rec['pe_bars'], 'P/E (×)', lambda v: '{:.1f}'.format(v),
                self._pe_explanation(e))
        self.tabs.addTab(pe_tab, 'P/E')
        eg_state = _trailing_state(e, 'trailing_eps_growth')
        if eg_state == 'loss':
            eg_tab = self._build_epsg_bridge_tab(e, rec)
        elif eg_state == 'unavailable':
            eg_tab = self._build_unavailable_tab(e, 'Trailing EPS growth')
        else:
            eg_tab = self._build_tab(
                rec['epsg_bars'], 'EPS growth (%)',
                lambda v: '{:+.1f}%'.format(v), self._epsg_explanation(e, rec))
        self.tabs.addTab(eg_tab, 'EPS growth')
        self.tabs.addTab(self._build_dynamics_tab(rec['dynamics'], rec['short']),
                         'Динамика')
        self._earningsPanel = EarningsPanel(e.get('ticker') or '')
        self.tabs.addTab(self._earningsPanel, 'Earnings')
        self.tabs.addTab(self._build_status_tab(e), 'Статус данных')
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

        _make_text_selectable(self)
        _install_table_copy(self._dynamicsTable)
        _install_table_copy(self._earningsPanel.table())

    def closeEvent(self, event):
        self._earningsPanel.shutdown()
        super().closeEvent(event)

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

    def _build_bridge_tab(self, e):
        """Recovery Layout: TTM-убыток → мост «факт → ожидание» вместо графика."""
        ticker = e.get('ticker') or ''
        sector = e.get('sector') or 'сектора'
        margin = e.get('net_margin')
        fp = e.get('forward_pe')
        sfp = e.get('sector_median_pe')

        gap = (fp / sfp - 1.0) * 100.0 if (fp is not None and sfp) else None
        if gap is None:
            verdict = 'по доступной оценке'
        elif abs(gap) <= _PE_ON_PAR_PCT:
            verdict = 'на уровне peers'
        elif fp < sfp:
            verdict = 'дешевле peers на {:.0f}%'.format(-gap)
        else:
            verdict = 'дороже peers на {:.0f}%'.format(gap)

        parts = [
            '<b>Фактическая прибыльность (TTM)</b>',
            'Net margin: {:+.1f}%'.format(margin),
            'Trailing P/E: не применимо — TTM-убыток',
            '',
            '<b>Ожидаемая оценка (Forward)</b>',
        ]
        if fp is not None:
            parts.append('{} Forward P/E: {:.1f}×'.format(ticker, fp))
        if sfp is not None:
            parts.append('{} peers Forward P/E: {:.1f}×'.format(sector, sfp))
        parts.append('Вывод: рынок оценивает ожидаемое восстановление '
                     '{} {}'.format(ticker, verdict))
        parts.append('')
        parts.append('<span style="color:#e57373;">Риск: вся оценка '
                     'опирается на прогноз возврата к прибыли.</span>')

        tab = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        body = QtWidgets.QLabel('<br>'.join(parts))
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setStyleSheet('color: {}; font-size: 13px;'.format(_TXT))
        lay.addWidget(body)
        lay.addStretch(1)
        return tab

    def _build_unavailable_tab(self, e, metric):
        """Техническая недоступность «Компания сейчас» — без вывода об убытке."""
        tab = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        head = QtWidgets.QLabel('{}: Data unavailable'.format(metric))
        head.setStyleSheet('color: {}; font-weight: bold; font-size: 13px;'
                           .format(_TXT))
        lay.addWidget(head)
        note = QtWidgets.QLabel(
            'Значение отсутствует по технической причине (источник не '
            'вернул данные). Вывод о прибыльности/убытке не делается — '
            'подробности во вкладке «Статус данных».')
        note.setWordWrap(True)
        note.setStyleSheet('color: {}; font-size: 12px;'.format(_MUTED))
        lay.addWidget(note)
        lay.addStretch(1)
        return tab

    def _build_epsg_bridge_tab(self, e, rec):
        """EPS growth при TTM-убытке: forward-сводка, историческая недоступна.

        Без графика с 3 столбцами: «Компания сейчас» отсутствует, а секторный
        TTM показан только как контекст (trailing и forward отвечают на разные
        вопросы и не заменяют друг друга).
        """
        ticker = e.get('ticker') or ''
        feg = e.get('eps_growth')
        sfeg = e.get('sector_median_eps_growth')
        steg = e.get('sector_median_trailing_eps_growth')
        rel = rec.get('rel')

        parts = ['<b>Forward EPS Growth</b>']
        if feg is not None:
            parts.append('{}: {:+.1f}%'.format(ticker, feg))
        if sfeg is not None:
            parts.append('Peers: {:+.1f}%'.format(sfeg))
        if rel is not None:
            parts.append('Преимущество: {:+.1f} п.п.'.format(rel))
        parts.append('')
        parts.append('Historical EPS growth {}: недоступен'.format(ticker))
        if steg is not None:
            parts.append('<span style="color:{};">Контекст: peers выросли '
                         'на {:+.1f}% за TTM; это не сопоставимо с '
                         'forward-прогнозом {}</span>'.format(
                             _MUTED, steg, ticker))

        tab = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        body = QtWidgets.QLabel('<br>'.join(parts))
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setStyleSheet('color: {}; font-size: 13px;'.format(_TXT))
        lay.addWidget(body)
        lay.addStretch(1)
        return tab

    def _build_status_tab(self, e):
        """Статус загрузки блоков данных: Блок → причина отсутствия."""
        tab = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        hint = QtWidgets.QLabel(
            'Статус загрузки блоков данных. «Источник не вернул данные» — '
            'блок отсутствует в ответе; «Расчёт недоступен» — значение '
            'пока не вычисляется (нужен временной ряд analyst estimates).')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: {}; font-size: 12px;'.format(_MUTED))
        lay.addWidget(hint)

        rows = _data_status_rows(e)
        table = QtWidgets.QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels(['Блок', 'Статус'])
        table.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        for r, (block, reason) in enumerate(rows):
            b = QtWidgets.QTableWidgetItem(block)
            b.setForeground(QColor(_TXT))
            s = QtWidgets.QTableWidgetItem(
                _DATA_STATUS_TXT.get(reason, str(reason)))
            s.setForeground(QColor('#81c784' if reason is None else _MUTED))
            table.setItem(r, 0, b)
            table.setItem(r, 1, s)
        table.resizeColumnsToContents()
        table.setFixedHeight(36 + 28 * len(rows))
        lay.addWidget(table)
        lay.addStretch(1)
        self._statusTable = table
        _install_table_copy(table)
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
        self._dynamicsTable = table
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
            gap = (fp / sfp - 1.0) * 100.0
            if abs(gap) <= _PE_ON_PAR_PCT:
                rel_txt = 'Forward P/E: на уровне peers ({} vs {}).'.format(
                    _fmt_pe(fp), _fmt_pe(sfp))
            elif fp < sfp:
                rel_txt = ('Forward P/E: дешевле peers на {:.0f}% '
                           '({} vs {}).'.format(-gap, _fmt_pe(fp),
                                                _fmt_pe(sfp)))
            else:
                rel_txt = ('Forward P/E: дороже peers на {:.0f}% '
                           '({} vs {}).'.format(gap, _fmt_pe(fp),
                                                _fmt_pe(sfp)))
            lines.append(rel_txt)
        if pct is not None:
            if pct > _PCT_HIGH:
                pos_txt = ('Оценка: дороже {:.0f}% компаний сектора '
                           '(дешевле {:.0f}%).'.format(pct, 100 - pct))
            elif pct < _PCT_LOW:
                pos_txt = ('Оценка: дешевле {:.0f}% компаний сектора '
                           '(дороже {:.0f}%).'.format(100 - pct, pct))
            else:
                pos_txt = 'Оценка: на уровне медианы сектора — не дороже ' \
                          'и не дешевле большинства peers.'
            lines.append(pos_txt)
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