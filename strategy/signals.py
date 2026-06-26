import pandas as pd
from config import RSI_OVERSOLD, RSI_OVERBOUGHT


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()

    # Multi-TF trend filters
    macro_bull  = d['close'] > d['sma200']
    macro_bear  = d['close'] < d['sma200']
    weekly_bull = d['close'] > d['w_ema20']
    weekly_bear = d['close'] < d['w_ema20']

    # RSI pullback crosses — signal fires on the bar the cross completes
    rsi_prev = d['rsi'].shift(1)
    rsi_cross_up   = (rsi_prev < RSI_OVERSOLD)  & (d['rsi'] >= RSI_OVERSOLD)
    rsi_cross_down = (rsi_prev > RSI_OVERBOUGHT) & (d['rsi'] <= RSI_OVERBOUGHT)

    # Long: all three timeframes aligned bullish + RSI recovered from oversold
    d['long_signal']  = macro_bull & weekly_bull & rsi_cross_up

    # Short: all three timeframes aligned bearish + RSI recovered from overbought
    d['short_signal'] = macro_bear & weekly_bear & rsi_cross_down

    return d
