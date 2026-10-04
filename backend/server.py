from dotenv import load_dotenv
from pathlib import Path
import os

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import asyncio
import logging
import re
import uuid
import ipaddress
from datetime import datetime, timezone, timedelta
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse
from typing import Optional, List
from zoneinfo import ZoneInfo

import bcrypt
import jwt
import httpx
from bson import ObjectId
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from docket_logic import analyze

# ----------------------------------------------------------------------------
# Config / DB
# ----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("edikimou")

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = "HS256"
MONITOR_INTERVAL = int(os.environ.get('MONITOR_INTERVAL_SECONDS', '120'))
STUCK_MINUTES = int(os.environ.get('STUCK_MINUTES', '20'))

EDIKI_BASE = "https://pinakio.e-diki.justice.gov.gr/api/v1"

# Email (Emergent managed Resend)
EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "e-dikiΜου")
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")

# Twilio (SMS + voice call) - optional, enabled when credentials present
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.environ.get("TWILIO_PHONE_NUMBER")
_twilio_client = None
if TWILIO_SID and TWILIO_TOKEN:
    try:
        from twilio.rest import Client as TwilioClient
        _twilio_client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
    except Exception as e:
        logger.error(f"Twilio init failed: {e}")

app = FastAPI(title="e-dikiΜου")
api = APIRouter(prefix="/api")


# ----------------------------------------------------------------------------
# Auth helpers
# ----------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email,
               "exp": datetime.now(timezone.utc) + timedelta(days=7), "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Μη εξουσιοδοτημένη πρόσβαση")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="Ο χρήστης δεν βρέθηκε")
        user["id"] = str(user["_id"])
        user.pop("_id", None)
        user.pop("password_hash", None)
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Η συνεδρία έληξε")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Μη έγκυρο token")


# ----------------------------------------------------------------------------
# Email (guardrail gate + sender)
# ----------------------------------------------------------------------------
_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Bad URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text host mismatch (G3)")


async def send_email(*, to: str, subject: str, html: str) -> Optional[str]:
    if not EMAIL_KEY:
        logger.warning("EMERGENT_EMAIL_KEY missing; skipping email send")
        return None
    _assert_safe_email(subject, html)
    payload = {"to": [to], "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME}
    if EMAIL_REPLY_TO:
        payload["contact_email"] = EMAIL_REPLY_TO
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(f"{EMAIL_BASE_URL}/api/v1/email/send",
                                headers={"X-Email-Key": EMAIL_KEY}, json=payload)
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return None


def build_alert_html(title: str, lines: List[str]) -> str:
    rows = "".join(f'<p style="margin:6px 0;color:#334155">{escape(l)}</p>' for l in lines)
    return (
        '<table role="presentation" width="100%" style="background:#f1f5f9;padding:24px">'
        '<tr><td align="center">'
        '<table role="presentation" width="560" style="background:#ffffff;border-radius:12px;'
        'border:1px solid #e2e8f0;overflow:hidden;font-family:Arial,Helvetica,sans-serif">'
        '<tr><td style="background:#0B0F17;padding:20px 28px">'
        '<span style="color:#D4AF37;font-size:20px;font-weight:bold">e-dikiΜου</span>'
        '<span style="color:#94A3B8;font-size:12px;display:block;margin-top:4px">'
        'Παρακολούθηση Πινακίων Δικαστηρίων</span></td></tr>'
        f'<tr><td style="padding:24px 28px">'
        f'<h2 style="margin:0 0 14px;color:#0F172A;font-size:18px">{escape(title)}</h2>'
        f'{rows}</td></tr>'
        '<tr><td style="padding:16px 28px;border-top:1px solid #e2e8f0">'
        '<p style="font-size:12px;color:#94a3b8;margin:0">Αυτόματη ειδοποίηση από το e-dikiΜου. '
        'Τα δεδομένα αντλούνται από το δημόσιο πινάκιο e-diki.justice.gov.gr και ενδέχεται να μην '
        'είναι πλήρως ενημερωμένα. Δεν ζητάμε ποτέ κωδικούς μέσω email.</p>'
        '</td></tr></table></td></tr></table>'
    )


def _to_e164(phone: str) -> Optional[str]:
    if not phone:
        return None
    p = re.sub(r"[^\d+]", "", phone.strip())
    if p.startswith("+"):
        return p
    if p.startswith("00"):
        return "+" + p[2:]
    if p.startswith("0"):
        return "+30" + p[1:]  # default to Greece
    if len(p) == 10:
        return "+30" + p
    return "+" + p


def send_sms(to: str, text: str) -> bool:
    num = _to_e164(to)
    if not _twilio_client or not TWILIO_FROM or not num:
        logger.warning("SMS skipped (twilio not configured or bad number)")
        return False
    try:
        _twilio_client.messages.create(to=num, from_=TWILIO_FROM, body=text[:600])
        return True
    except Exception as e:
        logger.error(f"SMS send error: {e}")
        return False


def make_call(to: str, text: str) -> bool:
    num = _to_e164(to)
    if not _twilio_client or not TWILIO_FROM or not num:
        logger.warning("Call skipped (twilio not configured or bad number)")
        return False
    try:
        twiml = (f'<Response><Say language="el-GR" voice="Google.el-GR-Standard-A">{escape(text)}</Say>'
                 f'<Pause length="1"/><Say language="el-GR">{escape(text)}</Say></Response>')
        _twilio_client.calls.create(to=num, from_=TWILIO_FROM, twiml=twiml)
        return True
    except Exception as e:
        logger.error(f"Call error: {e}")
        return False


async def dispatch_alert(tc: dict, subject: str, lines: List[str], short_text: str, voice: bool = True):
    channels = tc.get("notify_channels") or ["email"]
    if "email" in channels and tc.get("notify_email"):
        await send_email(to=tc["notify_email"], subject=f"[e-dikiΜου] {subject}",
                         html=build_alert_html(subject, lines))
    phone = tc.get("phone")
    if phone and "sms" in channels:
        await asyncio.to_thread(send_sms, phone, f"e-dikiΜου: {short_text}")
    if phone and voice and "call" in channels:
        await asyncio.to_thread(make_call, phone, short_text)


# ----------------------------------------------------------------------------
# e-diki client + status logic
# ----------------------------------------------------------------------------
_http: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    """One shared client so connections to e-diki are reused across checks."""
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=20)
    return _http


async def ediki_get(path: str, params: dict) -> Optional[object]:
    try:
        r = await _client().get(f"{EDIKI_BASE}{path}",
                                params={k: v for k, v in params.items() if v not in (None, "")})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"e-diki fetch failed {path}: {e}")
        return None


# Dropdown options (courts, kinds, categories) change rarely; cache them briefly.
_OPTIONS_TTL = 6 * 3600
_options_cache: dict = {}


async def ediki_options(path: str, params: dict, date: Optional[str] = None) -> list:
    """Dropdown values exactly as e-diki returns them.

    The form's date filter hides courts without a docket on that day (which is why courts
    such as Σύρος or Φλώρινα went missing), so ask for the full, date-independent list first
    and fall back to the date-restricted query only if that comes back empty.
    """
    key = (path, tuple(sorted((k, v) for k, v in params.items() if v)))
    hit = _options_cache.get(key)
    if hit and hit[0] > datetime.now(timezone.utc).timestamp():
        return hit[1]
    data = await ediki_get(path, params)
    if not data and date:
        data = await ediki_get(path, {**params, "courtDateFrom": date, "courtDateTo": date})
    data = data if isinstance(data, list) else []
    if data:
        _options_cache[key] = (datetime.now(timezone.utc).timestamp() + _OPTIONS_TTL, data)
    return data


DOCKET_PAGE_SIZE = 50
DOCKET_MAX_PAGES = 10


