# Frozen historical calibration audit: esp_1

This is an external Football-Data/B365 historical research audit. It does not grant Taiwan forward model acceptance.

- Training: validation split, 370 matches through 2025-05-25
- Evaluation: locked holdout split, 369 matches from 2025-08-15 onward
- Temperature was fitted only on the earlier validation rows; holdout rows were not used to choose or refit it.
- The source experiment identity is retained as provenance and is not claimed as the current production identity.

| Forecast | Temperature | Raw holdout Brier | Calibrated holdout Brier | Raw log loss | Calibrated log loss | Paired Brier Δ vs market | Paired log loss Δ vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| market_baseline | — | 0.571479 | — | 0.964961 | — | — | — |
| raw_dixon_coles | 1.03 | 0.583988 | 0.584201 | 0.983805 | 0.984084 | +0.012722 | +0.019123 |
| fusion_beta_0_65 | 1.52 | 0.585146 | 0.575398 | 0.985508 | 0.969666 | +0.003920 | +0.004705 |
| empirical_training_base | 1.02 | 0.632269 | 0.632568 | 1.049615 | 1.050018 | +0.061089 | +0.085056 |
