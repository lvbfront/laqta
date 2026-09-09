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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
