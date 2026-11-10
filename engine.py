"""Shared pipeline: find, track and score inside-bar setups for one symbol's day."""
from __future__ import annotations

import sys

import pandas as pd

import data
import scoring
from indicators import past_runs
from setups.inside_bar import Setup, evaluate, track

# Windows consoles default to cp1252 – alerts contain Hebrew and emoji
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def load_config(path: str = "config.yaml") -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    data.SOURCE = cfg["data"].get("source", "tradingview")
    return cfg


def change_from_daily(daily: pd.DataFrame, day: pd.DataFrame) -> float | None:
    if day.empty:
        return None
    prior = daily[daily.index.date < day.index[-1].date()]
    if prior.empty:
        return None
    return (float(day["close"].iloc[-1]) / float(prior["close"].iloc[-1]) - 1) * 100


def closed_bars(tf_df: pd.DataFrame, tf: int, now: pd.Timestamp | None) -> pd.DataFrame:
    if now is None or tf_df.empty:
        return tf_df
    return tf_df[tf_df.index + pd.Timedelta(minutes=tf) <= now]


def setups_for_day(symbol: str, day: pd.DataFrame, daily: pd.DataFrame, cfg: dict,
                   change_pct: float | None, now: pd.Timestamp | None = None,
                   since: int | None = None) -> list[tuple[Setup, pd.DataFrame]]:
    """All setups of the day (or only those whose inside bar is among the last `since` bars)."""
    levels = scoring.daily_levels(daily, day.index[-1].date()) if not daily.empty else []
    prior = daily[daily.index.date < day.index[-1].date()] if not daily.empty else daily
    prev_close = float(prior["close"].iloc[-1]) if len(prior) else None
    min_gain = cfg["scanner"]["min_change_pct"]
    hc = cfg.get("history", {})
    history = past_runs(daily, day.index[-1].date(), hc.get("lookback_days", 22), hc.get("big_run_pct", 80))         if not daily.empty else {}
    out = []
    for tf in cfg["data"]["timeframes"]:
        tf_df = closed_bars(data.resample(day, tf), tf, now)
        start = 1 if since is None else max(1, len(tf_df) - since)
        for i in range(start, len(tf_df)):
            # the stock must still be up enough when the inside bar closes (e.g. RBNE faded to +23%)
            if prev_close and (tf_df["close"].iloc[i] / prev_close - 1) * 100 < min_gain:
                continue
            s = evaluate(symbol, tf_df, i, day, cfg, tf, daily_levels=levels)
            if s is None:
                continue
            track(s, tf_df, cfg)
            s.history = history
            scoring.score(s, cfg, change_pct, levels)
            out.append((s, tf_df))
    return out
