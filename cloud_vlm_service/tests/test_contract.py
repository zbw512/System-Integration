from __future__ import annotations

from pathlib import Path

from cloud_vlm_service.contract import (
    LABEL_PARSE_ORDER,
    LABELS,
    UNCLASSIFIED_LABEL,
    load_prompt,
    normalize_prediction,
)

EXPECTED_PROMPT = (
    "仅依据视频画面，判断班级当前的主要学习场景。\n"
    "候选类别：听讲、小组讨论、独立学习、其他。\n"
    "只输出一个类别名称，不要解释。"
)


def test_prompt_matches_owner_script_exactly() -> None:
    prompt_path = Path(__file__).parents[1] / "prompt_scene4.txt"
    assert load_prompt(prompt_path) == EXPECTED_PROMPT


def test_contract_constants_match_owner_script() -> None:
    assert LABELS == ("听讲", "小组讨论", "独立学习", "其他")
    assert LABEL_PARSE_ORDER == ("小组讨论", "独立学习", "听讲", "其他")


def test_prediction_labels_are_parsed_in_owner_order() -> None:
    for label in LABELS:
        parsed = normalize_prediction(f"  {label}  ")
        assert parsed.predicted_label == label
        assert parsed.is_uncertain is False
        assert parsed.parse_status == "parsed"


def test_group_discussion_is_not_misread_as_other_label() -> None:
    parsed = normalize_prediction("小组讨论学生围坐")
    assert parsed.predicted_label == "小组讨论"


def test_unparseable_output_becomes_unclassified_and_uncertain() -> None:
    parsed = normalize_prediction("模型无法给出结果")
    assert parsed.predicted_label == UNCLASSIFIED_LABEL
    assert parsed.is_uncertain is True
    assert parsed.parse_status == "unparseable"
    assert parsed.raw_label == "无法解析"
