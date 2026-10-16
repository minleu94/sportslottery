from scripts.settle_results import settle_snapshot_results


def test_future_events_are_deferred_without_fetching_or_settling():
    class Engine:
        def fetch_results(self, *args, **kwargs):
            raise AssertionError("Future events must not fetch/settle a result")
    report = settle_snapshot_results(Engine(), [{"snapshot_id": "future", "sport": "baseball", "league": "MLB",
                         "event_start": "2026-10-15T10:00:00+00:00"}], now="2026-10-14T10:00:00+00:00")
    assert report["settled"] == report["games"] == report["unresolved"] == 0
    assert report["deferred_snapshots"] == 1
    assert report["coverage"]["baseball/MLB"]["fetch_status"] == "NOT_ATTEMPTED"


def test_missing_metadata_is_counted_unresolved_under_matching_reason_scope():
    report = settle_snapshot_results(object(), [{"snapshot_id": "bad", "sport": "soccer"}])
    assert report["unresolved"] == 1
    coverage = report["coverage"]["soccer/unknown"]
    assert coverage["unmatched_reason_counts"] == {"MISSING_SPORT_OR_LEAGUE_METADATA": 1}
