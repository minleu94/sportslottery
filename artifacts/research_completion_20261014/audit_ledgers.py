"""Read-only current/legacy ledger and model-data readiness audit."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.experiment_identity import get_current_experiment_identity
from core.performance_metrics import PerformanceMetricsEngine
from core.research_paths import research_paths
from core.snapshot_logger import compute_prediction_payload_hash
from core.strategy_version import get_strategy_metadata
from integrations.models.external.penaltyblog_dixon_coles import PenaltyblogDixonColesAdapter
from scripts.validate_parlay_forward import run

folder = Path(__file__).resolve().parent
paths = research_paths()
identity = get_current_experiment_identity()

def read(path):
    raw = path.read_bytes() if path.exists() else b""
    rows, bad = [], 0
    for line in raw.splitlines():
        try:
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("not an object")
            rows.append(item)
        except (ValueError, UnicodeDecodeError):
            bad += 1
    return rows, {"path":str(path),"exists":path.exists(),"sha256":hashlib.sha256(raw).hexdigest(),
                  "records":len(rows),"malformed":bad}

rows, info = read(paths["snapshots"])
cohort = PerformanceMetricsEngine.forward_cohort(rows, identity["experiment_id"])
info.update(valid_prediction_payloads=sum(
    row.get("prediction_payload_hash") == compute_prediction_payload_hash(row) for row in rows),
    current_forward_cohort_audit=cohort["audit"],
    current_qualified_settled_count=len(cohort["observations"]))
legacy_rows, legacy_info = read(ROOT / "data/historical/prediction_snapshots.jsonl")
info["legacy_reference"] = legacy_info
run(paths["parlays"], folder / "parlay-current-audit.json")
run(ROOT / "data/historical/parlay_snapshots.jsonl", folder / "parlay-legacy-audit.json")

adapter = PenaltyblogDixonColesAdapter(str(paths["root"] / "cache/models/penaltyblog_dixon_coles"))
model_readiness = {}
cutoff = datetime.now(timezone.utc).date().isoformat()
for league in ("eng.1", "esp.1"):
    model, provenance = adapter._get_or_fit_model(league, pred_date=cutoff)
    model_readiness[league] = {"fit_succeeded":model is not None,
                               "provenance":asdict(provenance) if provenance else None,
                               "scope":"training-data readiness only; no fabricated event or acceptance"}
report = {"generated_at":datetime.now(timezone.utc).isoformat(),
          "code_hash":get_strategy_metadata()["code_hash"],
          "experiment_identity":identity,"single_ledger":info,
          "soccer_training_data_readiness":model_readiness}
(folder / "ledger-audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
print(json.dumps({"payloads_verified":info["valid_prediction_payloads"],
                  "current_settled_n":len(cohort["observations"]),
                  "model_fits":{key:value["fit_succeeded"] for key,value in model_readiness.items()}}))
