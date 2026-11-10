"""Top gainers scanner (TradingView screener data, free) + manual watchlist."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from tradingview_screener import Query, col

NY = ZoneInfo("America/New_York")
FIELDS = ["name", "close", "change", "premarket_change", "volume", "premarket_volume",
          "market_cap_basic", "total_shares_outstanding_fundamental", "float_shares_outstanding", "exchange"]


def _premarket(now: datetime) -> bool:
    return now.hour < 9 or (now.hour == 9 and now.minute < 30)


def scan(cfg: dict, now: datetime | None = None) -> pd.DataFrame:
    sc = cfg["scanner"]
    now = now or datetime.now(NY)
    pre = _premarket(now)
    change_col, vol_col = ("premarket_change", "premarket_volume") if pre else ("change", "volume")

    _, df = (Query().select(*FIELDS)
             .where(col("exchange").isin(sc["exchanges"]), col(change_col) >= sc["min_change_pct"])
             .order_by(change_col, ascending=False).limit(200).get_scanner_data())
    if df.empty:
        return df
    df = df.rename(columns={change_col: "change_pct", vol_col: "day_volume"})
    df = df[df["day_volume"].fillna(0) >= sc["min_volume"]]
    # market cap BEFORE today's move: shares x previous close. TradingView's own
    # market_cap_basic is usually at the live price, so it is only a fallback.
    # In premarket "close" is still yesterday's close.
    prev_close = df["close"] if pre else df["close"] / (1 + df["change_pct"] / 100)
    df["market_cap"] = (df["total_shares_outstanding_fundamental"] * prev_close).fillna(
        df["market_cap_basic"] / (1 + df["change_pct"] / 100))
    # float rotation: how many times the tradable shares changed hands today
    df["float_rotation"] = df["day_volume"] / df["float_shares_outstanding"]
    if sc.get("min_float_rotation"):
        df = df[df["float_rotation"].isna() | (df["float_rotation"] >= sc["min_float_rotation"])]
    if sc.get("max_market_cap"):
        df = df[df["market_cap"].notna() & (df["market_cap"] <= sc["max_market_cap"])]
    if sc.get("min_market_cap"):
        df = df[df["market_cap"] >= sc["min_market_cap"]]
    df = df[~df["name"].str.contains(r"[.\-/]", regex=True)]  # skip warrants/units
    return df[["name", "close", "change_pct", "day_volume", "market_cap", "float_rotation", "exchange"]] \
        .head(sc["max_symbols"]).rename(columns={"name": "symbol"}).reset_index(drop=True)


def watchlist(path: str | Path = "watchlist.txt") -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return [ln.strip().upper() for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
