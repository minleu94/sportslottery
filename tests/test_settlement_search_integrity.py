from datetime import datetime, timedelta, timezone
import json

from core.parlay_engine import ParlayEngine
from core.settlement_engine import SettlementEngine
from core.snapshot_logger import AuditFailureError, PredictionSnapshotLogger, check_cutoff_integrity
from core.identity.team_alias import GLOBAL_TEAM_REGISTRY
from integrations.common.models import PredictionSignal, TaiwanLeg


def _leg(event_id, quality="HIGH", *, canonical=None, start=None, odds_time=None, odds=2.0):
    return TaiwanLeg(
        event_id=event_id,
        canonical_event_id=canonical,
        sport="baseball",
        league="MLB",
        market="不讓分",
        selection="客勝",
        taiwan_odds=odds,
        start_time_utc=start,
        odds_scraped_at=odds_time,
        odds_status="LIVE" if odds_time else "UNKNOWN",
        away_team="芝加哥小熊",
        home_team="辛辛那提紅人",
        side="客",
        evidence_quality=quality,
        signal_evidence={"evidence_quality": quality, "non_market_supports": 1},
    )


def test_false_is_lost_and_void_is_not_rewritten_as_loss(tmp_path):
    logger = PredictionSnapshotLogger(tmp_path / "snapshots.jsonl")
    logger.log_path.write_text(
        "\n".join(json.dumps({"snapshot_id": sid, "prediction_payload_hash": "", "market_implied_prob": .5,
                              "taiwan_odds": 2.0, "model_probability": .6, "is_settled": False})
                  for sid in ("lost", "void", "conflict")) + "\n", encoding="utf-8")

    lost = logger.settle_prediction("lost", actual_outcome=False)
    void = logger.settle_prediction("void", actual_outcome=False, settlement_status="VOID")
    conflict = logger.settle_prediction("conflict", actual_outcome=False, settlement_status="WON")

    assert lost["settlement_status"] == "LOST" and lost["actual_outcome"] is False
    assert void["settlement_status"] == "VOID" and void["actual_outcome"] is None
    assert void["brier_score"] is None and void["log_loss"] is None
    assert conflict["settlement_status"] == "UNRESOLVED" and not conflict["is_settled"]


def test_missing_or_unknown_times_are_excluded_from_forward_validation():
    eligible, reason = check_cutoff_integrity("2026-10-01T12:00:00Z", None, "2026-10-01T11:00:00Z")
    assert not eligible and reason == "START_TIME_UNKNOWN"
    eligible, reason = check_cutoff_integrity(
        "2026-10-01T12:00:00Z", "2026-10-01T15:00:00Z", None, "DATETIME"
    )
    assert not eligible and reason == "ODDS_TIME_UNKNOWN"
    eligible, reason = check_cutoff_integrity(
        "2026-10-01T12:00:00Z", "2026-10-01T15:00:00Z", "2026-10-01T11:00:00Z", "UNKNOWN"
    )
    assert not eligible and reason == "EXPERT_TIME_UNKNOWN"


def _snapshot_model_leg(*, data_as_of, timestamp=None):
    now = datetime.now(timezone.utc)
    start = (now + timedelta(hours=2)).isoformat()
    leg = _leg("model-evidence", start=start, odds_time=now.isoformat())
    leg.signals = [PredictionSignal(
        source_id="model-1", source_name="Model 1", source_type="MODEL",
        source_category="MODEL", independence_group="GROUP_1", event_id=leg.event_id,
        market=leg.market, selection=leg.selection, probability=.62,
        timestamp=timestamp or now.isoformat(), data_as_of=data_as_of,
        freshness_status="FRESH", metadata={"initialized": True},
    )]
    leg.signal_evidence.update({
        "probability_status": "UNVALIDATED_MODEL_ESTIMATE", "consensus_probability": .62,
        "model_probability_raw": .62, "model_probability_calibrated": .62,
        "model_fusion_groups": ["GROUP_1"], "excluded_model_ids": [],
        "model_provenances": [leg.signals[0].to_dict()],
        "publication_time_precision": "NOT_APPLICABLE",
    })
    leg.consensus_probability = .62
    return leg


