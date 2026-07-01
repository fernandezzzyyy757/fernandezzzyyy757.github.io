# Robinhood Premarket Bot

Scans a list of liquid stocks each morning for ones that are moving on fresh,
positive news, proposes **one** all-in trade with its reasoning, and only
buys/sells once you click Approve on a local dashboard.

## Read this before you touch real money

1. **Robinhood has no official public trading API.** This uses
   [`robin_stocks`](https://github.com/jmfernandes/robin_stocks), a
   reverse-engineered client that talks to the same private endpoints as the
   mobile app. That is against Robinhood's Terms of Service. Automating
   premarket trading like this carries real risk of your account being
   flagged, restricted, or closed. There is no way to do this against
   Robinhood "the legal way" today - if that risk is a dealbreaker, the same
   scan/propose/approve flow can be pointed at a broker with an official API
   (e.g. Alpaca) instead, with no ToS risk.
2. **This bot goes all-in on one position.** One bad gap-down or a stock that
   never recovers means a real, concentrated loss. There's no
   diversification here by design (that's what you asked for), so size your
   expectations accordingly.
3. **Start in `DRY_RUN` mode** (the default). The whole pipeline - scan,
   score, propose, "buy", "sell", log - runs normally, but no real order is
   ever sent to Robinhood. Watch it for at least several days and sanity
   check the proposals before setting `DRY_RUN=false` in `.env`.
4. Robinhood only accepts **limit orders** during extended hours
   (premarket 7:00-9:30am ET). The bot buys with a small price buffer above
   the last premarket trade to improve fill odds, but a fast-moving stock can
   still run away from your limit price before it fills.

## Setup

```bash
cd robinhood-premarket-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: Robinhood username/password, Finnhub API key (free at finnhub.io)
```

## Running it

You need two processes running during premarket hours (roughly 7:00am-10:00am ET):

```bash
# terminal 1
python bot.py

# terminal 2
python dashboard.py
```

Then open **http://localhost:5055** in your browser. When the bot finds a
candidate it'll show up there with the ticker, suggested entry time, position
size, and the news/sentiment reasoning behind it. Click **Approve & Buy** to
let it place the order, or **Reject** to skip the day.

After the position fills, the bot waits (default 15 minutes after market
open, configurable) or watches for your profit target / stop loss, then
proposes a sell the same way - approve it on the dashboard to exit.

First login of the day will likely prompt you in the terminal for a
Robinhood SMS/app verification code, since Robinhood requires device
verification for new sessions. After that it caches the session so you won't
be asked every run.

## Tuning it

All the knobs are in `config.py`:

- `DEFAULT_UNIVERSE` - the tickers it's willing to consider. Keep this to
  names you'd actually recognize/trust, since the bot will only ever explain
  its pick in terms of premarket move % + news sentiment, not deep fundamentals.
- `MIN_PREMARKET_MOVE_PCT` / `MAX_PREMARKET_MOVE_PCT` - the move range it
  looks for (default 1.5%-15%, to avoid both noise and overly extended gaps).
- `SCAN_TIME`, `ENTRY_DEADLINE`, `EXIT_CHECK_DELAY_MIN` - the schedule.
- `PROFIT_TARGET_PCT` / `STOP_LOSS_PCT` - optional early-exit triggers.
- `REQUIRE_EXIT_APPROVAL` - set to `False` if you'd rather the bot just sell
  automatically at the exit check instead of asking first.

## How the scan works

For each ticker in the universe it pulls a live quote, recent company news,
and a news-sentiment score from Finnhub, then scores candidates by: how big
the premarket move is (favoring a 2-8% sweet spot over extended gaps), how
bullish the associated news sentiment is, and how much recent coverage there
is. It requires at least one real news item in the last 24h - a price move
with no news behind it is skipped, since the bot needs something to show you
as the "why."

Note: Finnhub's free tier has rate limits and its `quote` endpoint reflects
the latest traded price (which is the premarket price during premarket
hours), but real-time freshness and depth of premarket coverage is better on
paid tiers. Treat the scan as a solid heuristic starting point, not a
guarantee it caught everything moving that morning.

## Files

- `bot.py` - the scheduler/orchestrator loop
- `scanner.py` - Finnhub-based scan + scoring
- `robinhood_client.py` - order placement wrapper (robin_stocks)
- `dashboard.py` + `templates/index.html` - local approval UI
- `state.py` - shared state file between the bot loop and the dashboard
- `config.py` - all tunable settings
