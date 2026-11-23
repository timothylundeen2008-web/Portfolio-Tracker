# M0-T at 2% risk (trial 98) — m0t2_lab 1.0 — 2026-11-23

Pre-registered in `claude/m0t2_lab_2026-11-23.md`. Trials 97 → 98. Research, not personalized advice.

## Verdict: **FAIL**

- Fails: book full CAGR 5.34% <= SPY 10.7%; book 2005-15 CAGR 5.36% <= SPY 7.34%; book 2016-26 CAGR 5.45% <= SPY 14.27%; book max DD -21.43% deeper than -20.0%

| | M0-T 2% (test) | M0-T 1% (live setting) | SPY |
|---|---|---|---|
| Book CAGR full | 5.34% | 3.79% | 10.70% |
| Book CAGR 2005-15 | 5.36% | 3.81% | 7.34% |
| Book CAGR 2016-26 | 5.45% | 3.84% | 14.27% |
| Book max DD | -21.43% | -11.92% | -55.19% |
| Worst month % | -7.09 | -5.07 | — |
| Months ≤ −10% | 0 | 0 | — |
| −20% from high breached | True | False | — |
| Average invested % | 58.9 | 36.5 | — |
| Max open risk % | 5.09 | 3.17 | — |
| Trades taken | 382 | 382 | — |
| Median risk at entry % | 0.5 | 0.46 | — |
| Entries held below 80% of intended risk (caps), % | 81.9 | 66.2 | — |

| Trades (closed, filtered — identical at any risk) | n | Win % | Avg win R | Avg loss R | Expectancy R | PF |
|---|---|---|---|---|---|---|
| full | 2101 | 28.4 | 3.4 | -0.81 | 0.438 | 1.83 |
| 2005-15 | 893 | 30.8 | 3.14 | -0.78 | 0.469 | 1.94 |
| 2016-26 | 1208 | 26.6 | 3.62 | -0.83 | 0.416 | 1.76 |

| Trades the book actually took | n | Expectancy R | PF |
|---|---|---|---|
| 2% | 379 | 0.505 | 2.02 |
| 1% | 379 | 0.505 | 2.02 |

Reference check: the 1% column should match trial 97's M0-T (3.79% / −11.92% on 2026-11-23 prices).
Risk settings restored after the run: yes

*m0t2_lab.py 1.0*
