"""BGE-M3 embeddings, on the CPU (spec §11).

The model is ~2GB and takes seconds to load, so it is loaded on first use
and kept — importing this module costs nothing, which matters because the
tool layer imports it transitively.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from app.config import EMBEDDING_DIM, EMBEDDING_MODEL


@lru_cache(maxsize=1)
def model() -> Any:
    from sentence_transformers import SentenceTransformer  # heavy: local import

    loaded = SentenceTransformer(EMBEDDING_MODEL)
    dimension = loaded.get_embedding_dimension()
    if dimension != EMBEDDING_DIM:
        # The stored vectors would be unusable, and the column would reject
        # them anyway — fail with the reason rather than a cast error.
        raise RuntimeError(
            f"{EMBEDDING_MODEL} returns {dimension} dimensions, but the schema and "
            f"app.config.EMBEDDING_DIM expect {EMBEDDING_DIM}. Changing the model "
            "needs a migration and a full reindex."
        )
    return loaded


def embed(texts: Sequence[str]) -> list[list[float]]:
    """Normalised, so cosine similarity is a dot product."""
    if not texts:
        return []
    vectors = model().encode(list(texts), normalize_embeddings=True)
    return [vector.tolist() for vector in vectors]


def embed_query(text: str) -> list[float]:
    return embed([text])[0]
