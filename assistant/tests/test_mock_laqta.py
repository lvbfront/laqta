from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.laqta.adapter import LaqtaNotFound
from app.laqta.fixtures import SEED_ORGANIZERS
from app.laqta.mock import STATUS_CLOSED, STATUS_DRAFT, MockLaqta
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import make_contact, make_onsite_booking

ORG_ID = uuid.uuid4()
WINDOW = (NOW + timedelta(days=30), NOW + timedelta(days=30, hours=7))


def create(mock: MockLaqta, *, key: str = "booking-1", **overrides):
    kwargs = {
        "idempotency_key": key,
        "org_id": ORG_ID,
        "name_ar": "حفل",
        "starts_at": WINDOW[0],
        "ends_at": WINDOW[1],
        "match_mode": "face",
        "privacy_mode": "standard",
    }
    kwargs.update(overrides)
    return mock.create_event(**kwargs)


def test_create_event_returns_a_laqta_shaped_event():
    mock = MockLaqta()
    event = create(mock)
    assert event.org_id == ORG_ID
    assert event.name_ar == "حفل"
    assert (event.starts_at, event.ends_at) == WINDOW
    assert event.status == STATUS_DRAFT
    assert mock.get_event(event.id) == event


def test_the_same_idempotency_key_returns_the_same_event():
    """spec §9: the key is booking.id, so a retried confirm must not create a
    second Laqta event."""
    mock = MockLaqta()
    first = create(mock, key="booking-42")
    second = create(mock, key="booking-42", name_ar="اسم مختلف")

    assert second is first
    assert second.name_ar == "حفل"  # the retry did not overwrite anything
    assert len(mock.calls_named("create_event")) == 2  # both calls recorded
    assert len({event.id for event in (first, second)}) == 1


def test_different_keys_create_different_events():
    mock = MockLaqta()
    assert create(mock, key="a").id != create(mock, key="b").id


def test_strict_privacy_mode_is_passed_through():
    mock = MockLaqta()
    event = create(mock, privacy_mode="strict")
    assert event.privacy_mode == "strict"
    assert mock.calls_named("create_event")[0]["privacy_mode"] == "strict"


def test_update_event_window():
    mock = MockLaqta()
    event = create(mock)
    moved = (WINDOW[0] + timedelta(days=7), WINDOW[1] + timedelta(days=7))

    updated = mock.update_event_window(event.id, *moved)
    assert (updated.starts_at, updated.ends_at) == moved
    assert updated.id == event.id
    assert mock.get_event(event.id).starts_at == moved[0]


def test_cancel_event_closes_it():
    mock = MockLaqta()
    event = create(mock)
    mock.cancel_event(event.id)
    assert mock.get_event(event.id).status == STATUS_CLOSED


@pytest.mark.parametrize(
    "call",
    [
        lambda mock: mock.get_event(uuid.uuid4()),
        lambda mock: mock.update_event_window(uuid.uuid4(), *WINDOW),
        lambda mock: mock.cancel_event(uuid.uuid4()),
        lambda mock: mock.get_user(uuid.uuid4()),
    ],
)
def test_unknown_ids_raise_not_found(call):
    with pytest.raises(LaqtaNotFound):
        call(MockLaqta())


def test_seeded_knows_the_seeded_organizers():
    mock = MockLaqta.seeded()
    for organizer in SEED_ORGANIZERS:
        assert mock.get_user(organizer.user.id) == organizer.user


def test_seeded_rehydrates_events_from_existing_bookings(db_session, policy):
    """Because this adapter is in-memory: without rehydration a booking made
    in one CLI run would point at an event the next run never heard of."""
    contact = make_contact(db_session)
    booking = make_onsite_booking(
        db_session,
        policy,
        NOW.date() + timedelta(days=30),
        contact_id=contact.id,
        laqta_event_id=uuid.uuid4(),
    )

    mock = MockLaqta.seeded(db_session)
    event = mock.get_event(booking.laqta_event_id)
    assert event.name_ar == booking.event_name
    assert event.starts_at == booking.starts_at
    # And the idempotency key still maps, so a retry stays idempotent.
    assert create(mock, key=str(booking.id)) is event


def test_calls_are_recorded_in_order():
    mock = MockLaqta()
    event = create(mock)
    mock.get_event(event.id)
    mock.cancel_event(event.id)
    assert [name for name, _ in mock.calls] == ["create_event", "get_event", "cancel_event"]
