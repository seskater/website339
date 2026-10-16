#!/usr/bin/env bash
# macOS/Linux shortcut: ./run.sh            -> http://localhost:8000
#                       ./run.sh --share    -> also a free public link for testers
cd "$(dirname "$0")" && exec "${PYTHON:-python3}" start.py "$@"
