"""Tests for environment-driven configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import BACKEND_DIR, Config


def _clear_backend_env(monkeypatch) -> None:
    for key in list(os.environ):
        if key.startswith("BACKEND_"):
            monkeypatch.delenv(key, raising=False)


def test_defaults_when_no_env_is_set(monkeypatch):
    _clear_backend_env(monkeypatch)

    cfg = Config.from_env()

    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8000
    assert cfg.api_prefix == "/api/v1"
    assert cfg.schema_version == "1.0"
    assert cfg.environment == "development"
    assert cfg.debug is False
    assert cfg.testing is False
    assert cfg.log_level == "INFO"
    assert cfg.max_upload_bytes == 512 * 1024 * 1024
    assert cfg.session_ttl_days == 14
    assert cfg.guest_session_ttl_hours == 24
    assert cfg.login_max_failures == 5
    assert cfg.registration_token is None
    assert Path(cfg.vlm_model_path) == (
        BACKEND_DIR.parent / "models" / "MiniCPM-V-4.6"
    )


def test_environment_overrides_are_applied(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("BACKEND_HOST", "0.0.0.0")
    monkeypatch.setenv("BACKEND_PORT", "9001")
    monkeypatch.setenv("BACKEND_DEBUG", "true")
    monkeypatch.setenv("BACKEND_LOG_LEVEL", "debug")
    monkeypatch.setenv("BACKEND_MAX_UPLOAD_MB", "16")
    monkeypatch.setenv("BACKEND_SESSION_TTL_DAYS", "3")
    monkeypatch.setenv("BACKEND_LOGIN_MAX_FAILURES", "2")
    monkeypatch.setenv("BACKEND_REGISTRATION_TOKEN", "admin-token")
    monkeypatch.setenv(
        "BACKEND_VLM_MODEL_PATH",
        "D:\\models\\custom-minicpm",
    )

    cfg = Config.from_env()

    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9001
    assert cfg.debug is True
    assert cfg.log_level == "DEBUG"
    assert cfg.max_upload_bytes == 16 * 1024 * 1024
    assert cfg.session_ttl_days == 3
    assert cfg.login_max_failures == 2
    assert cfg.registration_token == "admin-token"
    assert cfg.vlm_model_path == "D:\\models\\custom-minicpm"


def test_invalid_port_is_rejected(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("BACKEND_PORT", "70000")

    with pytest.raises(ValueError):
        Config.from_env()


def test_non_positive_upload_limit_is_rejected(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("BACKEND_MAX_UPLOAD_MB", "0")

    with pytest.raises(ValueError):
        Config.from_env()


def test_non_positive_session_security_values_are_rejected(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("BACKEND_SESSION_TTL_DAYS", "0")

    with pytest.raises(ValueError):
        Config.from_env()


def test_remote_vlm_environment_defaults_and_overrides(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("BACKEND_VLM_ADAPTER", "minicpm_remote")
    monkeypatch.setenv("BACKEND_VLM_REMOTE_URL", "http://127.0.0.1:19001")
    monkeypatch.setenv(
        "BACKEND_VLM_REMOTE_TOKEN",
        "backend-remote-token-0123456789abcdef",
    )
    monkeypatch.setenv("BACKEND_VLM_REMOTE_TIMEOUT_S", "45.5")
    monkeypatch.setenv("BACKEND_VLM_REMOTE_RETRIES", "1")
    monkeypatch.setenv("BACKEND_VLM_WINDOW_SECONDS", "3")
    monkeypatch.setenv("BACKEND_VLM_WINDOW_STRIDE_SECONDS", "3")
    monkeypatch.setenv("BACKEND_VLM_MAX_FRAMES", "8")

    cfg = Config.from_env()

    assert cfg.vlm_adapter == "minicpm_remote"
    assert cfg.vlm_remote_url == "http://127.0.0.1:19001"
    assert cfg.vlm_remote_timeout_s == 45.5
    assert cfg.vlm_remote_retries == 1
    assert cfg.vlm_window_seconds == 3.0
    assert cfg.vlm_window_stride_seconds == 3.0
    assert cfg.vlm_max_frames == 8


def test_remote_mode_rejects_more_than_eight_frames(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("BACKEND_VLM_ADAPTER", "minicpm_remote")
    monkeypatch.setenv("BACKEND_VLM_MAX_FRAMES", "9")

    with pytest.raises(ValueError):
        Config.from_env()


def test_overlapping_remote_window_stride_is_rejected(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("BACKEND_VLM_ADAPTER", "minicpm_remote")
    monkeypatch.setenv("BACKEND_VLM_WINDOW_SECONDS", "3")
    monkeypatch.setenv("BACKEND_VLM_WINDOW_STRIDE_SECONDS", "1.5")

    with pytest.raises(ValueError):
        Config.from_env()
