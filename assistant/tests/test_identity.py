from __future__ import annotations

import uuid

import pytest

from app.identity.dev_auth import AuthError, DevAuth
from app.identity.identity import Identity
from app.models import Contact, Staff
from app.models.enums import ContactSource, Team


@pytest.fixture()
def customer(db_session) -> Contact:
    c = Contact(
        laqta_user_id=uuid.uuid4(),
        laqta_org_id=uuid.uuid4(),
        name="عميل",
        source=ContactSource.chat,
    )
    db_session.add(c)
    db_session.flush()
    return c


@pytest.mark.parametrize("spec", ["anon", "anonymous", "  anon "])
def test_anon(db_session, spec):
    assert DevAuth(db_session).parse(spec) == Identity(kind="anonymous")


def test_customer_resolves_laqta_ids_from_contact(db_session, customer):
    ident = DevAuth(db_session).parse(f"customer:{customer.id}")
    assert ident == Identity(
        kind="customer",
        contact_id=customer.id,
        laqta_user_id=customer.laqta_user_id,
        laqta_org_id=customer.laqta_org_id,
    )


def test_staff(db_session):
    s = Staff(name="موظف", email="s@laqta.test", team=Team.ops)
    db_session.add(s)
    db_session.flush()
    assert DevAuth(db_session).parse(f"staff:{s.id}") == Identity(kind="staff", staff_id=s.id)


@pytest.mark.parametrize("spec", ["", "customer", "customer:", "customer:abc", "admin:1", "customer:-1", "3"])
def test_malformed_spec(db_session, spec):
    with pytest.raises(AuthError, match="expected anon"):
        DevAuth(db_session).parse(spec)


def test_unknown_customer(db_session):
    with pytest.raises(AuthError, match="no contact"):
        DevAuth(db_session).parse("customer:999999")


def test_contact_without_laqta_account_cannot_be_a_customer(db_session):
    lead = Contact(name="زائر", phone="+966500000099", source=ContactSource.chat)
    db_session.add(lead)
    db_session.flush()
    with pytest.raises(AuthError, match="no Laqta account"):
        DevAuth(db_session).parse(f"customer:{lead.id}")


def test_inactive_staff_rejected(db_session):
    s = Staff(name="سابق", email="old@laqta.test", team=Team.ops, active=False)
    db_session.add(s)
    db_session.flush()
    with pytest.raises(AuthError, match="no active staff"):
        DevAuth(db_session).parse(f"staff:{s.id}")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "anonymous", "contact_id": 1},
        {"kind": "customer"},
        {"kind": "customer", "contact_id": 1, "laqta_user_id": uuid.uuid4()},  # no org
        {"kind": "customer", "contact_id": 1, "laqta_user_id": uuid.uuid4(), "laqta_org_id": uuid.uuid4(), "staff_id": 1},
        {"kind": "staff"},
        {"kind": "staff", "staff_id": 1, "contact_id": 1},
        {"kind": "admin"},
    ],
)
def test_identity_rejects_inconsistent_ids(kwargs):
    with pytest.raises(ValueError):
        Identity(**kwargs)
