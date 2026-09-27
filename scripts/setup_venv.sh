#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x "$HOME/.local/bin/virtualenv" ]; then
  pip3 install --user --break-system-packages virtualenv
fi
"$HOME/.local/bin/virtualenv" .venv
.venv/bin/pip install -r requirements.txt
