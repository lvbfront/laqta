# Architecture: what is platform, what is assistant

This service holds two kinds of code. Keeping them apart is deliberate, and
this file exists so the split can be explained rather than rediscovered.

## The two kinds

**Platform logic** — rules about bookings that are true no matter who is
booking. A customer clicking "book" in the Laqta dashboard should be held to
the same lead times, the same onsite capacity limit and the same refund
tiers as one talking to the assistant.

**Assistant logic** — everything about *having a conversation*: the tool
registry, the agent loop, retrieval, the CRM (who we talked to, what they
asked, which ticket it became), and the machinery that stops a language
model from acting before the customer agreed.

The folder layout says which is which:

| | Platform — would move to the Laqta API | Assistant — stays here |
|---|---|---|
| Pure logic | `app/domain/` — `booking_state`, `availability`, `capacity`, `payment` | `app/assistant_domain/` — `confirmation`, `dates/` |
| Everything else | `app/models/booking.py`, `booking_event.py` | `app/tools/`, `app/agent/`, `app/kb/`, `app/cli/`, `app/identity/`, `app/laqta/` |
| Tables | `bookings`, `booking_events` | `contacts`, `staff`, `interactions`, `tool_calls`, `tickets`, `confirmations`, `kb_chunks`, `scheduled_actions` |
| `policy.yaml` | lead times, `max_event_days`, upload window, reschedule cutoff, payment deadline, refunds, onsite, packages, add-ons, strict mode, availability suggestions | `confirmation_ttl_minutes`, `handoff.*` |

Both pure packages hold to the same discipline — no LLM call, no clock, `now`
always a parameter — which is why they are neighbours. The difference is
destination: `app/assistant_domain/` is pure *and* assistant-only. A
dashboard has a date picker and a confirm button; it needs neither
natural-language date resolution nor a token proving the customer was given
a chance to reply.

## Why the platform logic is here today

Laqta has no booking concept. It has events, photos, guests and matches; the
commercial act of reserving an activation window does not exist in its
schema. The assistant is the first thing that needs it, and is currently its
only consumer, so the rules were written where they were needed.

The alternative — adding a booking domain to the Laqta API first, then
building the assistant against it — would have meant designing the platform
API with one hypothetical consumer, and shipping nothing until both halves
existed.

## The seam

`app/domain/` may import `app/config`, specific `app/models/*` modules, and
itself. Nothing else under `app/` — not even the `app.models` package, whose
`__init__` imports every model including assistant-only tables. Enforced,
not trusted:

- `tests/test_domain_portability.py` — the import rule, plus a check that
  `app/domain/` contains exactly the four platform modules.
- `tests/test_domain_purity.py` — no clock, no LLM, across both pure
  packages.

Dependencies run one way: the tools call the domain. `prepare_booking` calls
`capacity.check_without_lock`, `confirm_action` calls
`capacity.check_under_lock` then `booking_state.apply`, and both use
`payment.payment_deadline`. The domain knows nothing about any of them.

### What moving would involve

**Moves:** the four modules in `app/domain/`, the `Booking` and
`BookingEvent` models, their part of the initial migration, and
`tests/test_state_machine.py`, `test_availability.py`, `test_capacity_lock.py`,
`test_capacity_race.py`, `test_payment.py`. The advisory lock goes with
`capacity.py` and runs inside Laqta's transaction instead of the
assistant's; the race test runs against Laqta's database.

**Stays:** `app/assistant_domain/` and every assistant-only row above. The
CRM keeps owning "what happened between us" and would reference a booking by
id only.

**What the assistant calls instead:** `LaqtaAdapter` (`app/laqta/adapter.py`)
grows booking methods — `check_availability`, `create_booking`,
`reschedule_booking`, `cancel_booking` — and `MockLaqta` grows the same ones,
so the tests stay offline. The tool layer changes at three call sites:
`prepare_booking`, `prepare_reschedule`/`prepare_cancel`, and
`confirm_action` swap domain calls for adapter calls. Nothing else in the
tool layer moves, because the tools already speak in terms of "check this,
then execute that".

Two things get *better* in the process. `confirm_action` becomes one
idempotent API call that locks, rechecks and creates atomically on Laqta's
side, so the assistant stops needing transaction discipline for capacity.
And the idempotency key it already sends (`booking.id`, spec §9) is the key
that call would use.

One thing gets worse: the assistant's database and Laqta's become genuinely
separate, so `tickets` and `bookings` can no longer be joined in SQL.
`get_my_bookings` becomes a network call, and the context block (spec §12)
has to fetch bookings rather than select them.

### Two things to know about the boundary

`app/domain/capacity.py` takes a SQLAlchemy `Session`. The domain is not
database-free — only clock-free and assistant-free. That is fine for a move
into another SQLAlchemy service, and would be a rewrite for anything else.

The per-module import rule is about the *static* dependency: a copied
`app/domain/` needs `app/models/booking.py` and its imports, not this repo's
`app/models/__init__.py` and the aggregate API it exposes. Python still
executes that `__init__` at runtime here, because importing a submodule
initialises its parent package — and it must, since Alembic autogenerate
depends on every model being imported. The rule removes the coupling that
matters for a move, not the parent-package import that Python performs
regardless.
