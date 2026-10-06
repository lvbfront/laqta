# Status: known gaps

Open problems, deliberately not fixed yet, with where they live in the code (line numbers as of 2026-10-06). Background for each: docs/FACE_PIPELINE.md.

## Known gaps (decided: not fixing yet)

### b. Bystanders' faces are embedded without consent, and kept until the event is purged
- Every face that passes the quality gate in every photo is embedded (`api/app/workers/pipeline.py:61-62`) and stored as a `faces` row (`api/app/workers/jobs.py:62-75`). That includes people who never scan the QR code. Only `code`/`sequential` events skip this (`jobs.py:50`).
- These embeddings are deleted only by the event purge, via the cascade from `photos` (`api/app/workers/purge.py:105`, `api/app/models/face.py:49`). That's `ends_at` + 7 days for strict events, + 30 for standard (`api/app/models/event.py:28-29`).
- "Remove this photo of me" (`api/app/api/routes/delivery.py:141`) and a moderator's reject (`api/app/api/routes/photos.py:148`) only set `published = False`. The faces stay in the search index.
- Missing: per-person deletion, and any consent path for people who appear in photos without scanning.

### d. A photo of someone's face works as their selfie: no liveness check
- `/match` accepts any image file (`api/app/api/routes/match.py:104`) and runs no liveness detection before searching (`match.py:166`).
- No device binding and no rate limiting (no limiter anywhere in `api/app`).
- The guest page now only takes a frame from the live camera (`web/components/guest/SelfieCapture.tsx:39`; upload option removed 2026-10-06). That raises the bar but doesn't close it: a printed photo held up to the camera, a virtual camera, or a direct POST still works. `scripts/e2e_smoke` gets in this way on purpose.

### e. Embeddings are not encrypted at rest
- Plain pgvector columns: `api/app/models/face.py:64` (and `api/app/models/guest_face.py:32`, no longer written). No pgcrypto or app-level encryption anywhere in `api/app`.
- Readable by anyone with the Postgres credentials (dev defaults, `docker-compose.yml:11`) and by every container given `DATABASE_URL` (api, worker, ftps, purge-scheduler).
- In dev, Postgres is published on `127.0.0.1` only, since 2026-10-06. At-rest protection depends on the host disk.

### Browse-all photos endpoint
- `GET /api/events/{id}/photos` (`api/app/api/routes/photos.py:91-122`) returns every photo in an event, with thumbnail URLs, to any member of the org (`photos.py:100`; the status filter is optional).
- The moderation page calls it with `status=ready` (`web/app/dashboard/events/[id]/moderate/page.tsx:25`), so moderators see every processed photo, approved or not, rather than only the pending queue.
- CLAUDE.md: "No browse-all-photos endpoint or view, for any role… Moderators see the pending queue."

## Other open items

- **Dead code: the `guest_faces` table** (decided 2026-10-06: leave it, remove later). Nothing writes it since selfie embeddings stopped being stored, and migration `7f05f01ae4fa` deleted the old rows. To remove it later:
  - **Write a migration that drops the table.** It was created in `api/alembic/versions/73fb312b9091_initial_schema.py`.
  - **Delete these together:**
    - the model: `api/app/models/guest_face.py`
    - its export: `api/app/models/__init__.py:13,31`
    - the `Guest.faces` relationship: `api/app/models/guest.py:18,58`
    - the purge path, with its `guest_faces_deleted` report field: `api/app/workers/purge.py:15,41,136-163,181,201`
    - the job log line: `api/app/workers/jobs.py:114-115`
    - the CLI output: `api/scripts/purge.py:2,34`
  - **Update the tests that build `GuestFace` rows:**
    - `api/tests/test_purge.py`: guest-face cases at lines 23-43, 123-139, 176-212
    - `api/tests/test_guest_cascade.py:5-32`
    - `api/tests/test_code_match.py:6,77`
    - `api/tests/test_match_api.py:6,44-45` (keep the "nothing stored" intent another way)
- **Guests on a phone in dev:** gallery images are presigned MinIO URLs, and MinIO is localhost-only. Phone browsers also need HTTPS for the camera. Guest testing in dev is from the Mac's browser only.
- **Agent: a finished file that's edited later is never re-uploaded.** The queue is keyed by path (`agent/laqta_agent/queue_db.py`, `enqueue`), so a changed file at the same path is ignored.
- **No "processed" or "published" timestamps:** `photos` has no `processed_at`/`updated_at`, and `published` has none unless a moderator acted. `scripts/camera_check` shows when it observed those states.
- **Camera day:** unverified until the visit: whether the ZV-E10's own shutter button transfers during PC Remote, and the Wi-Fi transfer time (docs/CAMERA_DAY.md, steps 7–8). Camera model (original vs II) not yet known.
- **Windows agent:** never built or run on Windows. No `.exe` exists (agent/README.md, "Building"). Fixed 2026-10-06: settings are read and written as UTF-8 (`agent/laqta_agent/settings.py:32,43`), so an Arabic folder name no longer crashes on English-locale Windows (`agent/tests/test_settings_encoding.py`). Still untested on Windows:
  - watchdog's Windows backend
  - reading files the camera software still has open
  - how Arabic text renders in Tk
  - the PyInstaller build (`build_windows.bat` and the CI workflow have never run)
