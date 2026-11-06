#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

echo "== 环境 =="
bash "$SCRIPT_DIR/check_environment.sh"

echo "== 真实模型加载 =="
bash "$SCRIPT_DIR/load_model.sh"

echo "真实 GPU 模型加载检查完成。"
echo "下一步在 Windows 建立隧道并运行 scripts/test_single_window.ps1。"
