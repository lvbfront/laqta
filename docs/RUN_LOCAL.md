# Run everything locally

Everything is served on `http://localhost`. Verified on this Mac (Apple Silicon, macOS 26.5.1, Docker 29.6) on 2026-10-06. All commands run from the repo root unless a `cd` says otherwise.

| Service | URL / port | Runs in |
|---|---|---|
| API (FastAPI) | http://localhost:8000 (`/health`) | Docker `api` |
| Face worker (RQ + InsightFace buffalo_l) | n/a | Docker `worker` |
| Postgres 16 + pgvector | localhost:**5433** (5432 is taken by a native Postgres on this Mac) | Docker `postgres` |
| Redis | localhost:6379 | Docker `redis` |
| MinIO | http://localhost:9000 (console :9001) | Docker `minio` |
| FTPS ingest, purge scheduler | :2121 / n/a | Docker `ftps`, `purge-scheduler` |
| Web (Next.js) | http://localhost:3000 | host (`npm run dev`) |
| laqta_agent | n/a | host (Python venv) |

## 0. Prerequisites (once)

Docker Desktop (arm64), `python3.11`, Node 18+, and `ffmpeg` (only needed by `scripts/e2e_smoke`).

## 1. Config (once)

```bash
cp .env.example .env
```

In `.env`, set these two values:

```
POSTGRES_PORT=5433                       # a native Postgres already owns 5432 on this Mac
MINIO_PUBLIC_ENDPOINT=localhost:9000     # host the browser loads photo URLs from
```

`MINIO_PUBLIC_ENDPOINT` must be an address the guest's browser can reach. `localhost:9000` only works for a browser on this Mac. A phone on the same Wi-Fi or hotspot needs the Mac's current IP; see docs/CAMERA_DAY.md. A stale IP here gives broken images in the guest gallery and no other error.

```bash
cp web/.env.local.example web/.env.local     # NEXT_PUBLIC_API_URL=http://localhost:8000
```

## 2. Backend services

```bash
open -a Docker                 # wait until `docker info` succeeds
docker compose up -d --build   # postgres, redis, minio, api, worker, ftps, purge-scheduler
docker compose exec -T api alembic upgrade head
curl http://localhost:8000/health    # {"status":"ok"}
```

The first photo processed after a fresh volume downloads the buffalo_l model pack (~300 MB) into the `insightface_models` volume.

After editing anything under `api/app/services/ingest.py`, `api/app/workers/` or `api/app/ftps/`, run `docker compose restart worker ftps`. Only `api` hot-reloads.

## 3. Web

```bash
cd web && npm install && npm run dev     # http://localhost:3000
```

`NEXT_PUBLIC_*` values are read at startup, so restart `npm run dev` after editing `web/.env.local`.

## 4. laqta_agent

```bash
cd agent
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

You can run the agent two ways:

- **GUI** (what a photographer uses). It asks for a pairing code and a folder:
  ```bash
  LAQTA_API_URL=http://localhost:8000 .venv/bin/python -m laqta_agent.main
  ```
  Get a pairing code from the dashboard event card ("Pair camera agent").
- **Headless** (same watcher, queue and uploader; no window, no keychain):
  ```bash
  LAQTA_API_URL=http://localhost:8000 .venv/bin/python -m laqta_agent.headless \
      --folder ~/Pictures/laqta-inbox --queue-db ~/Pictures/laqta-queue.sqlite3 --pair-code ABC123
  # prints: PAIRED event=... token=...   -- after a restart, pass --token <token> instead of --pair-code
  ```

## 5. Health check

```bash
scripts/health_check
```

This checks every container, Postgres (pgvector, migrations at head), Redis, and MinIO. It checks that the API and the worker can each reach Postgres, Redis and the bucket, that the buffalo_l model files are present, that the web server is up, that the web's API URL and the presigned-image host are reachable, and that the agent can import and reach the API. The exit code is the number of failed checks. A missing agent *process* is only a WARN.

## 6. End-to-end smoke test (no camera)

```bash
python3.11 -m venv scripts/.venv
scripts/.venv/bin/pip install playwright && scripts/.venv/bin/python -m playwright install chromium
scripts/.venv/bin/python scripts/e2e_smoke
```

The test:
1. Creates an event.
2. Drops a 6-face photo and a photo with nobody in it into the folder the headless agent watches.
3. Waits for upload and processing.
4. Takes a selfie through `/e/<qr_token>` in headless Chromium, with the camera fed from an image file, and asserts the photo comes back and renders.
5. Asserts the empty photo never matches and a stranger gets zero matches.

It ends with `E2E SMOKE: PASS`, or exits non-zero with a `FAIL:` line.

## 7. Tests

```bash
cd agent && .venv/bin/python -m pytest tests -q          # 32 tests, ~50 s (real folder-watch scenarios)
# API suite, inside the container (133 tests, ~30 s). Stop the worker first: the tests
# share Redis with it, and test_upload_creates_pending_photo_and_enqueues_job fails if the
# live worker takes its job first.
docker compose stop worker
docker compose exec -T -e TEST_DATABASE_URL=postgresql+psycopg://laqta:laqta_dev_password@postgres:5432/laqta_test \
    api python -m pytest tests -q
docker compose start worker
```

## Stop

```bash
docker compose down        # keeps data volumes; `down -v` wipes DB, photos and model cache
pkill -f "next dev"
```
