#!/usr/bin/env python3
"""Forward-testing harness for the radar: record picks before the open,
score them after the close, and keep an honest running scoreboard.

Backtests can't prove the radar works — a strategy fitted to the past can
look great by luck. This harness does the only test that counts:

  record    premarket, run the radar and write today's picks to
            data/signals/YYYY-MM-DD.json. The file is committed by GitHub
            Actions, so the commit timestamp proves the picks existed
            before the market opened. No retroactive edits possible.
  evaluate  after the close, fetch real daily bars and score every pick:
            buy at the official open, measure open->close (1d) and
            open->close four trading days later (5d), minus SPY over the
            same window (the "excess" return — beating SPY is the bar).
  report    aggregate everything into data/scoreboard.md with hit rate,
            mean excess return, a bootstrap confidence interval, and a
            sign-test p-value. Same-day picks are correlated, so all
            significance math treats one trading DAY as one observation,
            not one pick. The verdict stays "too early" until there are
            at least MIN_DAYS_FOR_VERDICT days of picks.

Usage: python3 scripts/validate.py [auto|record|evaluate|report]
  auto (default) picks the mode from the Central-time clock; the GitHub
  cron fires it in the premarket and after-close windows.

Environment:
  DISCORD_WEBHOOK_URL  optional; weekly scoreboard post (Fridays)
  FORCE=1              ignore time gates (manual runs)
"""

import json
import math
import os
import random
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import radar  # noqa: E402
import stock_report  # noqa: E402

CENTRAL = ZoneInfo("America/Chicago")
EASTERN = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
SIGNALS_DIR = ROOT / "data" / "signals"
SCOREBOARD = ROOT / "data" / "scoreboard.md"

BENCHMARK = "SPY"
HORIZONS = {"1d": 0, "5d": 4}  # exit at close N trading days after entry
MISSING_GRACE_DAYS = 10        # trading days before a no-data pick is written off
MIN_DAYS_FOR_VERDICT = 20      # distinct pick-days before any verdict
BOOTSTRAP_N = 5000

BARS_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?range=6mo&interval=1d"
)


# ---------------------------------------------------------------- market data

def daily_bars(symbol, now_utc, fetch=radar.get_json):
    """Completed daily bars as [{date, open, close}], oldest first.

    Today's bar is dropped while the regular session is still open, so a
    forced midday evaluation can never score against a half-finished candle.
    """
    data = fetch(BARS_URL.format(symbol=symbol))
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        return []
    quote = ((result[0].get("indicators") or {}).get("quote") or [{}])[0]
    stamps = result[0].get("timestamp") or []
    opens, closes = quote.get("open") or [], quote.get("close") or []
    now_ny = now_utc.astimezone(EASTERN)
    session_open = now_ny.weekday() < 5 and (9, 30) <= (now_ny.hour, now_ny.minute) < (16, 5)
    bars = []
    for i, ts in enumerate(stamps):
        if i >= len(opens) or opens[i] is None or closes[i] is None:
            continue
        day = datetime.fromtimestamp(ts, tz=EASTERN).date().isoformat()
        if session_open and day == now_ny.date().isoformat():
            continue
        bars.append({"date": day, "open": float(opens[i]), "close": float(closes[i])})
    return bars


def bar_index(bars, day_iso):
    """Index of the first bar on or after day_iso, or None."""
    for i, bar in enumerate(bars):
        if bar["date"] >= day_iso:
            return i
    return None


# --------------------------------------------------------------------- record

def record(now_utc, force=False):
    now_ct = now_utc.astimezone(CENTRAL)
    in_window = now_ct.weekday() < 5 and (7, 30) <= (now_ct.hour, now_ct.minute) < (8, 25)
    if not in_window and not force:
        print(f"record: outside premarket window ({now_ct:%a %H:%M %Z}); skipping.")
        return False
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    path = SIGNALS_DIR / f"{now_ct.date().isoformat()}.json"
    if path.exists():
        print(f"record: {path.name} already recorded; skipping.")
        return False

    headlines, errors = stock_report.gather_headlines(now_utc)
    for err in errors:
        print(f"record: feed error: {err}", file=sys.stderr)
    picks = radar.build_radar(headlines, now_utc)
    entry = {
        "date": now_ct.date().isoformat(),
        "recorded_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "picks": [
            {
                "symbol": p["symbol"],
                "score": round(p["score"], 1),
                "bull_ratio": round(p["bull_ratio"], 3),
                "votes": p["votes"],
                "mentions": p["mentions"],
                "signal_price": p["price"],
                "signal_gap_pct": round(p["gap_pct"], 2) if p["gap_pct"] is not None else None,
            }
            for p in picks
        ],
        "complete": not picks,  # a no-pick day needs no evaluation
    }
    path.write_text(json.dumps(entry, indent=2) + "\n")
    print(f"record: wrote {path.name} with {len(picks)} pick(s).")
    return True


