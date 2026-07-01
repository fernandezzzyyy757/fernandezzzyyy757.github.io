import json
import os

import config


def load_seen_signals() -> set[str]:
    if not os.path.exists(config.STATE_FILE):
        return set()
    with open(config.STATE_FILE) as f:
        return set(json.load(f))


def save_seen_signals(seen: set[str]) -> None:
    # Keep the state file from growing forever -- only the most recent
    # entries are needed to dedupe against the current lookback window.
    trimmed = sorted(seen)[-500:]
    with open(config.STATE_FILE, "w") as f:
        json.dump(trimmed, f)
