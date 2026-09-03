# -*- coding: utf-8 -*-
"""Статический fixture компаний для company-level screener (этап 3).

Демо-данные CompanyQuantInput по секторам (benchmark returns соответствуют
текущим агрегатам секторов из stockanalysis). В реальном проде источник
должен поставлять живые метрики; формула и labels в company_quant.py.
"""
# (ticker, companyName, netMarginPct, netMarginYoyChangePp,
#  return1mPct, return1yPct, bench1mPct, bench1yPct)
_TECH = [
    ('NVDA', 'NVIDIA Corporation', 50.0, 6.0, 9.0, 190.0, 4.1, 64.4),
    ('MSFT', 'Microsoft Corporation', 36.0, 2.5, 4.0, 45.0, 4.1, 64.4),
    ('ORCL', 'Oracle Corporation', 23.0, 3.0, 12.0, 60.0, 4.1, 64.4),
    ('AAPL', 'Apple Inc.', 26.0, 1.0, 1.0, 30.0, 4.1, 64.4),
    ('ADBE', 'Adobe Inc.', 30.0, 2.0, -3.0, 5.0, 4.1, 64.4),
    ('CRM', 'Salesforce, Inc.', 19.0, 1.5, -2.0, 20.0, 4.1, 64.4),
    ('AMD', 'Advanced Micro Devices', 12.0, -3.0, -4.0, -15.0, 4.1, 64.4),
    ('INTC', 'Intel Corporation', 5.0, -5.0, -6.0, -35.0, 4.1, 64.4),
    ('PLTR', 'Palantir Technologies', None, None, 7.0, None, 4.1, 64.4),
]

_COMM = [
    ('GOOGL', 'Alphabet Inc.', 27.0, 2.0, 5.0, 15.0, -2.5, -4.2),
    ('META', 'Meta Platforms', 31.0, 3.0, 8.0, 40.0, -2.5, -4.2),
    ('NFLX', 'Netflix, Inc.', 18.0, 4.0, 6.0, 25.0, -2.5, -4.2),
    ('DIS', 'Walt Disney Co.', 7.0, -2.0, -4.0, -12.0, -2.5, -4.2),
    ('TMUS', 'T-Mobile US', 14.0, 1.0, 2.0, 10.0, -2.5, -4.2),
]

_FIN = [
    ('JPM', 'JPMorgan Chase', 32.0, 1.5, 3.0, 20.0, -0.5, -10.1),
    ('V', 'Visa Inc.', 48.0, 2.0, 4.0, 12.0, -0.5, -10.1),
    ('GS', 'Goldman Sachs', 25.0, 0.5, 2.0, 25.0, -0.5, -10.1),
    ('BAC', 'Bank of America', 22.0, -1.0, -2.0, 5.0, -0.5, -10.1),
    ('WFC', 'Wells Fargo', 18.0, -2.0, -3.0, -5.0, -0.5, -10.1),
]

_CONSDISCR = [
    ('AMZN', 'Amazon.com, Inc.', 9.0, 2.0, 6.0, 30.0, -2.8, -25.6),
    ('HD', 'Home Depot, Inc.', 13.0, 0.5, 1.0, -5.0, -2.8, -25.6),
    ('MCD', 'McDonald\'s Corp.', 35.0, 1.0, -1.0, -8.0, -2.8, -25.6),
    ('TSLA', 'Tesla, Inc.', 6.0, -4.0, -10.0, -40.0, -2.8, -25.6),
]

_CONSTAPLES = [
    ('PM', 'Philip Morris Intl', 28.0, 2.0, 2.0, 15.0, -4.4, -22.2),
    ('PG', 'Procter & Gamble', 18.0, 1.0, 1.0, 10.0, -4.4, -22.2),
    ('KO', 'Coca-Cola Company', 19.0, 1.0, 0.0, 8.0, -4.4, -22.2),
    ('PEP', 'PepsiCo, Inc.', 14.0, 0.5, -1.0, -5.0, -4.4, -22.2),
    ('WMT', 'Walmart Inc.', 3.0, 0.3, 3.0, 35.0, -4.4, -22.2),
    ('COST', 'Costco Wholesale', 2.5, 0.2, 2.0, 25.0, -4.4, -22.2),
]

_ENERGY = [
    ('EOG', 'EOG Resources', 25.0, 5.0, 4.0, 25.0, 2.0, 14.7),
    ('COP', 'ConocoPhillips', 15.0, 4.0, 5.0, 30.0, 2.0, 14.7),
    ('CVX', 'Chevron Corp.', 12.0, 2.0, 2.0, 15.0, 2.0, 14.7),
    ('XOM', 'Exxon Mobil', 10.0, 3.0, 3.0, 20.0, 2.0, 14.7),
    ('SLB', 'Schlumberger', 12.0, 1.0, 0.0, 5.0, 2.0, 14.7),
    ('OXY', 'Occidental Petroleum', 8.0, -3.0, -2.0, -10.0, 2.0, 14.7),
]

