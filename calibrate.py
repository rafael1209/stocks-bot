"""Compare the bot with your own trades.

For every trade in my_trades.csv it answers:
  * did the bot find the same inside bar? with what score / outcome?
  * if not – which rule rejected it (so we know which threshold to loosen)
  * which other setups the bot flagged that day that you did not take (noise)

  py calibrate.py                    (reads my_trades.csv, times in Israel time)
  py calibrate.py --tz America/New_York

my_trades.csv columns (timeframe / result / note may be left empty):
  symbol,date,time,timeframe,entry,stop,result,note
  CLGN,2026-10-20,17:09,1,0.7614,0.677,target,news + big volume
Yahoo keeps only ~30 days of 1-minute bars, so trades must be from the last month.
"""
from __future__ import annotations

import argparse
from collections import Counter

import pandas as pd

import data
import scoring
from engine import change_from_daily, load_config
from setups.inside_bar import evaluate, track

PRICE_TOL = 0.02  # 2% – how close the bot's mother-bar high must be to your entry


def match(trade, day, daily, cfg, levels, change):
    """Best bot candidate for one trade: (setup or None, reasons, tf, mother/inside times)."""
    t_entry = trade["ts"]
    tfs = [int(trade["timeframe"])] if pd.notna(trade["timeframe"]) else cfg["data"]["timeframes"]
    best = None
    for tf in tfs:
        tf_df = data.resample(day, tf)
        window = (tf_df.index <= t_entry) & (tf_df.index >= t_entry - pd.Timedelta(minutes=tf * (cfg["inside_bar"]["valid_bars"] + 2)))
        for i in [k for k in range(1, len(tf_df)) if window[k]]:
            mother, inside = tf_df.iloc[i - 1], tf_df.iloc[i]
            err = abs(mother["high"] / trade["entry"] - 1)
            if pd.notna(trade["stop"]):
                err += abs(inside["low"] / trade["stop"] - 1)
            if best is None or err < best[0]:
                why = []
                s = evaluate(trade["symbol"], tf_df, i, day, cfg, tf, why, daily_levels=levels)
                if s is not None:
                    track(s, tf_df, cfg)
                    scoring.score(s, cfg, change, levels)
                best = (err, s, why, tf, tf_df.index[i - 1], tf_df.index[i], float(mother["high"]), float(inside["low"]))
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="my_trades.csv")
    ap.add_argument("--tz", default="Asia/Jerusalem", help="timezone of the times in the file")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = load_config(args.config)

    trades = pd.read_csv(args.file, comment="#", dtype={"symbol": str, "date": str, "time": str})
    trades["symbol"] = trades["symbol"].str.strip().str.upper()
    trades["ts"] = [pd.Timestamp(f"{d} {t}", tz=args.tz).tz_convert(data.NY)
                    for d, t in zip(trades["date"], trades["time"])]
    for c in ("timeframe", "stop", "result", "note"):
        if c not in trades:
            trades[c] = None

    found, reasons, noise = 0, Counter(), []
    for _, tr in trades.iterrows():
        d = tr["ts"].date()
        m1 = data.minute_bars(tr["symbol"], start=d, end=d + pd.Timedelta(days=1))
        print(f"\n=== {tr['symbol']} {d} {tr['ts']:%H:%M} NY | entry {tr['entry']} stop {tr['stop']}"
              f"{' | ' + str(tr['result']) if pd.notna(tr['result']) else ''}")
        if m1.empty:
            print("  no minute data (older than ~30 days or bad symbol)")
            reasons["no data"] += 1
            continue
        day = m1[m1.index.date == d]
        daily = data.daily_bars(tr["symbol"], 90)
        levels = scoring.daily_levels(daily, d) if not daily.empty else []
        change = change_from_daily(daily, day[day.index <= tr["ts"]])
        best = match(tr, day, daily, cfg, levels, change)
        if best is None:
            print("  no bars before the entry time – check date/time/timezone")
            reasons["time mismatch"] += 1
            continue
        err, s, why, tf, mt, it, mh, il = best
        print(f"  closest pair: {tf}m mother {mt:%H:%M} high {mh:.4f} / inside {it:%H:%M} low {il:.4f}"
              f"  (off by {err:.1%})")
        if err > PRICE_TOL * 2:
            print("  ⚠️ no bar pair near your entry/stop – maybe a different timeframe or entry model")
        if s is not None:
            found += 1
            print(f"  ✅ bot found it: {s.kind}, score {s.score}, outcome {s.status}")
            for n in s.notes:
                print(f"     • {n}")
        else:
            for r in why:
                print(f"  ❌ rejected: {r}")
                reasons[r.split(" (")[0].split(" –")[0]] += 1

        # bot setups that day you did not take
        for tf2 in cfg["data"]["timeframes"]:
            tf_df = data.resample(day, tf2)
            for i in range(1, len(tf_df)):
                if tf2 == tf and tf_df.index[i] == it:
                    continue
                s2 = evaluate(tr["symbol"], tf_df, i, day, cfg, tf2, daily_levels=levels)
                if s2 is not None:
                    track(s2, tf_df, cfg)
                    scoring.score(s2, cfg, change, levels)
                    noise.append(dict(symbol=tr["symbol"], date=d, tf=tf2, time=f"{s2.inside_time:%H:%M}",
                                      kind=s2.kind, score=s2.score, status=s2.status))

    n = len(trades)
    print(f"\n==== bot found {found}/{n} of your trades")
    for r, c in reasons.most_common():
        print(f"  {c}x  {r}")
    if noise:
        nz = pd.DataFrame(noise)
        print(f"\n==== {len(nz)} other setups flagged on those days (not taken by you)")
        print(nz.groupby("tf")["score"].describe()[["count", "mean", "min", "max"]].round(0))
        nz.to_csv("calibration_noise.csv", index=False)
        print("saved calibration_noise.csv – mark the ones you would have taken")


if __name__ == "__main__":
    main()
