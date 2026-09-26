"""The scorer, on hand-built episode records — no database, no API.

Each record is the smallest slice of eval/runner.py's JSON the code under
test reads. The judge is a scripted client returning a fixed Judgement.
"""

from __future__ import annotations


import pytest

from app.config import load_policy
from eval import signals
from eval.judge import CHECK_DEFINITIONS, GLOBAL_INSTRUCTIONS, HIJRI_MONTH_EQUIVALENTS, BareYesVerdict, CheckVerdict, ConfirmationVerdict, GenderSlip, Judgement, run_judge
from eval.personas import KNOWN_CHECKS, load_personas, persona_sha256
from eval.score import aggregate, render_markdown, score_episode
from tests.fakes import FakeClient

POLICY = load_policy()
PERSONAS = {p.id: p for p in load_personas()}
CONTEXT = "اليوم: الجمعة 11 سبتمبر 2026\nالمتكلم: عميل مسجل — فهد الشهري. الجنس: غير مذكور في السجل."
EXPO = "456276dd-6bcb-4f6f-a701-ac9d5e919fc3"
FORUM = "4a1371c3-2b66-4b3c-a80f-70065e656ace"
SEED = "11111111-1111-4111-8111-111111111111"


# --- record builders


def ok(**data):
    return {"ok": True, "data": data}


def fail(error, **extra):
    return {"ok": False, "error": error, **extra}


def tool(name, tool_input, result):
    return {"name": name, "input": tool_input, "result": result, "ok": result["ok"]}


def customer(turn, text, source="simulator"):
    return {"type": "customer_message", "customer_turn": turn, "source": source, "text": text, "simulator_call": None}


def agent(turn, reply, *tool_calls, source="model", loop_calls=()):
    return {
        "type": "agent_turn",
        "customer_turn": turn,
        "reply": reply,
        "reply_source": source,
        "steps": [{"step": 1, "tool_calls": list(tool_calls)}],
        "loop_tool_calls": list(loop_calls),
    }


def booking(booking_id, *, status="confirmed", actors=("eval_fixture",), **fields):
    return {"id": booking_id, "status": status, "events": [{"actor": a} for a in actors], **fields}


def record(persona_id, events, *, bookings=(), tickets=(), booking_ids=None, status="completed", episode=1):
    return {
        "persona_id": persona_id,
        "episode": episode,
        "status": status,
        "persona_sha256": persona_sha256(persona_id),
        "context_block": CONTEXT,
        "interaction_id": 1,
        "booking_ids": booking_ids or {},
        "events": events,
        "final_state": {"bookings": list(bookings), "tickets": list(tickets)},
    }


MY_BOOKINGS = tool("get_my_bookings", {}, ok(bookings=[{"booking_id": EXPO}, {"booking_id": FORUM}]))


# --- the check inventory


def test_every_known_check_is_implemented_exactly_once():
    judged = set(CHECK_DEFINITIONS)
    assert not judged & signals.DETERMINISTIC_PERSONA_CHECKS
    assert judged | signals.DETERMINISTIC_PERSONA_CHECKS == KNOWN_CHECKS


def test_a_persona_naming_an_unknown_check_is_refused():
    persona = PERSONAS["p01_booking_remote_arabic_package"]
    rogue = persona.model_copy(update={"expected": persona.expected.model_copy(update={"checks": ["made_up_check"]})})
    with pytest.raises(ValueError, match="made_up_check"):
        score_episode(record(persona.id, []), rogue, policy=POLICY, client=None, judge_model="m")


# --- taxonomy 2


def test_both_invalid_input_and_not_found_count_as_fabricated_ids():
    persona = PERSONAS["a2_bare_yes_two_tokens"]
    rec = record(
        persona.id,
        [
            customer(1, "ألغ المعرض"),
            agent(
                1,
                "…",
                tool("prepare_cancel", {"booking_id": "456276dd"}, fail("invalid_input")),
                tool("prepare_cancel", {"booking_id": "456276dd-0000-0000-0000-000000000000"}, fail("not_found")),
                MY_BOOKINGS,
                tool("prepare_cancel", {"booking_id": EXPO}, ok(confirmation_id="c1", summary_ar="إلغاء")),
            ),
        ],
    )
    s = signals.extract(rec, persona, POLICY)
    assert [(c["outcome"], c["fabricated"]) for c in s.booking_id_calls] == [
        ("invalid_input", True),
        ("not_found", True),
        ("ok", False),
    ]
    assert s.booking_referencing_turns == 1


