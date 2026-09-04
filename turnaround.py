# -*- coding: utf-8 -*-
"""Turnaround vs Value Trap.

Механизм опирается на ДЕЛЬТЫ, а не на уровни (P/E, рост EPS) — в обоих
сценариях низкий forward P/E и высокий ожидаемый рост выглядят одинаково.
Различают:
  1) ревизии ожиданий — исторические сюрпризы «факт vs прогноз» за последние
     4 квартала (Yahoo earningsHistory): отчёты подтверждают восстановление или нет;
  2) операционный тренд — выручка и маржинальность улучшаются/ухудшаются.
Дешевизна по forward P/E — не диагноз, а контекст estimate-риска.

Чистая математика (без Qt): вход — ranked-строка компании из company_quant.
"""
import datetime

_SURP_UP = 2.0        # средний сюрприз > +2% и последний > 0 → ожидания растут
_SURP_DOWN = -2.0     # средний < −2% → ожидания падают
_REV_UP = 3.0         # рост выручки > 3% (и маржа > 0 п.п.) → тренд вверх
_REV_DOWN = -3.0
_MARGIN_DOWN = -1.5

_VERDICT = {
    'turnaround': '↗ Turnaround: восстановление прибыли подтверждается',
    'turnaround_pending': '↗ Turnaround (предварительно): ожидания растут, '
                          'операционного подтверждения ещё нет',
    'value_trap': '⚠ Value Trap: риск, что восстановление не произойдёт',
    'neutral': 'Динамика неопределённая',
}
_LABEL = {
    'turnaround': 'Turnaround',
    'turnaround_pending': 'Turnaround (предварительно)',
    'value_trap': 'Value Trap',
    'neutral': 'Нейтрально',
}
_COLOR = {
    'turnaround': '#81c784',
    'turnaround_pending': '#f0c14b',
    'value_trap': '#ef5350',
    'neutral': '#9aa0aa',
}
_OP_RU = {'improving': 'Улучшается', 'stable': 'Стабильный',
          'deteriorating': 'Ухудшается'}
_REV_RU = {'up': 'растут', 'flat': 'стабильны', 'down': 'снижаются'}


def _revision(surprise_avg, surprise_last):
    if surprise_avg is None or surprise_last is None:
        return None
    if surprise_avg > _SURP_UP and surprise_last > 0:
        return 'up'
    if surprise_avg < _SURP_DOWN or (surprise_avg < 0 and surprise_last < 0):
        return 'down'
    return 'flat'


def _op_trend(revenue_growth, margin_yoy):
    if revenue_growth is None or margin_yoy is None:
        return None
    if revenue_growth > _REV_UP and margin_yoy > 0:
        return 'improving'
    if revenue_growth < _REV_DOWN or margin_yoy < _MARGIN_DOWN:
        return 'deteriorating'
    return 'stable'


def _earnings_days(earnings_date):
    if not earnings_date:
        return None
    try:
        d = datetime.date.fromisoformat(earnings_date)
    except ValueError:
        return None
    return (d - datetime.date.today()).days


def _fmt_pct(v):
    if v is None:
        return '-'
    return '{:+.1f}%'.format(v)


