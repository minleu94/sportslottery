# Wallet-free research pipeline

The scheduled command is `python main.py research-pipeline`. It uses a separate
data root (`data/research_pipeline` by default) for source cache, model cache and
state, sealed single predictions, parlay candidates, odds observations, result
audit, run state, reports, and logs. `core.research_paths` is also used by the
interactive snapshot, parlay, model-gate, and odds-ledger defaults so newly
collected predictions are visible in the research UI. Existing legacy files
under `data/historical` remain readable as historical reference and are not
rewritten by this runner.

## Run modes

```powershell
python main.py research-pipeline --dry-run
python main.py research-pipeline --data-root C:\research\sportslottery --resume
```

Dry-run prints the selected 15-minute UTC window, stage plan, and resolved data
root. It does not fetch, create directories, or write state. A normal run obtains
Playsport odds, retains only complete-identity selections with a timezone-aware
start inside the next 60 minutes and odds no older than 15 minutes, evaluates
the configured research models, seals snapshots, records odds, logs linked
parlay candidates, settles available final results with Taiwan rules, updates
the isolated MLB Elo state when initialized, and writes a wallet-free weekly
report. Partial source health and result coverage are recorded with each run.

The Elo updater stores raw schedule observations in a hashed, isolated official
ledger. A checkpoint without that complete ledger is preserved as a backup but
is not trusted for incremental replay: the isolated model is rebuilt from its
configured neutral prior and official results. Schedule-query coverage and the
model `data_as_of` result watermark are separate values. Delayed games are
rechecked; when a late final precedes the rating watermark, ledgered games are
replayed into a temporary state, which becomes active only after the replay
succeeds. Only MLB regular/postseason types R/F/D/L/W affect ratings. Spring
training and exhibitions remain auditable in the source ledger but do not block
regular-season progress. Model estimates remain experimental; initialization
is not calibration evidence.

Soccer training data for EPL (`eng.1`) and La Liga (`esp.1`) is refreshed from
Football-Data.co.uk CSVs every six hours into the isolated Penaltyblog cache.
Each league file records source URLs, retrieval times, raw hashes, and the parsed
match range. A cache file is atomically replaced only after its requested
sources parse and meet the minimum history; failures preserve the last good
file and are reported. The adapter excludes matches on or after each prediction
date. These external feeds are research inputs, not Taiwan Sports Lottery
prices or proof of forward accuracy.

## Recovery and scope

Each cadence window has a persisted run ID and stage status. Stage attempts are
bounded (three by default); a retry reuses the same run window and logger
idempotency keys. `--resume` resumes the latest unfinished run up to 60 minutes
old. A run whose stage retries are exhausted remains in its audit history and
the next scheduled cadence starts a new window instead of getting stuck on that
failure. Resumed pregame selection rechecks quote age and event eligibility
against the current clock. The process lock prevents overlapping instances. A fetch failure or
settlement provider error leaves the run failed with its completed artifacts
and error details; pending games and unsupported league mappings remain
unsettled and visible. If an event starts while the machine is offline, the next
poll excludes it from pregame forecasts. If odds are stale, the event is also
excluded until a fresh observation arrives.

The report contains settled single-leg Brier, log loss, hit rate, and ROI for
the integrity-checked current-experiment cohort; model and market fair
probabilities are paired on the same observations. It also reports event-date
cluster bootstrap intervals, whole-ticket metrics from `evaluate_parlay_forward`,
source-health trends, and result coverage. Small cohorts and unsupported sports
are shown with their actual sample sizes/statuses. No real or shadow wallet is
constructed or modified.

## Windows Task Scheduler helper

`scripts/install_research_task.ps1 -DryRun` prints the task plan. The helper
uses absolute workspace/config/data paths and does not store credentials. You
can select a locked Python executable and workspace, or explicitly choose the
`SYSTEM` service account after checking its filesystem access. It does not
register or modify any task unless invoked without `-DryRun`. See
`docs/DEPLOYMENT_AND_RECOVERY.md` for wheel workspace, account, backup, and
restore instructions.
