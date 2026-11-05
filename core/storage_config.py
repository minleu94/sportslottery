"""Centralized storage and data location configuration.

Manages data location settings, disk metrics, data migration,
and Windows Scheduled Task synchronization.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import hashlib
import uuid
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
STORAGE_CONFIG_FILE = CONFIG_DIR / "storage_config.yaml"
RESEARCH_PIPELINE_CONFIG_FILE = CONFIG_DIR / "research_pipeline.yaml"

DEFAULT_F_PATH = Path(r"F:\Min\Python\Project\SportsLottery_Data")
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def _is_windows() -> bool:
    return os.name == "nt"


@dataclass(frozen=True)
class StoragePathBundle:
    """Canonical absolute paths resolved once for the current process."""

    root: Path
    wallet_db: Path
    research_root: Path
    shadow_root: Path
    shadow_db: Path


_storage_paths_lock = threading.Lock()
_storage_paths: Optional[StoragePathBundle] = None


def get_fallback_user_data_dir() -> Path:
    """Return a safe per-user storage root when custom or developer paths do not exist."""
    import sys
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "SportsLottery" / "data"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SportsLottery" / "data"
    else:
        return Path.home() / ".sportslottery" / "data"


def get_configured_storage_root() -> Path:
    """Read the active storage root from config, or fallback to sensible default."""
    if STORAGE_CONFIG_FILE.exists():
        try:
            payload = yaml.safe_load(STORAGE_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("data_root"):
                path = Path(payload["data_root"])
                if path.is_absolute():
                    # Check if drive / root actually exists on the host machine
                    drive_available = True
                    if os.name == "nt" and path.drive:
                        drive_available = Path(f"{path.drive}\\").exists()
                    if drive_available and (path.exists() or Path(path.anchor).exists()):
                        return path
                else:
                    return (PROJECT_ROOT / path).resolve()
        except Exception:
            pass
    if DEFAULT_F_PATH.exists():
        return DEFAULT_F_PATH
    if DEFAULT_DATA_DIR.exists():
        return DEFAULT_DATA_DIR
    user_fallback = get_fallback_user_data_dir()
    user_fallback.mkdir(parents=True, exist_ok=True)
    return user_fallback


def resolve_storage_path_bundle(root: Optional[Path] = None) -> StoragePathBundle:
    """Build one canonical path set without creating or migrating any data."""
    resolved_root = Path(root or get_configured_storage_root()).expanduser().resolve()
    research_root = (resolved_root / "research_pipeline").resolve()
    shadow_root = (resolved_root / "shadow").resolve()
    return StoragePathBundle(
        root=resolved_root,
        wallet_db=resolved_root / "war_chest.sqlite3",
        research_root=research_root,
        shadow_root=shadow_root,
        shadow_db=shadow_root / "shadow_portfolio.sqlite",
    )


def get_storage_path_bundle() -> StoragePathBundle:
    """Return the immutable active paths captured for this process."""
    global _storage_paths
    if _storage_paths is None:
        with _storage_paths_lock:
            if _storage_paths is None:
                _storage_paths = resolve_storage_path_bundle()
    return _storage_paths


def get_storage_root() -> Path:
    """Return the active base data directory resolved for this process."""
    return get_storage_path_bundle().root


def get_db_path() -> Path:
    """Return the active SQLite database path for war chest / wallet."""
    return get_storage_path_bundle().wallet_db


def get_research_root() -> Path:
    """Return the active research pipeline data root."""
    return get_storage_path_bundle().research_root


def get_storage_stats() -> Dict[str, Any]:
    """Gather storage path, disk usage, and component file sizes."""
    root = get_storage_root()
    exists = root.exists()

    # Disk usage
    drive = None
    free_gb = 0.0
    total_gb = 0.0
    used_pct = 0.0

    try:
        drive_target = str(root.anchor if root.is_absolute() else PROJECT_ROOT.anchor)
        drive = drive_target.rstrip("\\")
        total_b, used_b, free_b = shutil.disk_usage(drive_target)
        free_gb = round(free_b / (1024**3), 2)
        total_gb = round(total_b / (1024**3), 2)
        used_pct = round((used_b / total_b) * 100, 1) if total_b > 0 else 0.0
    except Exception:
        pass

    # File size metrics
    def get_file_size_mb(path: Path) -> float:
        try:
            if path.exists() and path.is_file():
                return round(path.stat().st_size / (1024 * 1024), 2)
        except Exception:
            pass
        return 0.0

    db_size = get_file_size_mb(root / "war_chest.sqlite3")
    research_db = root / "research_pipeline" / "historical" / "research.sqlite3"
    research_db_size = get_file_size_mb(research_db)
    parlay_size = get_file_size_mb(root / "research_pipeline" / "historical" / "parlay_snapshots.jsonl")
    pred_size = get_file_size_mb(root / "research_pipeline" / "historical" / "prediction_snapshots.jsonl")
    odds_size = get_file_size_mb(root / "research_pipeline" / "historical" / "odds_history.jsonl")
    mlb_size = get_file_size_mb(root / "research_pipeline" / "model_state" / "mlb_official_schedule_ledger.json")

    total_mb = 0.0
    file_count = 0
    if exists:
        try:
            for item in root.rglob("*"):
                if item.is_file():
                    file_count += 1
                    try:
                        total_mb += item.stat().st_size
                    except Exception:
                        pass
            total_mb = round(total_mb / (1024 * 1024), 2)
        except Exception:
            pass

    # Is directory junction on C:
    is_junction = False
    try:
        local_data = PROJECT_ROOT / "data"
        if local_data.exists():
            if os.name == "nt":
                import ctypes
                attrs = ctypes.windll.kernel32.GetFileAttributesW(str(local_data))
                is_junction = bool(attrs != -1 and (attrs & 0x400))
            else:
                is_junction = local_data.is_symlink()
    except Exception:
        pass

    return {
        "storage_root": str(root),
        "exists": exists,
        "is_junction": is_junction,
        "drive": drive,
        "drive_free_gb": free_gb,
        "drive_total_gb": total_gb,
        "drive_used_pct": used_pct,
        "db_size_mb": db_size,
        "research_db_size_mb": research_db_size,
        "parlay_snapshots_mb": parlay_size,
        "prediction_snapshots_mb": pred_size,
        "odds_history_mb": odds_size,
        "mlb_schedule_mb": mlb_size,
        "total_data_mb": total_mb,
        "file_count": file_count,
    }


def save_storage_config(target_path: Path) -> None:
    """Save storage_config.yaml and synchronize research_pipeline.yaml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_payload = {
        "data_root": str(target_path).replace("\\", "/"),
        "database_file": str(target_path / "war_chest.sqlite3").replace("\\", "/"),
        "research_pipeline_root": str(target_path / "research_pipeline").replace("\\", "/"),
    }
    STORAGE_CONFIG_FILE.write_text(yaml.safe_dump(config_payload, allow_unicode=True), encoding="utf-8")


