from pathlib import Path

import pytest

from core.research_paths import PROJECT_ROOT, research_paths, resolve_research_data_root
import core.storage_config as storage_config


def test_default_components_share_the_configured_research_ledger():
    from core.snapshot_logger import SNAPSHOT_FILE
    from core.shadow_parlay_logger import PARLAY_SNAPSHOT_FILE
    from core.odds_watcher import ODDS_HISTORY_FILE
    paths = research_paths()
    assert paths["snapshots"] == SNAPSHOT_FILE
    assert paths["parlays"] == PARLAY_SNAPSHOT_FILE
    assert paths["odds"] == ODDS_HISTORY_FILE
    assert paths["root"] == storage_config.get_storage_path_bundle().research_root
    assert paths["root"] == paths["root"].resolve()


@pytest.mark.parametrize("relative", [".", "data", "data/cache", "data/cache/subfolder",
                                    "data/historical", "data/model_state/checkpoint"])
def test_protected_parent_and_descendant_roots_are_rejected(relative):
    with pytest.raises(ValueError):
        resolve_research_data_root(PROJECT_ROOT / relative)


def test_reading_paths_has_no_filesystem_side_effect(tmp_path):
    target = tmp_path / "not_created"
    paths = research_paths(target)
    assert paths["root"] == target.resolve()
    assert not target.exists()


def test_research_path_from_project_data_alias_is_canonical():
    alias = PROJECT_ROOT / "data" / "research_pipeline"
    resolved = resolve_research_data_root(alias)

    assert resolved == alias.resolve()
