#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv-cloud}"
VENV_PYTHON="$VENV_DIR/bin/python"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "虚拟环境不存在：$VENV_PYTHON" >&2
  exit 1
fi

cd "$PROJECT_ROOT"
exec "$VENV_PYTHON" -m cloud_vlm_service.load_model
