from pathlib import Path

import pytest

from core.research_paths import PROJECT_ROOT, research_paths, resolve_research_data_root


def test_default_components_share_the_configured_research_ledger():
    from core.snapshot_logger import SNAPSHOT_FILE
    from core.shadow_parlay_logger import PARLAY_SNAPSHOT_FILE
    from core.odds_watcher import ODDS_HISTORY_FILE
    paths = research_paths()
    assert paths["snapshots"] == SNAPSHOT_FILE
    assert paths["parlays"] == PARLAY_SNAPSHOT_FILE
    assert paths["odds"] == ODDS_HISTORY_FILE
    assert paths["root"] == PROJECT_ROOT / "data/research_pipeline"


@pytest.mark.parametrize("relative", [".", "data", "data/cache", "data/cache/subfolder",
                                    "data/historical", "data/model_state/checkpoint"])
def test_protected_parent_and_descendant_roots_are_rejected(relative):
    with pytest.raises(ValueError):
        resolve_research_data_root(PROJECT_ROOT / relative)


def test_reading_paths_has_no_filesystem_side_effect(tmp_path):
    target = tmp_path / "not_created"
    paths = research_paths(target)
    assert paths["root"] == target
    assert not target.exists()
