#!/usr/bin/env python3
"""LINE Bot All-in-One Runner: FastAPI Webhook Server + Cloudflare Tunnel.

Starts the local webhook server on port 8000, establishes a secure public
HTTPS tunnel using Cloudflare Tunnel (`cloudflared`), and displays the exact
Webhook URL to configure in the LINE Developers Console.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

CLOUDFLARED_PATHS = [
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
    "cloudflared",
]


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
        print("======================================================================")
        print("  🎉 LINE Bot 對外通道已成功連線！")
        print("======================================================================")
        print(f"  🌐 您的公開 Webhook URL 為：")
        print(f"     {webhook_url}")
        print("----------------------------------------------------------------------")
        print("  📌 請依序完成 LINE 後台 2 處設定（只需設定一次）：")
        print("")
        print("  1️⃣ [LINE Official Account Manager 後台] (https://manager.line.biz/):")
        print("     點選「設定」➔「回應設定」：")
        print("     • 回應模式 ➔ 勾選「Bot (機器人)」")
        print("     • 自動回應訊息 ➔ 設定為「停用 (關閉)」  <-- 避免預設罐頭回覆！")
        print("     • Webhook ➔ 設定為「啟用」")
        print("")
        print("  2️⃣ [LINE Developers Console] (https://developers.line.biz/):")
        print("     進入您的 Channel ➔「Messaging API」頁籤：")
        print(f"     • Webhook URL ➔ 點擊 Edit，貼上：{webhook_url}")
        print("     • Use Webhook ➔ 切換為「開啟 (Enabled)」")
        print("     • 點擊「Verify」按鈕 ➔ 顯示「Success」即完成綁定！")
        print("======================================================================")
        print("  💬 現在您可以直接在手機 LINE 上測試發送：")
        print("     • 「20倍」➔ 立即獲得最佳串關推薦盤口與 1/4 凱利注碼")
        print("     • 「功能表」➔ 展開完整功能清單與下方快捷選單")
        print("     • 「查戰績」➔ 查詢每週 NT$200 預算與儲備池")
        print("     • 「今日開盤」➔ 查詢今日賽事雷達開盤概況")
        print("     • 「對沖」➔ 查詢手頭注單是否已聽牌")
        print("======================================================================")
        print("  (保持本視窗開啟即可持續接收與回覆 LINE 訊息，按 Ctrl+C 可結束)")
    else:
        print("  ❌ 未能自動取得 Cloudflare Tunnel 網址，請檢查網路連線。")

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n  🛑 正在關閉 LINE Bot 服務...")
        proc.terminate()
        print("  ✅ 服務已結束。")


if __name__ == "__main__":
    main()
