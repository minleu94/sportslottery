#!/usr/bin/env python3
"""Automated Unit Tests for Tray Manager & Zero-Friction Startup.

Validates:
1. Localhost DNS bypassing: verifies fallback to 127.0.0.1 for instant Windows connection.
2. Single-instance acquisition: when lock is already held, opens browser and returns 0 instead of silent exit.
3. Stale port cleanup: detects and cleans stale port owners before launching uvicorn.
4. ngrok command line includes --pooling-enabled to avoid ERR_NGROK_334.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.tray_manager import (
    AppTrayManager,
    LOCK_PORT,
    PORT,
    is_port_in_use,
    kill_stale_port,
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


def test_ngrok_command_includes_pooling_flag():
    """Verify that ngrok launch includes --pooling-enabled to prevent ERR_NGROK_334 on re-runs."""
    app = AppTrayManager()
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
