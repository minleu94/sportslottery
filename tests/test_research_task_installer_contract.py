from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT_ROOT / "scripts" / "install_research_task.ps1"
CONFIG = PROJECT_ROOT / "config" / "research_pipeline.yaml"


def test_research_task_installer_reserves_cadence_headroom():
    source = INSTALLER.read_text(encoding="utf-8")
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cadence_minutes = int(config["cadence_minutes"])
    execution_limit_minutes = min(14, cadence_minutes - 1)

    assert cadence_minutes == 15
    assert execution_limit_minutes == 14
    assert "$ExecutionLimitMinutes = [Math]::Min(14, $CadenceMinutes - 1)" in source
    assert "ExecutionLimitMinutes = $ExecutionLimitMinutes" in source
    assert "-ExecutionTimeLimit (New-TimeSpan -Minutes $Plan.ExecutionLimitMinutes)" in source
    assert "-MultipleInstances IgnoreNew" in source
    assert "--resume" in source
