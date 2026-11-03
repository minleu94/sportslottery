from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_default_model_cache_paths_stay_inside_isolated_test_storage():
    import core.storage_config as storage_config
    from integrations.models.espn_poisson_soccer import ESPNPoissonSoccerFallback
    from integrations.models.espn_pythagorean_mlb import ESPNPythagoreanMLBModel
    from integrations.models.external.fivethirtyeight_mlb_elo import FiveThirtyEightMLBEloAdapter
    from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter
    from integrations.models.penaltyblog_soccer_model import PenaltyblogSoccerAdapter
    from integrations.models.pybaseball_mlb_model import PybaseballMLBAdapter

    isolated_root = Path(storage_config.get_storage_root()).resolve()
    cache_paths = [
        Path(ESPNPoissonSoccerFallback().cache_dir),
        Path(ESPNPythagoreanMLBModel().cache_file),
        Path(FiveThirtyEightMLBEloAdapter().cache_file),
        Path(PenaltyblogDixonColesAdapter().cache_dir),
        Path(PenaltyblogSoccerAdapter().cache_dir),
        Path(PybaseballMLBAdapter().cache_file),
    ]

    assert all(path.resolve().is_relative_to(isolated_root) for path in cache_paths)


def test_test_harness_rejects_formal_data_file_reads_and_writes():
    import core.storage_config as storage_config

    target = Path(storage_config.DEFAULT_DATA_DIR) / "offline-guard-probe.json"
    with pytest.raises(RuntimeError, match="formal research data"):
        target.open("r", encoding="utf-8")
    with pytest.raises(RuntimeError, match="formal research data"):
        target.open("w", encoding="utf-8")


def test_webhook_app_import_does_not_load_local_line_credentials():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import scripts.line_webhook_server as server; assert server.notifier._instance is None",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("launcher", ["main.py", "sportslottery_bootstrap.py"])
def test_launcher_help_exits_without_starting_application(launcher: str):
    result = subprocess.run(
        [sys.executable, str(ROOT / launcher), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout
