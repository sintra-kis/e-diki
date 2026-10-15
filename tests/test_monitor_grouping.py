import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import server  # noqa: E402
from tests.fakes import Col  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def today():
    return datetime.now(server.ATHENS).date().isoformat()


def day(offset):
    return (datetime.now(server.ATHENS).date() + timedelta(days=offset)).isoformat()


class DB:
    def __init__(self):
        self.tracked_cases = Col()
        self.notifications = Col()


class FakeEdiki:
    """Records every request; serves dockets of 3 cases each."""

    def __init__(self, pages=1, fail_ids=(), fail_listing=False, delay=0.0):
        self.calls, self.pages, self.fail_ids, self.fail_listing, self.delay = [], pages, set(fail_ids), fail_listing, delay
        self.in_flight = self.max_in_flight = 0

    async def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if "id" in params:
                if params["id"] in self.fail_ids:
                    return None
                n = params["id"]
                return {"content": [{"id": n, "docketCases": [
                    {"serialNumber": "1", "gak": f"{n}-a/2026", "status": "CASE_END"},
                    {"serialNumber": "2", "gak": f"{n}-b/2026"},
                    {"serialNumber": "3", "gak": f"{n}-c/2026"}]}]}
            if self.fail_listing:
                return None
            page = params.get("page", 0)
            size = params["size"]
            ids = [f"p{page}d{i}" for i in range(size if page + 1 < self.pages else 3)]
            return {"content": [{"id": i} for i in ids], "totalPages": self.pages}
        finally:
            self.in_flight -= 1

    def listings(self):
        return [c for c in self.calls if "id" not in c[1]]

    def details(self):
        return [c for c in self.calls if "id" in c[1]]


@pytest.fixture
def env(monkeypatch):
    db, sent = DB(), []

    async def dispatch(tc, subject, lines, short, voice=True):
        sent.append(subject)

    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "dispatch_alert", dispatch)
    for name in ("_docket_cache", "_docket_locks", "_case_locks"):
        monkeypatch.setattr(server, name, {})
    monkeypatch.setattr(server, "_ediki_sem", None)
    return db, sent


def add_case(db, i, date=None, court="Σύρος", number=None, **kw):
    db.tracked_cases.docs.append({
        "id": f"c{i}", "user_id": f"u{i}", "active": True, "court_type": "Πολιτικό", "court_name": court,
        "court_kind": None, "court_category": None, "court_date": date or today(),
        "case_number": number or "p0d0-c/2026", "threshold": 5, **kw})


def doc(db, i):
    return next(d for d in db.tracked_cases.docs if d["id"] == f"c{i}")


# --- one fetch per court query -------------------------------------------------------------
def test_many_cases_on_same_hearing_cost_one_fetch(env, monkeypatch):
    db, _ = env
    ed = FakeEdiki()
    monkeypatch.setattr(server, "ediki_get", ed)
    for i in range(10):
        add_case(db, i)
    stats = run(server.monitor_tick())
    assert stats == {"cases": 10, "groups": 1}
    assert len(ed.listings()) == 1 and len(ed.details()) == 3
    assert all(doc(db, i)["matched"] is True for i in range(10))


def test_different_hearings_are_separate_groups(env, monkeypatch):
    db, _ = env
    ed = FakeEdiki()
    monkeypatch.setattr(server, "ediki_get", ed)
    add_case(db, 1, court="Σύρος")
    add_case(db, 2, court="Φλώρινα")
    add_case(db, 3, court="Σύρος")
    assert run(server.monitor_tick())["groups"] == 2
    assert len(ed.listings()) == 2


def test_call_count_independent_of_number_of_cases(env, monkeypatch):
    db, _ = env
    ed = FakeEdiki()
    monkeypatch.setattr(server, "ediki_get", ed)
    for i in range(50):
        add_case(db, i, court=f"Court {i % 4}")
    run(server.monitor_tick())
    assert len(ed.listings()) == 4 and len(ed.details()) == 12   # 4 hearings, not 50 cases


# --- pagination ----------------------------------------------------------------------------
def test_all_pages_are_read(env, monkeypatch):
    db, _ = env
    ed = FakeEdiki(pages=3)
    monkeypatch.setattr(server, "ediki_get", ed)
    res = run(server.get_dockets({"court_type": "x", "court_name": "y", "court_date": today()}))
    assert len(ed.listings()) == 3 and len(res.dockets) == server.DOCKET_PAGE_SIZE * 2 + 3


# --- cache ---------------------------------------------------------------------------------
def test_cache_shares_result_with_manual_refresh_then_expires(env, monkeypatch):
    db, _ = env
    ed = FakeEdiki()
    monkeypatch.setattr(server, "ediki_get", ed)
    tc = {"court_type": "x", "court_name": "y", "court_date": today()}
    run(server.get_dockets(tc))
    run(server.get_dockets(tc))
    assert len(ed.listings()) == 1
    run(server.get_dockets(tc, force=True))
    assert len(ed.listings()) == 2
    server._docket_cache[server.group_key(tc)] = (0, server._docket_cache[server.group_key(tc)][1])
    run(server.get_dockets(tc))
    assert len(ed.listings()) == 3


