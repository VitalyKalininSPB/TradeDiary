# -*- coding: utf-8 -*-
"""Уведомления об изменениях в Quantitative Assessment (без Qt).

События пишутся в `sector_quant.db`:
  quant_events            — смена sector signal / движение company score;
  company_score_baseline  — последний известный company score по тикеру;
  quant_meta              — служебные ключи (время последней стартовой проверки).
"""
import datetime
import os
import sqlite3

import company_quant

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DIR, 'sector_quant.db')

COMPANY_SCORE_THRESHOLD = 0.10
STARTUP_CHECK_DAYS = 3


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS quant_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, "
        "observed_at TEXT NOT NULL, key TEXT NOT NULL, message TEXT NOT NULL, "
        "seen INTEGER NOT NULL DEFAULT 0)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS company_score_baseline ("
        "ticker TEXT PRIMARY KEY, sector TEXT NOT NULL, "
        "score REAL NOT NULL, observed_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS quant_meta ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return conn


def _insert_event(kind, key, message):
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO quant_events (kind, observed_at, key, message) "
            "VALUES (?,?,?,?)",
            (kind, datetime.datetime.now().isoformat(), key, message))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def delete_events(ids):
    """Удалить события (используется симуляцией — не оставлять следов)."""
    if not ids:
        return
    conn = _conn()
    try:
        conn.executemany("DELETE FROM quant_events WHERE id=?",
                         [(i,) for i in ids])
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------ sector signal
def record_sector_signal_change(prev_sectors, new_sectors):
    """Событие для секторов, у которых изменился research signal.

    `prev_sectors`/`new_sectors` — списки секторных результатов (payload).
    Возвращает список созданных событий (dict).
    """
    prev = {}
    for s in prev_sectors or []:
        st = s.get('status') or {}
        prev[s.get('slug')] = st.get('action_id')
    events = []
    for s in new_sectors or []:
        slug = s.get('slug')
        st = s.get('status') or {}
        new_action = st.get('action_id')
        old_action = prev.get(slug)
        if old_action is None:
            continue
        if old_action != new_action:
            msg = '{}: сигнал изменился: {} → {}'.format(
                s.get('sector', slug),
                _action_label(old_action), _action_label(new_action))
            event_id = _insert_event('sector_signal', slug, msg)
            events.append({'id': event_id, 'kind': 'sector_signal',
                           'key': slug, 'message': msg,
                           'observed_at': datetime.datetime.now().isoformat()})
    return events


def _action_label(action_id):
    return {
        'priority_long_research': 'Priority long research',
        'watchlist': 'Watchlist',
        'investigate_catalyst': 'Investigate catalyst',
        'exclude_from_long': 'Exclude from long',
    }.get(action_id, action_id or '-')


# ------------------------------------------------------------ company score
def check_company_scores(companies):
    """Детект движения company score против baseline (порог 0.10).

    Переиспользует company_quant.rank_companies. Обновляет baseline и
    возвращает список новых событий.
    """
    events = []
    baseline = _load_baseline()
    now = datetime.datetime.now().isoformat()
    rows = company_quant.rank_companies(companies)
    conn = _conn()
    try:
        for e in rows:
            score = e.get('company_score')
            ticker = e.get('ticker')
            if score is None or not ticker:
                continue
            sector = e.get('sector') or ''
            prev = baseline.get(ticker)
            if prev is not None and abs(score - prev) >= COMPANY_SCORE_THRESHOLD:
                delta = score - prev
                msg = '{}: company score {:.2f} → {:.2f} ({:+.2f})'.format(
                    ticker, prev, score, delta)
                cur = conn.execute(
                    "INSERT INTO quant_events (kind, observed_at, key, message) "
                    "VALUES (?,?,?,?)",
                    ('company_score', now, ticker, msg))
                events.append({'id': cur.lastrowid, 'kind': 'company_score',
                               'key': ticker, 'message': msg,
                               'observed_at': now})
            conn.execute(
                "INSERT OR REPLACE INTO company_score_baseline "
                "(ticker, sector, score, observed_at) VALUES (?,?,?,?)",
                (ticker, sector, score, now))
        conn.commit()
    finally:
        conn.close()
    return events


def _load_baseline():
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT ticker, score FROM company_score_baseline").fetchall()
    finally:
        conn.close()
    return {t: s for t, s in rows}


def baseline_snapshot():
    """Снимок таблицы baseline: [(ticker, sector, score, observed_at)]."""
    conn = _conn()
    try:
        return conn.execute(
            "SELECT ticker, sector, score, observed_at "
            "FROM company_score_baseline").fetchall()
    finally:
        conn.close()


def restore_baseline(rows):
    """Восстановить baseline из снимка (используется симуляцией)."""
    conn = _conn()
    try:
        conn.execute("DELETE FROM company_score_baseline")
        conn.executemany(
            "INSERT INTO company_score_baseline "
            "(ticker, sector, score, observed_at) VALUES (?,?,?,?)",
            rows)
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------- query
def unseen_count():
    conn = _conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM quant_events WHERE seen=0").fetchone()[0]
    finally:
        conn.close()


def new_events():
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, kind, observed_at, key, message FROM quant_events "
            "WHERE seen=0 ORDER BY id").fetchall()
    finally:
        conn.close()
    return [{'id': r[0], 'kind': r[1], 'observed_at': r[2], 'key': r[3],
             'message': r[4]} for r in rows]


def mark_all_seen():
    conn = _conn()
    try:
        conn.execute("UPDATE quant_events SET seen=1 WHERE seen=0")
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------- startup check gate
def should_startup_check():
    """True, если стартовая проверка не запускалась больше STARTUP_CHECK_DAYS."""
    v = _meta_get('last_startup_check_at')
    if not v:
        return True
    try:
        last = datetime.datetime.fromisoformat(v)
    except ValueError:
        return True
    return (datetime.datetime.now() - last).total_seconds() \
        >= STARTUP_CHECK_DAYS * 86400


def mark_startup_check():
    _meta_set('last_startup_check_at', datetime.datetime.now().isoformat())


def _meta_get(key):
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT value FROM quant_meta WHERE key=?", (key,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _meta_set(key, value):
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO quant_meta (key, value) VALUES (?,?)",
            (key, value))
        conn.commit()
    finally:
        conn.close()