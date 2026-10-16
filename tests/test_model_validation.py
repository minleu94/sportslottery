import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.model_validation import (
    MatchRecord,
    _fit_predict,
    _score_decisions,
    _paired_block_bootstrap,
    load_validation_dataset,
    run_validation,
)
from scripts.fetch_validation_data import fetch_validation_sources


def _write_source_set(root: Path, seasons: dict[str, list[dict[str, str]]]):
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for season, rows in seasons.items():
        body = "Date,HomeTeam,AwayTeam,FTHG,FTAG,B365H,B365D,B365A\n"
        body += "".join(
            ",".join([row.get("Date", ""), row.get("HomeTeam", ""), row.get("AwayTeam", ""),
                       row.get("FTHG", ""), row.get("FTAG", ""), row.get("B365H", ""),
                       row.get("B365D", ""), row.get("B365A", "")]) + "\n"
            for row in rows
        )
        content = body.encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        filename = f"eng_1_{season}_E0_{digest[:12]}.csv"
        (root / filename).write_bytes(content)
        entries.append({"league": "eng.1", "season": season, "source_filename": "E0.csv",
                        "stored_filename": filename, "source_url": f"https://example.test/{season}/E0.csv",
                        "http_status": 200, "retrieved_at_utc": "2026-10-12T00:00:00+00:00",
                        "sha256": digest, "byte_count": len(content)})
    notes = b"B365H/D/A are bookmaker prices.\n"
    notes_hash = hashlib.sha256(notes).hexdigest()
    (root / f"notes_{notes_hash[:12]}.txt").write_bytes(notes)
    entries.append({"league": "notes", "source_filename": "notes.txt",
                    "stored_filename": f"notes_{notes_hash[:12]}.txt",
                    "source_url": "https://example.test/notes.txt", "http_status": 200,
                    "retrieved_at_utc": "2026-10-12T00:00:00+00:00", "sha256": notes_hash,
                    "byte_count": len(notes)})
    manifest = {"schema_version": "football-data-source-manifest-v1", "downloads": entries,
                "generated_at_utc": "2026-10-12T00:00:00+00:00", "errors": []}
    (root / "manifest_20261012T000000Z.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _row(day, home, away, hg="1", ag="0", h="2.10", d="3.20", a="3.80"):
    return {"Date": day, "HomeTeam": home, "AwayTeam": away, "FTHG": hg, "FTAG": ag,
            "B365H": h, "B365D": d, "B365A": a}


def _seasons_for_validation():
    return {
        "2324": [
            _row("11/08/23", "Arsenal", "Chelsea", "2", "1"),
            _row("12/08/23", "Liverpool", "Man City", "0", "0"),
            _row("13/08/23", "Chelsea", "Liverpool", "0", "2"),
            _row("14/08/23", "Man City", "Arsenal", "1", "0"),
        ],
        "2425": [
            _row("11/08/24", "Arsenal", "Chelsea", "2", "1"),
            _row("12/08/24", "Liverpool", "Man City", "0", "0"),
            _row("13/08/24", "Chelsea", "Liverpool", "0", "2"),
        ],
        "2526": [
            _row("11/08/25", "Arsenal", "Chelsea", "2", "1"),
            _row("12/08/25", "Liverpool", "Man City", "0", "0"),
            _row("13/08/25", "Chelsea", "Liverpool", "0", "2"),
        ],
    }


def test_official_source_profile_dedupes_conflicts_and_preserves_missingness(tmp_path):
    seasons = _seasons_for_validation()
    seasons["2324"] += [
        _row("11/08/23", "Arsenal", "Chelsea", "2", "1"),  # exact duplicate
        _row("11/08/23", "Arsenal", "Chelsea", "3", "1"),  # conflicting duplicate key
        _row("12/08/23", "Liverpool", "Man City", "0", "0"),  # exact duplicate to dedupe
        _row("bad-date", "Arsenal", "Liverpool"),
        _row("17/08/23", "Chelsea", "Man City", "not-final", "1"),
        _row("18/08/23", "Arsenal", "Liverpool", "1", "0", "1.00", "3.2", "3.7"),
    ]
    source_dir = _write_source_set(tmp_path / "sources", seasons)
    rows, profile = load_validation_dataset(source_dir, "eng.1")
    assert profile["conflicting_duplicate_groups"] == 1
    assert profile["exclusions"]["CONFLICTING_DUPLICATE_ROW_KEY"] == 3
    assert profile["duplicate_rows_removed"] == 1
    assert profile["missing_date_rows"] == 1
    assert profile["invalid_score_rows"] == 1
    assert profile["invalid_market_price_cells"] >= 1
    assert all(row.home_team != "Arsenal" or row.away_team != "Chelsea" for row in rows if row.season == "2324")
    assert {source["league"] for source in profile["sources"]} == {"eng.1", "notes"}
    assert all(len(source["sha256"]) == 64 for source in profile["sources"])


def _match(day, home="SOC_ARS", away="SOC_CHE", hg=1, ag=0):
    return MatchRecord("eng.1", "2324", day, home, away, home, away, hg, ag,
                       2.0, 3.0, 4.0, "fixture.csv", "a" * 64, day.day + 1, "REGISTRY")


class FakeModel:
    def __init__(self, home_goals, away_goals, home_teams, away_teams, weights):
        self.weights = weights
        self.teams = set(home_teams) | set(away_teams)

    def fit(self):
        return None

    def predict(self, home, away):
        return SimpleNamespace(home_win=0.5, draw=0.25, away_win=0.25)


def test_fit_strictly_excludes_same_day_and_anchors_weights_at_prediction_cutoff(monkeypatch):
    cutoff = date(2024, 1, 1)
    train = [_match(cutoff - timedelta(days=day), hg=day % 3, ag=(day + 1) % 2) for day in range(1, 62)]
    same_day = _match(cutoff, hg=99, ag=0)
    seen = {}

    def weights(dates, xi, base_date):
        seen["dates"] = list(dates)
        seen["base_date"] = base_date
        return [1.0] * len(dates)

    predictions, audit = _fit_predict(train + [same_day], [same_day], cutoff, 0.0018,
                                      model_factory=FakeModel, weights_func=weights)
    assert audit["fit_status"] == "OK"
    assert max(seen["dates"]) < cutoff
    assert seen["base_date"] == cutoff
    assert same_day.row_key in predictions
    assert audit["max_train_date"] < cutoff.isoformat()


def test_roi_excludes_partial_or_invalid_market_price_vectors():
    rows = [
        {"raw_probs": [0.8, 0.1, 0.1], "market_odds": [2.0, 3.0, 4.0], "outcome_idx": 0},
        {"raw_probs": [0.8, 0.1, 0.1], "market_odds": [None, 3.0, 4.0], "outcome_idx": 0},
        {"raw_probs": [0.8, 0.1, 0.1], "market_odds": [float("nan"), 3.0, 4.0], "outcome_idx": 0},
    ]
    score = _score_decisions(rows, "raw_probs")
    assert score["candidate_unique_games"] == 3
    assert score["decisions"] == 1
    assert score["excluded_incomplete_or_invalid_prices"] == 2
    assert score["roi_pct"] == 100.0
    assert "all three executable B365 prices" in score["cohort"]


def test_paired_roi_rule_bets_the_top_probability_outcome_for_each_source():
    score = _score_decisions(
        [{"model_probs": [0.5, 0.3, 0.2], "market_odds": [1.2, 5.0, 5.0], "outcome_idx": 0}],
        "model_probs", all_match_top_probability=True,
    )
    assert score["decisions"] == 1
    assert score["net_units"] == 0.2
    assert score["minimum_model_ev"] is None
    assert "top-probability" in score["selection_rule"]


def test_paired_block_bootstrap_is_deterministic_and_reports_production_scope():
    from core.model_validation import PRODUCTION_VALIDATION_SCOPE
    rows = []
    for month in ("2024-01", "2024-02", "2024-03"):
        rows.append({"date": f"{month}-01", "raw": [0.7, 0.2, 0.1],
                     "market_normalized_hda_probs": [0.5, 0.3, 0.2],
                     "market_odds": [2.0, 3.0, 4.0], "outcome_idx": 0})
        rows.append({"date": f"{month}-12", "raw": [0.2, 0.3, 0.5],
                     "market_normalized_hda_probs": [0.5, 0.3, 0.2],
                     "market_odds": [2.0, 3.0, 4.0], "outcome_idx": 2})
    first = _paired_block_bootstrap(rows, {"raw_model": "raw"}, replicates=30, seed=9)
    second = _paired_block_bootstrap(rows, {"raw_model": "raw"}, replicates=30, seed=9)
    assert first == second
    assert first["status"] == "COMPLETED"
    assert first["block_count"] == 3
    assert first["comparisons"]["raw_model"]["brier"]["valid_replicates"] == 30
    assert "MLB" in PRODUCTION_VALIDATION_SCOPE["unsupported_production_sports"]
    assert "eng.1" in PRODUCTION_VALIDATION_SCOPE["validated_external_leagues"]


def test_run_validation_freezes_xi_after_validation_and_writes_auditable_outputs(tmp_path, monkeypatch):
    import core.model_validation as module
    monkeypatch.setattr(module, "MIN_TRAIN_MATCHES", 2)
    monkeypatch.setattr(module, "MIN_TEAM_APPEARANCES", 1)
    source_dir = _write_source_set(tmp_path / "sources", _seasons_for_validation())
    cutoff_calls = []

    def weights(dates, xi, base_date):
        assert max(dates) < base_date
        cutoff_calls.append((xi, base_date, max(dates)))
        return [1.0] * len(dates)

    summary = run_validation(
        source_dir, tmp_path / "output", "eng.1", model_factory=FakeModel,
        weights_func=weights, forward_snapshot_path=tmp_path / "no-live-snapshots.jsonl",
    )
    assert summary["status"] == "COMPLETED_HISTORICAL_VALIDATION"
    assert summary["protocol"]["selected_xi_from_validation_only"] in summary["protocol"]["xi_candidates"]
    assert summary["protocol"]["holdout_used_for_parameter_selection"] is False
    assert all(max_date < cutoff for _, cutoff, max_date in cutoff_calls)
    assert summary["splits"]["locked_holdout"]["same_cohort_n_unique_games"] > 0
    assert summary["forward_product_validation"]["status"] == "NOT_YET_VALIDATED"
    prediction_rows = [json.loads(line) for line in (tmp_path / "output" / "predictions.jsonl").read_text().splitlines()]
    assert prediction_rows
    assert all(row["max_train_date"] is None or row["max_train_date"] < row["prediction_cutoff_exclusive"]
               for row in prediction_rows)
    assert (tmp_path / "output" / "predictions.csv").exists()
    assert (tmp_path / "output" / "report.md").exists()


class MockResponse:
    def __init__(self, body, status=200):
        self.content = body
        self.status_code = status
        self.headers = {"Content-Type": "text/csv"}


class MockSession:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        body, status = self.payloads.get(url, (b"", 404))
        return MockResponse(body, status)


def test_fetch_is_content_addressed_and_records_source_hashes_and_http_status(tmp_path):
    from scripts.fetch_validation_data import SOURCE_ROOT
    csv_bytes = b"Date,HomeTeam,AwayTeam,FTHG,FTAG,B365H,B365D,B365A\r\n"
    notes = b"notes\n"
    session = MockSession({f"{SOURCE_ROOT}/mmz4281/2324/E0.csv": (csv_bytes, 200),
                           f"{SOURCE_ROOT}/notes.txt": (notes, 200)})
    manifest = fetch_validation_sources(tmp_path / "sources", ("eng.1",), ("2324",), session=session)
    assert len(session.calls) == 2
    assert all(item["http_status"] == 200 and len(item["sha256"]) == 64 for item in manifest["downloads"])
    stored = [item["stored_filename"] for item in manifest["downloads"]]
    assert all((tmp_path / "sources" / name).exists() for name in stored)
    assert any(name.startswith("notes_") and name.endswith(".txt") for name in stored)
    assert len(list((tmp_path / "sources").glob("manifest_*.json"))) == 1


def test_fetch_failed_http_writes_failure_manifest_and_does_not_claim_success(tmp_path):
    from scripts.fetch_validation_data import SOURCE_ROOT
    session = MockSession({f"{SOURCE_ROOT}/mmz4281/2324/E0.csv": (b"not found", 404),
                           f"{SOURCE_ROOT}/notes.txt": (b"notes", 200)})
    with pytest.raises(RuntimeError, match="failed"):
        fetch_validation_sources(tmp_path / "sources", ("eng.1",), ("2324",), session=session)
    manifest = json.loads(next((tmp_path / "sources").glob("manifest_*.json")).read_text())
    failed = next(row for row in manifest["downloads"] if row["http_status"] == 404)
    assert failed["error"]
