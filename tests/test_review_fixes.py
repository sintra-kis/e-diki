"""Regression tests for the correctness/privacy fixes layered on top of the hardened base."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
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
from docket_logic import analyze  # noqa: E402
from tests.fakes import Col  # noqa: E402

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def case(serial, status=None, **kw):
    return {"serialNumber": str(serial), "status": status, **kw}


# --- "started" needs a case actually in progress --------------------------------------------
def test_timestamp_alone_does_not_start_a_docket():
    stamp = (NOW - timedelta(hours=20)).isoformat()
    d = {"lastStatusTimestamp": stamp, "docketCases": [case(1), case(2), case(3, gak="3/2026")]}
    r = analyze(d, "3/2026", stuck_minutes=20, now=NOW)
    assert r["started"] is False and r["stuck"] is False and r["remaining_ahead"] == 2


# --- group members never see each other's contact details -----------------------------------
def test_public_case_hides_contacts_from_other_users():
    tc = {"user_id": "u1", "notify_email": "a@b.gr", "phone": "+306900000000",
          "notify_channels": ["sms"], "pending_alerts": [1], "case_number": "1/2026"}
    other = server.public_case(dict(tc), "u2")
    assert not {"notify_email", "phone", "notify_channels", "pending_alerts"} & set(other)
    mine = server.public_case(dict(tc), "u1")
    assert mine["notify_email"] == "a@b.gr" and "pending_alerts" not in mine


# --- case number beats Α/Α serial, across dockets --------------------------------------------
TC = {"court_type": "Πολιτικό", "court_name": "Σύρος", "court_kind": None, "court_category": None,
      "court_date": "2026-10-05", "case_number": "12"}


def _fake_ediki(monkeypatch, dockets):
    async def get(path, params):
        if "id" in params:
            return {"content": [dockets[params["id"]]]}
        return {"content": [{"id": k} for k in dockets], "last": True, "totalPages": 1}

    monkeypatch.setattr(server, "ediki_get", get)
    monkeypatch.setattr(server, "_docket_cache", {})
    monkeypatch.setattr(server, "_docket_locks", {})


def test_case_number_in_later_docket_beats_serial_in_earlier_one(monkeypatch):
    _fake_ediki(monkeypatch, {
        "a": {"id": "a", "docketCases": [case(12, gak="999/2026")]},     # Α/Α 12 only
        "b": {"id": "b", "docketCases": [case(3, gak="12")]},            # real ΓΑΚ 12
    })
    r = run(server.resolve_case(dict(TC)))
    assert r["matched"] and r["docket_id"] == "b"


def test_serial_match_is_used_when_no_case_number_matches(monkeypatch):
    _fake_ediki(monkeypatch, {"a": {"id": "a", "docketCases": [case(12, gak="999/2026")]}})
    assert run(server.resolve_case(dict(TC)))["docket_id"] == "a"


# --- undelivered alerts are retried, never lost, never duplicated in-app ---------------------
class DB:
    def __init__(self, docs=()):
        self.tracked_cases, self.notifications = Col(), Col()
        self.tracked_cases.docs.extend(docs)


def test_failed_alert_is_retried_then_dropped(monkeypatch):
    doc = {"id": "c1", "user_id": "u1", "case_number": "1/2026"}
    db = DB([doc])
    monkeypatch.setattr(server, "db", db)
    outcomes = iter([False, False, True])
    sent = []

    async def dispatch(tc, subject, lines, short, voice=True):
        sent.append(subject)
        return next(outcomes)

    monkeypatch.setattr(server, "dispatch_alert", dispatch)

    def stored():
        return db.tracked_cases.docs[0]

    run(server._emit(dict(stored()), [], [("Πλησιάζει", ["x"], "short", True)]))
    assert len(stored()["pending_alerts"]) == 1
    run(server._emit(dict(stored()), [], []))
    assert stored()["pending_alerts"][0]["tries"] == 2
    run(server._emit(dict(stored()), [], []))
    assert stored()["pending_alerts"] == [] and len(sent) == 3
    assert db.notifications.docs == []


def test_alert_retry_gives_up_after_max_tries(monkeypatch):
    db = DB([{"id": "c1", "user_id": "u1", "case_number": "1/2026"}])
    monkeypatch.setattr(server, "db", db)

    async def dispatch(*a, **k):
        return False

    monkeypatch.setattr(server, "dispatch_alert", dispatch)
    run(server._emit(dict(db.tracked_cases.docs[0]), [], [("t", ["x"], "s", True)]))
    for _ in range(5):
        run(server._emit(dict(db.tracked_cases.docs[0]), [], []))
    assert db.tracked_cases.docs[0]["pending_alerts"] == []


def _verified_db(tc):
    db = DB()
    db.verified_contacts = Col()
    db.verified_contacts.docs.append({"user_id": "u1", "kind": "email", "value": "a@b.gr"})
    return db


def test_unconfigured_provider_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(server, "db", _verified_db(None))
    monkeypatch.setattr(server, "EMAIL_KEY", None)
    tc = {"id": "c", "user_id": "u1", "notify_channels": ["email"], "notify_email": "a@b.gr"}
    assert run(server.dispatch_alert(tc, "s", ["l"], "short")) is True


def test_failed_email_send_is_reported_as_failure(monkeypatch):
    monkeypatch.setattr(server, "db", _verified_db(None))
    monkeypatch.setattr(server, "EMAIL_KEY", "k")

    async def boom(**kw):
        return None

    monkeypatch.setattr(server, "send_email", boom)
    tc = {"id": "c", "user_id": "u1", "notify_channels": ["email"], "notify_email": "a@b.gr"}
    assert run(server.dispatch_alert(tc, "s", ["l"], "short")) is False


# --- approaching / stuck only on the hearing day ---------------------------------------------
def test_no_approaching_or_stuck_alert_before_court_day(monkeypatch):
    from tests.test_server_logic import run_checks, base_doc, live
    fake, sent = run_checks(monkeypatch, base_doc(court_date="2999-01-01", remaining_ahead=8),
                            [live(2, stuck=True)])
    types = [n["type"] for n in fake.notifications.docs]
    assert "approaching" not in types and "stuck" not in types and sent == []


# --- verification-code guesses are limited atomically ----------------------------------------
def test_parallel_wrong_guesses_cannot_exceed_the_attempt_limit(monkeypatch):
    mongo = AsyncMongoMockClient()["otp"]
    monkeypatch.setattr(server, "db", mongo)
    now = datetime.now(timezone.utc)
    run(mongo.contact_challenges.insert_one({
        "id": "ch1", "user_id": "u1", "kind": "email", "value": "a@b.gr", "used": False, "attempts": 0,
        "code_hash": server._code_hash("ch1", "123456"),
        "expires_at": (now + timedelta(minutes=5)).isoformat(), "created_at": now.isoformat()}))

    async def guess(code):
        try:
            await server.verify_contact(
                server.ContactVerifyIn(kind="email", value="a@b.gr", code=code), {"id": "u1"})
            return 200
        except server.HTTPException as e:
            return e.status_code

    async def go():
        res = await asyncio.gather(*(guess("000000") for _ in range(15)))
        right = await guess("123456")
        return res, right

    res, right = run(go())
    assert res.count(400) == server.CODE_MAX_ATTEMPTS
    assert right == 429
    assert run(mongo.verified_contacts.count_documents({})) == 0


# --- API level: duplicates, group privacy, notification ownership ----------------------------
async def _ediki(path, params):
    if path.endswith("courtNames"):
        return ["Σύρος"]
    if "id" in params:
        return {"content": [{"id": "d1", "code": "D1", "courtName": "Σύρος", "courtKind": "K", "courtCategory": "C",
                             "docketCases": [case(1, "CASE_END", gak="1/2026"), case(2, "CASE_START", gak="2/2026"),
                                             case(3, gak="3/2026"), case(4, gak="4/2026")]}]}
    return {"content": [{"id": "d1"}], "last": True, "totalPages": 1}


@pytest.fixture
def api(monkeypatch):
    async def ok(*a, **k):
        return True

    monkeypatch.setattr(server, "db", AsyncMongoMockClient()["review"])
    monkeypatch.setattr(server, "ediki_get", _ediki)
    monkeypatch.setattr(server, "dispatch_alert", ok)
    for n in ("_docket_cache", "_docket_locks", "_case_locks"):
        monkeypatch.setattr(server, n, {})
    with TestClient(server.app) as c:
        yield c


def _reg(c, name):
    r = c.post("/api/auth/register", json={"name": name, "email": f"{name}@x.gr", "password": "secret12"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, c.get("/api/auth/me", headers={
        "Authorization": f"Bearer {r.json()['access_token']}"}).json()["id"]


def test_duplicate_privacy_and_notification_ownership(api):
    c = api
    (ha, uid_a), (hb, _), (hc, _) = _reg(c, "a"), _reg(c, "b"), _reg(c, "c")
    g = c.post("/api/groups", json={"name": "G"}, headers=ha).json()
    assert c.post("/api/groups/join", json={"code": g["code"]}, headers=hb).status_code == 200
    loop = asyncio.new_event_loop()
    loop.run_until_complete(server.db.verified_contacts.insert_one({"user_id": uid_a, "kind": "email", "value": "a@x.gr"}))

    body = {"court_type": "Πολιτικό", "court_name": "Σύρος", "court_date": server._today_athens(),
            "case_number": "4/2026", "notify_email": "a@x.gr", "threshold": 5, "group_id": g["id"]}
    r = api.post("/api/cases", json=body, headers=ha)
    assert r.status_code == 200 and r.json()["remaining_ahead"] == 1
    assert "pending_alerts" not in r.json()
    assert api.post("/api/cases", json=body, headers=ha).status_code == 409           # duplicate

    seen_by_b = api.get("/api/cases", headers=hb).json()
    assert len(seen_by_b) == 1 and not {"notify_email", "phone"} & set(seen_by_b[0])   # no contact leak
    assert api.get("/api/cases", headers=ha).json()[0]["notify_email"] == "a@x.gr"

    notes = api.get("/api/notifications", headers=ha).json()
    nid = notes[0]["id"]
    assert api.post(f"/api/notifications/{nid}/read", headers=hc).status_code == 404   # stranger
    assert not next(n for n in api.get("/api/notifications", headers=ha).json() if n["id"] == nid)["read"]
    assert api.post(f"/api/notifications/{nid}/read", headers=ha).status_code == 200
