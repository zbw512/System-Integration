"""VLM adapter contract.

The rest of the backend knows *only* this interface. An adapter:

1. receives everything it needs through :class:`AnalysisRequest` (video id,
   resolved file path, duration, job id, metadata);
2. returns an :class:`AnalysisOutput` describing what produced the labels.

The adapter does **not** know about HTTP, SQLite, job status or JSON responses —
that separation is what makes the mock and the future MiniCPM adapter
interchangeable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class AnalysisRequest:
    """Everything an adapter needs to analyse one video.

    ``video_path`` is an absolute path that the service layer has already
    validated to be inside the data directory; an adapter must treat it as
    read-only and must not persist it in any client-facing payload.
    """

    job_id: str
    video_id: str
    video_path: str
    duration_s: float | None
    video_metadata: dict[str, Any] = field(default_factory=dict)
    #: Optional hook ``(stage_name, progress_0_to_1)`` so an adapter can report
    #: its real stages (sampling/inference) instead of the runner guessing.
    on_progress: Callable[[str, float], None] | None = None


@dataclass(frozen=True)
class AnalysisOutput:
    """Result of one adapter run.

    ``prediction_source`` must be one of the standard's enum values; a mock
    adapter therefore reports ``mock`` (never ``model``).
    """

    prediction_source: str
    provider: str
    model: dict[str, Any]
    segments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_mock(self) -> bool:
        return bool(self.metadata.get("is_mock")) or self.prediction_source == "mock"


class VlmAdapter(ABC):
    """Abstract base class every VLM adapter implements."""

    #: Short adapter identifier, e.g. ``mock``.
    name: str = "base"

    #: Whether :meth:`analyze` decodes the video itself before inference.
    #: The job runner uses this to announce the ``sampling_frames`` stage.
    uses_frame_sampling: bool = False

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Machine-readable description published by ``GET /api/v1/info``."""

    @abstractmethod
    def analyze(self, request: AnalysisRequest) -> AnalysisOutput:
        """Analyse one video and return standard-compatible segments.

        Implementations must raise :class:`services.errors.VlmAnalysisError`
        when the analysis cannot be completed, and must never return labels
        they did not actually produce.
        """
