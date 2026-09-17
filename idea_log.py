# -*- coding: utf-8 -*-
"""Журнал идей (run-log) для будущей аналитики — append-only SQLite.

Каждая открытая сделка автоматически пишется сюда (main.py: longClicked /
shortClicked / watchlist_dialog._open_trade_plan), при закрытии — дополняется
исходом (editClicked). ТЕХНИЧЕСКИЙ СНИМОК фиксируется на дату входа и больше
не пересчитывается — защита от look-ahead bias при будущем бэктесте.

Хранение: `idea_log.db`, таблица `ideas`, schema_version = 1
(PRAGMA user_version). Данные НЕ удаляются никогда: открытая запись обновляется
по ключу (ticker, entry_date, entry_price, direction), исход пишется в ту же
строку. Схема фиксирована — анализ/отображение допишутся позже.
"""
import datetime
import json
import os
import sqlite3

import company_data
import price_history
import technical_timing

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DIR, 'idea_log.db')

SCHEMA_VERSION = 1


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ideas ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "ticker TEXT NOT NULL, "
        "sector TEXT, "
        "direction TEXT NOT NULL, "            # long | short
        "horizon_days INTEGER DEFAULT 60, "
        "entry_date TEXT NOT NULL, "           # YYYY-MM-DD (дата сигнала)
        "entry_price REAL, "
        # -- фундаментальный снимок на дату входа
        "fundamental TEXT, "                   # JSON (net_margin/forward_pe/...)
        "source TEXT, "                        # источник фундаментального снимка
        "source_date TEXT, "
        "probability TEXT, "                   # high | medium | low (аннотация)
        "main_risk TEXT, "
        # -- технический снимок НА ДАТУ СИГНАЛА (не пересчитывать!)
        "signal_price REAL, "
        "price_vs_sma200 TEXT, "               # Above | Below | —
        "sma200 REAL, "
        "macd_state TEXT, "                    # bullish | bearish | —
        "rsi REAL, "
        "tech_status TEXT, "                   # ready | wait | reassess | no_data
        "tech_reason TEXT, "
        "tech_warning TEXT, "
        # -- исход
        "outcome TEXT NOT NULL DEFAULT 'open', "  # open | closed
        "close_date TEXT, "
        "days_to_outcome INTEGER, "
        "max_adverse_move_pct REAL, "          # движение ПРОТИВ позиции (%, >= 0)
        "final_pnl_pct REAL, "
        "notes TEXT, "
        "created_at TEXT NOT NULL, "
        "closed_at TEXT)")
    conn.execute("PRAGMA user_version = {}".format(SCHEMA_VERSION))
    return conn


# ---------------------------------------------------------------------------
# Технический снимок на дату сигнала (только из кэша, без сети)
# ---------------------------------------------------------------------------

def snapshot_technical(ticker, direction='long'):
    """Индикаторы по кэшированным ценам НА СЕЙЧАС. Возврат — словарь колонок.

    Снимок пишется один раз при логировании и никогда не пересчитывается.
    """
    series = price_history.load_series(ticker)
    if not series:
        return {
            'signal_price': None, 'price_vs_sma200': '—', 'sma200': None,
            'macd_state': None, 'rsi': None, 'tech_status': 'no_data',
            'tech_reason': 'нет кэша цен', 'tech_warning': '',
        }
    items = sorted(series.items())
    res = technical_timing.build_timing(
        ticker, [d for d, _ in items], [p for _, p in items], direction)
    return {
        'signal_price': res.get('price'),
        'price_vs_sma200': res.get('price_vs_sma200_txt'),
        'sma200': res.get('sma200'),
        'macd_state': res.get('macd_state'),
        'rsi': res.get('rsi'),
        'tech_status': res.get('status'),
        'tech_reason': res.get('reason'),
        'tech_warning': res.get('warning'),
    }


def snapshot_fundamental(ticker):
    """Фундаментальный снимок из кэша метрик (без сети) или (None, None)."""
    try:
        conn = sqlite3.connect(company_data.DB_PATH)
        row = conn.execute(
            "SELECT sector, net_margin, net_margin_yoy, forward_pe, "
            "eps_growth, revenue_growth, roic, debt_equity, earnings_date, "
            "fetched_at FROM company_metrics WHERE ticker=?",
            (ticker,)).fetchone()
        conn.close()
    except Exception:  # pragma: no cover - best-effort
        return None, None
    if not row:
        return None, None
    keys = ['sector', 'net_margin', 'net_margin_yoy', 'forward_pe',
            'eps_growth', 'revenue_growth', 'roic', 'debt_equity',
            'earnings_date']
    fund = {k: v for k, v in zip(keys, row)}
    fund['source'] = 'company_data cache'
    return fund, row[-1]


