# Laqta (لقطة)

Event photo delivery platform for the Saudi market. Photographers upload photos
live during an event; attendees scan a QR code, submit a selfie, and receive only
the photos they appear in, matched by on-device face recognition. No selfie image
is ever persisted, no browse-all-photos view exists for any role, and all face
processing runs locally via InsightFace — nothing biometric leaves the machine.

Product background: [`docs/plan.md`](docs/plan.md).
Hard constraints that govern every change in this repo: [`CLAUDE.md`](CLAUDE.md).

## Status

**Phase 1, in progress.** Done and verified end-to-end (including inside the real
arm64 Docker image, not just a host venv):

- Full data model (SQLAlchemy models + initial Alembic migration), against a live
  Postgres 16 + pgvector instance.
- Worker pipeline: pyvips thumbnailing/watermarking/EXIF, buffalo_l face
  detection + alignment + embedding, quality gating.
- Ingest API: `POST /api/events/{event_id}/photos`, batch multipart upload,
  per-event MD5 dedupe, enqueues the worker job. Verified end-to-end against
  real Postgres/Redis/MinIO, including running the worker job synchronously
  against a real ingested photo and confirming the full chain: raw upload →
  `status='ready'`, 6/6 faces detected, thumbnail/preview written, original
  overwritten with an EXIF-free re-encode.
- Match API: `POST /api/events/{event_id}/match` — selfie validated in memory
  before any search, matched against real event photos with a real selfie
  image end-to-end. Found and fixed a real bug along the way: Starlette's
  multipart parser spools uploads over 1MB to a real temp file on disk by
  default, smaller than a typical selfie — see "Match API" below for the
  details and the regression test that reproduces it.
