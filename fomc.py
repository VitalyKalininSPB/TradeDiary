# -*- coding: utf-8 -*-
"""FOMC statement feed (separate "Statements" dialog).

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

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

_BG = '#1e1f24'
_TXT = '#dcdce0'
_GRID = '#43464f'

_FEED_URL = 'https://www.federalreserve.gov/feeds/press_all.xml'
_REFRESH_HOURS = 24

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


def _http_text(url):
    """GET a page and decode as UTF-8 (the Fed serves utf-8 despite the header)."""
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
    r.raise_for_status()
    return r.content.decode('utf-8', errors='replace')


def _fetch_feed_items():
    """Parse the Fed RSS feed and return (title, url) of FOMC statements."""
    body = _http_text(_FEED_URL)
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


def _find_start_paragraph(paras):
    """Index of the first <p> that opens the statement body, else 0.

    Targets the stable modern FOMC template (since ~2019): the statement is
    announced with "approved the following statement for release by a
    N – M vote". Older/edge phrasing ("Information received since ...") is
    matched too, so a format drift degrades gracefully instead of parsing junk.
    """
    for i, p in enumerate(paras):
        plain = re.sub(r'<[^>]+>', '', p)
        if 'for release by a' in plain or \
                plain.strip().startswith('The Federal Open Market Committee approved') or \
                plain.strip().startswith('Information received since'):
            return i
    return 0


def _flat_fallback(seg):
    """Flat text fallback: collapse the page, trimmed at statement markers."""
    txt = re.sub(r'<[^>]+>', ' ', seg)
    txt = html_module.unescape(txt)
    txt = re.sub(r'\s+', ' ', txt).strip()
    txt = re.split(r'For media inquiries', txt)[0].strip()
    for marker in ('The Federal Open Market Committee', 'Information received '
                   'since', 'Economic activity', 'decided to maintain'):
        i = txt.find(marker)
        if i >= 0:
            txt = txt[i:]
            break
    return '<p>{}</p>'.format(html_module.escape(txt))


def _fetch_statement_body(url):
    """Return the statement body as HTML (paragraphs preserved).

    Keeping the original <p> blocks (and inline <strong>/<em>) avoids the
    readability loss of a flat text blob; the QTextBrowser renders it with the
    original paragraph structure.
    """
    body = _http_text(url)
    end = body.find('Implementation Note')
    seg = body[:end] if end > 0 else body
    # Drop the header/scripts/meta so the anchor is found only in the body.
    seg = re.sub(r'<head.*?</head>', '', seg, flags=re.S)
    seg = re.sub(r'<script.*?</script>', '', seg, flags=re.S)
    seg = re.sub(r'<style.*?</style>', '', seg, flags=re.S)
    paras = re.findall(r'<p[^>]*>(.*?)</p>', seg, re.S)
    out = []
    for p in paras[_find_start_paragraph(paras):]:
        inner = re.sub(r'<script.*?</script>', '', p, flags=re.S)
        plain = html_module.unescape(
            re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', inner))).strip()
        if not plain:
            continue
        if 'For media inquiries' in plain:
            continue
        out.append(inner.strip())
    if out:
        # Trim the page chrome ("For release at ... EDT", "Share") from the
        # intro paragraph, keeping the statement text.
        m = re.search(r'The Federal Open Market Committee approved', out[0])
        if m:
            out[0] = out[0][m.start():]
        return '<p>{}</p>'.format('</p><p>'.join(out))
    return _flat_fallback(seg)


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
    text = re.sub(r'<[^>]+>', ' ', body or '')
    text = html_module.unescape(re.sub(r'\s+', ' ', text))
    m = re.search(
        r'decided to maintain the target range for the federal funds rate '
        r'at ([^.,;]+)', text, re.I)
    if m:
        return 'ставка сохранена: {}'.format(
            re.sub(r'\s+', ' ', m.group(1)).strip())
    m = re.search(
        r'decided to (lower|raise) the target range for the federal funds '
        r'rate by ([^.,;]+)', text, re.I)
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
        summary = _decision_summary(it.get('body', ''))
        head = QLabel('FOMC statement, {}{}'.format(
            it['date'], ' — ' + summary if summary else ''))
        head.setWordWrap(True)
        head.setStyleSheet('color: {}; font-weight: bold;'.format(_TXT))
        root.addWidget(head)
        url = it.get('url') or ''
        if url:
            link = QLabel('<a href="{0}" style="color: #81a1c1;">Открыть '
                          'оригинал на federalreserve.gov</a>'.format(url))
            link.setOpenExternalLinks(True)
            link.setStyleSheet('font-size: 11px;')
            root.addWidget(link)
        view = QTextBrowser()
        view.setStyleSheet('QTextBrowser {{ background-color: {}; color: {}; }}'
                           .format(_BG, _TXT))
        body = it.get('body') or ''
        if body.startswith('<'):
            view.setHtml(body)
        else:
            view.setPlainText(body or '(текст заявления недоступен)')
        root.addWidget(view, 1)
        dlg.show()


class _FomcLoaderThread(QThread):
    """Refresh the FOMC feed off the UI thread, then emit load_done."""

    load_done = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            refresh_fomc_if_stale()
        except Exception as e:  # noqa: BLE001 - a failing refresh must not kill the UI
            print('FOMC refresh failed: {}'.format(e))
        self.load_done.emit()


class StatementsDialog(QDialog):
    """FOMC statements feed as a standalone dialog (button "Statements")."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('FOMC Statements')
        self.resize(780, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        head = QLabel('Заявления ФРС (FOMC) — источник: federalreserve.gov')
        head.setStyleSheet('color: {}; font-weight: bold;'.format(_TXT))
        root.addWidget(head)

        self.tab = FomcTab(self)
        root.addWidget(self.tab, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.reloadButton = QPushButton('Reload')
        self.reloadButton.clicked.connect(self._load)
        row.addWidget(self.reloadButton)
        closeBtn = QPushButton('Close')
        closeBtn.clicked.connect(self.accept)
        row.addWidget(closeBtn)
        root.addLayout(row)

        self._loader = None
        self._load()

    def _load(self):
        self.reloadButton.setEnabled(False)
        self.tab.set_statements(load_fomc_statements())
        self._loader = _FomcLoaderThread(self)
        self._loader.load_done.connect(self._on_load_done)
        self._loader.start()

    def _on_load_done(self):
        self.reloadButton.setEnabled(True)
        self.tab.set_statements(load_fomc_statements())
        if unread_count():
            self._show_goat('Есть непрочитанные заявления ФРС (FOMC). '
                            'Нажмите на строку, чтобы прочитать.')

    def _show_goat(self, advice):
        from qualitative_dialog import GoatAssistant
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
            self._goat = None
        if not advice:
            return
        self._goat = GoatAssistant('', self, advice=advice,
                                   auto_hide_ms=20000)
        self._goat.show()

    def closeEvent(self, event):
        if getattr(self, '_goat', None) is not None:
            self._goat.close()
            self._goat.deleteLater()
        if self._loader is not None and self._loader.isRunning():
            self._loader.wait(5000)
        super().closeEvent(event)