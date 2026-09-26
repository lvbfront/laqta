"""The FastAPI application.

Same framework as the Laqta API (api/app/main.py), same pins. CORS is an
allowlist from the environment rather than the `*` the Laqta API still
carries in dev — the note there says to tighten it before it leaves
localhost, and there is no reason to start loose here.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_policy, settings
from server import errors
from server.config import ServerSettings, get_server_settings, require_a_usable_database
from server.db import make_engine, make_session_factory
from server.laqta import SharedLaqta
from server.routes import chat
from server.store import SessionStore

log = logging.getLogger("server")


def create_app(
    *,
    server_settings: ServerSettings | None = None,
    database_url: str | None = None,
    model_client=None,
) -> FastAPI:
    config = server_settings or get_server_settings()
    url = database_url or settings.database_url
    # Before anything else: assistant_test is dropped by every pytest run and
    # assistant_eval is truncated between episodes.
    require_a_usable_database(url)

    engine = make_engine(max_sessions=config.max_sessions, url=url)
    session_factory = make_session_factory(engine)

    with session_factory() as db:
        # One hydrated adapter for the process. See server/laqta.py.
        laqta = SharedLaqta.seeded(db)

    if config.warm_kb:
        from app.kb.embedder import model

        log.info("loading the embedding model…")
        model()

    app = FastAPI(title="Laqta assistant", version="0.1.0")
    app.state.server_settings = config
    app.state.engine = engine
    app.state.store = SessionStore(
        session_factory=session_factory,
        policy=get_policy(),
        laqta=laqta,
        max_sessions=config.max_sessions,
        idle_seconds=config.session_idle_seconds,
        model_client=model_client,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )

    @app.exception_handler(errors.ChatError)
    def _chat_error(_request: Request, exc: errors.ChatError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body())

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "dev": config.dev,
            "database": require_a_usable_database(url),
            "sessions": len(app.state.store),
        }

    app.include_router(chat.router)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        app.state.store.close_all()
        engine.dispose()

    return app
