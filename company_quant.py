# -*- coding: utf-8 -*-
"""Company-level screener inside a sector (этап 3 Quantitative Assessment).

Детерминированный ranking компаний одного сектора. Без LLM, без внешних
data providers, без прогнозов доходности. Только нейтральные labels.

Вход — CompanyQuantInput (dict):
  ticker, companyName, sector, netMarginPct?, netMarginYoyChangePp?,
  return1mPct?, return1yPct?, benchmarkReturn1mPct?, benchmarkReturn1yPct?,
  forwardPE?, forwardEPSGrowth?, revenueGrowthPct?, roicPct?, debtEquity?.

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
  peg        = forwardPE / forwardEPSGrowth      # только при eps growth > 0
  growthAdjValuation = -tanh(relPEG / 0.5)       # если peg есть
  revenueGrowth = tanh(relRevenueGrowth / 15)    # если revenueGrowthPct есть
  capitalEfficiency = tanh(relROIC / 10)        # если roicPct есть
  companyScore = (5·rp + 3·momentum + 2·marginTrend + 2·valuation
                  + 2·growthAdjValuation + 2·revenueGrowth
                  + 2·capitalEfficiency) / (сумма доступных весов)
                 # без опциональных компонент совпадает с исходной
  # debtEquity в score не входит — только флаг/колонка (риск долга).
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
W_PEG = 2
W_REV = 2
W_ROIC = 2

SCORE_RESEARCH = 0.35
SCORE_LOW = -0.20
SCALE_VAL = 40.0
SCALE_PEG = 0.5
SCALE_REV = 15.0
SCALE_ROIC = 10.0

# Финансовый сектор: леверидж — бизнес-модель, Debt/Equity-флаг не показываем.
_DEBT_NOFLAG_SECTORS = {'Financials'}


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
    epsg = e.get('eps_growth')
    if epsg is not None and epsg < 0:
        out.append('EPS growth отрицательный ({:+.1f}%) — PEG неприменим'
                   .format(epsg))
    pct_peg = e.get('pct_peg')
    if pct_peg is not None and pct_peg > 70:
        out.append('Оценка с поправкой на рост выше большинства компаний '
                   'сектора (PEG {:.2f})'.format(e.get('peg')))
    if (pct_pe is not None and pct_pe > 60
            and epsg is not None and epsg < 0):
        out.append('Дорогой без роста: высокая оценка при падающем EPS')
    revg = e.get('revenue_growth')
    if (revg is not None and revg > 0 and yoy is not None and yoy < 0):
        out.append('Выручка растёт ({:+.1f}%), но маржа падает'.format(revg))
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
    pct_debt = e.get('pct_debt')
    if (pct_debt is not None and pct_debt > 70
            and e.get('sector') not in _DEBT_NOFLAG_SECTORS):
        out.append('Долг высокий: Debt/Equity {:.2f} — выше {:.0f}% сектора'
                   .format(e.get('debt_equity'), pct_debt))
    return out


def _contribs(e):
    """Вклад каждой компоненты в score (веса нормализованы)."""
    parts = [('Рентабельность', W_RP, e.get('relative_profitability')),
             ('Momentum', W_MOM, e.get('momentum'))]
    if e.get('margin_trend') is not None:
        parts.append(('Тренд маржи', W_TREND, e['margin_trend']))
    if e.get('valuation') is not None:
        parts.append(('Оценка', W_VAL, e['valuation']))
    if e.get('growth_adj_valuation') is not None:
        parts.append(('Оценка по росту (PEG)', W_PEG, e['growth_adj_valuation']))
    if e.get('rev_growth') is not None:
        parts.append(('Рост выручки', W_REV, e['rev_growth']))
    if e.get('capital_efficiency') is not None:
        parts.append(('Эффективность капитала (ROIC)', W_ROIC,
                      e['capital_efficiency']))
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
        'trailing_pe': c.get('trailingPE'),
        'trailing_eps_growth': c.get('trailingEPSGrowth'),
        'surprise_avg': c.get('surpriseAvg'),
        'surprise_last': c.get('surpriseLast'),
        'surprise_n': c.get('surpriseN'),
        'earnings_date': c.get('earningsDate'),
        'short_float': c.get('shortFloatPct'),
        'short_change': c.get('shortChangePct'),
        'short_ratio': c.get('shortRatio'),
        'short_date': c.get('shortDate'),
        'return_1m': c.get('return1mPct'), 'return_1y': c.get('return1yPct'),
        'benchmark_1m': c.get('benchmarkReturn1mPct'),
        'benchmark_1y': c.get('benchmarkReturn1yPct'),
        'warnings': [], 'label': LABEL_INSUFFICIENT,
        'relative_profitability': None, 'momentum': None, 'margin_trend': None,
        'valuation': None, 'growth_adj_valuation': None, 'rev_growth': None,
        'capital_efficiency': None,
        'sector_median_pe': None, 'sector_median_peg': None, 'peg': None,
        'sector_median_trailing_pe': None,
        'sector_median_trailing_eps_growth': None,
        'sector_median_forward_eps_growth': None,
        'pct_trailing_pe': None, 'pct_trailing_eps_growth': None,
        'revenue_growth': c.get('revenueGrowthPct'),
        'sector_median_rev_growth': None, 'pct_rev_growth': None,
        'roic': c.get('roicPct'), 'debt_equity': c.get('debtEquity'),
        'sector_median_roic': None, 'pct_roic': None,
        'sector_median_debt': None, 'pct_debt': None,
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
    if e['eps_growth'] is not None and not _finite(e['eps_growth']):
        e['warnings'].append('non_finite_eps_growth')
        e['eps_growth'] = None
    if e['trailing_pe'] is not None and not _finite(e['trailing_pe']):
        e['warnings'].append('non_finite_trailing_pe')
        e['trailing_pe'] = None
    if e['trailing_eps_growth'] is not None \
            and not _finite(e['trailing_eps_growth']):
        e['warnings'].append('non_finite_trailing_eps_growth')
        e['trailing_eps_growth'] = None
    if e['revenue_growth'] is not None and not _finite(e['revenue_growth']):
        e['warnings'].append('non_finite_revenue_growth')
        e['revenue_growth'] = None
    if e['roic'] is not None and not _finite(e['roic']):
        e['warnings'].append('non_finite_roic')
        e['roic'] = None
    if e['debt_equity'] is not None and not _finite(e['debt_equity']):
        e['warnings'].append('non_finite_debt_equity')
        e['debt_equity'] = None
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
    tpes = [e['trailing_pe'] for e in rankable if e['trailing_pe']]
    median_tpe = sorted(tpes)[len(tpes) // 2] if tpes else None
    epsg = [e['eps_growth'] for e in rankable if e['eps_growth'] is not None]
    median_epsg = sorted(epsg)[len(epsg) // 2] if epsg else None
    tepsg = [e['trailing_eps_growth'] for e in rankable
             if e['trailing_eps_growth'] is not None]
    median_tepsg = sorted(tepsg)[len(tepsg) // 2] if tepsg else None
    pegs = []
    for e in rankable:
        peg = None
        if e['forward_pe'] is not None and e['eps_growth'] is not None \
                and e['eps_growth'] > 0:
            peg = e['forward_pe'] / e['eps_growth']
        e['peg'] = peg
        if peg is not None:
            pegs.append(peg)
    median_peg = sorted(pegs)[len(pegs) // 2] if pegs else None
    revg = [e['revenue_growth'] for e in rankable
            if e['revenue_growth'] is not None]
    median_revg = sorted(revg)[len(revg) // 2] if revg else None
    roics = [e['roic'] for e in rankable if e['roic'] is not None]
    median_roic = sorted(roics)[len(roics) // 2] if roics else None
    debts = [e['debt_equity'] for e in rankable
             if e['debt_equity'] is not None]
    median_debt = sorted(debts)[len(debts) // 2] if debts else None
    for e in rankable:
        e['sector_median_margin'] = median
        e['sector_median_pe'] = median_pe
        e['sector_median_eps_growth'] = median_epsg
        e['sector_median_forward_eps_growth'] = median_epsg
        e['sector_median_trailing_pe'] = median_tpe
        e['sector_median_trailing_eps_growth'] = median_tepsg
        e['sector_median_peg'] = median_peg
        e['sector_median_rev_growth'] = median_revg
        e['sector_median_roic'] = median_roic
        e['sector_median_debt'] = median_debt
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
        growth_val = None
        if e['peg'] is not None and median_peg:
            rel_peg = (e['peg'] - median_peg) / median_peg
            growth_val = -math.tanh(rel_peg / SCALE_PEG)
        rev_growth = None
        if e['revenue_growth'] is not None and median_revg is not None:
            rev_growth = math.tanh(
                (e['revenue_growth'] - median_revg) / SCALE_REV)
        capital_eff = None
        if e['roic'] is not None and median_roic is not None:
            capital_eff = math.tanh((e['roic'] - median_roic) / SCALE_ROIC)
        parts = [(W_RP, rp), (W_MOM, momentum)]
        if trend is not None:
            parts.append((W_TREND, trend))
        if valuation is not None:
            parts.append((W_VAL, valuation))
        if growth_val is not None:
            parts.append((W_PEG, growth_val))
        if rev_growth is not None:
            parts.append((W_REV, rev_growth))
        if capital_eff is not None:
            parts.append((W_ROIC, capital_eff))
        used = sum(w for w, _ in parts)
        score = sum(w * c for w, c in parts) / used if used else None
        e['relative_profitability'] = rp
        e['rel_momentum_1m'] = rel1m
        e['rel_momentum_1y'] = rel1y
        e['momentum'] = momentum
        e['margin_trend'] = trend
        e['valuation'] = valuation
        e['growth_adj_valuation'] = growth_val
        e['rev_growth'] = rev_growth
        e['capital_efficiency'] = capital_eff
        e['company_score'] = score
        e['score_rounded'] = round(score, 2) if score is not None else None
        e['label'] = _label(score)
    margin_vals = [e['net_margin'] for e in rankable]
    pe_vals = [e['forward_pe'] for e in rankable]
    tpe_vals = [e['trailing_pe'] for e in rankable]
    tepsg_vals = [e['trailing_eps_growth'] for e in rankable]
    mom1m_vals = [e['rel_momentum_1m'] for e in rankable]
    mom1y_vals = [e['rel_momentum_1y'] for e in rankable]
    for e in rankable:
        e['pct_margin'] = _percentile(e['net_margin'], margin_vals)
        e['pct_pe'] = _percentile(e['forward_pe'], pe_vals)
        e['pct_trailing_pe'] = _percentile(e['trailing_pe'], tpe_vals)
        e['pct_trailing_eps_growth'] = _percentile(
            e['trailing_eps_growth'], tepsg_vals)
        e['pct_peg'] = _percentile(e['peg'], pegs)
        e['pct_rev_growth'] = _percentile(e['revenue_growth'], revg)
        e['pct_roic'] = _percentile(e['roic'], roics)
        e['pct_debt'] = _percentile(e['debt_equity'], debts)
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