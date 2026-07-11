#!/usr/bin/env python3
"""
MNQ "institutional footprint" strategy backtest.

Strategy (long side; shorts are fully mirrored):
  1. LIQUIDITY SWEEP  - price takes out a prior swing low (20-bar lookback,
     3-bar pivot) by >= 2 ticks, then closes back above it within 3 bars.
  2. DISPLACEMENT     - a bar with range >= 1.5x ATR(14), close in top 30% of
     its range, that creates a (bullish) FVG.
  3. ENTRY            - resting limit at 50% of the FVG, OR market entry when
     an opposing FVG is inverted (iFVG: close through a bearish FVG) while
     the setup is pending.
  4. CONFLUENCE       - entry zone must overlap a session volume-profile LVN
     and sit below the developing POC (variant B/D filter; note that
     "reversion room to POC" is structurally required in ALL variants because
     the developing POC is Target 1 - a setup with no room to T1 is untradeable).
  5. DELTA PROXY      - per-bar uptick/downtick volume approximation
     (no footprint data): require cumulative-delta divergence at the sweep
     low (price lower low, delta higher low) OR delta flip positive on the
     displacement bar (variant C/D filter).

Risk:
  - Stop: 2 ticks beyond the FVG boundary (not the sweep wick).
  - T1  : developing POC (half off, stop to breakeven).
  - T2  : opposing value-area edge (VAH for longs, VAL for shorts).
  - Max 3 trades/day, no entries 15:30-18:00 ET, flat by 16:55 ET.
  - Sessions: NY AM 09:30-11:30 ET and NY PM 13:30-15:30 ET only.

Costs: $0.52 round-turn commission per contract + 1 tick adverse slippage on
EVERY fill (entries, targets, stops, forced flat). 2 contracts per trade so
the 50%-off at T1 is a whole contract.

Ablation: A = sweep+FVG, B = A+profile confluence, C = A+delta, D = B+C.

Validation: 70/30 chronological train/test split, per-variant metrics net of
costs, and a 10k-resample bootstrap 95% CI on expectancy (R). Variants whose
CI includes zero are flagged.

Data: 1-minute OHLCV CSV (columns: timestamp,open,high,low,close,volume) via
--csv/--tz, or --synthetic to generate a realistic MNQ-like series for a
smoke test. Signals are computed on a resampled signal timeframe (default
5min); order fills, stops and targets are simulated bar-by-bar on 1m data.

Conservatism choices (all deliberate):
  - If a 1m bar touches both stop and target, the stop is assumed first.
  - If the entry limit and stop are both touched in the fill bar, the trade
    is an immediate loss.
  - Slippage is charged even on limit fills.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TICK = 0.25          # MNQ tick size
PT_VALUE = 2.0       # $ per index point per MNQ contract
ET = "America/New_York"


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

@dataclass
class Config:
    signal_tf: str = "5min"     # timeframe for structure/signal detection
    pivot_strength: int = 3     # bars each side for a swing pivot
    sweep_lookback: int = 20    # max signal bars between pivot and sweep
    sweep_ticks: int = 2        # min penetration beyond the pivot, in ticks
    reclaim_bars: int = 3       # bars allowed to close back through the pivot
    disp_window: int = 5        # bars after reclaim in which displacement may occur
    atr_len: int = 14
    disp_atr_mult: float = 1.5
    disp_close_pct: float = 0.30   # close must be in top/bottom 30% of range
    setup_ttl_bars: int = 12       # signal bars a pending limit stays working
    stop_ticks: int = 2            # stop beyond FVG boundary
    min_room_ticks: int = 2        # min distance entry -> T1 (POC)
    bin_size: float = 1.0          # volume-profile bin, points
    va_pct: float = 0.70           # value-area coverage
    lvn_frac: float = 0.35         # LVN: bin vol < frac * mean(nonzero bins)
    lvn_zone_ticks: int = 2        # entry zone half-width for LVN overlap test
    fvg_max_age: int = 30          # signal bars an opposing FVG stays eligible for iFVG
    contracts: int = 2             # 2 so "50% off at T1" is one whole contract
    commission_rt: float = 0.52    # $ round-turn per contract
    slippage_ticks: int = 1        # adverse ticks per side, every fill
    max_trades_day: int = 3
    # entry windows, minutes since midnight ET
    windows: tuple = ((9 * 60 + 30, 11 * 60 + 30), (13 * 60 + 30, 15 * 60 + 30))
    flat_minute: int = 16 * 60 + 55
    bootstrap_n: int = 10_000
    train_frac: float = 0.70
    seed: int = 7


VARIANTS = {
    "A": dict(use_lvn=False, use_delta=False, label="sweep + FVG only"),
    "B": dict(use_lvn=True, use_delta=False, label="A + volume-profile confluence"),
    "C": dict(use_lvn=False, use_delta=True, label="A + delta proxy filter"),
    "D": dict(use_lvn=True, use_delta=True, label="full stack (B + C)"),
}


# --------------------------------------------------------------------------
# Data loading / synthetic generation
# --------------------------------------------------------------------------

def load_csv(path: str, tz: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    need = ["timestamp", "open", "high", "low", "close", "volume"]
    alias = {"timestamp": ["timestamp", "time", "datetime", "date"]}
    ts_col = next((cols[a] for a in alias["timestamp"] if a in cols), None)
    if ts_col is None:
        sys.exit(f"CSV must have a timestamp column (one of {alias['timestamp']})")
    for c in need[1:]:
        if c not in cols:
            sys.exit(f"CSV missing column '{c}' (found: {list(df.columns)})")
    out = pd.DataFrame({
        "open": pd.to_numeric(df[cols["open"]]),
        "high": pd.to_numeric(df[cols["high"]]),
        "low": pd.to_numeric(df[cols["low"]]),
        "close": pd.to_numeric(df[cols["close"]]),
        "volume": pd.to_numeric(df[cols["volume"]]).fillna(0.0),
    })
    ts = pd.to_datetime(df[ts_col], utc=False)
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(tz)
    out.index = ts.dt.tz_convert(ET)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="first")]
    return out


def synthetic_mnq(days: int, seed: int) -> pd.DataFrame:
    """Realistic-ish MNQ 1m series: Globex day 18:00 -> 17:00 ET, U-shaped
    intraday volatility/volume, fat-tailed returns, mild intraday mean
    reversion so sweeps and reversals occur naturally."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp("2026-07-03", tz=ET)
    bdays = pd.bdate_range(end=end, periods=days)

    def vol_factor(minute_of_day: np.ndarray) -> np.ndarray:
        f = np.full(minute_of_day.shape, 0.35)
        m = minute_of_day
        f = np.where((m >= 8 * 60) & (m < 9 * 60 + 30), 0.7, f)
        f = np.where((m >= 9 * 60 + 30) & (m < 10 * 60 + 30), 1.6, f)
        f = np.where((m >= 10 * 60 + 30) & (m < 11 * 60 + 30), 1.2, f)
        f = np.where((m >= 11 * 60 + 30) & (m < 13 * 60 + 30), 0.8, f)
        f = np.where((m >= 13 * 60 + 30) & (m < 15 * 60), 1.3, f)
        f = np.where((m >= 15 * 60) & (m < 16 * 60), 1.5, f)
        f = np.where((m >= 16 * 60) & (m < 17 * 60), 0.5, f)
        return f

    price = 21000.0
    frames = []
    for day in bdays:
        start = (day - pd.Timedelta(days=1)).replace(hour=18, minute=0)
        idx = pd.date_range(start, periods=23 * 60, freq="1min", tz=ET)
        mod = idx.hour.values * 60 + idx.minute.values
        vf = vol_factor(mod)
        sigma = 3.2 * vf                      # per-minute sigma in points
        drift = rng.normal(0, 0.15)           # day-level drift, pts/min
        anchor = price
        n = len(idx)
        # 4 sub-steps per minute for OHLC
        sub = rng.standard_t(4, size=(n, 4)) * (sigma[:, None] / 2.0)
        sub += drift / 4.0
        opens = np.empty(n)
        highs = np.empty(n)
        lows = np.empty(n)
        closes = np.empty(n)
        p = price
        for i in range(n):
            # mild mean reversion to the session anchor
            mr = 0.004 * (anchor - p)
            path = p + np.cumsum(sub[i] + mr)
            opens[i] = p
            highs[i] = max(p, path.max()) + abs(rng.normal(0, 0.3 * sigma[i]))
            lows[i] = min(p, path.min()) - abs(rng.normal(0, 0.3 * sigma[i]))
            closes[i] = path[-1]
            p = closes[i]
        price = p
        rets = np.abs(closes - opens) / np.maximum(sigma, 1e-9)
        vol = (rng.gamma(2.0, 400.0, size=n) * vf * (1 + 2.0 * rets)).astype(int) + 1
        q = TICK
        frames.append(pd.DataFrame({
            "open": np.round(opens / q) * q,
            "high": np.round(highs / q) * q,
            "low": np.round(lows / q) * q,
            "close": np.round(closes / q) * q,
            "volume": vol.astype(float),
        }, index=idx))
    df = pd.concat(frames)
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    return df


