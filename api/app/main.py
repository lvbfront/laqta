from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import photos
from app.storage import minio_client


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

# Routers land here as they're implemented:
# from app.api.routes import events, match, delivery, moderation
# app.include_router(events.router)
# app.include_router(match.router)
# app.include_router(delivery.router)
# app.include_router(moderation.router)