# ------------------------------------------------------------------- evaluate

def evaluate(now_utc):
    if not SIGNALS_DIR.is_dir():
        print("evaluate: no signals recorded yet.")
        return False
    bench_bars = daily_bars(BENCHMARK, now_utc)
    if not bench_bars:
        print("evaluate: benchmark bars unavailable; try again later.", file=sys.stderr)
        return False
    bars_cache = {BENCHMARK: bench_bars}
    changed_any = False

    for path in sorted(SIGNALS_DIR.glob("*.json")):
        entry = json.loads(path.read_text())
        if entry.get("complete"):
            continue
        idx0 = bar_index(bench_bars, entry["date"])
        if idx0 is None:
            continue  # entry day hasn't traded yet
        entry_date = bench_bars[idx0]["date"]
        changed = entry.get("entry_date") != entry_date
        entry["entry_date"] = entry_date

        pending = False
        for pick in entry["picks"]:
            if pick.get("missing"):
                continue
            outcomes = pick.setdefault("outcomes", {})
            symbol = pick["symbol"]
            if symbol not in bars_cache:
                try:
                    bars_cache[symbol] = daily_bars(symbol, now_utc)
                except Exception as exc:  # noqa: BLE001
                    print(f"evaluate: bars {symbol} failed: {exc}", file=sys.stderr)
                    bars_cache[symbol] = None
            bars = bars_cache[symbol]
            if bars is None:  # transient fetch failure: retry next run
                pending = True
                continue
            pidx = next((i for i, b in enumerate(bars) if b["date"] == entry_date), None)
            if pidx is None:
                # No bar on the entry day. Give it a grace period (data can
                # lag), then write it off — but keep it in the file so the
                # report can count exclusions instead of hiding them.
                if idx0 + MISSING_GRACE_DAYS < len(bench_bars):
                    pick["missing"] = True
                    pick["missing_reason"] = f"no daily bar on {entry_date}"
                    changed = True
                else:
                    pending = True
                continue
            for name, offset in HORIZONS.items():
                if name in outcomes:
                    continue
                if pidx + offset >= len(bars) or idx0 + offset >= len(bench_bars):
                    pending = True
                    continue
                exit_bar, bench_exit = bars[pidx + offset], bench_bars[idx0 + offset]
                ret = exit_bar["close"] / bars[pidx]["open"] - 1
                bench_ret = bench_exit["close"] / bench_bars[idx0]["open"] - 1
                outcomes[name] = {
                    "entry_open": round(bars[pidx]["open"], 4),
                    "exit_close": round(exit_bar["close"], 4),
                    "exit_date": exit_bar["date"],
                    "ret_pct": round(ret * 100, 3),
                    "bench_ret_pct": round(bench_ret * 100, 3),
                    "excess_pct": round((ret - bench_ret) * 100, 3),
                }
                changed = True

        if not pending:
            entry["complete"] = True
            changed = True
        if changed:
            path.write_text(json.dumps(entry, indent=2) + "\n")
            changed_any = True
            print(f"evaluate: updated {path.name}")
    if not changed_any:
        print("evaluate: nothing new to score.")
    return changed_any


# --------------------------------------------------------------------- report

def bootstrap_ci(values, n_boot=BOOTSTRAP_N, alpha=0.05):
    """Percentile bootstrap CI for the mean; seeded so reruns match."""
    rng = random.Random(0)
    n = len(values)
    means = sorted(
        sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot)
    )
    return means[int(n_boot * alpha / 2)], means[int(n_boot * (1 - alpha / 2)) - 1]


