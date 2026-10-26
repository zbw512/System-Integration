"""Unit tests for the ``Segment`` schema (standard section 3.2).

The VLM adapter (P0-6) will emit segments through this validator, so the rules
are pinned down before any model output exists.
"""

from __future__ import annotations

import pytest

from schemas.segment import Segment, SegmentValidationError


def make_segment(**overrides) -> Segment:
    payload = {
        "index": 0,
        "start_s": 0.0,
        "end_s": 3.0,
        "scene_label": "听讲",
        "confidence": 0.82,
        "evidence": "教师面向学生讲授",
        "is_uncertain": False,
    }
    payload.update(overrides)
    return Segment(**payload)


def test_valid_segment_serializes_to_standard_shape():
    segment = make_segment().validate(duration_s=3.0)

    assert segment.to_dict() == {
        "index": 0,
        "start_s": 0.0,
        "end_s": 3.0,
        "scene_label": "听讲",
        "confidence": 0.82,
        "evidence": "教师面向学生讲授",
        "is_uncertain": False,
    }


def test_uncertain_unclassified_segment_is_allowed():
    segment = make_segment(scene_label="未分类", confidence=None, is_uncertain=True)

    assert segment.validate(duration_s=3.0).to_dict()["is_uncertain"] is True


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"end_s": 0.0}, "end_s"),
        ({"end_s": -1.0}, "end_s"),
        ({"start_s": -0.1}, "start_s"),
        ({"index": -1}, "index"),
        ({"end_s": 4.0}, "end_s"),
        ({"confidence": 1.5}, "confidence"),
        ({"confidence": -0.1}, "confidence"),
        ({"scene_label": "吃饭"}, "scene_label"),
        ({"evidence": "x" * 501}, "evidence"),
    ],
)
def test_invalid_segments_are_rejected(overrides, field):
    segment = make_segment(**overrides)

    with pytest.raises(SegmentValidationError) as excinfo:
        segment.validate(duration_s=3.0)

    assert excinfo.value.field == field


def test_duration_check_is_skipped_when_unknown():
    # duration_s missing => only the start/end ordering is enforced.
    assert make_segment(end_s=120.0).validate(duration_s=None).to_dict()["end_s"] == 120.0
