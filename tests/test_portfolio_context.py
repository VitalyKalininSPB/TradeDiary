# -*- coding: utf-8 -*-
import unittest

from portfolio_context import (build_portfolio_context, concentration_status,
                               largest_position, open_ideas_status)


class OpenIdeasStatusTest(unittest.TestCase):
    def test_normal_range(self):
        for count in (5, 6, 7, 8):
            status, note = open_ideas_status(count)
            self.assertEqual(status, 'normal', count)
            self.assertIsNone(note)

    def test_fewer_is_informational_not_warning(self):
        status, note = open_ideas_status(4)
        self.assertEqual(status, 'low')
        self.assertIsNotNone(note)
        self.assertIn('concentrated', note)

    def test_more_is_review_not_blocked(self):
        status, note = open_ideas_status(9)
        self.assertEqual(status, 'review')
        self.assertIsNotNone(note)


class ConcentrationStatusTest(unittest.TestCase):
    def test_normal_zone(self):
        for corr in (0.0, 0.2, 0.35, 0.5, 0.55):
            self.assertEqual(concentration_status(corr)[0], 'normal', corr)

    def test_elevated_zone(self):
        for corr in (0.56, 0.6, 0.7):
            self.assertEqual(concentration_status(corr)[0], 'elevated', corr)

    def test_high_zone(self):
        for corr in (0.71, 0.8, 1.0):
            self.assertEqual(concentration_status(corr)[0], 'high', corr)

    def test_unknown(self):
        self.assertEqual(concentration_status(None)[0], 'unknown')


class LargestPositionTest(unittest.TestCase):
    def test_largest(self):
        ticker, value, pct = largest_position(
            {'A': 1000, 'B': 5000, 'C': 2000}, total_equity_usd=50000)
        self.assertEqual(ticker, 'B')
        self.assertEqual(value, 5000)
        self.assertAlmostEqual(pct, 10.0)

    def test_empty(self):
        self.assertIsNone(largest_position({}, 50000))


class BuildPortfolioContextTest(unittest.TestCase):
    def test_build(self):
        ctx = build_portfolio_context(
            6, {'A': 1000, 'B': 5000}, 50000, corr=0.6)
        self.assertEqual(ctx['open_count'], 6)
        self.assertEqual(ctx['open_status'], 'normal')
        self.assertEqual(ctx['concentration'], 'elevated')
        self.assertEqual(ctx['largest'][0], 'B')

    def test_no_advanced_metrics(self):
        ctx = build_portfolio_context(
            6, {'A': 1000}, 50000, corr=0.3)
        for key in ('beta', 'equity_beta', 'portfolio_beta', 'volatility',
                    'portfolio_volatility', 'sharpe', 'var', 'weights'):
            self.assertNotIn(key, ctx)


if __name__ == '__main__':
    unittest.main()