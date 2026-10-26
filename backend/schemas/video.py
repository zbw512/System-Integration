"""``Video`` schema — interface standard section 3.1.

Field order in :meth:`Video.to_dict` follows the standard's example so the JSON
is diff-friendly and the frontend can rely on the documented set of keys.

An unprocessed video must expose ``prediction_source="none"``, ``provider=null``,
``model=null`` and ``segments=[]``. Nothing in this module fabricates an
analysis result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import SCHEMA_VERSION
from schemas.enums import PredictionSource, VideoSource, VideoStatus, is_evaluation_eligible


@dataclass
class Video:
    """A registered video and its (optional) analysis metadata."""

    video_id: str
    name: str
    source: VideoSource | str
    status: VideoStatus | str
    size_bytes: int
    created_at: str
    duration_s: float | None = None
    file_url: str | None = None
    prediction_source: PredictionSource | str = PredictionSource.NONE
    provider: str | None = None
    evaluation_eligible: bool = False
    model: dict[str, Any] | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    #: Path relative to the data directory; internal, never serialized.
    storage_path: str | None = None

    def __post_init__(self) -> None:
        self.source = VideoSource(self.source)
        self.status = VideoStatus(self.status)
        self.prediction_source = PredictionSource(self.prediction_source)
        # Standard 2.2: eligibility is derived by the backend from the
        # prediction source, never accepted from a client.
        self.evaluation_eligible = is_evaluation_eligible(self.prediction_source)
        if not isinstance(self.metadata, dict):
            raise TypeError("metadata 必须是对象")
        if not isinstance(self.segments, list):
            raise TypeError("segments 必须是数组")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire format defined by the standard."""
        return {
            "schema_version": self.schema_version,
            "video_id": self.video_id,
            "name": self.name,
            "source": VideoSource(self.source).value,
            "status": VideoStatus(self.status).value,
            "duration_s": self.duration_s,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "file_url": self.file_url,
            "prediction_source": PredictionSource(self.prediction_source).value,
            "provider": self.provider,
            "evaluation_eligible": self.evaluation_eligible,
            "model": self.model,
            "segments": self.segments,
            "metadata": self.metadata,
        }

    @property
    def is_processed(self) -> bool:
        """Whether an analysis result is actually attached."""
        return bool(self.segments) and self.prediction_source != PredictionSource.NONE
