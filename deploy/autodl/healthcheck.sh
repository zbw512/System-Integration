#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

VLM_SERVICE_TOKEN="${VLM_SERVICE_TOKEN:-}"
VLM_HOST="${VLM_HOST:-127.0.0.1}"
VLM_PORT="${VLM_PORT:-18080}"
VLM_SERVICE_TOKEN="${VLM_SERVICE_TOKEN%$'\r'}"
VLM_HOST="${VLM_HOST%$'\r'}"
VLM_PORT="${VLM_PORT%$'\r'}"

if [[ -z "${VLM_SERVICE_TOKEN:-}" ]]; then
  echo "VLM_SERVICE_TOKEN 未设置" >&2
  exit 1
fi

url="${VLM_HEALTH_URL:-http://${VLM_HOST:-127.0.0.1}:${VLM_PORT:-18080}/health}"
curl --fail --silent --show-error \
  --max-time 15 \
  -H "Authorization: Bearer $VLM_SERVICE_TOKEN" \
  "$url"
echo