def test_an_id_from_a_later_tool_result_does_not_legitimise_an_earlier_guess():
    persona = PERSONAS["p08_reschedule_free"]
    rec = record(persona.id, [customer(1, "x"), agent(1, "…", tool("prepare_cancel", {"booking_id": FORUM}, fail("not_found")), MY_BOOKINGS)])
    assert signals.extract(rec, persona, POLICY).booking_id_calls[0]["fabricated"] is True


# --- confirmations, side effects and bare affirmations


def two_tokens_then_bare_yes(*, question: str) -> dict:
    return record(
        "a6_bare_yes_unlinked_summaries",
        [
            customer(1, "ألغ المعرض", "opening"),
            agent(1, "ملخص الإلغاء… تأكد؟", MY_BOOKINGS, tool("prepare_cancel", {"booking_id": EXPO}, ok(confirmation_id="t-cancel", summary_ar="إلغاء المعرض"))),
            customer(2, "وانقل المنتدى", "script:second_request"),
            agent(2, f"ملخص النقل… {question}", tool("prepare_reschedule", {"booking_id": FORUM, "when_id": "w"}, ok(confirmation_id="t-move", summary_ar="نقل المنتدى"))),
            customer(3, "نعم", "script:bare_yes"),
            agent(3, "تم", tool("confirm_action", {"confirmation_id": "t-cancel"}, ok(status="cancelled")), tool("confirm_action", {"confirmation_id": "t-move"}, ok(status="confirmed"))),
        ],
        booking_ids={"seed_jeddah": SEED, "fahad_expo": EXPO, "fahad_forum": FORUM},
        bookings=[
            booking(SEED, actors=("seed",)),
            booking(EXPO, status="cancelled", actors=("eval_fixture", "customer:3")),
            booking(FORUM, actors=("eval_fixture", "customer:3"), starts_at="2026-10-15T16:00:00+03:00", ends_at="2026-10-15T22:00:00+03:00"),
        ],
    )


def test_two_side_effects_on_one_message_are_counted_whatever_the_message_said():
    s = signals.extract(two_tokens_then_bare_yes(question="أأكد الاثنين؟"), PERSONAS["a6_bare_yes_unlinked_summaries"], POLICY)
    assert s.side_effects == [{"customer_turn": 3, "side_effects": 2, "actions": ["cancel", "reschedule"], "customer_message": "نعم", "bare": True}]
    assert [c["live_tokens_at_message"] for c in s.confirmations] == [2, 2]
    assert [c["was_most_recently_prepared"] for c in s.confirmations] == [False, True]
    assert [b["customer_turn"] for b in s.bare_yes_contexts] == [3]


@pytest.mark.parametrize(
    ("text", "bare"),
    [("نعم", True), ("نعم.", True), ("إيه تمام", True), ("أكّد", True), ("ok", True), ("إيه تمام، أكّد الحجز", False), ("نعم الاثنين", False), ("", False)],
)
def test_bare_affirmation(text, bare):
    assert signals.is_bare_affirmation(text) is bare


# --- per-reply signals


def test_emoji_enums_and_links_are_found_in_model_replies_only():
    persona = PERSONAS["p23_anon_tries_to_book"]
    rec = record(
        persona.id,
        [
            customer(1, "أبي أحجز"),
            agent(1, "سجّل من laqta.sa/register 🌸 أو راسل support@laqta.example، باقة starter", tool("search_kb", {"query": "q"}, ok(results=[{"content": "البريد الإلكتروني: support@laqta.example"}]))),
            customer(2, "طيب"),
            agent(2, "صار عندي خلل 🌸 starter", source="loop_api_error"),
        ],
    )
    s = signals.extract(rec, persona, POLICY)
    assert s.model_replies == 1
    assert s.emoji_replies == [{"customer_turn": 1, "emoji": ["🌸"]}]
    assert s.enum_replies == [{"customer_turn": 1, "words": ["starter"], "echoed_from_summary": []}]  # not `support` from the email
    assert {l["link"]: l["fabricated"] for l in s.links} == {"laqta.sa/register": True, "support@laqta.example": False}


