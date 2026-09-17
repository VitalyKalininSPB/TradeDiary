# -*- coding: utf-8 -*-
from PySide6 import QtCore, QtGui, QtWidgets

import company_data
import company_fixture
import company_quant
import sector_quant

_TXT = '#dcdce0'
_TIER_COLORS = {
    'Strong': '#2e7d32',
    'Positive': '#1f6f3f',
    'Neutral': '#3a5a8c',
    'Weak': '#9a6b1f',
    'Negative': '#b71c1c',
    'n/a': '#3a3c46',
}
_STATUS_COLORS = {
    'Confirmed strength': '#2e7d32',
    'Quality under pressure': '#9a6b1f',
    'Price-led recovery': '#3a5a8c',
    'Confirmed weakness': '#b71c1c',
}

_HEADERS = ['Rank', 'Sector', 'Signal', 'Score', 'Next step']

# «Следующий шаг» в главной таблице и развёрнутый текст деталей по статусу.
_NEXT_STEP = {
    'Confirmed strength': 'Приоритет для исследования long-кандидатов',
    'Quality under pressure': 'Наблюдать; проверить расхождение сигналов',
    'Price-led recovery': 'Проверить катализатор',
    'Confirmed weakness': 'Исключить из поиска long-кандидатов',
}
_PRIORITY = {
    'Confirmed strength': 'High',
    'Quality under pressure': 'Medium',
    'Price-led recovery': 'Medium',
    'Confirmed weakness': 'Low',
}
_NEXT_STEP_DETAIL = {
    'Confirmed strength':
        'Посмотреть компании {sector} и выбрать те, у которых качественные '
        'финансовые показатели и нет явных qualitative red flags.',
    'Quality under pressure':
        'Разобраться, почему рынок не поддерживает сильную рентабельность '
        '{sector}: проверьте макро- и секторные факторы, свежие отчёты и guidance.',
    'Price-led recovery':
        'Проверить, действительно ли в {sector} начинается циклическое '
        'улучшение прибыльности (маржа, заказы, guidance).',
    'Confirmed weakness':
        '{sector} пока исключён из поиска long-кандидатов — дождитесь '
        'разворота рентабельности и momentum.',
}


class _SectorQuantThread(QtCore.QThread):
    """Fetch sector snapshots, compute and save the rating off the UI thread."""

    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, force, parent=None):
        super().__init__(parent)
        self._force = force

    def run(self):
        try:
            payload = sector_quant.run_sector_quant(force=self._force)
            self.finished.emit(payload)
        except Exception as e:  # noqa: BLE001 - surface the error to the UI
            self.failed.emit(str(e))


