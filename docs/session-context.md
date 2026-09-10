# Session context — Phase 2 (auth, code-match, FTPS, photo booth, desktop agent)

Written as a handoff for a fresh chat session picking up this project.
Read `CLAUDE.md` (repo root) first for the hard constraints and stack —
this file is "what happened and why", not the rulebook.

Covers everything built across this session, in the order it happened.
Phase 1 (data model, worker pipeline, ingest/match/delivery APIs, purge
job, the original Next.js frontend) was already complete and committed
before this session started — see commits `0381b11` through `8923156`.
Everything below is `2d665fc` through `bd7e1e3` (`git log --oneline` for
the full list; 18 commits total on `main` as of this writing, no other
branches, no git remote configured).

## Quick orientation: what actually works right now

- Dashboard auth: register/login/logout, session-based, org/role-scoped.
- Three event types (`match_mode`): `face` (selfie), `code` (manual
  staff-typed bib/badge tagging), `sequential` (auto-numbered photo
  booth), plus `both` (face+code combined).
- Three ways photos get into an event, all fully supported side by side,
  none deprecated: REST upload (dashboard), FTPS (per-event credentials,
  for cameras with built-in FTP), desktop agent (folder-watcher, for
  everything else).
- A full onboarding help page at `/help/camera` covering both the agent
  and FTP paths, with a searchable camera-model selector.
- A packaged, verified-working macOS build of the desktop agent; no
  Windows build exists yet (see "Known gaps" below — this is a real,
  currently-unresolved limitation, not an oversight).

## 1. Real dashboard auth

Commits `2d665fc`, `fa98b83`.

