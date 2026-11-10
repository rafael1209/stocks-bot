import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import load_config  # noqa: E402
from setups.inside_bar import evaluate, is_inside, track  # noqa: E402

CFG = load_config(str(Path(__file__).resolve().parents[1] / "config.yaml"))


def bars(rows, start="2026-11-02 09:30"):
    idx = pd.date_range(start, periods=len(rows), freq="1min", tz="America/New_York")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def run_then_pullback():
    """Run 1.00 -> 2.00, pullback to ~1.75, mother bar then inside bar."""
    rows = [[1.0 + 0.1 * k, 1.05 + 0.1 * k, 0.98 + 0.1 * k, 1.05 + 0.1 * k, 50_000] for k in range(10)]
    rows += [[1.95, 2.00, 1.90, 1.92, 60_000],
             [1.92, 1.93, 1.80, 1.82, 30_000],
             [1.82, 1.84, 1.62, 1.70, 25_000],   # mother: high 1.84 low 1.62
             [1.72, 1.80, 1.70, 1.78, 15_000]]   # inside: within mother, upper part
    return bars(rows)


def test_is_inside_includes_wicks():
    m = pd.Series(dict(high=10, low=8))
    assert is_inside(m, pd.Series(dict(high=10, low=8)))
    assert not is_inside(m, pd.Series(dict(high=10.01, low=9)))
    assert not is_inside(m, pd.Series(dict(high=9.5, low=7.99)))


def test_levels_and_reward_risk():
    df = run_then_pullback()
    s = evaluate("TEST", df, len(df) - 1, df, CFG, 1)
    assert s is not None
    assert s.entry == pytest.approx(1.84)
    assert s.stop == pytest.approx(1.70)
    assert s.target == pytest.approx(1.84 + 2 * 0.14)
    assert s.target_pct >= 10


def test_realistic_target_flag():
    df = run_then_pullback()
    s = evaluate("TEST", df, len(df) - 1, df, CFG, 1)
    assert s.realistic_target == (s.target <= 2.00)


def test_rejects_small_target():
    df = run_then_pullback()
    df.iloc[-1, df.columns.get_loc("low")] = 1.80  # risk 0.04 -> target ~4%
    assert evaluate("TEST", df, len(df) - 1, df, CFG, 1) is None


def test_rejects_huge_mother_bar():
    df = run_then_pullback()
    df.iloc[-2, df.columns.get_loc("high")] = 1.99
    df.iloc[-2, df.columns.get_loc("low")] = 1.30  # 0.69 of a 1.02 run > 33%
    assert evaluate("TEST", df, len(df) - 1, df, CFG, 1) is None


def test_track_trigger_then_target():
    df = run_then_pullback()
    s = evaluate("TEST", df, len(df) - 1, df, CFG, 1)
    future = bars([[1.80, 1.86, 1.79, 1.85, 90_000],
                   [1.85, 2.20, 1.84, 2.15, 120_000]], start=str(df.index[-1].tz_localize(None) + pd.Timedelta(minutes=1)))
    full = pd.concat([df, future])
    track(s, full, CFG)
    assert s.status == "target"
    assert s.breakout_vol_vs_avg > 1


def test_track_cancel_on_close_below_stop():
    df = run_then_pullback()
    s = evaluate("TEST", df, len(df) - 1, df, CFG, 1)
    start = str(df.index[-1].tz_localize(None) + pd.Timedelta(minutes=1))
    small = bars([[1.75, 1.76, 1.64, 1.66, 40_000]], start=start)  # ~2% under the stop: not strong
    track(s, pd.concat([df, small]), CFG)
    assert s.status == "pending"
    s = evaluate("TEST", df, len(df) - 1, df, CFG, 1)
    strong = bars([[1.75, 1.76, 1.55, 1.58, 40_000]], start=start)  # ~7% under the stop
    track(s, pd.concat([df, strong]), CFG)
    assert s.status == "cancelled"


