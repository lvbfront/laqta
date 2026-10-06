# Face pipeline: from camera to guest

What happens to a photo and to a face at each stage, where it is stored, in
what form, and when it is deleted. Every claim cites `file:line` as of this
commit. "Not implemented" means the code doesn't do it.

## Stage by stage

| # | Stage | What is stored | Where | Image or embedding | Deleted when |
|---|---|---|---|---|---|
| 1 | **Camera → folder** | The JPEG Imaging Edge writes | The Mac's watched folder | Image (full-res, with EXIF/GPS) | Never by Laqta: the agent only reads it |
| 2 | **Folder → laqta_agent** | Path, MD5, status, attempts, last error, timestamps | SQLite queue: `~/Library/Application Support/Laqta Agent/queue.sqlite3` (`agent/laqta_agent/config.py:54-71`, schema `agent/laqta_agent/queue_db.py:11-24`) | Neither: metadata only | Never: rows accumulate; no cleanup is implemented |
| 3 | **Agent → upload** | Raw bytes, one file per POST `/api/agent/photos` (`agent/laqta_agent/api_client.py:98-119`, `api/app/api/routes/agent.py:56-75`) | In transit (HTTP; plain `http://` in dev) | Image | n/a |
| 4 | **Ingest** | `photos` row (`status=pending`, MD5) + the **raw upload** at `events/{event}/photos/{photo}/original.jpg` (`api/app/services/ingest.py:47-68`); job enqueued on Redis (`ingest.py:83`) | Postgres + MinIO | Image, *still with GPS EXIF* until stage 5 | Overwritten in stage 5 |
| 5 | **Processing** (RQ worker) | Downloads the raw upload (`api/app/workers/jobs.py:45`), autorotates, then **overwrites `original.jpg`** with a GPS/EXIF-stripped re-encode, writes thumbnail and watermarked preview (`jobs.py:58-60`, `strip=True` in `api/app/services/image_ops.py:76,86,114`) | MinIO | Image (3 objects, all EXIF-free) | Event purge (row 9) |
| 6 | **Detection + embedding** | buffalo_l (`api/app/services/face_model.py:33`), CPU only (`face_model.py:40,45`); every face aligned to 112×112 from 5 landmarks (`face_model.py:93`) then embedded and L2-normalised (`face_model.py:95-97`); quality gate ≥40 px and det_score ≥0.5 (`api/app/workers/pipeline.py:22-34,61-62`) | Worker memory | Aligned crops exist only in memory | End of job |
| 7 | **Storage** | One `faces` row per gated face: bbox, det_score, `vector(512)` embedding (`api/app/models/face.py:57-64`, insert `jobs.py:62-75`); `published = event.auto_publish` (`jobs.py:87`) | Postgres (pgvector, HNSW index) | **Embedding** (no crop image is stored) | Event purge (row 9), via `ON DELETE CASCADE` from `photos` (`face.py:46-50`) |
| 8 | **Guest selfie** | Selfie bytes read into memory (`api/app/api/routes/match.py:138`), decoded (`match.py:147-148`), validated (`match.py:54-96`), embedded, searched with, then discarded. Only a `guests` row is stored (consent time, IP, session token) (`match.py:155-162`) | API process memory | Image and embedding both in memory only | When the request returns. Before 2026-10-06 the embedding was stored in `guest_faces` for 30 days; migration `api/alembic/versions/7f05f01ae4fa_delete_stored_selfie_embeddings.py` deleted those rows |
| 9 | **Matching** | Cosine search scoped to the event, top 2000 candidates (`api/app/services/face_search.py:15,58-73`) | Postgres | Embedding vs embeddings | n/a |
| 10 | **Threshold** | Keep `score ≥ MATCH_THRESHOLD` = **0.38** (`face_search.py:72`, `config.py:42`, `.env.example`). Per photo, the best face score wins (`match.py:182-185`) | n/a | n/a | n/a |
| 11 | **What is returned** | Only **published** photos (`match.py:195-212`). One `matches` row per photo (`match.py:214-215`). The response is `{guest_session_token, matches:[{photo_id, score}]}` (`match.py:219`). Images reach the guest only as 5-minute presigned MinIO URLs, which need a `Match` row and `published` (`api/app/api/routes/delivery.py:63-79`) | Postgres | Neither (IDs + scores) | Event purge |

**Event purge.** Runs daily from `purge-scheduler`. When `retention_until` passes, it deletes MinIO objects first, then DB rows (`purge.py:105-106`). `retention_until` = `ends_at` + 7 days for strict events, + 30 days for standard (`api/app/models/event.py:28-29,38-59`).

