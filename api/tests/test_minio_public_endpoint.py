"""presigned_get_url must sign against settings.minio_public_endpoint, not
settings.minio_endpoint, when the two differ -- the internal docker
compose service hostname ("minio:9000") only resolves on the docker
compose network, so a URL signed for it is unfetchable by any real
browser (confirmed by hand: broken thumbnails on a phone on the same
LAN, fixed by adding this distinction). Regression coverage for that.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.storage import minio_client


def test_presigned_url_uses_the_public_endpoint_when_set(monkeypatch):
    monkeypatch.setattr(minio_client.settings, "minio_endpoint", "minio:9000")
    monkeypatch.setattr(minio_client.settings, "minio_public_endpoint", "203.0.113.5:9000")
    minio_client.get_public_client.cache_clear()

    url = minio_client.presigned_get_url("events/e/photos/p/thumbnail.jpg", 300)

    assert urlparse(url).netloc == "203.0.113.5:9000"
    minio_client.get_public_client.cache_clear()


def test_presigned_url_falls_back_to_minio_endpoint_when_public_endpoint_unset(monkeypatch):
    monkeypatch.setattr(minio_client.settings, "minio_endpoint", "localhost:9000")
    monkeypatch.setattr(minio_client.settings, "minio_public_endpoint", "")
    minio_client.get_public_client.cache_clear()

    url = minio_client.presigned_get_url("events/e/photos/p/thumbnail.jpg", 300)

    assert urlparse(url).netloc == "localhost:9000"
    minio_client.get_public_client.cache_clear()


def test_upload_and_download_still_use_the_internal_endpoint(monkeypatch):
    """The internal client (get_client, used by upload_bytes/download_bytes
    -- calls made from inside the api/worker containers) must keep using
    minio_endpoint regardless of minio_public_endpoint -- only the
    browser-facing presigned URL needs the public host.
    """
    monkeypatch.setattr(minio_client.settings, "minio_endpoint", "minio:9000")
    monkeypatch.setattr(minio_client.settings, "minio_public_endpoint", "203.0.113.5:9000")
    minio_client.get_client.cache_clear()

    client = minio_client.get_client()

    assert client.meta.endpoint_url == "http://minio:9000"
    minio_client.get_client.cache_clear()