def classify_dynamics(e):
    """Классификация Turnaround / Value Trap по ranked-строке компании."""
    surprise_avg = e.get('surprise_avg')
    surprise_last = e.get('surprise_last')
    revg = e.get('revenue_growth')
    margin_yoy = e.get('net_margin_yoy')
    feg = e.get('eps_growth')
    tp = e.get('trailing_pe')
    fp = e.get('forward_pe')
    sfp = e.get('sector_median_pe')
    pct_pe = e.get('pct_pe')
    ed = e.get('earnings_date')

    rev = _revision(surprise_avg, surprise_last)
    op = _op_trend(revg, margin_yoy)
    cheap = None
    if fp is not None and sfp is not None:
        cheap = fp < sfp
    elif pct_pe is not None:
        cheap = pct_pe < 50

    if rev is None:
        # Нет данных о сюрпризах (Yahoo недоступен) — только операционный тренд.
        if op == 'deteriorating' and cheap:
            cat = 'value_trap'
        elif op == 'improving' and (feg is None or feg > 0):
            cat = 'turnaround_pending'
        else:
            cat = 'neutral'
    elif rev == 'up' and op in ('improving', 'stable') \
            and (feg is None or feg > 0):
        cat = 'turnaround'
    elif rev == 'up' and op == 'deteriorating':
        cat = 'turnaround_pending'
    elif rev == 'down':
        cat = 'value_trap'
    elif op == 'deteriorating' and rev == 'flat' and cheap:
        cat = 'value_trap'
    else:
        cat = 'neutral'

    verdict = _VERDICT[cat]
    if rev is None and cat == 'turnaround_pending':
        verdict = ('↗ Turnaround (предварительно): операционные метрики '
                   'улучшаются')
    rev_note = '' if rev is not None else \
        ('Данные о сюрпризах по отчётам пока недоступны — сигнал ревизий '
         'не учитывается.')
    days = _earnings_days(ed)

    # -------- карточка показателей (Показатель | Значение | Что это значит)
    rows = [
        ('P/E сейчас', '{:.1f}×'.format(tp) if tp is not None else '-',
         'По текущей прибыли акция выглядит дорогой/недорогой.'),
        ('P/E на год вперёд',
         '{:.1f}×'.format(fp) if fp is not None else '-',
         'По ожидаемой прибыли — что закладывает рынок.'),
        ('Ожидаемый EPS Growth', _fmt_pct(feg),
         'Прибыль должна вырасти/упасть по консенсусу аналитиков.'),
        ('Forward P/E peers', '{:.1f}×'.format(sfp) if sfp is not None else '-',
         'Сравнение с похожими компаниями сектора.'),
        ('Сюрпризы 4 кварталов', _fmt_pct(surprise_avg) if surprise_avg
         is not None else '-',
         'Отчёты перекрывают прогнозы (ревизии вверх) или нет (вниз).'),
        ('Revenue/margin тренд',
         _OP_RU.get(op, '-') if op is not None else '-',
         'Операционные факты подтверждают сценарий или опровергают.'),
    ]

    # -------- риск и что нужно для подтверждения
    if cat == 'turnaround':
        risk = ('Риск: восстановление ещё не доказано несколькими '
                'отчётными периодами.')
        confirm = ('Подтверждение: ещё один отчёт с перекрытием прогноза.')
    elif cat == 'turnaround_pending':
        risk = ('Ожидания растут, но выручка/маржа пока не подтверждают '
                'разворот.')
        confirm = ('Нужно: стабилизация выручки и маржи, позитивный guidance.')
    elif cat == 'value_trap':
        risk = ('Низкая оценка может отражать риск, что ожидаемое '
                'восстановление не произойдёт. Даже при низком forward P/E '
                'снижение EPS-прогноза поднимет мультипликатор без изменения '
                'цены — это estimate risk.')
        confirm = ('Для подтверждения: стабилизация выручки, маржи или '
                   'guidance.')
    else:
        risk = 'Нет выраженного сигнала — требуются дополнительные проверки.'
        confirm = 'Смотрите следующий квартальный отчёт и ревизии оценок.'

    # -------- короткая строка для панели
    summary = verdict
    if feg is not None and surprise_avg is not None:
        summary += ' · рост {:.0f}% · сюрпризы {:+.0f}%'.format(
            feg, surprise_avg)
    elif feg is not None:
        summary += ' · рост {:.0f}%'.format(feg)

    return {'category': cat, 'verdict': verdict, 'label': _LABEL[cat],
            'color': _COLOR[cat],
            'revision': rev, 'op': op, 'cheap': cheap,
            'rows': rows, 'risk': risk, 'confirm': confirm,
            'summary': summary, 'earnings_days': days, 'rev_note': rev_note,
            'revision_txt': _REV_RU.get(rev, '-')}