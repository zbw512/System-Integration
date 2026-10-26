"""Data model / validation layer.

P0-1 only publishes the shared enumerations. Video, segment, job and error
schemas are added in later P0 steps together with the code that uses them, so
no empty placeholder modules are created here.
"""

from __future__ import annotations

__all__ = ["enums"]
