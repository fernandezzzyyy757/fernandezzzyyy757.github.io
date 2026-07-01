# Project notes / where we left off

Context for picking this back up in a fresh session (e.g. on your own PC),
even without the original chat history.

## What this is

An agentic bot that scans the market premarket for stocks moving on fresh
positive news, proposes a single all-in trade (ticker, entry time, reasoning,
position size) on a local dashboard, and only trades once you click Approve.
Same flow for the exit (sell a bit after open).

Origin case: user's PLTR trade on 2026-07-01 - bought ~9:15 premarket on
positive news (Nvidia sovereign AI deal, CNBC Karp interview, etc.), held to
~9:40, +2%. This bot automates finding/proposing that kind of setup daily.

## Key decisions already made (don't re-ask these)

- **Broker: Robinhood**, via the unofficial `robin_stocks` library. User was
  told this violates Robinhood's ToS and risks account restriction, and
  explicitly chose it anyway over the ToS-safe alternative (Alpaca).
- **Approval channel: local web dashboard** (Flask, `http://localhost:5055`),
  not Telegram/SMS/email.
- **Hosting: user's own computer**, run on-demand during premarket hours, not
  a cloud VPS/always-on server.
- **Scanning: Finnhub API** (quotes + company news + news-sentiment) over a
  configurable ticker universe, not a fixed single-ticker watchlist.
- **Sizing: all-in** - full buying power into one position, one trade at a
  time, no diversification (intentional, per user's actual trading style).
- **Safety default: `DRY_RUN=true`** - full pipeline runs, no real orders,
  until user flips it in `.env` after watching it for a while.
- Exit is also approval-gated by default (`REQUIRE_EXIT_APPROVAL=True` in
  `config.py`), with optional profit-target/stop-loss/time-based auto-trigger
  of the *proposal* (not auto-execution).

## Status as of last session

All core files written and smoke-tested (py_compile clean, dashboard render
+ approve flow tested locally with a fake proposal). Not yet run against
real Finnhub data or a real Robinhood login. Not yet run for a live/dry-run
full trading day.

## Not done yet / open follow-ups

- Haven't tested a real end-to-end scan against live Finnhub data (needs a
  real `FINNHUB_API_KEY`).
- Haven't tested real Robinhood login/MFA flow via `robin_stocks` (needs
  real credentials, and will prompt interactively for an SMS/app code).
- User hasn't yet decided whether they want a fixed-watchlist mode (just
  their specific tickers) instead of the ~60-stock `DEFAULT_UNIVERSE` scan -
  this was offered as a next step but not confirmed.
- `config.py` thresholds (`MIN_PREMARKET_MOVE_PCT`, profit target, stop
  loss, exit delay, etc.) are reasonable defaults, not tuned/backtested.

## Where things live

See `README.md` in this folder for setup/run instructions and the full ToS
risk disclosure. Code: `bot.py` (orchestrator), `scanner.py` (Finnhub scan +
scoring), `robinhood_client.py` (order placement), `dashboard.py` +
`templates/index.html` (approval UI), `state.py` (shared state file),
`config.py` (all tunables).
