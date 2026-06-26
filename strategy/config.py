# Using micro contracts — available to retail, smaller margin requirement
SYMBOLS = {
    'MNQ': 'MNQ=F',   # Micro E-mini Nasdaq-100
    'MES': 'MES=F',   # Micro E-mini S&P 500
    'MGC': 'MGC=F',   # Micro Gold
    'SI':  'SI=F',    # Silver (no micro on yfinance; full contract used)
}

# Dollar value per 1-point move (per contract)
POINT_VALUE = {
    'MNQ': 2,     # Micro NQ: $2/point
    'MES': 5,     # Micro ES: $5/point
    'MGC': 10,    # Micro Gold: $10/point
    'SI':  50,    # Full silver: $50/point
}

START_DATE = '2010-01-01'   # micro contracts weren't liquid before ~2019; still useful for IS

ACCOUNT      = 25_000    # starting equity ($) — realistic for micro futures
RISK_PCT     = 0.01      # risk per trade (1%)
TARGET_RR    = 2.5       # reward-to-risk target
MAX_HOLD     = 20        # bars before time-based exit

COMMISSION   = 0.50      # $ per micro contract, round-trip (typical retail rate)
SLIPPAGE_PTS = 0.25      # points of slippage per fill

# Walk-forward windows
IS_YEARS    = 3          # in-sample training window (years)
OOS_MONTHS  = 6          # out-of-sample test period (months)

# Signal parameters
RSI_PERIOD      = 14
RSI_OVERSOLD    = 40     # pullback threshold for longs
RSI_OVERBOUGHT  = 60     # pullback threshold for shorts
EMA_FAST        = 20     # weekly EMA
SMA_TREND       = 200    # daily SMA for macro filter
ATR_PERIOD      = 14
SWING_BARS      = 5      # bars used to define swing high/low
ATR_STOP_MULT   = 0.25   # ATR added beyond swing for stop buffer
