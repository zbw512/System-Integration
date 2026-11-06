#!/usr/bin/env python3
"""Evaluate scene4/checkpoint-600 through the AutoDL HTTP service."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from test_window_client import (
    image_to_base64,
    read_uniform_video_frames,
)

LABELS = ["听讲", "小组讨论", "独立学习", "其他"]
LABEL_SET = set(LABELS)


@dataclass(frozen=True)
class EvaluationSample:
    sample_id: int
    clip_id: str
    video_path: Path
    gold_label: str


def load_samples(jsonl_path: Path, expected_count: int) -> list[EvaluationSample]:
    samples: list[EvaluationSample] = []
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            videos = record.get("videos")
            messages = record.get("messages")
            if not isinstance(videos, list) or len(videos) != 1:
                raise ValueError(f"第 {line_number} 行 videos 不合法")
            if not isinstance(messages, list) or not messages:
                raise ValueError(f"第 {line_number} 行 messages 不合法")
            gold = str(messages[-1].get("content", "")).strip()
            if gold not in LABEL_SET:
                raise ValueError(f"第 {line_number} 行标签不合法：{gold}")
            video_path = Path(videos[0])
            if not video_path.is_file():
                raise FileNotFoundError(f"第 {line_number} 行视频不存在：{video_path}")
            samples.append(
                EvaluationSample(
                    sample_id=line_number,
                    clip_id=video_path.stem,
                    video_path=video_path,
                    gold_label=gold,
                )
            )
    if len(samples) != expected_count:
        raise ValueError(
            f"验证集数量异常：期望 {expected_count}，实际 {len(samples)}"
        )
    return samples


def parse_prediction(raw: str) -> str:
    normalized = (raw or "").strip().replace(" ", "")
    for label in ["小组讨论", "独立学习", "听讲", "其他"]:
        if label in normalized:
            return label
    return "无法解析"


def call_service(
    *,
    url: str,
    token: str,
    timeout_s: float,
    retries: int,
    sample: EvaluationSample,
    frames: list[tuple[float, Any]],
) -> str:
    payload = {
        "request_id": f"eval-{sample.sample_id:04d}",
        "window_id": sample.clip_id,
        "window_start_s": 0.0,
        "window_end_s": max(3.0, frames[-1][0] + 0.001),
        "prompt_version": "scene4-label-v1",
        "frames": [
            {
                "timestamp_s": round(timestamp, 6),
                "mime_type": "image/png",
                "image_base64": image_to_base64(image),
            }
            for timestamp, image in frames
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
            if data.get("request_id") != payload["request_id"]:
                raise ValueError("响应 request_id 不匹配")
            return str(data["raw_prediction"])
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {429, 500, 502, 503, 504}
            if retryable and attempt < attempts:
                time.sleep(min(2.0, 0.5 * attempt))
                continue
            raise RuntimeError(f"HTTP {exc.code}") from exc
        except Exception as exc:
            if attempt < attempts and isinstance(
                exc,
                (urllib.error.URLError, TimeoutError, OSError),
            ):
                time.sleep(min(2.0, 0.5 * attempt))
                continue
            raise
    raise RuntimeError("重试耗尽")


def classification_metrics(
    y_true: list[str],
    y_pred: list[str],
    infrastructure_errors: list[str],
) -> tuple[dict[str, Any], dict[str, Any], list[list[int]]]:
    valid_mask = [
        prediction in LABEL_SET and not error
        for prediction, error in zip(y_pred, infrastructure_errors)
    ]
    valid_true = [truth for truth, keep in zip(y_true, valid_mask) if keep]
    valid_pred = [prediction for prediction, keep in zip(y_pred, valid_mask) if keep]
    unparsed = sum(
        prediction not in LABEL_SET and not error
        for prediction, error in zip(y_pred, infrastructure_errors)
    )
    correct = sum(
        truth == prediction
        for truth, prediction in zip(y_true, y_pred)
        if prediction in LABEL_SET
    )
    total = len(y_true)
    strict_accuracy = correct / total if total else 0.0
    parsed_accuracy = (
        sum(truth == prediction for truth, prediction in zip(valid_true, valid_pred))
        / len(valid_pred)
        if valid_pred
        else 0.0
    )

    per_class: dict[str, dict[str, float | int]] = {}
    for label in LABELS:
        tp = sum(t == label and p == label for t, p in zip(valid_true, valid_pred))
        fp = sum(t != label and p == label for t, p in zip(valid_true, valid_pred))
        fn = sum(t == label and p != label for t, p in zip(valid_true, valid_pred))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        per_class[label] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": sum(truth == label for truth in valid_true),
        }

    matrix = [
        [
            sum(truth == true_label and prediction == pred_label
                for truth, prediction in zip(valid_true, valid_pred))
            for pred_label in LABELS
        ]
        for true_label in LABELS
    ]
    metrics = {
        "total_samples": total,
        "parsed_samples": len(valid_pred),
        "unparsed_samples": unparsed,
        "infrastructure_errors": sum(bool(item) for item in infrastructure_errors),
        "parse_rate": round(len(valid_pred) / total, 6) if total else 0.0,
        "strict_accuracy": round(strict_accuracy, 6),
        "parsed_accuracy": round(parsed_accuracy, 6),
        "macro_f1": round(
            sum(float(item["f1"]) for item in per_class.values()) / len(LABELS),
            6,
        ),
        "prediction_distribution": dict(Counter(y_pred)),
    }
    return metrics, per_class, matrix


def write_outputs(
    *,
    output_dir: Path,
    samples: list[EvaluationSample],
    y_pred: list[str],
    raw_predictions: list[str],
    errors: list[str],
    inference_ms: list[float],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    y_true = [sample.gold_label for sample in samples]
    metrics, per_class, matrix = classification_metrics(y_true, y_pred, errors)

    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "per_class_metrics.json").write_text(
        json.dumps(per_class, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "confusion_matrix.json").write_text(
        json.dumps({"labels": LABELS, "matrix": matrix}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (output_dir / "predictions.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "sample_id",
                "clip_id",
                "video_path",
                "gold_label",
                "raw_prediction",
                "predicted_label",
                "round_trip_latency_ms",
                "error",
            ]
        )
        for sample, raw, prediction, latency, error in zip(
            samples,
            raw_predictions,
            y_pred,
            inference_ms,
            errors,
        ):
            writer.writerow(
                [
                    sample.sample_id,
                    sample.clip_id,
                    sample.video_path,
                    sample.gold_label,
                    raw,
                    prediction,
                    latency,
                    error,
                ]
            )

    with (output_dir / "errors.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["sample_id", "clip_id", "gold_label", "predicted_label", "raw_prediction", "error"]
        )
        for sample, raw, prediction, error in zip(
            samples,
            raw_predictions,
            y_pred,
            errors,
        ):
            if error or prediction != sample.gold_label:
                writer.writerow(
                    [
                        sample.sample_id,
                        sample.clip_id,
                        sample.gold_label,
                        prediction,
                        raw,
                        error,
                    ]
                )

    lines = [
        f"Accuracy (parsed): {metrics['parsed_accuracy']:.6f}",
        f"Strict accuracy:   {metrics['strict_accuracy']:.6f}",
        f"Macro F1:          {metrics['macro_f1']:.6f}",
        "",
        "label,precision,recall,f1,support",
    ]
    for label in LABELS:
        item = per_class[label]
        lines.append(
            f"{label},{item['precision']:.6f},{item['recall']:.6f},"
            f"{item['f1']:.6f},{item['support']}"
        )
    (output_dir / "classification_report.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:18080/predict_window",
    )
    parser.add_argument("--token-env", default="VLM_SERVICE_TOKEN")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=850)
    parser.add_argument("--max-frames", type=int, default=8)
    parser.add_argument("--timeout-s", type=float, default=300.0)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    if not 1 <= args.max_frames <= 8:
        raise ValueError("max-frames 必须在 1-8 之间")
    token = os.environ.get(args.token_env, "")
    if len(token) < 32:
        raise RuntimeError(f"环境变量 {args.token_env} 缺失或短于 32 字符")

    samples = load_samples(args.jsonl, args.expected_count)
    raw_predictions: list[str] = []
    predictions: list[str] = []
    errors: list[str] = []
    latencies: list[float] = []
    started = time.perf_counter()

    for sample in samples:
        frame_started = time.perf_counter()
        try:
            frames, _duration = read_uniform_video_frames(
                sample.video_path,
                max_frames=args.max_frames,
            )
            raw = call_service(
                url=args.url,
                token=token,
                timeout_s=args.timeout_s,
                retries=args.retries,
                sample=sample,
                frames=frames,
            )
            prediction = parse_prediction(raw)
            error = ""
        except Exception as exc:
            raw = ""
            prediction = ""
            error = f"{type(exc).__name__}: {exc}"

        raw_predictions.append(raw)
        predictions.append(prediction)
        errors.append(error)
        latencies.append(round((time.perf_counter() - frame_started) * 1000, 2))
        if sample.sample_id % 10 == 0 or sample.sample_id == len(samples):
            elapsed = time.perf_counter() - started
            print(
                f"[{sample.sample_id}/{len(samples)}] "
                f"elapsed={elapsed / 60:.1f}min predicted={prediction or 'ERROR'}"
            )

    write_outputs(
        output_dir=args.output_dir,
        samples=samples,
        y_pred=predictions,
        raw_predictions=raw_predictions,
        errors=errors,
        inference_ms=latencies,
    )
    print(f"评估输出目录：{args.output_dir}")
    return 0 if not any(errors) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("用户中断评估", file=sys.stderr)
        raise SystemExit(130)
