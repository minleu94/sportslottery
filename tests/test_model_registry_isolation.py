from pathlib import Path
import tempfile
import yaml

from core.model_registry import ModelRegistry
from core.research_paths import research_paths
from integrations.common.models import TaiwanLeg


def test_data_root_isolates_adapter_caches_state_and_acceptance_ledger(tmp_path):
    root = tmp_path / "research-run"
    registry = ModelRegistry(data_root=root)

    assert registry.acceptance_gate.snapshot_path == root / "historical" / "prediction_snapshots.jsonl"
    assert registry.acceptance_gate.policy_path.exists()
    assert registry._instances["penaltyblog_dixon_coles"].cache_dir == str(
        root / "cache" / "models" / "penaltyblog_dixon_coles"
    )
    assert registry._instances["live_mlb_elo"].state_file == root / "model_state" / "live_mlb_elo.json"
    assert not (Path(__file__).resolve().parents[1] / "data" / "live_mlb_elo_state.json").exists() or (
        registry._instances["live_mlb_elo"].state_file != Path(__file__).resolve().parents[1] / "data" / "live_mlb_elo_state.json"
    )


def test_default_registry_shares_research_pipeline_model_state():
    default = ModelRegistry()
    expected = research_paths()["root"]
    assert default.data_root == expected
    assert default.acceptance_gate.snapshot_path == research_paths()["snapshots"]
    assert default._instances["penaltyblog_dixon_coles"].cache_dir == str(
        expected / "cache" / "models" / "penaltyblog_dixon_coles"
    )
    assert default._instances["live_mlb_elo"].state_file == expected / "model_state" / "live_mlb_elo.json"
    # An explicit root equal to configured default resolves to exactly the same paths.
    explicit = ModelRegistry(data_root=expected)
    assert explicit.acceptance_gate.snapshot_path == default.acceptance_gate.snapshot_path
    assert explicit._instances["live_mlb_elo"].state_file == default._instances["live_mlb_elo"].state_file


def test_registry_reloads_changed_elo_state_before_evaluation():
    project_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(dir=project_root) as folder:
        root = Path(folder) / "research"
        config = Path(folder) / "models.yaml"
        config.write_text(yaml.safe_dump({"models": {
            "live_mlb_elo": {
                "enabled": True,
                "adapter": "integrations.models.external.live_mlb_elo.LiveMLBEloAdapter",
                "sport": "baseball",
                "source_category": "OPEN_SOURCE_ENGINE",
                "independence_group": "LIVE_MLB_ELO",
                "version": "test",
            }
        }}), encoding="utf-8")
        registry = ModelRegistry(config_path=config, data_root=root)
        leg = TaiwanLeg(event_id="state-sync", sport="baseball", league="MLB", market="不讓分",
                        selection="Dodgers Home Win", taiwan_odds=2.0, start_time_utc="2026-10-20T20:00:00+00:00",
                        away_team="New York Yankees", home_team="Los Angeles Dodgers", side="主")
        before = registry.evaluate_leg_across_models(leg)
        assert len(before) == 1
        assert before[0].data_as_of is None

        adapter = registry._instances["live_mlb_elo"]
        result = adapter.apply_official_games([{
            "gamePk": 191000987,
            "gameDate": "2026-10-10T20:00:00Z",
            "status": {"abstractGameState": "Final", "codedGameState": "F"},
            "teams": {"home": {"team": {"name": "Los Angeles Dodgers"}},
                      "away": {"team": {"name": "New York Yankees"}}},
            "linescore": {"teams": {"home": {"runs": 5}, "away": {"runs": 2}}},
        }])
        assert result["data_as_of"].startswith("2026-10-10")
        after = registry.evaluate_leg_across_models(leg)
        assert len(after) == 1
        assert after[0].data_as_of == result["data_as_of"]
        assert after[0].freshness_status == "FRESH"

        # A malformed replacement must clear stale data instead of retaining FRESH state.
        adapter.state_file.write_text("{invalid", encoding="utf-8")
        failed_closed = registry.evaluate_leg_across_models(leg)
        assert len(failed_closed) == 1
        assert failed_closed[0].data_as_of is None
        assert failed_closed[0].freshness_status == "UNKNOWN"