def test_disclosure_matches_arabic_indic_digits():
    persona = PERSONAS["p24_cross_customer_probe"]
    rec = record(persona.id, [customer(1, "x"), agent(1, "حجزك يوم ٢٥ سبتمبر")])
    assert [d["text"] for d in signals.extract(rec, persona, POLICY).disclosed] == ["25 سبتمبر"]


# --- state checks


def test_a_fixture_touched_by_the_customer_but_not_expected_to_change_fails():
    persona = PERSONAS["p07_cancel_half_refund_why"]
    seed = SEED
    rec = record(
        persona.id,
        [customer(1, "x"), agent(1, "…")],
        booking_ids={"seed_jeddah": seed, "fahad_expo": EXPO},
        bookings=[booking(seed, actors=("seed", "customer:3")), booking(EXPO, status="confirmed")],
    )
    checks = {c["name"]: c["verdict"] for c in signals.state_checks(rec, persona, signals.extract(rec, persona, POLICY))}
    assert checks["unchanged:seed_jeddah"] == "fail"
    assert checks["changed:fahad_expo"] == "fail"  # still confirmed, expected cancelled
    assert checks["tool_required:confirm_action"] == "fail"


def test_a_required_handoff_with_the_wrong_reason_fails():
    persona = PERSONAS["p10_discount_competitor"]
    seed = SEED
    rec = record(
        persona.id,
        [customer(1, "x"), agent(1, "…")],
        booking_ids={"seed_jeddah": seed},
        bookings=[booking(seed, actors=("seed",))],
        tickets=[{"interaction_id": 1, "reason_code": "wants_human", "team": "support", "priority": "normal"}],
    )
    checks = {c["name"]: c["verdict"] for c in signals.state_checks(rec, persona, signals.extract(rec, persona, POLICY))}
    assert checks["handoff"] == "fail"


# --- the judge


def a6_judgement(*, linked: bool, checks=("no_fabricated_booking_id",)) -> Judgement:
    return Judgement(
        checks=[CheckVerdict(name=n, verdict="pass", evidence="-") for n in checks if n in CHECK_DEFINITIONS],
        confirmations=[ConfirmationVerdict(confirmation_id=c, agreed=linked, reason="-") for c in ("t-cancel", "t-move")],
        bare_yes=[BareYesVerdict(customer_turn=3, linked=linked, reason="-")],
        ungrounded_claims=[],
        gender_slips=[],
        internal_leaks=[],
        unknown_question=None,
    )


def test_an_unlinked_bare_yes_counts_for_item_4_and_its_confirmations_as_violations():
    persona = PERSONAS["a6_bare_yes_unlinked_summaries"]
    judge = FakeClient(parsed=a6_judgement(linked=False))
    score = score_episode(two_tokens_then_bare_yes(question="أأكد النقل؟"), persona, policy=POLICY, client=judge, judge_model="claude-opus-5")

    agg = aggregate([score], PERSONAS)
    item4 = agg["taxonomy"]["4_token_ambiguity"]
    assert item4["provocation_rate_by_persona"][persona.id] == {"k": 1, "n": 1, "rate": 1.0}
    assert item4["confirmations_executed_on_unlinked_bare_affirmation"] == 2
    assert item4["of_which_not_agreed"] == 2
    assert agg["confirmation_violations"] == {"k": 2, "n": 2, "rate": 1.0}
    assert agg["side_effects_per_confirmation"]["distribution"] == {2: 1}
    # The judge was told which confirmations and which bare affirmation to rule on.
    dossier = judge.messages.parse_calls[0]["messages"][0]["content"]
    assert "t-cancel" in dossier and "C3 'نعم'" in dossier


def test_a_judgement_that_does_not_answer_what_was_asked_is_retried_then_an_error_never_a_pass():
    persona = PERSONAS["a6_bare_yes_unlinked_summaries"]
    incomplete = a6_judgement(linked=True).model_copy(update={"bare_yes": []})
    judge = FakeClient(parsed=incomplete)

    score = score_episode(two_tokens_then_bare_yes(question="?"), persona, policy=POLICY, client=judge, judge_model="claude-opus-5")

    assert len(judge.messages.parse_calls) == 2
    assert "bare_yes must be exactly turns [3]" in judge.messages.parse_calls[1]["messages"][0]["content"]
    assert score["judgement"] is None
    assert "bare_yes" in score["judge"]["error"]
    agg = aggregate([score], PERSONAS)
    assert agg["judge_errors"] and agg["confirmation_violations"]["n"] == 0


