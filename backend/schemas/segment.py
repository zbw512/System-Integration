"""``Segment`` schema — interface standard section 3.2.

Validation is centralised here so the VLM adapter (P0-6) cannot emit an
out-of-range segment and the API can never serve one.

Rules enforced by :meth:`Segment.validate`:

* ``index >= 0``;
* ``0 <= start_s < end_s``;
* ``end_s`` must not exceed the video duration (when the duration is known);
* ``confidence`` is ``None`` or within ``0.0–1.0``;
* ``scene_label`` is one of the recommended labels;
* ``evidence`` is a short string (the standard forbids dumping the raw model
  answer into it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from schemas.enums import SceneLabel, enum_values

MAX_EVIDENCE_LENGTH = 500


class SegmentValidationError(ValueError):
    """Raised when a segment violates the standard's constraints."""

    def __init__(self, message: str, *, field: str) -> None:
        self.field = field
        super().__init__(message)


@dataclass
class Segment:
    index: int
    start_s: float
    end_s: float
    scene_label: str
    confidence: float | None = None
    evidence: str = ""
    is_uncertain: bool = False

    def validate(self, duration_s: float | None = None) -> "Segment":
        """Validate in place and return ``self`` for chaining."""
        if not isinstance(self.index, int) or self.index < 0:
            raise SegmentValidationError("index 必须是非负整数", field="index")

        if not isinstance(self.start_s, (int, float)) or self.start_s < 0:
            raise SegmentValidationError("start_s 必须是非负数", field="start_s")

        if not isinstance(self.end_s, (int, float)):
            raise SegmentValidationError("end_s 必须是数字", field="end_s")

        if self.end_s <= self.start_s:
            raise SegmentValidationError(
                "end_s 必须大于 start_s", field="end_s"
            )

        if duration_s is not None and self.end_s > duration_s + 1e-6:
            raise SegmentValidationError(
                "end_s 超出视频时长", field="end_s"
            )

        if self.confidence is not None:
            if not isinstance(self.confidence, (int, float)) or not (
                0.0 <= float(self.confidence) <= 1.0
            ):
                raise SegmentValidationError(
                    "confidence 必须在 0.0 到 1.0 之间", field="confidence"
                )

        if self.scene_label not in enum_values(SceneLabel):
            raise SegmentValidationError(
                "scene_label 不是推荐标签", field="scene_label"
            )

        if not isinstance(self.evidence, str) or len(self.evidence) > MAX_EVIDENCE_LENGTH:
            raise SegmentValidationError(
                f"evidence 必须是长度不超过 {MAX_EVIDENCE_LENGTH} 的字符串",
                field="evidence",
            )

        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start_s": float(self.start_s),
            "end_s": float(self.end_s),
            "scene_label": self.scene_label,
            "confidence": None if self.confidence is None else float(self.confidence),
            "evidence": self.evidence,
            "is_uncertain": bool(self.is_uncertain),
        }
