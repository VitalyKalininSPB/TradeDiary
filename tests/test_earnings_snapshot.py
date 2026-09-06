# -*- coding: utf-8 -*-
"""Unit tests for Earnings Snapshot (SEC EDGAR XBRL normalization).

Покрытие (см. AGENTS.md -> Earnings Snapshot):
  1. Q1/Q2/Q3/Q4 extraction: direct quarterly; H1-Q1; 9M-H1; FY-9M.
  2. Capex с отрицательным знаком (cash outflow).
  3. FCF / net_debt / net_margin расчёты.
  4. Fallback XBRL тегов.
  5. Duplicate/restated facts: побеждает последний filing.
  6. Отсутствующие метрики: null/status, никогда не 0.
Интеграционный тест на CRC (живой SEC) — в
test_earnings_snapshot_integration.py.
"""
import datetime
import unittest

from earnings_snapshot import compute_snapshot


def fact(start, end, val, fy, fp, form, filed):
    e = {'end': end, 'val': val, 'fy': fy, 'fp': fp,
         'form': form, 'filed': filed, 'accn': 'x'}
    if start:
        e['start'] = start
    return e


def facts_doc(us_gaap):
    """Обернуть {tag: [entries]} в структуру SEC Company Facts.

    EPS в реальных данных лежит в единицах USD/shares — кладём туда же.
    """
    out = {}
    for tag, entries in us_gaap.items():
        unit = 'USD/shares' if tag == 'EarningsPerShareDiluted' else 'USD'
        out[tag] = {'units': {unit: entries}}
    return {'entityName': 'TEST', 'facts': {'us-gaap': out}}


Q1, Q2, Q3, Q4 = ('2025-03-31', '2025-06-30', '2025-09-30', '2025-12-31')
Q1P, Q2P, Q3P, Q4P = ('2024-03-31', '2024-06-30', '2024-09-30',
                      '2024-12-31')


def flow_quarterly(q_vals, fy, prev=False):
    """Прямые 3M-факты за кварталы года fy (prev — за 2024)."""
    ends = [Q1P, Q2P, Q3P, Q4P] if prev else [Q1, Q2, Q3, Q4]
    starts = [('2024-01-01',), ('2024-04-01',), ('2024-07-01',),
              ('2024-10-01',)] if prev else [
        ('2025-01-01',), ('2025-04-01',), ('2025-07-01',),
        ('2025-10-01',)]
    fps = ('Q1', 'Q2', 'Q3', 'Q4')
    out = []
    for (st,), end, val, fp in zip(starts, ends, q_vals, fps):
        out.append(fact(st, end, val, fy, fp, '10-Q', '2026-01-02'))
    return out


def ytd_entries(revenue_by_period):
    """Накопительные факты 2025: {'2025-03-31': 120, '2025-06-30': 280,...}."""
    out = []
    for end, val in revenue_by_period.items():
        if end == Q4:
            st, fp, form = '2025-01-01', 'FY', '10-K'
        elif end == Q3:
            st, fp, form = '2025-01-01', 'Q3', '10-Q'
        elif end == Q2:
            st, fp, form = '2025-01-01', 'Q2', '10-Q'
        else:
            st, fp, form = '2025-01-01', 'Q1', '10-Q'
        out.append(fact(st, end, val, 2025, fp, form, '2026-01-02'))
    return out


def balances_by_quarter(tag_vals):
    """Instant-факты (cash/debt) по кварталам 2025."""
    out = []
    for q, (end, fp, form, filed) in enumerate(
            ((Q1, 'Q1', '10-Q', '2025-05-01'),
             (Q2, 'Q2', '10-Q', '2025-08-01'),
             (Q3, 'Q3', '10-Q', '2025-11-01'),
             (Q4, 'FY', '10-K', '2026-03-01')), start=1):
        out.append(fact('', end, tag_vals[q], 2025, fp, form, filed))
    return out


