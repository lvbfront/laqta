"""Split the knowledge base into retrievable chunks (spec §11).

One `## ` section is one chunk. The section title is repeated at the top of
the chunk text because it measurably helps retrieval — a question about
packages matches a chunk that says "القسم: الباقات" more strongly than one
that only lists numbers.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.models.enums import KBAudience

SECTION_SPLIT = re.compile(r"^## ", re.MULTILINE)
AUDIENCE_MARKER = re.compile(r"^\s*<!--\s*audience:\s*([a-z_]+)\s*-->\s*$", re.MULTILINE)
TITLE_PREFIX = "القسم: "


@dataclass(frozen=True)
class Chunk:
    section_title: str
    audience: KBAudience
    content: str
    content_hash: str


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def chunk_text(text: str) -> tuple[Chunk, ...]:
    """Everything before the first `## ` is dropped: in this file that is the
    authoring comment and the H1 title, neither of which is an answer."""
    sections = SECTION_SPLIT.split(text)[1:]
    if not sections:
        raise ValueError("no '## ' sections found — is this the knowledge base?")
    return tuple(_chunk(section) for section in sections)


def chunk_file(path: Path) -> tuple[Chunk, ...]:
    return chunk_text(path.read_text(encoding="utf-8"))


def _chunk(section: str) -> Chunk:
    title, _, rest = section.partition("\n")
    title = title.strip()

    marker = AUDIENCE_MARKER.search(rest)
    if marker is None:
        # Never defaulted: a section with no marker could be internal, and
        # guessing "public" is how internal guidance reaches a customer.
        raise ValueError(f"section {title!r} has no '<!-- audience: ... -->' marker")
    try:
        audience = KBAudience(marker.group(1))
    except ValueError:
        raise ValueError(
            f"section {title!r} has unknown audience {marker.group(1)!r}; "
            f"expected one of {[member.value for member in KBAudience]}"
        ) from None

    body = AUDIENCE_MARKER.sub("", rest).strip()
    if not body:
        raise ValueError(f"section {title!r} has no content")

    content = f"{TITLE_PREFIX}{title}\n\n{body}"
    return Chunk(
        section_title=title,
        audience=audience,
        content=content,
        content_hash=content_hash(content),
    )
