#!/bin/bash
cd "$(dirname "$0")"

install_with_brew() {
    command -v brew >/dev/null 2>&1 || return 1
    echo "Installing $1 with Homebrew..."
    brew install "$1"
}

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python isn't installed yet."
    if ! install_with_brew python3; then
        echo "Opening the Python download page -- install it, then double-click Setup again."
        open "https://www.python.org/downloads/"
        read -p "Press Enter to close this window..."
        exit 1
    fi
fi

if ! command -v node >/dev/null 2>&1; then
    echo "Node.js isn't installed yet."
    if ! install_with_brew node; then
        echo "Opening the Node.js download page -- install it, then double-click Setup again."
        open "https://nodejs.org/"
        read -p "Press Enter to close this window..."
        exit 1
    fi
fi

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
"$PY" scripts/setup.py
echo
read -p "Press Enter to close this window..."
