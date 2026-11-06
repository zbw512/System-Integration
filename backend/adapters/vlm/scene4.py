"""Fixed scene4 label parsing used by MiniCPM-V 4.5 inference."""

from __future__ import annotations

from dataclasses import dataclass

from schemas.enums import SceneLabel

LABELS: tuple[str, ...] = (
    SceneLabel.LECTURE.value,
    SceneLabel.GROUP_DISCUSSION.value,
    SceneLabel.INDEPENDENT_STUDY.value,
    SceneLabel.OTHER.value,
)
PARSE_ORDER: tuple[str, ...] = (
    SceneLabel.GROUP_DISCUSSION.value,
    SceneLabel.INDEPENDENT_STUDY.value,
    SceneLabel.LECTURE.value,
    SceneLabel.OTHER.value,
)


@dataclass(frozen=True)
class Scene4ParseResult:
    label: str
    is_uncertain: bool
    parse_status: str
    raw_label: str


def parse_scene4_prediction(text: str) -> Scene4ParseResult:
    """Exactly mirror the owner's containment matching order."""
    normalized = (text or "").strip().replace(" ", "")
    for label in PARSE_ORDER:
        if label in normalized:
            return Scene4ParseResult(
                label=label,
                is_uncertain=False,
                parse_status="parsed",
                raw_label=label,
            )
    return Scene4ParseResult(
        label=SceneLabel.UNCLASSIFIED.value,
        is_uncertain=True,
        parse_status="unparseable",
        raw_label="无法解析",
    )
