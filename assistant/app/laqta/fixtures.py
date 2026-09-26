"""Fake Laqta accounts shared by scripts/seed.py (the `contacts` side) and
MockLaqta (the Laqta side), so the two agree on ids across processes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.laqta.adapter import LaqtaUser


@dataclass(frozen=True)
class SeedOrganizer:
    user: LaqtaUser
    name: str
    org_name: str
    phone: str


SEED_ORGANIZERS: tuple[SeedOrganizer, ...] = (
    SeedOrganizer(
        user=LaqtaUser(
            id=uuid.UUID("5eed0000-0000-4000-8000-000000000001"),
            org_id=uuid.UUID("5eed0000-0000-4000-8000-0000000000a1"),
            email="ahmed@alrayyan-events.test",
            role="owner",
        ),
        name="أحمد العتيبي",
        org_name="شركة الريّان للفعاليات",
        phone="+966500000001",
    ),
    SeedOrganizer(
        user=LaqtaUser(
            id=uuid.UUID("5eed0000-0000-4000-8000-000000000002"),
            org_id=uuid.UUID("5eed0000-0000-4000-8000-0000000000a2"),
            email="noura@alward-weddings.test",
            role="owner",
        ),
        name="نورة القحطاني",
        org_name="دار الورد لتنظيم الحفلات",
        phone="+966500000002",
    ),
    SeedOrganizer(
        user=LaqtaUser(
            id=uuid.UUID("5eed0000-0000-4000-8000-000000000003"),
            org_id=uuid.UUID("5eed0000-0000-4000-8000-0000000000a3"),
            email="fahad@business-forum.test",
            role="owner",
        ),
        name="فهد الشهري",
        org_name="ملتقى الأعمال السعودي",
        phone="+966500000003",
    ),
)

# The Laqta event behind the seeded onsite booking in Jeddah.
SEED_JEDDAH_EVENT_ID = uuid.UUID("5eed0000-0000-4000-8000-0000000000e1")
