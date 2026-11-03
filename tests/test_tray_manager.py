#!/usr/bin/env python3
"""Automated Unit Tests for Tray Manager & Zero-Friction Startup.

Validates:
1. Localhost DNS bypassing: verifies fallback to 127.0.0.1 for instant Windows connection.
2. Single-instance acquisition: when lock is already held, opens browser and returns 0 instead of silent exit.
3. Stale port cleanup: detects and cleans stale port owners before launching uvicorn.
4. ngrok command line includes --pooling-enabled to avoid ERR_NGROK_334.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from scripts.tray_manager import (
    AppTrayManager,
    LOCK_PORT,
    PORT,
)


def test_tray_manager_urls_use_ip_loopback():
    """Verify tray manager uses 127.0.0.1 rather than localhost to avoid Windows IPv6 resolution latency."""
    app = AppTrayManager()
    with patch("webbrowser.open") as mock_open:
        app.open_web_browser()
        mock_open.assert_called_once_with(f"http://127.0.0.1:{PORT}")


def test_single_instance_held_directly_opens_browser():
    """Verify that when tray is already resident, re-running opens the browser instead of silently failing."""
    app = AppTrayManager()
    with patch.object(app, "acquire_single_instance", return_value=False), \
         patch("webbrowser.open") as mock_open:
        ret = app.run()
        assert ret == 0
        mock_open.assert_called_once_with(f"http://127.0.0.1:{PORT}")


def test_ngrok_command_includes_pooling_flag(tmp_path, monkeypatch):
    """Verify that ngrok launch includes --pooling-enabled to prevent ERR_NGROK_334 on re-runs."""
    import scripts.tray_manager as tray_manager

    monkeypatch.setattr(tray_manager, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(tray_manager, "STATUS_FILE", tmp_path / "data" / "line_bot_runtime.json")
    monkeypatch.setattr(tray_manager, "TRAY_LOG", tmp_path / "data" / "tray_runtime.log")
    (tmp_path / "data").mkdir()
    app = AppTrayManager()
    app._network_access_allowed = True
    with patch("scripts.tray_manager.find_ngrok", return_value="ngrok.exe"), \
         patch("scripts.tray_manager.load_ngrok_config", return_value={"domain": "test-domain.ngrok-free.dev"}), \
         patch("scripts.tray_manager.subprocess.run") as mock_run, \
         patch("scripts.tray_manager.subprocess.Popen") as mock_popen, \
         patch("scripts.tray_manager.register_line_webhook", return_value=True), \
         patch("scripts.tray_manager.load_line_token", return_value="test_token"), \
         patch("time.sleep"):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        app._start_tunnel("cloudflared")
        assert mock_popen.called
        cmd = mock_popen.call_args[0][0]
        assert "--pooling-enabled" in cmd
        assert f"http://127.0.0.1:{PORT}" in cmd
        assert not any("taskkill" in str(call.args[0]).lower() for call in mock_run.call_args_list)


def test_local_only_startup_does_not_terminate_or_reuse_an_existing_api(tmp_path, monkeypatch):
    import scripts.tray_manager as tray_manager

    monkeypatch.setattr(tray_manager, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(tray_manager, "STATUS_FILE", tmp_path / "data" / "runtime.json")
    monkeypatch.setattr(tray_manager, "TRAY_LOG", tmp_path / "data" / "tray.log")
    monkeypatch.setattr(tray_manager, "is_port_in_use", lambda _port: True)
    monkeypatch.setattr(tray_manager, "find_python_executable", lambda gui=False: "python")
    monkeypatch.setattr(tray_manager, "find_cloudflared", lambda: "")
    monkeypatch.setattr("core.bootstrap_security.network_access_enabled", lambda: False)

    response = MagicMock()
    response.status = 200
    response.read.return_value = json.dumps({"app_build": tray_manager.APP_BUILD}).encode("utf-8")
    urlopen = MagicMock()
    urlopen.return_value.__enter__.return_value = response
    monkeypatch.setattr(tray_manager.urllib.request, "urlopen", urlopen)

    app = AppTrayManager()
    with patch("scripts.tray_manager.subprocess.Popen") as popen:
        app.start_services()

    popen.assert_not_called()
    assert app.is_running is False
    assert "停止現有 API" in app._status_text


def test_restart_failure_notification_reports_failure():
    app = AppTrayManager()
    app.icon = MagicMock()

    def failed_start():
        app.is_running = False
        app._status_text = "port unavailable"

    with patch.object(app, "stop_services"), patch.object(app, "start_services", side_effect=failed_start), patch("time.sleep"):
        app.restart_services()

    app.icon.notify.assert_called_once_with("服務未能啟動：port unavailable", "瘋狗流 v2.3.0 Dev")


def test_run_failure_notification_does_not_claim_success(monkeypatch):
    app = AppTrayManager()
    app.acquire_single_instance = lambda: True
    app.build_menu = lambda: None
    app.load_tray_icon = lambda: None

    def failed_start():
        app.is_running = False
        app._status_text = "port unavailable"

    app.start_services = failed_start
    app.monitor_loop = lambda: None
    icon = MagicMock()
    monkeypatch.setitem(sys.modules, "pystray", SimpleNamespace(Icon=MagicMock(return_value=icon)))

    with patch("time.sleep"):
        assert app.run() == 0

    icon.notify.assert_called_once_with("服務未能啟動：port unavailable", "台灣運彩 瘋狗流")