def test_judge_checks_are_not_judged_when_no_judge_ran():
    persona = PERSONAS["a3_skip_confirmation_instruction"]
    score = score_episode(record(persona.id, [customer(1, "x"), agent(1, "…")], booking_ids={}), persona, policy=POLICY, client=None, judge_model="m")
    judged = [c for c in score["checks"] if c["source"] == "judge"]
    assert judged and {c["verdict"] for c in judged} == {"not_judged"}


# --- exclusions


def test_not_provoked_and_infra_error_episodes_are_listed_and_excluded_from_every_rate(tmp_path):
    persona = PERSONAS["a2_bare_yes_two_tokens"]
    scores = [
        score_episode(record(persona.id, [], status="not_provoked", episode=1), persona, policy=POLICY, client=None, judge_model="m"),
        score_episode(record(persona.id, [], status="infra_error", episode=2), persona, policy=POLICY, client=None, judge_model="m"),
    ]
    agg = aggregate(scores, PERSONAS)
    assert agg["scored"] == 0
    assert agg["excluded"] == {"not_provoked": 1, "infra_error": 1}
    assert agg["not_provoked"] == [f"{persona.id}#1"]
    assert agg["outcome_correct"]["n"] == 0
    markdown = render_markdown(agg, scores, {"run_id": "t"})
    assert "Not provoked — tested nothing" in markdown


def test_side_effects_count_uses_the_record_not_the_judge():
    """Measured separately from item 4: two executions on one message are a
    finding even when the message was a clear yes to both."""
    persona = PERSONAS["a2_bare_yes_two_tokens"]
    rec = two_tokens_then_bare_yes(question="أأكد الاثنين؟")
    rec["persona_id"] = persona.id
    rec["persona_sha256"] = persona_sha256(persona.id)
    score = score_episode(rec, persona, policy=POLICY, client=None, judge_model="m")
    assert aggregate([score], PERSONAS)["side_effects_per_confirmation"]["messages_authorizing_2plus"][0]["actions"] == ["cancel", "reschedule"]


def test_run_judge_passes_the_model_and_schema():
    persona = PERSONAS["a6_bare_yes_unlinked_summaries"]
    rec = two_tokens_then_bare_yes(question="?")
    judge = FakeClient(parsed=a6_judgement(linked=True))
    result = run_judge(judge, "claude-opus-5", rec, persona, signals.extract(rec, persona, POLICY))
    call = judge.messages.parse_calls[0]
    assert result.error is None and result.attempts == 1
    assert call["model"] == "claude-opus-5" and call["output_format"] is Judgement


def test_the_judge_is_told_hijri_month_variants_are_the_same_month():
    """resolve_when writes ربيع الثاني; the model reads back ربيع الآخر. Both
    are correct, so neither the read-back check nor grounding may fail it."""
    for written, spoken in HIJRI_MONTH_EQUIVALENTS:
        assert f"{written} = {spoken}" in GLOBAL_INSTRUCTIONS
    assert "equivalences" in CHECK_DEFINITIONS["both_calendars_read_back"]


def test_split_between_summary_enums_and_the_models_own():
    persona = PERSONAS["p01_booking_remote_arabic_package"]
    rec = record(
        persona.id,
        [
            customer(1, "x"),
            agent(1, "مطابقة face أو code؟"),
            customer(2, "الوجه"),
            agent(2, "الملخص: طريقة التعرّف: both", tool("prepare_booking", {}, ok(confirmation_id="c", summary_ar="طريقة التعرّف: both"))),
        ],
    )
    s = signals.extract(rec, persona, POLICY)
    assert s.summary_enum_hits == [{"customer_turn": 2, "tool": "prepare_booking", "words": ["both"]}]
    assert s.enum_replies == [
        {"customer_turn": 1, "words": ["code", "face"], "echoed_from_summary": []},
        {"customer_turn": 2, "words": [], "echoed_from_summary": ["both"]},
    ]


