"""MiniCPM-V 4.5 + scene4/checkpoint-600 AutoDL adapter."""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

from adapters.vlm.base import AnalysisOutput, AnalysisRequest, VlmAdapter
from adapters.vlm.remote_client import RemoteVlmClient
from adapters.vlm.scene4 import parse_scene4_prediction
from adapters.vlm.window_frames import decode_video_windows
from config import Config, VLM45_PROMPT_VERSION, VLM_WINDOW_POLICY_ID
from schemas.enums import JobStage, PredictionSource, SceneLabel
from schemas.segment import Segment
from services.errors import VlmRemoteConfigurationError

logger = logging.getLogger(__name__)


class MiniCPMV45RemoteAdapter(VlmAdapter):
    """Call the AutoDL service once for each independently sampled window."""

    name = "minicpm_remote"
    provider = "minicpm_v"
    uses_frame_sampling = True

    def __init__(
        self,
        config: Config,
        *,
        client: RemoteVlmClient | None = None,
    ) -> None:
        self._config = config
        self._client = client or RemoteVlmClient(config)

    @property
    def model_info(self) -> dict[str, Any]:
        return {
            "name": "MiniCPM-V",
            "version": "4.5",
            "finetune": "scene4",
            "checkpoint": "checkpoint-600",
            "prompt_version": VLM45_PROMPT_VERSION,
            "adapter": self.name,
            "runtime": "autodl_remote",
        }

    def describe(self) -> dict[str, Any]:
        configured = bool(
            self._config.vlm_remote_url
            and self._config.vlm_remote_token
            and len(self._config.vlm_remote_token) >= 32
        )
        return {
            "name": self.name,
            "status": "configured" if configured else "unavailable",
            "provider": self.provider,
            "prediction_source": PredictionSource.MODEL.value,
            "model": self.model_info,
            "remote": True,
            "endpoint": self._config.vlm_remote_url,
            "loaded": None,
            "health_checked": False,
            "sampling": {
                "max_frames": self._config.vlm_max_frames,
                "window_seconds": self._config.vlm_window_seconds,
                "stride_seconds": self._config.vlm_window_stride_seconds,
                "max_duration_s": self._config.vlm_max_duration_s,
                "tail_strategy": "retain_short_window",
                "merge_adjacent_segments": False,
                "policy_id": VLM_WINDOW_POLICY_ID,
                "provisional": True,
            },
            "note": (
                "真实 MiniCPM-V 4.5 + LoRA 通过 AutoDL 推理；"
                "服务不可用时任务直接失败，不会回退 Mock。"
            ),
        }

    def analyze(self, request: AnalysisRequest) -> AnalysisOutput:
        if not 1 <= self._config.vlm_max_frames <= 8:
            raise VlmRemoteConfigurationError(
                "MiniCPM-V 4.5 最多允许 8 帧"
            )
        if self._config.vlm_window_stride_seconds < self._config.vlm_window_seconds:
            raise VlmRemoteConfigurationError("初版不支持重叠窗口")

        reporter = request.on_progress
        if reporter is not None:
            reporter(JobStage.SAMPLING_FRAMES.value, 0.2)

        decoded = decode_video_windows(
            request.video_path,
            duration_hint_s=request.duration_s,
            window_seconds=self._config.vlm_window_seconds,
            stride_seconds=self._config.vlm_window_stride_seconds,
            max_frames=self._config.vlm_max_frames,
            max_duration_s=self._config.vlm_max_duration_s,
            policy_id=VLM_WINDOW_POLICY_ID,
        )

        segments: list[dict[str, Any]] = []
        window_results: list[dict[str, Any]] = []
        total = len(decoded.windows)

        for window in decoded.windows:
            if reporter is not None:
                reporter(
                    JobStage.INFERENCE.value,
                    round(0.35 + 0.4 * window.index / total, 3),
                )

            request_id = f"{request.job_id}-w{window.index:04d}"
            window_id = f"{request.video_id}-w{window.index:04d}"
            frame_payloads = [
                {
                    "timestamp_s": frame.timestamp_s,
                    "mime_type": "image/png",
                    "image_base64": _encode_png_base64(frame.image),
                }
                for frame in window.frames
            ]

            prediction = self._client.predict_window(
                request_id=request_id,
                window_id=window_id,
                window_start_s=window.start_s,
                window_end_s=window.end_s,
                frames=frame_payloads,
            )
            parsed = parse_scene4_prediction(prediction.raw_prediction)
            if (
                prediction.remote_predicted_label is not None
                and prediction.remote_predicted_label != parsed.label
            ):
                logger.warning(
                    "remote/local parse mismatch request_id=%s remote=%s local=%s",
                    request_id,
                    prediction.remote_predicted_label,
                    parsed.label,
                )

            segment = Segment(
                index=window.index,
                start_s=window.start_s,
                end_s=window.end_s,
                scene_label=parsed.label,
                confidence=None,
                evidence="",
                is_uncertain=parsed.is_uncertain,
            ).validate(duration_s=decoded.duration_s or request.duration_s)
            segments.append(segment.to_dict())
            window_results.append(
                {
                    "window_index": window.index,
                    "start_s": window.start_s,
                    "end_s": window.end_s,
                    "short_tail": window.end_s - window.start_s
                    < self._config.vlm_window_seconds - 1e-6,
                    "frame_count": len(window.frames),
                    "frame_timestamps_s": [
                        frame.timestamp_s for frame in window.frames
                    ],
                    "raw_prediction": prediction.raw_prediction,
                    "predicted_label": parsed.label,
                    "parse_status": parsed.parse_status,
                    "is_uncertain": parsed.is_uncertain,
                    "remote_inference_ms": prediction.inference_ms,
                    "request_id": request_id,
                }
            )

            logger.info(
                "window inferred request_id=%s index=%d/%d frames=%d label=%s uncertain=%s inference_ms=%.2f",
                request_id,
                window.index + 1,
                total,
                len(window.frames),
                parsed.label,
                parsed.is_uncertain,
                prediction.inference_ms,
            )
            if parsed.is_uncertain:
                logger.warning(
                    "unparseable remote output request_id=%s raw_preview=%r",
                    request_id,
                    prediction.raw_prediction[:200],
                )
            if reporter is not None:
                reporter(
                    JobStage.INFERENCE.value,
                    round(0.35 + 0.4 * (window.index + 1) / total, 3),
                )

        return AnalysisOutput(
            prediction_source=PredictionSource.MODEL.value,
            provider=self.provider,
            model=self.model_info,
            segments=segments,
            metadata={
                "is_mock": False,
                "adapter": self.name,
                "runtime": "autodl_remote",
                "window_policy": {
                    "id": decoded.policy_id,
                    "provisional": True,
                    "window_seconds": self._config.vlm_window_seconds,
                    "stride_seconds": self._config.vlm_window_stride_seconds,
                    "max_frames": self._config.vlm_max_frames,
                    "max_duration_s": self._config.vlm_max_duration_s,
                    "tail_strategy": "retain_short_window",
                    "overlap": False,
                    "merge_adjacent_segments": False,
                },
                "window_count": total,
                "decoded_duration_s": decoded.duration_s,
                "video_fps": decoded.fps,
                "video_size": (
                    [decoded.width, decoded.height]
                    if decoded.width and decoded.height
                    else None
                ),
                "windows": window_results,
                "confidence_note": "模型未提供可校准置信度，confidence 置空",
            },
        )


def _encode_png_base64(image: Any) -> str:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")
