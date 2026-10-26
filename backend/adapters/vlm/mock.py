"""Mock VLM adapter.

Purpose: prove the *whole* job pipeline (API → service → adapter → storage →
video status) without loading a model or pretending to be MiniCPM.

Hard rules encoded here:

* ``prediction_source`` is ``mock`` — never ``model``;
* ``provider`` and ``model`` names contain ``mock`` so no UI can render the
  result as a real prediction;
* labels are taken from the standard's enum, and every segment is validated
  against the video duration before it leaves the adapter;
* the adapter refuses to invent timings it cannot derive (unknown duration).

The output is deterministic, which is what makes it useful in tests.
"""

from __future__ import annotations

from typing import Any

from adapters.vlm.base import AnalysisOutput, AnalysisRequest, VlmAdapter
from schemas.enums import PredictionSource, SceneLabel
from schemas.segment import Segment
from services.errors import VlmAnalysisError

#: Deterministic label cycle; all values are legal standard labels.
_LABEL_CYCLE = (
    SceneLabel.LECTURE.value,
    SceneLabel.GROUP_DISCUSSION.value,
    SceneLabel.INDEPENDENT_STUDY.value,
)

#: Never pretend to be a real model.
MOCK_PROVIDER = "mock_vlm"
MOCK_MODEL = {
    "name": "mock-vlm",
    "version": "0.1.0-mock",
    "prompt_version": "mock-scene-v1",
}

MOCK_EVIDENCE = "Mock 适配器生成的占位判断依据，不代表真实模型输出"


class MockVlmAdapter(VlmAdapter):
    """Deterministic stand-in for the MiniCPM-V adapter."""

    name = "mock"

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": "mock",
            "provider": MOCK_PROVIDER,
            "prediction_source": PredictionSource.MOCK.value,
            "model": dict(MOCK_MODEL),
            "evaluation_eligible": False,
            "note": "Mock 适配器：仅用于验证任务流程，不代表真实模型推理结果",
        }

    def analyze(self, request: AnalysisRequest) -> AnalysisOutput:
        duration = request.duration_s
        if duration is None or duration <= 0:
            # Refuse to fabricate a timeline for an unknown duration.
            raise VlmAnalysisError(
                "无法从视频容器解析时长，Mock 适配器不会伪造时间段",
                details={"video_id": request.video_id, "reason": "duration_unknown"},
            )

        segments = _build_segments(duration)

        return AnalysisOutput(
            prediction_source=PredictionSource.MOCK.value,
            provider=MOCK_PROVIDER,
            model=dict(MOCK_MODEL),
            segments=segments,
            metadata={
                "is_mock": True,
                "adapter": self.name,
                "note": "Mock 结果，不得作为正式模型评价依据",
            },
        )


def _build_segments(duration_s: float) -> list[dict[str, Any]]:
    """Split the clip into at most three equal, legal segments."""
    window_count = 1 if duration_s < 2 else min(3, max(1, int(duration_s // 1)))
    step = duration_s / window_count

    segments: list[dict[str, Any]] = []
    for index in range(window_count):
        start_s = round(index * step, 3)
        end_s = round(duration_s, 3) if index == window_count - 1 else round((index + 1) * step, 3)
        segment = Segment(
            index=index,
            start_s=start_s,
            end_s=end_s,
            scene_label=_LABEL_CYCLE[index % len(_LABEL_CYCLE)],
            confidence=round(0.55 + 0.1 * (index % 3), 3),
            evidence=MOCK_EVIDENCE,
            is_uncertain=False,
        )
        # Validate before returning: the adapter must never emit an illegal
        # segment, even in mock mode.
        segments.append(segment.validate(duration_s=duration_s).to_dict())
    return segments
