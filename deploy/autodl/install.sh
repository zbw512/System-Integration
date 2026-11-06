#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv-cloud}"
REQUESTED_PYTHON_BIN="${PYTHON_BIN:-}"

# AutoDL login shells usually put Conda on PATH, while non-interactive SSH
# commands may not. Prefer an explicit override, then common Conda locations.
if [[ -n "$REQUESTED_PYTHON_BIN" ]]; then
  PYTHON_BIN="$REQUESTED_PYTHON_BIN"
else
  PYTHON_BIN=""
  for candidate in \
    python3 \
    python \
    "$HOME/miniconda3/bin/python" \
    "$HOME/miniconda3/bin/python3" \
    /root/miniconda3/bin/python \
    /root/miniconda3/bin/python3 \
    /opt/conda/bin/python \
    /opt/conda/bin/python3 \
    /usr/bin/python3
  do
    if [[ "$candidate" == /* ]]; then
      [[ -x "$candidate" ]] || continue
    else
      command -v "$candidate" >/dev/null 2>&1 || continue
    fi
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [[ ! -f "$PROJECT_ROOT/cloud_vlm_service/requirements-gpu.txt" ]]; then
  echo "找不到 cloud_vlm_service/requirements-gpu.txt" >&2
  exit 1
fi

echo "Project root: $PROJECT_ROOT"
echo "Virtual env:  $VENV_DIR"

if [[ -z "$PYTHON_BIN" ]] || ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "未找到 Python 3.10+。可通过 PYTHON_BIN 显式指定解释器。" >&2
  echo "当前 PATH=$PATH" >&2
  exit 1
fi
echo "Python interpreter: $PYTHON_BIN"
"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"需要 Python 3.10+，当前为 {sys.version}")
print("Python:", sys.version.split()[0])
PY

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi 不存在；当前实例可能不是 GPU 实例。" >&2
  exit 1
fi
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR" || {
    echo "创建虚拟环境失败：$VENV_DIR" >&2
    exit 1
  }
fi
VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip wheel || {
  echo "升级 pip/wheel 失败；请检查网络和 pip 源。" >&2
  exit 1
}
"$VENV_PYTHON" -m pip install \
  -r "$PROJECT_ROOT/cloud_vlm_service/requirements-service.txt" || {
  echo "安装 FastAPI/Pillow 等服务依赖失败。" >&2
  exit 1
}

if ! "$VENV_PYTHON" -c "import torch, torchvision" >/dev/null 2>&1; then
  if [[ -z "${TORCH_INDEX_URL:-}" ]]; then
    cat >&2 <<'EOF'
当前虚拟环境没有 torch/torchvision。
请根据实际 AutoDL CUDA 镜像设置 TORCH_INDEX_URL 后重试，例如：
  TORCH_INDEX_URL=https://download.pytorch.org/whl/<matching-cuda> \
  TORCH_VERSION=2.14.1 \
  TORCHVISION_SPEC=torchvision \
  bash deploy/autodl/install.sh
不要混用 CPU 与 CUDA wheel。
EOF
    exit 2
  fi

  TORCH_VERSION="${TORCH_VERSION:-2.14.1}"
  TORCHVISION_SPEC="${TORCHVISION_SPEC:-torchvision}"
  "$VENV_PYTHON" -m pip install \
    --index-url "$TORCH_INDEX_URL" \
    "torch==$TORCH_VERSION" \
    "$TORCHVISION_SPEC" || {
    echo "Torch/Torchvision 安装失败。不要降级或覆盖 AutoDL 系统环境；请检查 wheel index 与 CUDA 版本。" >&2
    exit 1
  }
else
  "$VENV_PYTHON" - <<'PY'
import torch, torchvision
print("复用已安装 Torch:", torch.__version__)
print("复用已安装 Torchvision:", torchvision.__version__)
print("CUDA available:", torch.cuda.is_available())
PY
fi

"$VENV_PYTHON" -m pip install \
  -r "$PROJECT_ROOT/cloud_vlm_service/requirements-gpu.txt" || {
  echo "安装 Transformers/PEFT/Accelerate 等模型依赖失败。" >&2
  exit 1
}

"$VENV_PYTHON" - <<'PY' || {
import torch
if not torch.cuda.is_available():
    raise SystemExit("Torch 已安装但 CUDA 不可用")
print("Torch/CUDA 预检通过")
PY
  echo "Torch/CUDA 验证失败，停止安装。" >&2
  exit 1
}

echo
echo "Python 依赖安装完成。接下来执行："
echo "  bash $SCRIPT_DIR/check_environment.sh"
