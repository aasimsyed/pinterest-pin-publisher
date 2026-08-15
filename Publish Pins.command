#!/bin/bash
cd "$(dirname "$0")"
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
"$PY" scripts/publish.py
echo
read -p "Press Enter to close this window..."
