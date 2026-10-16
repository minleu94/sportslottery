from pathlib import Path
import json,sys
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.research_pipeline import ResearchPipeline
from core.strategy_version import get_core_code_hash
before=get_core_code_hash(ROOT)
result=ResearchPipeline().run()
receipt={"observed_at_utc":datetime.now(timezone.utc).isoformat(),"source_hash_before":before,"source_hash_after":get_core_code_hash(ROOT),"result":result}
Path(__file__).with_name("pipeline-current.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"status":result["status"],"run_window_id":result.get("run_window_id"),"error":result.get("error"),"stages":{k:v.get("status") for k,v in result.get("stages",{}).items()}},indent=2))
raise SystemExit(1 if result["status"]=="FAILED" else 0)
