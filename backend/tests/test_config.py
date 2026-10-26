"""Tests for environment-driven configuration."""

from __future__ import annotations

import os

import pytest

from config import Config


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


def test_environment_overrides_are_applied(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("BACKEND_HOST", "0.0.0.0")
    monkeypatch.setenv("BACKEND_PORT", "9001")
    monkeypatch.setenv("BACKEND_DEBUG", "true")
    monkeypatch.setenv("BACKEND_LOG_LEVEL", "debug")
    monkeypatch.setenv("BACKEND_MAX_UPLOAD_MB", "16")

    cfg = Config.from_env()

    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9001
    assert cfg.debug is True
    assert cfg.log_level == "DEBUG"
    assert cfg.max_upload_bytes == 16 * 1024 * 1024


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
