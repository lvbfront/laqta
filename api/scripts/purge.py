#!/usr/bin/env python3
"""Hard-delete expired guest_faces vectors and, for events past
retention_until, all of that event's photos/faces/guests/matches/downloads
plus the corresponding MinIO objects. See app/workers/purge.py for exactly
what gets deleted, in what order, and why.

Usage:
    python scripts/purge.py             # actually deletes
    python scripts/purge.py --dry-run   # reports what would be deleted; deletes nothing
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workers.purge import run_purge  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted; delete nothing.")
    args = parser.parse_args()

    report = run_purge(dry_run=args.dry_run)

    if not report.ran:
        print("Another purge run holds the advisory lock -- skipped.")
        sys.exit(0)

    label = "Would delete" if args.dry_run else "Deleted"
    print(f"{label} {report.guest_faces_deleted} expired guest_faces row(s).")

    if not report.events:
        print("No events past retention_until with remaining data.")
    for r in report.events:
        print(
            f"{label} event {r.event_id}: {r.photos_deleted} photo(s), "
            f"{r.minio_objects_deleted} MinIO object(s), {r.guests_deleted} guest(s)."
        )

    if args.dry_run:
        print("\nDry run -- nothing was actually deleted.")


if __name__ == "__main__":
    main()
