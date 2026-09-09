from __future__ import annotations

from functools import lru_cache

from redis import Redis
from rq import Queue

from app.config import settings

PHOTO_PROCESSING_QUEUE = "photo_processing"
PURGE_QUEUE = "purge"


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(settings.redis_url)


def get_photo_processing_queue() -> Queue:
    return Queue(PHOTO_PROCESSING_QUEUE, connection=get_redis())


def get_purge_queue() -> Queue:
    return Queue(PURGE_QUEUE, connection=get_redis())
