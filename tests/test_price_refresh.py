# -*- coding: utf-8 -*-
"""Обновление текущей цены: сигнал потока должен сохранять целые ключи.

Регрессия: `Signal(dict)` в PySide6 — это QVariantMap со строковыми ключами,
поэтому словарь {id(deal): price} приходил пустым и цена не обновлялась.
"""
import unittest

from PySide6 import QtWidgets

import main
import markets
from deals import Deal


class PriceRefreshSignalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = (QtWidgets.QApplication.instance()
                    or QtWidgets.QApplication([]))

    def test_signal_preserves_int_keys(self):
        orig = markets.fetch_world_price
        markets.fetch_world_price = lambda ticker: 123.45
        try:
            d = Deal(ticker='NVDA', currency=markets.USD)
            t = main._PriceRefreshThread([(id(d), 'NVDA', markets.USD)])
            out = []
            t.prices_ready.connect(lambda p: out.append(p))
            t.run()
        finally:
            markets.fetch_world_price = orig
        self.assertTrue(out, 'сигнал не эмитировался')
        self.assertEqual(out[0].get(id(d)), 123.45)


if __name__ == '__main__':
    unittest.main()
