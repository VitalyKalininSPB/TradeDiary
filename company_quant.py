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
    for e in rankable:
        e['sector_median_margin'] = median
        e['sector_median_pe'] = median_pe
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
    ranked = sorted([e for e in rankable if e['company_score'] is not None],
                    key=lambda e: e['company_score'], reverse=True)
    for i, e in enumerate(ranked, start=1):
        e['rank'] = i
    entries.sort(key=lambda e: (e['rank'] is None, e['rank']))
    return entries