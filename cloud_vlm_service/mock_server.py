"""Deterministic local HTTP double for AutoDL integration tests.

This module never imports Torch and must never be used as a production model.
It implements only the HTTP contract needed to test Flask networking, retries,
timeouts and error handling without a GPU.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

MODEL_INFO = {
    "name": "MiniCPM-V",
    "version": "4.5",
    "finetune": "scene4",
    "checkpoint": "checkpoint-600",
    "prompt_version": "scene4-label-v1",
}


def _json_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: dict[str, Any],
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def create_server(
    *,
    host: str,
    port: int,
    token: str,
    label: str = "听讲",
    failure_mode: str = "none",
    delay_s: float = 0.0,
) -> ThreadingHTTPServer:
    if failure_mode not in {"none", "unavailable", "inference_error", "unparseable"}:
        raise ValueError(f"未知 failure_mode：{failure_mode}")

    class Handler(BaseHTTPRequestHandler):
        server_version = "MockAutoDL/1.0"

        def log_message(self, format: str, *args) -> None:
            print(
                f"[MOCK AUTODL] {self.address_string()} {format % args}",
                flush=True,
            )

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            return supplied == f"Bearer {token}"

        def _reject_unauthorized(self) -> None:
            _json_response(
                self,
                401,
                {
                    "error": {
                        "code": "VLM_UNAUTHORIZED",
                        "message": "Token 无效或缺失",
                        "retryable": False,
                    }
                },
            )

        def do_GET(self) -> None:
            if urlparse(self.path).path != "/health":
                _json_response(self, 404, {"error": {"code": "NOT_FOUND"}})
                return
            if not self._authorized():
                self._reject_unauthorized()
                return
            loaded = failure_mode != "unavailable"
            _json_response(
                self,
                200 if loaded else 503,
                {
                    "status": "ok" if loaded else "degraded",
                    "loaded": loaded,
                    "model": MODEL_INFO,
                    "device": "cuda:mock",
                    "cuda_available": True,
                    "gpu_name": "Mock AutoDL GPU",
                    "base_model_present": True,
                    "adapter_present": True,
                    "max_frames": 8,
                    "load_error": None if loaded else "MOCK unavailable",
                },
            )

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/predict_window":
                _json_response(self, 404, {"error": {"code": "NOT_FOUND"}})
                return
            if not self._authorized():
                self._reject_unauthorized()
                return
            if failure_mode == "unavailable":
                _json_response(
                    self,
                    503,
                    {
                        "error": {
                            "code": "VLM_MODEL_LOAD_FAILED",
                            "message": "MOCK unavailable",
                            "retryable": True,
                        }
                    },
                )
                return
            if failure_mode == "inference_error":
                _json_response(
                    self,
                    502,
                    {
                        "error": {
                            "code": "VLM_INFERENCE_FAILED",
                            "message": "MOCK inference error",
                            "retryable": True,
                        }
                    },
                )
                return
            if delay_s > 0:
                time.sleep(delay_s)

            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                frames = payload["frames"]
                if not 1 <= len(frames) <= 8:
                    raise ValueError("frame count")
                if any(
                    item.get("mime_type") != "image/png"
                    or not item.get("image_base64")
                    for item in frames
                ):
                    raise ValueError("frame format")
                if payload.get("prompt_version") != "scene4-label-v1":
                    raise ValueError("prompt version")
            except Exception:
                _json_response(
                    self,
                    422,
                    {
                        "error": {
                            "code": "VLM_REQUEST_INVALID",
                            "message": "MOCK request invalid",
                            "retryable": False,
                        }
                    },
                )
                return

            raw = "未知结果" if failure_mode == "unparseable" else label
            predicted = (
                "未分类"
                if failure_mode == "unparseable"
                else label
            )
            _json_response(
                self,
                200,
                {
                    "request_id": payload["request_id"],
                    "window_id": payload["window_id"],
                    "raw_prediction": raw,
                    "predicted_label": predicted,
                    "is_uncertain": failure_mode == "unparseable",
                    "parse_status": (
                        "unparseable"
                        if failure_mode == "unparseable"
                        else "parsed"
                    ),
                    "model": MODEL_INFO,
                    "frame_count": len(frames),
                    "inference_ms": round(delay_s * 1000, 2),
                    "test_double": True,
                },
            )

    return ThreadingHTTPServer((host, port), Handler)


def run_server(
    server: ThreadingHTTPServer,
    *,
    ready_event: threading.Event | None = None,
) -> threading.Thread:
    def target() -> None:
        if ready_event is not None:
            ready_event.set()
        server.serve_forever(poll_interval=0.05)

    thread = threading.Thread(target=target, daemon=True, name="mock-autodl")
    thread.start()
    return thread


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock AutoDL VLM HTTP service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--token-env", default="VLM_SERVICE_TOKEN")
    parser.add_argument("--label", default="听讲")
    parser.add_argument(
        "--failure-mode",
        choices=("none", "unavailable", "inference_error", "unparseable"),
        default="none",
    )
    parser.add_argument("--delay-s", type=float, default=0.0)
    args = parser.parse_args()
    token = os.environ.get(args.token_env, "")
    if len(token) < 32:
        raise SystemExit(f"环境变量 {args.token_env} 缺失或短于 32 字符")

    server = create_server(
        host=args.host,
        port=args.port,
        token=token,
        label=args.label,
        failure_mode=args.failure_mode,
        delay_s=args.delay_s,
    )
    print(
        f"MOCK AutoDL listening on http://{args.host}:{server.server_port} "
        f"failure_mode={args.failure_mode}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
