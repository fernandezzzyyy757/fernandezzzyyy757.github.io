"""Tiny JSON-file state store shared between bot.py (writer) and dashboard.py
(reader/writer for approvals). A file is used instead of in-memory state so
the dashboard can run as a separate Flask process from the bot loop."""

import json
import os
import threading
from datetime import datetime

from config import STATE_FILE, DATA_DIR

_lock = threading.Lock()

DEFAULT_STATE = {
    "status": "idle",  # idle | proposed_entry | entered | proposed_exit | exited | expired | rejected
    "date": None,
    "proposal": None,   # dict describing the buy candidate + reasoning
    "position": None,   # dict describing the open position once bought
    "exit_proposal": None,
    "decision": None,   # "approved" | "rejected" | None, cleared after read
    "exit_decision": None,
    "history": [],      # list of completed trades
    "last_update": None,
}


def _ensure_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(STATE_FILE):
        _write(DEFAULT_STATE)


def load():
    _ensure_file()
    with _lock:
        with open(STATE_FILE, "r") as f:
            return json.load(f)


def _write(state):
    state["last_update"] = datetime.now().isoformat()
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp_path, STATE_FILE)


def save(state):
    with _lock:
        _write(state)


def update(**kwargs):
    state = load()
    state.update(kwargs)
    save(state)
    return state


def reset_for_new_day(today_str):
    save({**DEFAULT_STATE, "date": today_str, "history": load().get("history", [])})
