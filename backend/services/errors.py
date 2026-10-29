"""Domain errors raised by the service and storage layers.

Each error carries the fields of the standard error object (``code``,
``message``, ``details``, ``retryable``) so the HTTP layer can translate them
without services knowing about status codes or JSON.
"""

from __future__ import annotations

from typing import Any, Mapping


class ServiceError(Exception):
    """Base class for business failures."""

    code: str = "INTERNAL_ERROR"
    status: int = 500
    default_message: str = "服务内部错误"
    retryable: bool = False

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details: dict[str, Any] = dict(details or {})
        if retryable is not None:
            self.retryable = retryable
        super().__init__(self.message)


class VideoNotFoundError(ServiceError):
    code = "VIDEO_NOT_FOUND"
    status = 404
    default_message = "视频不存在"

    def __init__(self, video_id: str) -> None:
        super().__init__(details={"resource": "video", "video_id": video_id})


class DuplicateVideoError(ServiceError):
    code = "VIDEO_ALREADY_EXISTS"
    status = 409
    default_message = "该 video_id 已存在"

    def __init__(self, video_id: str) -> None:
        super().__init__(
            details={"resource": "video", "video_id": video_id},
            retryable=False,
        )


class InvalidVideoRequestError(ServiceError):
    """Invalid client input for a video endpoint (``400 VALIDATION_ERROR``)."""

    code = "VALIDATION_ERROR"
    status = 400
    default_message = "视频请求参数不合法"


class InvalidAccountRequestError(ServiceError):
    code = "VALIDATION_ERROR"
    status = 400
    default_message = "账户信息不合法"


class InvalidCredentialsError(ServiceError):
    """Use one generic message to avoid revealing whether a user exists."""

    code = "INVALID_CREDENTIALS"
    status = 401
    default_message = "用户名或密码不正确"


class AuthenticationRequiredError(ServiceError):
    code = "AUTHENTICATION_REQUIRED"
    status = 401
    default_message = "请先登录后查看个人历史"


class UsernameTakenError(ServiceError):
    code = "USERNAME_TAKEN"
    status = 409
    default_message = "该用户名已被使用"


class UnsupportedVideoFormatError(ServiceError):
    code = "UNSUPPORTED_VIDEO_FORMAT"
    status = 415
    default_message = "不支持的视频格式"


class PayloadTooLargeError(ServiceError):
    """Body or file exceeds the configured limit (``413``)."""

    code = "PAYLOAD_TOO_LARGE"
    status = 413
    default_message = "文件超过大小限制"


class LocalPathNotAllowedError(ServiceError):
    """A client-supplied path falls outside the configured import roots."""

    code = "LOCAL_PATH_NOT_ALLOWED"
    status = 400
    default_message = "本地路径不在允许的导入目录内"


class StoredFileMissingError(ServiceError):
    """The database row exists but the stored file is gone."""

    code = "VIDEO_FILE_MISSING"
    status = 404
    default_message = "视频记录存在，但存储文件已丢失"


class StorageError(ServiceError):
    code = "STORAGE_ERROR"
    status = 500
    default_message = "本地存储操作失败"
    retryable = True


class JobNotFoundError(ServiceError):
    code = "JOB_NOT_FOUND"
    status = 404
    default_message = "任务不存在"

    def __init__(self, job_id: str) -> None:
        super().__init__(details={"resource": "job", "job_id": job_id})


class JobAlreadyRunningError(ServiceError):
    """Duplicate submission: the video already has an active job."""

    code = "JOB_ALREADY_RUNNING"
    status = 409
    default_message = "该视频已有正在进行的分析任务"

    def __init__(self, video_id: str, job_id: str, job_status: str) -> None:
        super().__init__(
            details={
                "resource": "video",
                "video_id": video_id,
                "job_id": job_id,
                "job_status": job_status,
            },
            retryable=False,
        )


class JobStateError(ServiceError):
    """An illegal job state transition was attempted."""

    code = "JOB_STATE_CONFLICT"
    status = 409
    default_message = "任务状态不允许该操作"

    def __init__(self, job_id: str, *, expected: str = "") -> None:
        super().__init__(
            details={"job_id": job_id, "expected_transition": expected},
            retryable=False,
        )


class VlmAnalysisError(ServiceError):
    """The VLM adapter failed to produce an analysis."""

    code = "VLM_UPSTREAM_ERROR"
    status = 502
    default_message = "视觉模型分析失败"
    retryable = True


class VlmResultInvalidError(ServiceError):
    """The adapter returned something the standard does not allow."""

    code = "VLM_RESULT_INVALID"
    status = 422
    default_message = "视觉模型返回结果不合法"


class VideoNotProcessedError(ServiceError):
    """The video exists but has no persisted analysis result yet.

    Used by the result/export endpoints so an unanalysed, still-running or
    failed video is never presented as a successful analysis.
    """

    code = "VIDEO_NOT_PROCESSED"
    status = 409
    default_message = "视频尚未分析完成，暂无结果可导出"

    def __init__(
        self,
        video_id: str,
        video_status: str,
        job_context: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "resource": "video",
            "video_id": video_id,
            "status": video_status,
        }
        if job_context:
            details["job"] = job_context
        super().__init__(details=details, retryable=False)


# --------------------------------------------------------------------------- #
# Real VLM adapter (P0-5)
# --------------------------------------------------------------------------- #
class VlmModelNotFoundError(ServiceError):
    """The configured model directory or its weights are missing."""

    code = "VLM_MODEL_NOT_FOUND"
    status = 503
    default_message = "本地模型目录或权重缺失，无法执行真实推理"


class VlmLoadFailedError(ServiceError):
    """Loading the model into memory/GPU failed."""

    code = "VLM_LOAD_FAILED"
    status = 502
    default_message = "模型加载失败"
    retryable = True


class VideoDecodeError(ServiceError):
    """The video container could not be opened or decoded."""

    code = "VIDEO_DECODE_FAILED"
    status = 422
    default_message = "视频无法解码"


class VideoNoFramesError(ServiceError):
    """Decoding produced no usable frame."""

    code = "VIDEO_NO_FRAMES"
    status = 422
    default_message = "视频中没有可用的画面帧"