class QuarterExtractionTest(unittest.TestCase):
    def test_direct_quarterly_duration(self):
        gaap = {'RevenueFromContractWithCustomerExcludingAssessedTax':
                flow_quarterly([100, 130, 120, 140], 2025)}
        r = compute_snapshot('TEST', '0000000000', facts_doc(gaap))
        qs = sorted(r['quarters'], key=lambda q: q['fiscal_quarter'])
        self.assertEqual([q['revenue']['value'] for q in qs],
                         [100, 130, 120, 140])
        self.assertEqual([q['revenue']['status'] for q in qs],
                         ['available'] * 4)

    def test_ytd_derivation(self):
        """H1-Q1 / 9M-H1 / FY-9M без прямых квартальных фактов."""
        gaap = {'RevenueFromContractWithCustomerExcludingAssessedTax':
                ytd_entries({Q1: 120, Q2: 280, Q3: 430, Q4: 620})}
        r = compute_snapshot('TEST', '0000000000', facts_doc(gaap))
        qs = sorted(r['quarters'], key=lambda q: q['fiscal_quarter'])
        self.assertEqual([q['revenue']['value'] for q in qs],
                         [120, 160, 150, 190])
        self.assertEqual([q['revenue']['status'] for q in qs],
                         ['available', 'derived', 'derived', 'derived'])

    def test_direct_preferred_over_cumulative(self):
        """Прямой 3M-факт предпочтительнее накопительного вычитания."""
        gaap = {'RevenueFromContractWithCustomerExcludingAssessedTax':
                ytd_entries({Q1: 120, Q2: 280, Q3: 430, Q4: 620})
                + flow_quarterly([120, 170, 150, 200], 2025)}
        r = compute_snapshot('TEST', '0000000000', facts_doc(gaap))
        qs = sorted(r['quarters'], key=lambda q: q['fiscal_quarter'])
        self.assertEqual([q['revenue']['value'] for q in qs],
                         [120, 170, 150, 200])
        self.assertEqual([q['revenue']['status'] for q in qs],
                         ['available'] * 4)


class CapexFlowTest(unittest.TestCase):
    def test_negative_capex_sign_and_fcf(self):
        """Capex как отрицательный outflow -> модуль; fcf = ocf - |capex|."""
        gaap = {
            'RevenueFromContractWithCustomerExcludingAssessedTax':
                flow_quarterly([1000, 1100, 1200, 1300], 2025),
            'NetIncomeLoss': flow_quarterly([200, 250, 300, 350], 2025),
            'EarningsPerShareDiluted': flow_quarterly([2.0, 2.2, 2.4, 2.6],
                                                     2025),
            'NetCashProvidedByUsedInOperatingActivities':
                flow_quarterly([300, 320, 340, 360], 2025),
            'PaymentsToAcquirePropertyPlantAndEquipment':
                flow_quarterly([-40, -50, -60, -70], 2025),   # outflow
            'CashAndCashEquivalentsAtCarryingValue':
                balances_by_quarter({1: 500, 2: 600, 3: 550, 4: 700}),
            'LongTermDebtCurrent':
                balances_by_quarter({1: 100, 2: 100, 3: 100, 4: 100}),
            'LongTermDebtNoncurrent':
                balances_by_quarter({1: 400, 2: 400, 3: 400, 4: 400}),
        }
        r = compute_snapshot('TEST', '0000000000', facts_doc(gaap))
        qs = sorted(r['quarters'], key=lambda q: q['fiscal_quarter'])

        # capex показывается положительным
        self.assertEqual([q['capex']['value'] for q in qs], [40, 50, 60, 70])
        # fcf = ocf - capex
        self.assertEqual([q['fcf']['value'] for q in qs],
                         [260, 270, 280, 290])
        self.assertEqual([q['fcf']['status'] for q in qs],
                         ['available'] * 4)
        self.assertIn('fcf', r['derived_metrics'])
        # net_debt = (current + noncurrent) - cash
        self.assertEqual([q['net_debt']['value'] for q in qs],
                         [0, -100, -50, -200])
        # debt = current + noncurrent
        self.assertEqual([q['total_debt']['value'] for q in qs],
                         [500, 500, 500, 500])
        self.assertEqual([q['total_debt']['status'] for q in qs],
                         ['available'] * 4)
        # net_margin = net_income / revenue
        self.assertEqual([q['net_margin']['value'] for q in qs],
                         [0.2, 250 / 1100, 300 / 1200, 350 / 1300])


