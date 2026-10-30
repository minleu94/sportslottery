#!/usr/bin/env python3
"""Windows System Tray Manager for 台灣運彩瘋狗流決策台.

Runs LINE Bot Webhook server + Cloudflare Tunnel + Streamlit Web UI in the background
without any visible console windows. Places an interactive icon in the Windows
Notification Area (System Tray) for status observation, 1-click browser launch,
copying public HTTPS URLs to clipboard, service restart, and clean exit.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image
import pystray
from pystray import Icon, Menu, MenuItem

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STATUS_FILE = ROOT_DIR / "data" / "line_bot_runtime.json"
ICON_PATH = ROOT_DIR / "app_icon.ico"
LOCK_PORT = 28501  # Socket port used to ensure single instance
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def find_python_executable(gui: bool = False) -> str:
    """Find installed Python executable on host system."""
    name = "pythonw.exe" if gui else "python.exe"
    candidates = [
        rf"C:\Program Files\Python311\{name}",
        shutil.which("pythonw" if gui else "python"),
        os.path.expandvars(rf"%LOCALAPPDATA%\Programs\Python\Python311\{name}"),
        os.path.expandvars(rf"%LOCALAPPDATA%\Programs\Python\Python312\{name}"),
        sys.executable,
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return str(Path(c).resolve())
    return name


def copy_to_clipboard(text: str) -> bool:
    """Copy text string to Windows clipboard using clip.exe."""
    try:
        subprocess.run(["clip.exe"], input=text.encode("utf-16"), check=True)
        return True
    except Exception:
        return False


def get_runtime_info() -> Dict[str, Any]:
    """Read line_bot_runtime.json for active tunnel URLs."""
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def kill_proc_tree(proc: Optional[subprocess.Popen]) -> None:
    """Forcefully kill process and all its children via taskkill on Windows."""
    if not proc or proc.poll() is not None:
        return
    pid = proc.pid
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class AppTrayManager:
    """Coordinates background processes and manages Windows System Tray."""

    def __init__(self):
        self.proc_bot: Optional[subprocess.Popen] = None
        self.proc_st: Optional[subprocess.Popen] = None
        self.icon: Optional[Icon] = None
        self._lock_sock: Optional[socket.socket] = None
        self.is_running: bool = False
        self._status_text: str = "⏳ 服務啟動中..."

    def acquire_single_instance(self) -> bool:
        """Prevent multiple instances of tray manager using a loopback socket."""
        try:
            self._lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._lock_sock.bind(("127.0.0.1", LOCK_PORT))
            self._lock_sock.listen(1)
            return True
        except Exception:
            return False

    def load_tray_icon(self) -> Image.Image:
        """Load app icon or create dynamic fallback."""
        if ICON_PATH.exists():
            try:
                return Image.open(ICON_PATH)
            except Exception:
                pass
        # Fallback 64x64 green circle icon
        from PIL import ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill=(22, 163, 74), outline=(34, 197, 94), width=3)
        draw.polygon([(20, 42), (32, 18), (44, 42)], fill=(255, 255, 255))
        return img

    def _open_browser_when_ready(self, timeout: float = 35.0) -> None:
        """Poll Streamlit health check and automatically open browser."""
        url = "http://localhost:8501"
        start_t = time.time()
        while time.time() - start_t < timeout and self.is_running:
            try:
                req = urllib.request.Request(f"{url}/_stcore/health", headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        time.sleep(0.5)
                        webbrowser.open(url)
                        return
            except Exception:
                time.sleep(0.5)

    def start_services(self) -> None:
        """Launch bot runner and streamlit server without console windows."""
        python_gui = find_python_executable(gui=True)

        # 1. Start LINE Bot runner (FastAPI on 8000 + cloudflared tunnels for LINE + mobile)
        bot_cmd = [python_gui, "scripts/serve_line_bot.py"]
        self.proc_bot = subprocess.Popen(
            bot_cmd,
            cwd=str(ROOT_DIR),
            creationflags=CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 2. Start Streamlit web server on port 8501
        st_cmd = [
            python_gui,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.address",
            "0.0.0.0",
            "--server.port",
            "8501",
            "--browser.gatherUsageStats",
            "false",
        ]
        self.proc_st = subprocess.Popen(
            st_cmd,
            cwd=str(ROOT_DIR),
            creationflags=CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        self.is_running = True
        self._status_text = "🟢 服務正常運行中 (LINE + Web)"

        # 3. Background thread to auto-open browser when Streamlit is responsive
        threading.Thread(target=self._open_browser_when_ready, daemon=True).start()

    def stop_services(self) -> None:
        """Terminate all background processes and tunnels."""
        self.is_running = False
        self._status_text = "🔴 服務已停止"
        kill_proc_tree(self.proc_bot)
        kill_proc_tree(self.proc_st)
        self.proc_bot = None
        self.proc_st = None
        if STATUS_FILE.exists():
            try:
                STATUS_FILE.unlink(missing_ok=True)
            except Exception:
                pass

    def restart_services(self) -> None:
        """Restart all services."""
        self._status_text = "🔄 服務重啟中..."
        if self.icon:
            self.icon.update_menu()
        self.stop_services()
        time.sleep(1.5)
        self.start_services()
        if self.icon:
            self.icon.update_menu()
            self.icon.notify("LINE 機器人與決策台服務已成功重新啟動！", "瘋狗流運彩")

    def open_web_browser(self) -> None:
        """Open local Streamlit web UI in default browser."""
        webbrowser.open("http://localhost:8501")

    def copy_public_url(self) -> None:
        """Copy public Cloudflare HTTPS URL to clipboard."""
        info = get_runtime_info()
        url = info.get("streamlit_url")
        if url:
            copy_to_clipboard(url)
            if self.icon:
                self.icon.notify(f"已複製公網網址至剪貼簿：\n{url}\n（可直接傳送給手機使用）", "瘋狗流運彩")
        else:
            if self.icon:
                self.icon.notify("公網通道尚未連線完成，請稍候 3 秒後再試。", "瘋狗流運彩")

    def copy_webhook_url(self) -> None:
        """Copy LINE Webhook URL to clipboard."""
        info = get_runtime_info()
        url = info.get("webhook_url")
        if url:
            copy_to_clipboard(url)
            if self.icon:
                self.icon.notify(f"已複製 Webhook 網址：\n{url}", "瘋狗流運彩")
        else:
            if self.icon:
                self.icon.notify("Webhook 尚未配發，請稍候再試。", "瘋狗流運彩")

    def monitor_loop(self) -> None:
        """Background thread monitoring process health."""
        while self.is_running:
            time.sleep(4.0)
            b_alive = self.proc_bot and self.proc_bot.poll() is None
            s_alive = self.proc_st and self.proc_st.poll() is None
            if b_alive and s_alive:
                self._status_text = "🟢 服務正常運行中 (LINE + Web)"
            elif not b_alive and not s_alive:
                self._status_text = "🔴 服務異常中斷"
            elif not b_alive:
                self._status_text = "⚠️ LINE 服務異常"
            else:
                self._status_text = "⚠️ Web 網頁異常"

    def on_quit(self, icon: Icon, item: Any) -> None:
        """Handle Quit menu item."""
        self.stop_services()
        if self._lock_sock:
            try:
                self._lock_sock.close()
            except Exception:
                pass
        icon.stop()

    def build_menu(self) -> Menu:
        """Create tray context menu."""
        return Menu(
            MenuItem(lambda text: self._status_text, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("🌐 開啟決策台 (電腦瀏覽器)", lambda: self.open_web_browser(), default=True),
            MenuItem("📱 複製手機公網網址 (HTTPS)", lambda: self.copy_public_url()),
            MenuItem("💬 複製 LINE Webhook 網址", lambda: self.copy_webhook_url()),
            Menu.SEPARATOR,
            MenuItem("🔄 重新啟動服務", lambda: threading.Thread(target=self.restart_services, daemon=True).start()),
            MenuItem("❌ 停止並退出服務 (Quit)", self.on_quit),
        )

    def run(self) -> int:
        """Main entry point."""
        if not self.acquire_single_instance():
            print("瘋狗流系統匣服務已經在運行中，請檢查右下角系統匣圖示。")
            return 1

        self.start_services()

        # Start health check monitor
        t_mon = threading.Thread(target=self.monitor_loop, daemon=True)
        t_mon.start()

        # Build pystray Icon
        icon_img = self.load_tray_icon()
        self.icon = Icon(
            name="sportslottery_tray",
            icon=icon_img,
            title="台灣運彩 瘋狗流 (服務運行中)",
            menu=self.build_menu(),
        )

        try:
            # Notify user on startup
            time.sleep(1.0)
            self.icon.notify(
                "瘋狗流 3-in-1 服務已啟動！\n已在右下角系統匣常駐，並已為您開啟決策台。\n右鍵點擊圖示可查看狀態或複製手機網址。",
                "台灣運彩 瘋狗流",
            )
        except Exception:
            pass

        # Blocks until icon.stop() is called
        self.icon.run()
        return 0


if __name__ == "__main__":
    app = AppTrayManager()
    sys.exit(app.run())
