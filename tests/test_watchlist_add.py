# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import recommendation_panel
import watchlist


class WatchlistAddTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        watchlist.WATCHLIST_PATH = os.path.join(self._tmpdir, 'watchlist.json')
        self.addCleanup(os.path.isdir, self._tmpdir)

    def test_successful_add(self):
        ok, msg = recommendation_panel.add_to_watchlist_safe('CAKE')
        self.assertTrue(ok)
        self.assertEqual(msg, 'Added to Watchlist')
        entries = watchlist.load()
        self.assertEqual([e['ticker'] for e in entries], ['CAKE'])

    def test_repeated_add_no_duplicate(self):
        recommendation_panel.add_to_watchlist_safe('CAKE')
        ok, _ = recommendation_panel.add_to_watchlist_safe('CAKE')
        self.assertTrue(ok)
        entries = watchlist.load()
        self.assertEqual([e['ticker'] for e in entries], ['CAKE'])

    def test_contains_state(self):
        self.assertFalse(recommendation_panel.watchlist_contains('CAKE'))
        recommendation_panel.add_to_watchlist_safe('CAKE')
        self.assertTrue(recommendation_panel.watchlist_contains('CAKE'))

    def test_save_error_reports_message(self):
        def _boom(_):
            raise OSError('disk full')
        original_save = watchlist.save
        watchlist.save = _boom
        try:
            ok, msg = recommendation_panel.add_to_watchlist_safe('CAKE')
        finally:
            watchlist.save = original_save
        self.assertFalse(ok)
        self.assertIn('Не удалось сохранить watchlist', msg)

    def test_empty_ticker_rejected(self):
        ok, msg = recommendation_panel.add_to_watchlist_safe('')
        self.assertFalse(ok)
        self.assertEqual(msg, 'Не указан тикер.')


if __name__ == '__main__':
    unittest.main()