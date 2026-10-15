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
from docket_logic import analyze  # noqa: E402

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def case(serial, status=None, **kw):
    return {"serialNumber": str(serial), "status": status, **kw}


# --- docket logic ----------------------------------------------------------------------
def test_timestamp_alone_does_not_start_a_docket():
    stamp = (NOW - timedelta(hours=20)).isoformat()
    d = {"lastStatusTimestamp": stamp, "docketCases": [case(1), case(2), case(3, gak="3/2026")]}
    r = analyze(d, "3/2026", stuck_minutes=20, now=NOW)
    assert r["started"] is False and r["stuck"] is False and r["remaining_ahead"] == 2


# --- rate limiter / auth ---------------------------------------------------------------
def test_rate_limit_blocks_after_limit_and_is_per_key():
    server._hits.clear()
    for _ in range(3):
        server.rate_limit("k1", 3, 60)
    with pytest.raises(HTTPException) as e:
        server.rate_limit("k1", 3, 60)
    assert e.value.status_code == 429
    server.rate_limit("k2", 3, 60)


def test_malformed_token_subject_is_401_not_500():
    import jwt

    class Req:
        headers = {"Authorization": "Bearer " + jwt.encode({"sub": "not-an-objectid"}, "test-secret", algorithm="HS256")}
        cookies = {}

    with pytest.raises(HTTPException) as e:
        run(server.get_current_user(Req()))
    assert e.value.status_code == 401


# --- privacy in shared groups ----------------------------------------------------------
def test_group_members_do_not_see_each_others_contacts():
    tc = {"user_id": "u1", "notify_email": "a@b.gr", "phone": "+306900000000",
          "notify_channels": ["sms"], "pending_alerts": [1], "case_number": "1/2026"}
    other = server.public_case(dict(tc), "u2")
    assert "notify_email" not in other and "phone" not in other and "pending_alerts" not in other
    mine = server.public_case(dict(tc), "u1")
    assert mine["notify_email"] == "a@b.gr" and "pending_alerts" not in mine


# --- e-diki reads: matching across dockets + shared cache ------------------------------
class FakeEdiki:
    def __init__(self, dockets):
        self.dockets = dockets
        self.calls = []

    async def get(self, path, params):
        self.calls.append(dict(params))
        await asyncio.sleep(0)
        if "id" in params:
            return {"content": [self.dockets[params["id"]]]}
        return {"content": [{"id": k} for k in self.dockets], "last": True, "totalPages": 1}


TC = {"court_type": "Πολιτικό", "court_name": "Σύρος", "court_date": "2026-10-05", "case_number": "12"}


def _use(monkeypatch, fake):
    server._shared.clear()
    server._inflight.clear()
    monkeypatch.setattr(server, "ediki_get", fake.get)


def test_case_number_in_later_docket_beats_serial_in_earlier_one(monkeypatch):
    fake = FakeEdiki({
        "a": {"id": "a", "docketCases": [case(12, gak="999/2026")]},          # Α/Α 12 only
        "b": {"id": "b", "docketCases": [case(3, gak="12")]},                 # real ΓΑΚ 12
    })
    _use(monkeypatch, fake)
    r = run(server.resolve_case(dict(TC)))
    assert r["matched"] and r["docket_id"] == "b"


def test_serial_match_used_when_no_case_number_matches(monkeypatch):
    fake = FakeEdiki({"a": {"id": "a", "docketCases": [case(12, gak="999/2026")]}})
    _use(monkeypatch, fake)
    assert run(server.resolve_case(dict(TC)))["docket_id"] == "a"


def test_parallel_cases_share_docket_reads(monkeypatch):
    fake = FakeEdiki({"a": {"id": "a", "docketCases": [case(1, gak="1/2026"), case(2, gak="2/2026")]}})
    _use(monkeypatch, fake)

    async def go():
        return await asyncio.gather(*(server.resolve_case({**TC, "case_number": f"{i}/2026"}) for i in (1, 2, 1, 2)))

    res = run(go())
    assert all(r["matched"] for r in res)
    assert len(fake.calls) == 2          # one listing + one docket, not 8


def test_failed_read_is_not_cached(monkeypatch):
    calls = []

    async def flaky(path, params):
        calls.append(1)
        return None if len(calls) == 1 else {"ok": True}

    server._shared.clear()
    monkeypatch.setattr(server, "ediki_get", flaky)
    assert run(server.ediki_get_shared("/x", {})) is None
    assert run(server.ediki_get_shared("/x", {})) == {"ok": True}


# --- alert delivery + retry ------------------------------------------------------------
class Cases:
    def __init__(self, docs):
        self.docs = docs

    @staticmethod
    def _m(d, q):
        for k, v in q.items():
            if isinstance(v, dict):
                if "$lt" in v and not d.get(k, "") < v["$lt"]:
                    return False
                if "$lte" in v and not d.get(k, "") <= v["$lte"]:
                    return False
            elif d.get(k) != v:
                return False
        return True

    async def find_one(self, q):
        return next((dict(d) for d in self.docs if self._m(d, q)), None)

    async def update_one(self, q, upd):
        for d in self.docs:
            if self._m(d, q):
                d.update(upd["$set"])
                return

    async def update_many(self, q, upd):
        for d in self.docs:
            if self._m(d, q):
                d.update(upd["$set"])

    def find(self, q):
        outer = self

        class C:
            async def to_list(self, n):
                return [dict(d) for d in outer.docs if outer._m(d, q)]
        return C()


