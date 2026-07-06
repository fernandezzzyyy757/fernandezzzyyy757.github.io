#!/usr/bin/env python3
"""Morning stock news report posted to Discord.

Runs on a GitHub Actions schedule (see .github/workflows/stock-report.yml).
Fires at 7, 8, and 9 AM Central (Texas) time. The 7 AM report covers
overnight news; the 8 and 9 AM reports cover headlines since the prior hour.

Environment variables:
  DISCORD_WEBHOOK_URL  required (repo secret) unless DRY_RUN=1
  FORCE=1              skip the 7/8/9 AM Central time gate (manual test runs)
  DRY_RUN=1            print the Discord payload instead of posting
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
REPORT_HOURS = (7, 8, 9)
MAX_HEADLINES = 12
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) StockReportBot/1.0"

FEEDS = [
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("MarketWatch Pulse", "https://feeds.content.dowjones.io/public/rss/mw_marketpulse"),
    ("Seeking Alpha", "https://seekingalpha.com/market_currents.xml"),
    ("Benzinga", "https://www.benzinga.com/feed"),
    ("Investing.com", "https://www.investing.com/rss/news_25.rss"),
]


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_feed(xml_text, source):
    """Parse RSS 2.0 items into dicts with title, link, published, source."""
    items = []
    root = ElementTree.fromstring(xml_text)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if not title or not pub:
            continue
        try:
            published = parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        items.append({"title": title, "link": link, "published": published, "source": source})
    return items


def gather_headlines(now_utc):
    """All deduped headlines from the last 24h, newest first."""
    cutoff = now_utc - timedelta(hours=24)
    headlines, seen, errors = [], set(), []
    for source, url in FEEDS:
        try:
            items = parse_feed(fetch(url), source)
        except Exception as exc:  # noqa: BLE001 - any single feed may be flaky
            errors.append(f"{source}: {exc}")
            continue
        for item in items:
            key = item["title"].lower()
            if item["published"] >= cutoff and key not in seen:
                seen.add(key)
                headlines.append(item)
    headlines.sort(key=lambda h: h["published"], reverse=True)
    return headlines, errors


def format_time_ct(dt):
    local = dt.astimezone(CENTRAL)
    return local.strftime("%-I:%M %p").lstrip("0")


def build_payload(headlines, report_hour, now_ct, overnight):
    hour_label = f"{report_hour if report_hour <= 12 else report_hour - 12} AM"
    coverage = "overnight news" if overnight else "past hour"
    lines = []
    for h in headlines[:MAX_HEADLINES]:
        when = format_time_ct(h["published"])
        if h["link"]:
            lines.append(f"• **{h['source']}** — [{h['title']}]({h['link']}) ({when} CT)")
        else:
            lines.append(f"• **{h['source']}** — {h['title']} ({when} CT)")
    if not lines:
        lines = ["No fresh headlines from the feeds in this window."]

    description = ""
    for line in lines:
        if len(description) + len(line) + 1 > 4000:  # Discord embed description cap is 4096
            break
        description += line + "\n"

    embed = {
        "title": f"📈 {hour_label} Stock Report — {now_ct.strftime('%A, %B %-d')}",
        "description": description.rstrip(),
        "color": 0x2ECC71,
        "footer": {"text": f"Covering {coverage} · Yahoo Finance / CNBC / MarketWatch"},
    }
    return {"username": "Morning Stock Report", "embeds": [embed]}


def post_to_discord(webhook_url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status


def main():
    now_utc = datetime.now(timezone.utc)
    now_ct = now_utc.astimezone(CENTRAL)
    force = os.environ.get("FORCE") == "1"
    dry_run = os.environ.get("DRY_RUN") == "1"

    if now_ct.hour in REPORT_HOURS:
        report_hour = now_ct.hour
    elif force:
        report_hour = REPORT_HOURS[0]
    else:
        # The cron fires at 12-15 UTC to cover both CST and CDT; whichever
        # runs fall outside 7-9 AM Central simply exit here.
        print(f"Not a report hour in Central time ({now_ct:%H:%M %Z}); exiting.")
        return 0

    overnight = report_hour == REPORT_HOURS[0]
    window = timedelta(hours=15) if overnight else timedelta(minutes=75)
    all_headlines, errors = gather_headlines(now_utc)
    for err in errors:
        print(f"feed error: {err}", file=sys.stderr)
    if not all_headlines and errors and len(errors) == len(FEEDS):
        print("All feeds failed.", file=sys.stderr)
        return 1

    fresh_cutoff = now_utc - window
    headlines = [h for h in all_headlines if h["published"] >= fresh_cutoff]
    payload = build_payload(headlines, report_hour, now_ct, overnight)

    # Radar rides along in a second embed; its failure never blocks the news.
    try:
        import radar

        picks = radar.build_radar(all_headlines, now_utc)
        radar_embed = radar.format_radar(picks)
        if radar_embed:
            payload["embeds"].append(radar_embed)
        else:
            print("radar: no picks passed the filters this run")
    except Exception as exc:  # noqa: BLE001
        print(f"radar failed: {exc}", file=sys.stderr)

    if dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not set.", file=sys.stderr)
        return 1
    status = post_to_discord(webhook_url, payload)
    print(f"Posted {min(len(headlines), MAX_HEADLINES)} headlines (HTTP {status}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
