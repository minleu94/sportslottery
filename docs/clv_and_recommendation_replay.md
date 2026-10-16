# Closing-price observations and recommendation replay

These APIs read append-only research artifacts and do not run prediction models.

## CLV report

```python
from core.clv_reporting import load_current_clv_report

report = load_current_clv_report()  # current experiment identity
print(report["status_counts"])
for prediction in report["predictions"]:
    print(prediction["snapshot_ref"], prediction["status"],
          prediction["minutes_before_start"], prediction["odds_clv_ratio"])
```

`build_clv_report(snapshots, observations, experiment_id=..., as_of=...)` supports explicit ledgers and historical cutoffs. Rows are included only when the snapshot identity and immutable payload hash verify. Quote matching requires exact event and canonical event IDs, sport, league, market, selection, side, line, and event start. The quote must be from a named source, observed at or after the prediction and strictly before the event start, and no later than `as_of`. Timestamps must be timezone-aware. Rows without a quote remain `NO_PRESTART_QUOTE`; future events remain `PENDING_EVENT`.

The price is described as the **last pre-start observed price**. The watcher polls periodically, so this is not proof of the final price accepted by the book. The report gives minutes before start and separately aggregates observations within 15 minutes. Empty cohorts return `sample_size: 0` and null averages.

For new quote records, pass `side` to `OddsWatcher.record_observation`; `record_batch_from_legs` saves the leg side automatically. Older records without side cannot satisfy the exact-match query.

## Immutable recommendation replay

```python
from core.recommendation_replay import (
    load_current_recommendation_replay,
    compare_experiment_versions,
)

replay = load_current_recommendation_replay()
comparison = compare_experiment_versions(
    snapshots,
    experiment_ids=["exp_...old", "exp_...new"],
    as_of="2026-10-14T12:00:00+00:00",
)
```

`replay_recommendation(snapshot)` verifies the saved payload and recalculates breakeven probability and EV from the sealed probability and odds. It returns the original strategy/config identity, support evidence, exclusions, model candidate provenance, and snapshot references. It never retrains or calls a current model. `replay_recommendations(snapshots, experiment_id=...)` returns per-prediction diagnostics for one identity cohort.

`compare_experiment_versions` keeps identities separate and compares only exact common event, market, selection, side, and line keys. It requires verified sealed payloads, forward eligibility, matching known outcomes, and settlement timestamps no later than `as_of`. Repeated rows are deduplicated; conflicting outcomes for an identity/event are excluded. Metrics include Brier score, log loss, classification accuracy, selected-side hit rate, and flat-unit ROI. Empty metrics remain null with `n: 0`; no synthetic observations are added.

## Whole-ticket replay

```python
from core.recommendation_replay import (
    load_current_parlay_recommendations,
    replay_parlay_recommendation,
)

report = load_current_parlay_recommendations()
for ticket in report["recommendations"]:
    print(ticket["candidate_id"], ticket["joint_probability"],
          ticket["original_total_odds"], ticket["expected_value"],
          ticket["exclusion_reasons"])
```

The whole-ticket replay verifies the frozen ticket prediction hash, experiment identity, every pre-event leg snapshot hash/reference, leg-to-snapshot fields, and the saved joint/naive/correlation-penalty arithmetic via the same qualification rules used by parlay forward evaluation. It recalculates ticket odds from the frozen leg odds and EV/breakeven from the saved joint estimate. Each leg includes its original prediction snapshot evidence and snapshot ID/hash reference. The replay does not rerun parlay search or current models. A boolean eligibility flag alone is not sufficient to qualify a ticket.
