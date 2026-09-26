"""Run report: what ran, whether provocations fired, what it cost.

Built from the episode JSON files alone, so it can be regenerated for a run
directory at any time:

    python -m eval.report eval/runs/<run-id>

It scores nothing. It exists so a run's health — episodes that never
provoked, infrastructure errors, fingerprint drift — and its per-episode
token cost are visible before anyone reads a pass rate.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from eval import usage


def load_episodes(run_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((run_dir / "episodes").glob("*.json"))
    ]


def summarize(run_dir: Path, episodes: list[dict[str, Any]], run_meta: dict[str, Any]) -> dict[str, Any]:
    rows = [_episode_row(e) for e in episodes]
    by_persona: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_persona[row["persona_id"]].append(row)

    totals = {"agent": usage.zero(), "persona": usage.zero()}
    for e in episodes:
        totals["agent"] = usage.add(totals["agent"], e["usage"]["agent"])
        totals["persona"] = usage.add(totals["persona"], e["usage"]["persona"])

    costs = [r["cost_total"] for r in rows]
    return {
        "run": run_meta,
        "run_dir": str(run_dir),
        "episodes": len(rows),
        "status_counts": _count(r["status"] for r in rows),
        "end_reason_counts": _count(r["end_reason"] for r in rows),
        # Per identity kind: anonymous and customer sessions are offered
        # different tools, so their tool hashes differ by design.
        "fingerprints": {
            kind: sorted({(e["fingerprint"]["system_prompt_sha256"][:12], e["fingerprint"]["tools_sha256"][:12]) for e in episodes if _kind(e) == kind})
            for kind in sorted({_kind(e) for e in episodes})
        },
        "simulator_prompts": sorted({(e.get("simulator_prompt_sha256") or "unrecorded")[:12] for e in episodes}),
        "usage": totals,
        "cost_usd": {
            "agent": _sum(r["cost_agent"] for r in rows),
            "persona": _sum(r["cost_persona"] for r in rows),
            "total": _sum(costs),
            "mean_per_episode": None if not costs or None in costs else sum(costs) / len(costs),
        },
        "personas": [_persona_row(pid, prow) for pid, prow in sorted(by_persona.items())],
        "episode_rows": rows,
    }


def _kind(e: dict[str, Any]) -> str:
    return "anonymous" if e["identity"] == "anon" else "customer"


def _episode_row(e: dict[str, Any]) -> dict[str, Any]:
    agent_steps = sum(len(ev["steps"]) for ev in e["events"] if ev["type"] == "agent_turn")
    tool_calls = sum(len(s["tool_calls"]) for ev in e["events"] if ev["type"] == "agent_turn" for s in ev["steps"])
    provocation = e.get("provocation")
    return {
        "persona_id": e["persona_id"],
        "episode": e["episode"],
        "status": e["status"],
        "end_reason": e["end_reason"],
        "provocation": provocation["status"] if provocation else None,
        "customer_turns": e["customer_turns"],
        "agent_api_calls": agent_steps,
        "tool_calls": tool_calls,
        "agent_usage": e["usage"]["agent"],
        "persona_usage": e["usage"]["persona"],
        "cost_agent": e["cost_usd"]["agent"],
        "cost_persona": e["cost_usd"]["persona"],
        "cost_total": e["cost_usd"]["total"],
        "duration_s": e["duration_s"],
        "warnings": len(e["warnings"]),
    }


def _persona_row(persona_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    costs = [r["cost_total"] for r in rows]
    return {
        "persona_id": persona_id,
        "episodes": len(rows),
        "completed": sum(r["status"] == "completed" for r in rows),
        "not_provoked": sum(r["status"] == "not_provoked" for r in rows),
        "infra_error": sum(r["status"] == "infra_error" for r in rows),
        "adversarial": any(r["provocation"] is not None for r in rows),
        "mean_customer_turns": mean(r["customer_turns"] for r in rows),
        "mean_agent_api_calls": mean(r["agent_api_calls"] for r in rows),
        "mean_cost": None if None in costs else mean(costs),
        "total_cost": _sum(costs),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    run = summary["run"]
    cost = summary["cost_usd"]
    out = [
        f"# Eval run {run.get('run_id', '?')}",
        "",
        "**Nothing in this report is a score.** It records what ran and what it cost. "
        "An adversarial episode whose provocation never fired is `not_provoked`: "
        "it did not test anything and must be excluded from pass rates, never counted as a pass.",
        "",
        f"- Agent model: `{run.get('agent_model')}` · persona model: `{run.get('persona_model')}`",
        f"- Database: `{run.get('database')}` · episodes per persona: {run.get('episodes_per_persona')}",
        f"- Episodes recorded: {summary['episodes']} · status: {_fmt_counts(summary['status_counts'])}",
        f"- End reasons: {_fmt_counts(summary['end_reason_counts'])}",
        f"- Cost: agent {_usd(cost['agent'])} + persona {_usd(cost['persona'])} = **{_usd(cost['total'])}** "
        f"(mean {_usd(cost['mean_per_episode'])} per episode)",
    ]
    drifted = {kind: prints for kind, prints in summary["fingerprints"].items() if len(prints) > 1}
    if drifted:
        out.append(
            f"- ⚠ **Different system-prompt/tool fingerprints within one identity kind ({', '.join(drifted)})** "
            "— those episodes ran against different agent versions and are not comparable."
        )
    if len(summary["simulator_prompts"]) > 1:
        out.append(
            f"- ⚠ **Simulator instructions differ across episodes ({', '.join(summary['simulator_prompts'])})** "
            "— the customers were not instructed the same way."
        )
    out.append(
        "- Fingerprints (system prompt, tools): "
        + "; ".join(f"{kind} `{prints}`" for kind, prints in summary["fingerprints"].items())
    )

    out += ["", "## Tokens", "", "| | input | output | cache write | cache read |", "|---|---:|---:|---:|---:|"]
    for who in ("agent", "persona"):
        u = summary["usage"][who]
        out.append(f"| {who} | {u['input_tokens']:,} | {u['output_tokens']:,} | {u['cache_creation_input_tokens']:,} | {u['cache_read_input_tokens']:,} |")

    out += [
        "",
        "## Per persona",
        "",
        "| persona | episodes | completed | not provoked | infra error | turns (mean) | API calls (mean) | cost/episode | cost total |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for p in summary["personas"]:
        not_provoked = str(p["not_provoked"]) if p["adversarial"] else "–"
        out.append(
            f"| {p['persona_id']} | {p['episodes']} | {p['completed']} | {not_provoked} | {p['infra_error']} "
            f"| {p['mean_customer_turns']:.1f} | {p['mean_agent_api_calls']:.1f} | {_usd(p['mean_cost'])} | {_usd(p['total_cost'])} |"
        )

    out += [
        "",
        "## Per episode",
        "",
        "Agent tokens are summed over every API call in the episode; the per-call and per-turn "
        "breakdown is in the episode file.",
        "",
        "| persona | ep | status | end | turns | API calls | tools | in | out | cache write | cache read | agent $ | persona $ | total $ | warnings |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in summary["episode_rows"]:
        u = r["agent_usage"]
        status = f"**{r['status']}**" if r["status"] != "completed" else r["status"]
        out.append(
            f"| {r['persona_id']} | {r['episode']} | {status} | {r['end_reason']} | {r['customer_turns']} "
            f"| {r['agent_api_calls']} | {r['tool_calls']} | {u['input_tokens']:,} | {u['output_tokens']:,} "
            f"| {u['cache_creation_input_tokens']:,} | {u['cache_read_input_tokens']:,} "
            f"| {_usd(r['cost_agent'])} | {_usd(r['cost_persona'])} | {_usd(r['cost_total'])} | {r['warnings']} |"
        )
    out.append("")
    return "\n".join(out)


def write_report(run_dir: Path, run_meta: dict[str, Any]) -> dict[str, Any]:
    summary = summarize(run_dir, load_episodes(run_dir), run_meta)
    (run_dir / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(render_markdown(summary), encoding="utf-8")
    return summary


def _count(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in values:
        counts[str(v)] = counts.get(str(v), 0) + 1
    return dict(sorted(counts.items()))


def _fmt_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in counts.items()) or "-"


def _sum(values) -> float | None:
    values = list(values)
    return None if None in values else sum(values)


def _usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m eval.report <run-dir>", file=sys.stderr)
        return 2
    run_dir = Path(args[0])
    meta_path = run_dir / "run.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    summary = write_report(run_dir, meta)
    print(f"{run_dir / 'report.md'}: {summary['episodes']} episodes, {_usd(summary['cost_usd']['total'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
