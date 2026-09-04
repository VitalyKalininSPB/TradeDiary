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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
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