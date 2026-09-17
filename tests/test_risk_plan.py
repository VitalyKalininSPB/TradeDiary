# -*- coding: utf-8 -*-
import unittest

from risk_plan import (build_risk_plan, compute_metrics, quantity_from_notional,
                       risk_pct, validate_stop)


class ValidateStopTest(unittest.TestCase):
    def test_long_stop_below_entry_ok(self):
        self.assertIsNone(validate_stop('LONG', 100, 92))

    def test_short_stop_above_entry_ok(self):
        self.assertIsNone(validate_stop('SHORT', 100, 108))

    def test_long_stop_above_entry_error(self):
        self.assertIsNotNone(validate_stop('LONG', 100, 101))

    def test_long_stop_equal_entry_error(self):
        self.assertIsNotNone(validate_stop('LONG', 100, 100))

    def test_short_stop_below_entry_error(self):
        self.assertIsNotNone(validate_stop('SHORT', 100, 99))

    def test_missing_stop_is_error(self):
        self.assertIsNotNone(validate_stop('LONG', 100, 0))
        self.assertIsNotNone(validate_stop('LONG', 100, None))


class ComputeMetricsTest(unittest.TestCase):
    def test_long_metrics(self):
        m = compute_metrics(100, 92, 50)
        self.assertEqual(m['risk_per_share'], 8)
        self.assertEqual(m['position_value'], 5000)
        self.assertEqual(m['risk_at_stop'], 400)

    def test_short_metrics(self):
        m = compute_metrics(100, 108, 50)
        self.assertEqual(m['risk_per_share'], 8)
        self.assertEqual(m['risk_at_stop'], 400)


class RiskPctTest(unittest.TestCase):
    def test_pct(self):
        self.assertEqual(risk_pct(500, 100000), 0.5)

    def test_zero_equity_returns_none(self):
        self.assertIsNone(risk_pct(500, 0))


class QuantityFromNotionalTest(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(quantity_from_notional(5000, 100), 50)

    def test_floor(self):
        self.assertEqual(quantity_from_notional(5050, 100), 50)

    def test_invalid(self):
        self.assertIsNone(quantity_from_notional(0, 100))
        self.assertIsNone(quantity_from_notional(-5, 100))
        self.assertEqual(quantity_from_notional(5000, 0), 0)


class BuildRiskPlanTest(unittest.TestCase):
    def test_long_ok(self):
        plan = build_risk_plan(100, 92, 50, 'LONG', total_equity_usd=50000)
        self.assertTrue(plan['ok'])
        self.assertEqual(plan['metrics']['risk_per_share'], 8)
        self.assertEqual(plan['metrics']['position_value'], 5000)
        self.assertEqual(plan['metrics']['risk_at_stop'], 400)
        self.assertEqual(plan['position_value_usd'], 5000)
        self.assertEqual(plan['risk_at_stop_usd'], 400)
        self.assertAlmostEqual(plan['risk_pct'], 0.8)

    def test_short_ok(self):
        plan = build_risk_plan(100, 108, 50, 'SHORT', total_equity_usd=50000)
        self.assertTrue(plan['ok'])
        self.assertEqual(plan['metrics']['risk_at_stop'], 400)

    def test_missing_stop_blocked(self):
        plan = build_risk_plan(100, 0, 50, 'LONG', total_equity_usd=50000)
        self.assertFalse(plan['ok'])
        self.assertTrue(any('Stop-loss' in b for b in plan['blockers']))

    def test_wrong_side_blocked(self):
        plan = build_risk_plan(100, 101, 50, 'LONG', total_equity_usd=50000)
        self.assertFalse(plan['ok'])

    def test_notional_warning_not_blocked(self):
        plan = build_risk_plan(100, 92, 200, 'LONG', total_equity_usd=50000,
                               max_notional_usd=10000)
        self.assertTrue(plan['ok'])
        self.assertTrue(any('exceeds' in w.lower()
                            for w in plan['warnings']))

    def test_risk_over_one_percent_warning_not_blocked(self):
        plan = build_risk_plan(100, 80, 50, 'LONG', total_equity_usd=50000,
                               max_risk_pct=1.0)
        self.assertTrue(plan['ok'])
        self.assertTrue(any('per-trade limit' in w for w in plan['warnings']))

    def test_risk_over_two_percent_strong_warning(self):
        plan = build_risk_plan(100, 50, 50, 'LONG', total_equity_usd=50000,
                               max_risk_pct=1.0)
        self.assertTrue(plan['ok'])
        self.assertTrue(any('2%' in w for w in plan['warnings']))


if __name__ == '__main__':
    unittest.main()