def test_track_expires_after_valid_bars():
    df = run_then_pullback()
    s = evaluate("TEST", df, len(df) - 1, df, CFG, 1)
    flat = [[1.76, 1.79, 1.72, 1.76, 10_000]] * 12
    future = bars(flat, start=str(df.index[-1].tz_localize(None) + pd.Timedelta(minutes=1)))
    track(s, pd.concat([df, future]), CFG)
    assert s.status == "expired"


def test_trendline_break_in_downtrend():
    """Deep downtrend (would fail the pullback rule) but inside bar breaks the falling resistance."""
    rows = [[1.0 + 0.15 * k, 1.05 + 0.15 * k, 0.98 + 0.15 * k, 1.05 + 0.15 * k, 50_000] for k in range(8)]
    rows.append([2.0, 2.10, 1.95, 2.0, 80_000])  # high of day
    # decline, bounce to a lower high at 1.72, decline again
    for h in [1.95, 1.80, 1.75, 1.90, 1.70, 1.62, 1.66, 1.72, 1.62, 1.55, 1.48, 1.42]:  # 1.90 = middle touch
        rows.append([h - 0.04, h, h - 0.10, h - 0.05, 30_000])
    df = bars(rows)
    from indicators import descending_trendline
    line = descending_trendline(df, CFG["trendline"]["pivot_span"], CFG["trendline"]["min_touches"],
                                CFG["trendline"]["touch_tolerance_pct"])
    assert line is not None
    lv = line.value_at(df.index[-1] + pd.Timedelta(minutes=2))  # line at the inside bar
    mother = [lv - 0.05, lv + 0.03, lv - 0.12, lv - 0.02, 20_000]
    inside = [lv - 0.02, lv + 0.01, lv - 0.08, lv, 12_000]
    df = bars(rows + [mother, inside])
    import copy
    cfg = copy.deepcopy(CFG)
    cfg.pop("overhead")  # the synthetic entry sits under the round 1.50 – isolate the line logic
    s = evaluate("TEST", df, len(df) - 1, df, cfg, 1)
    assert s is not None
    assert "continuation" not in s.contexts  # downtrend: only the line break qualifies
    assert s.kind == "trendline_break"
    # the entry is the break of the line, never under it (CHSN 2026-11-03)
    nxt = df.index[-1] + pd.Timedelta(minutes=1)
    assert s.entry >= s.trendline.value_at(nxt) - 1e-9
    assert abs(s.target - (s.entry + 2 * (s.entry - s.stop))) < 1e-9
    assert s.realistic_target  # target well under the 2.10 high


def _long_day(start, extended_last: bool):
    """4 hours of slow 1m climb (so 15m SMA10 exists), then mother + inside bar."""
    n = 240
    rows = [[1.0 + 0.004 * k, 1.01 + 0.004 * k, 0.995 + 0.004 * k, 1.005 + 0.004 * k, 20_000] for k in range(n)]
    top = rows[-1][3]
    if extended_last:  # vertical spike far above every SMA10
        rows += [[top * (1 + 0.1 * k), top * (1 + 0.1 * k + 0.08), top * (1 + 0.1 * k - 0.01),
                  top * (1 + 0.1 * k + 0.07), 90_000] for k in range(1, 6)]
        top = rows[-1][3]
    rows += [[top, top * 1.04, top * 0.88, top * 0.97, 60_000],
             [top * 0.97, top * 1.0, top * 0.95, top * 0.99, 30_000]]
    return bars(rows, start=start)


def test_extension_rejects_spike_on_low_timeframes():
    df = _long_day("2026-11-02 09:30", extended_last=True)
    why = []
    assert evaluate("TEST", df, len(df) - 1, df, CFG, 1, why) is None
    assert any("extended" in r for r in why), why


def test_extension_values_and_premarket_skips_15m():
    from setups.inside_bar import extension
    df = _long_day("2026-11-02 04:00", extended_last=False)
    regular = extension(df, df["close"].iloc[-1], CFG, premarket=False)
    pre = extension(df, df["close"].iloc[-1], CFG, premarket=True)
    assert 15 in regular and 15 not in pre
    assert set(pre) == {1, 3, 5}


