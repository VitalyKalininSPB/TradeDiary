# -*- coding: utf-8 -*-
"""Агрегация позиций по тикеру: одна строка на тикер."""
import unittest

from PySide6 import QtWidgets

import main
from deals import Deal, Direction


class _Stub:
    pass


class PositionAggregationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = (QtWidgets.QApplication.instance()
                    or QtWidgets.QApplication([]))

    def _positions(self, deals):
        s = _Stub()
        s.data = deals
        return main.TradeDiary._build_positions(s)

    def test_groups_same_ticker_into_one_row(self):
        d1 = Deal(ticker='NVDA', amount=6, init_price=227.21,
                  stock_price=228.38, currency='USD', direction=Direction.LONG)
        d2 = Deal(ticker='NVDA', amount=13, init_price=227.00,
                  stock_price=228.38, currency='USD', direction=Direction.LONG)
        d3 = Deal(ticker='KSS', amount=54, init_price=18.26,
                  stock_price=18.46, currency='USD', direction=Direction.SHORT)
        pos = self._positions([d1, d2, d3])
        self.assertEqual([p.ticker for p in pos], ['NVDA', 'KSS'])
        nvda = pos[0]
        self.assertEqual(nvda.amount, 19)
        self.assertAlmostEqual(nvda.init_price, (227.21 * 6 + 227.0 * 13) / 19)
        self.assertEqual(len(nvda.deals), 2)

    def test_weighted_average_price_and_pnl(self):
        d1 = Deal(ticker='X', amount=1, init_price=100, stock_price=110,
                  currency='USD', direction=Direction.LONG)
        d2 = Deal(ticker='X', amount=3, init_price=100, stock_price=110,
                  currency='USD', direction=Direction.LONG)
        pos = self._positions([d1, d2])[0]
        self.assertEqual(pos.amount, 4)
        self.assertAlmostEqual(pos.init_price, 100)
        self.assertEqual(main.TableModel._result_text(pos),
                         '+10.0% · +$40.00')

    def test_earliest_open_date(self):
        d1 = Deal(ticker='X', amount=1, open_date='01/10/2026 09:00')
        d2 = Deal(ticker='X', amount=1, open_date='30/09/2026 14:19')
        pos = self._positions([d1, d2])[0]
        self.assertEqual(pos.open_date, '30/09/2026 14:19')

    def test_closed_deal_kept_with_result(self):
        d = Deal(ticker='X', amount=1, result='Win',
                 close_date='01/10/2026', init_price=100, stock_price=110)
        pos = self._positions([d])[0]
        self.assertEqual(pos.close_date, '01/10/2026')
        self.assertEqual(main.TableModel._result_text(pos), 'Win')

    def test_empty_ticker_skipped(self):
        d = Deal(ticker='', amount=1, init_price=100, stock_price=110)
        self.assertEqual(self._positions([d]), [])


if __name__ == '__main__':
    unittest.main()
