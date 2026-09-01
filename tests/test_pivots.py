# -*- coding: utf-8 -*-
import unittest

import numpy as np

from pivots import pivot_indices


class PivotIndicesTest(unittest.TestCase):
    def test_sine_has_peak_and_trough(self):
        values = list(np.sin(np.linspace(0, 4 * np.pi, 500)))
        pts = pivot_indices(values, min_points=8)
        signs = [s for _, s in pts]
        self.assertIn(-1, signs, "expected at least one peak (sign=-1)")
        self.assertIn(+1, signs, "expected at least one trough (sign=+1)")

    def test_short_series_is_empty(self):
        self.assertEqual(pivot_indices([1.0, 2.0, 3.0]), [])

    def test_all_nan_is_empty(self):
        self.assertEqual(pivot_indices([float("nan")] * 100), [])

    def test_monotonic_has_no_turns(self):
        values = list(np.linspace(0, 100, 200))
        self.assertEqual(pivot_indices(values), [])


if __name__ == "__main__":
    unittest.main()