def test_failures_are_not_cached(env, monkeypatch):
    db, _ = env
    ed = FakeEdiki(fail_listing=True)
    monkeypatch.setattr(server, "ediki_get", ed)
    tc = {"court_type": "x", "court_name": "y", "court_date": today()}
    assert run(server.get_dockets(tc)).ok is False
    ed.fail_listing = False
    assert run(server.get_dockets(tc)).ok is True


def test_concurrent_callers_share_one_in_flight_fetch(env, monkeypatch):
    db, _ = env
    ed = FakeEdiki(delay=0.01)
    monkeypatch.setattr(server, "ediki_get", ed)
    tc = {"court_type": "x", "court_name": "y", "court_date": today()}

    async def many():
        return await asyncio.gather(*(server.get_dockets(tc) for _ in range(8)))
    run(many())
    assert len(ed.listings()) == 1


# --- outage handling -------------------------------------------------------------------------
def test_listing_failure_marks_every_case_in_group_feed_down(env, monkeypatch):
    db, _ = env
    monkeypatch.setattr(server, "ediki_get", FakeEdiki(fail_listing=True))
    for i in range(3):
        add_case(db, i)
    run(server.monitor_tick())
    assert all(doc(db, i)["feed_ok"] is False and doc(db, i)["feed_fail_count"] == 1 for i in range(3))


def test_partial_failure_without_match_is_not_reported_as_not_found(env, monkeypatch):
    db, _ = env
    monkeypatch.setattr(server, "ediki_get", FakeEdiki(fail_ids={"p0d1"}))
    add_case(db, 1, number="nowhere/2026")
    run(server.monitor_tick())
    assert doc(db, 1)["feed_ok"] is False          # unreadable docket: a miss proves nothing


def test_partial_failure_with_a_match_still_works(env, monkeypatch):
    db, _ = env
    monkeypatch.setattr(server, "ediki_get", FakeEdiki(fail_ids={"p0d1"}))
    add_case(db, 1, number="p0d0-c/2026")
    run(server.monitor_tick())
    assert doc(db, 1)["feed_ok"] is True and doc(db, 1)["matched"] is True


# --- scheduling rules ------------------------------------------------------------------------
def test_past_hearings_are_retired_not_polled(env, monkeypatch):
    db, _ = env
    ed = FakeEdiki()
    monkeypatch.setattr(server, "ediki_get", ed)
    add_case(db, 1, date=day(-1))
    assert run(server.monitor_tick()) == {"cases": 0, "groups": 0}
    assert doc(db, 1)["active"] is False and doc(db, 1)["expired"] is True and ed.calls == []


def test_future_hearings_are_checked_rarely(env, monkeypatch):
    db, _ = env
    ed = FakeEdiki()
    monkeypatch.setattr(server, "ediki_get", ed)
    recent = datetime.now(timezone.utc).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(minutes=server.FUTURE_CHECK_MINUTES + 1)).isoformat()
    add_case(db, 1, date=day(3), last_checked=recent)
    add_case(db, 2, date=day(3), last_checked=stale, court="Φλώρινα")
    add_case(db, 3, date=day(3), court="Κέρκυρα")            # never checked
    stats = run(server.monitor_tick())
    assert stats["cases"] == 2 and doc(db, 1).get("matched") is None


def test_todays_hearings_are_always_checked(env, monkeypatch):
    db, _ = env
    monkeypatch.setattr(server, "ediki_get", FakeEdiki())
    add_case(db, 1, last_checked=datetime.now(timezone.utc).isoformat())
    assert run(server.monitor_tick())["cases"] == 1


# --- isolation + limits ----------------------------------------------------------------------
def test_one_failing_case_does_not_stop_the_others(env, monkeypatch):
    db, _ = env
    monkeypatch.setattr(server, "ediki_get", FakeEdiki())
    for i in range(3):
        add_case(db, i)
    real = server._evaluate_locked

    async def flaky(tc, fetched=None):
        if tc["id"] == "c1":
            raise RuntimeError("boom")
        return await real(tc, fetched)
    monkeypatch.setattr(server, "_evaluate_locked", flaky)
    run(server.monitor_tick())
    assert doc(db, 0).get("matched") is True and doc(db, 2).get("matched") is True


def test_global_request_concurrency_is_bounded(env, monkeypatch):
    db, _ = env
    ed = FakeEdiki(delay=0.005)

    # exercise the real ediki_get so its semaphore is in play, with a fake HTTP client
    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class Client:
        async def get(self, url, params=None):
            path = url.replace(server.EDIKI_BASE, "")
            return Resp(await ed(path, params or {}))

    monkeypatch.setattr(server, "_client", lambda: Client())
    monkeypatch.setattr(server, "EDIKI_CONCURRENCY", 2)
    for i in range(12):
        add_case(db, i, court=f"Court {i}")
    run(server.monitor_tick())
    assert 1 <= ed.max_in_flight <= 2


def test_monitor_sends_each_notification_once_across_ticks(env, monkeypatch):
    db, sent = env
    monkeypatch.setattr(server, "ediki_get", FakeEdiki())
    add_case(db, 1, number="p0d0-c/2026", threshold=5)
    run(server.monitor_tick())
    server._docket_cache.clear()
    run(server.monitor_tick())
    assert [n["type"] for n in db.notifications.docs].count("approaching") == 1
