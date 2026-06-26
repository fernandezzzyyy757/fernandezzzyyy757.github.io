import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta
from backtest import Trade, run_backtest
from metrics import compute_metrics
from config import IS_YEARS, OOS_MONTHS, ACCOUNT


def walk_forward(df: pd.DataFrame, symbol: str) -> dict:
    """
    Roll a fixed IS window forward in OOS_MONTHS steps.
    Strategy parameters are fixed — the walk-forward proves consistency
    across different time regimes, not parameter optimisation.
    All reported metrics come from OOS periods only.
    """
    df = df.dropna()
    start = df.index[0]
    end   = df.index[-1]

    windows     = []
    all_trades: list[Trade] = []
    all_equity_segments: list[pd.Series] = []
    equity = ACCOUNT

    is_start = start
    window_num = 0

    while True:
        is_end  = is_start + relativedelta(years=IS_YEARS)
        oos_end = is_end   + relativedelta(months=OOS_MONTHS)

        if oos_end > end:
            break
        if is_end not in df.index:
            is_end = df.index[df.index.searchsorted(is_end)]
        if oos_end not in df.index:
            oos_end = df.index[min(df.index.searchsorted(oos_end), len(df.index) - 1)]

        oos_df = df.loc[is_end:oos_end].copy()
        if len(oos_df) < 10:
            break

        window_num += 1
        trades, eq_curve = run_backtest(oos_df, symbol, equity)

        window_pnl = sum(t.pnl for t in trades)
        if eq_curve.dropna().shape[0] > 0:
            equity = eq_curve.dropna().iloc[-1]

        all_trades.extend(trades)
        all_equity_segments.append(eq_curve)

        windows.append({
            'window':    window_num,
            'is_start':  is_start.date(),
            'is_end':    is_end.date(),
            'oos_start': is_end.date(),
            'oos_end':   oos_end.date(),
            'trades':    len(trades),
            'wins':      sum(1 for t in trades if t.pnl > 0),
            'pnl':       round(window_pnl, 2),
        })

        is_start += relativedelta(months=OOS_MONTHS)

    if not all_equity_segments:
        return {'symbol': symbol, 'windows': [], 'metrics': {}, 'trades': []}

    combined_equity = pd.concat(all_equity_segments).sort_index()
    combined_equity = combined_equity[~combined_equity.index.duplicated(keep='last')]

    metrics = compute_metrics(all_trades, combined_equity, ACCOUNT)

    return {
        'symbol':  symbol,
        'windows': windows,
        'metrics': metrics,
        'equity':  combined_equity,
        'trades':  all_trades,
    }
