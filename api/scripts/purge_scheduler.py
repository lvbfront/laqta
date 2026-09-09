#!/usr/bin/env python3
"""Long-running loop: enqueue a purge run immediately, then every
PURGE_INTERVAL_SECONDS thereafter, forever. This is the process that
actually makes retention enforcement happen on its own -- without it,
app.workers.purge.run_purge() only ever executes when a human remembers
to invoke it (scripts/purge.py, or enqueuing the RQ job by hand), which
isn't a retention guarantee at all.

Enqueues onto the 'purge' RQ queue (already consumed by the `worker`
service's `rq worker ... purge` command, see docker-compose.yml) rather
than calling run_purge() directly, so the actual deletion work happens in
the same place all other background work does.

This is an interval loop, not wall-clock cron: the time of day it fires
drifts with container restarts. Acceptable for Phase 1 (see the README's
"Purge job" section); swap for rq-scheduler's .cron() or real cron if
wall-clock-fixed timing matters later -- app.workers.purge.run_purge
itself doesn't change either way.

Usage:
    python scripts/purge_scheduler.py
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.workers.jobs import purge_expired_data  # noqa: E402
from app.workers.queue import get_purge_queue  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("purge_scheduler")


def main() -> None:
    interval = settings.purge_interval_seconds
    logger.info("purge scheduler starting -- enqueueing every %ss", interval)
    queue = get_purge_queue()
    while True:
        try:
            job = queue.enqueue(purge_expired_data)
            logger.info("enqueued purge_expired_data (job id %s)", job.id)
        except Exception:
            logger.exception("failed to enqueue purge_expired_data")
        time.sleep(interval)


if __name__ == "__main__":
    main()
