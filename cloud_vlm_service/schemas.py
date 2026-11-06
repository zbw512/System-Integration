"""HTTP request and response schemas for the cloud inference service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cloud_vlm_service.config import PROMPT_VERSION


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImageFrame(StrictModel):
    timestamp_s: float | None = Field(default=None, ge=0)
    mime_type: Literal["image/png"] = "image/png"
    image_base64: str = Field(min_length=1)


class PredictWindowRequest(StrictModel):
    request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    window_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    window_start_s: float = Field(ge=0, allow_inf_nan=False)
    window_end_s: float = Field(gt=0, allow_inf_nan=False)
    prompt_version: str = PROMPT_VERSION
    frames: list[ImageFrame] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_window(self) -> "PredictWindowRequest":
        if self.window_end_s <= self.window_start_s:
            raise ValueError("window_end_s 必须大于 window_start_s")

        timestamps = [
            frame.timestamp_s
            for frame in self.frames
            if frame.timestamp_s is not None
        ]
        if any(
            current + 1e-6 < previous
            for previous, current in zip(timestamps, timestamps[1:])
        ):
            raise ValueError("frames 必须保持时间升序")
        return self


class PredictWindowResponse(StrictModel):
    request_id: str
    window_id: str
    raw_prediction: str
    predicted_label: str
    is_uncertain: bool
    parse_status: str
    model: dict[str, str]
    frame_count: int
    inference_ms: float


class HealthResponse(StrictModel):
    status: str
    loaded: bool
    model: dict[str, str]
    device: str | None
    cuda_available: bool
    gpu_name: str | None
    base_model_present: bool
    adapter_present: bool
    max_frames: int
    load_error: str | None = None


class ErrorDetail(StrictModel):
    code: str
    message: str
    retryable: bool
    request_id: str | None = None


class ErrorResponse(StrictModel):
    error: ErrorDetail