def test_rejects_continuation_without_recent_sma_touch():
    df = run_then_pullback()
    # shallow pullback that never comes back to SMA10
    df.iloc[-4] = [1.95, 2.00, 1.90, 1.92, 60_000]
    df.iloc[-3] = [1.92, 1.95, 1.86, 1.90, 30_000]
    df.iloc[-2] = [1.90, 1.98, 1.86, 1.95, 25_000]   # mother
    df.iloc[-1] = [1.94, 1.96, 1.87, 1.95, 15_000]   # inside
    import copy
    cfg = copy.deepcopy(CFG)
    cfg["extension"]["max_pct"] = {k: 999 for k in cfg["extension"]["max_pct"]}  # isolate the touch rule
    cfg["levels"]["include_round_numbers"] = False  # 1.98 sits under the round 2.00
    why = []
    s = evaluate("TEST", df, len(df) - 1, df, cfg, 1, why)
    assert s is None, s
    assert any("SMA10 touch" in r for r in why), why


def test_no_entry_in_first_15_minutes_after_open():
    """Inside bar at 09:31; price breaks the entry at 09:33 (blocked), entry only from 09:45."""
    df = run_then_pullback()  # starts 09:30 in bars(); rebuild it ending at 09:31
    df.index = df.index - (df.index[-1] - pd.Timestamp("2026-11-02 09:31", tz="America/New_York"))
    s = evaluate("TEST", df, len(df) - 1, df, CFG, 1)
    assert s is not None
    early = bars([[1.80, 1.86, 1.79, 1.82, 90_000]] * 2 + [[1.80, 1.83, 1.79, 1.82, 9_000]] * 11,
                 start="2026-11-02 09:32")
    later = bars([[1.82, 1.88, 1.81, 1.86, 90_000]], start="2026-11-02 09:45")
    track(s, pd.concat([df, early, later]), CFG)
    assert s.status == "triggered"
    assert s.trigger_time == pd.Timestamp("2026-11-02 09:45", tz="America/New_York")


def test_past_runs_finds_biggest_recent_daily_run():
    from indicators import past_runs
    idx = pd.date_range("2026-10-01", periods=10, freq="B", tz="America/New_York")
    close = [1.0, 1.0, 1.0, 2.6, 2.0, 1.5, 1.4, 1.3, 1.2, 1.2]
    high = [1.05, 1.05, 1.05, 2.8, 2.1, 1.6, 1.5, 1.4, 1.3, 1.3]  # day 4: 1.0 -> 2.8 = +180%
    daily = pd.DataFrame({"open": close, "high": high, "low": close, "close": close, "volume": 1}, index=idx)
    h = past_runs(daily, idx[-1].date() + pd.Timedelta(days=1), lookback_days=22, big_pct=80)
    assert round(h["max_pct"]) == 180
    assert h["days_ago"] == 7 and h["big_runs"] == 1


def test_round_number_right_overhead_rejects():
    """INLF 2026-11-02: entry 0.2919 under the round 0.30 – resistance overhead, not a breakout."""
    from setups.inside_bar import _overhead_resistance
    df = run_then_pullback()
    hit = _overhead_resistance(df, df, 0.2919, 0.0167, df.index[-1], CFG, None)
    assert hit and hit[0] == 0.30
    assert _overhead_resistance(df, df, 0.2919, 0.0167 * 0.2, df.index[-1], CFG, None) is None  # out of reach


def test_sideways_minutes_counts_the_range():
    from indicators import sideways_minutes
    flat = bars([[1.00, 1.04, 0.97, 1.01, 1000]] * 50)          # 50 min inside ~7%
    assert sideways_minutes(flat, 10) == 50
    spike = bars([[1.0, 1.5, 0.9, 1.4, 1000]] + [[1.00, 1.04, 0.97, 1.01, 1000]] * 5)
    assert sideways_minutes(spike, 10) == 5                       # the spike breaks the band
