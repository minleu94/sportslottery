#!/usr/bin/env python3
"""Launcher script for Taiwan Sports Lottery Crazy Dog System."""

import subprocess
import sys
import argparse
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent
APP_PATH = ROOT_DIR / "app.py"


def command_options(command, *option_names):
    parser = argparse.ArgumentParser(prog=f"python main.py {command}")
    for option in option_names:
        parser.add_argument(option)
    return parser.parse_args(sys.argv[2:])


def main():

    if len(sys.argv) > 1:
        cmd_arg = sys.argv[1].lower()
        if cmd_arg == "backup":
            options = command_options(cmd_arg, "--output")
            from scripts.workspace_backup import create_backup
            import json
            print(json.dumps(create_backup(ROOT_DIR, Path(options.output or ROOT_DIR / 'backups')), indent=2))
            return
        elif cmd_arg == "restore":
            options = command_options(cmd_arg, "--backup", "--destination")
            if not options.backup or not options.destination:
                raise SystemExit("restore requires --backup and --destination (a new directory)")
            from scripts.workspace_backup import restore_backup
            import json
            print(json.dumps(restore_backup(Path(options.backup), Path(options.destination)), indent=2))
            return
        elif cmd_arg == "snapshot":
            command_options(cmd_arg)
            from scripts.daily_snapshot import run_daily_snapshot
            run_daily_snapshot()
            return
        elif cmd_arg == "settle":
            options = command_options(cmd_arg, "--date")
            from scripts.settle_results import run_settlement
            run_settlement(options.date)
            return
        elif cmd_arg in ["settle-tickets", "auto-settle"]:
            from core.ticket_settlement import TicketSettlementEngine
            engine = TicketSettlementEngine()
            print("🤖 正在自動對獎並結算進行中注單...")
            report = engine.auto_settle_open_tickets(dry_run=False)
            print(f"檢查未結算注單: {report['total_open_checked']} 張")
            print(f"  • 中獎派彩: {report['settled_won']} 張 (NT$ {report['total_payout_credited']:,.2f} 已撥入保留儲備池)")
            print(f"  • 未中獎:   {report['settled_lost']} 張")
            print(f"  • 無效退盤: {report['settled_void']} 張")
            print(f"  • 尚在進行: {report['still_open']} 張")
            return
        elif cmd_arg in ["weekly-report", "report"]:
            options = command_options(cmd_arg, "--week")
            from scripts.generate_weekly_report import generate_weekly_report
            generate_weekly_report(options.week)
            return
        elif cmd_arg in ["watch-odds", "odds"]:
            command_options(cmd_arg)
            from scripts.odds_watcher import run_odds_watcher
            run_odds_watcher()
            return
        elif cmd_arg in ["export-research", "export"]:
            command_options(cmd_arg)
            from scripts.export_research_datasets import main as run_export
            run_export()
            return
        elif cmd_arg == "update-mlb-elo":
            from scripts.update_mlb_elo import main as run_update
            return run_update(sys.argv[2:])
        elif cmd_arg == "research-pipeline":
            parser = argparse.ArgumentParser(prog="python main.py research-pipeline")
            parser.add_argument("--config", default="config/research_pipeline.yaml")
            parser.add_argument("--data-root", default=None)
            parser.add_argument("--dry-run", action="store_true")
            parser.add_argument("--resume", action="store_true")
            options = parser.parse_args(sys.argv[2:])
            from core.research_pipeline import ResearchPipeline
            result = ResearchPipeline(config_path=options.config, data_root=options.data_root).run(
                dry_run=options.dry_run, resume=options.resume
            )
            import json
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result.get("status") == "FAILED":
                raise SystemExit(1)
            return
        elif cmd_arg in ["--help", "-h", "help"]:
            print("Usage: python main.py [snapshot | settle | settle-tickets | weekly-report | watch-odds | export-research | update-mlb-elo | research-pipeline | backup | restore]")
            print("MLB update: python main.py update-mlb-elo --start-date YYYY-MM-DD --end-date YYYY-MM-DD")
            print("Research pipeline: python main.py research-pipeline --dry-run [--data-root PATH]")
            return
        else:
            raise SystemExit(f"Unknown command: {cmd_arg}. Run python main.py --help.")


    print("=" * 60)
    print("🎯 啟動 台灣運彩「瘋狗流」賠率研究與注單記錄系統...")
    print("   每週限額 NT$ 200 | 模型為實驗估計 | 公開推牌需逐場核對")
    print("=" * 60)

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_PATH),
        "--server.address=0.0.0.0",
        "--server.port=8501",
        "--server.headless=false",
        "--browser.gatherUsageStats=false",
    ]

    try:
        # Start streamlit subprocess
        proc = subprocess.Popen(cmd)
        print("🚀 瀏覽器即將開啟 http://localhost:8501 ...")
        print("按 Ctrl+C 可停止系統。")
        proc.wait()
    except KeyboardInterrupt:
        print("\n系統已停止。祝您投注愉快、理性運彩！")
        proc.terminate()


if __name__ == "__main__":
    main()
