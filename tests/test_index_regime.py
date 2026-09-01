# -*- coding: utf-8 -*-
import unittest

import numpy as np

from index_dialog import _regime


class RegimeTest(unittest.TestCase):
    def test_insufficient_data_is_none(self):
        self.assertIsNone(_regime([100.0] * 100))

    def test_bull_above_sma(self):
        values = [100.0] * 250 + [110.0] * 50
        self.assertEqual(_regime(values), "bull")

    def test_bear_below_sma(self):
        values = [100.0] * 250 + [90.0] * 50
        self.assertEqual(_regime(values), "bear")

    def test_neutral_flat(self):
        values = [100.0] * 260
        self.assertIsNone(_regime(values))


if __name__ == "__main__":
    unittest.main()