class _TickerAnalyzeThread(QtCore.QThread):
    """Фоновый анализ отдельного тикера: сектор, метрики, ranked-строка."""

    analyzed = QtCore.Signal(str, object, object)   # ticker, sector, row
    failed = QtCore.Signal(str, str)                # ticker, error

    def __init__(self, ticker, parent=None):
        super().__init__(parent)
        self._ticker = ticker

    def run(self):
        try:
            row, sector = self._build_ticker_row(self._ticker)
            if row is None:
                self.failed.emit(self._ticker,
                                 'Нет данных по тикеру (проверьте тикер).')
                return
            self.analyzed.emit(self._ticker, sector or '', row)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(self._ticker, str(e))

    @staticmethod
    def _build_ticker_row(ticker):
        metrics = company_data.fetch_company_metrics(ticker)
        if not metrics:
            return None, None
        sector = metrics.get('sector') or ''
        row = {
            'ticker': ticker,
            'company': metrics.get('company_name') or ticker,
            'sector': sector,
            'forward_pe': metrics.get('forward_pe'),
            'trailing_pe': metrics.get('trailing_pe'),
            'eps_growth': metrics.get('eps_growth'),
            'trailing_eps_growth': metrics.get('trailing_eps_growth'),
            'revenue_growth': metrics.get('revenue_growth'),
            'net_margin': metrics.get('net_margin'),
            'net_margin_yoy': metrics.get('net_margin_yoy'),
            'surprise_avg': metrics.get('surprise_avg'),
            'surprise_last': metrics.get('surprise_last'),
            'surprise_n': metrics.get('surprise_n'),
            'earnings_date': metrics.get('earnings_date'),
            'short_float': metrics.get('short_float'),
            'short_change': metrics.get('short_change'),
            'short_ratio': metrics.get('short_ratio'),
            'short_date': metrics.get('short_date'),
            'data_status': metrics.get('data_status') or {},
            'sector_median_pe': None, 'sector_median_trailing_pe': None,
            'sector_median_eps_growth': None,
            'sector_median_trailing_eps_growth': None, 'pct_pe': None,
        }
        fp = metrics.get('forward_pe')
        feg = metrics.get('eps_growth')
        row['peg'] = (fp / feg) if (fp is not None and feg and feg > 0) else None
        if sector in company_fixture._FIXTURE:
            inputs = company_data.sector_companies_cached(sector)
            res = company_quant.rank_companies(inputs)
            scored = [r for r in res if r.get('_rankable')]
            ref = scored[0] if scored else {}
            row['sector_median_pe'] = ref.get('sector_median_pe')
            row['sector_median_trailing_pe'] = ref.get(
                'sector_median_trailing_pe')
            row['sector_median_eps_growth'] = ref.get('sector_median_eps_growth')
            row['sector_median_trailing_eps_growth'] = ref.get(
                'sector_median_trailing_eps_growth')
            pes = [r.get('forward_pe') for r in scored
                   if r.get('forward_pe') is not None]
            row['pct_pe'] = (company_quant._percentile(fp, pes)
                             if fp is not None else None)
            # Включить сам тикер в ранжирование сектора, чтобы получить
            # реальный quant-скор (score_rounded) для записи в Watchlist.
            bench1m = inputs[0].get('benchmarkReturn1mPct') if inputs else None
            bench1y = inputs[0].get('benchmarkReturn1yPct') if inputs else None
            mine_input = {
                'ticker': ticker,
                'companyName': metrics.get('company_name') or ticker,
                'sector': sector,
                'netMarginPct': metrics.get('net_margin'),
                'netMarginYoyChangePp': metrics.get('net_margin_yoy'),
                'return1mPct': metrics.get('return_1m'),
                'return1yPct': metrics.get('return_1y'),
                'benchmarkReturn1mPct': bench1m,
                'benchmarkReturn1yPct': bench1y,
                'forwardPE': metrics.get('forward_pe'),
                'forwardEPSGrowth': metrics.get('eps_growth'),
                'revenueGrowthPct': metrics.get('revenue_growth'),
                'roicPct': metrics.get('roic'),
                'debtEquity': metrics.get('debt_equity'),
            }
            all_ranked = company_quant.rank_companies(inputs + [mine_input])
            mine = [r for r in all_ranked
                    if r.get('ticker') == ticker
                    and r.get('score_rounded') is not None]
            if mine:
                row['score_rounded'] = mine[0]['score_rounded']
                row['company_score'] = mine[0]['company_score']
                row['rank'] = mine[0].get('rank')
        return row, sector


