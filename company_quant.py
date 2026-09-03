# -*- coding: utf-8 -*-
"""Company-level screener inside a sector (этап 3 Quantitative Assessment).

Детерминированный ranking компаний одного сектора. Без LLM, без внешних
data providers, без прогнозов доходности. Только нейтральные labels.

Вход — CompanyQuantInput (dict):
  ticker, companyName, sector, netMarginPct?, netMarginYoyChangePp?,
  return1mPct?, return1yPct?, benchmarkReturn1mPct?, benchmarkReturn1yPct?.

Для ranking обязательны ticker, companyName, sector, netMarginPct, return1mPct,
return1yPct, benchmarkReturn1mPct, benchmarkReturn1yPct. Отсутствующие значения
не заменяются нулями — компания помечается `insufficient_data`.

Расчёт (внутри сектора):
  relativeProfitability = tanh((netMarginPct - avgNetMarginSector) / 10)
  relativeMomentum1mPct = return1mPct - benchmarkReturn1mPct
  relativeMomentum1yPct = return1yPct - benchmarkReturn1yPct
  momentum = tanh((relativeMomentum1mPct + relativeMomentum1yPct) / 100)
  marginTrend = tanh(netMarginYoyChangePp / 5)   # если поле есть, иначе null
  valuation  = -tanh(relForwardPE / 40)          # если forwardPE есть
  companyScore = (5·rp + 3·momentum + 2·marginTrend + 2·valuation) /
                 (сумма доступных весов)
                 # без valuation и trend совпадает с исходной формулой
"""
import math

REQUIRED_FIELDS = (
    'ticker', 'companyName', 'sector', 'netMarginPct',
    'return1mPct', 'return1yPct', 'benchmarkReturn1mPct', 'benchmarkReturn1yPct',
)
_STRING_FIELDS = ('ticker', 'companyName', 'sector')
_NUMERIC_FIELDS = ('netMarginPct', 'return1mPct', 'return1yPct',
                   'benchmarkReturn1mPct', 'benchmarkReturn1yPct')

LABEL_RESEARCH_PRIORITY = 'research_priority'
LABEL_WATCHLIST = 'watchlist'
LABEL_LOW_PRIORITY = 'low_priority'
LABEL_INSUFFICIENT = 'insufficient_data'

# Веса компонент score (нормализуются по доступным компонентам).
W_RP = 5
W_MOM = 3
W_TREND = 2
W_VAL = 2

SCORE_RESEARCH = 0.35
SCORE_LOW = -0.20
SCALE_VAL = 40.0


def _finite(v):
    return isinstance(v, (int, float)) and v == v and not math.isinf(v)


def _label(score):
    if score is None:
        return LABEL_INSUFFICIENT
    if score >= SCORE_RESEARCH:
        return LABEL_RESEARCH_PRIORITY
    if score > SCORE_LOW:
        return LABEL_WATCHLIST
    return LABEL_LOW_PRIORITY


def _percentile(v, values):
    """Процентиль значения v среди выборки (0..100), None при отсутствии."""
    present = [x for x in values if x is not None]
    if v is None or not present:
        return None
    less = sum(1 for x in present if x < v)
    eq = sum(1 for x in present if x == v)
    return (less + 0.5 * eq) / len(present) * 100.0


def _flags(e):
    """Авто-предупреждения из связей метрик (простым языком, без отчётов)."""
    out = []
    yoy = e.get('net_margin_yoy')
    if yoy is not None and yoy < -1:
        out.append('Маржинальность падает за год (YoY {:+.1f} п.п.)'.format(yoy))
    pct_pe = e.get('pct_pe')
    if pct_pe is not None and pct_pe > 70:
        out.append('Оценка выше большинства компаний сектора '
                   '(Forward P/E {:.1f}×)'.format(e.get('forward_pe')))
    if (yoy is not None and yoy > 0
            and e.get('rel_momentum_1m') is not None
            and e['rel_momentum_1m'] < 0):
        out.append('Маржа растёт, но цена за месяц её не поддерживает')
    if e.get('rel_momentum_1y') is not None and e['rel_momentum_1y'] < -20:
        out.append('Слабая динамика цены за год '
                   '(Rel Momentum 1Y {:+.1f} п.п.)'.format(e['rel_momentum_1y']))
    if (pct_pe is not None and pct_pe > 60
            and e.get('rel_momentum_1y') is not None
            and e['rel_momentum_1y'] < 0):
        out.append('Дорогой и слабый: высокая оценка при отрицательном momentum')
    return out


def _contribs(e):
    """Вклад каждой компоненты в score (веса нормализованы)."""
    parts = [('Рентабельность', W_RP, e.get('relative_profitability')),
             ('Momentum', W_MOM, e.get('momentum'))]
    if e.get('margin_trend') is not None:
        parts.append(('Тренд маржи', W_TREND, e['margin_trend']))
    if e.get('valuation') is not None:
        parts.append(('Оценка', W_VAL, e['valuation']))
    used = sum(w for _n, w, _v in parts)
    if not used:
        return []
    return [(n, (w / used) * v) for n, w, v in parts if v is not None]


