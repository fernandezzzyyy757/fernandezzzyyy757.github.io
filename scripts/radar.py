#!/usr/bin/env python3
"""Bullish-signal radar: rank stocks by filtered StockTwits sentiment,
news coverage, and premarket price action.

This is a signal ranker, not a predictor. It surfaces the tickers with the
strongest combination of (a) genuinely bullish crowd sentiment after heavy
spam filtering, (b) real news coverage, and (c) constructive premarket
movement — the stocks worth looking at first, with reasons attached.

StockTwits spam filters applied to every message before it can vote:
  - must carry an explicit Bullish/Bearish sentiment tag
  - author must have >= MIN_FOLLOWERS followers
  - messages tagging >= SPAM_CASHTAG_COUNT tickers are dropped (pump spam)
  - one vote per user per symbol
Candidates priced under MIN_PRICE or with too little signal are excluded.
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) StockReportBot/1.0"
TRENDING_URL = "https://api.stocktwits.com/api/2/trending/symbols.json"
STREAM_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json?limit=30"
CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?range=2d&interval=1d&includePrePost=true"
)

MIN_FOLLOWERS = 30
SPAM_CASHTAG_COUNT = 4
MIN_PRICE = 2.0
MIN_SIGNAL_MESSAGES = 5  # need at least this many clean sentiment votes...
MIN_NEWS_MENTIONS = 1    # ...unless the stock is also in the news
MAX_CANDIDATES = 18      # symbols pulled from trending to evaluate
MAX_PICKS = 5
MESSAGE_MAX_AGE = timedelta(hours=16)

# Uppercase words that look like tickers but are usually English in headlines.
AMBIGUOUS = {
    "A", "ALL", "AN", "ANY", "ARE", "AT", "BE", "BIG", "BY", "CAN", "CEO",
    "DO", "EV", "FOR", "GO", "HAS", "IT", "NEW", "NOW", "ON", "ONE", "OR",
    "OUT", "PM", "SO", "TOP", "TV", "UK", "UP", "US", "WAY", "YOU",
}


def get_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def trending_symbols(fetch=get_json):
    """Equity symbols currently trending on StockTwits."""
    data = fetch(TRENDING_URL)
    out = []
    for sym in data.get("symbols", []):
        ticker = sym.get("symbol", "")
        # '.X' suffixes are crypto/forex; skip anything that isn't a plain
        # US-listed ticker.
        if not ticker or "." in ticker or len(ticker) > 5:
            continue
        out.append({"symbol": ticker, "title": sym.get("title", "")})
    return out[:MAX_CANDIDATES]


def stream_sentiment(symbol, now_utc, fetch=get_json):
    """Filtered bull/bear vote counts for one symbol's message stream."""
    data = fetch(STREAM_URL.format(symbol=symbol))
    bull = bear = considered = 0
    voters = set()
    cutoff = now_utc - MESSAGE_MAX_AGE
    for msg in data.get("messages", []):
        sentiment = ((msg.get("entities") or {}).get("sentiment") or {}).get("basic")
        if sentiment not in ("Bullish", "Bearish"):
            continue
        user = msg.get("user") or {}
        if user.get("followers", 0) < MIN_FOLLOWERS:
            continue
        if len(msg.get("symbols") or []) >= SPAM_CASHTAG_COUNT:
            continue
        uid = user.get("id")
        if uid in voters:
            continue
        created = msg.get("created_at", "")
        try:
            when = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if when < cutoff:
            continue
        voters.add(uid)
        considered += 1
        if sentiment == "Bullish":
            bull += 1
        else:
            bear += 1
    return {"bull": bull, "bear": bear, "votes": considered}


def price_gap(symbol, fetch=get_json):
    """Current/premarket price and % gap vs previous close, via Yahoo chart."""
    data = fetch(CHART_URL.format(symbol=symbol))
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        return None
    meta = result[0].get("meta") or {}
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    # Premarket quote, when Yahoo provides one, beats the stale regular price.
    pre = meta.get("preMarketPrice")
    if pre:
        price = pre
    if not price or not prev:
        return None
    return {"price": float(price), "gap_pct": (float(price) - float(prev)) / float(prev) * 100}


