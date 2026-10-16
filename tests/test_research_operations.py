import json
from types import SimpleNamespace
from core.research_operations import refresh_task_observation


def test_scheduler_refresh_only_queries_owned_task_and_saves_receipt(tmp_path,monkeypatch):
    import core.research_operations as ops
    observed=[]
    def run(command,**kwargs):
        observed.append(command)
        assert "Register-ScheduledTask" not in command[-1]
        assert "Start-ScheduledTask" not in command[-1]
        assert "SportsLottery-Research-Pipeline" in command[-1]
        return SimpleNamespace(returncode=0,stderr="",stdout=json.dumps({"task_name":"SportsLottery-Research-Pipeline","state":"Ready","enabled":True,"last_task_result":0,"observed_at_utc":"2026-10-14T22:00:00Z"}))
    monkeypatch.setattr(ops.subprocess,"run",run)
    root=tmp_path/"research"
    receipt=refresh_task_observation(root)
    assert receipt["enabled"]
    assert observed
    assert json.loads((root/"operations/task_status.json").read_text(encoding="utf-8"))["last_task_result"]==0


def test_scheduler_query_failure_never_claims_success(tmp_path,monkeypatch):
    import core.research_operations as ops
    monkeypatch.setattr(ops.subprocess,"run",lambda *args,**kwargs:SimpleNamespace(returncode=1,stderr="Access denied",stdout=""))
    receipt=refresh_task_observation(tmp_path/"research")
    assert receipt["state"]=="UNKNOWN"
    assert "Access denied" in receipt["error"]
    assert "enabled" not in receipt
