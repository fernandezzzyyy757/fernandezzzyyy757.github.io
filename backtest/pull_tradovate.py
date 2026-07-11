#!/usr/bin/env python3
"""
Pull MNQ 1-minute OHLCV history from Tradovate's chart API and save it in the
format backtest/mnq_footprint_backtest.py expects (data/mnq_1m.csv, naive UTC
timestamps -> run the backtest with --tz UTC).

Auth (same credential set a Tradovate API webhook bot uses):
    TRADOVATE_USER       account username
    TRADOVATE_PASS       password
    TRADOVATE_CID        API client id (integer)
    TRADOVATE_SEC        API client secret
  optional:
    TRADOVATE_APP_ID     app name registered with the API key (default MNQHistoryPuller)
    TRADOVATE_DEVICE_ID  stable device id string (default derived from hostname)
    TRADOVATE_DEMO=1     use demo.tradovateapi.com instead of live
    TRADOVATE_MD_TOKEN   an already-issued market-data access token; skips REST auth

Requires: pip install requests websockets

Usage:
    python backtest/pull_tradovate.py                 # MNQ continuous, as deep as allowed
    python backtest/pull_tradovate.py --symbol MNQU6  # a specific contract
    python backtest/pull_tradovate.py --max-days 400 --out data/mnq_1m.csv

Notes:
  - Historical charts come over the market-data websocket (md/getChart); the
    account needs API access + a CME data subscription or the request is
    rejected with an access error.
  - Bars are requested in pages going back from now until Tradovate signals
    end-of-history (eoh) or --max-days is reached.
  - Tradovate minute bars carry upVolume/downVolume (real uptick/downtick
    split). total volume = upVolume + downVolume is written to the `volume`
    column; the raw split is preserved in extra columns (up_volume,
    down_volume) which the backtest ignores today but could use as a REAL
    delta source instead of the tick-rule proxy.
  - If the downloaded span is < 60 days the script tells you to fall back to
    backtest/pull_databento.py.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import os
import socket
import sys

try:
    import requests
    import websockets
except ImportError as e:
    sys.exit(f"missing dependency: {e.name}. Run: pip install requests websockets")

LIVE_REST = "https://live.tradovateapi.com/v1"
DEMO_REST = "https://demo.tradovateapi.com/v1"
MD_WSS = "wss://md.tradovateapi.com/v1/websocket"
PAGE_ELEMENTS = 20_000          # bars per md/getChart page (server may cap lower)
MIN_ACCEPTABLE_DAYS = 60


def rest_base() -> str:
    return DEMO_REST if os.environ.get("TRADOVATE_DEMO") == "1" else LIVE_REST


def get_md_token() -> str:
    tok = os.environ.get("TRADOVATE_MD_TOKEN")
    if tok:
        return tok
    missing = [k for k in ("TRADOVATE_USER", "TRADOVATE_PASS", "TRADOVATE_CID",
                           "TRADOVATE_SEC") if not os.environ.get(k)]
    if missing:
        sys.exit(
            "Tradovate credentials not set. Export the same values your webhook "
            f"bot authenticates with: {', '.join(missing)}\n"
            "(or set TRADOVATE_MD_TOKEN to reuse an existing market-data token)"
        )
    body = {
        "name": os.environ["TRADOVATE_USER"],
        "password": os.environ["TRADOVATE_PASS"],
        "appId": os.environ.get("TRADOVATE_APP_ID", "MNQHistoryPuller"),
        "appVersion": "1.0",
        "cid": int(os.environ["TRADOVATE_CID"]),
        "sec": os.environ["TRADOVATE_SEC"],
        "deviceId": os.environ.get("TRADOVATE_DEVICE_ID",
                                   f"mnq-puller-{socket.gethostname()}"),
    }
    r = requests.post(f"{rest_base()}/auth/accesstokenrequest", json=body, timeout=30)
    r.raise_for_status()
    j = r.json()
    if "p-ticket" in j:
        sys.exit(f"Tradovate returned a penalty ticket (too many auth attempts): "
                 f"retry after {j.get('p-time')}s")
    if "errorText" in j:
        sys.exit(f"Tradovate auth failed: {j['errorText']}")
    tok = j.get("mdAccessToken")
    if not tok:
        sys.exit("Auth succeeded but no mdAccessToken was returned - the account "
                 "likely lacks a market-data subscription / API access add-on.")
    return tok


class MdSocket:
    """Minimal client for Tradovate's SockJS-style websocket framing."""

    def __init__(self, ws):
        self.ws = ws
        self.req_id = 0
        self.events: asyncio.Queue = asyncio.Queue()
        self.acks: dict[int, dict] = {}

    async def send(self, endpoint: str, body: dict | str | None = None) -> int:
        self.req_id += 1
        payload = "" if body is None else (
            body if isinstance(body, str) else json.dumps(body))
        await self.ws.send(f"{endpoint}\n{self.req_id}\n\n{payload}")
        return self.req_id

    async def pump(self):
        """Read frames; resolve acks, queue chart events, answer heartbeats."""
        async for raw in self.ws:
            if not raw or raw[0] in ("o", "c"):
                continue
            if raw[0] == "h":
                await self.ws.send("[]")
                continue
            if raw[0] != "a":
                continue
            for msg in json.loads(raw[1:]):
                if "i" in msg:
                    self.acks[msg["i"]] = msg
                if msg.get("e") == "chart":
                    await self.events.put(msg["d"])

    async def wait_ack(self, rid: int, timeout: float = 15.0) -> dict:
        deadline = asyncio.get_event_loop().time() + timeout
        while rid not in self.acks:
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(f"no ack for request {rid}")
            await asyncio.sleep(0.05)
        return self.acks.pop(rid)


