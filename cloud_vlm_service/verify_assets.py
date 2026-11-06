"""Verify model file structure without loading Torch or allocating GPU memory."""

from __future__ import annotations

import json
import sys

from cloud_vlm_service.config import Settings
from cloud_vlm_service.runtime import inspect_model_assets


def main() -> int:
    try:
        settings = Settings.from_env()
    except Exception as exc:
        print(json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False))
        return 2

    result = inspect_model_assets(settings)
    print(json.dumps({"ok": result["valid"], **result}, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
