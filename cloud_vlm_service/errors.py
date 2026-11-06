"""Safe service-level exceptions exposed as structured HTTP errors."""

from __future__ import annotations


class ServiceError(Exception):
    code = "VLM_SERVICE_ERROR"
    status_code = 500
    retryable = False
    public_message = "视觉模型服务异常"

    def __init__(
        self,
        message: str | None = None,
        *,
        retryable: bool | None = None,
    ) -> None:
        self.public_message = message or self.public_message
        if retryable is not None:
            self.retryable = retryable
        super().__init__(self.public_message)


class ModelAssetsMissingError(ServiceError):
    code = "VLM_MODEL_FILES_MISSING"
    status_code = 503
    public_message = "MiniCPM-V 4.5 基座或 LoRA 文件不完整"


class ModelLoadError(ServiceError):
    code = "VLM_MODEL_LOAD_FAILED"
    status_code = 503
    retryable = True
    public_message = "MiniCPM-V 4.5 模型加载失败"


class InferenceError(ServiceError):
    code = "VLM_INFERENCE_FAILED"
    status_code = 502
    retryable = True
    public_message = "MiniCPM-V 推理失败"


class InvalidFrameError(ServiceError):
    code = "VLM_INVALID_FRAME"
    status_code = 422
    public_message = "请求中的图片帧不合法"
