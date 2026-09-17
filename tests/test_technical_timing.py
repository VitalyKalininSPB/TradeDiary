# -*- coding: utf-8 -*-
import unittest

from technical_timing import (build_timing, compute_indicators, _conflicts,
                              _status_for)


def _series(start, step, n):
    return [start + step * i for i in range(n)]


class ConflictsTest(unittest.TestCase):
    def test_long_conflicts(self):
        self.assertEqual(
            _conflicts('long', False, False, False),
            ['цена ниже SMA 200', 'death cross (SMA 50 < SMA 200)',
             'MACD медвежий'])
        self.assertEqual(_conflicts('long', True, True, True), [])
        self.assertEqual(_conflicts('long', False, True, True),
                         ['цена ниже SMA 200'])

    def test_short_conflicts_mirror(self):
        self.assertEqual(
            _conflicts('short', True, True, True),
            ['цена выше SMA 200', 'golden cross (SMA 50 > SMA 200)',
             'MACD бычий'])
        self.assertEqual(_conflicts('short', False, False, False), [])

    def test_none_not_counted(self):
        self.assertEqual(_conflicts('long', None, None, None), [])
        self.assertEqual(_conflicts('short', None, None, None), [])


class StatusTest(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(_status_for(0), 'ready')
        self.assertEqual(_status_for(1), 'wait')
        self.assertEqual(_status_for(2), 'reassess')
        self.assertEqual(_status_for(3), 'reassess')


class IndicatorsTest(unittest.TestCase):
    def test_rsi_monotonic(self):
        up = compute_indicators(_series(100.0, 1.0, 300))
        self.assertEqual(up['rsi'], 100.0)
        self.assertEqual(up['rsi_band'], 'overbought')
        down = compute_indicators(_series(400.0, -1.0, 300))
        self.assertEqual(down['rsi'], 0.0)
        self.assertEqual(down['rsi_band'], 'oversold')

    def test_uptrend_structure(self):
        ind = compute_indicators(_series(100.0, 1.0, 300))
        self.assertIsNotNone(ind['sma50'])
        self.assertIsNotNone(ind['sma200'])
        self.assertTrue(ind['above_sma200'])
        self.assertTrue(ind['golden_cross'])
        self.assertEqual(ind['macd_state'], 'bullish')

    def test_downtrend_structure(self):
        ind = compute_indicators(_series(400.0, -1.0, 300))
        self.assertFalse(ind['above_sma200'])
        self.assertFalse(ind['golden_cross'])
        self.assertEqual(ind['macd_state'], 'bearish')


class BuildTimingTest(unittest.TestCase):
    def test_uptrend_long_ready(self):
        res = build_timing('AAA', None, _series(100.0, 1.0, 300), 'long')
        self.assertEqual(res['status'], 'ready')
        self.assertIn('READY TO CONSIDER ENTRY', res['status_txt'])
        self.assertEqual(res['conflicts'], [])
        # RSI перегрет -> мягкое предупреждение, но статус остаётся ready.
        self.assertTrue(res['warning'])

    def test_downtrend_long_reassess(self):
        res = build_timing('BBB', None, _series(400.0, -1.0, 300), 'long')
        self.assertEqual(res['status'], 'reassess')
        self.assertEqual(len(res['conflicts']), 3)
        self.assertEqual(res['warning'], '')

    def test_downtrend_short_ready(self):
        res = build_timing('CCC', None, _series(400.0, -1.0, 300), 'short')
        self.assertEqual(res['status'], 'ready')

    def test_no_data(self):
        res = build_timing('DDD', None, _series(100.0, 1.0, 30), 'long')
        self.assertEqual(res['status'], 'no_data')
        self.assertIsNotNone(res['reason'])

    def test_stop_ref_direction(self):
        long_res = build_timing('E', None, _series(100.0, 1.0, 300), 'long')
        self.assertIn('support', long_res['stop_ref'].lower())
        short_res = build_timing('F', None, _series(400.0, -1.0, 300), 'short')
        self.assertIn('resistance', short_res['stop_ref'].lower())

    def test_display_fields(self):
        res = build_timing('G', None, _series(100.0, 1.0, 300), 'long')
        self.assertEqual(res['price_vs_sma200_txt'], 'Above')
        self.assertEqual(res['cross_txt'], 'Golden Cross active')
        self.assertEqual(res['macd_txt'], 'Bullish')


if __name__ == '__main__':
    unittest.main()