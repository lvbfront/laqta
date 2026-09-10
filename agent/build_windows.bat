@echo off
REM Builds the Windows .exe. Run this ON a Windows machine -- PyInstaller
REM doesn't cross-compile; see build_macos.sh for the macOS equivalent,
REM run on a Mac. Not executed/verified as part of this repo's own test
REM run (no Windows machine available there) -- mirrors build_macos.sh,
REM which was.
cd /d "%~dp0"

python -m venv .venv-build
call .venv-build\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt

REM --collect-submodules/--hidden-import for keyring: it discovers its
REM platform backend (Windows Credential Locker here) via entry_points at
REM runtime, which PyInstaller's static import analysis doesn't see on
REM its own -- see the matching note in build_macos.sh, confirmed there
REM by hand for the macOS backend; the same mechanism applies here.
pyinstaller ^
  --name "Laqta Agent" ^
  --windowed ^
  --onefile ^
  --noconfirm ^
  --collect-submodules keyring.backends ^
  --hidden-import keyring.backends.Windows ^
  laqta_agent\main.py

echo.
echo Built: dist\Laqta Agent.exe
echo.
echo NOTE: laqta_agent\config.py's API_BASE_URL falls back to an
echo LAQTA_API_URL env var, but that only matters for running from
echo source -- an end user launching the built .exe has no env var set,
echo so the packaged app always uses config.py's hardcoded default
echo (currently http://localhost:8000, this project's dev server).
echo Before building a real release, edit that default in config.py
echo directly -- an env var set here at build time will NOT travel
echo into the .exe.
