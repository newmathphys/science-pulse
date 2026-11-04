#!/usr/bin/env bash
# Science Pulse: запуск через .venv (если есть), иначе системный python3.
# Примеры:
#   ./run.sh status
#   ./run.sh harvest --limit 2
#   ./run.sh publish
#   ./run.sh admin
set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

exec "$PY" -m science_pulse.cli "$@"
