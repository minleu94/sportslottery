"""Centralized storage and data location configuration.

Manages data location settings, disk metrics, data migration,
and Windows Scheduled Task synchronization.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
STORAGE_CONFIG_FILE = CONFIG_DIR / "storage_config.yaml"
RESEARCH_PIPELINE_CONFIG_FILE = CONFIG_DIR / "research_pipeline.yaml"

DEFAULT_F_PATH = Path(r"F:\Min\Python\Project\SportsLottery_Data")
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def get_configured_storage_root() -> Path:
    """Read the active storage root from config, or fallback to sensible default."""
    if STORAGE_CONFIG_FILE.exists():
        try:
            payload = yaml.safe_load(STORAGE_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("data_root"):
                path = Path(payload["data_root"])
                if path.is_absolute():
                    return path
                return (PROJECT_ROOT / path).resolve()
        except Exception:
            pass
    if DEFAULT_F_PATH.exists():
        return DEFAULT_F_PATH
    return DEFAULT_DATA_DIR


def get_storage_root() -> Path:
    """Return the active base data directory."""
    return get_configured_storage_root()


def get_db_path() -> Path:
    """Return the active SQLite database path for war chest / wallet."""
    return get_storage_root() / "war_chest.sqlite3"


def get_research_root() -> Path:
    """Return the active research pipeline data root."""
    return get_storage_root() / "research_pipeline"


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


def sync_junction(target_path: Path) -> None:
    """If on Windows and target_path is outside PROJECT_ROOT / 'data', link data junction."""
    if os.name != "nt":
        return
    local_data = PROJECT_ROOT / "data"
    resolved_target = target_path.resolve()
    if local_data.resolve() == resolved_target:
        return
    # Remove existing junction or folder if empty
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        if local_data.exists():
            subprocess.run(["cmd", "/c", "rmdir", str(local_data)], check=False, creationflags=creationflags)
        if not local_data.exists():
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(local_data), str(resolved_target)],
                check=False,
                creationflags=creationflags,
            )
    except Exception:
        pass


def update_storage_location(new_path_str: str, migrate: bool = True) -> Tuple[bool, str]:
    """Validate, migrate data, and apply new storage path."""
    new_path_str = new_path_str.strip().strip('"').strip("'")
    if not new_path_str:
        return False, "路徑不可為空。"

    target = Path(new_path_str)
    if not target.is_absolute():
        target = (PROJECT_ROOT / target).resolve()

    current = get_storage_root().resolve()
    if target.resolve() == current:
        return True, "存放路徑已是當前目錄，無需變更。"

    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return False, f"無法建立或寫入目標目錄: {exc}"

    if migrate and current.exists():
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            # Use robocopy on Windows for fast reliable transfer
            if os.name == "nt":
                subprocess.run(
                    ["robocopy", str(current), str(target), "/E", "/R:2", "/W:1"],
                    check=False,
                    creationflags=creationflags,
                )
            else:
                for item in current.iterdir():
                    dest_item = target / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, dest_item)
        except Exception as exc:
            return False, f"資料遷移失敗: {exc}"

    save_storage_config(target)
    sync_junction(target)
    sync_scheduled_task_argument(target / "research_pipeline")
    return True, f"已成功將資料存放位置更新為：{target}"


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
    $task = Get-ScheduledTask -TaskName "{task_name}" -ErrorAction SilentlyContinue
    if ($task) {{
        $action = New-ScheduledTaskAction -Execute $task.Actions[0].Execute -Argument '{arguments}' -WorkingDirectory '{PROJECT_ROOT}'
        Set-ScheduledTask -TaskName "{task_name}" -Action $action | Out-Null
        Write-Output "UPDATED"
    }} else {{
        Write-Output "TASK_NOT_FOUND"
    }}
    """
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script],
                              capture_output=True, text=True, timeout=10, creationflags=creationflags)
        out = proc.stdout.strip()
        if "UPDATED" in out:
            return True, "已同步更新 Windows 排程任務的資料路徑。"
        return False, out
    except Exception as exc:
        return False, str(exc)
