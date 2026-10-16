from core.odds_watcher import OddsWatcher


def test_unknown_times_stale_prices_and_different_lines_never_become_closing(tmp_path):
    watcher = OddsWatcher(tmp_path / "odds.jsonl")
    start = "2026-10-13T02:00:00Z"
    watcher.record_observation("1", "baseball", "MLB", "大小", "大", 2, None, start, line=8.5)
    watcher.record_observation("1", "baseball", "MLB", "大小", "大", 1.9, "2026-10-13T01:00:00Z", start, line=8.5)
    watcher.record_observation("1", "baseball", "MLB", "大小", "大", 1.8, "2026-10-13T01:59:00Z", start, line=9.5)
    assert watcher.get_closing_odds("1", "大小", "大", start, line=8.5) == (None, "NOT_AVAILABLE")
    assert watcher.get_closing_odds("1", "大小", "大", None, line=9.5) == (None, "NOT_AVAILABLE")


def test_local_id_reuse_and_post_start_prices_do_not_contaminate_clv(tmp_path):
    watcher = OddsWatcher(tmp_path / "odds.jsonl")
    start = "2026-10-13T02:00:00Z"
    watcher.record_observation("1", "baseball", "MLB", "不讓分", "主", 1.8, "2026-10-12T01:59:00Z", "2026-10-12T02:00:00Z")
    watcher.record_observation("1", "baseball", "MLB", "不讓分", "主", 1.9, "2026-10-13T01:59:00Z", start)
    watcher.record_observation("1", "baseball", "MLB", "不讓分", "主", 2.1, "2026-10-13T02:01:00Z", start)
    assert watcher.get_closing_odds("1", "不讓分", "主", start) == (1.9, "RECORDED")
