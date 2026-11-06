from __future__ import annotations

import pytest

from adapters.vlm.scene4 import LABELS, PARSE_ORDER, parse_scene4_prediction


def test_scene4_labels_match_owner_script() -> None:
    assert LABELS == ("听讲", "小组讨论", "独立学习", "其他")
    assert PARSE_ORDER == ("小组讨论", "独立学习", "听讲", "其他")


@pytest.mark.parametrize("label", ["听讲", "小组讨论", "独立学习", "其他"])
def test_parse_preserves_valid_label(label: str) -> None:
    parsed = parse_scene4_prediction(f"  {label}  ")
    assert parsed.label == label
    assert parsed.is_uncertain is False
    assert parsed.parse_status == "parsed"


def test_group_discussion_is_matched_before_shorter_labels() -> None:
    assert parse_scene4_prediction("小组讨论学生围坐").label == "小组讨论"


@pytest.mark.parametrize("raw", ["", "无法判断", "unknown", "???"])
def test_unparseable_becomes_unclassified_not_other(raw: str) -> None:
    parsed = parse_scene4_prediction(raw)
    assert parsed.label == "未分类"
    assert parsed.label != "其他"
    assert parsed.is_uncertain is True
    assert parsed.parse_status == "unparseable"
