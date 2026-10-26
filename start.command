#!/bin/bash
# Double-click this on a Mac to start Court Finder.
# The first time it sets up a private Python environment in .venv (needs python3).
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 isn't installed. Install it from https://www.python.org/downloads/"
  echo "or with Homebrew:  brew install python"
  read -r -p "Press Enter to close."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up Python environment in .venv ..."
  python3 -m venv .venv || { read -r -p "Couldn't set it up. Press Enter to close."; exit 1; }
fi

.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt \
  || { read -r -p "Couldn't install the requirements. Press Enter to close."; exit 1; }
.venv/bin/python app.py "$@"
read -r -p "Court Finder stopped. Press Enter to close."
