import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import server  # noqa: E402


def track(**kw):
    base = dict(court_type="Πολιτικό", court_name="Πρωτοδικείο Σύρου", court_date="2026-10-05",
                case_number="1/2026", notify_email="a@b.gr")
    return server.TrackIn(**{**base, **kw})


# --- notification channel validation ---------------------------------------------------
def test_email_only_default():
    assert track().notify_channels == ["email"]


def test_sms_requires_phone():
    with pytest.raises(ValidationError):
        track(notify_channels=["email", "sms"])


def test_phone_is_normalised_to_e164():
    t = track(notify_channels=["email", "call"], phone="694 123 4567")
    assert t.phone == "+306941234567"


def test_unknown_channel_rejected():
    with pytest.raises(ValidationError):
        track(notify_channels=["fax"])


def test_bad_phone_rejected():
    with pytest.raises(ValidationError):
        track(notify_channels=["sms"], phone="12")


def test_email_channel_requires_email():
    with pytest.raises(ValidationError):
        track(notify_email=None)


def test_sms_only_needs_no_email():
    t = track(notify_email=None, notify_channels=["sms"], phone="+306941234567")
    assert t.notify_channels == ["sms"]


def test_threshold_and_date_bounds():
    with pytest.raises(ValidationError):
        track(threshold=0)
    with pytest.raises(ValidationError):
        track(court_date="05/10/2026")


# --- feed-down alerting ----------------------------------------------------------------
class FakeCases:
    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, q):
        return dict(self.doc)

    async def update_one(self, q, upd):
        self.doc.update(upd["$set"])


class FakeNotes:
    def __init__(self):
        self.docs = []

    async def insert_one(self, d):
        self.docs.append(d)


class FakeDB:
    def __init__(self, doc):
        self.tracked_cases = FakeCases(doc)
        self.notifications = FakeNotes()


def run_checks(monkeypatch, doc, results):
    fake = FakeDB(doc)
    sent = []
    it = iter(results)

    async def fake_resolve(tc, fetched=None):
        return next(it)

    async def fake_dispatch(tc, subject, lines, short, voice=True):
        sent.append((subject, voice))

    monkeypatch.setattr(server, "db", fake)
    monkeypatch.setattr(server, "resolve_case", fake_resolve)
    monkeypatch.setattr(server, "dispatch_alert", fake_dispatch)
    for _ in results:
        asyncio.run(server.evaluate_case(doc))
    return fake, sent


def base_doc(**kw):
    today = datetime.now(server.ATHENS).date().isoformat()
    return {"id": "c1", "user_id": "u1", "case_number": "1/2026", "court_name": "Σύρος",
            "court_date": today, "threshold": 5, "status_key": "anamenetai", **kw}


def test_feed_down_alert_after_consecutive_failures_on_court_day(monkeypatch):
    fake, sent = run_checks(monkeypatch, base_doc(), [{"feed_ok": False}] * 4)
    types = [n["type"] for n in fake.notifications.docs]
    assert types == ["feed_down"]          # exactly once, not on every failed check
    assert len(sent) == 1
    assert fake.tracked_cases.doc["feed_fail_count"] == 4


def test_no_feed_down_alert_before_court_day(monkeypatch):
    doc = base_doc(court_date="2999-01-01")
    fake, sent = run_checks(monkeypatch, doc, [{"feed_ok": False}] * 5)
    assert fake.notifications.docs == [] and sent == []


def test_feed_restored_resets_state(monkeypatch):
    ok = {"feed_ok": True, "matched": False}
    fake, sent = run_checks(monkeypatch, base_doc(), [{"feed_ok": False}] * 3 + [ok])
    assert [n["type"] for n in fake.notifications.docs] == ["feed_down", "feed_restored"]
    assert fake.tracked_cases.doc["notified_feed_down"] is False
    assert fake.tracked_cases.doc["feed_fail_count"] == 0


# --- approaching / progress notifications ----------------------------------------------
def live(remaining, **kw):
    return {"feed_ok": True, "matched": True, "status_key": "anamenetai", "status_label": "Αναμένεται",
            "remaining_ahead": remaining, "paused_ahead": 0, "postponed_ahead": 0, "finished_ahead": 0,
            "started": True, "stuck": False, "target_serial": "9", "now_hearing_serial": "3",
            "court_name": "Σύρος", "court_kind": "Μον. Πρωτοδικείο", **kw}


def test_approaching_once_then_each_change(monkeypatch):
    doc = base_doc(remaining_ahead=8, now_hearing_serial="3")
    fake, sent = run_checks(monkeypatch, doc, [live(5), live(5), live(4), live(4), live(3)])
    types = [n["type"] for n in fake.notifications.docs]
    assert types == ["approaching", "progress", "progress"]     # 5 (first), 4, 3 - no duplicates
    # approaching is allowed to call; per-step progress updates are not
    assert [v for _, v in sent] == [True, False, False]


def test_remaining_counter_goes_back_up_when_held_case_returns(monkeypatch):
    doc = base_doc(remaining_ahead=3, notified_approaching=True, now_hearing_serial="3")
    fake, sent = run_checks(monkeypatch, doc, [live(4)])
    assert [n["type"] for n in fake.notifications.docs] == ["progress"]


def test_greek_plural_in_messages():
    assert server.remaining_phrase(1) == "Απομένει 1 υπόθεση"
    assert server.remaining_phrase(3) == "Απομένουν 3 υποθέσεις"
    assert server.remaining_phrase(0) == "Απομένουν 0 υποθέσεις"
