# ROT3 lab 1.0 — 2026-11-20

Track D. Rules and bars fixed before the run (claude/rot3_lab_2026-11-20.md). No tuning after it. Research, not personalized advice.

## Use A — ROT3 as O11's Offense book (long-term)

**Verdict: FAIL** — 2005-15 CAGR 4.49% ≤ O11 5.38%; 2016-26 CAGR 10.19% ≤ O11 14.4%

| Book | CAGR 2000–26 | 2005–15 | 2016–26 | Max DD | Sharpe |
|---|---|---|---|---|---|
| ROT3-engine | 6.83% | 4.49% | 10.19% | -19.3% | 0.60 |
| O11 | 9.36% | 5.38% | 14.40% | -19.3% | 0.79 |
| ROT3 alone | 7.49% | 6.93% | 12.07% | -40.8% | 0.52 |
| SPY | 7.98% | 7.06% | 14.19% | -55.2% | 0.50 |
| QQQ | 8.09% | 10.80% | 18.54% | -83.0% | 0.42 |

Engine time in each state (2000+): {'OFF': 55.3, 'DEF': 25.6, 'OUT': 14.1, 'BAL': 4.9}; fast exits: 46.
O11 reproduced: 9.36% / 5.38% / 14.40%, max DD -19.3% (offense lab with C3: 9.55 / 5.38 / 14.90, −19.3).

Stability (8- and 12-month trend average): 8-month: 2005-15 CAGR 4.28% ≤ O11 5.38%; 2016-26 CAGR 9.87% ≤ O11 14.4%; max DD -20.65% deeper than −20%; 12-month: 2016-26 CAGR 10.19% ≤ O11 14.4% → **NOT STABLE**

Calendar years, ROT3-engine minus O11 (points): 2000 -11.3, 2001 +0.0, 2002 -1.3, 2003 +0.3, 2004 +2.0, 2005 +13.9, 2006 +1.7, 2007 +1.4, 2008 +1.5, 2009 -9.0, 2010 -4.9, 2011 +0.7, 2012 -8.2, 2013 -2.9, 2014 -6.4, 2015 -0.1, 2016 -7.9, 2017 -5.7, 2018 +0.1, 2019 -3.8, 2020 +1.0, 2021 -17.1, 2022 +0.0, 2023 -6.5, 2024 -9.5, 2025 +0.3, 2026 +1.5

Latest ROT3 picks (month-end 2026-10-30): XLE 33%, XLV 33%, XLK 33%

## Use B — ROT3 for the swing book's idle cash

Same 4453 M0 ETF trades (stop B, SPY > 200-day filter) in both books. Window from 2005-04-12.

| Idle cash | CAGR full | 2005–15 | 2016–26 | Max DD | Avg in idle fund | Verdict |
|---|---|---|---|---|---|---|
| T-bills | 2.94% | 2.92% | 3.00% | -11.6% | — | baseline |
| ROT3 (10-month trend) | 7.95% | 6.38% | 9.69% | -24.9% | 63.7% | FAIL |
| ROT3 (8-month trend), stability | 7.04% | 5.78% | 8.47% | -28.9% | 63.7% | misses |
| ROT3 (12-month trend), stability | 7.95% | 7.23% | 8.83% | -34.3% | 63.7% | misses |
| SPY buy & hold | 10.66% | 7.34% | 14.19% | -55.2% | — | reference |

**Verdict: FAIL** — max DD -24.94% deeper than −20% (stand-down)
Stability: **NOT STABLE**.

Trials this run: 6 (long-term engine 28 → 31, swing 81 → 84).

*rot3_lab.py 1.0*
