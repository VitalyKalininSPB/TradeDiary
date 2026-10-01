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


class PartialCloseTest(unittest.TestCase):
    """Закрытие части позиции по текущей цене (без TP/SL)."""

    @classmethod
    def setUpClass(cls):
        cls._app = (QtWidgets.QApplication.instance()
                    or QtWidgets.QApplication([]))

    def _stub(self, data, balance):
        s = _Stub()
        s.data = data
        s.base_balance = balance
        s._settle = main.TradeDiary._settle.__get__(s)
        s._syncModel = lambda: None
        s.recalcBalance = lambda: None
        return s

    def test_long_partial_sell_fifo(self):
        d1 = Deal(ticker='X', amount=6, init_price=100, stock_price=110,
                  currency='USD', direction=Direction.LONG,
                  open_date='30/09/2026')
        d2 = Deal(ticker='X', amount=13, init_price=100, stock_price=110,
                  currency='USD', direction=Direction.LONG,
                  open_date='01/10/2026')
        s = self._stub([d1, d2], 10000.0)
        pos = main.Position('X', [d1, d2])
        left = main.TradeDiary._partial_close(s, pos, 4)
        self.assertEqual(d1.amount, 2)
        self.assertEqual(d2.amount, 13)
        self.assertAlmostEqual(s.base_balance, 10000.0 + 4 * 110)
        self.assertEqual(left, 15)

    def test_long_partial_exhausts_first_deal(self):
        d1 = Deal(ticker='X', amount=6, init_price=100, stock_price=110,
                  currency='USD', direction=Direction.LONG,
                  open_date='30/09/2026')
        d2 = Deal(ticker='X', amount=13, init_price=100, stock_price=110,
                  currency='USD', direction=Direction.LONG,
                  open_date='01/10/2026')
        s = self._stub([d1, d2], 10000.0)
        pos = main.Position('X', [d1, d2])
        left = main.TradeDiary._partial_close(s, pos, 8)
        self.assertNotIn(d1, s.data)
        self.assertEqual(d2.amount, 11)
        self.assertEqual(left, 11)

    def test_short_partial_buyback_debits(self):
        d = Deal(ticker='X', amount=54, init_price=18.26, stock_price=18.46,
                 currency='USD', direction=Direction.SHORT,
                 open_date='30/09/2026')
        s = self._stub([d], 10000.0)
        pos = main.Position('X', [d])
        left = main.TradeDiary._partial_close(s, pos, 20)
        self.assertEqual(d.amount, 34)
        self.assertAlmostEqual(s.base_balance, 10000.0 - 20 * 18.46)
        self.assertEqual(left, 34)

    def test_zero_qty_is_noop(self):
        d = Deal(ticker='X', amount=6, init_price=100, stock_price=110,
                 currency='USD', direction=Direction.LONG,
                 open_date='30/09/2026')
        s = self._stub([d], 10000.0)
        pos = main.Position('X', [d])
        left = main.TradeDiary._partial_close(s, pos, 0)
        self.assertEqual(d.amount, 6)
        self.assertEqual(s.base_balance, 10000.0)
        self.assertEqual(left, 6)


class EditDialogPartialTest(unittest.TestCase):
    """[Sell] в окне позиции применяется сразу (не по [OK])."""

    @classmethod
    def setUpClass(cls):
        cls._app = (QtWidgets.QApplication.instance()
                    or QtWidgets.QApplication([]))

    def test_sell_applies_immediately(self):
        from EditDealDialog import EditDealDialog
        d1 = Deal(ticker='X', amount=6, init_price=100, stock_price=110,
                  currency='USD', direction=Direction.LONG,
                  open_date='30/09/2026')
        d2 = Deal(ticker='X', amount=1, init_price=100, stock_price=110,
                  currency='USD', direction=Direction.LONG,
                  open_date='01/10/2026')
        pos = main.Position('X', [d1, d2])
        calls = []
        dlg = EditDealDialog()
        dlg.setPosition(pos, 10000.0,
                        on_partial=lambda q: (calls.append(q) or 6.0))
        dlg.partialQty.setText('1')
        dlg._partial_clicked()
        self.assertEqual(calls, [1.0])
        self.assertEqual(dlg._remaining, 6.0)
        self.assertEqual(dlg.amountEdit.text(), '6.00')


if __name__ == '__main__':
    unittest.main()
