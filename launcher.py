# -*- coding: utf-8 -*-
"""Modern Launcher for Taiwan Sports Lottery System.

Compiles into 'sportslottery.exe'.
Launches the modern FastAPI + React (shadcn/ui + Tailwind) application on port 8000,
monitors server readiness, and opens the default browser automatically.
Fallback to port 8001..8010 if occupied.
"""

from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path


def set_console_title(title: str):
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except Exception:
            pass


def find_project_dir() -> Path:
    # 1. If running as compiled exe, sys.executable is the exe path
    exe_dir = Path(sys.executable).resolve().parent
    if (exe_dir / "server" / "api.py").exists():
        return exe_dir
    # 2. If running as script
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "server" / "api.py").exists():
        return script_dir
    # 3. Environment variable
    configured = os.environ.get("SPORTSLOTTERY_WORKSPACE")
    if configured and (Path(configured) / "server" / "api.py").is_file():
        return Path(configured).expanduser().resolve()
    # 4. Fallback check current directory
    cwd = Path.cwd().resolve()
    if (cwd / "server" / "api.py").exists():
        return cwd
    raise FileNotFoundError("找不到 server/api.py。請確認專案路徑正確。")


def find_python_executable() -> str:
    # Always prioritize the official Python install on host machine
    candidates = [
        r"C:\Program Files\Python311\python.exe",
        shutil.which("python"),
        shutil.which("python3"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return str(Path(c).resolve())
    return "python"


def is_server_alive(url: str) -> bool:
    try:
        req = urllib.request.Request(f"{url}/api/health", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
            return False


def find_available_port(start_port: int = 8000) -> int:
    for p in range(start_port, start_port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', p)) != 0:
                return p
    return start_port


def wait_and_open_browser(url: str, timeout: float = 30.0):
    import webbrowser
    start_time = time.time()
    opened = False
    while time.time() - start_time < timeout:
        if is_server_alive(url):
            time.sleep(0.3)
            webbrowser.open(url)
            opened = True
            print(f"\n🚀 運彩決策台已成功就緒！已為您自動開啟瀏覽器 ({url})\n")
            break
        time.sleep(0.5)

    if not opened:
        print(f"\n⚠️ 決策台啟動耗時較久，請手動在瀏覽器開啟：{url}")


def main():
    import webbrowser
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    set_console_title("台灣運彩「瘋狗流」高倍串關決策台 (Modern Edition)")

    project_dir = find_project_dir()
    python_bin = find_python_executable()

    default_url = "http://127.0.0.1:8000"

    # 1. Check if an instance is already running
    if is_server_alive(default_url):
        print(rf"""
======================================================================
  🐕 台灣運彩「瘋狗流」決策系統 - Modern Edition (v2.0)
======================================================================
- 專案目錄 : {project_dir}
- 狀態     : 運彩決策台已在背景運行中！
- 決策台   : {default_url}
======================================================================
正在為您重新開啟瀏覽器...
""")
        webbrowser.open(default_url)
        print("【系統提醒】")
        print("1. 系統已自動於瀏覽器開啟。")
        print("2. 若要結束服務，請關閉此視窗或按下 Ctrl+C。")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n系統已停止。祝您投注愉快！")
        return

    # 2. Select available port (default 8000, or fallback 8001, 8002...)
    port = find_available_port(8000)
    url = f"http://127.0.0.1:{port}"

    banner = rf"""
======================================================================
  🐕 台灣運彩「瘋狗流」10~500倍高期望值串關系統 (Modern Edition)
  React + TypeScript + Tailwind CSS + shadcn/ui + FastAPI
======================================================================
- 專案目錄 : {project_dir}
- Python   : {python_bin}
- 決策台   : {url}
======================================================================
正在啟動現代化決策引擎與 API 服務，請稍候...
"""
    print(banner)

    # Command to run uvicorn
    cmd = [
        python_bin,
        "-m",
        "uvicorn",
        "server.api:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]

    proc = None
    abnormal_exit = False
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(project_dir),
            env=os.environ.copy(),
        )

        def cleanup():
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        atexit.register(cleanup)

        # Background thread to poll health and open browser
        browser_thread = threading.Thread(target=wait_and_open_browser, args=(url,), daemon=True)
        browser_thread.start()

        print("【系統提醒】")
        print("1. 服務啟動後將自動開啟預設瀏覽器（Edge / Chrome / Brave）。")
        print("2. 本系統每週嚴格風控 NT$ 200，贏錢全數自動轉入保留池。")
        print("3. 若要關閉系統，直接關閉此黑色視窗或按下 Ctrl+C 即可。\n")

        ret_code = proc.wait()
        if ret_code != 0:
            abnormal_exit = True
            print(f"\n❌ 運彩系統異常結束 (退出代碼: {ret_code})")
            input("\n按 Enter 鍵關閉視窗...")

    except KeyboardInterrupt:
        print("\n正在停止系統服務...")
    finally:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        if not abnormal_exit:
            print("系統已安全停止。祝您投注愉快、理性運彩！")


if __name__ == "__main__":
    main()