async def resolve_case(tc: dict) -> dict:
    """Fetch live state for one tracked case. Returns dict with feed_ok + analysis fields.

    feed_ok is False whenever e-diki could not be read completely (listing or any docket
    failed and the case was not found), so a silent outage is never mistaken for
    "case not in the docket yet".
    """
    params = {
        "courtType": tc["court_type"],
        "courtName": tc["court_name"],
        "courtKind": tc.get("court_kind"),
        "courtCategory": tc.get("court_category"),
        "courtDateFrom": tc["court_date"],
        "courtDateTo": tc["court_date"],
        "size": DOCKET_PAGE_SIZE,
    }
    incomplete = False
    for page in range(DOCKET_MAX_PAGES):
        listing = await ediki_get("/public/dockets", {**params, "page": page})
        if not isinstance(listing, dict):
            return {"feed_ok": False}
        content = listing.get("content") or []
        for d in content:
            full = await ediki_get("/public/dockets", {"id": d["id"]})
            if not full or not full.get("content"):
                incomplete = True
                continue
            analysis = analyze(full["content"][0], tc["case_number"], STUCK_MINUTES)
            if analysis:
                return {"feed_ok": True, **analysis}
        total_pages = listing.get("totalPages")
        if listing.get("last") is True or len(content) < DOCKET_PAGE_SIZE or \
                (isinstance(total_pages, int) and page + 1 >= total_pages):
            break
    return {"feed_ok": not incomplete, "matched": False}


# ----------------------------------------------------------------------------
# Monitoring + notifications
# ----------------------------------------------------------------------------
async def create_notification(tc: dict, ntype: str, title: str, message: str):
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": tc["user_id"],
        "group_id": tc.get("group_id"),
        "tracked_case_id": tc["id"],
        "type": ntype,
        "title": title,
        "message": message,
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def case_tag(tc: dict) -> str:
    return f"{tc.get('case_number')} · {tc.get('court_name')}"


FEED_DOWN_AFTER = int(os.environ.get('FEED_DOWN_AFTER_CHECKS', '3'))
ATHENS = ZoneInfo("Europe/Athens")
_case_locks: dict = {}

CARRY_FIELDS = ("docket_id", "docket_code", "building", "room", "court_kind", "court_category",
                "target_serial", "my_subject", "status_key", "status_label", "remaining_ahead",
                "paused_ahead", "finished_ahead", "postponed_ahead", "completed_count", "total_cases",
                "now_hearing_serial", "now_hearing_subject", "started", "stuck", "docket_last_update")


def _venue_lines(live: dict) -> List[str]:
    return [f"Δικαστήριο: {live.get('court_name')} — {live.get('court_kind') or ''}",
            f"Κτίριο/Αίθουσα: {live.get('building') or '-'} / {live.get('room') or '-'}"]


def ahead_detail(live: dict) -> str:
    """Why the number is what it is: held-back and postponed cases are visible to the lawyer."""
    parts = [f"{live['remaining_ahead']} μπροστά σας"]
    if live.get("paused_ahead"):
        parts.append(f"εκ των οποίων {live['paused_ahead']} διακοπείσες/κρατημένες")
    if live.get("postponed_ahead"):
        parts.append(f"{live['postponed_ahead']} αναβλήθηκαν")
    if live.get("finished_ahead"):
        parts.append(f"{live['finished_ahead']} ολοκληρώθηκαν")
    return ", ".join(parts)


def _is_court_day(tc: dict) -> bool:
    return tc.get("court_date") == datetime.now(ATHENS).date().isoformat()


async def evaluate_case(tc: dict):
    """Serialise checks per case (monitor loop vs. manual refresh) and work on fresh data,
    so one change never produces two notifications."""
    lock = _case_locks.setdefault(tc["id"], asyncio.Lock())
    async with lock:
        fresh = await db.tracked_cases.find_one({"id": tc["id"]})
        if fresh:
            await _evaluate_locked(fresh)


