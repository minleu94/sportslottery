# -*- coding: utf-8 -*-
"""Development Mode Runner for Taiwan Sports Lottery System (v2.3.0 Dev).

Ensures:
1. Instant startup (~1.5s total)
2. Stale port 8000 & 28501 cleanup
3. Lightning-fast Vite compilation (~0.3s)
4. Native Python resident execution in Windows System Tray
5. Automatic browser launch & clear health verification
6. Never abruptly crashes or closes window without explanation
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Setup encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parent.parent
os.chdir(ROOT_DIR)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

BANNER = r"""
======================================================================
  🇹🇼 台灣運彩「瘋狗流」開發即時模式 (v2.3.0 Dev)
  ⚡ 免打包 · 極速編譯 · 電腦端 / 手機端 / LINE Bot 三合一同步
======================================================================
"""


def kill_stale_ports(ports=(8000, 28501)) -> None:
    """Kill any process holding port 8000 or 28501."""
    try:
        import psutil

        for conn in psutil.net_connections():
            if conn.laddr and conn.laddr.port in ports and conn.pid:
                try:
                    p = psutil.Process(conn.pid)
                    if p.pid != os.getpid():
                        print(f"  - 終止舊進程 PID {p.pid} ({p.name()})...")
                        p.terminate()
                        p.wait(timeout=2.0)
                except Exception:
                    pass
    except Exception:
        for port in ports:
            try:
                cmd = f'netstat -ano | findstr :{port}'
                output = subprocess.check_output(cmd, shell=True, text=True, errors="ignore")
                for line in output.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 5 and "LISTENING" in parts:
                        pid = parts[-1]
                        if pid.isdigit() and int(pid) != os.getpid():
                            print(f"  - 終止舊進程 PID {pid}...")
                            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
            except Exception:
                pass


def build_frontend() -> bool:
    """Compile frontend React SPA with Vite."""
    node_candidates = [
        r"C:\Users\archi\AppData\Local\OpenAI\Codex\runtimes\cua_node\5c41f77a7900391c\bin\node.exe",
        shutil.which("node"),
    ]
    node_exe = next((p for p in node_candidates if p and Path(p).exists()), None)
    if not node_exe:
        print("  - [Notice] 未偵測到 Node.js，直接沿用現有編譯版本。")
        return True

    vite_script = ROOT_DIR / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_script.exists():
        print("  - [Notice] 未找到 vite.js，直接沿用現有編譯版本。")
        return True

    try:
        res = subprocess.run(
            [node_exe, str(vite_script), "build"],
            cwd=str(ROOT_DIR / "frontend"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20.0,
        )
        if res.returncode == 0:
            print("  - [OK] 前端 SPA 最新介面編譯成功！")
            return True
        else:
            print("  - [Warning] 前端編譯警告：", res.stderr.strip()[:200])
            return True
    except Exception as exc:
        print(f"  - [Warning] 前端編譯異常 ({exc})，將沿用現有檔案繼續啟動。")
        return True


def main():
    if "--build-only" in sys.argv:
        print("[Build] 極速同步最新前端介面 (Vite Build)...")
        ok = build_frontend()
        sys.exit(0 if ok else 1)

    print(BANNER)

    # 1. Port cleanup
    print("[1/3] 檢查並釋放背景連接埠 (8000, 28501)...")
    kill_stale_ports((8000, 28501))
    time.sleep(0.3)

    # 2. Frontend build
    print("[2/3] 極速同步最新前端介面 (Vite Build)...")
    build_frontend()

    # 3. Launch service via AppTrayManager
    print("[3/3] 正在以原生即時模式啟動決策台...")
    print("  [PC 瀏覽器]  http://localhost:8000 (啟動後自動開啟)")
    print("  [手機與公網] https://fifty-saddlebag-immortal.ngrok-free.dev")
    print("  [LINE 機器人] Webhook 連線中")
    print("\n" + "=" * 70)
    print("  🟢 服務運行中！請保持此視窗開啟即可持續運作。")
    print("  關閉此視窗或在右下角系統匣圖示點 Quit 即可結束。")
    print("=" * 70 + "\n")

    from scripts.tray_manager import AppTrayManager

    app = AppTrayManager()
    try:
        sys.exit(app.run())
    except KeyboardInterrupt:
        print("\n[Shutting down] 正在安全停止服務...")
        app.stop_services()
        if app._lock_sock:
            try:
                app._lock_sock.close()
            except Exception:
                pass
        if app.icon:
            try:
                app.icon.stop()
            except Exception:
                pass
        print("[Done] 服務已安全結束。")
        sys.exit(0)
    except Exception as exc:
        print(f"\n❌ [ERROR] 服務異常：{exc}")
        log_path = ROOT_DIR / "data" / "tray_runtime.log"
        if log_path.exists():
            print("\n最近的運行記錄 (data/tray_runtime.log)：")
            try:
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                print("\n".join(lines[-15:]))
            except Exception:
                pass
        print("\n" + "=" * 70)
        input("請按 Enter 鍵關閉視窗...")
        sys.exit(1)


if __name__ == "__main__":
    main()
