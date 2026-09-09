from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.face import Face
from tests.factories import make_event, make_organization, make_photo


def test_face_event_id_must_match_its_photos_event_id(db_session):
    """A face's event_id is denormalized from its photo's event_id purely
    for query performance (see app/models/face.py) -- it must never be
    able to disagree with the photo it actually belongs to, since that
    would let a guest at one event match a face that belongs to another.
    The composite FK (photo_id, event_id) -> photos(id, event_id) makes a
    mismatched pair structurally impossible to insert, not just a
    convention app.workers.jobs happens to follow.
    """
    org = make_organization(db_session)
    event_a = make_event(db_session, org, name_en="Event A")
    event_b = make_event(db_session, org, name_en="Event B")
    photo_in_a = make_photo(db_session, event_a)

    mismatched = Face(
        photo_id=photo_in_a.id,
        event_id=event_b.id,  # wrong on purpose: photo_in_a belongs to event_a
        bbox_x1=0.0,
        bbox_y1=0.0,
        bbox_x2=100.0,
        bbox_y2=100.0,
        det_score=0.9,
        embedding=[0.01] * 512,
    )
    db_session.add(mismatched)
    with pytest.raises(IntegrityError):
        db_session.flush()
