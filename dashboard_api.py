"""Monitoring dashboard server: serves the React app and the bot's state as JSON.

  py dashboard_api.py            -> http://localhost:8787
Reads only files the bot writes (state/, charts/, config.yaml, backtest/trades CSVs),
so it can run next to main.py without touching it.
"""
from __future__ import annotations

import json
import math
import mimetypes
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import yaml

from auth import COOKIE, SESSION_DAYS, Guard

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
DIST = ROOT / "dashboard" / "dist"
PORT = 8787


def _status() -> dict:
    p = STATE / "status.json"
    if not p.exists():
        return {"alive": False, "message": "The bot has not written any state yet – start it with: py main.py"}
    s = json.loads(p.read_text(encoding="utf-8"))
    age = (pd.Timestamp.now(tz="America/New_York") - pd.Timestamp(s["updated"])).total_seconds()
    # a scan takes up to ~2 min on a slow network; 3 intervals + 2 min without an update = stopped
    s["alive"] = age < 3 * s.get("interval_seconds", 45) + 120
    s["seconds_since_update"] = round(age)
    return s


def _events(limit: int) -> list:
    p = STATE / "events.jsonl"
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def _csv(name: str, comment: str | None = None) -> list:
    p = ROOT / name
    if not p.exists():
        return []
    try:
        df = pd.read_csv(p, comment=comment)
    except (ValueError, pd.errors.EmptyDataError):
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _backtest() -> dict:
    rows = _csv("backtest_results.csv")
    summary = []
    if rows:
        df = pd.DataFrame(rows)
        for (tf, kind), g in df.groupby(["tf", "kind"]):
            win, loss = int((g.status == "target").sum()), int((g.status == "stopped").sum())
            summary.append({"tf": int(tf), "kind": kind, "setups": len(g),
                            "triggered": int(g.status.isin(["triggered", "target", "stopped"]).sum()),
                            "target": win, "stopped": loss,
                            "win_rate": round(win / (win + loss), 2) if win + loss else None,
                            "total_r": 2 * win - loss})
    return {"rows": rows, "summary": summary}


def _clean(o):
    """Replace NaN / ±Infinity anywhere in the structure with None."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


_BARS_CACHE: dict = {}
_BARS_LOCK = threading.Lock()


def _wall(ts: pd.DatetimeIndex) -> list[int]:
    """New York wall-clock time as epoch seconds – the charts then show NY time."""
    naive = ts.tz_convert("America/New_York").tz_localize(None)
    return [int(x) for x in (naive - pd.Timestamp(0)) // pd.Timedelta(seconds=1)]


def _bars(symbol: str, tf: int) -> dict:
    """Today's candles (all sessions joined) + SMA10 for the live charts. Cached 8 s per symbol."""
    import data  # the bot's data layer (TradingView feed, Yahoo fallback)
    from indicators import sma
    symbol = symbol.upper()
    with _BARS_LOCK:
        hit = _BARS_CACHE.get(symbol)
        if hit and time.time() - hit[0] < 8:
            day = hit[1]
        else:
            day = data.today_session(data.minute_bars(symbol, 1))
            _BARS_CACHE[symbol] = (time.time(), day)
    if day.empty:
        return {"symbol": symbol, "tf": tf, "bars": [], "sma": []}
    b = data.resample(day, tf)
    t = _wall(b.index)
    ma = sma(b["close"], 10)
    return {
        "symbol": symbol, "tf": tf,
        "bars": [{"time": ti, "open": o, "high": h, "low": l, "close": c, "volume": v}
                 for ti, o, h, l, c, v in zip(t, b["open"], b["high"], b["low"], b["close"], b["volume"])],
        "sma": [{"time": ti, "value": round(float(x), 6)} for ti, x in zip(t, ma) if x == x],
        "updated": pd.Timestamp.now(tz="America/New_York").isoformat(),
    }


GUARD = Guard()
# endpoints reachable without a session: the login itself and the (data-free) app shell
PUBLIC_API = {"/api/session", "/api/login", "/api/logout", "/api/health"}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep the console quiet
        pass

    # ---- auth helpers ----------------------------------------------------
    def _client_ip(self) -> str:
        # Cloudflare -> nginx -> here: the visitor is in CF-Connecting-IP / X-Real-IP
        return (self.headers.get("CF-Connecting-IP") or self.headers.get("X-Real-IP")
                or self.client_address[0])

    def _session(self) -> str | None:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None

    def _authed(self) -> bool:
        return GUARD.valid_session(self._session())

    def _cookie(self, value: str, max_age: int) -> str:
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return f"{COOKIE}={value}; Max-Age={max_age}; Path=/; HttpOnly; SameSite=Strict{secure}"

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/logout":
            return self._json({"ok": True}, headers={"Set-Cookie": self._cookie("", 0)})
        if path != "/api/login":
            return self._json({"error": "not found"}, 404)
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 1024)
            pin = str(json.loads(self.rfile.read(n) or b"{}").get("pin", ""))
        except (ValueError, AttributeError):
            pin = ""
        ok, msg = GUARD.login(self._client_ip(), pin)
        if not ok:
            return self._json({"ok": False, "error": msg}, 401)
        return self._json({"ok": True}, headers={"Set-Cookie": self._cookie(GUARD.new_session(), SESSION_DAYS * 86400)})

    def _json(self, obj, code: int = 200, headers: dict | None = None) -> None:
        # NaN/Infinity are not valid JSON (e.g. a stock without float data) – send null instead
        body = json.dumps(_clean(obj), default=str, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        q, path = parse_qs(url.query), url.path
        if path == "/api/health":  # liveness only – no trading data
            st = _status()
            return self._json({k: st.get(k) for k in ("alive", "scans", "seconds_since_update")})
        if path == "/api/session":
            return self._json({"authenticated": self._authed(), "configured": GUARD.configured})
        # everything with data – API and chart snapshots – needs a valid session
        if (path.startswith("/api/") or path.startswith("/charts/")) and path not in PUBLIC_API and not self._authed():
            return self._json({"error": "login required"}, 401)
        try:
            if path == "/api/status":
                return self._json(_status())
            if path == "/api/events":
                return self._json(_events(int(q.get("limit", ["300"])[0])))
            if path == "/api/config":
                return self._json(yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")))
            if path == "/api/bars":
                return self._json(_bars(q["symbol"][0], int(q.get("tf", ["5"])[0])))
            if path == "/api/backtest":
                return self._json(_backtest())
            if path == "/api/pnl":
                import pnl
                return self._json(pnl.daily(STATE / "events.jsonl"))
            if path == "/api/trades":
                return self._json(_csv("my_trades.csv", comment="#"))
            if path.startswith("/charts/"):
                target = (ROOT / path.lstrip("/")).resolve()
                if ROOT / "charts" not in target.parents:  # no path traversal
                    return self.send_error(403)
                return self._file(target)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

        # the React app (single page: unknown paths fall back to index.html)
        if not DIST.exists():
            return self._json({"error": "dashboard not built – run: cd dashboard && npm run build"}, 503)
        target = (DIST / path.lstrip("/")).resolve()
        if DIST in target.parents and target.is_file():
            return self._file(target)
        return self._file(DIST / "index.html")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"dashboard on http://localhost:{port}")
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")  # 0.0.0.0 inside Docker, behind nginx
    ThreadingHTTPServer((host, port), Handler).serve_forever()
