"""What the model reads names booking choices the way the customer should
hear them (taxonomy 13).

Taxonomy 5 was the tool's summary_ar leaking English keys; it is covered by
test_summaries. 13 is the model writing those keys in its own questions,
because it read them in the system prompt, a tool schema, a tool result or
the context block. This covers those four sources. What the model then
writes is not covered and cannot be: the eval measures it.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from app.agent.context import build_context_block
from app.agent.loop import system_prompt
from app.identity.identity import Identity
from app.models import Confirmation
from app.models.enums import BookingStatus, MatchMode
from app.tools import registry
from app.tools.labels import CITY_AR, MATCH_MODE_AR, PACKAGE_AR, STATUS_AR, STRICT_MODE_AR
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import (
    customer_identity,
    make_contact,
    make_onsite_booking,
    make_tool_context,
    make_when,
    register_when,
)
from tests.test_summaries import DETAILS

FAR_DAY = date(2026, 10, 15)

# These double as ordinary English ("read back BOTH dates", "a live event",
# "reason_code"), so prose is not checked for them. Schema enums and titles
# are, below, where a hit can only be the key.
EVERYDAY_ENGLISH = {"both", "code", "live", "ended"}


def enum_words(policy) -> set[str]:
    return {
        *policy.packages,
        *policy.addons,
        *policy.onsite.cities,
        *(mode.value for mode in MatchMode),
        *(status.value for status in BookingStatus),
        "strict",
    }


def english_keys_in(text: str, words: set[str]) -> set[str]:
    # `_` counts as part of a word, as in eval/signals.py: strict_mode is a
    # field name the model passes, not a word it says.
    return {w for w in words if re.search(rf"(?<![A-Za-z_]){re.escape(w)}(?![A-Za-z_])", text, re.IGNORECASE)}


def schema_strings(node) -> tuple[list[str], list[str]]:
    """(prose, keys): descriptions on one side; enum values and titles on
    the other."""
    prose: list[str] = []
    keys: list[str] = []
    if isinstance(node, dict):
        for name, value in node.items():
            if name == "description" and isinstance(value, str):
                prose.append(value)
            elif name == "title" and isinstance(value, str):
                keys.append(value)
            elif name == "enum":
                keys.extend(str(v) for v in value)
            else:
                p, k = schema_strings(value)
                prose += p
                keys += k
    elif isinstance(node, list):
        for item in node:
            p, k = schema_strings(item)
            prose += p
            keys += k
    return prose, keys


@pytest.fixture()
def contact(db_session):
    return make_contact(db_session)


@pytest.fixture()
def ctx(db_session, policy, contact):
    return make_tool_context(db_session, policy, identity=customer_identity(contact))


# --- the system prompt


def test_the_system_prompt_names_booking_choices_in_arabic(policy):
    prompt = system_prompt()
    assert english_keys_in(prompt, enum_words(policy) - EVERYDAY_ENGLISH) == set()
    for label in (*MATCH_MODE_AR.values(), STRICT_MODE_AR):
        assert label in prompt


# --- tool schemas


@pytest.mark.parametrize("kind", ["anonymous", "customer"])
def test_no_tool_schema_offers_an_english_key(policy, db_session, contact, kind):
    identity = customer_identity(contact) if kind == "customer" else Identity(kind="anonymous")
    words = enum_words(policy)
    for schema in registry.schemas_for(identity):
        prose, keys = schema_strings(schema["input_schema"])
        prose.append(schema["description"])
        for text in prose:
            assert english_keys_in(text, words - EVERYDAY_ENGLISH) == set(), (schema["name"], text)
        for text in keys:
            assert english_keys_in(text, words) == set(), (schema["name"], text)


def test_the_booking_schema_offers_the_kb_names(db_session, contact):
    schema = next(
        s for s in registry.schemas_for(customer_identity(contact)) if s["name"] == "prepare_booking"
    )
    details = schema["input_schema"]["$defs"]["BookingDetails"]["properties"]
    assert details["match_mode"]["enum"] == list(MATCH_MODE_AR.values())
    assert details["package"]["enum"] == list(PACKAGE_AR.values())
    assert details["strict_mode"]["title"] == STRICT_MODE_AR


def test_the_schema_check_catches_the_old_wording(policy):
    """Control: the pre-fix schema text must fail both checks."""
    old = {
        "type": "object",
        "properties": {
            "package": {"description": "starter, standard or premium — the Arabic name is accepted too."},
            "strict_mode": {"title": "Strict Mode"},
            "match_mode": {"enum": ["face", "code", "sequential", "both"]},
        },
    }
    prose, keys = schema_strings(old)
    words = enum_words(policy)
    assert english_keys_in(" ".join(prose), words - EVERYDAY_ENGLISH) == {"starter", "standard", "premium"}
    assert english_keys_in(" ".join(keys), words) == {"strict", "face", "code", "sequential", "both"}


@pytest.mark.parametrize(
    ("field", "table"), [("match_mode", MATCH_MODE_AR), ("package", PACKAGE_AR)]
)
def test_every_name_the_schema_offers_is_accepted_and_stored_as_the_key(ctx, policy, db_session, field, table):
    for key, label in table.items():
        when_id = register_when(ctx, make_when(policy, FAR_DAY))
        result = registry.execute(
            "prepare_booking", {"when_id": when_id, "details": {**DETAILS, field: label}}, ctx=ctx
        )
        assert result["ok"] is True, result
        stored = db_session.get(Confirmation, result["data"]["confirmation_id"]).params["details"]
        assert stored[field] == key


def test_english_keys_are_still_accepted(ctx, policy):
    when_id = register_when(ctx, make_when(policy, FAR_DAY))
    details = {**DETAILS, "match_mode": "both", "package": "premium", "city": "riyadh"}
    assert registry.execute("prepare_booking", {"when_id": when_id, "details": details}, ctx=ctx)["ok"] is True


# --- tool results: the key stays, and its Arabic name sits beside it


def test_my_bookings_carry_arabic_names_beside_the_keys(ctx, db_session, policy, contact):
    make_onsite_booking(db_session, policy, FAR_DAY, contact_id=contact.id, city="jeddah")
    [booking] = registry.execute("get_my_bookings", {}, ctx=ctx)["data"]["bookings"]

    assert (booking["status"], booking["status_ar"]) == ("tentative", STATUS_AR["tentative"])
    assert (booking["city"], booking["city_ar"]) == ("jeddah", CITY_AR["jeddah"])
    assert (booking["package"], booking["package_ar"]) == ("premium", PACKAGE_AR["premium"])


def test_a_remote_city_outside_the_onsite_list_is_its_own_arabic_name(ctx, db_session, policy, contact):
    make_onsite_booking(db_session, policy, FAR_DAY, contact_id=contact.id, city="أبها", onsite_support=False)
    [booking] = registry.execute("get_my_bookings", {}, ctx=ctx)["data"]["bookings"]
    assert booking["city_ar"] == "أبها"


def test_a_confirmed_booking_result_carries_the_arabic_status(ctx, policy):
    when_id = register_when(ctx, make_when(policy, FAR_DAY))
    prepared = registry.execute("prepare_booking", {"when_id": when_id, "details": DETAILS}, ctx=ctx)
    ctx.user_turn += 1
    result = registry.execute(
        "confirm_action", {"confirmation_id": prepared["data"]["confirmation_id"]}, ctx=ctx
    )
    assert (result["data"]["status"], result["data"]["status_ar"]) == ("tentative", STATUS_AR["tentative"])


def test_an_unknown_package_refusal_lists_the_arabic_names(ctx, policy):
    when_id = register_when(ctx, make_when(policy, FAR_DAY))
    result = registry.execute(
        "prepare_booking", {"when_id": when_id, "details": {**DETAILS, "package": "الذهبية"}}, ctx=ctx
    )
    assert result["error"] == "unknown_package"
    assert result["packages_ar"] == [PACKAGE_AR[key] for key in result["packages"]]


# --- the context block


def test_the_context_block_names_the_city_in_arabic(db_session, policy, contact):
    make_onsite_booking(db_session, policy, FAR_DAY, contact_id=contact.id, city="jeddah")
    block = build_context_block(db_session, customer_identity(contact), now=NOW, policy=policy)
    assert CITY_AR["jeddah"] in block
    assert english_keys_in(block, enum_words(policy)) == set()
