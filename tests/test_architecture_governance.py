import ast
from pathlib import Path

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def test_contracts_stay_framework_provider_and_storage_independent():
    forbidden = (
        "fastapi",
        "starlette",
        "streamlit",
        "pydantic",
        "integrations",
        "server",
        "sqlite3",
        "requests",
        "httpx",
        "urllib",
        "core.storage_config",
        "core.market_forward_pipeline",
        "core.market_scheduler",
        "core.research_pipeline",
    )
    offenders = {}
    for path in (ROOT / "core" / "contracts").glob("*.py"):
        found = sorted(
            module for module in _imports(path)
            if any(_matches(module, prefix) for prefix in forbidden)
        )
        if found:
            offenders[str(path.relative_to(ROOT))] = found
    assert offenders == {}


def test_provider_adapters_do_not_depend_on_application_or_server_composition():
    forbidden = (
        "core.market_forward_pipeline",
        "core.market_scheduler",
        "core.research_pipeline",
        "core.signal_hub",
        "server",
    )
    offenders = {}
    for path in (ROOT / "integrations").rglob("*.py"):
        found = sorted(
            module for module in _imports(path)
            if any(_matches(module, prefix) for prefix in forbidden)
        )
        if found:
            offenders[str(path.relative_to(ROOT))] = found
    assert offenders == {}


def test_default_test_harness_blocks_network_calls():
    with pytest.raises(AssertionError, match="Network access is disabled"):
        requests.get("https://example.invalid/")


def test_ci_uses_locked_offline_suite_and_storage_boundary_checks():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pip install -r requirements-lock.txt" in workflow
    assert "pip install -r requirements.txt" not in workflow
    assert "npm ci" in workflow
    assert "python -m pip wheel --no-deps --no-build-isolation" in workflow
    assert "python -m pytest tests -v" in workflow
    assert "scripts/check_version_consistency.py" in workflow
    assert "scripts/check_tracked_file_policy.py" in workflow
    assert "npm run lint" in workflow
    assert "--junitxml=" in workflow
    assert "--run-live" not in workflow
    assert "--run-local-data" not in workflow


def test_release_workflow_validates_tag_version_and_main_ancestry_before_builds():
    workflow = (ROOT / ".github" / "workflows" / "build_releases.yml").read_text(encoding="utf-8")
    assert "validate_release_tag.py" in workflow
    assert "needs: validate-release" in workflow
    assert "fetch-depth: 0" in workflow
