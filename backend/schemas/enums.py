"""Shared enumerations taken verbatim from the interface standard v1.

These are the single source of truth for status/type/label strings used by the
API layer, the storage layer and (later) the VLM adapter. Publishing them via
``GET /api/v1/info`` lets the frontend consume the contract instead of guessing
field values.
"""

from __future__ import annotations

from enum import StrEnum


class VideoStatus(StrEnum):
    """Standard section 5.1 (Video)."""

    REGISTERED = "registered"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class VideoSource(StrEnum):
    """Standard section 3.1 (``source``)."""

    UPLOAD = "upload"
    SAV_CLIP = "sav_clip"
    LOCAL_PATH = "local_path"


class JobStatus(StrEnum):
    """Standard section 5.1 (Job)."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class JobStage(StrEnum):
    """Standard section 3.3 (``stage``)."""

    QUEUED = "queued"
    LOADING_VIDEO = "loading_video"
    SAMPLING_FRAMES = "sampling_frames"
    INFERENCE = "inference"
    PARSING = "parsing"
    SAVING = "saving"
    DONE = "done"


class JobType(StrEnum):
    """Standard section 3.3 (``job_type``)."""

    VIDEO_PROCESS = "video_process"
    EVALUATION = "evaluation"
    FUSION = "fusion"
    EXPORT = "export"


class PredictionSource(StrEnum):
    """Standard section 2.2.

    Real MiniCPM inference must use ``MODEL``; ``minicpm_v`` belongs in
    ``provider``, never in this field.
    """

    MODEL = "model"
    ORACLE = "oracle"
    MOCK = "mock"
    MANUAL = "manual"
    NONE = "none"


class SceneLabel(StrEnum):
    """Standard section 3.2 recommended scene labels."""

    LECTURE = "听讲"
    GROUP_DISCUSSION = "小组讨论"
    INDEPENDENT_STUDY = "独立学习"
    OTHER = "其他"
    UNCLASSIFIED = "未分类"


#: Standard section 2.2: only real model predictions may enter model metrics.
#: ``oracle``, ``mock`` and ``manual`` must never be scored as a prediction.
EVALUATION_ELIGIBLE_SOURCES: frozenset[PredictionSource] = frozenset(
    {PredictionSource.MODEL}
)


def enum_values(enum_cls: type[StrEnum]) -> list[str]:
    """Return the allowed wire values of an enum, in declaration order."""
    return [member.value for member in enum_cls]


def is_evaluation_eligible(prediction_source: str | None) -> bool:
    """Whether a prediction source may be scored as a model prediction.

    The backend owns this decision (standard section 2.2); clients must not
    infer it from ``provider``.
    """
    if prediction_source is None:
        return False
    try:
        source = PredictionSource(prediction_source)
    except ValueError:
        return False
    return source in EVALUATION_ELIGIBLE_SOURCES
