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

LOCK_PORT = 28501
DEBUG_LOG = Path(r"C:\Projects\PythonProjects\sportslottery\data\launcher_debug.log")


def log_debug(msg: str):
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%X')}] {msg}\n")
    except Exception:
        pass


def hide_console():
    """Hide console window on Windows."""
    if sys.platform == "win32":
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass


def ensure_streamlit_credentials(project_dir: Path):
    content = "[general]\nemail = ''\n"
    try:
        home_st = Path.home() / ".streamlit"
        home_st.mkdir(parents=True, exist_ok=True)
        creds_file = home_st / "credentials.toml"
        if not creds_file.exists():
            creds_file.write_text(content, encoding="utf-8")
    except Exception:
        pass

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
    exe_dir = Path(sys.executable).resolve().parent
    if (exe_dir / "app.py").exists():
        return exe_dir
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "app.py").exists():
        return script_dir
    configured = os.environ.get("SPORTSLOTTERY_WORKSPACE")
    if configured and (Path(configured) / "app.py").is_file():
        return Path(configured).expanduser().resolve()
    return Path(r"C:\Projects\PythonProjects\sportslottery")


def is_port_in_use(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False


def main():
    log_debug("Launcher started")
    try:
        project_dir = find_project_dir()
        log_debug(f"Project dir: {project_dir}")
        if str(project_dir) not in sys.path:
            sys.path.insert(0, str(project_dir))

        ensure_streamlit_credentials(project_dir)

        if is_port_in_use(LOCK_PORT):
            log_debug("Lock port in use, opening browser and exiting")
            webbrowser.open("http://localhost:8501")
            return

        hide_console()
        log_debug("Importing AppTrayManager")
        from scripts.tray_manager import AppTrayManager
        log_debug("Instantiating AppTrayManager")
        app = AppTrayManager()
        log_debug("Running AppTrayManager")
        sys.exit(app.run())
    except Exception as exc:
        import traceback
        log_debug(f"Exception: {traceback.format_exc()}")
        raise


if __name__ == "__main__":
    main()
