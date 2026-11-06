#!/usr/bin/env python3
"""Deterministically rebuild scene4 validation JSONL from the owner's CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

LABELS = {"听讲", "小组讨论", "独立学习", "其他"}


def build_records(
    *,
    csv_path: Path,
    video_dir: Path,
    prompt: str,
    expected_count: int,
) -> list[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"clip_id", "scene_label"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"CSV 必须包含字段 {sorted(required)}，实际为 {reader.fieldnames}"
            )
        rows = list(reader)

    if len(rows) != expected_count:
        raise ValueError(f"验证集数量异常：期望 {expected_count}，实际 {len(rows)}")

    seen: set[str] = set()
    records: list[dict] = []
    for row in sorted(rows, key=lambda item: item["clip_id"]):
        clip_id = row["clip_id"].strip()
        label = row["scene_label"].strip()
        if not clip_id:
            raise ValueError("clip_id 不能为空")
        if clip_id in seen:
            raise ValueError(f"重复 clip_id：{clip_id}")
        seen.add(clip_id)
        if label not in LABELS:
            raise ValueError(f"{clip_id} 标签不合法：{label}")

        video_path = (video_dir / f"{clip_id}.mp4").resolve()
        if not video_path.is_file():
            raise FileNotFoundError(f"{clip_id} 视频不存在：{video_path}")
        records.append(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": f"<video>\n{prompt}",
                    },
                    {
                        "role": "assistant",
                        "content": label,
                    },
                ],
                "videos": [str(video_path)],
            }
        )
    return records


def write_jsonl(records: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=output_path.name + ".",
        suffix=".tmp",
        dir=output_path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(temporary_name, output_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(r"E:\dachuang\SAV\exports\val_scene4_v1.csv"),
    )
    parser.add_argument(
        "--video-dir",
        type=Path,
        default=Path(r"E:\dachuang\SAV\dataset"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "work" / "minicpmv45_scene4_val_v1.jsonl",
    )
    parser.add_argument("--expected-count", type=int, default=850)
    args = parser.parse_args()

    prompt = (
        project_root / "cloud_vlm_service" / "prompt_scene4.txt"
    ).read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    records = build_records(
        csv_path=args.csv,
        video_dir=args.video_dir,
        prompt=prompt,
        expected_count=args.expected_count,
    )
    write_jsonl(records, args.output)
    counts = Counter(
        record["messages"][1]["content"] for record in records
    )
    print(f"已写入 {len(records)} 条验证记录：{args.output}")
    print(json.dumps(dict(counts), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
