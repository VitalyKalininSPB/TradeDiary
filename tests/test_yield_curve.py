# -*- coding: utf-8 -*-
import datetime
import unittest

from tests import daily_dates
from yield_curve import _ntfs_value, compute_ntfs_series


class NtfsValueTest(unittest.TestCase):
    def test_flat_curve_is_zero(self):
        # Flat 2% par curve + 2% current 3M bill -> forward == spot -> NTFS ~ 0.
        par = {0.5: 2.0, 1.0: 2.0, 2.0: 2.0}
        ntfs = _ntfs_value(par, cur_3m=2.0)
        self.assertAlmostEqual(ntfs, 0.0, places=1)

    def test_higher_forward_than_spot_is_positive(self):
        # Steep curve: longer maturities higher -> forward above current 3M.
        par = {0.5: 1.0, 1.0: 2.0, 2.0: 3.0}
        ntfs = _ntfs_value(par, cur_3m=1.0)
        self.assertGreater(ntfs, 0.0)


class ComputeNtfsSeriesTest(unittest.TestCase):
    def test_missing_series_is_empty(self):
        self.assertEqual(compute_ntfs_series({}), ([], []))

    def test_consistent_flat_series(self):
        dates = daily_dates(30)
        series = {
            "DTB3":   (dates, [2.0] * 30),
            "DGS6MO": (dates, [2.0] * 30),
            "DGS1":   (dates, [2.0] * 30),
            "DGS2":   (dates, [2.0] * 30),
        }
        out_dates, out_values = compute_ntfs_series(series)
        self.assertTrue(out_dates)
        self.assertTrue(out_values)
        for v in out_values:
            self.assertAlmostEqual(v, 0.0, places=1)


if __name__ == "__main__":
    unittest.main()
