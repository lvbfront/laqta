from __future__ import annotations

import pytest

from app.config import KB_PATH
from app.kb.chunker import TITLE_PREFIX, chunk_file, chunk_text, content_hash
from app.models.enums import KBAudience

SAMPLE = """<!--
An authoring comment. It mentions that "## " starts a section, which must
not be mistaken for one.
-->

# قاعدة معرفة لقطة

## الباقات
<!-- audience: public -->
الأساسية حتى 300 ضيف.

## سعة التشغيل
<!-- audience: internal -->
حد أقصى فعاليتين في اليوم لكل مدينة.
"""


def test_sections_become_chunks():
    chunks = chunk_text(SAMPLE)
    assert [chunk.section_title for chunk in chunks] == ["الباقات", "سعة التشغيل"]
    assert [chunk.audience for chunk in chunks] == [KBAudience.public, KBAudience.internal]


def test_the_preamble_and_its_comment_are_dropped():
    """The authoring comment says '## ' inside prose; that must not chunk."""
    chunks = chunk_text(SAMPLE)
    assert len(chunks) == 2
    for chunk in chunks:
        assert "authoring comment" not in chunk.content
        assert "قاعدة معرفة لقطة" not in chunk.content


def test_the_title_leads_the_chunk_text():
    """It measurably helps retrieval, so it is part of the indexed content."""
    first = chunk_text(SAMPLE)[0]
    assert first.content.startswith(f"{TITLE_PREFIX}الباقات")
    assert "الأساسية حتى 300 ضيف." in first.content


def test_the_audience_marker_is_not_indexed():
    for chunk in chunk_text(SAMPLE):
        assert "audience:" not in chunk.content


def test_hash_covers_the_title_and_the_body():
    chunks = chunk_text(SAMPLE)
    assert chunks[0].content_hash == content_hash(chunks[0].content)
    assert chunks[0].content_hash != chunks[1].content_hash

    retitled = chunk_text(SAMPLE.replace("## الباقات", "## الباقات والأسعار"))
    assert retitled[0].content_hash != chunks[0].content_hash


def test_chunking_is_deterministic():
    assert chunk_text(SAMPLE) == chunk_text(SAMPLE)


def test_a_section_without_an_audience_marker_is_rejected():
    """Guessing 'public' is how internal guidance reaches a customer."""
    text = SAMPLE.replace("<!-- audience: internal -->\n", "")
    with pytest.raises(ValueError, match="audience"):
        chunk_text(text)


def test_an_unknown_audience_is_rejected():
    text = SAMPLE.replace("audience: internal", "audience: everyone")
    with pytest.raises(ValueError, match="everyone"):
        chunk_text(text)


def test_an_empty_section_is_rejected():
    text = SAMPLE.replace("حد أقصى فعاليتين في اليوم لكل مدينة.\n", "")
    with pytest.raises(ValueError, match="no content"):
        chunk_text(text)


def test_a_file_with_no_sections_is_rejected():
    with pytest.raises(ValueError, match="no '## ' sections"):
        chunk_text("# just a title\n\nsome prose\n")


# --- Against the real knowledge base


def test_the_real_kb_chunks_cleanly():
    chunks = chunk_file(KB_PATH)
    assert len(chunks) == 19

    audiences = [chunk.audience for chunk in chunks]
    assert audiences.count(KBAudience.public) == 14
    assert audiences.count(KBAudience.internal) == 5

    titles = [chunk.section_title for chunk in chunks]
    assert len(set(titles)) == len(titles)  # unique, so a hit names one section
    assert "الباقات" in titles
    assert "سعة التشغيل" in titles


def test_the_real_kb_has_unique_hashes():
    chunks = chunk_file(KB_PATH)
    assert len({chunk.content_hash for chunk in chunks}) == len(chunks)
