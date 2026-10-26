"""Shared pytest fixtures.

Every test gets an isolated data directory under ``tmp_path`` and its own
application instance, so the real ``backend/var`` directory is never touched and
tests cannot see each other's videos.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

from app import create_app
from config import Config


@pytest.fixture()
def config(tmp_path: Path) -> Config:
    """Test configuration backed by a temporary data directory.

    ``log_level="CRITICAL"`` keeps the expected 500-path traceback out of the
    test output; logging itself is not under test here.
    """
    import_root = tmp_path / "imports"
    import_root.mkdir(parents=True, exist_ok=True)

    return Config(
        testing=True,
        log_level="CRITICAL",
        data_dir=str(tmp_path / "data"),
        import_roots=(str(import_root),),
        # Tests drive the queue explicitly (see the ``drain`` fixture) instead
        # of racing a background thread.
        job_worker_enabled=False,
    )


@pytest.fixture()
def drain(app: Flask):
    """Execute everything currently queued, synchronously."""

    def _drain(timeout: float = 30.0) -> int:
        return app.extensions["job_runner"].run_until_idle(timeout)

    return _drain


@pytest.fixture()
def import_root(config: Config) -> Path:
    """Directory that ``POST /videos/register`` is allowed to read from."""
    return Path(config.import_roots[0])


@pytest.fixture()
def app(config: Config) -> Flask:
    return create_app(config)


@pytest.fixture()
def client(app: Flask):
    """Flask test client (no real socket is opened)."""
    return app.test_client()
