"""Live loop: scan gainers, look for inside-bar setups, alert on Telegram.

Run:  py main.py           (loop)
      py main.py --once    (single pass)
Every pass also writes state/ for the dashboard (py dashboard_api.py).
"""
from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

import chart
import data
import monitor
import notifier
import scanner
from engine import change_from_daily, load_config, setups_for_day
from indicators import past_runs

ALERT_ON = {"triggered", "expired", "cancelled", "target", "stopped"}


class Bot:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.state: dict = {}        # setup key -> last status
        self.tracked: dict = {}      # setup key -> dashboard snapshot (alerted setups of the day)
        self.daily_cache: dict = {}
        self.last_new: dict = {}     # symbol -> time of the last "new setup" alert
        self.cooldown = pd.Timedelta(minutes=cfg.get("alerts", {}).get("symbol_cooldown_minutes", 10))
        self.errors: list = []
        self.started = pd.Timestamp.now(tz=data.NY)
        self.scans = 0
        self.telegram = {"configured": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
                         "sent": 0, "failed": 0, "last_ok": None, "last_error": None}
        self.restore_today()

    def restore_today(self) -> None:
        """After a restart, remember today's alerts so they are not sent again."""
        path = monitor.STATE_DIR / "events.jsonl"
        if not path.exists():
            return
        today = self.started.date().isoformat()
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not e.get("time", "").startswith(today) or "key" not in e:
                continue
            self.state[e["key"]] = e["status"]
            self.tracked[e["key"]] = {k: v for k, v in e.items() if k not in ("time", "event", "telegram")}
            if e["event"] == "new":
                self.last_new[e["symbol"]] = pd.Timestamp(e["time"])

    def error(self, where: str, e) -> None:
        print(f"{where}: {e}")
        self.errors = (self.errors + [{"time": pd.Timestamp.now(tz=data.NY).isoformat(),
                                       "where": where, "error": str(e)[:300]}])[-30:]

    def alert(self, s, event: str, change, tf_df, age=None, with_chart=False) -> None:
        img = None
        if with_chart:
            try:
                img = chart.render(s, tf_df)
            except Exception as e:  # a broken chart must not kill the alert (or the bot)
                self.error(f"chart {s.symbol}", e)
        ok = notifier.send(notifier.format_message(s, event, change, age), img)
        now = pd.Timestamp.now(tz=data.NY)
        if ok:
            self.telegram.update(sent=self.telegram["sent"] + 1, last_ok=now.isoformat())
        elif ok is False:
            self.telegram.update(failed=self.telegram["failed"] + 1, last_error=now.isoformat())
        snap = monitor.setup_dict(s, change, age, img.name if img else self.tracked.get(s.key, {}).get("chart"))
        self.tracked[s.key] = snap
        monitor.log_event({"time": now.isoformat(), "event": event, "telegram": ok, **snap})

    def runner_alerts(self, rows: dict, now: pd.Timestamp) -> None:
        """Heads-up the first time a stock runs past N% today – no setup yet, but get ready
        for the first pullback on the 1-minute chart. Remembered on disk across restarts."""
        pct = self.cfg.get("alerts", {}).get("runner_alert_pct")
        if not pct:
            return
        path = monitor.STATE_DIR / f"runners_{now.date().isoformat()}.json"
        seen = set(json.loads(path.read_text())) if path.exists() else set()
        for sym, r in rows.items():
            if sym in seen or (r.get("change_pct") or 0) < pct:
                continue
            seen.add(sym)
            rot = r.get("float_rotation")
            text = (f"🚀 מניה רצה | {sym} +{r['change_pct']:.0f}% | מחיר {notifier.px(r['close'])}\n"
                    f"ווליום {r['day_volume'] / 1e6:.1f}M" + (f" | סיבוב פלואט x{rot:.0f}" if rot == rot and rot else "")
                    + f" | שווי שוק לפני העלייה ${r['market_cap'] / 1e6:.1f}M\n"
                    "אין עדיין סטאפ – היכון לתיקון הראשון בגרף דקה. בדוק חדשות.")
            ok = notifier.send(text)
            monitor.log_event({"time": now.isoformat(), "event": "runner", "telegram": ok, "symbol": sym,
                               "change_pct": r["change_pct"], "price": r["close"], "day_volume": r["day_volume"],
                               "float_rotation": rot if rot == rot else None, "market_cap": r["market_cap"]})
        monitor.STATE_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps(sorted(seen)))

    def run_once(self) -> None:
        cfg, now, t0 = self.cfg, pd.Timestamp.now(tz=data.NY), time.time()
        if self.tracked and next(iter(self.tracked.values()))["inside_time"][:10] != now.date().isoformat():
            self.tracked.clear()  # new trading day
        try:
            gainers = scanner.scan(cfg)
        except Exception as e:  # screener is unofficial – keep the watchlist working
            self.error("scanner", e)
            gainers = pd.DataFrame(columns=["symbol", "change_pct", "close", "day_volume", "market_cap", "exchange"])
        changes = dict(zip(gainers["symbol"], gainers["change_pct"]))
        watch = scanner.watchlist()
        symbols = list(dict.fromkeys(list(gainers["symbol"]) + watch))
        print(f"[{now:%H:%M:%S}] scanning {len(symbols)}: {', '.join(symbols)}")

        rows = {r["symbol"]: r for r in gainers.to_dict("records")}
        self.runner_alerts(rows, now)
        universe = []
        for sym in symbols:
            row = {"symbol": sym, "source": "scanner" if sym in rows else "watchlist", **rows.get(sym, {})}
            try:
                day = data.today_session(data.minute_bars(sym, cfg["data"]["lookback_days"]))
                if day.empty:
                    universe.append({**row, "status": "no data"})
                    continue
                key = (sym, now.date())
                if key not in self.daily_cache:
                    self.daily_cache[key] = data.daily_bars(sym, cfg["data"]["daily_lookback_days"])
                daily = self.daily_cache[key]
                change = changes.get(sym) or change_from_daily(daily, day)
                found = setups_for_day(sym, day, daily, cfg, change, now=now,
                                       since=cfg["inside_bar"]["valid_bars"] + 1)
                row["history"] = past_runs(daily, now.date(), cfg.get("history", {}).get("lookback_days", 22))
                row.update(change_pct=change, last=float(day["close"].iloc[-1]), hod=float(day["high"].max()),
                           lod=float(day["low"].min()), status="ok",
                           spark=[round(float(x), 4) for x in data.resample(day, 5)["close"].tail(60)])
            except Exception as e:
                self.error(sym, e)
                universe.append({**row, "status": "error"})
                continue

            active = 0
            for s, tf_df in found:
                prev = self.state.get(s.key)
                if prev is None:
                    # only setups still waiting for the breakout; one that already
                    # triggered or finished before we saw it is not tradable
                    if s.status == "pending":
                        last = self.last_new.get(sym)
                        if last is not None and now - last < self.cooldown:
                            continue  # same stock alerted recently – look again next scan
                        age = int((tf_df.index > s.inside_time).sum())
                        self.alert(s, "new", change, tf_df, age, with_chart=True)
                        self.last_new[sym] = now
                    self.state[s.key] = s.status
                    continue
                if prev != s.status and s.status in ALERT_ON:
                    self.alert(s, s.status, change, tf_df, with_chart=s.status == "triggered")
                elif s.key in self.tracked:  # keep the dashboard snapshot fresh
                    self.tracked[s.key] = monitor.setup_dict(s, change, int((tf_df.index > s.inside_time).sum()),
                                                             self.tracked[s.key].get("chart"))
                self.state[s.key] = s.status
                active += s.status in ("pending", "triggered")
            # alerted setups the current rules no longer produce (e.g. rules changed) – stop showing them as live
            seen_keys = {s.key for s, _ in found}
            for k, snap in self.tracked.items():
                if snap["symbol"] == sym and snap["status"] == "pending" and k not in seen_keys:
                    snap["status"] = "invalidated"
            row["active_setups"] = active
            universe.append(row)

        self.scans += 1
        interval = cfg["loop"]["interval_seconds"]
        monitor.write_status({
            "updated": pd.Timestamp.now(tz=data.NY).isoformat(),
            "started": self.started.isoformat(), "pid": os.getpid(), "scans": self.scans,
            "scan_seconds": round(time.time() - t0, 1), "interval_seconds": interval,
            "next_scan": (pd.Timestamp.now(tz=data.NY) + pd.Timedelta(seconds=interval)).isoformat(),
            "session": monitor.session_phase(now, cfg),
            "data_source": data.SOURCE, "data_stats": data.STATS,
            "telegram": self.telegram, "watchlist": watch,
            "universe": universe,
            "setups": sorted(self.tracked.values(), key=lambda x: x["inside_time"], reverse=True),
            "errors": self.errors,
        })


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    bot = Bot(load_config(args.config))
    while True:
        try:
            bot.run_once()
        except Exception:  # one bad scan must not take the bot down – log it and try again next loop
            traceback.print_exc()
            bot.error("run_once", traceback.format_exc().strip().splitlines()[-1])
        if args.once:
            break
        time.sleep(bot.cfg["loop"]["interval_seconds"])


if __name__ == "__main__":
    print(f"started {datetime.now():%Y-%m-%d %H:%M}")
    main()
