from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.enums import AccountType, EventStatus, MatchMode, PhotoStatus, PrivacyMode
from app.models.event import Event
from app.models.organization import Organization
from app.models.photo import Photo

router = APIRouter(tags=["events"])

DEFAULT_CONSENT_AR = (
    "بموافقتك، سنستخدم صورة وجهك لبضع ثوانٍ فقط للبحث عن صورك في هذا الحدث. "
    "لا يتم حفظ صورتك على الإطلاق — يُحسب منها رمز رقمي فقط، ثم تُحذف فورًا."
)
DEFAULT_CONSENT_EN = (
    "By consenting, your face will be used for a few seconds only to find your photos from "
    "this event. Your selfie is never stored — only a numeric code is computed from it, then it's discarded."
)

# Phase 1 has no login/auth system at all (never part of the numbered
# backend steps) -- the dashboard operates against a single, implicit
# development organization rather than real multi-tenant accounts. This
# is a deliberate, documented Phase 1 simplification, not an oversight;
# see the README's "Dashboard API" section.
_DEFAULT_ORG_NAME = "Dev Organization"


class EventPublic(BaseModel):
    id: uuid.UUID
    name_ar: str
    name_en: str
    consent_text_ar: str
    consent_text_en: str
    privacy_mode: str
    match_mode: str
    status: str


class EventDetail(EventPublic):
    qr_token: str
    starts_at: datetime | None
    ends_at: datetime
    retention_until: datetime
    auto_publish: bool
    photo_count: int
    ready_photo_count: int
    pending_photo_count: int


class EventCreate(BaseModel):
    name_ar: str
    name_en: str
    ends_at: datetime
    starts_at: datetime | None = None
    privacy_mode: PrivacyMode = PrivacyMode.standard
    match_mode: MatchMode = MatchMode.face
    consent_text_ar: str | None = None
    consent_text_en: str | None = None


def _event_to_detail(db: Session, event: Event) -> EventDetail:
    photos = db.query(Photo).filter(Photo.event_id == event.id)
    total = photos.count()
    ready = photos.filter(Photo.status == PhotoStatus.ready).count()
    pending = photos.filter(Photo.status.in_([PhotoStatus.pending, PhotoStatus.processing])).count()
    return EventDetail(
        id=event.id,
        name_ar=event.name_ar,
        name_en=event.name_en,
        consent_text_ar=event.consent_text_ar,
        consent_text_en=event.consent_text_en,
        privacy_mode=event.privacy_mode.value,
        match_mode=event.match_mode.value,
        status=event.status.value,
        qr_token=event.qr_token,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        retention_until=event.retention_until,
        auto_publish=event.auto_publish,
        photo_count=total,
        ready_photo_count=ready,
        pending_photo_count=pending,
    )


@router.get("/api/events/by-token/{qr_token}", response_model=EventPublic)
def get_event_by_qr_token(qr_token: str, db: Annotated[Session, Depends(get_db)]) -> EventPublic:
    """Public, unauthenticated -- the qr_token itself is the access
    control (unguessable, see Event._generate_qr_token). This is the only
    lookup the guest-facing /e/[qr_token] page needs before consent.
    """
    event = db.query(Event).filter(Event.qr_token == qr_token).first()
    if event is None:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "Event not found."})
    return EventPublic(
        id=event.id,
        name_ar=event.name_ar,
        name_en=event.name_en,
        consent_text_ar=event.consent_text_ar,
        consent_text_en=event.consent_text_en,
        privacy_mode=event.privacy_mode.value,
        match_mode=event.match_mode.value,
        status=event.status.value,
    )


@router.get("/api/events/{event_id}", response_model=EventDetail)
def get_event(event_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> EventDetail:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "Event not found."})
    return _event_to_detail(db, event)


@router.get("/api/dashboard/organization")
def get_default_organization(db: Annotated[Session, Depends(get_db)]) -> dict:
    """Get-or-create the single implicit dev organization the dashboard
    operates against (no auth system exists to pick a real one from).
    """
    org = db.query(Organization).filter(Organization.name == _DEFAULT_ORG_NAME).first()
    if org is None:
        org = Organization(name=_DEFAULT_ORG_NAME, account_type=AccountType.organizer)
        db.add(org)
        db.commit()
    return {"id": str(org.id), "name": org.name}


@router.get("/api/organizations/{org_id}/events", response_model=list[EventDetail])
def list_org_events(org_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> list[EventDetail]:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail={"code": "organization_not_found", "message": "Organization not found."})
    events = db.query(Event).filter(Event.org_id == org_id).order_by(Event.created_at.desc()).all()
    return [_event_to_detail(db, e) for e in events]


@router.post("/api/organizations/{org_id}/events", response_model=EventDetail, status_code=201)
def create_event(org_id: uuid.UUID, body: EventCreate, db: Annotated[Session, Depends(get_db)]) -> EventDetail:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail={"code": "organization_not_found", "message": "Organization not found."})

    event = Event(
        org_id=org_id,
        name_ar=body.name_ar,
        name_en=body.name_en,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        status=EventStatus.active,
        consent_text_ar=body.consent_text_ar or DEFAULT_CONSENT_AR,
        consent_text_en=body.consent_text_en or DEFAULT_CONSENT_EN,
        privacy_mode=body.privacy_mode,
        match_mode=body.match_mode,
        # DB check constraint forces this false for strict events
        # regardless -- see ck_events_strict_requires_no_autopublish.
        auto_publish=(body.privacy_mode == PrivacyMode.standard),
    )
    db.add(event)
    db.commit()
    return _event_to_detail(db, event)
