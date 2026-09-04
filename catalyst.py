# -*- coding: utf-8 -*-
"""Катализаторы по тикерам: события с датами, оценкой, направлением и
ожиданием (без Qt).

Хранится в SQLite `catalyst.db`:
  catalyst_events — событие-катализатор (ticker, date, score, direction,
                    description, expectation, created_at, notified).

Напоминание «за сутки до предполагаемой даты»: due_events()/mark_notified().
"""
import datetime
import os
import sqlite3

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DIR, 'catalyst.db')

NOTIFY_LEAD_DAYS = 1

_DIRECTIONS = ['+', '−', '±']


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS catalyst_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, "
        "date TEXT NOT NULL, score INTEGER NOT NULL DEFAULT 0, "
        "direction TEXT NOT NULL DEFAULT '+', "
        "description TEXT NOT NULL DEFAULT '', "
        "expectation TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, "
        "notified INTEGER NOT NULL DEFAULT 0)")
    return conn


def _row_to_event(r):
    return {'id': r[0], 'ticker': r[1], 'date': r[2], 'score': r[3],
            'direction': r[4], 'description': r[5], 'expectation': r[6],
            'created_at': r[7], 'notified': r[8]}


def add_event(ticker, date, score=0, direction='+', description='',
              expectation=''):
    """Добавить событие. Возвращает id или None."""
    ticker = (ticker or '').strip().upper()
    if not ticker or not date:
        return None
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO catalyst_events "
            "(ticker, date, score, direction, description, expectation, "
            "created_at) VALUES (?,?,?,?,?,?,?)",
            (ticker, date, int(score or 0), direction or '+',
             description or '', expectation or '',
             datetime.datetime.now().isoformat()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_event(eid, date=None, score=None, direction=None,
                 description=None, expectation=None):
    """Обновить поля события (None = не трогать)."""
    conn = _conn()
    try:
        sets, vals = [], []
        for col, val in (('date', date), ('score', score),
                         ('direction', direction), ('description', description),
                         ('expectation', expectation)):
            if val is not None:
                sets.append('{} = ?'.format(col))
                vals.append(int(val) if col == 'score' else val)
        if sets:
            conn.execute(
                "UPDATE catalyst_events SET {} WHERE id=?".format(
                    ', '.join(sets)), vals + [eid])
            conn.commit()
    finally:
        conn.close()


def delete_event(eid):
    conn = _conn()
    try:
        conn.execute("DELETE FROM catalyst_events WHERE id=?", (eid,))
        conn.commit()
    finally:
        conn.close()


def _get_event(eid):
    conn = _conn()
    try:
        r = conn.execute(
            "SELECT id, ticker, date, score, direction, description, "
            "expectation, created_at, notified FROM catalyst_events "
            "WHERE id=?", (eid,)).fetchone()
    finally:
        conn.close()
    return _row_to_event(r) if r else None


def events_for(ticker):
    """События по тикеру, сортировка по дате."""
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return []
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, ticker, date, score, direction, description, "
            "expectation, created_at, notified FROM catalyst_events "
            "WHERE ticker=? ORDER BY date", (ticker,)).fetchall()
    finally:
        conn.close()
    return [_row_to_event(r) for r in rows]


def all_events():
    """Все события (для таба Events в watchlist), сортировка по дате."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, ticker, date, score, direction, description, "
            "expectation, created_at, notified FROM catalyst_events "
            "ORDER BY date, id").fetchall()
    finally:
        conn.close()
    return [_row_to_event(r) for r in rows]


def due_events(lead_days=NOTIFY_LEAD_DAYS):
    """События для напоминания: дата в окне [сегодня; сегодня+lead] или
    просроченные (приложение было закрыто). Показываются один раз."""
    today = datetime.date.today()
    horizon = (today + datetime.timedelta(days=lead_days)).isoformat()
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, ticker, date, score, direction, description, "
            "expectation, created_at, notified FROM catalyst_events "
            "WHERE notified=0 AND date <= ? ORDER BY date",
            (horizon,)).fetchall()
    finally:
        conn.close()
    return [_row_to_event(r) for r in rows]


def mark_notified(ids):
    if not ids:
        return
    conn = _conn()
    try:
        conn.executemany("UPDATE catalyst_events SET notified=1 WHERE id=?",
                         [(i,) for i in ids])
        conn.commit()
    finally:
        conn.close()


def reset_notified(ticker=None):
    """Сбросить флаг показа (повторные тесты/перезапуск напоминаний)."""
    conn = _conn()
    try:
        if ticker:
            conn.execute(
                "UPDATE catalyst_events SET notified=0 WHERE ticker=?",
                (ticker.strip().upper(),))
        else:
            conn.execute("UPDATE catalyst_events SET notified=0")
        conn.commit()
    finally:
        conn.close()


def summary_for(ticker):
    """Суммарка для колонки watchlist: count / ближайшая дата / max балл."""
    events = events_for(ticker)
    if not events:
        return None
    today = datetime.date.today().isoformat()
    upcoming = [e for e in events if e['date'] >= today]
    return {'count': len(events),
            'next': (upcoming[0]['date'] if upcoming else events[0]['date']),
            'max': max(e['score'] for e in events)}


def reminder_text(event, simulated=False):
    """Одна строка напоминания по событию."""
    parts = ['{}: катализатор «{}» — {}.'.format(
        event.get('ticker', ''), event.get('description') or 'событие',
        event.get('date', ''))]
    if event.get('expectation'):
        parts.append('Ожидание: ' + event['expectation'])
    text = ' '.join(parts)
    return ('Симуляция: ' + text) if simulated else text


# --------------------------------------------------------------------------
# TEMP SIM — временная симуляция наступления дат для теста.
# Первое событие тикера «наступает» через SIM_LEAD_MINUTES минут, каждое
# следующее — ещё через SIM_INTERVAL_MINUTES. В памяти, сбрасывается при
# рестарте приложения. Удалить после теста.
# --------------------------------------------------------------------------
import time as _time

SIM_LEAD_MINUTES = 30
SIM_INTERVAL_MINUTES = 7

_SIM = {}  # event_id -> remind timestamp (epoch seconds)
_SIM_TICKERS = set()


def sim_schedule_ticker(ticker, lead_minutes=SIM_LEAD_MINUTES,
                        interval_minutes=SIM_INTERVAL_MINUTES):
    """Расписать события тикера на виртуальное наступление. Возвращает True,
    если симуляция для тикера только что запущена (иначе новые события просто
    добавляются к активному расписанию)."""
    ticker = (ticker or '').strip().upper()
    first = ticker not in _SIM_TICKERS
    events = [e for e in events_for(ticker)
              if not e['notified'] and e['id'] not in _SIM]
    events.sort(key=lambda e: e['date'])
    if not events:
        return False
    now = _time.time()
    for i, e in enumerate(events):
        _SIM[e['id']] = now + (lead_minutes + i * interval_minutes) * 60
    _SIM_TICKERS.add(ticker)
    return first


def sim_pending():
    """События, чьё виртуальное время наступления прошло (и ещё не показаны)."""
    now = _time.time()
    out = []
    for eid, at in list(_SIM.items()):
        if at <= now:
            row = _get_event(eid)
            if row and not row['notified']:
                out.append(row)
    return out


def sim_has_scheduled():
    return bool(_SIM)


def sim_unschedule(eid):
    _SIM.pop(eid, None)


def sim_reset():
    _SIM.clear()
    _SIM_TICKERS.clear()