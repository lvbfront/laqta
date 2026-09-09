from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import StatementError

from app.models.enums import AccountType, PrivacyMode
from app.models.event import STANDARD_RETENTION_DAYS, STRICT_RETENTION_DAYS, Event
from app.models.organization import Organization


def _org(db) -> Organization:
    org = Organization(name="Retention Test Org", account_type=AccountType.organizer)
    db.add(org)
    db.flush()
    return org


def test_standard_event_defaults_retention_to_30_days_after_ends_at(db_session):
    ends_at = datetime.now(timezone.utc) + timedelta(days=1)
    event = Event(
        org_id=_org(db_session).id,
        name_ar="ح",
        name_en="Standard Event",
        ends_at=ends_at,
        consent_text_ar="ar",
        consent_text_en="en",
        privacy_mode=PrivacyMode.standard,
        auto_publish=True,
    )
    db_session.add(event)
    db_session.flush()

    assert STANDARD_RETENTION_DAYS == 30
    assert event.retention_until == ends_at + timedelta(days=30)


def test_strict_event_defaults_retention_to_7_days_after_ends_at(db_session):
    ends_at = datetime.now(timezone.utc) + timedelta(days=1)
    event = Event(
        org_id=_org(db_session).id,
        name_ar="ح",
        name_en="Strict Event",
        ends_at=ends_at,
        consent_text_ar="ar",
        consent_text_en="en",
        privacy_mode=PrivacyMode.strict,
        auto_publish=False,  # required by ck_events_strict_requires_no_autopublish
    )
    db_session.add(event)
    db_session.flush()

    assert STRICT_RETENTION_DAYS == 7
    assert event.retention_until == ends_at + timedelta(days=7)


def test_explicit_retention_until_overrides_the_default(db_session):
    ends_at = datetime.now(timezone.utc) + timedelta(days=1)
    custom_retention = ends_at + timedelta(days=365)  # e.g. a legal hold
    event = Event(
        org_id=_org(db_session).id,
        name_ar="ح",
        name_en="Custom Retention Event",
        ends_at=ends_at,
        retention_until=custom_retention,
        consent_text_ar="ar",
        consent_text_en="en",
        privacy_mode=PrivacyMode.standard,
        auto_publish=True,
    )
    db_session.add(event)
    db_session.flush()

    assert event.retention_until == custom_retention


def test_ends_at_is_required(db_session):
    # Without ends_at, retention_until has nothing to compute a default
    # from -- an event silently missing both is exactly how the purge job
    # would end up with a permanently-unpurgeable event (see
    # app/models/event.py). NOT NULL makes this impossible to construct.
    event = Event(
        org_id=_org(db_session).id,
        name_ar="ح",
        name_en="No End Date Event",
        consent_text_ar="ar",
        consent_text_en="en",
        privacy_mode=PrivacyMode.standard,
        auto_publish=True,
    )
    db_session.add(event)
    # Caught here, client-side, before Postgres's own NOT NULL constraint
    # on ends_at would ever fire: retention_until's default callable needs
    # ends_at to compute anything and raises a clear ValueError (wrapped
    # by SQLAlchemy in StatementError) rather than either silently
    # producing a nonsensical value or failing with an opaque
    # "None + timedelta" TypeError.
    with pytest.raises(StatementError, match="ends_at"):
        db_session.flush()
