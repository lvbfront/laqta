# Laqta Agent

A small desktop app for photographers: point it at the folder your
camera's tethering software (or memory-card import) saves photos to, and
it uploads each one to Laqta within a couple of seconds of the file
finishing being written -- no FTP, no URLs, no passwords. This is now
the primary way photos get into an event (see `docs/plan.md`'s "Tier B"
path); FTPS (`api/app/ftps/`) remains available for cameras with native
FTP support.

## Pairing (how a photographer connects it, in one sentence)

An organizer clicks "Pair agent" on an event's dashboard card, gets a
6-character code good for 15 minutes, reads it to the photographer, who
types it into this app once -- the app exchanges it for a long-lived
token (`POST /api/agent/pair`) stored in the OS keychain, and never asks
for anything else again.

## Running from source (dev)

```bash
cd agent
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate.bat
pip install -r requirements.txt
LAQTA_API_URL=http://localhost:8000 python -m laqta_agent.main
```

`LAQTA_API_URL` defaults to `http://localhost:8000` if unset -- only
relevant when running from source; see `laqta_agent/config.py` and
"Building" below for why a *built* app doesn't read this env var in
practice.

## Tests

```bash
source .venv/bin/activate
PYTHONPATH=. python -m pytest tests/ -v
```

Pure unit tests, no network/API/Docker required -- `test_stability.py`
(the file-stability check), `test_queue_db.py` (the SQLite queue,
including a real close-and-reopen to prove it survives a restart), and
`test_dedupe.py` (MD5-based duplicate detection, same-content-different-
path included). `tkinter` is required to import `laqta_agent.gui`, which
some of these tests import transitively -- on Homebrew Python, install it
via `brew install python-tk@3.11` if you get `ModuleNotFoundError:
_tkinter`.

## Building

PyInstaller doesn't cross-compile -- build each platform's app on that
platform.

```bash
./build_macos.sh      # on macOS -> dist/Laqta Agent.app
build_windows.bat      # on Windows -> dist\Laqta Agent.exe
```

**Before building a real release**, edit `API_BASE_URL`'s hardcoded
default in `laqta_agent/config.py` to the production API URL. The
`LAQTA_API_URL` env var only affects running from source -- a photographer
launching the built app has no env var set, so the packaged app always
uses whatever's hardcoded in `config.py` at build time.

## How it works

- `stability.py` -- the file-stability state machine. A path is only
  reported "safe to upload" once its size and mtime are identical across
  two separate checks (spaced ~1s apart by the caller). This is the
  single most important correctness property of the whole agent: camera
  transfers and card-reader copies can take well over a second for a
  large file, and a filesystem "file created" event fires the moment the
  file is *opened*, not when writing finishes.
- `watcher.py` -- `watchdog`-based recursive folder observer, feeds
  candidate paths into the stability tracker, and on confirmed-stable
  hands them to the queue (after an MD5-based duplicate check). Also
  does the startup/"catch-up" full-folder scan.
- `queue_db.py` -- SQLite-backed upload queue (pending / uploading /
  done / failed), survives an app restart or a network outage without
  losing track of anything, retries failures with exponential backoff.
- `uploader.py` -- background thread draining the queue one file at a
  time against the API.
- `api_client.py` -- the two HTTP calls this app ever makes: pair, and
  upload one photo.
- `keychain.py` -- wraps the `keyring` package for the OS-native
  credential store (macOS Keychain / Windows Credential Locker).
- `settings.py` -- non-secret local preferences (watched folder, locale,
  whether RAW is included) as a plain JSON file, deliberately separate
  from the keychain.
- `gui.py` -- the whole UI: a pairing screen, then a status window
  (connected/offline, counts, a plain-language error list, a manual
  catch-up-scan button, an unpair button, an AR/EN toggle). Arabic by
  default. Note: tkinter has no real logical-RTL layout engine the way a
  browser does, so "Arabic mode" here means right-aligned text on every
  label, not a fully mirrored window.

## RAW files

Off by default (`include_raw` in `settings.py` / `config.py`'s
`RAW_EXTENSIONS`) -- large and slow, and a guest-facing gallery only ever
needs the JPEG. A camera set to shoot RAW+JPEG works fine with the
default; RAW-only shooters would need `include_raw` turned on (not yet
exposed in the GUI -- currently a `settings.json` edit).