def test_missing_model_data_asof_does_not_use_signal_timestamp_or_become_eligible(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    leg = _snapshot_model_leg(data_as_of=None, timestamp=now)
    record = PredictionSnapshotLogger(tmp_path / "unknown-model-time.jsonl").log_snapshot(leg)

    assert record["model_as_of"] is None
    assert record["forward_validation_eligible"] is False
    assert record["exclusion_reason"] == "MODEL_TIME_UNKNOWN"


def test_snapshot_hash_rejects_forward_eligibility_flip(tmp_path):
    path = tmp_path / "eligibility-hash.jsonl"
    logger = PredictionSnapshotLogger(path)
    record = logger.log_snapshot(_snapshot_model_leg(data_as_of=datetime.now(timezone.utc).isoformat()))
    assert record["forward_validation_eligible"] is True

    stored = logger.get_all_snapshots()[0]
    stored["forward_validation_eligible"] = False
    path.write_text(json.dumps(stored) + "\n", encoding="utf-8")
    try:
        logger.settle_prediction(record["snapshot_id"], actual_outcome=True, settlement_status="WON")
        assert False, "eligibility changes must be rejected by payload hash verification"
    except AuditFailureError:
        pass


def test_strict_never_falls_back_and_low_quality_never_enters_high_consensus():
    now = datetime.now(timezone.utc)
    event_start = (now + timedelta(hours=2)).isoformat()
    odds_time = now.isoformat()
    legs = [_leg("a", "LOW", start=event_start, odds_time=odds_time),
            _leg("b", "LOW", start=event_start, odds_time=odds_time)]
    engine = ParlayEngine()

    strict = engine.search_parlays(legs, min_odds=1.05, max_odds=10, min_legs=2, max_legs=2, signal_filter="strict")
    normal = engine.search_parlays(legs, min_odds=1.05, max_odds=10, min_legs=2, max_legs=2, signal_filter="normal")

    assert strict == {"high_consensus": [], "aggressive": [], "moonshot": []}
    assert normal["aggressive"]
    assert normal["high_consensus"] == []


def test_readiness_rejects_started_and_stale_or_unknown_odds_times():
    now = datetime.now(timezone.utc)
    started = _leg("started", start=(now - timedelta(minutes=1)).isoformat(), odds_time=now.isoformat())
    stale = _leg("stale", start=(now + timedelta(hours=1)).isoformat(), odds_time=(now - timedelta(hours=1)).isoformat())
    unknown = _leg("unknown", start=(now + timedelta(hours=1)).isoformat())
    results = ParlayEngine().search_parlays(
        [started, stale, unknown, _leg("other", start=(now + timedelta(hours=2)).isoformat(), odds_time=now.isoformat())],
        min_odds=1.05, max_odds=10, min_legs=2, max_legs=2,
    )
    assert results == {"high_consensus": [], "aggressive": [], "moonshot": []}


def test_canonical_event_deduplicates_local_ids_and_doubleheaders_match_by_utc_time():
    now = datetime.now(timezone.utc)
    future = (now + timedelta(hours=4)).isoformat()
    odds_time = now.isoformat()
    duplicate_legs = [
        _leg("local-1", canonical="MLB_20261012_CHC_CIN_200000", start=future, odds_time=odds_time),
        _leg("local-2", canonical="MLB_20261012_CHC_CIN_200000", start=future, odds_time=odds_time),
        _leg("other-event", canonical="MLB_20261012_CHC_CIN_230000", start=(now + timedelta(hours=7)).isoformat(), odds_time=odds_time),
    ]
    result = ParlayEngine().search_parlays(duplicate_legs, min_odds=1.05, max_odds=10, min_legs=2, max_legs=2)
    combos = result["high_consensus"] + result["aggressive"]
    assert combos
    assert all(len({leg["canonical_event_id"] for leg in combo["legs"]}) == len(combo["legs"]) for combo in combos)

    engine = object.__new__(SettlementEngine)
    game1 = {"game_pk": "101", "away_team": "Chicago Cubs", "home_team": "Cincinnati Reds",
             "start_time_utc": "2024-09-10T20:00:00Z", "away_score": 2, "home_score": 1}
    game2 = {"game_pk": "102", "away_team": "Chicago Cubs", "home_team": "Cincinnati Reds",
             "start_time_utc": "2024-09-10T23:00:00Z", "away_score": 3, "home_score": 4}
    games = {"101": game1, "102": game2}
    first = {"event_start": "2024-09-10T20:05:00+00:00", "away_team": "小熊", "home_team": "紅人",
             "sport": "baseball", "league": "MLB"}
    second = {"event_start": "2024-09-10T23:05:00+00:00", "away_team": "Chicago Cubs", "home_team": "Cincinnati Reds",
              "sport": "baseball", "league": "MLB"}
    assert SettlementEngine.match_mlb_game(first, games) is game1
    assert SettlementEngine.match_mlb_game(second, games) is game2
    assert GLOBAL_TEAM_REGISTRY.resolve("小熊", sport="baseball", league="MLB").canonical_id == "MLB_CHC"


def test_fetch_retains_separate_gamepk_entries_for_doubleheader():
    class Response:
        status_code = 200
        def json(self):
            games = []
            for game_pk, game_time, away_score, home_score in (
                (101, "2024-09-10T20:00:00Z", 2, 1), (102, "2024-09-10T23:00:00Z", 3, 4)
            ):
                games.append({
                    "gamePk": game_pk, "gameDate": game_time,
                    "status": {"abstractGameState": "Final", "detailedState": "Final"},
                    "teams": {
                        "away": {"team": {"name": "Chicago Cubs"}, "score": away_score},
                        "home": {"team": {"name": "Cincinnati Reds"}, "score": home_score},
                    },
                })
            return {"dates": [{"date": "2024-09-10", "games": games}]}
    class Session:
        def get(self, *args, **kwargs): return Response()

    engine = object.__new__(SettlementEngine)
    engine.session = Session()
    fetched = engine.fetch_mlb_completed_games("2024-09-10")
    assert set(fetched) == {"101", "102"}
    assert fetched["101"]["game_pk"] != fetched["102"]["game_pk"]


def test_match_requires_both_teams_and_event_time():
    games = {"101": {"game_pk": "101", "away_team": "Chicago Cubs", "home_team": "Cincinnati Reds",
                     "start_time_utc": "2024-09-10T20:00:00Z"}}
    incomplete = {"away_team": "小熊", "sport": "baseball", "league": "MLB"}
    mismatch = {"event_start": "2024-09-10T20:00:00Z", "away_team": "小熊", "home_team": "白襪",
                "sport": "baseball", "league": "MLB"}
    assert SettlementEngine.match_mlb_game(incomplete, games) is None
    assert SettlementEngine.match_mlb_game(mismatch, games) is None


def test_raw_match_normalization_preserves_option_fields_without_fake_defaults():
    now = datetime.now(timezone.utc)
    start = (now + timedelta(hours=2)).isoformat()
    option_signal = {
        "source_id": "model-x", "source_name": "Model X", "source_type": "MODEL",
        "event_id": "evt-7", "market": "讓分", "selection": "客勝", "probability": .61,
        "source_category": "OPEN_SOURCE_ENGINE", "independence_group": "MODEL_X", "freshness_status": "FRESH",
    }
    match = {
        "match_id": "evt-7", "sport": "baseball", "league": "MLB", "canonical_event_id": "MLB_20261012_CHC_CIN_190000",
        "away_team": {"canonical_id": "MLB_CHC", "name": "芝加哥小熊"},
        "home_team": {"canonical_id": "MLB_CIN", "name": "辛辛那提紅人"},
        "start_time_utc": start, "odds_scraped_at": now.isoformat(), "odds_status": "LIVE",
        "options": [{
            "market_type": "讓分", "selection": "客勝", "side": "客", "line": "-1.5", "odds": "1.95",
            "eligible_for_parlay": False, "signals": [option_signal],
            "market_evidence": {"market_complete": True, "market_outcome_odds": {"客": 1.95, "主": 1.91}},
        }],
    }
    normalized = ParlayEngine._normalize_option(match["options"][0], match)
    assert normalized.event_id == "evt-7" and normalized.sport == "baseball"
    assert normalized.away_team == "芝加哥小熊" and normalized.home_team == "辛辛那提紅人"
    assert normalized.canonical_event_id == match["canonical_event_id"]
    assert normalized.line == "-1.5" and normalized.eligible_for_parlay is False
    assert normalized.signals[0].source_id == "model-x"
    assert normalized.signal_evidence["market_complete"] is True
    assert normalized.signal_evidence["market_outcome_odds"]["客"] == 1.95
    assert "vote_count" not in normalized.signal_evidence
    assert ParlayEngine._normalize_option({"odds": 2.0}).event_id == ""
    assert ParlayEngine._normalize_option({"odds": 2.0}).sport == ""


def test_strict_requires_two_independent_support_groups_per_leg():
    now = datetime.now(timezone.utc)
    start, scraped = (now + timedelta(hours=2)).isoformat(), now.isoformat()
    legs = [
        _leg("a", "MED", canonical="A", start=start, odds_time=scraped),
        _leg("b", "MED", canonical="B", start=start, odds_time=scraped),
    ]
    for leg in legs:
        leg.signal_evidence = {"agreement": "MED", "supporting_groups": ["G1"], "non_market_supports": 1}
    engine = ParlayEngine()
    result = engine.search_parlays(legs, min_odds=1.05, max_odds=10, min_legs=2, max_legs=2, signal_filter="strict")
    assert result["high_consensus"] == [] and result["aggressive"] == []
    for leg in legs:
        leg.signal_evidence["supporting_groups"] = ["G1", "G2"]
    result = engine.search_parlays(legs, min_odds=1.05, max_odds=10, min_legs=2, max_legs=2, signal_filter="strict")
    assert result["high_consensus"]


def test_invalid_legs_cannot_displace_ready_search_results():
    now = datetime.now(timezone.utc)
    ready_a = _leg("a", "MED", canonical="A", start=(now + timedelta(hours=2)).isoformat(), odds_time=now.isoformat())
    ready_b = _leg("b", "MED", canonical="B", start=(now + timedelta(hours=3)).isoformat(), odds_time=now.isoformat())
    invalid = [_leg(f"bad-{i}", "HIGH", canonical=f"BAD{i}", start=(now - timedelta(minutes=1)).isoformat(), odds_time=now.isoformat()) for i in range(16)]
    result = ParlayEngine().search_parlays([*invalid, ready_a, ready_b], min_odds=1.05, max_odds=10, min_legs=2, max_legs=2)
    candidates = result["high_consensus"] + result["aggressive"] + result["moonshot"]
    assert candidates
    assert all(candidate["is_ready"] for candidate in candidates)
    assert {leg["canonical_event_id"] for leg in candidates[0]["legs"]} == {"A", "B"}


def test_bounded_topk_matches_bruteforce_full_search_ranking():
    now = datetime.now(timezone.utc)
    start, scraped = (now + timedelta(hours=2)).isoformat(), now.isoformat()
    legs = []
    for event_index in range(5):
        for option_index, odds in enumerate((1.35 + event_index * .04, 1.55 + event_index * .05)):
            leg = _leg(f"e{event_index}", "HIGH" if (event_index + option_index) % 2 else "MED",
                       canonical=f"E{event_index}", start=start, odds_time=scraped, odds=odds)
            leg.selection = f"side-{option_index}"
            leg.signal_evidence.update({"agreement": leg.evidence_quality,
                                        "supporting_groups": ["G1", "G2"],
                                        "non_market_supports": event_index + option_index,
                                        "consensus_probability": .42 + .03 * event_index + .01 * option_index})
            legs.append(leg)

    class Guard:
        def evaluate_parlay(self, selected, total_odds):
            from types import SimpleNamespace
            joint = 1.0
            for leg in selected:
                joint *= leg.signal_evidence["consensus_probability"]
            return SimpleNamespace(joint_probability=joint, naive_joint_probability=joint,
                                   parlay_expected_value=joint * total_odds - 1,
                                   parlay_ev_pct=(joint * total_odds - 1) * 100,
                                   correlation_penalty=0.0, risk_grade="LOW", risk_factors=[])
    results = ParlayEngine(correlation_guard=Guard()).search_parlays(
        legs, min_odds=1.5, max_odds=4.0, min_legs=2, max_legs=2, max_matches_pool=10,
    )

    # Brute force all 40 event/option pairs and apply the public rank tuple.
    from itertools import combinations, product
    grouped = {}
    for leg in legs:
        grouped.setdefault(leg.canonical_event_id, []).append(leg)
    full = []
    score = {"HIGH": 3, "MED": 2}
    for event_ids in combinations(list(grouped), 2):
        for selected in product(*(grouped[eid] for eid in event_ids)):
            total = selected[0].taiwan_odds * selected[1].taiwan_odds
            if not 1.5 <= total <= 4.0:
                continue
            min_score = min(score[leg.evidence_quality] for leg in selected)
            avg_score = sum(score[leg.evidence_quality] for leg in selected) / 2
            support = sum(leg.signal_evidence["non_market_supports"] for leg in selected)
            joint = selected[0].signal_evidence["consensus_probability"] * selected[1].signal_evidence["consensus_probability"]
            target_distance = abs(total - 2.75)
            rank = (min_score, round(joint * total - 1, 4), round(avg_score, 2), support,
                    -round(target_distance, 2), round(total, 2))
            full.append(rank)
    expected = sorted(full, reverse=True)[:12]
    actual = [(
        row["min_evidence_score"], row["parlay_expected_value"], row["avg_evidence_score"],
        row["total_independent_sources"], -row["odds_distance"], row["total_odds"],
    ) for row in results["high_consensus"]]
    assert actual == expected


def test_settlement_script_fetches_each_snapshot_historical_date():
    from scripts.settle_results import settle_snapshot_results

    historical_date = "2024-09-10"
    game = {"game_pk": "101", "away_team": "Chicago Cubs", "home_team": "Cincinnati Reds",
            "start_time_utc": f"{historical_date}T20:00:00Z", "away_score": 2, "home_score": 1,
            "final_score": "2:1", "game_status": "Final"}
    class FakeEngine:
        def __init__(self):
            self.fetched_dates = []
            self.settled = []
        def fetch_mlb_completed_games(self, target_date):
            self.fetched_dates.append(target_date)
            return {"101": game} if target_date == historical_date else {}
        match_mlb_game = staticmethod(SettlementEngine.match_mlb_game)
        evaluate_leg_settlement = SettlementEngine.evaluate_leg_settlement
        def settle_single_prediction_direct(self, **kwargs):
            self.settled.append(kwargs)

    engine = FakeEngine()
    snap = {"snapshot_id": "old-snapshot", "event_start": f"{historical_date}T20:00:00Z",
            "sport": "baseball", "league": "MLB", "away_team": "小熊", "home_team": "紅人",
            "market": "不讓分", "selection": "客勝", "side": "客", "is_settled": False}
    counts = settle_snapshot_results(engine, [snap])
    assert historical_date in engine.fetched_dates
    assert counts["settled"] == 1
    assert engine.settled[0]["settlement_status"] == "WON"


def test_settlement_script_uses_full_snapshot_identity_for_closing_odds():
    from scripts.settle_results import settle_snapshot_results

    game = {"game_pk": "101", "away_team": "Chicago Cubs", "home_team": "Cincinnati Reds",
            "start_time_utc": "2024-09-10T20:00:00Z", "away_score": 2, "home_score": 1,
            "final_score": "2:1", "game_status": "Final"}

    class Watcher:
        def __init__(self): self.args = None
        def get_closing_odds(self, **kwargs):
            self.args = kwargs
            return 2.2, "RECORDED"

    class FakeEngine:
        def __init__(self):
            self.odds_watcher = Watcher()
            self.settled = []
        def fetch_mlb_completed_games(self, _target_date): return {"101": game}
        match_mlb_game = staticmethod(SettlementEngine.match_mlb_game)
        evaluate_leg_settlement = SettlementEngine.evaluate_leg_settlement
        def settle_single_prediction_direct(self, **kwargs): self.settled.append(kwargs)

    engine = FakeEngine()
    snap = {"snapshot_id": "identified-snapshot", "event_id": "provider-101",
            "canonical_event_id": "MLB_20240910_CHC_CIN_200000", "event_start": "2024-09-10T20:00:00Z",
            "sport": "baseball", "league": "MLB", "away_team": "小熊", "home_team": "紅人",
            "market": "讓分", "selection": "客勝", "side": "客", "line": -1.5,
            "is_settled": False}
    settle_snapshot_results(engine, [snap])

    assert engine.odds_watcher.args == {
        "event_id": "provider-101", "market": "讓分", "selection": "客勝",
        "event_start_iso": "2024-09-10T20:00:00Z", "line": -1.5,
        "canonical_event_id": "MLB_20240910_CHC_CIN_200000", "sport": "baseball", "league": "MLB",
    }
    saved = engine.settled[0]
    assert saved["closing_odds"] == 2.2
    assert saved["closing_odds_source"] == "ODDS_WATCHER_LAST_PRESTART_OBSERVATION"
