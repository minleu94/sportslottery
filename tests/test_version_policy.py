from pathlib import Path

import pytest

from scripts.check_version_consistency import (
    check_version_consistency,
    validate_tag_name,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_all_package_metadata_uses_canonical_app_version():
    assert check_version_consistency(REPO_ROOT) == "2.3.0"


@pytest.mark.parametrize("tag", ["v2.3.1", "2.3.0", "v2.3.0-rc1"])
def test_release_tag_must_exactly_match_stable_app_version(tag):
    with pytest.raises(ValueError):
        validate_tag_name(tag, "2.3.0")


def test_matching_release_tag_is_accepted():
    validate_tag_name("v2.3.0", "2.3.0")
