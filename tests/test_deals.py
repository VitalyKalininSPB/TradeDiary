# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import unittest

import deals
import risk
import persistence


class DealTest(unittest.TestCase):
    def test_defaults(self):
        d = deals.Deal()
        self.assertEqual(d.ticker, "")
        self.assertEqual(d.direction, deals.Direction.LONG)
        self.assertTrue(d.is_open)  # close_date пустой

    def test_is_open(self):
        self.assertTrue(deals.Deal().is_open)
        self.assertFalse(deals.Deal(close_date="01/01/2024").is_open)

    def test_trade_system_name(self):
        self.assertEqual(deals.trade_system_name(0), "Average MA")
        self.assertEqual(deals.trade_system_name(1), "MACD")
        self.assertEqual(deals.trade_system_name("bad"), "Average MA")

    def test_infer_direction(self):
        self.assertEqual(
            deals.infer_direction(deals.Deal(stop_loss=100, stock_price=90)),
            deals.Direction.SHORT)
        self.assertEqual(
            deals.infer_direction(deals.Deal(stop_loss=90, stock_price=100)),
            deals.Direction.LONG)
        self.assertEqual(
            deals.infer_direction(deals.Deal(take_profit=90, stock_price=100)),
            deals.Direction.SHORT)


class RiskTest(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(risk.risk_pct_for_corr(0.8), 0.010)
        self.assertEqual(risk.risk_pct_for_corr(0.6), 0.015)
        self.assertEqual(risk.risk_pct_for_corr(0.4), 0.020)
        self.assertEqual(risk.risk_pct_for_corr(0.1), 0.025)

    def test_extremes(self):
        self.assertEqual(risk.risk_pct_for_corr(1.5), 0.010)
        self.assertEqual(risk.risk_pct_for_corr(-0.5), 0.025)


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old_db = persistence.DB_PATH
        self._old_xml = persistence.XML_PATH
        persistence.DB_PATH = os.path.join(self._tmp, "diary.db")
        persistence.XML_PATH = os.path.join(self._tmp, "diary.xml")

    def tearDown(self):
        persistence.DB_PATH = self._old_db
        persistence.XML_PATH = self._old_xml
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_roundtrip(self):
        d = deals.Deal(
            ticker="GAZP", stock_price=84.45, amount=100.0,
            open_date="21/08/2026 16:50", init_price=84.45,
            take_profit=91.55, stop_loss=80.9, currency="RUB",
            direction=deals.Direction.LONG)
        persistence.save([d], balance=-100.0)
        loaded, balance = persistence.load()
        self.assertEqual(balance, -100.0)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].ticker, "GAZP")
        self.assertEqual(loaded[0].direction, deals.Direction.LONG)
        self.assertAlmostEqual(loaded[0].init_price, 84.45)

    def test_migrate_from_xml(self):
        xml = ('<?xml version="1.0" ?><diary>'
               '<balance value="123.5"/>'
               '<deal ticker="SBER" stockPrice="272.1" stocksAmount="100" '
               'openDate="23/08/2026 07:38" initPrice="272.1" takeProfit="0" '
               'stopLoss="0" tradeSystem="0" result="" closeDate="" '
               'whatsNext="" analysisNotes="" currency="RUB"/></diary>')
        with open(persistence.XML_PATH, "w", encoding="utf-8") as fh:
            fh.write(xml)
        deals_, balance = persistence.load()
        self.assertEqual(balance, 123.5)
        self.assertEqual(len(deals_), 1)
        self.assertEqual(deals_[0].ticker, "SBER")
        self.assertEqual(deals_[0].currency, "RUB")
        # после миграции файл переименован
        self.assertFalse(os.path.exists(persistence.XML_PATH))


if __name__ == "__main__":
    unittest.main()
