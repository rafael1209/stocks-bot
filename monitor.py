"""Bot state for the monitoring dashboard.

state/status.json   – rewritten every scan (what the bot sees right now)
state/events.jsonl  – one line per alert sent (history)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from setups.inside_bar import Setup, in_no_entry_window, is_premarket

STATE_DIR = Path(__file__).resolve().parent / "state"
CONTEXT_EN = {"continuation": "Uptrend continuation", "trendline_break": "Downtrend line break",
              "level_break": "Value-zone breakout"}


def _iso(t) -> str | None:
    return None if t is None or pd.isna(t) else pd.Timestamp(t).isoformat()


def _wall(t) -> int:
    """NY wall-clock time as epoch seconds (how the dashboard charts place candles)."""
    naive = pd.Timestamp(t).tz_convert("America/New_York").tz_localize(None)
    return int((naive - pd.Timestamp(0)) // pd.Timedelta(seconds=1))


def session_phase(now: pd.Timestamp, cfg: dict) -> str:
    hhmm = now.strftime("%H:%M")
    if now.weekday() >= 5 or hhmm < "04:00" or hhmm >= "20:00":
        return "closed"
    if is_premarket(now):
        return "premarket"
    if in_no_entry_window(now, cfg):
        return "no-entry window"
    return "regular" if hhmm < "16:00" else "after-hours"


def reasons_en(s: Setup) -> list[dict]:
    """Why the setup qualifies / what to watch – {text, tone: good|warn|info}."""
    out = []
    if "trendline_break" in s.contexts and s.trendline:
        out.append({"text": f"Breaks a descending trendline ({s.trendline.touches} touches)", "tone": "good"})
    if "level_break" in s.contexts and s.level is not None:
        label = {"היי פרה-מרקט": "premarket high", "רמה יומית": "daily level", "מספר עגול": "round number"}
        lbl = s.level_label
        for he, en in label.items():
            lbl = lbl.replace(he, en)
        lbl = lbl.replace("נגיעות", "touches")
        out.append({"text": f"Breaks value zone {s.level:.4g} ({lbl})", "tone": "good"})
    if "continuation" in s.contexts:
        out.append({"text": f"Uptrend intact (higher lows), pullback {s.run.pullback_of_run:.0%} of the run", "tone": "good"})
    if s.sma_touch:
        out.append({"text": "Touched SMA10 in the last bars", "tone": "good"})
    if s.inside_position >= 0.6:
        out.append({"text": "Inside bar sits in the upper part of the mother bar", "tone": "good"})
    h = s.history
    if h and h.get("max_pct", 0) >= 30:
        out.append({"text": f"Ran +{h['max_pct']:.0f}% {h['days_ago']} trading days ago"
                            + (f" ({h['big_runs']} runs of 80%+ this month)" if h["big_runs"] > 1 else ""),
                    "tone": "good" if h["max_pct"] >= 80 else "info"})
    if s.extension:
        ext = ", ".join(f"{tf}m {p:.0f}%" for tf, p in sorted(s.extension.items()))
        out.append({"text": f"Distance from SMA10: {ext}", "tone": "info"})
    gap = (s.hod / s.entry - 1) * 100
    out.append({"text": f"Entry {gap:.0f}% below the high of day" + (" – strong, near the high" if gap <= 5 else ""),
                "tone": "good" if gap <= 5 else "info" if gap <= 10 else "warn"})
    if not s.realistic_target:
        out.append({"text": f"Target above high of day {s.hod:.4g} – needs a new high", "tone": "info"})
    if s.breakout_vol_vs_avg is not None:
        strong = s.breakout_vol_vs_avg >= 1
        out.append({"text": f"Breakout volume x{s.breakout_vol_vs_avg:.1f} vs 10-bar avg"
                            + (f", x{s.breakout_vol_vs_pullback:.1f} vs pullback" if s.breakout_vol_vs_pullback else ""),
                    "tone": "good" if strong else "warn"})
    elif s.status != "pending":
        out.append({"text": "Volume unavailable – check the chart", "tone": "warn"})
    return out


def setup_dict(s: Setup, change: float | None, age: int | None = None, chart: str | None = None) -> dict:
    return {
        "key": s.key, "symbol": s.symbol, "timeframe": s.timeframe, "kind": s.kind,
        "contexts": s.contexts, "contexts_en": [CONTEXT_EN[c] for c in s.contexts],
        "status": s.status, "score": s.score,
        "entry": s.entry, "stop": s.stop, "target": s.target,
        "risk_pct": round(s.risk_pct, 2), "target_pct": round(s.target_pct, 2),
        "mother_time": _iso(s.mother_time), "inside_time": _iso(s.inside_time),
        "trigger_time": _iso(s.trigger_time), "exit_time": _iso(s.exit_time),
        "hod": s.hod, "level": s.level, "realistic_target": s.realistic_target,
        "extension": {str(k): round(v, 2) for k, v in s.extension.items()},
        "breakout_vol_vs_avg": s.breakout_vol_vs_avg, "change_pct": change,
        "bars_ago": age, "chart": chart, "reasons": reasons_en(s), "history": s.history,
        "trendline": {"t1": _wall(s.trendline.t1), "p1": s.trendline.p1,
                      "t2": _wall(s.trendline.t2), "p2": s.trendline.p2} if s.trendline else None,
        "mother_wall": _wall(s.mother_time), "inside_wall": _wall(s.inside_time),
    }


def _write_json(path: Path, obj) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, default=str, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # atomic: the dashboard never reads half a file


def write_status(status: dict) -> None:
    _write_json(STATE_DIR / "status.json", status)


def log_event(event: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    with open(STATE_DIR / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")
