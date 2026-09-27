#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -d "$HOME/.local/qtlibs/usr/lib/x86_64-linux-gnu" ]; then
  export LD_LIBRARY_PATH="$HOME/.local/qtlibs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
exec .venv/bin/python -m pytest tests/ -q "$@"
