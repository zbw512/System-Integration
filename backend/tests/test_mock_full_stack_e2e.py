"""No-GPU end-to-end test: Flask -> HTTP mock AutoDL -> SQLite -> result."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import create_app
from cloud_vlm_service.mock_server import create_server, run_server
from config import Config
from video_fixtures import write_test_video

TOKEN = "full-stack-token-0123456789abcdef"


def test_full_http_stack_with_mock_autodl(tmp_path: Path) -> None:
    mock_vlm = create_server(
        host="127.0.0.1",
        port=0,
        token=TOKEN,
        label="小组讨论",
    )
    ready = threading.Event()
    mock_thread = run_server(mock_vlm, ready_event=ready)
    assert ready.wait(2)

    app = create_app(
        Config(
            testing=True,
            log_level="CRITICAL",
            data_dir=str(tmp_path / "backend-data"),
            job_worker_enabled=True,
            vlm_adapter="minicpm_remote",
            vlm_remote_url=f"http://127.0.0.1:{mock_vlm.server_port}",
            vlm_remote_token=TOKEN,
            vlm_remote_retries=0,
            vlm_max_frames=8,
            vlm_window_seconds=3.0,
            vlm_window_stride_seconds=3.0,
        )
    )
    flask_server = make_server("127.0.0.1", 0, app, threaded=True)
    flask_thread = threading.Thread(
        target=flask_server.serve_forever,
        daemon=True,
        name="flask-e2e",
    )
    flask_thread.start()

    video = write_test_video(tmp_path / "three.mp4", seconds=3.0, fps=2)
    project_root = Path(__file__).resolve().parents[2]
    script = project_root / "scripts" / "test_full_video_e2e.py"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--video",
                str(video),
                "--api-base",
                f"http://127.0.0.1:{flask_server.server_port}",
                "--timeout-s",
                "20",
                "--poll-s",
                "0.1",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert completed.returncode == 0, completed.stderr + completed.stdout
        assert '"prediction_source": "model"' in completed.stdout
        assert '"provider": "minicpm_v"' in completed.stdout
        assert '"segment_count": 1' in completed.stdout
        assert "小组讨论" in completed.stdout
    finally:
        flask_server.shutdown()
        flask_thread.join(timeout=3)
        app.extensions["job_runner"].stop()
        mock_vlm.shutdown()
        mock_vlm.server_close()
        mock_thread.join(timeout=3)
