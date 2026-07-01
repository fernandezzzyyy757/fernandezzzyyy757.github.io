# Market Bot

Tracks a watchlist of tickers and tells you when something's happening:
a stock moving with fresh news (the "PLTR up 5% premarket, here's why" pattern),
or a ticker reporting earnings today. Runs on a schedule via GitHub Actions,
writes results to `data/latest.json`, and can push alerts to Discord and email.

## How it works

- `fetch.py` calls [Finnhub](https://finnhub.io) (free tier) for each symbol in
  `watchlist.json`: current quote/% change, recent news, and earnings
  calendar/history.
- News headlines are scored locally with VADER sentiment (no extra API/key
  needed) and tagged positive/negative/neutral.
- If a ticker's % change crosses the alert threshold (default 2%) **and** has
  fresh news, or if it reports earnings today, it sends one alert per
  ticker per day to Discord/email (deduped via `data/alert_state.json`).
- `dashboard.html` is a static page that reads `data/latest.json` and renders
  the watchlist, movers, news with sentiment dots, and earnings info.

## One-time setup

1. **Finnhub API key (free)** — sign up at https://finnhub.io/register, copy
   your API key.
2. **Discord alerts (optional)** — in your Discord server: Server Settings →
   Integrations → Webhooks → New Webhook → copy the webhook URL.
3. **Email alerts (optional)** — easiest with Gmail: enable 2FA on the account,
   then create an [App Password](https://myaccount.google.com/apppasswords).
   Use that as `SMTP_PASS` (not your regular password).
4. In the GitHub repo: **Settings → Secrets and variables → Actions** and add:
   - `FINNHUB_API_KEY` (required)
   - `DISCORD_WEBHOOK_URL` (optional, skip to disable Discord alerts)
   - `SMTP_USER`, `SMTP_PASS`, `ALERT_EMAIL_TO` (optional, skip to disable email)
   - `SMTP_HOST` / `SMTP_PORT` only if not using Gmail (defaults to
     `smtp.gmail.com:587`)
   - Optionally add a repo **variable** `MOVE_THRESHOLD_PERCENT` (e.g. `2.0`)
     to change the alert sensitivity.

## Editing your watchlist

Edit `market-bot/watchlist.json` — a plain JSON array of ticker symbols, e.g.:

```json
["PLTR", "NVDA", "AAPL", "TSLA"]
```

## Running it

- **Automatically**: `.github/workflows/market-bot.yml` runs every 15 minutes,
  8:00–20:45 UTC on weekdays (covers US premarket through market close;
  shift by an hour around US clock changes). Scheduled workflows only fire
  from the repo's default branch, so this starts working once this branch
  is merged.
- **Manually**: Actions tab → "Market Bot" → Run workflow.
- **Locally**: `pip install -r market-bot/requirements.txt`, then
  `FINNHUB_API_KEY=xxx python market-bot/fetch.py`.

## Viewing the dashboard

Once published via GitHub Pages, visit:
`https://fernandezzzyyy757.github.io/market-bot/dashboard.html`

(Not linked from the main site nav — it's a separate page you check directly.)

## Limitations

- Finnhub's free tier has rate limits (60 calls/min) and delayed/limited data
  for some endpoints — this is a "heads up something's moving" tool, not a
  broker-grade real-time feed. Always verify before trading.
- Sentiment scoring is a simple lexicon-based heuristic (VADER), not
  financial-specific NLP — treat it as a rough signal, not certainty.
- Nothing here is financial advice.
