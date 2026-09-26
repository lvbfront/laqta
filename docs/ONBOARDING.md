# Understanding the Laqta assistant

A reading guide for someone joining this codebase who will be asked to improve it —
and who needs to be able to explain how it works, at any depth, without notes.

Written to be read with the code open. It points at things; it doesn't repeat them.
Read `docs/ARCHITECTURE.md` for the module map and `docs/STATUS.md` for current
state; this file is about *why*, and about what to look at in what order.

---

## 0. The answer, before the detail

When someone asks "how did you build this?", the thirty-second version is:

> It's a tool-calling agent over a Postgres domain. The model never writes a date,
> never writes a booking, and never sees a rule it's trusted to follow — the dates go
> through a hand-written resolver that takes structured intents, the bookings go
> through a prepare/confirm pair where the code refuses to execute unless the customer
> replied after hearing the summary, and the business rules live in a pure domain layer
> with no clock and no LLM in it. Then there's an evaluation harness: simulated
> customers with hidden state, ~30 personas, deterministic checks plus an Opus judge,
> and a failure taxonomy with measured rates.

Every clause in that paragraph is a place someone can push. The rest of this document
is so you can go three levels deeper on any of them.

---

## 1. Reading order

Seven sittings. Each has a goal, the files, and one exercise. Do the exercises — reading
code teaches you less than breaking it.

### Sitting 1 — Use it, then trace one message

**Goal:** know what the thing does before you know how.

```bash
python -m app.cli.chat --as customer:1
/debug
```

Book something. Watch the tool calls scroll past. Then cancel it.

Now trace a single message through the code by hand, without running anything.
Start at `app/cli/chat.py`, follow into `app/agent/session.py` and
`app/agent/loop.py::run_turn`, and write down every function the message touches
until a reply comes back. It's about eight steps. Do not skip this — everything else
in this guide is a detour off that path.

**Exercise:** on paper, draw the loop. Model decides → tool executes → result goes back
→ model decides again. Mark where the loop can exit and where it can't.

### Sitting 2 — The domain layer

**Goal:** understand that the business rules are not in the prompt.

Read in this order:

- `app/domain/booking_state.py` — the whole file, it's ~175 lines. `TRANSITIONS` is a
  dict, not a pile of `if`s. Anything absent from it is illegal by construction.
- `app/domain/availability.py` — `check()` is a pure function: seven rules, first
  failure wins, returns a reason code and nothing else. No prose, no numbers.
- `app/domain/capacity.py` — `lock_onsite_days`, `check_under_lock`.
- `app/domain/payment.py` — the deadline rule and `refund_applies`.
- `policy.yaml` — every operational number in the system. If a number appears in code,
  it's a bug.

Three things to notice:

1. **`now` is always a parameter.** Nothing in `app/domain/` calls a clock.
   `tests/test_domain_purity.py` scans the AST and fails the build if it does. This is
   what makes a fake clock possible, and it's why time-based rules are testable to the
   second.
2. **`can_apply()` is a read-only twin of `apply()`** — same table, same guards, same
   exceptions, no mutation. It exists because a `prepare_*` tool has to know whether a
   transition *would* be refused without performing it.
3. **The rejection carries no capacity numbers.** `onsite_full` and nothing else. The
   model can't leak a number it was never sent, and a test scans for capacity integers
   and Arabic-Indic digits in rejection payloads.

**Exercise:** open `tests/test_state_machine.py` and find the test that walks all 35
state × trigger pairs. Delete one entry from `TRANSITIONS` and run it. Then delete the
guard on `window_open` and run it again. You now know what those two lines protect.

### Sitting 3 — The date resolver

**Goal:** the hardest correctness problem in the project, and the one you'll be asked
about most.

- `app/assistant_domain/dates/intents.py` — the pydantic models. Note what they *are*:
  the model emits `{"kind": "relative_weekday", "weekday": "thu", "which": "next"}`,
  not a date.
- `app/assistant_domain/dates/resolver.py` — `_resolve_date`, `_resolve_time`,
  `resolve`. Split deliberately: date and time are each simple alone and miserable
  together.
