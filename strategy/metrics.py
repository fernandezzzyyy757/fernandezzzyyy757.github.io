import pandas as pd
import numpy as np
from backtest import Trade


def compute_metrics(trades: list[Trade], equity_curve: pd.Series,
                    account_start: float) -> dict:
    if not trades:
        return {'total_trades': 0}

    pnls = [t.pnl for t in trades]
    rs   = [t.r_multiple for t in trades]

    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    win_rate  = len(wins)  / len(trades)
    loss_rate = len(losses) / len(trades)

    avg_win_r  = float(np.mean([t.r_multiple for t in wins]))   if wins   else 0.0
    avg_loss_r = float(np.mean([t.r_multiple for t in losses])) if losses else 0.0

    # Expectancy in R-multiples
    expectancy_r = (win_rate * avg_win_r) + (loss_rate * avg_loss_r)

    # Expectancy in dollars
    avg_win_d  = float(np.mean([t.pnl for t in wins]))   if wins   else 0.0
    avg_loss_d = float(np.mean([t.pnl for t in losses])) if losses else 0.0
    expectancy_d = (win_rate * avg_win_d) + (loss_rate * avg_loss_d)

    gross_wins  = sum(t.pnl for t in wins)
    gross_losses = abs(sum(t.pnl for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')

    # Max drawdown (capped at -100%; negative = loss)
    curve = equity_curve.dropna()
    peak  = curve.cummax()
    dd    = ((curve - peak) / peak).clip(lower=-1.0)
    max_dd = float(dd.min()) * 100

    # Drawdown duration (bars)
    in_dd = dd < 0
    dd_dur = 0
    cur = 0
    for v in in_dd:
        cur = cur + 1 if v else 0
        dd_dur = max(dd_dur, cur)

    # Sharpe (annualised, daily equity returns)
    daily_ret = curve.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)
              if daily_ret.std() > 0 else 0.0)

    # CAGR
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    cagr  = ((curve.iloc[-1] / curve.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else 0.0

    # Calmar (CAGR / max drawdown)
    calmar = abs(cagr / max_dd) if max_dd != 0 else 0.0

    # Break-even win rate for TARGET_RR
    from config import TARGET_RR
    be_wr = 1 / (1 + TARGET_RR) * 100

    return {
        'total_trades':    len(trades),
        'win_rate_pct':    round(win_rate * 100, 1),
        'loss_rate_pct':   round(loss_rate * 100, 1),
        'avg_win_R':       round(avg_win_r, 2),
        'avg_loss_R':      round(avg_loss_r, 2),
        'expectancy_R':    round(expectancy_r, 3),
        'expectancy_$':    round(expectancy_d, 2),
        'profit_factor':   round(profit_factor, 2),
        'gross_profit':    round(gross_wins, 2),
        'gross_loss':      round(-gross_losses, 2),
        'net_pnl':         round(sum(pnls), 2),
        'max_drawdown_pct':round(max_dd, 2),
        'max_dd_dur_bars': dd_dur,
        'sharpe':          round(sharpe, 2),
        'calmar':          round(calmar, 2),
        'cagr_pct':        round(cagr, 2),
        'breakeven_wr_pct':round(be_wr, 1),
        'final_equity':    round(curve.iloc[-1], 2),
        'account_start':   account_start,
    }


def print_metrics(label: str, m: dict) -> None:
    if m.get('total_trades', 0) == 0:
        print(f"  {label}: no trades generated")
        return

    be  = m['breakeven_wr_pct']
    wr  = m['win_rate_pct']
    exp = m['expectancy_R']

    edge = "POSITIVE" if exp > 0 else "NEGATIVE"
    wr_status = "ABOVE B/E" if wr > be else "BELOW B/E"

    print(f"""
  ─── {label} ───────────────────────────────────────
  Trades          : {m['total_trades']}
  Win rate        : {wr}%  ({wr_status}, B/E = {be}%)
  Avg win (R)     : {m['avg_win_R']}
  Avg loss (R)    : {m['avg_loss_R']}
  Expectancy (R)  : {exp}  [{edge} EDGE]
  Expectancy ($)  : ${m['expectancy_$']:,.2f} per trade
  Profit factor   : {m['profit_factor']}
  ───────────────────────────────────────────────
  Net P&L         : ${m['net_pnl']:,.2f}
  CAGR            : {m['cagr_pct']}%
  Max drawdown    : {m['max_drawdown_pct']}%
  Max DD duration : {m['max_dd_dur_bars']} bars
  Sharpe ratio    : {m['sharpe']}
  Calmar ratio    : {m['calmar']}
  ───────────────────────────────────────────────
  Start equity    : ${m['account_start']:,.2f}
  Final equity    : ${m['final_equity']:,.2f}""")
