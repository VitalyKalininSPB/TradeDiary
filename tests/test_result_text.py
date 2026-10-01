# -*- coding: utf-8 -*-
"""Result: P&L открытой сделки — «% · сумма» с учётом направления."""
import unittest

from PySide6 import QtWidgets

import main
from deals import Deal, Direction


class ResultTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = (QtWidgets.QApplication.instance()
                    or QtWidgets.QApplication([]))

    def _t(self, **kw):
        return main.TableModel._result_text(Deal(**kw))

    def test_long_win(self):
        self.assertEqual(
            self._t(init_price=100, stock_price=110, amount=10,
                    currency='USD', direction=Direction.LONG),
            '+10.0% · +$100.00')

    def test_short_win(self):
        self.assertEqual(
            self._t(init_price=100, stock_price=90, amount=10,
                    currency='USD', direction=Direction.SHORT),
            '+10.0% · +$100.00')

    def test_long_loss(self):
        self.assertEqual(
            self._t(init_price=100, stock_price=95, amount=10,
                    currency='USD', direction=Direction.LONG),
            '-5.0% · -$50.00')

    def test_short_loss(self):
        self.assertEqual(
            self._t(init_price=100, stock_price=105, amount=10,
                    currency='USD', direction=Direction.SHORT),
            '-5.0% · -$50.00')

    def test_without_amount_only_pct(self):
        self.assertEqual(
            self._t(init_price=100, stock_price=110, amount=0,
                    currency='USD', direction=Direction.LONG),
            '+10.0%')

    def test_rub_sign(self):
        self.assertEqual(
            self._t(init_price=300, stock_price=330, amount=10,
                    currency='RUB', direction=Direction.LONG),
            '+10.0% · +₽300.00')

    def test_closed_uses_stored_result(self):
        self.assertEqual(
            self._t(result='Win', close_date='01/10/2026'), 'Win')

    def test_missing_prices_empty(self):
        self.assertEqual(
            self._t(init_price=0, stock_price=110, amount=10), '')


if __name__ == '__main__':
    unittest.main()
