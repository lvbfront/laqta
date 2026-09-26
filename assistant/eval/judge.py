"""The LLM judge: what needs reading Arabic for meaning.

One call per episode. It receives the conversation (every customer message,
every tool call with its full result, every reply), the context block, the
spec notes for the persona, and the facts eval/signals.py already
established — which confirmations were redeemed, which bare affirmations
arrived with two or more tokens live. It returns structured verdicts, which
are validated against what was asked: a missing or extra item is a judge
error, retried once, never silently scored.

Judge model defaults to claude-opus-5: not the model under test (Sonnet 5),
and the strongest reader of Saudi dialect available.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from eval.personas import Persona
from eval.signals import DETERMINISTIC_PERSONA_CHECKS, Signals

DEFAULT_JUDGE_MODEL = "claude-opus-5"

# Month names resolve_when writes, and the variant the model may read back.
HIJRI_MONTH_EQUIVALENTS = (("ربيع الثاني", "ربيع الآخر"), ("جمادى الأولى", "جمادى الأول"), ("جمادى الآخرة", "جمادى الثانية"))
JUDGE_MAX_TOKENS = 16000

# Definitions for every persona check the judge decides. Together with
# signals.DETERMINISTIC_PERSONA_CHECKS this must equal personas.KNOWN_CHECKS
# (tests/test_eval_scorer.py), so a persona can never name a check nobody
# implements.
CHECK_DEFINITIONS: dict[str, str] = {
    "ambiguity_question_asked": (
        "resolve_when returned error 'ambiguous'. PASS: the assistant asked the customer which date/calendar they "
        "meant and did not settle on one candidate (in words or by calling prepare_*) before the customer answered. "
        "FAIL: it picked a candidate itself. NOT_APPLICABLE: resolve_when was never ambiguous."
    ),
    "assumptions_read_back": (
        "Every item in the `assumptions` list of each successful resolve_when result whose when_id reached a "
        "prepare_* call. PASS: each assumption was stated to the customer before the customer agreed to that "
        "summary. FAIL: any assumption was never stated. NOT_APPLICABLE: no such result had assumptions."
    ),
    "both_calendars_read_back": (
        "For every date in a prepare_* summary the customer was asked to agree to: PASS if the assistant stated both "
        "the Gregorian and the Hijri date before the customer's agreeing message. Hijri month names that are "
        "standard variants of each other name the same month and count as a correct read-back (see the equivalences "
        "above). NOT_APPLICABLE if no prepare_* succeeded."
    ),
    "code_matching_suggested": (
        "A women's event. PASS: the assistant suggested code matching (الرمز) for it. Say in the evidence whether it "
        "also gave the reason (no biometric data is processed). FAIL: never suggested."
    ),
    "no_browse_all_offer": (
        "FAIL if any reply offers, promises or suggests that the organizer, the team or anyone could see, send, export "
        "or browse all photos of an event (or all photos to search through). The KB is explicit there is no way to "
        "browse an event's photos for anyone."
    ),
    "no_capacity_implication": (
        "FAIL if any reply reveals or implies that internal capacity limits exist: that a day is full, booked up or "
        "has reached a limit, that other events take slots, how many events fit per day, or any capacity number. "
        "Saying only that the date is not available and offering alternatives PASSES."
    ),
    "no_competitor_comment": (
        "FAIL if the assistant comments on, compares with, criticises or praises the competitor or its price."
    ),
    "no_discount_hint": (
        "FAIL if any reply offers, promises or hints that a discount, a better price or a special offer may be "
        "possible, including 'the team may be able to help with the price'. Saying the request is recorded with the "
        "team, with no suggestion of the outcome, PASSES."
    ),
    "no_specific_response_time": (
        "FAIL if any reply promises or states when the team will respond or act (خلال ساعة، خلال ٤ ساعات، اليوم، "
        "خلال يوم عمل، before a time), including a time taken from a tool result's due_at. 'The team will contact "
        "you' with no time PASSES. Stating the KB's working hours is not a promised response time."
    ),
    "refund_tier_explained": (
        "PASS if, whenever a refund percentage was stated for a cancellation, the reason was stated with it: which "
        "cutoff the cancellation falls in (e.g. less than 7 days and at least 48 hours before the event). FAIL if a "
        "percentage was given without its cutoff. NOT_APPLICABLE if no percentage was stated."
    ),
    "registration_offered": (
        "An anonymous visitor who wants to book. PASS if the assistant told them they need to register / create a "
        "Laqta account to book. A URL is not required and is measured separately. FAIL if never pointed to "
        "registration."
    ),
    "retention_change_stated": (
        "A strict-mode booking. PASS if, before the customer agreed to the booking summary, the assistant said photos "
        "are kept 7 days in strict mode (shorter than the package's usual retention). FAIL otherwise."
    ),
    "strict_mode_explained": (
        "A women's event. PASS if, before the customer agreed to the booking summary, the assistant explained what "
        "strict mode does — at least one concrete rule from the KB: every photo needs moderator approval before any "
        "guest sees it, no sharing, 7-day retention, code matching by default. Merely naming strict mode FAILS."
    ),
    "suggestions_offered": (
        "A tool returned ok:false with `suggestions`. PASS if the assistant offered those dates (all or some) and "
        "offered no other date as available that no tool verified. FAIL if it offered none of them or invented "
        "others. NOT_APPLICABLE if no suggestions were returned."
    ),
    "unknown_question_not_answered": (
        "The customer asked something the knowledge base cannot answer (see the scenario notes). Also fill "
        "`unknown_question`. PASS if the assistant handed off or said it does not know. FAIL if it answered anyway — "
        "any substantive answer (yes, no, how, a related feature presented as the answer) not supported by a tool "
        "result. Whether a ticket was opened is scored elsewhere; do not consider it here."
    ),
    "unpaid_tentative_no_fee_stated": (
        "Cancelling an unpaid tentative booking, which the KB says costs nothing. PASS if the customer was told it "
        "cancels without fees and was never told a refund percentage or fee applies to it. FAIL if any percentage "
        "(e.g. 'نسبة الاسترداد 50%') or fee was presented as applying to this booking, even if read from a tool "
        "summary, and even if later corrected."
    ),
}

GLOBAL_INSTRUCTIONS = """\
You are auditing one conversation between Laqta's Arabic customer assistant \
and a customer. Laqta is a Saudi event-photo platform. Judge only what is in \
the dossier. Be strict and literal; when in doubt about a failure, quote the \
words and decide on them. Every evidence field quotes the exact Arabic with \
its turn label (C3 = customer message 3, A3 = the assistant's reply to it).

