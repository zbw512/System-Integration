"""HTTP client for the AutoDL MiniCPM-V 4.5 inference service."""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from config import Config
from services.errors import (
    VlmRemoteAuthFailedError,
    VlmRemoteConfigurationError,
    VlmRemoteInferenceError,
    VlmRemoteRejectedError,
    VlmRemoteUnavailableError,
    VlmResultInvalidError,
)

logger = logging.getLogger(__name__)

_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RemotePrediction:
    raw_prediction: str
    remote_predicted_label: str | None
    parse_status: str | None
    model: dict[str, Any]
    frame_count: int
    inference_ms: float
    request_id: str
    window_id: str


class RemoteVlmClient:
    def __init__(self, config: Config) -> None:
        self._base_url = (config.vlm_remote_url or "").rstrip("/")
        self._token = config.vlm_remote_token or ""
        self._timeout_s = config.vlm_remote_timeout_s
        self._retries = config.vlm_remote_retries
        self._max_response_bytes = config.vlm_remote_max_response_bytes

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}/predict_window"

    def _validate_configuration(self) -> None:
        if not self._base_url.startswith(("http://", "https://")):
            raise VlmRemoteConfigurationError(
                details={"reason": "invalid_url"}
            )
        if len(self._token) < 32:
            raise VlmRemoteConfigurationError(
                details={"reason": "missing_or_short_token"}
            )

    def predict_window(
        self,
        *,
        request_id: str,
        window_id: str,
        window_start_s: float,
        window_end_s: float,
        frames: list[dict[str, Any]],
    ) -> RemotePrediction:
        self._validate_configuration()
        payload = {
            "request_id": request_id,
            "window_id": window_id,
            "window_start_s": window_start_s,
            "window_end_s": window_end_s,
            "prompt_version": "scene4-label-v1",
            "frames": frames,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        attempts = self._retries + 1

        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(
                self.endpoint,
                data=body,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self._timeout_s,
                ) as response:
                    raw_body = response.read(self._max_response_bytes + 1)
                    if len(raw_body) > self._max_response_bytes:
                        raise VlmResultInvalidError(
                            "AutoDL 响应超过大小限制",
                            details={"reason": "response_too_large", "attempt": attempt},
                        )
                    return self._parse_response(
                        raw_body,
                        expected_request_id=request_id,
                        expected_window_id=window_id,
                        expected_frame_count=len(frames),
                    )
            except urllib.error.HTTPError as exc:
                service_code = self._extract_service_error_code(exc)
                if exc.code in {401, 403}:
                    raise VlmRemoteAuthFailedError(
                        details={
                            "reason": "unauthorized",
                            "http_status": exc.code,
                            "service_code": service_code,
                            "attempt": attempt,
                        }
                    ) from exc
                if 400 <= exc.code < 500 and exc.code not in {429}:
                    raise VlmRemoteRejectedError(
                        details={
                            "reason": "request_rejected",
                            "http_status": exc.code,
                            "service_code": service_code,
                            "attempt": attempt,
                        }
                    ) from exc
                if exc.code in _RETRYABLE_HTTP_STATUSES and attempt < attempts:
                    logger.warning(
                        "remote VLM HTTP %s attempt=%s/%s request_id=%s",
                        exc.code,
                        attempt,
                        attempts,
                        request_id,
                    )
                    time.sleep(min(2.0, 0.5 * attempt))
                    continue
                if exc.code in {429, 503, 504}:
                    raise VlmRemoteUnavailableError(
                        details={
                            "reason": "remote_unavailable",
                            "http_status": exc.code,
                            "service_code": service_code,
                            "attempts": attempt,
                        }
                    ) from exc
                raise VlmRemoteInferenceError(
                    details={
                        "reason": "remote_inference_failed",
                        "http_status": exc.code,
                        "service_code": service_code,
                        "attempts": attempt,
                    }
                ) from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
                if attempt < attempts:
                    logger.warning(
                        "remote VLM network failure attempt=%s/%s request_id=%s error=%s",
                        attempt,
                        attempts,
                        request_id,
                        type(exc).__name__,
                    )
                    time.sleep(min(2.0, 0.5 * attempt))
                    continue
                raise VlmRemoteUnavailableError(
                    details={
                        "reason": "network_failure",
                        "error_type": type(exc).__name__,
                        "attempts": attempt,
                    }
                ) from exc

        raise VlmRemoteUnavailableError(
            details={"reason": "retry_exhausted", "attempts": attempts}
        )

    @staticmethod
    def _extract_service_error_code(exc: urllib.error.HTTPError) -> str | None:
        try:
            raw = exc.read(64 * 1024)
            payload = json.loads(raw.decode("utf-8"))
            error = payload.get("error")
            if isinstance(error, dict) and isinstance(error.get("code"), str):
                return error["code"]
        except Exception:
            return None
        return None

    def _parse_response(
        self,
        raw_body: bytes,
        *,
        expected_request_id: str,
        expected_window_id: str,
        expected_frame_count: int,
    ) -> RemotePrediction:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VlmResultInvalidError(
                "AutoDL 返回的不是合法 JSON",
                details={"reason": "invalid_json"},
            ) from exc

        if not isinstance(payload, dict):
            raise VlmResultInvalidError(
                details={"reason": "response_not_object"}
            )
        if payload.get("request_id") != expected_request_id:
            raise VlmResultInvalidError(
                details={"reason": "request_id_mismatch"}
            )
        if payload.get("window_id") != expected_window_id:
            raise VlmResultInvalidError(
                details={"reason": "window_id_mismatch"}
            )
        raw_prediction = payload.get("raw_prediction")
        if not isinstance(raw_prediction, str):
            raise VlmResultInvalidError(
                details={"reason": "raw_prediction_not_string"}
            )

        model = payload.get("model")
        if not isinstance(model, dict):
            raise VlmResultInvalidError(details={"reason": "model_missing"})
        if str(model.get("version")) != "4.5":
            raise VlmResultInvalidError(
                details={"reason": "unexpected_model_version"}
            )
        if str(model.get("checkpoint")) != "checkpoint-600":
            raise VlmResultInvalidError(
                details={"reason": "unexpected_checkpoint"}
            )
        if str(model.get("prompt_version")) != "scene4-label-v1":
            raise VlmResultInvalidError(
                details={"reason": "unexpected_prompt_version"}
            )

        frame_count = payload.get("frame_count")
        if frame_count != expected_frame_count:
            raise VlmResultInvalidError(
                details={
                    "reason": "frame_count_mismatch",
                    "expected": expected_frame_count,
                    "actual": frame_count,
                }
            )
        inference_ms = payload.get("inference_ms")
        if not isinstance(inference_ms, (int, float)):
            raise VlmResultInvalidError(
                details={"reason": "inference_ms_invalid"}
            )

        return RemotePrediction(
            raw_prediction=raw_prediction,
            remote_predicted_label=(
                payload.get("predicted_label")
                if isinstance(payload.get("predicted_label"), str)
                else None
            ),
            parse_status=(
                payload.get("parse_status")
                if isinstance(payload.get("parse_status"), str)
                else None
            ),
            model=dict(model),
            frame_count=frame_count,
            inference_ms=float(inference_ms),
            request_id=expected_request_id,
            window_id=expected_window_id,
        )
