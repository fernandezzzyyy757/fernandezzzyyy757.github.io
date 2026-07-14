#!/usr/bin/env python3
"""
Regression tests for mnq_footprint_backtest.py — codifies the rule invariants
so future changes can't silently break them.

Run:  python backtest/test_backtest.py   (or: pytest backtest/test_backtest.py)
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mnq_footprint_backtest import (  # noqa: E402
    Config, SessionProfile, bootstrap_ci, load_csv, prepare, run_variant,
    synthetic_mnq, tick_rule_delta,
)

ET = "America/New_York"


def _trades_A(days: int = 40, seed: int = 11) -> pd.DataFrame:
    df = synthetic_mnq(days, seed)
    md = prepare(df, Config())
    tr, _ = run_variant(md, Config(), use_lvn=False, use_delta=False)
    assert len(tr) >= 10, f"expected a usable sample, got {len(tr)} trades"
    return tr


def test_rule_invariants():
    tr = _trades_A()
    et = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert(ET)
    xt = pd.to_datetime(tr["exit_time"], utc=True).dt.tz_convert(ET)
    mod_e = et.dt.hour * 60 + et.dt.minute
    mod_x = xt.dt.hour * 60 + xt.dt.minute

    in_am = (mod_e >= 570) & (mod_e < 690)
    in_pm = (mod_e >= 810) & (mod_e < 930)
    assert (in_am | in_pm).all(), "entry outside NY AM/PM windows"
    assert (mod_x <= 16 * 60 + 55).all(), "position held past 16:55 ET"
    assert tr.groupby("session").size().max() <= 3, "max 3 trades/day violated"

    L, S = tr[tr.side == "L"], tr[tr.side == "S"]
    assert len(L) and len(S), "one side never trades"
    assert (L.stop < L.entry).all() and (S.stop > S.entry).all(), "stop side wrong"
    assert (L.t1 > L.entry).all() and (S.t1 < S.entry).all(), "T1 side wrong"
    assert (L.t2 >= L.t1).all() and (S.t2 <= S.t1).all(), "T2 not beyond T1"

    # trades must not overlap (single position at a time)
    both = tr.sort_values("entry_time")
    prev_exit = pd.to_datetime(both["exit_time"], utc=True).shift(1)
    cur_entry = pd.to_datetime(both["entry_time"], utc=True)
    assert (cur_entry >= prev_exit).iloc[1:].all(), "overlapping trades"

    # net R of a full stop-out ~ -1 minus costs; should never be much worse
    # than -2 barring pathological tiny-risk trades
    assert tr.r.min() > -3.0, f"suspicious R floor: {tr.r.min()}"


def test_costs_are_charged():
    cfg = Config()
    tr = _trades_A()
    expected_comm = cfg.contracts * cfg.commission_rt
    assert np.allclose(tr.gross_usd - tr.net_usd, expected_comm, atol=0.01), \
        "commission not consistently applied"


def test_filters_only_narrow():
    """B/C/D trade sets must be (weakly) smaller than A and each variant's
    funnel must account for every setup."""
    df = synthetic_mnq(40, 11)
    md = prepare(df, Config())
    counts = {}
    for name, (lvn, dlt) in dict(A=(False, False), B=(True, False),
                                 C=(False, True), D=(True, True)).items():
        tr, cnt = run_variant(md, Config(), use_lvn=lvn, use_delta=dlt)
        counts[name] = len(tr)
        assert cnt.setups == (cnt.window_reject + cnt.busy_reject +
                              cnt.daycap_reject + cnt.room_reject +
                              cnt.lvn_reject + cnt.delta_reject + cnt.placed), \
            f"{name}: funnel doesn't sum"
    assert counts["B"] <= counts["A"] and counts["C"] <= counts["A"]
    assert counts["D"] <= min(counts["B"], counts["C"]) + 5, \
        "D should be near-strictest (small slack for engine interaction)"


def test_delta_source_selection(tmp_path=None):
    out = "/tmp/_delta_src_test.csv"
    n = 300
    idx = pd.date_range("2026-07-08 13:30", periods=n, freq="1min", tz="UTC")
    c = 22000 + np.cumsum(np.random.default_rng(1).normal(0, 2, n))
    base = pd.DataFrame({
        "timestamp": idx.tz_localize(None).strftime("%Y-%m-%d %H:%M:%S"),
        "open": c, "high": c + 2, "low": c - 2, "close": c,
        "volume": 100.0, "up_volume": 60.0, "down_volume": 40.0})
    base.to_csv(out, index=False)
    md = prepare(load_csv(out, "UTC"), Config())
    assert abs(md.delta5[1] - 100.0) < 1e-9, "real up/down split not used"
    base.drop(columns=["up_volume", "down_volume"]).to_csv(out, index=False)
    md2 = prepare(load_csv(out, "UTC"), Config())
    assert not np.allclose(md.delta5, md2.delta5), "proxy fallback identical to real"
    os.remove(out)


def test_tick_rule_carry():
    c = np.array([10.0, 11.0, 11.0, 10.0, 10.0])
    v = np.ones(5)
    d = tick_rule_delta(c, v)
    assert list(d) == [0.0, 1.0, 1.0, -1.0, -1.0], d  # unchanged carries sign


def test_profile_poc_va_lvn():
    p = SessionProfile(1.0)
    # bimodal: heavy nodes at 100-102 and 106-108, thin LVN at 104
    for lo, hi, v in [(100, 102, 900), (102, 104, 60), (104, 106, 60),
                      (106, 108, 800), (100.5, 101.5, 500)]:
        p.add(lo, hi, v)
    poc = p.poc()
    assert 100 <= poc <= 102, poc
    val, vah = p.value_area(0.70)
    assert val <= poc <= vah
    lvns = p.lvn_bins(0.5)
    assert any(lo <= 104 <= hi or lo <= 105 <= hi for lo, hi in lvns), \
        f"LVN around 104-105 not found: {lvns}"


def test_bootstrap_ci():
    rng = np.random.default_rng(0)
    r = rng.normal(0.5, 1.0, 200)
    lo, hi = bootstrap_ci(r, 2000, 0)
    assert lo < r.mean() < hi
    assert 0.2 < lo and hi < 0.8  # roughly mean +/- 2*se


def test_loader_tz():
    out = "/tmp/_tz_test.csv"
    pd.DataFrame({"timestamp": ["2026-07-09 13:30:00"], "open": [1.0],
                  "high": [1.0], "low": [1.0], "close": [1.0],
                  "volume": [1.0]}).to_csv(out, index=False)
    df = load_csv(out, "UTC")
    assert str(df.index[0]) == "2026-07-09 09:30:00-04:00"  # 13:30Z == 09:30 EDT
    os.remove(out)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
