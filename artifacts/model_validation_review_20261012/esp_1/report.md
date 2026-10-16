# Historical model validation: esp.1

Status: NOT an in-product or Taiwan lottery profitability validation.

Training/validation/locked holdout: 2324 / 2425 / 2526
Validation-selected xi: 0.0024
Forward product validation: NOT_YET_VALIDATED (eligible current experiment snapshots: 0)

## Split metrics

### validation

Same-cohort unique games: 370

| Model | N | Brier | Log loss | Hit rate | Home hit rate |
|---|---:|---:|---:|---:|---:|
| raw_dixon_coles | 370 | 0.581589 | 0.978327 | 0.508108 | 0.67027 |
| fusion_beta_0_65 | 370 | 0.585658 | 0.989479 | 0.52973 | 0.672973 |
| market_normalized_hda | 370 | 0.563736 | 0.95367 | 0.543243 | 0.681081 |
| empirical_training_base | 370 | 0.649283 | 1.073665 | 0.443243 | 0.556757 |

### locked_holdout

Same-cohort unique games: 369

| Model | N | Brier | Log loss | Hit rate | Home hit rate |
|---|---:|---:|---:|---:|---:|
| raw_dixon_coles | 369 | 0.583988 | 0.983805 | 0.517615 | 0.661247 |
| fusion_beta_0_65 | 369 | 0.585146 | 0.985508 | 0.531165 | 0.628726 |
| market_normalized_hda | 369 | 0.571479 | 0.964961 | 0.550136 | 0.639566 |
| empirical_training_base | 369 | 0.632269 | 1.049615 | 0.490515 | 0.509485 |

## Limitations

- All model probabilities are uncalibrated estimates unless later established by independent forward evidence.
- Football-Data Bet365 prices are not Taiwan lottery accepted prices; simulated ROI does not establish Taiwan profitability.
- Only events with all four model/market probability vectors enter the same-cohort multiclass comparison.
- Unmapped source team names are preserved as exact normalized source identities and reported; no fuzzy team inference is made.
