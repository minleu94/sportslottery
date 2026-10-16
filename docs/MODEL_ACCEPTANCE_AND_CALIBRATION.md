# Model acceptance and probability calibration

## Recommendation behavior

Models continue to run and their raw estimates remain visible in `model_candidate_probability_raw`, `model_candidate_probability_fused`, and `model_candidate_provenances`. These candidate estimates are for research and snapshot accumulation. They do not increase support, quality, or the recommendation probability until an exact-scope evidence gate returns `ACCEPTED`.

The runtime gate is implemented in `core/model_acceptance.py` and is called by `core/model_registry.py`. An accepted record must match model ID and version, executable artifact SHA-256, protocol ID and hash, league, market, and `taiwan_forward` source scope. The status is recomputed from valid settled snapshots; `config/model_acceptance.yaml` contains thresholds only and has no accepted-model switches. Missing, stale, contradictory, invalidly hashed, or scope-mismatched evidence fails closed. Historical Football-Data/B365 records can produce a `HISTORICAL_ONLY` status and cannot authorize Taiwan recommendations.

## Qualification protocol

The gate builds its calibration prefix from whole events until it reaches the configured sample and unique-event minimums, then uses later events for evaluation. Every calibration result must be settled before the first evaluation prediction. It fits binary temperature scaling only on the earlier cohort, then compares calibrated predictions with a valid normalized same-event market baseline. Incomplete or malformed market quotes remain research rows and cannot enter the benchmark cohort. The default policy requires 100 calibration events, 100 evaluation events, and 30 event-date clusters, paired 95% cluster-bootstrap intervals showing lower Brier and log loss, and a positive paired ROI interval with at least the predeclared number of actual bets. ROI uses a fixed one-unit stake only when calibrated probability times offered decimal odds clears the configured expected-value threshold. No-bet events return zero and do not count as executed bets.

Evidence must have timezone-aware prediction, model-data, event-start, and settlement timestamps in the correct order; a valid immutable snapshot hash and experiment identity; consistent result status and outcome; a usable result source; and valid normalized market prices. Conflicting repeated results are excluded, and repeated forecasts for an event/market/selection use the earliest row. The gate never chooses thresholds from its evaluation cohort. The runtime acceptance record is fingerprinted over its scope, criteria, cutoffs, sample counts, and metrics. The active recommendation uses one deterministic accepted model's exact certified calibrated probability; separate multi-model fusion remains a research estimate.

Shadow portfolio tickets store the experiment identity, prediction snapshot references, and a ticket payload hash. Qualified ticket summaries require exact current experiment identity and revalidated leg snapshot hashes; older unqualified paper tickets remain available in the general portfolio view.

## Calibration fitting API

`probability.calibration.fit_multiclass_temperature` and `apply_multiclass_temperature` provide normalized multiclass temperature scaling. `core.model_calibration.fit_chronological_temperature` requires a separate earlier training split and later evaluation split, checks the date boundary, fits only on training probabilities/outcomes, and returns the training cutoff and sample counts with heldout calibrated vectors. The Taiwan runtime gate uses the corresponding binary temperature transform for one selected outcome.

## Frozen historical audit

Run `python -m scripts.build_model_acceptance_calibration_audit` to rebuild the audit from immutable predictions in `artifacts/model_validation_review_20261013_luna/`. It fits temperatures on the `validation` split and evaluates on the locked `holdout` split, independently for each league and forecast variant. Outputs go to `artifacts/model_acceptance_calibration_audit_20261013/`.

The generated audit keeps the source files' hashes and source experiment identity as provenance. That identity describes the frozen historical pipeline and does not claim to represent current production code. The B365 results are historical external benchmarks, not Taiwan forward evidence. They therefore do not change runtime acceptance.
