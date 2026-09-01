# -*- coding: utf-8 -*-
import random
import datetime
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtCore import Qt

from deals import Deal, Direction, TRADE_SYSTEMS, trade_system_name


def _fmt_date(d):
    return d.strftime("%d/%m/%Y")


def generate_fake_history(open_deals, per_ticker=3):
    """Derive fictional CLOSED deals from the current open positions.

    Used so the Deal History window has content even before real trades exist.
    TODO(в GUI): убрать, когда появится настоящая история сделок.
    Returns a list of Deal objects.
    """
    random.seed()
    systems = list(range(len(TRADE_SYSTEMS)))
    results = [('Win', 1), ('Loss', -1), ('Win', 1), ('Loss', -1), ('BE', 0)]
    lookback_days = [15, 25, 40, 60, 90]
    out = []

    for deal in open_deals:
        ticker = deal.ticker
        currency = deal.currency
        base_price = deal.init_price or deal.stock_price
        if base_price <= 0 or not ticker:
            continue

        for _ in range(per_ticker):
            hold_days = random.choice(lookback_days)
            open_dt = datetime.date.today() - datetime.timedelta(days=hold_days + random.randint(0, 15))
            close_dt = open_dt + datetime.timedelta(days=hold_days)
            drift = random.uniform(-0.06, 0.06)
            close_price = round(base_price * (1 + drift), 2)
            stop = round(base_price * 0.97, 2)
            target = round(base_price * 1.06, 2)
            amount = random.choice([50, 100, 150, 200])
            res, sign = random.choice(results)
            if res == 'BE':
                close_price = round(base_price, 2)
            else:
                close_price = round(base_price * (1 + sign * random.uniform(0.01, 0.05)), 2)

            out.append(Deal(
                ticker=ticker,
                stock_price=close_price,
                amount=float(amount),
                open_date=_fmt_date(open_dt),
                init_price=base_price,
                take_profit=target,
                stop_loss=stop,
                trade_system=random.choice(systems),
                result=res,
                close_date=_fmt_date(close_dt),
                currency=currency,
                direction=deal.direction,
            ))
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

    def __init__(self, deals, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Deal History')
        self.resize(1150, 500)

        layout = QVBoxLayout(self)

        headers = [c[0] for c in self.COLUMNS]
        widths = [c[1] for c in self.COLUMNS]

        table = QTableWidget(len(deals), len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)

        for r, deal in enumerate(deals):
            status = 'CLOSED' if deal.close_date else 'OPEN'
            direction = 'S' if deal.direction == Direction.SHORT else 'L'
            values = [
                deal.ticker,
                direction,
                str(deal.stock_price),
                str(deal.amount),
                deal.currency,
                deal.open_date,
                deal.close_date or '-',
                str(deal.take_profit),
                str(deal.stop_loss),
                deal.result,
                trade_system_name(deal.trade_system),
                deal.notes,
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if status == 'CLOSED':
                    item.setForeground(Qt.GlobalColor.gray)
                table.setItem(r, c, item)

        for i, w in enumerate(widths):
            table.setColumnWidth(i, w)
        layout.addWidget(table)
