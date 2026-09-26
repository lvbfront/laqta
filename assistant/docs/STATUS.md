# STATUS — where `assistant/` stands

Written for a session that has never seen this repo. Layer 1 is complete and
tested; Layer 2 (evals) is in progress under `eval/` — personas, runner,
simulator, scorer (deterministic checks + Opus judge) and report exist, and
runs land in `eval/runs/`. A 12-episode pilot has run; the 10-per-persona run
has not. This file does not describe eval results: `docs/EVAL.md` §7 does.

- `layer1-spec.md` — the spec, in Arabic. **Source of truth**; this file is not.
- `docs/ARCHITECTURE.md` — the platform/assistant seam, and what moving it costs.
- `docs/EVAL.md` — limits the code cannot enforce (§1–§6), and the failure
  taxonomy with its causes, responses and eval rates (§7).
- `README.md` — setup commands.
- The repo root is Laqta (FastAPI + Next.js). `assistant/` is a separate
  service with its own venv, database, and dependencies. **Nothing outside
  `assistant/` has been modified.**

## What this service is

A text assistant (voice later) for Laqta, a Saudi event-photo platform.
Organizers book an *activation window* for an event; guests scan a QR code and
receive only the photos they appear in. The assistant books, reschedules and
cancels those windows, answers from a knowledge base by retrieval, and opens
tickets for humans.

## Run it

Postgres comes from the repo-root compose stack on host port **5433** (not
5432). Everything below runs from `assistant/` with `.venv` active.

```bash
cd .. && docker compose up -d postgres && cd assistant
docker compose -f ../docker-compose.yml exec postgres createdb -U laqta assistant       # once
docker compose -f ../docker-compose.yml exec postgres createdb -U laqta assistant_test  # once
python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
alembic upgrade head            # re-run after pulling: 3 migrations now
python -m scripts.seed          # idempotent
python -m scripts.index_kb      # idempotent; first run downloads BGE-M3 (~2GB)
pytest                          # 994 passed, 3 deselected
export ANTHROPIC_API_KEY=sk-ant-...
python -m app.cli.chat --as customer:1
```

`pytest -m "not kb"` skips the one module that loads the embedding model.
`pytest -m llm` runs the three smoke conversations against the real API.

## Built and verified

`994 passed, 3 deselected` (the 3 are the `llm` smoke tests). One module loads
BGE-M3; the rest need no model and no API key.

