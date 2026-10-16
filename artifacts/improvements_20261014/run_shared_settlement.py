from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from core.research_pipeline import ResearchPipeline,_write_json_atomic
from core.strategy_version import get_core_code_hash
folder=Path(__file__).resolve().parent/'shared_settlement';folder.mkdir(exist_ok=True)
pipeline=ResearchPipeline()
before=get_core_code_hash(Path.cwd())
with pipeline._Lock(pipeline.data_root/'locks/pipeline.lock'):
    pipeline._components()
    result=pipeline._stage_settlement(folder)
    report=pipeline._stage_report(folder)
record={'code_hash_before':before,'code_hash_after':get_core_code_hash(Path.cwd()),'settlement':result,'report':report}
_write_json_atomic(folder/'verification.json',record)
print(json.dumps({'settled':result['settled_snapshots'],'coverage':{k:{'snapshots':v.get('snapshots'),'matched':v.get('matched_snapshots'),'settled':v.get('settled_snapshots'),'status':v.get('status')} for k,v in result['coverage'].items()},'report':report},ensure_ascii=True))
