"""Unit tests for label parsing and segment building (no model involved)."""

from __future__ import annotations

import pytest

from adapters.vlm.scene import (
    ALLOWED_LABELS,
    FrameLabel,
    build_segments,
    parse_label_response,
)
from schemas.enums import SceneLabel
from services.errors import VideoNoFramesError


# --------------------------------------------------------------------------- #
# parse_label_response
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "label", "evidence", "uncertain"),
    [
        ("听讲|学生面向讲台", "听讲", "学生面向讲台", False),
        ("小组讨论｜学生围坐交流", "小组讨论", "学生围坐交流", False),
        ("独立学习|学生在阅读", "独立学习", "学生在阅读", False),
        ("其他|画面主体不是学生", "其他", "画面主体不是学生", False),
        ("未分类|画面信息不足", "未分类", "画面信息不足", True),
        ("听讲", "听讲", "", False),
        ("类别：独立学习|阅读课本", "独立学习", "阅读课本", False),
        ("  听讲 ： 学生听讲  ", "听讲", "学生听讲", False),
        ("这张图是小组讨论|学生围坐", "小组讨论", "学生围坐", False),
    ],
)
def test_parse_label_response(text, label, evidence, uncertain):
    parsed = parse_label_response(text)

    assert parsed.label == label
    assert parsed.evidence == evidence
    assert parsed.is_uncertain is uncertain


def test_allowed_labels_cover_the_standard_enum():
    assert set(ALLOWED_LABELS) == {label.value for label in SceneLabel}
    assert len(ALLOWED_LABELS) == 5


@pytest.mark.parametrize("text", ["", "   ", "无法判断", "the scene is unclear", "???"])
def test_unparseable_answer_becomes_unclassified_and_uncertain(text):
    parsed = parse_label_response(text)

    assert parsed.label == "未分类"
    assert parsed.is_uncertain is True
    assert parsed.matched is False


def test_evidence_is_truncated_to_a_readable_length():
    parsed = parse_label_response("听讲|" + "依" * 500)

    assert parsed.label == "听讲"
    assert len(parsed.evidence) == 200


def test_multiline_answer_uses_first_non_empty_line():
    parsed = parse_label_response("\n\n听讲|学生听课\n补充说明：画面稳定")

    assert parsed.label == "听讲"
    assert parsed.evidence == "学生听课"


def test_fullwidth_separator_is_supported():
    assert parse_label_response("听讲｜学生举手").label == "听讲"


# --------------------------------------------------------------------------- #
# build_segments
# --------------------------------------------------------------------------- #
def labels(*items) -> list[FrameLabel]:
    return [
        FrameLabel(
            timestamp_s=timestamp,
            label=label,
            evidence=evidence,
            is_uncertain=uncertain,
        )
        for timestamp, label, evidence, uncertain in items
    ]


def test_consecutive_identical_labels_are_merged():
    segments = build_segments(
        labels(
            (0.0, "听讲", "老师面向学生", False),
            (1.0, "听讲", "", False),
            (2.0, "小组讨论", "学生围坐", False),
        ),
        duration_s=3.0,
    )

    assert len(segments) == 2
    assert segments[0] == {
        "index": 0,
        "start_s": 0.0,
        "end_s": 2.0,
        "scene_label": "听讲",
        "confidence": None,
        "evidence": "老师面向学生",
        "is_uncertain": False,
    }
    assert segments[1]["start_s"] == 2.0
    assert segments[1]["end_s"] == 3.0
    assert segments[1]["index"] == 1


def test_last_segment_ends_at_video_duration():
    segments = build_segments(
        labels((0.0, "听讲", "", False), (1.0, "独立学习", "", False)), duration_s=3.0
    )

    assert segments[-1]["end_s"] == 3.0


def test_confidence_is_never_fabricated():
    segments = build_segments(labels((0.0, "听讲", "", False)), duration_s=3.0)

    assert segments[0]["confidence"] is None


def test_uncertainty_propagates_from_any_frame_in_the_run():
    segments = build_segments(
        labels(
            (0.0, "未分类", "", True),
            (1.0, "未分类", "", True),
            (2.0, "听讲", "", False),
        ),
        duration_s=3.0,
    )

    assert segments[0]["is_uncertain"] is True
    assert segments[1]["is_uncertain"] is False


def test_unknown_duration_uses_sampling_interval():
    segments = build_segments(
        labels((0.0, "听讲", "", False), (1.0, "小组讨论", "", False)), duration_s=None
    )

    assert segments[0]["start_s"] == 0.0
    assert segments[0]["end_s"] == 1.0
    assert segments[1]["start_s"] == 1.0
    assert segments[1]["end_s"] == 2.0


def test_sample_exactly_at_duration_does_not_create_overlap():
    segments = build_segments(
        labels((0.0, "听讲", "", False), (3.0, "小组讨论", "", False)), duration_s=3.0
    )

    assert len(segments) == 1
    assert segments[0]["start_s"] == 0.0
    assert segments[0]["end_s"] == 3.0


@pytest.mark.parametrize("duration", [0.5, 1.0, 3.0, 10.0, 60.0])
def test_segments_stay_inside_the_video(duration):
    timestamps = [0.0] + [duration / 2, duration]
    frame_labels = labels(
        (0.0, "听讲", "", False),
        (timestamps[1], "小组讨论", "", False),
        (timestamps[2], "独立学习", "", False),
    )

    segments = build_segments(frame_labels, duration_s=duration)

    previous_end = 0.0
    for segment in segments:
        assert 0.0 <= segment["start_s"] < segment["end_s"] <= duration + 1e-6
        assert segment["start_s"] >= previous_end - 1e-6
        previous_end = segment["end_s"]


def test_empty_labels_are_rejected():
    with pytest.raises(VideoNoFramesError):
        build_segments([], duration_s=3.0)
