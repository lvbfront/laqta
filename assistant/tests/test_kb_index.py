"""Indexing is idempotent and prunes what the file no longer says (spec §11).

A fake embedder throughout: this is about bookkeeping, not relevance, and
the real model is 2GB. tests/test_kb_retrieval.py uses the real one.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.config import EMBEDDING_DIM
from app.kb.chunker import chunk_text
from app.kb.index import index
from app.models.enums import KBAudience
from app.models.kb_chunk import KBChunk

TWO_SECTIONS = """# title

## الباقات
<!-- audience: public -->
الأساسية حتى 300 ضيف.

## سعة التشغيل
<!-- audience: internal -->
فعاليتين في اليوم لكل مدينة.
"""


class FakeEmbedder:
    """Deterministic vectors, and a record of what it was asked to embed."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        return [[float(len(text) % 7) + 1.0] + [0.0] * (EMBEDDING_DIM - 1) for text in texts]

    @property
    def embedded(self) -> list[str]:
        return [text for call in self.calls for text in call]


def test_first_run_indexes_everything(db_session):
    embedder = FakeEmbedder()
    report = index(db_session, chunk_text(TWO_SECTIONS), embed=embedder)

    assert (report.created, report.deleted, report.unchanged) == (2, 0, 0)
    assert db_session.scalar(select(func.count()).select_from(KBChunk)) == 2
    assert len(embedder.embedded) == 2


def test_running_twice_changes_nothing(db_session):
    chunks = chunk_text(TWO_SECTIONS)
    index(db_session, chunks, embed=FakeEmbedder())

    before = sorted(db_session.scalars(select(KBChunk.content_hash)).all())
    embedder = FakeEmbedder()
    report = index(db_session, chunks, embed=embedder)

    assert (report.created, report.deleted, report.unchanged) == (0, 0, 2)
    assert sorted(db_session.scalars(select(KBChunk.content_hash)).all()) == before
    # The expensive part did not happen at all.
    assert embedder.calls == []


def test_a_removed_section_loses_its_row(db_session):
    index(db_session, chunk_text(TWO_SECTIONS), embed=FakeEmbedder())

    shortened = TWO_SECTIONS.split("## سعة التشغيل")[0]
    report = index(db_session, chunk_text(shortened), embed=FakeEmbedder())

    assert (report.created, report.deleted, report.unchanged) == (0, 1, 1)
    titles = db_session.scalars(select(KBChunk.section_title)).all()
    assert titles == ["الباقات"]


def test_an_edited_section_is_replaced_not_duplicated(db_session):
    index(db_session, chunk_text(TWO_SECTIONS), embed=FakeEmbedder())

    edited = TWO_SECTIONS.replace("حتى 300 ضيف", "حتى 350 ضيف")
    embedder = FakeEmbedder()
    report = index(db_session, chunk_text(edited), embed=embedder)

    assert (report.created, report.deleted, report.unchanged) == (1, 1, 1)
    assert db_session.scalar(select(func.count()).select_from(KBChunk)) == 2
    contents = db_session.scalars(select(KBChunk.content)).all()
    assert any("350" in content for content in contents)
    assert not any("300" in content for content in contents)
    # Only the changed section was re-embedded.
    assert len(embedder.embedded) == 1
    assert "350" in embedder.embedded[0]


def test_audience_and_dimension_are_stored(db_session):
    index(db_session, chunk_text(TWO_SECTIONS), embed=FakeEmbedder())

    rows = {row.section_title: row for row in db_session.scalars(select(KBChunk)).all()}
    assert rows["الباقات"].audience is KBAudience.public
    assert rows["سعة التشغيل"].audience is KBAudience.internal
    assert len(rows["الباقات"].embedding) == EMBEDDING_DIM


def test_emptying_the_file_empties_the_table(db_session):
    index(db_session, chunk_text(TWO_SECTIONS), embed=FakeEmbedder())
    report = index(db_session, [], embed=FakeEmbedder())

    assert (report.created, report.deleted, report.unchanged) == (0, 2, 0)
    assert db_session.scalar(select(func.count()).select_from(KBChunk)) == 0
