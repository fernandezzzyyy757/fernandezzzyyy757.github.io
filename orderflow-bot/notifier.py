import requests

from orderflow import Signal

_COLOR_BY_KIND = {
    "absorption": 0xF1C40F,
    "exhaustion": 0xE74C3C,
    "bullish_divergence": 0x2ECC71,
    "bearish_divergence": 0xE67E22,
}


def send_signal(webhook_url: str, ticker: str, signal: Signal) -> None:
    if not webhook_url:
        raise ValueError("DISCORD_WEBHOOK_URL is not set")

    embed = {
        "title": f"{ticker} order-flow setup: {signal.kind.replace('_', ' ').title()}",
        "description": signal.detail,
        "color": _COLOR_BY_KIND.get(signal.kind, 0x3498DB),
        "fields": [
            {"name": "Price", "value": f"{signal.price:.2f}", "inline": True},
            {"name": "Bar time", "value": str(signal.timestamp), "inline": True},
        ],
        "footer": {"text": "Proxy order-flow bot -- delayed free data, not real DOM/tape"},
    }
    response = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
    response.raise_for_status()
