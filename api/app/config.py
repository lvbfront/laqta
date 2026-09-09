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

    # --- Matching / face pipeline ---
    match_threshold: float = 0.38
    guest_face_retention_days: int = 30
    face_model_pack: str = "buffalo_l"
    onnxruntime_provider: str = "CPUExecutionProvider"
    min_face_bbox_px: int = 40
    min_det_score: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
