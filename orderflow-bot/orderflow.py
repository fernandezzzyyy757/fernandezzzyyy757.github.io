from dataclasses import dataclass

import numpy as np
import pandas as pd

import config


@dataclass
class Signal:
    kind: str
    timestamp: pd.Timestamp
    price: float
    detail: str


def add_proxy_delta(df: pd.DataFrame) -> pd.DataFrame:
    """Approximate buy/sell (delta) volume from OHLC bars.

    Real order flow needs bid/ask-tagged trades. As a free-data proxy, each
    bar's volume is split by where the close sits within the bar's range:
    a close near the high implies more aggressive buying, a close near the
    low implies more aggressive selling. This is a well-known approximation
    (similar to Chaikin/Twiggs money flow) but it is NOT true executed-side
    volume -- treat signals as a rough directional-pressure heuristic only.
    """
    df = df.copy()
    rng = (df["High"] - df["Low"]).replace(0, np.nan)
    close_location = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / rng
    close_location = close_location.fillna(0.0)
    df["delta"] = close_location * df["Volume"]
    df["cum_delta"] = df["delta"].cumsum()
    return df


def rolling_vpoc(df: pd.DataFrame, bucket_size: float = config.VPOC_BUCKET_SIZE) -> float:
    """Volume-weighted price level (highest-volume price bucket) over the window."""
    buckets = (df["Close"] / bucket_size).round() * bucket_size
    volume_by_bucket = df.groupby(buckets)["Volume"].sum()
    return float(volume_by_bucket.idxmax())


def nearest_round_number(price: float, step: float = config.ROUND_NUMBER_STEP) -> float:
    return round(price / step) * step


def detect_signals(df: pd.DataFrame) -> list[Signal]:
    if len(df) < max(config.TREND_RUN_LENGTH + 1, 20):
        return []

    df = add_proxy_delta(df)
    signals: list[Signal] = []

    last = df.iloc[-1]
    last_ts = df.index[-1]
    vpoc = rolling_vpoc(df)
    round_level = nearest_round_number(last["Close"])

    ranges = df["High"] - df["Low"]
    volumes = df["Volume"]
    abs_deltas = df["delta"].abs()

    range_threshold = np.percentile(ranges, config.TIGHT_RANGE_PERCENTILE)
    volume_threshold = np.percentile(volumes, config.HIGH_VOLUME_PERCENTILE)
    delta_threshold = np.percentile(abs_deltas, config.EXTREME_DELTA_PERCENTILE)

    near_vpoc = abs(last["Close"] - vpoc) <= config.LEVEL_PROXIMITY
    near_round = abs(last["Close"] - round_level) <= config.LEVEL_PROXIMITY

    # Absorption: tight range + high volume at a key level -- size is being
    # absorbed without the price actually moving through.
    if (
        ranges.iloc[-1] <= range_threshold
        and volumes.iloc[-1] >= volume_threshold
        and (near_vpoc or near_round)
    ):
        level_desc = f"VPOC {vpoc:.2f}" if near_vpoc else f"round number {round_level:.2f}"
        signals.append(
            Signal(
                kind="absorption",
                timestamp=last_ts,
                price=float(last["Close"]),
                detail=f"Tight range on high volume near {level_desc}.",
            )
        )

    # Exhaustion: an extreme delta print at the end of a run of same-direction
    # bars, i.e. a possible climax before reversal.
    directions = np.sign(df["Close"] - df["Open"]).replace(0, np.nan).ffill()
    run_length = 1
    for i in range(len(directions) - 2, -1, -1):
        if directions.iloc[i] == directions.iloc[-1]:
            run_length += 1
        else:
            break

    if run_length >= config.TREND_RUN_LENGTH and abs_deltas.iloc[-1] >= delta_threshold:
        direction = "up" if directions.iloc[-1] > 0 else "down"
        signals.append(
            Signal(
                kind="exhaustion",
                timestamp=last_ts,
                price=float(last["Close"]),
                detail=f"Extreme delta print after a {run_length}-bar {direction} run.",
            )
        )

    # Delta divergence: price makes a new local high/low over the window but
    # cumulative delta does not confirm it.
    window = df.iloc[-20:]
    price_is_new_high = last["Close"] >= window["Close"].max()
    price_is_new_low = last["Close"] <= window["Close"].min()
    cum_delta_is_new_high = last["cum_delta"] >= window["cum_delta"].max()
    cum_delta_is_new_low = last["cum_delta"] <= window["cum_delta"].min()

    if price_is_new_high and not cum_delta_is_new_high:
        signals.append(
            Signal(
                kind="bearish_divergence",
                timestamp=last_ts,
                price=float(last["Close"]),
                detail="New price high not confirmed by cumulative delta.",
            )
        )
    elif price_is_new_low and not cum_delta_is_new_low:
        signals.append(
            Signal(
                kind="bullish_divergence",
                timestamp=last_ts,
                price=float(last["Close"]),
                detail="New price low not confirmed by cumulative delta.",
            )
        )

    return signals
