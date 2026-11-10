"""Market data layer. Swap this file to change provider (Alpaca SIP, Massive, ...)."""
from __future__ import annotations

import time

import pandas as pd
import yfinance as yf

NY = "America/New_York"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                            index=pd.DatetimeIndex([], tz=NY))
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df = df.dropna(subset=["open", "high", "low", "close"])
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(NY)
    return df


def _history(symbol: str, retries: int = 3, **kw) -> pd.DataFrame:
    """Yahoo is unofficial and sometimes times out – retry with backoff."""
    for attempt in range(retries):
        try:
            return _clean(yf.Ticker(symbol).history(auto_adjust=False, **kw))
        except Exception as e:
            if attempt == retries - 1:
                print(f"{symbol}: data error ({type(e).__name__}) – skipped")
                STATS["errors"] += 1
                return _clean(None)
            time.sleep(2 * (attempt + 1))


SOURCE = "tradingview"  # set from config.yaml (data.source) by engine.load_config
TV_MAX_BARS = 5000      # ~5 weeks of extended-hours minutes
STATS = {"tradingview": 0, "yahoo": 0, "errors": 0}  # data requests by source, for the dashboard


def _tradingview(symbol: str, n_bars: int) -> pd.DataFrame:
    import tv_data
    for attempt in range(2):
        try:
            return tv_data.bars(symbol, interval="1", n_bars=n_bars)
        except Exception as e:
            if attempt == 1:
                print(f"{symbol}: TradingView error ({type(e).__name__}) – using Yahoo")
            time.sleep(1)
    return _clean(None)


def minute_bars(symbol: str, days: int = 2, start=None, end=None) -> pd.DataFrame:
    """1-minute bars incl. pre/post market (all sessions joined).

    TradingView first: same bars as your chart and it has premarket volume
    (Cboe share of volume, ~8% of the total – fine for comparing bars).
    Yahoo is the fallback (full volume, but none in premarket)."""
    if SOURCE == "tradingview":
        if start is None:
            df = _tradingview(symbol, min(TV_MAX_BARS, max(1, days) * 960 + 100))
            if not df.empty:
                STATS["tradingview"] += 1
                return df
        else:
            df = _tradingview(symbol, TV_MAX_BARS)
            lo = pd.Timestamp(start).tz_localize(NY)
            hi = pd.Timestamp(end).tz_localize(NY) if end is not None else None
            if not df.empty and df.index[0] <= lo:
                STATS["tradingview"] += 1
                return df[(df.index >= lo) & ((df.index < hi) if hi is not None else True)]
    STATS["yahoo"] += 1
    if start is not None:
        return _history(symbol, interval="1m", start=start, end=end, prepost=True)
    return _history(symbol, interval="1m", period=f"{max(1, min(days, 7))}d", prepost=True)


def daily_bars(symbol: str, days: int = 60) -> pd.DataFrame:
    return _history(symbol, interval="1d", period=f"{days}d")


def resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes == 1 or df.empty:
        return df
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df.resample(f"{minutes}min", label="left", closed="left").agg(agg).dropna(subset=["open"])


def today_session(df: pd.DataFrame) -> pd.DataFrame:
    """Bars of the most recent trading date (04:00-20:00 NY)."""
    if df.empty:
        return df
    last_date = df.index[-1].date()
    return df[df.index.date == last_date]
