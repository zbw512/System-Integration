#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv-cloud}"
VENV_PYTHON="$VENV_DIR/bin/python"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/.env}"
RUN_DIR="${RUN_DIR:-$PROJECT_ROOT/.run}"
PID_FILE="$RUN_DIR/cloud-vlm.pid"
LOG_FILE="$RUN_DIR/cloud-vlm.log"
STARTUP_WAIT_S="${STARTUP_WAIT_S:-180}"
SKIP_PREFLIGHT="${SKIP_PREFLIGHT:-0}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "缺少环境文件：$ENV_FILE" >&2
  echo "先复制 deploy/autodl/.env.example 并生成 Token" >&2
  exit 1
fi
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "虚拟环境不存在：$VENV_PYTHON" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

VLM_SERVICE_TOKEN="${VLM_SERVICE_TOKEN:-}"
VLM_BASE_MODEL_PATH="${VLM_BASE_MODEL_PATH:-}"
VLM_ADAPTER_PATH="${VLM_ADAPTER_PATH:-}"
VLM_HOST="${VLM_HOST:-127.0.0.1}"
VLM_PORT="${VLM_PORT:-18080}"
VLM_LOG_LEVEL="${VLM_LOG_LEVEL:-INFO}"
VLM_SERVICE_TOKEN="${VLM_SERVICE_TOKEN%$'\r'}"
VLM_BASE_MODEL_PATH="${VLM_BASE_MODEL_PATH%$'\r'}"
VLM_ADAPTER_PATH="${VLM_ADAPTER_PATH%$'\r'}"
VLM_HOST="${VLM_HOST%$'\r'}"
VLM_PORT="${VLM_PORT%$'\r'}"
VLM_LOG_LEVEL="${VLM_LOG_LEVEL%$'\r'}"

if [[ "$SKIP_PREFLIGHT" != "1" ]]; then
  echo "启动前检查 GPU、依赖和模型文件..."
  bash "$SCRIPT_DIR/check_environment.sh" || {
    echo "启动前检查失败。不要绕过检查启动模型服务。" >&2
    exit 1
  }
fi

mkdir -p "$RUN_DIR"
if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(cat "$PID_FILE")"
  if kill -0 "$existing_pid" 2>/dev/null; then
    if bash "$SCRIPT_DIR/healthcheck.sh" >/dev/null 2>&1; then
      echo "服务已运行且健康，PID=$existing_pid"
      exit 0
    fi
    echo "检测到不健康的旧服务，PID=$existing_pid；停止后重新启动。"
    kill "$existing_pid"
    for _ in {1..20}; do
      if ! kill -0 "$existing_pid" 2>/dev/null; then
        break
      fi
      sleep 0.5
    done
    if kill -0 "$existing_pid" 2>/dev/null; then
      echo "旧服务 PID=$existing_pid 未能在 10 秒内退出，停止重试。" >&2
      exit 1
    fi
  fi
  rm -f "$PID_FILE"
fi

cd "$PROJECT_ROOT"
PYTHONUNBUFFERED=1 nohup "$VENV_PYTHON" -m uvicorn \
  cloud_vlm_service.app:create_app \
  --factory \
  --host "${VLM_HOST:-127.0.0.1}" \
  --port "${VLM_PORT:-18080}" \
  --workers 1 \
  --log-level "$(printf '%s' "${VLM_LOG_LEVEL:-INFO}" | tr '[:upper:]' '[:lower:]')" \
  >>"$LOG_FILE" 2>&1 &

pid=$!
echo "$pid" >"$PID_FILE"
echo "服务进程已启动，PID=$pid；等待模型就绪（最多 ${STARTUP_WAIT_S}s）"

deadline=$((SECONDS + STARTUP_WAIT_S))
while (( SECONDS < deadline )); do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "服务进程已退出，日志尾部：" >&2
    tail -n 80 "$LOG_FILE" >&2 || true
    rm -f "$PID_FILE"
    exit 1
  fi

  if bash "$SCRIPT_DIR/healthcheck.sh" >/dev/null 2>&1; then
    echo "服务已就绪：$(bash "$SCRIPT_DIR/healthcheck.sh")"
    exit 0
  fi
  sleep 3
done

echo "服务在 ${STARTUP_WAIT_S}s 内未就绪，日志尾部：" >&2
tail -n 100 "$LOG_FILE" >&2 || true
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid" || true
fi
rm -f "$PID_FILE"
exit 1