| Area | Code | Tests |
|---|---|---|
| Config + policy | `app/config.py`, `policy.yaml` | `test_config` |
| Schema | 10 tables, 3 migrations | `test_migration`, `test_booking_schema` |
| Seed | `scripts/seed.py` | `test_seed` |
| Identity | `app/identity/` | `test_identity` |
| State machine | `app/domain/booking_state.py` | `test_state_machine` |
| Availability | `app/domain/availability.py` | `test_availability` |
| Capacity lock | `app/domain/capacity.py` | `test_capacity_lock`, `test_capacity_race` |
| Payments/refunds | `app/domain/payment.py` | `test_payment` |
| Confirmations | `app/assistant_domain/confirmation.py` | `test_confirmation` |
| Date resolver | `app/assistant_domain/dates/` | `test_dates_resolver` (repo owner's) |
| Laqta adapter | `app/laqta/` | `test_mock_laqta` |
| Retrieval | `app/kb/` | `test_kb_chunker`, `test_kb_index`, `test_kb_retrieval` |
| Tools (9) | `app/tools/` | `test_tools_registry`, `test_tools_booking`, `test_scoping`, `test_handoff`, `test_side_effects` |
| Arabic names in / out | `app/tools/labels.py` | `test_labels`, `test_summaries`, `test_model_wording` |
| Agent loop + token usage | `app/agent/` | `test_agent_loop`, `test_agent_context`, `test_agent_summarize` |
| Eval personas | `eval/personas.py`, `eval/personas/` | `test_eval_personas` |
| Boundaries | — | `test_domain_purity`, `test_domain_portability` |

Facts worth knowing: 8 saved state transitions plus a creation trigger;
7 availability rules in spec order; 9 tools; 19 KB sections (14 `public`,
5 `internal`); `claude-sonnet-5` for conversation, `claude-haiku-4-5` for
summaries, BGE-M3 for embeddings.

**Not verified:** the live model's *behaviour*. Everything up to the API
boundary is tested with a scripted client. Besides the eval's own runs in
`eval/runs/`, one 3-turn live sample (2026-09-13) confirmed the system-prompt
cache is read: 7,912 tokens (tools + system prompt) written on
the first call and read on every later call, including both calls inside a
tool-using turn. `/debug` in the CLI prints `in / out / cache_write /
cache_read` per API call and per turn; `AgentSession.usage` holds the same
numbers for the eval. Behaviour is what the failure taxonomy below records
and what Layer 2 measures.

## Layers

```
app/config.py + policy.yaml   every number; policy = business, config = technical
app/models/                   10 tables, SQLAlchemy 2.0
app/domain/                   PLATFORM logic: booking_state, availability, capacity, payment
app/assistant_domain/         pure but assistant-only: confirmation, dates/
app/laqta/                    the only path to Laqta: adapter Protocol + MockLaqta
app/kb/                       chunker, embedder (lazy), index, search
app/tools/                    registry + 9 tools; the only place with side effects
app/agent/                    the only place that calls an LLM
app/identity/, app/cli/       DevAuth; chat and admin entry points
```

Two rules are enforced by tests, not by convention:

- `app/domain/` and `app/assistant_domain/` contain no clock read and no LLM
  call (`test_domain_purity`, AST-based).
- `app/domain/` may import only `app/config` and *specific* `app/models/*`
  modules — not the `app.models` package, whose `__init__` pulls in
  assistant-only tables (`test_domain_portability`).

### The seam

`app/domain/` is platform logic: a booking made from the Laqta dashboard
should obey the same lead times, capacity limit and refund tiers. It lives
here because Laqta has no booking concept yet (it has events, photos, guests,
matches) and the assistant is its only consumer. Moving it later = copy the
four modules, the `Booking`/`BookingEvent` models, their migration slice and
five test files; grow `LaqtaAdapter` with `check_availability`,
`create_booking`, `reschedule_booking`, `cancel_booking`; change three call
sites in `app/tools/`. Full detail, including what gets better and what gets
worse, in `ARCHITECTURE.md`.

## Non-obvious decisions

**Confirmation tokens (spec §8).** `prepare_*` validates everything and writes
a token; `confirm_action` refuses unless the token is this session's,
unexpired (10 min), unused, **and** `user_turn > prepared_at_user_turn` — i.e.
the customer sent a new message after the summary was read to them. The
instructions also say to confirm, but the instructions are not what enforces
it. `confirm_action` reads its parameters from the stored row, not from what
the model passes, so the model cannot confirm something other than what was
prepared. A turn that ends without a model reply voids whatever it prepared
(taxonomy 15), so the summary has to have actually reached the customer
before their next message can stand as agreement to it. Limit: it proves the
customer was *given a chance* to reply, not that they said yes — `EVAL.md` §1.

**`when_id` instead of dates.** The model never writes a date. `resolve_when`
takes structured intents (relative day, weekday, absolute, Hijri, prayer time,
part of day), returns a `when_id` held in session state, and every booking
tool takes that id. Any date that reaches a booking has been through the
resolver, and the resolver reports its guesses in `assumptions` for the model
to read back.

**Advisory locks for capacity.** `SELECT ... FOR UPDATE` cannot lock the row
that would breach the limit, because it does not exist yet — two transactions
both count "1 of 2" and both insert. So `capacity.lock_onsite_days` takes
`pg_advisory_xact_lock(hashtext('onsite:{city}:{day}'))`, always in **sorted
day order** (two multi-day events asking for the same days in opposite orders
would otherwise deadlock; there is a control test proving unsorted acquisition
really does deadlock, SQLSTATE 40P01). `prepare_*` checks availability
*without* a lock — holding one across a customer's reply would be wrong — and
`confirm_action` rechecks under the lock before writing.

**Audience filtering in SQL.** `kb_chunks.audience` is filtered inside the
query, so an `internal` chunk is never a row a customer's question can rank.
The tests force this at `min_score=0` for every question, including ones
written to target internal sections, so what excludes them is provably the
filter and not the relevance threshold.

**`now` as a parameter.** Nothing in either pure package reads a clock; `now`
comes from the caller everywhere, including the tool layer (`ToolContext.now`)
and the CLI (`--now 2026-09-11T14:05` makes a conversation reproducible). This
is what makes guard boundaries testable to the second and the Layer 4 fake
clock possible.

**Two-layer tool permissions.** `schemas_for(identity)` sends a role only the
tools it may use; `execute()` checks the role again, because a model can name
a tool it was never given. Resource scoping returns `not_found`, never
`forbidden`, so a booking id cannot be probed — the same anti-enumeration
pattern Laqta uses.

**The registry owns the transaction.** One tool call is one transaction. The
tool body runs inside a `begin_nested()` savepoint, so a crash undoes the
tool's own writes but keeps the surrounding transaction — including the
`tool_calls` row recording the crash, which is exactly when the log matters.

**Only `confirm_action` and `handoff_to_staff` change anything.** `prepare_*`
writes exactly one row, its own confirmation token, and nothing else — no
booking, no ticket, no transition, no Laqta call. Enforced by a full-column
snapshot test, and that test is itself verified by patching a prepare tool to
quietly rewrite a `venue` and watching it fail.

**Two spans for "day".** `event_days` counts calendar dates an event touches
(an onsite crew is unavailable on both sides of midnight) and drives capacity.
`event_length_days` counts days as a customer counts them (21:00→02:00 is one
day) and drives `max_event_days`. Conflating them wrongly rejected a normal
three-day event ending at 01:00.

**Business refusals are data.** `{"ok": false, "error": "onsite_full", ...}`
is ordinary information the model is expected to handle; `is_error: true`
reaches the model only for a real exception. Rejections carry no capacity
numbers — tested by scanning rejection payloads for any integer from the
capacity config and for digits (ASCII *and* Arabic-Indic) outside the ISO
suggestion dates.

## Deferred, and what would change it

| Deferred | State | What it takes |
|---|---|---|
| Layer 4 worker | `payment_expired`, `window_open`, `window_close` exist as transitions; `scheduled_actions` table exists and is unused; nothing fires them | A worker plus a fake clock; the transitions are already tested by passing `now` |
| Working-hours ticket deadlines | KB states them in working hours; Layer 1 applies the minutes as wall clock. Numbers in `policy.handoff` | A working-calendar helper; `escalate_after_reminder_minutes` is stored and unused |
| Precise prayer times | Approximate maghrib table by city and month; every use appends `وقت الصلاة تقريبي` | Umm al-Qura calculation |
| Real authentication | `DevAuth` only — identity is *chosen* with `--as`, not proven | `LaqtaAuth`: bearer token → `GET /api/auth/me`, same `Identity` shape |
| Staff tools | `Identity` supports `staff` and `search_kb` serves them internal sections; no staff-only tools exist | Layer 4 |
| Laqta integration | `MockLaqta` in memory; `seeded(session)` rehydrates events from bookings so ids survive restarts | An HTTP implementation of the same Protocol |
| Add-on prices | Catalogue is names only; the assistant never quotes a price | Prices belong in the KB, not `policy.yaml` |
| Web/voice | Terminal only | Layer 3 |

Not deferred but deliberate: **there is no browse-all-photos path anywhere**,
per the root `CLAUDE.md` hard constraints.

## Known limits already recorded

`docs/EVAL.md` §1–§4 carry four, each with what a metric should count (§5
holds taxonomy 11's reproductions; §7 is the failure taxonomy as the eval
measures it):

1. The confirmation guarantee stops at "was given a chance to reply".
2. An internal-only question returns plausible *public* sections above the
   threshold instead of nothing — confirmed live, see taxonomy item 1.
3. Section-level chunking misses a bullet buried in a long section
   (`MIN_INTERNAL_HIT_AT_3 = 0.80`, four of five).
4. `KB_MIN_SCORE = 0.45` sits in a narrow measured band: worst correct answer
   0.484, best off-topic 0.428, over 20 positives and 6 negatives. Re-derive
   with `pytest tests/test_kb_retrieval.py -k threshold -s`.

`scripts/try_kb.py` (19 lines, the repo owner's) prints raw retrieval scores
by hand for a few queries, including the item-1 case marked `MUST be empty`.

## Failure taxonomy — observed in manual testing

Collected by the repo owner over two hand-testing sessions against the live
model; 11 and 12 were found while writing the eval personas. Where a cause is
stated it is a reading of the code, not a proven diagnosis, unless it says
otherwise.

Every entry carries one of three statuses. **Read them literally — they are
not the same kind of claim.**

| Status | Entries | Meaning |
|---|---|---|
| **Fixed — enforced in code** | 2, 3, 5, 6, 9, 11, 13, 15, 16 | The tool's own handling and output are now correct whatever the model passes in. Covered by tests, and each of those tests was checked by removing the fix and watching it fail. What the model then *says* is still not enforced. |
| **Prompt-only — not verified** | 7, 8 | An instruction was added to the system prompt. Nothing enforces it and no test can cover it: a test can assert the instruction exists, not that the model follows it. Layer 2 measures the real rate. |
| **Open** | 1, 4, 10, 12, 14 | Deliberately not fixed. Layer 2 measures them as they are. |

The eval should keep scoring 2, 3, 5, 6, 9, 11 and 13 as regressions: "fixed" here means
the tool output is right, and the model can still paraphrase around it (e.g.
drop the retention sentence when reading the summary back).

**1. Ungrounded answers.** — *Open.* When `search_kb` returns irrelevant sections that
still clear 0.45, the model answers from its own knowledge instead of handing
off. Seen with a parking question and a live-video question. This is
`EVAL.md` §2 confirmed live. *Measure:* for questions the KB cannot answer,
classify each reply as handed off / said it does not know / answered anyway —
the third is the failure, and it reads as fine unless you know the KB.

**2. UUID fabrication.** — *Fixed at the source, enforced in code
(2026-09-13); the model's calls are not.* The model invents a padded UUID
(`9fe54331-0000-…`) or passes the bare first block, gets `not_found` or
`invalid_input`, calls `get_my_bookings`, and retries correctly. Twice in two
hand-testing sessions; in the pilot, 3 of the 4 episodes that referenced a
booking by id — a2 `456276dd` → `invalid_input`, a6 and p25 padded →
`not_found`. Recovery works; the extra round trip does not. *Cause (pilot
evidence, not proof):* the context block printed each booking as
`#<first UUID block>`. All three fabrications came when the customer named the
event and used exactly that block; in a4 the customer quoted the short id
themselves and the model looked it up first. *Measure:* fabricated
`booking_id` calls per booking-referencing turn.

*Fix:* the context block lists each booking by event name, date, city and
status, with **no id at all** — `_short` is gone rather than kept with a new
docstring, since nothing else used it. The full UUID was deliberately not put
there instead: the model would sooner or later read it to a customer, stopping
that would be a prompt-only rule (8 shows those don't hold), and a UUID cannot
be spoken in voice. `get_my_bookings` is the one source of ids. The
`prepare_cancel` description did not say so (only `prepare_reschedule`'s
did), so both tools' `booking_id` now carries "The full booking_id exactly as
get_my_bookings returned it." A customer quoting a dashboard number still
works: the full id `get_my_bookings` returns starts with it. *Tests:*
`test_agent_context` fails on the old block — no full id, first block, `#` or
8+ character hex run. *Still measurable:* fabrication with nothing in context
to complete would mean the cause reading was wrong; expect one
`get_my_bookings` per booking-referencing conversation instead. Note for the
eval: `eval/signals._booking_id_calls`'s docstring still says the context
block shows the first block.

**3. Arabic package names always rejected.** — *Fixed, enforced in code
(2026-09-13).* `الأساسية` / `القياسية` hit `unknown_package` on every booking
attempt before the model retries in English. *Cause:* `policy.packages` keys
are English slugs (`starter`/`standard`/`premium`) while the KB names the
packages in Arabic, so the model passes back what it read. One wasted call
every booking. *Measure:* `unknown_package` rate per completed booking.

*Fix:* `app/tools/labels.py` holds one explicit alias table per field —
packages, match modes, add-ons and cities — and pydantic `before` validators
on `prepare_booking` (and on `check_availability` / `resolve_when` for the
city) turn a known Arabic name or spelling into the English key. Rows,
confirmation params and Laqta calls only ever carry the key. No fuzzy
matching: an unknown name passes through unchanged and is rejected as before
(`unknown_package`, `unknown_addon`, `invalid_input`).

Cities are deliberately narrower than "any alias". Only spellings of جدة /
الرياض / الدمام resolve; a neighbouring city (الخبر, الظهران) is never mapped,
because a booking whose city silently changed would still pass the customer's
check — the summary would show the substitute. An **onsite** request in any
other city is refused as `onsite_city_unsupported` with `supported_cities`
(slugs) and `supported_cities_ar` returned. A **remote** booking in any other
city is accepted and stored exactly as given, since the KB says service
without onsite support covers every city. Availability rules still run in
spec §6 order, so an onsite request in an unsupported city *inside* the 7-day
lead time is refused as `lead_time` first. *Tests:* `test_labels`, and the
alias and city tests in `test_summaries` (every alias end to end through the
registry; الخبر mapped to الدمام makes 4 fail).

**4. Confirmation-token ambiguity.** — *Open.* Two `prepare_*` tokens can be live at
once, and nothing defines which one a bare `نعم` confirms. Untested but
reachable; a wrong cancel here costs real money. *Cause:* `confirmations` has
no per-interaction uniqueness, and `confirm_action` takes an explicit
`confirmation_id`, so the model chooses. The code guarantees single-use and
the turn gap, not that the right token was picked. *Measure:* sessions with
more than one live token, and whether the confirmed id matches the summary
most recently read aloud.

**5. `summary_ar` leaks English enums** to the customer (`both`, `starter`,
`code`). — *Fixed, enforced in code (2026-09-13).* *Cause:* `prepare_booking`
interpolated `match_mode.value` and `package` straight into Arabic prose.
*Measure:* English tokens in customer-visible text.

*Fix:* the summary renders package, match mode, add-ons and onsite city
through the Arabic labels in `app/tools/labels.py`, which a test pins to the
KB's own wording. *Tests:* `test_summaries` builds 120 booking summaries
(every valid package × match mode × strict × onsite × city, with all allowed
add-ons) plus reschedule and cancel summaries, and fails on any enum value or
any Latin letter; a control test feeds it the old wording to prove it fires.
*Still measurable:* the model's own replies are not covered — only the tool's
summary is.

**6. Strict mode silently shortens retention.** — *Fixed, enforced in code
(2026-09-13).* `policy.strict_mode.retention_days` (7) overrides the package's
(14 for starter) and nothing surfaced it. A customer could book a women's
event believing they get 14 days. *Measure:* strict-mode bookings where the
retention change was stated.

*Fix:* a strict-mode `summary_ar` now states it, e.g. `مدة حفظ الصور 7 أيام
بسبب الوضع المشدد، وتلغي مدة الباقة الأساسية (14 يوم).` Both numbers come
from `policy.yaml`. *Tests:* `test_summaries`, for each package. *Still
measurable:* whether the model reads that sentence out rather than
summarising the summary.

**7. Unprompted emoji** in most replies, including 🌸. — *Prompt-only, not
verified (2026-09-13).* *Cause:* the system prompt said nothing about emoji.
*Measure:* emoji rate per reply.

*Change:* the system prompt now says "Never use emoji, including when the
customer does." That is a request, not a guarantee. No code strips emoji and
no test covers the behaviour (`test_agent_loop` only asserts the sentence is
in the prompt). The 3-turn live sample above had no emoji, which is too small
to mean anything. The eval measures the real rate
(`p20_selfie_privacy_emoji` is the strongest provocation).

**8. Gender slips.** `توافقين` addressed to a male customer. — *Prompt-only,
not verified (2026-09-13).* *Cause:* `contacts` stored no gender and the
context block passed only a name; the prompt gave no guidance. *Measure:*
gendered verb/adjective agreement against the contact.

*Change:* `contacts.gender` exists (nullable; migration `3f1c9b7a2d40`) and is
set only from something the person stated — never inferred from a name, so
every seeded contact is NULL. The context block always says either `الجنس:
غير مذكور في السجل.` or the stated gender. The system prompt asks for
gender-neutral address (polite plural, or phrasing around the verb) unless
the record states a gender, and never to infer it from a name. The data
plumbing is tested (`test_agent_context`); the model's compliance is not and
cannot be.

**Not holding in practice yet.** In the 2026-09-13 live sample, with the
context block saying `الجنس: غير مذكور في السجل.`, the first reply was
`أهلاً فهد، حياك الله في لقطة. كيف أقدر أساعدك اليوم؟ تبي تحجز فعالية؟` —
the customer's name, and `تبي` (masculine singular) rather than the neutral
`تبون`. Later turns used the plural (`تحطون`). One sample; the eval measures
the real rate.

**9. Refund percentage changes with the date and the change is never
explained.** — *Fixed, enforced in code (2026-09-13).* `prepare_cancel`
returned the number without the tier or the boundary that produced it, so a
customer cancelling a day later saw a different figure with no reason.
*Measure:* cancellations where the tier and its cutoff were explained.

*Fix:* `app/domain/payment.refund_tier` returns the whole tier, and the
cancel summary appends its reason from `policy.refunds`, e.g. `ونسبة
الاسترداد 100% لأن الإلغاء قبل الفعالية بـ7 أيام أو أكثر.` / `… بأقل من 7
أيام وبـ48 ساعة أو أكثر` / `… خلال آخر 48 ساعة قبل الفعالية`. *Tests:*
`test_summaries`, including both edges of each tier. Since 11, this applies
to paid bookings only.

**10. The capacity refusal is right but leaky, and files nothing.** — *Open.* The tool
payload is clean (`الموعد غير متاح.`, no digits, enforced by test) — the leak
is in the model's phrasing, which reveals that internal capacity rules exist.
No ticket is opened either: `onsite_full` returns suggestions but no `handoff`
object, so a customer blocked by capacity leaves no trace for staff.
*Measure:* replies implying capacity limits exist; share of full-date
conversations ending with no ticket.

Two more were found while writing the eval personas, not in hand-testing.
Both are deliberately left unfixed so layer 2 measures them.

**11. An unpaid tentative cancellation is charged a time-based refund
tier.** — *Fixed, enforced in code (2026-09-13).* The KB (تعديل الموعد
والإلغاء): «الحجز المبدئي اللي ما انْدفع ممكن يتلغى في أي وقت بدون رسوم».
`prepare_cancel` applied `policy.refunds` to every booking, so an unpaid one
74.9h out was summarised as "50% refund". Reproduced by hand (repo owner) and
in the pilot (`p25`), both in `EVAL.md` §5. In p25 the agent later corrected
itself in chat, but `confirm_action` still logged `refund_percent: 50`: the
conversation ended right and the data ended wrong. *Cause:* no payment-status
exception anywhere, and `_cancel` recomputed the percentage at execution time,
so fixing the prepare alone would still have written 50%. *Measure:*
`unpaid_tentative_no_fee_stated` (judge), plus at the data level: no
`refund_percent` in the prepared params or either result.

*Fix:* `policy.yaml` scopes the table with a sibling key,
`refunds_apply_to: [confirmed]`. Only `mark_paid` makes a booking confirmed.
It is a sibling rather than a mapping around `refunds`, because
`tests/test_eval_personas.py` reads `refunds` as a plain list.
`app/domain/payment.refund_applies(status, policy)` decides, and both sites
use it:
- `prepare_cancel`, for an unpaid booking: the summary is `إلغاء «…» بتاريخ
  …. الحجز مبدئي وما انْدفع، فيتلغى بدون رسوم.`, with no percentage, no
  `refund_percent` in the result, and params of only `{"booking_id"}`.
- `_cancel` decides on the status before the transition, and returns no
  `refund_percent` for an unpaid booking. A booking **paid between prepare and
  confirm** is refused as `booking_changed` and not cancelled: the customer
  agreed to "بدون رسوم", and a tier now applies. The model re-prepares and
  gets the tiered summary.

Paid bookings are unchanged, tier reason included; `refund_percent` is still
recomputed at confirm time. The `prepare_cancel` description now says an
unpaid booking has no percentage.

*Tests:* in `test_summaries`, at nine points covering both edges of every tier
plus 74.9h:
- an unpaid booking's summary says بدون رسوم, with no `%` and no استرداد;
- its params are exactly `{"booking_id"}`, and neither result carries
  `refund_percent`;
- a paid booking carries the same percentage in the prepare result, the
  params and the confirm result.

Also the pay-between race, `test_payment`, and `test_config`, which checks
tentative is never in `refunds_apply_to`. The existing cancel tests in
`test_tools_booking` cancelled a never-paid booking and expected a
percentage; they now mark it paid first. Removing the fix
(`refund_applies` always true) fails 11 tests. Fixing only `prepare_cancel`
(`_cancel` always recomputing) fails 10, all at the confirm result or the race.

**12. Fabricated links.** — *Open.* The system prompt tells the agent to offer an
anonymous visitor "the Laqta registration link", but no tool result, KB
section or context block contains a URL, so any link the agent writes is
invented. *Cause:* the instruction names a fact the agent has no source for.
*Measure:* URLs in customer-visible text that do not appear in a tool result
or the context block (grounding check; provoked by `p23_anon_tries_to_book`).

**13. The model writes English enum words in its own replies.** — *Fixed at
the source, enforced in code (2026-09-13); the replies themselves are not.*
Found in the first live eval episodes (2026-09-13), not in hand-testing.
`summary_ar` was clean since the fix to 5, but in the pilot the model wrote the
keys in its own questions in 12 of 73 replies — every booking conversation that
reached the match-mode or package question: «بالوجه (face) أو برمز (code) أو
بالتسلسل (sequential)», «وضع الخصوصية الصارم (Strict Mode)», «أي باقة
تفضلون: Starter أو Standard أو Premium؟», «الحالة: مبدئي (Tentative)».
*Cause:* the model read those words in what it is sent — the system prompt
(`face, code, sequential, or both`, "strict mode"), `prepare_booking`'s schema
(the package description, the `MatchMode` enum, the title `Strict Mode`),
`confirm_action`'s `status: tentative`, and the context block's city slug.
«الوضع الصارم» for الوضع المشدد is the same cause: it translated "strict mode".
*Measure:* model replies containing an English enum word that no earlier
`summary_ar` in the session contained (`eval/signals.py` separates this from an
echo of 5). The same words are also flagged as ungrounded when they list
options, because the system prompt and tool descriptions are not grounding
sources.

*Fix:* every surface the model reads names these choices as the KB does, from
the tables in `app/tools/labels.py` (`STATUS_AR` moved there from
`context.py`; `STRICT_MODE_AR` added).
- **System prompt:** match modes as مطابقة الوجه، مطابقة الرمز، الترقيم
  التسلسلي، الوجه والرمز معاً; الوضع المشدد throughout; "a quote for الباقة
  المميزة" instead of "a premium quote".
- **`prepare_booking` schema:** `match_mode` and `package` are offered as
  enums of the Arabic names; `strict_mode` is titled الوضع المشدد; the city
  description names جدة / الرياض / الدمام. The `before` validators still
  accept the English keys, and rows, params and Laqta calls still carry only
  the keys. `search_kb` and `handoff_to_staff` descriptions follow suit.
- **Tool results:** the English value stays under its key — `status` is read
  by the scorer — with an Arabic sibling beside it, as `supported_cities_ar`
  already did: `status_ar` (get_my_bookings and all three `confirm_action`
  results), `city_ar` and `package_ar` (get_my_bookings), `packages_ar`
  (`unknown_package`, `onsite_not_available_for_package`), `available_ar` /
  `addons_ar` (`unknown_addon`, `addon_not_allowed_in_strict_mode`),
  `suggested_package_ar` (`guests_exceed_package`), and `team_ar` in
  `handoff_to_staff`'s result and in every refusal's `handoff` object
  (`TEAM_AR` moved to `labels.py` too).
- **Context block:** the city as جدة, not `jeddah`.

One sentence in the system prompt is prompt-only, like 7 and 8: a field ending
in `_ar` is customer wording, and the same field without it is an internal key
not to write in a reply.

*Tests:* `test_model_wording` scans the system prompt, every tool description,
and every schema enum and title for anonymous and customer, with a control fed
the old schema wording; checks each Arabic name the schema offers is accepted
and stored as the key, that English keys still are, and the `_ar` siblings and
the context-block city. `test_handoff` checks `team_ar` for every reason code;
`test_labels` checks the status and team tables are complete and the team
names are the KB's. Run against the pre-fix prompt, tools and context
block, 9 of its 13 tests fail (the 4 that pass are the control and the
regression guards for accepted input). Prose checks skip `both`, `code`,
`live`, `ended`, which are also ordinary English ("read back BOTH dates", "a
live event"); enums and titles are checked for all of them.
*Still measurable:* the model can still write an English word it never read.
The pilot numbers are historical: the 10× run is the comparison.

**14. The model leaks its own instruction-following into a reply.** —
*Open.* Found in the eval pilot (2026-09-13), one sample. In
`a3_skip_confirmation_instruction` the last reply to the customer was
«في أمان الله، ويعطيكم العافية. نتشرف بخدمتكم دايماً 🌸\n\nWait, no emoji
allowed.» — it broke the no-emoji rule, then wrote its self-correction into
the message instead of fixing the message. Distinct from 7 (the emoji) and 13
(enum words): the leak is the model narrating a rule it is following. *Cause:*
unknown; one sample. *Measure:* model replies containing a run of three or
more English words that are not enum words (`eval/signals.english_prose_in`
— catches English self-talk, not the same leak in Arabic), cross-checked
against the judge's `internal_leaks` of kind `other`. Pilot: 1 of 73 replies.

Two more were found while building the web layer (2026-09-16), by reading the
loop rather than by watching the model. Both are in the loop itself, so
neither has a persona: no conversation provokes an API timeout on purpose.

**15. A confirmation prepared on a turn the customer never got a reply
to.** — *Fixed, enforced in code (2026-09-16).* `redeem` requires
`user_turn > prepared_at_user_turn`, which asks whether a new customer
message arrived after the prepare. It does not ask whether the customer ever
saw the summary, and those are different questions whenever a turn ends
without a model reply: on turn 5 the customer says «احجز», `prepare_booking`
writes its token, the next `messages.create` times out, and the customer is
handed `API_ERROR_MESSAGE`. Whatever they say on turn 6 now satisfies the
check, and `confirm_action` books an event against a summary that was never
read to them. *Cause:* the prepare and the reading-back of its summary happen
in the same turn but are not the same event, and only the first one is
recorded. *Measure:* confirmed bookings whose confirmation was prepared on a
turn whose `reply_source` was not `model`.

*Fix:* `app/agent/loop.py` classifies how a turn ended (`_Turn.delivered`,
true only for a complete model reply) and voids on anything else —
`API_ERROR_MESSAGE`, the `AGENT_MAX_STEPS` fallback, an empty reply, a
refusal, a `max_tokens` truncation, and any propagating exception.
`confirmation.void_prepared_at_turn` sets `expires_at = now` on every unused
token prepared during that turn, so the next `redeem` raises
`ConfirmationExpired` — whose Arabic asks to start over, which is the right
instruction: the model has to prepare again, and preparing again regenerates
the summary and reads it back. Only that turn's tokens: one prepared and read
out on an earlier turn was seen, and stays good. *Limits:* expiring the row is
the whole mechanism, so an auditor cannot tell a voided token from one that
timed out naturally — a `voided_at` column would need a migration. And the
void is a database write, so a database failure is the one thing that can
leave a token alive; `assistant/server/` closes that by marking the chat
session broken and refusing further messages on it. *Tests:*
`test_confirmation_delivery.py`, all five endings plus two controls (a
delivered summary still confirms; an earlier turn's token survives a later
turn failing). With the void removed, all five endings create a booking.

**16. A tool call that loses its result wedges the whole session.** —
*Fixed, enforced in code (2026-09-16).* Every `tool_use` block must be
answered by a `tool_result` in the next message, or the request is malformed.
`registry.execute` never raises — a crashing tool comes back as data — but
its bookkeeping does: the `tool_calls` row is written and committed after the
savepoint closes, outside that guarantee. If that commit raises, the loop
propagates with a `tool_use` block in `session.messages` and no result beside
it. *Cause:* the results were appended to the message list only on the
success path. The cost is not the turn that failed, it is every later turn on
that session, because each one resends the whole history. *Measure:* sessions
whose message list holds a `tool_use` id with no matching `tool_result`.

*Fix:* the tool step collects its `tool_use` blocks first, and on any
`BaseException` (Ctrl-C included) fills in `crashed(...)` results for the
calls that never ran before re-raising, attaching them in a `finally`. The
stand-ins carry `is_error: true` and the exception text, so a model resuming
the conversation reads a failed call rather than an empty success. *Tests:*
`test_loop_wedge.py`, including a parallel step where one raising call would
otherwise orphan every block beside it. With the fix removed, 3 of its 4 fail.

## Known scope gap: independent photographers

Laqta has two customer types and the assistant serves only one. Everything
here is written for **event organizers**. **Independent photographers and
studios** are a real second flow: card payment on a subscription or event
credits, a gallery carrying their own brand, and venue or guest count that
may not apply. The activation window, the date resolver, capacity rules and
the booking state machine are shared; the required fields and payment are
not.

Nothing models the second flow — no persona, no required-field set, no
payment path. **Correct behaviour today is a handoff**, not an invented flow:
a customer asking about the photographer service should reach
`handoff_to_staff`, and an agent that collects organizer fields for a
photographer, or quotes card or subscription terms, is wrong. (The KB's
`خدمة المصورين` section is public and can answer questions about it; booking
it is what does not exist.)

## Trusting the tests

These tests were checked by deliberately breaking the thing they cover, which
is worth repeating before relying on them:

- Disable `lock_onsite_days` → `test_capacity_race` fails 3 runs out of 3
  (`assert 5 == 1`, all five threads book). `READ_TO_WRITE_DELAY` in that test
  exists to make the failure deterministic rather than timing-dependent; an
  earlier version of the test passed without the lock about half the time.
- Patch `can_apply` to rewrite a `venue` → `test_side_effects` fails on
  exactly `prepare_cancel` and `prepare_reschedule`.
- The taxonomy fixes, each removed in turn: package aliases off → 9 alias
  tests fail; English match mode back in the summary → the enum scan fails;
  strict retention sentence removed → 3 fail; refund reason removed → 5 fail;
  الخبر added as a الدمام alias → 4 fail; `supported_cities` dropped → 5 fail.
- A synthetic violating source is fed to the AST checker in
  `test_domain_portability`, so a walker that silently returns nothing cannot
  make the whole module pass.
- Taxonomy 15's void removed → all five `test_confirmation_delivery` endings
  fail, each by creating a real booking; the two controls still pass.
- Taxonomy 16's result back-fill removed → 3 of 4 `test_loop_wedge` tests
  fail; the working-turn control still passes.

## Gotchas for a cold session

- `assistant_test` is dropped and re-migrated at the start of every test
  session. Never point `ASSISTANT_TEST_DATABASE_URL` at anything real; the
  fixture refuses a name not ending in `_test`.
- Env vars are prefixed `ASSISTANT_` on purpose, so a shell configured for
  Laqta cannot point this service at Laqta's database.
- Alembic autogenerate needs hand-editing every time: it omits the `pgvector`
  import and `CREATE EXTENSION`, and re-emits `CREATE TYPE` for an enum shared
  by several tables. See the initial migration's docstring.
- `AGENT_MAX_TOKENS = 4096`, deviating from spec §12's 1024, because adaptive
  thinking draws from the same budget on Sonnet 5 and a truncated turn
  mid-summary is the worst place to run out.
- The dev `assistant` database contains one empty `interactions` row (#1) from
  a CLI smoke run. `python -m scripts.seed --reset` clears it.
- Migration `3f1c9b7a2d40` (contacts.gender) **has** been applied to the dev
  `assistant` database; it is at head. An earlier version of this file said it
  had not, which was true when written and stopped being true without the note
  being updated. Check with
  `psql -h localhost -p 5433 -U laqta assistant -c 'select * from alembic_version'`
  rather than trusting this line.
- `system_prompt.md` may contain `<!-- -->` notes for editors (one explains
  why booking questions are grouped for text but voice will want one field at
  a time). `system_prompt()` strips them before sending; they cost no tokens
  and never reach the model.
- The resolver is the repo owner's work (`app/assistant_domain/dates/`). A
  multi-day after-midnight bug found during handoff — `days=2` silently
  resolving to the same window as `days=1` — has been fixed; verified at
  `days=1/2/3` → 18/19/20 September for a Thursday 21:00→01:00 booking.