async def _evaluate_locked(tc: dict):
    live = await resolve_case(tc)
    now_iso = datetime.now(timezone.utc).isoformat()
    update = {"last_checked": now_iso, "feed_ok": live.get("feed_ok", False)}
    notes = []
    alerts = []

    # --- e-diki unreachable: never fail silently on the day of the hearing -------------
    if not live.get("feed_ok"):
        fails = (tc.get("feed_fail_count") or 0) + 1
        update["feed_fail_count"] = fails
        if (fails >= FEED_DOWN_AFTER and not tc.get("notified_feed_down") and _is_court_day(tc)
                and tc.get("status_key") not in ("oloklirothike", "anavlithike")):
            title = "Το e-diki δεν ανταποκρίνεται"
            msg = (f"Δεν μπορούμε να διαβάσουμε το πινάκιο εδώ και {fails} συνεχόμενους ελέγχους "
                   f"({case_tag(tc)}). Μέχρι να αποκατασταθεί δεν θα λαμβάνετε ενημερώσεις· "
                   f"παρακολουθήστε το πινάκιο χειροκίνητα.")
            notes.append(("feed_down", title, msg))
            alerts.append((title, [msg], f"Προσοχή: το e-diki δεν ανταποκρίνεται. Παρακολουθήστε το πινάκιο "
                                         f"χειροκίνητα για την υπόθεση {tc.get('case_number')}.", True))
            update["notified_feed_down"] = True
        await db.tracked_cases.update_one({"id": tc["id"]}, {"$set": update})
        await _emit(tc, notes, alerts)
        return

    update["feed_fail_count"] = 0
    if tc.get("notified_feed_down"):
        notes.append(("feed_restored", "Το e-diki ανταποκρίνεται ξανά",
                      f"Η παρακολούθηση της υπόθεσης {case_tag(tc)} συνεχίζεται κανονικά."))
        update["notified_feed_down"] = False

    update["matched"] = live.get("matched", False)
    if not live.get("matched"):
        await db.tracked_cases.update_one({"id": tc["id"]}, {"$set": update})
        await _emit(tc, notes, alerts)
        return

    for f in CARRY_FIELDS:
        update[f] = live.get(f)

    threshold = tc.get("threshold", 5)
    remaining = live["remaining_ahead"]
    waiting = live["status_key"] in ("anamenetai", "diakopike")

    # 1. status change of my case
    prev_status = tc.get("status_key")
    if prev_status and prev_status != live["status_key"]:
        title = f"Αλλαγή κατάστασης: {live['status_label']}"
        msg = f"Η υπόθεση {case_tag(tc)} (σειρά #{live.get('target_serial')}) είναι πλέον: {live['status_label']}."
        notes.append(("status_change", title, msg))
        if live["status_key"] in ("dikazetai", "oloklirothike", "anavlithike"):
            alerts.append((title, [msg, *_venue_lines(live)],
                           f"Η υπόθεση {tc.get('case_number')} είναι πλέον: {live['status_label']}.", True))

    # 2. approaching its turn (first time within the threshold)
    if waiting and live.get("started") and remaining <= threshold and not tc.get("notified_approaching"):
        title = "Η υπόθεσή σας πλησιάζει!"
        msg = (f"Απομένουν {remaining} υποθέσεις πριν από τη δική σας "
               f"({case_tag(tc)}, σειρά #{live.get('target_serial')}). "
               f"Τώρα δικάζεται η σειρά #{live.get('now_hearing_serial') or '—'}. ({ahead_detail(live)})")
        notes.append(("approaching", title, msg))
        alerts.append((title, [msg, *_venue_lines(live)],
                       f"Προσοχή! Απομένουν {remaining} υποθέσεις πριν από τη δική σας, "
                       f"αριθμός {tc.get('case_number')}, σειρά {live.get('target_serial')}.", True))
        update["notified_approaching"] = True
    elif (waiting and live.get("started") and tc.get("notified_approaching") and remaining <= threshold
          and tc.get("remaining_ahead") is not None and remaining != tc.get("remaining_ahead")):
        # 2b. already inside the threshold: tell the lawyer every time the count moves
        # (a case finished, was postponed, or a held-back case came back).
        title = f"Απομένουν {remaining} υποθέσεις"
        msg = (f"Η υπόθεσή σας {case_tag(tc)} (σειρά #{live.get('target_serial')}): "
               f"από {tc.get('remaining_ahead')} → {remaining} υποθέσεις μπροστά. ({ahead_detail(live)})")
        notes.append(("progress", title, msg))
        alerts.append((title, [msg, *_venue_lines(live)],
                       f"Υπόθεση {tc.get('case_number')}: απομένουν {remaining} μπροστά σας.", False))
    if remaining > threshold:
        update["notified_approaching"] = False

    # 3. now-hearing serial changed (in-app only)
    if (live.get("now_hearing_serial") and live.get("now_hearing_serial") != tc.get("now_hearing_serial")
            and live.get("started") and not any(n[0] == "progress" for n in notes)):
        notes.append(("progress", "Πρόοδος πινακίου",
                      f"Τώρα δικάζεται η σειρά #{live['now_hearing_serial']}"
                      f"{(' — ' + live['now_hearing_subject']) if live.get('now_hearing_subject') else ''}. "
                      f"Για την υπόθεσή σας (#{live.get('target_serial')}): {ahead_detail(live)}."))

    # 4. stuck docket
    if live.get("stuck") and not tc.get("notified_stuck"):
        title = "Προσοχή: το πινάκιο φαίνεται στάσιμο"
        msg = (f"Το πινάκιο {live.get('docket_code') or ''} στο {live.get('court_name')} δεν έχει "
               f"ενημερωθεί για πάνω από {STUCK_MINUTES} λεπτά, ενώ η υπόθεσή σας "
               f"({case_tag(tc)}) αναμένεται ακόμη. Ελέγξτε χειροκίνητα.")
        notes.append(("stuck", title, msg))
        alerts.append((title, [msg],
                       f"Προσοχή: το πινάκιο στο {live.get('court_name')} φαίνεται στάσιμο "
                       f"ενώ η υπόθεσή σας αναμένεται ακόμη.", True))
        update["notified_stuck"] = True
    if not live.get("stuck"):
        update["notified_stuck"] = False

    if live["status_key"] in ("oloklirothike", "anavlithike"):
        update["active"] = False

    await db.tracked_cases.update_one({"id": tc["id"]}, {"$set": update})
    await _emit(tc, notes, alerts)


