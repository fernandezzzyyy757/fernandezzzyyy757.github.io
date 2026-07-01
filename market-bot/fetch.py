#!/usr/bin/env python3
"""
Market analysis bot: pulls quotes/news/earnings for a watchlist from Finnhub,
scores news sentiment locally (VADER), writes a JSON feed for the dashboard,
and pushes Discord/email alerts when a ticker is moving premarket/intraday
with fresh news, or has earnings today.
"""
import json
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path

import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LATEST_PATH = DATA_DIR / "latest.json"
STATE_PATH = DATA_DIR / "alert_state.json"
WATCHLIST_PATH = BASE_DIR / "watchlist.json"

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB_URL = "https://finnhub.io/api/v1"
MOVE_THRESHOLD_PERCENT = float(os.environ.get("MOVE_THRESHOLD_PERCENT", "2.0"))
NEWS_LOOKBACK_DAYS = 2

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")

analyzer = SentimentIntensityAnalyzer()


def load_json(path, default):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def finnhub_get(endpoint, params):
    params = {**params, "token": FINNHUB_API_KEY}
    resp = requests.get(f"{FINNHUB_URL}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_quote(symbol):
    q = finnhub_get("quote", {"symbol": symbol})
    price = q.get("c")
    prev_close = q.get("pc")
    if not price or not prev_close:
        return None
    percent_change = round((price - prev_close) / prev_close * 100, 2)
    return {"price": price, "prev_close": prev_close, "percent_change": percent_change}


def score_sentiment(text):
    if not text:
        return "neutral", 0.0
    compound = analyzer.polarity_scores(text)["compound"]
    if compound >= 0.05:
        label = "positive"
    elif compound <= -0.05:
        label = "negative"
    else:
        label = "neutral"
    return label, compound


def get_news(symbol):
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=NEWS_LOOKBACK_DAYS)
    articles = finnhub_get(
        "company-news", {"symbol": symbol, "from": since.isoformat(), "to": today.isoformat()}
    )
    articles.sort(key=lambda a: a.get("datetime", 0), reverse=True)
    out = []
    for a in articles[:8]:
        headline = a.get("headline", "")
        summary = a.get("summary", "")
        label, score = score_sentiment(f"{headline}. {summary}")
        out.append(
            {
                "headline": headline,
                "url": a.get("url"),
                "source": a.get("source"),
                "datetime": datetime.fromtimestamp(a.get("datetime", 0), tz=timezone.utc).isoformat(),
                "sentiment": label,
                "sentiment_score": round(score, 3),
            }
        )
    return out


def get_earnings(symbol):
    today = datetime.now(timezone.utc).date()
    upcoming = None
    try:
        cal = finnhub_get(
            "calendar/earnings",
            {"symbol": symbol, "from": today.isoformat(), "to": (today + timedelta(days=45)).isoformat()},
        )
        events = cal.get("earningsCalendar", [])
        if events:
            e = sorted(events, key=lambda x: x["date"])[0]
            upcoming = {"date": e.get("date"), "eps_estimate": e.get("epsEstimate"), "hour": e.get("hour")}
    except requests.RequestException:
        pass

    last = None
    try:
        hist = finnhub_get("stock/earnings", {"symbol": symbol})
        if hist:
            h = hist[0]
            last = {
                "date": h.get("period"),
                "actual": h.get("actual"),
                "estimate": h.get("estimate"),
                "surprise_percent": h.get("surprisePercent"),
            }
    except requests.RequestException:
        pass

    return upcoming, last


def send_discord(message):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message[:1900]}, timeout=10)
    except requests.RequestException as e:
        print(f"Discord send failed: {e}", file=sys.stderr)


def send_email(subject, body):
    if not (SMTP_USER and SMTP_PASS and ALERT_EMAIL_TO):
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL_TO
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [ALERT_EMAIL_TO], msg.as_string())
    except smtplib.SMTPException as e:
        print(f"Email send failed: {e}", file=sys.stderr)


def build_alert_text(symbol, quote, news, reason):
    lines = [f"**{symbol}** {reason}", f"Price: {quote['price']} ({quote['percent_change']:+.2f}%)"]
    for n in news[:3]:
        emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}[n["sentiment"]]
        lines.append(f"{emoji} {n['headline']} ({n['source']})")
    return "\n".join(lines)


def main():
    if not FINNHUB_API_KEY:
        print("FINNHUB_API_KEY not set; writing empty feed.", file=sys.stderr)
        save_json(LATEST_PATH, {"generated_at": datetime.now(timezone.utc).isoformat(),
                                 "move_threshold_percent": MOVE_THRESHOLD_PERCENT, "tickers": []})
        return

    watchlist = load_json(WATCHLIST_PATH, [])
    state = load_json(STATE_PATH, {})
    today_str = datetime.now(timezone.utc).date().isoformat()

    results = []
    for symbol in watchlist:
        try:
            quote = get_quote(symbol)
            if quote is None:
                continue
            news = get_news(symbol)
            upcoming_earnings, last_earnings = get_earnings(symbol)
        except requests.RequestException as e:
            print(f"Failed fetching {symbol}: {e}", file=sys.stderr)
            continue

        is_mover = abs(quote["percent_change"]) >= MOVE_THRESHOLD_PERCENT
        has_fresh_news = len(news) > 0
        earnings_today = bool(upcoming_earnings and upcoming_earnings.get("date") == today_str)

        entry = {
            "symbol": symbol,
            **quote,
            "is_mover": is_mover,
            "news": news,
            "upcoming_earnings": upcoming_earnings,
            "last_earnings": last_earnings,
            "earnings_today": earnings_today,
        }
        results.append(entry)

        ticker_state = state.setdefault(symbol, {})

        if is_mover and has_fresh_news and ticker_state.get("mover_alert_date") != today_str:
            text = build_alert_text(symbol, quote, news, "is moving with fresh news")
            send_discord(text)
            send_email(f"[Market Bot] {symbol} moving {quote['percent_change']:+.2f}%", text)
            ticker_state["mover_alert_date"] = today_str

        if earnings_today and ticker_state.get("earnings_alert_date") != today_str:
            text = build_alert_text(symbol, quote, news, "reports earnings today")
            send_discord(text)
            send_email(f"[Market Bot] {symbol} earnings today", text)
            ticker_state["earnings_alert_date"] = today_str

    save_json(
        LATEST_PATH,
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "move_threshold_percent": MOVE_THRESHOLD_PERCENT,
            "tickers": results,
        },
    )
    save_json(STATE_PATH, state)


if __name__ == "__main__":
    main()
