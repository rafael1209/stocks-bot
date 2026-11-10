"""Indicators: SMA, volume averages, the day's run and pullback, descending trendlines."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length, min_periods=length).mean()


@dataclass
class Run:
    low: float          # low before the high of day
    high: float         # high of day so far
    high_time: pd.Timestamp
    run_pct: float      # % move low -> high
    pullback_pct: float  # % drop from high to current close
    pullback_of_run: float  # pullback as fraction of the run's range


def day_run(day: pd.DataFrame, upto: pd.Timestamp | None = None) -> Run | None:
    """The first run that put the stock on the scanner: session low (before HOD) to HOD."""
    d = day if upto is None else day[day.index <= upto]
    if len(d) < 3:
        return None
    high_time = d["high"].idxmax()
    high = float(d.loc[high_time, "high"])
    low = float(d.loc[:high_time, "low"].min())
    if low <= 0 or high <= low:
        return None
    last = float(d["close"].iloc[-1])
    rng = high - low
    return Run(low, high, high_time, (high / low - 1) * 100,
               (1 - last / high) * 100, (high - last) / rng)


@dataclass
class Trendline:
    t1: pd.Timestamp
    p1: float
    t2: pd.Timestamp
    p2: float
    touches: int

    def value_at(self, t: pd.Timestamp) -> float:
        span = (self.t2 - self.t1).total_seconds()
        slope = (self.p2 - self.p1) / span
        return self.p1 + slope * (t - self.t1).total_seconds()


def swing_highs(df: pd.DataFrame, span: int) -> list[pd.Timestamp]:
    h = df["high"].to_numpy()
    out = []
    for i in range(span, len(h) - span):
        if h[i] == h[i - span:i + span + 1].max():
            out.append(df.index[i])
    return out


def descending_trendline(df: pd.DataFrame, span: int = 3, min_touches: int = 2,
                         tol_pct: float = 1.0) -> Trendline | None:
    """Resistance line from the high of day through the most recent lower swing high.

    Every high between the anchors must stay under the line (within tolerance)."""
    if len(df) < span * 2 + 3:
        return None
    hod_t = df.index[df["high"] == df["high"].max()][-1]  # last bar at the high (ties)
    after = df[df.index >= hod_t]
    pivots = [t for t in swing_highs(after, span) if t != hod_t]
    if not pivots:
        return None
    p1 = float(df.loc[hod_t, "high"])
    for t2 in reversed(pivots):
        p2 = float(df.loc[t2, "high"])
        if p2 >= p1:
            continue
        line = Trendline(hod_t, p1, t2, p2, 0)
        seg = after[after.index <= t2]
        vals = np.array([line.value_at(t) for t in seg.index])
        if (seg["high"].to_numpy() > vals * (1 + tol_pct / 100)).any():
            continue
        # a touch is a separate reaction (a swing high) at the line, not bars sliding down it
        touch_pts = [hod_t, t2] + [t for t in swing_highs(seg, 2) if t not in (hod_t, t2)]
        line.touches = sum(abs(float(seg.loc[t, "high"]) / line.value_at(t) - 1) * 100 <= tol_pct for t in touch_pts)
        if line.touches >= min_touches:
            return line
    return None


def swing_lows(df: pd.DataFrame, span: int) -> list[pd.Timestamp]:
    lo = df["low"].to_numpy()
    return [df.index[i] for i in range(span, len(lo) - span) if lo[i] == lo[i - span:i + span + 1].min()]


def uptrend_intact(df: pd.DataFrame, run_high_time: pd.Timestamp, span: int, tol_pct: float) -> tuple[bool, str]:
    """Higher-low structure from the run low: the swing lows keep rising and nothing
    since the last swing low traded under it (within tolerance)."""
    before_hod = df[df.index <= run_high_time]
    if before_hod.empty:
        return False, "no run"
    run_low_t = before_hod["low"].idxmin()
    after = df[df.index >= run_low_t]
    pivots = [run_low_t] + [t for t in swing_lows(after, span) if t != run_low_t]
    lows = [float(df.loc[t, "low"]) for t in pivots]
    if len(lows) >= 2 and lows[-1] <= lows[-2] * (1 - tol_pct / 100):
        return False, f"lower low {lows[-1]:.4g} under {lows[-2]:.4g}"
    since = after[after.index > pivots[-1]]
    if not since.empty and since["low"].min() < lows[-1] * (1 - tol_pct / 100):
        return False, f"broke the last higher low {lows[-1]:.4g}"
    return True, f"higher lows, last {lows[-1]:.4g}"


def resistance_zones(df: pd.DataFrame, span: int, cluster_pct: float, min_touches: int) -> list[tuple[float, int]]:
    """Price zones where the stock stalled at least `min_touches` times (swing highs
    within cluster_pct of each other). Returns [(price, touches)]."""
    highs = sorted(float(df.loc[t, "high"]) for t in swing_highs(df, span))
    zones, used = [], set()
    for k, h in enumerate(highs):
        if k in used:
            continue
        group = [j for j, g in enumerate(highs) if j not in used and abs(g / h - 1) * 100 <= cluster_pct]
        if len(group) >= min_touches:
            used.update(group)
            zones.append((max(highs[j] for j in group), len(group)))
    return zones


def support_zones(df: pd.DataFrame, span: int, cluster_pct: float, min_touches: int) -> list[tuple[float, int]]:
    """Price zones where the stock found support at least `min_touches` times (swing lows
    within cluster_pct of each other). Returns [(price, touches)] – price = lowest low."""
    lows = sorted(float(df.loc[t, "low"]) for t in swing_lows(df, span))
    zones, used = [], set()
    for k, lo in enumerate(lows):
        if k in used:
            continue
        group = [j for j, g in enumerate(lows) if j not in used and abs(g / lo - 1) * 100 <= cluster_pct]
        if len(group) >= min_touches:
            used.update(group)
            zones.append((min(lows[j] for j in group), len(group)))
    return zones


def past_runs(daily: pd.DataFrame, today, lookback_days: int = 22, big_pct: float = 80) -> dict:
    """Biggest one-day runs (previous close -> day high) in the last N trading days before today.
    Stocks that ran 80-200% recently tend to run again."""
    prior = daily[daily.index.date < today]
    if len(prior) < 2:
        return {}
    run = (prior["high"] / prior["close"].shift(1) - 1) * 100
    last = run.tail(lookback_days).dropna()
    if last.empty:
        return {}
    t = last.idxmax()
    return {"max_pct": float(last.max()), "date": t.date().isoformat(),
            "days_ago": int(len(prior) - prior.index.get_loc(t)),  # trading days
            "big_runs": int((last >= big_pct).sum())}


def sideways_minutes(m1: pd.DataFrame, band_pct: float) -> int:
    """How many minutes back from the last bar the price stayed inside one band of at most
    band_pct (high/low of the whole stretch). Long = a directionless range."""
    hi = lo = None
    n = 0
    for h, l in zip(m1["high"].to_numpy()[::-1], m1["low"].to_numpy()[::-1]):
        h2 = h if hi is None else max(hi, h)
        l2 = l if lo is None else min(lo, l)
        if l2 <= 0 or (h2 / l2 - 1) * 100 > band_pct:
            break
        hi, lo, n = h2, l2, n + 1
    return n
