"""Adapters bridging backend business code and concrete model implementations.

Currently only a VLM (vision-language model) adapter exists. The EEG adapter
arrives in a later phase; nothing here pretends the EEG model is available.
"""

from __future__ import annotations

__all__ = ["vlm"]