- `tests/test_dates_resolver.py` — 82 cases pinned to a fixed reference date,
  Friday 2026-09-11 = 29 Rabi' al-Awwal 1448.

The design claim: **an LLM asked for a date will produce a plausible one, and you
cannot tell a right answer from a wrong one by looking at it.** So it isn't allowed to.
It emits a description, the code computes the date, and anything it couldn't compute
comes back as `Ambiguous` with a question rather than a guess.

Two bugs found here are worth knowing by heart, because they're the best answer to
"tell me about a bug you found":

- **"يوم ١٧" jumped a year instead of a month.** Reusing the `AbsoluteDate` rollforward
  meant that when today is 29 Rabi' al-Awwal, "the 17th" resolved to August *2027*
  instead of 28 September 2026. The right rule is: roll to the next month, not the next
  year. Only visible because the tests pin a specific reference date — on the 5th of a
  month it passes silently.
- **Multi-night events silently lost a night.** The after-midnight roll compared full
  datetimes (`end <= start`). For `days=2`, the end is already a day ahead, so the roll
  never fired and a two-night booking resolved to the same window as a one-night
  booking. No test failed. The fix compares clock times (`end_t <= start_t`).

**Exercise:** change the reference date to a different weekday and watch how many tests
break. That tells you which ones were actually testing the logic.

### Sitting 4 — Tools, and the confirmation rule

**Goal:** understand the one guarantee the system makes.

- `app/tools/registry.py` — the `@tool` decorator, role filtering, and `execute()`.
  Note that roles are checked **twice**: the tool list sent to the model is filtered,
  and the tool re-checks at execution. The first is convenience; the second is the
  guard.
- `app/tools/customer.py` — the eight tools. Seven read. One writes.
- `app/assistant_domain/confirmation.py` — the token.

**The rule, and why it's in code:**

`prepare_booking` verifies everything and changes nothing, returning a
`confirmation_id` and an Arabic summary. `confirm_action` is the only tool that can
create a booking, and it refuses unless:

- the token exists and belongs to this session,
- it hasn't expired (10 min) and hasn't been used,
- **a new customer message arrived after `prepare`** — `current_user_turn >
  prepared_at_user_turn`,
- and availability still holds under the capacity lock.

`tests/test_agent_loop.py::test_user_turn_counts_customer_messages_not_tool_calls` is
the most important test in the repo. A turn making three tool calls is still one
customer message. If that ever drifts, the model could prepare and confirm without the
customer speaking, and the whole guarantee evaporates.

**Know the limit and say it before you're asked:** the code proves the customer was
*given a chance to reply*. It does not prove the reply was "yes". That's measured, not
guaranteed — see `confirmation_violations` in the eval. It's written down in
`docs/EVAL.md` §1.

Also in this sitting:

- **Rejections are data, not errors.** A business refusal is `{"ok": false, "error":
  "lead_time", ...}` and the model handles it — you'll see it recover from
  `unknown_package` in one round trip. `is_error: true` is reserved for genuine
  exceptions, and those run inside a `begin_nested()` savepoint so the tool's writes
  are undone while the audit row survives.

**Exercise:** find `tests/test_side_effects.py`. It snapshots every column of every
table and asserts that only `confirm_action` and `handoff_to_staff` change anything.
Patch a read-only tool to quietly rewrite a venue and watch it fail.

### Sitting 5 — Retrieval

**Goal:** know what the model is allowed to know.

- `kb/laqta-kb.md` — 19 sections, 14 public and 5 internal. Each carries an
  `audience` marker.
- `app/kb/chunker.py` — one `##` section per chunk, title prefixed into the indexed
  text. A section with no audience marker **raises** rather than defaulting to public.
- `app/kb/search.py` — the audience filter is a SQL `WHERE`, not a post-filter. An
  internal section is not a row a customer's query can rank, let alone read. An
  unrecognised role raises rather than getting public content.
- `app/config.py` — `KB_MIN_SCORE = 0.45`, with a long comment explaining that it was
  measured, not guessed: worst correct answer 0.484, best off-topic 0.428.

**The thing to be honest about:** that band is 0.056 wide on six negatives, and the
hardest one sits 0.002 under the ceiling. It will move.

