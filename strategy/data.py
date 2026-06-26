import pandas as pd
import yfinance as yf
from config import SYMBOLS, START_DATE


def fetch_daily(symbol: str) -> pd.DataFrame:
    ticker = SYMBOLS[symbol]
    try:
        raw = yf.download(ticker, start=START_DATE, auto_adjust=True, progress=False)
        if raw.empty:
            raise ValueError("empty response")
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw.columns = [c.lower() for c in raw.columns]
        raw.index = pd.to_datetime(raw.index)
        df = raw[['open', 'high', 'low', 'close', 'volume']].dropna()
        if df.empty:
            raise ValueError("no data after cleaning")
        return df
    except Exception as e:
        print(f"  [WARNING] yfinance failed ({e}). Using synthetic data — run locally for real results.")
        from synthetic_data import generate
        return generate(symbol, start=START_DATE)


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    weekly = daily.resample('W-FRI').agg({
        'open':   'first',
        'high':   'max',
        'low':    'min',
        'close':  'last',
        'volume': 'sum',
    }).dropna()
    return weekly
