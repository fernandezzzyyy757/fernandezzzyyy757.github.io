# Radar forward test — methodology

This folder is the out-of-sample track record for the morning radar
(`scripts/radar.py`). It exists because backtesting can't prove a strategy
works: a strategy tuned on past data can look great purely by luck. The
fix is to test on data that didn't exist when the picks were made.

## How it works

1. **Record (premarket, ~7:55 AM Central).** The radar runs and its picks
   are written to `signals/YYYY-MM-DD.json` and **committed to git before
   the market opens**. The commit timestamp (visible in the repo history
   and in the GitHub Actions run log) is the proof that nothing was
   back-filled or edited after the fact.
2. **Evaluate (after the close).** Each pick is scored as if bought at the
   official opening price and sold at the close — same day (`1d`) and four
   trading days later (`5d`) — using real daily bars. Every return is
   measured **in excess of SPY** over the identical window: beating the
   market is the bar, not just going up.
3. **Report.** `scoreboard.md` aggregates everything: hit rate, mean
   excess return, a 95% bootstrap confidence interval, and a sign-test
   p-value.

## Why the statistics are done this way

- **One day = one observation.** Five picks made the same morning are
  correlated (they ride the same market). Counting them as five
  independent samples would fake a bigger sample size, so all
  significance math clusters by trading day.
- **No survivorship bias.** Picks that can't be scored (halted, delisted,
  no data) are counted and shown on the scoreboard, never silently
  dropped.
- **No verdict before ~20 pick-days.** With fewer days, any result is
  noise. The scoreboard says "too early" until the sample is real, and
  only claims an edge when the confidence interval excludes zero.

## Reading the verdict

- ⏳ **TOO EARLY** — not enough days yet. Keep collecting.
- ➖ **NO DETECTABLE EDGE YET** — results so far are indistinguishable
  from luck.
- ✅ **EDGE DETECTED** — the radar has beaten SPY by a margin unlikely to
  be luck (95% CI above zero).
- ❌ **NEGATIVE EDGE** — the radar reliably underperforms SPY; trading it
  would cost money.

Nothing here is a promise about the future — regimes change — but it is
an honest, tamper-evident answer to "has this actually worked, on data it
never saw, at real prices?"
