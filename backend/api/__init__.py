"""HTTP layer: blueprint registration and the unified error contract.

The API layer only validates input, calls services and returns standard
responses. It must not contain video decoding, model inference or storage
logic.
"""

from __future__ import annotations

from flask import Flask

from api.jobs import jobs_bp
from api.system import health_bp, info_bp
from api.videos import videos_bp

__all__ = ["register_blueprints"]


def register_blueprints(app: Flask) -> None:
    """Register every HTTP blueprint on ``app``."""
    cfg = app.config["APP_CONFIG"]

    # ``/health`` lives at the root (standard section 4.1), everything else is
    # versioned under ``/api/v1``.
    app.register_blueprint(health_bp)
    app.register_blueprint(info_bp, url_prefix=cfg.api_prefix)
    app.register_blueprint(videos_bp, url_prefix=f"{cfg.api_prefix}/videos")
    app.register_blueprint(jobs_bp, url_prefix=f"{cfg.api_prefix}/jobs")
