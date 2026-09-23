# -*- coding: utf-8 -*-
"""Фьючерсы Brent (FORTS): разбор ISS, выбор контракта, денежная математика."""
import datetime
import os
import shutil
import tempfile
import unittest

import deals
import futures
import persistence
import risk_plan

_ISS = {
    'securities': {
        'columns': ['SECID', 'SHORTNAME', 'LASTTRADEDATE', 'MINSTEP', 'STEPPRICE',
                    'INITIALMARGIN', 'LOTVOLUME', 'ASSETCODE', 'PREVSETTLEPRICE'],
        'data': [
            ['BRX6', 'BR-11.26', '2026-11-02', 0.01, 8.40657, 19711.5, 10, 'BR', 96.38],
            ['BRV6', 'BR-10.26', '2026-10-01', 0.01, 8.40657, 17678.39, 10, 'BR', 100.15],
            ['SiZ6', 'Si-12.26', '2026-12-17', 1.0, 1.0, 9000.0, 1000, 'Si', 85000],
        ]},
    'marketdata': {'columns': ['SECID', 'LAST', 'SETTLEPRICE'],
                   'data': [['BRX6', 95.87, 95.94], ['BRV6', 0, 99.57]]},
}


class FuturesTest(unittest.TestCase):
    def setUp(self):
        self.specs = futures.parse_iss(_ISS, 'BR')

    def test_parse_filters_and_sorts(self):
        self.assertEqual([s.secid for s in self.specs], ['BRV6', 'BRX6'])
        x = self.specs[1]
        self.assertEqual(x.lot_volume, 10)
        self.assertAlmostEqual(x.point_value, 840.657)
        self.assertEqual(x.price, 95.87)
        self.assertEqual(self.specs[0].price, 99.57)  # нет LAST -> settle

    def test_asset_of(self):
        for t in ('BR', 'br', 'BR-11.26', 'BRX6', 'brx6'):
            self.assertEqual(futures.asset_of(t), 'BR', t)
        for t in ('', 'AAPL', 'SBER', 'NASD-12.26', 'BRA6'):
            self.assertIsNone(futures.asset_of(t), t)

    def test_shortname_to_secid(self):
        self.assertEqual(futures.shortname_to_secid('BR-11.26'), 'BRX6')
        self.assertEqual(futures.shortname_to_secid('BR-1.27'), 'BRF7')
        self.assertEqual(futures.secid_for('BRX6'), 'BRX6')

    def test_pick_front_month_skips_expired(self):
        before = datetime.date(2026, 9, 23)
        after = datetime.date(2026, 10, 5)
        self.assertEqual(futures.pick_contract(self.specs, 'BR', before).secid, 'BRV6')
        self.assertEqual(futures.pick_contract(self.specs, 'BR', after).secid, 'BRX6')
        self.assertEqual(futures.pick_contract(self.specs, 'br-11.26').secid, 'BRX6')
        self.assertIsNone(futures.pick_contract(self.specs, 'BR-5.30'))

    def test_money(self):
        pv = 840.657
        self.assertAlmostEqual(futures.pnl_rub(95, 97, 2, 'LONG', pv), 2 * 2 * pv)
        self.assertAlmostEqual(futures.pnl_rub(95, 97, 2, deals.Direction.SHORT, pv),
                               -2 * 2 * pv)
        self.assertAlmostEqual(futures.risk_rub(95, 93, 1, pv), 2 * pv)
        self.assertEqual(futures.margin_rub(3, 19711.5), 59134.5)
        # номинал 1 контракта: 95 × 840.657 ₽ / 84.0657 = $950
        self.assertEqual(futures.contracts_from_notional(2000, 95, pv, 84.0657), 2)

    def test_expiry(self):
        d = datetime.date(2026, 9, 28)
        b, w = futures.expiry_issue('2026-10-01', d)
        self.assertIsNone(b)
        self.assertIn('3', w)
        b, w = futures.expiry_issue('2026-09-01', d)
        self.assertIsNotNone(b)
        self.assertEqual(futures.expiry_issue('2026-12-01', d), (None, None))

    def test_risk_plan_multiplier(self):
        plan = risk_plan.build_risk_plan(95.0, 93.0, 1, 'LONG', 10000.0,
                                         usd_rate=84.0657, multiplier=840.657)
        self.assertAlmostEqual(plan['metrics']['risk_per_share'], 1681.314)
        self.assertAlmostEqual(plan['risk_at_stop_usd'], 20.0, places=6)
        self.assertAlmostEqual(plan['position_value_usd'], 950.0, places=6)
        self.assertAlmostEqual(plan['risk_pct'], 0.2, places=6)


class FuturesPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._db, self._xml = persistence.DB_PATH, persistence.XML_PATH
        persistence.DB_PATH = os.path.join(self.tmp, 'diary.db')
        persistence.XML_PATH = os.path.join(self.tmp, 'diary.xml')

    def tearDown(self):
        persistence.DB_PATH, persistence.XML_PATH = self._db, self._xml
        shutil.rmtree(self.tmp)

    def test_roundtrip_future(self):
        d = deals.Deal(ticker='BR-11.26', stock_price=95.87, init_price=95.87,
                       amount=2, stop_loss=93.0, currency='RUB',
                       asset_type=deals.AssetType.FUTURE, point_value=840.657,
                       margin=19711.5, expiry='2026-11-02')
        persistence.save([d, deals.Deal(ticker='AAPL')], 1000.0)
        loaded, bal = persistence.load()
        self.assertEqual(bal, 1000.0)
        self.assertTrue(loaded[0].is_future)
        self.assertAlmostEqual(loaded[0].point_value, 840.657)
        self.assertEqual(loaded[0].expiry, '2026-11-02')
        self.assertFalse(loaded[1].is_future)

    def test_migrates_old_schema(self):
        import sqlite3
        conn = sqlite3.connect(persistence.DB_PATH)
        conn.execute(
            "CREATE TABLE deals (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "ticker TEXT NOT NULL, stock_price REAL, amount REAL, open_date TEXT,"
            "init_price REAL, take_profit REAL, stop_loss REAL, trade_system INTEGER,"
            "result TEXT, close_date TEXT, whats_next TEXT, notes TEXT,"
            "currency TEXT, direction TEXT)")
        conn.execute("INSERT INTO deals (ticker, stock_price, direction) "
                     "VALUES ('SBER', 300, 'LONG')")
        conn.commit()
        conn.close()
        loaded, _ = persistence.load()
        self.assertEqual(loaded[0].ticker, 'SBER')
        self.assertEqual(loaded[0].asset_type, deals.AssetType.STOCK)


if __name__ == '__main__':
    unittest.main()
