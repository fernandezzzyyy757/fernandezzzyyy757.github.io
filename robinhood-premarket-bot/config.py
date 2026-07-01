import os
import pytz
from dotenv import load_dotenv

load_dotenv()

ET = pytz.timezone("America/New_York")

# --- Credentials ---
ROBINHOOD_USERNAME = os.getenv("ROBINHOOD_USERNAME", "")
ROBINHOOD_PASSWORD = os.getenv("ROBINHOOD_PASSWORD", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# Safety switch - see README. Keep True until you trust the bot.
DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() in ("1", "true", "yes")

# --- Schedule (all times America/New_York) ---
SCAN_TIME = "08:00"          # when the morning scan runs
ENTRY_DEADLINE = "09:25"     # if you haven't approved by now, proposal expires
MARKET_OPEN = "09:30"
EXIT_CHECK_DELAY_MIN = 15    # propose selling this many minutes after open by default

# --- Strategy thresholds (tune these to taste) ---
MIN_PREMARKET_MOVE_PCT = 1.5     # ignore anything moving less than this
MAX_PREMARKET_MOVE_PCT = 15.0    # ignore anything already this extended (chasing risk)
MIN_AVG_VOLUME = 500_000         # liquidity floor so you can actually get in/out
MAX_CANDIDATES_TO_SCORE = 60     # how many tickers from the universe to check per run

# Exit rule applied automatically if you don't want to approve every sell too.
# Bot always shows you the exit proposal on the dashboard first regardless;
# this only controls whether it needs your click or fires on its own.
REQUIRE_EXIT_APPROVAL = True
PROFIT_TARGET_PCT = 2.0          # propose selling early if this profit is hit
STOP_LOSS_PCT = -3.0             # propose selling early if this loss is hit

# The universe of tickers the scanner checks each morning. Keep this to
# liquid, well-covered names - illiquid tickers make "all in" exits dangerous.
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "PLTR", "AMZN", "GOOGL", "META",
    "NFLX", "AVGO", "CRM", "ORCL", "ADBE", "INTC", "MU", "SNOW", "SHOP",
    "UBER", "ABNB", "COIN", "SOFI", "PYPL", "SQ", "RIVN", "LCID", "F", "GM",
    "BA", "DIS", "NKE", "SBUX", "JPM", "BAC", "WFC", "GS", "XOM", "CVX",
    "PFE", "MRNA", "JNJ", "UNH", "V", "MA", "WMT", "TGT", "COST", "HD",
    "SNAP", "PINS", "RBLX", "DASH", "DKNG", "ROKU", "ZM", "DOCU", "CRWD",
    "PANW", "NET", "DDOG", "MDB", "SMCI",
]

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
TRADE_LOG = os.path.join(DATA_DIR, "trades.log")
SESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".robinhood_session")
