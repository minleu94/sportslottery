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

Paired ROI: same complete common cohort, one top-probability outcome per match, fixed one-unit stake for every probability source:

| Probability source | Candidate games | Decisions (N) | Excluded: missing probability | Excluded: incomplete prices | Net units | ROI |
|---|---:|---:|---:|---:|---:|---:|
| raw_dixon_coles | 370 | 370 | 0 | 0 | -33.38 | -9.02% |
| fusion_beta_0_65 | 370 | 370 | 0 | 0 | -15.75 | -4.26% |
| market_normalized_hda | 370 | 370 | 0 | 0 | -8.70 | -2.35% |
| empirical_training_base | 370 | 370 | 0 | 0 | -29.85 | -8.07% |

Supplemental EV-threshold strategy: model selects the highest probability-times-B365-price EV only when estimated EV ≥5%; the market baseline tests its probabilities against its own prices and therefore has no positive-EV selection by construction:

| Price/probability strategy | Candidate games | Decisions (N) | Excluded: missing probability | Excluded: incomplete prices | Net units | ROI |
|---|---:|---:|---:|---:|---:|---:|
| raw_dixon_coles | 380 | 220 | 10 | 0 | -38.17 | -17.35% |
| fusion_beta_0_65 | 380 | 297 | 10 | 0 | -33.23 | -11.19% |
| market_normalized_hda | 380 | 0 | 0 | 0 | +0.00 | N/A |
| empirical_training_base | 380 | 335 | 0 | 0 | -45.53 | -13.59% |


### locked_holdout

Same-cohort unique games: 369

| Model | N | Brier | Log loss | Hit rate | Home hit rate |
|---|---:|---:|---:|---:|---:|
| raw_dixon_coles | 369 | 0.583988 | 0.983805 | 0.517615 | 0.661247 |
| fusion_beta_0_65 | 369 | 0.585146 | 0.985508 | 0.531165 | 0.628726 |
| market_normalized_hda | 369 | 0.571479 | 0.964961 | 0.550136 | 0.639566 |
| empirical_training_base | 369 | 0.632269 | 1.049615 | 0.490515 | 0.509485 |

Paired ROI: same complete common cohort, one top-probability outcome per match, fixed one-unit stake for every probability source:

| Probability source | Candidate games | Decisions (N) | Excluded: missing probability | Excluded: incomplete prices | Net units | ROI |
|---|---:|---:|---:|---:|---:|---:|
| raw_dixon_coles | 369 | 369 | 0 | 0 | -12.56 | -3.40% |
| fusion_beta_0_65 | 369 | 369 | 0 | 0 | -1.43 | -0.39% |
| market_normalized_hda | 369 | 369 | 0 | 0 | +13.78 | +3.73% |
| empirical_training_base | 369 | 369 | 0 | 0 | +11.03 | +2.99% |

Supplemental EV-threshold strategy: model selects the highest probability-times-B365-price EV only when estimated EV ≥5%; the market baseline tests its probabilities against its own prices and therefore has no positive-EV selection by construction:

| Price/probability strategy | Candidate games | Decisions (N) | Excluded: missing probability | Excluded: incomplete prices | Net units | ROI |
|---|---:|---:|---:|---:|---:|---:|
| raw_dixon_coles | 380 | 219 | 11 | 0 | -44.08 | -20.13% |
| fusion_beta_0_65 | 380 | 293 | 11 | 0 | -13.05 | -4.45% |
| market_normalized_hda | 380 | 0 | 0 | 0 | +0.00 | N/A |
| empirical_training_base | 380 | 319 | 0 | 0 | -29.40 | -9.22% |



## Paired calendar-month block bootstrap 95% CI

Delta is model minus normalized B365 market on the same matches; Brier and Log loss lower is better, hit rate and ROI higher is better.

