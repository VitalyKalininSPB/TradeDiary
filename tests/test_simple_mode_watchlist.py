# -*- coding: utf-8 -*-
import unittest

from simple_mode import build_simple_card, _eps_outperform, _watchlist_trigger


def _card(**over):
    e = {
        'ticker': 'T',
        'eps_growth': None,
        'sector_median_eps_growth': None,
        'forward_pe': None,
        'sector_median_pe': None,
        'trailing_pe': None,
        'surprise_avg': None,
        'net_margin_yoy': None,
        'pct_pe': None,
        'earnings_date': None,
        'sector': None,
    }
    e.update(over)
    return build_simple_card(e)


class EpsOutperformTest(unittest.TestCase):
    def test_substantial_outperformance_fires(self):
        # 12.0 >= 8.0 + 2.0 и 12.0 >= 8.0*1.20=9.6 → да
        self.assertEqual(_eps_outperform(12.0, 8.0), (True, False))

    def test_abs_ok_but_rel_not_ok(self):
        # sfeg=15: abs-порог 17, rel-порог 18 → feg=17.5 abs ок, rel нет
        self.assertEqual(_eps_outperform(17.5, 15.0), (False, False))

    def test_low_base_uses_abs_only(self):
        # benchmark <= 0 → только абсолютный порог +2.0 п.п.
        self.assertEqual(_eps_outperform(1.0, -2.0), (True, True))
        self.assertEqual(_eps_outperform(-1.0, -2.0), (False, True))

    def test_missing_benchmark(self):
        self.assertEqual(_eps_outperform(None, 8.0), (False, False))
        self.assertEqual(_eps_outperform(12.0, None), (False, False))


class WatchlistTriggerTest(unittest.TestCase):
    def test_eps_outperformance(self):
        # 12.0 существенно выше 8.0 → eps_outperformance
        trig = _watchlist_trigger(12.0, 8.0, 20.0, 25.0, None, None,
                                  False, False)
        self.assertEqual(trig[0], 'eps_outperformance')

    def test_eps_outperformance_low_base(self):
        trig = _watchlist_trigger(1.0, -2.0, 20.0, 25.0, None, None,
                                  False, False)
        self.assertEqual(trig[0], 'eps_outperformance')
        self.assertIn('низкая/отрицательная база', trig[1])

    def test_growth_at_reasonable_valuation(self):
        # рост выше, но НЕ «существенно выше» (abs 9.0<8.1+2.0) → growth_valuation
        trig = _watchlist_trigger(9.0, 8.1, 23.1, 27.9, None, None,
                                  False, False)
        self.assertEqual(trig[0], 'growth_valuation')

    def test_growth_but_expensive_no_trigger(self):
        # рост выше, но valuation дороже → не рост-ценной
        self.assertIsNone(_watchlist_trigger(9.0, 8.1, 40.0, 20.0, None, None,
                                             False, True))

    def test_strong_earnings_signal(self):
        # средний сюрприз >= +5% → earnings_signal
        trig = _watchlist_trigger(None, None, 20.0, 25.0, 8.0, None,
                                  False, False)
        self.assertEqual(trig[0], 'earnings_signal')
        # рост маржи YoY >= +3 п.п. → earnings_signal
        trig = _watchlist_trigger(None, None, 20.0, 25.0, None, 4.0,
                                  False, False)
        self.assertEqual(trig[0], 'earnings_signal')

    def test_signal_conflict(self):
        # рост не «существенно выше», но положительный, и valuation дороже,
        # при подтверждённом сильном росте (positive_eps) → конфликт
        trig = _watchlist_trigger(9.0, 8.0, 40.0, 20.0, None, None,
                                  True, True)
        self.assertEqual(trig[0], 'signal_conflict')

    def test_no_triggers(self):
        # рост ниже benchmark, valuation не дороже, нет сюрпризов/маржи
        self.assertIsNone(_watchlist_trigger(7.0, 8.0, 20.0, 20.0, None, None,
                                             False, False))


class SimpleCardWatchlistActionTest(unittest.TestCase):
    def test_cake_example_eps_outperformance(self):
        # CAKE: +10.6 vs +8.1 при forward P/E 23.1 vs 27.9 → существенное
        # превосходство по EPS (новый порог: +2.0 п.п. и ×1.20)
        card = _card(eps_growth=10.6, sector_median_eps_growth=8.1,
                     forward_pe=23.1, sector_median_pe=27.9,
                     surprise_avg=3.0, net_margin_yoy=1.0)
        self.assertEqual(card['verdict'], 'watchlist')
        self.assertEqual(card['watchlist_trigger'][0], 'eps_outperformance')
        self.assertIn('Details сейчас', card['action'])
        self.assertIn('опережает peers/сектор', card['action'])

    def test_growth_valuation_trigger(self):
        # рост выше, но не «существенно» (+1 п.п.), valuation не дороже
        card = _card(eps_growth=9.0, sector_median_eps_growth=8.1,
                     forward_pe=23.1, sector_median_pe=27.9,
                     surprise_avg=3.0, net_margin_yoy=1.0)
        self.assertEqual(card['verdict'], 'watchlist')
        self.assertEqual(card['watchlist_trigger'][0], 'growth_valuation')
        self.assertIn('Details сейчас', card['action'])

    def test_no_trigger_keeps_wait_action(self):
        card = _card(eps_growth=7.0, sector_median_eps_growth=8.0,
                     forward_pe=20.0, sector_median_pe=20.0)
        self.assertEqual(card['verdict'], 'watchlist')
        self.assertIsNone(card['watchlist_trigger'])
        self.assertIn('Открыть Details при техническом сетапе', card['action'])

    def test_candidate_not_watchlist(self):
        card = _card(eps_growth=15.0, sector_median_eps_growth=8.0,
                     forward_pe=20.0, sector_median_pe=25.0,
                     surprise_avg=2.0, net_margin_yoy=1.0)
        self.assertEqual(card['verdict'], 'candidate')
        self.assertNotIn('Открыть Details', card['action'])


if __name__ == '__main__':
    unittest.main()