async def _emit(tc: dict, notes: list, alerts: list):
    for ntype, title, msg in notes:
        await create_notification(tc, ntype, title, msg)
    for subject, lines, short, voice in alerts:
        await dispatch_alert(tc, subject, lines, short, voice=voice)


async def monitor_loop():
    await asyncio.sleep(5)
    while True:
        try:
            cases = await db.tracked_cases.find({"active": True}).to_list(1000)
            for tc in cases:
                try:
                    await evaluate_case(tc)
                except Exception as e:
                    logger.error(f"evaluate_case error {tc.get('id')}: {e}")
        except Exception as e:
            logger.error(f"monitor loop error: {e}")
        await asyncio.sleep(MONITOR_INTERVAL)


# ----------------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------------
class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


CHANNELS = ("email", "sms", "call")


class TrackIn(BaseModel):
    court_type: str
    court_name: str
    court_kind: Optional[str] = None
    court_category: Optional[str] = None
    court_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    case_number: str = Field(min_length=1, max_length=64)
    notify_email: Optional[EmailStr] = None
    notify_channels: List[str] = ["email"]
    phone: Optional[str] = None
    threshold: int = Field(default=5, ge=1, le=50)
    group_id: Optional[str] = None
    label: Optional[str] = Field(default=None, max_length=120)

    @field_validator("notify_channels")
    @classmethod
    def _channels(cls, v: List[str]) -> List[str]:
        v = list(dict.fromkeys(v or ["email"]))
        bad = [c for c in v if c not in CHANNELS]
        if bad:
            raise ValueError(f"Μη έγκυρο κανάλι ειδοποίησης: {', '.join(bad)}")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: Optional[str]) -> Optional[str]:
        if not v or not v.strip():
            return None
        num = _to_e164(v)
        if not num or not re.fullmatch(r"\+\d{8,15}", num):
            raise ValueError("Μη έγκυρος αριθμός τηλεφώνου")
        return num

    @model_validator(mode="after")
    def _channel_requirements(self):
        if "email" in self.notify_channels and not self.notify_email:
            raise ValueError("Απαιτείται email για ειδοποίηση μέσω email")
        if ({"sms", "call"} & set(self.notify_channels)) and not self.phone:
            raise ValueError("Απαιτείται αριθμός τηλεφώνου για SMS ή κλήση")
        return self


class GroupIn(BaseModel):
    name: str


class JoinGroupIn(BaseModel):
    code: str