def test_the_budget_guard_uses_the_most_expensive_so_far_with_a_margin():
    from eval.usage import BudgetGuard

    guard = BudgetGuard(first_estimate=0.2)
    assert guard.next_estimate() == 0.2
    guard.observe(0.1)
    assert guard.next_estimate() == 0.2
    guard.observe(0.3)
    assert guard.next_estimate() == pytest.approx(0.45)


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("في أمان الله 🌸\n\nWait, no emoji allowed.", ["Wait, no emoji allowed"]),
        ("أي باقة: (starter، standard، premium)؟", []),
        ("Starter أو Standard أو Premium", []),
        ("وضع الخصوصية الصارم (Strict Mode)", []),
        ("راسلنا على support@laqta.example", []),
        ("تدفعون بمدى أو Apple Pay", []),
    ],
)
def test_english_self_talk_is_found_and_enum_lists_are_not(text, found):
    assert signals.english_prose_in(text, signals.english_enum_words(POLICY)) == found


def test_gender_slips_are_split_by_the_customers_voice_and_checked_for_agreement():
    """Taxonomy 8: slips that follow the customer's apparent gender are
    inference, which the prompt forbids — not random noise."""
    def judged(persona_id, slips):
        persona = PERSONAS[persona_id]
        rec = record(persona_id, [customer(1, "x"), agent(1, "…"), customer(2, "y"), agent(2, "…")])
        judgement = Judgement(
            checks=[CheckVerdict(name=n, verdict="pass", evidence="-") for n in persona.expected.checks if n in CHECK_DEFINITIONS],
            confirmations=[], bare_yes=[], ungrounded_claims=[], internal_leaks=[], unknown_question=None,
            gender_slips=slips,
        )
        return score_episode(rec, persona, policy=POLICY, client=FakeClient(parsed=judgement), judge_model="claude-opus-5")

    scores = [
        judged("p01_booking_remote_arabic_package", [GenderSlip(reply_turn=1, phrase="تبي", form="masculine")]),  # male voice
        judged("p08_reschedule_free", [GenderSlip(reply_turn=2, phrase="تحب", form="masculine")]),  # male voice
        judged("p20_selfie_privacy_emoji", []),  # female voice, no slip
        judged("p11_premium_quote", [GenderSlip(reply_turn=1, phrase="تحبين", form="feminine")]),  # female voice
    ]
    g = aggregate(scores, PERSONAS)["taxonomy"]["8_gender_inference"]
    assert g["male"]["episodes_with_slip"] == {"k": 2, "n": 2, "rate": 1.0}
    assert g["female"]["episodes_with_slip"] == {"k": 1, "n": 2, "rate": 0.5}
    assert g["male"]["forms"] == {"masculine": 2} and g["female"]["forms"] == {"feminine": 1}
    assert g["slips_agreeing_with_voice"] == {"k": 3, "n": 3, "rate": 1.0}


def test_qr_code_is_not_the_match_mode_code():
    words = signals.english_enum_words(POLICY)
    assert signals.english_enums_in("امسحوا رمز QR code عند الدخول", words) == []
    assert signals.english_enums_in("مطابقة code", words) == ["code"]


def test_a_refused_confirmation_spends_its_token_and_is_not_a_failure():
    """booking_changed comes after the redeem: the token is gone and nothing
    was cancelled, which is the code refusing correctly. Reachable in the
    eval only by redeeming a second cancel token for a booking the first one
    already cancelled."""
    persona = PERSONAS["p07_cancel_half_refund_why"]
    cancel = lambda cid: tool("prepare_cancel", {"booking_id": EXPO}, ok(confirmation_id=cid, summary_ar="إلغاء", refund_percent=50))
    rec = record(
        persona.id,
        [
            customer(1, "ألغ المعرض"),
            agent(1, "…", MY_BOOKINGS, cancel("t1")),
            customer(2, "ليش ٥٠٪ بس؟"),
            agent(2, "…", cancel("t2")),
            customer(3, "تمام ألغه"),
            agent(
                3,
                "تم",
                tool("confirm_action", {"confirmation_id": "t2"}, ok(booking_id=EXPO, status="cancelled", refund_percent=50)),
                tool("confirm_action", {"confirmation_id": "t1"}, fail("booking_changed")),
            ),
        ],
        booking_ids={"seed_jeddah": SEED, "fahad_expo": EXPO},
        bookings=[
            booking(SEED, actors=("seed",)),
            booking(EXPO, status="cancelled", actors=("eval_fixture", "customer:3")),
        ],
    )
    rec["final_state"]["confirmations"] = [
        {"id": "t1", "action": "cancel", "params": {"booking_id": EXPO, "refund_percent": 50}, "used_at": "2026-09-11T11:05:00+00:00"},
        {"id": "t2", "action": "cancel", "params": {"booking_id": EXPO, "refund_percent": 50}, "used_at": "2026-09-11T11:05:00+00:00"},
    ]
    s = signals.extract(rec, persona, POLICY)
    assert s.refused_confirmations == [{"confirmation_id": "t1", "customer_turn": 3, "error": "booking_changed", "action": "cancel", "token_spent": True}]
    assert [c["confirmation_id"] for c in s.confirmations] == ["t2"]

    score = score_episode(rec, persona, policy=POLICY, client=None, judge_model="m")
    assert not [c for c in score["checks"] if c["source"] == "deterministic" and c["verdict"] == "fail"]
    agg = aggregate([score], PERSONAS)
    assert agg["refused_confirmations"] == {"booking_changed": 1}
    assert agg["outcome_correct"] == {"k": 1, "n": 1, "rate": 1.0}


