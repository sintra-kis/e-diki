import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import server  # noqa: E402
from tests.fakes import Col  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class DB:
    def __init__(self):
        self.locks, self.verified_contacts = Col(), Col()
        self.tracked_cases, self.notifications = Col(), Col()

    async def command(self, name):
        if getattr(self, "down", False):
            raise RuntimeError("no db")
        return {"ok": 1}


@pytest.fixture
def db(monkeypatch):
    d = DB()
    monkeypatch.setattr(server, "db", d)
    return d


# --- single monitor across workers -------------------------------------------------------
def test_only_one_worker_holds_the_lease(db, monkeypatch):
    monkeypatch.setattr(server, "WORKER_ID", "A")
    assert run(server.acquire_monitor_lease()) is True
    assert run(server.acquire_monitor_lease()) is True      # the owner renews
    monkeypatch.setattr(server, "WORKER_ID", "B")
    assert run(server.acquire_monitor_lease()) is False     # B stays passive


def test_expired_lease_is_taken_over(db, monkeypatch):
    monkeypatch.setattr(server, "WORKER_ID", "A")
    run(server.acquire_monitor_lease())
    db.locks.docs[0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    monkeypatch.setattr(server, "WORKER_ID", "B")
    assert run(server.acquire_monitor_lease()) is True
    assert db.locks.docs[0]["owner"] == "B"


def test_released_lease_can_be_taken_immediately(db, monkeypatch):
    monkeypatch.setattr(server, "WORKER_ID", "A")
    run(server.acquire_monitor_lease())
    run(server.release_monitor_lease())
    monkeypatch.setattr(server, "WORKER_ID", "B")
    assert run(server.acquire_monitor_lease()) is True


def test_release_does_not_touch_someone_elses_lease(db, monkeypatch):
    monkeypatch.setattr(server, "WORKER_ID", "A")
    run(server.acquire_monitor_lease())
    monkeypatch.setattr(server, "WORKER_ID", "B")
    run(server.release_monitor_lease())
    monkeypatch.setattr(server, "WORKER_ID", "C")
    assert run(server.acquire_monitor_lease()) is False


# --- alerts only reach verified contacts --------------------------------------------------
@pytest.fixture
def sent(db, monkeypatch):
    out = []

    async def email(*, to, subject, html):
        out.append(("email", to))

    monkeypatch.setattr(server, "send_email", email)
    monkeypatch.setattr(server, "send_sms", lambda to, text: out.append(("sms", to)) or True)
    monkeypatch.setattr(server, "make_call", lambda to, text: out.append(("call", to)) or True)
    return out


def case(**kw):
    return {"id": "c1", "user_id": "u1", "case_number": "1/2026", "court_name": "Σύρος",
            "notify_email": "A@B.gr", "notify_channels": ["email", "sms", "call"], "phone": "6941234567", **kw}


def dispatch(tc, voice=True):
    db_case = dict(tc)
    run(server.dispatch_alert(db_case, "S", ["l"], "short", voice=voice))


def verify(db, kind, value, uid="u1"):
    db.verified_contacts.docs.append({"user_id": uid, "kind": kind, "value": value})


def test_nothing_is_sent_to_unverified_contacts(db, sent):
    tc = case()
    db.tracked_cases.docs.append(tc)
    dispatch(tc)
    assert sent == []
    assert [n["type"] for n in db.notifications.docs] == ["verify_needed"]


def test_warning_is_in_app_only_once(db, sent):
    tc = case()
    db.tracked_cases.docs.append(tc)
    dispatch(tc)
    dispatch(db.tracked_cases.docs[0])      # next alert sees notified_unverified=True
    assert len(db.notifications.docs) == 1


def test_only_verified_channels_fire(db, sent):
    tc = case()
    db.tracked_cases.docs.append(tc)
    verify(db, "email", "a@b.gr")
    dispatch(tc)
    assert sent == [("email", "a@b.gr")]
    assert [n["type"] for n in db.notifications.docs] == ["verify_needed"]   # phone still pending


def test_all_verified_sends_everything(db, sent):
    tc = case()
    db.tracked_cases.docs.append(tc)
    verify(db, "email", "a@b.gr")
    verify(db, "phone", "+306941234567")
    dispatch(tc)
    assert sent == [("email", "a@b.gr"), ("sms", "+306941234567"), ("call", "+306941234567")]
    assert db.notifications.docs == []


def test_progress_alert_skips_the_phone_call(db, sent):
    tc = case()
    db.tracked_cases.docs.append(tc)
    verify(db, "email", "a@b.gr")
    verify(db, "phone", "+306941234567")
    dispatch(tc, voice=False)
    assert ("call", "+306941234567") not in sent and ("sms", "+306941234567") in sent


def test_someone_elses_verification_does_not_unlock_alerts(db, sent):
    tc = case(notify_channels=["email"])
    db.tracked_cases.docs.append(tc)
    verify(db, "email", "a@b.gr", uid="other-user")
    dispatch(tc)
    assert sent == []


# --- pending list for the UI --------------------------------------------------------------
def test_pending_contacts_lists_unverified_distinct_values(db):
    db.tracked_cases.docs += [case(id="c1"), case(id="c2"),
                              case(id="c3", notify_channels=["email"], notify_email="x@y.gr", phone=None),
                              {**case(id="c4"), "user_id": "someone-else", "notify_email": "private@z.gr"}]
    verify(db, "email", "a@b.gr")
    pending = run(server.pending_contacts({"id": "u1"}))
    assert sorted((p["kind"], p["value"]) for p in pending) == [("email", "x@y.gr"), ("phone", "+306941234567")]


# --- health ---------------------------------------------------------------------------------
def test_health_ok_and_down(db):
    assert run(server.health()) == {"status": "ok"}
    db.down = True
    with pytest.raises(HTTPException) as e:
        run(server.health())
    assert e.value.status_code == 503


def test_blank_phone_is_not_a_number():
    assert server._to_e164("   ") is None
