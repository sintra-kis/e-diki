"""End-to-end API flow on an in-memory Mongo and a fake e-diki."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("mongomock_motor")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import server  # noqa: E402


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_full_flow(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(server, "db", db)
    server._hits.clear()
    server._shared.clear()
    today = datetime.now(server.ATHENS).date().isoformat()

    async def fake_get(path, params):
        if "id" in params:
            return {"content": [{"id": "d1", "code": "D1", "courtName": "Σύρος", "courtKind": "K", "courtCategory": "C",
                                 "lastStatusTimestamp": datetime.now(timezone.utc).isoformat(),
                                 "docketCases": [{"serialNumber": "1", "status": "CASE_END", "gak": "1/2026"},
                                                 {"serialNumber": "2", "status": "CASE_START", "gak": "2/2026"},
                                                 {"serialNumber": "3", "gak": "3/2026"},
                                                 {"serialNumber": "4", "gak": "4/2026"}]}]}
        if path == "/public/dockets":
            return {"content": [{"id": "d1"}], "last": True, "totalPages": 1}
        return ["Σύρος"]

    monkeypatch.setattr(server, "ediki_get", fake_get)
    loop = asyncio.new_event_loop()

    def reg(name, email, pw):
        return c.post("/api/auth/register", json={"name": name, "email": email, "password": pw}).json()["access_token"]

    with TestClient(server.app) as c:
        a, b, other = reg("A", "a@x.gr", "secret1"), reg("B", "b@x.gr", "secret2"), reg("C", "c@x.gr", "secret3")
        assert c.get("/api/auth/me", headers=auth("garbage")).status_code == 401

        g = c.post("/api/groups", json={"name": "G"}, headers=auth(a)).json()
        assert len(g["code"]) == 8
        assert c.post("/api/groups/join", json={"code": g["code"].lower()}, headers=auth(b)).status_code == 200

        uid = c.get("/api/auth/me", headers=auth(a)).json()["id"]
        loop.run_until_complete(db.verified_contacts.insert_one({"user_id": uid, "kind": "email", "value": "a@x.gr"}))
        body = dict(court_type="Πολιτικό", court_name="Σύρος", court_date=today, case_number="4/2026",
                    notify_email="a@x.gr", threshold=5, group_id=g["id"])
        r = c.post("/api/cases", json=body, headers=auth(a))
        assert r.status_code == 200 and r.json()["remaining_ahead"] == 1
        assert c.post("/api/cases", json=body, headers=auth(a)).status_code == 409   # duplicate

        seen_by_b = c.get("/api/cases", headers=auth(b)).json()
        assert len(seen_by_b) == 1 and "notify_email" not in seen_by_b[0]            # no contact leak
        assert c.get("/api/cases", headers=auth(a)).json()[0]["notify_email"] == "a@x.gr"

        notes = c.get("/api/notifications", headers=auth(a)).json()
        assert any(n["type"] == "approaching" for n in notes)
        nid = notes[0]["id"]
        c.post(f"/api/notifications/{nid}/read", headers=auth(other))                 # stranger cannot mark read
        assert not next(n for n in c.get("/api/notifications", headers=auth(a)).json() if n["id"] == nid)["read"]
        c.post(f"/api/notifications/{nid}/read", headers=auth(a))
        assert next(n for n in c.get("/api/notifications", headers=auth(a)).json() if n["id"] == nid)["read"]

        for _ in range(10):
            c.post("/api/groups/join", json={"code": "ZZZZZZZZ"}, headers=auth(other))
        assert c.post("/api/groups/join", json={"code": "ZZZZZZZZ"}, headers=auth(other)).status_code == 429
        for _ in range(10):
            c.post("/api/auth/login", json={"email": "a@x.gr", "password": "bad"})
        assert c.post("/api/auth/login", json={"email": "a@x.gr", "password": "secret1"}).status_code == 429