## Answers

**a. Is the guest selfie stored as an image, an embedding, or discarded?**
**Both are discarded** (since 2026-10-06). The image exists only in API process memory during the request (`match.py:138-153`). It is never written to disk, MinIO, a temp file or a log:
- The multipart spool limit is raised so the upload can't spill to disk (`api/app/main.py:58-66`).
- pyvips debug logging is pinned off (`main.py:25`).
- `tests/test_selfie_never_persisted.py` checks this.

The embedding is used for one search (`match.py:166-171`) and then discarded too. Only a `guests` row with consent time, IP and session token is stored (`match.py:155-162`), and `api/tests/test_match_api.py` asserts no `guest_faces` row is written.

Earlier versions stored it in `guest_faces` for 30 days. Migration `api/alembic/versions/7f05f01ae4fa_delete_stored_selfie_embeddings.py` deleted those rows and logged the count to `audit_log`. The empty table and its purge path remain until a decision to drop them.

**b. Are embeddings computed for every face in every photo, including people who never scanned? When are they deleted?**
**Yes.** For any event with `match_mode` `face` or `both`, every face that passes the quality gate is embedded and stored (`pipeline.py:60-62`, `jobs.py:62-75`). That includes bystanders who never scan the QR code or consent. `code`/`sequential` events skip detection entirely (`jobs.py:50`, `pipeline.py:59-60`).

These embeddings are deleted **only** when the whole event is purged: ends_at + 7 days (strict) or + 30 days (standard). Nothing removes them earlier:
- A guest's "remove this photo of me" only sets `published=False` (`delivery.py:139-141`).
- A moderator's reject only sets `published=False` (`api/app/api/routes/photos.py:148`).
- In both cases the faces stay searchable in the index. They are just filtered out of results.

Per-person deletion of a bystander's embedding: **not implemented.**

**c. Is there explicit consent before the guest camera opens?**
**Yes, in the UI.**
- The consent checkbox is never pre-ticked (`web/components/guest/ConsentScreen.tsx:17`).
- The selfie button stays disabled until it's ticked (`ConsentScreen.tsx:62-63`).
- Only that click moves the flow to `capture` (`web/app/e/[qr_token]/page.tsx:125-131`), and only then does `getUserMedia` run (`web/components/guest/SelfieCapture.tsx:39`).
- The API refuses a match unless `consent=true` (`match.py:132-136`) and records `consent_at` and IP (`match.py:155-160`).

**Caveat:** the API's consent is just a client-sent boolean, so it proves the request said yes, not that a person saw the text. Consent is never asked from people who appear in photos without scanning (see b).

**d. Can someone get another person's photos using a photo of their face instead of a live selfie? Any liveness check or device binding?**
**Yes, they can.**
- Liveness detection: **not implemented.**
- Device binding: **not implemented.**
- Rate limiting on `/match`: **not implemented** (no limiter anywhere in `api/app`).
- The guest page has an upload-a-file fallback that accepts any image (`SelfieCapture.tsx:184-190`), and the API takes any image file (`match.py:104`).

Anyone with the event's QR link and a clear photo of someone (e.g. from social media) gets that person's matched photos. The e2e smoke test does exactly this: it feeds a still image into the camera path.

**e. Are embeddings encrypted at rest, and who can read them?**
**Not encrypted** at the application or database level. They are plain pgvector `vector(512)` columns (`face.py:64`, `api/app/models/guest_face.py:32`; no pgcrypto or app-level encryption anywhere in `api/app`). At-rest protection depends on the host disk: in dev, the `pgdata` Docker volume on this Mac.

Who can read them:
- Anyone with the Postgres credentials (`laqta` / `laqta_dev_password` in `.env`).
- The api, worker, ftps and purge-scheduler containers, which all get `DATABASE_URL`.

No HTTP endpoint returns embeddings (the only use in `api/app/api` is inside `match.py`).

In dev, Postgres, Redis (no password) and MinIO run with default credentials but are published on `127.0.0.1` only (`docker-compose.yml`), so other devices on the same Wi-Fi or hotspot can't reach them; `scripts/health_check` checks this.

## Related gaps (not changed here)

- `GET /api/events/{id}/photos` returns every photo in an event, with thumbnail URLs, to any org member (`photos.py:90-124`). The moderation page uses it with `status=ready` (`web/app/dashboard/events/[id]/moderate/page.tsx:25`), so moderators see all processed photos, not just the pending queue. This is close to the CLAUDE.md "no browse-all" rule. Flagged, not changed.
