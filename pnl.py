"""What every triggered setup would have made, traded exactly by the plan.

Entry at the setup's entry price, exit at the stop (-risk %) or the 2R target (+target %).
The bot only follows a setup while the stock stays in its scanner, so some breakouts never
get a stop/target event. Those are finished here on 1-minute bars: the first bar after the
breakout that touches the stop or the target closes the trade (both in one bar = stop, the
conservative read); if neither is hit, the trade is marked at the day's last price
(still running today = "open", at the latest price).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pandas as pd

NY = "America/New_York"
_CACHE: dict = {}  # key -> (fetched_at, result); finished past days are kept for good
_LOCK = threading.Lock()


def _trades(events_path: Path) -> list[dict]:
    """One row per setup that broke out – the latest snapshot the bot logged for it."""
    by_key: dict[str, dict] = {}
    if not events_path.exists():
        return []
    for ln in events_path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if not e.get("key") or e.get("status") not in ("triggered", "target", "stopped"):
            continue
        prev = by_key.get(e["key"])
        if prev is None or prev["status"] == "triggered":  # a stop/target is final
            by_key[e["key"]] = e
    return list(by_key.values())


def _finish(t: dict, today: str) -> dict:
    """Follow a breakout without a stop/target event on 1-minute bars."""
    import data
    trig = pd.Timestamp(t["trigger_time"]).tz_convert(NY)
    day = trig.date().isoformat()
    bars = data.minute_bars(t["symbol"], days=max(2, (pd.Timestamp(today).date() - trig.date()).days + 2))
    bars = bars[(bars.index >= trig) & (bars.index.date == trig.date())]
    entered = False
    for ts, b in bars.iterrows():
        if not entered:
            if b["high"] < t["entry"]:
                continue
            entered = True
            if b["high"] >= t["target"]:
                return {"result": "target", "exit": t["target"], "exit_time": ts.isoformat(), "simulated": True}
            continue  # the breakout bar itself: its low may be from before the entry
        if b["low"] <= t["stop"]:
            return {"result": "stopped", "exit": t["stop"], "exit_time": ts.isoformat(), "simulated": True}
        if b["high"] >= t["target"]:
            return {"result": "target", "exit": t["target"], "exit_time": ts.isoformat(), "simulated": True}
    if bars.empty:
        return {"result": "open" if day == today else "unknown", "exit": None, "exit_time": None, "simulated": True}
    return {"result": "open" if day == today else "day_close", "exit": float(bars["close"].iloc[-1]),
            "exit_time": bars.index[-1].isoformat(), "simulated": True}


def _outcome(t: dict, today: str) -> dict:
    if t["status"] == "target":
        return {"result": "target", "exit": t["target"], "exit_time": t.get("exit_time"), "simulated": False}
    if t["status"] == "stopped":
        return {"result": "stopped", "exit": t["stop"], "exit_time": t.get("exit_time"), "simulated": False}
    day = t["trigger_time"][:10]
    with _LOCK:
        hit = _CACHE.get(t["key"])
    # a finished past day never changes; today's open trades are refreshed every 30 s
    if hit and (hit[1]["result"] != "open" or time.time() - hit[0] < 30):
        return hit[1]
    try:
        out = _finish(t, today)
    except Exception as e:  # data feed down – show the trade, just without a result
        out = {"result": "unknown", "exit": None, "exit_time": None, "simulated": True, "error": str(e)}
    if out["result"] != "unknown" or day == today:
        with _LOCK:
            _CACHE[t["key"]] = (time.time(), out)
    return out


def daily(events_path: Path) -> dict:
    today = pd.Timestamp.now(tz=NY).date().isoformat()
    rows = []
    for t in _trades(events_path):
        if not t.get("trigger_time") or not t.get("entry"):
            continue
        o = _outcome(t, today)
        ret = (o["exit"] / t["entry"] - 1) * 100 if o["exit"] else None
        rows.append({
            "key": t["key"], "symbol": t["symbol"], "timeframe": t["timeframe"], "kind": t.get("kind"),
            "score": t.get("score"), "day": t["trigger_time"][:10], "trigger_time": t["trigger_time"],
            "entry": t["entry"], "stop": t["stop"], "target": t["target"],
            "risk_pct": t.get("risk_pct"), "target_pct": t.get("target_pct"),
            "result": o["result"], "exit": o["exit"], "exit_time": o["exit_time"], "simulated": o["simulated"],
            "return_pct": round(ret, 3) if ret is not None else None,
        })
    rows.sort(key=lambda r: r["trigger_time"])
    return {"today": today, "trades": rows}
