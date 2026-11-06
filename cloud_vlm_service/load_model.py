"""Load and validate the real model once, then exit."""

from __future__ import annotations

import json
import logging
import sys

from cloud_vlm_service.config import Settings
from cloud_vlm_service.runtime import MiniCPMV45LoRARuntime


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        settings = Settings.from_env()
        runtime = MiniCPMV45LoRARuntime(settings)
        runtime.load()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "health": runtime.health_snapshot(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
