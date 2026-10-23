import json
from datetime import datetime,timezone
from pathlib import Path
from core.research_health import build_research_health


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding="utf-8")


def test_health_exposes_failed_stage_and_stale_sources_without_writes(tmp_path):
    root=tmp_path/"research"
    write(root/"runs/20261014T0100Z/run.json",{"status":"COMPLETE","started_at":"2026-10-14T01:00:00Z","completed_at":"2026-10-14T01:02:00Z"})
    write(root/"runs/20261014T0200Z/run.json",{"status":"FAILED","started_at":"2026-10-14T02:00:00Z","error":"Final score missing","stages":{"model_update":{"status":"FAILED","attempts":3,"error":"Final score missing"}}})
    path=root/"source_health/playsport.jsonl";path.parent.mkdir()
    path.write_text(json.dumps({"alliance_id":"1","source_status":"LIVE","observed_at":"2026-10-14T01:01:00Z","recorded_at":"2026-10-14T01:01:00Z"})+"\ninvalid\n",encoding="utf-8")
    before={str(p):p.read_bytes() for p in root.rglob("*") if p.is_file()}
    health=build_research_health(root,now=datetime(2026,10,14,2,5,tzinfo=timezone.utc))
    assert health["pipeline"]["status"]=="FAILED"
    assert health["pipeline"]["overdue"]
    assert health["sources"][0]["stale"]
    assert health["malformed_source_records"]==1
    assert health["scheduler"] is None
    assert before=={str(p):p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_health_scheduler_observation_and_model_watermark_are_independent(tmp_path):
    root=tmp_path/"research"
    write(root/"operations/task_status.json",{"enabled":True,"state":"Ready","last_task_result":0,"observed_at_utc":"2026-10-14T01:00:00Z"})
    write(root/"model_state/live_mlb_elo.json",{"processed_game_pks":["1","2"],"data_as_of":"2025-03-29T02:10:00Z","source":"MLB Stats API"})
    health=build_research_health(root,now=datetime(2026,10,14,2,5,tzinfo=timezone.utc))
    assert health["scheduler"]["observation_stale"]
    assert health["pipeline"]["status"]=="NO_OBSERVATION"
    assert health["models"][0]["processed_games"]==2
    assert health["models"][0]["days_behind"]>365


def test_health_excludes_future_run_receipts(tmp_path):
    root=tmp_path/"research"
    write(root/"runs/future/run.json",{"status":"COMPLETE","started_at":"2026-10-15T02:00:00Z","completed_at":"2026-10-15T02:01:00Z"})
    health=build_research_health(root,now=datetime(2026,10,14,2,5,tzinfo=timezone.utc))
    assert health["pipeline"]["status"]=="NO_OBSERVATION"
    assert health["pipeline"]["last_success_at"] is None
    assert health["read_errors"]


def test_league_connections_distinguish_result_support_and_model_configuration(tmp_path):
    root=tmp_path/"research"
    write(root/"runs/20261014T0200Z/run.json",{"status":"COMPLETE","started_at":"2026-10-14T02:00:00Z","completed_at":"2026-10-14T02:01:00Z"})
    write(root/"runs/20261014T0200Z/data/source_legs.json",[
        {"event_id":"e","canonical_event_id":"e","sport":"soccer","league":"MLS","market":"不讓分","selection":"主勝","side":"主", "taiwan_odds":2.0,
         "away_team":"Seattle Sounders FC","home_team":"LA Galaxy","start_time_utc":"2026-10-14T03:00:00Z","odds_scraped_at":"2026-10-14T02:00:00Z","odds_status":"FRESH"}])
    health=build_research_health(root,now=datetime(2026,10,14,2,5,tzinfo=timezone.utc))
    row=health["league_connections"][0]
    assert row["league"]=="MLS"
    assert row["ready_option_count"]==1
    assert row["result_source_supported"]
    assert row["configured_model_adapters"]==["espn_poisson_soccer"]
