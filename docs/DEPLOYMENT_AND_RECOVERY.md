# Deployment and recovery

This project can run from a source checkout or from the installed wheel. The
scheduled research pipeline is wallet-free and writes to its configured
research data root. Completing a run means the stages ran; it does not establish
model profitability or verified betting returns.

## Install the wheel into a persistent workspace

Install the wheel into a Python 3.11 or 3.12 environment, then materialize the
runtime into a writable directory. Keep that workspace and its `data` directory
between upgrades; the wheel is the code distribution, while the workspace holds
the editable configuration and research records.

```powershell
py -m venv C:\SportsLottery\venv
C:\SportsLottery\venv\Scripts\python.exe -m pip install .\dist\sportslottery-2.0.1-py3-none-any.whl
$env:SPORTSLOTTERY_WORKSPACE = 'C:\SportsLottery\workspace'
C:\SportsLottery\venv\Scripts\sportslottery.exe --workspace $env:SPORTSLOTTERY_WORKSPACE research-pipeline --dry-run
```

`--workspace` takes precedence over `SPORTSLOTTERY_WORKSPACE`. The launcher
copies packaged runtime files into that directory and keeps an existing
workspace configuration, saving the packaged default under
`config/defaults/`. Review `config/research_pipeline.yaml` and run a dry-run
before starting collection:

```powershell
C:\SportsLottery\venv\Scripts\sportslottery.exe --workspace C:\SportsLottery\workspace research-pipeline --dry-run
C:\SportsLottery\venv\Scripts\sportslottery.exe --workspace C:\SportsLottery\workspace research-pipeline
```

For a locked environment, pass its Python executable explicitly. The scheduler
helper accepts `-PythonPath`; use the environment's `pythonw.exe` when it is
available to avoid a console window, or its `python.exe` if that is the only
installed executable. If both exist beside one another, the helper validates
with `python.exe` and schedules `pythonw.exe`.

There is no required API key or credential environment variable for the
research pipeline. The wheel launcher supports `SPORTSLOTTERY_WORKSPACE`; the
scheduled helper instead records absolute workspace, config, and data-root
paths in the task action. Set `data_root` in the YAML or pass `--data-root` to
choose the research ledger location. Keep it separate from protected production
data directories.

## Windows Task Scheduler setup

Review the generated plan first. This command only validates the configuration
and prints a plan; it does not register a task:

```powershell
.\scripts\install_research_task.ps1 -DryRun `
  -WorkingDirectory C:\SportsLottery\workspace `
  -PythonPath C:\SportsLottery\venv\Scripts\pythonw.exe `
  -DataRoot C:\SportsLottery\research
```

After reviewing the plan and confirming that account can read the workspace and
write the research root, registration uses the current user's interactive
logon. It does not store a password. Interactive tasks run only while that user
has an interactive logon; they are not a background service while the user is
signed out. Do not treat an enabled task as proof that a run succeeded: inspect
the task result and the saved pipeline health record.

An optional service-account mode avoids stored credentials by using Windows
`SYSTEM`. It requires an explicit workspace path:

```powershell
.\scripts\install_research_task.ps1 -DryRun -RunAsSystem `
  -WorkingDirectory C:\SportsLottery\workspace `
  -PythonPath C:\SportsLottery\venv\Scripts\pythonw.exe `
  -DataRoot C:\SportsLottery\research
```

Only register after checking that the chosen workspace, Python runtime and
research root are readable/writable by `SYSTEM`. A user-profile virtualenv,
profile-only config, mapped drive, or user-only ACL may fail under that account.
The task action is local to this machine and may run without a desktop session;
it does not gain access to the signed-in user's profile. This mode changes the
task principal only when explicitly selected. The existing task keeps its current-user principal; use this option only when
explicitly selecting a different principal.

Use the helper's `-Uninstall` option to remove only a task with its ownership
description marker. Do not use it against a task that has been renamed or
replaced by another deployment.

## First backup and restore

Create a backup before changing the workspace or its data. Choose an output
directory outside the source `data`, `core`, `scripts`, `config`, and other
backed-up directories:

```powershell
python .\main.py backup --output D:\SportsLotteryBackups
```

The command prints the timestamped backup directory and file count. It copies
the supported runtime directories and `data`, records SHA-256 hashes, and uses
the pipeline lock while reading. It does not package Python itself, installed
dependencies, OS task registrations, or arbitrary files outside its declared
backup set.

Restore only into a new empty path; existing paths are refused rather than
overwritten:

```powershell
python .\main.py restore `
  --backup D:\SportsLotteryBackups\20261015T120000Z_ab12cd34 `
  --destination D:\SportsLottery\recovered
```

The restore checks every saved file hash and writes a receipt. Install the
project dependencies in a compatible Python environment, inspect the restored
`config/research_pipeline.yaml`, and run a dry-run against the restored workspace
before resuming collection. Back up regularly and retain at least one copy
outside the machine or disk that holds the working workspace.

## What the league coverage status means

`available_third_party_verified_observed_slate` means a public provider route
and exact identities were checked for the named observed events. It does not
mean a complete league roster, guaranteed future source availability, or an
official league data agreement. `unsupported_source_unverified` means the
current source route and identity scope have not been verified; it does not
mean that the competition has no results or no provider anywhere. The health
panel carries the reason and checked reference for the Turkish First League and
Belarusian Premier League rows so they remain visible without being misreported
as having no score.


## Windows operation notes

Use a short backup destination (for example `D:\SLBackups` or this checkout's
`backups` directory). Deep artifact paths plus long source names can exceed
Windows path limits. Failed operations keep an `.incomplete` staging directory;
only a completed directory with a verified manifest is a usable backup.

The backup snapshots SQLite databases and JSONL ledgers first, releasing their
locks before copying public-source files. The pipeline lock stays held during
backup. Freeze source/config edits during the operation; arbitrary external
writers that do not use the shared locks cannot be guaranteed consistent.
The restore command always requires a new destination and checks the declared
inventory and file hashes before publishing it.
