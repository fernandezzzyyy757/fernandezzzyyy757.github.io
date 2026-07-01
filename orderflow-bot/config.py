import os

from dotenv import load_dotenv

load_dotenv()


def _get_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TICKER = os.getenv("TICKER", "GC=F")
POLL_INTERVAL_SECONDS = _get_int("POLL_INTERVAL_SECONDS", 60)
LOOKBACK_BARS = _get_int("LOOKBACK_BARS", 180)

# Volume-at-price bucket size, in price points, for the rolling VPOC calc.
VPOC_BUCKET_SIZE = 1.0

# Round-number grid that price levels get compared against for absorption setups.
ROUND_NUMBER_STEP = 25.0

# A bar must fall in the top/bottom X percentile of the lookback window to count
# as "high volume", "tight range", or "extreme delta" for a signal to fire.
HIGH_VOLUME_PERCENTILE = 75
TIGHT_RANGE_PERCENTILE = 25
EXTREME_DELTA_PERCENTILE = 90

# How close (in price points) a bar's close must be to a VPOC or round number
# to count as being "at" that level.
LEVEL_PROXIMITY = 1.5

# Number of consecutive same-direction bars required before an exhaustion
# signal is considered (i.e. there must actually be a trend to exhaust).
TREND_RUN_LENGTH = 3

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
