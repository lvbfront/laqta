"""Index kb/laqta-kb.md into the assistant database (spec §11).

    python -m scripts.index_kb

Safe to run repeatedly: chunks are keyed by content hash, so an unchanged
file is a no-op and no embeddings are computed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import KB_PATH
from app.db import SessionLocal
from app.kb.chunker import chunk_file
from app.kb.index import index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--kb", type=Path, default=KB_PATH, help="knowledge base file")
    args = parser.parse_args(argv)

    chunks = chunk_file(args.kb)
    by_audience: dict[str, int] = {}
    for chunk in chunks:
        by_audience[chunk.audience.value] = by_audience.get(chunk.audience.value, 0) + 1

    with SessionLocal() as session:
        database = session.get_bind().url.database or ""
        if not database.startswith("assistant"):
            print(f"refusing to index into {database!r}: not an assistant database", file=sys.stderr)
            return 1

        report = index(session, chunks)
        session.commit()

    print(f"{args.kb.name}: {len(chunks)} sections ({by_audience})")
    print(f"{database}: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
