"""Environment-driven configuration for the AutoDL inference service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_MODEL_PATH = "/root/autodl-tmp/MiniCPM-V-4_5"
DEFAULT_ADAPTER_PATH = "/root/autodl-tmp/checkpoint-600"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18080
DEFAULT_MAX_FRAMES = 8
DEFAULT_MAX_REQUEST_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_FRAME_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_IMAGE_PIXELS = 16_000_000

MODEL_NAME = "MiniCPM-V"
MODEL_VERSION = "4.5"
MODEL_FINETUNE = "scene4"
LORA_CHECKPOINT = "checkpoint-600"
PROMPT_VERSION = "scene4-label-v1"


class ConfigurationError(ValueError):
    """The service cannot start with the current environment variables."""


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须是整数，当前值：{raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings.

    Tests construct this object directly. Production uses :meth:`from_env`.
    """

    base_model_path: Path = Path(DEFAULT_BASE_MODEL_PATH)
    adapter_path: Path = Path(DEFAULT_ADAPTER_PATH)
    service_token: str = ""
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    max_frames: int = DEFAULT_MAX_FRAMES
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES
    max_image_pixels: int = DEFAULT_MAX_IMAGE_PIXELS
    load_on_startup: bool = True
    log_level: str = "INFO"
    prompt_path: Path = Path(__file__).with_name("prompt_scene4.txt")

    @classmethod
    def from_env(cls) -> "Settings":
        token = _env_str("VLM_SERVICE_TOKEN", "")
        settings = cls(
            base_model_path=Path(
                _env_str("VLM_BASE_MODEL_PATH", DEFAULT_BASE_MODEL_PATH)
            ).expanduser(),
            adapter_path=Path(
                _env_str("VLM_ADAPTER_PATH", DEFAULT_ADAPTER_PATH)
            ).expanduser(),
            service_token=token,
            host=_env_str("VLM_HOST", DEFAULT_HOST),
            port=_env_int("VLM_PORT", DEFAULT_PORT),
            max_frames=_env_int("VLM_MAX_FRAMES", DEFAULT_MAX_FRAMES),
            max_request_bytes=_env_int(
                "VLM_MAX_REQUEST_BYTES", DEFAULT_MAX_REQUEST_BYTES
            ),
            max_frame_bytes=_env_int(
                "VLM_MAX_FRAME_BYTES", DEFAULT_MAX_FRAME_BYTES
            ),
            max_image_pixels=_env_int(
                "VLM_MAX_IMAGE_PIXELS", DEFAULT_MAX_IMAGE_PIXELS
            ),
            load_on_startup=_env_bool("VLM_LOAD_ON_STARTUP", True),
            log_level=_env_str("VLM_LOG_LEVEL", "INFO").upper(),
            prompt_path=Path(
                _env_str(
                    "VLM_PROMPT_PATH",
                    str(Path(__file__).with_name("prompt_scene4.txt")),
                )
            ).expanduser(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.service_token:
            raise ConfigurationError(
                "缺少 VLM_SERVICE_TOKEN；请生成至少 32 字符的随机 Token"
            )
        if len(self.service_token) < 32:
            raise ConfigurationError("VLM_SERVICE_TOKEN 至少需要 32 个字符")
        if not 1 <= self.port <= 65535:
            raise ConfigurationError("VLM_PORT 必须在 1-65535 之间")
        if not 1 <= self.max_frames <= DEFAULT_MAX_FRAMES:
            raise ConfigurationError(
                f"VLM_MAX_FRAMES 必须在 1-{DEFAULT_MAX_FRAMES} 之间"
            )
        if self.max_request_bytes <= 0:
            raise ConfigurationError("VLM_MAX_REQUEST_BYTES 必须大于 0")
        if self.max_frame_bytes <= 0 or self.max_frame_bytes > self.max_request_bytes:
            raise ConfigurationError(
                "VLM_MAX_FRAME_BYTES 必须大于 0 且不能超过请求体上限"
            )
        if self.max_image_pixels <= 0:
            raise ConfigurationError("VLM_MAX_IMAGE_PIXELS 必须大于 0")

    @property
    def model_info(self) -> dict[str, str]:
        return {
            "name": MODEL_NAME,
            "version": MODEL_VERSION,
            "finetune": MODEL_FINETUNE,
            "checkpoint": LORA_CHECKPOINT,
            "prompt_version": PROMPT_VERSION,
        }
