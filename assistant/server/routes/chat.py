"""The four endpoints.

Sync `def`, not `async def`, and that is load-bearing rather than an
oversight. `run_turn` blocks: sync SDK, sync SQLAlchemy. Declared async it
would block the event loop and every other request with it; declared sync,
Starlette runs it in a threadpool, so sessions proceed in parallel and the
per-session lock in store.py is what serialises one session's turns.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request

from app.config import get_policy
from server import errors, identity as identity_module
from server.clock import Clock
from server.config import ServerSettings
from server.schemas import CreateSessionRequest, EndSessionRequest, SendMessageRequest
from server.store import ChatSession, SessionStore

router = APIRouter(prefix="/chat", tags=["chat"])


def _store(request: Request) -> SessionStore:
    return request.app.state.store


def _settings(request: Request) -> ServerSettings:
    return request.app.state.server_settings


def _describe(chat: ChatSession, *, dev: bool) -> dict:
    return {
        "session_id": chat.id,
        "identity": chat.identity.kind,
        "identity_spec": chat.identity_spec,
        "now": chat.clock.now().isoformat(),
        "clock_overridden": chat.clock.overridden,
        "dev": dev,
        "turn": chat.agent.user_turn,
        # Only in dev: it names the customer, their bookings and their open
        # tickets, which is the session's own context and not the browser's.
        "context_block": chat.agent.context_block if dev else None,
    }


@router.post("/sessions")
def create_session(body: CreateSessionRequest, request: Request) -> dict:
    settings = _settings(request)
    store = _store(request)
    policy = get_policy()

    clock = _clock(body.now, dev=settings.dev, policy=policy)
    # A throwaway session just to resolve the identity: DevAuth reads contacts
    # and staff, and the chat session's own Session should not be opened until
    # there is going to be a chat session.
    with store._session_factory() as db:  # noqa: SLF001 — same module's concern
        try:
            who, spec = identity_module.resolve(db, body.identity, dev=settings.dev)
        except identity_module.AuthError as exc:
            raise errors.bad_identity(str(exc)) from exc

    chat = store.create(identity=who, identity_spec=spec, clock=clock)
    return _describe(chat, dev=settings.dev)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict:
    settings = _settings(request)
    chat = _store(request).get(session_id)
    return {**_describe(chat, dev=settings.dev), "messages": chat.history(), "ended": chat.ended}


@router.post("/sessions/{session_id}/messages")
def send_message(session_id: str, body: SendMessageRequest, request: Request) -> dict:
    settings = _settings(request)
    text = body.text.strip()
    if not text:
        raise errors.empty_message()
    if len(text) > settings.max_message_chars:
        raise errors.message_too_long(settings.max_message_chars)

    chat = _store(request).get(session_id)
    return chat.send(client_message_id=body.client_message_id, text=text, dev=settings.dev)


@router.post("/sessions/{session_id}/end")
def end_session(session_id: str, body: EndSessionRequest, request: Request) -> dict:
    return _store(request).end(session_id, summarise=body.summarise)


def _clock(raw: str | None, *, dev: bool, policy) -> Clock:
    if raw is None or not dev:
        return Clock.real()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise errors.bad_now(str(exc)) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=policy.tz)
    return Clock.starting_at(parsed)