**And the failure mode this creates**, which matters more: an internal-only question
doesn't come back empty. It comes back with three *public* sections above threshold, so
the model has plausible, wrong context in hand and answers from its own knowledge
instead of handing off. Documented in `docs/EVAL.md` §2 and measured as taxonomy item 1.

**Exercise:** `python -m scripts.try_kb`. Add three off-topic Arabic questions of your
own and see how close they land to 0.45.

### Sitting 6 — The loop and the prompt

**Goal:** the part that's actually an "agent".

- `app/agent/loop.py::run_turn` — ~30 lines. Written by hand rather than using the
  SDK's tool runner, because the role check, the logging, and the user-turn counter all
  hook into it.
- `app/agent/context.py` — the block injected each session: today's date in both
  calendars, who's speaking, their bookings, open tickets, last contact. **The model
  has no idea what day it is unless you tell it.** This is also where the booking id
  used to live, and why it doesn't any more (taxonomy 2).
- `app/agent/system_prompt.md` — read it alongside `docs/STATUS.md`'s status table.
- `app/tools/labels.py` — the Arabic label tables.

**The distinction that runs through this whole project:**

> Code-enforced rules hold. Prompt-only rules are requests.

`summary_ar` renders every enum in Arabic because a function generates it — 120
generated summaries are tested, and no English reaches a customer. "Don't use emoji" and
"use gender-neutral address" are prompt lines, and the eval measured **21 gender slips
in 73 replies**. Same document, same wording, completely different reliability.

That's the single most useful thing this codebase taught, and it's the answer to "what
would you do differently?"

### Sitting 7 — The evaluation

**Goal:** the part that makes any of the above a claim rather than an opinion.

- `eval/personas/*.yaml` — 31 personas, each with a goal and **hidden state the agent
  must ask for**. Their details deliberately differ from obvious defaults, so an agent
  that invents a field instead of asking gets it wrong.
- `eval/run.py` — drives episodes. Haiku plays the customer, Sonnet is the agent,
  running through the *real* `run_turn`. Every message, tool call, result and token
  count is logged to JSON.
- `eval/score.py` — deterministic checks first, then one Opus call per episode for
  what needs reading Arabic.
- `docs/EVAL.md` §7 — the failure taxonomy. Fourteen entries, each with the failure,
  the cause, what changed, how it's measured, and which personas provoke it.

Five design points worth being able to defend:

1. **Scripted provocations, and an episode where the provocation never fired is
   reported as `not_provoked`, never as passed.** Excluded from every rate.
2. **The judge is a different, more capable model** than the one under test.
3. **Every metric has a control that deliberately fails it.** Feed the grounding checker
   a known fabricated price and confirm it fires. A checker that never fires isn't
   measuring anything.
4. **Fingerprints.** The system prompt, tools, simulator prompt and judge instructions
   are all hashed and recorded with the run, so a rate belongs to a specific version.
5. **Three kinds of evidence are kept apart:** hand-observed (shows a failure exists),
   pilot at one episode per persona (direction only, never a rate), and the 10× run
   (the only source of rates).

**Exercise:** open the pilot at `eval/runs/pilot-20260913/scores.md` and read one
episode transcript end to end. Then read `docs/EVAL.md` §7.4 entry 8 and see how a
count of slips became a claim about *inference*.

---

## 2. The decisions, and the reasons

These are the ones you'll be asked to defend. Each is a sentence you should be able to
say cold, plus where the code is.

| Decision | Why | Where |
|---|---|---|
| Transition table as data | The legal set is readable in one screen; everything else is illegal by construction | `domain/booking_state.py` |
| `now` is always a parameter | Time-based rules testable to the second; fake clock possible later | all of `domain/`, enforced by `test_domain_purity` |
| Advisory locks, not `FOR UPDATE` | Row locks can't stop a *phantom insert* — the competing booking is a row that doesn't exist yet | `domain/capacity.py` |
| Optimistic locking, app-supplied counter | `apply()` is testable in memory with no session; a stale writer gets `StaleDataError` instead of silently overwriting | `models/booking.py`, `version_id_generator=False` |
| Structured intents, not dates | A plausible wrong date is indistinguishable from a right one | `assistant_domain/dates/` |
| Tools take `when_id`, never a date | Makes it impossible for a date to reach a booking without passing the resolver | `tools/customer.py` |
| One tool with side effects | Auditing "can this write?" is a one-line answer | `confirm_action` |
| Audience filter in SQL | Post-filtering means the row was still ranked and retrieved | `kb/search.py` |
| Adapter over the platform | The whole booking flow runs against `MockLaqta`; the real one is a thin HTTP layer | `laqta/adapter.py` |
| Domain layer kept portable | Booking rules are *platform* logic; they live here because Laqta has no booking concept yet | `docs/ARCHITECTURE.md`, `test_domain_portability` |

