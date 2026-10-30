"""Read the one public URL published by the current tray-managed build."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.app_meta import APP_BUILD


def process_is_running(pid: Any) -> bool:
    try:
        process_id = int(pid)
        if process_id <= 0:
            return False
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL

            handle = kernel32.OpenProcess(0x00100000, False, process_id)  # SYNCHRONIZE
            if not handle:
                return False
            try:
                return kernel32.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT
            finally:
                kernel32.CloseHandle(handle)
        os.kill(process_id, 0)
        return True
    except (TypeError, ValueError, OSError):
        return False


def load_active_runtime(path: Path) -> dict[str, Any]:
    """Return runtime metadata only when it belongs to this live app build."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("app_build") != APP_BUILD:
        return {}
    if not process_is_running(data.get("pid")):
        return {}
    url = str(data.get("tunnel_url") or "").rstrip("/")
    if not url.startswith("https://"):
        return {}
    data["tunnel_url"] = url
    data["webhook_url"] = f"{url}/callback"
    return data
