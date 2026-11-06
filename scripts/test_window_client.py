#!/usr/bin/env python3
"""Send one real video window to the AutoDL inference service."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import av
from PIL import Image

EPSILON = 1e-6


def select_window_frames(
    video_path: Path,
    *,
    start_s: float,
    end_s: float,
    max_frames: int,
) -> list[tuple[float, Image.Image]]:
    if end_s <= start_s:
        raise ValueError("end_s 必须大于 start_s")
    if max_frames < 1:
        raise ValueError("max_frames 必须为正整数")

    container = av.open(str(video_path))
    frames: list[tuple[float, Image.Image]] = []
    try:
        for frame in container.decode(video=0):
            timestamp = float(frame.time) if frame.time is not None else None
            if timestamp is None or timestamp < 0:
                raise RuntimeError("视频包含缺失或非法时间戳")
            if timestamp + EPSILON < start_s:
                continue
            if timestamp >= end_s - EPSILON:
                break
            frames.append(
                (timestamp, frame.to_image().convert("RGB"))
            )
    finally:
        container.close()

    if not frames:
        raise RuntimeError("指定窗口内没有可用视频帧")
    if len(frames) <= max_frames:
        return frames
    if max_frames == 1:
        return [frames[0]]

    indices = [
        round(index * (len(frames) - 1) / (max_frames - 1))
        for index in range(max_frames)
    ]
    return [frames[index] for index in indices]


def read_uniform_video_frames(
    video_path: Path,
    *,
    max_frames: int,
) -> tuple[list[tuple[float, Image.Image]], float | None]:
    """Match the owner's evaluation loader: decode all frames, then uniform 8."""
    container = av.open(str(video_path))
    decoded: list[tuple[float, Image.Image]] = []
    duration_s: float | None = None
    try:
        stream = container.streams.video[0]
        if stream.duration and stream.time_base:
            duration_s = float(stream.duration * stream.time_base)
        elif container.duration:
            duration_s = float(container.duration / 1_000_000)
        for frame in container.decode(stream):
            timestamp = float(frame.time) if frame.time is not None else None
            if timestamp is None or timestamp < 0:
                raise RuntimeError("视频包含缺失或非法时间戳")
            decoded.append(
                (timestamp, frame.to_image().convert("RGB"))
            )
    finally:
        container.close()

    if not decoded:
        raise RuntimeError("未能解码视频帧")
    if len(decoded) <= max_frames:
        selected = decoded
    elif max_frames == 1:
        selected = [decoded[0]]
    else:
        indices = [
            round(index * (len(decoded) - 1) / (max_frames - 1))
            for index in range(max_frames)
        ]
        selected = [decoded[index] for index in indices]
    return selected, duration_s


def image_to_base64(image: Image.Image) -> str:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def build_request(
    frames: list[tuple[float, Image.Image]],
    *,
    start_s: float,
    end_s: float,
    window_id: str,
) -> dict:
    return {
        "request_id": f"window-test-{int(time.time() * 1000)}",
        "window_id": window_id,
        "window_start_s": start_s,
        "window_end_s": end_s,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--start-s", type=float, default=0.0)
    parser.add_argument("--end-s", type=float, default=3.0)
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:18080/predict_window",
    )
    parser.add_argument("--max-frames", type=int, default=8)
    parser.add_argument("--token-env", default="VLM_SERVICE_TOKEN")
    args = parser.parse_args()

    if not args.video.is_file():
        raise FileNotFoundError(args.video)
    token = os.environ.get(args.token_env, "").strip()
    if not token:
        raise RuntimeError(f"环境变量 {args.token_env} 未设置")

    frames = select_window_frames(
        args.video,
        start_s=args.start_s,
        end_s=args.end_s,
        max_frames=args.max_frames,
    )
    payload = build_request(
        frames,
        start_s=args.start_s,
        end_s=args.end_s,
        window_id=args.video.stem,
    )
    request = urllib.request.Request(
        args.url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )

    print(
        f"窗口 {args.start_s:.3f}-{args.end_s:.3f}s，"
        f"发送 {len(frames)} 帧，请求体 {len(request.data)} 字节"
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {body}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"无法访问推理服务：{exc}", file=sys.stderr)
        return 1

    elapsed = time.perf_counter() - started
    print(f"HTTP {status}，客户端总耗时 {elapsed * 1000:.1f} ms")
    print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
