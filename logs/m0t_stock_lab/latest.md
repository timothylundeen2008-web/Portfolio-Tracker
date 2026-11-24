# M0-T on ETFs + S&P 500 stocks (trial 99) — m0t_stock_lab 1.1 — 2026-11-24

Pre-registered in `claude/m0t_stock_lab_2026-11-23.md`. Trials 98 → 99. Research, not personalized advice.

## Verdict: **FAIL**

- Fails: 2022-26 PF 1.15 < 1.3; book full CAGR 8.03% <= SPY 14.19%; book 2017-21 CAGR 6.76% <= SPY 18.2%; book 2022-26 CAGR 9.47% <= SPY 10.13%; book max DD -26.59% deeper than -20.0%
- 719 S&P 500 members since 2017, 609 with prices; stock trades' missing-stock stress: neutral 0.25R, harsh 0.146R

| | C1 ETFs + stocks (decision) | ETF only | Stocks only | SPY |
|---|---|---|---|---|
| Book CAGR full | 8.03% | 4.43% | 6.72% | 14.19% |
| Book CAGR 2017-21 | 6.76% | 6.38% | 8.85% | 18.20% |
| Book CAGR 2022-26 | 9.47% | 2.33% | 4.81% | 10.13% |
| Max DD | -26.59% | -13.12% | -26.55% | -33.72% |
| Worst month % | -8.93 | -7.63 | -8.65 | — |
| Months ≤ −10% | 0 | 0 | 0 | — |
| −20% from high breached | True | False | True | — |
| Average invested % | 67.3 | 41.3 | 64.2 | — |
| Trades taken | 198 | 191 | 207 | — |
| … of which stocks | 180 | 0 | 207 | — |

| Trades (closed) | n | Win % | Avg win R | Avg loss R | Expectancy R | PF |
|---|---|---|---|---|---|---|
| C1 ETFs + stocks (decision) full | 7713 | 24.4 | 4.49 | -1.14 | 0.279 | 1.34 |
| C1 ETFs + stocks (decision) 2017-21 | 3881 | 27.6 | 4.4 | -1.15 | 0.43 | 1.55 |
| C1 ETFs + stocks (decision) 2022-26 | 3832 | 21.1 | 4.62 | -1.13 | 0.126 | 1.15 |
| ETF only full | 1105 | 25.2 | 3.42 | -0.83 | 0.305 | 1.55 |
| ETF only 2017-21 | 558 | 27.1 | 3.12 | -0.81 | 0.319 | 1.61 |
| ETF only 2022-26 | 547 | 23.2 | 3.78 | -0.85 | 0.292 | 1.5 |
| Stocks only full | 6608 | 24.3 | 4.68 | -1.19 | 0.274 | 1.32 |
| Stocks only 2017-21 | 3323 | 27.7 | 4.6 | -1.2 | 0.449 | 1.54 |
| Stocks only 2022-26 | 3285 | 20.8 | 4.77 | -1.18 | 0.098 | 1.11 |

**How trades ended (both universes):** closing-basis stop 4001 (-0.17R); disaster stop 3188 (+0.93R); trend: close below falling trail MA 502 (-0.54R); open at end 140 (+2.41R); leveraged 90-day cap 22 (+6.29R)

Ladder restored after the run: yes

*m0t_stock_lab.py 1.1*
