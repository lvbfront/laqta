from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central app configuration, populated from environment variables / .env.

    See .env.example at the repo root for the full list and defaults used
    in local development via docker compose.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Database ---
    database_url: str = "postgresql+psycopg://laqta:laqta_dev_password@localhost:5432/laqta"

    # --- Redis / queue ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Object storage (MinIO in dev, S3-compatible in prod) ---
    minio_endpoint: str = "localhost:9000"
    # The host a browser can actually resolve, for presigned URLs only
    # (see app/storage/minio_client.py's get_public_client) -- distinct
    # from minio_endpoint because that's the docker-compose *internal*
    # service hostname ("minio:9000"), meaningless outside the Docker
    # network. Empty (the default) falls back to minio_endpoint.
    minio_public_endpoint: str = ""
    minio_access_key: str = "laqta"
    minio_secret_key: str = "laqta_dev_password"
    minio_bucket: str = "laqta-photos"
    minio_secure: bool = False
    signed_url_ttl_seconds: int = 300
    # How often scripts/purge_scheduler.py enqueues a purge run. This is an
    # interval loop (run once at start, then every N seconds), not
    # wall-clock cron -- the time of day it fires drifts with container
    # restarts. Default 86400 (daily). See docker-compose.yml's
    # purge-scheduler service and the README's "Purge job" section.
    purge_interval_seconds: int = 86400

    # --- Matching / face pipeline ---
    match_threshold: float = 0.38
    guest_face_retention_days: int = 30
    face_model_pack: str = "buffalo_l"
    onnxruntime_provider: str = "CPUExecutionProvider"
    min_face_bbox_px: int = 40
    min_det_score: float = 0.5
    # Variance of the Laplacian of the detected face crop; below this, the
    # selfie is rejected as too blurry to embed reliably. 100 is a common
    # starting heuristic for this metric -- expect to retune against real
    # selfies (see MATCH_THRESHOLD tuning notes in the README).
    min_blur_variance: float = 100.0
    # Multipart parts above this are rejected outright (413) -- a real
    # selfie is never this large, and it bounds max_upload_spool_bytes below.
    max_selfie_upload_bytes: int = 8 * 1024 * 1024
    # Starlette's multipart parser spools each part in memory only up to
    # this size before spilling to a real temp file on disk. Its default
    # (1MB) is smaller than a typical phone selfie/event photo, which would
    # silently violate "the selfie never touches disk" for any normal
    # upload. Must stay above max_selfie_upload_bytes (see app/main.py,
    # where this is applied) and above a realistic event-photo size.
    max_upload_spool_bytes: int = 20 * 1024 * 1024

    # --- FTPS ingest (per-event credentials, see docs/plan.md) ---
    # 2121/explicit-TLS by default -- a nonprivileged port an unprivileged
    # container user can bind. docs/plan.md also allows 990/implicit; a
    # real deployment fronts this with 21 or 990 via the platform's port
    # mapping, not by changing what the process itself binds to.
    ftps_host: str = "0.0.0.0"
    ftps_port: int = 2121
    ftps_passive_port_start: int = 30000
    ftps_passive_port_end: int = 30009
    # Set when the server is reachable behind NAT/Docker port-forwarding
    # under a different address than it binds to -- passive mode sends
    # this address to the client in response to PASV, otherwise the
    # client tries to open a data connection to the container's internal
    # IP and hangs. Empty = pyftpdlib uses the control connection's own
    # local address (correct for local/dev, where there's no NAT hop).
    ftps_masquerade_address: str = ""
    # Self-signed dev cert, generated on first server start if missing --
    # see app/ftps/server.py. A real deployment points these at a real
    # cert/key pair instead.
    ftps_cert_file: str = "/tmp/laqta-ftps/cert.pem"
    ftps_key_file: str = "/tmp/laqta-ftps/key.pem"
    # Scratch directory files land in transiently during an FTPS upload --
    # FTP's STOR has to write to a real filesystem path; each file is read
    # back and handed to app.services.ingest.ingest_photo, then deleted,
    # in app.ftps.handler.on_file_received. Not the same guarantee as
    # CLAUDE.md's "selfie never touches disk" rule (that's selfies only --
    # event photos are meant to persist, just in MinIO, not here), but
    # still cleaned up immediately rather than left to accumulate.
    ftps_upload_root: str = "/tmp/laqta-ftps/uploads"

    # --- Desktop watch-folder agent pairing (agent/, see docs) ---
    # Deliberately short -- a photographer reads this off a screen once
    # and types it into the agent within a few minutes; a long TTL just
    # widens the window for a code shown on a shared/public dashboard
    # screen to be used by the wrong person.
    agent_pairing_code_ttl_minutes: int = 15


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
