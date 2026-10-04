"""End-to-end HTTP smoke test of the real FastAPI app against an in-memory MongoDB."""
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mongomock_motor")
from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import server  # noqa: E402


async def fake_ediki(path, params):
    if path.endswith("courtNames"):
        return ["Πρωτοδικείο Σύρου", "Πρωτοδικείο Φλώρινας"]
    if "id" in params:
        return {"content": [{"id": "d1", "code": "D1", "courtName": "Πρωτοδικείο Σύρου", "courtKind": "Μον. Πρωτοδικείο",
                             "lastStatusTimestamp": None, "docketCases": [
            {"serialNumber": "1", "gak": "1/2026", "status": "CASE_START", "description": "Αγωγή"},
            {"serialNumber": "2", "gak": "2/2026"},
            {"serialNumber": "3", "gak": "3/2026"},
            {"serialNumber": "4", "gak": "4/2026"}]}]}
    return {"content": [{"id": "d1"}], "totalPages": 1}


@pytest.fixture
def client(monkeypatch):
    sent = []

    async def send_code(kind, value, code):
        sent.append(code)
        return True

    monkeypatch.setattr(server, "db", AsyncMongoMockClient()["smoke"])
    monkeypatch.setattr(server, "ediki_get", fake_ediki)
    monkeypatch.setattr(server, "_send_code", send_code)
    monkeypatch.setattr(server, "dispatch_alert", lambda *a, **k: _noop())
    for name in ("_docket_cache", "_docket_locks", "_case_locks"):
        monkeypatch.setattr(server, name, {})
    with TestClient(server.app) as c:
        c.codes = sent
        yield c


async def _noop():
    return None


def auth(c, email="lawyer@firm.gr"):
    r = c.post("/api/auth/register", json={"name": "Μαρία Π", "email": email, "password": "secret12"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health_and_root(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/").json()["status"] == "ok"


def test_full_user_journey(client):
    h = auth(client)
    assert client.get("/api/auth/me", headers=h).json()["email"] == "lawyer@firm.gr"
    assert client.post("/api/auth/login", json={"email": "lawyer@firm.gr", "password": "secret12"}).status_code == 200

    # dropdown comes from e-diki, without needing a date
    assert "Πρωτοδικείο Σύρου" in client.get("/api/ediki/court-names", params={"courtType": "Πολιτικό"}).json()

    body = {"court_type": "Πολιτικό", "court_name": "Πρωτοδικείο Σύρου", "court_date": server._today_athens(),
            "case_number": "4/2026", "notify_email": "lawyer@firm.gr", "notify_channels": ["email"], "threshold": 5}
    # cannot track before the email is verified
    r = client.post("/api/cases", json=body, headers=h)
    assert r.status_code == 400 and "επαληθευτεί" in r.json()["detail"]

    assert client.post("/api/contacts/request", json={"kind": "email", "value": "lawyer@firm.gr"}, headers=h).status_code == 200
    bad = client.post("/api/contacts/verify", json={"kind": "email", "value": "lawyer@firm.gr", "code": "000000"}, headers=h)
    assert bad.status_code == 400
    ok = client.post("/api/contacts/verify", json={"kind": "email", "value": "lawyer@firm.gr", "code": client.codes[-1]}, headers=h)
    assert ok.status_code == 200
    assert client.get("/api/contacts", headers=h).json() == [{"kind": "email", "value": "lawyer@firm.gr"}]

    case = client.post("/api/cases", json=body, headers=h)
    assert case.status_code == 200, case.text
    c = case.json()
    assert c["matched"] is True and c["remaining_ahead"] == 2          # #2 and #3 are still before #4
    assert c["now_hearing_serial"] == "1"

    cases = client.get("/api/cases", headers=h).json()
    assert len(cases) == 1 and "_id" not in cases[0]
    assert client.post(f"/api/cases/{c['id']}/refresh", headers=h).status_code == 200

    notes = client.get("/api/notifications", headers=h).json()
    assert any(n["type"] == "approaching" for n in notes)
    nid = notes[0]["id"]
    assert client.post(f"/api/notifications/{nid}/read", headers=h).status_code == 200

    # another user sees nothing and cannot touch it
    h2 = auth(client, "other@firm.gr")
    assert client.get("/api/cases", headers=h2).json() == []
    assert client.post(f"/api/notifications/{nid}/read", headers=h2).status_code == 404
    assert client.delete(f"/api/cases/{c['id']}", headers=h2).status_code == 403
    assert client.delete(f"/api/cases/{c['id']}", headers=h).status_code == 200


def test_groups_share_cases(client):
    h1, h2 = auth(client, "a@firm.gr"), auth(client, "b@firm.gr")
    g = client.post("/api/groups", json={"name": "Γραφείο"}, headers=h1).json()
    assert len(g["code"]) == 10
    assert client.post("/api/groups/join", json={"code": g["code"].lower()}, headers=h2).status_code == 200
    assert [x["id"] for x in client.get("/api/groups", headers=h2).json()] == [g["id"]]


def test_protected_routes_need_a_valid_token(client):
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/cases", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_login_is_rate_limited(client):
    auth(client)
    codes = [client.post("/api/auth/login", json={"email": "lawyer@firm.gr", "password": "wrong-pass"}).status_code
             for _ in range(server.LOGIN_FAILS_PER_EMAIL + 1)]
    assert codes[:server.LOGIN_FAILS_PER_EMAIL] == [401] * server.LOGIN_FAILS_PER_EMAIL and codes[-1] == 429


def test_invalid_case_payload_is_rejected(client):
    h = auth(client)
    r = client.post("/api/cases", headers=h, json={"court_type": "Πολιτικό", "court_name": "x", "court_date": "05/10/2026",
                                                    "case_number": "1", "notify_channels": ["fax"]})
    assert r.status_code == 422