def rank_companies(companies):
    """Rank companies within each sector.

    `companies` — list of CompanyQuantInput dicts (possibly mixed sectors).
    Returns result dicts, each sector ranked separately by companyScore desc
    (insufficient_data last, no score).
    """
    by_sector = {}
    for c in companies:
        by_sector.setdefault(c.get('sector'), []).append(c)
    results = []
    for sector in by_sector:
        results.extend(_rank_sector(sector, by_sector[sector]))
    return results


def _evaluate(c):
    e = {
        'ticker': c.get('ticker'), 'company': c.get('companyName'),
        'sector': c.get('sector'),
        'net_margin': c.get('netMarginPct'),
        'net_margin_yoy': c.get('netMarginYoyChangePp'),
        'forward_pe': c.get('forwardPE'),
        'eps_growth': c.get('forwardEPSGrowth'),
        'return_1m': c.get('return1mPct'), 'return_1y': c.get('return1yPct'),
        'benchmark_1m': c.get('benchmarkReturn1mPct'),
        'benchmark_1y': c.get('benchmarkReturn1yPct'),
        'warnings': [], 'label': LABEL_INSUFFICIENT,
        'relative_profitability': None, 'momentum': None, 'margin_trend': None,
        'valuation': None, 'sector_median_pe': None,
        'company_score': None, 'score_rounded': None, 'rank': None,
    }
    missing = [f for f in REQUIRED_FIELDS
           if c.get(f) is None or (f in _STRING_FIELDS and c.get(f) == '')]
    if missing:
        e['warnings'].append('missing_required_fields:' + ','.join(missing))
        return e
    if not all(_finite(c[f]) for f in _NUMERIC_FIELDS):
        e['warnings'].append('non_finite_required_fields')
        return e
    if c.get('netMarginYoyChangePp') is None:
        e['warnings'].append('missing_net_margin_yoy_change')
    elif not _finite(c['netMarginYoyChangePp']):
        e['warnings'].append('non_finite_net_margin_yoy_change')
        e['net_margin_yoy'] = None
    if e['forward_pe'] is not None and not _finite(e['forward_pe']):
        e['warnings'].append('non_finite_forward_pe')
        e['forward_pe'] = None
    e['_rankable'] = True
    return e


def _rank_sector(sector, companies):
    entries = [_evaluate(c) for c in companies]
    rankable = [e for e in entries if e.get('_rankable')]
    margins = [e['net_margin'] for e in rankable]
    avg = sum(margins) / len(margins) if margins else 0.0
    median = sorted(margins)[len(margins) // 2] if margins else None
    pes = [e['forward_pe'] for e in rankable if e['forward_pe']]
    median_pe = sorted(pes)[len(pes) // 2] if pes else None
    epsg = [e['eps_growth'] for e in rankable if e['eps_growth'] is not None]
    median_epsg = sorted(epsg)[len(epsg) // 2] if epsg else None
    for e in rankable:
        e['sector_median_margin'] = median
        e['sector_median_pe'] = median_pe
        e['sector_median_eps_growth'] = median_epsg
        rp = math.tanh((e['net_margin'] - avg) / 10.0)
        rel1m = e['return_1m'] - e['benchmark_1m']
        rel1y = e['return_1y'] - e['benchmark_1y']
        momentum = math.tanh((rel1m + rel1y) / 100.0)
        trend = math.tanh(e['net_margin_yoy'] / 5.0) \
            if e['net_margin_yoy'] is not None else None
        valuation = None
        if e['forward_pe'] is not None and median_pe:
            rel_pe = (e['forward_pe'] - median_pe) / median_pe
            valuation = -math.tanh(rel_pe / SCALE_VAL)
        parts = [(W_RP, rp), (W_MOM, momentum)]
        if trend is not None:
            parts.append((W_TREND, trend))
        if valuation is not None:
            parts.append((W_VAL, valuation))
        used = sum(w for w, _ in parts)
        score = sum(w * c for w, c in parts) / used if used else None
        e['relative_profitability'] = rp
        e['rel_momentum_1m'] = rel1m
        e['rel_momentum_1y'] = rel1y
        e['momentum'] = momentum
        e['margin_trend'] = trend
        e['valuation'] = valuation
        e['company_score'] = score
        e['score_rounded'] = round(score, 2) if score is not None else None
        e['label'] = _label(score)
    margin_vals = [e['net_margin'] for e in rankable]
    pe_vals = [e['forward_pe'] for e in rankable]
    mom1m_vals = [e['rel_momentum_1m'] for e in rankable]
    mom1y_vals = [e['rel_momentum_1y'] for e in rankable]
    for e in rankable:
        e['pct_margin'] = _percentile(e['net_margin'], margin_vals)
        e['pct_pe'] = _percentile(e['forward_pe'], pe_vals)
        e['pct_mom_1m'] = _percentile(e['rel_momentum_1m'], mom1m_vals)
        e['pct_mom_1y'] = _percentile(e['rel_momentum_1y'], mom1y_vals)
        e['flags'] = _flags(e)
        e['contribs'] = _contribs(e)
    ranked = sorted([e for e in rankable if e['company_score'] is not None],
                    key=lambda e: e['company_score'], reverse=True)
    for i, e in enumerate(ranked, start=1):
        e['rank'] = i
    entries.sort(key=lambda e: (e['rank'] is None, e['rank']))
    return entries