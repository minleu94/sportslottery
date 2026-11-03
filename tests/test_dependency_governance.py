from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]


def _requirements_from_file(path: Path) -> list[Requirement]:
    return [
        Requirement(line.strip())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_lock_is_exact_and_covers_declared_runtime_build_and_test_dependencies():
    locked: dict[str, Requirement] = {}
    for requirement in _requirements_from_file(ROOT / "requirements-lock.txt"):
        key = canonicalize_name(requirement.name)
        assert key not in locked, f"duplicate lock entry for {requirement.name}"
        pins = list(requirement.specifier)
        assert len(pins) == 1 and pins[0].operator == "==", (
            f"lock entry must be an exact version pin: {requirement}"
        )
        locked[key] = requirement

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = _requirements_from_file(ROOT / "requirements.txt")
    declared.extend(Requirement(item) for item in project["build-system"]["requires"])
    declared.extend(Requirement(item) for item in project["project"]["dependencies"])
    for group in project["project"].get("optional-dependencies", {}).values():
        declared.extend(Requirement(item) for item in group)

    for requirement in declared:
        key = canonicalize_name(requirement.name)
        assert key in locked, f"{requirement.name} is missing from requirements-lock.txt"
        pins = list(locked[key].specifier)
        version = Version(pins[0].version)
        assert version in requirement.specifier, (
            f"locked {requirement.name}=={version} violates declared range {requirement.specifier}"
        )