# ---------------------------------------------------------------------------
# Даты и цена исхода (best-effort из кэша цен)
# ---------------------------------------------------------------------------

def _norm_date(s):
    """'DD/MM/YYYY HH:MM' | 'YYYY-MM-DD' -> 'YYYY-MM-DD' (или None)."""
    if not s:
        return None
    s = str(s).strip()
    if '-' in s and len(s) >= 10 and s[4] == '-':
        return s[:10]
    try:
        return datetime.datetime.strptime(s[:10], '%d/%m/%Y').date().isoformat()
    except ValueError:
        return None


def _as_date(s):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _close_price(ticker, close_ymd):
    """Последняя кэшированная цена на дату закрытия (или последняя вообще)."""
    series = price_history.load_series(ticker)
    if not series:
        return None
    items = sorted(series.items())
    for d, p in reversed(items):
        if close_ymd and d <= close_ymd:
            return p
    return items[-1][1]


def _max_adverse_pct(ticker, open_ymd, close_ymd, entry, direction):
    """Макс. движение ПРОТИВ позиции в % от entry за период (>= 0)."""
    if not entry or entry <= 0:
        return None
    series = price_history.load_series(ticker)
    if not series:
        return None
    worst = 0.0
    for d, p in sorted(series.items()):
        if open_ymd and d < open_ymd:
            continue
        if close_ymd and d > close_ymd:
            break
        if direction == 'short':
            adv = (p - entry) / entry
        else:
            adv = (entry - p) / entry
        worst = max(worst, adv)
    return worst * 100.0


# ---------------------------------------------------------------------------
# Запись идеи (append-only)
# ---------------------------------------------------------------------------

def _deal_attrs(deal):
    ticker = (getattr(deal, 'ticker', '') or '').strip().upper()
    direction = ('short' if str(getattr(deal, 'direction', 'LONG')).upper()
                 == 'SHORT' else 'long')
    entry = getattr(deal, 'init_price', None) or getattr(deal, 'stock_price',
                                                         None) or 0.0
    entry_date = _norm_date(getattr(deal, 'open_date', '') or '')
    return ticker, direction, float(entry or 0.0), entry_date


def log_idea_from_deal(deal):
    """Записать/обновить открытую идею по сделке. Возвращает id или None.

    Ключ записи — (ticker, entry_date, entry_price, direction). Повторное
    логирование той же идеи обновляет снимки, НЕ создаёт дубликат.
    """
    ticker, direction, entry, entry_date = _deal_attrs(deal)
    if not ticker or not entry_date:
        return None
    tech = snapshot_technical(ticker, direction)
    fund, fetched_at = snapshot_fundamental(ticker)
    sector = (fund or {}).get('sector')
    source = 'company_data cache' if fund else None
    now = datetime.datetime.now().isoformat(timespec='seconds')

    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT id FROM ideas WHERE ticker=? AND entry_date=? AND "
            "entry_price=? AND direction=? AND outcome='open'",
            (ticker, entry_date, entry, direction)).fetchone()
        if cur:
            idea_id = cur[0]
            conn.execute(
                "UPDATE ideas SET signal_price=?, price_vs_sma200=?, "
                "sma200=?, macd_state=?, rsi=?, tech_status=?, "
                "tech_reason=?, tech_warning=?, "
                "fundamental=COALESCE(fundamental,?), "
                "sector=COALESCE(sector,?), source=COALESCE(source,?), "
                "source_date=COALESCE(source_date,?), notes=COALESCE(notes,'') "
                "WHERE id=?", (
                    tech['signal_price'], tech['price_vs_sma200'],
                    tech['sma200'], tech['macd_state'], tech['rsi'],
                    tech['tech_status'], tech['tech_reason'],
                    tech['tech_warning'],
                    json.dumps(fund, ensure_ascii=False) if fund else None,
                    sector, source, fetched_at, idea_id))
        else:
            cur = conn.execute(
                "INSERT INTO ideas (ticker, sector, direction, entry_date, "
                "entry_price, fundamental, source, source_date, signal_price, "
                "price_vs_sma200, sma200, macd_state, rsi, tech_status, "
                "tech_reason, tech_warning, outcome, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?)", (
                    ticker, sector, direction, entry_date, entry,
                    json.dumps(fund, ensure_ascii=False) if fund else None,
                    source, fetched_at, tech['signal_price'],
                    tech['price_vs_sma200'], tech['sma200'], tech['macd_state'],
                    tech['rsi'], tech['tech_status'], tech['tech_reason'],
                    tech['tech_warning'], now))
            idea_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return idea_id