_HEALTH = [
    ('LLY', 'Eli Lilly and Co.', 40.0, 8.0, 6.0, 45.0, 3.7, 20.4),
    ('ABBV', 'AbbVie Inc.', 15.0, 2.0, 5.0, 20.0, 3.7, 20.4),
    ('UNH', 'UnitedHealth Group', 8.0, 1.0, 4.0, 15.0, 3.7, 20.4),
    ('TMO', 'Thermo Fisher', 18.0, 1.0, 3.0, 10.0, 3.7, 20.4),
    ('MRK', 'Merck & Co.', 25.0, -3.0, -2.0, -15.0, 3.7, 20.4),
    ('PFE', 'Pfizer Inc.', 12.0, -6.0, -4.0, -20.0, 3.7, 20.4),
    ('JNJ', 'Johnson & Johnson', 18.0, 1.5, 2.0, -5.0, 3.7, 20.4),
]

_INDUSTRIALS = [
    ('GE', 'GE Aerospace', 12.0, 1.0, 2.0, 25.0, 2.0, -9.4),
    ('CAT', 'Caterpillar Inc.', 16.0, 2.0, 3.0, 20.0, 2.0, -9.4),
    ('HON', 'Honeywell Intl', 15.0, 0.5, 1.0, 5.0, 2.0, -9.4),
    ('DE', 'Deere & Company', 18.0, -1.0, 0.0, -10.0, 2.0, -9.4),
    ('UPS', 'United Parcel Service', 7.0, -2.0, -3.0, -20.0, 2.0, -9.4),
    ('BA', 'Boeing Company', 2.0, -4.0, -5.0, -30.0, 2.0, -9.4),
]

_MATERIALS = [
    ('NEM', 'Newmont Corp.', 10.0, 3.0, 6.0, 30.0, 11.1, 17.2),
    ('FCX', 'Freeport-McMoRan', 8.0, 4.0, 8.0, 40.0, 11.1, 17.2),
    ('APD', 'Air Products', 15.0, 2.0, 5.0, 20.0, 11.1, 17.2),
    ('LIN', 'Linde plc', 18.0, 1.5, 4.0, 15.0, 11.1, 17.2),
    ('SHW', 'Sherwin-Williams', 12.0, 1.0, 3.0, 10.0, 11.1, 17.2),
    ('DOW', 'Dow Inc.', 4.0, -2.0, -1.0, -15.0, 11.1, 17.2),
]

_REALESTATE = [
    ('SPG', 'Simon Property', 35.0, 0.8, -7.0, -30.0, -5.9, -20.0),
    ('O', 'Realty Income', 30.0, 0.0, -6.0, -25.0, -5.9, -20.0),
    ('PLD', 'Prologis Inc.', 28.0, 1.0, -2.0, -10.0, -5.9, -20.0),
    ('AMT', 'American Tower', 25.0, 1.5, -1.0, -5.0, -5.9, -20.0),
    ('WELL', 'Welltower Inc.', 22.0, 0.5, -3.0, -12.0, -5.9, -20.0),
    ('EQIX', 'Equinix Inc.', 20.0, 2.0, -4.0, -15.0, -5.9, -20.0),
]

_UTILITIES = [
    ('NEE', 'NextEra Energy', 15.0, 1.0, -2.0, -10.0, -6.8, -25.2),
    ('AEP', 'American Electric Power', 14.0, 0.3, -5.0, -20.0, -6.8, -25.2),
    ('DUK', 'Duke Energy', 13.0, 0.5, -3.0, -12.0, -6.8, -25.2),
    ('SO', 'Southern Company', 12.0, 0.5, -4.0, -15.0, -6.8, -25.2),
    ('EXC', 'Exelon Corp.', 10.0, -1.0, -7.0, -30.0, -6.8, -25.2),
]

_FIXTURE = {
    'Technology': _TECH,
    'Communication Services': _COMM,
    'Financials': _FIN,
    'Consumer Discretionary': _CONSDISCR,
    'Consumer Staples': _CONSTAPLES,
    'Energy': _ENERGY,
    'Healthcare': _HEALTH,
    'Industrials': _INDUSTRIALS,
    'Materials': _MATERIALS,
    'Real Estate': _REALESTATE,
    'Utilities': _UTILITIES,
}


def companies_for(sector):
    """CompanyQuantInput dicts for a sector name ([] if unknown)."""
    rows = _FIXTURE.get(sector, [])
    return [_row_to_input(r, sector) for r in rows]


def _row_to_input(r, sector):
    ticker, name, margin, yoy, r1m, r1y, b1m, b1y = r
    return {
        'ticker': ticker,
        'companyName': name,
        'sector': sector,
        'netMarginPct': margin,
        'netMarginYoyChangePp': yoy,
        'return1mPct': r1m,
        'return1yPct': r1y,
        'benchmarkReturn1mPct': b1m,
        'benchmarkReturn1yPct': b1y,
    }