def _is_windows_junction(path: Path) -> bool:
    if not _is_windows() or not path.exists():
        return False
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return bool(attrs != -1 and (attrs & 0x400))
    except Exception:
        return False


def sync_junction(target_path: Path) -> Tuple[bool, str]:
    """Safely point the project data alias at a validated storage root.

    Existing directories are renamed to a retained backup before linking; they
    are never recursively removed. A failed link restores the previous path.
    """
    if not _is_windows():
        return True, "Junction 不適用於此作業系統。"
    local_data = PROJECT_ROOT / "data"
    try:
        resolved_target = Path(target_path).resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return False, f"Junction 目標路徑無效：{exc}"
    if not resolved_target.is_dir():
        return False, f"Junction 目標不存在或不是目錄：{resolved_target}"
    if local_data.resolve() == resolved_target:
        return True, "Junction 已指向目標目錄。"
    try:
        resolved_target.relative_to(local_data.resolve())
        return False, "目標目錄不可位於 data Junction 之下。"
    except ValueError:
        pass

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    backup = None
    had_original_path = os.path.lexists(str(local_data))
    original_path_moved = False

    def restore_original_path() -> Optional[str]:
        if backup is None or not os.path.lexists(str(backup)):
            return None
        if os.path.lexists(str(local_data)):
            return f"原始 data 路徑保留於 {backup}；目前 data 路徑仍存在，未覆寫。"
        try:
            os.rename(backup, local_data)
            return None
        except Exception as exc:
            return f"原始 data 路徑復原失敗：{exc}；原資料保留於 {backup}。"

    def remove_unverified_junction() -> Optional[str]:
        if had_original_path and not original_path_moved:
            # The initial rename failed before the original path was moved.
            # Leave that path untouched instead of treating it as a new link.
            return None
        if not os.path.lexists(str(local_data)):
            return None
        backup_detail = (f"原始資料備份位置：{backup}。" if backup
                         else "原本沒有 data 目錄可供復原。")
        if not _is_windows_junction(local_data):
            return f"data 路徑不是已驗證的 Junction，為避免刪除未知內容而保留；{backup_detail}"
        proc = subprocess.run(
            ["cmd", "/c", "rmdir", str(local_data)], capture_output=True,
            text=True, check=False, creationflags=creationflags,
        )
        if proc.returncode != 0 or os.path.lexists(str(local_data)):
            detail = (proc.stderr or proc.stdout or f"rmdir 回傳碼 {proc.returncode}").strip()
            return f"無法移除未驗證的 Junction：{detail}；{backup_detail}"
        return None

    try:
        if had_original_path:
            backup = local_data.with_name(f"data.storage-backup-{uuid.uuid4().hex}")
            os.rename(local_data, backup)
            original_path_moved = True
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(local_data), str(resolved_target)],
            capture_output=True, text=True, check=False, creationflags=creationflags,
        )
        if proc.returncode != 0 or not _is_windows_junction(local_data) or local_data.resolve() != resolved_target:
            detail = (proc.stderr or proc.stdout or f"mklink 回傳碼 {proc.returncode}").strip()
            cleanup_error = remove_unverified_junction()
            restore_error = restore_original_path() if cleanup_error is None else None
            recovery = cleanup_error or restore_error
            if recovery:
                return False, f"建立 data Junction 失敗：{detail}；{recovery}"
            return False, f"建立 data Junction 失敗：{detail}；原始 data 路徑已保留或復原，原始資料未刪除。"
        return True, (f"Junction 已切換；原目錄保留於 {backup}" if backup else "Junction 已切換。")
    except Exception as exc:
        try:
            cleanup_error = remove_unverified_junction()
            restore_error = restore_original_path() if cleanup_error is None else None
            recovery = cleanup_error or restore_error
        except Exception as restore_exc:
            recovery = f"復原步驟失敗：{restore_exc}；原始資料保留於 {backup}。"
        suffix = f"；{recovery}" if recovery else "；原始 data 路徑已保留或復原，原始資料未刪除。"
        return False, f"Junction 切換失敗：{exc}{suffix}"


