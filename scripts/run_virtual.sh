#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# User-space Qt xcb deps (no sudo on this host): extracted .debs live here.
if [ -d "$HOME/.local/qtlibs/usr/lib/x86_64-linux-gnu" ]; then
  export LD_LIBRARY_PATH="$HOME/.local/qtlibs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
# Let our Fusion palette win over the desktop platform theme (dark Mint etc.).
unset QT_QPA_PLATFORMTHEME
exec .venv/bin/python src/main.py --virtual "$@"
