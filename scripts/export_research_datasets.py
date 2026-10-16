#!/usr/bin/env python3
"""Export Clean Research Datasets for Forward Evaluation.

Generates:
- `data/research/single_leg_forward.csv`
- `data/research/parlay_forward.csv`
- `data/research/source_metrics.csv`

Usage:
  python scripts/export_research_datasets.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Fix console encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.research_dataset_exporter import ResearchDatasetExporter


def main():
    print("=" * 65)
    print("📁 匯出前瞻評估研究資料集 (RESEARCH DATASET EXPORT)")
    print("=" * 65)
    exporter = ResearchDatasetExporter()
    res = exporter.export_all()
    for name, p in res.items():
        print(f"  ✓ {name:<20} ➔ {p}")
    print("\n資料集已完成匯出至 data/research/。所有紀錄均附帶原 Snapshot ID 以供回溯審查。")


if __name__ == "__main__":
    main()