class FallbackTagsTest(unittest.TestCase):
    def test_revenue_fallback_tag_used(self):
        gaap = {'SalesRevenueNet': flow_quarterly([111, 222, 333, 444], 2025)}
        r = compute_snapshot('TEST', '0000000000', facts_doc(gaap))
        qs = sorted(r['quarters'], key=lambda q: q['fiscal_quarter'])
        self.assertEqual([q['revenue']['value'] for q in qs],
                         [111, 222, 333, 444])
        self.assertEqual(qs[0]['revenue']['source_tag'], 'SalesRevenueNet')

    def test_ocf_fallback_tag(self):
        gaap = {
            'RevenueFromContractWithCustomerExcludingAssessedTax':
                flow_quarterly([1000] * 4, 2025),
            'NetIncomeLoss': flow_quarterly([100] * 4, 2025),
            'EarningsPerShareDiluted': flow_quarterly([1.0] * 4, 2025),
            'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations':
                flow_quarterly([10, 20, 30, 40], 2025),
        }
        r = compute_snapshot('TEST', '0000000000', facts_doc(gaap))
        qs = sorted(r['quarters'], key=lambda q: q['fiscal_quarter'])
        self.assertEqual([q['ocf']['value'] for q in qs], [10, 20, 30, 40])
        self.assertEqual(qs[0]['ocf']['source_tag'],
                         'NetCashProvidedByUsedInOperatingActivities'
                         'ContinuingOperations')


class RestatedTest(unittest.TestCase):
    def test_latest_filing_wins(self):
        """Данные за одинаковый период из разных filing: побеждает поздний."""
        e = fact('2025-01-01', Q1, 100, 2025, 'Q1', '10-Q', '2025-05-01')
        e2 = fact('2025-01-01', Q1, 120, 2025, 'Q1', '10-Q', '2025-09-01')
        gaap = {'RevenueFromContractWithCustomerExcludingAssessedTax':
                [e, e2, *flow_quarterly([130, 140, 150], 2025)[1:]]}
        r = compute_snapshot('TEST', '0000000000', facts_doc(gaap))
        q1 = [q for q in r['quarters'] if q['fiscal_quarter'] == 1][0]
        self.assertEqual(q1['revenue']['value'], 120)
        self.assertEqual(q1['revenue']['source_tag'],
                         'RevenueFromContractWithCustomerExcludingAssessedTax')


class MissingMetricsTest(unittest.TestCase):
    def test_no_zero_substitution(self):
        """Отсутствующие метрики -> null / 'missing', никогда не 0."""
        gaap = {'RevenueFromContractWithCustomerExcludingAssessedTax':
                flow_quarterly([100, 200, 300, 400], 2025)}
        r = compute_snapshot('TEST', '0000000000', facts_doc(gaap))
        self.assertEqual(r['status'], 'insufficient')
        for m in ('net_income', 'diluted_eps', 'ocf', 'capex', 'cash',
                  'fcf', 'total_debt'):
            self.assertIn(m, r['missing_metrics'])
        q0 = r['quarters'][0]
        for m in ('net_income', 'diluted_eps', 'ocf', 'cash', 'capex'):
            self.assertIsNone(q0[m]['value'])
            self.assertEqual(q0[m]['status'], 'missing')

    def test_eps_cumulative_only_is_missing(self):
        """EPS 6M/9M/FY (накопительные) не вычитаются и не подменяются."""
        gaap = {
            'RevenueFromContractWithCustomerExcludingAssessedTax':
                flow_quarterly([1000] * 4, 2025),
            'NetIncomeLoss': flow_quarterly([100] * 4, 2025),
            'EarningsPerShareDiluted': [
                fact('2025-01-01', end, val, 2025, fp, form, '2026-01-02')
                for end, val, fp, form in (
                    (Q1, 1.0, 'Q1', '10-Q'), (Q2, 2.1, 'Q2', '10-Q'),
                    (Q3, 3.2, 'Q3', '10-Q'), (Q4, 4.3, 'FY', '10-K'))
            ],
        }
        r = compute_snapshot('TEST', '0000000000', facts_doc(gaap))
        qs = {q['fiscal_quarter']: q for q in r['quarters']}
        self.assertEqual(qs[1]['diluted_eps']['value'], 1.0)   # 3M — квартал
        self.assertIsNone(qs[2]['diluted_eps']['value'])
        self.assertIsNone(qs[3]['diluted_eps']['value'])
        self.assertIsNone(qs[4]['diluted_eps']['value'])
        self.assertEqual(r['source_coverage']['diluted_eps'], 1)
        self.assertEqual(r['status'], 'partial')


