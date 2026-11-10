"""Marked chart PNG: mother/inside bars, entry/stop/target, SMA10, trendline, volume."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import mplfinance as mpf
import pandas as pd

from indicators import sma
from setups.inside_bar import Setup


# dark theme to match the dashboard (and easier on the eyes in Telegram)
STYLE = mpf.make_mpf_style(
    base_mpf_style="nightclouds", facecolor="#121823", figcolor="#121823", edgecolor="#2b364a",
    gridcolor="#1f2633", gridstyle="-", rc={"axes.labelcolor": "#8b95a9", "xtick.color": "#8b95a9",
                                             "ytick.color": "#8b95a9", "text.color": "#e7ebf3"},
    marketcolors=mpf.make_marketcolors(up="#22c55e", down="#f05252", wick="inherit", edge="inherit",
                                       volume={"up": "#1f6f43", "down": "#7a2e33"}))


def render(setup: Setup, tf_df: pd.DataFrame, out_dir: str | Path = "charts", bars: int = 80) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    d = tf_df[tf_df.index <= setup.inside_time + pd.Timedelta(minutes=setup.timeframe * 12)].tail(bars)
    d = d.rename(columns=str.capitalize)

    adds = []
    ma = sma(d["Close"], 10)
    if ma.notna().any():  # fewer than 10 bars early in the session -> all NaN, mplfinance chokes on it
        adds.append(mpf.make_addplot(ma, color="#4c8dff", width=1.3))
    marks = pd.Series(float("nan"), index=d.index)
    for t in (setup.mother_time, setup.inside_time):
        if t in marks.index:
            marks[t] = d.loc[t, "Low"] * 0.985
    if marks.notna().any():
        adds.append(mpf.make_addplot(marks, type="scatter", marker="^", markersize=60, color="#ff9800"))

    levels, colors = [setup.entry, setup.stop, setup.target], ["#2e7d32", "#c62828", "#1565c0"]
    if setup.level is not None:  # the value zone being broken
        levels.append(setup.level)
        colors.append("#ff9800")
    lines = dict(hlines=levels, colors=colors,
                 linestyle="--", linewidths=1)
    kw = {}
    if setup.trendline is not None and setup.trendline.t1 in d.index:
        end = d.index[-1]
        kw["alines"] = dict(alines=[[(setup.trendline.t1, setup.trendline.p1),
                                     (end, setup.trendline.value_at(end))]], colors=["#8e24aa"])

    title = (f"{setup.symbol} {setup.timeframe}m  {setup.kind}  score {setup.score}\n"
             f"E {setup.entry:.4g}  S {setup.stop:.4g}  T {setup.target:.4g} (+{setup.target_pct:.1f}%)")
    path = out / f"{setup.symbol}_{setup.timeframe}m_{setup.inside_time:%Y%m%d_%H%M}.png"
    mpf.plot(d, type="candle", style=STYLE, volume=True, addplot=adds, hlines=lines, title=title,
             figsize=(11, 7), savefig=dict(fname=str(path), dpi=110, bbox_inches="tight"), **kw)
    return path
