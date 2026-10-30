import json
import os

from core.app_meta import APP_BUILD
from core.tunnel_runtime import load_active_runtime, process_is_running


def test_runtime_url_requires_live_current_build(tmp_path):
    assert process_is_running(os.getpid()) is True
    runtime_path = tmp_path / "line_bot_runtime.json"
    status = {
        "pid": os.getpid(),
        "app_build": APP_BUILD,
        "tunnel_url": "https://example.ngrok-free.dev/",
        "webhook_url": "https://wrong.example/callback",
    }
    runtime_path.write_text(json.dumps(status), encoding="utf-8")

    runtime = load_active_runtime(runtime_path)

    assert runtime["tunnel_url"] == "https://example.ngrok-free.dev"
    assert runtime["webhook_url"] == "https://example.ngrok-free.dev/callback"


def test_runtime_url_rejects_legacy_or_dead_owner(tmp_path):
    assert process_is_running(99999999) is False
    runtime_path = tmp_path / "line_bot_runtime.json"
    runtime_path.write_text(json.dumps({
        "pid": 99999999,
        "tunnel_url": "https://old.example.ngrok-free.dev",
    }), encoding="utf-8")

    assert load_active_runtime(runtime_path) == {}
