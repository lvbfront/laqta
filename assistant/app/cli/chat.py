"""Talk to the assistant from the terminal (spec §13).

    python -m app.cli.chat --as customer:1
    python -m app.cli.chat --as anon
    python -m app.cli.chat --as customer:1 --now 2026-09-11T14:05

In-conversation commands:
    /debug   show or hide every tool call and its result, and token usage per
             API call and per turn (cache_write / cache_read show whether the
             system prompt cache is actually hit)
    /ctx     print the context block this session started with
    /end     end the session and write the summary
    /quit    leave without writing a summary
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from app.agent.loop import run_turn
from app.agent.session import AgentSession
from app.agent.summarize import summarize_session
from app.config import get_policy
from app.db import SessionLocal
from app.identity.dev_auth import AuthError, DevAuth
from app.laqta.mock import MockLaqta

PROMPT = "أنت: "
ASSISTANT = "المساعد: "

CREDENTIALS_HELP = """
No Anthropic credentials found. The conversation loop needs one of:

    export ANTHROPIC_API_KEY=sk-ant-...

or an `ant auth login` profile, if you have the ant CLI installed. Everything
else in this service (tests included) runs without it.
""".strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--as",
        dest="identity_spec",
        default="anon",
        help="anon | customer:<contact_id> | staff:<staff_id>",
    )
    parser.add_argument(
        "--now",
        help="ISO timestamp to run as, e.g. 2026-09-11T14:05. Defaults to the real clock.",
    )
    parser.add_argument("--debug", action="store_true", help="start with tool tracing on")
    args = parser.parse_args(argv)

    policy = get_policy()
    now = _parse_now(args.now, policy)

    with SessionLocal() as db:
        try:
            identity = DevAuth(db).parse(args.identity_spec)
        except AuthError as exc:
            print(f"{exc}", file=sys.stderr)
            return 1

        client = _client()
        if client is None:
            print(CREDENTIALS_HELP, file=sys.stderr)
            return 1

        session = AgentSession.start(
            db,
            identity=identity,
            policy=policy,
            laqta=MockLaqta.seeded(db),
            now=now,
        )
        debug = args.debug

        print(f"— جلسة #{session.interaction.id} ({identity.kind}) —")
        print(session.context_block)
        print("—" * 40)
        print("اكتب رسالتك. /debug /ctx /end /quit")

        while True:
            try:
                line = input(f"\n{PROMPT}").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                session.save_transcript()
                return 0

            if not line:
                continue

            if line == "/quit":
                session.save_transcript()
                return 0

            if line == "/debug":
                debug = not debug
                print(f"[تتبع الأدوات: {'مفعّل' if debug else 'متوقف'}]")
                continue

            if line == "/ctx":
                print(session.context_block)
                continue

            if line == "/end":
                summary = summarize_session(session, now=_parse_now(args.now, policy))
                if summary is None:
                    print("[ما فيه محادثة تستحق ملخص]")
                else:
                    print(f"\n[الملخص: {summary.summary_ar}]")
                    print(f"[النتيجة: {summary.outcome}]")
                return 0

            try:
                reply = run_turn(
                    session,
                    line,
                    now=_parse_now(args.now, policy),
                    client=client,
                    on_event=(lambda message: print(f"  [{message}]")) if debug else None,
                )
            except Exception as exc:  # noqa: BLE001 — narrowed immediately
                if _is_auth_error(exc):
                    session.save_transcript()
                    print(f"\n{CREDENTIALS_HELP}", file=sys.stderr)
                    return 1
                raise
            print(f"\n{ASSISTANT}{reply}")


def _parse_now(raw: str | None, policy) -> datetime:
    """A fixed --now makes a conversation reproducible; the domain takes the
    clock as a parameter precisely so this is possible."""
    if raw is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=policy.tz)
    return parsed


def _client():
    """None only when there are certainly no credentials.

    A bare `Anthropic()` constructor succeeding proves nothing — the SDK
    defers authentication to the first request. But it can also read an
    `ant auth login` profile that this process cannot see, so credentials
    are only ruled out when there is no key *and* no ant CLI to hold a
    profile.
    """
    import shutil

    try:
        from app.agent.loop import default_client

        client = default_client()
    except Exception:  # noqa: BLE001 — a misconfigured SDK is "no credentials" here
        return None

    has_inline_credential = bool(
        getattr(client, "api_key", None) or getattr(client, "auth_token", None)
    )
    if not has_inline_credential and shutil.which("ant") is None:
        return None
    return client


def _is_auth_error(exc: BaseException) -> bool:
    import anthropic

    return isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError))


if __name__ == "__main__":
    sys.exit(main())
