# -*- coding: utf-8 -*-
import datetime
import unittest

import numpy as np

from tests import daily_dates
from mlrci import compute_net_liquidity, _zscore, _REAL_ID, _WALCL_ID, _TGA_ID, \
    _RRP_ID, _BBB_ID, _VIX_ID, compute_signals


class NetLiquidityTest(unittest.TestCase):
    def test_alignment_and_rrp_scaling(self):
        d1, d2 = datetime.date(2024, 1, 1), datetime.date(2024, 1, 2)
        series = {
            _WALCL_ID: ([d1, d2], [1000.0, 1100.0]),
            _TGA_ID:   ([d1], [100.0]),
            _RRP_ID:   ([d1], [2.0]),   # bn -> *1000 = 2000
        }
        dates, values = compute_net_liquidity(series)
        self.assertEqual(dates, [d1, d2])
        self.assertAlmostEqual(values[0], 1000.0 - 100.0 - 2000.0)
        self.assertAlmostEqual(values[1], 1100.0 - 100.0 - 2000.0)

    def test_empty_input(self):
        self.assertEqual(compute_net_liquidity({}), ([], []))


class ZScoreTest(unittest.TestCase):
    def test_warmup_is_nan_and_tail_positive(self):
        arr = list(np.arange(60.0))
        z = _zscore(arr, 5 * 365)
        self.assertTrue(np.isnan(z[0]))
        self.assertFalse(np.isnan(z[-1]))
        self.assertGreater(z[-1], 0.0)

    def test_constant_series_is_nan(self):
        z = _zscore([5.0] * 40, 5 * 365)
        self.assertTrue(all(np.isnan(v) for v in z))


class ComputeSignalsTest(unittest.TestCase):
    def _aligned(self):
        base = daily_dates(120)
        n = len(base)
        zero = [0.0] * n
        return base, {
            _REAL_ID: zero[:],
            "NTFS": zero[:],
            "NetLiq": zero[:],
            _BBB_ID: zero[:],
            _VIX_ID: zero[:],
        }, [0.0] * n

    def test_returns_two_lists(self):
        base, aligned, mlrci = self._aligned()
        buy, sell = compute_signals(aligned, base, mlrci)
        self.assertIsInstance(buy, list)
        self.assertIsInstance(sell, list)


if __name__ == "__main__":
    unittest.main()
