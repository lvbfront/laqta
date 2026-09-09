from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.face import Face

# How many nearest-neighbor candidates to pull from the HNSW index before
# filtering by score threshold. Must comfortably exceed how many faces a
# single real event will ever have in Phase 1 -- see the recall note below
# for why the size of this matters.
DEFAULT_CANDIDATE_LIMIT = 2000


@dataclass(frozen=True)
class FaceMatch:
    face_id: uuid.UUID
    photo_id: uuid.UUID
    score: float


def search_faces(
    db: Session,
    *,
    event_id: uuid.UUID,
    query_embedding: list[float],
    threshold: float,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> list[FaceMatch]:
    """Cosine-similarity search over faces scoped to one event.

    This is pgvector's documented filtered-ANN case: a `WHERE event_id = X`
    predicate alongside an `ORDER BY embedding <=> :query LIMIT k` on the
    same table. Postgres plans this as an HNSW index scan on the embedding
    for the ORDER BY, then applies the event_id predicate as a *post-scan*
    filter -- the HNSW graph traversal itself has no way to take that filter
    into account. With the default `hnsw.iterative_scan = off`, the scan
    stops once it has examined its candidate window (governed by
    hnsw.ef_search) regardless of how many of those candidates passed the
    filter, so if other events' faces dominate the nearest-neighbor
    ordering, this event's true matches can be silently dropped even though
    they're sitting right there in the index.

    Setting `hnsw.iterative_scan = 'relaxed_order'` (added in pgvector
    0.8.0; this deployment runs 0.8.6, confirmed via `SELECT extversion
    FROM pg_extension WHERE extname='vector'`) tells the scan to keep
    walking the graph -- beyond the initial ef_search window, up to
    hnsw.max_scan_tuples -- until it has gathered `candidate_limit`
    *post-filter* rows. See tests/test_face_search_recall.py for a
    regression test that reproduces the under-return without it.

    `SET LOCAL` scopes the setting to the current transaction only, so it
    never leaks onto other queries sharing this connection/session.
    """
    db.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))

    distance = Face.embedding.cosine_distance(query_embedding)
    stmt = (
        select(Face.id, Face.photo_id, (1 - distance).label("score"))
        .where(Face.event_id == event_id)
        .order_by(distance)
        .limit(candidate_limit)
    )

    rows = db.execute(stmt).all()
    return [
        FaceMatch(face_id=row.id, photo_id=row.photo_id, score=row.score)
        for row in rows
        if row.score >= threshold
    ]