def sign_test_p(wins, n):
    """Exact two-sided binomial test against a 50% coin."""
    cdf = lambda k: sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n  # noqa: E731
    return min(1.0, 2 * min(cdf(wins), 1 - cdf(wins - 1)))


def collect_stats():
    """Per-horizon stats over every evaluated pick, clustered by day."""
    stats = {name: {"picks": [], "by_day": {}} for name in HORIZONS}
    n_missing = n_pending = n_days_recorded = 0
    if SIGNALS_DIR.is_dir():
        for path in sorted(SIGNALS_DIR.glob("*.json")):
            entry = json.loads(path.read_text())
            if entry["picks"]:
                n_days_recorded += 1
            for pick in entry["picks"]:
                if pick.get("missing"):
                    n_missing += 1
                    continue
                outcomes = pick.get("outcomes") or {}
                if len(outcomes) < len(HORIZONS):
                    n_pending += 1
                for name, out in outcomes.items():
                    stats[name]["picks"].append(out["excess_pct"])
                    stats[name]["by_day"].setdefault(entry["date"], []).append(
                        (out["excess_pct"], out["ret_pct"], out["bench_ret_pct"])
                    )
    return stats, n_missing, n_pending, n_days_recorded


def horizon_summary(data):
    picks, by_day = data["picks"], data["by_day"]
    if not picks:
        return None
    daily_means = [sum(e for e, _, _ in v) / len(v) for v in by_day.values()]
    win_days = sum(1 for m in daily_means if m > 0)
    lo, hi = bootstrap_ci(daily_means)
    # Equal-weight compounding: each day, split across that day's picks.
    strat = bench = 1.0
    for v in by_day.values():
        strat *= 1 + sum(r for _, r, _ in v) / len(v) / 100
        bench *= 1 + sum(b for _, _, b in v) / len(v) / 100
    return {
        "n_picks": len(picks),
        "n_days": len(by_day),
        "hit_rate": sum(1 for e in picks if e > 0) / len(picks),
        "mean_excess": sum(picks) / len(picks),
        "daily_mean_excess": sum(daily_means) / len(daily_means),
        "ci": (lo, hi),
        "win_days": win_days,
        "p_value": sign_test_p(win_days, len(daily_means)),
        "cum_strategy": (strat - 1) * 100,
        "cum_benchmark": (bench - 1) * 100,
    }


def verdict_line(s):
    if s is None or s["n_days"] < MIN_DAYS_FOR_VERDICT:
        n = s["n_days"] if s else 0
        return (f"⏳ TOO EARLY — {n}/{MIN_DAYS_FOR_VERDICT} pick-days collected. "
                "No conclusion is honest yet; keep collecting.")
    lo, hi = s["ci"]
    if lo > 0:
        return (f"✅ EDGE DETECTED — daily mean excess {s['daily_mean_excess']:+.2f}%, "
                f"95% CI [{lo:+.2f}%, {hi:+.2f}%] excludes zero over {s['n_days']} days.")
    if hi < 0:
        return (f"❌ NEGATIVE EDGE — the radar underperforms SPY: 95% CI "
                f"[{lo:+.2f}%, {hi:+.2f}%] is below zero over {s['n_days']} days.")
    return (f"➖ NO DETECTABLE EDGE YET — 95% CI [{lo:+.2f}%, {hi:+.2f}%] still "
            f"straddles zero after {s['n_days']} days. Indistinguishable from luck so far.")