- `bcrypt` directly (not `passlib` — confirmed incompatible with
  `bcrypt>=4.1`, see `api/app/core/security.py`'s comment).
- Bearer-token sessions in `user_sessions` (separate table from
  `Guest.session_token` because staff can have >1 concurrent session).
- `api/app/api/deps.py`: `get_current_user`, `require_org_member`,
  `require_event_access`, `require_role(*roles)`. Anti-enumeration
  pattern used everywhere in this codebase: 401 (no/bad session), 404
  (valid session, wrong org — hide existence), 403 (valid session, right
  org, wrong role — resource visibly exists, action forbidden).
- Replaced the old `GET /api/dashboard/organization`
  get-or-create-a-dev-org hack with real `POST /api/auth/register`
  (creates org + owner user together) / `login` / `logout` / `me`.
- Frontend: `web/app/login/page.tsx`, token in `localStorage` via
  `web/lib/auth.ts` (not a cookie — see `api/app/main.py`'s CORS comment
  on why bearer-in-header avoids CSRF exposure from a wildcard origin).
- `api/scripts/seed.py` now creates a real login for its seeded org
  (`--email`/`--password`, printed at the end) since there's no more
  default-org endpoint to lean on — and its default email isn't under
  `.local`, which `pydantic.EmailStr` rejects as a reserved TLD (found by
  hand: the original default literally couldn't log in).

## 2. Code-match mode

Commit `2d665fc`.

`match_mode='code'`: guest types a bib/badge code instead of a selfie.
`photo_codes` table, many-to-one (a photo can have several codes — race
photos with multiple runners in frame). Staff tag codes manually via the
moderation page. Biometric-free by design: the worker
(`api/app/workers/jobs.py`) skips face detection entirely for
`match_mode in (code, sequential)` — confirmed by hand that
`insightface`/`onnxruntime` never even get imported for these events'
photos, not just that the result is discarded.

## 3. FTPS ingest with per-event credentials

Commit `3a367d5`.

`pyftpdlib` + `TLS_FTPHandler` (`api/app/ftps/`). Custom DB-backed
authorizer (`app/ftps/authorizer.py`) validates against
`event_ftp_credentials` instead of an in-memory user table. Write-only
permissions — no LIST/RETR, matching the "no browse" spirit of
`CLAUDE.md` even though that rule is written about the REST API. A
self-signed dev cert is generated on first start
(`app/ftps/certs.py`). Credentials issued/listed/revoked through
`api/app/api/routes/ftp_credentials.py`, same auth pattern as everything
else. Docker Compose service: `ftps` (port 2121 + passive range
30000-30009 by default, see `docker-compose.yml` and `.env.example`).

**Important operational gotcha, documented in the main `README.md`:**
`api` runs with `uvicorn --reload` and picks up code changes live;
`worker` and `ftps` do **not** — they import their Python modules once at
container start and keep running old code until explicitly restarted:

```bash
docker compose restart worker ftps
```

This bit us for real once this session (a fix landed, passed every test,
worked through the dashboard, but silently didn't apply to a live FTPS
upload until the container was restarted).

## 4. Two live bugs found and fixed via real phone/browser testing

Commits `e74b9ff`, `776e208`.

- **Broken gallery thumbnails.** Presigned MinIO URLs were signed
  against `MINIO_ENDPOINT`, the docker-compose *internal* service
  hostname (`minio:9000`) — unresolvable by any real browser. Fixed by
  adding `MINIO_PUBLIC_ENDPOINT` (`app/storage/minio_client.py`'s
  `get_public_client()`), used only for presigned URLs; internal
  upload/download from inside containers still uses the internal
  endpoint. Set via `.env`'s `MINIO_PUBLIC_ENDPOINT` (this machine's LAN
  IP for phone testing).
- **QR code encoding `localhost`.** `EventCard.tsx`'s guest QR used
  `window.location.origin` — whatever host loaded the dashboard tab.
  Fixed via `NEXT_PUBLIC_SITE_URL` env override
  (`web/.env.local`), which wins over `window.location.origin` for both
  the guest URL and the FTP-credentials panel's displayed host.
- Also: the "choose a photo from your device" fallback on the guest
  selfie screen had `capture="user"` on its file input, which forces
  mobile browsers straight to the camera instead of the photo library —
  removed (`web/components/guest/SelfieCapture.tsx`).

**Environment note relevant to both fixes:** this dev machine has a
*native* Postgres already on port 5432, so docker-compose's `postgres`
runs on host port 5433 instead (`.env`'s `POSTGRES_PORT=5433`) —
internal container-to-container traffic is unaffected, only the
host-side publish port. If a fresh session's `docker compose up` fails
to bind 5432, this is why, and the fix is already in `.env`.

## 5. Sequential match mode (photo booth)

Commit `a2c5885`.

A fourth `match_mode` value: `sequential`. Staff taps "next guest"
(`POST /api/events/{id}/next-guest`, `SELECT ... FOR UPDATE` so two
rapid taps can't hand out the same number twice) between subjects at a
solo-portrait booth; `Event.current_solo_number` advances, and every
photo that lands while a number is "open" gets auto-tagged with it
(`app/services/ingest.py`) — no staff typing a code in by hand
afterward, no camera integration needed. Guests share one number for
however many shots were taken before the next tap (covers retakes) —
this grouping model (one number per *guest session*, not one number per
*photo*) was a deliberate choice the user made when asked, over the
simpler "every photo gets its own number" alternative.

Reuses the entire existing `match_mode='code'` guest-facing lookup
unchanged (same `match_by_code` endpoint, same `CodeEntry` component).
Biometric-free like code mode. Dashboard: `EventCard.tsx` shows a large
current-number display + "Next guest" button for these events.

## 6. Desktop watch-folder agent + its pairing API

Commit `d7e8003`. New top-level directory `agent/`.

**Why it exists:** camera FTP (item 3) only works for cameras with
native built-in FTP — most consumer/prosumer bodies don't have it. The
agent is the alternative: point it at a folder, anything that lands
there gets uploaded automatically. Explicitly **not** a replacement for
FTP — see item 8, the two are equally-supported paths for different
shooting styles (stationary/booth vs. moving around the venue).

### API side (`api/app/`)

- `models/agent_pairing_code.py` — 6-char code (excludes 0/O/1/I/L,
  ambiguous-character avoidance), 15-min TTL, single-use.
- `models/agent_token.py` — long-lived, event-scoped, no expiry (only
  ends via `revoked_at`). **`token_hash` is SHA-256, not bcrypt** —
  deliberate: the token is already 256 bits of `secrets.token_urlsafe`
  (nothing low-entropy to defend against precomputation the way bcrypt
  defends passwords), and every request needs a fast indexed
  equality lookup with no separate "username" to look up by first the
  way `EventFtpCredential` has.
- `api/app/api/routes/agent_pairing.py` — dashboard-side, session-
  authenticated: issue a pairing code, list/revoke agent tokens.
- `api/app/api/routes/agent.py` — agent-facing:
  - `POST /api/agent/pair` — **deliberately unauthenticated by
    session** (a photographer never has a staff login), code → token
    exchange.
  - `POST /api/agent/photos` — bearer AgentToken auth
    (`api/app/api/deps.py`'s `get_agent_event`), one file per call,
    same shared `ingest_photo()` as REST/FTPS.

### Agent side (`agent/laqta_agent/`)

Python 3.11, `tkinter` GUI (not a CLI — the users are photographers), no
local web server. Run from source:

```bash
cd agent
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate.bat
pip install -r requirements.txt
LAQTA_API_URL=http://localhost:8000 python -m laqta_agent.main
```

(`tkinter` needs `brew install python-tk@3.11` on Homebrew Python if you
hit `ModuleNotFoundError: _tkinter`.)

Key modules, in the order data flows through them:
- `stability.py` — the core correctness property. A file is only
  considered safe to upload once its size **and** mtime are identical
  across two separate checks, spaced ~1s apart by the caller (the
  checker itself holds no timers, which is what makes it trivially unit
  testable without real sleeps). This is the single most important
  piece of the whole agent: a filesystem "created" event fires the
  moment a file is *opened*, not when writing finishes.
- `watcher.py` — `watchdog`-based recursive observer feeds candidate
  paths into the stability tracker; on confirmed-stable, MD5s the file
  and hands it to the queue. Also does the startup/manual "catch-up"
  full-folder scan (`FolderWatcher.start()` calls this immediately —
  confirmed by hand that a photographer who pairs *after* already
  shooting doesn't lose those photos, see item 8's help-page content).
- `queue_db.py` — SQLite (`pending`/`uploading`/`done`/`failed`),
  survives a real restart (verified with an actual close-and-reopen, not
  just reasoned about), retries with exponential backoff, dedupes by MD5
  across different paths (not just same-path re-enqueue).
- `uploader.py` — background thread draining the queue one file at a
  time. Also runs `ApiClient.check_connectivity()` periodically while
  idle — see item 9.
- `api_client.py`, `keychain.py` (OS-native credential store via
  `keyring`), `settings.py` (non-secret local prefs, plain JSON,
  deliberately separate from the keychain), `gui.py` (pairing screen +
  status window, Arabic default — note tkinter has no real logical-RTL
  layout engine, so "Arabic mode" here means right-aligned text, not a
  mirrored window).

Tests: `agent/tests/` — pure, no network/Docker needed,
`PYTHONPATH=. python -m pytest tests/ -v`. 25 passing as of the last
commit.

## 7. Agent packaging

Commit `e72ca8d`.

- **A real macOS `.app` was built and verified** (launches standalone,
  checked both the raw build and a re-extracted zip). Hosted at
  `web/public/downloads/LaqtaAgent-macOS.zip`, linked from `/help/camera`
  and the dashboard's pairing panel.
- **No Windows `.exe` exists.** PyInstaller cannot cross-compile one
  from this macOS-only dev environment under any circumstances, and
  there's no Windows machine available here. `build_windows.bat` mirrors
  `build_macos.sh` but has never actually been run.
- `.github/workflows/build-agent.yml` is the real mechanism to produce a
  Windows build (a `windows-latest` CI runner genuinely can run
  `build_windows.bat`) — triggered by an `agent-v*` tag or manually. **It
  has never executed** — this repo has no `git remote` configured, so
  there's nowhere for it to run yet. Both download surfaces (help page,
  dashboard panel) show "not available yet" for Windows rather than a
  fake/broken link. Once this repo is pushed somewhere and the workflow
  runs, download its Windows artifact and commit it to
  `web/public/downloads/LaqtaAgent-windows.zip` (or wire the workflow to
  publish there directly).

## 8. `/help/camera` — onboarding page and the agent-vs-FTP reframe

Commits `c65cb13`, `e72ca8d`.

Bilingual (Arabic default, RTL), `web/app/help/camera/`:
- `content.ts` — all prose lives here as locale-keyed data (`Record<"ar"
  | "en", HelpContent>`), deliberately separate from `web/lib/i18n.ts`'s
  short UI-chrome strings since this is a full article.
- `cameras.json` — the searchable camera-model data
  (`{brand, model, hasBuiltInFtp, note?}`), plain JSON so it's editable
  without a code change. **Deliberately conservative**: a model is only
  marked `hasBuiltInFtp: true` with real confidence (mostly flagship/pro
  bodies) — wrongly claiming FTP support sends someone down a dead end,
  while defaulting an uncertain camera to the agent path is always at
  least workable. Needs periodic review as firmware updates add FTP to
  more bodies over time; the file's own `_comment` field says this.
- `page.tsx` — leads with a "two ways, both fully supported" overview
  (agent = stationary/booth; FTP = moving around the venue), then a
  `CameraSelector` (searches `cameras.json`, shows a verdict, an "I don't
  see my camera" fallback defaults to the agent path), then two
  **equal-weight tabs** (agent / FTP) — picking a camera switches which
  tab opens by default but never hides or disables the other one.
- `components/help/FlowDiagram.tsx` — the agent tab's two-layer-
  relationship diagram (camera → USB → tethering software → **folder** →
  agent → Laqta). Always a vertical flow, not horizontal — an earlier
  horizontal version clipped off-screen at ordinary page widths with
  full-length Arabic labels, caught live and redesigned.
- `components/help/CameraSelector.tsx` — the search had a real bug
  caught live: an exact-contiguous-substring match failed "Canon R5"
  against "Canon EOS R5" (the word "EOS" in between broke it). Fixed to
  match per-word, any order.

**The reframe** (also touches `web/components/dashboard/EventCard.tsx`,
`agent/README.md`): earlier in this session the agent was positioned as
the primary ingest path with FTP as a fallback. That framing was wrong
and has been corrected everywhere — dashboard's "Pair camera agent" and
"FTP credentials" buttons now carry equal visual weight instead of one
looking primary, and both READMEs/help content now present them as
parallel choices based on shooting style.

Vendor links (Canon EOS Utility, Nikon NX Tether, Sony Imaging Edge
Remote, Fujifilm X Acquire) go to each brand's official **root** domain
with a note on what to search for, not a deep support-article path —
deliberately, since a deep link has no way to be kept verified as still
valid over time.

## 9. Wireless tethering section + proactive no-internet detection

Commit `bd7e1e3`, most recent.

Added a wireless-tethering subsection to the agent tab of `/help/camera`
(`content.ts`'s `wireless` field), leading with a **red, most-prominent**
warning: don't use the camera's own Wi-Fi access-point mode, because the
laptop then has zero internet route at all while the agent keeps
queuing silently. Covers the correct setup (camera + laptop both join
the *same external* hotspot/travel router), central/elevated placement,
a realistic 10-20m indoor range, small/medium JPEG only (large files are
too slow over wireless), disabling camera auto power-off, spare
batteries, and a pre-event coverage-test procedure.

**While writing this, found the agent's offline detection didn't
actually cover the scenario being documented.** `Uploader.online` was
*reactive only* — updated as a side effect of a real upload attempt
failing. With an empty queue (exactly the AP-mode case, before any photo
has been taken), it would sit at its optimistic default indefinitely.
Fixed:
- `ApiClient.check_connectivity()` — plain unauthenticated `GET
  /health`.
- `Uploader` now runs this periodically while idle
  (`HEALTH_CHECK_INTERVAL_SECONDS`, `config.py`), not just reactively —
  state is corrected within about a second of `start()`.
- `gui.py` — a new full-width, bold red banner appears while offline
  (the existing small connected/offline label stays too), with wording
  that names the AP-mode mistake directly.

Verified live (not just unit tests): ran the real `AgentApp` headlessly
pointed at an actually-unreachable address (`192.0.2.1`, TEST-NET-1),
confirmed the banner appears with the right text using only the
empty-queue path (no upload ever attempted), then confirmed it clears
once pointed back at the real API. `agent/tests/
test_uploader_connectivity.py` exercises the real background thread
(not just pure logic) for this.

## Known gaps / deliberately unfinished

- **No Windows agent build.** See item 7. Needs either a Windows
  machine or this repo pushed somewhere so `.github/workflows/
  build-agent.yml` can actually run.
- **No git remote configured.** Purely local repo right now — this
  blocks the above, and blocks any real CI from ever running.
- `cameras.json`'s FTP-capability list is a best-effort seed (flagship/
  pro bodies mostly), not exhaustive — expect to need edits as
  photographers report models that should be added/corrected.
- The agent's RAW-inclusion setting (`settings.json`'s `include_raw`)
  exists but isn't exposed in the GUI yet — currently a manual JSON
  edit.
- Payments, a live-updating gallery, and real (non-interval-loop)
  scheduling for the purge job are all still open — see the main
  `README.md`'s own "Next up" section, which is kept reasonably current.

## Working environment notes (useful for resuming manual verification)

- Docker Compose: `postgres` (host port 5433, see item 4), `redis`,
  `minio`, `api`, `worker`, `ftps`, `purge-scheduler`. Bring up with
  `docker compose up -d`. **Remember `worker`/`ftps` need an explicit
  restart after code changes** (item 3).
- A throwaway Python 3.11 venv at `/tmp/.venv-p2` (host-side, pinned to
  `api/requirements.txt`) was used throughout this session for
  migrations/scripts run directly against the docker-compose Postgres
  from the host (not inside a container) — recreate similarly if needed,
  or just `docker compose exec api <command>`.
- `agent/.venv` — the agent's own venv, `pip install -r
  agent/requirements.txt` (includes `pyinstaller` for packaging).
- Frontend dev server runs natively on the host per `CLAUDE.md`, not in
  Docker: `cd web && npm run dev`. `web/.env.local` needs
  `NEXT_PUBLIC_API_URL` and, for phone/LAN testing,
  `NEXT_PUBLIC_SITE_URL` set to this machine's actual LAN IP (item 4) —
  both are gitignored, machine-specific, not committed.
- Every feature in this session was verified against the real running
  stack (real Postgres/Redis/MinIO/FTPS, a real headless-Chromium
  browser via Playwright for the frontend, a real macOS build launch for
  the agent) — not mocked. If resuming work, prefer continuing that
  pattern over trusting code review alone.
