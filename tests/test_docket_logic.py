import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from docket_logic import analyze, case_number_matches, find_case, norm_status, serial_key  # noqa: E402

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


def case(serial, status=None, **kw):
    return {"serialNumber": str(serial), "status": status, **kw}


def docket(*cases, **kw):
    return {"id": "d1", "docketCases": list(cases), **kw}


# --- case number matching ---------------------------------------------------------
def test_matching_is_exact_not_substring():
    # "1234/2025" must not match the case whose serial is "1", nor "12" match gak 4123/2025
    assert not case_number_matches("1234/2025", {"serialNumber": "1", "gak": "999/2025"})
    assert not case_number_matches("12", {"serialNumber": "7", "gak": "4123/2025"})


def test_matching_ignores_whitespace_and_case():
    assert case_number_matches("11545 / 2026", {"gak": "11545/2026"})
    assert case_number_matches("abc1", {"eak": "ABC1"})


def test_case_number_beats_serial():
    cases = [case(12, gak="1/2026"), case(5, gak="12")]
    assert find_case(cases, "12")["serialNumber"] == "5"   # gak "12", not serial 12


def test_serial_used_when_no_case_number_matches():
    cases = [case(3, gak="10/2026"), case(4, gak="11/2026")]
    assert find_case(cases, "4")["gak"] == "11/2026"


def test_no_match_returns_none():
    assert analyze(docket(case(1, gak="1/2026")), "2/2026") is None


# --- serial keys ---------------------------------------------------------------------
def test_serial_key_ordering():
    assert serial_key("5") < serial_key("12")
    assert serial_key("5") < serial_key("5-1") < serial_key("6")
    assert serial_key("abc") > serial_key("999999")


# --- statuses ------------------------------------------------------------------------
def test_norm_status():
    assert norm_status("CASE_START", None, None)[0] == "dikazetai"
    assert norm_status("CASE_RESUME", None, None)[0] == "dikazetai"
    assert norm_status("CASE_PAUSE", None, None)[0] == "diakopike"
    assert norm_status(None, None, None)[0] == "anamenetai"
    assert norm_status("CASE_END", None, "Αναβολή για 12/3")[0] == "anavlithike"
    assert norm_status("CASE_END", None, "Εκδόθηκε απόφαση")[0] == "oloklirothike"
    # "ονόματα"/"αποτελέσματα" must not read as a postponement
    assert norm_status("CASE_END", None, "Ανακοινώθηκαν τα αποτελέσματα")[0] == "oloklirothike"


# --- remaining_ahead: the lawyer's scenarios ------------------------------------------
def test_postponed_case_ahead_is_not_counted():
    # #2 being heard, #5 postponed, mine is #6 -> #3, #4 remain
    d = docket(case(1, "CASE_END"), case(2, "CASE_START"), case(3), case(4),
               case(5, "CASE_END", result="Αναβολή"), case(6, gak="6/2026"), case(7))
    r = analyze(d, "6/2026", now=NOW)
    assert r["remaining_ahead"] == 2
    assert r["postponed_ahead"] == 1 and r["finished_ahead"] == 1
    assert r["now_hearing_serial"] == "2"
    assert r["status_key"] == "anamenetai"


def test_held_back_case_still_counts_as_ahead():
    # #5 was kept (paused) for a missing document: court moved on to #6, mine is #7.
    d = docket(case(4, "CASE_END"), case(5, "CASE_PAUSE"), case(6, "CASE_START"), case(7, gak="7/2026"))
    r = analyze(d, "7/2026", now=NOW)
    assert r["remaining_ahead"] == 1 and r["paused_ahead"] == 1


def test_out_of_order_hearing_counts_by_serial_not_position():
    d = docket(case(1), case(2, "CASE_END"), case(9, "CASE_START"), case(5, gak="5/2026"))
    r = analyze(d, "5/2026", now=NOW)
    assert r["remaining_ahead"] == 1   # only #1 is still before #5


def test_my_case_being_heard():
    d = docket(case(1, "CASE_END"), case(2, "CASE_START", gak="2/2026"))
    r = analyze(d, "2/2026", now=NOW)
    assert r["status_key"] == "dikazetai" and r["remaining_ahead"] == 0


# --- stuck detection -------------------------------------------------------------------
def _stamped(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def test_stuck_when_docket_silent_too_long():
    d = docket(case(1, "CASE_END"), case(2), case(3, gak="3/2026"), lastStatusTimestamp=_stamped(45))
    assert analyze(d, "3/2026", stuck_minutes=20, now=NOW)["stuck"] is True


def test_not_stuck_when_recent_or_nothing_ahead():
    recent = docket(case(1, "CASE_END"), case(2), case(3, gak="3/2026"), lastStatusTimestamp=_stamped(5))
    assert analyze(recent, "3/2026", stuck_minutes=20, now=NOW)["stuck"] is False
    nothing_ahead = docket(case(1, "CASE_END"), case(2, "CASE_END"), case(3, gak="3/2026"),
                           lastStatusTimestamp=_stamped(90))
    assert analyze(nothing_ahead, "3/2026", stuck_minutes=20, now=NOW)["stuck"] is False


def test_stuck_when_only_a_held_case_remains_ahead():
    d = docket(case(1, "CASE_END"), case(2, "CASE_PAUSE"), case(3, gak="3/2026"), lastStatusTimestamp=_stamped(45))
    assert analyze(d, "3/2026", stuck_minutes=20, now=NOW)["stuck"] is True


def test_naive_timestamp_does_not_crash():
    d = docket(case(1), case(2, gak="2/2026"), lastStatusTimestamp="2026-10-05T09:00:00")
    assert analyze(d, "2/2026", now=NOW)["docket_last_update"] is not None


# --- description of my case (shown on the card) ----------------------------------------
def test_my_description_excludes_court_kind():
    d = docket(case(1, gak="1/2026", description="Αγωγή αποζημίωσης", subCode="123"), courtKind="Μον. Πρωτοδικείο")
    r = analyze(d, "1/2026", now=NOW)
    assert r["my_description"] == "Αγωγή αποζημίωσης · Αντικείμενο 123"
    assert "Μον. Πρωτοδικείο" in r["my_subject"]


def test_my_description_is_none_when_unknown():
    assert analyze(docket(case(1, gak="1/2026"), courtKind="Μον."), "1/2026", now=NOW)["my_description"] is None
