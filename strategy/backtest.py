import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from config import RISK_PCT, TARGET_RR, MAX_HOLD, COMMISSION, SLIPPAGE_PTS, ATR_STOP_MULT, POINT_VALUE


@dataclass
class Trade:
    symbol:      str
    direction:   str
    entry_date:  pd.Timestamp
    entry_price: float
    stop:        float
    target:      float
    size:        float = 0.0        # contracts
    exit_date:   Optional[pd.Timestamp] = None
    exit_price:  Optional[float]   = None
    exit_reason: Optional[str]     = None
    pnl:         float = 0.0       # net $
    r_multiple:  float = 0.0


def _close_trade(trade: Trade, exit_price: float, date: pd.Timestamp,
                 reason: str, point_val: float) -> Trade:
    trade.exit_date   = date
    trade.exit_reason = reason

    if trade.direction == 'long':
        gross  = (exit_price - trade.entry_price) * trade.size * point_val
        r_mult = (exit_price - trade.entry_price) / (trade.entry_price - trade.stop)
    else:
        gross  = (trade.entry_price - exit_price) * trade.size * point_val
        r_mult = (trade.entry_price - exit_price) / (trade.stop - trade.entry_price)

    trade.exit_price = exit_price
    trade.pnl        = gross - COMMISSION * trade.size
    trade.r_multiple = r_mult
    return trade


def run_backtest(df: pd.DataFrame, symbol: str,
                 account_start: float) -> tuple[list[Trade], pd.Series]:
    point_val = POINT_VALUE[symbol]
    trades: list[Trade] = []
    equity = account_start
    equity_curve = pd.Series(np.nan, index=df.index, dtype=float)
    active: Optional[Trade] = None
    bars_held = 0
    rows = list(df.iterrows())

    for i, (date, row) in enumerate(rows):
        equity_curve[date] = equity

        # ── Manage open position ──────────────────────────────────────────
        if active is not None:
            bars_held += 1
            lo, hi = row['low'], row['high']

            if active.direction == 'long':
                if lo <= active.stop:
                    # Could gap through stop; use stop price (not low)
                    fill = active.stop - SLIPPAGE_PTS
                    active = _close_trade(active, fill, date, 'stop', point_val)
                    equity += active.pnl
                    trades.append(active)
                    active = None; bars_held = 0
                    continue
                elif hi >= active.target:
                    fill = active.target - SLIPPAGE_PTS
                    active = _close_trade(active, fill, date, 'target', point_val)
                    equity += active.pnl
                    trades.append(active)
                    active = None; bars_held = 0
                    continue
            else:  # short
                if hi >= active.stop:
                    fill = active.stop + SLIPPAGE_PTS
                    active = _close_trade(active, fill, date, 'stop', point_val)
                    equity += active.pnl
                    trades.append(active)
                    active = None; bars_held = 0
                    continue
                elif lo <= active.target:
                    fill = active.target + SLIPPAGE_PTS
                    active = _close_trade(active, fill, date, 'target', point_val)
                    equity += active.pnl
                    trades.append(active)
                    active = None; bars_held = 0
                    continue

            if bars_held >= MAX_HOLD:
                fill = row['close']
                active = _close_trade(active, fill, date, 'time', point_val)
                equity += active.pnl
                trades.append(active)
                active = None; bars_held = 0
            continue

        # ── Check for new entry (need a next bar to fill) ─────────────────
        if i >= len(rows) - 1:
            continue

        next_date, next_row = rows[i + 1]

        if row['long_signal']:
            entry = next_row['open'] + SLIPPAGE_PTS
            stop  = row['swing_lo'] - ATR_STOP_MULT * row['atr']
            risk  = entry - stop
            if risk <= 0:
                continue
            target = entry + TARGET_RR * risk
            risk_dollars = equity * RISK_PCT
            size = risk_dollars / (risk * point_val)
            if size < 1.0:
                continue   # can't size properly — skip rather than over-risk
            size = float(int(size))   # floor to whole contracts
            active = Trade(
                symbol=symbol, direction='long',
                entry_date=next_date, entry_price=entry,
                stop=stop, target=target, size=size,
            )
            bars_held = 0

        elif row['short_signal']:
            entry = next_row['open'] - SLIPPAGE_PTS
            stop  = row['swing_hi'] + ATR_STOP_MULT * row['atr']
            risk  = stop - entry
            if risk <= 0:
                continue
            target = entry - TARGET_RR * risk
            risk_dollars = equity * RISK_PCT
            size = risk_dollars / (risk * point_val)
            if size < 1.0:
                continue   # can't size properly — skip rather than over-risk
            size = float(int(size))
            active = Trade(
                symbol=symbol, direction='short',
                entry_date=next_date, entry_price=entry,
                stop=stop, target=target, size=size,
            )
            bars_held = 0

    equity_curve = equity_curve.ffill()
    return trades, equity_curve
