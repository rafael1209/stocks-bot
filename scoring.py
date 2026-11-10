"""Quality score 0-100. Never blocks a setup, only ranks it and explains why."""
from __future__ import annotations

import pandas as pd

from setups.inside_bar import Setup

WEIGHTS = {"position": 15, "context": 20, "sma": 10, "near_high": 20, "levels": 10, "gain": 10, "volume": 15,
           "history": 10}


def daily_levels(daily: pd.DataFrame, today) -> list[float]:
    """Real levels of the daily chart: swing highs/lows (2 days each side) + yesterday's high/low."""
    from indicators import swing_highs, swing_lows
    prior = daily[daily.index.date < today]
    if prior.empty:
        return []
    lv = {float(prior.loc[t, "high"]) for t in swing_highs(prior, 2)}
    lv |= {float(prior.loc[t, "low"]) for t in swing_lows(prior, 2)}
    lv |= {float(prior["high"].iloc[-1]), float(prior["low"].iloc[-1])}
    return sorted(round(x, 4) for x in lv)


def score(setup: Setup, cfg: dict, change_pct: float | None, levels: list[float]) -> Setup:
    tr, vol = cfg["trend"], cfg["volume"]
    parts, notes = {}, []

    parts["position"] = min(1.0, max(0.0, (setup.inside_position - 0.3) / 0.5))
    if setup.inside_position >= 0.6:
        notes.append("נר פנימי בחלק העליון של נר האם")

    ctx = []
    if "trendline_break" in setup.contexts:
        ctx.append(min(1.0, 0.5 + 0.2 * (setup.trendline.touches - 1)))
        notes.append(f"פריצת קו מגמה יורד ({setup.trendline.touches} נגיעות)")
    if "level_break" in setup.contexts:
        ctx.append(0.9)
        notes.append(f"פריצת אזור ערך {setup.level:.4g} ({setup.level_label})")
    if "continuation" in setup.contexts:
        p, soft, hard = setup.run.pullback_of_run, tr["max_pullback_of_run"], tr["hard_max_pullback_of_run"]
        ctx.append(1.0 if p <= soft else max(0.0, 1 - (p - soft) / (hard - soft)))
        notes.append(f"טרנד עולה שלם (נמוכים עולים), תיקון {p:.0%} מהריצה")
    # more than one reason to enter = stronger
    parts["context"] = min(1.0, max(ctx) + 0.1 * (len(ctx) - 1)) if ctx else 0.0

    if setup.extension:
        notes.append("מתיחה מ-SMA10: " + " | ".join(f"{tf}m {p:.0f}%" for tf, p in sorted(setup.extension.items())))

    parts["sma"] = 1.0 if setup.sma_touch else 0.0
    if setup.sma_touch:
        notes.append(f"נגיעה ב-SMA10 ב-{cfg['trend']['sma_touch_lookback_bars']} הנרות האחרונים")

    # strength: entries close to the high of day won (5/6 within 5%), far below it lost (3/40 at 10%+)
    gap = (setup.hod / setup.entry - 1) * 100
    parts["near_high"] = 1.0 if gap <= 5 else max(0.0, 1 - (gap - 5) / 15)
    notes.append(f"כניסה {gap:.0f}% מתחת לשיא היומי" + (" – קרוב לשיא 💪" if gap <= 5 else ""))
    if not setup.realistic_target:  # information only – no longer part of the score
        notes.append(f"יעד מעל ה-HOD ({setup.hod:.4g}) – דורש גבוה חדש")

    blocking = [lv for lv in levels if setup.entry < lv < setup.target]
    parts["levels"] = 0.0 if blocking else 1.0
    if blocking:
        notes.append(f"⚠️ רמה יומית בדרך: {blocking[0]:.4g}")

    # a stock that already ran 80-200% in the last weeks tends to run again
    h = setup.history
    if h:
        parts["history"] = min(1.0, h["max_pct"] / 100) if h["max_pct"] >= 30 else 0.0
        if h["max_pct"] >= 30:
            notes.append(f"ריצה של +{h['max_pct']:.0f}% לפני {h['days_ago']} ימי מסחר"
                         + (f" ({h['big_runs']} ריצות של 80%+ בחודש)" if h["big_runs"] > 1 else ""))
    if change_pct is not None:
        parts["gain"] = min(1.0, change_pct / cfg["scanner"]["preferred_change_pct"])

    if setup.status != "pending" and setup.breakout_vol_vs_avg is None:
        notes.append("ווליום לא זמין (פרה-מרקט) – בדוק בגרף")
    if setup.breakout_vol_vs_avg is not None:
        strong = setup.breakout_vol_vs_avg >= 1 or (setup.breakout_vol_vs_pullback or 0) >= vol["spike_vs_pullback"]
        parts["volume"] = 1.0 if strong else 0.3
        notes.append(f"ווליום פריצה x{setup.breakout_vol_vs_avg:.1f} מממוצע 10"
                     + (f", x{setup.breakout_vol_vs_pullback:.1f} מהתיקון" if setup.breakout_vol_vs_pullback else ""))

    total = sum(WEIGHTS[k] for k in parts)
    setup.score = round(100 * sum(WEIGHTS[k] * v for k, v in parts.items()) / total) if total else 0
    setup.notes = notes
    return setup
