"""
Parameter sensitivity grid search.

Tests all combinations of key signal parameters on each symbol using the
same walk-forward OOS structure. The goal is NOT to find the best parameters
— it is to check that positive expectancy exists across a range of settings.

If only one narrow setting produces edge, the strategy is likely curve-fit.
Real edge shows up as a cluster of green cells, not a single outlier.
"""

import itertools
import pandas as pd
import numpy as np
from tabulate import tabulate

import config as cfg
from data import fetch_daily, to_weekly
from indicators import add_indicators
from signals import generate_signals
from walk_forward import walk_forward
from backtest import Trade


# Parameter grid — keep small to avoid combinatorial explosion
GRID = {
    'RSI_OVERSOLD':   [35, 40, 45],
    'EMA_FAST':       [15, 20, 25],
    'ATR_STOP_MULT':  [0.25, 0.50, 0.75],
}


def _patch_config(**kwargs) -> None:
    for k, v in kwargs.items():
        setattr(cfg, k, v)


def _restore_config(saved: dict) -> None:
    for k, v in saved.items():
        setattr(cfg, k, v)


def run_sensitivity(symbol: str, df_base: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a DataFrame with one row per parameter combination,
    columns: RSI_OVERSOLD, EMA_FAST, ATR_STOP_MULT, trades, win_rate, expectancy_R.
    """
    saved = {k: getattr(cfg, k) for k in GRID}
    # Also save the RSI_OVERBOUGHT mirror
    saved['RSI_OVERBOUGHT'] = cfg.RSI_OVERBOUGHT

    keys   = list(GRID.keys())
    combos = list(itertools.product(*[GRID[k] for k in keys]))

    rows = []
    for combo in combos:
        params = dict(zip(keys, combo))
        _patch_config(**params)
        # Mirror RSI_OVERBOUGHT so shorts are symmetric
        cfg.RSI_OVERBOUGHT = 100 - params['RSI_OVERSOLD']

        try:
            from indicators import add_indicators as _add
            from signals import generate_signals as _gen
            df = _add(df_base[['open', 'high', 'low', 'close', 'volume']].copy(),
                      df_base[['open', 'high', 'low', 'close', 'volume']].resample('W-FRI').agg({
                          'open': 'first', 'high': 'max',
                          'low':  'min',   'close': 'last', 'volume': 'sum',
                      }).dropna())
            df = _gen(df)
            result  = walk_forward(df, symbol)
            m       = result.get('metrics', {})
            trades  = m.get('total_trades', 0)
            wr      = m.get('win_rate_pct', 0)
            exp_r   = m.get('expectancy_R', 0)
            dd      = m.get('max_drawdown_pct', 0)
        except Exception:
            trades = wr = exp_r = dd = 0

        rows.append({
            'RSI_OS':   params['RSI_OVERSOLD'],
            'EMA_W':    params['EMA_FAST'],
            'ATR_mult': params['ATR_STOP_MULT'],
            'trades':   trades,
            'win%':     wr,
            'exp_R':    exp_r,
            'maxDD%':   dd,
            'edge':     '+' if exp_r > 0 else '-',
        })

    _restore_config(saved)
    return pd.DataFrame(rows)


def print_sensitivity(symbol: str, df_results: pd.DataFrame) -> None:
    total  = len(df_results)
    pos    = (df_results['exp_R'] > 0).sum()
    pct    = round(pos / total * 100, 0) if total > 0 else 0

    print(f"\n  ─── {symbol} — PARAMETER SENSITIVITY ({pos}/{total} combos positive = {pct:.0f}%) ───")

    display = df_results.sort_values('exp_R', ascending=False).copy()
    display['exp_R'] = display['exp_R'].map('{:+.3f}'.format)
    display['maxDD%'] = display['maxDD%'].map('{:.1f}%'.format)

    print(tabulate(display, headers='keys', tablefmt='simple',
                   showindex=False, floatfmt='.2f'))

    if pct >= 70:
        verdict = "ROBUST — edge exists across most parameter settings"
    elif pct >= 40:
        verdict = "MODERATE — edge present but sensitive to parameters"
    else:
        verdict = "FRAGILE — edge depends heavily on specific settings"

    print(f"\n  Verdict: {verdict}")
