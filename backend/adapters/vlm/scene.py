"""Parse model answers and turn per-frame labels into standard segments.

Two separate concerns, both pure functions so they can be tested without a model:

* :func:`parse_label_response` — map free text to one of the five allowed labels
  plus the model's own short evidence, with an explicit ``is_uncertain`` flag;
* :func:`build_segments` — merge consecutive identical labels into standard
  ``Segment`` dicts, keeping real sample timestamps as boundaries.

Deliberate limits (documented in the README):

* **confidence is ``None``** — a small VLM's self-reported score is not a
  calibrated probability, so we do not fabricate one;
* boundaries come from **sampling resolution** (e.g. one sample per second), not
  from the model locating scene cuts;
* anything unparseable becomes ``未分类`` with ``is_uncertain=True``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from schemas.enums import SceneLabel
from schemas.segment import Segment
from services.errors import VideoNoFramesError

MAX_EVIDENCE_CHARS = 200

#: Allowed labels, longest first so containment matching prefers "小组讨论".
ALLOWED_LABELS: tuple[str, ...] = tuple(
    sorted((label.value for label in SceneLabel), key=len, reverse=True)
)

_EPSILON = 1e-6
_TRIM_CHARS = " \t\r\n。．.，,；;：:、\"'“”‘’[]【】()（）"
_PREFIX = re.compile(r"^\s*(?:类别|类型|答案|判断|结果|label)\s*[:：]\s*", re.IGNORECASE)


@dataclass(frozen=True)
class LabelParseResult:
    label: str
    evidence: str
    is_uncertain: bool
    matched: bool


@dataclass(frozen=True)
class FrameLabel:
    """One sampled frame's classification."""

    timestamp_s: float
    label: str
    evidence: str = ""
    is_uncertain: bool = False


def _clean(text: str) -> str:
    cleaned = _PREFIX.sub("", text.strip())
    return cleaned.strip(_TRIM_CHARS)


def _match_label(text: str) -> str | None:
    if not text:
        return None
    if text in ALLOWED_LABELS:
        return text
    for label in ALLOWED_LABELS:
        if label in text:
            return label
    return None


def _split_answer(line: str) -> tuple[str, str]:
    """Split ``label|evidence``; fall back to a colon form when needed."""
    normalized = line.replace("｜", "|")
    if "|" in normalized:
        head, _, tail = normalized.partition("|")
        return head, tail
    for separator in ("：", ":"):
        if separator in normalized:
            head, _, tail = normalized.partition(separator)
            return head, tail
    return normalized, ""


def parse_label_response(text: str) -> LabelParseResult:
    """Map one model answer to ``(label, evidence, is_uncertain)``."""
    raw = (text or "").strip()
    if not raw:
        return LabelParseResult(
            label=SceneLabel.UNCLASSIFIED.value,
            evidence="",
            is_uncertain=True,
            matched=False,
        )

    first_line = next((line for line in raw.splitlines() if line.strip()), "")
    head, tail = _split_answer(first_line)

    label = _match_label(_clean(head))
    if label is None:
        # Some answers omit the separator entirely ("听讲").
        label = _match_label(_clean(first_line))

    matched = label is not None
    if label is None:
        label = SceneLabel.UNCLASSIFIED.value

    evidence = _clean(tail)[:MAX_EVIDENCE_CHARS] if tail else ""
    uncertain = (not matched) or label == SceneLabel.UNCLASSIFIED.value

    return LabelParseResult(
        label=label,
        evidence=evidence,
        is_uncertain=uncertain,
        matched=matched,
    )


def _median_interval(timestamps: list[float]) -> float:
    diffs = sorted(
        b - a for a, b in zip(timestamps, timestamps[1:]) if b - a > _EPSILON
    )
    if not diffs:
        return 1.0
    return diffs[len(diffs) // 2]


def _segment_bounds(
    *,
    start: float,
    next_start: float | None,
    duration_s: float | None,
    interval: float,
    floor: float,
) -> tuple[float, float] | None:
    """Compute legal ``(start, end)`` or ``None`` when the video has no room.

    Guarantees ``floor <= start < end <= duration`` (when the duration is known)
    so merged segments can never overlap or run past the end.
    """
    length = interval if interval > _EPSILON else 1.0
    start = max(start, floor)

    if duration_s is not None and duration_s > _EPSILON:
        if start >= duration_s - _EPSILON:
            return None  # the video already ended; this sample has no span
        end = duration_s if next_start is None else min(next_start, duration_s)
        if end <= start:
            end = min(start + length, duration_s)
        if end <= start:
            return None
    else:
        end = (start + length) if next_start is None else next_start
        if end <= start:
            end = start + length

    start_r, end_r = round(start, 3), round(end, 3)
    if end_r <= start_r:
        end_r = round(start_r + 0.001, 3)
    if duration_s is not None:
        end_r = min(end_r, round(duration_s, 3))
        if end_r <= start_r:
            return None
    return start_r, end_r


def build_segments(
    frame_labels: list[FrameLabel], *, duration_s: float | None
) -> list[dict]:
    """Merge consecutive identical labels and emit standard segment dicts."""
    if not frame_labels:
        raise VideoNoFramesError(details={"reason": "no_frame_labels"})

    interval = _median_interval([item.timestamp_s for item in frame_labels])

    runs: list[tuple[str, list[FrameLabel]]] = []
    for item in frame_labels:
        if runs and runs[-1][0] == item.label:
            runs[-1][1].append(item)
        else:
            runs.append((item.label, [item]))

    segments: list[dict] = []
    previous_end = 0.0

    for position, (label, items) in enumerate(runs):
        next_start = (
            runs[position + 1][1][0].timestamp_s if position + 1 < len(runs) else None
        )
        bounds = _segment_bounds(
            start=items[0].timestamp_s,
            next_start=next_start,
            duration_s=duration_s,
            interval=interval,
            floor=previous_end,
        )
        if bounds is None:
            # Degenerate tail sample (e.g. pts == duration): extend the previous
            # segment to the end instead of emitting an overlapping/illegal one.
            if segments and duration_s is not None:
                segments[-1]["end_s"] = round(duration_s, 3)
            continue

        start, end = bounds
        evidence = next((item.evidence for item in items if item.evidence), "")
        segment = Segment(
            index=len(segments),
            start_s=start,
            end_s=end,
            scene_label=label,
            # No calibrated probability exists: never invent one.
            confidence=None,
            evidence=evidence,
            is_uncertain=any(item.is_uncertain for item in items),
        )
        segment.validate(duration_s=duration_s)
        segments.append(segment.to_dict())
        previous_end = end

    return segments
