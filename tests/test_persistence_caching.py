"""Unit test for persistence caching and invalidation."""
from pathlib import Path
import tempfile
import pytest

from core.persistence import read_jsonl, append_jsonl, atomic_write_bytes, clear_jsonl_cache


def test_persistence_caching_and_invalidation(tmp_path: Path):
    target = tmp_path / "test_ledger.jsonl"
    clear_jsonl_cache()

    # Empty initially
    assert read_jsonl(target) == []

    # Write two records
    append_jsonl(target, {"id": 1, "value": "A"})
    append_jsonl(target, {"id": 2, "value": "B"})

    records_first = read_jsonl(target)
    assert len(records_first) == 2
    assert records_first[0]["value"] == "A"
    assert records_first[1]["value"] == "B"

    # Mutating returned record should not mutate internal cache
    records_first[0]["value"] = "MUTATED"

    records_second = read_jsonl(target)
    assert records_second[0]["value"] == "A"

    # Append invalidates cache and returns fresh data
    append_jsonl(target, {"id": 3, "value": "C"})
    records_third = read_jsonl(target)
    assert len(records_third) == 3
    assert records_third[2]["value"] == "C"

    # atomic_write_bytes invalidates cache
    atomic_write_bytes(target, b'{"id": 99, "value": "Z"}\n')
    records_fourth = read_jsonl(target)
    assert len(records_fourth) == 1
    assert records_fourth[0]["id"] == 99
