#!/usr/bin/env python3
"""Windows System Tray Manager for 台灣運彩瘋狗流決策台 (v2.3.0 Dev).

Coordinates single-port modern services without any visible console windows:
1. Modern FastAPI Backend + React SPA (http://localhost:8000)
2. Single Cloudflare Secure HTTPS Tunnel (Port 8000 -> Web + LINE Webhook)
3. LINE Messaging API Webhook Auto-Registration
4. Windows System Tray Resident Icon with 1-click browser launch and URL copying
"""

from __future__ import annotations

import json
import logging
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

import requests
import yaml
from PIL import Image
import pystray
from pystray import Icon, Menu, MenuItem


def get_project_root() -> Path:
    """Find the canonical project directory."""
    configured = os.environ.get("SPORTSLOTTERY_WORKSPACE")
    if configured and (Path(configured) / "server" / "api.py").is_file():
        return Path(configured).expanduser().resolve()
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "server" / "api.py").exists():
            return exe_dir
    cwd = Path.cwd().resolve()
    if (cwd / "server" / "api.py").exists():
        return cwd
    file_dir = Path(__file__).resolve().parent.parent
    if (file_dir / "server" / "api.py").exists():
        return file_dir
    return Path(r"C:\Projects\PythonProjects\sportslottery")


ROOT_DIR = get_project_root()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.app_meta import APP_BUILD
from core.tunnel_runtime import load_active_runtime

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONFIG_FILE = ROOT_DIR / "config" / "line_notifier.yaml"
NGROK_CONFIG_FILE = ROOT_DIR / "config" / "ngrok_config.yaml"
STATUS_FILE = ROOT_DIR / "data" / "line_bot_runtime.json"
ICON_PATH = ROOT_DIR / "app_icon.ico"
TRAY_LOG = ROOT_DIR / "data" / "tray_runtime.log"
LOCK_PORT = 28501  # Socket port used to ensure single instance
PORT = 8000
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

CLOUDFLARED_PATHS = [
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
    "cloudflared",
]