class Notes:
    def __init__(self):
        self.docs = []

    async def insert_one(self, d):
        self.docs.append(d)


class DB:
    def __init__(self, docs):
        self.tracked_cases, self.notifications = Cases(docs), Notes()


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
    alert = ("Πλησιάζει", ["x"], "short", True)
    run(server._emit(dict(doc), [], [alert]))                       # fails -> queued
    assert len(doc["pending_alerts"]) == 1
    run(server._emit(dict(doc), [], []))                            # retry fails again
    assert doc["pending_alerts"][0]["tries"] == 2
    run(server._emit(dict(doc), [], []))                            # retry succeeds
    assert doc["pending_alerts"] == [] and len(sent) == 3
    assert db.notifications.docs == []                              # retries never duplicate in-app notes


def test_alert_retry_gives_up_after_max_tries(monkeypatch):
    doc = {"id": "c1", "user_id": "u1", "case_number": "1/2026"}
    monkeypatch.setattr(server, "db", DB([doc]))

    async def dispatch(*a, **k):
        return False

    monkeypatch.setattr(server, "dispatch_alert", dispatch)
    run(server._emit(dict(doc), [], [("t", ["x"], "s", True)]))
    for _ in range(5):
        run(server._emit(dict(doc), [], []))
    assert doc["pending_alerts"] == []


def test_dispatch_with_nothing_configured_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(server, "EMAIL_KEY", None)
    monkeypatch.setattr(server, "_twilio_client", None)
    tc = {"notify_channels": ["email", "sms"], "notify_email": "a@b.gr", "phone": "+306900000000"}
    assert run(server.dispatch_alert(tc, "s", ["l"], "short")) is True


def test_dispatch_reports_failure_when_email_send_fails(monkeypatch):
    monkeypatch.setattr(server, "EMAIL_KEY", "k")

    async def boom(**kw):
        return None

    monkeypatch.setattr(server, "send_email", boom)
    tc = {"notify_channels": ["email"], "notify_email": "a@b.gr"}
    assert run(server.dispatch_alert(tc, "s", ["l"], "short")) is False


# --- monitor round ---------------------------------------------------------------------
def test_monitor_skips_future_cases_and_retires_past_ones(monkeypatch):
    today = datetime.now(server.ATHENS).date()
    docs = [
        {"id": "past", "active": True, "court_date": (today - timedelta(days=1)).isoformat()},
        {"id": "today", "active": True, "court_date": today.isoformat()},
        {"id": "future", "active": True, "court_date": (today + timedelta(days=3)).isoformat()},
    ]
    monkeypatch.setattr(server, "db", DB(docs))
    checked = []

    async def fake_eval(tc):
        checked.append(tc["id"])

    monkeypatch.setattr(server, "evaluate_case", fake_eval)
    run(server.monitor_once())
    assert checked == ["today"]
    by = {d["id"]: d for d in docs}
    assert by["past"]["active"] is False and by["past"]["ended_reason"] == "expired"
    assert by["future"]["active"] is True


def test_monitor_runs_cases_in_parallel_within_limit(monkeypatch):
    today = datetime.now(server.ATHENS).date().isoformat()
    docs = [{"id": f"c{i}", "active": True, "court_date": today} for i in range(12)]
    monkeypatch.setattr(server, "db", DB(docs))
    state = {"now": 0, "peak": 0}

    async def fake_eval(tc):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1

    monkeypatch.setattr(server, "evaluate_case", fake_eval)
    run(server.monitor_once())
    assert 1 < state["peak"] <= server.MONITOR_CONCURRENCY


def test_one_failing_case_does_not_stop_the_round(monkeypatch):
    today = datetime.now(server.ATHENS).date().isoformat()
    docs = [{"id": "bad", "active": True, "court_date": today}, {"id": "good", "active": True, "court_date": today}]
    monkeypatch.setattr(server, "db", DB(docs))
    done = []

    async def fake_eval(tc):
        if tc["id"] == "bad":
            raise RuntimeError("boom")
        done.append(tc["id"])

    monkeypatch.setattr(server, "evaluate_case", fake_eval)
    run(server.monitor_once())
    assert done == ["good"]


# --- notifications only on the hearing day ---------------------------------------------
def test_no_approaching_or_stuck_alert_before_court_day(monkeypatch):
    from test_server_logic import run_checks, base_doc, live
    doc = base_doc(court_date="2999-01-01", remaining_ahead=8)
    fake, sent = run_checks(monkeypatch, doc, [live(2, stuck=True)])
    types = [n["type"] for n in fake.notifications.docs]
    assert "approaching" not in types and "stuck" not in types and sent == []
