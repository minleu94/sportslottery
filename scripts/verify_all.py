#!/usr/bin/env python3
"""One-Click Verification Script for Sportslottery (P3-1).

Performs comprehensive validation of:
1. Python unit and integration test suites (Security, Betting Integrity, SQLite Backup/Restore, Resilience, Wallet, Settlement).
2. Frontend TypeScript type checking (tsc -b).
3. Frontend production build (vite build).
4. Cross-platform path and environment sanity.

Returns exit code 0 on complete pass, non-zero on any failure.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"


def print_banner(msg: str) -> None:
    sep = "=" * 70
    print(f"\n{sep}\n  {msg}\n{sep}")


def print_success(msg: str) -> None:
    print(f" [PASS] {msg}")


def print_fail(msg: str) -> None:
    print(f" [FAIL] {msg}")


def find_node_executable() -> str | None:
    """Find a usable node binary across Windows, macOS, and Linux."""
    # 1. System PATH
    node_in_path = shutil.which("node")
    if node_in_path:
        return node_in_path

    # 2. Windows known locations
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "runtimes",
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "nodejs",
            Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "nodejs",
            Path(os.environ.get("APPDATA", "")) / "npm",
        ]
        for base in candidates:
            if not base.exists():
                continue
            matches = list(base.glob("**/node.exe"))
            if matches:
                return str(matches[0])

    # 3. Unix known locations
    for p in ["/usr/local/bin/node", "/usr/bin/node", "/opt/homebrew/bin/node"]:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    return None


def run_python_tests() -> bool:
    print_banner("1. Running Python Regression & Security Suites")
    test_targets = [
        "tests/test_phase1_security.py",
        "tests/test_phase2_betting_integrity.py",
        "tests/test_sqlite_backup_restore.py",
        "tests/test_external_source_resilience.py",
        "tests/test_wallet_atomicity.py",
        "tests/test_ticket_settlement.py",
        "tests/test_bet_validation.py",
        "tests/test_profile_manager.py",
    ]

    cmd = [sys.executable, "-m", "pytest"] + test_targets + ["-v", "--tb=short"]
    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT_DIR))
    if result.returncode == 0:
        print_success("Python test suites passed cleanly.")
        return True
    else:
        print_fail(f"Python tests failed with return code {result.returncode}.")
        return False


def run_frontend_build() -> bool:
    print_banner("2. Running Frontend TypeScript Typecheck & Production Build")
    node_exe = find_node_executable()
    if not node_exe:
        print_fail("Node.js executable could not be found. Please install Node.js (v18+).")
        return False

    print(f"Using Node runtime: {node_exe}")

    # Check if node_modules exists
    if not (FRONTEND_DIR / "node_modules").is_dir():
        print_fail("frontend/node_modules is missing! Run 'npm install' in frontend directory.")
        return False

    tsc_cli = FRONTEND_DIR / "node_modules" / "typescript" / "bin" / "tsc"
    vite_cli = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"

    # Step 2a: tsc -b
    print("\n--- Running TypeScript check (tsc -b) ---")
    tsc_cmd = [node_exe, str(tsc_cli), "-b"]
    tsc_res = subprocess.run(tsc_cmd, cwd=str(FRONTEND_DIR))
    if tsc_res.returncode != 0:
        print_fail(f"TypeScript typecheck failed with return code {tsc_res.returncode}.")
        return False
    print_success("TypeScript check passed (0 type errors).")

    # Step 2b: vite build
    print("\n--- Running Vite Production Build ---")
    vite_cmd = [node_exe, str(vite_cli), "build"]
    vite_res = subprocess.run(vite_cmd, cwd=str(FRONTEND_DIR))
    if vite_res.returncode != 0:
        print_fail(f"Vite production build failed with return code {vite_res.returncode}.")
        return False
    print_success("Vite production build completed successfully.")
    return True


def run_cross_platform_checks() -> bool:
    print_banner("3. Checking Cross-Platform File and Path Hygiene")
    # Verify data and dist directories can be resolved with normalized paths
    data_dir = ROOT_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    backups_dir = data_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    print_success(f"Paths verified on {sys.platform}: {ROOT_DIR.as_posix()}")
    return True


def main() -> int:
    print_banner("Sportslottery System Verification Suite (Phase 1, 2, 3)")
    print(f"Platform: {sys.platform} | Python: {sys.version.split()[0]} | Workspace: {ROOT_DIR}")

    passed = True
    if not run_cross_platform_checks():
        passed = False

    if not run_python_tests():
        passed = False

    if not run_frontend_build():
        passed = False

    print_banner("Verification Summary")
    if passed:
        print_success("ALL VERIFICATION CHECKS PASSED! Ready for deployment on dev branch.")
        return 0
    else:
        print_fail("ONE OR MORE CHECKS FAILED. Please review the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