async def fetch_page(sock: MdSocket, symbol: str, closest: dt.datetime,
                     elements: int) -> tuple[list[dict], bool]:
    """One md/getChart page ending at `closest`. Returns (bars, eoh)."""
    rid = await sock.send("md/getchart", {
        "symbol": symbol,
        "chartDescription": {
            "underlyingType": "MinuteBar",
            "elementSize": 1,
            "elementSizeUnit": "UnderlyingUnits",
            "withHistogram": False,
        },
        "timeRange": {
            "closestTimestamp": closest.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "asMuchAsElements": elements,
        },
    })
    ack = await sock.wait_ack(rid)
    if ack.get("s") != 200:
        raise RuntimeError(f"md/getChart rejected: {ack}")
    hist_id = ack["d"]["historicalId"]

    bars: list[dict] = []
    eoh = False
    idle_deadline = asyncio.get_event_loop().time() + 60
    while True:
        try:
            d = await asyncio.wait_for(sock.events.get(), timeout=10)
        except asyncio.TimeoutError:
            if asyncio.get_event_loop().time() > idle_deadline:
                break
            continue
        got_data = False
        for chart in d.get("charts", []):
            if chart.get("id") not in (hist_id, None) and "eoh" not in chart:
                continue
            if chart.get("eoh"):
                eoh = True
            for b in chart.get("bars", []):
                bars.append(b)
                got_data = True
        if eoh or (got_data and sock.events.empty()):
            # bars for a historical page arrive in one burst; a short grace
            # drain catches stragglers
            try:
                while True:
                    d = await asyncio.wait_for(sock.events.get(), timeout=2)
                    for chart in d.get("charts", []):
                        if chart.get("eoh"):
                            eoh = True
                        bars.extend(chart.get("bars", []))
            except asyncio.TimeoutError:
                pass
            break

    rid = await sock.send("md/cancelchart", {"subscriptionId": hist_id})
    try:
        await sock.wait_ack(rid, timeout=5)
    except TimeoutError:
        pass
    return bars, eoh


async def pull(symbol: str, max_days: int, out_path: str) -> None:
    token = get_md_token()
    print(f"Authenticated. Connecting to {MD_WSS} ...")
    all_bars: dict[str, dict] = {}
    stop_before = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_days)

    async with websockets.connect(MD_WSS) as ws:
        sock = MdSocket(ws)
        pump = asyncio.create_task(sock.pump())
        try:
            rid = await sock.send("authorize", token)
            ack = await sock.wait_ack(rid)
            if ack.get("s") != 200:
                sys.exit(f"websocket authorize failed: {ack}")

            closest = dt.datetime.now(dt.timezone.utc)
            page = 0
            while True:
                page += 1
                bars, eoh = await fetch_page(sock, symbol, closest, PAGE_ELEMENTS)
                new = 0
                earliest = closest
                for b in bars:
                    ts = b["timestamp"]
                    if ts not in all_bars:
                        all_bars[ts] = b
                        new += 1
                    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    earliest = min(earliest, t)
                print(f"page {page}: +{new} bars (total {len(all_bars):,}), "
                      f"earliest {earliest:%Y-%m-%d %H:%M}Z, eoh={eoh}")
                if eoh or new == 0 or earliest <= stop_before:
                    break
                closest = earliest - dt.timedelta(minutes=1)
        finally:
            pump.cancel()

    if not all_bars:
        sys.exit("No bars received - check the symbol and that the account has "
                 "CME market data + API access.")

    rows = []
    for ts, b in sorted(all_bars.items()):
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        up = b.get("upVolume", 0) or 0
        dn = b.get("downVolume", 0) or 0
        vol = up + dn
        rows.append((t.strftime("%Y-%m-%d %H:%M:%S"), b["open"], b["high"],
                     b["low"], b["close"], vol, up, dn))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume",
                    "up_volume", "down_volume"])
        w.writerows(rows)

    t0 = dt.datetime.fromisoformat(rows[0][0])
    t1 = dt.datetime.fromisoformat(rows[-1][0])
    span = (t1 - t0).days
    print(f"\nWrote {len(rows):,} bars to {out_path}")
    print(f"Span: {t0} -> {t1} UTC  ({span} days)")
    print(f"\nNext: python backtest/mnq_footprint_backtest.py --csv {out_path} --tz UTC")
    if span < MIN_ACCEPTABLE_DAYS:
        print(f"\nWARNING: only {span} days of history - too shallow for a "
              f"meaningful 70/30 split. Use backtest/pull_databento.py instead.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--symbol", default="MNQ",
                    help="continuous root (MNQ) or a specific contract e.g. MNQU6")
    ap.add_argument("--max-days", type=int, default=400)
    ap.add_argument("--out", default="data/mnq_1m.csv")
    args = ap.parse_args()
    asyncio.run(pull(args.symbol, args.max_days, args.out))


if __name__ == "__main__":
    main()
