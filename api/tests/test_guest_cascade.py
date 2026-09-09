from __future__ import annotations

from app.models.download import Download
from app.models.guest import Guest
from app.models.guest_face import GuestFace
from app.models.match import Match
from tests.factories import in_days, make_event, make_organization, make_photo, now_utc


def test_deleting_guest_cascades_to_guest_faces_matches_and_downloads(db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event)

    guest = Guest(event_id=event.id, consent_at=now_utc(), session_token="tok-cascade-test")
    db_session.add(guest)
    db_session.flush()

    db_session.add(GuestFace(guest_id=guest.id, embedding=[0.01] * 512, expires_at=in_days(30)))
    db_session.add(Match(guest_id=guest.id, photo_id=photo.id, score=0.5))
    db_session.add(Download(guest_id=guest.id, photo_id=photo.id))
    db_session.flush()

    assert db_session.query(GuestFace).count() == 1
    assert db_session.query(Match).count() == 1
    assert db_session.query(Download).count() == 1

    db_session.delete(guest)
    db_session.flush()

    assert db_session.query(Guest).count() == 0
    assert db_session.query(GuestFace).count() == 0, "guest_faces row survived guest deletion"
    assert db_session.query(Match).count() == 0, "matches row survived guest deletion"
    assert db_session.query(Download).count() == 0, "downloads row survived guest deletion"
