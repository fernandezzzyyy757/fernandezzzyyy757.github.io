"""
Generates synthetic OHLCV data that mimics futures price behaviour:
- Geometric Brownian Motion base
- Trend regimes (bull/bear) that persist for months → gives the multi-TF
  trend filter something real to latch onto
- Volatility clustering (quiet periods followed by noisy periods)
Used only for smoke-testing the backtest engine locally or in CI.
Run with real yfinance data in production.
"""

import numpy as np
import pandas as pd
from datetime import datetime


# Approximate daily vol and drift for each instrument
_PARAMS = {
    'MNQ': dict(annual_vol=0.22, annual_drift=0.10, price=15_000),
    'MES': dict(annual_vol=0.18, annual_drift=0.08, price=4_500),
    'MGC': dict(annual_vol=0.14, annual_drift=0.04, price=1_900),
    'SI':  dict(annual_vol=0.25, annual_drift=0.03, price=23),
    # fallback for legacy names
    'NQ':  dict(annual_vol=0.22, annual_drift=0.10, price=15_000),
    'ES':  dict(annual_vol=0.18, annual_drift=0.08, price=4_500),
    'GC':  dict(annual_vol=0.14, annual_drift=0.04, price=1_900),
}


def generate(symbol: str, start: str = '2005-01-01',
             end: str = '2024-01-01', seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    params = _PARAMS.get(symbol, _PARAMS['ES'])

    dates = pd.bdate_range(start=start, end=end)
    n     = len(dates)

    daily_vol   = params['annual_vol']   / np.sqrt(252)
    daily_drift = params['annual_drift'] / 252

    # Regime: switch bull/bear every ~6 months on average
    regime_len = int(252 / 2)
    regimes    = np.repeat(
        rng.choice([1, -1], size=(n // regime_len) + 2),
        regime_len
    )[:n]

    # Vol clustering: quiet / noisy alternates
    vol_mult  = 1 + 0.5 * np.abs(np.sin(np.linspace(0, 6 * np.pi, n)))

    # Build close series
    log_returns = (
        daily_drift * regimes
        + daily_vol * vol_mult * rng.standard_normal(n)
    )
    close = params['price'] * np.exp(np.cumsum(log_returns))

    # OHLC from close
    bar_range = close * daily_vol * vol_mult * rng.uniform(0.8, 1.2, n)
    open_  = close * np.exp(-log_returns)                   # prev close
    high   = np.maximum(open_, close) + bar_range * 0.6
    low    = np.minimum(open_, close) - bar_range * 0.6
    volume = (rng.uniform(50_000, 200_000, n) * vol_mult).astype(int)

    df = pd.DataFrame({
        'open':   open_,
        'high':   high,
        'low':    low,
        'close':  close,
        'volume': volume,
    }, index=dates)

    return df
