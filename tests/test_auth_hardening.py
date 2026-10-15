import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

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


class Users(Col):
    async def insert_one(self, d):
        await super().insert_one(d)
        return SimpleNamespace(inserted_id=f"id{len(self.docs)}")


class DB:
    def __init__(self):
        self.auth_attempts = Col()
        self.users = Users()
        self.notifications = Col()
        self.groups = Col(unique="code")


@pytest.fixture
def db(monkeypatch):
    d = DB()
    monkeypatch.setattr(server, "db", d)
    return d


def req(ip="1.2.3.4"):
    return SimpleNamespace(client=SimpleNamespace(host=ip), headers={})


def add_user(db, email="a@b.gr", pw="secret1"):
    db.users.docs.append({"_id": "507f1f77bcf86cd799439011", "email": email, "name": "A",
                          "password_hash": server.hash_password(pw)})


def login(email="a@b.gr", pw="secret1", ip="1.2.3.4"):
    return run(server.login(server.LoginIn(email=email, password=pw), req(ip)))


# --- login rate limiting ---------------------------------------------------------------
def test_login_ok_and_wrong_password(db):
    add_user(db)
    assert login()["access_token"]
    with pytest.raises(HTTPException) as e:
        login(pw="nope")
    assert e.value.status_code == 401


def test_account_locks_after_repeated_failures_even_with_right_password(db):
    add_user(db)
    for _ in range(server.LOGIN_FAILS_PER_EMAIL):
        with pytest.raises(HTTPException) as e:
            login(pw="bad")
        assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:
        login(pw="secret1")
    assert e.value.status_code == 429


def test_failed_attempts_reset_after_successful_login(db):
    add_user(db)
    for _ in range(server.LOGIN_FAILS_PER_EMAIL - 1):
        with pytest.raises(HTTPException):
            login(pw="bad")
    login()
    for _ in range(server.LOGIN_FAILS_PER_EMAIL - 1):
        with pytest.raises(HTTPException) as e:
            login(pw="bad")
        assert e.value.status_code == 401


def test_ip_limit_stops_spraying_many_accounts(db):
    for i in range(server.LOGIN_FAILS_PER_IP):
        with pytest.raises(HTTPException) as e:
            login(email=f"user{i}@b.gr", pw="x", ip="9.9.9.9")
        assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:
        login(email="another@b.gr", pw="x", ip="9.9.9.9")
    assert e.value.status_code == 429
    with pytest.raises(HTTPException) as e:   # a different IP is unaffected
        login(email="another@b.gr", pw="x", ip="8.8.8.8")
    assert e.value.status_code == 401


def test_unknown_email_gets_same_error_as_wrong_password(db):
    with pytest.raises(HTTPException) as e:
        login(email="ghost@b.gr")
    assert e.value.status_code == 401 and "Λάθος email ή κωδικός" in e.value.detail


def test_register_limited_per_ip(db):
    for i in range(server.REGISTER_PER_IP_HOUR):
        run(server.register(server.RegisterIn(name="N", email=f"u{i}@b.gr", password="secret1"), req()))
    with pytest.raises(HTTPException) as e:
        run(server.register(server.RegisterIn(name="N", email="late@b.gr", password="secret1"), req()))
    assert e.value.status_code == 429


def test_forwarded_header_only_trusted_when_configured(monkeypatch):
    r = SimpleNamespace(client=SimpleNamespace(host="10.0.0.1"), headers={"x-forwarded-for": "5.5.5.5, 10.0.0.1"})
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    assert server.client_ip(r) == "10.0.0.1"
    monkeypatch.setenv("TRUST_PROXY", "1")
    assert server.client_ip(r) == "5.5.5.5"


def test_malformed_token_subject_is_401_not_500(db):
    token = server.jwt.encode({"sub": "not-an-objectid", "type": "access"}, server.JWT_SECRET, algorithm="HS256")
    r = SimpleNamespace(headers={"Authorization": f"Bearer {token}"}, cookies={})
    with pytest.raises(HTTPException) as e:
        run(server.get_current_user(r))
    assert e.value.status_code == 401


