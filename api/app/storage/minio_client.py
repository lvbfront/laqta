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
