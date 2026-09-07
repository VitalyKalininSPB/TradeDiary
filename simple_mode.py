# -*- coding: utf-8 -*-
"""Simple Mode — краткая карточка тикера (без Qt).

Вердикт отвечает на три вопроса:
  1) есть ли преимущество относительно peers;
  2) насколько надёжны данные;
  3) что делать дальше.

Это ЭВРИСТИКИ v1, а не «истинная стоимость»: пороги конфигурируются
константами ниже. Карточка строит выводы ТОЛЬКО по полям, реально
присутствующим в строке e: полный score/ранг из rank_companies не
имитируется (для ручного анализа тикера его просто нет в строке).

Пороги (согласованы):
  rel_eps >= +5 п.п.            — относительное преимущество EPS-прогноза;
  rel_eps <= -5 п.п.            — явный минус vs peers (Skip);
  дороговизна = pct_pe > 70 ИЛИ forward_pe >= 1.30 * медианы сектора (OR);
  дешевизна  = pct_pe < 30 ИЛИ forward_pe <= 0.77 * медианы сектора (OR).
Дешевизна сама по себе НЕ повышает вердикт (защита от value trap).
Candidate требует подтверждающий слой (сюрпризы/маржа/ревизии) — иначе
Watchlist, как для CRC: сильный rel_eps, но 0 подтверждающих слоёв.
"""
import datetime

# Пороги-эвристики вердикта.
_REL_FROM = 5.0          # п.п. — порог относительного преимущества EPS-прогноза
_EXPENSIVE_PCT = 70.0    # pct_pe выше → «заметно дороже большинства peers»
_CHEAP_PCT = 30.0        # pct_pe ниже → «заметно дешевле большинства peers»
_EXPENSIVE_MULT = 1.30   # forward_pe >= множитель × медианы сектора → дорого
_CHEAP_MULT = 0.77      # forward_pe <= множитель × медианы сектора → дёшево

_VERDICT_RU = {
    'candidate': 'Candidate — понятное относительное преимущество',
    'watchlist': 'Watchlist — нейтрально',
    'skip': 'Skip — без преимущества',
    'no_data': 'Нет данных',
}
_VERDICT_COLOR = {
    'candidate': '#81c784',
    'watchlist': '#f0c14b',
    'skip': '#ef5350',
    'no_data': '#9aa0aa',
}
_ACTION = {
    'candidate': 'Действие: искать точку входа — технический сетап или '
                 'подтверждённый катализатор; проверить риски.',
    'watchlist': 'Действие: Watchlist. Открыть Details при техническом '
                 'сетапе или после нового отчётного/количественного '
                 'подтверждения.',
    'skip': 'Действие: преимущества нет или есть критический красный флаг — '
            'не открывать позицию.',
    'no_data': 'Действие: метрик недостаточно — повторить анализ после '
               'появления данных.',
}


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _rel(src, dst):
    if src is None or dst is None:
        return None
    try:
        return float(src) - float(dst)
    except (TypeError, ValueError):
        return None


def _fdate(s):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s))
    except ValueError:
        return None


def _fmt_pct(v):
    return '{:+.1f}%'.format(v) if v is not None else None


def _fmt_pe(v):
    return '{:.1f}×'.format(v) if v is not None else None


def _fmt_date(d):
    return d.strftime('%d %b %Y')


def _plural(n, one, few, many):
    n = abs(n) % 100
    n1 = n % 10
    if 10 < n < 20:
        return many
    if 1 < n1 < 5:
        return few
    if n1 == 1:
        return one
    return many


