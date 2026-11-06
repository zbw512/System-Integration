#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
RUN_DIR="${RUN_DIR:-$PROJECT_ROOT/.run}"
PID_FILE="$RUN_DIR/cloud-vlm.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "没有 PID 文件，服务未运行或不是由 start_service.sh 启动。"
  exit 0
fi

pid="$(cat "$PID_FILE")"
if ! kill -0 "$pid" 2>/dev/null; then
  echo "PID $pid 已不存在，清理 PID 文件。"
  rm -f "$PID_FILE"
  exit 0
fi

echo "正在停止 PID=$pid"
kill "$pid"
for _ in {1..20}; do
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "服务已停止。"
    exit 0
  fi
  sleep 0.5
done

echo "进程在 10 秒内未退出，请检查日志；脚本不会自动 kill -9。" >&2
exit 1
