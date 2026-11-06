"""Independent MiniCPM-V 4.5 + scene4 inference service for AutoDL."""

from cloud_vlm_service.config import Settings
from cloud_vlm_service.runtime import MiniCPMV45LoRARuntime

__all__ = ["MiniCPMV45LoRARuntime", "Settings"]