def build_simple_card(e, catalyst=None):
    """Сокращённая карточка тикера. Вход — ranked-строка (полная ИЛИ
    сокращённый row из ручного анализа): используются только реальные поля.
    `catalyst` — результат catalyst.summary_for(ticker) или None."""
    feg = _num(e.get('eps_growth'))
    sfeg = _num(e.get('sector_median_eps_growth'))
    fp = _num(e.get('forward_pe'))
    sfp = _num(e.get('sector_median_pe'))
    tp = _num(e.get('trailing_pe'))
    sa = _num(e.get('surprise_avg'))
    yoy = _num(e.get('net_margin_yoy'))
    pct_pe = _num(e.get('pct_pe'))
    ed = _fdate(e.get('earnings_date'))

    rel = _rel(feg, sfeg)
    positive_eps = rel is not None and rel >= _REL_FROM
    negative_eps = rel is not None and rel <= -_REL_FROM

    expensive = (
        (pct_pe is not None and pct_pe > _EXPENSIVE_PCT)
        or (fp is not None and sfp is not None
            and fp >= _EXPENSIVE_MULT * sfp))
    cheap = (
        (pct_pe is not None and pct_pe < _CHEAP_PCT)
        or (fp is not None and sfp is not None
            and fp <= _CHEAP_MULT * sfp))

    # Подтверждающие слои «качества» истории. Без них относительное
    # преимущество по EPS-прогнозу считается недоказанным → Watchlist.
    # Revision (аналитики) сюда не входит: он считается из временного ряда
    # analyst estimates и пока не реализован (calculation_unavailable).
    missing = []
    if sa is None:
        missing.append('earnings surprises')
    if yoy is None:
        missing.append('margin trend')
    confirmers = 2 - len(missing)

    # Катализатор: показываем факт из summary_for без «нет катализатора».
    cat = catalyst or {}
    cat_count = cat.get('count') or 0
    if cat_count:
        cat_line = ('Катализатор: {} {}'.format(
            cat_count, _plural(cat_count, 'событие', 'события', 'событий')))
        if cat.get('next'):
            nd = _fdate(cat['next'])
            if nd:
                cat_line += ' · ближайшее: {}'.format(_fmt_date(nd))
    else:
        cat_line = 'Катализатор: не обнаружен системой'

    # Earnings: только честные даты, без выдумок «примерно +90 дней».
    last_line = None
    next_line = 'Следующий отчёт: ожидается по календарю'
    if ed is not None:
        days = (ed - datetime.date.today()).days
        if days >= 0:
            next_line = 'Следующий отчёт: {} · до отчёта: {} дн.'.format(
                _fmt_date(ed), days)
        else:
            last_line = 'Последний отчёт: {} ({} дн. назад)'.format(
                _fmt_date(ed), -days)

    # Вердикт.
    if fp is None and feg is None and sa is None and yoy is None:
        verdict = 'no_data'
    elif negative_eps:
        verdict = 'skip'
    elif expensive and not (positive_eps or cat_count):
        verdict = 'skip'
    elif (positive_eps and confirmers >= 1 and not expensive
          and (pct_pe is not None or (fp is not None and sfp is not None))):
        verdict = 'candidate'
    else:
        verdict = 'watchlist'

    # Ключевые факты (порядок: преимущество, оценка, качество данных).
    facts = []
    if feg is not None and sfeg is not None:
        cmp_txt = 'сильнее' if rel >= 0 else 'слабее'
        facts.append('Прогноз EPS: {} против {} у сектора — {} peers'.format(
            _fmt_pct(feg), _fmt_pct(sfeg), cmp_txt))
    elif feg is not None:
        facts.append('Прогноз EPS: {} (сектор вне базы — сравнения нет)'.format(
            _fmt_pct(feg)))
    else:
        facts.append('Прогноз EPS: нет данных')

    if fp is not None and sfp is not None:
        cmp_txt = 'дороже' if expensive else ('дешевле' if cheap
                                              else 'примерно на уровне')
        facts.append('Оценка: forward P/E {} против {} у сектора — {} peers'
                     .format(_fmt_pe(fp), _fmt_pe(sfp), cmp_txt))
    elif fp is not None:
        facts.append('Оценка: forward P/E {} (сектор вне базы — сравнения '
                     'нет)'.format(_fmt_pe(fp)))
    else:
        facts.append('Оценка: нет данных')

    if confirmers == 2:
        facts.append('Качество данных: полные данные по отчётам '
                     '(сюрпризы, маржа).')
    elif missing:
        joined = ', '.join(missing[:-1])
        if len(missing) > 1:
            joined += ' и ' + missing[-1]
        else:
            joined = missing[-1]
        facts.append('Данные неполные: текущие источники не загрузили '
                     '{}.'.format(joined))
    else:
        facts.append('Качество данных: нет данных по отчётам.')

    sector = e.get('sector') or ''
    sector_line = 'Сектор: {}'.format(sector) if sector else None

    return {
        'verdict': verdict,
        'verdict_ru': _VERDICT_RU[verdict],
        'verdict_color': _VERDICT_COLOR[verdict],
        'title': 'Рекомендация — {}'.format(e.get('ticker') or ''),
        'sector': sector_line,
        'facts': facts,
        'rel_eps': rel,
        'positive_eps': positive_eps,
        'expensive': expensive,
        'cheap': cheap,
        'confirmers': confirmers,
        'catalyst': cat_line,
        'last_earnings': last_line,
        'next_earnings': next_line,
        'action': _ACTION[verdict],
    }