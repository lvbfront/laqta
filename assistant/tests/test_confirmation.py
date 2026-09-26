"""The mandatory-confirmation mechanism (spec §8), at the domain level.
The tool-level view of the same rules is in test_tools_booking.py.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.assistant_domain.confirmation import (
    AwaitingCustomerReply,
    ConfirmationAlreadyUsed,
    ConfirmationExpired,
    ConfirmationNotFound,
    params_hash,
    prepare,
    redeem,
)
from app.models.enums import ConfirmationAction
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import customer_identity, make_contact, make_interaction

PARAMS = {"booking_id": "b-1", "refund_percent": 50}
PREPARED_TURN = 3


@pytest.fixture()
def interaction(db_session):
    contact = make_contact(db_session)
    return make_interaction(db_session, identity=customer_identity(contact))


def prepared(db_session, policy, interaction, *, user_turn=PREPARED_TURN, now=NOW):
    return prepare(
        db_session,
        interaction_id=interaction.id,
        action=ConfirmationAction.cancel,
        params=PARAMS,
        user_turn=user_turn,
        now=now,
        policy=policy,
    )


def test_ttl_comes_from_policy(db_session, policy, interaction):
    confirmation = prepared(db_session, policy, interaction)
    assert confirmation.expires_at == NOW + timedelta(minutes=policy.confirmation_ttl_minutes)
    assert confirmation.used_at is None


def test_a_new_customer_message_lets_it_through(db_session, policy, interaction):
    confirmation = prepared(db_session, policy, interaction)
    redeemed = redeem(
        db_session,
        confirmation.id,
        interaction_id=interaction.id,
        user_turn=PREPARED_TURN + 1,
        now=NOW,
    )
    assert redeemed.used_at == NOW


def test_confirming_in_the_same_turn_fails(db_session, policy, interaction):
    """The case the whole mechanism exists for: the model read the summary
    and "confirmed" without the customer saying anything."""
    confirmation = prepared(db_session, policy, interaction)
    with pytest.raises(AwaitingCustomerReply):
        redeem(
            db_session,
            confirmation.id,
            interaction_id=interaction.id,
            user_turn=PREPARED_TURN,
            now=NOW,
        )
    assert confirmation.used_at is None


def test_an_earlier_turn_also_fails(db_session, policy, interaction):
    confirmation = prepared(db_session, policy, interaction)
    with pytest.raises(AwaitingCustomerReply):
        redeem(
            db_session,
            confirmation.id,
            interaction_id=interaction.id,
            user_turn=PREPARED_TURN - 1,
            now=NOW,
        )


def test_expiry(db_session, policy, interaction):
    confirmation = prepared(db_session, policy, interaction)
    just_alive = confirmation.expires_at - timedelta(seconds=1)
    assert redeem(
        db_session,
        confirmation.id,
        interaction_id=interaction.id,
        user_turn=PREPARED_TURN + 1,
        now=just_alive,
    )

    expired = prepared(db_session, policy, interaction)
    with pytest.raises(ConfirmationExpired):
        redeem(
            db_session,
            expired.id,
            interaction_id=interaction.id,
            user_turn=PREPARED_TURN + 1,
            now=expired.expires_at,
        )


def test_single_use(db_session, policy, interaction):
    confirmation = prepared(db_session, policy, interaction)
    kwargs = {
        "interaction_id": interaction.id,
        "user_turn": PREPARED_TURN + 1,
        "now": NOW,
    }
    redeem(db_session, confirmation.id, **kwargs)
    with pytest.raises(ConfirmationAlreadyUsed):
        redeem(db_session, confirmation.id, **kwargs)


def test_another_session_cannot_use_it(db_session, policy, interaction):
    """And it reports not_found, not forbidden — a token id cannot be probed."""
    confirmation = prepared(db_session, policy, interaction)
    other_contact = make_contact(db_session)
    other = make_interaction(db_session, identity=customer_identity(other_contact))

    with pytest.raises(ConfirmationNotFound):
        redeem(
            db_session,
            confirmation.id,
            interaction_id=other.id,
            user_turn=PREPARED_TURN + 1,
            now=NOW,
        )
    assert confirmation.used_at is None


def test_unknown_id(db_session, interaction):
    with pytest.raises(ConfirmationNotFound):
        redeem(
            db_session,
            uuid.uuid4(),
            interaction_id=interaction.id,
            user_turn=PREPARED_TURN + 1,
            now=NOW,
        )


def test_used_before_expired_when_both_apply(db_session, policy, interaction):
    """Order of checks: a spent token reports already_used even after it
    would also have expired, which is the more accurate message."""
    confirmation = prepared(db_session, policy, interaction)
    redeem(
        db_session,
        confirmation.id,
        interaction_id=interaction.id,
        user_turn=PREPARED_TURN + 1,
        now=NOW,
    )
    with pytest.raises(ConfirmationAlreadyUsed):
        redeem(
            db_session,
            confirmation.id,
            interaction_id=interaction.id,
            user_turn=PREPARED_TURN + 1,
            now=confirmation.expires_at + timedelta(hours=1),
        )


def test_params_hash_is_stable_and_sensitive(db_session, policy, interaction):
    confirmation = prepared(db_session, policy, interaction)
    assert confirmation.params_hash == params_hash(PARAMS)
    assert params_hash(PARAMS) == params_hash(dict(reversed(list(PARAMS.items()))))
    assert params_hash(PARAMS) != params_hash({**PARAMS, "refund_percent": 100})
