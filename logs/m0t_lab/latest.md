# M0-T lab 1.0 — 2026-11-23

Pre-registered in `claude/m0t_lab_2026-11-23.md`. Trials 96 → 97. Research, not personalized advice.

## M0-T (no sector-rotation exit, no ladder trims): **FAIL**

- Fails: book full CAGR 3.79% <= SPY 10.7%; book 2005-15 CAGR 3.81% <= SPY 7.34%; book 2016-26 CAGR 3.84% <= SPY 14.27%
- Guard — the resimulation reproduces live M0 exactly with both rules on: yes

| | M0-T | M0 (live rule) | SPY |
|---|---|---|---|
| Book CAGR full | 3.79% | 2.89% | 10.70% |
| Book CAGR 2005-15 | 3.81% | 2.83% | 7.34% |
| Book CAGR 2016-26 | 3.84% | 2.99% | 14.27% |
| Book max DD | -11.92% | -11.59% | -55.19% |
| Average invested | 36.5 | 34.3 | — |
| Trades taken by the $10k book | 382 | 1227 | — |
| Median hold (sessions) | 17.0 | 1.0 | — |
| Months ≤ −10% | 0 | 0 | — |

| Trades (closed, filtered) | n | Win % | Avg win R | Avg loss R | Expectancy R | PF |
|---|---|---|---|---|---|---|
| M0-T full | 2101 | 28.4 | 3.4 | -0.81 | 0.438 | 1.83 |
| M0-T 2005-15 | 893 | 30.8 | 3.14 | -0.78 | 0.469 | 1.94 |
| M0-T 2016-26 | 1208 | 26.6 | 3.62 | -0.83 | 0.416 | 1.76 |
| M0 full | 4449 | 32.9 | 1.06 | -0.59 | 0.126 | 1.57 |
| M0 2005-15 | 1953 | 33.5 | 1.07 | -0.55 | 0.155 | 1.78 |
| M0 2016-26 | 2496 | 32.4 | 1.05 | -0.62 | 0.104 | 1.43 |

**Diagnostics (report only, not trials):**
- Rotation exit removed only: book 3.61%, expectancy 0.374R
- Ladder removed only: book 3.52%, expectancy 0.153R
- M0 baseline recorded 2026-11-20: 2.94%/yr; this run: 2.89%

**How M0-T trades ended:** closing-basis stop 891 (+0.10R); disaster stop 830 (+0.95R); trend: close below falling trail MA 340 (-0.55R); leveraged 90-day cap 40 (+5.74R); open at end 3 (+0.92R)

*m0t_lab.py 1.0*
