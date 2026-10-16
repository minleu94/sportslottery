# Historical model validation: eng.1

Status: NOT an in-product or Taiwan lottery profitability validation.

Training/validation/locked holdout: 2324 / 2425 / 2526
Validation-selected xi: 0.0024
Forward product validation: NOT_YET_VALIDATED (eligible current experiment snapshots: 0)

## Split metrics

### validation

Same-cohort unique games: 368

| Model | N | Brier | Log loss | Hit rate | Home hit rate |
|---|---:|---:|---:|---:|---:|
| raw_dixon_coles | 368 | 0.583256 | 0.975595 | 0.516304 | 0.665761 |
| fusion_beta_0_65 | 368 | 0.606935 | 1.020636 | 0.538043 | 0.660326 |
| market_normalized_hda | 368 | 0.580989 | 0.974519 | 0.538043 | 0.665761 |
| empirical_training_base | 368 | 0.655148 | 1.08041 | 0.410326 | 0.589674 |

### locked_holdout

Same-cohort unique games: 372

| Model | N | Brier | Log loss | Hit rate | Home hit rate |
|---|---:|---:|---:|---:|---:|
| raw_dixon_coles | 372 | 0.615492 | 1.027024 | 0.467742 | 0.650538 |
| fusion_beta_0_65 | 372 | 0.633596 | 1.054572 | 0.481183 | 0.607527 |
| market_normalized_hda | 372 | 0.612056 | 1.019546 | 0.489247 | 0.63172 |
| empirical_training_base | 372 | 0.657686 | 1.08628 | 0.419355 | 0.580645 |

## Limitations

- All model probabilities are uncalibrated estimates unless later established by independent forward evidence.
- Football-Data Bet365 prices are not Taiwan lottery accepted prices; simulated ROI does not establish Taiwan profitability.
- Only events with all four model/market probability vectors enter the same-cohort multiclass comparison.
- Unmapped source team names are preserved as exact normalized source identities and reported; no fuzzy team inference is made.