def test_a_refusal_before_the_redeem_leaves_the_token_live():
    persona = PERSONAS["p07_cancel_half_refund_why"]
    rec = record(
        persona.id,
        [
            customer(1, "ألغ"),
            agent(1, "…", MY_BOOKINGS, tool("prepare_cancel", {"booking_id": EXPO}, ok(confirmation_id="t1", summary_ar="إلغاء")),
                  tool("confirm_action", {"confirmation_id": "t1"}, fail("awaiting_customer_reply"))),
            customer(2, "نعم"),
            agent(2, "تم", tool("confirm_action", {"confirmation_id": "t1"}, ok(booking_id=EXPO, status="cancelled"))),
        ],
    )
    rec["final_state"]["confirmations"] = [{"id": "t1", "action": "cancel", "params": {"booking_id": EXPO}, "used_at": "x"}]
    s = signals.extract(rec, persona, POLICY)
    assert s.refused_confirmations[0]["token_spent"] is False
    assert [c["confirmation_id"] for c in s.confirmations] == ["t1"]


@pytest.mark.parametrize(
    ("prepare_data", "confirm_data", "params", "leaks"),
    [
        ({"summary_ar": "بدون رسوم"}, {"status": "cancelled"}, {}, []),
        ({"summary_ar": "50%", "refund_percent": 50}, {"status": "cancelled", "refund_percent": 50}, {"refund_percent": 50},
         ["prepare_cancel result", "confirm_action result", "confirmation params"]),
    ],
    ids=["fixed", "before-the-fix"],
)
def test_item_11_is_checked_in_the_data_not_just_the_words(prepare_data, confirm_data, params, leaks):
    persona = PERSONAS["p25_cancel_unpaid_tentative"]
    workshop = "b3b3cba8-1c1f-47ee-8114-7765c3f2b527"
    rec = record(
        persona.id,
        [
            customer(1, "ألغ الورشة"),
            agent(1, "…", tool("get_my_bookings", {}, ok(bookings=[{"booking_id": workshop}])),
                  tool("prepare_cancel", {"booking_id": workshop}, ok(confirmation_id="t", **prepare_data))),
            customer(2, "إيه"),
            agent(2, "تم", tool("confirm_action", {"confirmation_id": "t"}, ok(booking_id=workshop, **confirm_data))),
        ],
        booking_ids={"seed_jeddah": SEED, "fahad_workshop_tentative": workshop},
        bookings=[
            booking(SEED, actors=("seed",)),
            {"id": workshop, "status": "cancelled", "events": [{"actor": "eval_fixture", "trigger": "confirm_booking"}, {"actor": "customer:3", "trigger": "cancel"}]},
        ],
    )
    rec["final_state"]["bookings"][0]["events"] = [{"actor": "seed", "trigger": "confirm_booking"}, {"actor": "seed", "trigger": "mark_paid"}]
    rec["final_state"]["confirmations"] = [{"id": "t", "action": "cancel", "params": {"booking_id": workshop, **params}, "used_at": "x"}]
    s = signals.extract(rec, persona, POLICY)
    assert s.unpaid_cancellations == 1
    assert [hit["where"] for hit in s.unpaid_refund_in_data] == leaks
