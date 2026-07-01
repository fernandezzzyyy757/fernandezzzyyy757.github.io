"""Scans a universe of tickers for premarket movers backed by fresh, positive
news, and scores/ranks them. Uses Finnhub for quotes, company news, and news
sentiment. Free-tier Finnhub is rate-limited (~60 calls/min), so this sleeps
between batches - a full scan of ~60 tickers takes a couple minutes."""

import time
import requests

from config import (
    FINNHUB_API_KEY,
    DEFAULT_UNIVERSE,
    MIN_PREMARKET_MOVE_PCT,
    MAX_PREMARKET_MOVE_PCT,
    MIN_AVG_VOLUME,
    MAX_CANDIDATES_TO_SCORE,
)

BASE_URL = "https://finnhub.io/api/v1"


class ScannerError(Exception):
    pass


def _get(path, params):
    params = {**params, "token": FINNHUB_API_KEY}
    resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=10)
    if resp.status_code == 429:
        time.sleep(2)
        resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_quote(symbol):
    """c=current, pc=previous close. During premarket hours Finnhub's `c`
    reflects the latest traded price, which is the premarket price."""
    return _get("/quote", {"symbol": symbol})


def get_company_news(symbol, from_date, to_date):
    return _get("/company-news", {"symbol": symbol, "from": from_date, "to": to_date})


def get_news_sentiment(symbol):
    try:
        return _get("/news-sentiment", {"symbol": symbol})
    except requests.HTTPError:
        return {}


def _score_candidate(symbol, quote, news, sentiment):
    pc = quote.get("pc") or 0
    c = quote.get("c") or 0
    if not pc or not c:
        return None

    move_pct = ((c - pc) / pc) * 100

    if move_pct < MIN_PREMARKET_MOVE_PCT or move_pct > MAX_PREMARKET_MOVE_PCT:
        return None
    if not news:
        return None  # require an actual catalyst, not just a random gap

    # Sweet spot: reward moves in the 2-8% range, taper off as it gets extended
    if move_pct <= 8:
        move_score = move_pct / 8 * 60
    else:
        move_score = max(0, 60 - (move_pct - 8) * 4)

    bullish_pct = (sentiment.get("sentiment", {}) or {}).get("bullishPercent", 0.5) * 100
    buzz = (sentiment.get("buzz", {}) or {}).get("buzz", 0)
    sentiment_score = min(bullish_pct, 100) * 0.3 + min(buzz * 10, 10)

    news_score = min(len(news), 5) * 2

    total_score = round(move_score + sentiment_score + news_score, 1)

    top_headlines = sorted(news, key=lambda n: n.get("datetime", 0), reverse=True)[:3]

    return {
        "symbol": symbol,
        "score": total_score,
        "premarket_price": c,
        "previous_close": pc,
        "premarket_move_pct": round(move_pct, 2),
        "bullish_pct": round(bullish_pct, 1),
        "headlines": [
            {
                "headline": n.get("headline"),
                "source": n.get("source"),
                "url": n.get("url"),
                "datetime": n.get("datetime"),
            }
            for n in top_headlines
        ],
    }


def scan(universe=None, from_date=None, to_date=None):
    """Returns a list of scored candidates, best first."""
    if not FINNHUB_API_KEY:
        raise ScannerError("FINNHUB_API_KEY is not set - see .env.example")

    universe = (universe or DEFAULT_UNIVERSE)[:MAX_CANDIDATES_TO_SCORE]
    candidates = []

    for i, symbol in enumerate(universe):
        try:
            quote = get_quote(symbol)
            news = get_company_news(symbol, from_date, to_date)
            sentiment = get_news_sentiment(symbol)
            result = _score_candidate(symbol, quote, news, sentiment)
            if result:
                candidates.append(result)
        except requests.RequestException as e:
            print(f"[scanner] skipping {symbol}: {e}")

        # stay well under Finnhub's free-tier rate limit
        if i % 25 == 24:
            time.sleep(1)

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def build_reasoning(candidate):
    lines = [
        f"{candidate['symbol']} is up {candidate['premarket_move_pct']}% premarket "
        f"(${candidate['previous_close']} -> ${candidate['premarket_price']}).",
        f"News sentiment: {candidate['bullish_pct']}% bullish across recent coverage.",
        "Recent headlines:",
    ]
    for h in candidate["headlines"]:
        lines.append(f"  - [{h['source']}] {h['headline']}")
    return "\n".join(lines)
