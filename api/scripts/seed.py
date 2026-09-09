#!/usr/bin/env python3
"""Create a demo organization + event and ingest a local folder of photos
into it, so the full ingest -> worker -> match -> delivery loop can be
exercised immediately without going through the (not yet built) events
API or a running frontend.

Usage:
    python scripts/seed.py /path/to/photos
    python scripts/seed.py /path/to/photos --privacy-mode strict

Requires Postgres/Redis/MinIO reachable (docker compose up -d postgres
redis minio) and migrations applied (alembic upgrade head). Run the
worker afterward to actually process the queued photos:
    docker compose up worker
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.models.enums import AccountType, EventStatus, MatchMode, PhotoStatus, PrivacyMode  # noqa: E402
from app.models.event import Event  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.photo import Photo  # noqa: E402
from app.storage import minio_client  # noqa: E402
from app.workers.jobs import process_photo  # noqa: E402
from app.workers.queue import get_photo_processing_queue  # noqa: E402

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def _original_key(event_id, photo_id) -> str:
    return f"events/{event_id}/photos/{photo_id}/original.jpg"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="Folder of photos to ingest (non-recursive)")
    parser.add_argument("--org-name", default="Demo Organizer")
    parser.add_argument("--event-name-ar", default="حدث تجريبي")
    parser.add_argument("--event-name-en", default="Demo Event")
    parser.add_argument("--privacy-mode", choices=["standard", "strict"], default="standard")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"Not a directory: {args.folder}", file=sys.stderr)
        sys.exit(1)

    paths = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
    if not paths:
        print(f"No images found in {args.folder}", file=sys.stderr)
        sys.exit(1)

    minio_client.ensure_bucket()

    db = SessionLocal()
    try:
        org = Organization(name=args.org_name, account_type=AccountType.organizer)
        db.add(org)
        db.flush()

        privacy_mode = PrivacyMode(args.privacy_mode)
        event = Event(
            org_id=org.id,
            name_ar=args.event_name_ar,
            name_en=args.event_name_en,
            status=EventStatus.active,
            # ends_at is required -- retention_until's default (7 or 30
            # days out, by privacy_mode) is computed from it. A demo event
            # "ends" 4 hours from now, a plausible single-day event.
            ends_at=datetime.now(timezone.utc) + timedelta(hours=4),
            consent_text_ar="بموافقتك، سنستخدم صورة وجهك مؤقتًا للعثور على صورك في هذا الحدث.",
            consent_text_en="By consenting, we'll briefly use your face to find your photos from this event.",
            privacy_mode=privacy_mode,
            match_mode=MatchMode.face,
            # The DB check constraint forces this false for strict events
            # regardless of what's passed here -- see ck_events_strict_requires_no_autopublish.
            auto_publish=(privacy_mode == PrivacyMode.standard),
        )
        db.add(event)
        db.flush()
        db.commit()

        print(f"Created organization {org.id} ({org.name})")
        print(
            f"Created event {event.id} ({event.name_en}) -- "
            f"qr_token={event.qr_token}, privacy_mode={event.privacy_mode.value}"
        )
        print(f"Guest URL (once the frontend exists): /e/{event.qr_token}")
        print(f"Match API: POST /api/events/{event.id}/match\n")

        queue = get_photo_processing_queue()
        seen_md5: set[str] = set()
        queued = 0
        skipped = 0

        for path in paths:
            content = path.read_bytes()
            md5 = hashlib.md5(content).hexdigest()
            if md5 in seen_md5:
                print(f"  {path.name}: duplicate within this folder, skipping")
                skipped += 1
                continue
            seen_md5.add(md5)

            existing = db.query(Photo).filter(Photo.event_id == event.id, Photo.md5 == md5).first()
            if existing is not None:
                print(f"  {path.name}: already ingested as {existing.id}, skipping")
                skipped += 1
                continue

            photo = Photo(event_id=event.id, s3_key_original="pending", md5=md5, status=PhotoStatus.pending)
            db.add(photo)
            db.flush()

            key = _original_key(event.id, photo.id)
            photo.s3_key_original = key
            content_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            minio_client.upload_bytes(key, content, content_type)
            db.commit()

            queue.enqueue(process_photo, str(photo.id))
            print(f"  {path.name}: queued as photo {photo.id}")
            queued += 1

        print(f"\nDone -- {queued} photo(s) queued for processing, {skipped} skipped.")
        print("Run the worker to actually process them: docker compose up worker")
    finally:
        db.close()


if __name__ == "__main__":
    main()
