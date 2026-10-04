# Deployment

e-dikiΜου = FastAPI backend + MongoDB + React frontend (built to static files).

## 1. Before going live

| Item | How |
|---|---|
| Database | A MongoDB reachable from the backend (`MONGO_URL`, `DB_NAME`). Indexes are created on first start. |
| Secrets | Set `JWT_SECRET` (≥ 32 random chars). Never commit a real `.env`; see `backend/.env.example`. |
| Email | `EMERGENT_EMAIL_KEY` – required for email alerts **and** for verification codes sent by email. |
| SMS / calls | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`. Without them the SMS/call options are disabled. A Twilio trial account only reaches verified numbers; Greek calls use the `Google.el-GR-Standard-A` voice, which should be tested with one real call. |
| Frontend | `REACT_APP_BACKEND_URL` = public URL of the backend (no `/api`), set **at build time**. |
| CORS | `CORS_ORIGINS` = the site's origin(s). |
| Proxy | Behind a reverse proxy that overwrites `X-Forwarded-For`, set `TRUST_PROXY=1`; otherwise every user shares one IP for rate limiting. |

## 2. Run

```bash
# backend (from backend/)
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001          # health: GET /api/health

# frontend (from frontend/)
yarn install && yarn build                             # serve build/ as static files
```

Several backend workers/instances are fine: a lease in MongoDB (`locks` collection) makes exactly one of them run the
monitor; if it dies another takes over within ~6 minutes (3 × `MONITOR_INTERVAL_SECONDS`), or immediately on a clean shutdown.

## 3. Smoke test after deploy

1. `GET /api/health` → `{"status":"ok"}`.
2. Register, add a case: the court list must include courts such as Πρωτοδικείο Σύρου / Φλώρινας (loaded live from e-diki).
3. Verify an email (code arrives), add a case for today's docket: status, `σειρά` and "υποθέσεις μπροστά" appear.
4. Check the logs for `monitor tick: N cases in M docket queries` every `MONITOR_INTERVAL_SECONDS`.
5. If e-diki answers 429/403 to the server, lower `EDIKI_CONCURRENCY` or raise `MONITOR_INTERVAL_SECONDS`.

## 4. Operational notes

- Existing cases whose email/phone was never verified keep in-app notifications; email/SMS/call are paused until the
  owner verifies them from the dashboard banner ("Επαλήθευση").
- Cases are retired automatically the day after the hearing; hearings on a later day are re-checked every 30 minutes.
- Back up MongoDB (users, cases, verified contacts). Notifications and `auth_attempts` are disposable.

## 5. Tests

```bash
pip install -r backend/requirements.txt
python -m pytest tests -n 0 -q -c /dev/null     # 97 tests incl. an HTTP smoke test on an in-memory MongoDB
```
