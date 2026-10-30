#!/usr/bin/env python3
"""Windows System Tray Manager for 台灣運彩瘋狗流決策台.

Runs LINE Bot Webhook server + Cloudflare Tunnel + Streamlit Web UI in the background
without any visible console windows. Places an interactive icon in the Windows
Notification Area (System Tray) for status observation, 1-click browser launch,
copying public HTTPS URLs to clipboard, service restart, and clean exit.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional

# Setup file logger
LOG_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / "tray_manager.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger("tray_manager")

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


def show_native_popup(msg: str, title: str = "台灣運彩 瘋狗流", is_error: bool = False):
    """Display native Windows message box popup."""
    try:
        import ctypes
        icon_flag = 0x10 if is_error else 0x40  # MB_ICONERROR or MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(0, msg, title, icon_flag)
    except Exception:
        pass


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
        self._monitor_enabled: bool = True
        self._status_text: str = "⏳ 服務啟動中..."
        self._restart_lock = threading.Lock()

    @staticmethod
    def _http_ok(url: str) -> bool:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "sportslottery-tray/1.0"})
            with urllib.request.urlopen(request, timeout=1.5) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError):
            return False

    def _wait_for_services(self, timeout: float = 45.0) -> tuple[bool, str]:
        """Wait until local endpoints and the public URL are ready."""
        deadline = time.monotonic() + timeout
        checks = (
            ("LINE webhook", "http://127.0.0.1:8001/"),
            ("Streamlit", "http://127.0.0.1:8501/_stcore/health"),
            ("URL router", "http://127.0.0.1:8502/_stcore/health"),
        )
        while time.monotonic() < deadline:
            for name, proc in (("LINE", self.proc_bot), ("Web", self.proc_st)):
                if proc is None or proc.poll() is not None:
                    return False, f"{name} service process exited during startup"
            local_ready = all(self._http_ok(url) for _, url in checks)
            runtime_info = get_runtime_info()
            public_ready = bool(runtime_info.get("streamlit_url") and runtime_info.get("webhook_url"))
            if local_ready and public_ready:
                return True, ""
            time.sleep(0.5)
        pending = [name for name, url in checks if not self._http_ok(url)]
        if not (get_runtime_info().get("streamlit_url") and get_runtime_info().get("webhook_url")):
            pending.append("public tunnel")
        return False, "Timed out waiting for: " + ", ".join(pending)

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

    def start_services(self, *, open_browser: bool = True) -> bool:
        """Launch services and report ready only after all local endpoints respond."""
        python_exe = sys.executable
        if python_exe.lower().endswith("pythonw.exe"):
            py_normal = python_exe[:-5] + ".exe"
            if os.path.exists(py_normal):
                python_exe = py_normal
        logger.info("Using python executable: %s", python_exe)

        self.is_running = False
        self._status_text = "⏳ 服務啟動中..."
        try:
            if STATUS_FILE.exists():
                STATUS_FILE.unlink(missing_ok=True)
            bot_cmd = [python_exe, "-u", "scripts/serve_line_bot.py"]
            with open(LOG_DIR / "bot_service.log", "a", encoding="utf-8") as bot_log:
                self.proc_bot = subprocess.Popen(
                    bot_cmd,
                    cwd=str(ROOT_DIR),
                    creationflags=CREATE_NO_WINDOW,
                    stdin=subprocess.DEVNULL,
                    stdout=bot_log,
                    stderr=subprocess.STDOUT,
                )

            st_cmd = [
                python_exe,
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
                "--server.headless",
                "true",
            ]
            with open(LOG_DIR / "streamlit_service.log", "a", encoding="utf-8") as st_log:
                self.proc_st = subprocess.Popen(
                    st_cmd,
                    cwd=str(ROOT_DIR),
                    creationflags=CREATE_NO_WINDOW,
                    stdin=subprocess.DEVNULL,
                    stdout=st_log,
                    stderr=subprocess.STDOUT,
                )

            ready, reason = self._wait_for_services()
            if not ready:
                raise RuntimeError(reason)
        except Exception as exc:
            logger.exception("Service startup failed: %s", exc)
            kill_proc_tree(self.proc_bot)
            kill_proc_tree(self.proc_st)
            self.proc_bot = None
            self.proc_st = None
            self.is_running = False
            self._status_text = f"⚠️ 服務啟動失敗：{exc}"
            return False

        self.is_running = True
        self._status_text = "🟢 服務正常運行中 (LINE + Web)"

        if open_browser:
            def _auto_open_browser():
                logger.info("Opening default web browser to http://localhost:8501")
                try:
                    webbrowser.open("http://localhost:8501")
                except Exception as exc:
                    logger.warning("Failed to open browser: %s", exc)

            threading.Thread(target=_auto_open_browser, daemon=True).start()
        return True

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
        """Restart only child services while keeping the tray process alive."""
        if not self._restart_lock.acquire(blocking=False):
            logger.info("Ignoring duplicate restart request; restart is already in progress.")
            return
        try:
            logger.info("Restarting managed services from tray menu.")
            self._status_text = "🔄 服務重啟中..."
            if self.icon:
                self.icon.update_menu()
            self.stop_services()
            time.sleep(1.0)
            ready = self.start_services(open_browser=False)
            if self.icon:
                self.icon.update_menu()
                if ready:
                    self.icon.notify("LINE Bot、路由器與決策台已重新啟動。", "瘋狗流運彩")
                else:
                    self.icon.notify("服務重啟失敗，請查看 data\\tray_manager.log。", "瘋狗流運彩")
        except Exception as exc:
            logger.exception("Service restart failed: %s", exc)
            self._status_text = f"⚠️ 服務重啟失敗：{exc}"
            if self.icon:
                self.icon.update_menu()
                self.icon.notify(str(exc), "服務重啟失敗")
        finally:
            self._restart_lock.release()

    def open_web_browser(self) -> None:
        """Open local Streamlit web UI in default browser."""
        webbrowser.open("http://localhost:8501")

    def copy_public_url(self) -> None:
        """Copy the active public HTTPS URL to the clipboard."""
        info = get_runtime_info()
        url = info.get("streamlit_url")
        if url and copy_to_clipboard(url):
            if self.icon:
                self.icon.notify(f"已複製公網網址：\n{url}\n可在手機瀏覽器開啟。", "瘋狗流運彩")
        elif self.icon:
            self.icon.notify("目前沒有可用的公網網址，請確認服務與 ngrok 通道已啟動。", "瘋狗流運彩")

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
        while self._monitor_enabled:
            time.sleep(4.0)
            if not self._monitor_enabled or not self.is_running:
                continue
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
        self._monitor_enabled = False
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
            MenuItem("🌐 開啟決策台 (電腦瀏覽器)", lambda: self.open_web_browser()),
            MenuItem("📱 複製手機公網網址 (HTTPS)", lambda: self.copy_public_url()),
            MenuItem("💬 複製 LINE Webhook 網址", lambda: self.copy_webhook_url()),
            Menu.SEPARATOR,
            MenuItem("🔄 重新啟動服務", lambda: threading.Thread(target=self.restart_services, daemon=True).start()),
            MenuItem("❌ 停止並退出服務 (Quit)", self.on_quit),
        )

    def _on_icon_ready(self, icon: Icon) -> None:
        """Called by pystray after native Windows HWND message loop starts."""
        icon.visible = True
        logger.info("Pystray message loop is ready and icon is set to VISIBLE.")
        try:
            time.sleep(0.5)
            if self.is_running:
                message = "瘋狗流服務已在系統匣啟動！\n右鍵點擊圖示可重啟服務或開啟決策台。"
                title = "台灣運彩 瘋狗流"
            else:
                message = "服務沒有正常啟動。右鍵選「重新啟動服務」，或查看 data\\tray_manager.log。"
                title = "瘋狗流服務啟動異常"
            icon.notify(message, title)
        except Exception as exc:
            logger.warning("Notification error: %s", exc)

    def run(self) -> int:
        """Main entry point."""
        logger.info("Starting AppTrayManager...")
        if not self.acquire_single_instance():
            logger.info("Single instance lock held; directly opening web browser for user.")
            try:
                webbrowser.open("http://localhost:8501")
            except Exception as exc:
                logger.warning("Failed to open browser on duplicate launch: %s", exc)
            return 0

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

        logger.info("Running pystray icon loop...")
        try:
            self.icon.run(setup=self._on_icon_ready)
        except Exception as exc:
            logger.error("pystray run crashed: %s\n%s", exc, traceback.format_exc())
            show_native_popup(f"系統匣圖示啟動失敗：{exc}", "瘋狗流錯誤", is_error=True)
            self.stop_services()
            return 1

        logger.info("pystray icon loop exited cleanly.")
        return 0


if __name__ == "__main__":
    try:
        app = AppTrayManager()
        sys.exit(app.run())
    except Exception as exc:
        logger.error("Top-level exception: %s\n%s", exc, traceback.format_exc())
        show_native_popup(f"服務啟動異常：{exc}", "瘋狗流錯誤", is_error=True)
        sys.exit(1)
