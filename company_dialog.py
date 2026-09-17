# -*- coding: utf-8 -*-
from PySide6 import QtCore, QtGui, QtWidgets

import company_data
import company_quant
import recommendation_panel

_TXT = '#dcdce0'
_LABEL_COLORS = {
    company_quant.LABEL_RESEARCH_PRIORITY: '#2e7d32',
    company_quant.LABEL_WATCHLIST: '#3a5a8c',
    company_quant.LABEL_LOW_PRIORITY: '#9a6b1f',
    company_quant.LABEL_INSUFFICIENT: '#5a5d66',
}
_LABEL_RU = {
    company_quant.LABEL_RESEARCH_PRIORITY: 'Приоритет для исследования',
    company_quant.LABEL_WATCHLIST: 'Наблюдать',
    company_quant.LABEL_LOW_PRIORITY: 'Низкий приоритет',
    company_quant.LABEL_INSUFFICIENT: 'Недостаточно данных',
}
# Для Short-вкладки приоритет инвертируется: худшая компания = высший приоритет.
_LABEL_SHORT_RU = {
    company_quant.LABEL_RESEARCH_PRIORITY: 'Низкий приоритет (short)',
    company_quant.LABEL_WATCHLIST: 'Наблюдать (short)',
    company_quant.LABEL_LOW_PRIORITY: 'Высокий приоритет (short)',
    company_quant.LABEL_INSUFFICIENT: 'Недостаточно данных',
}

_HEADERS = ['Rank', 'Ticker', 'Company', 'Net Margin', 'Net Margin YoY',
            'Forward P/E', 'EPS growth %', 'PEG', 'Rev Growth %',
            'ROIC %', 'Debt/Equity', 'Rel Momentum 1M', 'Rel Momentum 1Y',
            'Company Score', 'Research status', 'Сравнение с сектором']

# Коза для одной компании показывается не более 2 раз за запуск приложения
# (иначе информационный перегруз). Счётчик в памяти — сбрасывается при рестарте.
_GOAT_LIMIT = 2
_GOAT_SHOWN = {}


def _interest_coverage_status(ic):
    """Информационный статус Interest coverage (не влияет на скор)."""
    if ic is None:
        return '-'
    if ic >= 5.0:
        return 'Comfortable'
    if ic >= 2.0:
        return 'Acceptable'
    if ic >= 1.5:
        return 'Tight'
    return 'Weak'