def report(now_utc, force=False):
    stats, n_missing, n_pending, n_days_recorded = collect_stats()
    now_ct = now_utc.astimezone(CENTRAL)
    lines = [
        "# Radar forward-test scoreboard",
        "",
        f"_Updated {now_ct:%Y-%m-%d %H:%M} CT · picks recorded premarket, "
        "scored at real market prices, benchmarked against SPY. "
        "Commit history is the audit trail: every pick was committed before "
        "the open of the day it was scored on._",
        "",
        f"- Pick-days recorded: **{n_days_recorded}**  · picks pending "
        f"evaluation: {n_pending} · picks excluded for missing data: {n_missing}",
        "",
    ]
    summaries = {}
    for name in HORIZONS:
        s = summaries[name] = horizon_summary(stats[name])
        lines.append(f"## {name} horizon (buy at open, sell at close"
                     + ("" if name == "1d" else f" +{HORIZONS[name]} trading days") + ")")
        lines.append("")
        if s is None:
            lines.append("No evaluated picks yet.")
            lines.append("")
            continue
        lines += [
            f"- Sample: **{s['n_picks']} picks over {s['n_days']} days**",
            f"- Hit rate vs SPY: **{s['hit_rate']:.0%}** of picks beat the benchmark",
            f"- Mean excess return per pick: **{s['mean_excess']:+.2f}%**",
            f"- Daily mean excess: {s['daily_mean_excess']:+.2f}% "
            f"(95% bootstrap CI [{s['ci'][0]:+.2f}%, {s['ci'][1]:+.2f}%])",
            f"- Winning days: {s['win_days']}/{s['n_days']} "
            f"(sign test p = {s['p_value']:.3f})",
            f"- Cumulative if traded: strategy {s['cum_strategy']:+.1f}% "
            f"vs SPY {s['cum_benchmark']:+.1f}%",
            "",
            f"**{verdict_line(s)}**",
            "",
        ]
    lines += [
        "---",
        "",
        "Statistical notes: picks made the same day move together, so every "
        "significance number treats one trading day as one observation. "
        "Excluded picks are counted above rather than silently dropped "
        "(survivorship honesty). A verdict requires at least "
        f"{MIN_DAYS_FOR_VERDICT} pick-days.",
    ]
    SCOREBOARD.parent.mkdir(parents=True, exist_ok=True)
    SCOREBOARD.write_text("\n".join(lines) + "\n")
    print(f"report: wrote {SCOREBOARD}")

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if webhook and (now_ct.weekday() == 4 or force):
        post_discord(webhook, summaries, n_days_recorded)
    return True


def post_discord(webhook, summaries, n_days_recorded):
    fields = []
    for name, s in summaries.items():
        if s is None:
            continue
        fields.append({
            "name": f"{name} horizon",
            "value": (f"{s['n_picks']} picks / {s['n_days']} days · "
                      f"hit rate {s['hit_rate']:.0%} · "
                      f"mean excess {s['mean_excess']:+.2f}%\n{verdict_line(s)}"),
            "inline": False,
        })
    if not fields:
        fields = [{"name": "Status", "value":
                   f"{n_days_recorded} pick-days recorded; nothing evaluated yet.",
                   "inline": False}]
    payload = {
        "username": "Radar Forward Test",
        "embeds": [{
            "title": "🧪 Radar forward-test scoreboard",
            "description": "Out-of-sample results: picks recorded premarket, "
                           "scored at real prices vs SPY.",
            "fields": fields,
            "color": 0x9B59B6,
            "footer": {"text": "Full details: data/scoreboard.md in the repo"},
        }],
    }
    try:
        status = stock_report.post_to_discord(webhook, payload)
        print(f"report: posted scoreboard to Discord (HTTP {status}).")
    except Exception as exc:  # noqa: BLE001
        print(f"report: Discord post failed: {exc}", file=sys.stderr)


# ----------------------------------------------------------------------- main

def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "auto").lower()
    force = os.environ.get("FORCE") == "1"
    now_utc = datetime.now(timezone.utc)
    now_ct = now_utc.astimezone(CENTRAL)

    if mode == "auto":
        # Windows are sized so exactly one of each paired UTC cron lands
        # inside per day, whichever of CST/CDT is in effect.
        morning = (7, 30) <= (now_ct.hour, now_ct.minute) < (8, 25)
        evening = (16, 45) <= (now_ct.hour, now_ct.minute) < (18, 15)
        if force:
            record(now_utc, force=True)
            evaluate(now_utc)
            report(now_utc, force=True)
        elif morning:
            record(now_utc)
        elif evening:
            evaluate(now_utc)
            report(now_utc)
        else:
            print(f"auto: {now_ct:%a %H:%M %Z} is outside both windows; nothing to do.")
        return 0
    if mode == "record":
        record(now_utc, force=force)
    elif mode == "evaluate":
        evaluate(now_utc)
    elif mode == "report":
        report(now_utc, force=force)
    else:
        print(f"unknown mode: {mode} (use record | evaluate | report | auto)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
