# -*- coding: utf-8 -*-
"""Ручной watchlist: компании с решением (Research / Watching / Rejected /
Owned), заметкой, датой и причиной решения + снапшот quant/qual score.

Хранится в JSON-файле `watchlist.json`. Legacy-формат (список строк-тикеров)
мигрируется при загрузке.
"""
import datetime
import json
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(_DIR, 'watchlist.json')

STATUSES = ['Research', 'Watching', 'Rejected', 'Owned']
DEFAULT_STATUS = 'Research'


def _entry(ticker):
    return {
        'ticker': ticker,
        'status': DEFAULT_STATUS,
        'note': '',
        'reason': '',
        'date': datetime.date.today().isoformat(),
        'snapshot': None,
    }


def load():
    """Вернуть список записей-словарей (мигрируя legacy строки)."""
    try:
        with open(WATCHLIST_PATH, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    entries = []
    for item in data:
        if isinstance(item, str):
            t = item.strip().upper()
            if t:
                entries.append(_entry(t))
        elif isinstance(item, dict) and item.get('ticker'):
            entries.append(item)
    return entries


def save(entries):
    with open(WATCHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def add(ticker, status=None, note='', reason='', snapshot=None):
    """Добавить/обновить запись. Вернуть 'added' | 'updated' | 'empty'."""
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return 'empty'
    today = datetime.date.today().isoformat()
    entries = load()
    for e in entries:
        if e['ticker'] == ticker:
            if status in STATUSES:
                e['status'] = status
            if note:
                e['note'] = note
            if reason:
                e['reason'] = reason
            if snapshot is not None:
                e['snapshot'] = snapshot
            e['date'] = today
            save(entries)
            return 'updated'
    entry = _entry(ticker)
    if status in STATUSES:
        entry['status'] = status
    entry['note'] = note
    entry['reason'] = reason
    entry['snapshot'] = snapshot
    entries.append(entry)
    save(entries)
    return 'added'


def update(ticker, status=None, note=None, reason=None, snapshot=None):
    """Обновить отдельные поля существующей записи (None = не трогать)."""
    ticker = (ticker or '').strip().upper()
    entries = load()
    for e in entries:
        if e['ticker'] == ticker:
            if status in STATUSES:
                e['status'] = status
            if note is not None:
                e['note'] = note
            if reason is not None:
                e['reason'] = reason
            if snapshot is not None:
                e['snapshot'] = snapshot
            e['date'] = datetime.date.today().isoformat()
            save(entries)
            return True
    return False


def remove(ticker):
    ticker = (ticker or '').strip().upper()
    entries = [e for e in load() if e['ticker'] != ticker]
    save(entries)


def find(ticker):
    ticker = (ticker or '').strip().upper()
    for e in load():
        if e['ticker'] == ticker:
            return e
    return None