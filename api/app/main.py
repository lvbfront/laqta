from fastapi import FastAPI

app = FastAPI(
    title="Laqta API",
    description="Event photo delivery platform — core matching loop (Phase 1).",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Routers are mounted here as they're implemented:
# from app.api.routes import events, photos, match, delivery, moderation
# app.include_router(events.router)
# app.include_router(photos.router)
# app.include_router(match.router)
# app.include_router(delivery.router)
# app.include_router(moderation.router)
