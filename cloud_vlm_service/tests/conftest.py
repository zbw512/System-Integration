from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from cloud_vlm_service.config import Settings

TOKEN = "test-token-0123456789abcdef0123456789abcdef"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        base_model_path=tmp_path / "base",
        adapter_path=tmp_path / "adapter",
        service_token=TOKEN,
        load_on_startup=False,
        log_level="CRITICAL",
    )


@pytest.fixture()
def png_base64() -> str:
    output = io.BytesIO()
    Image.new("RGB", (16, 12), (32, 64, 96)).save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def valid_request(png_base64: str) -> dict:
    return {
        "request_id": "req-test-1",
        "window_id": "job-1-window-0",
        "window_start_s": 0.0,
        "window_end_s": 3.0,
        "prompt_version": "scene4-label-v1",
        "frames": [
            {
                "timestamp_s": index * 0.4,
                "mime_type": "image/png",
                "image_base64": png_base64,
            }
            for index in range(8)
        ],
    }
