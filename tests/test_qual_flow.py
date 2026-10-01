# -*- coding: utf-8 -*-
"""Qual: явное подтверждение «прошёл / не прошёл» двумя кнопками."""
import os
import tempfile
import unittest

from PySide6 import QtWidgets

import qualitative_dialog
import watchlist


class QualConfirmFlowTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        watchlist.WATCHLIST_PATH = os.path.join(self._tmpdir, 'watchlist.json')
        self._orig_web = qualitative_dialog.QWebEngineView
        qualitative_dialog.QWebEngineView = None  # без webview в тесте
        self._orig_info = QtWidgets.QMessageBox.information
        QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: None)
        self._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        qualitative_dialog.QWebEngineView = self._orig_web
        QtWidgets.QMessageBox.information = self._orig_info

    def _advance_to_last(self, d):
        d.tickerEdit.setText('TESTQ')
        d._begin_assessment()
        for _ in range(len(qualitative_dialog.STAGES) - 1):
            d._next_stage()

    def test_confirm_buttons_replace_finish_on_last_stage(self):
        d = qualitative_dialog.QualitativeAssessmentDialog()
        self._advance_to_last(d)
        self.assertEqual(d._current_stage, len(qualitative_dialog.STAGES) - 1)
        self.assertFalse(d.nextButton.isVisible())
        self.assertTrue(d.qualPassButton.isVisible())
        self.assertTrue(d.qualFailButton.isVisible())

    def test_passed_saves_qual(self):
        d = qualitative_dialog.QualitativeAssessmentDialog()
        self._advance_to_last(d)
        for i in range(len(qualitative_dialog.STAGES)):
            d._ratings[i] = 3
        d._confirm_qual(True)
        entry = watchlist.find('TESTQ')
        self.assertIsNotNone(watchlist.get_qual(entry))

    def test_not_passed_clears_qual(self):
        watchlist.set_qual_snapshot('TESTQ', 3.0, report='old')
        d = qualitative_dialog.QualitativeAssessmentDialog()
        self._advance_to_last(d)
        d._ratings[0] = 3
        d._confirm_qual(False)
        entry = watchlist.find('TESTQ')
        self.assertIsNone(watchlist.get_qual(entry))


if __name__ == '__main__':
    unittest.main()
