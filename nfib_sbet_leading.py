#!/usr/bin/env python3
"""
Download the six NFIB SBET leading components from the official NFIB API.

NFIB's SBET platform runs a DreamFactory REST backend at
https://api.nfib-sbet.org (see https://nfib-sbet.org/Developers.html). The
Optimism-index components are returned by the getIndicators2 stored procedure;
the mapping and the fetch live in nfib.py (the single source of truth also
used by the app's auto-load path).

Output:
  nfib_leading_components.csv  (date,exp_sales,exp_cond,job_plans,capex,inv_plans,expand)

Requirements:
  pip install requests pandas

Example:
  python nfib_sbet_leading.py --start 1986-01-01 --end 2026-07-01
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from nfib import CODES, fetch_components


def parse_month(value: str) -> date:
    try:
        parsed = pd.Timestamp(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Use YYYY-MM-DD."
        ) from exc

    return date(parsed.year, parsed.month, 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download the six NFIB SBET leading components."
    )
    parser.add_argument(
        "--start",
        default="1986-01-01",
        type=parse_month,
        help="First month, YYYY-MM-DD. Default: 1986-01-01",
    )
    parser.add_argument(
        "--end",
        default=date.today().replace(day=1).isoformat(),
        type=parse_month,
        help="Last month, YYYY-MM-DD. Default: current month",
    )
    parser.add_argument(
        "--output",
        default="nfib_leading_components.csv",
        help="Output CSV file. Default: nfib_leading_components.csv",
    )
    args = parser.parse_args()

    if args.start > args.end:
        parser.error("--start must not be later than --end")

    dates, cols = fetch_components(
        args.start.year, args.start.month, args.end.year, args.end.month)

    if not dates:
        parser.error("The API returned no rows for the requested range.")

    frame = pd.DataFrame(cols)
    frame.insert(0, "date", [d.isoformat() for d in dates])
    frame = frame.round(1)

    output_path = Path(args.output)
    frame.to_csv(
        output_path, index=False, na_rep="NA", float_format="%.1f"
    )

    print(f"Saved: {output_path.resolve()}", file=sys.stderr)
    print(
        f"Months: {len(frame)} | Range: {frame['date'].iloc[0]} to "
        f"{frame['date'].iloc[-1]}",
        file=sys.stderr,
    )
    missing = int(frame[list(CODES)].isna().sum().sum())
    if missing:
        print(
            f"Warning: {missing} missing values preserved as NA.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()