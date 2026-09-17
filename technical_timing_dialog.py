# -*- coding: utf-8 -*-
"""Блок «Technical timing — Daily» для тикера Watchlist (Simple Mode).

Показывает последний рассчитанный технический статус (из technical_timing.db):
Trend (цена vs SMA 200, cross SMA50/200), Momentum (RSI, MACD), Status,
Reason и мягкое предупреждение (растянутость). Кнопки действия выносятся
сигналами наружу (WatchlistDialog открывает DealDialog / график).

Сам диалог ничего не считает и не ходит в сеть — он только отображает
готовый результат монитора.
"""
from PySide6 import QtWidgets
from PySide6.QtCore import Qt, Signal

_TXT = '#dcdce0'
_MUTED = '#9aa0aa'
_YELLOW = '#f0c14b'
_GRID = '#43464f'


def _esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;')


class TechnicalTimingDialog(QtWidgets.QDialog):
    open_trade_plan = Signal(str)  # ticker
    view_chart = Signal(str)       # ticker

    def __init__(self, ticker, result=None, parent=None):
        super().__init__(parent)
        self._ticker = (ticker or '').strip().upper()
        self.setWindowTitle('Technical timing — {}'.format(self._ticker))
        self.setMinimumWidth(520)
        self.setStyleSheet(
            'QDialog {{ background: #1e1f24; color: {}; }}'.format(_TXT))

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        head = QtWidgets.QLabel('Technical timing — Daily · {}'.format(
            self._ticker))
        head.setStyleSheet('color: {}; font-weight: bold; '
                           'font-size: 13px;'.format(_TXT))
        root.addWidget(head)

        self._statusLbl = QtWidgets.QLabel('')
        self._statusLbl.setWordWrap(True)
        self._statusLbl.setStyleSheet('color: #ffffff; font-weight: bold;'
                                      ' font-size: 13px; padding: 4px 8px;'
                                      ' border-radius: 4px;')
        root.addWidget(self._statusLbl)

        self._body = QtWidgets.QLabel('')
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setStyleSheet('color: {}; font-size: 12px;'.format(_TXT))
        root.addWidget(self._body)

        self._warnLbl = QtWidgets.QLabel('')
        self._warnLbl.setWordWrap(True)
        self._warnLbl.setVisible(False)
        self._warnLbl.setStyleSheet(
            'color: {}; font-size: 12px; font-weight: bold;'.format(_YELLOW))
        root.addWidget(self._warnLbl)

        self._metaLbl = QtWidgets.QLabel('')
        self._metaLbl.setStyleSheet('color: {}; font-size: 10px;'.format(
            _MUTED))
        root.addWidget(self._metaLbl)

        row = QtWidgets.QHBoxLayout()
        tradeBtn = QtWidgets.QPushButton('Open trade plan')
        chartBtn = QtWidgets.QPushButton('View chart')
        keepBtn = QtWidgets.QPushButton('Keep watching')
        row.addWidget(tradeBtn)
        row.addWidget(chartBtn)
        row.addStretch(1)
        row.addWidget(keepBtn)
        root.addLayout(row)

        tradeBtn.clicked.connect(
            lambda: self.open_trade_plan.emit(self._ticker))
        chartBtn.clicked.connect(lambda: self.view_chart.emit(self._ticker))
        keepBtn.clicked.connect(self.close)

        self._render(result)

    def _render(self, result):
        status = (result or {}).get('status') or 'no_data'
        status_txt = (result or {}).get('status_txt') or 'Нет данных'
        color = (result or {}).get('status_color') or _MUTED

        self._statusLbl.setText(status_txt)
        self._statusLbl.setStyleSheet(
            'color: #ffffff; font-weight: bold; font-size: 13px;'
            ' background-color: {}; padding: 4px 8px;'
            ' border-radius: 4px;'.format(color))

        if not result:
            self._body.setText(
                '<span style="color:{0};">Технический статус ещё не '
                'рассчитан. Закройте окно и откройте Watchlist — статус '
                'пересчитается в фоне (нужны свежие цены и ~год дневной '
                'истории).</span>'.format(_MUTED))
            self._warnLbl.setVisible(False)
            self._metaLbl.setText('')
            return

        price = result.get('price_txt') or '—'
        sma50 = result.get('sma50_txt') or '—'
        sma200 = result.get('sma200_txt') or '—'
        pvs = result.get('price_vs_sma200_txt') or '—'
        cross = result.get('cross_txt') or '—'
        rsi = result.get('rsi_txt') or '—'
        macd = result.get('macd_txt') or '—'

        lines = [
            '<b>Trend:</b>',
            '&nbsp;&nbsp;Price vs SMA 200: {} ({} vs {})'.format(
                _esc(pvs), _esc(price), _esc(sma200)),
            '&nbsp;&nbsp;SMA 50 vs SMA 200: {} ({} vs {})'.format(
                _esc(cross), _esc(sma50), _esc(sma200)),
            '<b>Momentum:</b>',
            '&nbsp;&nbsp;RSI(14): {}'.format(_esc(rsi)),
            '&nbsp;&nbsp;MACD: {}'.format(_esc(macd)),
            '<b>Reason:</b> {}'.format(_esc(result.get('reason') or '')),
        ]
        self._body.setText('<br>'.join(lines))

        warning = result.get('warning') or ''
        self._warnLbl.setText(('⚠ ' + warning) if warning else '')
        self._warnLbl.setVisible(bool(warning))

        as_of = result.get('as_of') or '—'
        computed = (result.get('computed_at') or '')[:16]
        self._metaLbl.setText('Данные на {} · расчёт {}'.format(
            as_of, computed))