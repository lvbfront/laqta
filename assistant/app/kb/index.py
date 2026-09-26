"""Index the knowledge base into kb_chunks (spec §11).

Idempotent by content_hash: running it twice embeds nothing the second time
and leaves the table identical. A section removed from the file loses its
row, and an edited section is a delete plus a create, because its hash
changes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.kb.chunker import Chunk
from app.kb.embedder import embed as default_embed
from app.models.kb_chunk import KBChunk

Embedder = Callable[[Sequence[str]], list[list[float]]]


@dataclass(frozen=True)
class IndexReport:
    created: int
    deleted: int
    unchanged: int

    def __str__(self) -> str:
        return (
            f"{self.created} created, {self.deleted} deleted, {self.unchanged} unchanged"
        )


def index(
    session: Session,
    chunks: Sequence[Chunk],
    *,
    embed: Embedder = default_embed,
) -> IndexReport:
    """`embed` is injectable so the indexing tests do not need the model."""
    desired = {chunk.content_hash: chunk for chunk in chunks}
    existing = {row.content_hash: row for row in session.scalars(select(KBChunk)).all()}

    new_hashes = [digest for digest in desired if digest not in existing]
    stale_rows = [row for digest, row in existing.items() if digest not in desired]

    if new_hashes:
        # Only the new ones: re-embedding unchanged sections is the expensive
        # mistake this whole function exists to avoid.
        vectors = embed([desired[digest].content for digest in new_hashes])
        for digest, vector in zip(new_hashes, vectors, strict=True):
            chunk = desired[digest]
            session.add(
                KBChunk(
                    section_title=chunk.section_title,
                    audience=chunk.audience,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    embedding=vector,
                )
            )

    for row in stale_rows:
        session.delete(row)

    session.flush()
    return IndexReport(
        created=len(new_hashes),
        deleted=len(stale_rows),
        unchanged=len(desired) - len(new_hashes),
    )
