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

- **`guest_faces` table:** no longer written (selfie embeddings are discarded since 2026-10-06; the old rows were deleted by migration `7f05f01ae4fa`). The empty table, its model and its purge path remain. Decision pending: drop them.
- **FTPS ports exposed on the LAN:** `:2121` and `:30000-30009` are still published on all interfaces (`docker-compose.yml`, `ftps` service). They're password-protected per event, and the ZV-E10 can't use FTP.
- **Guests on a phone in dev:** gallery images are presigned MinIO URLs, and MinIO is localhost-only. Phone browsers also need HTTPS for the camera. Guest testing in dev is from the Mac's browser only.
- **Agent: a finished file that's edited later is never re-uploaded.** The queue is keyed by path (`agent/laqta_agent/queue_db.py`, `enqueue`), so a changed file at the same path is ignored.
- **No "processed" or "published" timestamps:** `photos` has no `processed_at`/`updated_at`, and `published` has none unless a moderator acted. `scripts/camera_check` shows when it observed those states.
- **Camera day:** unverified until the visit: whether the ZV-E10's own shutter button transfers during PC Remote, and the Wi-Fi transfer time (docs/CAMERA_DAY.md, steps 7–8). Camera model (original vs II) not yet known.
- **Windows agent:** never built or run on Windows. No `.exe` exists (agent/README.md, "Building").
