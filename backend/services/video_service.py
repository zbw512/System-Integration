"""Video business logic: upload, registration, listing and retrieval.

The service owns all decisions the client must not make:

* ``video_id`` allocation (and ``sav_<stem>`` naming for SAV clips, matching the
  standard's example ``sav_20181016_05_1064``);
* ``status`` of a fresh record (always ``registered``);
* ``prediction_source`` / ``provider`` / ``model`` / ``segments`` — a new video
  has no analysis result, so these stay ``none`` / ``null`` / ``null`` / ``[]``;
* ``evaluation_eligible`` (derived from the prediction source);
* the stored file location, which never comes from a client filename.
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any, Mapping

from common.timeutil import utc_timestamp
from config import Config
from schemas.enums import PredictionSource, VideoSource, VideoStatus, enum_values
from schemas.video import Video
from services.errors import (
    DuplicateVideoError,
    InvalidVideoRequestError,
    LocalPathNotAllowedError,
    StoredFileMissingError,
    UnsupportedVideoFormatError,
    VideoNotFoundError,
)
from services.media_probe import probe_video
from storage import files as storage_files
from storage.repositories import VideoRepository

_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
_STEM_SANITIZER = re.compile(r"[^A-Za-z0-9_.\-]")

VID_PREFIX = "vid_"
SAV_PREFIX = "sav_"
_MAX_ID_LENGTH = 64

#: Sources that may be created through ``POST /api/v1/videos/register``.
REGISTERABLE_SOURCES = (VideoSource.LOCAL_PATH, VideoSource.SAV_CLIP)


class VideoService:
    """Coordinates the repository, the file store and media probing."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._repository = VideoRepository(config.database_path)
        self._data_dir = os.path.abspath(config.data_dir)
        self._videos_dir = os.path.abspath(config.videos_dir)
        self._allowed_extensions = tuple(
            extension.lower() for extension in config.allowed_video_extensions
        )

    @property
    def repository(self) -> VideoRepository:
        return self._repository

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def create_from_upload(self, upload) -> Video:
        """Persist a multipart upload and return the new ``registered`` record."""
        display_name = storage_files.sanitize_name(getattr(upload, "filename", "") or "")
        if not display_name:
            raise InvalidVideoRequestError("缺少有效的上传文件名", details={"field": "file"})

        extension = storage_files.file_extension(display_name)
        if extension not in self._allowed_extensions:
            raise UnsupportedVideoFormatError(
                details={"extension": extension, "allowed": list(self._allowed_extensions)}
            )

        video_id = self._allocate_id(VID_PREFIX)
        dest_abs, dest_rel = self._dest_path(video_id, extension)

        size_bytes, sha256 = storage_files.save_stream(
            upload.stream, dest_abs, max_bytes=self._config.max_upload_bytes
        )

        try:
            duration_s = probe_video(
                dest_abs,
                display_name=display_name,
                allowed_extensions=self._allowed_extensions,
            )
            metadata: dict[str, Any] = {
                "sha256": sha256,
                "original_filename": display_name,
                "content_type": getattr(upload, "mimetype", None),
            }
            video = Video(
                video_id=video_id,
                name=display_name,
                source=VideoSource.UPLOAD,
                status=VideoStatus.REGISTERED,
                size_bytes=size_bytes,
                created_at=utc_timestamp(),
                duration_s=duration_s,
                file_url=self._file_url(video_id),
                prediction_source=PredictionSource.NONE,
                provider=None,
                model=None,
                segments=[],
                metadata=metadata,
                storage_path=dest_rel,
            )
            return self._repository.create(video)
        except BaseException:
            # Never leave an orphan file behind if probing or the insert fails.
            storage_files.remove_quietly(dest_abs)
            raise

    def create_from_path(
        self,
        path: str,
        *,
        source: VideoSource,
        name: str | None = None,
        video_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Video:
        """Register a file that already exists inside an allowed import root."""
        if source not in REGISTERABLE_SOURCES:
            raise InvalidVideoRequestError(
                "source 必须是 local_path 或 sav_clip",
                details={
                    "field": "source",
                    "allowed": [item.value for item in REGISTERABLE_SOURCES],
                },
            )

        if not isinstance(path, str) or not path.strip():
            raise InvalidVideoRequestError("缺少 path", details={"field": "path"})

        resolved = os.path.realpath(path.strip())
        if not self._is_allowed_import_path(resolved):
            # Deliberately does not echo the host path back to the client.
            raise LocalPathNotAllowedError(details={"field": "path"})
        if not os.path.isfile(resolved):
            raise InvalidVideoRequestError("path 指向的文件不存在", details={"field": "path"})

        display_name = storage_files.sanitize_name(name or os.path.basename(resolved))
        if not display_name:
            raise InvalidVideoRequestError("缺少有效的文件名", details={"field": "name"})

        extension = storage_files.file_extension(display_name)
        if extension not in self._allowed_extensions:
            raise UnsupportedVideoFormatError(
                details={"extension": extension, "allowed": list(self._allowed_extensions)}
            )

        if video_id is not None:
            video_id = self.validate_video_id(video_id)
        elif source is VideoSource.SAV_CLIP:
            video_id = self._sav_video_id(display_name)
        else:
            video_id = self._allocate_id(VID_PREFIX)

        if self._repository.exists(video_id):
            raise DuplicateVideoError(video_id)

        dest_abs, dest_rel = self._dest_path(video_id, extension)
        size_bytes, sha256 = storage_files.copy_into_store(
            resolved, dest_abs, max_bytes=self._config.max_upload_bytes
        )

        try:
            duration_s = probe_video(
                dest_abs,
                display_name=display_name,
                allowed_extensions=self._allowed_extensions,
            )
            merged_metadata: dict[str, Any] = {
                "sha256": sha256,
                "original_filename": display_name,
                "import_source": source.value,
            }
            merged_metadata.update(dict(metadata or {}))
            video = Video(
                video_id=video_id,
                name=display_name,
                source=source,
                status=VideoStatus.REGISTERED,
                size_bytes=size_bytes,
                created_at=utc_timestamp(),
                duration_s=duration_s,
                file_url=self._file_url(video_id),
                prediction_source=PredictionSource.NONE,
                provider=None,
                model=None,
                segments=[],
                metadata=merged_metadata,
                storage_path=dest_rel,
            )
            return self._repository.create(video)
        except BaseException:
            storage_files.remove_quietly(dest_abs)
            raise

    def list_videos(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Return the standard list envelope (``items`` + ``pagination``)."""
        status_value = None
        if status:
            try:
                status_value = VideoStatus(status).value
            except ValueError as exc:
                raise InvalidVideoRequestError(
                    "status 不是合法值",
                    details={"field": "status", "allowed": enum_values(VideoStatus)},
                ) from exc

        source_value = None
        if source:
            try:
                source_value = VideoSource(source).value
            except ValueError as exc:
                raise InvalidVideoRequestError(
                    "source 不是合法值",
                    details={"field": "source", "allowed": enum_values(VideoSource)},
                ) from exc

        videos, total = self._repository.list(
            limit=limit, offset=offset, status=status_value, source=source_value
        )
        items = [video.to_dict() for video in videos]

        return {
            "items": items,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "has_next": offset + len(items) < total,
            },
            # Transition alias kept by the standard (section 1.4); new code
            # should read ``items``.
            "videos": items,
        }

    def get_video(self, video_id: str) -> Video:
        video = self._repository.get(video_id)
        if video is None:
            raise VideoNotFoundError(video_id)
        return video

    def get_stored_file(self, video_id: str) -> tuple[Video, str]:
        """Return the record plus the absolute path of its stored file."""
        video = self.get_video(video_id)
        if not video.storage_path:
            raise StoredFileMissingError(details={"video_id": video_id})

        try:
            absolute = storage_files.resolve_stored_path(self._data_dir, video.storage_path)
        except storage_files.PathEscapeError as exc:
            raise StoredFileMissingError(details={"video_id": video_id}) from exc

        if not os.path.isfile(absolute):
            raise StoredFileMissingError(details={"video_id": video_id})
        return video, absolute

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def validate_video_id(video_id: Any) -> str:
        if not isinstance(video_id, str) or not _VIDEO_ID_PATTERN.match(video_id):
            raise InvalidVideoRequestError(
                "video_id 只能包含字母、数字、下划线、点和连字符，长度 1-64 且以字母或数字开头",
                details={"field": "video_id"},
            )
        return video_id

    def _file_url(self, video_id: str) -> str:
        return f"{self._config.api_prefix}/videos/{video_id}/file"

    def _allocate_id(self, prefix: str) -> str:
        return f"{prefix}{uuid.uuid4().hex[:12]}"

    def _sav_video_id(self, display_name: str) -> str:
        stem = os.path.splitext(display_name)[0]
        safe = _STEM_SANITIZER.sub("_", stem).strip("._-")
        if not safe:
            safe = uuid.uuid4().hex[:12]
        return f"{SAV_PREFIX}{safe[: _MAX_ID_LENGTH - len(SAV_PREFIX)]}"

    def _dest_path(self, video_id: str, extension: str) -> tuple[str, str]:
        absolute = os.path.join(self._videos_dir, f"{video_id}{extension}")
        if not storage_files.is_within(self._data_dir, absolute):
            raise InvalidVideoRequestError(
                "非法的存储路径", details={"field": "video_id"}
            )
        return absolute, storage_files.to_relative(self._data_dir, absolute)

    def _is_allowed_import_path(self, resolved: str) -> bool:
        return any(
            storage_files.is_within(root, resolved)
            for root in self._config.allowed_import_roots
        )
