"""PIN login for the dashboard (standard library only).

The PIN itself is never stored: web.env holds a PBKDF2 hash of it (DASHBOARD_PIN_HASH)
and a random signing key for session cookies (DASHBOARD_SECRET). Set both with:
    python3 set_pin.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

ITERATIONS = 300_000
SESSION_DAYS = 30
MAX_FAILS_PER_IP = 5          # then that address waits LOCK_MINUTES
LOCK_MINUTES = 15
MAX_FAILS_PER_HOUR = 30       # all addresses together – stops a distributed guess
COOKIE = "stocks_session"


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        algo, iters, salt, want = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(got.hex(), want)
    except (ValueError, TypeError):
        return False


def _read_env_file(path: str) -> dict:
    """KEY=VALUE lines, read as-is. (docker compose env_file would expand the '$' signs
    inside the PBKDF2 hash as variables and corrupt it.)"""
    p = Path(path) if path else None
    if not p or not p.is_file():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        k, sep, v = line.partition("=")
        if sep and not k.startswith("#"):
            out[k.strip()] = v.strip()
    return out


class Guard:
    """Sessions + brute-force limits. Configured from the environment at startup."""

    def __init__(self):
        conf = _read_env_file(os.getenv("WEB_ENV_FILE", ""))
        self.pin_hash = (conf.get("DASHBOARD_PIN_HASH") or os.getenv("DASHBOARD_PIN_HASH", "")).strip()
        self.secret = (conf.get("DASHBOARD_SECRET") or os.getenv("DASHBOARD_SECRET", "")).strip().encode()
        self.lock = threading.Lock()
        self.fails: dict[str, list[float]] = {}   # ip -> failure times
        self.all_fails: list[float] = []

    @property
    def configured(self) -> bool:
        return bool(self.pin_hash and self.secret)

    # ---- sessions -------------------------------------------------------
    def _sign(self, payload: str) -> str:
        return hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()

    def new_session(self) -> str:
        exp = str(int(time.time()) + SESSION_DAYS * 86400)
        nonce = secrets.token_hex(8)
        payload = f"{exp}.{nonce}"
        return base64.urlsafe_b64encode(f"{payload}.{self._sign(payload)}".encode()).decode()

    def valid_session(self, token: str | None) -> bool:
        if not token or not self.configured:
            return False
        try:
            exp, nonce, sig = base64.urlsafe_b64decode(token.encode()).decode().split(".")
        except (ValueError, UnicodeDecodeError):
            return False
        return hmac.compare_digest(sig, self._sign(f"{exp}.{nonce}")) and int(exp) > time.time()

    # ---- login with limits ---------------------------------------------
    def locked_for(self, ip: str) -> int:
        """Seconds this address (or everyone) must wait before the next try; 0 = may try."""
        now = time.time()
        with self.lock:
            self.all_fails = [t for t in self.all_fails if now - t < 3600]
            if len(self.all_fails) >= MAX_FAILS_PER_HOUR:
                return int(3600 - (now - self.all_fails[0]))
            mine = [t for t in self.fails.get(ip, []) if now - t < LOCK_MINUTES * 60]
            self.fails[ip] = mine
            if len(mine) >= MAX_FAILS_PER_IP:
                return int(LOCK_MINUTES * 60 - (now - mine[0]))
        return 0

    def login(self, ip: str, pin: str) -> tuple[bool, str]:
        if not self.configured:
            return False, "PIN is not set on the server yet"
        wait = self.locked_for(ip)
        if wait:
            return False, f"Too many attempts – try again in {wait // 60 + 1} min"
        if verify_pin(pin, self.pin_hash):
            with self.lock:
                self.fails.pop(ip, None)
            return True, ""
        with self.lock:
            now = time.time()
            self.fails.setdefault(ip, []).append(now)
            self.all_fails.append(now)
            left = MAX_FAILS_PER_IP - len(self.fails[ip])
        return False, f"Wrong PIN – {max(0, left)} attempts left" if left > 0 else \
            f"Too many attempts – try again in {LOCK_MINUTES} min"