class SectorQuantDialog(QtWidgets.QDialog):
    """Sector Quantitative Assessment: 5-column summary (Rank, Sector, Signal,
    Score, Next step) + a detail panel opened by clicking a sector."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Sector Quantitative Assessment')
        self.resize(900, 720)

        root = QtWidgets.QVBoxLayout(self)

        self.infoLabel = QtWidgets.QLabel('Загрузка…')
        self.infoLabel.setStyleSheet('color: {};'.format(_TXT))
        root.addWidget(self.infoLabel)

        trow = QtWidgets.QHBoxLayout()
        tlabel = QtWidgets.QLabel('Ticker:')
        tlabel.setStyleSheet('color: {};'.format(_TXT))
        self.tickerEdit = QtWidgets.QLineEdit()
        self.tickerEdit.setPlaceholderText('Например: AMD, PFE, MU…')
        self.tickerButton = QtWidgets.QPushButton('Анализ')
        trow.addWidget(tlabel)
        trow.addWidget(self.tickerEdit, 1)
        trow.addWidget(self.tickerButton)
        root.addLayout(trow)
        self.tickerButton.clicked.connect(self._analyze_ticker)
        self.tickerEdit.returnPressed.connect(self._analyze_ticker)

        self.table = QtWidgets.QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemClicked.connect(self._on_item_clicked)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        root.addWidget(self.table, 3)

        self.detail = QtWidgets.QTextBrowser()
        self.detail.setStyleSheet(
            'background: #1e1f24; color: {}; border: 1px solid #43464f;'
            .format(_TXT))
        self.detail.setOpenExternalLinks(False)
        root.addWidget(self.detail, 2)

        row = QtWidgets.QHBoxLayout()
        self.refreshButton = QtWidgets.QPushButton('Refresh')
        self.closeButton = QtWidgets.QPushButton('Close')
        row.addWidget(self.refreshButton)
        row.addStretch(1)
        row.addWidget(self.closeButton)
        root.addLayout(row)

        self.refreshButton.clicked.connect(lambda: self._start(force=True))
        self.closeButton.clicked.connect(self.close)

        self._thread = None
        self._ticker_thread = None
        self._payload = None
        self._current_sector = None
        self._load_cached()
        self._start(force=False)

    def _load_cached(self):
        payload = sector_quant.load_result()
        if payload is not None:
            self._render(payload, from_cache=True)

    def _start(self, force):
        if self._thread is not None and self._thread.isRunning():
            return
        self.refreshButton.setEnabled(False)
        self.infoLabel.setText('Загрузка данных по секторам…')
        self._thread = _SectorQuantThread(force, self)
        self._thread.finished.connect(self._on_finished)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_finished(self, payload):
        self.refreshButton.setEnabled(True)
        self._render(payload, from_cache=False)
        events = payload.get('sector_events') or []
        if events:
            self._show_goat(
                '{} секторов изменили сигнал:\n'.format(len(events))
                + '\n'.join(e['message'] for e in events[:4]))

    def _on_failed(self, error):
        self.refreshButton.setEnabled(True)
        QtWidgets.QMessageBox.warning(
            self, 'Sector Quantitative Assessment', error)
        if not self.table.rowCount():
            self.infoLabel.setText('Нет данных. ' + error)

    def _render(self, payload, from_cache=False):
        self._payload = payload
        sectors = payload.get('sectors', [])
        errors = payload.get('errors', [])
        err_note = ('; без данных: {}'.format(', '.join(errors))) if errors else ''
        status = 'кэш' if from_cache else (payload.get('computed_at') or '')[:16]
        self.infoLabel.setText(
            'Секторов: {} · срез {} · источник {} · расчёт {}{}'.format(
                len(sectors), payload.get('data_date', ''),
                payload.get('source', ''), status, err_note))
        self.table.setRowCount(len(sectors))
        for r, s in enumerate(sectors):
            st = s.get('status') or {}
            signal = st.get('status', '-')
            vals = [
                s.get('rank') if s.get('rank') is not None else '-',
                s.get('sector', ''),
                signal,
                self._fmt(s.get('score')),
                _NEXT_STEP.get(signal, '-'),
            ]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(str(v))
                if c == 2:
                    color = _STATUS_COLORS.get(signal, _TIER_COLORS['n/a'])
                    item.setBackground(QtGui.QColor(color))
                    item.setForeground(QtGui.QColor('#ffffff'))
                    item.setToolTip(st.get('status_ru', ''))
                elif c == 3:
                    item.setForeground(QtGui.QColor(_TXT))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self._show_details(sectors[0] if sectors else None)

    def _on_item_clicked(self, item):
        if self._payload is None:
            return
        sectors = self._payload.get('sectors', [])
        row = item.row()
        if 0 <= row < len(sectors):
            self._show_details(sectors[row])

    def _on_item_double_clicked(self, item):
        """Двойной клик по сектору → переход к компаниям сектора."""
        if self._payload is None:
            return
        sectors = self._payload.get('sectors', [])
        row = item.row()
        if 0 <= row < len(sectors):
            self._current_sector = sectors[row].get('sector', '')
            self._view_companies()

    def _show_details(self, s):
        if s is None:
            self.detail.setPlainText('')
            self._current_sector = None
            return
        st = s.get('status') or {}
        signal = st.get('status', '-')
        sector = s.get('sector', '')
        self._current_sector = sector
        rel_pp = s.get('rel_margin_pp')
        if rel_pp is None:
            rel_line = '• Net Margin: {}'.format(self._fmt(s.get('net_margin'), '%'))
        else:
            rel_line = ('• Net Margin: {}, на {:.1f} п.п. {} среднего по '
                        'секторам'.format(
                            self._fmt(s.get('net_margin'), '%'), abs(rel_pp),
                            'выше' if rel_pp >= 0 else 'ниже'))
        lines = [
            '{} — {}'.format(sector, signal),
            '',
            'Score: {}'.format(self._fmt(s.get('score'))),
            'Priority: {}'.format(_PRIORITY.get(signal, '-')),
            '',
            'Почему:',
            rel_line,
            '• Relative Profitability: {:+.2f}'.format(s.get('profit'))
            if s.get('profit') is not None else '• Relative Profitability: -',
            '• Rel Momentum 1M: {:+.1f} п.п.'.format(s.get('rel_mom_1m'))
            if s.get('rel_mom_1m') is not None else '• Rel Momentum 1M: -',
            '• Rel Momentum 1Y: {:+.1f} п.п.'.format(s.get('rel_mom_1y'))
            if s.get('rel_mom_1y') is not None else '• Rel Momentum 1Y: -',
            '• Momentum: {:+.2f}'.format(s.get('momentum'))
            if s.get('momentum') is not None else '• Momentum: -',
            '',
            'Следующий шаг:',
            _NEXT_STEP_DETAIL.get(signal, '-').format(sector=sector),
        ]
        self.detail.setPlainText('\n'.join(lines))

    def _analyze_ticker(self):
        ticker = self.tickerEdit.text().strip().upper()
        if not ticker:
            return
        if self._ticker_thread is not None and self._ticker_thread.isRunning():
            return
        self.tickerButton.setEnabled(False)
        self.infoLabel.setText('Анализ тикера {}…'.format(ticker))
        self._ticker_thread = _TickerAnalyzeThread(ticker, self)
        self._ticker_thread.analyzed.connect(self._on_ticker_analyzed)
        self._ticker_thread.failed.connect(self._on_ticker_failed)
        self._ticker_thread.start()

    def _on_ticker_analyzed(self, ticker, sector, row):
        self.tickerButton.setEnabled(True)
        self.infoLabel.setText(
            'Тикер {} · сектор: {}'.format(ticker, sector or 'вне базы'))
        from recommendation_panel import RecommendationDialog
        dlg = RecommendationDialog(row, self.window())
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        main = self.window()
        if hasattr(main, '_dialogs_set'):
            main._dialogs_set().add(dlg)
            dlg.destroyed.connect(lambda obj=None, d=dlg:
                                  main._dialogs_set().discard(d))
        dlg.show()

    def _on_ticker_failed(self, ticker, error):
        self.tickerButton.setEnabled(True)
        self.infoLabel.setText('Тикер {}: {}'.format(ticker, error))

    def _view_companies(self):
        if not self._current_sector:
            return
        from company_dialog import CompanyScreenDialog
        dlg = CompanyScreenDialog(self._current_sector, self.window())
        dlg.exec()

    def _show_goat(self, advice):
        from qualitative_dialog import GoatAssistant
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        if not advice:
            return
        self._goat = GoatAssistant('', self, advice=advice, auto_hide_ms=8000)
        self._goat.show()

    @staticmethod
    def _fmt(value, suffix=''):
        if value is None:
            return '-'
        if suffix:
            return '{:+.1f}{}'.format(value, suffix)
        return '{:+.2f}'.format(value)

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(5000)
        if self._ticker_thread is not None and self._ticker_thread.isRunning():
            self._ticker_thread.wait(5000)
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        super().closeEvent(event)