# ----------------------------------------------------------------------------
# Auth routes
# ----------------------------------------------------------------------------
@api.post("/auth/register")
async def register(body: RegisterIn):
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Το email χρησιμοποιείται ήδη")
    doc = {"name": body.name, "email": email, "password_hash": hash_password(body.password),
           "role": "user", "group_ids": [], "created_at": datetime.now(timezone.utc).isoformat()}
    res = await db.users.insert_one(doc)
    uid = str(res.inserted_id)
    return {"access_token": create_access_token(uid, email),
            "user": {"id": uid, "name": body.name, "email": email}}


@api.post("/auth/login")
async def login(body: LoginIn):
    email = body.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Λάθος email ή κωδικός")
    uid = str(user["_id"])
    return {"access_token": create_access_token(uid, email),
            "user": {"id": uid, "name": user.get("name"), "email": email}}


@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return {"id": user["id"], "name": user.get("name"), "email": user.get("email")}


# ----------------------------------------------------------------------------
# e-diki dropdown routes (public)
# ----------------------------------------------------------------------------
@api.get("/config")
async def config():
    return {"twilio_enabled": bool(_twilio_client and TWILIO_FROM),
            "email_enabled": bool(EMAIL_KEY)}


@api.get("/ediki/court-types")
async def court_types():
    return [{"label": "Πολιτικό", "value": "Πολιτικό"},
            {"label": "Ποινικό", "value": "Ποινικό"},
            {"label": "Διοικητικό", "value": "Διοικητικό"}]


@api.get("/ediki/court-names")
async def court_names(courtType: str, date: Optional[str] = None):
    return await ediki_options("/public/dockets/courtNames", {"courtType": courtType}, date)


@api.get("/ediki/court-kinds")
async def court_kinds(courtType: str, courtName: str, date: Optional[str] = None):
    return await ediki_options("/public/dockets/courtKinds",
                               {"courtType": courtType, "courtName": courtName}, date)


@api.get("/ediki/court-categories")
async def court_categories(courtType: str, courtName: str, courtKind: Optional[str] = None, date: Optional[str] = None):
    return await ediki_options("/public/dockets/courtCategories",
                               {"courtType": courtType, "courtName": courtName, "courtKind": courtKind}, date)


# ----------------------------------------------------------------------------
# Tracked cases
# ----------------------------------------------------------------------------
def public_case(tc: dict) -> dict:
    tc.pop("_id", None)
    return tc


async def user_group_ids(user) -> List[str]:
    u = await db.users.find_one({"_id": ObjectId(user["id"])})
    return u.get("group_ids", []) if u else []


@api.post("/cases")
async def add_case(body: TrackIn, user=Depends(get_current_user)):
    if body.group_id and body.group_id not in await user_group_ids(user):
        raise HTTPException(status_code=403, detail="Δεν ανήκετε σε αυτή την ομάδα")
    tc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "group_id": body.group_id,
        "label": body.label,
        "court_type": body.court_type,
        "court_name": body.court_name,
        "court_kind": body.court_kind,
        "court_category": body.court_category,
        "court_date": body.court_date,
        "case_number": body.case_number.strip(),
        "notify_email": body.notify_email.lower() if body.notify_email else None,
        "notify_channels": body.notify_channels,
        "phone": body.phone,
        "threshold": body.threshold,
        "active": True,
        "feed_ok": None, "matched": None, "status_key": None, "status_label": None,
        "remaining_ahead": None, "now_hearing_serial": None, "now_hearing_subject": None,
        "notified_approaching": False, "notified_stuck": False,
        "notified_feed_down": False, "feed_fail_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.tracked_cases.insert_one(dict(tc))
    try:
        await evaluate_case(tc)
    except Exception as e:
        logger.error(f"initial evaluate error: {e}")
    fresh = await db.tracked_cases.find_one({"id": tc["id"]})
    return public_case(fresh)


@api.get("/cases")
async def list_cases(user=Depends(get_current_user)):
    gids = await user_group_ids(user)
    query = {"$or": [{"user_id": user["id"]}, {"group_id": {"$in": gids}}]} if gids else {"user_id": user["id"]}
    cases = await db.tracked_cases.find(query).sort("created_at", -1).to_list(1000)
    return [public_case(c) for c in cases]


