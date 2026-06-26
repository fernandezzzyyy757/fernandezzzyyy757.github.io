import sys
import pandas as pd
from tabulate import tabulate

from config import SYMBOLS, ACCOUNT, RISK_PCT, TARGET_RR, IS_YEARS, OOS_MONTHS
from data import fetch_daily, to_weekly
from indicators import add_indicators
from signals import generate_signals
from walk_forward import walk_forward
from metrics import print_metrics, compute_metrics
from backtest import run_backtest


def build_df(symbol: str) -> pd.DataFrame:
    print(f"  Downloading {symbol} ({SYMBOLS[symbol]})...")
    daily  = fetch_daily(symbol)
    weekly = to_weekly(daily)
    df     = add_indicators(daily, weekly)
    df     = generate_signals(df)
    return df


def run_full_backtest(symbol: str, df: pd.DataFrame) -> None:
    trades, equity = run_backtest(df.dropna(), symbol, ACCOUNT)
    m = compute_metrics(trades, equity, ACCOUNT)
    print_metrics(f"{symbol} — FULL IN-SAMPLE", m)


def run_oos(symbol: str, df: pd.DataFrame) -> dict:
    result = walk_forward(df, symbol)
    m = result['metrics']
    print_metrics(f"{symbol} — OOS WALK-FORWARD (reported periods only)", m)

    if result['windows']:
        headers = ['#', 'IS start', 'IS end', 'OOS end', 'Trades', 'Wins', 'P&L ($)']
        rows = [
            [w['window'], w['is_start'], w['is_end'],
             w['oos_end'], w['trades'], w['wins'],
             f"${w['pnl']:,.2f}"]
            for w in result['windows']
        ]
        print()
        print(tabulate(rows, headers=headers, tablefmt='simple'))

    return result


def main():
    print()
    print("=" * 60)
    print("  MULTI-TF TREND PULLBACK STRATEGY")
    print(f"  Account: ${ACCOUNT:,}  |  Risk/trade: {RISK_PCT*100}%  |  Target R:R: {TARGET_RR}")
    print(f"  Walk-forward: {IS_YEARS}yr IS → {OOS_MONTHS}mo OOS windows")
    print("=" * 60)

    target = sys.argv[1].upper() if len(sys.argv) > 1 else None
    symbols = [target] if target and target in SYMBOLS else list(SYMBOLS.keys())

    summary_rows = []

    for sym in symbols:
        print(f"\n{'='*60}")
        print(f"  {sym}")
        print(f"{'='*60}")
        try:
            df = build_df(sym)
        except Exception as e:
            print(f"  Data fetch failed: {e}")
            continue

        result = run_oos(sym, df)
        m = result.get('metrics', {})
        if m.get('total_trades', 0) > 0:
            summary_rows.append([
                sym,
                m['total_trades'],
                f"{m['win_rate_pct']}%",
                f"{m['expectancy_R']}R",
                f"{m['max_drawdown_pct']}%",
                f"{m['sharpe']}",
                f"{m['cagr_pct']}%",
                f"${m['net_pnl']:,.2f}",
            ])

    if len(symbols) > 1 and summary_rows:
        print(f"\n{'='*60}")
        print("  PORTFOLIO SUMMARY — OOS ONLY")
        print(f"{'='*60}")
        headers = ['Symbol', 'Trades', 'Win%', 'Exp(R)', 'MaxDD', 'Sharpe', 'CAGR', 'Net P&L']
        print(tabulate(summary_rows, headers=headers, tablefmt='simple'))
        print()


if __name__ == '__main__':
    main()
