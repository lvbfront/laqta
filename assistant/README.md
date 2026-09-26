# assistant — مساعد لقطة

Text assistant that books Laqta activation windows, answers from the knowledge
base, and hands off to staff. The spec is `layer1-spec.md`; it wins over this
file.

**Every command here runs from `assistant/`, with the venv active.** That is
the shell mistake to avoid: the repo root is Laqta's, this directory is the
assistant's, and they have separate databases and separate dependencies.

## 1. Postgres

Postgres lives in the repo-root compose stack and is published on host port
**5433**, not 5432:

```bash
cd ..                          # repo root
docker compose up -d postgres
```

Create the two databases once (the `vector` extension is enabled by the
migration, per database):

```bash
docker compose exec postgres createdb -U laqta assistant
docker compose exec postgres createdb -U laqta assistant_test
```

## 2. Venv

```bash
cd assistant
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Migrations

```bash
alembic upgrade head
alembic revision --autogenerate -m "what changed"
```

Autogenerate output always needs a read before committing: it does not emit
the `pgvector` import or `CREATE EXTENSION`, and it re-emits `CREATE TYPE` for
an enum that several tables share. See the initial migration's docstring.

## 4. Seed

```bash
python -m scripts.seed           # idempotent: safe to run repeatedly
python -m scripts.seed --reset   # wipe the CRM tables first, then seed
```

Prints the `--as customer:N` handle for each seeded organizer.

## 5. Index the knowledge base

```bash
python -m scripts.index_kb
```

Reads `kb/laqta-kb.md`, one chunk per `## ` section, and embeds them with
BGE-M3. The first run downloads the model (~2GB, cached in
`~/.cache/huggingface`); later runs are offline. Safe to repeat: chunks are
keyed by content hash, so an unchanged file embeds nothing, and a section
deleted from the file loses its row.

## 6. Tests

```bash
pytest                  # everything
pytest -m "not kb"      # skip the one module that loads the embedding model
```

`assistant_test` is created, wiped and migrated by the test session itself —
it never touches `assistant` or any Laqta database. Tests marked `llm` hit the
real Anthropic API and are deselected by default; run them with
`pytest -m llm`.

## 7. Talk to it

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # or an `ant auth login` profile
python -m app.cli.chat --as customer:1   # a signed-in organizer
python -m app.cli.chat --as anon         # a visitor who cannot book
python -m app.cli.chat --as customer:1 --now 2026-09-11T14:05   # fixed clock
```

In-conversation commands: `/debug` traces every tool call and result, `/ctx`
prints the context block, `/end` writes the session summary, `/quit` leaves
without one.

Staff actions that have no tool yet:

```bash
python -m app.cli.admin mark-paid <booking_id>   # tentative → confirmed
python -m app.cli.admin show <booking_id>        # status and full history
```

The API key is only needed for the conversation loop and the `llm`-marked
tests. Everything else — migrations, seed, indexing, the whole default test
suite — runs without one.

## Docs

- `docs/ARCHITECTURE.md` — which modules are platform logic versus assistant
  logic, why the platform ones live here today, and what moving them into the
  Laqta API would involve.
- `docs/EVAL.md` — known limits the code cannot enforce, for the layer-2 eval
  to measure: the edge of the confirmation guarantee, two recorded retrieval
  cases, and how `KB_MIN_SCORE` was derived.

## Configuration

- `policy.yaml` — every operational number (lead times, capacity, packages,
  refunds). Nothing in it is overridable from the environment.
- Environment variables are prefixed `ASSISTANT_`, e.g.
  `ASSISTANT_DATABASE_URL`, `ASSISTANT_TEST_DATABASE_URL`. Laqta's own
  `DATABASE_URL` is deliberately ignored, so a shell set up for Laqta cannot
  point the assistant at Laqta's database.
