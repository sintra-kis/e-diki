# e-dikiΜου — PRD

## Problem statement
Web app "e-dikiΜου" (Greek UI) for lawyers to track court cause lists (πινάκια) from the official portal https://pinakio.e-diki.justice.gov.gr. User registers a case to monitor with: date, type, κατάστημα (courthouse), δικαστήριο (court kind), διαδικασία (category), case number and notification email. The app queries e-diki's public API, finds the case in its docket, shows live status (Αναμένεται/Δικάζεται/Διακόπηκε/Ολοκληρώθηκε/Αναβλήθηκε) and its σειρά (serial), computes how many cases remain ahead (excluding completed/postponed), detects a "stuck" docket, shows the case currently being heard + its subject, and notifies via email + in-app the moment status changes / the case approaches its turn.

## Architecture
- Backend: FastAPI (/app/backend/server.py), MongoDB (motor). JWT auth (bcrypt). httpx client proxying e-diki public API `https://pinakio.e-diki.justice.gov.gr/api/v1` (`/public/dockets`, `/public/dockets/courtNames|courtKinds|courtCategories`). asyncio background monitor loop (every MONITOR_INTERVAL_SECONDS=120s) re-evaluates each active tracked case and emits notifications. Email via Emergent managed Resend.
- Frontend: React (CRA + craco, "@/" alias), Tailwind + custom dark/gold theme, sonner toasts, lucide icons. Pages: Auth, Dashboard. Components: NowHearingBanner, CaseCard, AddCaseDialog (cascading dropdowns from live e-diki), Notifications, GroupsDialog.

## e-diki mapping (reverse-engineered)
- Κατάστημα=courtName, Δικαστήριο=courtKind, Διαδικασία=courtCategory, Τύπος=courtType(Πολιτικό/Ποινικό/Διοικητικό), σειρά=serialNumber, case number matches code/eak/gak/abm/subCode/serialNumber.
- Status: CASE_START/CASE_RESUME=Δικάζεται, CASE_PAUSE=Διακόπηκε, CASE_END=Ολοκληρώθηκε (or Αναβλήθηκε if result/endReason indicates αναβολή), null=Αναμένεται.
- remaining_ahead = count of cases with serial < mine AND status Αναμένεται (excludes completed/postponed) — handles out-of-order hearing & αναβολές.
- stuck = docket started but no status update for > STUCK_MINUTES (20) while my case still waiting.

## Implemented (2026-10-03)
- JWT register/login/me; token in localStorage Bearer.
- Live cascading dropdowns (date→κατάστημα→δικαστήριο→διαδικασία) from e-diki.
- Add/list/refresh/delete tracked cases; private per user; optional group sharing.
- Groups: create (6-char code) / join by code; group members share cases + notifications.
- Background monitor + per-case "Έλεγχος τώρα" manual refresh.
- Notifications: status change, approaching (<=threshold), progress (now-hearing changed), stuck. In-app + email (approaching/status/stuck).
- NowHearingBanner, feed-health indicator, Greek UI throughout.

## Backlog / P1
- WebSocket/SSE push for instant updates (currently 20–30s frontend polling + 120s backend monitor).
- Richer offense/subject detail via getCaseDetailsPublic where available.
- Per-case notification history view & email open tracking.
- Group management (leave group, remove member, rename).

## Monitoring (updated)
- Each pass groups active cases by court query (type, κατάστημα, δικαστήριο, διαδικασία, date): one read of e-diki per group, every case evaluated against that result; groups run concurrently, global request cap `EDIKI_CONCURRENCY` (6).
- Results are cached `DOCKET_CACHE_TTL_SECONDS` (15) so a manual refresh or a late-added case reuses a fresh read; failures are never cached.
- Past hearings are retired (`active=false, expired=true`); later-day hearings are re-checked every `FUTURE_CHECK_MINUTES` (30).
- Fixed cadence `MONITOR_INTERVAL_SECONDS` (120) measured start-to-start.
- `TRUST_PROXY=1` makes rate limiting use X-Forwarded-For (only behind a proxy that overwrites it).
