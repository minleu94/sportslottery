"""Capture final operational evidence without changing predictions or wallet."""
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.research_paths import research_paths
from core.snapshot_logger import compute_prediction_payload_hash
from core.experiment_identity import get_current_experiment_identity
from core.strategy_version import get_core_code_hash
from core.research_health import build_research_health
from core.clv_reporting import load_current_clv_report, read_jsonl
from core.recommendation_replay import load_current_recommendation_replay, load_current_parlay_recommendations

folder = Path(__file__).resolve().parent
paths = research_paths(folder / 'runtime_final2')
identity = get_current_experiment_identity()
snapshots = read_jsonl(paths['snapshots'])
invalid = [r.get('snapshot_id') for r in snapshots if
           r.get('prediction_payload_hash') != compute_prediction_payload_hash(r)]
assert not invalid, invalid
health = build_research_health(paths['root'])
clv = load_current_clv_report(root=paths['root'])
replay = load_current_recommendation_replay(root=paths['root'])
parlays = load_current_parlay_recommendations(root=paths['root'])
report = json.loads((paths['reports'] / 'weekly_2026-10-14.json').read_text(encoding='utf-8'))
assert report['experiment_identity']['experiment_id'] == identity['experiment_id']
assert health['pipeline']['status'] == 'COMPLETE'
assert len(health['sources']) == 8
run_path = max(paths['root'].glob('runs/*/run.json'), key=lambda p: json.loads(p.read_text(encoding='utf-8'))['started_at'])
run = json.loads(run_path.read_text(encoding='utf-8'))
assert run['status'] == 'COMPLETE'
assert run['experiment_identity']['experiment_id'] == identity['experiment_id']
assert all(s['status'] == 'SUCCEEDED' for s in run['stages'].values())
search_path = run_path.parent / 'data/parlay_search_diagnostics.json'
search = json.loads(search_path.read_text(encoding='utf-8'))
assert all(d['max_matches_pool_applied'] is False for d in search.values())
assert all(d['search_complete'] or d['budget_exhausted'] for d in search.values())
audit = {
    'observed_at_utc': datetime.now(timezone.utc).isoformat(),
    'source_hash': get_core_code_hash(ROOT), 'experiment_id': identity['experiment_id'],
    'pipeline_run': run, 'pipeline_run_path': str(run_path),
    'pipeline_run_sha256': hashlib.sha256(run_path.read_bytes()).hexdigest(),
    'search_diagnostics': search, 'health': health,
    'prediction_ledger': {'records': len(snapshots), 'invalid_payload_hashes': invalid,
                          'sha256': hashlib.sha256(paths['snapshots'].read_bytes()).hexdigest()},
    'clv': clv, 'single_replay_count': len(replay['recommendations']),
    'parlay_replay_count': parlays['candidate_count'],
    'parlay_replay_integrity_failures': [p['candidate_id'] for p in parlays['recommendations'] if not p['integrity_valid']],
    'parlay_replay_math_failures': [p['candidate_id'] for p in parlays['recommendations'] if not p['math_consistent']],
    'model_cohort_n': report['single_leg']['paired_probability_cohort_n'],
    'raw_settled_n': report['single_leg']['settled_count'],
}
shared = research_paths()
shared_rows = read_jsonl(shared['snapshots'])
assert len(shared_rows) == len([s for s in shared['snapshots'].read_text(encoding='utf-8').splitlines() if s.strip()])
shared_invalid = [r.get('snapshot_id') for r in shared_rows if r.get('prediction_payload_hash') != compute_prediction_payload_hash(r)]
assert not shared_invalid, shared_invalid
audit['shared_ledger'] = {'records': len(shared_rows), 'invalid_payload_hashes': shared_invalid,
                          'settled_records_all_versions': sum(r.get('is_settled') is True for r in shared_rows),
                          'health': build_research_health()}
assert not audit['parlay_replay_integrity_failures']
assert not audit['parlay_replay_math_failures']
(folder / 'completion-checks.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k:audit[k] for k in ('source_hash','experiment_id','single_replay_count','parlay_replay_count','model_cohort_n','raw_settled_n')}))
