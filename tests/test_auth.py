import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auth  # noqa: E402

TEST_PIN = "".join(secrets.choice("0123456789") for _ in range(6))  # throwaway, test only


def test_hash_and_verify():
    h = auth.hash_pin(TEST_PIN)
    assert TEST_PIN not in h
    assert auth.verify_pin(TEST_PIN, h)
    assert not auth.verify_pin("000000" if TEST_PIN != "000000" else "111111", h)
    assert not auth.verify_pin(TEST_PIN, "garbage")


def _server(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PIN_HASH", auth.hash_pin(TEST_PIN))
    monkeypatch.setenv("DASHBOARD_SECRET", secrets.token_hex(32))
    import dashboard_api
    dashboard_api.GUARD = auth.Guard()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), dashboard_api.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _req(url, data=None, cookie=None):
    r = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None, method="POST" if data is not None else "GET")
    if cookie:
        r.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or b"{}"), resp.headers.get("Set-Cookie")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), e.headers.get("Set-Cookie")


def test_login_flow_and_lockout(monkeypatch):
    srv, base = _server(monkeypatch)
    try:
        assert _req(base + "/api/status")[0] == 401                       # locked without a session
        assert _req(base + "/charts/x.png")[0] == 401
        assert _req(base + "/api/session")[1] == {"authenticated": False, "configured": True}

        wrong = "000000" if TEST_PIN != "000000" else "111111"
        code, body, _ = _req(base + "/api/login", {"pin": wrong})
        assert code == 401 and "attempts left" in body["error"]

        code, body, cookie = _req(base + "/api/login", {"pin": TEST_PIN})
        assert code == 200 and body["ok"] and "HttpOnly" in cookie
        session = cookie.split(";")[0]
        assert _req(base + "/api/session", cookie=session)[1]["authenticated"] is True
        assert _req(base + "/api/config", cookie=session)[0] == 200       # data with a session

        # 5 wrong tries lock this address – even the right PIN is refused then
        for _ in range(5):
            _req(base + "/api/login", {"pin": wrong})
        code, body, _ = _req(base + "/api/login", {"pin": TEST_PIN})
        assert code == 401 and "Too many attempts" in body["error"]

        assert _req(base + "/api/session", cookie="stocks_session=forged")[1]["authenticated"] is False
    finally:
        srv.shutdown()


def test_no_pin_configured_stays_locked(monkeypatch):
    monkeypatch.delenv("DASHBOARD_PIN_HASH", raising=False)
    monkeypatch.delenv("DASHBOARD_SECRET", raising=False)
    g = auth.Guard()
    assert not g.configured
    assert g.login("1.2.3.4", TEST_PIN) == (False, "PIN is not set on the server yet")
    assert not g.valid_session("anything")


def test_guard_reads_hash_with_dollar_signs_from_file(tmp_path, monkeypatch):
    """The PBKDF2 hash contains '$' – it must reach the Guard unchanged."""
    f = tmp_path / "web.env"
    h = auth.hash_pin(TEST_PIN)
    f.write_text(f"DASHBOARD_PIN_HASH={h}\nDASHBOARD_SECRET={secrets.token_hex(32)}\n")
    monkeypatch.setenv("WEB_ENV_FILE", str(f))
    monkeypatch.delenv("DASHBOARD_PIN_HASH", raising=False)
    g = auth.Guard()
    assert g.pin_hash == h and g.configured
    assert g.login("9.9.9.9", TEST_PIN)[0]
