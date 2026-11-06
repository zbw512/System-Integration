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

VLM_SERVICE_TOKEN="${VLM_SERVICE_TOKEN:-}"
VLM_BASE_MODEL_PATH="${VLM_BASE_MODEL_PATH:-}"
VLM_ADAPTER_PATH="${VLM_ADAPTER_PATH:-}"
VLM_SERVICE_TOKEN="${VLM_SERVICE_TOKEN%$'\r'}"
VLM_BASE_MODEL_PATH="${VLM_BASE_MODEL_PATH%$'\r'}"
VLM_ADAPTER_PATH="${VLM_ADAPTER_PATH%$'\r'}"
export VLM_SERVICE_TOKEN VLM_BASE_MODEL_PATH VLM_ADAPTER_PATH

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "虚拟环境不存在：$VENV_PYTHON" >&2
  echo "先执行 deploy/autodl/install.sh" >&2
  exit 1
fi

echo "== Python =="
"$VENV_PYTHON" --version
"$VENV_PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"需要 Python 3.10+，当前为 {sys.version}")
PY

echo "== GPU =="
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
else
  echo "nvidia-smi 不存在" >&2
  exit 1
fi

echo "== Python packages =="
"$VENV_PYTHON" - <<'PY'
import importlib.metadata as metadata
import json
import torch
import torchvision

names = [
    "torch",
    "torchvision",
    "transformers",
    "peft",
    "accelerate",
    "safetensors",
    "fastapi",
    "uvicorn",
    "Pillow",
]
versions = {name: metadata.version(name) for name in names}
print(json.dumps(versions, ensure_ascii=False, indent=2))
print("cuda_available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu_name:", torch.cuda.get_device_name(0))
    free, total = torch.cuda.mem_get_info()
    print("cuda_free_mib:", round(free / 1024**2))
    print("cuda_total_mib:", round(total / 1024**2))
    if total < 20 * 1024**3:
        raise SystemExit(
            "显存不足：BF16 权重约 16.2 GiB，建议至少 24 GiB，"
            "并优先选择 32/40 GiB。"
        )
else:
    raise SystemExit("CUDA 不可用")
PY

echo "== Disk =="
df -h /root/autodl-tmp "$PROJECT_ROOT"

echo "== Model assets =="
(
  cd "$PROJECT_ROOT"
  "$VENV_PYTHON" -m cloud_vlm_service.verify_assets
)

echo "环境检查通过。"
