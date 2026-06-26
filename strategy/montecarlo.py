"""
Monte Carlo simulation over OOS trade R-multiples.

Given the actual sequence of R-multiples produced by the walk-forward,
we shuffle them 10,000 times and measure:
  - Max drawdown distribution (5th / 50th / 95th percentile)
  - Probability of hitting a given drawdown threshold
  - Longest losing streak distribution
  - Risk of ruin (equity falling below a threshold)
  - Confidence interval on final equity

This tells you what range of outcomes to expect from variance alone,
independent of whether the future matches the past.
"""

import numpy as np
import pandas as pd
from backtest import Trade


N_SIMS        = 10_000
RUIN_THRESHOLD = 0.20   # 20% drawdown = "ruin" for this analysis
SEED          = 42


def _max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    dd   = (equity - peak) / peak
    return float(dd.min())


def _longest_losing_streak(rs: np.ndarray) -> int:
    best = cur = 0
    for r in rs:
        cur = cur + 1 if r < 0 else 0
        best = max(best, cur)
    return best


def run_montecarlo(trades: list[Trade], account_start: float,
                   risk_pct: float = 0.01) -> dict:
    if len(trades) < 5:
        return {}

    r_multiples = np.array([t.r_multiple for t in trades])
    n           = len(r_multiples)
    rng         = np.random.default_rng(SEED)

    final_equities = np.empty(N_SIMS)
    max_drawdowns  = np.empty(N_SIMS)
    loss_streaks   = np.empty(N_SIMS, dtype=int)

    for i in range(N_SIMS):
        shuffled = rng.permutation(r_multiples)
        equity   = np.empty(n + 1)
        equity[0] = account_start

        for j, r in enumerate(shuffled):
            dollar_pnl    = equity[j] * risk_pct * r
            equity[j + 1] = equity[j] + dollar_pnl

        final_equities[i] = equity[-1]
        max_drawdowns[i]  = _max_drawdown(equity)
        loss_streaks[i]   = _longest_losing_streak(shuffled)

    pct_ruin      = float(np.mean(max_drawdowns <= -RUIN_THRESHOLD)) * 100
    dd_pcts       = np.percentile(max_drawdowns * 100, [5, 25, 50, 75, 95])
    eq_pcts       = np.percentile(final_equities, [5, 25, 50, 75, 95])
    streak_pcts   = np.percentile(loss_streaks, [50, 75, 95])

    # Break-even probability (final equity >= start)
    pct_profitable = float(np.mean(final_equities >= account_start)) * 100

    return {
        'n_trades':         n,
        'n_sims':           N_SIMS,
        'ruin_threshold':   RUIN_THRESHOLD * 100,
        'prob_ruin_pct':    round(pct_ruin, 1),
        'prob_profit_pct':  round(pct_profitable, 1),
        'dd_p5':            round(dd_pcts[0], 1),
        'dd_p25':           round(dd_pcts[1], 1),
        'dd_p50':           round(dd_pcts[2], 1),
        'dd_p75':           round(dd_pcts[3], 1),
        'dd_p95':           round(dd_pcts[4], 1),
        'eq_p5':            round(eq_pcts[0], 2),
        'eq_p25':           round(eq_pcts[1], 2),
        'eq_p50':           round(eq_pcts[2], 2),
        'eq_p75':           round(eq_pcts[3], 2),
        'eq_p95':           round(eq_pcts[4], 2),
        'streak_p50':       int(streak_pcts[0]),
        'streak_p75':       int(streak_pcts[1]),
        'streak_p95':       int(streak_pcts[2]),
        'account_start':    account_start,
    }


def print_montecarlo(label: str, m: dict) -> None:
    if not m:
        print(f"  {label}: not enough trades for simulation (need ≥ 5)")
        return

    print(f"""
  ─── {label} — MONTE CARLO ({m['n_sims']:,} simulations, {m['n_trades']} trades) ───
  Probability of profit        : {m['prob_profit_pct']}%
  Probability of >{m['ruin_threshold']:.0f}% drawdown  : {m['prob_ruin_pct']}%

  Max drawdown range (across all simulations):
    Best  5%  of paths : {m['dd_p5']}%
    25th percentile    : {m['dd_p25']}%
    Median             : {m['dd_p50']}%
    75th percentile    : {m['dd_p75']}%
    Worst 95% of paths : {m['dd_p95']}%

  Final equity range (start: ${m['account_start']:,.0f}):
    5th  percentile    : ${m['eq_p5']:,.2f}
    25th percentile    : ${m['eq_p25']:,.2f}
    Median             : ${m['eq_p50']:,.2f}
    75th percentile    : ${m['eq_p75']:,.2f}
    95th percentile    : ${m['eq_p95']:,.2f}

  Longest losing streak:
    Typical  (p50)     : {m['streak_p50']} losses in a row
    Bad      (p75)     : {m['streak_p75']} losses in a row
    Extreme  (p95)     : {m['streak_p95']} losses in a row""")
