# -*- coding: utf-8 -*-
"""Standalone Desktop Launcher for Taiwan Sports Lottery System.

Designed for PyInstaller standalone bundles on Windows and macOS.
Runs Streamlit internally without requiring Python installed on the host system,
auto-suppresses setup prompts, monitors server readiness, and opens default browser.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def set_console_title(title: str):
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except Exception:
            pass


def get_base_dir() -> Path:
    """Resolve the directory containing project resources."""
    if getattr(sys, "frozen", False):
        # Running inside PyInstaller bundle
        if hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ensure_streamlit_environment(base_dir: Path):
    """Ensure ~/.streamlit/credentials.toml and config exist to prevent prompts and telemetry."""
    content_creds = "[general]\nemail = ''\n"
    content_config = """[server]
port = 8501
headless = true
enableCORS = false
enableXsrfProtection = false

[browser]
gatherUsageStats = false
"""
    # 1. User home streamlit directory
    try:
        home_st = Path.home() / ".streamlit"
        home_st.mkdir(parents=True, exist_ok=True)
        creds_file = home_st / "credentials.toml"
        if not creds_file.exists():
            creds_file.write_text(content_creds, encoding="utf-8")
    except Exception:
        pass

    # 2. Local streamlit directory in writable location
    try:
        proj_st = base_dir / ".streamlit"
        proj_st.mkdir(parents=True, exist_ok=True)
        (proj_st / "credentials.toml").write_text(content_creds, encoding="utf-8")
        (proj_st / "config.toml").write_text(content_config, encoding="utf-8")
    except Exception:
        pass


def wait_and_open_browser(url: str, timeout: float = 35.0):
    """Poll the Streamlit HTTP server until responsive, then open default browser."""
    start_time = time.time()
    opened = False
    health_url = f"{url}/_stcore/health"

    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(health_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    time.sleep(0.5)
                    webbrowser.open(url)
                    opened = True
                    print(f"\n🚀 運彩決策台已成功就緒！已為您自動開啟瀏覽器 ({url})\n")
                    break
        except Exception:
            try:
                # Fallback to main URL check
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        time.sleep(0.5)
                        webbrowser.open(url)
                        opened = True
                        print(f"\n🚀 運彩決策台已成功就緒！已為您自動開啟瀏覽器 ({url})\n")
                        break
            except Exception:
                pass
        time.sleep(0.5)

    if not opened:
        print(f"\n⚠️ 伺服器啟動耗時較久，請手動在瀏覽器輸入網址開啟：{url}")


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    set_console_title("台灣運彩「瘋狗流」決策系統")

    base_dir = get_base_dir()
    app_path = base_dir / "app.py"

    # Pre-configure Streamlit environment
    ensure_streamlit_environment(base_dir)

    # Make sure base_dir is first in sys.path
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))

    url = "http://localhost:8501"

    banner = rf"""
======================================================================
  🐕 台灣運彩「瘋狗流」10~500倍高期望值串關系統
  賽季雷達 · Signal Hub 情報串關 · 每週 NT$ 200 嚴格風控
======================================================================
- 運行目錄 : {base_dir}
- 決策台   : {url}
======================================================================
正在啟動運彩決策引擎，請稍候...
"""
    print(banner)

    if not app_path.exists():
        print(f"❌ 嚴重錯誤：找不到主程式入口檔案 {app_path}")
        input("按 Enter 鍵關閉...")
        return

    # Start browser polling thread in background
    browser_thread = threading.Thread(target=wait_and_open_browser, args=(url,), daemon=True)
    browser_thread.start()

    print("【系統提醒】")
    print("1. 服務啟動後將自動開啟預設瀏覽器（Edge / Chrome / Safari）。")
    print("2. 本系統每週嚴格風控 NT$ 200，理性運彩、健康投資。")
    print("3. 若要關閉系統，直接關閉此視窗或按下 Ctrl+C 即可。\n")

    # Launch Streamlit via internal CLI in the same process
    try:
        from streamlit.web import cli as stcli

        sys.argv = [
            "streamlit",
            "run",
            str(app_path),
            "--server.port=8501",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
            "--global.developmentMode=false",
        ]
        sys.exit(stcli.main())
    except KeyboardInterrupt:
        print("\n系統已安全停止。祝您投注愉快！")
    except Exception as exc:
        print(f"\n❌ 啟動失敗: {exc}")
        input("\n按 Enter 鍵關閉視窗...")


if __name__ == "__main__":
    main()
