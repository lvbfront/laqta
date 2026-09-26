"""Retrieval quality and the audience boundary (spec §11).

The one test module that loads the real BGE-M3 model (~2GB, cached after the
first run). Marked `kb`, so `pytest -m "not kb"` skips it for a fast loop.

Questions and their acceptable sections live in kb_questions.yaml.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config import KB_MIN_SCORE, KB_PATH
from app.identity.identity import Identity
from app.kb.chunker import chunk_file
from app.kb.embedder import embed
from app.kb.search import audiences_for, search
from app.models.enums import KBAudience
from app.models.kb_chunk import KBChunk
from app.tools import registry
from tests.factories import customer_identity, make_contact, make_tool_context

pytestmark = pytest.mark.kb

QUESTIONS = yaml.safe_load((Path(__file__).parent / "kb_questions.yaml").read_text("utf-8"))
PUBLIC = QUESTIONS["public"]
INTERNAL = QUESTIONS["internal"]
OFF_TOPIC = QUESTIONS["off_topic"]

# Measured by test_the_threshold_separates_answers_from_noise below; raise
# them if a change improves retrieval, never lower them to make a
# regression pass.
MIN_HIT_AT_1 = 0.70
MIN_HIT_AT_3 = 0.90
# Four of the five internal questions. See test_staff_can_reach_internal_sections
# for the one that misses and why it is recorded rather than tuned away.
MIN_INTERNAL_HIT_AT_3 = 0.80

ALL_QUERIES = [item["q"] for item in PUBLIC + INTERNAL] + list(OFF_TOPIC)


@pytest.fixture(scope="session")
def kb_chunks():
    return chunk_file(KB_PATH)


@pytest.fixture(scope="session")
def internal_titles(kb_chunks):
    titles = {
        chunk.section_title for chunk in kb_chunks if chunk.audience is KBAudience.internal
    }
    assert titles, "the knowledge base has no internal sections to protect"
    return titles


@pytest.fixture(scope="session")
def chunk_vectors(kb_chunks):
    """One model load, one pass over the knowledge base."""
    return embed([chunk.content for chunk in kb_chunks])


@pytest.fixture(scope="session")
def query_vectors():
    return dict(zip(ALL_QUERIES, embed(ALL_QUERIES), strict=True))


@pytest.fixture(autouse=True)
def stub_query_embedding(monkeypatch, query_vectors):
    """Queries are embedded once for the session and looked up by exact text;
    an unknown query raises rather than quietly loading the model again."""
    monkeypatch.setattr("app.kb.search.embed_query", lambda text: query_vectors[text])


@pytest.fixture()
def indexed_kb(db_session, kb_chunks, chunk_vectors):
    for chunk, vector in zip(kb_chunks, chunk_vectors, strict=True):
        db_session.add(
            KBChunk(
                section_title=chunk.section_title,
                audience=chunk.audience,
                content=chunk.content,
                content_hash=chunk.content_hash,
                embedding=vector,
            )
        )
    db_session.flush()


def titles_for(db_session, query: str, *, identity_kind: str, min_score: float = KB_MIN_SCORE):
    return [
        hit.section_title
        for hit in search(db_session, query, identity_kind=identity_kind, min_score=min_score)
    ]


# --- Quality


def test_hit_rates(indexed_kb, db_session):
    at_1 = 0
    at_3 = 0
    misses = []

    for item in PUBLIC:
        acceptable = set(item["sections"])
        titles = titles_for(db_session, item["q"], identity_kind="customer")
        if titles and titles[0] in acceptable:
            at_1 += 1
        if acceptable & set(titles):
            at_3 += 1
        else:
            misses.append((item["q"], titles))

    total = len(PUBLIC)
    assert at_3 / total >= MIN_HIT_AT_3, f"hit@3 {at_3}/{total}; misses: {misses}"
    assert at_1 / total >= MIN_HIT_AT_1, f"hit@1 {at_1}/{total}; misses: {misses}"


def test_the_threshold_separates_answers_from_noise(indexed_kb, db_session):
    """KB_MIN_SCORE has to sit between the worst real answer and the best
    off-topic match. Too high and the assistant refuses good questions; too
    low and it answers from a loosely-related section instead of handing
    off. This assertion is where that number comes from."""
    correct = []
    for item in PUBLIC:
        acceptable = set(item["sections"])
        hits = search(db_session, item["q"], identity_kind="customer", min_score=0.0)
        best = next((hit for hit in hits if hit.section_title in acceptable), None)
        if best is not None:
            correct.append((round(best.score, 3), item["q"]))

    noise = []
    for query in OFF_TOPIC:
        hits = search(db_session, query, identity_kind="customer", min_score=0.0)
        noise.append((round(hits[0].score, 3) if hits else 0.0, query))

    worst_correct = min(correct)
    best_noise = max(noise)
    summary = (
        f"KB_MIN_SCORE={KB_MIN_SCORE} | worst correct {worst_correct} | "
        f"best off-topic {best_noise} | margin below {round(KB_MIN_SCORE - best_noise[0], 3)} | "
        f"margin above {round(worst_correct[0] - KB_MIN_SCORE, 3)}"
    )
    # Printed, not just asserted: this is the measurement the constant comes
    # from, and it is worth reading on a `pytest -s` run rather than only
    # when it breaks.
    print(f"\nthreshold measurement: {summary}")

    assert best_noise[0] < KB_MIN_SCORE <= worst_correct[0], f"does not separate — {summary}"


@pytest.mark.parametrize("query", OFF_TOPIC)
def test_off_topic_questions_return_nothing(indexed_kb, db_session, query):
    assert titles_for(db_session, query, identity_kind="customer") == []


def test_the_tool_reports_no_relevant_section(indexed_kb, db_session, policy):
    contact = make_contact(db_session)
    ctx = make_tool_context(db_session, policy, identity=customer_identity(contact))

    result = registry.execute("search_kb", {"query": OFF_TOPIC[0]}, ctx=ctx)
    assert result["ok"] is True
    assert result["data"] == {"results": [], "note": "no_relevant_section"}


def test_a_good_question_comes_back_with_content(indexed_kb, db_session, policy):
    contact = make_contact(db_session)
    ctx = make_tool_context(db_session, policy, identity=customer_identity(contact))

    result = registry.execute("search_kb", {"query": PUBLIC[0]["q"]}, ctx=ctx)
    assert result["ok"] is True
    assert result["data"]["results"]
    assert result["data"]["results"][0]["section"] in set(PUBLIC[0]["sections"])
    assert "الباقات" in result["data"]["results"][0]["content"]


# --- The audience boundary


@pytest.mark.parametrize("identity_kind", ["customer", "anonymous"])
def test_internal_sections_are_never_retrievable(
    indexed_kb, db_session, internal_titles, identity_kind
):
    """Every question, including the ones written to target internal
    sections, at min_score=0 so results are forced. What keeps internal
    guidance out is the SQL audience filter, not the relevance threshold."""
    for item in INTERNAL + PUBLIC:
        titles = titles_for(db_session, item["q"], identity_kind=identity_kind, min_score=0.0)
        leaked = internal_titles & set(titles)
        assert not leaked, f"{identity_kind} retrieved {leaked} for {item['q']!r}"


def test_internal_questions_answer_nothing_for_a_customer(indexed_kb, db_session):
    """At the real threshold, the internal questions mostly find nothing at
    all — which is what makes the assistant hand off rather than improvise."""
    answered = {
        item["q"]: titles_for(db_session, item["q"], identity_kind="customer")
        for item in INTERNAL
    }
    assert all(
        set(item["sections"]).isdisjoint(answered[item["q"]]) for item in INTERNAL
    ), answered


def test_staff_can_reach_internal_sections(indexed_kb, db_session):
    """The counterpart: the filter is by audience, not a blanket ban.

    A rate rather than all five, because one question genuinely misses:
    "أي فريق مسؤول عن تمديد فعالية شغالة؟" is answered by a single bullet
    inside a long internal section ("تمديد الفعاليات" under العمليات), and
    three sections that share more vocabulary with the question outrank it.
    Spec §11 fixes one chunk per `## ` section, so that is a known limit of
    section-level retrieval, not something to tune away here — it is exactly
    the kind of miss layer 2's eval set should track.
    """
    found: list[str] = []
    misses: list[tuple[str, list[str]]] = []

    for item in INTERNAL:
        titles = titles_for(db_session, item["q"], identity_kind="staff", min_score=0.0)
        if set(item["sections"]) & set(titles):
            found.append(item["q"])
        else:
            misses.append((item["q"], titles))

    assert len(found) / len(INTERNAL) >= MIN_INTERNAL_HIT_AT_3, misses


def test_the_tool_gives_a_customer_no_internal_content(
    indexed_kb, db_session, policy, internal_titles
):
    contact = make_contact(db_session)
    ctx = make_tool_context(db_session, policy, identity=customer_identity(contact))

    for item in INTERNAL:
        result = registry.execute("search_kb", {"query": item["q"]}, ctx=ctx)
        sections = {entry["section"] for entry in result["data"]["results"]}
        assert not internal_titles & sections, (item["q"], sections)


def test_anonymous_visitors_get_the_same_public_view(indexed_kb, db_session):
    assert audiences_for("anonymous") == audiences_for("customer") == (KBAudience.public,)
    assert KBAudience.internal in audiences_for("staff")


def test_an_unknown_role_gets_nothing():
    """Fail closed: a typo in a role name must not default to public."""
    with pytest.raises(ValueError, match="unknown identity kind"):
        audiences_for("moderator")


def test_identity_kinds_are_all_mapped():
    for kind in ("anonymous", "customer", "staff"):
        assert audiences_for(kind)
    assert Identity(kind="anonymous").kind == "anonymous"