def close_idea_from_deal(deal):
    """Зафиксировать исход по сделке. Возвращает id или None (не найдено)."""
    ticker, direction, entry, entry_date = _deal_attrs(deal)
    if not ticker or not entry_date:
        return None
    close_date = _norm_date(getattr(deal, 'close_date', '') or '')
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id FROM ideas WHERE ticker=? AND entry_date=? AND "
            "entry_price=? AND direction=? AND outcome='open'",
            (ticker, entry_date, entry, direction)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    idea_id = row[0]

    days = None
    d0 = _as_date(entry_date)
    d1 = _as_date(close_date)
    if d0 and d1:
        days = max((d1 - d0).days, 0)
    final = _close_price(ticker, close_date)
    pnl = None
    if final and entry > 0:
        pnl = ((final - entry) / entry * 100.0) if direction == 'long' \
            else ((entry - final) / entry * 100.0)
    adverse = _max_adverse_pct(ticker, entry_date, close_date, entry, direction)

    conn = _conn()
    try:
        conn.execute(
            "UPDATE ideas SET outcome='closed', close_date=?, "
            "days_to_outcome=?, max_adverse_move_pct=?, final_pnl_pct=?, "
            "closed_at=? WHERE id=?", (
                close_date, days, adverse, pnl,
                datetime.datetime.now().isoformat(timespec='seconds'),
                idea_id))
        conn.commit()
    finally:
        conn.close()
    return idea_id


# ---------------------------------------------------------------------------
# Аннотации и экспорт
# ---------------------------------------------------------------------------

def annotate_idea(idea_id, probability=None, main_risk=None, source=None,
                  source_date=None, horizon_days=None, notes=None):
    """Дозаполнить контекст идеи (вероятность/риск/источник) без потери."""
    sets, vals = [], []
    for col, val in (('probability', probability), ('main_risk', main_risk),
                     ('source', source), ('source_date', source_date),
                     ('horizon_days', horizon_days), ('notes', notes)):
        if val is not None:
            sets.append('{} = ?'.format(col))
            vals.append(val)
    if not sets:
        return False
    conn = _conn()
    try:
        conn.execute("UPDATE ideas SET {} WHERE id=?".format(', '.join(sets)),
                     vals + [idea_id])
        conn.commit()
    finally:
        conn.close()
    return True


def annotate_idea_by_ticker(ticker, probability=None, main_risk=None,
                            source=None, notes=None):
    """Аннотировать все открытые идеи тикера (из отчёта/исследования)."""
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return 0
    rows = all_ideas(open_only=True)
    n = 0
    for r in rows:
        if r['ticker'] == ticker:
            annotate_idea(r['id'], probability=probability,
                          main_risk=main_risk, source=source, notes=notes)
            n += 1
    return n


def all_ideas(open_only=False):
    """Все записи списком словарей (для экспорта/будущей аналитики)."""
    conn = _conn()
    try:
        sql = ("SELECT id, ticker, sector, direction, horizon_days, "
               "entry_date, entry_price, fundamental, source, source_date, "
               "probability, main_risk, signal_price, price_vs_sma200, sma200, "
               "macd_state, rsi, tech_status, tech_reason, tech_warning, "
               "outcome, close_date, days_to_outcome, max_adverse_move_pct, "
               "final_pnl_pct, notes, created_at, closed_at FROM ideas")
        if open_only:
            sql += " WHERE outcome='open'"
        cols = ['id', 'ticker', 'sector', 'direction', 'horizon_days',
                'entry_date', 'entry_price', 'fundamental', 'source',
                'source_date', 'probability', 'main_risk', 'signal_price',
                'price_vs_sma200', 'sma200', 'macd_state', 'rsi',
                'tech_status', 'tech_reason', 'tech_warning', 'outcome',
                'close_date', 'days_to_outcome', 'max_adverse_move_pct',
                'final_pnl_pct', 'notes', 'created_at', 'closed_at']
        return [dict(zip(cols, r)) for r in conn.execute(sql)]
    finally:
        conn.close()


def export_csv(path):
    """Выгрузить журнал в CSV (шапка фиксирована, повторный вызов — полный сброс)."""
    rows = all_ideas()
    cols = ['id', 'ticker', 'sector', 'direction', 'horizon_days',
            'entry_date', 'entry_price', 'probability', 'main_risk', 'source',
            'source_date', 'signal_price', 'price_vs_sma200', 'sma200',
            'macd_state', 'rsi', 'tech_status', 'outcome', 'close_date',
            'days_to_outcome', 'max_adverse_move_pct', 'final_pnl_pct',
            'notes', 'created_at']
    import csv
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c) for c in cols])


def count():
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM ideas").fetchone()[0]
    finally:
        conn.close()


def open_count():
    conn = _conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM ideas WHERE outcome='open'").fetchone()[0]
    finally:
        conn.close()