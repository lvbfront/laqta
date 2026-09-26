"""Mandatory confirmation tokens (spec §8).

The instructions tell the model to confirm before acting. This module is why
it cannot skip that: a prepare_* writes a token, and confirm_action is only
allowed to proceed if the token is this session's, unexpired, unused, and —
the important one — a NEW customer message has arrived since the prepare.

What this guarantees: the customer was given a chance to reply. What it does
NOT guarantee: that the reply was "yes" rather than "no". That gap is
measured by confirmation_violations in layer 2, and is stated in EVAL.md.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Policy
from app.models.confirmation import Confirmation
from app.models.enums import ConfirmationAction


class ConfirmationError(Exception):
    """Base for every refusal. `code` is what the tool layer reports."""

    code = "confirmation_error"
    detail_ar = "ما نقدر نكمل هذا الإجراء."


class ConfirmationNotFound(ConfirmationError):
    # Same error for "no such token" and "another session's token", so a
    # token id cannot be probed — the enumeration-safe pattern from spec §4.
    code = "not_found"
    detail_ar = "ما لقيت طلب تأكيد بهذا الرقم."


class ConfirmationExpired(ConfirmationError):
    code = "expired"
    detail_ar = "انتهت مدة التأكيد. نبدأ من جديد؟"


class ConfirmationAlreadyUsed(ConfirmationError):
    code = "already_used"
    detail_ar = "هذا الطلب تم تنفيذه مرة وحدة بالفعل."


class AwaitingCustomerReply(ConfirmationError):
    code = "awaiting_customer_reply"
    detail_ar = "لازم أقرأ الملخص على العميل وأنتظر رده قبل التنفيذ."


def params_hash(params: Mapping[str, Any]) -> str:
    """Stable hash of the prepared parameters. Stored for auditing and for
    layer 2's evals — it makes "the model prepared X and confirmed Y"
    detectable even though confirm_action reads its parameters from the row
    rather than from the model."""
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prepare(
    session: Session,
    *,
    interaction_id: int,
    action: ConfirmationAction,
    params: dict[str, Any],
    user_turn: int,
    now: datetime,
    policy: Policy,
) -> Confirmation:
    """Record a verified-but-not-executed action."""
    confirmation = Confirmation(
        interaction_id=interaction_id,
        action=action,
        params=params,
        params_hash=params_hash(params),
        prepared_at_user_turn=user_turn,
        expires_at=now + timedelta(minutes=policy.confirmation_ttl_minutes),
    )
    session.add(confirmation)
    session.flush()
    return confirmation


def redeem(
    session: Session,
    confirmation_id: uuid.UUID,
    *,
    interaction_id: int,
    user_turn: int,
    now: datetime,
) -> Confirmation:
    """Spend the token, or raise. On success it is marked used, so a second
    confirm_action for the same token fails."""
    confirmation = session.scalar(
        select(Confirmation).where(
            Confirmation.id == confirmation_id,
            Confirmation.interaction_id == interaction_id,
        )
    )
    if confirmation is None:
        raise ConfirmationNotFound()
    if confirmation.used_at is not None:
        raise ConfirmationAlreadyUsed()
    if now >= confirmation.expires_at:
        raise ConfirmationExpired()
    if user_turn <= confirmation.prepared_at_user_turn:
        # The model read the summary and "confirmed" in the same breath. The
        # customer has not spoken since.
        raise AwaitingCustomerReply()

    confirmation.used_at = now
    session.flush()
    return confirmation


def void_prepared_at_turn(
    session: Session,
    *,
    interaction_id: int,
    user_turn: int,
    now: datetime,
) -> int:
    """Kill every live token this turn prepared, and report how many.

    `redeem` asks whether a new customer message arrived after the prepare.
    It cannot ask whether the customer ever *saw* the summary, and those come
    apart when a turn ends without a reply: prepare_* runs, the API call that
    would have read its summary back fails, and the token is then one message
    away from redeemable against a summary nobody read.

    So the caller voids on any turn that did not deliver a complete model
    reply. Expiring is the whole refusal rather than a delay: the next
    `redeem` raises ConfirmationExpired, whose Arabic asks to start over, and
    the model has to prepare again — which regenerates the summary and reads
    it back. Only this turn's tokens: one prepared and read back on an
    earlier turn was seen, and stays good.
    """
    live = session.scalars(
        select(Confirmation).where(
            Confirmation.interaction_id == interaction_id,
            Confirmation.prepared_at_user_turn == user_turn,
            Confirmation.used_at.is_(None),
            Confirmation.expires_at > now,
        )
    ).all()
    for confirmation in live:
        # Not a separate voided_at column, which would need a migration: the
        # row keeps an expires_at of the instant the turn failed, and an
        # auditor cannot tell that from a natural expiry.
        confirmation.expires_at = now
    session.flush()
    return len(live)