def _storage_inventory(root: Path) -> Dict[str, Tuple[str, str]]:
    """Hash every regular file and record directories/symlinks without following them."""
    inventory: Dict[str, Tuple[str, str]] = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        rel_base = base.relative_to(root).as_posix()
        if rel_base != ".":
            inventory[rel_base] = ("dir", "")
        for name in list(dirs):
            path = base / name
            rel = path.relative_to(root).as_posix()
            is_junction = bool(getattr(path, "is_junction", lambda: False)())
            if path.is_symlink() or is_junction:
                inventory[rel] = ("symlink", os.readlink(path))
                dirs.remove(name)
            else:
                inventory[rel] = ("dir", "")
        for name in files:
            path = base / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                inventory[rel] = ("symlink", os.readlink(path))
                continue
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            inventory[rel] = ("file", digest.hexdigest())
    return inventory


def _copy_and_verify_storage(current: Path, target: Path) -> Tuple[bool, str]:
    """Copy without deleting source and verify every source path and file hash."""
    try:
        before = _storage_inventory(current)
        if _is_windows():
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run(
                ["robocopy", str(current), str(target), "/E", "/R:2", "/W:1", "/COPY:DAT", "/DCOPY:DAT", "/SL"],
                capture_output=True, text=True, check=False, creationflags=creationflags,
            )
            # Robocopy codes 0-7 are successful copy/metadata outcomes.
            if not 0 <= proc.returncode <= 7:
                return False, f"robocopy 失敗（回傳碼 {proc.returncode}）：{(proc.stderr or proc.stdout).strip()}"
        else:
            for item in current.iterdir():
                dest_item = target / item.name
                if item.is_dir() and not item.is_symlink():
                    shutil.copytree(item, dest_item, dirs_exist_ok=True, symlinks=True)
                elif item.is_symlink():
                    if not dest_item.exists() and not dest_item.is_symlink():
                        dest_item.symlink_to(os.readlink(item), target_is_directory=item.is_dir())
                else:
                    shutil.copy2(item, dest_item)
        after = _storage_inventory(current)
        copied = _storage_inventory(target)
        if before != after:
            return False, "複製期間來源資料有變動，未能驗證完整性。"
        missing_or_changed = [key for key, value in before.items() if copied.get(key) != value]
        if missing_or_changed:
            return False, f"目標資料驗證失敗；缺少或不一致項目 {len(missing_or_changed)} 個。"
        for relative in before:
            if relative.casefold().endswith((".sqlite", ".sqlite3", ".db")):
                database = target / Path(relative)
                try:
                    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
                        check = connection.execute("PRAGMA quick_check").fetchone()
                except sqlite3.DatabaseError as exc:
                    return False, f"目標 SQLite 完整性檢查失敗：{relative}（{exc}）"
                if not check or str(check[0]).casefold() != "ok":
                    return False, f"目標 SQLite 完整性檢查失敗：{relative}"
        return True, "複製完成且逐檔 SHA-256 驗證通過。"
    except Exception as exc:
        return False, f"資料遷移或完整性驗證失敗：{exc}"


