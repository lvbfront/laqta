"""Vector search over kb_chunks (spec §11).

The audience filter is applied in SQL, not after the fact: an internal
section must never be a row a customer's query can rank, let alone read.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import KB_MIN_SCORE, KB_TOP_K
from app.kb.embedder import embed_query
from app.models.enums import KBAudience
from app.models.kb_chunk import KBChunk

AUDIENCES_FOR_IDENTITY: dict[str, tuple[KBAudience, ...]] = {
    "anonymous": (KBAudience.public,),
    "customer": (KBAudience.public,),
    "staff": (KBAudience.public, KBAudience.internal),
}


@dataclass(frozen=True)
class SearchHit:
    section_title: str
    content: str
    score: float


def audiences_for(identity_kind: str) -> tuple[KBAudience, ...]:
    try:
        return AUDIENCES_FOR_IDENTITY[identity_kind]
    except KeyError:
        # Fail closed: an unrecognised role gets nothing, not public-by-default.
        raise ValueError(f"unknown identity kind: {identity_kind!r}") from None


def search(
    session: Session,
    query: str,
    *,
    identity_kind: str,
    top_k: int = KB_TOP_K,
    min_score: float = KB_MIN_SCORE,
) -> list[SearchHit]:
    """The best `top_k` sections this role may see, or an empty list when
    nothing clears `min_score` — which the caller reports as
    no_relevant_section, and the instructions turn into a handoff."""
    allowed = audiences_for(identity_kind)
    vector = embed_query(query)
    distance = KBChunk.embedding.cosine_distance(vector)

    rows = session.execute(
        select(
            KBChunk.section_title,
            KBChunk.content,
            (1 - distance).label("score"),
        )
        .where(KBChunk.audience.in_(allowed))
        .order_by(distance)
        .limit(top_k)
    ).all()

    if not rows or rows[0].score < min_score:
        return []
    return [
        SearchHit(section_title=row.section_title, content=row.content, score=float(row.score))
        for row in rows
    ]
