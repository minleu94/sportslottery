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

Paired ROI: same complete common cohort, one top-probability outcome per match, fixed one-unit stake for every probability source:

| Probability source | Candidate games | Decisions (N) | Excluded: missing probability | Excluded: incomplete prices | Net units | ROI |
|---|---:|---:|---:|---:|---:|---:|
| raw_dixon_coles | 368 | 368 | 0 | 0 | -29.21 | -7.94% |
| fusion_beta_0_65 | 368 | 368 | 0 | 0 | -15.01 | -4.08% |
| market_normalized_hda | 368 | 368 | 0 | 0 | -19.29 | -5.24% |
| empirical_training_base | 368 | 368 | 0 | 0 | -63.95 | -17.38% |

Supplemental EV-threshold strategy: model selects the highest probability-times-B365-price EV only when estimated EV ≥5%; the market baseline tests its probabilities against its own prices and therefore has no positive-EV selection by construction:

| Price/probability strategy | Candidate games | Decisions (N) | Excluded: missing probability | Excluded: incomplete prices | Net units | ROI |
|---|---:|---:|---:|---:|---:|---:|
| raw_dixon_coles | 380 | 241 | 12 | 0 | +46.69 | +19.37% |
| fusion_beta_0_65 | 380 | 307 | 12 | 0 | -27.09 | -8.82% |
| market_normalized_hda | 380 | 0 | 0 | 0 | +0.00 | N/A |
| empirical_training_base | 380 | 356 | 0 | 0 | -60.49 | -16.99% |


### locked_holdout

Same-cohort unique games: 372

| Model | N | Brier | Log loss | Hit rate | Home hit rate |
|---|---:|---:|---:|---:|---:|
| raw_dixon_coles | 372 | 0.615492 | 1.027024 | 0.467742 | 0.650538 |
| fusion_beta_0_65 | 372 | 0.633596 | 1.054572 | 0.481183 | 0.607527 |
| market_normalized_hda | 372 | 0.612056 | 1.019546 | 0.489247 | 0.63172 |
| empirical_training_base | 372 | 0.657686 | 1.08628 | 0.419355 | 0.580645 |

Paired ROI: same complete common cohort, one top-probability outcome per match, fixed one-unit stake for every probability source:

| Probability source | Candidate games | Decisions (N) | Excluded: missing probability | Excluded: incomplete prices | Net units | ROI |
|---|---:|---:|---:|---:|---:|---:|
| raw_dixon_coles | 372 | 372 | 0 | 0 | -51.07 | -13.73% |
| fusion_beta_0_65 | 372 | 372 | 0 | 0 | -46.01 | -12.37% |
| market_normalized_hda | 372 | 372 | 0 | 0 | -41.44 | -11.14% |
| empirical_training_base | 372 | 372 | 0 | 0 | -41.14 | -11.06% |

Supplemental EV-threshold strategy: model selects the highest probability-times-B365-price EV only when estimated EV ≥5%; the market baseline tests its probabilities against its own prices and therefore has no positive-EV selection by construction:

| Price/probability strategy | Candidate games | Decisions (N) | Excluded: missing probability | Excluded: incomplete prices | Net units | ROI |
|---|---:|---:|---:|---:|---:|---:|
| raw_dixon_coles | 380 | 226 | 8 | 0 | -26.56 | -11.75% |
| fusion_beta_0_65 | 380 | 287 | 8 | 0 | -4.72 | -1.64% |
| market_normalized_hda | 380 | 0 | 0 | 0 | +0.00 | N/A |
| empirical_training_base | 380 | 358 | 0 | 0 | -15.94 | -4.45% |


## Limitations

- All model probabilities are uncalibrated estimates unless later established by independent forward evidence.
- Football-Data B365H/D/A are pre-closing bookmaker odds; C-suffixed fields are closing odds. Neither source is Taiwan lottery accepted pricing; simulated ROI does not establish Taiwan profitability.
- Only events with all four model/market probability vectors enter the same-cohort multiclass comparison.
- Unmapped source team names are preserved as exact normalized source identities and reported; no fuzzy team inference is made.
