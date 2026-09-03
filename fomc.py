# -*- coding: utf-8 -*-
"""FOMC statement feed for the macro dashboard.

Lists the post-meeting FOMC statements ("Federal Reserve issues FOMC
statement") from the Fed's RSS feed (press_all.xml), with the full statement
text on click. The feed covers roughly the last ~7 weeks. Data is cached in
macro_cache.db; the feed is refreshed at most once a day, always from a
background thread. Each statement is marked read individually (per click) and
the flag survives restarts.
"""
import datetime
import html as html_module
import os
import re
import sqlite3

import requests

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QTextBrowser, QVBoxLayout,
                               QWidget)

_BG = '#1e1f24'
_TXT = '#dcdce0'
_GRID = '#43464f'

_FEED_URL = 'https://www.federalreserve.gov/feeds/press_all.xml'
_REFRESH_HOURS = 24

# Phrase that opens the statement body on the Fed press-release pages.
_START_PATTERNS = [
    'The Federal Open Market Committee approved the following',
    'Recent indicators suggest that economic activity',
    'Economic activity',
    'Information received since the Federal Open Market Committee met',
]

_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'macro_cache.db')


def _conn():
    conn = sqlite3.connect(_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fomc_statements ("
        "id TEXT PRIMARY KEY, date TEXT NOT NULL, title TEXT NOT NULL, "
        "url TEXT NOT NULL, body TEXT NOT NULL, "
        "read INTEGER NOT NULL DEFAULT 0, fetched_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fomc_meta ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return conn


def _meta_get(key, default=None):
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT value FROM fomc_meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
    finally:
        conn.close()


def _meta_set(key, value):
    conn = _conn()
    try:
        conn.execute("INSERT OR REPLACE INTO fomc_meta (key, value) "
                     "VALUES (?,?)", (key, value))
        conn.commit()
    finally:
        conn.close()


def load_fomc_statements():
    """Return cached statements as a list of dicts, newest first."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, date, title, url, body, read FROM fomc_statements "
            "ORDER BY date DESC").fetchall()
    finally:
        conn.close()
    return [{'id': r[0], 'date': r[1], 'title': r[2], 'url': r[3],
             'body': r[4], 'read': bool(r[5])} for r in rows]


def save_fomc_statements(items):
    """Replace the cached list, preserving read flags by statement id."""
    conn = _conn()
    try:
        existing = dict(conn.execute(
            "SELECT id, read FROM fomc_statements").fetchall())
        ids = [it['id'] for it in items]
        placeholders = ','.join('?' * len(ids)) if ids else "''"
        conn.execute(
            "DELETE FROM fomc_statements WHERE id NOT IN ({})".format(
                placeholders), ids)
        now = datetime.datetime.now().isoformat()
        for it in items:
            conn.execute(
                "INSERT OR REPLACE INTO fomc_statements "
                "(id, date, title, url, body, read, fetched_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (it['id'], it['date'], it['title'], it['url'], it['body'],
                 1 if existing.get(it['id']) else 0, now))
        conn.commit()
    finally:
        conn.close()
    _meta_set('last_refresh', datetime.datetime.now().isoformat())


def unread_count():
    """Number of statements the user has not clicked yet."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM fomc_statements WHERE read=0").fetchone()
    finally:
        conn.close()
    return int(row[0])


def mark_read(statement_id):
    conn = _conn()
    try:
        conn.execute("UPDATE fomc_statements SET read=1 WHERE id=?",
                     (statement_id,))
        conn.commit()
    finally:
        conn.close()


def _fetch_feed_items():
    """Parse the Fed RSS feed and return (title, url) of FOMC statements."""
    body = requests.get(_FEED_URL, headers={'User-Agent': 'Mozilla/5.0'},
                        timeout=25).text
    body = body.lstrip('\ufeff')
    out = []
    for block in re.findall(r'<item>.*?</item>', body, re.S):
        title = re.search(r'<title>(.*?)</title>', block, re.S)
        link = re.search(r'<link>(.*?)</link>', block, re.S)
        if not title or not link:
            continue
        t = html_module.unescape(
            re.sub(r'<[^>]+>', '', title.group(1))).strip()
        l = html_module.unescape(link.group(1)).strip()
        if l.startswith('<![CDATA[') and l.endswith(']]>'):
            l = l[9:-3]
        if 'monetary' in l and t == 'Federal Reserve issues FOMC statement':
            out.append((t, l))
    return out


def _fetch_statement_body(url):
    """Return the statement text from a Fed press-release page."""
    body = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'},
                        timeout=25).text
    end = body.find('Implementation Note')
    seg = body[:end] if end > 0 else body
    start = -1
    for pat in _START_PATTERNS:
        start = seg.find(pat)
        if start >= 0:
            break
    seg = seg[start:] if start >= 0 else seg
    txt = re.sub(r'<script.*?</script>', ' ', seg, flags=re.S)
    txt = re.sub(r'<style.*?</style>', ' ', txt, flags=re.S)
    txt = re.sub(r'<[^>]+>', ' ', txt)
    txt = html_module.unescape(txt)
    txt = re.sub(r'\s+', ' ', txt).strip()
    txt = re.split(r'For media inquiries', txt)[0].strip()
    return txt


