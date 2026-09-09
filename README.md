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

Not built yet: the ingest API (so nothing enqueues worker jobs yet), match API,
delivery API, purge job, frontend, seed script.

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
│   │   ├── api/routes/                # empty — ingest/match/delivery land here
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

## Environment variables

See [`.env.example`](.env.example) for the full, current list (Postgres/Redis/MinIO
connection settings, `MATCH_THRESHOLD`, `GUEST_FACE_RETENTION_DAYS`, face-pipeline
tuning). This section will be expanded as the ingest/match/delivery APIs land.

## Running tests

Tests run against a real Postgres + pgvector database (UUID/vector/enum types
aren't meaningfully testable against SQLite). `tests/conftest.py` will create
the test database if it doesn't exist, drop and recreate its schema, and run
Alembic migrations against it every session — point it at a *disposable*
database, never at dev data.

```bash
cd api
source .venv/bin/activate
docker compose up -d postgres   # if not already running
TEST_DATABASE_URL=postgresql+psycopg://laqta:laqta_dev_password@localhost:5432/laqta_test \
  pytest tests/ -v
```

`TEST_DATABASE_URL` defaults to `laqta_test` on `localhost:5432` if unset.

## Next up

Ingest API (`POST /api/events/{event_id}/photos`) — MD5 dedupe, write the
original to MinIO, create the `photos` row, enqueue `app.workers.jobs.process_photo`.
Then match API, delivery API, purge job, frontend, seed script.
