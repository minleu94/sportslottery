import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_core_imports_shared_types_from_core_contracts():
    legacy_type_modules = {"integrations.common.models", "integrations.odds.market_models"}
    offenders = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "core").rglob("*.py")
        if _imports(path) & legacy_type_modules
    }
    assert offenders == set()


def test_research_and_market_helpers_do_not_import_their_orchestrators_back():
    forbidden = {
        "core/research_mlb.py": "core.research_pipeline",
        "core/research_reporting.py": "core.research_pipeline",
        "core/research_operations.py": "core.research_pipeline",
        "core/market_forward_pipeline.py": "core.market_scheduler",
        "core/probability_evidence.py": "core.edge_engine",
    }
    for relative_path, module_name in forbidden.items():
        assert module_name not in _imports(ROOT / relative_path)


def test_contract_modules_have_no_provider_dependencies():
    for path in (ROOT / "core" / "contracts").glob("*.py"):
        imported = _imports(path)
        assert not any(module.startswith("integrations.") for module in imported)\n