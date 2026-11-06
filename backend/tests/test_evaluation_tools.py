"""Deterministic validation-set builder and offline metric tests."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_scene4_val_jsonl import build_records, write_jsonl
from evaluate_cloud_model import (
    EvaluationSample,
    classification_metrics,
    write_outputs,
)


def test_validation_builder_uses_csv_labels_without_guessing(
    tmp_path: Path,
) -> None:
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    (video_dir / "clip_b.mp4").write_bytes(b"b")
    (video_dir / "clip_a.mp4").write_bytes(b"a")
    csv_path = tmp_path / "val.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["clip_id", "video_relpath", "scene_label"])
        writer.writerow(["clip_b", "ignored.mp4", "小组讨论"])
        writer.writerow(["clip_a", "ignored.mp4", "听讲"])

    prompt = "固定 Prompt"
    records = build_records(
        csv_path=csv_path,
        video_dir=video_dir,
        prompt=prompt,
        expected_count=2,
    )

    assert [Path(item["videos"][0]).stem for item in records] == [
        "clip_a",
        "clip_b",
    ]
    assert records[0]["messages"][0]["content"] == "<video>\n固定 Prompt"
    assert records[0]["messages"][1]["content"] == "听讲"
    assert records[1]["messages"][1]["content"] == "小组讨论"

    output = tmp_path / "val.jsonl"
    write_jsonl(records, output)
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2


def test_metrics_exclude_infrastructure_errors_and_unparsed() -> None:
    metrics, per_class, matrix = classification_metrics(
        y_true=["听讲", "听讲", "小组讨论", "独立学习"],
        y_pred=["听讲", "其他", "听讲", "无法解析"],
        infrastructure_errors=["", "", "", ""],
    )

    assert metrics["total_samples"] == 4
    assert metrics["parsed_samples"] == 3
    assert metrics["unparsed_samples"] == 1
    assert metrics["strict_accuracy"] == 0.25
    assert metrics["parsed_accuracy"] == 0.333333
    assert metrics["macro_f1"] == 0.125
    assert per_class["听讲"]["precision"] == 0.5
    assert per_class["听讲"]["recall"] == 0.5
    assert matrix[0] == [1, 0, 0, 1]


def test_metrics_separate_infrastructure_errors() -> None:
    metrics, _, _ = classification_metrics(
        y_true=["听讲", "听讲"],
        y_pred=["听讲", ""],
        infrastructure_errors=["", "TimeoutError: timed out"],
    )
    assert metrics["parsed_samples"] == 1
    assert metrics["unparsed_samples"] == 0
    assert metrics["infrastructure_errors"] == 1


def test_outputs_include_required_metric_files(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    samples = [
        EvaluationSample(1, "clip", video, "听讲"),
        EvaluationSample(2, "clip2", video, "独立学习"),
    ]
    write_outputs(
        output_dir=tmp_path / "out",
        samples=samples,
        y_pred=["听讲", "无法解析"],
        raw_predictions=["听讲", "unknown"],
        errors=["", ""],
        inference_ms=[10.0, 11.0],
    )

    for name in (
        "metrics.json",
        "per_class_metrics.json",
        "confusion_matrix.json",
        "classification_report.txt",
        "predictions.csv",
        "errors.csv",
    ):
        assert (tmp_path / "out" / name).is_file()
