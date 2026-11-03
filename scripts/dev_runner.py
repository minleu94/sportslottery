# -*- coding: utf-8 -*-
"""Development launcher for the local Sportslottery React and FastAPI app."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
os.chdir(ROOT_DIR)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

_local_app_data = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
_configured_log_dir = os.environ.get("SPORTSLOTTERY_LOG_DIR", "").strip()
LOG_DIR = Path(_configured_log_dir) if _configured_log_dir else _local_app_data / "Sportslottery" / "logs"
STARTUP_LOG = LOG_DIR / "dev_runner.log"
_startup_log_file = None


class _DiagnosticStream:
    """Write startup output to the log and, when available, the console."""

    def __init__(self, console, logfile):
        self.console = console
        self.logfile = logfile

    def write(self, value):
        self.logfile.write(value)
        self.logfile.flush()
        if self.console is not None:
            try:
                self.console.write(value)
                self.console.flush()
            except Exception:
                pass
        return len(value)

    def flush(self):
        self.logfile.flush()
        if self.console is not None:
            try:
                self.console.flush()
            except Exception:
                pass


def configure_startup_diagnostics() -> None:
    """Keep errors from the hidden VBS launch available in a local log."""
    global _startup_log_file
    STARTUP_LOG.parent.mkdir(parents=True, exist_ok=True)
    _startup_log_file = STARTUP_LOG.open("a", encoding="utf-8", buffering=1)
    sys.stdout = _DiagnosticStream(sys.stdout, _startup_log_file)
    sys.stderr = _DiagnosticStream(sys.stderr, _startup_log_file)
    started_at = datetime.now(timezone.utc).isoformat()
    print(f"[{started_at}] dev_runner starting; pid={os.getpid()}; python={sys.executable}")


def _report_command_failure(label: str, result: subprocess.CompletedProcess) -> None:
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
    print(f"  - [Error] {label} failed with exit code {result.returncode}.")
    if output:
        print(output[-12000:])


def build_frontend() -> bool:
    """Run the same TypeScript, Vite, and theme checks as the frontend build."""
    node_exe = shutil.which("node")
    frontend_dir = ROOT_DIR / "frontend"
    tsc_script = frontend_dir / "node_modules" / "typescript" / "bin" / "tsc"
    vite_script = frontend_dir / "node_modules" / "vite" / "bin" / "vite.js"
    theme_check = frontend_dir / "scripts" / "check-theme-contract.mjs"

    missing = [str(path.relative_to(ROOT_DIR)) for path in (tsc_script, vite_script, theme_check) if not path.is_file()]
    if not node_exe:
        print("  - [Error] Node.js was not found; refusing to serve an unverified or stale frontend build.")
        return False
    if missing:
        print("  - [Error] Frontend build dependencies or checks are missing: " + ", ".join(missing))
        return False

    commands = (
        ("TypeScript", [node_exe, str(tsc_script), "-b"]),
        ("Vite", [node_exe, str(vite_script), "build"]),
        ("Theme contract", [node_exe, str(theme_check)]),
    )
    for label, command in commands:
        try:
            result = subprocess.run(
                command,
                cwd=str(frontend_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120.0,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            print(f"  - [Error] {label} timed out after 120 seconds.")
            output = exc.stdout or exc.stderr
            if output:
                print(str(output)[-12000:])
            return False
        except OSError as exc:
            print(f"  - [Error] Could not run {label}: {type(exc).__name__}: {exc}")
            return False

        if result.returncode != 0:
            _report_command_failure(label, result)
            return False
        print(f"  - [OK] {label} passed.")

    print("  - [OK] React frontend build completed.")
    return True


def main() -> int:
    configure_startup_diagnostics()

    if "--build-only" in sys.argv:
        print("[Build] Validating and compiling the React frontend.")
        return 0 if build_frontend() else 1

    print("\nSportslottery local development startup")
    print("[1/2] Compiling frontend; existing port owners will not be terminated.")
    if not build_frontend():
        print(f"[Startup failed] Frontend build did not pass. See {STARTUP_LOG}.")
        return 1

    print("[2/2] Starting the Tray manager; FastAPI health and app build are verified before ready.")
    print("  Local UI: http://127.0.0.1:8000")
    print(f"  Startup diagnostics: {STARTUP_LOG}")

    from scripts.tray_manager import AppTrayManager

    app = AppTrayManager()
    try:
        return app.run()
    except KeyboardInterrupt:
        print("\n[Shutdown] Stopping Sportslottery services.")
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
        print("[Shutdown] Services stopped.")
        return 0
    except Exception as exc:
        print(f"[Startup failed] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        print(f"See startup diagnostics: {STARTUP_LOG}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