| Split | Model | Metric | Delta | 95% CI | Valid draws |
|---|---|---|---:|---:|---:|
| validation | raw_dixon_coles | brier | +0.0179 | [+0.0099, +0.0254] | 1000 |
| validation | raw_dixon_coles | log_loss | +0.0247 | [+0.0130, +0.0369] | 1000 |
| validation | raw_dixon_coles | hit_rate | -0.0351 | [-0.0588, -0.0139] | 1000 |
| validation | raw_dixon_coles | paired_top_probability_roi_pct | -6.6702 | [-11.4122, -2.1923] | 1000 |
| validation | fusion_beta_0_65 | brier | +0.0219 | [+0.0066, +0.0392] | 1000 |
| validation | fusion_beta_0_65 | log_loss | +0.0358 | [+0.0094, +0.0661] | 1000 |
| validation | fusion_beta_0_65 | hit_rate | -0.0135 | [-0.0268, +0.0000] | 1000 |
| validation | fusion_beta_0_65 | paired_top_probability_roi_pct | -1.9054 | [-5.3907, +1.3205] | 1000 |
| validation | market_normalized_hda | brier | +0.0000 | [+0.0000, +0.0000] | 1000 |
| validation | market_normalized_hda | log_loss | +0.0000 | [+0.0000, +0.0000] | 1000 |
| validation | market_normalized_hda | hit_rate | +0.0000 | [+0.0000, +0.0000] | 1000 |
| validation | market_normalized_hda | paired_top_probability_roi_pct | +0.0000 | [+0.0000, +0.0000] | 1000 |
| validation | empirical_training_base | brier | +0.0855 | [+0.0581, +0.1097] | 1000 |
| validation | empirical_training_base | log_loss | +0.1200 | [+0.0804, +0.1559] | 1000 |
| validation | empirical_training_base | hit_rate | -0.1000 | [-0.1389, -0.0587] | 1000 |
| validation | empirical_training_base | paired_top_probability_roi_pct | -5.7162 | [-16.5211, +6.8718] | 1000 |
Bootstrap blocks: 10 calendar months; replicates: 1000; seed: 20261013.
| locked_holdout | raw_dixon_coles | brier | +0.0125 | [+0.0049, +0.0205] | 1000 |
| locked_holdout | raw_dixon_coles | log_loss | +0.0188 | [+0.0084, +0.0286] | 1000 |
| locked_holdout | raw_dixon_coles | hit_rate | -0.0325 | [-0.0561, -0.0086] | 1000 |
| locked_holdout | raw_dixon_coles | paired_top_probability_roi_pct | -7.1382 | [-13.4927, -0.7849] | 1000 |
| locked_holdout | fusion_beta_0_65 | brier | +0.0137 | [+0.0019, +0.0257] | 1000 |
| locked_holdout | fusion_beta_0_65 | log_loss | +0.0205 | [+0.0041, +0.0356] | 1000 |
| locked_holdout | fusion_beta_0_65 | hit_rate | -0.0190 | [-0.0358, -0.0028] | 1000 |
| locked_holdout | fusion_beta_0_65 | paired_top_probability_roi_pct | -4.1219 | [-8.7772, +0.1309] | 1000 |
| locked_holdout | market_normalized_hda | brier | +0.0000 | [+0.0000, +0.0000] | 1000 |
| locked_holdout | market_normalized_hda | log_loss | +0.0000 | [+0.0000, +0.0000] | 1000 |
| locked_holdout | market_normalized_hda | hit_rate | +0.0000 | [+0.0000, +0.0000] | 1000 |
| locked_holdout | market_normalized_hda | paired_top_probability_roi_pct | +0.0000 | [+0.0000, +0.0000] | 1000 |
| locked_holdout | empirical_training_base | brier | +0.0608 | [+0.0385, +0.0827] | 1000 |
| locked_holdout | empirical_training_base | log_loss | +0.0847 | [+0.0531, +0.1171] | 1000 |
| locked_holdout | empirical_training_base | hit_rate | -0.0596 | [-0.1120, -0.0125] | 1000 |
| locked_holdout | empirical_training_base | paired_top_probability_roi_pct | -0.7452 | [-15.0527, +12.2219] | 1000 |
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
