"""System endpoints: ``GET /health`` and ``GET /api/v1/info``.

Both endpoints are read-only and deliberately honest: they describe what the
backend can actually do right now. ``/api/v1/info`` lists unimplemented
capabilities as ``not_implemented`` instead of advertising features that do not
exist yet. Video jobs, result export and VLM adapter selection are implemented;
EEG, evaluation and fusion are not.
"""

from __future__ import annotations

import time

from flask import Blueprint, current_app, jsonify, request

from api.errors import get_request_id, utc_timestamp
from config import Config
from storage import db as storage_db
from schemas.enums import (
    JobStage,
    JobStatus,
    JobType,
    PredictionSource,
    SceneLabel,
    VideoSource,
    VideoStatus,
    enum_values,
)

health_bp = Blueprint("health", __name__)
info_bp = Blueprint("info", __name__)

OK = "ok"
NOT_IMPLEMENTED = "not_implemented"

_ENUM_EXPORTS = {
    "video_status": VideoStatus,
    "video_source": VideoSource,
    "job_status": JobStatus,
    "job_stage": JobStage,
    "job_type": JobType,
    "prediction_source": PredictionSource,
    "scene_label": SceneLabel,
}


@health_bp.get("/health")
def health():
    """Liveness probe.

    Returns ``200`` while the HTTP layer is able to answer. Component checks
    report unimplemented subsystems explicitly, so a green ``/health`` must not
    be read as "the model is loaded".
    """
    cfg: Config = current_app.config["APP_CONFIG"]
    started_at = current_app.extensions.get("backend_started_at_monotonic")
    uptime_s = max(0.0, time.monotonic() - started_at) if started_at else 0.0

    payload = {
        "status": OK,
        "schema_version": cfg.schema_version,
        "service": {
            "name": cfg.service_name,
            "version": cfg.service_version,
            "environment": cfg.environment,
        },
        "time": utc_timestamp(),
        "uptime_s": round(uptime_s, 3),
        "checks": {
            "http": OK,
            "storage": OK if storage_db.ping(cfg.database_path) else "error",
            "vlm_adapter": NOT_IMPLEMENTED,
            "eeg_adapter": NOT_IMPLEMENTED,
        },
        "request_id": get_request_id(),
    }
    return jsonify(payload), 200


@info_bp.get("/info")
def info():
    """Service and interface description for frontend integration."""
    cfg: Config = current_app.config["APP_CONFIG"]

    payload = {
        "schema_version": cfg.schema_version,
        "generated_at": utc_timestamp(),
        "service": {
            "name": cfg.service_name,
            "version": cfg.service_version,
            "environment": cfg.environment,
        },
        "api": {
            "prefix": cfg.api_prefix,
            "version": "v1",
            "base_url": request.host_url.rstrip("/"),
            "configured_base_url": f"http://{cfg.host}:{cfg.port}",
            "content_types": {
                "json": "application/json",
                "upload": "multipart/form-data",
            },
            "time_format": "RFC3339 UTC (YYYY-MM-DDTHH:MM:SSZ)",
            "list_format": {
                "items": "array",
                "pagination": ["limit", "offset", "total", "has_next"],
            },
        },
        # False means "not built yet" — never report a capability we lack.
        "capabilities": {
            "video_upload": True,
            "video_registration": True,
            # True only when a real (non-mock) adapter is configured; the
            # adapter detail below says whether the weights are actually present.
            "video_analysis": current_app.extensions["vlm_adapter"].name != "mock",
            "job_execution": True,
            "result_export": True,
            "evaluation": False,
            "eeg_ingest": False,
            "fusion": False,
            "realtime_stream": False,
        },
        "adapters": {
            "vlm": current_app.extensions["vlm_adapter"].describe(),
            "eeg": {"provider": None, "status": NOT_IMPLEMENTED},
        },
        "job_policy": {
            "duplicate_submission": "409 JOB_ALREADY_RUNNING",
            "cancel_supported": False,
            "worker": "single-thread-in-process",
            "concurrency": 1,
            "note": "任务在单进程单线程队列中串行执行；服务重启时未完成的任务会被标记为 "
            "failed（JOB_INTERRUPTED），不会伪装成仍在运行。",
        },
        "endpoints": [
            {
                "method": "GET",
                "path": "/health",
                "status": "implemented",
                "description": "健康检查",
            },
            {
                "method": "GET",
                "path": f"{cfg.api_prefix}/info",
                "status": "implemented",
                "description": "服务与接口说明",
            },
            {
                "method": "POST",
                "path": f"{cfg.api_prefix}/videos/upload",
                "status": "implemented",
                "description": "上传视频（multipart/form-data，字段名 file）",
            },
            {
                "method": "POST",
                "path": f"{cfg.api_prefix}/videos/register",
                "status": "implemented",
                "description": "登记已存在于导入目录内的视频",
            },
            {
                "method": "GET",
                "path": f"{cfg.api_prefix}/videos",
                "status": "implemented",
                "description": "视频列表（items + pagination）",
            },
            {
                "method": "GET",
                "path": f"{cfg.api_prefix}/videos/{'{video_id}'}",
                "status": "implemented",
                "description": "视频详情",
            },
            {
                "method": "GET",
                "path": f"{cfg.api_prefix}/videos/{'{video_id}'}/file",
                "status": "implemented",
                "description": "受控视频文件访问（支持 Range）",
            },
            {
                "method": "POST",
                "path": f"{cfg.api_prefix}/videos/{'{video_id}'}/process",
                "status": "implemented",
                "description": "创建视频分析任务，返回 202 + Job",
            },
            {
                "method": "GET",
                "path": f"{cfg.api_prefix}/videos/{'{video_id}'}/results",
                "status": "implemented",
                "description": "查询/导出已保存的分析结果（format=json|csv）",
            },
            {
                "method": "GET",
                "path": f"{cfg.api_prefix}/jobs",
                "status": "implemented",
                "description": "任务列表（items + pagination）",
            },
            {
                "method": "GET",
                "path": f"{cfg.api_prefix}/jobs/{'{job_id}'}",
                "status": "implemented",
                "description": "任务详情",
            },
        ],
        "limits": {
            "max_upload_bytes": cfg.max_upload_bytes,
            "list_default_limit": cfg.list_default_limit,
            "list_max_limit": cfg.list_max_limit,
            "allowed_video_extensions": list(cfg.allowed_video_extensions),
        },
        "storage": {
            "engine": "sqlite",
            "persistent": True,
            "video_file_access": "restricted_to_data_dir",
            "note": "视频文件与元数据保存在后端数据目录，服务重启后仍可查询；"
            "文件访问被限制在该目录内。",
        },
        "enums": {name: enum_values(enum_cls) for name, enum_cls in _ENUM_EXPORTS.items()},
        "evaluation_rules": {
            "evaluation_eligible_sources": ["model"],
            "note": "只有 prediction_source=model 的结果可参与模型指标计算；"
            "oracle、mock、manual 一律不可评估。",
        },
        "request_id": get_request_id(),
    }
    return jsonify(payload), 200
