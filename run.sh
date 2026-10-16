#!/usr/bin/env bash
# One-command start: creates a virtualenv, installs dependencies, starts the web app.
#   ./run.sh                 -> http://localhost:8000
#   PORT=9000 ./run.sh
# Set ANTHROPIC_API_KEY (or put it in a .env file here) for Claude ranking;
# without it the app falls back to basic keyword matching.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then set -a; . ./.env; set +a; fi

PY=${PYTHON:-python3}
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
fi
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
  touch .venv/.installed
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Note: ANTHROPIC_API_KEY is not set, so results use basic keyword matching."
fi
echo "Vinted Finder running at http://localhost:${PORT:-8000}"
exec .venv/bin/uvicorn vinted_finder.app:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
