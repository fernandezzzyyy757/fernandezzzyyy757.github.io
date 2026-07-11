# MNQ institutional-footprint backtest

- data: 2026-01-04 18:00:00-05:00 → 2026-07-03 16:59:00-04:00  (179,400 1m bars, 130 sessions)
- signal TF 5min; costs: $0.52/RT/contract + 1 tick slippage per side (charged on every fill); 2 contracts/trade
- train/test split: 70% chronological (train through 2026-05-11)
- bootstrap: 10,000 resamples, 95% CI on expectancy (R); ⚠️ = CI includes zero


## TRAIN

| variant | trades | win% | avg R | exp $ | maxDD $ | PF | expectancy 95% CI (R) | net $ |
|---|---|---|---|---|---|---|---|---|
| A (sweep + FVG only) | 58 | 32.8% | -0.110 | -3.39 | -538.46 | 0.82 | [-0.610, +0.512] ⚠️ | -196.57 |
| B (A + volume-profile confluence) | 12 | 58.3% | -0.025 | +8.86 | -225.62 | 1.37 | [-0.584, +0.556] ⚠️ | +106.27 |
| C (A + delta proxy filter) | 38 | 39.5% | +0.130 | +2.51 | -321.64 | 1.15 | [-0.545, +1.008] ⚠️ | +95.23 |
| D (full stack (B + C)) | 9 | 66.7% | +0.160 | +16.65 | -181.08 | 1.70 | [-0.465, +0.812] ⚠️ | +149.89 |

⚠️ CI includes zero (not statistically distinguishable from breakeven): A, B, C, D

## TEST

| variant | trades | win% | avg R | exp $ | maxDD $ | PF | expectancy 95% CI (R) | net $ |
|---|---|---|---|---|---|---|---|---|
| A (sweep + FVG only) | 18 | 33.3% | -0.303 | -4.19 | -386.23 | 0.81 | [-0.777, +0.216] ⚠️ | -75.47 |
| B (A + volume-profile confluence) | 5 | 20.0% | -0.299 | +8.46 | -144.62 | 1.29 | [-1.128, +0.870] ⚠️ | +42.30 |
| C (A + delta proxy filter) | 14 | 42.9% | -0.088 | +10.51 | -163.57 | 1.80 | [-0.674, +0.528] ⚠️ | +147.19 |
| D (full stack (B + C)) | 4 | 25.0% | -0.119 | +39.09 | -30.58 | 5.94 | [-1.155, +1.097] ⚠️ | +156.34 |

⚠️ CI includes zero (not statistically distinguishable from breakeven): A, B, C, D

## FULL

| variant | trades | win% | avg R | exp $ | maxDD $ | PF | expectancy 95% CI (R) | net $ |
|---|---|---|---|---|---|---|---|---|
| A (sweep + FVG only) | 76 | 32.9% | -0.156 | -3.58 | -691.50 | 0.82 | [-0.546, +0.332] ⚠️ | -272.04 |
| B (A + volume-profile confluence) | 17 | 47.1% | -0.105 | +8.74 | -272.15 | 1.35 | [-0.576, +0.414] ⚠️ | +148.57 |
| C (A + delta proxy filter) | 52 | 40.4% | +0.071 | +4.66 | -321.64 | 1.30 | [-0.461, +0.738] ⚠️ | +242.42 |
| D (full stack (B + C)) | 13 | 53.8% | +0.074 | +23.56 | -181.08 | 2.24 | [-0.481, +0.665] ⚠️ | +306.23 |

⚠️ CI includes zero (not statistically distinguishable from breakeven): A, B, C, D

## Diagnostics (setup funnel per variant)

| variant | setups | window✗ | room✗ | lvn✗ | delta✗ | busy✗ | cap✗ | placed | fill-limit | fill-iFVG | cxl-stop | cxl-ttl | cxl-win | lvn✓ | div✓ | flip✓ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 2113 | 1388 | 279 | 0 | 0 | 304 | 3 | 139 | 57 | 19 | 41 | 8 | 14 | 34 | 50 | 24 |
| B | 2113 | 1388 | 282 | 330 | 0 | 79 | 0 | 34 | 7 | 10 | 11 | 2 | 4 | 34 | 140 | 49 |
| C | 2113 | 1388 | 279 | 0 | 207 | 146 | 3 | 90 | 40 | 12 | 23 | 6 | 9 | 81 | 75 | 24 |
| D | 2113 | 1388 | 282 | 330 | 59 | 32 | 0 | 22 | 5 | 8 | 6 | 1 | 2 | 81 | 149 | 49 |
