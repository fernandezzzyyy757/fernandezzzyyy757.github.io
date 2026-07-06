# VP Setups — Volume Profile Alert System

One TradingView indicator (`vp-setups.pine`) that watches for the three volume-profile setups and pings Discord with the instrument, setup type, suggested entry, stop, and targets — pre-filtered so most junk never reaches your phone.

| Setup | What fires it | Runs on |
|---|---|---|
| 🟢/🔴 **A — Value-area fade** | Price probes outside yesterday's value area, prints ≥2 rejection wicks on below-average volume, then **closes back inside** | MES / ES |
| 🟠 **B — Naked POC tag** | Price touches a prior-session POC that was never revisited | MES / ES |
| 🔵 **C — LVN break** | Price **closes** into the low-volume shelf on ≥1.5× average volume | MNQ / NQ |

Built-in filters: confirmation closes (never raw touches) · volume signature checks · rejection-wick evidence · trend-day lockout (no fades when the session opens and holds outside value) · alert windows 9:30–11:30 & 14:00–16:00 ET only · ATR-buffered structural stops · skip if stop wider than 1×ATR · skip if reward:risk under 2R · max one alert per setup-side per session.

---

## Step 1 — Discord webhooks (5 min)

Make one channel per setup so the channel name tells you which playbook to open:

1. In your server create `#es-va-fade`, `#es-npoc`, `#nq-lvn-break`.
2. For each: channel **Edit → Integrations → Webhooks → New Webhook → Copy Webhook URL**. Save all three URLs.

## Step 2 — Install the indicator (5 min)

1. Open TradingView → chart **MES1!** (CME Micro E-mini S&P, continuous front month), **5-minute** timeframe.
2. Pine Editor (bottom panel) → paste the whole contents of `vp-setups.pine` → **Add to chart**.
3. You'll see: amber POC line + blue dashed VAH/VAL + shaded value area from the last completed session, dotted amber naked-POC lines, and a gray box on the LVN shelf (when one exists).
4. Indicator settings per chart:

| Chart | A — Fade | B — nPOC | C — LVN |
|---|---|---|---|
| **MES1!** (5m) | ✅ on | ✅ on | ❌ off |
| **MNQ1!** (5m) | ❌ off | ❌ off | ✅ on |

Trading CL later? Add a third chart with B + C on, and mute it Wednesdays around the 10:30 ET inventory report.

> Equities session is the default (09:30–16:15 ET). The script builds profiles from RTH only; overnight volume is ignored on purpose.

## Step 3 — Wire the alerts (5 min)

For **each** chart:

1. Right-click the chart → **Add alert**.
2. **Condition:** `VP Setups` → **Any alert() function call** (this is required — the script writes the message itself).
3. **Expiration:** open-ended / longest available.
4. **Notifications tab:** tick **Webhook URL** and paste that instrument's Discord webhook.
5. Leave the message box alone — the script's own text (with entry/stop/targets) is what gets delivered.

Because MES runs setups A+B on one chart, its alerts share one channel — or duplicate the MES chart with only one setup enabled per chart if you want A and B in separate channels.

**Plan notes:** webhooks need any paid TradingView plan. On the free plan, skip the webhook and tick **Send push notification to app** instead — same alerts, TradingView app instead of Discord.

**Test it:** temporarily set *Minimum reward:risk* to 0 and *Fade: min rejection wicks* to 1, wait for a fire (or use bar replay — markers appear where alerts would fire), confirm the Discord message renders, then restore the settings.

## Step 4 — Tune before trusting (the important one)

Run **bar replay** on a few weeks of MES/MNQ history. The chart prints a label at every would-be alert (`FADE ▲`, `nPOC`, `LVN ▲`, and `FADES OFF — trend day` when the lockout trips). Ask of each marker: *would taking this at the printed stop/target have been sane?* Then tune:

| Too many junk alerts | Missing good moves |
|---|---|
| Raise *min rejection wicks* to 3 | Lower to 1 |
| Raise *LVN break volume* to 2.0× | Lower to 1.2× |
| Raise *minimum R:R* to 2.5 | Lower to 1.5 |
| Lower *trend-day lockout* to 4 bars | Raise to 8 |
| Narrow the alert windows | Widen them |

Defaults are sane starting points, **not** backtested truth.

## What the messages look like

> 🟠 **MES1! — NAKED POC TAG — LONG**
> Tagged untested POC 5842.25 from 2 session(s) ago
> Entry ~5842.25 · Stop 5834.50 · Target 5868.00
> Risk 7.75 · ~3.3R — confirm reaction at the level first

> 🔵 **MNQ1! — LVN BREAK — LONG**
> Closed into the low-volume shelf 21140.00–21195.00 on 1.8× avg volume
> Entry ~21148.75 · Stop 21128.25 · T1 (shelf top) 21195.00 · T2 (HVN) 21242.50
> Risk 20.50 · 4.6R to T2

## Honest limitations

- **The alert is location, not permission.** It means "price is at your level with the right signature." The 30-second check when your phone buzzes — does the reaction match the playbook, is there no news candle — is still your job.
- Profiles are approximated from 5-minute bars (volume spread across each bar's range), not tick data. POC/VA land within a row or two of a tick-built profile — fine for these setups.
- The script tracks the single most prominent LVN shelf per session and up to 12 naked POCs.
- Alerts fire on **bar close**, so entries lag the raw touch by up to one candle. That's the junk filter working as intended.
- It cannot see the news calendar. FOMC days, CPI mornings: mute the channels.
- Nothing here is backtested for profitability or financial advice. Structure-based stops/targets are suggestions; you are the risk manager. Trade micros until the stats say otherwise.

## Files

- `vp-setups.pine` — the indicator (Pine Script v6)
- `README.md` — this guide

If TradingView's compiler flags any line when you paste, note the error message and line number — small syntax nits are quick to fix.
