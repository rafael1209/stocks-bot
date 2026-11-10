"""Minute bars straight from TradingView's chart feed (unofficial, no login).

Unlike Yahoo it includes premarket/after-hours VOLUME, and matches what you see
on your TradingView chart. Used by data.py with Yahoo as fallback.
"""
from __future__ import annotations

import json
import random
import re
import string
import time

import pandas as pd
import websocket

WS_URL = "wss://data.tradingview.com/socket.io/websocket"
HEADERS = {"Origin": "https://www.tradingview.com"}
_FRAME = re.compile(r"~m~(\d+)~m~")


def _wrap(func: str, params: list) -> str:
    msg = json.dumps({"m": func, "p": params}, separators=(",", ":"))
    return f"~m~{len(msg)}~m~{msg}"


def _session(prefix: str) -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase, k=12))


def _frames(raw: str):
    pos = 0
    while True:
        m = _FRAME.match(raw, pos)
        if not m:
            return
        n, start = int(m.group(1)), m.end()
        yield raw[start:start + n]
        pos = start + n


def bars(symbol: str, exchange: str | None = None, interval: str = "1", n_bars: int = 3000,
         extended: bool = True, timeout: int = 20) -> pd.DataFrame:
    """OHLCV bars, NY time index. `symbol` may already be 'NASDAQ:XYZ'."""
    full = f"{exchange}:{symbol}" if exchange and ":" not in symbol else symbol  # bare tickers resolve too
    ws = websocket.create_connection(WS_URL, header=HEADERS, timeout=timeout)
    cs = _session("cs_")
    sym = "=" + json.dumps({"symbol": full, "adjustment": "splits",
                            "session": "extended" if extended else "regular"}, separators=(",", ":"))
    for func, params in [("set_auth_token", ["unauthorized_user_token"]),
                         ("chart_create_session", [cs, ""]),
                         ("resolve_symbol", [cs, "sym_1", sym]),
                         ("create_series", [cs, "s1", "s1", "sym_1", interval, n_bars])]:
        ws.send(_wrap(func, params))

    rows = []
    deadline = time.monotonic() + timeout  # heartbeats keep recv() alive, so cap the whole request
    try:
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"TradingView: no series_completed for {full} within {timeout}s")
            raw = ws.recv()
            for frame in _frames(raw):
                if frame.startswith("~h~"):  # heartbeat – echo it back
                    ws.send(f"~m~{len(frame)}~m~{frame}")
                    continue
                try:
                    msg = json.loads(frame)
                except ValueError:
                    continue
                kind = msg.get("m")
                if kind in ("symbol_error", "series_error", "critical_error", "protocol_error"):
                    raise RuntimeError(f"TradingView {kind}: {msg.get('p')}")
                if kind == "timescale_update":
                    for v in msg["p"][1].get("s1", {}).get("s", []):
                        rows.append(v["v"][:6])
                if kind == "series_completed":
                    raise StopIteration
    except StopIteration:
        pass
    finally:
        ws.close()

    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"][: len(rows[0])] if rows else
                      ["time", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df
    if "volume" not in df:
        df["volume"] = 0.0
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("time"), unit="s", utc=True)).tz_convert("America/New_York")
    df.index.name = "Datetime"
    return df.astype(float)
