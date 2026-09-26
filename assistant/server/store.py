"""Chat sessions, in this process, one at a time each.

`AgentSession` is an in-memory dataclass: its message list, the customer-turn
counter the confirmation rule depends on, and the resolved-date store exist
nowhere else. Only the `interactions` row and its transcript are durable. So a
session lives here, in a dict, and dies with the process. The README says so;
it is not a thing to discover.

Two rules, and the second is the reason this module exists.

**One turn at a time per session.** A `threading.Lock` per session, held for
the whole turn. Endpoints are sync `def`, so Starlette runs them in its
threadpool and a second request for the same session blocks on the lock
instead of interleaving with the first. Two sessions still run in parallel.

**A client_message_id is answered once.** Every result `run_turn` returns is
recorded against its id, including the apologies — `loop_api_error` is a
result the customer was shown, not a gap to fill in later. A repeat returns
the record and does not re-enter the loop. Because the lock is held across the
whole turn, a repeat that arrives while the first is still running blocks,
then finds the record: waiting and replaying are the same code path, with
nothing to coordinate.

The reason is the confirmation rule. Re-entering the loop would advance
`user_turn` with no new customer message behind it, and a turn that the
customer never sent is exactly what `confirm_action` reads as the customer
having replied to a summary.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.agent.loop import run_turn
from app.agent.session import AgentSession
from app.agent.summarize import summarize_session
from app.config import Policy
from app.identity.identity import Identity
from server import errors, events
from server.clock import Clock, wall_now
from server.laqta import SharedLaqta
from server.recording import RecordingClient


@dataclass(frozen=True)
class TurnRecord:
    """One answered client_message_id. Whatever the customer was shown."""

    client_message_id: str
    turn: int
    text: str
    reply: str
    reply_source: str
    events: dict[str, Any]

    def response(self, *, replayed: bool) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "reply_source": self.reply_source,
            "events": self.events,
            "turn": self.turn,
            "replayed": replayed,
        }


@dataclass
class ChatSession:
    id: str
    db: Session
    agent: AgentSession
    clock: Clock
    identity_spec: str
    client: RecordingClient

    lock: threading.Lock = field(default_factory=threading.Lock)
    turns: list[TurnRecord] = field(default_factory=list)
    answered: dict[str, TurnRecord] = field(default_factory=dict)
    last_used_at: datetime = field(default_factory=wall_now)
    ended: bool = False
    # Set when something failed in a way that leaves this session's state
    # untrustworthy. Never cleared.
    broken: str | None = None

    @property
    def identity(self) -> Identity:
        return self.agent.identity

    def history(self) -> list[dict[str, Any]]:
        """What to put back on screen after a reload. Read from the records
        rather than from agent.messages, which also holds tool_use blocks,
        tool results and thinking — none of which is a chat message."""
        out: list[dict[str, Any]] = []
        for record in self.turns:
            out.append(
                {
                    "role": "user",
                    "text": record.text,
                    "turn": record.turn,
                    "client_message_id": record.client_message_id,
                }
            )
            out.append(
                {
                    "role": "assistant",
                    "text": record.reply,
                    "turn": record.turn,
                    "reply_source": record.reply_source,
                }
            )
        return out

    def send(self, *, client_message_id: str, text: str, dev: bool) -> dict[str, Any]:
        """Run one turn, or replay the one this id already got."""
        with self.lock:
            existing = self.answered.get(client_message_id)
            if existing is not None:
                # Either a retry of something finished, or a duplicate that
                # queued behind the original and is only now getting in.
                return existing.response(replayed=True)
            if self.broken is not None:
                raise errors.session_broken()
            if self.ended:
                raise errors.session_ended()

            self.last_used_at = wall_now()
            mark = self.client.mark
            started = perf_counter()
            now = self.clock.now()
            try:
                reply = run_turn(self.agent, text, now=now, client=self.client)
            except Exception as exc:
                # run_turn absorbs the transient API failures itself, so
                # anything arriving here is a misconfiguration, a bug, or a
                # confirmation token that could not be voided. In every case
                # the next turn would run against state we cannot vouch for.
                self.broken = f"{type(exc).__name__}: {exc}"
                raise errors.session_broken() from exc

            steps = self.client.since(mark)
            record = TurnRecord(
                client_message_id=client_message_id,
                turn=self.agent.user_turn,
                text=text,
                reply=reply,
                reply_source=events.reply_source(reply, steps),
                events=events.for_turn(
                    self.agent,
                    user_turn=self.agent.user_turn,
                    steps=steps,
                    latency_ms=int((perf_counter() - started) * 1000),
                    now=now,
                    dev=dev,
                ),
            )
            self.turns.append(record)
            self.answered[client_message_id] = record
            self.last_used_at = wall_now()
            return record.response(replayed=False)

    def finish(self, *, summarise: bool) -> dict[str, Any]:
        """End the conversation and write its summary, which is what the next
        session's context block reads as «آخر تواصل».

        Nothing to summarise means nothing to say: a session where the
        customer never spoke gets closed without an API call.
        """
        with self.lock:
            if self.ended:
                return {"session_id": self.id, "summary": None, "outcome": None, "ended": True}
            self.ended = True
            now = self.clock.now()
            if not self.turns or not summarise or self.broken is not None:
                self.agent.end(now=now, outcome="abandoned" if not self.turns else None)
                return {"session_id": self.id, "summary": None, "outcome": None, "ended": True}
            summary = summarize_session(self.agent, now=now, client=self.client.inner)
            return {
                "session_id": self.id,
                "summary": summary.summary_ar if summary else None,
                "outcome": summary.outcome if summary else None,
                "ended": True,
            }

    def close(self) -> None:
        self.db.close()


class SessionStore:
    """Every live conversation in this process."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        policy: Policy,
        laqta: SharedLaqta,
        max_sessions: int,
        idle_seconds: int,
        model_client: Any | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy
        self._laqta = laqta
        self._max_sessions = max_sessions
        self._idle_seconds = idle_seconds
        self._model_client = model_client
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.Lock()

    def create(self, *, identity: Identity, identity_spec: str, clock: Clock) -> ChatSession:
        self.evict_idle()
        with self._lock:
            if len(self._sessions) >= self._max_sessions:
                raise errors.too_many_sessions()

        db = self._session_factory()
        try:
            agent = AgentSession.start(
                db,
                identity=identity,
                policy=self._policy,
                laqta=self._laqta.for_session(),
                now=clock.started_at,
            )
        except Exception:
            db.close()
            raise

        chat = ChatSession(
            # Opaque: interactions.id is a sequential integer, and handing one
            # to a browser would make every other conversation guessable.
            id=secrets.token_urlsafe(24),
            db=db,
            agent=agent,
            clock=clock,
            identity_spec=identity_spec,
            client=RecordingClient(self._client()),
        )
        with self._lock:
            self._sessions[chat.id] = chat
        return chat

    def get(self, session_id: str) -> ChatSession:
        with self._lock:
            chat = self._sessions.get(session_id)
        if chat is None:
            raise errors.session_not_found()
        return chat

    def end(self, session_id: str, *, summarise: bool = True) -> dict[str, Any]:
        chat = self.get(session_id)
        try:
            return chat.finish(summarise=summarise)
        finally:
            self._forget(chat.id)
            chat.close()

    def evict_idle(self) -> None:
        """Idle conversations go out through the same door as `/end`, so an
        abandoned one still writes its summary rather than vanishing."""
        cutoff = wall_now()
        with self._lock:
            stale = [
                chat.id
                for chat in self._sessions.values()
                if (cutoff - chat.last_used_at).total_seconds() > self._idle_seconds
            ]
        for session_id in stale:
            try:
                self.end(session_id)
            except errors.ChatError:
                pass

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for chat in sessions:
            chat.close()

    def _forget(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _client(self) -> Any:
        """A client, or a zero-arg factory returning one.

        The factory form is for tests: a scripted fake is consumed as it is
        read, so sessions that are meant to be independent need one each.
        """
        if self._model_client is None:
            from app.agent.loop import default_client

            return default_client()
        if hasattr(self._model_client, "messages"):
            return self._model_client
        return self._model_client()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
