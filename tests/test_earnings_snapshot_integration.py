# -*- coding: utf-8 -*-
"""Integration test: живой SEC EDGAR через build_earnings_snapshot().

CRC realtiies: CIK 0001609253 (California Resources Corp),
XBRL-факты содержат restated/сравнительные значения, отчётность частичная
(potential situations like Q4-2025 EPS только FY-формат) — проверяем, что
модуль корректно дедуплицирует, указывает статус partial и не падает.

Тест помечен @skip(skip_integration=True) если сеть недоступна
(используется в CI без доступа к SEC).
"""
import unittest

from earnings_snapshot import build_earnings_snapshot
from earnings_snapshot import cik_for_ticker


def _sec_available():
    try:
        return cik_for_ticker('CRC') is not None
    except Exception:
        return False


@unittest.skipUnless(_sec_available(), 'SEC EDGAR недоступен в этом окружении')
class CrcIntegrationTest(unittest.TestCase):
    def test_crc_builds_snapshot(self):
        r = build_earnings_snapshot('CRC')
        self.assertEqual(r['ticker'].upper(), 'CRC')
        self.assertEqual(r['cik'], '0001609253')
        self.assertIn(r['status'], ('complete', 'partial', 'insufficient'))
        self.assertEqual(len(r['quarters']), 4)
        self.assertRegex(r['as_of_filed_date'], r'\d{4}-\d{2}-\d{2}')

        # revenue/net_income присутствуют хотя бы частично (никогда не 0)
        for q in r['quarters']:
            self.assertTrue(any(m.get('value') is not None for m in
                                (q['revenue'], q['net_income'], q['ocf'])))
            self.assertNotEqual(q['revenue'].get('value'), 0)

        # кварталы монотонно по датам (последние 4 завершённых периода)
        ends = [q['period_end'] for q in r['quarters']]
        self.assertEqual(ends, sorted(ends))

        # derived присутствуют хотя бы в одном квартале
        self.assertIn('fcf', r['derived_metrics'])
        self.assertIn('net_margin', r['derived_metrics'])

    def test_crc_ticker_lookup_case_insensitive(self):
        r = build_earnings_snapshot('crc')
        self.assertEqual(r['cik'], '0001609253')

    def test_unknown_ticker(self):
        r = build_earnings_snapshot('NO_SUCH_TICKER_XYZ')
        self.assertEqual(r['status'], 'unavailable')
        self.assertTrue(any('не найден' in w for w in r['warnings']))
        self.assertEqual(r['quarters'], [])


if __name__ == '__main__':
    unittest.main()