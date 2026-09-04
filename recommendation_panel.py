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

import recommendation

_BG = '#1e1f24'
_TXT = '#dcdce0'
_GRID = '#43464f'
_MUTED = '#9aa0aa'
_SECTOR_BAR = '#3a5a8c'
_COMPANY_BAR = '#f0c14b'


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
        if e is None:
            self._title = 'Рекомендация'
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
        self._summary.setText('\n'.join(rec['summary_lines']))
        self._mech.setText('\n'.join(rec['expanded_lines']))
        self._draw_bars(self._ax_pe, 'P/E (×)', rec['pe_bars'],
                        lambda v: '{:.1f}'.format(v))
        self._draw_bars(self._ax_epsg, 'EPS growth (%)', rec['epsg_bars'],
                        lambda v: '{:+.1f}%'.format(v))
        self._refresh_canvas()
        self._update_header()

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
        self.setWindowTitle('Сравнение с сектором — {}'.format(
            e.get('ticker') or ''))
        self.resize(840, 660)
        root = QtWidgets.QVBoxLayout(self)

        rec = recommendation.build_recommendation(e)
        self._build_rec_header(root, rec, e)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_tab(
            rec['pe_bars'], 'P/E (×)', lambda v: '{:.1f}'.format(v),
            self._pe_explanation(e)), 'P/E')
        self.tabs.addTab(self._build_tab(
            rec['epsg_bars'], 'EPS growth (%)',
            lambda v: '{:+.1f}%'.format(v), self._epsg_explanation(e, rec)),
            'EPS growth')
        root.addWidget(self.tabs, 1)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        close = QtWidgets.QPushButton('Close')
        close.clicked.connect(self.close)
        row.addWidget(close)
        root.addLayout(row)

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