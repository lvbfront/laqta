"""A token prepared on a turn whose reply never arrived (spec §8).

`redeem` asks whether a new customer message arrived after the prepare. That
is not the same question as whether the customer ever saw the summary, and
the two come apart whenever a turn ends without a model reply: prepare_*
writes its token, the API call that would have read the summary back never
returns one, and the customer is handed a canned apology instead. The token
is then a single message away from redeemable.

So the loop voids every token a turn prepared unless that turn ended in a
complete model reply. These tests drive the whole path with a scripted
client — the prepare is real, the confirm is real, and the refusal has to
come from the token being dead rather than from anything the fake arranged.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.agent.loop import API_ERROR_MESSAGE, FALLBACK_MESSAGE, REFUSAL_MESSAGE, run_turn
from app.agent.session import AgentSession
from app.assistant_domain.confirmation import ConfirmationExpired, prepare, redeem
from app.config import AGENT_MAX_STEPS
from app.laqta.mock import MockLaqta
from app.models import Booking, Confirmation
from app.models.enums import ConfirmationAction
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import customer_identity, make_contact, make_when
from tests.fakes import (
    FakeClient,
    FakeResponse,
    FakeText,
    calls_tool,
    says,
    transient_api_error,
)

FAR_DAY = date(2026, 10, 15)  # ~34 days out: clears every lead time
SEARCH = {"query": "وش الباقات المتوفرة؟"}
WHEN_ID = "w0000001"
DETAILS = {
    "event_name": "ملتقى الريّان",
    "city": "jeddah",
    "venue": "فندق هيلتون جدة",
    "expected_guests": 400,
    "photographers": 2,
    "match_mode": "face",
    "strict_mode": False,
    "package": "premium",
    "addons": [],
    "onsite_support": False,
}


@pytest.fixture(autouse=True)
def stub_embeddings(monkeypatch):
    """One ending drives the loop round with search_kb; keep the 2GB model
    out of it."""
    from app.config import EMBEDDING_DIM

    monkeypatch.setattr(
        "app.kb.search.embed_query", lambda text: [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    )


@pytest.fixture()
def session(db_session, policy):
    """A customer session with a window already resolved, so a scripted
    prepare_booking needs no resolve_when round trip first. `resolved` is the
    same dict the tool context reads."""
    contact = make_contact(db_session)
    agent = AgentSession.start(
        db_session,
        identity=customer_identity(contact),
        policy=policy,
        laqta=MockLaqta.seeded(),
        now=NOW,
    )
    agent.resolved[WHEN_ID] = make_when(policy, FAR_DAY)
    return agent


def prepares_a_booking() -> FakeResponse:
    return calls_tool("prepare_booking", {"when_id": WHEN_ID, "details": DETAILS})


def only_confirmation(db_session) -> Confirmation:
    rows = db_session.scalars(select(Confirmation)).all()
    assert len(rows) == 1, f"expected exactly one prepared token, got {len(rows)}"
    return rows[0]


def confirm_next_turn(session, confirmation_id, *, text="نعم أكد الحجز"):
    """The customer replies, the model confirms. Returns the confirm_action
    result the model was handed back."""
    client = FakeClient(
        calls_tool("confirm_action", {"confirmation_id": str(confirmation_id)}),
        says("تمام."),
    )
    run_turn(session, text, now=NOW, client=client)
    return json.loads(session.messages[-2]["content"][0]["content"])


# --- The five ways a turn can end without the customer reading a summary.
#
# Each returns the client for turn 1 and the reply the customer is left with.


def ending_api_error():
    client = FakeClient(prepares_a_booking())
    scripted = client.messages.create

    def fail_once_the_script_runs_out(**kwargs):
        if not client.messages.responses:
            raise transient_api_error()
        return scripted(**kwargs)

    client.messages.create = fail_once_the_script_runs_out  # type: ignore[method-assign]
    return client, API_ERROR_MESSAGE


def ending_max_steps():
    # Exactly AGENT_MAX_STEPS tool-calling responses: the loop runs out of
    # steps, hands off, and the customer gets the canned message.
    extra = [calls_tool("search_kb", SEARCH)] * (AGENT_MAX_STEPS - 1)
    return FakeClient(prepares_a_booking(), *extra), FALLBACK_MESSAGE


def ending_refusal():
    return FakeClient(prepares_a_booking(), FakeResponse([], "refusal")), REFUSAL_MESSAGE


def ending_truncated():
    cut_off = FakeResponse([FakeText("تمام، الملخص: حجز «ملتقى الريّان» بتاريخ")], "max_tokens")
    return FakeClient(prepares_a_booking(), cut_off), None  # reply is text + "…"


def ending_empty_reply():
    return FakeClient(prepares_a_booking(), FakeResponse([])), FALLBACK_MESSAGE


ENDINGS = {
    "api_error": ending_api_error,
    "max_steps": ending_max_steps,
    "refusal": ending_refusal,
    "truncated": ending_truncated,
    "empty_reply": ending_empty_reply,
}


@pytest.mark.parametrize("ending", sorted(ENDINGS))
def test_a_token_prepared_on_an_undelivered_turn_cannot_be_confirmed(
    session, db_session, ending
):
    """The customer never read the summary, so the next thing they say must
    not be able to stand as agreement to it."""
    client, expected_reply = ENDINGS[ending]()
    reply = run_turn(session, "أبي أحجز", now=NOW, client=client)
    if expected_reply is not None:
        assert reply == expected_reply

    # The prepare really ran: without this the test would pass on a token
    # that was never written.
    confirmation = only_confirmation(db_session)
    assert confirmation.prepared_at_user_turn == 1
    assert confirmation.used_at is None

    result = confirm_next_turn(session, confirmation.id)

    assert result == {"ok": False, "error": "expired", "detail": "انتهت مدة التأكيد. نبدأ من جديد؟"}
    assert db_session.scalars(select(Booking)).all() == []
    assert db_session.get(Confirmation, confirmation.id).used_at is None


def test_a_delivered_summary_is_still_confirmable_next_turn(session, db_session):
    """The control. If this stops passing, the fix has broken booking."""
    run_turn(
        session,
        "أبي أحجز",
        now=NOW,
        client=FakeClient(prepares_a_booking(), says("الملخص: حجز «ملتقى الريّان»… أأكد؟")),
    )
    confirmation = only_confirmation(db_session)

    result = confirm_next_turn(session, confirmation.id)

    assert result["ok"] is True, result
    assert len(db_session.scalars(select(Booking)).all()) == 1
    assert db_session.get(Confirmation, confirmation.id).used_at is not None


def test_only_the_failing_turns_own_tokens_are_voided(session, db_session):
    """A summary read out on turn 1 was seen. A later turn failing does not
    unsee it, so that token stays good."""
    run_turn(
        session,
        "أبي أحجز",
        now=NOW,
        client=FakeClient(prepares_a_booking(), says("الملخص: … أأكد؟")),
    )
    confirmation = only_confirmation(db_session)
    expires_at = confirmation.expires_at

    # Turn 2 fails, and prepared nothing of its own.
    assert run_turn(session, "لحظة", now=NOW, client=FakeClient(raises=transient_api_error())) == (
        API_ERROR_MESSAGE
    )
    assert db_session.get(Confirmation, confirmation.id).expires_at == expires_at

    assert confirm_next_turn(session, confirmation.id)["ok"] is True
    assert len(db_session.scalars(select(Booking)).all()) == 1


# --- The clock comparison the whole mechanism rests on


def test_expiry_counts_the_instant_itself_as_expired(db_session, policy):
    """Voiding sets `expires_at` to the instant the turn failed, which only
    refuses anything because `redeem` compares `now >= expires_at`.

    Inclusive is load-bearing, not incidental. A fixed clock hands the failing
    turn and the next one the identical `now` — that is how the eval runs
    every episode and how most of these tests run — so under an exclusive
    comparison a voided token would be live on exactly the turn it was
    supposed to stop, and the void would refuse nothing at all.
    """
    interaction_id = _an_interaction(db_session)
    token = prepare(
        db_session,
        interaction_id=interaction_id,
        action=ConfirmationAction.cancel,
        params={"booking_id": "b-1"},
        user_turn=1,
        now=NOW,
        policy=policy,
    )
    token.expires_at = NOW  # what void_prepared_at_turn writes
    db_session.flush()

    with pytest.raises(ConfirmationExpired):
        redeem(db_session, token.id, interaction_id=interaction_id, user_turn=2, now=NOW)

    # The control, one microsecond the other side of the boundary: the turn
    # gap is satisfied either way, so expiry is the only thing being measured.
    token.expires_at = NOW + timedelta(microseconds=1)
    db_session.flush()
    assert redeem(
        db_session, token.id, interaction_id=interaction_id, user_turn=2, now=NOW
    ).used_at == NOW


def test_a_frozen_clock_still_refuses_a_voided_token(session, db_session):
    """The same point end to end, with one `now` shared by both turns rather
    than two that happen to be equal."""
    frozen = NOW
    client, _ = ending_api_error()
    assert run_turn(session, "أبي أحجز", now=frozen, client=client) == API_ERROR_MESSAGE

    confirmation = only_confirmation(db_session)
    assert confirmation.expires_at == frozen, "the void did not land on this token"

    client = FakeClient(
        calls_tool("confirm_action", {"confirmation_id": str(confirmation.id)}),
        says("تمام."),
    )
    run_turn(session, "نعم", now=frozen, client=client)
    result = json.loads(session.messages[-2]["content"][0]["content"])

    assert result["error"] == "expired"
    assert db_session.scalars(select(Booking)).all() == []


def _an_interaction(db_session) -> int:
    from tests.factories import make_interaction

    contact = make_contact(db_session)
    return make_interaction(db_session, identity=customer_identity(contact)).id


# --- When the void itself cannot be written


@pytest.fixture()
def void_write_fails(monkeypatch):
    """The one failure that can leave a token alive: the database.

    Patched at the loop's call site rather than deeper down, because what is
    under test is what run_turn does about it, not how the write breaks.
    """
    from app.agent import loop as agent_loop

    def cannot_write(*_args, **_kwargs):
        raise RuntimeError("server closed the connection unexpectedly")

    monkeypatch.setattr(agent_loop.confirmations, "void_prepared_at_turn", cannot_write)


def test_a_void_that_cannot_be_written_fails_the_turn(session, db_session, void_write_fails):
    """An api_error turn would otherwise return its polite apology with the
    token still live, and nothing above would ever hear about it. The caller
    has to be told the session is finished instead."""
    client, _ = ending_api_error()

    with pytest.raises(RuntimeError, match="server closed the connection"):
        run_turn(session, "أبي أحجز", now=NOW, client=client)

    # The token really is still live — this is the state being refused, not
    # a hypothetical one.
    confirmation = only_confirmation(db_session)
    assert confirmation.expires_at > NOW
    assert confirmation.used_at is None


def test_a_failing_void_does_not_mask_the_real_error(session, void_write_fails):
    """The other half. When run_turn is already failing, the caller is being
    told the turn failed anyway, and the useful exception is the first one."""
    client = FakeClient(prepares_a_booking(), raises=None)
    scripted = client.messages.create

    def fail_hard_once_the_script_runs_out(**kwargs):
        if not client.messages.responses:
            raise ValueError("a bug in our own code")
        return scripted(**kwargs)

    client.messages.create = fail_hard_once_the_script_runs_out  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="a bug in our own code"):
        run_turn(session, "أبي أحجز", now=NOW, client=client)


def test_a_delivered_turn_never_touches_the_void(session, db_session, void_write_fails):
    """A turn that delivered its reply does not void, so a broken void must
    not be able to fail it."""
    reply = run_turn(
        session,
        "أبي أحجز",
        now=NOW,
        client=FakeClient(prepares_a_booking(), says("الملخص: … أأكد؟")),
    )
    assert reply == "الملخص: … أأكد؟"
