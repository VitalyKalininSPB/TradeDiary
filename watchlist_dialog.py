# -*- coding: utf-8 -*-
from PySide6 import QtWidgets
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor

import markets
import watchlist

_TXT = '#dcdce0'
_STATUS_COLORS = {
    'Research': '#3a5a8c',
    'Watching': '#9a6b1f',
    'Rejected': '#b71c1c',
    'Owned': '#2e7d32',
}

_HEADERS = ['Ticker', 'Status', 'Date', 'Reason', 'Qual', 'Quant', 'Note']


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
            self.snapLabel.setText(self._snapshot_text(
                entry.get('snapshot'), entry.get('date')))
        elif snapshot is not None:
            self.snapLabel.setText(self._snapshot_text(
                snapshot, snapshot.get('date')))

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
    def _snapshot_text(snapshot, date):
        if not snapshot:
            return 'нет снапшота'
        parts = []
        if snapshot.get('qual') is not None:
            parts.append('Qual: {:.2f}/5'.format(snapshot['qual']))
        if snapshot.get('quant') is not None:
            parts.append('Quant: {:+.2f}'.format(snapshot['quant']))
        if snapshot.get('quant_sector'):
            parts.append('сектор: {}'.format(snapshot['quant_sector']))
        if not parts:
            return 'нет снапшота'
        if date:
            parts.append('дата: {}'.format(date))
        return ' · '.join(parts)

    def values(self):
        return {
            'ticker': self.tickerEdit.text().strip().upper(),
            'status': self.statusCombo.currentText(),
            'reason': self.reasonEdit.text().strip(),
            'note': self.noteEdit.toPlainText().strip(),
        }


class WatchlistDialog(QtWidgets.QDialog):
    """Watchlist: ручные решения по компаниям (Research/Watching/Rejected/
    Owned) с заметкой, датой, причиной и снапшотом score."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Watchlist')
        self.resize(960, 460)

        root = QtWidgets.QVBoxLayout(self)
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
        self.table.itemDoubleClicked.connect(lambda *_: self._edit())
        root.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        self.addButton = QtWidgets.QPushButton('Add')
        self.editButton = QtWidgets.QPushButton('Edit')
        self.removeButton = QtWidgets.QPushButton('Remove')
        self.chartButton = QtWidgets.QPushButton('Chart')
        self.testNotifyButton = QtWidgets.QPushButton('Test notify (15s)')
        self.closeButton = QtWidgets.QPushButton('Close')
        row.addWidget(self.addButton)
        row.addWidget(self.editButton)
        row.addWidget(self.removeButton)
        row.addWidget(self.chartButton)
        row.addWidget(self.testNotifyButton)
        row.addStretch(1)
        row.addWidget(self.closeButton)
        root.addLayout(row)

        self.addButton.clicked.connect(self._add)
        self.editButton.clicked.connect(self._edit)
        self.removeButton.clicked.connect(self._remove)
        self.chartButton.clicked.connect(self._chart)
        self.testNotifyButton.clicked.connect(self._test_notify)
        self.closeButton.clicked.connect(self.close)
        self._test_timer = None
        self._test_timer2 = None

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
        root.addLayout(sim_row)
        self.simSectorButton.clicked.connect(self._simulate_sector)
        self.simCompanyButton.clicked.connect(self._simulate_company)
        self.simSequenceButton.clicked.connect(self._simulate_sequence)

        self._refresh()

    def _refresh(self):
        entries = watchlist.load()
        self._entries = entries
        self.table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            snap = e.get('snapshot') or {}
            vals = [
                e.get('ticker', ''),
                e.get('status', watchlist.DEFAULT_STATUS),
                e.get('date', ''),
                e.get('reason', ''),
                self._fmt(snap.get('qual'), '/5'),
                self._fmt(snap.get('quant')),
                e.get('note', ''),
            ]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(str(v))
                if c == 1:
                    color = _STATUS_COLORS.get(v, _STATUS_COLORS['Research'])
                    item.setBackground(QColor(color))
                    item.setForeground(QColor('#ffffff'))
                elif c == 6:
                    item.setToolTip(v)
                elif c in (4, 5):
                    item.setForeground(QColor(_TXT))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def _selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

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
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        super().closeEvent(event)