# `assistant/server/` — the HTTP layer

A thin edge over `app.agent.loop.run_turn`. It adds four things the terminal
CLI did not need — sessions that survive a page reload, one turn at a time per
session, an answer per `client_message_id`, and a clock — and no business
logic whatsoever. Every rule about booking, dates, confirmation and retrieval
is in `app/`, reached through the same `run_turn` the CLI and the eval use.

## Run it

```bash
cd assistant && source .venv/bin/activate
pip install -r requirements.txt          # fastapi, uvicorn, httpx are new
export ANTHROPIC_API_KEY=sk-ant-...      # or assistant/.env
export ASSISTANT_DEV=1                   # identity picker, clock override, dev panel

python -m server.run                     # server + widget, one command
```

`python -m server.run` starts uvicorn on :8080 with `--warm` (so the first
knowledge-base question does not stall while BGE-M3 loads) and the widget's
Vite dev server on :5173. Either alone:

```bash
uvicorn server.app:create_app --factory --port 8080
cd web && npm run dev
```

## Endpoints

| | |
|---|---|
| `POST /chat/sessions` | `{ session_id, identity, now, turn, dev }`. `{identity, now}` in the body are read **only** under `ASSISTANT_DEV`. |
| `POST /chat/sessions/{id}/messages` | `{client_message_id, text}` → `{reply, reply_source, events, turn, replayed}` |
| `GET /chat/sessions/{id}` | the message history, so a reload restores the chat |
| `POST /chat/sessions/{id}/end` | ends it and writes the summary the next session reads as «آخر تواصل» |
| `GET /health` | status, dev flag, database name, live session count |

Errors are `{"error": {code, message_ar, retryable}}`. The widget shows
`message_ar`; `retryable: false` means offer a new conversation rather than a
retry button.

`reply_source` is `model`, or one of `loop_api_error` / `loop_refusal` /
`loop_fallback` / `model_truncated`. The last four are sentences the loop
wrote, not the model, and the widget must not present them as the assistant's
own words.

## Things to know before you rely on it

**Single process, in memory.** `AgentSession` holds the message list, the
customer-turn counter the confirmation rule depends on, and the resolved-date
store, and none of it is written anywhere. **Restart the server and every open
conversation is gone**, along with its idempotency records. The `interactions`
row and its transcript survive; the session cannot be rebuilt from them.
That also means one process only: a second worker would not share the
sessions dict or the locks. `python -m server.run` starts one, without
`--reload`, deliberately.

**A conversation holds a database connection** for as long as it is open,
because `AgentSession.interaction` is an ORM object bound to its Session. The
pool is sized from `ASSISTANT_MAX_SESSIONS`; past that, new sessions are
refused rather than queued.

**Laqta is hydrated once, at startup.** `SharedLaqta` builds one `MockLaqta`
when the process starts and rebuilds its event map from the `bookings` table
at that moment. It is shared by every session, so two browser tabs see each
other's bookings — but **anything written by another process while the server
is running is invisible to it until restart**. A booking made in
`python -m app.cli.chat`, or by a script, or by a second server, is a
`LaqtaNotFound` here even though the row is plainly in Postgres. If you have
been using the CLI, restart the server. This goes away when `MockLaqta` is
replaced by the real HTTP adapter, which has no local copy to go stale.

**Idle sessions are ended, not dropped.** After `ASSISTANT_SESSION_IDLE_SECONDS`
they go out through the same path as `/end`, so an abandoned conversation
still writes its summary. The sweep runs when a new session is created, so an
idle server does nothing until someone arrives.

## `ASSISTANT_DEV`

Off by default, and there is no half-on. With it off:

- the request's `identity` is **not read at all** — not validated and
  rejected, never passed to `DevAuth`. Every session is anonymous.
- the request's `now` is not read; the clock is real.
- `events` comes back `{}` and `context_block` comes back `null`. A
  customer's browser has no business holding tool arguments or a context
  block naming their bookings.

With it on, the client may pick `anon` / `customer:<id>` / `staff:<id>` and a
starting date, and gets the dev panel's payload per turn: tool calls with
arguments and results, confirmation tokens and their state, resolved
`when_id`s, the user-turn counter, per-step stop reasons and latencies, and
token counts.

`DevAuth` is *chosen* identity, not proven — that is what its docstring says
and why it is behind a flag.

### What the dev panel cannot show

Listed rather than invented. The loop does not expose them and nothing in
`app/` was changed to make it:

- **thinking blocks** — they are in `session.messages`, and showing the
  model's reasoning is a different decision from showing it tool calls;
- **which step a tool call belongs to** — `tool_calls` records `user_turn`,
  not the step within the turn, so calls are listed per turn;
- **why a tool was chosen** — nothing records it;
- **streaming** — `messages.create` is called without `stream=True` and the
  reply is assembled only after the loop finishes. Hence a typing indicator
  and no token-by-token output.

## The clock

The HTTP edge is the only place in the service that reads the real clock;
everything under `app/` takes `now` as a parameter, and an AST test enforces
that for the domain packages.

A dev `now` sets where a session **starts**, not a frozen instant: each turn
gets `override + elapsed wall time`. Freezing it would also switch off the
ten-minute confirmation TTL, so a demo of Hijri and relative dates would
quietly be a demo with one of the guards not running.

## Database

`ASSISTANT_DATABASE_URL`, default `assistant`. The server **refuses to start**
against `assistant_test` (dropped by every pytest run) or `assistant_eval`
(truncated between eval episodes). It is a denylist rather than an allowlist:
running two assistants side by side against a third database name is
legitimate, and refusing everything unfamiliar only teaches people to edit the
check.

## Settings

All `ASSISTANT_`-prefixed, read from the environment or `assistant/.env`.

| | default | |
|---|---|---|
| `ASSISTANT_DEV` | `false` | identity picker, clock override, dev panel |
| `ASSISTANT_CORS_ORIGINS` | the Vite dev origins | comma-separated allowlist, never `*` |
| `ASSISTANT_MAX_MESSAGE_CHARS` | `2000` | refused at the edge, before the model is called |
| `ASSISTANT_MAX_SESSIONS` | `100` | also sizes the connection pool |
| `ASSISTANT_SESSION_IDLE_SECONDS` | `1800` | then ended and summarised |
| `ASSISTANT_WARM_KB` | `false` | load BGE-M3 at startup instead of on the first question |

## Tests

```bash
pytest server                # this layer
pytest                       # everything; `testpaths = tests server`
```

No test calls a real model — they all pass a scripted client through
`run_turn(client=...)`, the same seam the eval uses.

The server tests do **not** use the suite's `db_session` fixture. It wraps a
test in a transaction and rolls it back, which is right for code handed a
Session and useless against code that opens its own connections and commits.
They truncate and re-seed around each test instead, as `eval/database.py` does
between episodes.
