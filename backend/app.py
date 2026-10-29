"""Flask application entry point for the learning-state analysis backend.

Run the development server::

    python app.py

or through the Flask CLI::

    flask --app app run --host 127.0.0.1 --port 8000

:func:`create_app` builds the application without starting a server, so tests
can use ``app.test_client()``.

Implemented scope
-----------------
The application includes video upload/registration and file access, persistent
analysis jobs, a single background worker, result JSON/CSV export, and both Mock
and real MiniCPM-V VLM adapters. EEG ingestion, evaluation metrics, cross-modal
fusion and real-time streaming remain unavailable and are reported honestly by
the API.
"""

from __future__ import annotations

import atexit
import logging
import time
from typing import Optional

from flask import Flask, Response, g, request

from api import register_blueprints
from api.errors import (
    REQUEST_ID_PATTERN,
    get_request_id,
    new_request_id,
    register_error_handlers,
)
from adapters.vlm import build_vlm_adapter
from config import Config
from logging_setup import configure_logging
from services.export_service import ExportService
from services.auth_service import AuthService
from services.job_service import JobService
from services.task_runner import JobRunner
from services.video_service import VideoService
from storage import db as storage_db
from storage.db import connect
from storage.files import ensure_storage_dirs
from storage.repositories import JobRepository, VideoRepository
from common.timeutil import utc_timestamp

logger = logging.getLogger(__name__)

#: Keys stored on ``app.extensions``.
BACKEND_STARTED_AT = "backend_started_at_monotonic"
REQUEST_STARTED_AT = "request_started_at_monotonic"


def _recover_interrupted_jobs(cfg: Config) -> None:
    """Fail jobs a previous process left ``queued``/``running``.

    A single-process runner cannot resume interrupted work, so pretending those
    jobs are still active would be a lie. Each orphan job (and its video) is
    marked failed with a readable reason, in one transaction.
    """
    jobs = JobRepository(cfg.database_path)
    videos = VideoRepository(cfg.database_path)
    with connect(cfg.database_path) as connection:
        affected = jobs.fail_orphaned(connection, finished_at=utc_timestamp())
        for _job_id, video_id in affected:
            videos.set_failed(connection, video_id)
    if affected:
        logger.warning(
            "marked %d interrupted job(s) as failed after restart", len(affected)
        )


def create_app(config: Optional[Config] = None) -> Flask:
    """Application factory.

    Parameters
    ----------
    config:
        Explicit configuration; when omitted it is read from ``BACKEND_*``
        environment variables.
    """
    cfg = config if config is not None else Config.from_env()

    configure_logging(cfg)

    app = Flask(__name__)
    app.config.update(
        APP_CONFIG=cfg,
        TESTING=cfg.testing,
        DEBUG=cfg.debug,
        MAX_CONTENT_LENGTH=cfg.max_upload_bytes,
    )

    # Readable UTF-8 JSON instead of \uXXXX escapes; stable key order.
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    app.extensions[BACKEND_STARTED_AT] = time.monotonic()

    # --- local persistence -------------------------------------------------
    # Video files and the SQLite database live under ``data_dir`` (gitignored).
    # Initialising here means a missing directory or unreadable schema fails
    # loudly at startup instead of on the first request.
    ensure_storage_dirs(cfg.data_dir, cfg.video_subdir)
    storage_db.init_db(cfg.database_path)
    app.extensions["video_service"] = VideoService(cfg)
    app.extensions["export_service"] = ExportService(cfg)
    app.extensions["auth_service"] = AuthService(cfg.database_path)

    # --- analysis pipeline -------------------------------------------------
    # The adapter is resolved through ``app.extensions`` on every job, so a
    # test (or a future hot swap) can replace it without rebuilding the runner.
    app.extensions["vlm_adapter"] = build_vlm_adapter(cfg)

    job_service = JobService(cfg)
    runner = JobRunner(
        cfg,
        adapter_getter=lambda: app.extensions["vlm_adapter"],
        job_service=job_service,
    )
    job_service.attach_runner(runner)
    app.extensions["job_service"] = job_service
    app.extensions["job_runner"] = runner

    _recover_interrupted_jobs(cfg)

    if cfg.job_worker_enabled:
        runner.start()
        atexit.register(runner.stop)

    @app.before_request
    def _assign_request_id() -> None:
        """Reuse a well-formed caller id, otherwise mint a new one."""
        incoming = request.headers.get(cfg.request_id_header, "")
        if REQUEST_ID_PATTERN.match(incoming or ""):
            g.request_id = incoming
        else:
            g.request_id = new_request_id()
        g.setdefault(REQUEST_STARTED_AT, time.monotonic())

    @app.after_request
    def _finalize_response(response: Response) -> Response:
        """Expose the correlation id and write one access log line."""
        response.headers["X-Request-Id"] = get_request_id()

        # JSON is UTF-8 by definition (RFC 8259), but older clients such as
        # Windows PowerShell 5.1 fall back to Latin-1 when the charset is
        # omitted and then render Chinese messages as mojibake. State it.
        content_type = response.headers.get("Content-Type") or ""
        if response.mimetype == "application/json" and "charset" not in content_type:
            response.headers["Content-Type"] = "application/json; charset=utf-8"

        started = getattr(g, REQUEST_STARTED_AT, None)
        duration_ms = (time.monotonic() - started) * 1000 if started else 0.0
        # Log the path only: query strings may carry user data.
        logger.info(
            "%s %s -> %s (%.1f ms)",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        return response

    register_error_handlers(app)
    register_blueprints(app)

    logger.info(
        "application created name=%s version=%s api_prefix=%s environment=%s",
        cfg.service_name,
        cfg.service_version,
        cfg.api_prefix,
        cfg.environment,
    )
    return app


#: Module-level instance so ``flask --app app`` and any WSGI server can use it.
app = create_app()


if __name__ == "__main__":
    _cfg: Config = app.config["APP_CONFIG"]
    logger.info("starting development server on http://%s:%s", _cfg.host, _cfg.port)
    # ``use_reloader=False`` keeps a single process (and a single log stream)
    # when the server runs as a background job.
    app.run(host=_cfg.host, port=_cfg.port, debug=_cfg.debug, use_reloader=False)
