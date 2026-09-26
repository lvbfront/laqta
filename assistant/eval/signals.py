"""Everything about an episode that can be decided without a model.

Pure functions over one episode record (eval/runner.py's JSON). No database,
no API. The judge (eval/judge.py) is given these facts rather than asked to
rediscover them, and decides only what needs reading Arabic for meaning.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.config import Policy
from eval.personas import Persona

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)

# Pictographs, dingbats and symbols. Not arrows or punctuation.
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿]")

# URLs, bare domains and email addresses. Taxonomy 12: a link is only
# grounded if its text appears in a tool result or the context block.
LINK_RE = re.compile(
    r"https?://[^\s)»\]،]+"
    r"|www\.[^\s)»\]،]+"
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    r"|\b[\w-]+(?:\.[\w-]+)*\.(?:sa|com|net|org|io|app|me|co|example)\b(?:/[^\s)»\]،]*)?",
    re.IGNORECASE,
)

_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DIACRITICS = re.compile("[ً-ْٰـ]")  # harakat, shadda, dagger alef, tatweel

MODEL_REPLY_SOURCES = ("model", "model_truncated")
BOOKING_STATUS_WORDS = ("tentative", "confirmed", "live", "ended", "cancelled")
MATCH_MODE_WORDS = ("face", "code", "sequential", "both")

# A reply that is only these words agrees to *something* without saying what.
_AFFIRMATIONS = (
    "نعم", "ايه", "إيه", "اي", "أي", "ايوه", "إيوه", "ايوا", "اوك", "اوكي", "أوكي", "تمام", "طيب",
    "موافق", "موافقة", "اكيد", "أكيد", "يب", "اكد", "أكد", "أكّد", "نفذ", "نفّذ", "ok", "okay", "yes",
)


def normalize_arabic(text: str) -> str:
    text = _DIACRITICS.sub("", text.translate(_ARABIC_INDIC))
    return re.sub("[أإآ]", "ا", text).lower()


_AFFIRMATION_SET = frozenset(normalize_arabic(w) for w in _AFFIRMATIONS)


def is_bare_affirmation(text: str) -> bool:
    words = re.findall(r"[a-zء-ي]+", normalize_arabic(text))
    return 1 <= len(words) <= 2 and all(w in _AFFIRMATION_SET for w in words)


# --- views over the record


@dataclass(frozen=True)
class Call:
    index: int
    customer_turn: int
    name: str
    input: dict
    result: dict | None
    ok: bool | None
    source: str  # model | loop


@dataclass(frozen=True)
class Reply:
    customer_turn: int
    text: str
    source: str


def calls(record: dict) -> list[Call]:
    out: list[Call] = []
    for event in record["events"]:
        if event["type"] != "agent_turn":
            continue
        for step in event["steps"]:
            for c in step["tool_calls"]:
                out.append(Call(len(out), event["customer_turn"], c["name"], c["input"] or {}, c["result"], c["ok"], "model"))
        for c in event["loop_tool_calls"]:
            out.append(Call(len(out), event["customer_turn"], c["name"], c["input"] or {}, c["result"], c["ok"], "loop"))
    return out


def replies(record: dict) -> list[Reply]:
    return [Reply(e["customer_turn"], e["reply"], e["reply_source"]) for e in record["events"] if e["type"] == "agent_turn"]


def model_replies(record: dict) -> list[Reply]:
    """Replies whose words are the model's. A canned loop message (API error,
    refusal, fallback) is not scored as the model's phrasing."""
    return [r for r in replies(record) if r.source in MODEL_REPLY_SOURCES]


def customer_messages(record: dict) -> list[dict]:
    return [e for e in record["events"] if e["type"] == "customer_message"]


def _result_text(call: Call) -> str:
    return json.dumps(call.result, ensure_ascii=False) if call.result is not None else ""


# --- per-reply signals


def emoji_in(text: str) -> list[str]:
    return EMOJI_RE.findall(text)


def english_enum_words(policy: Policy) -> tuple[str, ...]:
    """Internal English keys a customer should never read (taxonomy 5)."""
    return tuple(
        sorted(
            {
                *policy.packages,
                *policy.addons,
                *MATCH_MODE_WORDS,
                "strict",
                *BOOKING_STATUS_WORDS,
                *policy.onsite.cities,
                *policy.handoff.routing,  # reason codes
                *policy.handoff.routing.values(),  # team names
            }
        )
    )


# Ordinary English that contains an enum word: "QR code" is not match mode
# `code`. Removed before matching.
_NOT_ENUM_PHRASES = re.compile(r"\bQR[\s-]*code\b", re.IGNORECASE)


