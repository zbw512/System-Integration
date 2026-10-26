"""VLM adapter package.

``build_vlm_adapter`` is the single place that maps configuration to a concrete
adapter. Adding the real MiniCPM-V implementation (P0-5) touched this function
and one module — the API, services and storage layers stayed unchanged.

Two modes, never mixed:

* ``mock``    — deterministic placeholder labels, ``prediction_source=mock``;
* ``minicpm`` — real local MiniCPM-V 4.6 inference, ``prediction_source=model``.
  It never falls back to mock output when inference fails; the job fails instead.
"""

from __future__ import annotations

from config import SUPPORTED_VLM_ADAPTERS, Config
from adapters.vlm.base import AnalysisOutput, AnalysisRequest, VlmAdapter
from adapters.vlm.minicpm import MiniCPMV46Adapter
from adapters.vlm.mock import MockVlmAdapter

__all__ = [
    "AnalysisOutput",
    "AnalysisRequest",
    "VlmAdapter",
    "MiniCPMV46Adapter",
    "MockVlmAdapter",
    "build_vlm_adapter",
]


def build_vlm_adapter(config: Config) -> VlmAdapter:
    """Instantiate the adapter selected by ``config.vlm_adapter``."""
    name = (config.vlm_adapter or "").lower()

    if name == "mock":
        return MockVlmAdapter()
    if name == "minicpm":
        return MiniCPMV46Adapter(config)

    # ``Config.from_env`` already rejects unknown values; this guards direct
    # dataclass construction (e.g. in tests) from silently building nothing.
    raise ValueError(
        f"未知的 VLM 适配器 {config.vlm_adapter!r}，可选值：{list(SUPPORTED_VLM_ADAPTERS)}"
    )
