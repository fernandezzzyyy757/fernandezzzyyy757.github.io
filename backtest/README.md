# MNQ "institutional footprint" backtest

Event-driven backtest of a sweep → displacement → FVG reversion strategy on
MNQ, with volume-profile and delta-proxy confluence filters, an A/B/C/D
ablation, and a bootstrap validation harness. Signals are detected on a 5-minute
structure timeframe; fills, stops and targets are simulated bar-by-bar on
1-minute data.

## Run

```bash
pip install pandas numpy

# smoke test on synthetic MNQ-like data (no edge expected; validates the harness)
python backtest/mnq_footprint_backtest.py --synthetic --days 130

# real data
python backtest/mnq_footprint_backtest.py --csv path/to/mnq_1m.csv --tz UTC
```

## Getting data

Two pullers write `data/mnq_1m.csv` in the expected format (naive UTC
timestamps; run the backtest with `--tz UTC`):

```bash
# Tradovate (same credentials as an API webhook bot; needs CME data + API access)
pip install requests websockets
export TRADOVATE_USER=... TRADOVATE_PASS=... TRADOVATE_CID=... TRADOVATE_SEC=...
python backtest/pull_tradovate.py            # pages back until end-of-history

# Databento fallback (GLBX.MDP3, MNQ continuous front month, ohlcv-1m)
pip install databento
export DATABENTO_API_KEY=db-XXXX
python backtest/pull_databento.py            # cost preflight + confirm, ~2y default
```

The Tradovate puller reports the downloaded span and warns if it is under 60
days (too shallow for a meaningful 70/30 split — use the Databento puller
instead). It also preserves Tradovate's real `up_volume`/`down_volume` split
in extra columns; the backtest ignores them today but they could replace the
tick-rule delta proxy with real delta.

CSV format: `timestamp,open,high,low,close,volume`, 1-minute bars. Naive
timestamps are localized with `--tz` (default UTC) and converted to ET
internally; tz-aware timestamps are used as-is. Data should ideally cover the
full Globex session (18:00 ET onward) so the developing volume profile and
session cumulative delta are meaningful — RTH-only data will work but the
profile then starts at 09:30.

Outputs to `backtest/out/`: `report.md` plus `trades_{A,B,C,D}.csv`.

## Strategy rules implemented

Long side shown; shorts are fully mirrored.

1. **Liquidity sweep** — price takes out the most recent confirmed swing low
   (20-bar lookback, 3-bar pivot each side) by ≥ 2 ticks, then closes back
   above it within 3 bars.
2. **Displacement** — within 5 bars of the reclaim: range ≥ 1.5 × ATR(14),
   close in the top 30% of the bar, and the bar creates a bullish FVG
   (3-bar gap, confirmed at the close of the following bar).
3. **Entry** — resting limit at 50% of the FVG, or market entry on iFVG
   (a bearish FVG ≤ 30 bars old is inverted by a close through its top while
   the setup is pending). Pending orders expire after 12 signal bars, at the
   entry-window close, or if price trades through the stop before the fill.
4. **Confluence (variants B/D)** — the FVG must overlap a session
   volume-profile LVN (local-minimum bin with volume < 35% of the mean
   non-empty bin). "Below developing POC" is enforced structurally in *all*
   variants because the developing POC is T1 — setups without ≥ 2 ticks of
   room to T1 are discarded everywhere (`room✗` in the diagnostics).
5. **Delta proxy (variants C/D)** — tick-rule delta on 1m closes (+volume on
   uptick, −volume on downtick, carry on unchanged). Require **divergence**
   (price new low at the sweep, cumulative delta higher low vs the pivot bar)
   OR **flip** (session-anchored cumulative delta ≤ 0 at the sweep and > 0 at
   the displacement close). Note: the literal reading "per-bar delta positive
   on the displacement bar" is vacuous — a bar closing in its top 30% has
   positive per-bar delta by construction under any per-bar proxy — so the
   flip is defined on session cumulative delta, which actually discriminates
   (see the `div✓`/`flip✓` columns in the diagnostics funnel).

### Risk / execution

- Stop: 2 ticks beyond the FVG boundary. T1 = developing POC at setup time
  (half off, stop to breakeven). T2 = developing value-area edge (VAH for
  longs, VAL for shorts; if VA is degenerate the runner exits at T1).
- 2 contracts per trade so "50% off" is a whole contract. R is computed
  against the initial stop for the full position, net of costs.
- Max 3 trades/day; entries only 09:30–11:30 and 13:30–15:30 ET; flat by
  16:55 ET. Sessions roll at 18:00 ET (profile, delta anchor, day counters).
- Costs: $0.52 round-turn commission per contract + 1 tick adverse slippage
  charged on **every** fill, including limit fills (deliberately
  conservative).
- Conservative intrabar assumptions: stop before target when both are touched
  in one 1m bar; a fill bar that also touches the stop is an immediate loss.

### Ablation

| variant | filters |
|---|---|
| A | sweep + displacement + FVG entry only |
| B | A + LVN overlap |
| C | A + delta divergence/flip |
| D | B + C (full stack) |

### Validation

- 70/30 chronological train/test split by session.
- Per variant and segment: trades, win%, avg R, expectancy ($/trade), max
  drawdown ($, trade-sequence equity), profit factor — all net of costs.
- Bootstrap 95% CI on expectancy (R), 10,000 resamples; variants whose CI
  includes zero are flagged ⚠️.
- A diagnostics funnel shows where setups die per variant (window, room,
  LVN, delta, busy, day-cap) and the unconditional pass rates of each
  confluence condition.

`report_synthetic_example.md` is a committed example run
(`--synthetic --days 130 --seed 7`). As expected on synthetic data with no
injected edge, every variant's CI includes zero — a useful null test that the
harness doesn't manufacture significance.

## Knobs

All parameters live in the `Config` dataclass (pivot strength, lookback,
displacement multiple, LVN threshold, bin size, TTLs, windows, costs).
CLI: `--signal-tf {1min,3min,5min}`, `--bin-size`, `--seed`, `--out`.
