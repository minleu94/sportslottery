# -*- coding: utf-8 -*-
"""Launcher for Taiwan Sports Lottery System.

Compiles into 'sportslottery.exe'.
Coordinates 3-in-1 resident services in Windows System Tray:
1. Desktop Streamlit Web UI (http://localhost:8501)
2. Mobile Public HTTPS Web (Cloudflare Tunnel)
3. LINE Bot Interactive Webhook Server (Port 8000 + Cloudflare Tunnel)
4. Windows Notification Area Tray Icon (pystray)
"""

from __future__ import annotations

import ctypes
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

LOCK_PORT = 28501


def hide_console():
    """Hide console window on Windows."""
    if sys.platform == "win32":
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE = 0
        except Exception:
            pass


def ensure_streamlit_credentials(project_dir: Path):
    """Ensure ~/.streamlit/credentials.toml and project/.streamlit/credentials.toml exist to prevent email prompt."""
    content = "[general]\nemail = ''\n"
    # User home
    try:
        home_st = Path.home() / ".streamlit"
        home_st.mkdir(parents=True, exist_ok=True)
        creds_file = home_st / "credentials.toml"
        if not creds_file.exists():
            creds_file.write_text(content, encoding="utf-8")
    except Exception:
        pass

    # Project directory
    try:
        proj_st = project_dir / ".streamlit"
        proj_st.mkdir(parents=True, exist_ok=True)
        proj_creds = proj_st / "credentials.toml"
        if not proj_creds.exists():
            proj_creds.write_text(content, encoding="utf-8")

        proj_cfg = proj_st / "config.toml"
        if not proj_cfg.exists():
            proj_cfg.write_text(
                "[server]\nport = 8501\nheadless = true\n\n[browser]\ngatherUsageStats = false\n",
                encoding="utf-8",
            )
    except Exception:
        pass


def find_project_dir() -> Path:
    # If running as compiled exe, sys.executable is the exe path
    exe_dir = Path(sys.executable).resolve().parent
    if (exe_dir / "app.py").exists():
        return exe_dir
    # If running as script
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "app.py").exists():
        return script_dir
    configured = os.environ.get("SPORTSLOTTERY_WORKSPACE")
    if configured and (Path(configured) / "app.py").is_file():
        return Path(configured).expanduser().resolve()
    return ROOT_DIR


def is_port_in_use(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


def main():
    project_dir = find_project_dir()
    ensure_streamlit_credentials(project_dir)

    # 1. If tray manager is already running, open browser and exit
    if is_port_in_use(LOCK_PORT):
        webbrowser.open("http://localhost:8501")
        return

    # 2. Hide console window so it acts like a clean system tray app
    hide_console()

    # 3. Import and run AppTrayManager
    from scripts.tray_manager import AppTrayManager
    app = AppTrayManager()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
