from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.booking_state import record_creation
from tests.factories import WELL_BEFORE, make_booking, make_contact


def _saved(db_session, **overrides):
    contact = make_contact(db_session)
    booking = make_booking(contact_id=contact.id, laqta_org_id=contact.laqta_org_id, **overrides)
    record_creation(booking, now=WELL_BEFORE, actor="test")
    db_session.add(booking)
    db_session.flush()
    return booking


def test_two_bookings_cannot_share_one_laqta_event(db_session):
    """What makes the adapter's idempotency key enforced, not just intended."""
    event_id = uuid.uuid4()
    _saved(db_session, laqta_event_id=event_id)
    # In a savepoint, so the failed insert doesn't poison the test
    # transaction the fixture still has to roll back.
    with pytest.raises(IntegrityError, match="uq_bookings_laqta_event_id"):
        with db_session.begin_nested():
            _saved(db_session, laqta_event_id=event_id)


def test_many_bookings_may_await_their_laqta_event(db_session):
    # The index is partial, so NULLs do not collide.
    for _ in range(3):
        _saved(db_session, laqta_event_id=None)
