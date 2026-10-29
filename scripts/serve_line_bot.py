#!/usr/bin/env python3
"""LINE Bot All-in-One Runner: FastAPI Webhook Server + Cloudflare Tunnel.

Starts the local webhook server on port 8000, establishes a secure public
HTTPS tunnel using Cloudflare Tunnel (`cloudflared`), and displays the exact
Webhook URL to configure in the LINE Developers Console.
"""

from __future__ import annotations

import json
import os
import re
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
STATUS_FILE = ROOT_DIR / "data" / "line_bot_runtime.json"

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


def run_fastapi_server(port: int = 8000):
    """Run uvicorn server in a separate thread."""
    import uvicorn
    from scripts.line_webhook_server import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main():
    port = 8000
    cloudflared_exe = find_cloudflared()
    token = load_token()

    print("======================================================================")
    print("  🐕 台灣運彩 瘋狗流 LINE Bot 互動伺服器啟動中...")
    print("======================================================================")

    # 1. Start FastAPI server in background thread
    server_thread = threading.Thread(target=run_fastapi_server, args=(port,), daemon=True)
    server_thread.start()
    time.sleep(1.0)
    print(f"  ✅ Webhook 本地服務已啟動: http://127.0.0.1:{port}")

    if not cloudflared_exe:
        print("  ⚠️ 未找到 cloudflared.exe，請手動使用 ngrok 或其他工具轉發 http://127.0.0.1:8000")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  🛑 LINE Bot 服務已停止。")
        return

    # 2. Launch cloudflared tunnel
    print("  ⏳ 正在建立 Cloudflare 臨時公開安全通道 (免費免登入)...")
    cmd = [cloudflared_exe, "tunnel", "--url", f"http://127.0.0.1:{port}"]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )

    tunnel_url = None
    pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

    for line in iter(proc.stdout.readline, ""):
        match = pattern.search(line)
        if match:
            tunnel_url = match.group(0)
            break

    if tunnel_url:
        webhook_url = f"{tunnel_url}/callback"

        # Record runtime status to disk
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "pid": os.getpid(),
                "started_at": time.time(),
                "tunnel_url": tunnel_url,
                "webhook_url": webhook_url,
                "port": port,
            }, f, indent=2)

        # 3. Automatically update LINE webhook endpoint via API!
        reg_res = register_line_webhook(webhook_url, token)

        print("======================================================================")
        print("  🎉 LINE Bot 對外通道已成功連線！")
        print("======================================================================")
        print(f"  🌐 您的公開 Webhook URL：{webhook_url}")

        if reg_res.get("success"):
            print("  ⚡ 【自動同步成功】已透過 LINE API 自動將此 Webhook 註冊至您的 LINE Channel！")
            test_info = reg_res.get("test_payload") or {}
            print(f"  🔍 連通性驗證結果：{test_info.get('reason', 'OK')} (HTTP {test_info.get('statusCode', 200)})")
        else:
            print(f"  ⚠️ 自動註冊 Webhook 略過或失敗：{reg_res.get('error', reg_res.get('reason'))}")

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
        print("     • 「對沖」➔ 查詢手頭注單是否已聽牌")
        print("======================================================================")
        print("  (背景服務正常運行中，按 Ctrl+C 可結束)")
    else:
        print("  ❌ 未能自動取得 Cloudflare Tunnel 網址，請檢查網路連線。")

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n  🛑 正在關閉 LINE Bot 服務...")
        proc.terminate()
        if STATUS_FILE.exists():
            STATUS_FILE.unlink(missing_ok=True)
        print("  ✅ 服務已結束。")


if __name__ == "__main__":
    main()
