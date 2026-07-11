#!/usr/bin/env python3
"""
Pull MNQ continuous front-month 1-minute OHLCV from Databento (GLBX.MDP3) and
save it in the format backtest/mnq_footprint_backtest.py expects
(data/mnq_1m.csv, naive UTC timestamps -> run the backtest with --tz UTC).

Auth: set DATABENTO_API_KEY (or pass --key). Get a key + free credits at
https://databento.com (the $125 signup credit covers years of ohlcv-1m).

Requires: pip install databento

Usage:
    export DATABENTO_API_KEY=db-XXXX...
    python backtest/pull_databento.py                    # last 2 years, cost preflight + confirm
    python backtest/pull_databento.py --start 2024-01-01 --end 2026-07-10 --yes
    python backtest/pull_databento.py --roll v           # volume-based roll instead of calendar

Notes:
  - Symbol is the continuous front month: MNQ.c.0 (calendar roll) or MNQ.v.0
    (volume roll, --roll v). The splice is UNADJUSTED - fine for this backtest
    since positions are intraday-only, but the session volume profile on roll
    days mixes two contracts' prices; expect a handful of odd profile days per
    year.
  - The script prints the estimated cost from the metadata API and asks for
    confirmation before spending credits (skip with --yes).
  - Databento ohlcv-1m timestamps (ts_event) are the bar OPEN time in UTC,
    which is exactly what the backtest's loader assumes.
"""

from __future__ import annotations

import argparse
import os
import sys

try:
    import databento as db
except ImportError:
    sys.exit("missing dependency. Run: pip install databento")

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--key", default=os.environ.get("DATABENTO_API_KEY"))
    ap.add_argument("--start", default=None, help="YYYY-MM-DD (default: end - 730 days)")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--roll", choices=["c", "v"], default="c",
                    help="continuous roll rule: c=calendar (default), v=volume")
    ap.add_argument("--out", default="data/mnq_1m.csv")
    ap.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    args = ap.parse_args()

    if not args.key:
        sys.exit("No API key. Set DATABENTO_API_KEY or pass --key db-XXXX...")

    import pandas as pd
    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.utcnow().tz_localize(None).normalize()
    start = pd.Timestamp(args.start) if args.start else end - pd.Timedelta(days=730)
    symbol = f"MNQ.{args.roll}.0"
    print(f"{DATASET} {SCHEMA} {symbol}: {start.date()} -> {end.date()}")

    client = db.Historical(args.key)
    req = dict(dataset=DATASET, symbols=[symbol], stype_in="continuous",
               schema=SCHEMA, start=start.strftime("%Y-%m-%d"),
               end=end.strftime("%Y-%m-%d"))

    try:
        cost = client.metadata.get_cost(**req)
        print(f"Estimated cost: ${cost:.2f}")
    except Exception as e:  # cost preflight is best-effort
        print(f"(cost preflight failed: {e})")
        cost = None
    if not args.yes:
        ans = input("Proceed with download? [y/N] ").strip().lower()
        if ans != "y":
            sys.exit("aborted")

    print("Downloading ...")
    data = client.timeseries.get_range(**req)
    df = data.to_df()          # tz-aware UTC index (ts_event = bar open), float prices
    if df.empty:
        sys.exit("No data returned - check the date range and symbol.")

    out = df[["open", "high", "low", "close", "volume"]].copy()
    out.insert(0, "timestamp", out.index.tz_convert("UTC").tz_localize(None)
               .strftime("%Y-%m-%d %H:%M:%S"))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    out.to_csv(args.out, index=False)

    print(f"\nWrote {len(out):,} bars to {args.out}")
    print(f"Span: {out['timestamp'].iloc[0]} -> {out['timestamp'].iloc[-1]} UTC")
    print(f"\nNext: python backtest/mnq_footprint_backtest.py --csv {args.out} --tz UTC")


if __name__ == "__main__":
    main()
