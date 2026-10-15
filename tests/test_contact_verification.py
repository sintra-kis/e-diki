import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import server  # noqa: E402

U1, U2 = {"id": "u1"}, {"id": "u2"}


class Col:
    """Tiny in-memory stand-in for a motor collection (equality, $gte, $set, $inc, upsert)."""

    def __init__(self):
        self.docs = []

    @staticmethod
    def _match(d, q):
        for k, v in q.items():
            if isinstance(v, dict):
                if "$gte" in v and not d.get(k, "") >= v["$gte"]:
                    return False
                if "$lt" in v and not d.get(k, 0) < v["$lt"]:
                    return False
            elif d.get(k) != v:
                return False
        return True

    async def find_one(self, q, sort=None):
        hits = [d for d in self.docs if self._match(d, q)]
        if sort:
            hits.sort(key=lambda d: d.get(sort[0][0], ""), reverse=sort[0][1] < 0)
        return dict(hits[0]) if hits else None

    async def find_one_and_update(self, q, upd):
        for d in self.docs:
            if self._match(d, q):
                before = dict(d)
                d.update(upd.get("$set", {}))
                for k, n in upd.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + n
                return before
        return None

    async def insert_one(self, d):
        self.docs.append(dict(d))

    async def delete_one(self, q):
        for d in self.docs:
            if self._match(d, q):
                self.docs.remove(d)
                return

    async def count_documents(self, q):
        return sum(1 for d in self.docs if self._match(d, q))

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if self._match(d, q):
                d.update(upd.get("$set", {}))
                for k, n in upd.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + n
                return
        if upsert:
            self.docs.append({**q, **upd.get("$set", {})})

    def find(self, q):
        outer = self

        class Cursor:
            async def to_list(self, n):
                return [dict(d) for d in outer.docs if outer._match(d, q)]
        return Cursor()


class DB:
    def __init__(self):
        self.contact_challenges, self.verified_contacts = Col(), Col()


@pytest.fixture
def env(monkeypatch):
    db, sent = DB(), []

    async def fake_send(kind, value, code):
        sent.append((kind, value, code))
        return True

    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "_send_code", fake_send)
    return db, sent


def run(coro):
    return asyncio.run(coro)


def request(user, kind, value):
    return run(server.request_contact_code(server.ContactIn(kind=kind, value=value), user))


def verify(user, kind, value, code):
    return run(server.verify_contact(server.ContactVerifyIn(kind=kind, value=value, code=code), user))


def age_challenges(db, seconds):
    for d in db.contact_challenges.docs:
        d["created_at"] = (datetime.fromisoformat(d["created_at"]) - timedelta(seconds=seconds)).isoformat()


def test_happy_path_email(env):
    db, sent = env
    request(U1, "email", " Lawyer@Firm.GR ")
    kind, value, code = sent[0]
    assert value == "lawyer@firm.gr" and len(code) == 6
    assert verify(U1, "email", "lawyer@firm.gr", code)["ok"]
    assert run(server.is_verified("u1", "email", "lawyer@firm.gr"))


def test_phone_is_normalised_before_verifying(env):
    db, sent = env
    request(U1, "phone", "694 123 4567")
    assert sent[0][1] == "+306941234567"
    verify(U1, "phone", "6941234567", sent[0][2])
    assert run(server.is_verified("u1", "phone", "+306941234567"))


def test_code_is_not_stored_in_plain_text(env):
    db, sent = env
    request(U1, "email", "a@b.gr")
    assert sent[0][2] not in str(db.contact_challenges.docs)


def test_wrong_code_then_lockout_even_with_right_code(env):
    db, sent = env
    request(U1, "email", "a@b.gr")
    good = sent[0][2]
    bad = "000000" if good != "000000" else "111111"
    for _ in range(server.CODE_MAX_ATTEMPTS):
        with pytest.raises(HTTPException) as e:
            verify(U1, "email", "a@b.gr", bad)
        assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        verify(U1, "email", "a@b.gr", good)
    assert e.value.status_code == 429
    assert not run(server.is_verified("u1", "email", "a@b.gr"))