# --------------------------------------------------------------------------
# Precomputation
# --------------------------------------------------------------------------

def tick_rule_delta(c: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Uptick/downtick volume proxy on 1m closes (tick rule): +volume when the
    close upticks, -volume on a downtick, carry the previous sign on no change."""
    dc = np.diff(c, prepend=c[0])
    sign = pd.Series(np.sign(dc)).replace(0, np.nan).ffill().fillna(0).to_numpy()
    return sign * v


@dataclass
class MarketData:
    # 1m arrays
    t1: np.ndarray          # int64 ns, bar START times (ET wall data below)
    o1: np.ndarray
    h1: np.ndarray
    l1: np.ndarray
    c1: np.ndarray
    v1: np.ndarray
    mod1: np.ndarray        # minute-of-day ET
    skey1: np.ndarray       # session key (Globex day) ordinal
    idx1: pd.DatetimeIndex
    # signal-tf arrays
    tend5: np.ndarray       # int64 ns, bar END times
    o5: np.ndarray
    h5: np.ndarray
    l5: np.ndarray
    c5: np.ndarray
    atr5: np.ndarray
    delta5: np.ndarray
    cumdelta5: np.ndarray       # global cumsum (used for divergence differences)
    sesscum5: np.ndarray        # session-anchored cumulative delta (sign is meaningful)
    piv_lo5: np.ndarray     # bool: bar is a swing low (confirmed pivot_strength bars later)
    piv_hi5: np.ndarray
    idx5: pd.DatetimeIndex


def prepare(df1: pd.DataFrame, cfg: Config) -> MarketData:
    idx1 = df1.index
    mod1 = (idx1.hour * 60 + idx1.minute).values
    # Globex session key: 18:00 ET starts the next trading day (ET wall-clock date)
    skey1 = (idx1 + pd.Timedelta(hours=6)).tz_localize(None).normalize().to_numpy()

    agg = df1.resample(cfg.signal_tf, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["open"])
    idx5 = agg.index
    o5, h5, l5, c5, v5 = (agg[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume"))

    pc = np.concatenate([[c5[0]], c5[:-1]])
    tr = np.maximum(h5 - l5, np.maximum(np.abs(h5 - pc), np.abs(l5 - pc)))
    atr5 = pd.Series(tr).ewm(alpha=1 / cfg.atr_len, adjust=False,
                             min_periods=cfg.atr_len).mean().to_numpy()

    d1 = tick_rule_delta(df1["close"].to_numpy(float), df1["volume"].to_numpy(float))
    d5 = (pd.Series(d1, index=idx1).resample(cfg.signal_tf, label="left", closed="left")
          .sum().reindex(idx5).fillna(0.0).to_numpy())
    cum5 = np.cumsum(d5)
    skey5 = (idx5 + pd.Timedelta(hours=6)).tz_localize(None).normalize().to_numpy()
    sesscum5 = pd.Series(d5).groupby(skey5).cumsum().to_numpy()

    k = cfg.pivot_strength
    n = len(c5)
    piv_lo = np.zeros(n, bool)
    piv_hi = np.zeros(n, bool)
    for i in range(k, n - k):
        w_lo = l5[i - k:i + k + 1]
        if l5[i] == w_lo.min() and (w_lo == l5[i]).sum() == 1:
            piv_lo[i] = True
        w_hi = h5[i - k:i + k + 1]
        if h5[i] == w_hi.max() and (w_hi == h5[i]).sum() == 1:
            piv_hi[i] = True

    step = pd.Timedelta(cfg.signal_tf)
    tend5 = (idx5 + step).asi8

    return MarketData(
        t1=idx1.asi8, o1=df1["open"].to_numpy(float), h1=df1["high"].to_numpy(float),
        l1=df1["low"].to_numpy(float), c1=df1["close"].to_numpy(float),
        v1=df1["volume"].to_numpy(float), mod1=mod1, skey1=skey1, idx1=idx1,
        tend5=tend5, o5=o5, h5=h5, l5=l5, c5=c5, atr5=atr5,
        delta5=d5, cumdelta5=cum5, sesscum5=sesscum5,
        piv_lo5=piv_lo, piv_hi5=piv_hi, idx5=idx5,
    )


# --------------------------------------------------------------------------
# Session volume profile
# --------------------------------------------------------------------------

class SessionProfile:
    """Developing volume profile, accumulated 1m-bar by 1m-bar from the 18:00
    ET session open. Volume is split evenly across the price bins a bar spans."""

    def __init__(self, bin_size: float):
        self.bin = bin_size
        self.vols: dict[int, float] = {}

    def reset(self):
        self.vols.clear()

    def add(self, lo: float, hi: float, vol: float):
        b0 = int(np.floor(lo / self.bin))
        b1 = int(np.floor(hi / self.bin))
        nb = b1 - b0 + 1
        w = vol / nb
        for b in range(b0, b1 + 1):
            self.vols[b] = self.vols.get(b, 0.0) + w

    def poc(self) -> float | None:
        if not self.vols:
            return None
        b = max(self.vols, key=self.vols.get)
        return (b + 0.5) * self.bin

    def value_area(self, pct: float) -> tuple[float, float] | None:
        """Standard VA expansion from the POC bin outward, greedier side first."""
        if not self.vols:
            return None
        bins = sorted(self.vols)
        vols = np.array([self.vols[b] for b in bins])
        total = vols.sum()
        if total <= 0:
            return None
        p = int(np.argmax(vols))
        lo = hi = p
        acc = vols[p]
        while acc < pct * total and (lo > 0 or hi < len(bins) - 1):
            up = vols[hi + 1] if hi < len(bins) - 1 else -1.0
            dn = vols[lo - 1] if lo > 0 else -1.0
            if up >= dn:
                hi += 1
                acc += up
            else:
                lo -= 1
                acc += dn
        return bins[lo] * self.bin, (bins[hi] + 1) * self.bin  # (VAL, VAH)

    def lvn_bins(self, frac: float) -> list[tuple[float, float]]:
        """Bins that are local minima with volume < frac * mean(nonzero bins).
        Returns (price_lo, price_hi) ranges."""
        if len(self.vols) < 5:
            return []
        bins = sorted(self.vols)
        vols = np.array([self.vols[b] for b in bins])
        nz = vols[vols > 0]
        if len(nz) == 0:
            return []
        thresh = frac * nz.mean()
        out = []
        for i in range(1, len(bins) - 1):
            if vols[i] < thresh and vols[i] <= vols[i - 1] and vols[i] <= vols[i + 1]:
                out.append((bins[i] * self.bin, (bins[i] + 1) * self.bin))
        return out


# --------------------------------------------------------------------------
# Setup detection (side-parameterised: side=+1 long, side=-1 short)
# --------------------------------------------------------------------------

@dataclass
class Setup:
    side: int
    created_idx: int        # signal bar index at whose close the setup confirmed
    pivot_idx: int
    pivot_px: float
    sweep_idx: int
    sweep_ext: float        # sweep extreme (low for longs, high for shorts)
    disp_idx: int
    fvg_lo: float
    fvg_hi: float

    @property
    def mid(self) -> float:
        return (self.fvg_lo + self.fvg_hi) / 2.0

    def stop_px(self, cfg: Config) -> float:
        edge = self.fvg_lo if self.side > 0 else self.fvg_hi
        return edge - self.side * cfg.stop_ticks * TICK


class SweepDetector:
    """State machine over completed signal-tf bars for one side."""

    def __init__(self, side: int, md: MarketData, cfg: Config):
        self.side = side
        self.md = md
        self.cfg = cfg
        self.pivots: list[int] = []       # confirmed pivot indices
        self.sweeps: list[dict] = []      # awaiting reclaim
        self.armed: list[dict] = []       # reclaimed, awaiting displacement

    def on_bar(self, j: int) -> list[Setup]:
        md, cfg, s = self.md, self.cfg, self.side
        piv = md.piv_lo5 if s > 0 else md.piv_hi5
        ext = md.l5 if s > 0 else md.h5           # sweep side extreme
        px_piv = md.l5 if s > 0 else md.h5

        # pivot at j-k is now confirmed
        k = cfg.pivot_strength
        if j - k >= 0 and piv[j - k]:
            self.pivots.append(j - k)
        self.pivots = [p for p in self.pivots if j - p <= cfg.sweep_lookback]

        out: list[Setup] = []

        # --- new sweep? (most recent eligible pivot) ---
        if self.pivots:
            p = self.pivots[-1]
            pv = px_piv[p]
            if s * (pv - ext[j]) >= cfg.sweep_ticks * TICK:   # penetration >= 2 ticks
                self.sweeps.append(dict(pivot_idx=p, pivot_px=pv, sweep_idx=j,
                                        sweep_ext=ext[j]))

        # --- reclaim check ---
        still = []
        for sw in self.sweeps:
            if s * (md.c5[j] - sw["pivot_px"]) > 0:           # closed back through pivot
                self.armed.append(dict(**sw, reclaim_idx=j))
            elif j - sw["sweep_idx"] < cfg.reclaim_bars:
                still.append(sw)
            # else: expired without reclaim
        self.sweeps = still

        # --- displacement + FVG confirmation (bar j confirms an FVG on j-1) ---
        d = j - 1
        still = []
        for ar in self.armed:
            done = False
            if ar["reclaim_idx"] <= d <= ar["reclaim_idx"] + cfg.disp_window and d >= 1:
                rng_ = md.h5[d] - md.l5[d]
                atr = md.atr5[d]
                if rng_ > 0 and not np.isnan(atr) and rng_ >= cfg.disp_atr_mult * atr:
                    pos = (md.c5[d] - md.l5[d]) / rng_ if s > 0 else (md.h5[d] - md.c5[d]) / rng_
                    if pos >= 1.0 - cfg.disp_close_pct:
                        # FVG: gap between bar d-1 and bar d+1 (= j)
                        if s > 0 and md.l5[j] > md.h5[d - 1]:
                            out.append(Setup(s, j, ar["pivot_idx"], ar["pivot_px"],
                                             ar["sweep_idx"], ar["sweep_ext"], d,
                                             md.h5[d - 1], md.l5[j]))
                            done = True
                        elif s < 0 and md.h5[j] < md.l5[d - 1]:
                            out.append(Setup(s, j, ar["pivot_idx"], ar["pivot_px"],
                                             ar["sweep_idx"], ar["sweep_ext"], d,
                                             md.h5[j], md.l5[d - 1]))
                            done = True
            if not done and j - ar["reclaim_idx"] <= cfg.disp_window:
                still.append(ar)
        self.armed = still
        return out


class FVGBook:
    """Tracks open FVGs on the signal tf for iFVG (inversion) entries."""

    def __init__(self, md: MarketData, cfg: Config):
        self.md = md
        self.cfg = cfg
        self.bull: list[dict] = []   # zone below price; inverted when close < lo
        self.bear: list[dict] = []   # zone above price; inverted when close > hi

    def on_bar(self, j: int) -> dict[int, bool]:
        """Update book with bar j; FVG formed by (j-2, j-1, j). Returns
        {side: True} when an opposing FVG was inverted by bar j's close."""
        md, cfg = self.md, self.cfg
        events = {+1: False, -1: False}
        c = md.c5[j]
        for f in self.bear:
            if not f["inv"] and c > f["hi"]:
                f["inv"] = True
                events[+1] = True     # bearish FVG inverted -> long trigger
        for f in self.bull:
            if not f["inv"] and c < f["lo"]:
                f["inv"] = True
                events[-1] = True     # bullish FVG inverted -> short trigger
        if j >= 2:
            if md.l5[j] > md.h5[j - 2]:
                self.bull.append(dict(lo=md.h5[j - 2], hi=md.l5[j], idx=j, inv=False))
            if md.h5[j] < md.l5[j - 2]:
                self.bear.append(dict(lo=md.h5[j], hi=md.l5[j - 2], idx=j, inv=False))
        self.bull = [f for f in self.bull if j - f["idx"] <= cfg.fvg_max_age]
        self.bear = [f for f in self.bear if j - f["idx"] <= cfg.fvg_max_age]
        return events


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------

@dataclass
class Pending:
    setup: Setup
    limit: float
    stop: float
    t1: float
    t2: float
    placed_idx5: int
    market_entry: bool = False   # switched on by an iFVG event


@dataclass
class Position:
    setup: Setup
    entry_time: pd.Timestamp
    entry: float
    stop: float
    t1: float
    t2: float
    qty: int
    stop_init: float = 0.0       # original stop, for R denominator (stop moves to BE)
    half_done: bool = False
    realized_pts: float = 0.0    # signed points * contracts already banked
    entry_kind: str = "limit"


@dataclass
class Counters:
    setups: int = 0
    window_reject: int = 0
    room_reject: int = 0
    lvn_reject: int = 0
    delta_reject: int = 0
    busy_reject: int = 0
    daycap_reject: int = 0
    placed: int = 0
    filled_limit: int = 0
    filled_ifvg: int = 0
    cancelled_stop: int = 0
    cancelled_ttl: int = 0
    cancelled_window: int = 0
    # measured on every setup regardless of variant (diagnostic only)
    delta_div_true: int = 0
    delta_flip_true: int = 0
    lvn_true: int = 0


def in_window(mod: int, cfg: Config) -> bool:
    return any(a <= mod < b for a, b in cfg.windows)


def run_variant(md: MarketData, cfg: Config, use_lvn: bool, use_delta: bool):
    n1 = len(md.t1)
    n5 = len(md.tend5)
    trades: list[dict] = []
    cnt = Counters()

    profile = SessionProfile(cfg.bin_size)
    det = {+1: SweepDetector(+1, md, cfg), -1: SweepDetector(-1, md, cfg)}
    fvgs = FVGBook(md, cfg)
    pending: list[Pending] = []
    pos: Position | None = None
    session = None
    day_trades = 0
    j5 = 0
    slp = cfg.slippage_ticks * TICK

    def delta_ok(st: Setup) -> bool:
        """Divergence: price made a new extreme at the sweep but cumulative
        delta did not (delta higher low for longs). Flip: session cumulative
        delta was against the trade at the sweep and flipped through zero by
        the displacement bar close (a per-bar delta sign test is vacuous - a
        displacement bar closing in its top 30% has positive bar delta by
        construction under any per-bar proxy)."""
        s = st.side
        cd = md.cumdelta5
        divergence = s * (cd[st.sweep_idx] - cd[st.pivot_idx]) > 0
        flip = (s * md.sesscum5[st.sweep_idx] <= 0) and (s * md.sesscum5[st.disp_idx] > 0)
        cnt.delta_div_true += int(divergence)
        cnt.delta_flip_true += int(flip)
        return divergence or flip

    def try_create(st: Setup, i1: int):
        nonlocal pending
        cnt.setups += 1
        if not in_window(md.mod1[i1], cfg):
            cnt.window_reject += 1
            return
        if pos is not None or any(p.setup.side == st.side for p in pending):
            cnt.busy_reject += 1
            return
        if day_trades >= cfg.max_trades_day:
            cnt.daycap_reject += 1
            return
        s = st.side
        poc = profile.poc()
        va = profile.value_area(cfg.va_pct)
        if poc is None or va is None:
            cnt.room_reject += 1
            return
        t1 = poc
        entry = st.mid
        # structural: reversion room from entry to T1 (all variants)
        if s * (t1 - entry) < cfg.min_room_ticks * TICK:
            cnt.room_reject += 1
            return
        t2 = va[1] if s > 0 else va[0]     # VAH for longs, VAL for shorts
        if s * (t2 - t1) < 2 * TICK:
            t2 = t1                        # degenerate VA: runner exits at T1
        # evaluate both confluence conditions on every surviving setup so the
        # diagnostics funnel is comparable across variants
        zone = (st.fvg_lo, st.fvg_hi)   # entry zone = the FVG (limit rests at its mid)
        lvn_hit = any(zone[0] < hi and zone[1] > lo
                      for lo, hi in profile.lvn_bins(cfg.lvn_frac))
        cnt.lvn_true += int(lvn_hit)
        d_ok = delta_ok(st)
        if use_lvn and not lvn_hit:
            cnt.lvn_reject += 1
            return
        if use_delta and not d_ok:
            cnt.delta_reject += 1
            return
        stop = st.stop_px(cfg)
        if s * (entry - stop) <= 0:
            cnt.room_reject += 1
            return
        pending.append(Pending(st, entry, stop, t1, t2, st.created_idx))
        cnt.placed += 1

    def open_position(p: Pending, i1: int, entry_px: float, kind: str):
        nonlocal pos, pending, day_trades
        pos = Position(p.setup, md.idx1[i1], entry_px, p.stop, p.t1, p.t2,
                       cfg.contracts, stop_init=p.stop, entry_kind=kind)
        day_trades += 1
        pending = []      # single position; clear all working setups

    def close_trade(exit_time, reason):
        nonlocal pos
        st = pos.setup
        risk_pts = abs(pos.entry - pos.stop_init)
        gross = pos.realized_pts * PT_VALUE
        comm = cfg.contracts * cfg.commission_rt
        net = gross - comm
        r = net / (cfg.contracts * risk_pts * PT_VALUE) if risk_pts > 0 else 0.0
        trades.append(dict(
            side="L" if st.side > 0 else "S",
            entry_time=pos.entry_time, exit_time=exit_time,
            entry=pos.entry, stop=pos.stop_init, t1=pos.t1, t2=pos.t2,
            risk_pts=risk_pts, entry_kind=pos.entry_kind,
            gross_usd=round(gross, 2), net_usd=round(net, 2), r=r,
            exit_reason=reason, session=str(pos.entry_time.date()),
        ))
        pos = None

    for i in range(n1):
        t_start = md.t1[i]
        # ---- session rollover (18:00 ET Globex open) ----
        if md.skey1[i] != session:
            session = md.skey1[i]
            profile.reset()
            day_trades = 0
            pending = []

        # ---- 1. process signal-tf bars completed by now ----
        while j5 < n5 and md.tend5[j5] <= t_start:
            new_setups = []
            for side in (+1, -1):
                new_setups += det[side].on_bar(j5)
            inv = fvgs.on_bar(j5)
            for st in new_setups:
                try_create(st, i)
            # iFVG: pending setup goes market when an opposing FVG inverts
            for p in pending:
                if inv[p.setup.side]:
                    p.market_entry = True
            # TTL expiry
            keep = []
            for p in pending:
                if j5 - p.placed_idx5 >= cfg.setup_ttl_bars:
                    cnt.cancelled_ttl += 1
                else:
                    keep.append(p)
            pending = keep
            j5 += 1

        o, h, l, c = md.o1[i], md.h1[i], md.l1[i], md.c1[i]
        mod = md.mod1[i]
        ts = md.idx1[i]

        # ---- 2. manage open position ----
        if pos is not None:
            s = pos.setup.side
            if mod >= cfg.flat_minute and mod < 18 * 60:
                px = o - s * slp
                pos.realized_pts += s * (px - pos.entry) * pos.qty
                close_trade(ts, "flat_1655")
            else:
                # conservative: stop before target within the same bar
                stop_hit = (l <= pos.stop) if s > 0 else (h >= pos.stop)
                if stop_hit:
                    px = pos.stop - s * slp
                    pos.realized_pts += s * (px - pos.entry) * pos.qty
                    close_trade(ts, "stop" if not pos.half_done else "be_stop")
                else:
                    if not pos.half_done:
                        t1_hit = (h >= pos.t1) if s > 0 else (l <= pos.t1)
                        if t1_hit:
                            half = pos.qty // 2
                            px = pos.t1 - s * slp
                            pos.realized_pts += s * (px - pos.entry) * half
                            pos.qty -= half
                            pos.half_done = True
                            pos.stop = pos.entry            # breakeven
                    if pos is not None and pos.half_done:
                        t2_hit = (h >= pos.t2) if s > 0 else (l <= pos.t2)
                        if t2_hit:
                            px = pos.t2 - s * slp
                            pos.realized_pts += s * (px - pos.entry) * pos.qty
                            close_trade(ts, "t2")

        # ---- 3. pending entries ----
        if pos is None and pending:
            keep = []
            for p in pending:
                s = p.setup.side
                if pos is not None:
                    break                       # a fill this bar clears the book
                if not in_window(mod, cfg):
                    cnt.cancelled_window += 1
                    continue
                if p.market_entry:              # iFVG trigger: market at this bar's open
                    px = o + s * slp
                    if s * (px - p.stop) > 0 and s * (p.t1 - px) >= cfg.min_room_ticks * TICK:
                        open_position(p, i, px, "ifvg")
                        cnt.filled_ifvg += 1
                    else:
                        cnt.cancelled_stop += 1
                    continue
                touched = (l <= p.limit) if s > 0 else (h >= p.limit)
                pre_stop = (l <= p.stop) if s > 0 else (h >= p.stop)
                if touched:
                    open_position(p, i, p.limit + s * slp, "limit")
                    cnt.filled_limit += 1
                elif pre_stop:                  # invalidated before the limit filled
                    cnt.cancelled_stop += 1
                else:
                    keep.append(p)
            if pos is not None:
                pending = []
                # same-bar stop-out (conservative: no target credit this bar)
                s = pos.setup.side
                if (l <= pos.stop) if s > 0 else (h >= pos.stop):
                    px = pos.stop - s * slp
                    pos.realized_pts += s * (px - pos.entry) * pos.qty
                    close_trade(ts, "stop_same_bar")
            else:
                pending = keep

        # ---- 4. update developing profile with this bar ----
        profile.add(l, h, md.v1[i])

    # force-close anything left (end of data)
    if pos is not None:
        s = pos.setup.side
        px = md.c1[-1] - s * slp
        pos.realized_pts += s * (px - pos.entry) * pos.qty
        close_trade(md.idx1[-1], "eod_data")

    return pd.DataFrame(trades), cnt


# --------------------------------------------------------------------------
# Metrics / validation
# --------------------------------------------------------------------------

def bootstrap_ci(r: np.ndarray, n_boot: int, seed: int) -> tuple[float, float]:
    if len(r) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(r), size=(n_boot, len(r)))
    means = r[idx].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def metrics(tr: pd.DataFrame, cfg: Config) -> dict:
    if tr.empty:
        return dict(trades=0)
    r = tr["r"].to_numpy()
    usd = tr["net_usd"].to_numpy()
    wins = usd > 0
    equity = np.cumsum(usd)
    dd = equity - np.maximum.accumulate(equity)
    gross_w = usd[usd > 0].sum()
    gross_l = -usd[usd < 0].sum()
    lo, hi = bootstrap_ci(r, cfg.bootstrap_n, cfg.seed)
    return dict(
        trades=len(tr),
        win_pct=100.0 * wins.mean(),
        avg_r=float(r.mean()),
        expectancy_r=float(r.mean()),
        expectancy_usd=float(usd.mean()),
        max_dd_usd=float(dd.min()),
        profit_factor=(gross_w / gross_l) if gross_l > 0 else float("inf"),
        ci_lo=lo, ci_hi=hi,
        ci_includes_zero=(np.isnan(lo) or (lo <= 0.0 <= hi)),
        net_usd=float(usd.sum()),
    )


