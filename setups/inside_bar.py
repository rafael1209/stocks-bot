"""Entry model #1: inside bar.

Every setup needs at least one context:
  continuation    – uptrend intact (higher lows), healthy pullback, SMA10 touch
  trendline_break – the entry breaks a real descending resistance line (3+ touches)
  level_break     – the entry breaks a value zone: a level the stock stalled at
                    before, the premarket high, or a prior day's high/low
Entry = mother high, stop = inside-bar low, target = entry + R:R x risk.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from data import resample
from indicators import (Run, Trendline, day_run, descending_trendline, resistance_zones, sma,
                        sideways_minutes, support_zones, swing_lows, uptrend_intact)


@dataclass
class Setup:
    symbol: str
    timeframe: int
    kind: str
    mother_time: pd.Timestamp
    inside_time: pd.Timestamp
    entry: float
    stop: float
    target: float
    risk_pct: float
    target_pct: float
    mother_of_run: float
    inside_position: float      # 0 = bottom of mother bar, 1 = top
    hod: float
    realistic_target: bool      # target stays inside the price range already traded today
    sma_touch: bool
    run: Run
    trendline: Trendline | None = None
    extension: dict = field(default_factory=dict)  # {timeframe: % entry above SMA10}
    contexts: list[str] = field(default_factory=list)
    level: float | None = None
    level_label: str = ""
    history: dict = field(default_factory=dict)  # biggest recent daily run (see indicators.past_runs)
    status: str = "pending"     # pending | triggered | expired | cancelled | target | stopped
    trigger_time: pd.Timestamp | None = None
    exit_time: pd.Timestamp | None = None
    breakout_vol_vs_avg: float | None = None
    breakout_vol_vs_pullback: float | None = None
    score: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.symbol}|{self.timeframe}|{self.inside_time.isoformat()}"


def is_inside(mother: pd.Series, inside: pd.Series) -> bool:
    """Mother bar engulfs the next bar including wicks."""
    return inside["high"] <= mother["high"] and inside["low"] >= mother["low"]


def _reject(why: list | None, reason: str) -> None:
    if why is not None:
        why.append(reason)
    return None


def evaluate(symbol: str, tf_df: pd.DataFrame, i: int, m1_day: pd.DataFrame, cfg: dict,
             timeframe: int, why: list | None = None, daily_levels: list[float] | None = None) -> Setup | None:
    """Check whether bars i-1 (mother) and i (inside) of tf_df form a valid setup,
    using only data available when bar i closed. Rejection reasons go into `why`."""
    if i < 1:
        return None
    mother, inside = tf_df.iloc[i - 1], tf_df.iloc[i]
    if not is_inside(mother, inside):
        return _reject(why, "not an inside bar (the next bar is not engulfed incl. wicks)")

    ib, tr, tl = cfg["inside_bar"], cfg["trend"], cfg["trendline"]
    close_time = tf_df.index[i] + pd.Timedelta(minutes=timeframe)
    m1 = m1_day[m1_day.index < close_time]
    run = day_run(m1)
    if run is None:
        return _reject(why, "no run found yet for the day")

    # never long against the main trend: a stock that gave back most of its run is in sellers' hands
    if run.pullback_of_run > tr.get("max_giveback_of_run", 1):
        return _reject(why, f"gave back {run.pullback_of_run:.0%} of the run (max {tr['max_giveback_of_run']:.0%}) – main trend is down")

    entry, stop = float(mother["high"]), float(inside["low"])

    # descending trendline running through the setup: the entry is the BREAK of the line,
    # never under it – entry = max(mother high, line value at the next bar)  (CHSN 2026-11-03)
    line = None
    if tl.get("enabled"):
        line = descending_trendline(tf_df.iloc[: i - 1], tl["pivot_span"], tl["min_touches"], tl["touch_tolerance_pct"])
        if line is not None:
            lv = line.value_at(tf_df.index[i])
            if stop <= lv <= entry * (1 + tl.get("max_line_above_entry_pct", tl["touch_tolerance_pct"]) / 100):
                entry = max(entry, float(line.value_at(tf_df.index[i] + pd.Timedelta(minutes=timeframe))))
            else:
                line = None

    risk = entry - stop
    if risk <= 0:
        return _reject(why, "no risk (entry <= stop)")
    risk_pct = risk / entry * 100
    target = entry + ib["reward_risk"] * risk
    target_pct = (target / entry - 1) * 100
    if target_pct < ib["min_target_pct"]:
        return _reject(why, f"target only +{target_pct:.1f}% (min {ib['min_target_pct']}%) – stop too tight")

    mother_rng = float(mother["high"] - mother["low"])
    mother_of_run = mother_rng / (run.high - run.low)
    if mother_of_run > ib["max_mother_of_run"]:
        return _reject(why, f"mother bar is {mother_of_run:.0%} of the run (max {ib['max_mother_of_run']:.0%})")

    realistic = target <= run.high
    if ib.get("require_realistic_target") and not realistic:
        return _reject(why, f"target {target:.4f} above high of day {run.high:.4f}")

    # sellers defending the entry: repeated upper wicks at the same level
    wk = cfg.get("wicks")
    if wk:
        near = tf_df.iloc[max(0, i + 1 - wk["lookback_bars"]): i + 1]
        near = near[(near["high"] - entry).abs() / entry * 100 <= wk["level_tolerance_pct"]]
        rng = (near["high"] - near["low"]).replace(0, float("nan"))
        upper = (near["high"] - near[["open", "close"]].max(axis=1)) / rng
        rejections = int((upper >= wk["min_wick_share"]).sum())
        if rejections >= wk["max_rejections"]:
            return _reject(why, f"{rejections} upper wicks at the entry level {entry:.4g} – sellers defending it")

    # no directionless range: stuck in a narrow band for a long time before the setup (MERC 2026-11-03)
    rg = cfg.get("range")
    if rg:
        mins = sideways_minutes(m1_day[m1_day.index < tf_df.index[i]], rg["band_pct"])
        if mins >= rg["max_minutes"]:
            return _reject(why, f"sideways {mins} min inside a {rg['band_pct']}% band – a range with no direction")

    ext = extension(m1, entry, cfg, premarket=is_premarket(tf_df.index[i]))
    for tf_chk, pct in ext.items():
        limit = cfg["extension"]["max_pct"][tf_chk]
        if pct > limit:
            return _reject(why, f"extended {pct:.0f}% above SMA10 on the {tf_chk}m chart (max {limit}%)")

    # SMA10 touched within the last few bars of the setup's own timeframe
    s = sma(tf_df["close"].iloc[: i + 1], tr["sma_length"])
    n = tr["sma_touch_lookback_bars"]
    recent = tf_df.iloc[max(0, i + 1 - n): i + 1]
    tol = 1 + tr["sma_touch_tolerance_pct"] / 100
    sma_touch = bool((recent["low"] <= s.loc[recent.index] * tol).any())

    contexts, failed = [], []
    hist = tf_df.iloc[: i - 1]  # bars before the mother bar

    # 1. descending trendline break (found above, entry already set at the break of the line)
    if line is not None:
        contexts.append("trendline_break")
    elif tl.get("enabled"):
        failed.append(f"no downtrend line ({tl['min_touches']}+ touches) at the entry")

    # 2. value-zone breakout
    level, level_label = _level_break(hist, m1, entry, float(inside["high"]), tf_df.index[i], cfg, daily_levels)
    if level is not None:
        contexts.append("level_break")
    else:
        failed.append("no value zone at the entry")

    # 3. uptrend intact (continuation)
    up = cfg.get("uptrend", {})
    ok, up_reason = uptrend_intact(tf_df.iloc[: i + 1], run.high_time, up.get("pivot_span", 2),
                                   up.get("tolerance_pct", 1))
    if not ok:
        failed.append(f"uptrend broken ({up_reason})")
    elif run.pullback_of_run > tr["hard_max_pullback_of_run"]:
        failed.append(f"pullback {run.pullback_of_run:.0%} of the run (max {tr['hard_max_pullback_of_run']:.0%})")
    elif tr.get("require_recent_sma_touch") and not sma_touch:
        failed.append(f"no SMA10 touch on the {timeframe}m chart in the last {n} bars")
    else:
        contexts.append("continuation")

    # a value-zone breakout alone (no uptrend, no downtrend line) must come from the base the
    # stock built after its high – under that base the sellers still own the stock (RBNE)
    if contexts == ["level_break"]:
        post_high = hist[hist.index > run.high_time]
        base = [float(post_high.loc[t, "low"]) for t in swing_lows(post_high, 2)]
        if base and entry < min(base):
            contexts = []
            failed.append(f"value zone {level:.4g} is under the post-high base {min(base):.4g} – against the main trend")

    if not contexts:
        return _reject(why, "no context: " + "; ".join(failed))

    # resistance right overhead: a strong level between the entry and the first part of the move
    blocker = _overhead_resistance(hist, m1, entry, risk, tf_df.index[i], cfg, daily_levels)
    if blocker:
        return _reject(why, f"resistance overhead at {blocker[0]:.4g} ({blocker[1]}) – no room to run")
    kind = contexts[0]

    inside_mid = (inside["high"] + inside["low"]) / 2
    position = float((inside_mid - mother["low"]) / mother_rng) if mother_rng else 1.0

    return Setup(symbol, timeframe, kind, tf_df.index[i - 1], tf_df.index[i], entry, stop, target,
                 risk_pct, target_pct, mother_of_run, position, run.high, realistic, sma_touch,
                 run, line, ext, contexts, level, level_label)


def _level_break(hist: pd.DataFrame, m1: pd.DataFrame, entry: float, inside_high: float,
                 t: pd.Timestamp, cfg: dict, daily_levels: list[float] | None) -> tuple[float | None, str]:
    """Nearest value zone that the entry breaks: price was held under it and the
    breakout of the mother bar takes it out."""
    lv = cfg.get("levels")
    if not lv:
        return None, ""
    cands = []
    # intraday zones the stock kept stalling at: 0 of 19 reached the target in the backtest
    if lv.get("include_intraday_zones"):
        cands += [(p, f"{n} נגיעות") for p, n in resistance_zones(hist, lv["pivot_span"], lv["cluster_pct"], lv["min_touches"])]
    if lv.get("include_premarket_high") and not is_premarket(t):
        pre = m1[[is_premarket(x) for x in m1.index]]
        if not pre.empty:
            cands.append((float(pre["high"].max()), "היי פרה-מרקט"))
    if lv.get("include_daily_levels") and daily_levels:
        cands += [(p, "רמה יומית") for p in daily_levels]
    if lv.get("include_round_numbers"):
        cands += [(p, "מספר עגול") for p in round_numbers(entry)]
    best = None
    for p, label in cands:
        if p <= 0:
            continue
        broken_by_entry = p * (1 - lv["max_level_above_entry_pct"] / 100) <= entry <= p * (1 + lv["max_entry_above_level_pct"] / 100)
        held_under = inside_high <= p * (1 + lv["max_entry_above_level_pct"] / 100)
        if broken_by_entry and held_under and (best is None or abs(p - entry) < abs(best[0] - entry)):
            best = (p, label)
    if best is None:
        return None, ""
    p, label = best
    if label != "מספר עגול" and any(abs(r / p - 1) <= 0.005 for r in round_numbers(p)):
        label += " + מספר עגול"
    return p, label


def _overhead_resistance(hist: pd.DataFrame, m1: pd.DataFrame, entry: float, risk: float, t: pd.Timestamp,
                         cfg: dict, daily_levels: list[float] | None) -> tuple[float, str] | None:
    """First strong level above the entry within `within_r` x risk (e.g. 0.30 over a 0.29 entry)."""
    oc = cfg.get("overhead")
    if not oc:
        return None
    lv = cfg["levels"]
    lo, hi = entry * (1 + lv["max_entry_above_level_pct"] / 300), entry + oc["within_r"] * risk
    cands = [(p, "round number") for p in round_numbers(entry)]
    if oc.get("include_intraday_zones"):  # off by default: too many weak 2-touch zones
        cands += [(p, f"{n} touches today") for p, n in
                  resistance_zones(hist, lv["pivot_span"], lv["cluster_pct"], oc.get("zone_min_touches", 3))]
    if oc.get("include_daily_levels") and daily_levels:  # off: 15-20 per stock would block everything
        cands += [(p, "daily level") for p in daily_levels]
    if not is_premarket(t):
        pre = m1[[is_premarket(x) for x in m1.index]]
        if not pre.empty:
            cands.append((float(pre["high"].max()), "premarket high"))
    inside = sorted((p, why) for p, why in cands if lo < p <= hi)
    return inside[0] if inside else None


def round_numbers(price: float) -> list[float]:
    """Psychological levels around the price ($1 for pennies, half dollars, whole dollars...)."""
    if price < 1:
        steps = [0.10, 0.25]
    elif price < 10:
        steps = [0.50]
    elif price < 100:
        steps = [1.0]
    else:
        steps = [5.0]
    out = {1.0} if 0.8 <= price <= 1.2 else set()
    for st in steps:
        base = round(price / st) * st
        out.update(round(base + k * st, 4) for k in (-1, 0, 1))
    return sorted(p for p in out if p > 0)


def in_no_entry_window(t: pd.Timestamp, cfg: dict) -> bool:
    hhmm = t.strftime("%H:%M")
    return any(a <= hhmm < b for a, b in cfg.get("session", {}).get("no_entry_windows", []))


def is_premarket(t: pd.Timestamp) -> bool:
    return t.hour < 9 or (t.hour == 9 and t.minute < 30)


def extension(m1: pd.DataFrame, price: float, cfg: dict, premarket: bool) -> dict:
    """% the price sits above SMA10 on every checked chart (skips charts without 10 bars yet)."""
    ex = cfg.get("extension")
    if not ex:
        return {}
    out = {}
    for tf in ex["max_pct"]:
        if premarket and tf in ex.get("premarket_ignore", []):
            continue
        val = sma(resample(m1, tf)["close"], ex["sma_length"]).iloc[-1] if len(m1) else float("nan")
        if pd.notna(val) and val > 0:
            out[tf] = (price / val - 1) * 100
    return out


def cancel_level(setup: Setup, before: pd.DataFrame, cfg: dict) -> float:
    """Price a waiting setup must CLOSE under to be cancelled: a few % under the stop,
    or under a support zone sitting just below the stop (many bars held there)."""
    ib = cfg["inside_bar"]
    level = setup.stop * (1 - ib.get("stop_break_buffer_pct", 0) / 100)
    sh = ib.get("support_hold")
    if sh:
        for price, _ in support_zones(before, sh["pivot_span"], sh["cluster_pct"], sh["min_touches"]):
            if setup.stop * (1 - sh["max_gap_pct"] / 100) <= price <= setup.stop:
                level = min(level, price * (1 - sh["break_pct"] / 100))
    return level


def track(setup: Setup, tf_df: pd.DataFrame, cfg: dict) -> Setup:
    """Advance a setup through the bars after the inside bar."""
    ib, vol = cfg["inside_bar"], cfg["volume"]
    after = tf_df[tf_df.index > setup.inside_time]
    cancel_at = cancel_level(setup, tf_df[tf_df.index <= setup.inside_time], cfg)

    def broke(bar) -> bool:  # only a strong break of the stop cancels a waiting setup
        return (bar["close"] if ib["stop_break"] == "close" else bar["low"]) < cancel_at

    waited = 0
    for t, bar in after.iterrows():
        if setup.status == "pending":
            if in_no_entry_window(t, cfg):  # e.g. the first 15 minutes after the open
                if broke(bar):
                    setup.status, setup.exit_time = "cancelled", t
                    break
                continue
            waited += 1
            if bar["high"] >= setup.entry:
                setup.status, setup.trigger_time = "triggered", t
                hist = tf_df[tf_df.index < t]
                # Yahoo has no premarket volume (0) and the 09:30 bar holds the opening
                # auction – both would distort the averages
                hist = hist[(hist["volume"] > 0) & (hist.index.strftime("%H:%M") != "09:30")]
                avg = hist["volume"].tail(vol["avg_length"]).mean()
                pull = hist[hist.index > setup.run.high_time]["volume"].mean()
                # no volume data (e.g. Yahoo premarket) = unknown, not weak
                known = bar["volume"] > 0
                setup.breakout_vol_vs_avg = float(bar["volume"] / avg) if known and avg > 0 else None
                setup.breakout_vol_vs_pullback = float(bar["volume"] / pull) if known and pull > 0 else None
            else:
                if broke(bar):
                    setup.status, setup.exit_time = "cancelled", t
                    break
                if waited >= ib["valid_bars"]:
                    setup.status, setup.exit_time = "expired", t
                    break
                continue
        if setup.status == "triggered":
            # same bar touching both: assume the stop first (conservative)
            if bar["low"] <= setup.stop:
                setup.status, setup.exit_time = "stopped", t
                break
            if bar["high"] >= setup.target:
                setup.status, setup.exit_time = "target", t
                break
    return setup
