"""Read a single owned Windows scheduler task; never change task settings."""
from __future__ import annotations
import json
import os
import subprocess
from datetime import datetime,timezone
from core.research_paths import research_paths

TASK_QUERY = r"""$ErrorActionPreference='Stop'; $t=Get-ScheduledTask -TaskName 'SportsLottery-Research-Pipeline'; $i=Get-ScheduledTaskInfo -TaskName 'SportsLottery-Research-Pipeline'; [ordered]@{observed_at_utc=[DateTime]::UtcNow.ToString('o');task_name=$t.TaskName;state=$t.State.ToString();enabled=$t.Settings.Enabled;last_run_time_utc=$i.LastRunTime.ToUniversalTime().ToString('o');last_task_result=$i.LastTaskResult;next_run_time_utc=$i.NextRunTime.ToUniversalTime().ToString('o');logon_type=$t.Principal.LogonType.ToString()} | ConvertTo-Json"""


def refresh_task_observation(data_root=None):
    if os.name != "nt":
        return {"state":"UNAVAILABLE","error":"Windows scheduler is unavailable on this platform."}
    try:
        process=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",TASK_QUERY],
                               capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=20,
                               creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or "Scheduler query failed")
        record=json.loads(process.stdout)
        if not isinstance(record,dict) or record.get("task_name")!="SportsLottery-Research-Pipeline":
            raise ValueError("Unexpected scheduler response")
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        record={"observed_at_utc":datetime.now(timezone.utc).isoformat(),"state":"UNKNOWN","error":str(exc)}
    from core.research_pipeline import _write_json_atomic
    _write_json_atomic(research_paths(data_root)["root"] / "operations/task_status.json", record)
    return record
