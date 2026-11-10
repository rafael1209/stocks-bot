"""Telegram alerts. Without TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID it prints to the console."""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

from setups.inside_bar import Setup

KIND_HE = {"continuation": "המשכיות בטרנד עולה", "trendline_break": "פריצת קו מגמה", "level_break": "פריצת אזור ערך"}
EVENT_HE = {"new": "🟡 סטאפ נוצר", "triggered": "🟢 פריצה", "expired": "⚪ פג תוקף",
            "cancelled": "🔴 בוטל (שבר סטופ)", "target": "🎯 הגיע ליעד", "stopped": "❌ נעצר בסטופ"}


def px(p: float) -> str:
    """Penny stocks need 4 decimals (0.2946), others 2."""
    return f"{p:.4f}" if p < 1 else f"{p:.2f}"


def format_message(setup: Setup, event: str, change_pct: float | None = None, age: int | None = None) -> str:
    kinds = " + ".join(KIND_HE[k] for k in (setup.contexts or [setup.kind]))
    head = f"{EVENT_HE[event]} | {setup.symbol} {setup.timeframe}m | נר פנימי – {kinds}"
    if age:
        head += f" | נוצר לפני {age} נרות"
    lines = [head,
             f"כניסה {px(setup.entry)} | סטופ {px(setup.stop)} (-{setup.risk_pct:.1f}%) | "
             f"יעד {px(setup.target)} (+{setup.target_pct:.1f}%)",
             f"ציון {setup.score}/100" + (f" | עלייה יומית {change_pct:.0f}%" if change_pct else "")]
    lines += [f"• {n}" for n in setup.notes]
    return "\n".join(lines)


def send(text: str, image: Path | None = None) -> bool | None:
    """True = delivered, False = failed, None = Telegram not configured (printed)."""
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print(text + (f"\n[chart] {image}" if image else "") + "\n")
        return None
    base = f"https://api.telegram.org/bot{token}"
    for attempt in range(4):  # the connection to Telegram resets now and then
        try:
            if image:
                with open(image, "rb") as f:
                    r = requests.post(f"{base}/sendPhoto", data={"chat_id": chat, "caption": text[:1024]},
                                      files={"photo": f}, timeout=20)
            else:
                r = requests.post(f"{base}/sendMessage", data={"chat_id": chat, "text": text}, timeout=20)
            if not r.ok:
                print(f"telegram error: {r.text[:200]}")
            return r.ok
        except requests.RequestException as e:
            if attempt == 3:
                print(f"telegram error: {type(e).__name__}\n{text}")
                return False
            time.sleep(2 * (attempt + 1))
    return False
