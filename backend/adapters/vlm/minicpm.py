"""Real MiniCPM-V 4.6 adapter (P0-5).

Pipeline (all inside :meth:`analyze`):

1. verify the local model directory exists;
2. decode the stored video and sample frames **with real timestamps**
   (:mod:`adapters.vlm.frames`, PyAV backend);
3. lazily load the model once (``bfloat16`` + ``sdpa`` on CUDA) and reuse it for
   every later job — nothing is loaded at Flask import time;
4. classify each sampled frame with a tightly constrained prompt, one image per
   generation call;
5. parse the answer to one of the five standard labels plus the model's own
   short evidence (:mod:`adapters.vlm.scene`);
6. merge consecutive identical labels into standard ``segments``.

Deliberate boundaries (also in README):

* the model classifies **sample points**; segment borders are the sampling
  resolution, not model-detected scene cuts;
* ``confidence`` is ``None`` because no calibrated probability is available;
* labels are scene categories only — they must not be read as attention or
  psychological state;
* a failure raises a domain error and the job becomes ``failed``. There is
  **no** fallback to mock labels.

Verified locally on 2026-10-24 with transformers 5.19.0 / torch 2.13.0+cu126 /
RTX 4060 Laptop: model load ~7 s, ~1.7–2.2 s per frame, ~2.5 GiB VRAM.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from adapters.vlm.base import AnalysisOutput, AnalysisRequest, VlmAdapter
from adapters.vlm.frames import sample_frames
from adapters.vlm.scene import FrameLabel, build_segments, parse_label_response
from config import Config
from schemas.enums import JobStage, PredictionSource
from services.errors import VlmAnalysisError, VlmLoadFailedError, VlmModelNotFoundError

logger = logging.getLogger(__name__)

#: Prompt version recorded on every result (bump when the prompt changes).
PROMPT_VERSION = "scene-zh-v1"

SCENE_PROMPT = (
    "你是一名课堂观察员。只根据这张课堂视频截图的可见内容，判断当前学习场景类别。\n"
    "类别只能是：听讲、小组讨论、独立学习、其他、未分类。\n"
    "只输出一行，格式为：类别|不超过20字的可见依据。\n"
    "如果画面无法判断，输出：未分类|画面信息不足"
)

#: Vision-token settings verified against this transformers build.
_DOWNSAMPLE_MODE = "16x"
_MAX_SLICE_NUMS = 1


class MiniCPMV46Adapter(VlmAdapter):
    """Adapter around the local ``MiniCPM-V-4.6`` checkpoint."""

    name = "minicpm_v"
    provider = "minicpm_v"
    uses_frame_sampling = True

    MODEL_NAME = "MiniCPM-V"
    MODEL_VERSION = "4.6"

    def __init__(self, config: Config) -> None:
        self._config = config
        self._model_path = os.path.abspath(config.vlm_model_path)
        self._processor: Any = None
        self._model: Any = None
        self._device: str | None = None
        self._load_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    def describe(self) -> dict[str, Any]:
        present = self._model_present()
        return {
            "name": self.name,
            "status": "configured" if present else "unavailable",
            "provider": self.provider,
            "prediction_source": PredictionSource.MODEL.value,
            "model": self.model_info,
            "device": self._config.vlm_device,
            "model_path_present": present,
            "loaded": self._model is not None,
            "sampling": {
                "max_frames": self._config.vlm_max_frames,
                "interval_s": self._config.vlm_frame_interval_s,
                "max_duration_s": self._config.vlm_max_duration_s,
            },
            "note": (
                "真实 MiniCPM-V 4.6 适配器；模型在首个任务执行时按需加载并在进程内复用。"
                if present
                else "未找到本地模型目录或权重，真实推理任务会失败（不会回退到 mock）"
            ),
        }

    @property
    def model_info(self) -> dict[str, Any]:
        return {
            "name": self.MODEL_NAME,
            "version": self.MODEL_VERSION,
            "prompt_version": PROMPT_VERSION,
        }

    def _model_present(self) -> bool:
        if not os.path.isdir(self._model_path):
            return False
        if not os.path.isfile(os.path.join(self._model_path, "config.json")):
            return False
        return any(
            name.startswith("model") and name.endswith(".safetensors")
            for name in os.listdir(self._model_path)
        )

    # ------------------------------------------------------------------ #
    # Analysis
    # ------------------------------------------------------------------ #
    def analyze(self, request: AnalysisRequest) -> AnalysisOutput:
        self._ensure_model_present()
        reporter = request.on_progress

        if reporter is not None:
            reporter(JobStage.SAMPLING_FRAMES.value, 0.2)

        sampling = sample_frames(
            request.video_path,
            interval_s=self._config.vlm_frame_interval_s,
            max_frames=self._config.vlm_max_frames,
            max_duration_s=self._config.vlm_max_duration_s,
        )
        logger.info(
            "sampled %d frames (duration=%s, fps=%s)",
            sampling.count,
            sampling.duration_s,
            sampling.fps,
        )

        processor, model, device = self._ensure_loaded()

        frame_labels: list[FrameLabel] = []
        total = max(1, sampling.count)


        for position, frame in enumerate(sampling.frames):
            raw = self._generate(processor, model, device, frame.image)
            parsed = parse_label_response(raw)

            frame_labels.append(
                FrameLabel(
                    timestamp_s=frame.timestamp_s,
                    label=parsed.label,
                    evidence=parsed.evidence,
                    is_uncertain=parsed.is_uncertain,
                )
            )
            if reporter is not None:
                # Inference spans 0.35 -> 0.75; the runner then reports parsing.
                reporter(
                    JobStage.INFERENCE.value,
                    round(0.35 + 0.4 * (position + 1) / total, 3),
                )



            if reporter is not None:
                # Inference spans 0.35 -> 0.75; the runner then reports parsing.
                reporter(
                    JobStage.INFERENCE.value,
                    round(0.35 + 0.4 * (position + 1) / total, 3),
                )

        duration_s = sampling.duration_s if sampling.duration_s is not None else request.duration_s
        segments = build_segments(frame_labels, duration_s=duration_s)

        return AnalysisOutput(
            prediction_source=PredictionSource.MODEL.value,
            provider=self.provider,
            model=self.model_info,
            segments=segments,
            metadata={
                "is_mock": False,
                "adapter": self.name,
                "prompt_version": PROMPT_VERSION,
                "device": device,
                "frame_count": sampling.count,
                "frame_timestamps_s": [frame.timestamp_s for frame in sampling.frames],
                "sampling": {
                    "interval_s": self._config.vlm_frame_interval_s,
                    "max_frames": self._config.vlm_max_frames,
                    "max_duration_s": self._config.vlm_max_duration_s,
                },
                "decoded_duration_s": sampling.duration_s,
                "video_fps": sampling.fps,
                "video_size": (
                    [sampling.width, sampling.height]
                    if sampling.width and sampling.height
                    else None
                ),
                "label_counts": _count_labels(frame_labels),
                "confidence_note": "模型未提供可校准置信度，confidence 置空",
                "boundary_note": "分段边界来自采样分辨率，不是模型检测的场景切换点",
            },
        )

    # ------------------------------------------------------------------ #
    # Model plumbing
    # ------------------------------------------------------------------ #
    def _ensure_model_present(self) -> None:
        if not self._model_present():
            raise VlmModelNotFoundError(
                details={
                    "reason": "model_missing",
                    "model": self.MODEL_NAME,
                    "version": self.MODEL_VERSION,
                }
            )

    def _resolve_device(self) -> str:
        requested = (self._config.vlm_device or "cuda").strip().lower()
        if not requested.startswith("cuda"):
            # CPU inference is neither implemented nor verified; say so instead
            # of silently running 100x slower and calling it supported.
            raise VlmLoadFailedError(
                "本实现仅支持 CUDA 设备，未提供 CPU 回退",
                details={"requested_device": requested, "reason": "unsupported_device"},
            )
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - environment guard
            raise VlmLoadFailedError(
                "缺少 torch", details={"reason": "dependency_missing"}
            ) from exc
        if not torch.cuda.is_available():
            raise VlmLoadFailedError(
                "未检测到可用的 CUDA 设备",
                details={"reason": "cuda_unavailable", "requested_device": requested},
            )
        return requested

    def _ensure_loaded(self) -> tuple[Any, Any, str]:
        if self._model is not None and self._processor is not None:
            return self._processor, self._model, self._device or "cuda"

        with self._load_lock:
            if self._model is not None and self._processor is not None:
                return self._processor, self._model, self._device or "cuda"

            device = self._resolve_device()
            try:
                import torch
                from transformers import AutoModelForImageTextToText, AutoProcessor
            except ImportError as exc:  # pragma: no cover - environment guard
                raise VlmLoadFailedError(
                    "缺少 transformers 或 torch",
                    details={"reason": "dependency_missing"},
                ) from exc

            try:
                processor = AutoProcessor.from_pretrained(
                    self._model_path, local_files_only=True
                )
                model = (
                    AutoModelForImageTextToText.from_pretrained(
                        self._model_path,
                        torch_dtype=torch.bfloat16,
                        attn_implementation="sdpa",
                        local_files_only=True,
                    )
                    .eval()
                    .to(device)
                )
            except Exception as exc:
                logger.exception("failed to load MiniCPM-V model")
                raise VlmLoadFailedError(
                    details={"reason": "load_failed", "error_type": type(exc).__name__}
                ) from exc

            self._processor, self._model, self._device = processor, model, device
            logger.info("MiniCPM-V loaded on %s", device)
            return processor, model, device

    def _generate(self, processor: Any, model: Any, device: str, image: Any) -> str:
        import torch

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": SCENE_PROMPT},
                ],
            }
        ]

        try:
            inputs = processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
                # transformers >= 5 routes processor kwargs through this dict;
                # verified with 5.19.0 (passing them flat triggers a warning and
                # the placeholder count may disagree with the vision encoder).
                processor_kwargs={
                    "max_slice_nums": _MAX_SLICE_NUMS,
                    "downsample_mode": _DOWNSAMPLE_MODE,
                },
            ).to(device)

            with torch.inference_mode():
                generated = model.generate(
                    **inputs,
                    max_new_tokens=self._config.vlm_max_new_tokens,
                    do_sample=False,
                    downsample_mode=_DOWNSAMPLE_MODE,
                )
        except Exception as exc:
            logger.exception("MiniCPM-V generation failed")
            raise VlmAnalysisError(
                details={"reason": "generation_failed", "error_type": type(exc).__name__}
            ) from exc

        prompt_length = inputs["input_ids"].shape[-1]
        return processor.batch_decode(
            generated[:, prompt_length:], skip_special_tokens=True
        )[0]


def _count_labels(frame_labels: list[FrameLabel]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in frame_labels:
        counts[item.label] = counts.get(item.label, 0) + 1
    return counts