def news_mentions(symbol, title, headlines):
    """Count headlines mentioning the ticker or company name; keep one link."""
    company = ""
    if title:
        first = re.split(r"[\s,]+", title.strip())[0]
        if len(first) > 3 and first.upper() != symbol:
            company = first.lower()
    pattern = None
    if symbol not in AMBIGUOUS:
        pattern = re.compile(r"(?<![A-Z$])" + re.escape(symbol) + r"(?![A-Z])")
    cashtag = "$" + symbol
    count, link, headline = 0, "", ""
    for h in headlines:
        text = h["title"]
        hit = cashtag in text
        if not hit and pattern and pattern.search(text):
            hit = True
        if not hit and company and company in text.lower():
            hit = True
        if hit:
            count += 1
            if not link:
                link, headline = h.get("link", ""), text
    return count, link, headline


def score_pick(votes, bull, bear, mentions, gap_pct):
    """Composite 0-100 score. Sentiment 35, buzz 20, news 25, gap 20."""
    ratio = (bull + 2) / (votes + 4) if votes else 0.5
    sent_pts = max(0.0, (ratio - 0.5) * 2) * 35
    buzz_pts = min(votes, 20)
    news_pts = min(mentions * 8, 25)
    gap_pts = 0.0
    if gap_pct is not None:
        if 0.5 <= gap_pct <= 8:
            gap_pts = 8 + (min(gap_pct, 5) / 5) * 12  # peaks around +5%
        elif gap_pct > 8:
            gap_pts = 6  # already extended; chasing risk
        elif gap_pct > 0:
            gap_pts = 5
        else:
            gap_pts = max(-10.0, gap_pct * 2)
    return max(0.0, min(100.0, sent_pts + buzz_pts + news_pts + gap_pts)), ratio


def build_radar(headlines, now_utc, fetch=get_json):
    """Return scored picks, best first. Never raises for a single bad symbol."""
    picks = []
    for cand in trending_symbols(fetch):
        symbol, title = cand["symbol"], cand["title"]
        try:
            senti = stream_sentiment(symbol, now_utc, fetch)
        except Exception as exc:  # noqa: BLE001
            print(f"radar: stream {symbol} failed: {exc}", file=sys.stderr)
            continue
        mentions, link, headline = news_mentions(symbol, title, headlines)
        if senti["votes"] < MIN_SIGNAL_MESSAGES and mentions < MIN_NEWS_MENTIONS:
            continue
        try:
            quote = price_gap(symbol, fetch)
        except Exception as exc:  # noqa: BLE001
            print(f"radar: quote {symbol} failed: {exc}", file=sys.stderr)
            quote = None
        if quote and quote["price"] < MIN_PRICE:
            continue
        gap_pct = quote["gap_pct"] if quote else None
        total, ratio = score_pick(senti["votes"], senti["bull"], senti["bear"], mentions, gap_pct)
        if senti["bear"] > senti["bull"]:
            continue  # bullish radar only
        picks.append({
            "symbol": symbol,
            "title": title,
            "score": total,
            "bull_ratio": ratio,
            "votes": senti["votes"],
            "mentions": mentions,
            "link": link,
            "headline": headline,
            "price": quote["price"] if quote else None,
            "gap_pct": gap_pct,
        })
    picks.sort(key=lambda p: p["score"], reverse=True)
    return picks[:MAX_PICKS]


def format_radar(picks):
    """Discord embed dict for the radar section, or None if nothing scored."""
    if not picks:
        return None
    lines = []
    for i, p in enumerate(picks, 1):
        bits = []
        if p["price"] is not None:
            bits.append(f"${p['price']:,.2f}")
        if p["gap_pct"] is not None:
            bits.append(f"{p['gap_pct']:+.1f}% vs close")
        bits.append(f"{p['bull_ratio']:.0%} bullish ({p['votes']} clean msgs)")
        bits.append(f"{p['mentions']} headline{'s' if p['mentions'] != 1 else ''}")
        line = f"**{i}. ${p['symbol']}** · score {p['score']:.0f} — " + " · ".join(bits)
        if p["gap_pct"] is not None and p["gap_pct"] > 8:
            line += " ⚠️ already extended"
        if p["link"]:
            line += f"\n   ↳ [{_shorten_title(p, 80)}]({p['link']})"
        lines.append(line)
    return {
        "title": "📊 Radar — strongest bullish setups right now",
        "description": "\n".join(lines)[:4000],
        "color": 0xF1C40F,
        "footer": {
            "text": "Filtered StockTwits sentiment + news volume + premarket gap. "
                    "A ranking of attention, not a promise — check the chart first."
        },
    }


def _shorten_title(pick, limit):
    return (pick.get("headline") or "related headline")[:limit]
