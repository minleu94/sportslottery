# -*- coding: utf-8 -*-
"""Launcher for Taiwan Sports Lottery System (v2.3.0 Dev).

Compiles into 'sportslottery.exe'.
Coordinates single-port 3-in-1 resident services in Windows System Tray:
1. Modern Desktop React UI (http://localhost:8000)
2. Mobile Public HTTPS Web (Cloudflare Tunnel to Port 8000)
3. LINE Bot Interactive Webhook Server (/callback on Port 8000)
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
PORT = 8000


def hide_console():
    """Hide console window on Windows."""
    if sys.platform == "win32":
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass


def find_project_dir() -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "server" / "api.py").exists():
            return exe_dir
    cwd = Path.cwd().resolve()
    if (cwd / "server" / "api.py").exists():
        return cwd
    configured = os.environ.get("SPORTSLOTTERY_WORKSPACE")
    if configured and (Path(configured) / "server" / "api.py").is_file():
        return Path(configured).expanduser().resolve()
    return ROOT_DIR


def is_port_in_use(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


def main():
    try:
        project_dir = find_project_dir()
        if str(project_dir) not in sys.path:
            sys.path.insert(0, str(project_dir))

        # 1. If tray manager is already running, open browser and exit
        if is_port_in_use(LOCK_PORT):
            webbrowser.open(f"http://localhost:{PORT}")
            return

        # 2. Hide console window so it acts like a clean system tray app
        hide_console()

        # 3. Import and run AppTrayManager
        from scripts.tray_manager import AppTrayManager
        app = AppTrayManager()
        sys.exit(app.run())
    except Exception:
        import traceback
        log_dir = Path.home() / ".sportslottery"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "launcher_error.log", "a", encoding="utf-8") as f:
            f.write(f"=== Crash at {time.ctime()} ===\n")
            f.write(f"{traceback.format_exc()}\n")
        raise


if __name__ == "__main__":
    main()
