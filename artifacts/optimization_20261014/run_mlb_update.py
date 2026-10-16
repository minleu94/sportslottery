import sys,json
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.research_pipeline import ResearchPipeline
from core.strategy_version import get_core_code_hash
pipeline=ResearchPipeline()
folder=Path(__file__).parent/'mlb_update'
folder.mkdir(exist_ok=True)
before=get_core_code_hash(ROOT)
with pipeline._Lock(pipeline.data_root/'locks/pipeline.lock'):
    result=pipeline._stage_model_update(folder)
receipt={"observed_at_utc":datetime.now(timezone.utc).isoformat(),"code_before":before,"code_after":get_core_code_hash(ROOT),"result":result}
(folder/'verification.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:result.get(k) for k in ['updated_games','data_as_of','pending_game_dates','held_final_count','reschedule_reconciliation']},indent=2))
