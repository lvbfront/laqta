# Laqta — event photo delivery platform

Photographers upload photos live during an event. Attendees scan a QR code,
submit a selfie, and receive only the photos they appear in.

Product context: see `docs/plan.md`. Build only what the current task asks for.

## Hard constraints — never violate

- The selfie image is NEVER persisted. Not to disk, object storage, temp
  files, or logs. In-memory only, embed, then discard.
- No browse-all-photos endpoint or view, for any role, at any time.
  Moderators see the pending queue. Guests see their own matches only.
  Do not add one as an admin convenience.
- All face processing runs locally via InsightFace. Never call an external
  face recognition API. Biometric data must not leave the Kingdom.
- Model pack is buffalo_l. Do not switch — embeddings from different model
  packs are not comparable, and switching invalidates every stored vector.
- Strict-mode events (privacy_mode = 'strict') must never return an
  unapproved photo. Enforce at the DB layer and the API layer.
- Face crops must be aligned to 112x112 using the five landmarks before
  embedding. Never embed a raw crop.
- Strip GPS EXIF from every derivative image.

## Stack

Python 3.11 / FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL 16 + pgvector /
Redis + RQ / MinIO via boto3 / InsightFace buffalo_l on onnxruntime CPU /
pyvips / Next.js 14 App Router + TypeScript + Tailwind, RTL-first.

Docker Compose runs Postgres, Redis, MinIO, API, worker.
The Next.js dev server runs natively on the host, not in Docker.
Dev machine is an Apple Silicon Mac — use arm64 images.
