"""Server and widget, one command.

    python -m server.run

One uvicorn process, no --reload: sessions live in that process's memory, and
a reloader restarting it mid-conversation would drop every one of them
without saying so.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ASSISTANT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ASSISTANT_DIR / "web"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--web-port", type=int, default=5173)
    parser.add_argument("--no-web", action="store_true", help="the API only")
    parser.add_argument(
        "--no-warm",
        action="store_true",
        help="skip loading BGE-M3 at startup; the first KB question pays for it instead",
    )
    args = parser.parse_args(argv)

    env = dict(os.environ)
    env.setdefault("ASSISTANT_DEV", "1")
    if not args.no_warm:
        env["ASSISTANT_WARM_KB"] = "1"

    api = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "server.app:create_app", "--factory",
            "--host", "127.0.0.1", "--port", str(args.port),
        ],
        cwd=ASSISTANT_DIR,
        env=env,
    )
    web = None
    if not args.no_web and WEB_DIR.exists() and shutil.which("npm"):
        web = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(args.web_port)],
            cwd=WEB_DIR,
            env={**env, "VITE_ASSISTANT_API": f"http://127.0.0.1:{args.port}"},
        )
    elif not args.no_web:
        print(f"[no widget: {WEB_DIR} not built yet, or npm not on PATH]", file=sys.stderr)

    def stop(*_args) -> None:
        for process in (web, api):
            if process is not None and process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGINT, lambda *_: (stop(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (stop(), sys.exit(0)))
    try:
        return api.wait()
    finally:
        stop()


if __name__ == "__main__":
    sys.exit(main())
