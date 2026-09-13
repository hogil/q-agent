#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${QAGENT_PYTHON:-python3}"
exec "$python_bin" -X utf8 "$script_dir/../app/run_agent.py" "$@"
