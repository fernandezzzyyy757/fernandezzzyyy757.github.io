# Gold Futures Proxy Order-Flow Bot

Polls delayed 1-minute bars for the gold futures continuous contract (`GC=F`)
from Yahoo Finance, computes proxy order-flow metrics, and posts a Discord
alert when a setup fires.

## Important limitation

This uses **free OHLCV bar data**, not a real Level 2/depth-of-market feed.
There is no true bid/ask-tagged trade data here, so:

- "Delta" is *approximated* from where each bar's close sits within its
  high/low range (a Chaikin/Twiggs-style proxy), not actual buy-vs-sell
  executed volume.
- Data is delayed (commonly 10-20 minutes for CME futures via Yahoo).
- There's no real DOM, no tape, no iceberg/absorption detection based on
  actual resting orders.

Treat alerts as a rough directional-pressure heuristic for further manual
chart review -- not a substitute for a real footprint/DOM tool. If you later
get access to a real depth feed (Databento, Rithmic, CQG, Sierra Chart DTC,
etc.), swap out `data_feed.py` for a proper bid/ask trade feed and the delta
math becomes exact instead of approximate.

## Setup

```bash
cd orderflow-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:
- `DISCORD_WEBHOOK_URL`: Discord server -> Settings -> Integrations ->
  Webhooks -> New Webhook -> Copy Webhook URL.
- `TICKER`: defaults to `GC=F` (COMEX gold continuous contract). Use `MGC=F`
  if Yahoo has separate micro gold data for your needs.
- `POLL_INTERVAL_SECONDS`, `LOOKBACK_BARS`: adjust polling cadence and how
  much history feeds the rolling calculations.

Tune the signal thresholds in `config.py` (percentiles for "high volume",
"tight range", "extreme delta", proximity to VPOC/round numbers, etc.) to
match how often you want alerts to fire.

## Run

```bash
python3 main.py
```

Runs forever, polling on the configured interval. Use a process manager
(systemd, pm2, tmux, or a cron-launched supervisor) to keep it alive on a
server, since GitHub Pages (or any static host) can't run this for you.

## Signals detected

- **Absorption**: tight-range, high-volume bar sitting at the rolling VPOC
  or a round-number level -- size being absorbed without price follow-through.
- **Exhaustion**: an extreme delta print capping a multi-bar directional run
  -- a possible climax before reversal.
- **Bullish/bearish divergence**: price makes a new local high/low that
  cumulative delta doesn't confirm.
