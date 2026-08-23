# -*- coding: utf-8 -*-
"""Company logo fetching with on-disk caching.

Primary source: Parqet asset logos (https://assets.parqet.com/logos/symbol/{ticker}),
which cover most world / US tickers and a number of MOEX names. Result files
are cached in the local `logos/` directory so the logo is only fetched once.

If a provider returns nothing usable, a small letter avatar (placeholder) is
rendered locally as a fallback, so the label is never visually broken.
"""
import os
import re
import threading
import requests

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
from PySide6.QtSvg import QSvgRenderer

_UA = {'User-Agent': 'TradeDiary/1.1 (https://github.com/TradeDiary; ti-diary-user@localhost)'}
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_DIR = os.path.join(_BASE_DIR, 'logos')

_FETCH_TIMEOUT = 10
_TARGET_HEIGHT = 44

# in-memory pixmap cache: key -> QPixmap or None (None == known missing)
_cached = {}
_lock = threading.Lock()


def _ext_for(data):
    if not data:
        return '.bin'
    head = data[:16].lstrip().lower()
    if head.startswith(b'<svg') or b'<svg' in data[:64]:
        return '.svg'
    if data[:8].startswith(b'\x89PNG'):
        return '.png'
    if data[1:4] == b'PNG':
        return '.png'
    if data[:3] == b'GIF':
        return '.gif'
    if data[:2] in (b'BM',):
        return '.bmp'
    if data[:2] == b'\xff\xd8':
        return '.jpg'
    return '.bin'


def _safe_name(ticker):
    name = re.sub(r'[^A-Za-z0-9._-]', '_', ticker or '').strip()
    return name or 'unknown'


def _cache_path(ticker, ext):
    return os.path.join(LOGO_DIR, _safe_name(ticker) + ext)


def _render_pixmap(data):
    """Turn raw bytes (SVG or bitmap) into a QPixmap.

    Uses Qt's built-in format plugins (svg/raster) via loadFromData, which is
    more tolerant of real-world SVG files than the manual QSvgRenderer path.
    """
    if not data:
        return None
    pm = QPixmap()
    if pm.loadFromData(data):
        return pm
    if _ext_for(data) == '.svg':
        renderer = QSvgRenderer(bytes(data))
        size = renderer.defaultSize()
        if size.width() <= 0 or size.height() <= 0:
            size = QSize(120, 120)
        pm = QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        ok = renderer.render(painter)
        painter.end()
        if ok:
            return pm
    return None


def _fetch_provider(ticker):
    """Fetch logo bytes for a ticker; returns bytes or None."""
    url = 'https://assets.parqet.com/logos/symbol/{}'.format(ticker)
    try:
        r = requests.get(url, headers=_UA, timeout=_FETCH_TIMEOUT)
        r.raise_for_status()
        if not r.content:
            return None
        return r.content
    except Exception as e:
        print('Logo fetch failed for ' + ticker + ': ' + str(e))
        return None


def _placeholder(ticker):
    """Local fallback: rounded square with the first letter of the ticker."""
    size = 44
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(58, 90, 128))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, 8, 8)
    p.setPen(QColor(255, 255, 255))
    f = QFont('Sans', 20)
    f.setBold(True)
    p.setFont(f)
    letter = (ticker or '?').strip()[:1].upper() or '?'
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, letter)
    p.end()
    return pm


def _moex_sec_names(ticker):
    """Fetch the company names for a MOEX security.

    Returns (latname, shortname) or (None, None) on failure.
    """
    url = 'https://iss.moex.com/iss/securities/{}.json?iss.meta=off'.format(ticker)
    try:
        r = requests.get(url, headers=_UA, timeout=_FETCH_TIMEOUT)
        r.raise_for_status()
        d = r.json().get('description', {})
        cols = d.get('columns', [])
        name_idx = cols.index('name')
        val_idx = cols.index('value')
        names = {}
        for row in d.get('data', []):
            try:
                names[row[name_idx]] = row[val_idx]
            except Exception:
                continue
        return names.get('LATNAME'), names.get('SHORTNAME') or names.get('NAME')
    except Exception as e:
        print('MOEX names fetch failed for ' + ticker + ': ' + str(e))
        return None, None