def fmt_row(name: str, m: dict) -> str:
    if m.get("trades", 0) == 0:
        return f"| {name} | 0 | - | - | - | - | - | - | - |"
    if np.isnan(m["ci_lo"]):
        ci = "n/a (n<2)"
    else:
        ci = f"[{m['ci_lo']:+.3f}, {m['ci_hi']:+.3f}]"
    flag = " ⚠️" if m["ci_includes_zero"] else ""
    pf = f"{m['profit_factor']:.2f}" if np.isfinite(m["profit_factor"]) else "inf"
    return (f"| {name} | {m['trades']} | {m['win_pct']:.1f}% | {m['avg_r']:+.3f} | "
            f"{m['expectancy_usd']:+.2f} | {m['max_dd_usd']:.2f} | {pf} | {ci}{flag} | "
            f"{m['net_usd']:+.2f} |")


HEADER = ("| variant | trades | win% | avg R | exp $ | maxDD $ | PF | "
          "expectancy 95% CI (R) | net $ |\n"
          "|---|---|---|---|---|---|---|---|---|")


def run_all(df1: pd.DataFrame, cfg: Config, outdir: str) -> str:
    md = prepare(df1, cfg)
    days = np.unique(md.skey1)
    cutoff_date = pd.Timestamp(days[int(len(days) * cfg.train_frac) - 1]).date()

    lines = ["# MNQ institutional-footprint backtest\n"]
    lines.append(f"- data: {md.idx1[0]} → {md.idx1[-1]}  ({len(md.idx1):,} 1m bars, "
                 f"{len(days)} sessions)")
    lines.append(f"- signal TF {cfg.signal_tf}; costs: ${cfg.commission_rt}/RT/contract "
                 f"+ {cfg.slippage_ticks} tick slippage per side (charged on every fill); "
                 f"{cfg.contracts} contracts/trade")
    lines.append(f"- train/test split: {cfg.train_frac:.0%} chronological "
                 f"(train through {cutoff_date})")
    lines.append(f"- bootstrap: {cfg.bootstrap_n:,} resamples, 95% CI on expectancy (R); "
                 "⚠️ = CI includes zero\n")

    all_trades = {}
    diag_lines = ["\n## Diagnostics (setup funnel per variant)\n",
                  "| variant | setups | window✗ | room✗ | lvn✗ | delta✗ | busy✗ | "
                  "cap✗ | placed | fill-limit | fill-iFVG | cxl-stop | cxl-ttl | cxl-win | "
                  "lvn✓ | div✓ | flip✓ |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]

    for name, spec in VARIANTS.items():
        tr, cnt = run_variant(md, cfg, spec["use_lvn"], spec["use_delta"])
        all_trades[name] = tr
        if not tr.empty:
            tr.to_csv(os.path.join(outdir, f"trades_{name}.csv"), index=False)
        diag_lines.append(
            f"| {name} | {cnt.setups} | {cnt.window_reject} | {cnt.room_reject} | "
            f"{cnt.lvn_reject} | {cnt.delta_reject} | {cnt.busy_reject} | "
            f"{cnt.daycap_reject} | {cnt.placed} | {cnt.filled_limit} | "
            f"{cnt.filled_ifvg} | {cnt.cancelled_stop} | {cnt.cancelled_ttl} | "
            f"{cnt.cancelled_window} | {cnt.lvn_true} | {cnt.delta_div_true} | "
            f"{cnt.delta_flip_true} |")

    for seg, mask_fn in (
        ("TRAIN", lambda tr: pd.to_datetime(tr["session"]).dt.date <= cutoff_date),
        ("TEST", lambda tr: pd.to_datetime(tr["session"]).dt.date > cutoff_date),
        ("FULL", lambda tr: pd.Series(True, index=tr.index)),
    ):
        lines.append(f"\n## {seg}\n")
        lines.append(HEADER)
        flagged = []
        for name, spec in VARIANTS.items():
            tr = all_trades[name]
            sub = tr[mask_fn(tr)] if not tr.empty else tr
            m = metrics(sub, cfg)
            lines.append(fmt_row(f"{name} ({spec['label']})", m))
            if m.get("ci_includes_zero", True):
                flagged.append(name)
        lines.append(f"\n⚠️ CI includes zero (not statistically distinguishable from "
                     f"breakeven): {', '.join(flagged) if flagged else 'none'}")

    lines += diag_lines
    report = "\n".join(lines) + "\n"
    with open(os.path.join(outdir, "report.md"), "w") as f:
        f.write(report)
    return report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="1m OHLCV CSV (timestamp,open,high,low,close,volume)")
    src.add_argument("--synthetic", action="store_true",
                     help="generate synthetic MNQ 1m data (smoke test)")
    ap.add_argument("--tz", default="UTC", help="timezone of naive CSV timestamps (default UTC)")
    ap.add_argument("--days", type=int, default=130, help="synthetic: trading days")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--signal-tf", default="5min", choices=["1min", "3min", "5min"])
    ap.add_argument("--bin-size", type=float, default=1.0, help="volume profile bin (points)")
    ap.add_argument("--out", default=None, help="output dir (default backtest/out)")
    args = ap.parse_args()

    cfg = Config(signal_tf=args.signal_tf, bin_size=args.bin_size, seed=args.seed)
    outdir = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(outdir, exist_ok=True)

    if args.synthetic:
        print(f"Generating synthetic MNQ 1m data: {args.days} days, seed {args.seed} ...")
        df1 = synthetic_mnq(args.days, args.seed)
    else:
        df1 = load_csv(args.csv, args.tz)
    report = run_all(df1, cfg, outdir)
    print(report)
    print(f"Outputs written to {outdir}/")


if __name__ == "__main__":
    main()
