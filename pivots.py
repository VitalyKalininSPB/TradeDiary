# -*- coding: utf-8 -*-
"""Pure-math helpers for chart analysis: significant trend turning points.

No Qt / matplotlib dependency — numpy only. Any chart dialog (macro dashboard,
price history, index charts, ...) can import `pivot_indices` to highlight
meaningful reversals ("точки перегиба") on its series.
"""
import bisect
import datetime

import numpy as np


def pivot_indices(values, dates=None, window_frac=0.03, range_frac=0.18,
                  min_gap_days=60, local_days=365, smooth_days=90,
                  min_points=8):
    """Significant trend turning points as (index, sign) pairs.

    A centred moving average strips high-frequency noise; a slope-sign change
    marks a candidate turn. To keep local 4-8-month reversals even next to a
    big secular move, the minimum separation between kept turns is measured
    against the *trailing local* range (about `local_days` of history) instead
    of the whole series; a minimum calendar gap also thins the candidates.

    Args:
        values:      array-like of floats (a single FRED/price series).
        dates:       optional list of dates (same length as values) used for
                     the local-range window, the minimum-gap filter and the
                     smoothing window (calendar-based).
        window_frac: smoothing window as a fraction of the series length,
                     used only when `dates` is None.
        range_frac:  minimum vertical distance between kept turns, as a
                     fraction of the trailing local range.
        min_gap_days:minimum calendar distance between kept turns (dates only).
        local_days:  trailing calendar window for the local range (dates only).
        smooth_days: smoothing window in calendar days (dates only).
        min_points:  minimum series length before any turn can be detected.

    Returns:
        list of (index, sign) tuples into `values`, where sign is +1 at a
        bottom (series turns up -> "sell": real rate about to rise) and -1 at
        a top (series turns down -> "buy": real rate about to fall).
    """
    vals = np.asarray(values, dtype=float)
    n = len(vals)
    if n < min_points or not np.any(np.isfinite(vals)):
        return []
    if dates is not None:
        deltas = np.diff([d.toordinal() for d in dates])
        med = float(np.median(deltas)) if len(deltas) else 1.0
        med = max(med, 1e-9)
        w = max(3, int(round(smooth_days / med)) | 1)
        w = min(w, n - 2)
    else:
        w = max(3, min(int(round(n * window_frac)) | 1, n - 1))
    if (w & 1) == 0:
        w -= 1
    if w < 3 or n - w + 1 < 3:
        return []
    half = (w - 1) // 2
    y = np.convolve(np.nan_to_num(vals), np.ones(w) / w, mode='valid')
    d = np.sign(np.diff(y))
    cand, prev_s, i = [], 0, 0
    while i < len(d):
        s = d[i]
        j = i
        while j < len(d) and d[j] == s:
            j += 1
        if prev_s != 0 and s != 0 and s != prev_s:
            cand.append((i + half, s))
        prev_s = s
        i = j
    if not cand:
        return []

    full_range = np.nanmax(vals) - np.nanmin(vals)

    def local_range(idx):
        if dates is not None:
            i0 = bisect.bisect_left(dates, dates[idx] -
                                    datetime.timedelta(days=local_days))
            seg = vals[i0:idx]
        else:
            seg = vals[max(0, idx - int(round(n * 0.1))):idx]
        if len(seg) < 5:
            return None
        rng = float(np.nanmax(seg) - np.nanmin(seg))
        return rng if rng > 0 else None

    out = []
    for idx, s in cand:
        if out:
            if dates is not None and \
                    (dates[idx] - dates[out[-1][0]]).days < min_gap_days:
                continue
            rng = local_range(idx)
            thr = rng * range_frac if rng is not None else full_range * range_frac
            if abs(vals[idx] - vals[out[-1][0]]) < thr:
                continue
        out.append((idx, s))
    return out