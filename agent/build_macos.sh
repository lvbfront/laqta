#!/usr/bin/env bash
# Builds the macOS .app bundle. Run this ON a Mac -- PyInstaller doesn't
# cross-compile; see build_windows.bat for the Windows equivalent, run on
# a Windows machine.
set -euo pipefail
cd "$(dirname "$0")"

python3.11 -m venv .venv-build
source .venv-build/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# --collect-submodules/--hidden-import for keyring: it discovers its
# platform backend (macOS Keychain here) via entry_points at runtime,
# which PyInstaller's static import analysis doesn't see on its own --
# confirmed by hand: without these flags the built app raises
# NoKeyringError at first keychain access despite running fine from
# source.
pyinstaller \
  --name "Laqta Agent" \
  --windowed \
  --onefile \
  --noconfirm \
  --collect-submodules keyring.backends \
  --hidden-import keyring.backends.macOS \
  --osx-bundle-identifier sa.laqta.agent \
  laqta_agent/main.py

echo ""
echo "Built: dist/Laqta Agent.app"
echo ""
echo "NOTE: laqta_agent/config.py's API_BASE_URL falls back to an"
echo "LAQTA_API_URL env var, but that only matters for running from"
echo "source -- an end user launching the built .app has no env var set,"
echo "so the packaged app always uses config.py's hardcoded default"
echo "(currently http://localhost:8000, this project's dev server)."
echo "Before building a real release, edit that default in config.py"
echo "directly -- an env var set here at build time will NOT travel"
echo "into the .app."