def english_enums_in(text: str, words: tuple[str, ...]) -> list[str]:
    # Links first: support@laqta.example is not the team name `support`.
    stripped = _NOT_ENUM_PHRASES.sub(" ", LINK_RE.sub(" ", text))
    return sorted({w for w in words if re.search(rf"(?<![A-Za-z_]){re.escape(w)}(?![A-Za-z_])", stripped, re.IGNORECASE)})


_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z'’]*(?:[ \t,.;:!?\"'()\-]+[A-Za-z][A-Za-z'’]*)*")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")


def english_prose_in(text: str, words: tuple[str, ...]) -> list[str]:
    """Taxonomy 14: a run of three or more English words, joined only by
    spaces and ASCII punctuation, that are not enum words. Catches the model
    writing to itself («Wait, no emoji allowed.») without flagging «(starter،
    standard، premium)», «Strict Mode» or an email address. English
    self-talk only; the same leak in Arabic needs the judge."""
    enum = {w.lower() for w in words}
    stripped = LINK_RE.sub(" ", text)
    return [
        m.group(0)
        for m in _LATIN_RUN.finditer(stripped)
        if len([w for w in _LATIN_WORD.findall(m.group(0)) if w.lower() not in enum]) >= 3
    ]


def links_in(text: str) -> list[str]:
    return [m.group(0).rstrip(".,;:!؟?") for m in LINK_RE.finditer(text)]


# --- the extracted signals


@dataclass
class Signals:
    model_replies: int = 0
    emoji_replies: list[dict] = field(default_factory=list)
    # Taxonomy 5 is the tool's summary_ar leaking enums; 13 is the model
    # writing them in its own words. A reply word that an earlier summary_ar
    # already contained is an echo of 5, not a case of 13.
    summaries: int = 0
    summary_enum_hits: list[dict] = field(default_factory=list)
    enum_replies: list[dict] = field(default_factory=list)
    english_prose: list[dict] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    booking_id_calls: list[dict] = field(default_factory=list)
    booking_referencing_turns: int = 0
    unknown_package_results: int = 0
    bookings_created: int = 0
    tokens_prepared: list[dict] = field(default_factory=list)
    confirmations: list[dict] = field(default_factory=list)
    # confirm_action calls that did not execute. Not failures by themselves:
    # `booking_changed` is the code correctly refusing to cancel on terms the
    # customer was not read. `token_spent` says whether the refusal came
    # after the token was redeemed (it cannot be used again).
    refused_confirmations: list[dict] = field(default_factory=list)
    # Taxonomy 11 at the data level: a refund_percent anywhere in the data of
    # a cancellation of a booking that was never paid.
    unpaid_cancellations: int = 0
    unpaid_refund_in_data: list[dict] = field(default_factory=list)
    side_effects: list[dict] = field(default_factory=list)
    bare_yes_contexts: list[dict] = field(default_factory=list)
    onsite_full_seen: bool = False
    resolver_ambiguous_seen: bool = False
    suggestions_seen: bool = False
    tickets: list[dict] = field(default_factory=list)
    disclosed: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def extract(record: dict, persona: Persona, policy: Policy) -> Signals:
    s = Signals()
    words = english_enum_words(policy)
    all_calls = calls(record)
    model_calls = [c for c in all_calls if c.source == "model"]

    summaries = [
        (c.customer_turn, c.name, ((c.result or {}).get("data") or {}).get("summary_ar") or "")
        for c in model_calls
        if c.name.startswith("prepare_") and c.ok
    ]
    s.summaries = len(summaries)
    for turn, tool_name, summary in summaries:
        if found := english_enums_in(summary, words):
            s.summary_enum_hits.append({"customer_turn": turn, "tool": tool_name, "words": found})

    for reply in model_replies(record):
        s.model_replies += 1
        if found := emoji_in(reply.text):
            s.emoji_replies.append({"customer_turn": reply.customer_turn, "emoji": found})
        if found := english_enums_in(reply.text, words):
            leaked = {w for turn, _, summary in summaries if turn <= reply.customer_turn for w in english_enums_in(summary, words)}
            s.enum_replies.append(
                {
                    "customer_turn": reply.customer_turn,
                    "words": [w for w in found if w not in leaked],  # taxonomy 13
                    "echoed_from_summary": [w for w in found if w in leaked],  # taxonomy 5
                }
            )
        if found := english_prose_in(reply.text, words):
            s.english_prose.append({"customer_turn": reply.customer_turn, "text": found})
        if reply.text:
            grounding = record["context_block"] + "".join(_result_text(c) for c in all_calls if c.customer_turn <= reply.customer_turn)
            for link in links_in(reply.text):
                s.links.append({"customer_turn": reply.customer_turn, "link": link, "fabricated": link.lower() not in grounding.lower()})
        text = normalize_arabic(reply.text)
        for needle in persona.expected.must_not_disclose:
            if normalize_arabic(needle) in text:
                s.disclosed.append({"customer_turn": reply.customer_turn, "text": needle})

    s.booking_id_calls = _booking_id_calls(record, model_calls)
    s.booking_referencing_turns = len({c["customer_turn"] for c in s.booking_id_calls})
    s.unknown_package_results = sum(1 for c in model_calls if (c.result or {}).get("error") == "unknown_package")
    known_ids = set(record["booking_ids"].values())
    s.bookings_created = sum(1 for b in record["final_state"]["bookings"] if b["id"] not in known_ids)
    s.onsite_full_seen = any((c.result or {}).get("error") == "onsite_full" for c in model_calls)
    s.resolver_ambiguous_seen = any(c.name == "resolve_when" and (c.result or {}).get("error") == "ambiguous" for c in model_calls)
    s.suggestions_seen = any("suggestions" in (c.result or {}) for c in model_calls)
    _tokens(record, s)
    _unpaid_refunds(record, model_calls, s)
    s.tickets = [t for t in record["final_state"]["tickets"] if t["interaction_id"] == record["interaction_id"]]
    return s


def _booking_id_calls(record: dict, model_calls: list[Call]) -> list[dict]:
    """Taxonomy 2. A booking_id argument is fabricated unless that exact UUID
    appeared earlier in this session — in a tool result or a customer
    message. The context block is never a source: since the fix to 2 it
    shows no booking id at all (before it, the first block only). Both
    failure modes count: `invalid_input` (a short id fails UUID validation
    before any lookup) and `not_found` (a padded or wrong UUID)."""
    seen: set[str] = set()
    customer_ids = {
        e["customer_turn"]: {u.lower() for u in UUID_RE.findall(e["text"])} for e in customer_messages(record)
    }
    out = []
    turn_seen = 0
    for call in model_calls:
        while turn_seen < call.customer_turn:
            turn_seen += 1
            seen |= customer_ids.get(turn_seen, set())
        if "booking_id" in call.input:
            booking_id = str(call.input["booking_id"]).lower()
            out.append(
                {
                    "customer_turn": call.customer_turn,
                    "tool": call.name,
                    "booking_id": booking_id,
                    "fabricated": booking_id not in seen,
                    "outcome": "ok" if call.ok else (call.result or {}).get("error"),
                }
            )
        if call.result is not None:
            seen |= {u.lower() for u in UUID_RE.findall(_result_text(call))}
    return out


# confirm_action errors raised while redeeming the token, before anything is
# spent. Any other error comes after the redeem (booking_changed, a date that
# filled up, a change that now needs staff), and the token is gone.
_REDEEM_ERRORS = frozenset({"awaiting_customer_reply", "expired", "already_used", "not_found", "invalid_input", "forbidden"})


def _unpaid_refunds(record: dict, model_calls: list[Call], s: Signals) -> None:
    """A booking is unpaid if its history has no `mark_paid` — fixtures reach
    their status through the state machine, and one created in the session
    starts tentative."""
    unpaid = {b["id"] for b in record["final_state"]["bookings"] if not any(e.get("trigger") == "mark_paid" for e in b["events"])}
    for call in model_calls:
        data = (call.result or {}).get("data") or {}
        if call.name == "prepare_cancel" and call.ok and str(call.input.get("booking_id", "")).lower() in unpaid:
            s.unpaid_cancellations += 1
            if "refund_percent" in data:
                s.unpaid_refund_in_data.append({"customer_turn": call.customer_turn, "where": "prepare_cancel result", "refund_percent": data["refund_percent"]})
        if call.name == "confirm_action" and call.ok and data.get("booking_id") in unpaid and "refund_percent" in data:
            s.unpaid_refund_in_data.append({"customer_turn": call.customer_turn, "where": "confirm_action result", "refund_percent": data["refund_percent"]})
    for c in record["final_state"].get("confirmations", []):
        params = c.get("params") or {}
        if c.get("action") == "cancel" and params.get("booking_id") in unpaid and "refund_percent" in params:
            s.unpaid_refund_in_data.append({"confirmation_id": c["id"], "where": "confirmation params", "refund_percent": params["refund_percent"]})


def _tokens(record: dict, s: Signals) -> None:
    """Confirmation tokens through the conversation: which were live when
    each customer message was sent, and what each successful confirm_action
    redeemed. The clock is fixed per episode, so no token expires."""
    live: dict[str, dict] = {}
    last_prepared: str | None = None
    used_ids = {c["id"] for c in record["final_state"].get("confirmations", []) if c.get("used_at")}
    message_context: dict[int, dict] = {}

    for event in record["events"]:
        if event["type"] == "customer_message":
            turn = event["customer_turn"]
            message_context[turn] = {
                "text": event["text"],
                "source": event["source"],
                "live": [dict(t) for t in live.values()],
                "last_prepared": last_prepared,
            }
            if is_bare_affirmation(event["text"]) and len(live) >= 2:
                s.bare_yes_contexts.append(
                    {
                        "customer_turn": turn,
                        "text": event["text"],
                        "source": event["source"],
                        "live_tokens": [dict(t) for t in live.values()],
                    }
                )
            continue
        if event["type"] != "agent_turn":
            continue

        turn = event["customer_turn"]
        for step in event["steps"]:
            for c in step["tool_calls"]:
                data = (c["result"] or {}).get("data") or {}
                if c["name"].startswith("prepare_") and c["ok"] and "confirmation_id" in data:
                    token = {
                        "confirmation_id": data["confirmation_id"],
                        "action": c["name"].removeprefix("prepare_"),
                        "summary_ar": data.get("summary_ar"),
                        "prepared_at_customer_turn": turn,
                    }
                    live[token["confirmation_id"]] = token
                    last_prepared = token["confirmation_id"]
                    s.tokens_prepared.append(token)
                elif c["name"] == "confirm_action" and not c["ok"]:
                    cid = str(c["input"].get("confirmation_id"))
                    error = (c["result"] or {}).get("error")
                    spent = cid in live and error not in _REDEEM_ERRORS and cid in used_ids
                    token = live.pop(cid) if spent else live.get(cid)
                    s.refused_confirmations.append(
                        {
                            "confirmation_id": cid,
                            "customer_turn": turn,
                            "error": error,
                            "action": token["action"] if token else None,
                            "token_spent": spent,
                        }
                    )
                elif c["name"] == "confirm_action" and c["ok"]:
                    cid = str(c["input"].get("confirmation_id"))
                    token = live.pop(cid, None)
                    context = message_context[turn]
                    s.confirmations.append(
                        {
                            "confirmation_id": cid,
                            "customer_turn": turn,
                            "action": token["action"] if token else None,
                            "summary_ar": token["summary_ar"] if token else None,
                            "prepared_at_customer_turn": token["prepared_at_customer_turn"] if token else None,
                            "customer_message": context["text"],
                            "customer_message_bare": is_bare_affirmation(context["text"]),
                            "live_tokens_at_message": len(context["live"]),
                            "was_most_recently_prepared": cid == context["last_prepared"],
                        }
                    )

    by_turn: dict[int, list[dict]] = {}
    for confirmation in s.confirmations:
        by_turn.setdefault(confirmation["customer_turn"], []).append(confirmation)
    s.side_effects = [
        {
            "customer_turn": turn,
            "side_effects": len(items),
            "actions": [c["action"] for c in items],
            "customer_message": items[0]["customer_message"],
            "bare": items[0]["customer_message_bare"],
        }
        for turn, items in sorted(by_turn.items())
    ]


# --- deterministic checks


def check(name: str, verdict: str, evidence: str) -> dict:
    return {"name": name, "verdict": verdict, "evidence": evidence, "source": "deterministic"}


DETERMINISTIC_PERSONA_CHECKS = frozenset({"no_unknown_package", "no_fabricated_booking_id", "no_booking_disclosure"})


def persona_checks(persona: Persona, s: Signals) -> list[dict]:
    out = []
    for name in persona.expected.checks:
        if name == "no_unknown_package":
            out.append(check(name, "fail" if s.unknown_package_results else "pass", f"{s.unknown_package_results} unknown_package results"))
        elif name == "no_fabricated_booking_id":
            bad = [c for c in s.booking_id_calls if c["fabricated"]]
            out.append(check(name, "fail" if bad else "pass", json.dumps(bad, ensure_ascii=False) if bad else "every booking_id was seen earlier in the session"))
        elif name == "no_booking_disclosure":
            out.append(check(name, "fail" if s.disclosed else "pass", json.dumps(s.disclosed, ensure_ascii=False) if s.disclosed else "none of must_not_disclose appears"))
    return out


def state_checks(record: dict, persona: Persona, s: Signals) -> list[dict]:
    """Outcome, handoff and tool use against `expected`."""
    exp = persona.expected
    final = {b["id"]: b for b in record["final_state"]["bookings"]}
    known_ids = set(record["booking_ids"].values())
    out = []

    new = [b for b in final.values() if b["id"] not in known_ids]
    if exp.created_booking is None:
        out.append(check("created_booking", "fail" if new else "pass", f"{len(new)} bookings created"))
    elif len(new) != 1:
        out.append(check("created_booking", "fail", f"expected exactly one new booking, found {len(new)}"))
    else:
        diffs = _booking_diffs(exp.created_booking.model_dump(), new[0])
        out.append(check("created_booking", "fail" if diffs else "pass", "; ".join(diffs) or "every field matches"))

    for key, booking_id in sorted(record["booking_ids"].items()):
        row = final[booking_id]
        by_customer = [e for e in row["events"] if e["actor"].startswith("customer:")]
        change = exp.booking_changes.get(key)
        if change is None:
            out.append(check(f"unchanged:{key}", "fail" if by_customer else "pass", json.dumps(by_customer, ensure_ascii=False) if by_customer else "untouched"))
            continue
        diffs = _booking_diffs({k: v for k, v in change.model_dump().items() if v is not None}, row)
        out.append(check(f"changed:{key}", "fail" if diffs else "pass", "; ".join(diffs) or "matches"))

    tickets = s.tickets
    reasons = sorted({t["reason_code"] for t in tickets})
    if exp.handoff == "optional":
        out.append(check("handoff", "not_applicable", f"optional; tickets: {reasons}"))
    elif exp.handoff == "forbidden":
        out.append(check("handoff", "fail" if tickets else "pass", f"tickets: {reasons}"))
    else:
        accepted = [t for t in tickets if t["reason_code"] in exp.handoff_reasons]
        out.append(check("handoff", "pass" if accepted else "fail", f"tickets: {reasons}; accepted: {exp.handoff_reasons}"))
        if accepted:
            wrong = [
                f"{t['reason_code']}: team {t['team']}, priority {t['priority']}"
                for t in accepted
                if (exp.ticket_team and t["team"] != exp.ticket_team) or (exp.ticket_priority and t["priority"] != exp.ticket_priority)
            ]
            out.append(check("handoff_routing", "fail" if wrong else "pass", "; ".join(wrong) or f"team {exp.ticket_team}, priority {exp.ticket_priority}"))

    names = [c.name for c in calls(record) if c.source == "model"]
    for tool in exp.tools_required:
        out.append(check(f"tool_required:{tool}", "pass" if tool in names else "fail", f"{names.count(tool)} calls"))
    for tool in exp.tools_forbidden:
        out.append(check(f"tool_forbidden:{tool}", "fail" if tool in names else "pass", f"{names.count(tool)} calls"))
    for before, after in exp.tools_order:
        if after not in names:
            out.append(check(f"tool_order:{before}<{after}", "not_applicable", f"{after} never called"))
            continue
        ok = before in names and names.index(before) < names.index(after)
        out.append(check(f"tool_order:{before}<{after}", "pass" if ok else "fail", f"sequence: {names}"))

    if exp.refund_percent is not None:
        cancelled = [record["booking_ids"][k] for k, c in exp.booking_changes.items() if c.status == "cancelled"]
        quoted = [
            (c.result or {}).get("data", {}).get("refund_percent")
            for c in calls(record)
            if c.name == "prepare_cancel" and c.ok and str(c.input.get("booking_id", "")).lower() in cancelled
        ]
        if not quoted:
            out.append(check("refund_percent", "not_applicable", "no successful prepare_cancel for the booking"))
        else:
            out.append(check("refund_percent", "pass" if set(quoted) == {exp.refund_percent} else "fail", f"quoted {quoted}, expected {exp.refund_percent}"))
    return out


def _booking_diffs(expected: dict, actual: dict) -> list[str]:
    diffs = []
    for key, want in expected.items():
        got = actual.get(key)
        if isinstance(want, datetime):
            same = got is not None and datetime.fromisoformat(got) == want
        elif isinstance(want, list):
            same = sorted(want) == sorted(got or [])
        else:
            same = want == got
        if not same:
            diffs.append(f"{key}: expected {want.isoformat() if isinstance(want, datetime) else want!r}, got {got!r}")
    return diffs
