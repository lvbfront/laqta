import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.formparsers import MultiPartParser

from app.api.routes import auth, delivery, events, match, photos
from app.config import settings
from app.storage import minio_client

# pyvips logs every operation call and every property get/set at DEBUG
# level, including the *raw image buffer bytes themselves* (found while
# testing app/api/routes/match.py's "selfie never touches disk/MinIO/logs"
# guarantee: turning on root-level DEBUG logging to inspect that test's
# own log output flooded caplog with the selfie's raw JPEG bytes via
# pyvips.vobject's "VipsObject.set: name = buffer, value = b'...'"). This
# has nothing to do with our own logging code being careful -- it's a
# third-party library default that would leak selfie bytes into logs the
# moment anyone enables DEBUG logging process-wide (a normal thing to do
# while troubleshooting something unrelated). Pinned above WARNING
# unconditionally, independent of whatever level the root/app logger is
# set to.
logging.getLogger("pyvips").setLevel(logging.WARNING)

# Starlette's default multipart spool threshold is 1MB per part -- smaller
# than a typical phone selfie or event photo, which would then silently
# spill to a real temp file on disk (SpooledTemporaryFile.rollover) before
# any of our own code runs. Confirmed empirically during development: a
# 2MB upload triggers a real rollover under the default. This is what
# actually keeps CLAUDE.md's "the selfie never touches disk" true for a
# realistic upload -- not just that our own route code never calls open().
#
# This is a memory/disk-risk tradeoff, not a free fix: every part of every
# multipart request (ingest's event photos too, not just selfies) now
# stays in RAM up to MAX_UPLOAD_SPOOL_BYTES before Starlette would even
# consider spilling to disk. There is currently no request/part size limit
# anywhere upstream of this -- nothing rejects a deliberately huge upload
# before it reaches this buffer. A burst of large concurrent uploads could
# therefore pressure memory well before disk was ever the risk being
# guarded against. Before production: add an actual max-request-size
# check (e.g. reject on Content-Length, or a request-body-size ASGI
# middleware) ahead of this. If you're tuning MAX_UPLOAD_SPOOL_BYTES later
# for that reason, know that lowering it re-opens the selfie-on-disk gap
# tests/test_selfie_never_persisted.py exists to catch -- that test uses a
# ~1.3MB fixture specifically to stay under whatever this is set to; if
# this drops below that, the test (correctly) starts failing.
#
# This depends on the exact attribute names on the exact Starlette version
# requirements.txt pins (0.41.3, via fastapi==0.115.6) -- confirmed by
# hand: a newer Starlette (1.x) renames max_file_size to spool_max_size,
# which would make this assignment a silent no-op (it'd just set an
# unused attribute) and quietly reopen the disk-spill gap with no error
# anywhere -- exactly the failure mode this whole patch exists to prevent.
# Asserting the attributes exist turns a version bump that renames them
# into a loud ImportError at startup instead.
assert hasattr(MultiPartParser, "max_file_size"), (
    "starlette.formparsers.MultiPartParser.max_file_size not found -- this Starlette "
    "version likely renamed/removed the multipart spool-threshold attribute this patch "
    "sets. Re-verify against the new version (see this comment) before proceeding: "
    "an unnoticed rename here silently reopens the 'selfie never touches disk' gap."
)
assert hasattr(MultiPartParser, "max_part_size")
MultiPartParser.max_file_size = settings.max_upload_spool_bytes
MultiPartParser.max_part_size = settings.max_upload_spool_bytes


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    minio_client.ensure_bucket()
    yield


app = FastAPI(
    title="Laqta API",
    description="Event photo delivery platform.",
    version="0.2.0",
    lifespan=lifespan,
)

# The Next.js dev server runs natively on the host (not in Docker, see
# CLAUDE.md), on a different origin/port than the API -- browser requests
# from it are cross-origin. Auth is bearer-token-in-header (Authorization),
# not cookies, specifically so a wildcard origin here doesn't also imply
# CSRF exposure the way it would with cookie-based credentials -- a
# malicious page on another origin can't attach a token it was never
# given. Still dev-only permissiveness, though: tighten to an explicit
# origin allowlist before this is ever exposed beyond localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(photos.router)
app.include_router(match.router)
app.include_router(delivery.router)
app.include_router(events.router)

# Routers land here as they're implemented:
# from app.api.routes import moderation
# app.include_router(moderation.router)
