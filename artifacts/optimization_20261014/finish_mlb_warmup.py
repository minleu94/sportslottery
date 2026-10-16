import json,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.research_pipeline import ResearchPipeline
from core.strategy_version import get_core_code_hash
pipeline=ResearchPipeline()
folder=Path(__file__).parent/'mlb_catchup'
folder.mkdir(exist_ok=True)
code=get_core_code_hash(ROOT)
rows=[]
with pipeline._Lock(pipeline.data_root/'locks/pipeline.lock'):
    for index in range(8):
        batch=folder/f"batch_{index+1}";batch.mkdir(exist_ok=True)
        result=pipeline._stage_model_update(batch)
        rows.append(result)
        (folder/'progress.json').write_text(json.dumps({"code_before":code,"code_after":get_core_code_hash(ROOT),"results":rows},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:result.get(k) for k in ['data_as_of','official_schedule_queried_through','official_ledger_complete_through_yesterday','pending_game_dates','held_final_count']}),flush=True)
        if result.get('official_ledger_complete_through_yesterday'):
            break
print('Bounded catchup finished',flush=True)
