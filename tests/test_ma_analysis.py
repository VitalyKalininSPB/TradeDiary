# -*- coding: utf-8 -*-
import unittest

import numpy as np

from ma_chart_dialog import _smooth, _crosses, analyze_death_crosses
from tests import daily_dates


class SmoothTest(unittest.TestCase):
    def test_simple_moving_average(self):
        out = _smooth([1.0, 2.0, 3.0, 4.0, 5.0], [1.0, 2.0, 3.0, 4.0, 5.0], 3)
        self.assertTrue(np.isnan(out[0]))
        self.assertTrue(np.isnan(out[1]))
        self.assertAlmostEqual(out[2], 2.0)
        self.assertAlmostEqual(out[4], 4.0)


class CrossesTest(unittest.TestCase):
    def test_death_cross(self):
        short = [2.0, 2.0, 2.0]
        long = [1.0, 1.0, 3.0]
        deaths, goldens = _crosses(short, long)
        self.assertIn(2, deaths)
        self.assertEqual(goldens, [])

    def test_golden_cross(self):
        short = [1.0, 3.0, 3.0]
        long = [2.0, 2.0, 2.0]
        deaths, goldens = _crosses(short, long)
        self.assertIn(1, goldens)
        self.assertEqual(deaths, [])


class DeathCrossAnalysisTest(unittest.TestCase):
    def test_detects_cross_on_trending_series(self):
        # Up, then sharp down through SMA50 -> a death cross should appear.
        n = 400
        prices = [100.0 + 0.05 * i for i in range(300)] + \
                 [115.0 - 0.5 * i for i in range(100)]
        dates = daily_dates(n)
        res = analyze_death_crosses(dates, np.array(prices))
        self.assertTrue(res["death_indices"])
        self.assertIn("grid", res)
        self.assertIn("details", res)


if __name__ == "__main__":
    unittest.main()
