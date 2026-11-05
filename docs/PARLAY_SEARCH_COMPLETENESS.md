# Parlay search coverage and frontier ranking

`ParlayEngine.search_parlays` (`fair-frontier-v3-probability-transparency`) keeps its three result
buckets and ranking limits (up to 12 results per bucket) for compatibility with
existing callers while providing exact admissible pruning and resumable execution.
The search considers all ready options from all eligible events after the selected
quality filter, without truncating the event pool.

## Search mechanics and pruning

The search evaluates candidate combinations using odds interval bounds:
- For any partial selection, the smallest and largest possible products from the
  remaining distinct events are bounded. If that interval cannot intersect the
  requested odds band, the whole branch is pruned.
- Mutual exclusion is strictly enforced: only one selection can be chosen per
  event.
- Sharp evaluation caching: when `SharpEdgeEngine` is present, individual option
  sharp margins are precomputed once per search invocation rather than recomputed
  repeatedly during node traversal.

## Modes and ranking objectives

1. **Leg counts & low-multiplier banker mode**:
   - The engine defaults to `min_legs=1` and `max_legs=6`; callers can choose other bounds.
   - The UI banker mode defaults to 1~3 legs around 3.75x with 20% tolerance (3.0x~4.5x). Its odds and leg bounds can be adjusted before searching.
2. **Ranking modes (`ranking_mode`)**:
   - `WIN_PROBABILITY` (default): Ranks candidates by joint probability first (Sharp joint probability if qualified, otherwise joint candidate probability), then estimated EV, evidence score, and independent supports.
   - `VALUE`: Ranks candidates by estimated EV first (Sharp parlay EV if qualified, otherwise parlay EV), then joint probability and evidence metrics.
   - Lower odds or higher estimated metrics do not guarantee forward profitability or calibration.

## Budgets, diagnostics, and resumable execution

The default budget is 250,000 visited search nodes per direct call, configurable via `search_budget`.
Direct calls can continue a batch with `resume_state` and can receive a monotonic deadline through `deadline_monotonic`.
The research pipeline additionally controls its aggregate work with `parlay_total_node_budget`,
`parlay_batch_node_budget`, and `parlay_total_seconds` in `research_pipeline.yaml`.

With diagnostics enabled, returned fields describe the search scope:
- `search_complete`: boolean indicating whether the entire search space was exhausted.
- `search_status`:
  - `COMPLETE`: Entire admissible search space was visited.
  - `BUDGET_EXHAUSTED`: Per-call node budget was reached before completing.
  - `PARTIAL_NO_GLOBAL_TOP_GUARANTEE`: Search returned partial results; `deadline_reached` separately reports whether the supplied deadline elapsed.
  - `NOT_STARTED_TOTAL_LIMIT`: Research-pipeline tier skipped because its aggregate budget or deadline was exhausted before it started.
- `visited_nodes`, `odds_pruned_nodes`, `checked_combinations`, and `odds_matching_combinations`.

If `search_status == "BUDGET_EXHAUSTED"`, empty result buckets mean no qualifying
combination was found within the examined portion, not that no combination exists.
A complete search with empty buckets confirms that all legal options were searched
and no combination satisfied the odds interval and constraints.

The returned three buckets (`high_consensus`, `aggressive`, `moonshot`) are ranked
display sets, not exhaustive lists. Each bucket retains at most its top 12 results.
