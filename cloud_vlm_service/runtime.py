"""Model loading and one-window inference for MiniCPM-V 4.5 + LoRA."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from cloud_vlm_service.config import Settings
from cloud_vlm_service.contract import load_prompt
from cloud_vlm_service.errors import (
    InferenceError,
    InvalidFrameError,
    ModelAssetsMissingError,
    ModelLoadError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InferenceResult:
    raw_prediction: str
    frame_count: int
    inference_ms: float


def inspect_model_assets(settings: Settings) -> dict[str, Any]:
    """Validate required local files without importing Torch."""
    base = settings.base_model_path
    adapter = settings.adapter_path
    errors: list[str] = []

    config_path = base / "config.json"
    index_path = base / "model.safetensors.index.json"
    if not base.is_dir():
        errors.append("base_model_directory_missing")
    if not config_path.is_file():
        errors.append("base_config_missing")
    else:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if str(config.get("version")) != "4.5":
                errors.append("base_model_version_not_4_5")
        except Exception:
            errors.append("base_config_invalid")

    required_runtime_files = (
        "configuration_minicpm.py",
        "image_processing_minicpmv.py",
        "modeling_minicpmv.py",
        "modeling_navit_siglip.py",
        "preprocessor_config.json",
        "processing_minicpmv.py",
        "resampler.py",
        "tokenizer.json",
        "tokenizer_config.json",
    )
    for filename in required_runtime_files:
        if not (base / filename).is_file():
            errors.append(f"base_file_missing:{filename}")

    shard_names: list[str] = []
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            shard_names = sorted(set(index.get("weight_map", {}).values()))
            if not shard_names:
                errors.append("base_index_has_no_shards")
            for shard_name in shard_names:
                shard_path = base / shard_name
                if not shard_path.is_file():
                    errors.append(f"base_shard_missing:{shard_name}")
                elif shard_path.stat().st_size <= 0:
                    errors.append(f"base_shard_empty:{shard_name}")
        except Exception:
            errors.append("base_index_invalid")
    else:
        shard_names = sorted(path.name for path in base.glob("model*.safetensors"))
        if not shard_names:
            errors.append("base_weights_missing")

    adapter_config = adapter / "adapter_config.json"
    adapter_weights = adapter / "adapter_model.safetensors"
    if not adapter.is_dir():
        errors.append("adapter_directory_missing")
    if not adapter_config.is_file():
        errors.append("adapter_config_missing")
    else:
        try:
            config = json.loads(adapter_config.read_text(encoding="utf-8"))
            if str(config.get("peft_type")).upper() != "LORA":
                errors.append("adapter_is_not_lora")
        except Exception:
            errors.append("adapter_config_invalid")
    if not adapter_weights.is_file():
        errors.append("adapter_weights_missing")
    elif adapter_weights.stat().st_size <= 0:
        errors.append("adapter_weights_empty")

    return {
        "valid": not errors,
        "errors": errors,
        "base_model_path": str(base),
        "adapter_path": str(adapter),
        "base_shards": shard_names,
        "adapter_weight_bytes": (
            adapter_weights.stat().st_size if adapter_weights.is_file() else None
        ),
    }


class MiniCPMV45LoRARuntime:
    """Single-process, single-model runtime.

    The model is loaded once. A process-wide inference lock deliberately
    serialises requests so two windows cannot allocate activation memory at the
    same time.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any = None
        self._tokenizer: Any = None
        self._torch: Any = None
        self._prompt = load_prompt(settings.prompt_path)
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._load_error: str | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    @property
    def model_info(self) -> dict[str, str]:
        return self.settings.model_info

    def load(self) -> None:
        if self.loaded:
            return

        with self._load_lock:
            if self.loaded:
                return

            assets = inspect_model_assets(self.settings)
            if not assets["valid"]:
                problem = ", ".join(assets["errors"])
                self._load_error = f"模型文件校验失败：{problem}"
                raise ModelAssetsMissingError(self._load_error)

            try:
                import torch
                from peft import PeftModel
                from transformers import AutoModel, AutoTokenizer
            except ImportError as exc:
                self._load_error = f"缺少 GPU 推理依赖：{type(exc).__name__}"
                raise ModelLoadError(self._load_error) from exc

            if not torch.cuda.is_available():
                self._load_error = "没有可用的 CUDA GPU"
                raise ModelLoadError(self._load_error)

            try:
                tokenizer = AutoTokenizer.from_pretrained(
                    str(self.settings.base_model_path),
                    trust_remote_code=True,
                    local_files_only=True,
                )
                base_model = AutoModel.from_pretrained(
                    str(self.settings.base_model_path),
                    trust_remote_code=True,
                    local_files_only=True,
                    # The model card declares transformers 4.51.0, where this
                    # argument is named torch_dtype. The numeric dtype remains
                    # the owner-required BF16.
                    torch_dtype=torch.bfloat16,
                    attn_implementation="sdpa",
                ).eval().cuda()
                model = PeftModel.from_pretrained(
                    base_model,
                    str(self.settings.adapter_path),
                ).eval()
            except Exception as exc:
                self._load_error = f"模型加载异常：{type(exc).__name__}"
                logger.exception("MiniCPM-V 4.5 + LoRA model load failed")
                raise ModelLoadError(self._load_error) from exc

            self._torch = torch
            self._tokenizer = tokenizer
            self._model = model
            self._load_error = None
            logger.info(
                "model_loaded base=%s adapter=%s model=%s prompt_version=%s",
                self.settings.base_model_path,
                self.settings.adapter_path,
                self.settings.model_info["version"],
                self.settings.model_info["prompt_version"],
            )

    def predict_window(self, frames: Sequence[Any]) -> InferenceResult:
        if not frames:
            raise InvalidFrameError("至少需要一帧图片")
        if len(frames) > self.settings.max_frames:
            raise InvalidFrameError(
                f"一个窗口最多允许 {self.settings.max_frames} 帧"
            )

        if not self.loaded:
            self.load()

        messages = [
            {
                "role": "user",
                "content": list(frames) + [self._prompt],
            }
        ]

        started = time.perf_counter()
        try:
            with self._inference_lock:
                with self._torch.inference_mode():
                    raw = self._model.chat(
                        image=None,
                        msgs=messages,
                        tokenizer=self._tokenizer,
                        use_image_id=False,
                        max_slice_nums=2,
                    )
        except Exception as exc:
            logger.exception("MiniCPM-V 4.5 inference failed")
            raise InferenceError(
                f"模型推理异常：{type(exc).__name__}"
            ) from exc

        if not isinstance(raw, str):
            raise InferenceError("模型返回了非文本结果")

        return InferenceResult(
            raw_prediction=raw,
            frame_count=len(frames),
            inference_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def health_snapshot(self) -> dict[str, Any]:
        assets = inspect_model_assets(self.settings)
        cuda_available = False
        gpu_name: str | None = None
        device: str | None = None

        if self._torch is not None:
            try:
                cuda_available = bool(self._torch.cuda.is_available())
                if cuda_available:
                    device = "cuda"
                    gpu_name = str(self._torch.cuda.get_device_name(0))
            except Exception:
                logger.exception("failed to query CUDA health")

        return {
            "status": "ok" if self.loaded else "degraded",
            "loaded": self.loaded,
            "model": self.model_info,
            "device": device,
            "cuda_available": cuda_available,
            "gpu_name": gpu_name,
            "base_model_present": not any(
                item.startswith("base_") for item in assets["errors"]
            ),
            "adapter_present": not any(
                item.startswith("adapter_") for item in assets["errors"]
            ),
            "max_frames": self.settings.max_frames,
            "load_error": self._load_error,
        }