def is_port_in_use(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def load_ngrok_config() -> Dict[str, str]:
    """Read domain and authtoken from config/ngrok_config.yaml if present."""
    if NGROK_CONFIG_FILE.exists():
        try:
            with open(NGROK_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                return {k: str(v).strip() for k, v in data.items() if v is not None}
        except Exception:
            pass
    return {}


def find_ngrok() -> str:
    """Find installed ngrok executable."""
    which = shutil.which("ngrok")
    if which:
        return which
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\ngrok.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\ngrok\ngrok.exe"),
        r"C:\Program Files\ngrok\ngrok.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return ""


def log_tray(msg: str):
    try:
        TRAY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(TRAY_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%X')}] {msg}\n")
    except Exception:
        pass


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
        if c and Path(c).is_file() and not Path(c).name.lower().startswith("sportslottery"):
            return str(Path(c).resolve())
    return rf"C:\Program Files\Python311\{name}"


def find_cloudflared() -> str:
    """Find installed cloudflared executable."""
    for p in CLOUDFLARED_PATHS:
        if os.path.exists(p):
            return p
    which = shutil.which("cloudflared")
    if which:
        return which
    return ""


def load_line_token() -> str:
    """Read channel_access_token from config file."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return str(cfg.get("channel_access_token") or "").strip()
        except Exception:
            pass
    return ""


def register_line_webhook(webhook_url: str, token: str) -> bool:
    """Automatically register webhook endpoint URL directly via LINE Messaging API."""
    if not token:
        return False
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = "https://api.line.me/v2/bot/channel/webhook/endpoint"
    try:
        resp = requests.put(url, headers=headers, json={"endpoint": webhook_url}, timeout=10.0)
        return resp.status_code == 200
    except Exception as exc:
        log_tray(f"Error registering LINE webhook: {exc}")
        return False


def copy_to_clipboard(text: str) -> bool:
    """Copy text string to Windows clipboard using clip.exe."""
    try:
        subprocess.run(["clip.exe"], input=text.encode("utf-16"), check=True, creationflags=CREATE_NO_WINDOW)
        return True
    except Exception:
        return False


def get_runtime_info() -> Dict[str, Any]:
    """Read line_bot_runtime.json for active tunnel URLs."""
    return load_active_runtime(STATUS_FILE)


def kill_proc_tree(proc: Optional[subprocess.Popen]) -> None:
    """Forcefully kill process and all its children via taskkill on Windows."""
    if not proc or proc.poll() is not None:
        return
    pid = proc.pid
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, creationflags=CREATE_NO_WINDOW)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class AppTrayManager:
    """Coordinates FastAPI backend, Cloudflare single tunnel, and System Tray."""

    def __init__(self):
        self.proc_api: Optional[subprocess.Popen] = None
        self.proc_tunnel: Optional[subprocess.Popen] = None
        self.icon: Optional[Icon] = None
        self._lock_sock: Optional[socket.socket] = None
        self.is_running: bool = False
        self._status_text: str = "⏳ 服務啟動中..."
        self._tunnel_url: Optional[str] = None
        self._webhook_url: Optional[str] = None

    def acquire_single_instance(self) -> bool:
        """Prevent multiple instances of tray manager using a loopback socket."""
        try:
            self._lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._lock_sock.bind(("127.0.0.1", LOCK_PORT))
            self._lock_sock.listen(1)
            log_tray(f"Acquired single instance lock on port {LOCK_PORT}")
            return True
        except Exception as exc:
            log_tray(f"Failed to acquire lock: {exc}")
            return False

    def load_tray_icon(self) -> Image.Image:
        """Load app icon or create dynamic fallback."""
        if ICON_PATH.exists():
            try:
                return Image.open(ICON_PATH)
            except Exception as exc:
                log_tray(f"Error loading icon: {exc}")
        from PIL import ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill=(22, 163, 74), outline=(34, 197, 94), width=3)
        draw.polygon([(20, 42), (32, 18), (44, 42)], fill=(255, 255, 255))
        return img

    def _open_browser_when_ready(self, timeout: float = 35.0) -> None:
        """Poll FastAPI health check and automatically open browser."""
        url = f"http://localhost:{PORT}"
        health_url = f"{url}/api/health"
        start_t = time.time()
        while time.time() - start_t < timeout and self.is_running:
            try:
                req = urllib.request.Request(health_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        time.sleep(0.3)
                        log_tray(f"FastAPI healthy, opening browser: {url}")
                        webbrowser.open(url)
                        return
            except Exception:
                time.sleep(0.4)

    def _wait_for_current_api(self, timeout: float = 35.0) -> bool:
        """Require the newly launched backend to answer, not a stale port owner."""
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{PORT}/api/health"
        while time.monotonic() < deadline:
            if self.proc_api is None or self.proc_api.poll() is not None:
                return False
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "sportslottery-tray/1.0"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                if resp.status == 200 and payload.get("app_build") == APP_BUILD:
                    log_tray(f"Current API build verified: {APP_BUILD}")
                    return True
            except Exception:
                pass
            time.sleep(0.4)
        log_tray(f"API did not become ready with expected build {APP_BUILD}; tunnel will not start.")
        return False

    def _start_tunnel(self, cloudflared_exe: str) -> None:
        """Launch public tunnel (ngrok static domain prioritized, cloudflared as fallback) and auto-register LINE webhook."""
        ngrok_cfg = load_ngrok_config()
        domain = ngrok_cfg.get("domain", "").strip()
        authtoken = ngrok_cfg.get("authtoken", "").strip()
        ngrok_exe = find_ngrok()

        # 1. Prioritize ngrok static domain if configured
        if ngrok_exe and domain:
            # Terminate any stray previous ngrok instance to prevent ERR_NGROK_334
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/IM", "ngrok.exe"], capture_output=True, creationflags=CREATE_NO_WINDOW)
            time.sleep(0.5)

            clean_domain = domain.replace("https://", "").replace("http://", "").rstrip("/")
            if authtoken and not authtoken.startswith("填寫"):
                try:
                    subprocess.run([ngrok_exe, "config", "add-authtoken", authtoken], capture_output=True, check=True)
                except Exception as exc:
                    log_tray(f"Error configuring ngrok authtoken: {exc}")

            ngrok_cmd = [ngrok_exe, "http", f"http://127.0.0.1:{PORT}", f"--url=https://{clean_domain}"]
            try:
                log_file = open(ROOT_DIR / "data" / "ngrok.log", "a", encoding="utf-8")
                self.proc_tunnel = subprocess.Popen(
                    ngrok_cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                )
                time.sleep(1.5)
                if self.proc_tunnel.poll() is None:
                    self._tunnel_url = f"https://{clean_domain}"
                    self._webhook_url = f"{self._tunnel_url}/callback"
                    log_tray(f"ngrok static domain tunnel live: {self._tunnel_url} (PID: {self.proc_tunnel.pid})")

                    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump({
                            "pid": os.getpid(),
                            "started_at": time.time(),
                            "app_build": APP_BUILD,
                            "api_pid": self.proc_api.pid if self.proc_api else None,
                            "tunnel_url": self._tunnel_url,
                            "webhook_url": self._webhook_url,
                            "streamlit_url": self._tunnel_url,
                            "port": PORT,
                            "provider": "ngrok",
                        }, f, indent=2)

                    token = load_line_token()
                    reg_ok = register_line_webhook(self._webhook_url, token)
                    log_tray(f"LINE Webhook auto-registration result: {reg_ok}")
                    return
                else:
                    log_tray(f"ngrok exited prematurely (code {self.proc_tunnel.returncode}), falling back to cloudflared...")
            except Exception as exc:
                log_tray(f"ngrok launch failed: {exc}, falling back to cloudflared...")

        # 2. Fallback to Cloudflare quick tunnel
        if not cloudflared_exe:
            log_tray("No tunnel executable (ngrok or cloudflared) found, skipping public tunnel.")
            return

        cmd = [cloudflared_exe, "tunnel", "--url", f"http://127.0.0.1:{PORT}"]
        self.proc_tunnel = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        log_tray(f"Cloudflare tunnel spawned with PID: {self.proc_tunnel.pid}")

        pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        for line in iter(self.proc_tunnel.stdout.readline, ""):
            match = pattern.search(line)
            if match:
                self._tunnel_url = match.group(0)
                self._webhook_url = f"{self._tunnel_url}/callback"
                log_tray(f"Cloudflare tunnel live: {self._tunnel_url}")

                STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump({
                        "pid": os.getpid(),
                        "started_at": time.time(),
                        "app_build": APP_BUILD,
                        "api_pid": self.proc_api.pid if self.proc_api else None,
                        "tunnel_url": self._tunnel_url,
                        "webhook_url": self._webhook_url,
                        "streamlit_url": self._tunnel_url,
                        "port": PORT,
                        "provider": "cloudflare",
                    }, f, indent=2)

                token = load_line_token()
                reg_ok = register_line_webhook(self._webhook_url, token)
                log_tray(f"LINE Webhook auto-registration result: {reg_ok}")
                break

    def start_services(self) -> None:
        """Launch the verified modern backend, then expose it through one tunnel."""
        self.is_running = False
        if STATUS_FILE.exists():
            try:
                STATUS_FILE.unlink(missing_ok=True)
            except Exception as exc:
                log_tray(f"Could not clear previous runtime status: {exc}")

        python_bin = find_python_executable(gui=False)
        cloudflared_exe = find_cloudflared()

        # Check if port is already active with our current build
        if is_port_in_use(PORT):
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/health", headers={"User-Agent": "sportslottery-tray/1.0"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                if resp.status == 200 and payload.get("app_build") == APP_BUILD:
                    log_tray(f"Existing verified FastAPI found on port {PORT} (build {APP_BUILD}). Reusing active service.")
                    self.is_running = True
                    self._status_text = "🟢 新版網頁正常"
                    threading.Thread(target=self._start_tunnel, args=(cloudflared_exe,), daemon=True).start()
                    threading.Thread(target=self._open_browser_when_ready, daemon=True).start()
                    return
            except Exception:
                pass
            log_tray(f"Port {PORT} is currently in use. Launching current backend instance...")

        log_tray(f"Starting FastAPI on port {PORT} via: {python_bin}")

        # 1. Start FastAPI server with structured output log
        server_log_path = ROOT_DIR / "data" / "server.log"
        server_log_path.parent.mkdir(parents=True, exist_ok=True)
        server_log_file = open(server_log_path, "a", encoding="utf-8")

        api_cmd = [
            python_bin,
            "-m",
            "uvicorn",
            "server.api:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(PORT),
            "--log-level",
            "warning",
        ]
        self.proc_api = subprocess.Popen(
            api_cmd,
            cwd=str(ROOT_DIR),
            creationflags=CREATE_NO_WINDOW,
            stdout=server_log_file,
            stderr=subprocess.STDOUT,
        )
        log_tray(f"FastAPI server started with PID: {self.proc_api.pid}")

        if not self._wait_for_current_api():
            kill_proc_tree(self.proc_api)
            self.proc_api = None
            self._status_text = "🔴 新版 API 未就緒；未啟動公開通道"
            return

        self.is_running = True
        self._status_text = "🟡 新版網頁正常 (公網通道連線中)"

        # 2. Start the tunnel only after verifying this process owns the expected API.
        threading.Thread(target=self._start_tunnel, args=(cloudflared_exe,), daemon=True).start()

        # 3. Background thread to auto-open browser when ready
        threading.Thread(target=self._open_browser_when_ready, daemon=True).start()

    def stop_services(self) -> None:
        """Terminate all background processes and tunnels."""
        log_tray("Stopping services...")
        self.is_running = False
        self._status_text = "🔴 服務已停止"
        kill_proc_tree(self.proc_api)
        kill_proc_tree(self.proc_tunnel)
        self.proc_api = None
        self.proc_tunnel = None
        self._tunnel_url = None
        self._webhook_url = None
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/IM", "ngrok.exe"], capture_output=True, creationflags=CREATE_NO_WINDOW)
            subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True, creationflags=CREATE_NO_WINDOW)
        if STATUS_FILE.exists():
            try:
                STATUS_FILE.unlink(missing_ok=True)
            except Exception:
                pass
        log_tray("Services stopped cleanly.")

    def restart_services(self) -> None:
        """Restart services."""
        self._status_text = "🔄 服務重啟中..."
        if self.icon:
            self.icon.update_menu()
        self.stop_services()
        time.sleep(1.0)
        self.start_services()
        if self.icon:
            self.icon.update_menu()
            self.icon.notify("決策台與對外通道已成功重新啟動！", "瘋狗流 v2.3.0 Dev")

    def get_lan_url(self) -> str:
        """Detect local machine LAN IP."""
        lan_ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
        return f"http://{lan_ip}:{PORT}"

    def open_web_browser(self) -> None:
        """Open local FastAPI modern React UI in default browser."""
        webbrowser.open(f"http://localhost:{PORT}")

    def open_mobile_browser(self) -> None:
        """Open public HTTPS tunnel URL or LAN URL in browser."""
        info = get_runtime_info()
        url = info.get("tunnel_url") or self.get_lan_url()
        webbrowser.open(url)

    def copy_public_url(self) -> None:
        """Copy public Cloudflare or ngrok HTTPS URL to clipboard."""
        info = get_runtime_info()
        url = info.get("tunnel_url")

        if url:
            copy_to_clipboard(url)
            if self.icon:
                self.icon.notify(f"已複製手機公網網址至剪貼簿：\n{url}\n（出門在外 4G/5G 手機瀏覽器可直接開啟）", "瘋狗流 v2.3.0 Dev")
        else:
            if self.icon:
                self.icon.notify("公網安全通道連線中，請稍候 3 秒後再試。", "瘋狗流 v2.3.0 Dev")

    def copy_lan_url(self) -> None:
        """Copy local network Wi-Fi URL to clipboard."""
        url = self.get_lan_url()
        copy_to_clipboard(url)
        if self.icon:
            self.icon.notify(f"已複製區網網址至剪貼簿：\n{url}\n（手機連線同一 Wi-Fi 即可開啟）", "瘋狗流 v2.3.0 Dev")

    def copy_webhook_url(self) -> None:
        """Copy LINE Webhook URL to clipboard."""
        info = get_runtime_info()
        url = info.get("webhook_url")

        if url:
            copy_to_clipboard(url)
            if self.icon:
                self.icon.notify(f"已複製 LINE Webhook 網址：\n{url}", "瘋狗流 v2.3.0 Dev")
        else:
            if self.icon:
                self.icon.notify("Webhook 尚未配發，請稍候再試。", "瘋狗流 v2.3.0 Dev")

    def rebind_line_webhook(self) -> None:
        """Re-register LINE webhook endpoint."""
        info = get_runtime_info()
        webhook_url = info.get("webhook_url")

        token = load_line_token()
        if not webhook_url:
            if self.icon:
                self.icon.notify("尚未建立公網通道，請稍候重試。", "瘋狗流 v2.3.0 Dev")
            return
        if not token:
            if self.icon:
                self.icon.notify("未在 config/line_notifier.yaml 設定 channel_access_token。", "瘋狗流 v2.3.0 Dev")
            return
        ok = register_line_webhook(webhook_url, token)
        log_tray(f"Manual rebind LINE Webhook: {webhook_url} -> {ok}")
        if self.icon:
            if ok:
                self.icon.notify(f"✅ LINE Webhook 已成功重新綁定！\n{webhook_url}", "瘋狗流 v2.3.0 Dev")
            else:
                self.icon.notify(f"❌ 綁定失敗，請確認 Access Token 或網路狀態。", "瘋狗流 v2.3.0 Dev")

    def monitor_loop(self) -> None:
        """Background thread monitoring process health."""
        while self.is_running:
            time.sleep(3.0)
            a_alive = self.proc_api and self.proc_api.poll() is None
            t_alive = self.proc_tunnel and self.proc_tunnel.poll() is None
            if a_alive and t_alive:
                self._status_text = "🟢 服務正常運行中 (LINE + Web + Mobile)"
            elif a_alive:
                self._status_text = "🟡 網頁正常 (公網通道連線中)"
            else:
                self._status_text = "🔴 服務異常中斷"

    def on_quit(self, icon: Icon, item: Any) -> None:
        """Handle Quit menu item."""
        log_tray("Quit menu clicked by user.")
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
            MenuItem("🌐 開啟決策台 (電腦端瀏覽器)", lambda: self.open_web_browser(), default=True),
            MenuItem("📱 開啟手機端網頁 (預設瀏覽器)", lambda: self.open_mobile_browser()),
            MenuItem("📋 複製手機公網網址 (HTTPS)", lambda: self.copy_public_url()),
            MenuItem("📶 複製手機區網網址 (Wi-Fi)", lambda: self.copy_lan_url()),
            MenuItem("💬 複製 LINE Webhook 網址", lambda: self.copy_webhook_url()),
            MenuItem("🤖 重新連動 LINE Webhook", lambda: threading.Thread(target=self.rebind_line_webhook, daemon=True).start()),
            Menu.SEPARATOR,
            MenuItem("🔄 重新啟動服務 (Web + LINE + Tunnel)", lambda: threading.Thread(target=self.restart_services, daemon=True).start()),
            MenuItem("❌ 停止並退出服務 (Quit)", self.on_quit),
        )

    def run(self) -> int:
        """Main entry point."""
        log_tray("AppTrayManager.run() starting")
        if not self.acquire_single_instance():
            log_tray("Single instance acquire failed, exiting run()")
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
            title="台灣運彩 瘋狗流 (v2.3.0 Dev 運行中)",
            menu=self.build_menu(),
        )

        try:
            time.sleep(1.0)
            self.icon.notify(
                "瘋狗流 v2.3.0 Dev 3-in-1 服務已啟動！\n已在右下角系統匣常駐，並已開啟決策台。\n右鍵點擊圖示可查看狀態或複製手機網址。",
                "台灣運彩 瘋狗流 (v2.3.0 Dev)",
            )
        except Exception as exc:
            log_tray(f"Notify error: {exc}")

        log_tray("Starting self.icon.run() event loop...")
        self.icon.run()
        log_tray("self.icon.run() exited cleanly.")
        return 0


if __name__ == "__main__":
    try:
        app = AppTrayManager()
        sys.exit(app.run())
    except Exception as exc:
        import traceback
        log_tray(f"FATAL UNCAUGHT ERROR: {exc}\n{traceback.format_exc()}")
        raise
