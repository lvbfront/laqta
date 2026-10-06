"""The agent without the tkinter window: the same FolderWatcher,
UploadQueue, Uploader and ApiClient that gui.AgentApp wires together, for
scripts (scripts/e2e_smoke) and terminal use on camera day. The token is
kept in memory only -- pass it back with --token after a restart instead
of touching the real keychain entry the GUI app uses.

    LAQTA_API_URL=http://localhost:8000 python -m laqta_agent.headless \
        --folder ~/Pictures/laqta-inbox --queue-db /tmp/q.sqlite3 --pair-code ABC123
"""
from __future__ import annotations

import argparse
import signal
import socket
import threading
from pathlib import Path

from laqta_agent.api_client import ApiClient
from laqta_agent.queue_db import UploadQueue
from laqta_agent.uploader import Uploader
from laqta_agent.watcher import FolderWatcher


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--queue-db", type=Path, required=True)
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument("--pair-code")
    auth.add_argument("--token")
    args = parser.parse_args()

    client = ApiClient()
    token = args.token
    if token is None:
        token, event_id = client.pair(args.pair_code, socket.gethostname())
        print(f"PAIRED event={event_id} token={token}", flush=True)

    queue = UploadQueue(args.queue_db)
    watcher = FolderWatcher(args.folder, queue)
    uploader = Uploader(queue, client, lambda: token)
    watcher.start()
    uploader.start()
    print(f"WATCHING {args.folder}", flush=True)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait()
    watcher.stop()
    uploader.stop()
    queue.close()


if __name__ == "__main__":
    main()
