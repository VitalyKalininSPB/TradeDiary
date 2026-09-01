# -*- coding: utf-8 -*-
"""Shared helpers for the test suite (no pytest dependency, stdlib unittest)."""
import datetime
import os
import sys

# Ensure the repo root is importable and Qt runs headless (offscreen) in tests.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def daily_dates(n, end=None):
    """Return `n` consecutive dates ending at `end` (or today)."""
    end = end or datetime.date.today()
    return [end - datetime.timedelta(days=n - 1 - i) for i in range(n)]
