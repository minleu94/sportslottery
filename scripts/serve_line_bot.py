#!/usr/bin/env python3
"""LINE Bot All-in-One Runner: FastAPI Webhook Server + Cloudflare Tunnel.

Starts the local webhook server on port 8001, establishes a secure public
HTTPS tunnel using Cloudflare Tunnel (`cloudflared`), and displays the exact
Webhook URL to configure in the LINE Developers Console.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional
import requests
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CONFIG_FILE = ROOT_DIR / "config" / "line_notifier.yaml"
NGROK_CONFIG_FILE = ROOT_DIR / "config" / "ngrok_config.yaml"
STATUS_FILE = ROOT_DIR / "data" / "line_bot_runtime.json"


def wait_for_local_port(port: int, timeout: float = 10.0) -> bool:
    """Return once a local service accepts TCP connections on the requested port."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.2)
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


def launch_ngrok_tunnel(domain: str, authtoken: str = "", port: int = 8501) -> tuple[Optional[subprocess.Popen], Optional[str]]:
    """Launch official ngrok tunnel with user's permanent static dev domain."""
    clean_domain = domain.replace("https://", "").replace("http://", "").rstrip("/")
    if authtoken and not authtoken.startswith("填寫"):
        try:
            subprocess.run(["ngrok", "config", "add-authtoken", authtoken], capture_output=True, check=True)
        except Exception as exc:
            print(f"  ⚠️ 設定 ngrok authtoken 提示: {exc}")

    ngrok_cmd = ["ngrok", "http", f"http://127.0.0.1:{port}", f"--url=https://{clean_domain}"]
    create_flag = 0x08000000 if sys.platform == "win32" else 0
    ngrok_log = open(ROOT_DIR / "data" / "ngrok.log", "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            ngrok_cmd,
            stdout=ngrok_log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=create_flag,
        )
        time.sleep(1.5)
        if proc.poll() is not None:
            print("  ⚠️ ngrok 啟動後退出，請檢查 data/ngrok.log")
            return None, None

        url = f"https://{clean_domain}"
        return proc, url
    except Exception as exc:
        print(f"  ⚠️ 啟動 ngrok 通道失敗: {exc}")
        return None, None

CLOUDFLARED_PATHS = [
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
    "cloudflared",
]


