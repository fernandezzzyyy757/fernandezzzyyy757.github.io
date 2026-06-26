"""
Usage:
  python main.py                  # all symbols, full run
  python main.py MES              # single symbol
  python main.py MES --no-sens    # skip sensitivity grid (faster)
  python main.py MES --no-mc      # skip Monte Carlo
  python main.py MES --export     # write trade/equity CSVs to ./output/
"""

import sys
import os
import pandas as pd
from tabulate import tabulate

from config import SYMBOLS, ACCOUNT, RISK_PCT, TARGET_RR, IS_YEARS, OOS_MONTHS
from data import fetch_daily, to_weekly
from indicators import add_indicators
from signals import generate_signals
from walk_forward import walk_forward
from metrics import print_metrics, compute_metrics
from backtest import run_backtest
from montecarlo import run_montecarlo, print_montecarlo
from sensitivity import run_sensitivity, print_sensitivity
from export import export_trades, export_equity


def build_df(symbol: str) -> pd.DataFrame:
    print(f"  Downloading {symbol} ({SYMBOLS[symbol]})...")
    daily  = fetch_daily(symbol)
    weekly = to_weekly(daily)
    df     = add_indicators(daily, weekly)
    df     = generate_signals(df)
    return df


def main():
    args       = sys.argv[1:]
    run_sens   = '--no-sens'   not in args
    run_mc     = '--no-mc'     not in args
    do_export  = '--export'    in args
    flags      = {'--no-sens', '--no-mc', '--export'}
    sym_args   = [a for a in args if a not in flags]

    if sym_args:
        target  = sym_args[0].upper()
        symbols = [target] if target in SYMBOLS else list(SYMBOLS.keys())
    else:
        symbols = list(SYMBOLS.keys())

    print()
    print("=" * 62)
    print("  MULTI-TF TREND PULLBACK — FULL ANALYSIS")
    print(f"  Account ${ACCOUNT:,}  |  Risk {RISK_PCT*100}%/trade  |  R:R {TARGET_RR}")
    print(f"  Walk-forward {IS_YEARS}yr IS → {OOS_MONTHS}mo OOS")
    print("=" * 62)

    summary_rows = []

    for sym in symbols:
        print(f"\n{'='*62}")
        print(f"  {sym}")
        print(f"{'='*62}")

        try:
            df = build_df(sym)
        except Exception as e:
            print(f"  Data fetch failed: {e}")
            continue

        # ── OOS walk-forward ─────────────────────────────────────────────
        result = walk_forward(df, sym)
        m      = result.get('metrics', {})
        trades = result.get('trades', [])
        equity = result.get('equity', pd.Series(dtype=float))

        print_metrics(f"{sym} — OOS WALK-FORWARD", m)

        if result.get('windows'):
            headers = ['#', 'IS start', 'IS end', 'OOS end', 'Trades', 'Wins', 'P&L']
            rows = [
                [w['window'], w['is_start'], w['is_end'],
                 w['oos_end'], w['trades'], w['wins'], f"${w['pnl']:,.2f}"]
                for w in result['windows']
            ]
            print()
            print(tabulate(rows, headers=headers, tablefmt='simple'))

        # ── Monte Carlo ───────────────────────────────────────────────────
        if run_mc and trades:
            mc = run_montecarlo(trades, ACCOUNT, RISK_PCT)
            print_montecarlo(sym, mc)

        # ── Parameter sensitivity ─────────────────────────────────────────
        if run_sens:
            print(f"\n  Running sensitivity grid (27 combinations)...")
            sens_df = run_sensitivity(sym, df)
            print_sensitivity(sym, sens_df)

        # ── CSV export ────────────────────────────────────────────────────
        if do_export and trades:
            tp = export_trades(trades, sym, out_dir='output')
            ep = export_equity(equity, sym, out_dir='output')
            print(f"\n  Exported: {tp}")
            print(f"  Exported: {ep}")

        if m.get('total_trades', 0) > 0:
            summary_rows.append([
                sym,
                m['total_trades'],
                f"{m['win_rate_pct']}%",
                f"{m['breakeven_wr_pct']}%",
                f"{m['expectancy_R']:+.3f}R",
                f"{m['max_drawdown_pct']}%",
                f"{m['sharpe']}",
                f"{m['cagr_pct']}%",
                f"${m['net_pnl']:,.2f}",
            ])

    # ── Portfolio summary ─────────────────────────────────────────────────
    if len(symbols) > 1 and summary_rows:
        print(f"\n{'='*62}")
        print("  PORTFOLIO SUMMARY — OOS ONLY")
        print(f"{'='*62}")
        headers = ['Symbol', 'Trades', 'Win%', 'B/E%', 'Exp(R)', 'MaxDD', 'Sharpe', 'CAGR', 'Net P&L']
        print(tabulate(summary_rows, headers=headers, tablefmt='simple'))
        print()


if __name__ == '__main__':
    main()
