@echo off
rem Double-click this on Windows to start Court Finder.
rem The first time it sets up a private Python environment in .venv.
cd /d "%~dp0"

set PY=py
where py >nul 2>nul || set PY=python
where %PY% >nul 2>nul || (
  echo Python 3 is not installed. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" in the installer.
  pause
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  echo First run: setting up Python environment in .venv ...
  %PY% -m venv .venv || (pause & exit /b 1)
)

.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt || (pause & exit /b 1)
.venv\Scripts\python.exe app.py %*
pause
