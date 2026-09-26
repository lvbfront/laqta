"""The end-of-session summary (spec §12), with a scripted client."""

from __future__ import annotations

import pytest

from app.agent.session import AgentSession
from app.agent.summarize import SessionSummary, readable_transcript, summarize_session
from app.config import settings
from app.laqta.mock import MockLaqta
from app.models.interaction import Interaction
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import customer_identity, make_contact
from tests.fakes import FakeClient

SUMMARY = SessionSummary(
    summary_ar="سأل عن الباقات وحجز مبدئياً ملتقى الريّان يوم ١٧ سبتمبر في جدة.",
    outcome="booked",
)


@pytest.fixture()
def session(db_session, policy):
    contact = make_contact(db_session)
    return AgentSession.start(
        db_session,
        identity=customer_identity(contact),
        policy=policy,
        laqta=MockLaqta.seeded(),
        now=NOW,
    )


def test_the_summary_and_outcome_are_stored_on_the_interaction(session, db_session):
    session.add_user_message("أبغى أحجز فعالية")
    session.add_assistant_content([_text("أبشر، وش اسم الفعالية؟")])

    client = FakeClient(parsed=SUMMARY)
    result = summarize_session(session, now=NOW, client=client)

    assert result == SUMMARY
    stored = db_session.get(Interaction, session.interaction.id)
    assert stored.summary == SUMMARY.summary_ar
    assert stored.outcome == "booked"
    assert stored.ended_at == NOW
    assert client.messages.parse_calls[0]["model"] == settings.summary_model


def test_a_silent_session_is_closed_as_abandoned(session, db_session):
    client = FakeClient(parsed=SUMMARY)
    assert summarize_session(session, now=NOW, client=client) is None

    stored = db_session.get(Interaction, session.interaction.id)
    assert stored.outcome == "abandoned"
    assert stored.summary is None
    # Nothing was sent to the model, because there was nothing to summarise.
    assert client.messages.parse_calls == []


def test_the_transcript_sent_for_summary_is_only_what_was_said(session):
    """Tool plumbing is already in tool_calls; feeding it to the summariser
    invites a summary about tools instead of about the customer."""
    session.add_user_message("وش الباقات؟")
    session.add_assistant_content(
        [_tool_use("search_kb", {"query": "الباقات"}), _text("عندنا ثلاث باقات.")]
    )
    session.add_tool_results(
        [{"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"ok": true}'}]
    )

    transcript = readable_transcript(session)
    assert "العميل: وش الباقات؟" in transcript
    assert "المساعد: عندنا ثلاث باقات." in transcript
    assert "search_kb" not in transcript
    assert "tool_result" not in transcript


def test_the_outcome_label_is_constrained():
    with pytest.raises(ValueError):
        SessionSummary(summary_ar="...", outcome="مبسوط")


class _Block:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, **_kwargs):
        return self.payload


def _text(text: str):
    return _Block({"type": "text", "text": text})


def _tool_use(name: str, tool_input: dict):
    return _Block({"type": "tool_use", "id": "toolu_1", "name": name, "input": tool_input})