def load_token() -> str:
    """Read channel_access_token from config file."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return str(cfg.get("channel_access_token") or "").strip()
        except Exception:
            pass
    return ""


def register_line_webhook(webhook_url: str, token: str) -> Dict[str, Any]:
    """Automatically register webhook endpoint URL directly via LINE Messaging API."""
    if not token:
        return {"success": False, "reason": "NO_TOKEN"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = "https://api.line.me/v2/bot/channel/webhook/endpoint"
    try:
        resp = requests.put(url, headers=headers, json={"endpoint": webhook_url}, timeout=10.0)
        if resp.status_code == 200:
            # Test webhook connectivity
            test_resp = requests.post(
                "https://api.line.me/v2/bot/channel/webhook/test",
                headers=headers,
                json={"endpoint": webhook_url},
                timeout=10.0,
            )
            return {
                "success": True,
                "status_code": 200,
                "test_status": test_resp.status_code,
                "test_payload": test_resp.json() if test_resp.status_code == 200 else test_resp.text,
            }
        return {"success": False, "status_code": resp.status_code, "error": resp.text}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def find_cloudflared() -> str:
    """Find installed cloudflared executable."""
    for p in CLOUDFLARED_PATHS:
        if os.path.exists(p):
            return p
    import shutil
    which = shutil.which("cloudflared")
    if which:
        return which
    return ""


def run_fastapi_server(port: int = 8001):
    """Run uvicorn server in a separate thread."""
    import uvicorn
    from scripts.line_webhook_server import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def launch_cloudflared_tunnel(
    cloudflared_exe: str,
    port: int,
    timeout: float = 30.0,
) -> tuple[Optional[subprocess.Popen], Optional[str]]:
    """Start cloudflared tunnel for the specified local port and return (process, public_https_url)."""
    cmd = [cloudflared_exe, "tunnel", "--url", f"http://127.0.0.1:{port}"]
    create_flag = 0x08000000 if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
        creationflags=create_flag,
    )
    pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    tunnel_url = None

    def _reader():
        nonlocal tunnel_url
        for line in iter(proc.stdout.readline, ""):
            match = pattern.search(line)
            if match and not tunnel_url:
                tunnel_url = match.group(0)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    start_t = time.time()
    while time.time() - start_t < timeout:
        if tunnel_url:
            break
        time.sleep(0.3)

    return proc, tunnel_url


def main():
    port = 8000
    st_port = 8000
    router_port = 8000
    cloudflared_exe = find_cloudflared()
    token = load_token()

    print("======================================================================")
    print("  🐕 台灣運彩 瘋狗流 LINE Bot 互動伺服器啟動中...")
    print("======================================================================")

    # 1. Start FastAPI server in background thread
    server_thread = threading.Thread(target=run_fastapi_server, args=(port,), daemon=True)
    server_thread.start()
    if not wait_for_local_port(port):
        raise RuntimeError(f"LINE webhook did not start listening on 127.0.0.1:{port}")
    print(f"  ✅ Webhook 本地服務已啟動: http://127.0.0.1:{port}")

    from scripts.public_router import run_public_router
    router_thread = threading.Thread(target=run_public_router, args=(router_port,), daemon=True)
    router_thread.start()
    if not wait_for_local_port(router_port):
        raise RuntimeError(f"Shared URL router did not start listening on 127.0.0.1:{router_port}")
    print(f"  ✅ 共用網址路由器已啟動: http://127.0.0.1:{router_port}")

    # 2. Expose one local router. It sends /callback to FastAPI and all other
    # paths, including Streamlit's websocket, to Streamlit.
    ngrok_cfg = load_ngrok_config()
    ngrok_domain = ngrok_cfg.get("domain", "")
    ngrok_token = ngrok_cfg.get("authtoken", "")
    ngrok_enabled = ngrok_cfg.get("enabled", "true").lower() not in {"false", "0", "no", "off"}

    st_proc = None
    streamlit_url = None

    if ngrok_enabled and ngrok_domain and not ngrok_domain.startswith("填寫"):
        print(f"  🚀 正在連線 ngrok 永久固定專屬網址: {ngrok_domain}...")
        st_proc, streamlit_url = launch_ngrok_tunnel(ngrok_domain, authtoken=ngrok_token, port=router_port)
        if streamlit_url:
            print(f"  ✅ ngrok 永久固定網址已就緒: {streamlit_url}")

    if not streamlit_url:
        if cloudflared_exe:
            print("  ⏳ 正在建立 Cloudflare 臨時共用通道 (手機網頁與 LINE Bot)...")
            st_proc, streamlit_url = launch_cloudflared_tunnel(cloudflared_exe, port=router_port)
        else:
            print("  ⚠️ 找不到可用的公開通道：請設定 ngrok 固定網址或安裝 cloudflared")

    tunnel_url = streamlit_url
    webhook_url = f"{streamlit_url.rstrip('/')}/callback" if streamlit_url else None

    # Record runtime status to disk
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "pid": os.getpid(),
            "started_at": time.time(),
            "tunnel_url": tunnel_url,
            "webhook_url": webhook_url,
            "streamlit_url": streamlit_url,
            "port": port,
            "streamlit_port": st_port,
            "router_port": router_port,
        }, f, indent=2)

    if webhook_url:
        # 3. Automatically update LINE webhook endpoint via API!
        reg_res = register_line_webhook(webhook_url, token)

        print("======================================================================")
        print("  🎉 共用公網通道已啟動。")
        print("======================================================================")
        print(f"  🌐 LINE Webhook 公開網址：{webhook_url}")
        if streamlit_url:
            print(f"  📱 決策台網頁 (公網 HTTPS 網址)：{streamlit_url}")
            print("     (任何朋友、出門在外 4G/5G 手機瀏覽器皆可直接開啟)")

        if reg_res.get("success"):
            print("  ⚡ 【自動同步成功】已透過 LINE API 自動將此 Webhook 註冊至您的 LINE Channel！")
            test_info = reg_res.get("test_payload") or {}
            print(f"  🔍 連通性驗證結果：{test_info.get('reason', 'OK')} (HTTP {test_info.get('statusCode', 200)})")
        else:
            status = reg_res.get("status_code")
            status_text = f"HTTP {status}: " if status else ""
            print(f"  ⚠️ 自動註冊 Webhook 略過或失敗：{status_text}{reg_res.get('error', reg_res.get('reason'))}")

        print("----------------------------------------------------------------------")
        print("  📌 最後一步：請至 [LINE 官方帳號管理後台] 關閉罐頭訊息（僅需確認一次）：")
        print("     網址：https://manager.line.biz/")
        print("     路徑：右上角「設定」➔「回應設定」：")
        print("     • 回應模式 ➔ 選擇「Bot (機器人)」")
        print("     • 自動回應訊息 ➔ 點擊「停用 (關閉)」  <-- 徹底消除預設罐頭回覆！")
        print("     • Webhook ➔ 點擊「啟用」")
        print("======================================================================")
        print("  💬 現在您可以直接在手機 LINE 上測試發送：")
        print("     • 「20倍」➔ 立即獲得最佳串關推薦盤口與 1/4 凱利注碼")
        print("     • 「功能表」➔ 展開完整功能清單與下方快捷選單")
        print("     • 「查戰績」➔ 查詢每週 NT$200 預算與儲備池")
        print("     • 「今日開盤」➔ 查詢今日賽事雷達開盤概況")
        print("     • 「個人設定」➔ 查詢目前玩家、取得手機公網網址、管理帳號")
        print("======================================================================")
        print("  (背景服務正常運行中，按 Ctrl+C 可結束)")
    else:
        print("  ❌ 沒有取得可用的公網網址；LINE webhook 與手機公網頁面都無法連線。")

    try:
        while True:
            time.sleep(2.0)
    except KeyboardInterrupt:
        print("\n  🛑 正在關閉 LINE Bot 服務...")
        if st_proc:
            st_proc.terminate()
        if STATUS_FILE.exists():
            STATUS_FILE.unlink(missing_ok=True)
        print("  ✅ 服務已結束。")


if __name__ == "__main__":
    main()