class StatusTest(unittest.TestCase):
    def _doc(self, **drop):
        gaap = {
            'RevenueFromContractWithCustomerExcludingAssessedTax':
                flow_quarterly([1000] * 4, 2025),
            'NetIncomeLoss': flow_quarterly([100] * 4, 2025),
            'EarningsPerShareDiluted': flow_quarterly([1.0] * 4, 2025),
            'NetCashProvidedByUsedInOperatingActivities':
                flow_quarterly([150] * 4, 2025),
            'PaymentsToAcquirePropertyPlantAndEquipment':
                flow_quarterly([50] * 4, 2025),
            'CashAndCashEquivalentsAtCarryingValue':
                balances_by_quarter({1: 300, 2: 300, 3: 300, 4: 300}),
            'LongTermDebtNoncurrent':
                balances_by_quarter({1: 800, 2: 800, 3: 800, 4: 800}),
        }
        for k in drop:
            gaap.pop(k)
        return gaap

    def test_complete(self):
        r = compute_snapshot('TEST', '0000000000',
                             facts_doc(self._doc()))
        self.assertEqual(r['status'], 'complete')
        self.assertEqual(r['missing_metrics'], [])
        self.assertEqual(r['source_coverage']['revenue'], 4)
        self.assertEqual(r['source_coverage']['total_debt'], 4)

    def test_partial_without_cash_flow(self):
        r = compute_snapshot('TEST', '0000000000', facts_doc(
            self._doc(NetCashProvidedByUsedInOperatingActivities=True,
                      PaymentsToAcquirePropertyPlantAndEquipment=True)))
        self.assertEqual(r['status'], 'partial')
        self.assertIn('ocf', r['missing_metrics'])
        self.assertIn('fcf', r['missing_metrics'])

    def test_partial_without_cash(self):
        r = compute_snapshot('TEST', '0000000000', facts_doc(
            self._doc(CashAndCashEquivalentsAtCarryingValue=True)))
        self.assertEqual(r['status'], 'partial')
        self.assertIn('cash', r['missing_metrics'])
        self.assertIn('net_debt', r['missing_metrics'])


class YoYTest(unittest.TestCase):
    def test_yoy_and_qoq(self):
        """YoY — тот же квартал прошлого года; QoQ — предыдущий квартал."""
        gaap = {'RevenueFromContractWithCustomerExcludingAssessedTax':
                flow_quarterly([800, 900, 1000, 1100], 2024, prev=True)
                + flow_quarterly([1000, 1100, 1200, 1300], 2025)}
        r = compute_snapshot('TEST', '0000000000', facts_doc(gaap))
        q2 = [q for q in r['quarters'] if q['fiscal_quarter'] == 2][0]
        self.assertAlmostEqual(q2['revenue']['yoy_pct'],
                               (1100 / 900 - 1) * 100)
        self.assertAlmostEqual(q2['revenue']['qoq_pct'],
                               (1100 / 1000 - 1) * 100)
        self.assertEqual(len(r['quarters']), 4)

    def test_zero_denominator_returns_null(self):
        prev = flow_quarterly([800, 0, 1000, 1100], 2024, prev=True)
        cur = flow_quarterly([0, 1100, 1200, 1300], 2025)
        gaap = {'RevenueFromContractWithCustomerExcludingAssessedTax':
                prev + cur}
        r = compute_snapshot('TEST', '0000000000', facts_doc(gaap))
        q2 = [q for q in r['quarters'] if q['fiscal_quarter'] == 2][0]
        self.assertIsNone(q2['revenue']['yoy_pct'])
        self.assertIsNone(q2['revenue']['qoq_pct'])


if __name__ == '__main__':
    unittest.main()