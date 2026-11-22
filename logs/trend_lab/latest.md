# Trend lab 1.0 — 2026-11-22

Pre-registered in `claude/trend_lab_2026-11-21.md`. Trials 94 → 96. Synthetic 3× and inverse 3× funds (checked against real ones below). Research, not personalized advice.

## S3 — leveraged trend (3× SPY / QQQ sleeves): **FAIL**

- Fails: 2000-12 expectancy -0.04% <= 0; book full CAGR 6.22% <= SPY 7.83%; book 2000-12 CAGR 0.78% <= SPY 1.68%; book 2013-26 CAGR 11.32% <= SPY 13.73%; book max DD -38.9% deeper than -30.0%; worst 2-session book loss -15.3% < -15.0%; worst year -22.2% < -20.0%
- Trades 220 · expectancy +2.7% per trade (3× position) · PF 1.65 · win +35% · avg win +20% / avg loss -7% (payoff 3.00) · wins ≥ +25%: +28% of wins · mean sleeve size 30% of equity
- By index: SPY n 105, exp +2.0%, payoff 3.00; QQQ n 115, exp +3.4%, payoff 2.96
- Worst 1-session / 2-session book loss -10.5% / -15.3% · worst year -22.2% · −20% high-water stops 4
- ROBUST (financing ×2, +10bp a side): CAGR 5.33% → no · STABLE (neighbours beating SPY): 0 of 6
- 2000-12: n 96, expectancy -0.0%, PF 0.99
- 2013-26: n 124, expectancy +4.9%, PF 2.38

| Book | CAGR | Max DD | SPY CAGR | SPY max DD |
|---|---|---|---|---|
| full | 6.22% | -38.9% | 7.83% | -55.2% |
| 2000-12 | 0.78% | -26.6% | 1.68% | -55.2% |
| 2013-26 | 11.32% | -38.9% | 13.73% | -33.7% |

| Neighbour | CAGR | Max DD |
|---|---|---|
| sma_long 150 | 5.57% | -41.0% |
| sma_long 250 | 4.96% | -36.9% |
| vol_target 0.1 | 4.99% | -30.1% |
| vol_target 0.2 | 7.18% | -41.0% |
| trail 0.15 | 7.07% | -39.2% |
| trail 0.25 | 6.61% | -38.9% |

## S4 — bear failed rally, inverse 3×: **FAIL**

- Fails: 2013-26 expectancy -4.75% <= 0; PF 1.30 < 1.5; book max DD -25.6% deeper than -15.0%; 2013-26 book only -1.20 pts over T-bills (< 1.0)
- Trades 53 · expectancy +2.0% per trade · PF 1.30 · win +32% · avg win +27% / avg loss -10% (payoff 2.75) · wins ≥ +25%: +65% of wins
- Worst trade -4.3% of equity · −20% high-water stops 1
- ROBUST (spreads ×2, 60bp stop slippage): expectancy +1.6% → yes · STABLE (neighbours with positive expectancy): 6 of 6
- 2000-12: n 40, expectancy +4.2%, PF 1.69
- 2013-26: n 13, expectancy -4.7%, PF 0.43

| Book (25% per trade) | CAGR | Max DD | T-bill CAGR |
|---|---|---|---|
| full | 2.68% | -25.6% | 1.95% |
| 2000-12 | 4.93% | -18.7% | 2.10% |
| 2013-26 | 0.61% | -11.9% | 1.81% |

| Neighbour | Trades | Expectancy | PF |
|---|---|---|---|
| touch 0.98 | 56 | +3.8% | 1.60 |
| touch 1.0 | 41 | +3.3% | 1.57 |
| target 0.08 | 53 | +1.4% | 1.21 |
| target 0.12 | 52 | +3.9% | 1.57 |
| stop_band 1.01 | 58 | +0.5% | 1.08 |
| stop_band 1.03 | 48 | +0.2% | 1.02 |

## S3 + S4 together (report only)

- CAGR 7.02%, max DD -42.2%, worst 2 sessions -15.3% · 2000-12 3.63%; 2013-26 10.03% · SPY 7.83% / -55.2%

## Synthetic vs real funds (calendar years, synthetic − real)

- UPRO: {'years': 18, 'mean_diff_pts': 0.16, 'worst_diff_pts': 3.05, 'daily_corr': 0.9983}
- TQQQ: {'years': 17, 'mean_diff_pts': 0.0, 'worst_diff_pts': 2.47, 'daily_corr': 0.999}
- SPXU: {'years': 18, 'mean_diff_pts': -0.87, 'worst_diff_pts': 2.76, 'daily_corr': 0.9982}
- SQQQ: {'years': 17, 'mean_diff_pts': -0.34, 'worst_diff_pts': 3.22, 'daily_corr': 0.9988}

## Today (paper only, not a trade)

- SPY 2026-11-20: -5.54% vs 200-day (rising), -9.24% vs 50-day · S3 ON: no · S4 bear state: no
- QQQ 2026-11-20: -10.79% vs 200-day (rising), -14.41% vs 50-day · S3 ON: no · S4 bear state: no

*trend_lab.py 1.0*