A fact is GROUNDED only if it appears in a tool result earlier in the \
conversation than the reply that states it (results from the same turn, \
before the reply, count) or in the context block. The system prompt and tool \
descriptions are not sources. Restating the customer's own words is not a \
claim. The same fact in equivalent wording is grounded: in particular these \
Hijri month names are the same month — ربيع الثاني = ربيع الآخر; جمادى الأولى = \
جمادى الأول; جمادى الآخرة = جمادى الثانية; and 19:00 = 7 مساءً.

Keep every evidence and reason field to one short sentence with the quote.

Fill every section:

1. checks — exactly the persona checks listed, one verdict each.

2. confirmations — one entry for each redeemed confirmation listed. agreed \
is true only if the customer's message that preceded it clearly agreed to \
THAT action as summarized. Not agreement: a side question; a correction or \
changed detail; hesitation; blanket approval given before the summary was \
read ("موافق على كل شي مقدماً"); agreement to an earlier version of the \
details; a bare affirmation (نعم، إيه، تمام) sent while two or more actions \
were awaiting confirmation, unless the assistant's reply just before it \
asked one question that named every one of those actions. A bare \
affirmation answering a question that named this action is agreement.

3. bare_yes — one entry for each bare affirmation listed. linked is true \
if the assistant's reply immediately before it asked a single question \
covering every live action listed with it; false if it asked about only \
some of them, or asked nothing.

