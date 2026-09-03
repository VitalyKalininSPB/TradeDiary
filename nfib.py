# -*- coding: utf-8 -*-
"""NFIB composite of leading survey components (Small Business Economic Trends).

There is no free machine-readable source for NFIB data (it is not on FRED), so
the component series are imported manually as a multi-column CSV (see
macro_dialog._load_nfib_csv). This module only does the math: trailing z-score
per component, averaged, then squashed with tanh to [-100, +100] — the same
shape as the MLRCI oscillator, so long-term turning points are visible.

All six components are forward-looking (leading) diffusion indexes; a higher
value means more optimism, so the direction is +1 for every component.
"""
import warnings

import numpy as np

# (label, CSV column name). Diffusion indexes (net %), higher = more optimism.
COMPONENTS = [
    ('Expected higher sales', 'exp_sales'),
    ('Expected business conditions', 'exp_cond'),
    ('Job creation plans', 'job_plans'),
    ('Capital expenditure plans', 'capex'),
    ('Inventory plans', 'inv_plans'),
    ('Good time to expand', 'expand'),
]

_Z_WINDOW = 60   # months: trailing baseline for the z-score
_MIN_BASE = 24   # minimum baseline points before the z-score starts
_BUY_LEVEL = 80.0
_SELL_LEVEL = -80.0


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