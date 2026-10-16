"""One-time structural refactor: keep reporting outside predictive identity."""
import ast
from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "core/research_pipeline.py"
source = path.read_text(encoding="utf-8")
tree = ast.parse(source)
node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "ResearchPipeline")
names = {"_stage_report", "_binary_metrics", "_paired_cluster_ci", "_render_report"}
methods = [item for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in names]
assert len(methods) == len(names)
lines = source.splitlines(keepends=True)
blocks, spans = [], []
for item in methods:
    start = min([item.lineno, *(decorator.lineno for decorator in item.decorator_list)]) - 1
    spans.append((start, item.end_lineno))
    text = "".join(lines[start:item.end_lineno])
    if item.name == "_stage_report":
        text = text.replace("        now = self.clock()", "        from core.research_pipeline import _write_json_atomic, _read_json\n        now = self.clock()", 1)
        text = text.replace('parse_aware_time(row.get("observed_at"))',
                            'parse_aware_time(row.get("observed_at") or row.get("recorded_at") or row.get("attempted_at"))')
    blocks.append(text)
for start, end in sorted(spans, reverse=True):
    del lines[start:end]
source = "".join(lines).replace("class ResearchPipeline:", "class ResearchPipeline(ResearchReportMixin):", 1)
source = source.replace("from core.parlay_engine import ParlayEngine\n", "from core.parlay_engine import ParlayEngine\nfrom core.research_reporting import ResearchReportMixin\n", 1)
reporting = '''"""Read-only research scores and report files; no forecast or eligibility logic."""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.bet_validation import parse_aware_time
from core.experiment_identity import get_current_experiment_identity


class ResearchReportMixin:
'''+"\n\n".join(blocks)
ast.parse(source)
ast.parse(reporting)
(root / "core/research_reporting.py").write_text(reporting, encoding="utf-8")
path.write_text(source, encoding="utf-8")
