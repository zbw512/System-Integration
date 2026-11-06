"""FastAPI application for AutoDL-hosted MiniCPM-V scene4 inference."""

from __future__ import annotations

import base64
import binascii
import io
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from cloud_vlm_service.config import PROMPT_VERSION, Settings
from cloud_vlm_service.contract import contract_metadata, normalize_prediction
from cloud_vlm_service.errors import InvalidFrameError, ServiceError
from cloud_vlm_service.runtime import MiniCPMV45LoRARuntime
from cloud_vlm_service.schemas import (
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    PredictWindowRequest,
    PredictWindowResponse,
)

logger = logging.getLogger(__name__)


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
    request_id: str | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            retryable=retryable,
            request_id=request_id,
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


class RequestBodyLimitMiddleware:
    """Reject oversized bodies even when Content-Length is absent."""

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = None
        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length":
                try:
                    content_length = int(value.decode("ascii"))
                except (ValueError, UnicodeDecodeError):
                    content_length = -1
                break

        if content_length is not None and (
            content_length < 0 or content_length > self.max_bytes
        ):
            response = _error_response(
                status_code=413,
                code="VLM_REQUEST_TOO_LARGE",
                message="请求体超过服务限制",
                retryable=False,
            )
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise InvalidFrameError("请求体超过服务限制")
            return message

        await self.app(scope, limited_receive, send)


def _decode_png_frames(request: PredictWindowRequest, settings: Settings) -> list[Image.Image]:
    if len(request.frames) > settings.max_frames:
        raise InvalidFrameError(
            f"一个窗口最多允许 {settings.max_frames} 帧"
        )

    images: list[Image.Image] = []
    for position, frame in enumerate(request.frames):
        try:
            raw = base64.b64decode(frame.image_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidFrameError(
                f"第 {position + 1} 帧不是合法 base64"
            ) from exc

        if not raw:
            raise InvalidFrameError(f"第 {position + 1} 帧为空")
        if len(raw) > settings.max_frame_bytes:
            raise InvalidFrameError(f"第 {position + 1} 帧超过大小限制")

        try:
            with Image.open(io.BytesIO(raw)) as probe:
                if probe.format != "PNG":
                    raise InvalidFrameError(
                        f"第 {position + 1} 帧必须是 PNG，实际为 {probe.format}"
                    )
                width, height = probe.size
                if width <= 0 or height <= 0:
                    raise InvalidFrameError(f"第 {position + 1} 帧尺寸无效")
                if width * height > settings.max_image_pixels:
                    raise InvalidFrameError(f"第 {position + 1} 帧像素数超过限制")
                probe.verify()

            with Image.open(io.BytesIO(raw)) as decoded:
                image = decoded.convert("RGB")
        except InvalidFrameError:
            raise
        except (
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            Image.DecompressionBombError,
        ) as exc:
            raise InvalidFrameError(
                f"第 {position + 1} 帧不是可解码的 PNG"
            ) from exc

        images.append(image)

    return images


def create_app(
    settings: Settings | None = None,
    *,
    runtime: MiniCPMV45LoRARuntime | None = None,
) -> FastAPI:
    cfg = settings or Settings.from_env()
    cfg.validate()
    actual_runtime = runtime or MiniCPMV45LoRARuntime(cfg)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if cfg.load_on_startup:
            try:
                await run_in_threadpool(actual_runtime.load)
            except ServiceError:
                logger.exception("model was not loaded during service startup")
        yield
        logger.info("MiniCPM-V inference service stopped")

    app = FastAPI(
        title="MiniCPM-V 4.5 scene4 inference",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.runtime = actual_runtime
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=cfg.max_request_bytes,
    )

    async def require_token(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise _auth_error()
        supplied = authorization.removeprefix("Bearer ").strip()
        if not secrets.compare_digest(supplied, cfg.service_token):
            raise _auth_error()

    def _auth_error() -> ServiceError:
        error = ServiceError("Token 无效或缺失")
        error.code = "VLM_UNAUTHORIZED"
        error.status_code = 401
        return error

    @app.exception_handler(ServiceError)
    async def handle_service_error(request: Request, exc: ServiceError):
        request_id = getattr(request.state, "request_id", None)
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.public_message,
            retryable=exc.retryable,
            request_id=request_id,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", None)
        return _error_response(
            status_code=422,
            code="VLM_REQUEST_INVALID",
            message="请求参数不合法",
            retryable=False,
            request_id=request_id,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", None)
        logger.exception("unexpected service error request_id=%s", request_id)
        return _error_response(
            status_code=500,
            code="VLM_INTERNAL_ERROR",
            message="推理服务内部错误",
            retryable=True,
            request_id=request_id,
        )

    @app.get("/health", response_model=HealthResponse)
    async def health(_: None = Depends(require_token)):
        payload = actual_runtime.health_snapshot()
        status_code = 200 if payload["loaded"] else 503
        return JSONResponse(status_code=status_code, content=payload)

    @app.post("/predict_window", response_model=PredictWindowResponse)
    def predict_window(
        body: PredictWindowRequest,
        request: Request,
        _: None = Depends(require_token),
    ):
        request_id = body.request_id or uuid.uuid4().hex
        request.state.request_id = request_id

        if body.prompt_version != PROMPT_VERSION:
            return _error_response(
                status_code=422,
                code="VLM_PROMPT_VERSION_UNSUPPORTED",
                message=f"仅支持 {PROMPT_VERSION}",
                retryable=False,
                request_id=request_id,
            )

        frames = _decode_png_frames(body, cfg)
        result = actual_runtime.predict_window(frames)
        parsed = normalize_prediction(result.raw_prediction)

        logger.info(
            "prediction request_id=%s window_id=%s frames=%d label=%s uncertain=%s inference_ms=%.2f",
            request_id,
            body.window_id,
            result.frame_count,
            parsed.predicted_label,
            parsed.is_uncertain,
            result.inference_ms,
        )

        return PredictWindowResponse(
            request_id=request_id,
            window_id=body.window_id,
            raw_prediction=result.raw_prediction,
            predicted_label=parsed.predicted_label,
            is_uncertain=parsed.is_uncertain,
            parse_status=parsed.parse_status,
            model=actual_runtime.model_info,
            frame_count=result.frame_count,
            inference_ms=result.inference_ms,
        )

    @app.get("/contract")
    async def contract(_: None = Depends(require_token)):
        return contract_metadata()

    return app
