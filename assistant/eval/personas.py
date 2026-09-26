"""Persona schema and loader.

A persona is one simulated customer: who they are, what they want, what they
know but will only say when asked, and — kept apart from all of that — what
the spec says must happen. The persona simulator sees `voice`, `opening`,
`goal`, `hidden_state`, `rules` and nothing else. `expected` is for the
scorer only; neither the simulator nor the agent ever sees it.

Every expected value is derived from layer1-spec.md, policy.yaml or
kb/laqta-kb.md. None is copied from the agent's observed behaviour.
`tests/test_eval_personas.py` recomputes the time-dependent ones (refund
tier, payment deadline, 48h window, onsite lead time) from policy.yaml by
plain arithmetic, without importing the agent's domain code.

Files: one persona per `personas/<id>.yaml`; shared bookings in
`personas/_fixtures.yaml`.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

PERSONAS_DIR = Path(__file__).resolve().parent / "personas"
FIXTURES_PATH = PERSONAS_DIR / "_fixtures.yaml"

# The nine tools of spec §10, written out rather than read from the agent's
# registry: a persona must not silently follow a renamed tool.
SPEC_TOOLS = frozenset(
    {
        "search_kb",
        "resolve_when",
        "check_availability",
        "get_my_bookings",
        "prepare_booking",
        "prepare_reschedule",
        "prepare_cancel",
        "confirm_action",
        "handoff_to_staff",
    }
)
CUSTOMER_ONLY_TOOLS = frozenset(
    {"get_my_bookings", "prepare_booking", "prepare_reschedule", "prepare_cancel", "confirm_action"}
)

# spec §3 tickets.reason_code, and policy.yaml handoff.routing.
REASON_CODES = frozenset(
    {
        "discount",
        "premium_quote",
        "long_event",
        "late_change",
        "complaint",
        "live_issue",
        "legal",
        "unknown_question",
        "wants_human",
    }
)

# STATUS.md "Failure taxonomy". 11 and 12 were found while writing the
# personas, 13 and 14 in the first live eval episodes — not in hand-testing.
TAXONOMY = {
    1: "ungrounded answers",
    2: "UUID fabrication",
    3: "Arabic package names rejected",
    4: "confirmation-token ambiguity",
    5: "summary_ar leaks English enums",
    6: "strict mode silently shortens retention",
    7: "unprompted emoji",
    8: "gender slips",
    9: "refund percentage change unexplained",
    10: "capacity refusal leaky, files nothing",
    11: "unpaid tentative cancellation charged a time-based refund tier",
    12: "fabricated link or URL",
    13: "English enum words in the model's own replies",
    14: "the model's own instruction-following leaked into a reply",
}

# The five adversarial cases the eval brief requires, plus a sixth:
# bare_yes_unlinked_summaries separates the two summaries a2 lets the agent
# combine into one question, so item 4 is provoked more often.
ADVERSARIAL_KINDS = (
    "date_change_mid_conversation",
    "bare_yes_two_tokens",
    "skip_confirmation_instruction",
    "partial_booking_id",
    "internal_only_question",
    "bare_yes_unlinked_summaries",
)

# Persona-specific checks. Each name is implemented by the scorer (step 3);
# the scorer must refuse to run a persona naming a check it does not know.
# Checks every episode gets regardless — grounding, internal leaks,
# confirmation violations, English enums (5), emoji (7), gender (8) — are
# not listed per persona.
KNOWN_CHECKS = frozenset(
    {
        "ambiguity_question_asked",       # resolver said ambiguous; agent asked, did not pick
        "assumptions_read_back",          # every resolve_when assumption reached the customer
        "both_calendars_read_back",       # Gregorian and Hijri text both said before prepare
        "code_matching_suggested",        # women's event: code matching suggested (system prompt)
        "no_booking_disclosure",          # nothing from `must_not_disclose` reaches the customer
        "no_browse_all_offer",            # root CLAUDE.md: no browse-all photos, for any role
        "no_capacity_implication",        # taxonomy 10: reply does not imply capacity limits exist
        "no_competitor_comment",          # KB internal: record competitor note, no comment
        "no_discount_hint",               # no offer, promise or hint of a discount
        "no_fabricated_booking_id",       # taxonomy 2: no booking_id the agent was never given
        "no_specific_response_time",      # handoff: no promised response time
        "refund_tier_explained",          # taxonomy 9: tier and its cutoff stated
        "registration_offered",           # anonymous booking attempt: pointed to registration. No
                                          # tool or KB section holds a link, so any URL is taxonomy 12
        "retention_change_stated",        # taxonomy 6: strict mode retention (7 days) stated
        "strict_mode_explained",          # women's event: strict mode explained
        "suggestions_offered",            # tool suggestions offered, no others invented
        "unknown_question_not_answered",  # taxonomy 1 / EVAL §2: handed off or said unknown
        "unpaid_tentative_no_fee_stated", # KB: unpaid tentative cancels without fees (taxonomy 11)
        "no_unknown_package",             # taxonomy 3: zero unknown_package results
    }
)

OUTCOMES = ("booked", "rescheduled", "cancelled", "handed_off", "answered", "refused")

_TEMPLATE = re.compile(r"\{\{\s*bookings\.([a-z0-9_]+)\.(id|short)\s*\}\}")


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- fixtures


class FixtureBooking(_Strict):
    """A booking present before the conversation starts. `status` is reached
    through the real state machine by the runner, not written directly."""

    id: str
    contact: int
    event_name: str
    city: str
    venue: str
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    expected_guests: int
    photographers: int
    match_mode: Literal["face", "code", "sequential", "both"]
    strict_mode: bool
    package: Literal["starter", "standard", "premium"]
    addons: list[str] = Field(default_factory=list)
    onsite_support: bool
    status: Literal["tentative", "confirmed", "live", "ended"]
    tentative_at: AwareDatetime


# --- persona


class Voice(_Strict):
    name: str
    # How the simulated customer refers to themselves. Not what the agent
    # should use: scripts/seed.py leaves contacts.gender NULL, so every
    # episode's context block says the gender is not stated and the correct
    # address is gender-neutral (taxonomy 8).
    gender: Literal["male", "female"]
    style: str


class When(_Strict):
    """Exactly one condition. Evaluated after each agent reply."""

    after_tool: str | None = None  # the nth successful call of this tool has happened
    nth: int = 1
    live_tokens_at_least: int | None = None  # prepared, unused, unexpired confirmations
    customer_turn: int | None = None  # the customer has sent this many messages

    @model_validator(mode="after")
    def _one(self) -> When:
        set_ = [self.after_tool, self.live_tokens_at_least, self.customer_turn]
        if sum(v is not None for v in set_) != 1:
            raise ValueError("a script condition needs exactly one of after_tool, live_tokens_at_least, customer_turn")
        if self.after_tool is not None and self.after_tool not in SPEC_TOOLS:
            raise ValueError(f"unknown tool in script condition: {self.after_tool}")
        return self


class ScriptedTurn(_Strict):
    """A customer message sent verbatim instead of the simulator's, the first
    time its condition holds. Adversarial moves are scripted so they happen
    every episode rather than whenever the simulator feels like it."""

    id: str
    when: When
    say: str


class ExpectedBooking(_Strict):
    """The one booking row this conversation should create."""

    event_name: str
    city: str
    venue: str
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    expected_guests: int
    photographers: int
    match_mode: Literal["face", "code", "sequential", "both"]
    strict_mode: bool
    package: Literal["starter", "standard", "premium"]
    addons: list[str] = Field(default_factory=list)
    onsite_support: bool
    status: Literal["tentative"] = "tentative"
    # spec §2: min(tentative_at + 72h, starts_at - 24h), tentative_at = now.
    payment_due_at: AwareDatetime


class BookingChange(_Strict):
    status: Literal["tentative", "confirmed", "live", "ended", "cancelled"] | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None


class Expected(_Strict):
    outcomes: list[Literal[OUTCOMES]]  # type: ignore[valid-type]
    created_booking: ExpectedBooking | None = None
    # Fixture key -> the fields that must differ afterwards. Every fixture not
    # listed here, and the seed booking, must be byte-for-byte unchanged.
    booking_changes: dict[str, BookingChange] = Field(default_factory=dict)

    # required: a ticket must be opened. forbidden: none may be. optional: the
    # spec allows either; the episode is left out of handoff precision/recall.
    handoff: Literal["required", "forbidden", "optional"]
    handoff_reasons: list[str] = Field(default_factory=list)
    ticket_team: Literal["sales", "ops", "support", "privacy"] | None = None
    ticket_priority: Literal["normal", "urgent", "privacy"] | None = None

    # Spec-derived number the agent must quote (prepare_cancel), when relevant.
    refund_percent: int | None = None

    tools_required: list[str] = Field(default_factory=list)
    tools_forbidden: list[str] = Field(default_factory=list)
    # (a, b): the first call of b must come after some call of a.
    tools_order: list[tuple[str, str]] = Field(default_factory=list)

    checks: list[str] = Field(default_factory=list)
    must_not_disclose: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> Expected:
        for name in [*self.tools_required, *self.tools_forbidden, *(t for pair in self.tools_order for t in pair)]:
            if name not in SPEC_TOOLS:
                raise ValueError(f"unknown tool: {name}")
        if overlap := set(self.tools_required) & set(self.tools_forbidden):
            raise ValueError(f"tools both required and forbidden: {sorted(overlap)}")
        if unknown := set(self.checks) - KNOWN_CHECKS:
            raise ValueError(f"unknown checks: {sorted(unknown)}")
        if unknown := set(self.handoff_reasons) - REASON_CODES:
            raise ValueError(f"unknown reason codes: {sorted(unknown)}")
        if self.handoff == "required" and not self.handoff_reasons:
            raise ValueError("a required handoff must name the accepted reason codes")
        if self.handoff == "forbidden" and (self.handoff_reasons or self.ticket_team):
            raise ValueError("a forbidden handoff cannot name reasons or a team")
        if ("booked" in self.outcomes) != (self.created_booking is not None):
            raise ValueError("created_booking is given exactly when the outcome is booked")
        acts = {"booked", "rescheduled", "cancelled"} & set(self.outcomes)
        if acts and "confirm_action" not in self.tools_required:
            raise ValueError("an outcome that changes a booking requires confirm_action")
        if not acts and "confirm_action" not in self.tools_forbidden:
            raise ValueError("an outcome that changes no booking must forbid confirm_action")
        return self


class Persona(_Strict):
    id: str
    title: str
    taxonomy: list[int] = Field(default_factory=list)
    adversarial: Literal[ADVERSARIAL_KINDS] | None = None  # type: ignore[valid-type]
    # "opening", or the id of the scripted turn that carries the provocation.
    # An adversarial episode whose provocation never fired is reported as
    # not provoked — never as a pass.
    provocation: str | None = None

    identity: str  # anon | customer:<contact_id>
    now: AwareDatetime
    fixtures: list[str] = Field(default_factory=list)

    voice: Voice
    opening: str
    goal: str
    hidden_state: dict[str, str] = Field(default_factory=dict)
    rules: list[str] = Field(default_factory=list)
    script: list[ScriptedTurn] = Field(default_factory=list)
    max_customer_turns: int = Field(default=12, ge=2, le=30)

    expected: Expected

    @model_validator(mode="after")
    def _consistent(self) -> Persona:
        if unknown := set(self.taxonomy) - TAXONOMY.keys():
            raise ValueError(f"unknown taxonomy entries: {sorted(unknown)}")
        if not re.fullmatch(r"anon|customer:\d+", self.identity):
            raise ValueError(f"identity must be anon or customer:<id>, got {self.identity!r}")
        if (self.adversarial is None) != (self.provocation is None):
            raise ValueError("adversarial and provocation go together")
        script_ids = [turn.id for turn in self.script]
        if len(script_ids) != len(set(script_ids)):
            raise ValueError("duplicate scripted turn ids")
        if self.provocation not in (None, "opening", *script_ids):
            raise ValueError(f"provocation {self.provocation!r} is neither 'opening' nor a script id")
        if self.identity == "anon":
            if used := CUSTOMER_ONLY_TOOLS & set(self.expected.tools_required):
                raise ValueError(f"an anonymous persona cannot be required to call {sorted(used)}")
        return self

    @property
    def contact_id(self) -> int | None:
        return None if self.identity == "anon" else int(self.identity.split(":")[1])

    def template_keys(self) -> set[str]:
        texts = [self.opening, self.goal, *self.hidden_state.values(), *self.rules, *(t.say for t in self.script)]
        return {m.group(1) for text in texts for m in _TEMPLATE.finditer(text)}


def render(text: str, booking_ids: dict[str, str]) -> str:
    """Fill `{{bookings.<key>.id}}` / `{{bookings.<key>.short}}`. The seed's
    Jeddah booking gets a fresh UUID every episode, so ids cannot be written
    into the YAML literally."""

    def sub(match: re.Match) -> str:
        full = booking_ids[match.group(1)]
        return full if match.group(2) == "id" else full.split("-")[0]

    return _TEMPLATE.sub(sub, text)


# The booking scripts/seed.py creates, addressable by this key in templates
# and in expected.booking_changes.
SEED_BOOKING_KEY = "seed_jeddah"


@lru_cache(maxsize=1)
def load_fixtures() -> dict[str, FixtureBooking]:
    raw = yaml.safe_load(FIXTURES_PATH.read_text(encoding="utf-8"))
    return {key: FixtureBooking.model_validate(value) for key, value in raw["bookings"].items()}


def persona_sha256(persona_id: str) -> str:
    """Of the YAML file, so a scorer can tell whether `expected` changed since
    an episode ran."""
    return hashlib.sha256((PERSONAS_DIR / f"{persona_id}.yaml").read_bytes()).hexdigest()


def load_personas(directory: Path = PERSONAS_DIR) -> list[Persona]:
    personas = []
    for path in sorted(directory.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        persona = Persona.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        if persona.id != path.stem:
            raise ValueError(f"{path.name}: id {persona.id!r} does not match the file name")
        personas.append(persona)
    return personas
