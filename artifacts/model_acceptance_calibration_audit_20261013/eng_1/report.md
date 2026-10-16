# Frozen historical calibration audit: eng_1

This is an external Football-Data/B365 historical research audit. It does not grant Taiwan forward model acceptance.

- Training: validation split, 368 matches through 2025-05-25
- Evaluation: locked holdout split, 372 matches from 2025-08-15 onward
- Temperature was fitted only on the earlier validation rows; holdout rows were not used to choose or refit it.
- The source experiment identity is retained as provenance and is not claimed as the current production identity.

| Forecast | Temperature | Raw holdout Brier | Calibrated holdout Brier | Raw log loss | Calibrated log loss | Paired Brier Δ vs market | Paired log loss Δ vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| market_baseline | — | 0.612056 | — | 1.019546 | — | — | — |
| raw_dixon_coles | 1.09 | 0.615492 | 0.615082 | 1.027024 | 1.026371 | +0.003026 | +0.006825 |
| fusion_beta_0_65 | 1.72 | 0.633596 | 0.610944 | 1.054572 | 1.019373 | -0.001112 | -0.000174 |
| empirical_training_base | 1.32 | 0.657686 | 0.656228 | 1.086280 | 1.083513 | +0.044172 | +0.063967 |
