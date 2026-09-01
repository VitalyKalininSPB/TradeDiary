# -*- coding: utf-8 -*-
import unittest

from tests import daily_dates
from macro_dialog import _at_days_ago, _gdp_phase, _late_cycle, \
    _PHASE_EARLY, _PHASE_MATURE, _PHASE_DECLINE, _PHASE_RECESSION


class AtDaysAgoTest(unittest.TestCase):
    def test_returns_value_days_ago(self):
        n = 500
        dates = daily_dates(n)
        values = list(range(n))
        got = _at_days_ago(dates, values, 90)
        self.assertIsNotNone(got)
        # ~90 days back from today == n-1-90 index
        self.assertAlmostEqual(got, n - 1 - 90, delta=2)


class GdpPhaseTest(unittest.TestCase):
    def test_empty_is_none(self):
        self.assertIsNone(_gdp_phase([], []))
        self.assertIsNone(_gdp_phase(daily_dates(10), [1.0] * 10))

    def _series(self, value_at, n=1100):
        """Build ~3y of daily GDP where `value_at(d)` is the value `d` days ago."""
        dates = daily_dates(n)
        values = [value_at(n - 1 - i) for i in range(n)]
        return dates, values

    def test_recession_when_contracting(self):
        # value_at(d) rising in d -> today < a year ago -> negative YoY growth.
        dates, values = self._series(lambda d: float(d))
        self.assertEqual(_gdp_phase(dates, values), _PHASE_RECESSION)

    def test_early_growth_when_recovering_below_trend(self):
        # Slight positive growth that is accelerating -> Early Growth.
        dates, values = self._series(lambda d: 100.0 - 0.001 * d + 2e-6 * d * d)
        self.assertEqual(_gdp_phase(dates, values), _PHASE_EARLY)

    def test_decline_when_decelerating_above_trend(self):
        # Faster growth that is decelerating -> Decline.
        dates, values = self._series(lambda d: 100.0 - 0.001 * d - 1.6e-5 * d * d)
        self.assertEqual(_gdp_phase(dates, values), _PHASE_DECLINE)

    def test_maturity_on_moderate_steady_growth(self):
        import math
        k = math.log(1.022) / 365.0   # ~2.2% steady YoY growth
        dates, values = self._series(lambda d, k=k: 100.0 * math.exp(-k * d))
        self.assertEqual(_gdp_phase(dates, values), _PHASE_MATURE)


class LateCycleTest(unittest.TestCase):
    def test_late_cycle_true(self):
        n = 200
        dates = daily_dates(n)
        gdpi = [100.0 - 0.01 * i for i in range(n)]   # falling
        cc = [100.0 + 0.01 * i for i in range(n)]      # holding/rising
        self.assertTrue(_late_cycle(gdpi, dates, cc, dates))

    def test_not_late_when_both_fall(self):
        n = 200
        dates = daily_dates(n)
        gdpi = [100.0 - 0.01 * i for i in range(n)]
        cc = [100.0 - 0.01 * i for i in range(n)]
        self.assertFalse(_late_cycle(gdpi, dates, cc, dates))

    def test_empty_is_false(self):
        self.assertFalse(_late_cycle([], [], [], []))


if __name__ == "__main__":
    unittest.main()
