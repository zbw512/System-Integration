#!/usr/bin/env python3
"""Upload one video through Flask and verify the real AutoDL result."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def request_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
):
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers or {},
    )
    with opener.open(request, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def encode_multipart(file_path: Path) -> tuple[bytes, str]:
    boundary = f"----CodexAutoDL{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    file_bytes = file_path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, f"multipart/form-data; boundary={boundary}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-s", type=float, default=600.0)
    parser.add_argument("--poll-s", type=float, default=2.0)
    args = parser.parse_args()

    if not args.video.is_file():
        raise FileNotFoundError(args.video)
    base = args.api_base.rstrip("/")
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookies)
    )

    _, info = request_json(opener, f"{base}/api/v1/info")
    adapter = info.get("adapters", {}).get("vlm", {})
    if adapter.get("name") != "minicpm_remote":
        raise RuntimeError(
            f"Flask 未使用 minicpm_remote，当前为 {adapter.get('name')}"
        )
    if str(adapter.get("model", {}).get("version")) != "4.5":
        raise RuntimeError("Flask 报告的模型版本不是 4.5")

    body, content_type = encode_multipart(args.video)
    _, video = request_json(
        opener,
        f"{base}/api/v1/videos/upload",
        method="POST",
        data=body,
        headers={"Content-Type": content_type},
    )
    video_id = video["video_id"]
    _, job = request_json(
        opener,
        f"{base}/api/v1/videos/{video_id}/process",
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    job_id = job["job_id"]
    print(f"video_id={video_id} job_id={job_id}")

    deadline = time.monotonic() + args.timeout_s
    while time.monotonic() < deadline:
        _, job = request_json(opener, f"{base}/api/v1/jobs/{job_id}")
        progress = float(job.get("progress", 0.0)) * 100
        print(
            f"status={job['status']} stage={job['stage']} "
            f"progress={progress:.1f}%"
        )
        if job["status"] == "completed":
            break
        if job["status"] == "failed":
            raise RuntimeError(
                f"Job 失败：{json.dumps(job.get('error'), ensure_ascii=False)}"
            )
        time.sleep(args.poll_s)
    else:
        raise TimeoutError("等待 Job 完成超时")

    _, result = request_json(
        opener,
        f"{base}/api/v1/videos/{video_id}/results?format=json",
    )
    if result.get("prediction_source") != "model":
        raise RuntimeError("结果不是真实模型来源")
    if result.get("is_mock") is not False:
        raise RuntimeError("结果被标记为 Mock")
    if not result.get("segments"):
        raise RuntimeError("真实模型没有产生 Segment")

    print(
        json.dumps(
            {
                "video_id": video_id,
                "job_id": job_id,
                "prediction_source": result["prediction_source"],
                "provider": result["provider"],
                "model": result["model"],
                "segment_count": len(result["segments"]),
                "labels": [
                    segment["scene_label"] for segment in result["segments"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(
            f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}",
            file=sys.stderr,
        )
        raise SystemExit(1)
