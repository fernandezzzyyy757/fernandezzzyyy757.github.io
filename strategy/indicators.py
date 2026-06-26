import pandas as pd
import numpy as np
from config import (
    RSI_PERIOD, EMA_FAST, SMA_TREND,
    ATR_PERIOD, SWING_BARS,
)


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def rsi(series: pd.Series, n: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=n - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=n - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = ATR_PERIOD) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=n - 1, adjust=False).mean()


def add_indicators(daily: pd.DataFrame, weekly: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy()

    # Daily
    d['sma200']   = sma(d['close'], SMA_TREND)
    d['rsi']      = rsi(d['close'])
    d['atr']      = atr(d['high'], d['low'], d['close'])
    d['swing_lo'] = d['low'].rolling(SWING_BARS).min()
    d['swing_hi'] = d['high'].rolling(SWING_BARS).max()

    # Weekly EMA forward-filled to daily index (no look-ahead — uses prior completed week)
    w = weekly.copy()
    w['w_ema20'] = ema(w['close'], EMA_FAST)
    aligned = w[['w_ema20']].reindex(d.index, method='ffill')
    d = d.join(aligned)

    return d
