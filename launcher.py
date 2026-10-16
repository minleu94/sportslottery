# -*- coding: utf-8 -*-
"""Launcher for Taiwan Sports Lottery System.

Compiles into 'sportslottery.exe'.
Automates environment setup, suppresses first-run prompts, waits for HTTP 200,
and opens the user's browser seamlessly.
"""

from __future__ import annotations

import atexit
import os
import shutil
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
    raise FileNotFoundError("找不到 app.py。請使用 sportslottery --workspace 工作目錄，或從專案目錄啟動。")


def find_python_executable() -> str:
    candidates = [
        r"C:\Program Files\Python311\python.exe",
        shutil.which("python"),
        shutil.which("python3"),
        sys.executable if "python" in Path(sys.executable).name.lower() else None,
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return str(Path(c).resolve())
    return "python"


def wait_and_open_browser(url: str, timeout: float = 30.0):
    import webbrowser
    start_time = time.time()
    opened = False
    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    time.sleep(0.5)
                    webbrowser.open(url)
                    opened = True
                    print(f"\n🚀 決策台已成功就緒！已為您自動開啟瀏覽器 ({url})")
                    break
        except Exception:
            time.sleep(0.5)

    if not opened:
        print(f"\n⚠️ 決策台啟動耗時較久，請手動在瀏覽器開啟：{url}")


def main():
    # Ensure UTF-8 output
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    set_console_title("Sports Lottery System")

    project_dir = find_project_dir()
    app_path = project_dir / "app.py"
    python_bin = find_python_executable()
    url = "http://localhost:8501"

    # Pre-configure credentials before starting anything
    ensure_streamlit_credentials(project_dir)

    banner = rf"""
======================================================================
  🐕 台灣運彩「瘋狗流」10~500倍高期望值串關系統
  賽季雷達 · Signal Hub 情報串關 · 每週 NT$ 200 嚴格風控
======================================================================
- 專案目錄 : {project_dir}
- Python   : {python_bin}
- 決策台   : {url}
======================================================================
正在啟動運彩決策引擎，請稍候...
"""
    print(banner)

    if not app_path.exists():
        print(f"❌ 找不到主程式檔案：{app_path}")
        print("請確認此程式與專案檔案位於同一目錄中。")
        input("\n按 Enter 鍵關閉...")
        return

    cmd = [
        python_bin,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port=8501",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]

    proc = None
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

        # Background thread to wait for HTTP 200 before opening browser
        browser_thread = threading.Thread(target=wait_and_open_browser, args=(url,), daemon=True)
        browser_thread.start()

        print("【系統提醒】")
        print("1. 服務啟動後將自動彈出瀏覽器。")
        print("2. 本系統每週嚴格風控 NT$ 200，贏錢自動鎖入獲利池。")
        print("3. 若要關閉系統，直接關閉此黑色視窗或按下 Ctrl+C 即可。\n")

        # Keep alive until user closes window
        proc.wait()

    except KeyboardInterrupt:
        print("\n正在停止系統服務...")
    finally:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        print("系統已安全停止。祝您投注愉快、理性運彩！")


if __name__ == "__main__":
    main()
