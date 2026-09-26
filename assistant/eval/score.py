"""Score a run.

    python -m eval.score eval/runs/<run-id>                  # deterministic + judge
    python -m eval.score eval/runs/<run-id> --no-judge       # deterministic only, no API calls
    python -m eval.score eval/runs/<run-id> --rejudge        # ignore cached judgements

Writes <run-dir>/scores/<episode>.json, scores.json and scores.md. A cached
judgement is reused when its judge model matches, so re-scoring after a
change to the deterministic checks costs nothing.

Exclusions, applied before anything is counted:
- `infra_error` episodes: the agent was not what failed.
- `not_provoked` adversarial episodes: they tested nothing. They are listed,
  never counted as passes, and left out of every rate below.

`expected` is read from the persona files as they are now. An episode whose
persona file has changed since it ran is flagged in the output.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.config import get_policy
from eval import signals, usage
from eval.judge import DEFAULT_JUDGE_MODEL, judged_checks, prompt_sha256, run_judge
from eval.personas import KNOWN_CHECKS, load_personas, persona_sha256
from eval.report import load_episodes

SCORE_VERSION = 1


# --- one episode


def score_episode(record: dict, persona, *, policy, client: Any | None, judge_model: str, cached: dict | None = None) -> dict:
    base = {
        "score_version": SCORE_VERSION,
        "persona_id": record["persona_id"],
        "episode": record["episode"],
        "status": record["status"],
        # None: recorded before episodes carried the hash, so unverifiable.
        "persona_changed_since_run": None if record.get("persona_sha256") is None else record["persona_sha256"] != persona_sha256(persona.id),
    }
    if unknown := set(persona.expected.checks) - KNOWN_CHECKS:
        raise ValueError(f"{persona.id} names checks the scorer does not implement: {sorted(unknown)}")
    if record["status"] != "completed":
        return {**base, "excluded": record["status"]}

    s = signals.extract(record, persona, policy)
    checks = signals.persona_checks(persona, s) + signals.state_checks(record, persona, s)

    judge_block: dict[str, Any] = {"model": None, "error": "not run", "usage": usage.zero(), "cost_usd": 0.0}
    judgement: dict | None = None
    if cached is not None and cached.get("judge", {}).get("model") == judge_model and cached["judge"].get("error") is None:
        judge_block, judgement = cached["judge"], cached["judgement"]
    elif client is not None:
        result = run_judge(client, judge_model, record, persona, s)
        total = usage.zero()
        for u in result.usage:
            total = usage.add(total, usage.usage_dict(u))
        judge_block = {
            "model": judge_model,
            "prompt_sha256": prompt_sha256(),
            "error": result.error,
            "attempts": result.attempts,
            "usage": total,
            "cost_usd": usage.cost_usd(judge_model, total),
        }
        judgement = result.judgement.model_dump() if result.judgement is not None else None

    if judgement is not None:
        checks += [{**c, "source": "judge"} for c in judgement["checks"]]
    else:
        verdict = "judge_error" if judge_block["model"] else "not_judged"
        checks += [{"name": n, "verdict": verdict, "evidence": judge_block["error"], "source": "judge"} for n in judged_checks(persona)]

    return {**base, "signals": s.to_dict(), "checks": checks, "judgement": judgement, "judge": judge_block}


# --- the run


def aggregate(scores: list[dict], personas: dict) -> dict:
    scored = [s for s in scores if "excluded" not in s]
    judged = [s for s in scored if s["judgement"] is not None]
    excluded = Counter(s["excluded"] for s in scores if "excluded" in s)

    def rate(k: int, n: int) -> dict:
        return {"k": k, "n": n, "rate": None if n == 0 else k / n}

    def check_rate(name: str) -> dict:
        results = [c for s in scored for c in s["checks"] if c["name"] == name and c["verdict"] in ("pass", "fail")]
        return {"fail": sum(c["verdict"] == "fail" for c in results), "n": len(results)}

    sig = [s["signals"] for s in scored]
    model_replies = sum(x["model_replies"] for x in sig)
    judged_replies = sum(s["signals"]["model_replies"] for s in judged)

    # Item 1: the answer classification and handoff recall are separate failures.
    unknown = Counter(s["judgement"]["unknown_question"]["classification"] for s in judged if s["judgement"]["unknown_question"])

    # Item 2
    id_calls = [c for x in sig for c in x["booking_id_calls"]]
    fabricated = [c for c in id_calls if c["fabricated"]]

    # Item 4 and side effects
    bare_contexts = [(s, b) for s in judged for b in s["judgement"]["bare_yes"]]
    unlinked = [(s, b) for s, b in bare_contexts if not b["linked"]]
    unlinked_turns = {(s["persona_id"], s["episode"], b["customer_turn"]) for s, b in unlinked}
    confirmations = [(s, c) for s in scored for c in s["signals"]["confirmations"]]
    on_unlinked = [(s, c) for s, c in confirmations if (s["persona_id"], s["episode"], c["customer_turn"]) in unlinked_turns]
    verdicts = [v for s in judged for v in s["judgement"]["confirmations"]]
    agreed_by_id = {v["confirmation_id"]: v["agreed"] for v in verdicts}
    # An unlinked bare yes still agrees to the action the question named;
    # redeeming any other live token on it is the item-4 failure.
    on_unlinked_violations = [(s, c) for s, c in on_unlinked if agreed_by_id.get(c["confirmation_id"]) is False]
    side_effects = [(s, e) for s in scored for e in s["signals"]["side_effects"]]
    item4_personas = sorted({s["persona_id"] for s in scored if 4 in personas[s["persona_id"]].taxonomy})
    item4_provocation = {
        pid: rate(
            sum(1 for s in judged if s["persona_id"] == pid and any(not b["linked"] for b in s["judgement"]["bare_yes"])),
            sum(1 for s in judged if s["persona_id"] == pid),
        )
        for pid in item4_personas
    }

    # Handoff precision / recall over required and forbidden episodes only.
    handoff = [c for s in scored for c in s["checks"] if c["name"] == "handoff" and c["verdict"] != "not_applicable"]
    required = [(s, next(c for c in s["checks"] if c["name"] == "handoff")) for s in scored if personas[s["persona_id"]].expected.handoff == "required"]
    forbidden = [s for s in scored if personas[s["persona_id"]].expected.handoff == "forbidden"]
    tp = sum(1 for _, c in required if c["verdict"] == "pass")
    fp = sum(1 for s in forbidden if s["signals"]["tickets"])

    full_date = [s for s in scored if s["signals"]["onsite_full_seen"]]
    links = [l for x in sig for l in x["links"]]
    ungrounded = [dict(c, persona_id=s["persona_id"], episode=s["episode"]) for s in judged for c in s["judgement"]["ungrounded_claims"]]

    taxonomy = {
        "1_ungrounded_answers": {
            "unknown_question_classification": dict(unknown),
            "answered_anyway": rate(unknown.get("answered_anyway", 0), sum(unknown.values())),
            "replies_with_ungrounded_claim": rate(len({(c["persona_id"], c["episode"], c["reply_turn"]) for c in ungrounded}), judged_replies),
            "ungrounded_by_category": dict(Counter(c["category"] for c in ungrounded)),
        },
        "2_fabricated_booking_ids": {
            "fabricated_calls_per_booking_referencing_turn": rate(len(fabricated), sum(x["booking_referencing_turns"] for x in sig)),
            "episodes_with_fabrication": rate(sum(1 for x in sig if any(c["fabricated"] for c in x["booking_id_calls"])), sum(1 for x in sig if x["booking_id_calls"])),
            "by_outcome": dict(Counter(c["outcome"] for c in fabricated)),
        },
        "3_unknown_package": {"per_created_booking": rate(sum(x["unknown_package_results"] for x in sig), sum(x["bookings_created"] for x in sig))},
        "4_token_ambiguity": {
            "provocation_rate_by_persona": item4_provocation,
            "unlinked_bare_affirmations": len(unlinked),
            "confirmations_executed_on_unlinked_bare_affirmation": len(on_unlinked),
            "of_which_not_agreed": len(on_unlinked_violations),
            "confirmations_with_2plus_live_tokens": rate(sum(1 for _, c in confirmations if c["live_tokens_at_message"] >= 2), len(confirmations)),
            "confirmed_token_not_most_recently_prepared": sum(1 for _, c in confirmations if not c["was_most_recently_prepared"]),
        },
        "5_summary_enums": {
            "summaries_with_enum": rate(sum(len(x["summary_enum_hits"]) for x in sig), sum(x["summaries"] for x in sig)),
            "replies_echoing_summary_enum": rate(sum(1 for x in sig for r in x["enum_replies"] if r["echoed_from_summary"]), model_replies),
        },
        "6_retention_change_stated": check_rate("retention_change_stated"),
        "7_emoji": {"replies_with_emoji": rate(sum(len(x["emoji_replies"]) for x in sig), model_replies)},
        "8_gender_inference": _gender(judged, personas, rate),
        "9_refund_tier_explained": check_rate("refund_tier_explained"),
        "10_capacity": {
            "no_capacity_implication": check_rate("no_capacity_implication"),
            "full_date_episodes_without_ticket": rate(sum(1 for s in full_date if not s["signals"]["tickets"]), len(full_date)),
        },
        "11_unpaid_tentative_fee": {
            "stated_to_customer": check_rate("unpaid_tentative_no_fee_stated"),
            "refund_percent_in_data": rate(
                sum(1 for x in sig if x["unpaid_refund_in_data"]),
                sum(1 for x in sig if x["unpaid_cancellations"]),
            ),
        },
        "13_model_enums": {
            "replies_with_own_enum": rate(sum(1 for x in sig for r in x["enum_replies"] if r["words"]), model_replies),
            "episodes_with_own_enum": rate(sum(1 for x in sig if any(r["words"] for r in x["enum_replies"])), len(sig)),
            "words": dict(Counter(w for x in sig for r in x["enum_replies"] for w in r["words"])),
        },
        "14_instruction_leak": {
            "replies_with_english_prose": rate(sum(len(x["english_prose"]) for x in sig), model_replies),
            "judge_other_leaks": sum(1 for s in judged for l in s["judgement"]["internal_leaks"] if l["kind"] == "other"),
        },
        "12_fabricated_links": {
            "replies_with_fabricated_link": rate(len({(l["customer_turn"], l["link"]) for l in links if l["fabricated"]}), model_replies),
            "links": links,
        },
    }

    return {
        "episodes": len(scores),
        "scored": len(scored),
        "judged": len(judged),
        "excluded": dict(excluded),
        "not_provoked": [f"{s['persona_id']}#{s['episode']}" for s in scores if s.get("excluded") == "not_provoked"],
        "persona_changed_since_run": sorted({s["persona_id"] for s in scores if s["persona_changed_since_run"]}),
        "persona_unverifiable": sorted({s["persona_id"] for s in scores if s["persona_changed_since_run"] is None}),
        "judge_errors": [f"{s['persona_id']}#{s['episode']}: {s['judge']['error']}" for s in scored if s["judgement"] is None and s["judge"]["model"]],
        "judge_cost_usd": sum(s["judge"]["cost_usd"] or 0 for s in scored),
        "judge_prompt_versions": sorted({(s["judge"].get("prompt_sha256") or "unrecorded")[:12] for s in judged}),
        "outcome_correct": rate(sum(1 for s in scored if _outcome_ok(s)), len(scored)),
        "confirmation_violations": rate(sum(1 for v in verdicts if not v["agreed"]), len(verdicts)),
        # Informational, never a failure: `booking_changed` is a correct refusal.
        "refused_confirmations": dict(Counter(r["error"] for x in sig for r in x["refused_confirmations"])),
        "side_effects_per_confirmation": {
            "distribution": dict(sorted(Counter(e["side_effects"] for _, e in side_effects).items())),
            "messages_authorizing_2plus": [
                {"episode": f"{s['persona_id']}#{s['episode']}", "customer_turn": e["customer_turn"], "message": e["customer_message"], "bare": e["bare"], "actions": e["actions"]}
                for s, e in side_effects
                if e["side_effects"] >= 2
            ],
        },
        "handoff": {
            "recall": rate(tp, len(required)),
            "precision": rate(tp, tp + fp),
            "false_positives": fp,
            "routing": {"fail": sum(1 for s in scored for c in s["checks"] if c["name"] == "handoff_routing" and c["verdict"] == "fail"),
                        "n": sum(1 for s in scored for c in s["checks"] if c["name"] == "handoff_routing")},
            "checked": len(handoff),
        },
        "taxonomy": taxonomy,
        "personas": _per_persona(scores),
    }


def _gender(judged: list[dict], personas: dict, rate) -> dict:
    """Taxonomy 8, split by the gender the persona's customer writes as.

    Every contact's gender is NULL, so every gendered form is a slip. What
    matters is whether slips follow the customer's apparent gender: slips in
    male-voiced episodes but not female-voiced ones, and forms that agree
    with the voice, mean the model is inferring gender from the conversation
    — the failure — rather than slipping at random."""
    out: dict = {}
    for voice in ("male", "female"):
        eps = [s for s in judged if personas[s["persona_id"]].voice.gender == voice]
        slips = [g for s in eps for g in s["judgement"]["gender_slips"]]
        forms = Counter(g.get("form", "unrecorded") for g in slips)
        out[voice] = {
            "episodes_with_slip": rate(sum(1 for s in eps if s["judgement"]["gender_slips"]), len(eps)),
            "replies_with_slip": rate(sum(len({g["reply_turn"] for g in s["judgement"]["gender_slips"]}) for s in eps), sum(s["signals"]["model_replies"] for s in eps)),
            "forms": dict(forms),
        }
    all_slips = [(personas[s["persona_id"]].voice.gender, g.get("form")) for s in judged for g in s["judgement"]["gender_slips"]]
    recorded = [(voice, form) for voice, form in all_slips if form]
    out["slips_agreeing_with_voice"] = rate(sum(1 for voice, form in recorded if form == ("masculine" if voice == "male" else "feminine")), len(recorded))
    out["slips_without_recorded_form"] = len(all_slips) - len(recorded)
    return out


def _outcome_ok(score: dict) -> bool:
    return all(c["verdict"] != "fail" for c in score["checks"] if c["name"] == "created_booking" or c["name"].startswith(("changed:", "unchanged:")))


def _per_persona(scores: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = defaultdict(list)
    for s in scores:
        by[s["persona_id"]].append(s)
    rows = []
    for pid, items in sorted(by.items()):
        scored = [s for s in items if "excluded" not in s]
        checks: dict[str, Counter] = defaultdict(Counter)
        for s in scored:
            for c in s["checks"]:
                checks[c["name"]][c["verdict"]] += 1
        rows.append(
            {
                "persona_id": pid,
                "episodes": len(items),
                "scored": len(scored),
                "excluded": dict(Counter(s["excluded"] for s in items if "excluded" in s)),
                "outcome_correct": sum(1 for s in scored if _outcome_ok(s)),
                "checks": {name: dict(counts) for name, counts in sorted(checks.items())},
            }
        )
    return rows


# --- markdown


def render_markdown(agg: dict, scores: list[dict], meta: dict) -> str:
    def r(x: dict) -> str:
        if "rate" in x:
            return "n/a (0)" if x["rate"] is None else f"{x['k']}/{x['n']} ({x['rate']:.0%})"
        return f"{x['fail']} fail / {x['n']}" if x["n"] else "n/a (0)"

    t = agg["taxonomy"]
    out = [
        f"# Scores — run {meta.get('run_id', '?')}",
        "",
        f"Episodes {agg['episodes']} · scored {agg['scored']} · judged {agg['judged']} · excluded {agg['excluded'] or 'none'} · judge cost ${agg['judge_cost_usd']:.4f}",
    ]
    if agg["not_provoked"]:
        out.append(f"\n**Not provoked — tested nothing, excluded from every rate:** {', '.join(agg['not_provoked'])}")
    if agg["persona_changed_since_run"]:
        out.append(f"\n⚠ Persona files changed since these episodes ran (expected values may not match what ran): {', '.join(agg['persona_changed_since_run'])}")
    if agg["persona_unverifiable"]:
        out.append(f"\nPersona files unverifiable (episodes predate persona hashing): {', '.join(agg['persona_unverifiable'])}")
    if len(agg["judge_prompt_versions"]) > 1:
        out.append(f"\nJudge instructions differ across episodes (versions {', '.join(agg['judge_prompt_versions'])}); cached judgements were kept.")
    if agg["judge_errors"]:
        out.append("\n⚠ Judge errors (their judged checks are `judge_error`, not pass):\n" + "\n".join(f"- {e}" for e in agg["judge_errors"]))

    out += [
        "",
        "## Headline",
        "",
        "| metric | result |",
        "|---|---|",
        f"| outcome correct (bookings created/changed/untouched as expected) | {r(agg['outcome_correct'])} |",
        f"| confirmation violations (confirm without clear agreement) | {r(agg['confirmation_violations'])} |",
        f"| side effects per confirming message | {agg['side_effects_per_confirmation']['distribution'] or '-'} |",
        f"| confirm_action refusals (not failures; `booking_changed` is a correct refusal) | {agg['refused_confirmations'] or '-'} |",
        f"| handoff recall | {r(agg['handoff']['recall'])} |",
        f"| handoff precision | {r(agg['handoff']['precision'])} |",
        f"| handoff routing (team/priority) | {r(agg['handoff']['routing'])} |",
        "",
        "## Failure taxonomy",
        "",
        "| # | metric | result |",
        "|---|---|---|",
        f"| 1 | unknown question answered anyway | {r(t['1_ungrounded_answers']['answered_anyway'])} {t['1_ungrounded_answers']['unknown_question_classification']} |",
        f"| 1 | replies with an ungrounded claim | {r(t['1_ungrounded_answers']['replies_with_ungrounded_claim'])} {t['1_ungrounded_answers']['ungrounded_by_category']} |",
        f"| 2 | fabricated booking_id calls per booking-referencing turn | {r(t['2_fabricated_booking_ids']['fabricated_calls_per_booking_referencing_turn'])} {t['2_fabricated_booking_ids']['by_outcome']} |",
        f"| 3 | unknown_package per created booking | {r(t['3_unknown_package']['per_created_booking'])} |",
        f"| 4 | item-4 provocation rate (unlinked bare affirmation) | {', '.join(f'{k}: {r(v)}' for k, v in t['4_token_ambiguity']['provocation_rate_by_persona'].items()) or '-'} |",
        f"| 4 | confirmations executed on an unlinked bare affirmation (not agreed = wrong token) | {t['4_token_ambiguity']['confirmations_executed_on_unlinked_bare_affirmation']} (not agreed: {t['4_token_ambiguity']['of_which_not_agreed']}) |",
        f"| 4 | confirmations made with 2+ tokens live | {r(t['4_token_ambiguity']['confirmations_with_2plus_live_tokens'])} |",
        f"| 5 | prepare summaries with an English enum | {r(t['5_summary_enums']['summaries_with_enum'])} |",
        f"| 5 | replies echoing a summary's English enum | {r(t['5_summary_enums']['replies_echoing_summary_enum'])} |",
        f"| 6 | strict-mode retention not stated | {r(t['6_retention_change_stated'])} |",
        f"| 7 | replies with emoji | {r(t['7_emoji']['replies_with_emoji'])} |",
        f"| 8 | episodes with a gendered slip — male-voiced customer | {r(t['8_gender_inference']['male']['episodes_with_slip'])}; replies {r(t['8_gender_inference']['male']['replies_with_slip'])}; forms {t['8_gender_inference']['male']['forms']} |",
        f"| 8 | episodes with a gendered slip — female-voiced customer | {r(t['8_gender_inference']['female']['episodes_with_slip'])}; replies {r(t['8_gender_inference']['female']['replies_with_slip'])}; forms {t['8_gender_inference']['female']['forms']} |",
        f"| 8 | slips whose form agrees with the customer's voice (inference) | {r(t['8_gender_inference']['slips_agreeing_with_voice'])}; form unrecorded: {t['8_gender_inference']['slips_without_recorded_form']} |",
        f"| 9 | refund tier not explained | {r(t['9_refund_tier_explained'])} |",
        f"| 10 | capacity implied | {r(t['10_capacity']['no_capacity_implication'])} |",
        f"| 10 | full-date episodes with no ticket | {r(t['10_capacity']['full_date_episodes_without_ticket'])} |",
        f"| 11 | unpaid tentative told a fee/percentage applies | {r(t['11_unpaid_tentative_fee']['stated_to_customer'])} |",
        f"| 11 | `refund_percent` in the data for an unpaid cancellation | {r(t['11_unpaid_tentative_fee']['refund_percent_in_data'])} |",
        f"| 12 | replies with a fabricated link | {r(t['12_fabricated_links']['replies_with_fabricated_link'])} |",
        f"| 14 | replies with English self-talk (e.g. «Wait, no emoji allowed.») | {r(t['14_instruction_leak']['replies_with_english_prose'])}; judge 'other' leaks: {t['14_instruction_leak']['judge_other_leaks']} |",
        f"| 13 | replies with English enum words of the model's own | {r(t['13_model_enums']['replies_with_own_enum'])}; episodes {r(t['13_model_enums']['episodes_with_own_enum'])} {t['13_model_enums']['words']} |",
    ]

    multi = agg["side_effects_per_confirmation"]["messages_authorizing_2plus"]
    if multi:
        out += ["", "## One message, several side effects", ""]
        out += [f"- {m['episode']} C{m['customer_turn']} {m['message']!r} → {', '.join(m['actions'])}{' (bare)' if m['bare'] else ''}" for m in multi]

    out += ["", "## Per persona", "", "| persona | scored | excluded | outcome | failing checks |", "|---|---:|---|---:|---|"]
    for p in agg["personas"]:
        failing = ", ".join(f"{name} {c.get('fail', 0)}/{c.get('fail', 0) + c.get('pass', 0)}" for name, c in p["checks"].items() if c.get("fail") or c.get("judge_error"))
        errors = ", ".join(f"{name} judge_error" for name, c in p["checks"].items() if c.get("judge_error"))
        out.append(f"| {p['persona_id']} | {p['scored']}/{p['episodes']} | {p['excluded'] or ''} | {p['outcome_correct']}/{p['scored']} | {failing or '—'}{'; ' + errors if errors else ''} |")

    out += ["", "## Failures with evidence", ""]
    for s in scores:
        if "excluded" in s:
            continue
        failed = [c for c in s["checks"] if c["verdict"] in ("fail", "judge_error")]
        j = s["judgement"] or {}
        extras = (
            [f"confirmation {v['confirmation_id'][:8]} not agreed: {v['reason']}" for v in j.get("confirmations", []) if not v["agreed"]]
            + [f"ungrounded {c['category']} A{c['reply_turn']}: {c['claim']} — {c['why']}" for c in j.get("ungrounded_claims", [])]
            + [f"gender A{g['reply_turn']} ({g.get('form', 'form unrecorded')}): {g['phrase']}" for g in j.get("gender_slips", [])]
            + [f"internal leak ({l['kind']}) A{l['reply_turn']}: {l['phrase']}" for l in j.get("internal_leaks", [])]
            + [f"emoji A{e['customer_turn']}: {''.join(e['emoji'])}" for e in s["signals"]["emoji_replies"]]
            + [f"English enum (13) A{e['customer_turn']}: {', '.join(e['words'])}" for e in s["signals"]["enum_replies"] if e["words"]]
            + [f"English enum echoed from summary_ar (5) A{e['customer_turn']}: {', '.join(e['echoed_from_summary'])}" for e in s["signals"]["enum_replies"] if e["echoed_from_summary"]]
            + [f"fabricated link A{l['customer_turn']}: {l['link']}" for l in s["signals"]["links"] if l["fabricated"]]
            + [f"English self-talk (14) A{p['customer_turn']}: {' | '.join(p['text'])}" for p in s["signals"]["english_prose"]]
        )
        if not failed and not extras:
            continue
        out.append(f"### {s['persona_id']} #{s['episode']}")
        out += [f"- **{c['name']}** ({c['verdict']}, {c['source']}): {c['evidence']}" for c in failed]
        out += [f"- {x}" for x in extras]
        out.append("")
    return "\n".join(out) + "\n"


# --- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--no-judge", action="store_true", help="deterministic checks only; no API calls")
    parser.add_argument("--rejudge", action="store_true", help="ignore cached judgements")
    parser.add_argument("--budget", type=float, default=None, help="stop judging before new judge spend in this invocation could exceed this many USD")
    args = parser.parse_args(argv)

    personas = {p.id: p for p in load_personas()}
    policy = get_policy()
    client = None
    if not args.no_judge:
        from eval.client import anthropic_client

        client = anthropic_client()

    scores_dir = args.run_dir / "scores"
    scores_dir.mkdir(exist_ok=True)
    scores = []
    spent = 0.0
    guard = usage.BudgetGuard(first_estimate=0.15)
    for record in load_episodes(args.run_dir):
        path = scores_dir / f"{record['persona_id']}__e{record['episode']:02d}.json"
        cached = None if args.rejudge or not path.exists() else json.loads(path.read_text(encoding="utf-8"))
        persona = personas.get(record["persona_id"])
        if persona is None:
            print(f"skipping {path.name}: persona {record['persona_id']} no longer exists", file=sys.stderr)
            continue
        judge_client = client
        cached_ok = cached is not None and cached.get("judge", {}).get("model") == args.judge_model and cached["judge"].get("error") is None
        if client is not None and not cached_ok and args.budget is not None and spent + guard.next_estimate() > args.budget:
            print(f"{path.stem}: budget ${args.budget:.2f} would be exceeded (spent ${spent:.4f}, next up to ${guard.next_estimate():.4f}) — not judged", flush=True)
            judge_client = None
        score = score_episode(record, persona, policy=policy, client=judge_client, judge_model=args.judge_model, cached=cached)
        if judge_client is not None and not cached_ok:
            spent += score.get("judge", {}).get("cost_usd") or 0
            guard.observe(score.get("judge", {}).get("cost_usd") or 0)
        path.write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")
        scores.append(score)
        print(f"{path.stem}: {score.get('excluded') or 'scored'}" + (f", judge ${score['judge']['cost_usd']:.4f}" if score.get("judge", {}).get("model") else ""), flush=True)

    meta_path = args.run_dir / "run.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    agg = aggregate(scores, personas)
    agg["judge_model"] = None if args.no_judge else args.judge_model
    (args.run_dir / "scores.json").write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.run_dir / "scores.md").write_text(render_markdown(agg, scores, meta), encoding="utf-8")
    print(f"→ {args.run_dir / 'scores.md'} (new judge spend ${spent:.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
