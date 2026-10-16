Scope: current Python source only; historical data and prose reports excluded. Structural AST extraction; no semantic inference.

# Graph Report - C:\Projects\PythonProjects\sportslottery  (2026-10-12)

## Corpus Check
- 82 files · ~50,491 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 755 nodes · 1677 edges · 50 communities (38 shown, 12 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 83 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Application
- core
- core
- identity
- Application
- models
- core
- Application
- Application
- core
- Application
- external
- core
- core
- common
- external
- core
- settlement
- Application
- core
- core
- core
- external
- core
- core
- core
- Application
- Application
- core
- models
- Application
- probability
- models
- core
- core
- core
- scripts
- Application
- collectors
- core
- settlement
- external
- optimizer
- probability
- risk
- acceptance
- acceptance
- tests
- tickets

## God Nodes (most connected - your core abstractions)
1. `TaiwanLeg` - 120 edges
2. `PredictionSignal` - 60 edges
3. `SignalHub` - 41 edges
4. `PredictionSnapshotLogger` - 33 edges
5. `PlaysportExpertAdapter` - 32 edges
6. `PlaysportScraper` - 30 edges
7. `PenaltyblogDixonColesAdapter` - 27 edges
8. `ShadowPortfolioManager` - 26 edges
9. `WeeklyWalletManager` - 24 edges
10. `FiveThirtyEightMLBEloAdapter` - 23 edges

## Surprising Connections (you probably didn't know these)
- `CorrelationEvaluation` --uses--> `TaiwanLeg`  [INFERRED]
  core/correlation_guard.py → integrations/common/models.py
- `CorrelationGuard` --uses--> `TaiwanLeg`  [INFERRED]
  core/correlation_guard.py → integrations/common/models.py
- `ConfidenceInterval` --uses--> `PredictionSignal`  [INFERRED]
  core/edge_engine.py → integrations/common/models.py
- `DirectEdgeResult` --uses--> `PredictionSignal`  [INFERRED]
  core/edge_engine.py → integrations/common/models.py
- `ProbabilityEdgeEvaluation` --uses--> `PredictionSignal`  [INFERRED]
  core/edge_engine.py → integrations/common/models.py

## Import Cycles
- None detected.

## Communities (50 total, 12 thin omitted)

### Community 0 - "Application"
Cohesion: 0.06
Nodes (45): BeautifulSoup, ParlayEngine, Any, Searches for optimal parlay combinations using TaiwanLeg candidates., Search valid parlays matching target odds [min_odds, max_odds] or target_odds ±, PlaysportScraper, Any, Path (+37 more)

### Community 1 - "core"
Cohesion: 0.08
Nodes (31): ParlayOptimizer, Any, Search all valid parlays meeting criteria and return top ranked combinations., Any, Connection, List tickets, optionally filtered by status ('OPEN', 'WON', 'LOST')., Create and place a new parlay ticket. Deducts stake from War Chest., Settle a ticket as WON or LOST. If WON, credits payout to War Chest. (+23 more)

### Community 2 - "core"
Cohesion: 0.08
Nodes (21): ConfidenceInterval, DirectEdgeResult, ProbabilityEdgeEvaluation, Any, Perform full quantitative evaluation for a TaiwanLeg., Rigorous quantitative probability and value evaluation for a single selection., A genuine betting selection available in Taiwan Sports Lottery.      All Parlay, TaiwanLeg (+13 more)

### Community 3 - "identity"
Cohesion: 0.13
Nodes (19): CanonicalEvent, EventMatcher, Any, Matches raw events from different providers to unified CanonicalEvent., Match with existing canonical event, or create a new one if teams resolve., Identity, Canonical Teams, and Event Matching Package., normalize_league_and_sport(), Normalize league string or alliance_id to (canonical_league, sport). (+11 more)

### Community 4 - "Application"
Cohesion: 0.13
Nodes (20): get_system_components(), Monitors live sport seasons and Taiwan Sports Lottery market availability., SeasonRadar, get_current_iso_week(), get_now_iso(), date, Path, Return ISO week format, e.g., '2026-W38'. (+12 more)

### Community 5 - "models"
Cohesion: 0.11
Nodes (14): PenaltyblogSoccerAdapter, Any, Evaluate a soccer TaiwanLeg option using real team stats., Evaluates soccer TaiwanLeg betting options using real stats Poisson models., Any, PybaseballMLBAdapter, Evaluate an MLB TaiwanLeg option using real team stats., Evaluates MLB TaiwanLeg betting options using real team stats and Pythagorean ex (+6 more)

### Community 6 - "core"
Cohesion: 0.16
Nodes (20): PerformanceMetricsEngine, Evaluates forward prediction snapshots and generates segmented performance metri, get_core_code_hash(), get_evidence_weights_hash(), get_git_status_and_reproducibility(), get_strategy_metadata(), Any, Path (+12 more)

### Community 7 - "Application"
Cohesion: 0.10
Nodes (18): Any, Session, Settle a snapshot with strict payload hash check., Return True if multiple result providers report conflicting scores., Settle parlay candidates and shadow tickets using official Taiwan VOID logic., Official Taiwan Lottery result settlement engine with audit verification., Fetch completed MLB games for date YYYY-MM-DD from statsapi.mlb.com., SettlementEngine (+10 more)

### Community 8 - "Application"
Cohesion: 0.11
Nodes (19): Any, Synthesize a collection of signals for a TaiwanLeg with source-family independen, Backward-compatible evaluation for raw option dictionaries., Aggregates multi-source evidence for TaiwanLeg betting selections., Gather all external evidence for a TaiwanLeg and calculate agreement level., SignalHub, test_evidence_weights_config_loading(), test_independence_group_deduplication() (+11 more)

### Community 9 - "core"
Cohesion: 0.11
Nodes (18): EdgeEngine, Computes calibrated probability distributions, edge, and EV for TaiwanLeg object, Normalize market odds to remove margin proportionally., Calibrate raw probability towards 0.50 via logit shrinkage., Calculate conservative binomial confidence interval., Direct mathematical edge and trap evaluation for a single probability & odds., calculate_conservative_lower_bound(), calibrate_with_signals() (+10 more)

### Community 10 - "Application"
Cohesion: 0.14
Nodes (14): Any, Connection, Path, Place an isolated paper bet with fixed NT$10 virtual stake (deduplicated)., Pick and record today's Top HIGH, Top MED, and Top Target candidates with strict, Settle a shadow ticket supporting Taiwan rules (WON, LOST, PUSH, VOID)., Compute virtual cumulative stake, payout, P/L, unique tickets, and overlap., Retrieve recent shadow tickets. (+6 more)

### Community 11 - "external"
Cohesion: 0.11
Nodes (20): PenaltyblogDixonColesAdapter, Evaluates soccer TaiwanLeg betting options using genuine Dixon & Coles bivariate, Penaltyblog Dixon-Coles directly imports and invokes penaltyblog; category MUST, Model evaluation must log full ModelInputProvenance metadata., Production directory (data/cache, data/historical) must have ZERO synthetic matc, Soccer historical match records must contain genuine dates, teams, scores, and n, Leakage Guard: Dixon-Coles model must ONLY fit on matches strictly before predic, If training matches < MIN_MATCHES_REQUIRED or team apps < MIN_APPS, return None (+12 more)

### Community 12 - "core"
Cohesion: 0.15
Nodes (14): OddsWatcher, Path, Find the last valid observed odds strictly before event start.          Returns, Records real-time odds observations and extracts genuine pre-game closing odds., compute_parlay_fingerprint(), Compute deterministic SHA-256 hash of sorted leg identifiers., Verify that missing closing odds returns None and NOT_AVAILABLE without fabricat, Verify that parlay fingerprint is deterministic and invariant to leg order. (+6 more)

### Community 13 - "core"
Cohesion: 0.13
Nodes (14): _calc_brier(), _calc_logloss(), Any, Evaluate individual expert performance and consensus buckets., Evaluate Crowd consensus percentage bins (50-60%, 60-70%, 70-80%, 80%+)., Evaluate probability calibration: predicted probability bins vs empirical hit ra, Calculate ROI percentage: ((sum of winning odds) - N) / N * 100., Compute aggregate Brier, Log Loss, and ROI for models. (+6 more)

### Community 14 - "common"
Cohesion: 0.12
Nodes (11): Any, Authentic pick verified on an expert's personal prediction page., VerifiedExpertPick, DummyExpertScraper, Mock scraper returning controlled expert picks for testing., test_exact_line_matching_spread(), test_exact_line_matching_total(), test_expert_pick_date_validation() (+3 more)

### Community 15 - "external"
Cohesion: 0.11
Nodes (16): FiveThirtyEightMLBEloAdapter, Look up today's probable starting pitchers from cached MLB schedule., Evaluate an MLB TaiwanLeg option using FiveThirtyEight Elo win probability formu, Evaluates MLB TaiwanLeg betting options using FiveThirtyEight's Elo model formul, Calibrate team Elo ratings using real 2026 MLB standings from MLB Stats API., FiveThirtyEight raw MLB dataset ceased in 2023; verify it is not misrepresented, FiveThirtyEight MLB Elo is a local reimplementation of 538's paper, NOT an exter, test_538_source_freshness() (+8 more)

### Community 16 - "core"
Cohesion: 0.19
Nodes (9): ModelQualityLabel, PredictionSignal, Standardized model reliability classification., Standard signal emitted by any prediction, expert, crowd, or market source., Integrations and adapters package., ModelInputProvenance, Rigorous metadata documenting the exact training dataset and provenance., Verify that 2025-2026 and 2026-2027 season match records are present in the socc (+1 more)

### Community 17 - "settlement"
Cohesion: 0.14
Nodes (14): Taiwan Settlement Rules Package., OfficialCompletionStatus, Any, Official Taiwan Sports Lottery rules engine v2., Official match completion states under Taiwan Sports Lottery regulations., Structured settlement outcome containing full rule lineage., Deterministically assign official settlement rule ID., resolve_settlement_rule_id() (+6 more)

### Community 18 - "Application"
Cohesion: 0.18
Nodes (10): Any, Connection, Path, Record closing odds and calculate Closing Line Value (CLV)., Settle a ticket. If WON or VOID, credits appropriate payout into Reserve Bankrol, Aggregate Closing Line Value statistics., Place a ticket. Deducts stake from the Weekly Wallet., TicketRecorder (+2 more)

### Community 19 - "core"
Cohesion: 0.13
Nodes (13): compute_leg_overlap_ratio(), Any, Path, Record all parlay search results for today across tiers (append-only)., Retrieve all recorded parlay snapshots., Settle a parlay candidate applying Taiwan Lottery VOID rules.          If a leg, Compute Jaccard overlap ratio between two parlay leg sets., Records and settles candidate parlay combinations across multiplier tiers. (+5 more)

### Community 20 - "core"
Cohesion: 0.14
Nodes (8): CorrelationEvaluation, CorrelationGuard, Any, Evaluation of parlay cross-leg independence and joint value., Analyzes a set of TaiwanLegs in a parlay and penalizes joint probability for cor, Calculate joint probability, correlation haircut, and parlay EV., Verify parlay correlation detection, haircut factor, and parlay EV., test_correlation_guard_haircut()

### Community 21 - "core"
Cohesion: 0.18
Nodes (9): compute_prediction_payload_hash(), Any, Record an evaluation snapshot for a TaiwanLeg (append-only & idempotent)., Record snapshots for multiple legs., Search existing snapshot log for duplicate key., Read all snapshots from jsonl., Settle a snapshot with strict payload hash verification., Compute aggregate Brier score and log loss across settled forward-eligible snaps (+1 more)

### Community 22 - "external"
Cohesion: 0.20
Nodes (8): LiveMLBEloAdapter, Path, Persist current ratings and history to disk., Calculate home and away win probabilities., Update ratings from real match score using Margin of Victory multiplier., Evaluate a TaiwanLeg MLB betting option., Production self-maintained MLB Elo rating and prediction adapter., Load ratings and update history from disk.

### Community 23 - "core"
Cohesion: 0.23
Nodes (7): Path, Export source_metrics.csv., Export all 3 research datasets., Exports structured audit and evaluation datasets to data/research/., Export single_leg_forward.csv., Export parlay_forward.csv., ResearchDatasetExporter

### Community 24 - "core"
Cohesion: 0.19
Nodes (7): ESPNScheduleAdapter, Any, Session, Provides schedule awareness from ESPN public endpoints., Fetch today's events for a given league code., Verify live connection to ESPN public scoreboard API., test_live_espn_schedule_provider()

### Community 25 - "core"
Cohesion: 0.17
Nodes (10): Evaluate whether a selection won based on Taiwan Lottery rules (backward compati, Evaluate market outcome strictly according to Taiwan Sports Lottery rules v2., Verify postponement beyond valid window settles as VOID., test_postponed_market_settlement(), Called game (e.g. rain stoppage after 6 innings):     - Moneyline (不讓分): Pre-gam, Match abandoned early or cancelled -> VOID., 9-inning completed game settles all markets normally., test_taiwan_settlement_called_game_rules() (+2 more)

### Community 26 - "Application"
Cohesion: 0.27
Nodes (6): Any, Connection, Return the core numbers, lifetime accounting, and operational limits., Deposit external cash up to the weekly shortfall limit., Deduct bet stake from Weekly Wallet., Withdraw realized profits from Prize Pool to real bank account.

### Community 27 - "Application"
Cohesion: 0.21
Nodes (6): DixonColesGoalModel, Any, Load authentic match results from cache file., Point-in-Time Filter & Leakage Guard: strictly exclude matches on or after pred_, Fit DixonColesGoalModel using historical point-in-time matches with native decay, Evaluate a soccer TaiwanLeg option using fitted Dixon-Coles model.          Retu

### Community 28 - "core"
Cohesion: 0.24
Nodes (6): ModelRegistry, Any, Path, Manages all registered open-source prediction models., Run all matching enabled models on a TaiwanLeg., test_model_registry_loads_provenance_metadata()

### Community 29 - "models"
Cohesion: 0.31
Nodes (4): ESPNPoissonSoccerFallback, Any, Evaluate a soccer TaiwanLeg option using real team stats., Evaluates soccer TaiwanLeg betting options using real team stats and univariate

### Community 30 - "Application"
Cohesion: 0.42
Nodes (8): ensure_streamlit_credentials(), find_project_dir(), find_python_executable(), main(), Path, Ensure ~/.streamlit/credentials.toml and project/.streamlit/credentials.toml exi, set_console_title(), wait_and_open_browser()

### Community 31 - "probability"
Cohesion: 0.31
Nodes (8): calculate_implied_prob(), devig_multiplicative(), devig_three_way(), devig_two_way(), Calculate raw implied probability q = 1 / odds., Remove overround using standard proportional (multiplicative) normalization., De-vig a 2-way binary market (e.g. Spread, Over/Under, Tennis).      Returns:, De-vig a 3-way market (e.g. Soccer 1X2).      Returns:         (fair_home, fair_

### Community 32 - "models"
Cohesion: 0.32
Nodes (4): ESPNPythagoreanMLBModel, Any, Evaluate an MLB TaiwanLeg option using real team stats., Evaluates MLB TaiwanLeg betting options using real team stats and Pythagorean ex

### Community 33 - "core"
Cohesion: 0.33
Nodes (4): Any, Calculate dual CLV metrics and preserve independent reference closing market., Record an immutable odds observation point., Record observations for a batch of TaiwanLeg objects.

### Community 34 - "core"
Cohesion: 0.33
Nodes (6): check_cutoff_integrity(), Verify that prediction and evidence strictly precede the event start time., Verify that expert picks with DATE_ONLY precision are flagged and excluded from, Verify that predictions observed after match start are excluded as POST_START_DA, test_prediction_snapshot_precedes_event(), test_unknown_expert_timestamp_excluded_from_strict_forward_metrics()

### Community 35 - "core"
Cohesion: 0.40
Nodes (5): AuditFailureError, Raised when an existing prediction payload has been modified or corrupted., Exception, Verify that altering any original prediction field triggers AuditFailureError du, test_prediction_payload_hash_immutable()

### Community 36 - "scripts"
Cohesion: 0.60
Nodes (4): brier_score(), log_loss(), Multiclass Brier score: sum((p_i - o_i)^2)., run_expanded_backtest()

## Knowledge Gaps
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TaiwanLeg` connect `core` to `Application`, `Application`, `models`, `core`, `Application`, `Application`, `core`, `external`, `core`, `common`, `external`, `core`, `settlement`, `core`, `core`, `external`, `Application`, `core`, `models`, `models`, `core`, `Application`, `tests`?**
  _High betweenness centrality (0.352) - this node is a cross-community bridge._
- **Why does `PlaysportScraper` connect `Application` to `core`, `Application`?**
  _High betweenness centrality (0.124) - this node is a cross-community bridge._
- **Why does `PredictionSignal` connect `core` to `Application`, `models`, `core`, `Application`, `models`, `core`, `Application`, `core`, `external`, `common`, `external`, `settlement`, `external`, `Application`, `core`, `models`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `TaiwanLeg` (e.g. with `CorrelationEvaluation` and `CorrelationGuard`) actually correct?**
  _`TaiwanLeg` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 17 inferred relationships involving `PredictionSignal` (e.g. with `ConfidenceInterval` and `DirectEdgeResult`) actually correct?**
  _`PredictionSignal` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `SignalHub` (e.g. with `ParlayEngine` and `EdgeEngine`) actually correct?**
  _`SignalHub` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `PredictionSnapshotLogger` (e.g. with `ResearchDatasetExporter` and `SettlementEngine`) actually correct?**
  _`PredictionSnapshotLogger` has 4 INFERRED edges - model-reasoned connections that need verification._