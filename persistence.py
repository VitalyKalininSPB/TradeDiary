# -*- coding: utf-8 -*-
"""Персистенция дневника: SQLite `diary.db` + миграция из legacy `diary.xml`.

Данные сделок и баланс хранятся в SQLite (надёжнее и проще ручного XML). При
первом запуске после обновления выполняется однократная миграция из старого
`diary.xml` (файл переименовывается в `diary.xml.migrated`, чтобы не дублировать).
"""
import os
import sqlite3
import xml.dom.minidom

from deals import Deal, Direction, infer_direction

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DIR, 'diary.db')
XML_PATH = os.path.join(_DIR, 'diary.xml')

_DEAL_COLS = (
    "ticker", "stock_price", "amount", "open_date", "init_price",
    "take_profit", "stop_loss", "trade_system", "result", "close_date",
    "whats_next", "notes", "currency", "direction",
)


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS balance (id INTEGER PRIMARY KEY, value REAL NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS deals ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ticker TEXT NOT NULL, stock_price REAL, amount REAL, open_date TEXT,"
        "init_price REAL, take_profit REAL, stop_loss REAL, trade_system INTEGER,"
        "result TEXT, close_date TEXT, whats_next TEXT, notes TEXT,"
        "currency TEXT, direction TEXT)")
    return conn


def _f(el, attr):
    try:
        return float(el.getAttribute(attr) or 0)
    except ValueError:
        return 0.0


def _i(el, attr):
    try:
        return int(el.getAttribute(attr) or 0)
    except ValueError:
        return 0


def _migrate_xml():
    """Разобрать legacy diary.xml -> (deals, balance). (None, 0.0) если файла нет."""
    if not os.path.exists(XML_PATH):
        return None, 0.0
    try:
        dom = xml.dom.minidom.parse(XML_PATH)
    except Exception:
        return None, 0.0
    collection = dom.documentElement

    balance = 0.0
    for b in collection.getElementsByTagName("balance"):
        try:
            balance = float(b.getAttribute("value") or 0)
        except ValueError:
            balance = 0.0

    deals = []
    for d in collection.getElementsByTagName("deal"):
        deal = Deal(
            ticker=d.getAttribute("ticker"),
            stock_price=_f(d, "stockPrice"),
            amount=_f(d, "stocksAmount"),
            open_date=d.getAttribute("openDate"),
            init_price=_f(d, "initPrice"),
            take_profit=_f(d, "takeProfit"),
            stop_loss=_f(d, "stopLoss"),
            trade_system=_i(d, "tradeSystem"),
            result=d.getAttribute("result"),
            close_date=d.getAttribute("closeDate"),
            whats_next=d.getAttribute("whatsNext"),
            notes=d.getAttribute("analysisNotes"),
            currency=d.getAttribute("currency"),
        )
        deal.direction = infer_direction(deal)
        deals.append(deal)
    return deals, balance


def _row_to_deal(row):
    return Deal(
        ticker=row[0], stock_price=row[1] or 0.0, amount=row[2] or 0.0,
        open_date=row[3] or "", init_price=row[4] or 0.0,
        take_profit=row[5] or 0.0, stop_loss=row[6] or 0.0,
        trade_system=row[7] or 0, result=row[8] or "",
        close_date=row[9] or "", whats_next=row[10] or "",
        notes=row[11] or "", currency=row[12] or "",
        direction=Direction(row[13]) if row[13] in (Direction.LONG.value,
                                                    Direction.SHORT.value)
        else Direction.LONG,
    )


def load():
    """Вернуть (deals: list[Deal], balance: float). При необходимости мигрирует XML."""
    conn = _conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
    finally:
        conn.close()

    if n == 0 and os.path.exists(XML_PATH):
        deals, balance = _migrate_xml()
        if deals is not None:
            save(deals, balance)
            try:
                os.rename(XML_PATH, XML_PATH + ".migrated")
            except OSError:
                pass
            return deals, balance

    conn = _conn()
    try:
        row = conn.execute("SELECT value FROM balance WHERE id=1").fetchone()
        balance = row[0] if row else 0.0
        rows = conn.execute(
            "SELECT {} FROM deals ORDER BY id".format(", ".join(_DEAL_COLS))
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_deal(r) for r in rows], balance


def save(deals, balance):
    """Полностью перезаписать сделки и баланс (одной транзакцией)."""
    conn = _conn()
    try:
        conn.execute("DELETE FROM deals")
        conn.execute("DELETE FROM balance")
        conn.execute("INSERT INTO balance (id, value) VALUES (1, ?)", (balance,))
        conn.executemany(
            "INSERT INTO deals ({}) VALUES ({})".format(
                ", ".join(_DEAL_COLS), ", ".join("?" * len(_DEAL_COLS))),
            [(d.ticker, d.stock_price, d.amount, d.open_date, d.init_price,
              d.take_profit, d.stop_loss, d.trade_system, d.result,
              d.close_date, d.whats_next, d.notes, d.currency, d.direction.value)
             for d in deals])
        conn.commit()
    finally:
        conn.close()
