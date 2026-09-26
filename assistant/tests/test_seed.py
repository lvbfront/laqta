from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.identity.dev_auth import DevAuth
from app.laqta.fixtures import SEED_JEDDAH_EVENT_ID, SEED_ORGANIZERS
from app.models import Booking, BookingEvent, Contact, Staff
from app.models.enums import BookingStatus, Team
from scripts.seed import is_seeded, reset, seed

NOW = datetime(2026, 9, 11, 11, 5, tzinfo=timezone.utc)  # Fri 14:05 Riyadh


@pytest.fixture()
def seeded(db_session, policy):
    return seed(db_session, now=NOW, policy=policy)


def _counts(session) -> dict[str, int]:
    return {
        model.__name__: session.scalar(select(func.count()).select_from(model))
        for model in (Staff, Contact, Booking, BookingEvent)
    }


def test_four_teams_each_with_a_manager_and_two_staff(db_session, seeded):
    staff = db_session.scalars(select(Staff)).all()
    assert Counter(s.team for s in staff) == {t: 3 for t in Team}
    for team in Team:
        members = [s for s in staff if s.team == team]
        managers = [s for s in members if s.manager_id is None]
        assert len(managers) == 1
        assert all(s.manager_id == managers[0].id for s in members if s is not managers[0])


def test_three_organizers_linked_to_mock_laqta_accounts(db_session, seeded):
    contacts = db_session.scalars(select(Contact).order_by(Contact.id)).all()
    assert [(c.laqta_user_id, c.laqta_org_id) for c in contacts] == [
        (o.user.id, o.user.org_id) for o in SEED_ORGANIZERS
    ]
    for contact in contacts:
        assert DevAuth(db_session).parse(f"customer:{contact.id}").contact_id == contact.id


def test_one_onsite_jeddah_booking_leaving_one_slot(db_session, seeded, policy):
    booking = seeded.jeddah_booking
    assert db_session.scalar(select(func.count()).select_from(Booking)) == 1
    assert (booking.city, booking.onsite_support, booking.status) == (
        "jeddah", True, BookingStatus.confirmed,
    )
    assert booking.laqta_event_id == SEED_JEDDAH_EVENT_ID
    assert booking.contact_id == seeded.contacts[0].id
    # The race test needs exactly one slot left on that day.
    assert policy.onsite.max_events_per_city_per_day - 1 == 1


def test_seed_booking_respects_policy(seeded, policy):
    booking = seeded.jeddah_booking
    assert booking.starts_at - NOW >= timedelta(hours=policy.lead_time_hours.onsite)
    assert booking.starts_at.astimezone(policy.tz).date() == booking.ends_at.astimezone(policy.tz).date()
    assert booking.payment_due_at == min(
        NOW + timedelta(hours=policy.payment_deadline.after_tentative_hours),
        booking.starts_at - timedelta(hours=policy.payment_deadline.before_start_hours),
    )


def test_seed_booking_history_comes_from_the_state_machine(db_session, seeded):
    booking = seeded.jeddah_booking
    events = db_session.scalars(
        select(BookingEvent).where(BookingEvent.booking_id == booking.id).order_by(BookingEvent.id)
    ).all()
    assert [(e.from_status, e.to_status) for e in events] == [
        (None, BookingStatus.tentative),
        (BookingStatus.tentative, BookingStatus.confirmed),
    ]
    assert [e.trigger for e in events] == ["confirm_booking", "mark_paid"]
    assert booking.version == 2  # created, then paid


# --- Idempotency


def test_seeding_twice_changes_nothing(db_session, policy, seeded):
    before = _counts(db_session)
    again = seed(db_session, now=NOW + timedelta(days=1), policy=policy)

    assert _counts(db_session) == before
    assert again.jeddah_booking.id == seeded.jeddah_booking.id
    assert [c.id for c in again.contacts] == [c.id for c in seeded.contacts]
    assert [s.id for s in again.staff] == [s.id for s in seeded.staff]
    assert again.jeddah_booking.version == 2  # not re-transitioned


def test_seeding_twice_leaves_one_row_per_natural_key(db_session, policy, seeded):
    seed(db_session, now=NOW, policy=policy)
    emails = db_session.scalars(select(Staff.email)).all()
    assert len(emails) == len(set(emails))
    user_ids = db_session.scalars(select(Contact.laqta_user_id)).all()
    assert len(user_ids) == len(set(user_ids))


def test_partially_seeded_database_is_completed(db_session, policy, seeded):
    """Half a seed (say, an interrupted run) fills in rather than duplicating."""
    db_session.delete(db_session.scalars(select(Staff).where(Staff.manager_id.is_not(None))).first())
    db_session.flush()
    assert db_session.scalar(select(func.count()).select_from(Staff)) == 11

    seed(db_session, now=NOW, policy=policy)
    assert db_session.scalar(select(func.count()).select_from(Staff)) == 12


# --- Options


def test_explicit_jeddah_date(db_session, policy):
    result = seed(db_session, now=NOW, policy=policy, jeddah_date=date(2026, 10, 1))
    assert result.jeddah_booking.starts_at.astimezone(policy.tz).date() == date(2026, 10, 1)


def test_refuses_a_date_inside_the_onsite_lead_time(db_session, policy):
    with pytest.raises(ValueError, match="lead time"):
        seed(db_session, now=NOW, policy=policy, jeddah_date=NOW.date() + timedelta(days=1))


def test_reset_wipes_and_allows_reseeding(db_session, seeded, policy):
    assert is_seeded(db_session)
    reset(db_session)
    assert not is_seeded(db_session)
    assert db_session.scalar(select(func.count()).select_from(Staff)) == 0

    seed(db_session, now=NOW, policy=policy)
    assert db_session.scalar(select(func.count()).select_from(Contact)) == len(SEED_ORGANIZERS)
