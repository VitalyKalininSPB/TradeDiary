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


class QuantPassedFlagTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        watchlist.WATCHLIST_PATH = os.path.join(self._tmpdir, 'watchlist.json')

    def test_not_passed_by_default(self):
        watchlist.add('LLY')
        entry = watchlist.find('LLY')
        self.assertFalse(watchlist.is_quant_passed(entry))

    def test_manual_flag_marks_passed(self):
        watchlist.add('LLY')
        self.assertTrue(watchlist.set_quant_passed('LLY', True))
        entry = watchlist.find('LLY')
        self.assertTrue(watchlist.is_quant_passed(entry))
        self.assertIsNone(watchlist.get_quant(entry))

    def test_manual_flag_can_be_cleared(self):
        watchlist.add('LLY')
        watchlist.set_quant_passed('LLY', True)
        watchlist.set_quant_passed('LLY', False)
        self.assertFalse(watchlist.is_quant_passed(watchlist.find('LLY')))

    def test_real_snapshot_counts_as_passed(self):
        watchlist.set_quant_snapshot('LLY', 1.5, sector='Healthcare')
        self.assertTrue(watchlist.is_quant_passed(watchlist.find('LLY')))

    def test_set_on_missing_ticker_creates_entry(self):
        self.assertTrue(watchlist.set_quant_passed('NOPE', True))
        self.assertTrue(watchlist.is_quant_passed(watchlist.find('NOPE')))

    def test_qual_does_not_require_quant(self):
        watchlist.set_qual_snapshot('LLY', 3.0, report='thesis')
        entry = watchlist.find('LLY')
        self.assertIsNotNone(watchlist.get_qual(entry))
        self.assertFalse(watchlist.is_quant_passed(entry))

    def test_clear_quant_removes_snapshot_and_flag(self):
        watchlist.set_quant_snapshot('LLY', 1.5, sector='Healthcare')
        watchlist.set_qual_snapshot('LLY', 3.0, report='thesis')
        self.assertTrue(watchlist.clear_quant('LLY'))
        entry = watchlist.find('LLY')
        self.assertFalse(watchlist.is_quant_passed(entry))
        self.assertIsNone(watchlist.get_quant(entry))
        self.assertIsNotNone(watchlist.get_qual(entry))  # Qual не тронут

    def test_clear_qual_removes_snapshot(self):
        watchlist.set_qual_snapshot('LLY', 3.0, report='thesis')
        watchlist.set_quant_snapshot('LLY', 1.5, sector='Healthcare')
        self.assertTrue(watchlist.clear_qual('LLY'))
        entry = watchlist.find('LLY')
        self.assertIsNone(watchlist.get_qual(entry))
        self.assertTrue(watchlist.is_quant_passed(entry))  # Quant не тронут

    def test_clear_on_missing_ticker_returns_false(self):
        self.assertFalse(watchlist.clear_quant('NOPE'))
        self.assertFalse(watchlist.clear_qual('NOPE'))


class RecommendationButtonsTest(unittest.TestCase):
    """Add to Watchlist не ставит Quant; Quant — только явной кнопкой."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        watchlist.WATCHLIST_PATH = os.path.join(self._tmpdir, 'watchlist.json')
        from PySide6 import QtWidgets
        self._orig_info = QtWidgets.QMessageBox.information
        QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: None)

    def tearDown(self):
        from PySide6 import QtWidgets
        QtWidgets.QMessageBox.information = self._orig_info

    @staticmethod
    def _stub(e):
        class _S:
            pass
        s = _S()
        s._ticker = e.get('ticker')
        s._e = e
        s._refresh_watchlist_button = lambda: None
        return s

    def test_add_does_not_mark_quant(self):
        e = {'ticker': 'LLY', 'sector': 'Healthcare', 'score_rounded': 1.2}
        recommendation_panel.RecommendationDialog._add_to_watchlist(self._stub(e))
        entry = watchlist.find('LLY')
        self.assertIsNotNone(entry)
        self.assertIsNone(watchlist.get_quant(entry))
        self.assertFalse(watchlist.is_quant_passed(entry))

    def test_mark_quant_saves_score(self):
        e = {'ticker': 'LLY', 'sector': 'Healthcare', 'score_rounded': 1.2}
        stub = self._stub(e)
        recommendation_panel.RecommendationDialog._add_to_watchlist(stub)
        recommendation_panel.RecommendationDialog._mark_quant_passed(stub)
        entry = watchlist.find('LLY')
        self.assertTrue(watchlist.is_quant_passed(entry))
        self.assertEqual(watchlist.get_quant(entry)['score'], 1.2)

    def test_mark_quant_without_score_sets_manual_flag(self):
        e = {'ticker': 'PLUG', 'sector': 'Industrials'}
        stub = self._stub(e)
        recommendation_panel.RecommendationDialog._mark_quant_passed(stub)
        entry = watchlist.find('PLUG')
        self.assertTrue(watchlist.is_quant_passed(entry))
        self.assertIsNone(watchlist.get_quant(entry))


if __name__ == '__main__':
    unittest.main()