# --- notification ownership -------------------------------------------------------------
@pytest.fixture
def notes(db, monkeypatch):
    db.notifications.docs += [
        {"id": "n-mine", "user_id": "u1", "group_id": None, "read": False},
        {"id": "n-other", "user_id": "u2", "group_id": None, "read": False},
        {"id": "n-group", "user_id": "u2", "group_id": "g1", "read": False},
    ]

    async def gids(user):
        return ["g1"] if user["id"] == "u1" else []
    monkeypatch.setattr(server, "user_group_ids", gids)
    return db.notifications


def mark(note_id, uid="u1"):
    return run(server.read_notification(note_id, {"id": uid}))


def read_state(notes, nid):
    return next(d for d in notes.docs if d["id"] == nid)["read"]


def test_can_mark_own_and_group_notifications(notes):
    mark("n-mine")
    mark("n-group")
    assert read_state(notes, "n-mine") and read_state(notes, "n-group")


def test_cannot_mark_someone_elses_notification(notes):
    with pytest.raises(HTTPException) as e:
        mark("n-other")
    assert e.value.status_code == 404 and not read_state(notes, "n-other")


def test_group_notification_not_visible_outside_group(notes):
    with pytest.raises(HTTPException):
        mark("n-group", uid="u3")
    assert not read_state(notes, "n-group")


# --- groups -----------------------------------------------------------------------------
def oid(n):
    return {"id": f"{n:024x}"}   # the routes build bson ObjectIds from user ids


@pytest.fixture
def groups(db, monkeypatch):
    class Users2(Col):
        pass
    db.users = Users2()
    return db


def patch_user_update(monkeypatch, db):
    # group routes touch users by ObjectId; the fake only needs to accept the call
    async def noop(*a, **k):
        return SimpleNamespace(matched_count=1)
    monkeypatch.setattr(db.users, "update_one", noop)


def test_group_code_format_and_entropy():
    codes = {server.new_group_code() for _ in range(500)}
    assert len(codes) == 500
    for c in codes:
        assert len(c) == server.GROUP_CODE_LEN and set(c) <= set(server.GROUP_CODE_ALPHABET)
    assert not set("01OI") & set(server.GROUP_CODE_ALPHABET)


def test_create_and_join_group(groups, monkeypatch):
    patch_user_update(monkeypatch, groups)
    g = run(server.create_group(server.GroupIn(name=" Γραφείο "), oid(1)))
    assert g["name"] == "Γραφείο" and len(g["code"]) == server.GROUP_CODE_LEN
    joined = run(server.join_group(server.JoinGroupIn(code=f" {g['code'].lower()} "), oid(2)))
    assert joined["id"] == g["id"]
    assert oid(2)["id"] in groups.groups.docs[0]["member_ids"]


def test_create_group_retries_on_code_collision(groups, monkeypatch):
    patch_user_update(monkeypatch, groups)
    groups.groups.docs.append({"id": "old", "code": "COLLIDES01"})
    codes = iter(["COLLIDES01", "FRESHCODE22"])
    monkeypatch.setattr(server, "new_group_code", lambda: next(codes))
    g = run(server.create_group(server.GroupIn(name="G"), oid(1)))
    assert g["code"] == "FRESHCODE22"


def test_join_with_wrong_codes_is_throttled(groups, monkeypatch):
    patch_user_update(monkeypatch, groups)
    for _ in range(server.JOIN_FAILS_PER_USER_HOUR):
        with pytest.raises(HTTPException) as e:
            run(server.join_group(server.JoinGroupIn(code="WRONGCODE1"), oid(9)))
        assert e.value.status_code == 404
    g = run(server.create_group(server.GroupIn(name="G"), oid(7)))
    with pytest.raises(HTTPException) as e:     # even the right code is refused while throttled
        run(server.join_group(server.JoinGroupIn(code=g["code"]), oid(9)))
    assert e.value.status_code == 429


def test_throttle_is_per_user(groups, monkeypatch):
    patch_user_update(monkeypatch, groups)
    for _ in range(server.JOIN_FAILS_PER_USER_HOUR):
        with pytest.raises(HTTPException):
            run(server.join_group(server.JoinGroupIn(code="WRONGCODE1"), oid(9)))
    g = run(server.create_group(server.GroupIn(name="G"), oid(7)))
    assert run(server.join_group(server.JoinGroupIn(code=g["code"]), oid(8)))["id"] == g["id"]
