from __future__ import annotations

from pathlib import Path

import pytest

from cloud_vlm_service.config import ConfigurationError, Settings


def test_defaults_use_required_autodl_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VLM_SERVICE_TOKEN", "x" * 32)
    monkeypatch.setenv("VLM_PROMPT_PATH", str(tmp_path / "prompt.txt"))

    settings = Settings.from_env()

    assert settings.base_model_path == Path("/root/autodl-tmp/MiniCPM-V-4_5")
    assert settings.adapter_path == Path("/root/autodl-tmp/checkpoint-600")
    assert settings.host == "127.0.0.1"
    assert settings.port == 18080
    assert settings.max_frames == 8


def test_paths_are_overridable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VLM_SERVICE_TOKEN", "x" * 32)
    monkeypatch.setenv("VLM_BASE_MODEL_PATH", str(tmp_path / "base"))
    monkeypatch.setenv("VLM_ADAPTER_PATH", str(tmp_path / "adapter"))
    monkeypatch.setenv("VLM_PROMPT_PATH", str(tmp_path / "prompt.txt"))

    settings = Settings.from_env()

    assert settings.base_model_path == tmp_path / "base"
    assert settings.adapter_path == tmp_path / "adapter"


def test_token_is_required() -> None:
    with pytest.raises(ConfigurationError):
        Settings(service_token="").validate()


def test_more_than_eight_frames_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        Settings(service_token="x" * 32, max_frames=9).validate()


def test_invalid_port_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        Settings(service_token="x" * 32, port=70000).validate()
