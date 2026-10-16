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



## Paired calendar-month block bootstrap 95% CI

Delta is model minus normalized B365 market on the same matches; Brier and Log loss lower is better, hit rate and ROI higher is better.

| Split | Model | Metric | Delta | 95% CI | Valid draws |
|---|---|---|---:|---:|---:|
| validation | raw_dixon_coles | brier | +0.0023 | [-0.0109, +0.0151] | 1000 |
| validation | raw_dixon_coles | log_loss | +0.0011 | [-0.0180, +0.0204] | 1000 |
| validation | raw_dixon_coles | hit_rate | -0.0217 | [-0.0608, +0.0219] | 1000 |
| validation | raw_dixon_coles | paired_top_probability_roi_pct | -2.6957 | [-12.8479, +9.4497] | 1000 |
| validation | fusion_beta_0_65 | brier | +0.0259 | [+0.0074, +0.0411] | 1000 |
| validation | fusion_beta_0_65 | log_loss | +0.0461 | [+0.0142, +0.0745] | 1000 |
| validation | fusion_beta_0_65 | hit_rate | +0.0000 | [-0.0258, +0.0275] | 1000 |
| validation | fusion_beta_0_65 | paired_top_probability_roi_pct | +1.1630 | [-5.3976, +8.5190] | 1000 |
| validation | market_normalized_hda | brier | +0.0000 | [+0.0000, +0.0000] | 1000 |
| validation | market_normalized_hda | log_loss | +0.0000 | [+0.0000, +0.0000] | 1000 |
| validation | market_normalized_hda | hit_rate | +0.0000 | [+0.0000, +0.0000] | 1000 |
| validation | market_normalized_hda | paired_top_probability_roi_pct | +0.0000 | [+0.0000, +0.0000] | 1000 |
| validation | empirical_training_base | brier | +0.0742 | [+0.0488, +0.1003] | 1000 |
| validation | empirical_training_base | log_loss | +0.1059 | [+0.0689, +0.1436] | 1000 |
| validation | empirical_training_base | hit_rate | -0.1277 | [-0.1787, -0.0765] | 1000 |
| validation | empirical_training_base | paired_top_probability_roi_pct | -12.1359 | [-26.1947, +2.7788] | 1000 |
Bootstrap blocks: 10 calendar months; replicates: 1000; seed: 20261013.
| locked_holdout | raw_dixon_coles | brier | +0.0034 | [-0.0071, +0.0150] | 1000 |
| locked_holdout | raw_dixon_coles | log_loss | +0.0075 | [-0.0085, +0.0232] | 1000 |
| locked_holdout | raw_dixon_coles | hit_rate | -0.0215 | [-0.0372, +0.0000] | 1000 |
| locked_holdout | raw_dixon_coles | paired_top_probability_roi_pct | -2.5887 | [-7.0648, +3.9688] | 1000 |
| locked_holdout | fusion_beta_0_65 | brier | +0.0215 | [-0.0008, +0.0432] | 1000 |
| locked_holdout | fusion_beta_0_65 | log_loss | +0.0350 | [-0.0020, +0.0709] | 1000 |
| locked_holdout | fusion_beta_0_65 | hit_rate | -0.0081 | [-0.0265, +0.0124] | 1000 |
| locked_holdout | fusion_beta_0_65 | paired_top_probability_roi_pct | -1.2285 | [-6.3310, +4.3125] | 1000 |
| locked_holdout | market_normalized_hda | brier | +0.0000 | [+0.0000, +0.0000] | 1000 |
| locked_holdout | market_normalized_hda | log_loss | +0.0000 | [+0.0000, +0.0000] | 1000 |
| locked_holdout | market_normalized_hda | hit_rate | +0.0000 | [+0.0000, +0.0000] | 1000 |
| locked_holdout | market_normalized_hda | paired_top_probability_roi_pct | +0.0000 | [+0.0000, +0.0000] | 1000 |
| locked_holdout | empirical_training_base | brier | +0.0456 | [+0.0216, +0.0669] | 1000 |
| locked_holdout | empirical_training_base | log_loss | +0.0667 | [+0.0353, +0.0956] | 1000 |
| locked_holdout | empirical_training_base | hit_rate | -0.0699 | [-0.1206, -0.0149] | 1000 |
| locked_holdout | empirical_training_base | paired_top_probability_roi_pct | +0.0807 | [-12.1961, +13.2073] | 1000 |
Bootstrap blocks: 10 calendar months; replicates: 1000; seed: 20261013.

## Production sport coverage

Validated historical leagues: eng.1, esp.1.
Unsupported production sports/leagues: MLB, NPB, CPBL, KBO, NBA/WNBA, NFL, other soccer leagues.
Frozen audited Football-Data.co.uk point-in-time match and B365 H/D/A sources currently cover only English Premier League and Spanish La Liga; Taiwan production market snapshots are not interchangeable with these sources.

## Limitations

- All model probabilities are uncalibrated estimates unless later established by independent forward evidence.
- Football-Data B365H/D/A are pre-closing bookmaker odds; C-suffixed fields are closing odds. Neither source is Taiwan lottery accepted pricing; simulated ROI does not establish Taiwan profitability.
- Only events with all four model/market probability vectors enter the same-cohort multiclass comparison.
- Paired confidence intervals resample calendar-month blocks on the same match cohort; the supported historical source scope currently covers only EPL and La Liga, not the full production sport set.
- Unmapped source team names are preserved as exact normalized source identities and reported; no fuzzy team inference is made.
