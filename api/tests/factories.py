from __future__ import annotations

import math
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.face import Face
from app.models.enums import AccountType, EventStatus, MatchMode, PhotoStatus, PrivacyMode
from app.models.organization import Organization
from app.models.photo import Photo


def make_organization(db: Session, **kwargs) -> Organization:
    org = Organization(
        name=kwargs.get("name", "Test Org"),
        account_type=kwargs.get("account_type", AccountType.organizer),
    )
    db.add(org)
    db.flush()
    return org


def make_event(db: Session, org: Organization | None = None, **kwargs) -> Event:
    org = org or make_organization(db)
    event = Event(
        org_id=org.id,
        name_ar=kwargs.get("name_ar", "حدث تجريبي"),
        name_en=kwargs.get("name_en", "Test Event"),
        status=kwargs.get("status", EventStatus.active),
        consent_text_ar=kwargs.get("consent_text_ar", "نص الموافقة"),
        consent_text_en=kwargs.get("consent_text_en", "Consent text"),
        privacy_mode=kwargs.get("privacy_mode", PrivacyMode.standard),
        match_mode=kwargs.get("match_mode", MatchMode.face),
        auto_publish=kwargs.get("auto_publish", True),
    )
    db.add(event)
    db.flush()
    return event


def make_photo(db: Session, event: Event, **kwargs) -> Photo:
    original_key = kwargs.get("s3_key_original", f"events/{event.id}/photos/{uuid.uuid4()}/original.jpg")
    photo = Photo(
        event_id=event.id,
        s3_key_original=original_key,
        # Realistic post-worker shape by default -- a photo that's ready
        # enough to be published/matched always has these set together
        # (see app/workers/jobs.py).
        s3_key_thumbnail=kwargs.get("s3_key_thumbnail", original_key.replace("original.jpg", "thumbnail.jpg")),
        s3_key_preview=kwargs.get("s3_key_preview", original_key.replace("original.jpg", "preview.jpg")),
        md5=kwargs.get("md5", uuid.uuid4().hex),
        status=kwargs.get("status", PhotoStatus.ready),
        published=kwargs.get("published", True),
    )
    db.add(photo)
    db.flush()
    return photo


def make_face(db: Session, photo: Photo, embedding: list[float], det_score: float = 0.9) -> Face:
    face = Face(
        photo_id=photo.id,
        event_id=photo.event_id,
        bbox_x1=0.0,
        bbox_y1=0.0,
        bbox_x2=100.0,
        bbox_y2=100.0,
        det_score=det_score,
        embedding=embedding,
    )
    db.add(face)
    return face


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def in_days(days: int) -> datetime:
    return now_utc() + timedelta(days=days)


def random_unit_vector(dim: int = 512, seed: int | None = None) -> list[float]:
    rng = random.Random(seed)
    v = [rng.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def biased_unit_vector(base: list[float], cosine_target: float, seed: int | None = None) -> list[float]:
    """Build a unit vector with cosine similarity ~= cosine_target to `base`."""
    rng = random.Random(seed)
    dim = len(base)
    noise = [rng.gauss(0, 1) for _ in range(dim)]
    dot = sum(a * b for a, b in zip(base, noise))
    noise = [n - dot * b for n, b in zip(noise, base)]
    noise_norm = math.sqrt(sum(x * x for x in noise))
    noise = [x / noise_norm for x in noise]

    alpha = cosine_target
    beta = math.sqrt(max(0.0, 1 - alpha**2))
    v = [alpha * b + beta * n for b, n in zip(base, noise)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]
