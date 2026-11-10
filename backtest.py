"""Replay the strategy on recent minute data (Yahoo keeps ~30 days of 1m bars).

  py backtest.py --symbols INO,CLRO --days 10
  py backtest.py --days 10            (uses today's scanner list)
  py backtest.py --symbols INO --days 5 --charts   (save a chart per setup)
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

import pandas as pd

import chart
import data
import monitor
import scanner
from engine import change_from_daily, load_config, setups_for_day


def _level_type(label: str) -> str:
    if not label:
        return ""
    for he, en in (("היי פרה-מרקט", "premarket_high"), ("רמה יומית", "daily"), ("מספר עגול", "round"),
                   ("נגיעות", "intraday_zone")):
        if label.startswith(he) or (he == "נגיעות" and he in label):
            return en + ("+round" if "+ מספר עגול" in label else "")
    return label


def run(symbols: list[str], days: int, cfg: dict, charts: bool = False) -> pd.DataFrame:
    rows = []
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=min(days, 29) + 1)
    for sym in symbols:
        daily = data.daily_bars(sym, 90)
        m1 = pd.concat([data.minute_bars(sym, start=d, end=min(d + timedelta(days=7), end))
                        for d in pd.date_range(start, end, freq="7D").date])
        if m1.empty:
            continue
        m1 = m1[~m1.index.duplicated()]
        for d, day in m1.groupby(m1.index.date):
            change = change_from_daily(daily, day)
            prior = daily[daily.index.date < d]
            if prior.empty:
                continue
            day_high_pct = (day["high"].max() / prior["close"].iloc[-1] - 1) * 100
            if day_high_pct < cfg["scanner"]["min_change_pct"]:
                continue
            for s, tf_df in setups_for_day(sym, day, daily, cfg, change):
                if charts:
                    chart.render(s, tf_df, out_dir="charts/backtest")
                rows.append(dict(symbol=sym, date=d, tf=s.timeframe, kind=s.kind,
                                 inside=s.inside_time.strftime("%H:%M"), entry=round(s.entry, 4),
                                 stop=round(s.stop, 4), target=round(s.target, 4),
                                 target_pct=round(s.target_pct, 1), realistic=s.realistic_target,
                                 score=s.score, status=s.status,
                                 vol_x=round(s.breakout_vol_vs_avg or 0, 1),
                                 # details for analysing what separates winners from losers
                                 contexts="+".join(s.contexts), level=s.level, level_type=_level_type(s.level_label),
                                 session=monitor.session_phase(s.inside_time, cfg),
                                 risk_pct=round(s.risk_pct, 1), hod_gap_pct=round((s.hod / s.entry - 1) * 100, 1),
                                 pullback=round(s.run.pullback_of_run, 2), run_pct=round(s.run.run_pct, 0),
                                 sma_touch=s.sma_touch, inside_pos=round(s.inside_position, 2),
                                 mother_of_run=round(s.mother_of_run, 2),
                                 ext_1m=round(s.extension.get(1, float("nan")), 1),
                                 ext_15m=round(s.extension.get(15, float("nan")), 1),
                                 tl_touches=s.trendline.touches if s.trendline else 0))
    return pd.DataFrame(rows)


def summary(df: pd.DataFrame) -> pd.DataFrame:
    def agg(g):
        win, loss = (g.status == "target").sum(), (g.status == "stopped").sum()
        rr = 2 * win - loss
        return pd.Series(dict(setups=len(g), triggered=g.status.isin(["triggered", "target", "stopped"]).sum(),
                              target=win, stopped=loss,
                              win_rate=round(win / (win + loss), 2) if win + loss else None, total_R=rr))
    return df.groupby(["tf", "kind"]).apply(agg, include_groups=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="")
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--charts", action="store_true")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = load_config(args.config)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] \
        or list(scanner.scan(cfg)["symbol"]) + scanner.watchlist()
    df = run(symbols, args.days, cfg, args.charts)
    if df.empty:
        print("no setups found")
        return
    pd.set_option("display.width", 200)
    print(df.to_string(index=False))
    print("\n", summary(df))
    df.to_csv("backtest_results.csv", index=False)
    print("\nsaved backtest_results.csv")


if __name__ == "__main__":
    main()