- Delivery API: `GET /api/guest/photos/{photo_id}/url` — short-TTL presigned
  MinIO URLs, scoped to a guest session token and gated on an actual `Match`
  row (which also naturally means "matched below threshold" and "never
  matched" are the same, correctly-denied state).

Not built yet: purge job, frontend, seed script.

## Repo layout

```
laqta/
├── docker-compose.yml     # postgres (pgvector), redis, minio, api, worker
├── .env.example            # copy to .env — all services read from it
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/        # 1 migration so far: initial schema
│   ├── app/
│   │   ├── main.py             # FastAPI app (health check only, so far)
│   │   ├── config.py            # Settings, from env vars
│   │   ├── db.py                  # SQLAlchemy engine/session/Base
│   │   ├── models/                  # one file per table (see below)
│   │   ├── api/routes/
│   │   │   ├── photos.py                # ingest: POST /api/events/{id}/photos
│   │   │   ├── match.py                   # POST /api/events/{id}/match
│   │   │   └── delivery.py                  # GET /api/guest/photos/{id}/url
│   │   │                                # (moderation lands here next)
│   │   ├── api/utils.py                  # client_ip() -- shared by match/delivery
│   │   ├── workers/
│   │   │   ├── pipeline.py              # pure: bytes in, derivatives+faces out
│   │   │   ├── jobs.py                    # RQ job: DB + MinIO orchestration
│   │   │   └── queue.py                     # RQ queue/connection setup
│   │   ├── services/
│   │   │   ├── image_ops.py             # pyvips: thumbnail/watermark/EXIF
│   │   │   ├── face_model.py              # InsightFace buffalo_l wrapper
│   │   │   └── face_search.py               # pgvector cosine search
│   │   ├── storage/
│   │   │   └── minio_client.py          # boto3 S3-compatible client
│   │   └── core/
│   ├── scripts/
│   │   └── embed_folder.py      # CLI: detect+embed a folder, dump JSON
│   └── tests/
└── web/                      # Next.js app — not scaffolded yet
```

## Data model

11 tables, all UUID-keyed (`api/app/models/`):

- `organizations` — `account_type`: `organizer` | `photographer`
- `users` — `role`: `owner` | `staff` | `photographer` | `moderator`
- `events` — `privacy_mode` (`standard`|`strict`), `match_mode` (`face`|`code`|`both`),
  `auto_publish`, `retention_until`, bilingual consent text, `qr_token`.
  A **check constraint** forces `auto_publish = false` whenever
  `privacy_mode = 'strict'` — enforced again in the API layer once it exists.
- `photographers` — scoped to an org; `ftp_username`/`ftp_password_hash` are
  reserved for the Phase 2 FTPS ingest path, unused for now.
- `photos` — `status` (`pending`|`processing`|`ready`|`failed`), `published`
  (moderation gate, separate from processing status), MD5-deduped per event
  (`uq_photos_event_md5`).
- `faces` — one row per detected face, `bbox_*`, `det_score`, a `vector(512)`
  `embedding` with an **HNSW index** (`vector_cosine_ops`), and `event_id`
  (denormalized from `photo.event_id`, also indexed). The denormalization
  matters: it puts the event scope on the *same table* as the vector index,
  which is what lets `app/services/face_search.py` use pgvector's
  `hnsw.iterative_scan` fix for filtered-ANN recall (see that file's
  docstring, and `tests/test_face_search_recall.py`, for the mechanism —
  the test is a forced/synthetic reproduction, not a real-world recall
  measurement, and says so up front).
  `faces.event_id` can't drift from its own photo's event (which would let
  a guest at one event match a face belonging to another): `photos` carries
  a `uq_photos_id_event_id` unique constraint on `(id, event_id)`, and
  `faces` references it with a **composite FK** on `(photo_id, event_id)`
  rather than two independent single-column FKs — see
  `tests/test_face_event_integrity.py`.
- `guests` — consent timestamp + IP, a bearer `session_token` that scopes the
  guest's own delivery API calls. **No selfie image or plaintext phone number
  is representable in this schema anywhere** — only a hashed phone and a
  vector.
- `guest_faces` — the selfie's embedding + `expires_at`. This row is the only
  trace of a selfie that ever exists.
- `matches` — guest × photo, max cosine score across that photo's faces,
  optional `feedback` (`not_me` | `remove_requested`).
- `downloads` — every delivery, logged.
- `audit_log` — append-only, no FKs (must survive the rows it refers to being
  purged).

## Local setup (what works today)

Prerequisites: Docker Desktop (Apple Silicon / arm64), Python 3.11 for anything
run outside Docker.

```bash
cp .env.example .env
docker compose up -d postgres redis minio
```

> If you already run Postgres natively on port 5432, either stop it or set
> `POSTGRES_PORT` in `.env` to a free port before bringing the container up —
> a local server bound to `127.0.0.1:5432` silently wins over Docker's publish
> mapping on macOS.

Apply the schema:

```bash
cd api
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATABASE_URL=postgresql+psycopg://laqta:laqta_dev_password@localhost:5432/laqta \
  alembic upgrade head
```

(Once the `api`/`worker` containers have real code, `docker compose up` runs
migrations the same way from inside the container — see `docker-compose.yml`.)

Confirm the API skeleton runs:

```bash
docker compose up -d api
curl http://localhost:8000/health   # {"status": "ok"}
```

## Worker pipeline

`app/workers/pipeline.process_photo_bytes()` is the pure core (raw uploaded
JPEG bytes in; a re-encoded original + thumbnail/preview bytes + gated
`DetectedFace`s out, no DB/MinIO):

1. **Load** (`image_ops.load_image`): `.autorot()` runs immediately, before
   anything else touches the image. Without this, a sideways phone/camera
   photo (EXIF `Orientation` ≠ 1) stays sideways in every derivative once
   EXIF is stripped later — the orientation *tag* would be gone but the
   pixels were never physically rotated to match. This also means face
   detection always sees upright pixels, not just that display looks right.
2. **pyvips**: read EXIF `DateTimeOriginal` (interpreted as `Asia/Riyadh`, since
   camera clocks are set to local time — see `docs/plan.md`) before anything
   is stripped, then produce three JPEGs, each written with `strip=True` so
   **no EXIF field, GPS included, survives in any of them** (CLAUDE.md):
   a 300px thumbnail, a 1200px watermarked preview (diagonal tiled
   "Laqta · لقطة"), and a near-lossless (Q95), full-resolution re-encode of
   the original itself (`image_ops.prepare_original_jpeg`) — see "GPS and
   the stored original" below for why the original needs this too.
3. **buffalo_l detection** (`app/services/face_model.py`): runs the pack's
   detector, then explicitly aligns each detection to a 112×112 crop via
   `insightface.utils.face_align.norm_crop` (five landmarks, similarity
   transform) *before* computing the ArcFace embedding — alignment is a
   visible, separate step in this code, not hidden inside a convenience call.
   Embeddings are L2-normalized explicitly after `get_feat()` (which returns
   raw, unnormalized features).
4. **Quality gate** (`app/workers/pipeline._passes_quality_gate`): drops faces
   under `MIN_FACE_BBOX_PX` (40px, either side) or `MIN_DET_SCORE` (0.5) —
   applied after detection, at a permissive `det_thresh=0.3` in the model
   itself, so the real business threshold lives in one place.

`app/workers/jobs.process_photo(photo_id)` is the RQ job that wires this to
Postgres + MinIO: downloads the raw-uploaded original, runs the pipeline,
**overwrites `s3_key_original`** with the re-encoded/stripped version, uploads
the thumbnail/preview derivatives, inserts `faces` rows, and sets
`photo.status`/`photo.published` (the latter mirrors `event.auto_publish`, so
a strict-mode event's photos stay unpublished until a moderator acts —
nothing here bypasses that). Nothing enqueues this job yet since the ingest
API isn't built.

### GPS and the stored original

The thumbnail/preview being GPS-free isn't sufficient on its own: per the
ingest/delivery API design, guests download *originals* too, and the raw
bytes a camera uploads routinely carry GPS EXIF. Stripping only the
derivatives would leave exact event-location data sitting in the one file
guests actually download most. The ingest endpoint (not built yet) is
deliberately not the place to fix this — its request handler does no image
processing, by design, so bursts stay fast — so the worker job does it
instead: it downloads whatever was raw-uploaded, and before a photo can ever
reach `status='ready'`, overwrites `s3_key_original` with
`prepare_original_jpeg`'s output. There is only ever one object at that key;
nothing served to a guest was ever the unstripped upload. See
`tests/test_original_gps_stripped.py`.

**Verified for real**, not just unit-tested: built the actual arm64 Docker
image and ran full detection+alignment+embedding inside it against a real
multi-face photo (6/6 faces detected, scores 0.87–0.92, off-diagonal cosine
similarity between different people ~0–0.2, deterministic across repeated
runs) — and confirmed the Arabic half of the watermark renders correctly
inside the container (`fonts-noto-core`; `fonts-dejavu-core` alone has no
Arabic glyphs, which would have silently produced tofu boxes in production
despite working on a Mac's system fonts in dev).

### Tuning the match threshold — `scripts/embed_folder.py`

```bash
cd api
source .venv/bin/activate
python scripts/embed_folder.py /path/to/real/event/photos \
  --out results.json --pairwise-csv similarities.csv
```

Runs detection+embedding (ungated — every detection is included, with a
`passes_gate` flag per current `MIN_FACE_BBOX_PX`/`MIN_DET_SCORE`) over every
image in a folder and dumps one JSON record per face (bbox, det_score,
embedding). `--pairwise-csv` additionally computes cosine similarity across
every pair of gated faces in the folder, sorted descending — the direct input
for eyeballing where same-person vs. different-person scores separate before
committing to `MATCH_THRESHOLD`.

## Ingest API

`POST /api/events/{event_id}/photos` — multipart, `files` (repeatable field,
batch upload). Returns 201 immediately with a per-file status; **no image
processing happens in the request handler** — cameras send bursts and the
response has to stay fast:

1. 404 if the event doesn't exist.
2. Per file: read bytes, MD5 hash, check for an existing `(event_id, md5)` row
   (fast-path dedupe) — insert a `pending` `photos` row, upload the raw bytes
   to MinIO at `events/{event_id}/photos/{photo_id}/original.jpg`, commit,
   enqueue `app.workers.jobs.process_photo` on the `photo_processing` RQ
   queue. One file's failure (bad upload, race-lost dedupe caught via the
   `uq_photos_event_md5` `IntegrityError`) doesn't sink the rest of the batch
   — each file gets its own try/except and its own row in the response.
3. Response: `{"results": [{"filename", "status": "queued"|"duplicate"|"error",
   "photo_id"?, "duplicate_of"?, "error"?}, ...]}`.

Dedupe is enforced twice on purpose: a pre-check query (avoids a wasted MinIO
upload in the common case) and the DB unique constraint (`try: db.flush()
except IntegrityError`, which is what actually holds under two near-
simultaneous uploads of the same file — see `tests/test_ingest_photos.py`).

No auth on this endpoint yet — Phase 2 introduces per-event FTPS/photographer
credentials; there's nothing to check against yet in Phase 1.

## Match API

`POST /api/events/{event_id}/match` — multipart, `selfie` (image) + `consent`
(bool, must be `true`). The selfie is **never written to disk, MinIO, a temp
file, or a log line** — decoded in memory, embedded, discarded when the
request returns. See `tests/test_selfie_never_persisted.py`, and the note
below about a real bug that testing this surfaced.

Validation runs, in this order, entirely before any search against the
event's faces — a selfie that fails is never compared against anything:

| Order | Check | Error `code` |
|---|---|---|
| 1 | Exactly one face detected | `no_face_detected` / `multiple_faces_detected` |
| 2 | Detection score ≥ `MIN_DET_SCORE` | `low_detection_confidence` |
| 3 | Face bbox ≥ `MIN_FACE_BBOX_PX` on its shorter side | `face_too_small` |
| 4 | Variance of the Laplacian of the face crop ≥ `MIN_BLUR_VARIANCE` | `selfie_too_blurry` |

Each is a distinct code with an actionable message (move closer, better
light, remove sunglasses/mask, hold the camera steady, take the photo
alone) — not a generic "try again". `tests/test_selfie_validation.py` pins
the order and every branch using a mocked detector (fast, deterministic,
no model needed); `tests/test_match_api.py` covers the real end-to-end path
with the actual model.

On success: embeds the selfie, `app.services.face_search.search_faces`
(cosine similarity, scoped to the event, HNSW + `iterative_scan` — see
"Data model" above), groups by photo taking the max score, keeps only
**published** photos (a plain post-filter on the result set, deliberately
*not* folded into the search query itself — doing that would reintroduce
the filtered-ANN recall issue `faces.event_id` was denormalized to avoid),
creates `guests` + `guest_faces` rows (`expires_at` = now + `GUEST_FACE_RETENTION_DAYS`),
persists one `matches` row per surfaced photo, and returns
`{guest_session_token, matches: [{photo_id, score}, ...]}` sorted descending.

The full per-query score distribution is logged at `DEBUG` (not just what
crossed threshold) — `MATCH_THRESHOLD` tuning is a matter of running real
selfies against a real event and reading these:

```
match scores event=<uuid> guest=<uuid> threshold=0.380 n=14 scores=[0.71, 0.68, 0.55, 0.4, 0.31, ...]
```

**A real bug, found by building the "never touches disk" test properly:**
Starlette's multipart parser spools each uploaded part in memory only up to
`MultiPartParser.max_file_size` (default 1MB) before spilling to a real
`SpooledTemporaryFile`-backed temp file — confirmed empirically that a 2MB
upload triggers a real disk write under that default. A phone selfie
routinely exceeds 1MB, so the *selfie itself* would have silently violated
CLAUDE.md's constraint regardless of anything our own route code does.
Fixed in `app/main.py` by raising that threshold well above any realistic
upload; `tests/test_selfie_never_persisted.py` uses a genuinely ~1.3MB
fixture image specifically so it would have caught this, and does (verified
by reverting the fix locally and watching the test fail on the disk-spill
assertion before restoring it).

## Delivery API

`GET /api/guest/photos/{photo_id}/url?variant=preview|original` — header
`Authorization: Bearer <guest_session_token>`. Returns a short-TTL
(`SIGNED_URL_TTL_SECONDS`) presigned MinIO URL; the API never proxies the
image bytes itself.

Every request is scoped down to one question: does a `Match` row connect
this guest to this photo? Nothing else about the photo or the guest's event
membership is checked separately, because that one condition already
implies it — a guest's matches only ever come from their own event's faces.
That same single check is *why* a photo from a different event and a
photo that scored below `MATCH_THRESHOLD` land on exactly the same 404:
neither ever produced a `Match` row (the match endpoint only persists rows
for photos that clear threshold), so "wrong event" and "below threshold"
are indistinguishable, correctly-denied states, not two code paths that
could drift out of sync. `published` is re-checked here too, not just
trusted from match time — a future moderation action could unpublish a
photo after it was matched, and that has to revoke delivery immediately.
See `tests/test_delivery_scoping.py` for both cases plus missing/invalid
session tokens.

Every issued URL is logged to `downloads` (guest_id, photo_id, ip, at) —
logged at issuance, not at the actual MinIO GET, since presigned-URL
downloads happen directly against MinIO and aren't otherwise observable
from the API process.

## Environment variables

See [`.env.example`](.env.example) for the full, current list (Postgres/Redis/MinIO
connection settings, `MATCH_THRESHOLD`, `GUEST_FACE_RETENTION_DAYS`, face-pipeline
tuning, blur/upload-size limits, `SIGNED_URL_TTL_SECONDS`).

## Running tests

Tests run against real backends — Postgres + pgvector (UUID/vector/enum types
aren't meaningfully testable against SQLite), Redis, and MinIO. `tests/conftest.py`
will create the test database if it doesn't exist, drop and recreate its
schema, and run Alembic migrations against it every session — point
`TEST_DATABASE_URL` at a *disposable* database, never at dev data. The
`client` fixture (for API route tests) reuses the same rollback-isolated
session as `db_session` via a `get_db` dependency override, so route code
that calls a real `.commit()` still leaves no trace after the test.

```bash
cd api
source .venv/bin/activate
docker compose up -d postgres redis minio   # if not already running
TEST_DATABASE_URL=postgresql+psycopg://laqta:laqta_dev_password@localhost:5432/laqta_test \
  pytest tests/ -v
```

`TEST_DATABASE_URL` defaults to `laqta_test` on `localhost:5432` if unset; Redis/MinIO
settings come from the same env vars the app uses (see `.env.example`).

## Next up

Purge job (scheduled RQ job: hard-delete expired `guest_faces` and
past-retention event data, writing to `audit_log`). Then the frontend and
seed script.
