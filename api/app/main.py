from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.formparsers import MultiPartParser

from app.api.routes import delivery, match, photos
from app.config import settings
from app.storage import minio_client

# Starlette's default multipart spool threshold is 1MB per part -- smaller
# than a typical phone selfie or event photo, which would then silently
# spill to a real temp file on disk (SpooledTemporaryFile.rollover) before
# any of our own code runs. Confirmed empirically during development: a
# 2MB upload triggers a real rollover under the default. This is what
# actually keeps CLAUDE.md's "the selfie never touches disk" true for a
# realistic upload -- not just that our own route code never calls open().
MultiPartParser.max_file_size = settings.max_upload_spool_bytes
MultiPartParser.max_part_size = settings.max_upload_spool_bytes


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    minio_client.ensure_bucket()
    yield


app = FastAPI(
    title="Laqta API",
    description="Event photo delivery platform — core matching loop (Phase 1).",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(photos.router)
app.include_router(match.router)
app.include_router(delivery.router)

# Routers land here as they're implemented:
# from app.api.routes import events, moderation
# app.include_router(events.router)
# app.include_router(moderation.router)
