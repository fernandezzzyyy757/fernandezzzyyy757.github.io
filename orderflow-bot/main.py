import time
import traceback

import config
import state
from data_feed import fetch_bars
from notifier import send_signal
from orderflow import detect_signals


def run_once(seen: set[str]) -> set[str]:
    df = fetch_bars(config.TICKER, config.LOOKBACK_BARS)
    if df.empty:
        print("No data returned (market may be closed).")
        return seen

    for signal in detect_signals(df):
        key = f"{signal.kind}:{signal.timestamp.isoformat()}"
        if key in seen:
            continue
        send_signal(config.DISCORD_WEBHOOK_URL, config.TICKER, signal)
        print(f"Sent alert: {key} -- {signal.detail}")
        seen.add(key)

    return seen


def main() -> None:
    print(f"Watching {config.TICKER}, polling every {config.POLL_INTERVAL_SECONDS}s")
    seen = state.load_seen_signals()
    while True:
        try:
            seen = run_once(seen)
            state.save_seen_signals(seen)
        except Exception:
            traceback.print_exc()
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