def update_storage_location(new_path_str: str, migrate: bool = True) -> Tuple[bool, str]:
    """Validate, migrate data, and apply new storage path."""
    new_path_str = new_path_str.strip().strip('"').strip("'")
    if not new_path_str:
        return False, "路徑不可為空。"

    target = Path(new_path_str)
    if not target.is_absolute():
        target = (PROJECT_ROOT / target).resolve()

    current = get_storage_root().resolve()
    target = target.resolve()
    if target.resolve() == current:
        return True, "存放路徑已是當前目錄，無需變更。"
    if target.is_relative_to(current) or current.is_relative_to(target):
        return False, "來源與目標路徑不可互相包含。"
    if migrate and not current.is_dir():
        return False, f"來源資料目錄不存在或無法讀取：{current}"

    try:
        target.mkdir(parents=True, exist_ok=True)
        if not target.is_dir():
            return False, "目標路徑不是目錄。"
        probe = target / f".sportslottery-write-check-{uuid.uuid4().hex}"
        with probe.open("xb"):
            pass
        probe.unlink()
    except Exception as exc:
        try:
            if "probe" in locals() and probe.exists():
                probe.unlink()
        except Exception:
            pass
        return False, f"無法建立或寫入目標目錄: {exc}"

    if migrate and current.exists():
        try:
            source_inventory = _storage_inventory(current)
            target_inventory = _storage_inventory(target)
            conflicts = [key for key, value in source_inventory.items()
                         if key in target_inventory and target_inventory[key] != value]
            if conflicts:
                return False, f"目標已有 {len(conflicts)} 個不同內容的同名項目；為避免覆蓋，已中止遷移。"
        except Exception as exc:
            return False, f"無法檢查目標資料：{exc}"
        copied, message = _copy_and_verify_storage(current, target)
        if not copied:
            return False, message

    try:
        save_storage_config(target)
    except Exception as exc:
        try:
            save_storage_config(current)
        except Exception as restore_exc:
            return False, f"儲存設定失敗：{exc}；回復舊設定也失敗：{restore_exc}。來源資料未刪除。"
        return False, f"儲存設定失敗：{exc}；已嘗試保留舊路徑設定。"

    scheduled_ok, scheduled_message = sync_scheduled_task_argument(target / "research_pipeline")
    if _is_windows() and not scheduled_ok and "TASK_NOT_FOUND" not in scheduled_message:
        restore_errors = []
        try:
            save_storage_config(current)
        except Exception as restore_exc:
            restore_errors.append(f"設定復原失敗：{restore_exc}")
        try:
            task_ok, task_message = sync_scheduled_task_argument(current / "research_pipeline")
            if not task_ok and "TASK_NOT_FOUND" not in task_message:
                restore_errors.append(f"排程復原失敗：{task_message}")
        except Exception as restore_exc:
            restore_errors.append(f"排程復原失敗：{restore_exc}")
        suffix = ("；" + "；".join(restore_errors)) if restore_errors else ""
        return False, f"排程同步失敗：{scheduled_message}；已回復舊儲存設定{suffix}。來源資料未刪除。"

    junction_ok, junction_message = sync_junction(target)
    if not junction_ok:
        restore_errors = []
        try:
            save_storage_config(current)
        except Exception as exc:
            restore_errors.append(f"設定復原失敗：{exc}")
        if _is_windows() and scheduled_ok:
            task_ok, task_message = sync_scheduled_task_argument(current / "research_pipeline")
            if not task_ok:
                restore_errors.append(f"排程復原失敗：{task_message}")
        suffix = ("；" + "；".join(restore_errors)) if restore_errors else ""
        return False, f"{junction_message}；已保留原始資料並復原先前設定{suffix}"
    return True, f"已成功將資料存放位置更新為：{target}；{junction_message}"