def _wp_api(lang, **params):
    url = 'https://{}.wikipedia.org/w/api.php'.format(lang)
    params['action'] = 'query'
    params['format'] = 'json'
    try:
        r = requests.get(url, headers=_UA, params=params, timeout=_FETCH_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print('Wikipedia ' + lang + ' API failed: ' + str(e))
        return None


def _wp_search_page(lang, term):
    """Return the best-matching article title for `term` (or None)."""
    data = _wp_api(lang, list='search', srsearch=term, srlimit=1, srnamespace=0)
    if not data:
        return None
    res = data.get('query', {}).get('search')
    if res:
        return res[0].get('title')
    return None


def _wp_logo_file(lang, page):
    """Find a logo image file name for an article, else None."""
    data = _wp_api(lang, titles=page, prop='images', imlimit=500)
    if not data:
        return None
    best = None
    for p in data.get('query', {}).get('pages', {}).values():
        for im in p.get('images', []):
            title = im.get('title', '')
            low = title.lower()
            if 'logo' not in low:
                continue
            if 'commons-logo' in low or 'wikimedia' in low:
                continue
            if best is None or ('.svg' in low and '.svg' not in best.lower()):
                best = title
    return best


def _wp_file_url(lang, file):
    data = _wp_api(lang, titles=file, prop='imageinfo', iiprop='url')
    if not data:
        return None
    for p in data.get('query', {}).get('pages', {}).values():
        info = p.get('imageinfo')
        if info:
            return info[0].get('url')
    return None


def _moex_logo_bytes(ticker):
    """Resolve and download a logo image for a MOEX ticker via Wikipedia."""
    latname, shortname = _moex_sec_names(ticker)
    candidates = []
    if latname:
        candidates.append(('en', latname))
    if shortname:
        candidates.append(('ru', shortname))
    for lang, term in candidates:
        page = _wp_search_page(lang, term)
        if not page:
            continue
        logo_file = _wp_logo_file(lang, page)
        if not logo_file:
            continue
        url = _wp_file_url(lang, logo_file)
        if not url:
            continue
        url = url.split('?', 1)[0]
        try:
            r = requests.get(url, headers=_UA, timeout=_FETCH_TIMEOUT)
            r.raise_for_status()
            if r.content:
                return r.content
        except Exception as e:
            print('MOEX logo download failed for ' + ticker + ': ' + str(e))
    return None


def moex_logo_pixmap(ticker):
    """Return a QPixmap logo for a MOEX ticker (Wikipedia-based), cached.

    Returns None (not the letter avatar) when no logo could be resolved, so the
    caller can fall back to another provider. Only real logos are cached.
    """
    ticker = (ticker or '').strip().upper()
    key = 'MOEX:' + ticker
    if not ticker:
        return None
    base = _safe_name('MOEX_' + ticker)
    pm = _cache_lookup(key, base)
    if pm is not None:
        return pm
    data = _moex_logo_bytes(ticker)
    if data:
        path = os.path.join(LOGO_DIR, base + _ext_for(data))
        try:
            with open(path, 'wb') as fh:
                fh.write(data)
        except Exception as e:
            print('MOEX logo cache write failed for ' + ticker + ': ' + str(e))
        pm = _render_pixmap(data)
        if pm is not None and not pm.isNull():
            pm = pm.scaledToHeight(
                _TARGET_HEIGHT, Qt.TransformationMode.SmoothTransformation)
            return _store(key, pm)
    return None


def _cache_lookup(key, base):
    """Look up a cached pixmap in memory or on disk; return QPixmap or None."""
    with _lock:
        if key in _cached:
            return _cached[key]
    os.makedirs(LOGO_DIR, exist_ok=True)
    try:
        for fname in os.listdir(LOGO_DIR):
            if fname.lower().startswith(base.lower() + '.'):
                path = os.path.join(LOGO_DIR, fname)
                with open(path, 'rb') as fh:
                    data = fh.read()
                pm = _render_pixmap(data)
                if pm is not None and not pm.isNull():
                    pm = pm.scaledToHeight(
                        _TARGET_HEIGHT, Qt.TransformationMode.SmoothTransformation)
                    return _store(key, pm)
    except Exception as e:
        print('Logo cache read failed for ' + key + ': ' + str(e))
    return None


def logo_pixmap(ticker):
    """Return a QPixmap for a company logo (small), loading from cache if possible.

    The result is cached in memory and on disk. Returns None when no logo could
    be obtained, so the caller can try another provider or show a placeholder.
    """
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return None

    with _lock:
        if ticker in _cached:
            return _cached[ticker]

    os.makedirs(LOGO_DIR, exist_ok=True)

    # 1) On-disk cache (any extension)
    for fname in os.listdir(LOGO_DIR):
        if fname.lower().startswith(_safe_name(ticker).lower() + '.'):
            path = os.path.join(LOGO_DIR, fname)
            try:
                with open(path, 'rb') as fh:
                    data = fh.read()
                pm = _render_pixmap(data)
                if pm is not None and not pm.isNull():
                    pm = pm.scaledToHeight(
                        _TARGET_HEIGHT, Qt.TransformationMode.SmoothTransformation)
                    return _store(ticker, pm)
            except Exception as e:
                print('Logo cache read failed for ' + ticker + ': ' + str(e))

    # 2) Network
    data = _fetch_provider(ticker)
    if data:
        path = _cache_path(ticker, _ext_for(data))
        try:
            with open(path, 'wb') as fh:
                fh.write(data)
        except Exception as e:
            print('Logo cache write failed for ' + ticker + ': ' + str(e))
        pm = _render_pixmap(data)
        if pm is not None and not pm.isNull():
            pm = pm.scaledToHeight(
                _TARGET_HEIGHT, Qt.TransformationMode.SmoothTransformation)
            return _store(ticker, pm)

    # 3) Nothing found -> signal the caller (do not cache, do not fake a logo)
    return None


def placeholder_pixmap(ticker, height=_TARGET_HEIGHT):
    """A local letter avatar used only when no real logo could be resolved."""
    return _placeholder(ticker).scaledToHeight(
        height, Qt.TransformationMode.SmoothTransformation)


def _store(ticker, pm):
    with _lock:
        _cached[ticker] = pm
    return pm