class _CompanyDataThread(QtCore.QThread):
    """Обновление живых метрик компаний (не чаще раза в день) в фоне."""

    loaded = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, sector, parent=None):
        super().__init__(parent)
        self._sector = sector

    def run(self):
        try:
            inputs = company_data.sector_companies(self._sector, force=False)
            self.loaded.emit(inputs)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class CompanyScreenDialog(QtWidgets.QDialog):
    """Company screener inside one sector: two lists — long candidates
    (Company Score desc) and short candidates (Company Score asc, weakest
    first). Both use the same neutral metrics; this is not a buy/sell call."""

    def __init__(self, sector, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Companies — {}'.format(sector))
        self.resize(1180, 680)

        root = QtWidgets.QVBoxLayout(self)
        self.infoLabel = QtWidgets.QLabel('')
        self.infoLabel.setStyleSheet('color: {};'.format(_TXT))
        root.addWidget(self.infoLabel)

        self.tabs = QtWidgets.QTabWidget()
        self.longTable = self._make_table()
        self.shortTable = self._make_table()
        self.tabs.addTab(self.longTable, 'Long candidates')
        self.tabs.addTab(self.shortTable, 'Short candidates')
        self.longTable.itemClicked.connect(
            lambda item: self._on_company_clicked(self.longTable, item))
        self.shortTable.itemClicked.connect(
            lambda item: self._on_company_clicked(self.shortTable, item))
        root.addWidget(self.tabs, 3)

        self.recPanel = recommendation_panel.RecommendationPanel()
        root.addWidget(self.recPanel)

        self.detail = QtWidgets.QTextBrowser()
        self.detail.setStyleSheet(
            'background: #1e1f24; color: {}; border: 1px solid #43464f;'
            .format(_TXT))
        root.addWidget(self.detail, 2)

        row = QtWidgets.QHBoxLayout()
        self.watchButton = QtWidgets.QPushButton('Add to watchlist')
        self.qualButton = QtWidgets.QPushButton('Qualitative Assessment')
        self.qualButton.setEnabled(False)
        closeButton = QtWidgets.QPushButton('Close')
        row.addWidget(self.watchButton)
        row.addWidget(self.qualButton)
        row.addStretch(1)
        row.addWidget(closeButton)
        root.addLayout(row)
        self.watchButton.clicked.connect(self._add_to_watchlist)
        self.qualButton.clicked.connect(self._open_qualitative)
        closeButton.clicked.connect(self.close)

        self._sector = sector
        self._thread = None
        self._long_rows = []
        self._short_rows = []
        self._load()

    def _make_table(self):
        table = QtWidgets.QTableWidget(0, len(_HEADERS))
        table.setHorizontalHeaderLabels(_HEADERS)
        table.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _load(self):
        inputs = company_data.sector_companies_cached(self._sector)
        if not inputs:
            self.infoLabel.setText(
                'Сектор {}: нет данных компаний.'.format(self._sector))
            self.longTable.setRowCount(0)
            self.shortTable.setRowCount(0)
        else:
            self._render(inputs, detect=False)
        self._start_refresh()

    def _start_refresh(self):
        if self._thread is not None and self._thread.isRunning():
            return
        self._thread = _CompanyDataThread(self._sector, self)
        self._thread.loaded.connect(self._on_loaded)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_loaded(self, inputs):
        self._render(inputs, detect=True)

    def _on_failed(self, error):
        self.infoLabel.setText(self.infoLabel.text() + ' · ошибка метрик: ' + error)

    def _render(self, inputs, detect=False):
        rows = company_quant.rank_companies(inputs)
        events = []
        if detect:
            from quant_alerts import check_company_scores
            try:
                events = check_company_scores(inputs)
            except Exception as e:  # noqa: BLE001
                print('Company alerts: {}'.format(e))
        scored = [r for r in rows if r['company_score'] is not None]
        unscored = [r for r in rows if r['company_score'] is None]
        long_rows = sorted(
            [r for r in scored
             if r['label'] in (company_quant.LABEL_RESEARCH_PRIORITY,
                               company_quant.LABEL_WATCHLIST)],
            key=lambda r: r['company_score'], reverse=True)
        short_rows = sorted(
            [r for r in scored
             if r['label'] == company_quant.LABEL_LOW_PRIORITY],
            key=lambda r: r['company_score'])
        for i, r in enumerate(long_rows, start=1):
            r['_long_rank'] = i
        for i, r in enumerate(short_rows, start=1):
            r['_short_rank'] = i
        note = ''
        if events:
            note = ' · {} компаний изменили score'.format(len(events))
        if unscored:
            note += ' · {} без данных'.format(len(unscored))
        self.infoLabel.setText(
            'Сектор {} · Long {} · Short {} · Long = сильные, Short = худшие{}'.format(
                self._sector, len(long_rows), len(short_rows), note))
        if events:
            self._show_goat(
                'Компании изменили score:\n' + '\n'.join(
                    e['message'] for e in events[:4]))
        self._fill(self.longTable, long_rows, '_long_rank')
        self._fill(self.shortTable, short_rows, '_short_rank', short=True)
        self._long_rows = long_rows
        self._short_rows = short_rows
        self._show_company_detail(long_rows[0] if long_rows else None,
                                  from_click=False)

    def _on_company_clicked(self, table, item):
        rows = self._long_rows if table is self.longTable else self._short_rows
        row = item.row()
        if 0 <= row < len(rows):
            self._show_company_detail(rows[row],
                                      short=table is self.shortTable,
                                      from_click=True)

    def _sector_context(self):
        try:
            from sector_quant import load_result
            payload = load_result()
        except Exception:  # noqa: BLE001
            return None
        for s in (payload or {}).get('sectors', []):
            if s.get('sector') == self._sector:
                return s
        return None

    def _show_company_detail(self, s, short=False, from_click=False):
        if s is None:
            self.detail.setPlainText('')
            self.qualButton.setEnabled(False)
            self.recPanel.set_company(None)
            return
        self.recPanel.set_company(s)
        label = s.get('label', company_quant.LABEL_INSUFFICIENT)
        title = (_LABEL_SHORT_RU if short else _LABEL_RU).get(label, label)
        company = s.get('company') or s.get('ticker') or ''
        sr = self._sector_context()
        lines = ['{} — {}'.format(company, title), '']

        lines.append('Почему попала в shortlist:')
        margin = s.get('net_margin')
        pct_margin = s.get('pct_margin')
        if margin is not None and pct_margin is not None:
            lines.append('• Net Margin: {:.1f}% — выше {:.0f}% компаний '
                         '{}'.format(margin, pct_margin, self._sector))
        elif margin is not None:
            lines.append('• Net Margin: {:.1f}%'.format(margin))
        else:
            lines.append('• Net Margin: -')
        rp = s.get('relative_profitability')
        lines.append('• Relative Profitability: {:+.2f}'.format(rp)
                     if rp is not None else '• Relative Profitability: -')
        r1m = s.get('rel_momentum_1m')
        lines.append('• Relative Momentum 1M: {:+.1f} п.п.'.format(r1m)
                     if r1m is not None else '• Relative Momentum 1M: -')
        r1y = s.get('rel_momentum_1y')
        lines.append('• Relative Momentum 1Y: {:+.1f} п.п.'.format(r1y)
                     if r1y is not None else '• Relative Momentum 1Y: -')
        pe = s.get('forward_pe')
        pct_pe = s.get('pct_pe')
        if pe is not None and pct_pe is not None:
            lines.append('• Forward P/E: {:.1f}× — дешевле {:.0f}% компаний '
                         '{}'.format(pe, 100 - pct_pe, self._sector))
        elif pe is not None:
            lines.append('• Forward P/E: {:.1f}×'.format(pe))
        else:
            lines.append('• Forward P/E: -')
        eg = s.get('eps_growth')
        lines.append('• EPS growth (YoY): {:+.1f}%'.format(eg)
                     if eg is not None else '• EPS growth (YoY): -')
        peg = s.get('peg')
        pct_peg = s.get('pct_peg')
        if peg is not None and pct_peg is not None:
            lines.append('• PEG: {:.2f} — дешевле {:.0f}% компаний '
                         '{}'.format(peg, 100 - pct_peg, self._sector))
        elif peg is not None:
            lines.append('• PEG: {:.2f}'.format(peg))
        else:
            lines.append('• PEG: -')
        revg = s.get('revenue_growth')
        pct_revg = s.get('pct_rev_growth')
        if revg is not None and pct_revg is not None:
            lines.append('• Revenue Growth (YoY): {:+.1f}% — выше {:.0f}% '
                         'компаний {}'.format(revg, pct_revg, self._sector))
        elif revg is not None:
            lines.append('• Revenue Growth (YoY): {:+.1f}%'.format(revg))
        else:
            lines.append('• Revenue Growth (YoY): -')
        roic = s.get('roic')
        pct_roic = s.get('pct_roic')
        if roic is not None and pct_roic is not None:
            lines.append('• ROIC: {:+.1f}% — выше {:.0f}% компаний '
                         '{}'.format(roic, pct_roic, self._sector))
        elif roic is not None:
            lines.append('• ROIC: {:+.1f}%'.format(roic))
        else:
            lines.append('• ROIC: -')
        ic = s.get('interest_coverage')
        if ic is not None:
            lines.append('• Interest coverage: {:.1f}× → {}'.format(
                ic, _interest_coverage_status(ic)))
        else:
            lines.append('• Interest coverage: -')
        de = s.get('debt_equity')
        pct_debt = s.get('pct_debt')
        if de is not None and pct_debt is not None:
            lines.append('• Debt/Equity: {:.2f} — выше {:.0f}% компаний '
                         '{}'.format(de, pct_debt, self._sector))
        elif de is not None:
            lines.append('• Debt/Equity: {:.2f}'.format(de))
        else:
            lines.append('• Debt/Equity: -')
        score = s.get('score_rounded')
        lines.append('• Company Score: {:+.2f}'.format(score)
                     if score is not None else '• Company Score: -')

        contribs = s.get('contribs') or []
        if contribs:
            lines.append('')
            lines.append('Компоненты score:')
            lines.append('  ' + ' · '.join(
                '{} {:+.2f}'.format(n, v) for n, v in contribs))
        flags = s.get('flags') or []
        if flags:
            lines.append('')
            lines.append('Флаги:')
            for f in flags:
                lines.append('  • {}'.format(f))

        lines.append('')
        lines.append('Контекст:')
        lines.append('• Sector: {}'.format(self._sector))
        st = (sr or {}).get('status') or {}
        lines.append('• Sector Signal: {}'.format(st.get('status', '-')))
        ss = (sr or {}).get('score')
        lines.append('• Sector Score: {:+.2f}'.format(ss)
                     if ss is not None else '• Sector Score: -')

        lines.append('')
        lines.append('Следующий шаг:')
        lines.append('Запустить Qualitative Assessment.')
        self.detail.setPlainText('\n'.join(lines))
        self.qualButton.setEnabled(True)
        if not from_click:
            return
        flags = s.get('flags') or []
        if flags or label == company_quant.LABEL_RESEARCH_PRIORITY:
            ticker = s.get('ticker') or ''
            shown = _GOAT_SHOWN.get(ticker, 0)
            if shown < _GOAT_LIMIT:
                _GOAT_SHOWN[ticker] = shown + 1
                self._show_goat(self._company_goat_text(s, short))

    def _company_goat_text(self, s, short=False):
        label = s.get('label', company_quant.LABEL_INSUFFICIENT)
        title = (_LABEL_SHORT_RU if short else _LABEL_RU).get(label, label)
        ticker = s.get('ticker') or s.get('company') or ''
        flags = s.get('flags') or []
        head = '{} — {}.'.format(ticker, title)
        if flags:
            return head + ' Обратите внимание: ' + '; '.join(flags[:3])
        return head

    def _open_qualitative(self):
        table = self.tabs.currentWidget()
        rows = self._long_rows if table is self.longTable else self._short_rows
        row = table.currentRow()
        if not (0 <= row < len(rows)):
            return
        ticker = rows[row].get('ticker')
        if not ticker:
            return
        from qualitative_dialog import QualitativeAssessmentDialog
        dlg = QualitativeAssessmentDialog(self.window())
        dlg.tickerEdit.setText(ticker)
        dlg.show()

    def _fill(self, table, rows, rank_key, short=False):
        table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            label = s.get('label', company_quant.LABEL_INSUFFICIENT)
            label_ru = (_LABEL_SHORT_RU if short else _LABEL_RU).get(label, label)
            vals = [
                s.get(rank_key) if s.get(rank_key) is not None else '-',
                s.get('ticker') or '-',
                s.get('company') or '-',
                self._fmt(s.get('net_margin'), '%'),
                self._fmt(s.get('net_margin_yoy'), 'pp'),
                self._pe(s.get('forward_pe')),
                self._fmt(s.get('eps_growth'), '%'),
                self._peg(s.get('peg')),
                self._fmt(s.get('revenue_growth'), '%'),
                self._fmt(s.get('roic'), '%'),
                self._ratio(s.get('debt_equity')),
                self._fmt(s.get('rel_momentum_1m'), '%'),
                self._fmt(s.get('rel_momentum_1y'), '%'),
                self._fmt(s.get('score_rounded')),
                label_ru,
            ]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(str(v))
                if c == 14:
                    color = _LABEL_COLORS.get(label, _LABEL_COLORS[
                        company_quant.LABEL_INSUFFICIENT])
                    item.setBackground(QtGui.QColor(color))
                    item.setForeground(QtGui.QColor('#ffffff'))
                    tip = _LABEL_RU.get(label, label)
                    warnings = s.get('warnings') or []
                    if warnings:
                        tip += '\n' + '\n'.join(warnings)
                    item.setToolTip(tip)
                elif c == 5:
                    item.setForeground(self._color_vs(
                        s.get('forward_pe'), s.get('sector_median_pe'),
                        lower_better=True))
                elif c == 6:
                    item.setForeground(self._color_vs(
                        s.get('eps_growth'),
                        s.get('sector_median_eps_growth'),
                        lower_better=False))
                elif c == 7:
                    item.setForeground(self._color_vs(
                        s.get('peg'), s.get('sector_median_peg'),
                        lower_better=True))
                elif c == 8:
                    item.setForeground(self._color_vs(
                        s.get('revenue_growth'),
                        s.get('sector_median_rev_growth'),
                        lower_better=False))
                elif c == 9:
                    item.setForeground(self._color_vs(
                        s.get('roic'), s.get('sector_median_roic'),
                        lower_better=False))
                elif c in (4, 10, 11, 12, 13):
                    item.setForeground(QtGui.QColor(_TXT))
                table.setItem(r, c, item)
            btn = QtWidgets.QPushButton('Сравнение с сектором')
            btn.setFixedHeight(22)
            btn.setToolTip('4-столбцовые графики P/E и EPS growth '
                           '(сектор/компания × сейчас/форвард) + рекомендация')
            btn.clicked.connect(lambda _=False, row=s: self._open_chart(row))
            table.setCellWidget(r, len(_HEADERS) - 1, btn)
        table.resizeColumnsToContents()

    def _selected(self):
        table = self.tabs.currentWidget()
        row = table.currentRow()
        if 0 <= row < table.rowCount():
            item = table.item(row, 1)
            return item.text() if item else ''
        return ''

    def _open_chart(self, s):
        if not s:
            return
        from recommendation_panel import RecommendationDialog
        dlg = RecommendationDialog(s, self.window())
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        main = self.window()
        if hasattr(main, '_dialogs_set'):
            main._dialogs_set().add(dlg)
            dlg.destroyed.connect(lambda obj=None, d=dlg:
                                  main._dialogs_set().discard(d))
        dlg.show()

    def _add_to_watchlist(self):
        ticker = self._selected()
        if not ticker:
            return
        table = self.tabs.currentWidget()
        row = table.currentRow()
        score_item = table.item(row, 13)
        quant = None
        if score_item and score_item.text() != '-':
            try:
                quant = float(score_item.text())
            except ValueError:
                quant = None
        from watchlist_dialog import WatchlistEntryDialog
        dlg = WatchlistEntryDialog(ticker=ticker, parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        from watchlist import add as watchlist_add
        res = watchlist_add(v['ticker'], v['status'], v['note'], v['reason'])
        if quant is not None:
            import datetime
            from watchlist import set_quant_snapshot
            set_quant_snapshot(
                v['ticker'], quant,
                sector=self._sector,
                date=datetime.date.today().isoformat())
        QtWidgets.QMessageBox.information(
            self, 'Watchlist',
            '{} {} в watchlist{}.'.format(
                v['ticker'],
                'добавлен' if res == 'added' else 'обновлён',
                ' (Quant {:.2f})'.format(quant) if quant is not None else ''))

    @staticmethod
    def _fmt(value, suffix=''):
        if value is None:
            return '-'
        if suffix:
            return '{:+.1f}{}'.format(value, suffix)
        return '{:.2f}'.format(value)

    @staticmethod
    def _pe(value):
        if value is None:
            return '-'
        return '{:.1f}×'.format(value)

    @staticmethod
    def _peg(value):
        if value is None:
            return '-'
        return '{:.2f}'.format(value)

    @staticmethod
    def _ratio(value):
        if value is None:
            return '-'
        return '{:.2f}'.format(value)

    @staticmethod
    def _color_vs(value, median, lower_better):
        """Зелёный, если значение лучше медианы сектора, красный — если хуже."""
        if value is None or median is None:
            return QtGui.QColor(_TXT)
        good = (value <= median) if lower_better else (value >= median)
        return QtGui.QColor('#81c784' if good else '#ef5350')

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

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(5000)
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        super().closeEvent(event)