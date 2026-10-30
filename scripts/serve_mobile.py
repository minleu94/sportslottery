#!/usr/bin/env python3
"""Mobile URL helper for the unified 台灣運彩瘋狗流 service.

Auto-detects local LAN and Tailscale IPs, renders terminal QR codes for iPhone scanning,
The tray manager owns the single FastAPI process and public tunnel. This
compatibility command must never start a second server on the same port.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def detect_network_ips() -> tuple[str, str | None]:
    """Detect LAN IPv4 address and Tailscale IPv4 address.
    
    Returns:
        tuple of (lan_ip, tailscale_ip or None)
    """
    lan_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            lan_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            lan_ip = "127.0.0.1"

    tailscale_ip = None
    # 1. Try tailscale CLI
    try:
        out = subprocess.check_output(["tailscale", "ip", "-4"], text=True, stderr=subprocess.DEVNULL).strip()
        if re.match(r"^100\.\d+\.\d+\.\d+$", out):
            tailscale_ip = out
    except Exception:
        pass

    # 2. Try ipconfig / ifconfig if tailscale CLI is not in PATH
    if not tailscale_ip:
        try:
            if sys.platform == "win32":
                out = subprocess.check_output(["ipconfig"], text=True, stderr=subprocess.DEVNULL)
            else:
                out = subprocess.check_output(["ifconfig"], text=True, stderr=subprocess.DEVNULL)
            # Tailscale uses 100.64.0.0/10 CGNAT space
            matches = re.findall(r"100\.(?:6[4-9]|[7-9]\d|1[0-1]\d|12[0-7])\.\d+\.\d+", out)
            if matches:
                tailscale_ip = matches[0]
        except Exception:
            pass

    return lan_ip, tailscale_ip


def render_terminal_qr(url: str) -> None:
    """Render QR Code in terminal using qrcode library with fallback."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception as exc:
        print(f"   [QR 碼產生略過: {exc}]")


def print_mobile_banner(lan_ip: str, tailscale_ip: str | None, port: int = 8000, qr_target: str = "auto") -> str:
    """Print welcoming console banner with URLs and QR code.
    
    Returns the primary mobile target URL.
    """
    lan_url = f"http://{lan_ip}:{port}"
    ts_url = f"http://{tailscale_ip}:{port}" if tailscale_ip else None
    local_url = f"http://localhost:{port}"

    if qr_target == "tailscale" and ts_url:
        primary_url = ts_url
        qr_label = "Tailscale 遠端連線網址 (出門在外 4G/5G 可連)"
    elif qr_target == "local" or not ts_url:
        primary_url = lan_url
        qr_label = "家用 Wi-Fi 區域網路網址 (手機與電腦需連同一個 Wi-Fi)"
    else:
        # Auto: default to local LAN if both available, but show both
        primary_url = lan_url
        qr_label = "家用 Wi-Fi 區域網路網址 (出門可用下方 Tailscale)"

    line_sep = "=" * 74
    print("\n" + line_sep)
    print(" 🐕 台灣運彩「瘋狗流」高倍串關決策台 — 行動端極致體驗 (iPhone Mobile Hub)")
    print(line_sep)
    print("\n 📶 連線位址 (Direct Access URLs):")
    print(f"   • 家用 Wi-Fi 內網:     {lan_url}")
    if ts_url:
        print(f"   • Tailscale 全球遠端: {ts_url}")
    print(f"   • 本機電腦瀏覽器:     {local_url}")

    print(f"\n 📷 請用 iPhone 相機直接掃描下方 QR Code ({qr_label})：\n")
    render_terminal_qr(primary_url)

    print("\n 📲 iPhone 快速加入主畫面步驟（一鍵變身獨立 App）：")
    print("   1. 用 iPhone 相機掃描上方 QR Code，在 Safari 開啟決策台")
    print("   2. 點擊 Safari 底部工具列的「分享」按鈕（帶向上箭頭的方塊圖示）")
    print("   3. 往下滑動點選「加入主畫面」(Add to Home Screen)")
    print("   4. 點選右上角「新增」—— 手機桌面即出現專屬『瘋狗流』App 圖示！")
    print("   5. 點開即享 iPhone 全螢幕獨立 App 體驗（無 Safari 網址列干擾，直覺觸控）🚀")
    print(line_sep + "\n")

    return primary_url


def main() -> int:
    parser = argparse.ArgumentParser(description="瘋狗流運彩 iPhone / 行動端啟動服務器")
    parser.add_argument("--port", type=int, default=8000, help="FastAPI 監聽埠號 (預設: 8000)")
    parser.add_argument("--qr-target", choices=["auto", "local", "tailscale"], default="auto", help="QR Code 目標網路")
    parser.add_argument("--dry-run", action="store_true", help="僅印出網路資訊與 QR Code，不啟動服務")
    args = parser.parse_args()
    if not args.dry_run and args.port != 8000:
        parser.error("手機、桌面與 LINE 共用 Port 8000；請勿另外指定服務埠。")

    lan_ip, tailscale_ip = detect_network_ips()
    primary_url = print_mobile_banner(lan_ip, tailscale_ip, port=args.port, qr_target=args.qr_target)

    if args.dry_run:
        return 0

    print("\n📱 行動端、LINE Bot 與桌面網頁共用同一個服務與公開網址。")
    print("   即將啟動系統匣服務管理器，請從系統匣複製 HTTPS 手機網址。\n")
    from scripts.tray_manager import AppTrayManager
    return AppTrayManager().run()


if __name__ == "__main__":
    sys.exit(main())
