import pandas as pd
import yfinance as yf


def fetch_bars(ticker: str, lookback_bars: int) -> pd.DataFrame:
    """Fetch recent 1-minute OHLCV bars for `ticker` from Yahoo Finance.

    Yahoo's free intraday data for futures is delayed (typically ~10-20 min)
    and is bar data only -- there is no bid/ask depth here, so this is a
    proxy feed, not a real order-flow/DOM feed.
    """
    df = yf.download(
        ticker,
        period="5d",
        interval="1m",
        progress=False,
        auto_adjust=False,
        multi_level_index=False,
    )
    if df.empty:
        return df

    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    df = df.tail(lookback_bars).copy()
    df.index.name = "timestamp"
    return df