async def _owned_case(case_id: str, user) -> dict:
    tc = await db.tracked_cases.find_one({"id": case_id})
    if not tc:
        raise HTTPException(status_code=404, detail="Δεν βρέθηκε")
    gids = await user_group_ids(user)
    if tc["user_id"] != user["id"] and tc.get("group_id") not in gids:
        raise HTTPException(status_code=403, detail="Δεν έχετε πρόσβαση")
    return tc


@api.post("/cases/{case_id}/refresh")
async def refresh_case(case_id: str, user=Depends(get_current_user)):
    tc = await _owned_case(case_id, user)
    await evaluate_case(tc)
    return public_case(await db.tracked_cases.find_one({"id": case_id}))


@api.delete("/cases/{case_id}")
async def delete_case(case_id: str, user=Depends(get_current_user)):
    tc = await db.tracked_cases.find_one({"id": case_id})
    if not tc:
        raise HTTPException(status_code=404, detail="Δεν βρέθηκε")
    if tc["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Μόνο ο δημιουργός μπορεί να διαγράψει")
    await db.tracked_cases.delete_one({"id": case_id})
    _case_locks.pop(case_id, None)
    await db.notifications.delete_many({"tracked_case_id": case_id})
    return {"ok": True}


# ----------------------------------------------------------------------------
# Notifications
# ----------------------------------------------------------------------------
@api.get("/notifications")
async def list_notifications(user=Depends(get_current_user)):
    gids = await user_group_ids(user)
    query = {"$or": [{"user_id": user["id"]}, {"group_id": {"$in": gids}}]} if gids else {"user_id": user["id"]}
    notes = await db.notifications.find(query).sort("created_at", -1).limit(100).to_list(100)
    for n in notes:
        n.pop("_id", None)
    return notes


@api.post("/notifications/{note_id}/read")
async def read_notification(note_id: str, user=Depends(get_current_user)):
    await db.notifications.update_one({"id": note_id}, {"$set": {"read": True}})
    return {"ok": True}


@api.post("/notifications/read-all")
async def read_all(user=Depends(get_current_user)):
    gids = await user_group_ids(user)
    query = {"$or": [{"user_id": user["id"]}, {"group_id": {"$in": gids}}]} if gids else {"user_id": user["id"]}
    await db.notifications.update_many(query, {"$set": {"read": True}})
    return {"ok": True}


# ----------------------------------------------------------------------------
# Groups
# ----------------------------------------------------------------------------
@api.post("/groups")
async def create_group(body: GroupIn, user=Depends(get_current_user)):
    code = uuid.uuid4().hex[:6].upper()
    g = {"id": str(uuid.uuid4()), "name": body.name, "code": code,
         "owner_id": user["id"], "member_ids": [user["id"]],
         "created_at": datetime.now(timezone.utc).isoformat()}
    await db.groups.insert_one(dict(g))
    await db.users.update_one({"_id": ObjectId(user["id"])}, {"$addToSet": {"group_ids": g["id"]}})
    g.pop("_id", None)
    return g


@api.post("/groups/join")
async def join_group(body: JoinGroupIn, user=Depends(get_current_user)):
    g = await db.groups.find_one({"code": body.code.upper()})
    if not g:
        raise HTTPException(status_code=404, detail="Λάθος κωδικός ομάδας")
    await db.groups.update_one({"id": g["id"]}, {"$addToSet": {"member_ids": user["id"]}})
    await db.users.update_one({"_id": ObjectId(user["id"])}, {"$addToSet": {"group_ids": g["id"]}})
    g.pop("_id", None)
    return g


@api.get("/groups")
async def list_groups(user=Depends(get_current_user)):
    gids = await user_group_ids(user)
    groups = await db.groups.find({"id": {"$in": gids}}).to_list(100)
    for g in groups:
        g.pop("_id", None)
    return groups


# ----------------------------------------------------------------------------
# Lifecycle
# ----------------------------------------------------------------------------
@api.get("/")
async def root():
    return {"app": "e-dikiΜου", "status": "ok"}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.tracked_cases.create_index("id", unique=True)
    await db.notifications.create_index("id", unique=True)
    asyncio.create_task(monitor_loop())
    logger.info("e-dikiΜου started; monitor interval=%ss", MONITOR_INTERVAL)


@app.on_event("shutdown")
async def shutdown():
    if _http is not None:
        await _http.aclose()
    client.close()
