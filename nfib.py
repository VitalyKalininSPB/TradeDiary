# -*- coding: utf-8 -*-
"""NFIB composite of leading survey components (Small Business Economic Trends).

The six forward-looking components come from the official NFIB SBET REST API
(DreamFactory backend, see https://nfib-sbet.org/Developers.html). The short
API codes below are the ones used by the Indicators page (graphs.js). This
module is the single source of truth for both the app's auto-load path and the
standalone downloader script (nfib_sbet_leading.py). It computes a trailing
z-score per component, averages them, then squashes with tanh to [-100, +100]
— the same shape as the MLRCI oscillator.

All six components are forward-looking (leading) diffusion indexes; a higher
value means more optimism, so the direction is +1 for every component.
"""
import datetime
import warnings

import numpy as np
import requests

# (label, CSV column name). Diffusion indexes (net %), higher = more optimism.
COMPONENTS = [
    ('Expected higher sales', 'exp_sales'),
    ('Expected business conditions', 'exp_cond'),
    ('Job creation plans', 'job_plans'),
    ('Capital expenditure plans', 'capex'),
    ('Inventory plans', 'inv_plans'),
    ('Good time to expand', 'expand'),
]

# CSV column -> NFIB API indicator code (short codes from the Indicators page).
CODES = {
    'exp_sales': 'sersale',    # Expect Real Sales Higher
    'exp_cond': 'sebcd',       # Expect Economy to Improve
    'job_plans': 'sxlfch',     # Plans to Increase Employment
    'capex': 'snpce',          # Plans to Make Capital Outlays
    'inv_plans': 'sxinvch',    # Plans to Increase Inventories
    'expand': 'sgtex',         # Now a Good Time to Expand
}

_API_URL = 'https://api.nfib-sbet.org:443/rest/sbetdb/_proc/getIndicators2'
_APP_NAME = 'sbet'
_TIMEOUT_SECONDS = 60

_Z_WINDOW = 60   # months: trailing baseline for the z-score
_MIN_BASE = 24   # minimum baseline points before the z-score starts
_BUY_LEVEL = 80.0
_SELL_LEVEL = -80.0


def fetch_components(start_year, start_month, end_year, end_month):
    """Fetch the six leading components from the NFIB API in one call.

    Returns (dates, cols) with cols {name: [values]} aligned on monthly dates
    (ascending). Raises requests.RequestException on network/HTTP failure.
    """
    payload = {
        'app_name': _APP_NAME,
        'params': [
            {'name': 'minYear', 'param_type': 'IN', 'value': start_year},
            {'name': 'minMonth', 'param_type': 'IN', 'value': start_month},
            {'name': 'maxYear', 'param_type': 'IN', 'value': end_year},
            {'name': 'maxMonth', 'param_type': 'IN', 'value': end_month},
            {'name': 'indicator', 'param_type': 'IN',
             'value': ','.join(CODES.values())},
        ],
    }
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-DreamFactory-Application-Name': _APP_NAME,
    }
    response = requests.post(
        _API_URL, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()

    names = [name for _label, name in COMPONENTS]
    cols = {name: [] for name in names}
    dates = []
    for row in response.json():
        raw = row.get('monthyear')
        if not raw:
            continue
        try:
            year, month, _day = [int(part) for part in raw.split('/')]
        except ValueError:
            continue
        dates.append(datetime.date(year, month, 1))
        for name in names:
            value = row.get(CODES[name])
            try:
                cols[name].append(float(value))
            except (TypeError, ValueError):
                cols[name].append(float('nan'))
    if dates:
        order = sorted(range(len(dates)), key=lambda i: dates[i])
        dates = [dates[i] for i in order]
        cols = {name: [v[i] for i in order] for name, v in cols.items()}
    return dates, cols


def _zscore(values, window=_Z_WINDOW, min_base=_MIN_BASE):
    """Trailing z-score over the last `window` points (monthly data)."""
    arr = np.asarray(values, dtype=float)
    out = np.full_like(arr, np.nan, dtype=float)
    for i in range(len(arr)):
        lo = max(0, i - window)
        seg = arr[lo:i + 1]
        seg = seg[np.isfinite(seg)]
        if seg.size < min_base:
            continue
        mu, sd = np.nanmean(seg), np.nanstd(seg)
        if sd == 0 or not np.isfinite(sd):
            continue
        out[i] = (arr[i] - mu) / sd
    return out


def compute_composite(cols):
    """Composite oscillator [-100..+100] from {name: [values]} dict.

    Returns [] when a required component is missing or empty. Components are
    averaged after equal-weight z-scoring, then squashed with tanh.
    """
    names = [name for _label, name in COMPONENTS]
    if not cols or any(name not in cols for name in names):
        return []
    n = len(cols[names[0]])
    if n == 0:
        return []
    z = np.column_stack([_zscore(cols[name]) for name in names])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        mean = np.nanmean(z, axis=1)
    return [float(x) for x in np.tanh(mean) * 100.0]