# -*- coding: utf-8 -*-
"""Простой watchlist: список тикеров в JSON-файле в корне репозитория."""
import json
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(_DIR, 'watchlist.json')


def load():
    """Вернуть список тикеров (upper-case). Пустой список, если файла нет."""
    try:
        with open(WATCHLIST_PATH, encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(t).strip().upper() for t in data if str(t).strip()]
    except (OSError, ValueError):
        pass
    return []


def save(items):
    """Полностью перезаписать watchlist заданным списком тикеров."""
    cleaned = [str(t).strip().upper() for t in items if str(t).strip()]
    with open(WATCHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)


def add(ticker):
    """Добавить тикер в watchlist. True, если добавлен (ранее отсутствовал)."""
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return False
    items = load()
    if ticker in items:
        return False
    items.append(ticker)
    save(items)
    return True