#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
config_path="${QAGENT_WORKBENCH_CONFIG:-${repo_root}/config/workbench.yaml}"
python_binary="${PYTHON_BINARY:-python3}"

if [[ ! -f "$config_path" ]]; then
  printf 'QAGENT_WORKBENCH_CONFIG does not point to a file: %s\n' "$config_path" >&2
  exit 2
fi
args=("--config" "$config_path")
if [[ -n "${QAGENT_PORT:-}" ]]; then
  if [[ ! "$QAGENT_PORT" =~ ^[0-9]+$ ]] || (( QAGENT_PORT < 1 || QAGENT_PORT > 65535 )); then
    printf 'QAGENT_PORT must be between 1 and 65535\n' >&2
    exit 2
  fi
  args+=("--port" "$QAGENT_PORT")
fi
if [[ -n "${QAGENT_RAW_FILE:-}" ]]; then
  if [[ ! -f "$QAGENT_RAW_FILE" ]]; then
    printf 'QAGENT_RAW_FILE does not point to a file\n' >&2
    exit 2
  fi
  args+=("--raw-file" "$QAGENT_RAW_FILE")
fi
if [[ -n "${QAGENT_LLM_OVERLAY:-}" ]]; then
  if [[ ! -f "$QAGENT_LLM_OVERLAY" ]]; then
    printf 'QAGENT_LLM_OVERLAY does not point to a file\n' >&2
    exit 2
  fi
  args+=("--agent-overlay" "$QAGENT_LLM_OVERLAY")
fi

exec "$python_binary" -X utf8 "$repo_root/app/workbench.py" "${args[@]}"
