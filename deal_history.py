# -*- coding: utf-8 -*-
import random
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtCore import Qt

import DealDialog


def _fmt_date(d):
    return d.strftime("%d/%m/%Y")


def generate_fake_history(open_rows, per_ticker=3):
    """Derive fictional CLOSED deals from the current open positions.

    Used so the Deal History window has content even before real trades exist.
    TODO(в GUI): убрать, когда появится настоящая история сделок.
    Returns a list of rows matching the main data schema (13 fields).
    """
    random.seed()
    systems = list(range(len(DealDialog.TRADE_SYSTEMS)))
    results = [('Win', 1), ('Loss', -1), ('Win', 1), ('Loss', -1), ('BE', 0)]
    lookback_days = [15, 25, 40, 60, 90]
    out = []

    for row in open_rows:
        ticker = str(row[0] or '')
        currency = str(row[12] or '')
        try:
            base_price = float(row[4] or 0) or float(row[1] or 0)
        except (ValueError, TypeError):
            base_price = 0.0
        if base_price <= 0 or not ticker:
            continue

        for _ in range(per_ticker):
            hold_days = random.choice(lookback_days)
            # Уходим в прошлое от "сегодня" (признак дат не критичен — это фейк).
            open_dt = __import__('datetime').date.today() - __import__('datetime').timedelta(days=hold_days + random.randint(0, 15))
            close_dt = open_dt + __import__('datetime').timedelta(days=hold_days)
            drift = random.uniform(-0.06, 0.06)     # итоговая доходность сделки
            close_price = round(base_price * (1 + drift), 2)
            stop = round(base_price * 0.97, 2)
            target = round(base_price * 1.06, 2)
            amount = random.choice([50, 100, 150, 200])
            res, sign = random.choice(results)
            if res == 'BE':
                close_price = round(base_price, 2)
            else:
                close_price = round(base_price * (1 + sign * random.uniform(0.01, 0.05)), 2)

            fake = [ticker,                          # 0 ticker
                    str(close_price),                # 1 price
                    str(amount),                     # 2 amount
                    _fmt_date(open_dt),              # 3 openDate
                    str(base_price),                 # 4 initPrice
                    str(target),                     # 5 TP
                    str(stop),                       # 6 SL
                    random.choice(systems),          # 7 system
                    res,                             # 8 result
                    _fmt_date(close_dt),             # 9 closeDate
                    '',                              # 10 whatsNext
                    '',                              # 11 notes
                    currency,                        # 12 currency
                    ]
            out.append(fake)
    return out


class DealHistoryDialog(QDialog):
    """Compact read-only table of every deal (open and closed)."""

    COLUMNS = [
        ('Ticker', 90),
        ('Dir', 40),
        ('Price', 70),
        ('Amount', 70),
        ('Cur.', 45),
        ('Open', 130),
        ('Close', 130),
        ('TP', 70),
        ('SL', 70),
        ('Result', 90),
        ('System', 70),
        ('Notes', 200),
    ]

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Deal History')
        self.resize(1150, 500)

        layout = QVBoxLayout(self)

        headers = [c[0] for c in self.COLUMNS]
        widths = [c[1] for c in self.COLUMNS]

        table = QTableWidget(len(rows), len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)

        for r, row in enumerate(rows):
            status, direction = self._rowMeta(row)
            values = [
                str(row[0] or ''),                                      # Ticker
                direction,                                              # Dir
                str(row[1] or ''),                                      # Price
                str(row[2] or ''),                                      # Amount
                str(row[12] or ''),                                     # Currency
                str(row[3] or ''),                                      # Open
                str(row[9] or '-'),                                     # Close
                str(row[5] or ''),                                      # TP
                str(row[6] or ''),                                      # SL
                str(row[8] or ''),                                      # Result
                DealDialog.trade_system_name(row[7]),                   # System
                str(row[11] or ''),                                     # Notes
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if status == 'CLOSED':
                    item.setForeground(Qt.GlobalColor.gray)
                table.setItem(r, c, item)

        for i, w in enumerate(widths):
            table.setColumnWidth(i, w)
        layout.addWidget(table)

    def _rowMeta(self, row):
        """Return (status, direction) for a deal row. Direction is inferred.

        TODO(в GUI): добавлять явное поле direction в модель; пока копия логики
        из main.recalcSlTpClicked (_dealDirection).
        """
        def _num(idx):
            try:
                return float(row[idx] or 0)
            except (ValueError, TypeError, IndexError):
                return 0.0

        try:
            price = float(row[1] or 0)
        except (ValueError, TypeError):
            price = 0.0

        status = 'OPEN' if not (row[9] if len(row) > 9 else '') else 'CLOSED'
        sl = _num(6)
        if sl:
            direction = 'S' if sl > price else 'L'
        else:
            tp = _num(5)
            direction = 'S' if tp and tp < price else 'L'
        return status, direction
