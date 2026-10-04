"""Pure docket-analysis logic (no I/O) so it can be unit-tested in isolation."""
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

# Statuses (as returned by norm_status) in which a case with a lower serial number
# may still be called before ours.
STILL_AHEAD = ("anamenetai", "diakopike")
FINISHED = ("oloklirothike", "anavlithike")

# Fields compared against the number the user typed, strongest identifiers first.
# serialNumber (Α/Α) is only used when none of the others match, so that a short
# serial like "12" can never hijack a case-number lookup.
_PRIMARY_FIELDS = ("gak", "eak", "abm", "code", "subCode")
_SERIAL_FIELDS = ("serialNumber",)


def norm_status(status, end_reason, result):
    if status in ("CASE_START", "CASE_RESUME"):
        return ("dikazetai", "Δικάζεται")
    if status == "CASE_PAUSE":
        return ("diakopike", "Διακόπηκε")
    if status == "CASE_END":
        rl = ((result or "") + " " + (end_reason or "")).lower()
        if "αναβ" in rl or "postpon" in rl:
            return ("anavlithike", "Αναβλήθηκε")
        if end_reason == "CASE_END_WITHOUT_PRONUNCIATION":
            return ("oloklirothike", "Ολοκληρώθηκε (χωρίς εκφώνηση)")
        return ("oloklirothike", "Ολοκληρώθηκε")
    return ("anamenetai", "Αναμένεται")


def case_state(case: dict):
    return norm_status(case.get("status"), case.get("endReason"), case.get("result"))


def serial_key(s) -> tuple:
    """Sortable key for a serial number. '5' -> (5,), '5-1' -> (5, 1), junk -> sorts last."""
    nums = re.findall(r"\d+", str(s if s is not None else ""))
    return tuple(int(n) for n in nums) if nums else (10 ** 9,)


def _clean(x) -> str:
    return re.sub(r"\s+", "", str(x if x is not None else "")).lower()


def case_number_matches(entered: str, case: dict, fields=_PRIMARY_FIELDS + _SERIAL_FIELDS) -> bool:
    """Exact (whitespace/case-insensitive) match against the given identifier fields."""
    e = _clean(entered)
    if not e:
        return False
    return any(_clean(case.get(f)) == e for f in fields)


def find_case(cases: list, entered: str) -> Optional[dict]:
    """Case-number fields win over the Α/Α serial; first exact match in docket order."""
    for fields in (_PRIMARY_FIELDS, _SERIAL_FIELDS):
        for c in cases:
            if case_number_matches(entered, c, fields):
                return c
    return None


def case_subject(case: dict, docket: dict) -> str:
    parts = []
    if case.get("description"):
        parts.append(str(case["description"]))
    if case.get("subCode"):
        parts.append(f"Αντικείμενο {case['subCode']}")
    kind = docket.get("courtKind") or ""
    cat = docket.get("courtCategory") or ""
    tail = " / ".join([p for p in (kind, cat) if p])
    if tail:
        parts.append(tail)
    return " · ".join(parts) if parts else (kind or "—")


def max_ts(docket: dict):
    ts = []
    for v in [docket.get("lastStatusTimestamp")] + [c.get("lastStatusTimestamp") for c in (docket.get("docketCases") or [])]:
        if v:
            try:
                d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
                ts.append(d if d.tzinfo else d.replace(tzinfo=timezone.utc))
            except Exception:
                pass
    return max(ts) if ts else None


def analyze(docket: dict, entered_number: str, stuck_minutes: int = 20, now: Optional[datetime] = None) -> Optional[dict]:
    """Locate the user's case in a docket and work out how far away its turn is.

    remaining_ahead counts every case with a lower serial that may still be called:
    waiting ones and paused/held ones ("Διακόπηκε"), e.g. a colleague asked for the case
    to be kept until a document arrives. Postponed and completed cases are excluded.
    """
    cases = docket.get("docketCases") or []
    target = find_case(cases, entered_number)
    if target is None:
        return None
    my_key = serial_key(target.get("serialNumber"))
    tkey, tlabel = case_state(target)

    waiting_ahead = paused_ahead = finished_ahead = postponed_ahead = 0
    completed = 0
    now_hearing = None
    any_started = False
    for c in cases:
        k, _ = case_state(c)
        sk = serial_key(c.get("serialNumber"))
        if k != "anamenetai":
            any_started = True
        if k in FINISHED:
            completed += 1
        if sk < my_key:
            if k == "anamenetai":
                waiting_ahead += 1
            elif k == "diakopike":
                paused_ahead += 1
            elif k == "oloklirothike":
                finished_ahead += 1
            elif k == "anavlithike":
                postponed_ahead += 1
        if k == "dikazetai":
            if now_hearing is None or sk > serial_key(now_hearing.get("serialNumber")):
                now_hearing = c

    remaining = waiting_ahead + paused_ahead
    last_update = max_ts(docket)
    started = last_update is not None or any_started
    now = now or datetime.now(timezone.utc)
    stuck = bool(started and tkey in STILL_AHEAD and remaining > 0 and last_update is not None
                 and now - last_update > timedelta(minutes=stuck_minutes))

    return {
        "matched": True,
        "docket_id": docket.get("id"),
        "docket_code": docket.get("code"),
        "building": docket.get("building"),
        "room": docket.get("room"),
        "court_name": docket.get("courtName"),
        "court_kind": docket.get("courtKind"),
        "court_category": docket.get("courtCategory"),
        "target_serial": target.get("serialNumber"),
        "my_subject": case_subject(target, docket),
        "status_key": tkey,
        "status_label": tlabel,
        "remaining_ahead": remaining,
        "paused_ahead": paused_ahead,
        "finished_ahead": finished_ahead,
        "postponed_ahead": postponed_ahead,
        "completed_count": completed,
        "total_cases": len(cases),
        "now_hearing_serial": now_hearing.get("serialNumber") if now_hearing else None,
        "now_hearing_subject": case_subject(now_hearing, docket) if now_hearing else None,
        "started": started,
        "stuck": stuck,
        "docket_last_update": last_update.isoformat() if last_update else None,
    }