def test_expired_code_rejected(env):
    db, sent = env
    request(U1, "email", "a@b.gr")
    db.contact_challenges.docs[0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with pytest.raises(HTTPException) as e:
        verify(U1, "email", "a@b.gr", sent[0][2])
    assert e.value.status_code == 400


def test_code_cannot_be_reused(env):
    db, sent = env
    request(U1, "email", "a@b.gr")
    verify(U1, "email", "a@b.gr", sent[0][2])
    with pytest.raises(HTTPException):
        verify(U1, "email", "a@b.gr", sent[0][2])


def test_other_user_cannot_use_my_code(env):
    db, sent = env
    request(U1, "email", "a@b.gr")
    with pytest.raises(HTTPException):
        verify(U2, "email", "a@b.gr", sent[0][2])
    assert not run(server.is_verified("u2", "email", "a@b.gr"))


def test_verification_is_per_user(env):
    db, sent = env
    request(U1, "email", "a@b.gr")
    verify(U1, "email", "a@b.gr", sent[0][2])
    assert not run(server.is_verified("u2", "email", "a@b.gr"))


def test_resend_cooldown(env):
    db, sent = env
    request(U1, "email", "a@b.gr")
    with pytest.raises(HTTPException) as e:
        request(U1, "email", "a@b.gr")
    assert e.value.status_code == 429 and len(sent) == 1
    age_challenges(db, server.CODE_COOLDOWN_S + 1)
    request(U1, "email", "a@b.gr")
    assert len(sent) == 2


def test_per_user_hourly_cap_stops_sms_spraying(env):
    db, sent = env
    for i in range(server.CODE_PER_USER_HOUR):
        request(U1, "phone", f"+3069400000{i:02d}")
    with pytest.raises(HTTPException) as e:
        request(U1, "phone", "+306940000099")
    assert e.value.status_code == 429


def test_per_contact_daily_cap_protects_a_victim_number(env):
    db, sent = env
    for i in range(server.CODE_PER_CONTACT_DAY):
        request({"id": f"attacker{i}"}, "phone", "+306941234567")
    with pytest.raises(HTTPException) as e:
        request({"id": "attacker9"}, "phone", "+306941234567")
    assert e.value.status_code == 429


def test_failed_delivery_is_reported_and_not_counted(env, monkeypatch):
    db, sent = env

    async def failing(kind, value, code):
        return False
    monkeypatch.setattr(server, "_send_code", failing)
    with pytest.raises(HTTPException) as e:
        request(U1, "email", "a@b.gr")
    assert e.value.status_code == 503 and db.contact_challenges.docs == []


def test_invalid_contacts_rejected(env):
    for kind, value in (("email", "not-an-email"), ("phone", "123")):
        with pytest.raises(HTTPException) as e:
            request(U1, kind, value)
        assert e.value.status_code == 422


def test_already_verified_does_not_resend(env):
    db, sent = env
    request(U1, "email", "a@b.gr")
    verify(U1, "email", "a@b.gr", sent[0][2])
    assert request(U1, "email", "a@b.gr")["already_verified"] is True
    assert len(sent) == 1


# --- gate in front of "add case" ---------------------------------------------------------
def track(**kw):
    base = dict(court_type="Πολιτικό", court_name="Σύρος", court_date="2026-10-05", case_number="1/2026")
    return server.TrackIn(**{**base, **kw})


def test_cannot_track_with_unverified_email(env):
    with pytest.raises(HTTPException) as e:
        run(server.require_verified_contacts("u1", track(notify_email="a@b.gr")))
    assert e.value.status_code == 400


def test_cannot_track_with_unverified_phone(env):
    db, sent = env
    request(U1, "email", "a@b.gr")
    verify(U1, "email", "a@b.gr", sent[0][2])
    body = track(notify_email="a@b.gr", notify_channels=["email", "sms"], phone="6941234567")
    with pytest.raises(HTTPException):
        run(server.require_verified_contacts("u1", body))


def test_verified_contacts_pass_the_gate(env):
    db, sent = env
    request(U1, "email", "a@b.gr")
    verify(U1, "email", "a@b.gr", sent[0][2])
    request(U1, "phone", "6941234567")
    verify(U1, "phone", "+306941234567", sent[1][2])
    body = track(notify_email="A@B.gr", notify_channels=["email", "call"], phone="6941234567")
    run(server.require_verified_contacts("u1", body))   # no exception


def test_someone_elses_verified_email_does_not_count(env):
    db, sent = env
    request(U2, "email", "a@b.gr")
    verify(U2, "email", "a@b.gr", sent[0][2])
    with pytest.raises(HTTPException):
        run(server.require_verified_contacts("u1", track(notify_email="a@b.gr")))
