# -*- coding: utf-8 -*-
"""Портфельный контекст для Simple Mode (чистая математика, без Qt).

Простой набор информационных показателей с ясным действием:
  - количество открытых идей (обычный диапазон 5–8);
  - крупнейшая позиция в USD и её доля от equity;
  - концентрация портфеля, сопоставленная с существующими зонами корреляции.

Только текст и статусы: ничего не меняет в сделках и не блокирует. Любые
Advanced-метрики (beta, volatility, VaR, веса, optimizer и т.п.) сюда НЕ
попадают — их нет в выводе этого модуля.
"""
_OPEN_MIN = 5
_OPEN_MAX = 8

_OPEN_NOTE_LOW = ('Portfolio is more concentrated than your usual range '
                  '(fewer than {} open ideas).')
_OPEN_NOTE_HIGH = ('You have more open ideas than your usual range. Check '
                   'that you can follow catalysts, earnings and review dates.')

# Сопоставление существующих зон корреляции (main.py._corrFeedback) с тремя
# статусами: <=0.55 — normal, (0.55..0.70] — elevated, >0.70 — high.
_CORR_ELEVATED = 0.55
_CORR_HIGH = 0.70

_CONCENTRATION_RU = {
    'normal': 'Normal',
    'elevated': 'Elevated',
    'high': 'High',
}
_CONCENTRATION_NOTE = {
    'normal': 'Current positions do not show strong portfolio overlap.',
    'elevated': ('Several positions may move together. Avoid adding another '
                 'similar idea at full size.'),
    'high': ('Your portfolio is strongly concentrated in similar positions or '
             'risk factors. Consider a smaller new position, replacing an '
             'existing idea, or using Watchlist.'),
}


def open_ideas_status(count):
    """Статус количества открытых идей.

    Возвращает (status, note): status в {'normal', 'low', 'review'};
    note — информационная строка (может быть None). Не блокирует никогда.
    """
    if count is None:
        return 'normal', None
    if count < _OPEN_MIN:
        return 'low', _OPEN_NOTE_LOW.format(_OPEN_MIN)
    if count > _OPEN_MAX:
        return 'review', _OPEN_NOTE_HIGH
    return 'normal', None


def concentration_status(corr):
    """Статус концентрации из существующей корреляции портфеля.

    corr <= 0.55 → 'normal'; 0.55 < corr <= 0.70 → 'elevated';
    corr > 0.70 → 'high'. None → 'unknown'.
    """
    if corr is None:
        return 'unknown', None
    if corr > _CORR_HIGH:
        return 'high', _CONCENTRATION_NOTE['high']
    if corr > _CORR_ELEVATED:
        return 'elevated', _CONCENTRATION_NOTE['elevated']
    return 'normal', _CONCENTRATION_NOTE['normal']


def largest_position(usd_by_ticker, total_equity_usd):
    """Крупнейшая позиция: (ticker, value_usd, pct_of_equity) или None."""
    if not usd_by_ticker:
        return None
    ticker = max(usd_by_ticker, key=usd_by_ticker.get)
    value = usd_by_ticker[ticker]
    pct = risk_pct_of_equity(value, total_equity_usd)
    return (ticker, value, pct)


def risk_pct_of_equity(value_usd, total_equity_usd):
    """Доля value_usd в total_equity_usd (%). None при equity <= 0."""
    if not total_equity_usd or total_equity_usd <= 0:
        return None
    return value_usd / total_equity_usd * 100.0


def build_portfolio_context(open_count, usd_by_ticker, total_equity_usd,
                            corr):
    """Собрать контекст портфеля для панели Simple Mode.

    Возвращает dict: open_count/open_status/open_note, largest
    (ticker, value_usd, pct) или None, concentration/status_ru/note.
    Advanced-метрики (beta, volatility, VaR и т.п.) не включаются.
    """
    open_status, open_note = open_ideas_status(open_count)
    conc_status, conc_note = concentration_status(corr)
    return {
        'open_count': open_count,
        'open_status': open_status,
        'open_note': open_note,
        'largest': largest_position(usd_by_ticker, total_equity_usd),
        'concentration': conc_status,
        'concentration_ru': _CONCENTRATION_RU.get(conc_status, '—'),
        'concentration_note': conc_note,
    }