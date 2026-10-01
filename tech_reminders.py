# -*- coding: utf-8 -*-
"""Ручные напоминания «проверить технический статус» тикера (без Qt).

Пользователь задаёт дату в окне Technical timing; приложение напоминает
козой (с подтверждением) в этот день — как для катализаторов.
Хранится в SQLite `tech_reminders.db`.
"""
import datetime
import os
import sqlite3

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DIR, 'tech_reminders.db')


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tech_reminders ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, "
        "due_date TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL, notified INTEGER NOT NULL DEFAULT 0)")
    return conn


def _row(r):
    return {'id': r[0], 'ticker': r[1], 'due_date': r[2], 'note': r[3],
            'created_at': r[4], 'notified': r[5]}


def add(ticker, due_date, note=''):
    """Добавить напоминание. Одно напоминание на тикер (заменяет прежнее).

    Возвращает id или None.
    """
    ticker = (ticker or '').strip().upper()
    if not ticker or not due_date:
        return None
    conn = _conn()
    try:
        conn.execute("DELETE FROM tech_reminders WHERE ticker=?", (ticker,))
        cur = conn.execute(
            "INSERT INTO tech_reminders (ticker, due_date, note, created_at) "
            "VALUES (?,?,?,?)",
            (ticker, due_date, note or '',
             datetime.datetime.now().isoformat()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def for_ticker(ticker):
    """Все напоминания по тикеру, сортировка по дате."""
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return []
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, ticker, due_date, note, created_at, notified "
            "FROM tech_reminders WHERE ticker=? ORDER BY due_date",
            (ticker,)).fetchall()
    finally:
        conn.close()
    return [_row(r) for r in rows]


def next_for(ticker):
    """Ближайшее (по дате) напоминание по тикеру или None."""
    items = for_ticker(ticker)
    return items[0] if items else None


def all_reminders():
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, ticker, due_date, note, created_at, notified "
            "FROM tech_reminders ORDER BY due_date, id").fetchall()
    finally:
        conn.close()
    return [_row(r) for r in rows]


def remove(rid):
    conn = _conn()
    try:
        conn.execute("DELETE FROM tech_reminders WHERE id=?", (rid,))
        conn.commit()
    finally:
        conn.close()


def remove_for_ticker(ticker):
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return
    conn = _conn()
    try:
        conn.execute("DELETE FROM tech_reminders WHERE ticker=?", (ticker,))
        conn.commit()
    finally:
        conn.close()


def due_events():
    """Напоминания, срок которых наступил (или прошёл), ещё не показанные."""
    today = datetime.date.today().isoformat()
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, ticker, due_date, note, created_at, notified "
            "FROM tech_reminders WHERE notified=0 AND due_date <= ? "
            "ORDER BY due_date", (today,)).fetchall()
    finally:
        conn.close()
    return [_row(r) for r in rows]


def mark_notified(ids):
    if not ids:
        return
    conn = _conn()
    try:
        conn.executemany(
            "UPDATE tech_reminders SET notified=1 WHERE id=?",
            [(i,) for i in ids])
        conn.commit()
    finally:
        conn.close()


def reminder_text(r):
    """Одна строка напоминания."""
    note = r.get('note') or ''
    return ('{}: пора проверить технический статус (напоминание на {}).{} '
            'Откройте Watchlist → колонка Tech.').format(
        r.get('ticker', ''), r.get('due_date', ''),
        (' Комментарий: ' + note) if note else '')