def fetch_fomc_statements():
    """Fetch FOMC statements from the Fed (network only). Newest first."""
    items = []
    for title, url in _fetch_feed_items():
        m = re.search(r'monetary(\d{8})', url)
        if not m:
            continue
        d = m.group(1)
        date = '{}-{}-{}'.format(d[:4], d[4:6], d[6:8])
        try:
            body = _fetch_statement_body(url)
        except Exception as e:  # noqa: BLE001 - a failing page must not drop the item
            print('FOMC: failed to fetch {}: {}'.format(url, e))
            body = ''
        items.append({'id': date, 'date': date, 'title': title,
                      'url': url, 'body': body})
    seen = set()
    out = []
    for it in items:
        if it['id'] in seen:
            continue
        seen.add(it['id'])
        out.append(it)
    out.sort(key=lambda x: x['date'], reverse=True)
    return out


def refresh_fomc_if_stale(force=False):
    """Fetch and cache when the feed is older than a day (background only)."""
    last = _meta_get('last_refresh')
    fresh = False
    if last:
        try:
            age = datetime.datetime.now() - datetime.datetime.fromisoformat(last)
            fresh = age.total_seconds() < _REFRESH_HOURS * 3600
        except ValueError:
            fresh = False
    if fresh and not force:
        return
    items = fetch_fomc_statements()
    if items:
        save_fomc_statements(items)


def _decision_summary(body):
    """Short summary of the rate decision, or '' when not found."""
    m = re.search(
        r'decided to maintain the target range for the federal funds rate '
        r'at ([^.,;]+)', body, re.I)
    if m:
        return 'ставка сохранена: {}'.format(
            re.sub(r'\s+', ' ', m.group(1)).strip())
    m = re.search(
        r'decided to (lower|raise) the target range for the federal funds '
        r'rate by ([^.,;]+)', body, re.I)
    if m:
        verb = 'понижена' if m.group(1) == 'lower' else 'повышена'
        return 'ставка {} на {}'.format(
            verb, re.sub(r'\s+', ' ', m.group(2)).strip())
    return ''


class FomcTab(QWidget):
    """Feed of FOMC statements: a list, not a chart."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel('FOMC statements'))
        self.noteLabel = QLabel('')
        self.noteLabel.setStyleSheet('color: {};'.format(_TXT))
        bar.addWidget(self.noteLabel, 1)
        hint = QLabel('обновляется раз в день')
        hint.setStyleSheet('color: #6a6d78; font-size: 11px;')
        bar.addWidget(hint)
        root.addLayout(bar)

        self.list = QListWidget()
        self.list.setStyleSheet(
            'QListWidget {{ background-color: {}; color: {}; border: 1px solid '
            '{}; }}'
            'QListWidget::item {{ padding: 8px; }}'
            'QListWidget::item:selected {{ background-color: #3a3d49; }}'
            .format(_BG, _TXT, _GRID))
        self.list.itemClicked.connect(self._on_item_clicked)
        root.addWidget(self.list, 1)

        desc = QLabel('Заявления Федерального комитета по открытым рынкам '
                      '(FOMC) после заседаний. Клик по строке — полный текст. '
                      'Источник: federalreserve.gov (RSS).')
        desc.setWordWrap(True)
        desc.setStyleSheet('color: #6a6d78; font-size: 11px;')
        root.addWidget(desc)

    def set_statements(self, items):
        self._items = items or []
        self.list.clear()
        for it in self._items:
            summary = _decision_summary(it.get('body', ''))
            label = '{} — {}'.format(it['date'], summary or 'FOMC statement')
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, it['id'])
            if not it.get('read'):
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            self.list.addItem(item)
        self._refresh_note()

    def _refresh_note(self):
        self.noteLabel.setText('{} заявлений, {} непрочитанных'.format(
            len(self._items), unread_count()))

    def _on_item_clicked(self, item):
        sid = item.data(Qt.ItemDataRole.UserRole)
        for it in self._items:
            if it['id'] == sid:
                self._show_statement(it)
                mark_read(sid)
                f = item.font()
                f.setBold(False)
                item.setFont(f)
                self._refresh_note()
                break

    def _show_statement(self, it):
        dlg = QDialog(self)
        dlg.setWindowTitle('FOMC statement — {}'.format(it['date']))
        dlg.resize(760, 600)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        root = QVBoxLayout(dlg)
        root.setContentsMargins(12, 12, 12, 12)
        head = QLabel('FOMC statement, {}'.format(it['date']))
        head.setStyleSheet('color: {}; font-weight: bold;'.format(_TXT))
        root.addWidget(head)
        view = QTextBrowser()
        view.setStyleSheet('QTextBrowser {{ background-color: {}; color: {}; }}'
                           .format(_BG, _TXT))
        view.setPlainText(it.get('body') or '(текст заявления недоступен)')
        root.addWidget(view, 1)
        dlg.show()