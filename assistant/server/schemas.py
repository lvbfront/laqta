"""Request and response bodies.

Deliberately thin. The response payloads are built as plain dicts in store.py
and events.py, because `events` has a shape that depends on the dev flag and
pinning it in a model here would be a second place to keep in step.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    # Both are read only when ASSISTANT_DEV is on. With it off they are not
    # rejected — they are never looked at (see server/identity.py).
    identity: str | None = Field(default=None, description="dev only: anon | customer:<id> | staff:<id>")
    now: str | None = Field(default=None, description="dev only: ISO timestamp the session starts at")


class SendMessageRequest(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=200)
    text: str


class EndSessionRequest(BaseModel):
    # A session closed because the customer walked away is still worth
    # summarising; one closed by a test usually is not.
    summarise: bool = True
