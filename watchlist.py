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
        'quant': None,
        'qual': None,
    }


def _migrate_legacy(entry):
    """Перенести старые quant/qual из единого snapshot в отдельные поля.

    Старый формат хранил всё в одном `snapshot` dict. Новый — отдельные
    `quant` и `qual` снапшоты на каждый вид анализа.
    """
    s = entry.get('snapshot')
    if not isinstance(s, dict):
        return
    if entry.get('quant') is None and s.get('quant') is not None:
        entry['quant'] = {'score': s['quant'], 'sector': s.get('quant_sector'),
                          'date': s.get('date')}
        s.pop('quant', None)
        s.pop('quant_sector', None)
    if entry.get('qual') is None and (s.get('qual') is not None
                                      or s.get('quality')):
        entry['qual'] = {'score': s.get('qual'), 'report': s.get('quality'),
                         'report_html': s.get('quality_html'),
                         'date': s.get('date')}
        s.pop('qual', None)
        s.pop('quality', None)
        s.pop('quality_html', None)


def get_quant(entry):
    """Quant-снапшот {score, sector, date} или None (legacy fallback)."""
    if not isinstance(entry, dict):
        return None
    q = entry.get('quant')
    if isinstance(q, dict):
        return q
    s = entry.get('snapshot') or {}
    if s.get('quant') is not None:
        return {'score': s['quant'], 'sector': s.get('quant_sector'),
                'date': s.get('date')}
    return None


def get_qual(entry):
    """Qual-снапшот {score, report, report_html, date} или None (legacy fallback)."""
    if not isinstance(entry, dict):
        return None
    q = entry.get('qual')
    if isinstance(q, dict):
        return q
    s = entry.get('snapshot') or {}
    if s.get('qual') is not None or s.get('quality'):
        return {'score': s.get('qual'), 'report': s.get('quality'),
                'report_html': s.get('quality_html'), 'date': s.get('date')}
    return None


def set_quant_snapshot(ticker, score, sector=None, date=None):
    """Записать Quant-снапшот отдельным полем (не трогая Qual)."""
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return 'empty'
    today = date or datetime.date.today().isoformat()
    entries = load()
    for e in entries:
        if e.get('ticker') == ticker:
            _migrate_legacy(e)
            e['quant'] = {'score': score, 'sector': sector, 'date': today}
            e['date'] = today
            save(entries)
            return 'updated'
    entry = _entry(ticker)
    entry['quant'] = {'score': score, 'sector': sector, 'date': today}
    entries.append(entry)
    save(entries)
    return 'added'


def set_qual_snapshot(ticker, score, report=None, report_html=None, date=None):
    """Записать Qual-снапшот отдельным полем (не трогая Quant)."""
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return 'empty'
    today = date or datetime.date.today().isoformat()
    entries = load()
    for e in entries:
        if e.get('ticker') == ticker:
            _migrate_legacy(e)
            e['qual'] = {'score': score, 'report': report,
                         'report_html': report_html, 'date': today}
            e['date'] = today
            save(entries)
            return 'updated'
    entry = _entry(ticker)
    entry['qual'] = {'score': score, 'report': report,
                     'report_html': report_html, 'date': today}
    entries.append(entry)
    save(entries)
    return 'added'


def load():
    """Вернуть список записей-словарей (мигрируя legacy строки и snapshot)."""
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
            _migrate_legacy(item)
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