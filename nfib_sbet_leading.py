#!/usr/bin/env python3
"""
Download the six NFIB SBET leading components from the official NFIB API.

NFIB's SBET platform runs a DreamFactory REST backend at
https://api.nfib-sbet.org (see https://nfib-sbet.org/Developers.html). The
Optimism-index components are returned by the getIndicators2 stored procedure;
the six forward-looking (leading) components used by the TradeDiary composite
are mapped to the short API codes below.

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
from typing import Any

import pandas as pd
import requests

API_URL = "https://api.nfib-sbet.org:443/rest/sbetdb/_proc/getIndicators2"
APP_NAME = "sbet"
TIMEOUT_SECONDS = 60

# CSV column -> indicator code returned by the API. Codes are the short ones
# used by the Indicators page (graphs.js): sersale = expect real sales higher,
# sebcd = expect economy to improve, sxlfch = plans to increase employment,
# snpce = plans to make capital outlays, sxinvch = plans to increase
# inventories, sgtex = now a good time to expand.
SERIES = {
    "exp_sales": "sersale",
    "exp_cond": "sebcd",
    "job_plans": "sxlfch",
    "capex": "snpce",
    "inv_plans": "sxinvch",
    "expand": "sgtex",
}


def parse_month(value: str) -> date:
    try:
        parsed = pd.Timestamp(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Use YYYY-MM-DD."
        ) from exc

    return date(parsed.year, parsed.month, 1)


def fetch_indicators(start: date, end: date) -> list[dict[str, Any]]:
    """Call getIndicators2 once with all six components comma-separated."""
    payload = {
        "app_name": APP_NAME,
        "params": [
            {"name": "minYear", "param_type": "IN", "value": start.year},
            {"name": "minMonth", "param_type": "IN", "value": start.month},
            {"name": "maxYear", "param_type": "IN", "value": end.year},
            {"name": "maxMonth", "param_type": "IN", "value": end.month},
            {"name": "indicator", "param_type": "IN",
             "value": ",".join(SERIES.values())},
        ],
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-DreamFactory-Application-Name": APP_NAME,
    }
    response = requests.post(
        API_URL, json=payload, headers=headers, timeout=TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.json()


def normalize(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert API rows (monthyear + one column per code) into a DataFrame."""
    records = []
    for row in rows:
        raw = row.get("monthyear")
        parsed = pd.to_datetime(raw, errors="coerce") if raw else pd.NaT
        if pd.isna(parsed):
            continue
        rec = {"date": pd.Timestamp(parsed.year, parsed.month, 1)}
        for column, code in SERIES.items():
            rec[column] = pd.to_numeric(row.get(code), errors="coerce")
        records.append(rec)

    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    return (
        frame.groupby("date", as_index=False)
        .last()
        .sort_values("date")
        .reset_index(drop=True)
    )


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

    rows = fetch_indicators(args.start, args.end)
    frame = normalize(rows)

    if frame.empty:
        parser.error("The API returned no rows for the requested range.")

    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
    frame = frame.reindex(columns=["date", *SERIES.keys()]).round(1)

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
    missing = int(frame[list(SERIES)].isna().sum().sum())
    if missing:
        print(
            f"Warning: {missing} missing values preserved as NA.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()