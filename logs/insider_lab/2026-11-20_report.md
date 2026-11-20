# Insider lab 1.0 — 2026-11-20

Track B: insider cluster buying. Rules and bar fixed before the run (claude/insider_lab_2026-11-20.md). Research, not personalized advice.

## Verdict: **FAIL** — 2006-15: profit factor 1.15 < 1.3; 2016-26: mean excess vs SPY -0.12% ≤ 0 · **NOT STABLE**

Counting buys: 10230; cluster signals: 573 (573 from 2006).

| Hold | Trades | 2006–15 exp R / PF | 2016–26 exp R / PF | Excess vs SPY 06–15 / 16–26 | Win % | Harsh stress exp R |
|---|---|---|---|---|---|---|
| 60 sessions (decision) | 413 | 0.079 / 1.15 (n 199) | 0.222 / 1.46 (n 214) | 2.67% (t 1.48) / -0.12% (t -0.11) | 49.9 | -0.148 |
| 40 sessions | 417 | 0.065 / 1.15 (n 200) | 0.167 / 1.45 (n 217) | 1.88% (t 1.35) / -1.25% (t -1.56) | 54.0 | -0.14 |
| 90 sessions | 408 | 0.105 / 1.18 (n 199) | 0.239 / 1.45 (n 209) | 2.86% (t 1.62) / -1.51% (t -1.24) | 47.3 | -0.154 |

Signal outcomes (60-session hold): {'no price data': 125, 'ok': 425, 'no price at entry': 23, 'overlap': 12}. Unpriced signals from 2006 (stressed): 148; neutral expectancy 0.113R, harsh -0.148R (PF 0.76).

## Book (reported, not judged): 10% positions, up to 10, idle cash in T-bills

| Book | CAGR 2006–26 | 2006–15 | 2016–26 | Max DD |
|---|---|---|---|---|
| Insider 60-session | 6.44% | 5.56% | 7.25% | -47.8% |
| Insider 40-session | 3.62% | 2.7% | 4.44% | -48.4% |
| Insider 90-session | 4.98% | 3.86% | 6.04% | -56.3% |
| SPY | 10.64% | 7.05% | 14.19% | -55.2% |

Live swing reference: M0 on ETFs with T-bill idle cash backtests at 2.94% a year (ROT3 lab, 2005–26).

## Notes

- 217 of 293 signal companies have free (Yahoo) prices; the rest are stressed per signal.

Trials: 3 new (swing 84 → 87).

*insider_lab.py 1.0*
