"""Environment settings + policy.yaml loading.

Settings are environment plumbing (where the DB is). Policy is business
rules (every operational number). They're kept apart on purpose: nothing in
policy.yaml is overridable from the environment.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ASSISTANT_DIR = Path(__file__).resolve().parent.parent
POLICY_PATH = ASSISTANT_DIR / "policy.yaml"
KB_PATH = ASSISTANT_DIR / "kb" / "laqta-kb.md"

# --- Retrieval. Technical constants tied to the embedding model, not
# business policy: swap the model and all four need re-deriving. The
# dimension additionally needs a migration and a full reindex.
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024
KB_TOP_K = 3
# Cosine similarity below which the best match counts as irrelevant, so the
# assistant says it does not know and hands off instead of answering from a
# loosely-related section.
#
# Measured, not guessed. Over tests/kb_questions.yaml (20 positives, 6
# adversarial negatives) the worst correct answer scores 0.484 and the best
# off-topic match 0.428, leaving 0.022 of margin below this value and 0.034
# above. BGE-M3 compresses Arabic cosine similarities into roughly 0.3–0.7,
# so ~0.45 is mid-range rather than a weak-match threshold.
#
# The band is thin: the hardest negative so far sits 0.002 under the
# ceiling, so the next one may move this number. Re-derive with
#   pytest tests/test_kb_retrieval.py -k threshold -s
# and see docs/EVAL.md §4. test_the_threshold_separates_answers_from_noise
# fails if a change to the knowledge base or the question set closes the gap.
KB_MIN_SCORE = 0.45

# --- The agent loop (spec §12).
SYSTEM_PROMPT_PATH = ASSISTANT_DIR / "app" / "agent" / "system_prompt.md"

# Guard against an infinite tool loop: eight steps is far more than any real
# booking turn needs (resolve_when → check_availability → prepare → read back
# is four), and hitting it means something is wrong, not that the customer
# asked something hard.
AGENT_MAX_STEPS = 8

# Spec §12 says 1024. Raised because adaptive thinking draws from the same
# budget on Sonnet 5, and a truncated turn (stop_reason "max_tokens") in the
# middle of reading a booking summary back is the worst place to run out.
AGENT_MAX_TOKENS = 4096

# A 2–3 line summary plus an outcome label — nothing here needs more.
SUMMARY_MAX_TOKENS = 512


class Settings(BaseSettings):
    # ASSISTANT_ prefix: a shell that already exports Laqta's DATABASE_URL
    # must not silently point the assistant at Laqta's database.
    model_config = SettingsConfigDict(
        env_prefix="ASSISTANT_", env_file=ASSISTANT_DIR / ".env", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://laqta:laqta_dev_password@localhost:5433/assistant"
    test_database_url: str = (
        "postgresql+psycopg://laqta:laqta_dev_password@localhost:5433/assistant_test"
    )

    # The conversation model, and a cheaper one for the end-of-session
    # summary. No date suffixes — these ids are complete as they are.
    agent_model: str = "claude-sonnet-5"
    summary_model: str = "claude-haiku-4-5"

    # The API key is deliberately absent: the Anthropic SDK resolves it
    # itself from ANTHROPIC_API_KEY (or an `ant auth login` profile), and a
    # credential has no business sitting in a settings object we print.


settings = Settings()


class _Frozen(BaseModel):
    # extra="forbid": a typo in policy.yaml fails loudly at load time instead
    # of silently falling back to nothing.
    model_config = ConfigDict(frozen=True, extra="forbid")


class LeadTimeHours(_Frozen):
    remote: int
    onsite: int


class PaymentDeadline(_Frozen):
    after_tentative_hours: int
    before_start_hours: int


class RefundTier(_Frozen):
    min_hours_before: int
    percent: int


class Onsite(_Frozen):
    cities: tuple[str, ...]
    max_events_per_city_per_day: int
    included_in: tuple[str, ...]
    addon_for: tuple[str, ...]


class Package(_Frozen):
    max_guests: int | None  # None = unlimited
    max_photos: int | None
    seats: int | None
    retention_days: int


class StrictMode(_Frozen):
    retention_days: int
    default_match_mode: str
    forbidden_addons: tuple[str, ...]


class Availability(_Frozen):
    suggestion_count: int
    suggestion_search_days: int


class PriorityMinutes(_Frozen):
    normal: int
    urgent: int
    privacy: int

    def for_priority(self, priority: str) -> int:
        try:
            return getattr(self, priority)
        except AttributeError:  # pragma: no cover - guarded by tests
            raise ValueError(f"unknown ticket priority: {priority!r}") from None


class Handoff(_Frozen):
    # Keys are ticket reason codes and values team names; validated against
    # the enums in tests rather than here, to keep config free of model
    # imports (app.models imports this module).
    routing: dict[str, str]
    to_team_manager: tuple[str, ...]
    priority_by_reason: dict[str, str]
    acknowledge_within_minutes: PriorityMinutes
    escalate_after_reminder_minutes: PriorityMinutes

    def team_for(self, reason_code: str) -> str:
        try:
            return self.routing[reason_code]
        except KeyError:
            raise ValueError(f"no team routes reason {reason_code!r}") from None


class Policy(_Frozen):
    timezone: str
    lead_time_hours: LeadTimeHours
    max_event_days: int
    upload_opens_before_hours: int
    upload_closes_after_hours: int
    free_reschedule_before_hours: int
    payment_deadline: PaymentDeadline
    refunds: tuple[RefundTier, ...]
    refunds_apply_to: tuple[str, ...]
    onsite: Onsite
    packages: dict[str, Package]
    addons: tuple[str, ...]
    strict_mode: StrictMode
    confirmation_ttl_minutes: int
    availability: Availability
    handoff: Handoff

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @model_validator(mode="after")
    def _check_consistency(self) -> Policy:
        ZoneInfo(self.timezone)  # raises on an unknown zone

        thresholds = [t.min_hours_before for t in self.refunds]
        if not thresholds or thresholds != sorted(thresholds, reverse=True):
            raise ValueError("refunds must be ordered by min_hours_before, descending")
        if thresholds[-1] != 0:
            # Without a zero tier, some cancellation times match no tier at all.
            raise ValueError("the last refunds tier must have min_hours_before: 0")

        for field in ("included_in", "addon_for"):
            unknown = set(getattr(self.onsite, field)) - self.packages.keys()
            if unknown:
                raise ValueError(f"onsite.{field} names unknown packages: {sorted(unknown)}")

        unknown_addons = set(self.strict_mode.forbidden_addons) - set(self.addons)
        if unknown_addons:
            raise ValueError(
                f"strict_mode.forbidden_addons names add-ons that are not in the "
                f"catalogue: {sorted(unknown_addons)}"
            )
        return self


def load_policy(path: Path = POLICY_PATH) -> Policy:
    with path.open(encoding="utf-8") as f:
        return Policy.model_validate(yaml.safe_load(f))


@lru_cache
def get_policy() -> Policy:
    return load_policy()
