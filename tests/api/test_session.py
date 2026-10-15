"""Sessions, identity from users.json, development-only endpoints (003 spec US1, edge cases)."""
import json
import time

import itsdangerous
import pytest

from copilot_api.config import StartupError, load_config

PROTECTED = [
    ("GET", "/api/session"), ("GET", "/api/groups"), ("POST", "/api/ask"),
    ("GET", "/api/sources/p_79e8df3857393da815e28cdf"),
    ("GET", "/api/sources/p_79e8df3857393da815e28cdf/page.png"),
    ("POST", "/api/work-orders"), ("GET", "/api/work-orders"),
    ("GET", "/api/work-orders?mine=true"),
    ("GET", "/api/work-orders/wo_1"), ("PATCH", "/api/work-orders/wo_1"),
    ("POST", "/api/work-orders/wo_1/request-approval"), ("POST", "/api/work-orders/wo_1/approve"),
    ("POST", "/api/work-orders/wo_1/reject"), ("POST", "/api/work-orders/wo_1/submit"),
]
BODIES = {"/api/ask": {"question": "How do I reset E-31?"},
          "/api/work-orders": {"suggestion": {"summary": "x", "asset_id": "TAC-C-0143"}},
          "/api/work-orders/wo_1": {"summary": "x"}}


def _call(client, method, path):
    body = BODIES.get(path.split("?")[0], {"confirm": True})
    return client.request(method, path, json=body if method in ("POST", "PATCH") else None,
                          headers={"Idempotency-Key": "k1"})


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_401_without_session(harness, method, path):
    r = _call(harness.client(), method, path)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}
    assert harness.engine.calls == []


@pytest.mark.parametrize("path", ["/api/ask", "/api/work-orders"])
def test_401_comes_before_body_validation(harness, path):
    r = harness.client().post(path, json={"unexpected": 1})
    assert r.status_code == 401


@pytest.mark.parametrize("cookie", ["garbage", "dTAz.ZXhwaXJlZA.c2lnbmF0dXJl"])
def test_401_with_tampered_cookie(harness, cookie):
    c = harness.client()
    c.cookies.set("copilot_session", cookie)
    assert c.get("/api/session").status_code == 401


def test_401_with_cookie_signed_by_another_secret(harness):
    from copilot_api.session import Sessions

    c = harness.client()
    c.cookies.set("copilot_session", Sessions("other-secret", 3600).sign("u02"))
    assert c.get("/api/session").status_code == 401


def test_401_with_expired_cookie(harness, monkeypatch):
    monkeypatch.setattr(itsdangerous.timed.TimestampSigner, "get_timestamp",
                        lambda self: int(time.time()) - 2 * 3600)
    token = harness.sessions.sign("u03")
    monkeypatch.undo()
    c = harness.client()
    c.cookies.set("copilot_session", token)
    assert c.get("/api/session").status_code == 401


def test_sign_in_sets_signed_http_only_cookie(harness):
    c = harness.client()
    r = c.post("/api/session", json={"user_id": "u03"})
    assert r.status_code == 200
    assert r.json() == {"user_id": "u03", "name": "Priya Natarajan",
                        "groups": ["family-compressors", "region-na"]}
    header = r.headers["set-cookie"]
    assert header.startswith("copilot_session=")
    for attr in ("HttpOnly", "SameSite=lax", "Path=/"):
        assert attr.lower() in header.lower()
    value = header.split(";")[0].split("=", 1)[1]
    assert value != "u03" and "region" not in value
    assert harness.sessions.user_id(value) == "u03"
    assert c.get("/api/session").json()["user_id"] == "u03"


def test_unknown_user_is_invalid_request(harness):
    r = harness.client().post("/api/session", json={"user_id": "u99"})
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_request"


def test_sign_out(harness):
    c = harness.client()
    c.post("/api/session", json={"user_id": "u03"})
    r = c.delete("/api/session")
    assert r.status_code == 204
    assert "max-age=0" in r.headers["set-cookie"].lower()
    assert c.get("/api/session").status_code == 401


def test_dev_users_and_groups(harness):
    users = harness.client().get("/api/dev/users").json()["users"]
    assert {u["user_id"] for u in users} == {f"u{i:02d}" for i in range(1, 13)}
    assert set(users[0]) == {"user_id", "name", "title", "groups"}
    groups = harness.client("u03").get("/api/groups").json()
    assert groups["cert-hv"].startswith("High-voltage")


def test_production_disables_dev_sign_in(make_harness):
    h = make_harness(app_env="production")
    assert h.client().post("/api/session", json={"user_id": "u02"}).status_code == 404
    assert h.client().get("/api/dev/users").status_code == 404
    assert h.client().get("/api/dev/users").json() == {"error": "not_found"}
    # a session issued by the real identity provider still works
    c = h.client("u03")
    assert c.get("/api/session").json()["user_id"] == "u03"
    assert c.get("/api/groups").status_code == 200


def test_production_needs_a_session_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "")
    with pytest.raises(StartupError):
        load_config()


def test_users_json_change_applies_on_next_request(harness, users_file):
    c = harness.client("u03")
    c.post("/api/ask", json={"question": "How do I reset E-31 on TAC-C-0143?"})
    assert harness.engine.calls[-1][0].groups == {"region-na", "family-compressors"}

    data = json.loads(users_file.read_text())
    next(u for u in data["users"] if u["id"] == "u03")["groups"].append("cert-hv")
    users_file.write_text(json.dumps(data))

    c.post("/api/ask", json={"question": "How do I reset E-31 on TAC-C-0143?"})
    assert harness.engine.calls[-1][0].groups == {"region-na", "family-compressors", "cert-hv"}
    assert "cert-hv" in c.get("/api/session").json()["groups"]

    data["users"] = [u for u in data["users"] if u["id"] != "u03"]
    users_file.write_text(json.dumps(data))
    assert c.get("/api/session").status_code == 401
    assert c.post("/api/ask", json={"question": "again"}).status_code == 401