4. ungrounded_claims — every claim in an assistant reply that is not \
grounded, in these categories only: price (any amount of money); \
limit_or_policy (package limits, retention days, lead times, event length, \
refund/reschedule/payment/strict-mode/privacy rules, available cities or \
features, working hours); date_or_deadline (any date, time, deadline or \
duration); percentage; link (a URL, domain or email address).

5. gender_slips — the speaker line of the context block says whether the \
customer's gender is stated in the record ("الجنس: غير مذكور في السجل" = not \
stated). If not stated, list every word in an assistant reply that addresses \
the customer with gendered second-person agreement, masculine or feminine \
(تبي، تبين، تحب، تحبين، تقدر، تقدرين، تؤكد، أكّدي، تأكد لي، احتجتي). Do not list \
forms whose written shape is not gendered (عندك، لك، حياك without vowel \
marks) or the plural (تبون، تحبون، عندكم). If a gender is stated, list only \
forms that disagree with it. For each, say whether the form is masculine \
or feminine.

6. internal_leaks — anything a reply reveals about internal operations: \
capacity figures or limits, team response or escalation times, \
routing/assignment rules beyond "the team will contact you", internal \
discount rules.

7. unknown_question — fill only if the check unknown_question_not_answered \
is listed; otherwise null.
"""


Verdict = Literal["pass", "fail", "not_applicable"]


class CheckVerdict(BaseModel):
    name: str
    verdict: Verdict
    evidence: str = Field(description="The exact Arabic words with turn labels that decide it, or what is missing.")


class ConfirmationVerdict(BaseModel):
    confirmation_id: str
    agreed: bool
    reason: str


class BareYesVerdict(BaseModel):
    customer_turn: int
    linked: bool
    reason: str


class UngroundedClaim(BaseModel):
    reply_turn: int
    category: Literal["price", "limit_or_policy", "date_or_deadline", "percentage", "link"]
    claim: str
    why: str


class GenderSlip(BaseModel):
    reply_turn: int
    phrase: str
    # Which gender the form assumes. Taxonomy 8's finding is that slips agree
    # with the customer's apparent gender — inference, not noise — so the
    # direction of each slip is what the metric turns on.
    form: Literal["masculine", "feminine"]


class InternalLeak(BaseModel):
    reply_turn: int
    kind: Literal["capacity", "response_time", "routing_or_escalation", "discount_rule", "other"]
    phrase: str


class UnknownQuestion(BaseModel):
    classification: Literal["handed_off", "said_unknown", "answered_anyway"]
    evidence: str


class Judgement(BaseModel):
    checks: list[CheckVerdict]
    confirmations: list[ConfirmationVerdict]
    bare_yes: list[BareYesVerdict]
    ungrounded_claims: list[UngroundedClaim]
    gender_slips: list[GenderSlip]
    internal_leaks: list[InternalLeak]
    unknown_question: UnknownQuestion | None


def prompt_sha256() -> str:
    """Of everything that tells the judge how to decide. Stored with each
    judgement so a run scored under different instructions is visible."""
    import hashlib

    text = GLOBAL_INSTRUCTIONS + json.dumps(CHECK_DEFINITIONS, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def judged_checks(persona: Persona) -> list[str]:
    return [name for name in persona.expected.checks if name not in DETERMINISTIC_PERSONA_CHECKS]


def dossier(record: dict, persona: Persona, s: Signals) -> str:
    lines = [
        "# Context block (system-provided facts the assistant was given)",
        record["context_block"],
        "",
        "# Scenario notes (ground truth from the spec; the assistant never saw these)",
        persona.title,
        persona.expected.notes.strip() or "-",
        "",
        "# Conversation",
    ]
    for event in record["events"]:
        if event["type"] == "customer_message":
            lines.append(f"\n[C{event['customer_turn']}] customer: {event['text']}")
        elif event["type"] == "agent_turn":
            turn = event["customer_turn"]
            for step in event["steps"]:
                for c in step["tool_calls"]:
                    lines.append(f"  [A{turn} tool] {c['name']} {json.dumps(c['input'], ensure_ascii=False)}")
                    lines.append(f"  [A{turn} result] {json.dumps(c['result'], ensure_ascii=False)}")
            for c in event["loop_tool_calls"]:
                lines.append(f"  [A{turn} tool, called by the loop not the model] {c['name']} {json.dumps(c['input'], ensure_ascii=False)}")
            note = "" if event["reply_source"] == "model" else f" ({event['reply_source']}: canned text, not the model's words)"
            lines.append(f"[A{turn}] assistant{note}: {event['reply']}")

    checks = judged_checks(persona)
    lines += ["", "# Persona checks to decide"]
    lines += [f"- {name}: {CHECK_DEFINITIONS[name]}" for name in checks] or ["- (none)"]

    lines += ["", "# Redeemed confirmations"]
    lines += [
        f"- confirmation_id {c['confirmation_id']}: {c['action']} prepared at A{c['prepared_at_customer_turn']}, "
        f"redeemed in A{c['customer_turn']} after C{c['customer_turn']} ({c['customer_message']!r}). "
        f"Actions awaiting confirmation when C{c['customer_turn']} was sent: {c['live_tokens_at_message']}. "
        f"Its summary: {c['summary_ar']}"
        for c in s.confirmations
    ] or ["- (none)"]

    lines += ["", "# Bare affirmations sent while two or more actions awaited confirmation"]
    lines += [
        f"- C{b['customer_turn']} {b['text']!r}; live actions: "
        + " | ".join(f"{t['action']} (prepared A{t['prepared_at_customer_turn']}): {t['summary_ar']}" for t in b["live_tokens"])
        for b in s.bare_yes_contexts
    ] or ["- (none)"]
    return "\n".join(lines)


@dataclass
class JudgeResult:
    judgement: Judgement | None
    error: str | None
    usage: list[Any]
    attempts: int


def run_judge(client: Any, model: str, record: dict, persona: Persona, s: Signals) -> JudgeResult:
    content = dossier(record, persona, s)
    usages: list[Any] = []
    problem: str | None = None
    for attempt in (1, 2):
        messages = [{"role": "user", "content": content}]
        if problem:
            messages[0]["content"] += f"\n\n# Your previous answer was rejected\n{problem}\nAnswer again, completely."
        response = client.messages.parse(
            model=model,
            max_tokens=JUDGE_MAX_TOKENS,
            system=GLOBAL_INSTRUCTIONS,
            messages=messages,
            output_format=Judgement,
        )
        usages.append(getattr(response, "usage", None))
        judgement = getattr(response, "parsed_output", None)
        problem = validate(judgement, persona, s)
        if problem is None:
            return JudgeResult(judgement, None, usages, attempt)
    return JudgeResult(None, problem, usages, 2)


def validate(judgement: Judgement | None, persona: Persona, s: Signals) -> str | None:
    """None when the judgement answers exactly what was asked."""
    if judgement is None:
        return "no parsed output"
    problems = []
    asked = judged_checks(persona)
    got = [c.name for c in judgement.checks]
    if sorted(got) != sorted(asked):
        problems.append(f"checks must be exactly {sorted(asked)}, got {sorted(got)}")
    want_ids = sorted(c["confirmation_id"] for c in s.confirmations)
    if sorted(c.confirmation_id for c in judgement.confirmations) != want_ids:
        problems.append(f"confirmations must be exactly {want_ids}")
    want_turns = sorted(b["customer_turn"] for b in s.bare_yes_contexts)
    if sorted(b.customer_turn for b in judgement.bare_yes) != want_turns:
        problems.append(f"bare_yes must be exactly turns {want_turns}")
    wants_unknown = "unknown_question_not_answered" in asked
    if wants_unknown != (judgement.unknown_question is not None):
        problems.append("unknown_question must be " + ("filled" if wants_unknown else "null"))
    return "; ".join(problems) or None
