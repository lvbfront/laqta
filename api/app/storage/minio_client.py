from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config import settings


@lru_cache
def get_client():
    scheme = "https" if settings.minio_secure else "http"
    return boto3.client(
        "s3",
        endpoint_url=f"{scheme}://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )


@lru_cache
def get_public_client():
    """Same credentials, a different endpoint_url -- used only for
    presigned_get_url(). A presigned URL is fetched directly by a guest's
    or organizer's browser, which can't resolve settings.minio_endpoint
    when that's docker-compose's internal service hostname ("minio:9000")
    -- confirmed by hand: a phone on the same LAN got broken-image icons
    for every thumbnail because the signed URL pointed at that
    unresolvable-outside-Docker host. SigV4 signs the host as part of the
    signature, so the URL has to be *signed* for whatever host the
    browser will actually connect to, not just have its host swapped
    after the fact -- hence a whole separate client rather than a
    string-replace on the returned URL. settings.minio_public_endpoint
    defaults to empty, which falls back to settings.minio_endpoint (the
    common case: tests, and a real deployment where internal/external
    endpoints are the same hostname).
    """
    scheme = "https" if settings.minio_secure else "http"
    endpoint = settings.minio_public_endpoint or settings.minio_endpoint
    return boto3.client(
        "s3",
        endpoint_url=f"{scheme}://{endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )


def ensure_bucket() -> None:
    client = get_client()
    try:
        client.head_bucket(Bucket=settings.minio_bucket)
    except ClientError as exc:
        status = exc.response.get("Error", {}).get("Code")
        if status not in ("404", "NoSuchBucket"):
            raise
        client.create_bucket(Bucket=settings.minio_bucket)


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    get_client().put_object(
        Bucket=settings.minio_bucket, Key=key, Body=data, ContentType=content_type
    )


def download_bytes(key: str) -> bytes:
    response = get_client().get_object(Bucket=settings.minio_bucket, Key=key)
    return response["Body"].read()


def presigned_get_url(
    key: str, expires_in_seconds: int, *, download_filename: str | None = None
) -> str:
    """Short-TTL signed URL for direct guest download from MinIO/S3 -- the
    API never proxies the bytes itself. Access control happens before this
    is ever called (app.api.routes.delivery checks the guest has an actual
    Match to the photo); the signature only bounds *how long* the URL
    works, not *who* it works for.

    `download_filename`, when given, signs a Content-Disposition: attachment
    header into the URL so the browser actually downloads the file instead
    of navigating to it inline -- pass it for a guest's "download my photo"
    action, leave it unset for an <img> preview src.
    """
    params: dict[str, str] = {"Bucket": settings.minio_bucket, "Key": key}
    if download_filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{download_filename}"'
    return get_public_client().generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in_seconds)


def delete_objects(keys: list[str]) -> list[str]:
    """Best-effort batch delete. Returns the keys that failed (empty if
    everything succeeded) -- callers that must not lose track of an
    object (see app/workers/purge.py) should treat a non-empty result as
    "don't delete the DB row that pointed at this yet". S3/MinIO delete is
    idempotent: re-deleting an already-gone key is not an error, so
    retrying a partial failure with the same key list is always safe.
    """
    if not keys:
        return []
    client = get_client()
    failed: list[str] = []
    for i in range(0, len(keys), 1000):  # DeleteObjects caps at 1000 keys/request
        batch = keys[i : i + 1000]
        response = client.delete_objects(
            Bucket=settings.minio_bucket,
            Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
        )
        failed.extend(err["Key"] for err in response.get("Errors", []))
    return failed


def derived_key(original_key: str, name: str) -> str:
    """Derive a sibling object key from an original's key, e.g.
    'events/<event_id>/photos/<photo_id>/original.jpg' ->
    'events/<event_id>/photos/<photo_id>/<name>.jpg'. Thumbnail/preview
    keys are always derived this way rather than stored independently, so
    the convention only needs to be defined once (here) and followed by
    both the ingest path that writes originals and the worker that writes
    derivatives.
    """
    directory = original_key.rsplit("/", 1)[0]
    return f"{directory}/{name}.jpg"
