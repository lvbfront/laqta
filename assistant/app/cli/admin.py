"""Staff actions that have no tool yet (spec §13).

    python -m app.cli.admin mark-paid <booking_id>
    python -m app.cli.admin show <booking_id>

Payment lands outside the assistant, so marking a booking paid is a staff
action. It goes through the state machine like every other transition, which
is why it shows up in booking_events with an actor.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone

from app.config import get_policy
from app.db import SessionLocal
from app.domain.booking_state import GuardFailed, InvalidTransition, Trigger, apply
from app.models.booking import Booking


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    paid = sub.add_parser("mark-paid", help="tentative → confirmed")
    paid.add_argument("booking_id")
    paid.add_argument("--actor", default="staff:cli")

    show = sub.add_parser("show", help="print one booking and its history")
    show.add_argument("booking_id")

    args = parser.parse_args(argv)
    policy = get_policy()
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        booking = _load(db, args.booking_id)
        if booking is None:
            print(f"no booking {args.booking_id}", file=sys.stderr)
            return 1

        if args.command == "show":
            _print(booking, policy)
            return 0

        try:
            apply(booking, Trigger.mark_paid, now=now, policy=policy, actor=args.actor)
        except (InvalidTransition, GuardFailed) as exc:
            print(f"{exc}", file=sys.stderr)
            return 1

        db.commit()
        _print(booking, policy)
        return 0


def _load(db, raw_id: str) -> Booking | None:
    try:
        booking_id = uuid.UUID(raw_id)
    except ValueError:
        print(f"not a booking id: {raw_id}", file=sys.stderr)
        return None
    return db.get(Booking, booking_id)


def _print(booking: Booking, policy) -> None:
    local = booking.starts_at.astimezone(policy.tz)
    print(f"{booking.id}  {booking.event_name}")
    print(f"  status      {booking.status.value} (version {booking.version})")
    print(f"  when        {local:%Y-%m-%d %H:%M} Riyadh, {booking.city}")
    print(f"  payment due {booking.payment_due_at.astimezone(policy.tz):%Y-%m-%d %H:%M}")
    print(f"  laqta event {booking.laqta_event_id}")
    for event in booking.events:
        source = event.from_status.value if event.from_status else "—"
        print(f"  · {event.at:%Y-%m-%d %H:%M}  {source} → {event.to_status.value}  ({event.actor})")


if __name__ == "__main__":
    sys.exit(main())
