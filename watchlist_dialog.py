# -*- coding: utf-8 -*-
import datetime

from PySide6 import QtWidgets
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QColor

import catalyst
import markets
import technical_timing
import watchlist

_TXT = '#dcdce0'
_RED = '#ef5350'
_LINK = '#7aa2f7'
_MUTED = '#9aa0aa'
_STATUS_COLORS = {
    'Research': '#3a5a8c',
    'Watching': '#9a6b1f',
    'Rejected': '#b71c1c',
    'Owned': '#2e7d32',
}

_HEADERS = ['Ticker', 'Status', 'Date', 'Reason', 'Quant', 'Quant ✓',
            'Qual', 'Qual ✓', 'Catalyst', 'Tech', 'Note']
_EV_HEADERS = ['Ticker', 'Дата', 'Балл', 'Напр', 'Описание', 'Ожидание']


class WatchlistEntryDialog(QtWidgets.QDialog):
    """Ручной workflow: статус, причина решения, заметка, дата + снапшот."""

    def __init__(self, ticker='', snapshot=None, entry=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Watchlist entry')
        self.setMinimumWidth(460)

        form = QtWidgets.QFormLayout(self)
        self.tickerEdit = QtWidgets.QLineEdit(ticker or '')
        self.tickerEdit.setReadOnly(bool(ticker))
        self.statusCombo = QtWidgets.QComboBox()
        self.statusCombo.addItems(watchlist.STATUSES)
        self.reasonEdit = QtWidgets.QLineEdit()
        self.reasonEdit.setPlaceholderText('Причина решения…')
        self.noteEdit = QtWidgets.QTextEdit()
        self.noteEdit.setFixedHeight(72)
        self.noteEdit.setPlaceholderText('Личная заметка…')
        self.snapLabel = QtWidgets.QLabel()
        self.snapLabel.setWordWrap(True)
        self.snapLabel.setStyleSheet('color: {};'.format(_TXT))

        form.addRow('Ticker:', self.tickerEdit)
        form.addRow('Status:', self.statusCombo)
        form.addRow('Reason:', self.reasonEdit)
        form.addRow('Note:', self.noteEdit)
        form.addRow('Snapshot:', self.snapLabel)

        if entry is not None:
            self.tickerEdit.setText(entry.get('ticker') or '')
            if entry.get('status') in watchlist.STATUSES:
                self.statusCombo.setCurrentText(entry['status'])
            self.reasonEdit.setText(entry.get('reason') or '')
            self.noteEdit.setPlainText(entry.get('note') or '')
            self.snapLabel.setText(self._snapshot_text(entry))
        elif snapshot is not None:
            self.snapLabel.setText(self._snapshot_text(
                {'ticker': ticker or '', 'snapshot': snapshot,
                 'quant': None, 'qual': None}))

        row = QtWidgets.QHBoxLayout()
        ok = QtWidgets.QPushButton('OK')
        cancel = QtWidgets.QPushButton('Cancel')
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        form.addRow(row)

    @staticmethod
    def _snapshot_text(entry):
        snap = (entry or {}).get('snapshot') or {}
        qn = watchlist.get_quant(entry)
        ql = watchlist.get_qual(entry)
        parts = []
        if ql is not None and ql.get('score') is not None:
            parts.append('Qual: {:.2f}/5'.format(ql['score']))
        if qn is not None and qn.get('score') is not None:
            parts.append('Quant: {:+.2f}'.format(qn['score']))
        if qn and qn.get('sector'):
            parts.append('сектор: {}'.format(qn['sector']))
        cat = snap.get('catalyst')
        if isinstance(cat, dict) and cat.get('count'):
            parts.append('Catalyst: {} событий · ближайшее {} · макс {}/5'
                         .format(cat['count'], cat.get('next', '-'),
                                 cat.get('max', '-')))
        elif isinstance(cat, (int, float)):
            parts.append('Catalyst: {:.2f}/5'.format(cat))
        q = (ql or {}).get('report')
        if q:
            snippet = q.replace('\n', ' ').strip()
            parts.append('Quality: {}…'.format(snippet[:60]))
        if not parts:
            return 'нет снапшота'
        if entry and entry.get('date'):
            parts.append('дата: {}'.format(entry['date']))
        return ' · '.join(parts)

    def values(self):
        return {
            'ticker': self.tickerEdit.text().strip().upper(),
            'status': self.statusCombo.currentText(),
            'reason': self.reasonEdit.text().strip(),
            'note': self.noteEdit.toPlainText().strip(),
        }


class _TechnicalTimingThread(QThread):
    """Фоновый пересчёт Technical timing по тикерам Watchlist.

    Сеть (обновление цен) и запись в БД — только здесь, вне UI-потока.
    Свежие результаты из кэша пропускаются (compute_fresh вернёт None);
    эмитится только пересчитанное.
    """

    timing_ready = Signal(str, object)  # ticker, result

    def __init__(self, tickers, parent=None):
        super().__init__(parent)
        self._tickers = [t for t in (tickers or []) if t]
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        for t in self._tickers:
            if self._cancel:
                break
            try:
                result = technical_timing.compute_fresh(t)
            except Exception:  # pragma: no cover - best-effort
                result = None
            if result is not None:
                self.timing_ready.emit(t, result)


class WatchlistDialog(QtWidgets.QDialog):
    """Watchlist: ручные решения по компаниям (Research/Watching/Rejected/
    Owned) с заметкой, датой, причиной и снапшотом score."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Watchlist')
        self.resize(960, 460)

        root = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()

        # ------------------------------------------------ таб Watchlist
        wtab = QtWidgets.QWidget()
        wlay = QtWidgets.QVBoxLayout(wtab)
        wlay.setContentsMargins(0, 0, 0, 0)
        self.table = QtWidgets.QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.cellDoubleClicked.connect(self._on_table_double)
        wlay.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        self.addButton = QtWidgets.QPushButton('Add')
        self.editButton = QtWidgets.QPushButton('Edit')
        self.removeButton = QtWidgets.QPushButton('Remove')
        self.chartButton = QtWidgets.QPushButton('Chart')
        self.catalystButton = QtWidgets.QPushButton('Catalyst')
        self.technicalButton = QtWidgets.QPushButton('Technical')
        self.testNotifyButton = QtWidgets.QPushButton('Test notify (15s)')
        self.closeButton = QtWidgets.QPushButton('Close')
        row.addWidget(self.addButton)
        row.addWidget(self.editButton)
        row.addWidget(self.removeButton)
        row.addWidget(self.chartButton)
        row.addWidget(self.catalystButton)
        row.addWidget(self.technicalButton)
        row.addWidget(self.testNotifyButton)
        row.addStretch(1)
        row.addWidget(self.closeButton)
        wlay.addLayout(row)

        self.addButton.clicked.connect(self._add)
        self.editButton.clicked.connect(self._edit)
        self.removeButton.clicked.connect(self._remove)
        self.chartButton.clicked.connect(self._chart)
        self.catalystButton.clicked.connect(self._catalyst)
        self.technicalButton.clicked.connect(self._technical)
        self.testNotifyButton.clicked.connect(self._test_notify)
        self.closeButton.clicked.connect(self.close)
        self._test_timer = None
        self._test_timer2 = None
        self._timing_loader = None

        sim_row = QtWidgets.QHBoxLayout()
        simLabel = QtWidgets.QLabel('Симуляция (тест):')
        simLabel.setStyleSheet('color: {};'.format(_TXT))
        self.simSectorButton = QtWidgets.QPushButton('Sim sector change')
        self.simCompanyButton = QtWidgets.QPushButton('Sim company change')
        self.simSequenceButton = QtWidgets.QPushButton('Sim both (15s, +15s)')
        sim_row.addWidget(simLabel)
        sim_row.addWidget(self.simSectorButton)
        sim_row.addWidget(self.simCompanyButton)
        sim_row.addWidget(self.simSequenceButton)
        sim_row.addStretch(1)
        wlay.addLayout(sim_row)
        self.simSectorButton.clicked.connect(self._simulate_sector)
        self.simCompanyButton.clicked.connect(self._simulate_company)
        self.simSequenceButton.clicked.connect(self._simulate_sequence)

        # -------------------------------------------------- таб Events
        etab = QtWidgets.QWidget()
        elay = QtWidgets.QVBoxLayout(etab)
        elay.setContentsMargins(0, 0, 0, 0)
        self.eventsTable = QtWidgets.QTableWidget(0, len(_EV_HEADERS))
        self.eventsTable.setHorizontalHeaderLabels(_EV_HEADERS)
        self.eventsTable.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        self.eventsTable.verticalHeader().setVisible(False)
        self.eventsTable.horizontalHeader().setStretchLastSection(True)
        self.eventsTable.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.eventsTable.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.eventsTable.itemDoubleClicked.connect(lambda *_: self._edit_event())
        elay.addWidget(self.eventsTable, 1)

        erow = QtWidgets.QHBoxLayout()
        self.evAddButton = QtWidgets.QPushButton('Add')
        self.evEditButton = QtWidgets.QPushButton('Edit')
        self.evDeleteButton = QtWidgets.QPushButton('Delete')
        self.evRefreshButton = QtWidgets.QPushButton('Refresh')
        erow.addWidget(self.evAddButton)
        erow.addWidget(self.evEditButton)
        erow.addWidget(self.evDeleteButton)
        erow.addWidget(self.evRefreshButton)
        erow.addStretch(1)
        elay.addLayout(erow)
        self.evAddButton.clicked.connect(self._add_event)
        self.evEditButton.clicked.connect(self._edit_event)
        self.evDeleteButton.clicked.connect(self._delete_event)
        self.evRefreshButton.clicked.connect(self._refresh_events)

        self.tabs.addTab(wtab, 'Watchlist')
        self.tabs.addTab(etab, 'Events')
        root.addWidget(self.tabs, 1)

        self._events = []
        self._refresh()

    def _refresh(self):
        entries = watchlist.load()
        self._entries = entries
        self.table.setRowCount(len(entries))
        today = datetime.date.today().isoformat()
        for r, e in enumerate(entries):
            qn = watchlist.get_quant(e)
            ql = watchlist.get_qual(e)
            quant_ok = qn is not None
            qual_ok = ql is not None
            summary = catalyst.summary_for(e.get('ticker', ''))
            cat_txt = ''
            if summary:
                cat_txt = '{} · {} · {}/5'.format(
                    summary['count'], summary['next'], summary['max'])
            tech = technical_timing.load_timing(e.get('ticker', '')) \
                or technical_timing.load_any_timing(e.get('ticker', ''))
            if tech and tech.get('status') != 'no_data':
                tech_txt = tech['status_txt']
                tech_color = tech['status_color']
            else:
                tech_txt = 'Нет данных' if tech else '…'
                tech_color = _MUTED
            vals = [
                e.get('ticker', ''),
                e.get('status', watchlist.DEFAULT_STATUS),
                e.get('date', ''),
                e.get('reason', ''),
                self._fmt((qn or {}).get('score')),
                '💡' if quant_ok else '—',
                self._fmt((ql or {}).get('score'), '/5'),
                '💡' if qual_ok else '—',
                cat_txt,
                tech_txt,
                e.get('note', ''),
            ]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(str(v))
                if c == 1:
                    color = _STATUS_COLORS.get(v, _STATUS_COLORS['Research'])
                    item.setBackground(QColor(color))
                    item.setForeground(QColor('#ffffff'))
                elif c in (5, 7):
                    if v == '💡':
                        item.setForeground(QColor('#f0c14b'))
                        item.setToolTip(
                            'Quant Assessment пройден' if c == 5
                            else 'Qual Assessment пройден\nДвойной клик — '
                                 'просмотр Qual-отчёта')
                    else:
                        item.setForeground(QColor(_TXT))
                        item.setToolTip(
                            'Quant Assessment не пройден' if c == 5
                            else 'Qual Assessment не пройден\nДвойной клик — '
                                 'просмотр Qual-отчёта')
                elif c == 10:
                    item.setToolTip(v)
                elif c in (4, 6):
                    item.setForeground(QColor(_TXT))
                    if c == 6:
                        item.setToolTip(
                            'Двойной клик — просмотр Qual-отчёта')
                elif c == 8:
                    due = summary and summary['next'] <= today
                    item.setForeground(QColor(_RED if due else _LINK))
                    f = item.font()
                    f.setUnderline(True)
                    item.setFont(f)
                    if summary:
                        item.setToolTip(
                            'Двойной клик — редактировать катализаторы.\n'
                            '{} событий · ближайшее {} · макс {}/5'.format(
                                summary['count'], summary['next'],
                                summary['max']))
                    else:
                        item.setToolTip(
                            'Двойной клик — добавить катализаторы.')
                elif c == 9:
                    item.setForeground(QColor(tech_color))
                    item.setToolTip(
                        'Двойной клик — Technical timing.\n' +
                        (tech.get('reason') if tech else
                         'Технический статус загружается…'))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self._refresh_events()
        self._start_timing(
            [e.get('ticker', '') for e in entries if e.get('ticker')])

    def _start_timing(self, tickers):
        """Фоновый пересчёт Technical timing (мгновенный рендер уже из кэша).

        Не блокируем UI: если предыдущий пересчёт ещё идёт — дожидаемся его
        результатов (compute_fresh не зависит от состава списка на старте).
        """
        if self._timing_loader is not None and self._timing_loader.isRunning():
            return
        if not tickers:
            return
        loader = _TechnicalTimingThread(tickers)
        self._timing_loader = loader
        loader.timing_ready.connect(self._on_timing_ready)
        loader.start()

    def _on_timing_ready(self, ticker, result):
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and (item.text() or '').strip().upper() == ticker:
                status = result.get('status') or 'no_data'
                txt = result.get('status_txt') or status
                color = result.get('status_color') or _MUTED
                cell = self.table.item(r, 9)
                if cell is None:
                    cell = QtWidgets.QTableWidgetItem(txt)
                    self.table.setItem(r, 9, cell)
                else:
                    cell.setText(txt)
                cell.setForeground(QColor(color))
                cell.setToolTip(
                    'Двойной клик — Technical timing.\n' +
                    (result.get('reason') or ''))
                break

    def _refresh_events(self):
        self._events = catalyst.all_events()
        self.eventsTable.setRowCount(len(self._events))
        today = datetime.date.today().isoformat()
        for r, e in enumerate(self._events):
            vals = [e['ticker'], e['date'], str(e['score']), e['direction'],
                    e['description'], e['expectation']]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(v)
                if c == 1 and e['date'] <= today:
                    item.setForeground(QColor(_RED))
                self.eventsTable.setItem(r, c, item)
        self.eventsTable.resizeColumnsToContents()

    def _ticker_options(self):
        return [e.get('ticker', '') for e in self._entries if e.get('ticker')]

    def _add_event(self):
        from catalyst_dialog import CatalystEventDialog
        dlg = CatalystEventDialog(parent=self, options=self._ticker_options())
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        if not v['ticker']:
            return
        catalyst.add_event(**v)
        self._refresh()

    def _edit_event(self):
        row = self.eventsTable.currentRow()
        if not (0 <= row < len(self._events)):
            return
        e = self._events[row]
        from catalyst_dialog import CatalystEventDialog
        dlg = CatalystEventDialog(parent=self, ticker=e['ticker'],
                                  options=self._ticker_options(), event=e)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        catalyst.update_event(e['id'], date=v['date'], score=v['score'],
                              direction=v['direction'],
                              description=v['description'],
                              expectation=v['expectation'])
        self._refresh()

    def _delete_event(self):
        row = self.eventsTable.currentRow()
        if not (0 <= row < len(self._events)):
            return
        e = self._events[row]
        ret = QtWidgets.QMessageBox.question(
            self, 'Delete event',
            'Удалить событие «{}» ({}) у {}?'.format(
                e.get('description') or 'без описания', e['date'],
                e['ticker']),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if ret != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        catalyst.delete_event(e['id'])
        self._refresh()

    def _catalyst(self):
        entry = self._selected()
        if entry is None:
            return
        ticker = entry.get('ticker', '')
        if not ticker:
            return
        from catalyst_dialog import CatalystDialog
        main = self.window()
        dlg = CatalystDialog(main, ticker=ticker)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if hasattr(main, '_dialogs_set'):
            main._dialogs_set().add(dlg)
            dlg.destroyed.connect(lambda obj=None, d=dlg:
                                  main._dialogs_set().discard(d))
        dlg.show()
        dlg.finished.connect(lambda *_: self._refresh())

    def _technical(self):
        """Блок «Technical timing — Daily» для выбранного тикера."""
        entry = self._selected()
        if entry is None:
            return
        ticker = entry.get('ticker', '')
        if not ticker:
            return
        from technical_timing_dialog import TechnicalTimingDialog
        result = technical_timing.load_timing(ticker) \
            or technical_timing.load_any_timing(ticker)
        dlg = TechnicalTimingDialog(ticker, result, self)
        dlg.open_trade_plan.connect(lambda t=dlg: self._open_trade_plan(ticker))
        dlg.view_chart.connect(lambda t=dlg: self._view_chart(ticker))
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        main = self.window()
        if hasattr(main, '_dialogs_set'):
            main._dialogs_set().add(dlg)
            dlg.destroyed.connect(lambda obj=None, d=dlg:
                                  main._dialogs_set().discard(d))
        dlg.show()

    def _view_chart(self, ticker):
        from ma_chart_dialog import MAChartDialog
        try:
            _, currency = markets.market_currency(ticker)
        except Exception:  # noqa: BLE001
            currency = None
        dlg = MAChartDialog(ticker, currency or markets.USD, '', '',
                            self.window())
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        main = self.window()
        if hasattr(main, '_dialogs_set'):
            main._dialogs_set().add(dlg)
            dlg.destroyed.connect(lambda obj=None, d=dlg:
                                  main._dialogs_set().discard(d))
        dlg.show()

    def _open_trade_plan(self, ticker):
        """Открыть DealDialog с контекстом Technical timing (Long по умолчанию)."""
        from DealDialog import DealDialog, DirectionType
        main = self.window()
        dlg = DealDialog()
        if hasattr(main, 'balanceUsd'):
            dlg.setData(main.balanceUsd())
        if hasattr(main, 'totalEquityUsd'):
            dlg.setEquityUsd(main.totalEquityUsd())
        dlg.setMode(DirectionType.BUY)
        dlg.ticketEdit.setText(ticker or '')
        dlg.tickerChanged()
        dlg.loadTechnicalContext(ticker or '', hint=True)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        if not (hasattr(main, 'data') and hasattr(main, 'debitLong')):
            return
        deal = dlg.makeDeal()
        main.debitLong(deal)
        main.data.append(deal)
        main.tradeTableView.model().layoutChanged.emit()
        main.recalcBalance()
        main.onTickerAdded(deal.ticker, deal.currency)

    def _selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def _on_table_double(self, row, col):
        if col == 8:
            self._catalyst()
        elif col == 9:
            self._technical()
        elif col in (6, 7):
            self._view_quality()
        else:
            self._edit()

    def _view_quality(self):
        """Показать полный Qual-отчёт: таблица этапов, итоги, Quality Assessment."""
        import re
        entry = self._selected()
        if entry is None:
            return
        ql = watchlist.get_qual(entry) or {}
        text = ql.get('report')
        if not text:
            QtWidgets.QMessageBox.information(
                self, 'Qual Assessment',
                'Нет сохранённого Qual-отчёта для {}.'.format(
                    entry.get('ticker', '')))
            return

        stages = []
        avg = ''
        total = ''
        thesis = []
        in_thesis = False
        for ln in text.split('\n'):
            if in_thesis:
                thesis.append(ln)
                continue
            m = re.match(r'^(.*?):\s*(\d+)/5(?:\s*—\s*(.*))?$', ln)
            if m and m.group(1) not in ('Ticker', 'Average', 'Total'):
                stages.append((m.group(1), m.group(2),
                               (m.group(3) or '').strip()))
                continue
            if ln.startswith('Quality Assessment:'):
                in_thesis = True
                continue
            if ln.startswith('Average:'):
                avg = ln[len('Average:'):].strip()
            elif ln.startswith('Total:'):
                total = ln[len('Total:'):].strip()

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle('Qual Assessment — {}'.format(
            entry.get('ticker', '')))
        dlg.resize(760, 540)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        table = QtWidgets.QTableWidget(max(1, len(stages)), 3)
        table.setHorizontalHeaderLabels(['Этап', 'Оценка', 'Заметка'])
        table.setEditTriggers(
            QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        for r, (name, rating, note) in enumerate(stages):
            for c, val in enumerate((name, rating + '/5', note)):
                item = QtWidgets.QTableWidgetItem(val)
                item.setForeground(QColor(_TXT))
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        table.setFixedHeight(36 + 28 * max(1, len(stages)))
        lay.addWidget(table)

        summary = ' '.join(x for x in (avg, total) if x)
        if summary:
            lbl = QtWidgets.QLabel(summary)
            lbl.setStyleSheet('color: {};'.format(_TXT))
            lay.addWidget(lbl)

        quality_html = ql.get('report_html')
        html_has_text = bool(re.sub(r'<[^>]+>', '', quality_html or '').strip())
        if thesis or html_has_text:
            head = QtWidgets.QLabel('Quality Assessment:')
            head.setStyleSheet('color: {}; font-weight: bold;'.format(_TXT))
            lay.addWidget(head)
            if html_has_text:
                tb = QtWidgets.QTextBrowser()
                tb.setHtml(quality_html)
                tb.setStyleSheet(
                    'QTextBrowser { background-color: #1e1f24; '
                    'color: #dcdce0; border: 1px solid #43464f; }')
                lay.addWidget(tb, 1)
            else:
                te = QtWidgets.QPlainTextEdit()
                te.setReadOnly(True)
                te.setPlainText('\n'.join(thesis).strip())
                te.setStyleSheet(
                    'QPlainTextEdit { background-color: #1e1f24; '
                    'color: #dcdce0; }')
                lay.addWidget(te, 1)
        else:
            lay.addStretch(1)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        ok = QtWidgets.QPushButton('Close')
        ok.clicked.connect(dlg.accept)
        row.addWidget(ok)
        lay.addLayout(row)
        dlg.exec()

    def _add(self):
        dlg = WatchlistEntryDialog(snapshot={}, parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        if not v['ticker']:
            return
        res = watchlist.add(v['ticker'], v['status'], v['note'], v['reason'],
                            snapshot={'date': None})
        self._refresh()
        QtWidgets.QMessageBox.information(
            self, 'Watchlist',
            '{} {} в watchlist.'.format(v['ticker'],
                                        'добавлен' if res == 'added'
                                        else 'обновлён'))

    def _edit(self):
        entry = self._selected()
        if entry is None:
            return
        dlg = WatchlistEntryDialog(ticker=entry.get('ticker'),
                                   snapshot=None, entry=entry, parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        watchlist.update(v['ticker'], v['status'], v['note'], v['reason'])
        self._refresh()

    def _remove(self):
        entry = self._selected()
        if entry is None:
            return
        ticker = entry.get('ticker', '')
        ret = QtWidgets.QMessageBox.question(
            self, 'Remove from Watchlist',
            'Remove {} from watchlist?'.format(ticker),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if ret != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        watchlist.remove(ticker)
        self._refresh()

    def _chart(self):
        entry = self._selected()
        if entry is None:
            return
        ticker = entry.get('ticker', '')
        if not ticker:
            return
        from ma_chart_dialog import MAChartDialog
        try:
            _, currency = markets.market_currency(ticker)
        except Exception:  # noqa: BLE001
            currency = None
        dlg = MAChartDialog(ticker, currency or markets.USD, '', '',
                            self.window())
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        main = self.window()
        if hasattr(main, '_dialogs_set'):
            main._dialogs_set().add(dlg)
            dlg.destroyed.connect(lambda obj=None, d=dlg:
                                  main._dialogs_set().discard(d))
        dlg.show()

    def _test_notify(self):
        """Тест: уведомление по Watchlist через 15 секунд (коза)."""
        entries = watchlist.load()
        if not entries:
            self._show_goat('Watchlist пуст — добавьте компанию.')
            return
        lines = ['Watchlist: {} компаний'.format(len(entries))]
        for e in entries[:6]:
            lines.append('• {} ({}) — {}'.format(
                e.get('ticker', ''), e.get('status', ''),
                e.get('date', '')))
        if len(entries) > 6:
            lines.append('…и ещё {}'.format(len(entries) - 6))
        msg = '\n'.join(lines) + '\n\nПроверьте статусы и заметки.'
        self._show_goat('Тест: уведомление придёт через 15 секунд.')
        if self._test_timer is not None:
            self._test_timer.stop()
        self._test_timer = QTimer(self)
        self._test_timer.setSingleShot(True)
        self._test_timer.timeout.connect(lambda: self._show_goat(msg))
        self._test_timer.start(15000)

    def _simulate_sequence(self):
        """Тест: sector signal через 15 с, затем company score ещё через 15 с."""
        self._show_goat(
            'Тест: секторный сигнал через 15 с, затем company score '
            'ещё через 15 с.')
        if self._test_timer is not None:
            self._test_timer.stop()
        if self._test_timer2 is not None:
            self._test_timer2.stop()

        def first():
            self._simulate_sector()
            self._test_timer2 = QTimer(self)
            self._test_timer2.setSingleShot(True)
            self._test_timer2.timeout.connect(self._simulate_company)
            self._test_timer2.start(15000)

        self._test_timer = QTimer(self)
        self._test_timer.setSingleShot(True)
        self._test_timer.timeout.connect(first)
        self._test_timer.start(15000)

    def _simulate_sector(self):
        """Симуляция смены секторного сигнала (одноразово, без следов)."""
        from sector_quant import load_result
        from quant_alerts import record_sector_signal_change, delete_events
        payload = load_result()
        sectors = (payload or {}).get('sectors') or []
        if not sectors:
            self._show_goat('Нет данных секторов — откройте Quant Assessment.')
            return
        flip = {
            'priority_long_research': 'watchlist',
            'watchlist': 'investigate_catalyst',
            'investigate_catalyst': 'exclude_from_long',
            'exclude_from_long': 'priority_long_research',
        }
        import copy
        prev = copy.deepcopy(sectors)
        st = prev[0].get('status') or {}
        prev[0]['status'] = dict(st)
        prev[0]['status']['action_id'] = flip.get(st.get('action_id'), 'watchlist')
        events = record_sector_signal_change(prev, sectors)
        if events:
            delete_events([e['id'] for e in events])
        self._show_goat(
            'Симуляция смены секторного сигнала:\n'
            + (events[0]['message'] if events else 'изменений нет'))

    def _simulate_company(self):
        """Симуляция движения company score (одноразово, без следов)."""
        from company_data import sector_companies_cached
        from quant_alerts import (check_company_scores, delete_events,
                                  baseline_snapshot, restore_baseline)
        comps = sector_companies_cached('Technology')
        if not comps:
            self._show_goat('Нет данных компаний.')
            return
        snap = baseline_snapshot()
        check_company_scores(comps)  # baseline текущими значениями
        import copy
        c = dict(copy.deepcopy(comps[0]))
        c['netMarginPct'] = (c.get('netMarginPct') or 10.0) + 25.0
        c['return1yPct'] = (c.get('return1yPct') or 0.0) + 60.0
        events = check_company_scores([c] + comps[1:])
        restore_baseline(snap)
        if events:
            delete_events([e['id'] for e in events])
        self._show_goat(
            'Симуляция изменения company score:\n'
            + (events[0]['message'] if events else 'изменений нет'))

    def _show_goat(self, advice):
        from qualitative_dialog import GoatAssistant
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        if not advice:
            return
        self._goat = GoatAssistant('', self, advice=advice, auto_hide_ms=12000)
        self._goat.show()

    @staticmethod
    def _fmt(value, suffix=''):
        if value is None:
            return '-'
        if suffix:
            return '{:.2f}{}'.format(value, suffix)
        return '{:+.2f}'.format(value)

    def closeEvent(self, event):
        if self._test_timer is not None:
            self._test_timer.stop()
        if self._test_timer2 is not None:
            self._test_timer2.stop()
        if self._timing_loader is not None:
            if self._timing_loader.isRunning():
                self._timing_loader.cancel()
                self._timing_loader.wait(5000)
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        super().closeEvent(event)