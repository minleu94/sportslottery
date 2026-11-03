"""Keep local credentials and mutable config out of desktop distributions."""

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = PROJECT_ROOT / "sportslottery_dist.spec"
EXPECTED_SAFE_CONFIG_FILES = {
    "evidence_weights.yaml",
    "expert_sources.yaml",
    "model_acceptance.yaml",
    "models.yaml",
    "ngrok_config.example.yaml",
    "odds_api.example.yaml",
    "research_pipeline.yaml",
    "result_coverage_evidence.yaml",
    "source_registry.yaml",
    "storage_config.yaml",
}


def test_pyinstaller_config_bundle_is_an_explicit_safe_allowlist():
    source = SPEC_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    configured_names = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SAFE_CONFIG_FILES"
            for target in node.targets
        ):
            configured_names = ast.literal_eval(node.value)
            break

    assert configured_names is not None
    assert set(configured_names) == EXPECTED_SAFE_CONFIG_FILES
    assert all((PROJECT_ROOT / "config" / name).is_file() for name in configured_names)
    assert "('config', 'config')" not in source