def get_scheduled_task_status() -> Dict[str, Any]:
    """Check the Windows Scheduled Task status."""
    task_name = "SportsLottery-Research-Pipeline"
    if os.name != "nt":
        return {"available": False, "task_name": task_name, "state": "UNSUPPORTED_OS"}

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        f"""
        $task = Get-ScheduledTask -TaskName "{task_name}" -ErrorAction SilentlyContinue
        if (-not $task) {{
            [pscustomobject]@{{ Exists = $false; State = "NOT_FOUND" }} | ConvertTo-Json
        }} else {{
            $info = Get-ScheduledTaskInfo -TaskName "{task_name}" -ErrorAction SilentlyContinue
            [pscustomobject]@{{
                Exists = $true
                State = $task.State.ToString()
                Enabled = ($task.Settings.Enabled -and $task.State -ne 'Disabled')
                LastRunTime = if ($info.LastRunTime) {{ $info.LastRunTime.ToString("yyyy-MM-dd HH:mm:ss") }} else {{ "" }}
                NextRunTime = if ($info.NextRunTime) {{ $info.NextRunTime.ToString("yyyy-MM-dd HH:mm:ss") }} else {{ "" }}
                LastTaskResult = $info.LastTaskResult
                Arguments = ($task.Actions | Select-Object -ExpandProperty Arguments -ErrorAction SilentlyContinue)
            }} | ConvertTo-Json
        }}
        """,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, creationflags=creationflags)
        if proc.returncode == 0 and proc.stdout.strip():
            import json
            return json.loads(proc.stdout.strip())
    except Exception as exc:
        return {"available": True, "task_name": task_name, "error": str(exc), "state": "QUERY_ERROR"}

    return {"available": True, "task_name": task_name, "state": "UNKNOWN"}


def set_scheduled_task_enabled(enable: bool) -> Tuple[bool, str]:
    """Enable or disable the scheduled task."""
    task_name = "SportsLottery-Research-Pipeline"
    if os.name != "nt":
        return False, "僅支援 Windows 排程器。"

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    action = "Enable-ScheduledTask" if enable else "Disable-ScheduledTask"
    cmd = ["powershell", "-NoProfile", "-Command", f'{action} -TaskName "{task_name}"']
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, creationflags=creationflags)
        if proc.returncode == 0:
            return True, f"排程任務已{'啟用' if enable else '停用'}。"
        return False, proc.stderr.strip() or f"執行失敗（回傳碼 {proc.returncode}）"
    except Exception as exc:
        return False, f"執行失敗: {exc}"


def sync_scheduled_task_argument(new_research_root: Path) -> Tuple[bool, str]:
    """Update scheduled task data-root argument to match the new storage path."""
    task_name = "SportsLottery-Research-Pipeline"
    if os.name != "nt":
        return False, "僅支援 Windows 排程器。"

    main_py = PROJECT_ROOT / "main.py"
    config_yaml = CONFIG_DIR / "research_pipeline.yaml"
    arguments = f'"{main_py}" research-pipeline --config "{config_yaml}" --data-root "{new_research_root}" --resume'

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    ps_script = f"""
    $ErrorActionPreference = "Stop"
    $task = Get-ScheduledTask -TaskName "{task_name}" -ErrorAction SilentlyContinue
    if ($task) {{
        try {{
            $action = New-ScheduledTaskAction -Execute $task.Actions[0].Execute -Argument '{arguments}' -WorkingDirectory '{PROJECT_ROOT}'
            Set-ScheduledTask -TaskName "{task_name}" -Action $action | Out-Null
            Write-Output "UPDATED"
        }} catch {{
            [Console]::Error.WriteLine($_.Exception.Message)
            exit 1
        }}
    }} else {{
        Write-Output "TASK_NOT_FOUND"
    }}
    """
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script],
                              capture_output=True, text=True, timeout=10, creationflags=creationflags)
        out = proc.stdout.strip()
        if proc.returncode == 0 and out == "UPDATED":
            return True, "已同步更新 Windows 排程任務的資料路徑。"
        detail = (proc.stderr or proc.stdout or f"PowerShell 回傳碼 {proc.returncode}").strip()
        return False, detail
    except Exception as exc:
        return False, str(exc)
