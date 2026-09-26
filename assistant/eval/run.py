"""Run the persona set against the live agent.

    python -m eval.run                          # every persona, 10 episodes each
    python -m eval.run --episodes 3 --persona a2 --persona p25
    python -m eval.run --dry-run                # seed + render every persona, no API calls

Agent: settings.agent_model (claude-sonnet-5), through the real agent loop.
Customer: claude-haiku-4-5, playing the persona.

Writes eval/runs/<run-id>/: one JSON file per episode (every message, every
tool call with arguments and result, API usage per call), plus report.md and
report.json, rewritten after every episode so an interrupted run still has
one. Regenerate a report with `python -m eval.report <run-dir>`.

Only ever touches the `assistant_eval` database. Episodes run one at a time:
they share that database, and onsite capacity is counted across all bookings
in it.
"""

from __future__ import annotations

# --- Point the app at assistant_eval BEFORE anything imports app.db. -------
# app.db builds its engine from settings at import time, and the CLIs and
# scripts reach it through SessionLocal. Nothing the runner calls uses
# SessionLocal, but if anything ever did, it must land here and not in
# `assistant`, which holds the repo owner's hand-testing sessions.
from app import config as _app_config  # noqa: E402 — imports no database code
from eval.guard import EVAL_DATABASE, eval_database_url, require_eval_database  # noqa: E402

_app_config.settings.database_url = eval_database_url(_app_config.settings.database_url)
# ---------------------------------------------------------------------------

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.db  # noqa: E402
from app.config import get_policy, settings  # noqa: E402
from eval import database, report, usage  # noqa: E402
from eval.client import anthropic_client  # noqa: E402
from eval.personas import load_personas, render  # noqa: E402

PERSONA_MODEL = "claude-haiku-4-5"
DEFAULT_EPISODES = 10
RUNS_DIR = Path(__file__).resolve().parent / "runs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episodes", type=int, default=DEFAULT_EPISODES, help=f"episodes per persona (default {DEFAULT_EPISODES})")
    parser.add_argument("--persona", action="append", default=[], help="persona id or id prefix; repeatable. Default: all")
    parser.add_argument("--out", type=Path, default=None, help="run directory (default eval/runs/<timestamp>)")
    parser.add_argument("--dry-run", action="store_true", help="prepare the database and seed every selected persona; no API calls")
    parser.add_argument("--verbose", "-v", action="store_true", help="print every message and tool call as it happens")
    parser.add_argument("--budget", type=float, default=None, help="stop before an episode that could take this run's spend over this many USD")
    args = parser.parse_args(argv)
    if args.episodes < 1:
        parser.error("--episodes must be at least 1")

    url = settings.database_url
    require_eval_database(url)
    require_eval_database(app.db.engine)  # proves the redirect above happened before app.db was imported

    personas = _select(load_personas(), args.persona)
    if not personas:
        print(f"no persona matches {args.persona}", file=sys.stderr)
        return 1

    print(f"preparing {EVAL_DATABASE} (migrate, index KB)…")
    kb_report = database.prepare_database(url)
    print(f"  kb: {kb_report}")

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with Session(engine, autoflush=False) as db:
            require_eval_database(db)
            if args.dry_run:
                return _dry_run(db, personas)
            return _run(db, personas, args, kb_report)
    finally:
        engine.dispose()


def _run(db: Session, personas, args, kb_report: str) -> int:
    from eval.runner import run_episode

    client = anthropic_client()
    policy = get_policy()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = args.out or RUNS_DIR / run_id
    (run_dir / "episodes").mkdir(parents=True, exist_ok=False)

    meta = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "agent_model": settings.agent_model,
        "persona_model": PERSONA_MODEL,
        "database": EVAL_DATABASE,
        "episodes_per_persona": args.episodes,
        "personas": [p.id for p in personas],
        "kb_index": kb_report,
        "argv": sys.argv[1:],
    }
    (run_dir / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    total = args.episodes * len(personas)
    print(f"run {run_id}: {len(personas)} personas × {args.episodes} episodes = {total} conversations → {run_dir}")

    done = 0
    spent = 0.0
    guard = usage.BudgetGuard(first_estimate=0.20)
    try:
        # Round-robin, so an interrupted run has covered every persona evenly.
        for episode in range(1, args.episodes + 1):
            for persona in personas:
                done += 1
                if args.budget is not None and spent + guard.next_estimate() > args.budget:
                    print(f"stopping before [{done}/{total}] {persona.id}: spent ${spent:.4f}, next episode up to ${guard.next_estimate():.4f}, budget ${args.budget:.2f}", flush=True)
                    raise _BudgetReached
                print(f"[{done}/{total}] {persona.id} episode {episode}", flush=True)
                record = run_episode(
                    db,
                    persona,
                    episode=episode,
                    policy=policy,
                    agent_client=client,
                    persona_client=client,
                    agent_model=settings.agent_model,
                    persona_model=PERSONA_MODEL,
                    on_progress=(lambda m: print(m, flush=True)) if args.verbose else None,
                )
                path = run_dir / "episodes" / f"{persona.id}__e{episode:02d}.json"
                path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                cost = record["cost_usd"]["total"]
                spent += cost or 0
                guard.observe(cost or 0)
                provocation = f", provocation {record['provocation']['status']}" if record["provocation"] else ""
                print(
                    f"    {record['status']} ({record['end_reason']}), {record['customer_turns']} turns"
                    f"{provocation}, {'n/a' if cost is None else f'${cost:.4f}'}, {record['duration_s']}s"
                    + (f", {len(record['warnings'])} warnings" if record["warnings"] else ""),
                    flush=True,
                )
                report.write_report(run_dir, meta)
    except _BudgetReached:
        report.write_report(run_dir, meta)
        print(f"budget reached — {done - 1} episodes recorded, ${spent:.4f} → {run_dir / 'report.md'}")
        return 0
    except KeyboardInterrupt:
        print("\ninterrupted — report covers the finished episodes", file=sys.stderr)
        report.write_report(run_dir, meta)
        return 130

    summary = report.write_report(run_dir, meta)
    print(f"done: {summary['status_counts']}, this run ${spent:.4f} → {run_dir / 'report.md'}")
    return 0


class _BudgetReached(Exception):
    pass


def _dry_run(db: Session, personas) -> int:
    """Everything up to the first API call, for every persona: seed, fixtures
    through the state machine, identity, templates, context block."""
    from app.agent.session import AgentSession
    from app.identity.dev_auth import DevAuth
    from app.laqta.mock import MockLaqta

    policy = get_policy()
    for persona in personas:
        ids = database.reset_and_seed(db, persona, policy=policy)
        identity = DevAuth(db).parse(persona.identity)
        for text in [persona.opening, persona.goal, *persona.hidden_state.values(), *persona.rules, *(t.say for t in persona.script)]:
            if "{{" in render(text, ids):
                raise RuntimeError(f"{persona.id}: unrendered template in {text!r}")
        session = AgentSession.start(db, identity=identity, policy=policy, laqta=MockLaqta.seeded(db), now=persona.now)
        print(f"{persona.id}: {len(ids)} bookings, {identity.kind}, opening: {render(persona.opening, ids)}")
        print("  " + session.context_block.replace("\n", "\n  "))
    print(f"dry run ok: {len(personas)} personas seeded in {EVAL_DATABASE}; no API calls made")
    return 0


def _select(personas, wanted: list[str]):
    if not wanted:
        return personas
    return [p for p in personas if any(p.id == w or p.id.startswith(w) for w in wanted)]


if __name__ == "__main__":
    sys.exit(main())
