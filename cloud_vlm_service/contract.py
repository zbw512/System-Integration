"""Fixed scene4 prompt and label parsing contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cloud_vlm_service.config import PROMPT_VERSION

LABELS: tuple[str, ...] = ("听讲", "小组讨论", "独立学习", "其他")
LABEL_PARSE_ORDER: tuple[str, ...] = (
    "小组讨论",
    "独立学习",
    "听讲",
    "其他",
)
UNPARSED_RAW_LABEL = "无法解析"
UNCLASSIFIED_LABEL = "未分类"


@dataclass(frozen=True)
class PredictionParseResult:
    predicted_label: str
    is_uncertain: bool
    parse_status: str
    raw_label: str


def load_prompt(path: Path) -> str:
    """Load the supplied prompt without changing non-whitespace content."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    if not text:
        raise ValueError(f"Prompt 文件为空：{path}")
    return text


def normalize_prediction(text: str) -> PredictionParseResult:
    """Apply the exact containment order used by the owner's scripts."""
    normalized = (text or "").strip().replace(" ", "")
    for label in LABEL_PARSE_ORDER:
        if label in normalized:
            return PredictionParseResult(
                predicted_label=label,
                is_uncertain=False,
                parse_status="parsed",
                raw_label=label,
            )

    return PredictionParseResult(
        predicted_label=UNCLASSIFIED_LABEL,
        is_uncertain=True,
        parse_status="unparseable",
        raw_label=UNPARSED_RAW_LABEL,
    )


def contract_metadata() -> dict[str, object]:
    return {
        "prompt_version": PROMPT_VERSION,
        "labels": list(LABELS),
        "label_parse_order": list(LABEL_PARSE_ORDER),
        "unclassified_label": UNCLASSIFIED_LABEL,
        "raw_unparsed_label": UNPARSED_RAW_LABEL,
        "max_frames": 8,
        "multi_frame_call_count": 1,
        "model_chat_options": {
            "image": None,
            "use_image_id": False,
            "max_slice_nums": 2,
        },
    }
