# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import idea_log

_ORIG_SNAP = idea_log.snapshot_technical

_TECH = {
    'signal_price': 100.0, 'price_vs_sma200': 'Above', 'sma200': 95.0,
    'macd_state': 'bullish', 'rsi': 61.0, 'tech_status': 'ready',
    'tech_reason': 'нет конфликта', 'tech_warning': '',
}


def _deal(ticker='AAA', direction='LONG', open_date='17/09/2026 10:00',
          entry=100.0, close_date=None):
    return SimpleNamespace(ticker=ticker, direction=direction,
                           open_date=open_date, close_date=close_date,
                           init_price=entry, stock_price=entry,
                           currency='USD')


class IdeaLogTest(unittest.TestCase):
    def setUp(self):
        fd, tmp = tempfile.mkstemp()
        os.close(fd)
        os.unlink(tmp)
        self._db = tmp + '.db'
        self._patcher = patch.object(idea_log, 'DB_PATH', self._db)
        self._patcher.start()
        idea_log.snapshot_technical = lambda t, direction='long': dict(_TECH)
        idea_log.snapshot_fundamental = lambda t: (None, None)

    def tearDown(self):
        self._patcher.stop()
        for p in (self._db, self._db + '-journal'):
            if os.path.exists(p):
                os.unlink(p)

    def test_log_creates_row(self):
        idea_log.log_idea_from_deal(_deal())
        rows = idea_log.all_ideas()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r['ticker'], 'AAA')
        self.assertEqual(r['direction'], 'long')
        self.assertEqual(r['entry_date'], '2026-09-17')
        self.assertEqual(r['entry_price'], 100.0)
        self.assertEqual(r['tech_status'], 'ready')
        self.assertEqual(r['price_vs_sma200'], 'Above')
        self.assertEqual(r['macd_state'], 'bullish')
        self.assertEqual(r['rsi'], 61.0)
        self.assertEqual(r['outcome'], 'open')

    def test_relog_updates_not_duplicates(self):
        idea_log.log_idea_from_deal(_deal())
        idea_log.log_idea_from_deal(_deal())
        self.assertEqual(idea_log.count(), 1)
        self.assertEqual(idea_log.open_count(), 1)

    def test_short_direction_detected(self):
        idea_log.log_idea_from_deal(_deal(direction='SHORT'))
        self.assertEqual(idea_log.all_ideas()[0]['direction'], 'short')

    def test_snapshot_immutable_no_lookahead(self):
        idea_log.log_idea_from_deal(_deal())
        # «будущее»: снимок стал бы другим, если пересчитать
        idea_log.snapshot_technical = lambda t, direction='long': dict(
            _TECH, tech_status='reassess', price_vs_sma200='Below', rsi=20.0)
        idea_log.close_idea_from_deal(_deal(close_date='25/09/2026 15:00'))
        rows = idea_log.all_ideas()
        self.assertEqual(rows[0]['tech_status'], 'ready')
        self.assertEqual(rows[0]['price_vs_sma200'], 'Above')
        self.assertEqual(rows[0]['rsi'], 61.0)

    def test_close_long_outcome(self):
        series = {'2026-09-10': 95.0, '2026-09-15': 98.0, '2026-09-18': 96.0,
                  '2026-09-20': 88.0, '2026-09-25': 92.0}
        with patch.object(idea_log.price_history, 'load_series',
                          return_value=series):
            idea_log.log_idea_from_deal(_deal(entry=100.0))
            idea_log.close_idea_from_deal(_deal(
                entry=100.0, close_date='25/09/2026 15:00'))
        r = idea_log.all_ideas()[0]
        self.assertEqual(r['outcome'], 'closed')
        self.assertEqual(r['close_date'], '2026-09-25')
        self.assertEqual(r['days_to_outcome'], 8)
        self.assertAlmostEqual(r['final_pnl_pct'], -8.0)
        self.assertAlmostEqual(r['max_adverse_move_pct'], 12.0)

    def test_close_short_outcome(self):
        # для шорта просадка = рост цены выше входа (104 в окне)
        series = {'2026-09-10': 95.0, '2026-09-18': 104.0, '2026-09-25': 92.0}
        with patch.object(idea_log.price_history, 'load_series',
                          return_value=series):
            idea_log.log_idea_from_deal(_deal(direction='SHORT', entry=100.0))
            idea_log.close_idea_from_deal(_deal(
                direction='SHORT', entry=100.0,
                close_date='25/09/2026 15:00'))
        r = idea_log.all_ideas()[0]
        self.assertAlmostEqual(r['final_pnl_pct'], 8.0)
        self.assertAlmostEqual(r['max_adverse_move_pct'], 4.0)

    def test_annotate_by_ticker(self):
        idea_log.log_idea_from_deal(_deal())
        n = idea_log.annotate_idea_by_ticker(
            'AAA', probability='medium', main_risk='сквиз',
            source='Perplexity 09.2026')
        self.assertEqual(n, 1)
        r = idea_log.all_ideas()[0]
        self.assertEqual(r['probability'], 'medium')
        self.assertEqual(r['main_risk'], 'сквиз')
        self.assertEqual(r['source'], 'Perplexity 09.2026')

    def test_export_csv(self):
        idea_log.log_idea_from_deal(_deal())
        out = self._db + '.csv'
        idea_log.export_csv(out)
        with open(out, encoding='utf-8') as f:
            txt = f.read()
        self.assertIn('ticker', txt)
        self.assertIn('AAA', txt)
        self.assertIn('ready', txt)
        os.unlink(out)

    def test_snapshot_technical_no_cache(self):
        idea_log.snapshot_technical = _ORIG_SNAP
        with patch.object(idea_log.price_history, 'load_series',
                          return_value={}):
            snap = idea_log.snapshot_technical('NOPE')
        self.assertEqual(snap['tech_status'], 'no_data')


if __name__ == '__main__':
    unittest.main()