---

## 3. Things to be able to draw

On a whiteboard, from memory, in under two minutes each:

1. **The agent loop.** Six boxes. Where it exits, where the step cap is.
2. **The booking state machine.** Five states, the triggers between them, and the two
   transitions that are deliberately absent (`reschedule` from `live`, `window_open`
   from `tentative`).
3. **The prepare/confirm sequence**, with the user-turn counter on it.
4. **The eval pipeline.** Persona → runner → transcript + DB state → deterministic
   checks → judge → report.

---

## 4. Honest notes

**On authorship.** Most of this code was written by Claude Code under direction. What
was decided, reviewed, and rejected is the work, and it's defensible — but say so
plainly if asked, because the alternative is being caught. The date resolver and its 82
tests were hand-written, and that's the part to offer when someone wants to see you
write code.

**On the numbers.** Until the 10× run lands, every rate in `docs/EVAL.md` §7 is
directional — one episode per persona. Don't quote a percentage off a single sample.
The document says so in §7.1, and saying it out loud before someone asks is worth more
than the number.

**On what isn't built.** Layers 3 and 4 don't exist yet: no voice, and no follow-up
engine — the tickets the assistant creates sit in Postgres with `due_at` in the past
and nobody notified. The photographer customer flow is a known scope gap; today the
correct behaviour is a handoff. All recorded in `docs/STATUS.md` rather than
discovered by a reader.

---

## 5. If you're going to change something

Read `docs/STATUS.md` first, and pay attention to the three tiers: *fixed and enforced
in code*, *prompt-only and unverified*, and *open*. The second tier is where the
surprises are.

Then: run the pilot before you change anything, so you have a before. Change one thing.
Prove the change works by removing it and watching a specific test fail. Run the pilot
again. That's the loop this project runs on, and it's why the taxonomy has causes in it
rather than guesses.

---

## 6. Drill questions

Answer each out loud, without the code open. If one is shaky, the sitting to
reread is named.

1. How do you stop a language model from booking something the customer didn't agree
   to? — *Sitting 4*
2. How do you handle "الخميس الجاي" and "بعد العيد" reliably? — *Sitting 3*
3. Two customers try to take the last on-site slot in the same second. What happens,
   and why isn't `SELECT FOR UPDATE` enough? — *Sitting 2*
4. How do you keep internal policy out of a customer's answer? — *Sitting 5*
5. How do you know the agent works? What's the task success rate, and what fails? —
   *Sitting 7*
6. What's the difference between a bug you fixed in the prompt and one you fixed in
   code? — *Sitting 6, plus `STATUS.md`'s three tiers*
7. Tell me about a test that was wrong. — the capacity race test passed with the lock
   removed until a 0.2s delay was added; the fajr assertion sat in the wrong file and
   never ran at all
8. Tell me about a bug a test caught that you wouldn't have found. — "يوم ١٧" rolling
   a year instead of a month; multi-night events silently losing a night because the
   after-midnight check compared datetimes instead of clock times
9. What would you do differently? — the honest answers are: measure before fixing (the
   cosmetic fixes went in before the pilot had a baseline), and decide earlier which
   rules are code and which are prompt

**The shortest useful tour**, if someone gives you twenty minutes: `ARCHITECTURE.md`
for the seam, `agent/loop.py` for the loop, `dates/resolver.py` for the resolver,
`booking_state.py` for the transition table, `test_capacity_race.py` for the control
that makes a test load-bearing, and `EVAL.md` §7 for the taxonomy. Everything else
hangs off those six.
