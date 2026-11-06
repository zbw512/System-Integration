"""Application configuration for the learning-state analysis backend.

All values are read from environment variables with conservative local
defaults. No secret is ever stored in this file; see ``.env.example`` for the
supported keys.

The module intentionally has no third-party imports so that configuration can
be inspected (and unit-tested) even if Flask is not installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: Interface standard version this backend implements (standard section 1.1).
SCHEMA_VERSION = "1.0"

SERVICE_NAME = "learning-state-backend"
SERVICE_VERSION = "0.5.0"

#: URL prefix for all versioned endpoints (standard section 1.1).
API_PREFIX = "/api/v1"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_MAX_UPLOAD_MB = 512
DEFAULT_GUEST_SESSION_TTL_HOURS = 24
DEFAULT_SESSION_TTL_DAYS = 14
DEFAULT_LOGIN_MAX_FAILURES = 5
DEFAULT_LOGIN_WINDOW_SECONDS = 15 * 60
DEFAULT_LOGIN_BLOCK_SECONDS = 15 * 60
DEFAULT_REGISTRATION_MAX_ATTEMPTS = 10
DEFAULT_REGISTRATION_WINDOW_SECONDS = 60 * 60

#: Backend source directory; defaults keep runtime data out of the code tree.
BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BACKEND_DIR / "var"
DEFAULT_DB_FILENAME = "app.db"
DEFAULT_VIDEO_SUBDIR = "videos"

#: Containers accepted for upload/registration (ISO base media file format).
DEFAULT_ALLOWED_VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mov")

#: List pagination limits published by ``GET /api/v1/info`` (standard 1.4).
LIST_DEFAULT_LIMIT = 50
LIST_MAX_LIMIT = 500

#: VLM adapter implementations this build knows about.
DEFAULT_VLM_ADAPTER = "mock"
SUPPORTED_VLM_ADAPTERS = (
    "mock",
    "minicpm",
    "minicpm_remote",
    "minicpm_v45_lora",
)

#: Project root; model weights live outside the backend package and are never
#: copied into it.
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_MODEL_PATH = REPO_ROOT / "models" / "MiniCPM-V-4.6"

#: Short-video sampling defaults for the real adapter. Chosen for a 8 GB GPU:
#: 8 frames x ~1.7 s inference keeps a 60 s job well under a few minutes.
DEFAULT_VLM_MAX_FRAMES = 8
DEFAULT_VLM_FRAME_INTERVAL_S = 1.0
DEFAULT_VLM_MAX_DURATION_S = 60.0
DEFAULT_VLM_MAX_NEW_TOKENS = 48
DEFAULT_VLM_DEVICE = "cuda"

#: MiniCPM-V 4.5 + LoRA remote inference defaults. The window policy is
#: provisional pending an exact training-loader comparison.
DEFAULT_VLM_REMOTE_URL = "http://127.0.0.1:18080"
DEFAULT_VLM_REMOTE_TIMEOUT_S = 300.0
DEFAULT_VLM_REMOTE_RETRIES = 2
DEFAULT_VLM_REMOTE_MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_VLM_WINDOW_SECONDS = 3.0
DEFAULT_VLM_WINDOW_STRIDE_SECONDS = 3.0
VLM_WINDOW_POLICY_ID = "provisional-3s-window-3s-stride-tail-v1"
VLM45_PROMPT_VERSION = "scene4-label-v1"


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"环境变量 {name} 必须是整数，当前值：{raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_paths(name: str) -> tuple[str, ...]:
    """Parse a ``;``-separated (``os.pathsep``) list of directories."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return ()
    parts = [part.strip() for part in raw.split(os.pathsep)]
    return tuple(part for part in parts if part)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"环境变量 {name} 必须是数字，当前值：{raw!r}") from exc


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration.

    ``from_env`` is the only supported production entry point; tests may build
    the dataclass directly because every field has a default.
    """

    service_name: str = SERVICE_NAME
    service_version: str = SERVICE_VERSION
    schema_version: str = SCHEMA_VERSION
    api_prefix: str = API_PREFIX

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    environment: str = "development"
    debug: bool = False
    testing: bool = False

    log_level: str = "INFO"
    log_file: str | None = None

    #: Global request body limit; maps to ``413 PAYLOAD_TOO_LARGE``.
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_MB * 1024 * 1024

    #: Header used to correlate a client request with the error payload.
    request_id_header: str = "X-Request-Id"

    # --- local persistence -------------------------------------------------
    #: Root for uploaded/registered video files and the SQLite database.
    #: Defaults to ``backend/var`` which is ignored by Git.
    data_dir: str = str(DEFAULT_DATA_DIR)
    #: Explicit database file; defaults to ``<data_dir>/app.db``.
    db_path: str | None = None
    #: Sub-directory of ``data_dir`` holding video files.
    video_subdir: str = DEFAULT_VIDEO_SUBDIR

    #: Directories that ``local_path`` / ``sav_clip`` registration may read
    #: from. Files are copied into ``data_dir``; the source directory must be
    #: explicitly allowed, so a client-supplied path can never read arbitrary
    #: locations on the host.
    import_roots: tuple[str, ...] = ()

    allowed_video_extensions: tuple[str, ...] = DEFAULT_ALLOWED_VIDEO_EXTENSIONS

    list_default_limit: int = LIST_DEFAULT_LIMIT
    list_max_limit: int = LIST_MAX_LIMIT
    guest_session_ttl_hours: int = DEFAULT_GUEST_SESSION_TTL_HOURS
    session_ttl_days: int = DEFAULT_SESSION_TTL_DAYS
    login_max_failures: int = DEFAULT_LOGIN_MAX_FAILURES
    login_window_seconds: int = DEFAULT_LOGIN_WINDOW_SECONDS
    login_block_seconds: int = DEFAULT_LOGIN_BLOCK_SECONDS
    registration_max_attempts: int = DEFAULT_REGISTRATION_MAX_ATTEMPTS
    registration_window_seconds: int = DEFAULT_REGISTRATION_WINDOW_SECONDS
    registration_token: str | None = None

    # --- background analysis ------------------------------------------------
    #: Start the single background worker thread when the application boots.
    #: Tests disable it and drive the queue explicitly so runs are deterministic.
    job_worker_enabled: bool = True
    #: Which VLM adapter to build. P0-3 ships ``mock``; ``minicpm`` is the real
    #: MiniCPM-V 4.6 adapter (P0-5). Unknown values fail fast at startup.
    vlm_adapter: str = DEFAULT_VLM_ADAPTER

    # --- real VLM (P0-5) ----------------------------------------------------
    #: Local model directory; never copied into the backend tree.
    vlm_model_path: str = str(DEFAULT_MODEL_PATH)
    #: Device for the real adapter. Only ``cuda`` is implemented and verified.
    vlm_device: str = DEFAULT_VLM_DEVICE
    #: Sampling policy for short videos (frames, spacing, hard duration cap).
    vlm_max_frames: int = DEFAULT_VLM_MAX_FRAMES
    vlm_frame_interval_s: float = DEFAULT_VLM_FRAME_INTERVAL_S
    vlm_max_duration_s: float = DEFAULT_VLM_MAX_DURATION_S
    #: Generation cap per sampled frame.
    vlm_max_new_tokens: int = DEFAULT_VLM_MAX_NEW_TOKENS

    # --- MiniCPM-V 4.5 remote adapter --------------------------------------
    vlm_remote_url: str = DEFAULT_VLM_REMOTE_URL
    vlm_remote_token: str | None = field(default=None, repr=False)
    vlm_remote_timeout_s: float = DEFAULT_VLM_REMOTE_TIMEOUT_S
    vlm_remote_retries: int = DEFAULT_VLM_REMOTE_RETRIES
    vlm_remote_max_response_bytes: int = DEFAULT_VLM_REMOTE_MAX_RESPONSE_BYTES
    vlm_window_seconds: float = DEFAULT_VLM_WINDOW_SECONDS
    vlm_window_stride_seconds: float = DEFAULT_VLM_WINDOW_STRIDE_SECONDS

    @classmethod
    def from_env(cls) -> "Config":
        """Build a configuration snapshot from ``BACKEND_*`` environment vars."""
        max_upload_mb = _env_int("BACKEND_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB)
        if max_upload_mb <= 0:
            raise ValueError("环境变量 BACKEND_MAX_UPLOAD_MB 必须为正整数")

        port = _env_int("BACKEND_PORT", DEFAULT_PORT)
        if not (1 <= port <= 65535):
            raise ValueError("环境变量 BACKEND_PORT 必须在 1-65535 之间")

        log_file = _env_str("BACKEND_LOG_FILE", "")
        db_path = _env_str("BACKEND_DB_PATH", "")

        vlm_adapter = _env_str("BACKEND_VLM_ADAPTER", DEFAULT_VLM_ADAPTER).lower()
        if vlm_adapter not in SUPPORTED_VLM_ADAPTERS:
            raise ValueError(
                f"环境变量 BACKEND_VLM_ADAPTER 只能是 {list(SUPPORTED_VLM_ADAPTERS)}，"
                f"当前值：{vlm_adapter!r}"
            )

        vlm_max_frames = _env_int("BACKEND_VLM_MAX_FRAMES", DEFAULT_VLM_MAX_FRAMES)
        if vlm_max_frames < 1 or vlm_max_frames > 64:
            raise ValueError("环境变量 BACKEND_VLM_MAX_FRAMES 必须在 1-64 之间")

        vlm_frame_interval_s = _env_float(
            "BACKEND_VLM_FRAME_INTERVAL_S", DEFAULT_VLM_FRAME_INTERVAL_S
        )
        if vlm_frame_interval_s <= 0:
            raise ValueError("环境变量 BACKEND_VLM_FRAME_INTERVAL_S 必须大于 0")

        vlm_max_duration_s = _env_float(
            "BACKEND_VLM_MAX_DURATION_S", DEFAULT_VLM_MAX_DURATION_S
        )
        if vlm_max_duration_s <= 0:
            raise ValueError("环境变量 BACKEND_VLM_MAX_DURATION_S 必须大于 0")

        vlm_max_new_tokens = _env_int(
            "BACKEND_VLM_MAX_NEW_TOKENS", DEFAULT_VLM_MAX_NEW_TOKENS
        )
        if vlm_max_new_tokens < 1:
            raise ValueError("环境变量 BACKEND_VLM_MAX_NEW_TOKENS 必须为正整数")

        vlm_remote_timeout_s = _env_float(
            "BACKEND_VLM_REMOTE_TIMEOUT_S", DEFAULT_VLM_REMOTE_TIMEOUT_S
        )
        if vlm_remote_timeout_s <= 0:
            raise ValueError("环境变量 BACKEND_VLM_REMOTE_TIMEOUT_S 必须大于 0")

        vlm_remote_retries = _env_int(
            "BACKEND_VLM_REMOTE_RETRIES", DEFAULT_VLM_REMOTE_RETRIES
        )
        if not 0 <= vlm_remote_retries <= 5:
            raise ValueError("环境变量 BACKEND_VLM_REMOTE_RETRIES 必须在 0-5 之间")

        vlm_remote_max_response_bytes = _env_int(
            "BACKEND_VLM_REMOTE_MAX_RESPONSE_BYTES",
            DEFAULT_VLM_REMOTE_MAX_RESPONSE_BYTES,
        )
        if vlm_remote_max_response_bytes <= 0:
            raise ValueError(
                "环境变量 BACKEND_VLM_REMOTE_MAX_RESPONSE_BYTES 必须为正整数"
            )

        vlm_window_seconds = _env_float(
            "BACKEND_VLM_WINDOW_SECONDS", DEFAULT_VLM_WINDOW_SECONDS
        )
        vlm_window_stride_seconds = _env_float(
            "BACKEND_VLM_WINDOW_STRIDE_SECONDS",
            DEFAULT_VLM_WINDOW_STRIDE_SECONDS,
        )
        if vlm_window_seconds <= 0:
            raise ValueError("环境变量 BACKEND_VLM_WINDOW_SECONDS 必须大于 0")
        if vlm_window_stride_seconds < vlm_window_seconds:
            raise ValueError(
                "BACKEND_VLM_WINDOW_STRIDE_SECONDS 不能小于窗口长度；"
                "初版不支持重叠窗口"
            )
        if (
            vlm_adapter in {"minicpm_remote", "minicpm_v45_lora"}
            and vlm_max_frames > 8
        ):
            raise ValueError("MiniCPM-V 4.5 远程模式最多允许 8 帧")

        guest_session_ttl_hours = _env_int(
            "BACKEND_GUEST_SESSION_TTL_HOURS",
            DEFAULT_GUEST_SESSION_TTL_HOURS,
        )
        if guest_session_ttl_hours < 1:
            raise ValueError("环境变量 BACKEND_GUEST_SESSION_TTL_HOURS 必须为正整数")

        session_ttl_days = _env_int("BACKEND_SESSION_TTL_DAYS", DEFAULT_SESSION_TTL_DAYS)
        login_max_failures = _env_int(
            "BACKEND_LOGIN_MAX_FAILURES", DEFAULT_LOGIN_MAX_FAILURES
        )
        login_window_seconds = _env_int(
            "BACKEND_LOGIN_WINDOW_SECONDS", DEFAULT_LOGIN_WINDOW_SECONDS
        )
        login_block_seconds = _env_int(
            "BACKEND_LOGIN_BLOCK_SECONDS", DEFAULT_LOGIN_BLOCK_SECONDS
        )
        registration_max_attempts = _env_int(
            "BACKEND_REGISTRATION_MAX_ATTEMPTS",
            DEFAULT_REGISTRATION_MAX_ATTEMPTS,
        )
        registration_window_seconds = _env_int(
            "BACKEND_REGISTRATION_WINDOW_SECONDS",
            DEFAULT_REGISTRATION_WINDOW_SECONDS,
        )
        for name, value in (
            ("BACKEND_SESSION_TTL_DAYS", session_ttl_days),
            ("BACKEND_LOGIN_MAX_FAILURES", login_max_failures),
            ("BACKEND_LOGIN_WINDOW_SECONDS", login_window_seconds),
            ("BACKEND_LOGIN_BLOCK_SECONDS", login_block_seconds),
            ("BACKEND_REGISTRATION_MAX_ATTEMPTS", registration_max_attempts),
            ("BACKEND_REGISTRATION_WINDOW_SECONDS", registration_window_seconds),
        ):
            if value < 1:
                raise ValueError(f"环境变量 {name} 必须为正整数")

        return cls(
            host=_env_str("BACKEND_HOST", DEFAULT_HOST),
            port=port,
            environment=_env_str("BACKEND_ENV", "development"),
            debug=_env_bool("BACKEND_DEBUG", False),
            testing=_env_bool("BACKEND_TESTING", False),
            log_level=_env_str("BACKEND_LOG_LEVEL", "INFO").upper(),
            log_file=log_file or None,
            max_upload_bytes=max_upload_mb * 1024 * 1024,
            data_dir=_env_str("BACKEND_DATA_DIR", str(DEFAULT_DATA_DIR)),
            db_path=db_path or None,
            video_subdir=_env_str("BACKEND_VIDEO_SUBDIR", DEFAULT_VIDEO_SUBDIR),
            import_roots=_env_paths("BACKEND_IMPORT_ROOTS"),
            guest_session_ttl_hours=guest_session_ttl_hours,
            session_ttl_days=session_ttl_days,
            login_max_failures=login_max_failures,
            login_window_seconds=login_window_seconds,
            login_block_seconds=login_block_seconds,
            registration_max_attempts=registration_max_attempts,
            registration_window_seconds=registration_window_seconds,
            registration_token=_env_str("BACKEND_REGISTRATION_TOKEN", "") or None,
            job_worker_enabled=_env_bool("BACKEND_JOB_WORKER", True),
            vlm_adapter=vlm_adapter,
            vlm_model_path=_env_str("BACKEND_VLM_MODEL_PATH", str(DEFAULT_MODEL_PATH)),
            vlm_device=_env_str("BACKEND_VLM_DEVICE", DEFAULT_VLM_DEVICE),
            vlm_max_frames=vlm_max_frames,
            vlm_frame_interval_s=vlm_frame_interval_s,
            vlm_max_duration_s=vlm_max_duration_s,
            vlm_max_new_tokens=vlm_max_new_tokens,
            vlm_remote_url=_env_str(
                "BACKEND_VLM_REMOTE_URL", DEFAULT_VLM_REMOTE_URL
            ),
            vlm_remote_token=(
                _env_str("BACKEND_VLM_REMOTE_TOKEN", "") or None
            ),
            vlm_remote_timeout_s=vlm_remote_timeout_s,
            vlm_remote_retries=vlm_remote_retries,
            vlm_remote_max_response_bytes=vlm_remote_max_response_bytes,
            vlm_window_seconds=vlm_window_seconds,
            vlm_window_stride_seconds=vlm_window_stride_seconds,
        )

    # --- derived paths -----------------------------------------------------
    @property
    def database_path(self) -> str:
        """Absolute path of the SQLite database file."""
        raw = self.db_path or os.path.join(self.data_dir, DEFAULT_DB_FILENAME)
        return os.path.abspath(raw)

    @property
    def videos_dir(self) -> str:
        """Absolute path of the directory holding video files."""
        return os.path.abspath(os.path.join(self.data_dir, self.video_subdir))

    @property
    def allowed_import_roots(self) -> tuple[str, ...]:
        """Absolute import roots plus the data directory itself."""
        roots = [os.path.abspath(path) for path in self.import_roots]
        roots.append(os.path.abspath(self.data_dir))
        # Preserve order, drop duplicates.
        seen: list[str] = []
        for root in roots:
            if root not in seen:
                seen.append(root)
        return tuple(seen)
