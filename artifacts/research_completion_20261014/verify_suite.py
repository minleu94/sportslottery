"""Record a full offline suite against an unchanged source/configuration digest."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.strategy_version import get_core_code_hash

folder = Path(__file__).resolve().parent
command = [sys.executable, "-m", "pytest", "tests", "-q", "--color=no",
           "--basetemp", "artifacts/pytest-root-audited-final",
           "--junitxml", str(folder / "pytest-final.xml")]
before = get_core_code_hash(ROOT)
started = datetime.now(timezone.utc).isoformat()
with (folder / "pytest-final.txt").open("w", encoding="utf-8") as stream:
    result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
after = get_core_code_hash(ROOT)
record = {"command":command, "started_at":started,
          "completed_at":datetime.now(timezone.utc).isoformat(),
          "returncode":result.returncode, "source_hash_before":before,
          "source_hash_after":after, "source_unchanged":before == after}
(folder / "pytest-verification.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
print((folder / "pytest-final.txt").read_text(encoding="utf-8")[-3500:])
print(json.dumps(record, indent=2))
raise SystemExit(result.returncode or (0 if before == after else 2))
