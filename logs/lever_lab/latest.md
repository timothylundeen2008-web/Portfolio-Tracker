# Lever lab 1.2 — 2026-11-21

Pre-registered in `claude/lever_lab_2026-11-21.md`. Trials 91 → 94. Option values are Black-Scholes MODEL prices (no historical option data). Research, not personalized advice.

## S1a — mirror the M0 trade: **FAIL**

- Fails: 2005-15 expectancy -0.008 <= 0; 2005-15 PF 0.91 < 1.3; 2016-26 expectancy -0.017 <= 0; 2016-26 PF 0.83 < 1.3; payoff 1.62 < 2.0; book full CAGR -1.79% <= SPY 10.29%; book 2005-15 CAGR -0.25% <= SPY 7.06%; book 2016-26 CAGR -3.32% <= SPY 13.80%; book max DD -38.7% deeper than -30.0%
- Trades 4062 · expectancy -1.3% of premium · PF 0.86 · win +35% · avg win +24% / avg loss -15% (payoff 1.62) · wins ≥ +25%: +26% of wins · median hold 1 sessions
- 2005-15: n 1815, expectancy -0.8%, PF 0.91; harsh stress expectancy -13.0%
- 2016-26: n 2247, expectancy -1.7%, PF 0.83; harsh stress expectancy -14.1%
- ROBUST (harsh stress > 0 both halves): no · STABLE (neighbours beating SPY): 0 of 4

| Book (affordable funds, 5% premium, max 4) | CAGR | Max DD | SPY CAGR |
|---|---|---|---|
| full | -1.79% | -38.7% | 10.29% |
| 2005-15 | -0.25% | -12.2% | 7.06% |
| 2016-26 | -3.32% | -33.8% | 13.80% |

- Same book on every M0 fund (fractional contracts, not buyable at $10k): CAGR -5.92%, max DD -78.8%
- Times the live −20% high-water stop would have halted the book: 1

**Delta sweep (report only — not a bar, not a trial; each delta has its own affordable funds):**

| Delta | Trades | Expectancy | PF | Payoff | Wins ≥ +25% | Affordable funds | Book CAGR | Book max DD | Every-fund CAGR |
|---|---|---|---|---|---|---|---|---|---|
| 0.50 | 4062 | -1.9% | 0.84 | 1.48 | +27% | 12 | -7.49% | -84.2% | -10.02% |
| 0.60 | 4062 | -1.5% | 0.86 | 1.56 | +27% | 5 | -3.08% | -58.7% | -7.26% |
| 0.70 | 4062 | -1.3% | 0.86 | 1.62 | +26% | 3 | -1.79% | -38.7% | -5.92% |
| 0.75 | 4062 | -1.4% | 0.85 | 1.64 | +26% | 2 | -0.47% | -25.9% | -5.73% |
| 0.80 | 4062 | -1.5% | 0.83 | 1.67 | +26% | 1 | 0.58% | -21.1% | -5.85% |
| 0.90 | 4062 | -1.8% | 0.75 | 1.62 | +26% | 0 | 1.79% | -0.0% | -7.02% |

## S1b — option-native exits: **FAIL**

- Fails: 2016-26 PF 1.03 < 1.3; payoff 1.56 < 2.0; book full CAGR 0.55% <= SPY 10.29%; book 2005-15 CAGR 4.56% <= SPY 7.06%; book 2016-26 CAGR -3.36% <= SPY 13.80%; book max DD -45.9% deeper than -30.0%
- Trades 4062 · expectancy +3.6% of premium · PF 1.17 · win +43% · avg win +57% / avg loss -37% (payoff 1.56) · wins ≥ +25%: +75% of wins · median hold 26 sessions
- 2005-15: n 1815, expectancy +7.4%, PF 1.38; harsh stress expectancy -5.4%
- 2016-26: n 2247, expectancy +0.6%, PF 1.03; harsh stress expectancy -11.9%
- ROBUST (harsh stress > 0 both halves): no · STABLE (neighbours beating SPY): 0 of 4

| Book (affordable funds, 5% premium, max 4) | CAGR | Max DD | SPY CAGR |
|---|---|---|---|
| full | 0.55% | -45.9% | 10.29% |
| 2005-15 | 4.56% | -25.4% | 7.06% |
| 2016-26 | -3.36% | -40.4% | 13.80% |

- Same book on every M0 fund (fractional contracts, not buyable at $10k): CAGR 2.19%, max DD -55.5%
- Times the live −20% high-water stop would have halted the book: 2

**Delta sweep (report only — not a bar, not a trial; each delta has its own affordable funds):**

| Delta | Trades | Expectancy | PF | Payoff | Wins ≥ +25% | Affordable funds | Book CAGR | Book max DD | Every-fund CAGR |
|---|---|---|---|---|---|---|---|---|---|
| 0.50 | 4062 | -1.0% | 0.96 | 1.60 | +80% | 12 | -5.43% | -85.9% | -8.30% |
| 0.60 | 4062 | +1.9% | 1.08 | 1.59 | +77% | 5 | 0.08% | -65.4% | -1.75% |
| 0.70 | 4062 | +3.6% | 1.17 | 1.56 | +75% | 3 | 0.55% | -45.9% | 2.19% |
| 0.75 | 4062 | +3.9% | 1.20 | 1.52 | +73% | 2 | 1.73% | -31.2% | 3.93% |
| 0.80 | 4062 | +3.9% | 1.22 | 1.47 | +71% | 1 | 2.89% | -21.7% | 3.83% |
| 0.90 | 4062 | +3.0% | 1.21 | 1.37 | +64% | 0 | 1.79% | -0.0% | 3.48% |

Reference — the same M0 trades in shares: n 4062, expectancy +0.112R, PF 1.48.

Affordable funds (one 0.70-delta, 60-day call ≤ 5% of $10,000 today): XLB, XLRE, XLU

| Fund | Price | IV % | One contract $ | % of $10k |
|---|---|---|---|---|
| XLU | 42.69 | 32.1 | 367 | 3.7 |
| XLRE | 42.46 | 33.0 | 380 | 3.8 |
| XLB | 48.34 | 36.3 | 471 | 4.7 |
| TLT | 81.45 | 22.7 | 509 | 5.1 |
| XLF | 54.57 | 36.0 | 520 | 5.2 |
| KRE | 68.32 | 37.3 | 672 | 6.7 |
| SLV | 36.97 | 87.9 | 747 | 7.5 |
| EEM | 53.84 | 55.7 | 751 | 7.5 |
| XLE | 60.51 | 52.2 | 799 | 8.0 |
| ITA | 66.17 | 46.8 | 807 | 8.1 |
| EFA | 96.14 | 33.6 | 860 | 8.6 |
| XLP | 90.46 | 36.6 | 875 | 8.7 |
| IYT | 78.62 | 44.6 | 918 | 9.2 |
| XRT | 86.49 | 52.8 | 1,169 | 11.7 |
| XLC | 100.03 | 44.8 | 1,174 | 11.7 |
| XLY | 112.46 | 45.2 | 1,311 | 13.1 |
| XME | 80.3 | 74.4 | 1,443 | 14.4 |
| XHB | 96.6 | 61.7 | 1,491 | 14.9 |
| IGV | 91.66 | 66.3 | 1,500 | 15.0 |
| GDX | 68.4 | 99.8 | 1,522 | 15.2 |
| ITB | 91.15 | 70.4 | 1,568 | 15.7 |
| XLI | 156.37 | 40.0 | 1,636 | 16.4 |
| XLV | 177.24 | 38.3 | 1,782 | 17.8 |
| XBI | 140.18 | 68.2 | 2,347 | 23.5 |
| XLK | 149.01 | 70.3 | 2,521 | 25.2 |
| XOP | 168.06 | 63.6 | 2,620 | 26.2 |
| IWM | 256.61 | 40.2 | 2,698 | 27.0 |
| IBB | 199.54 | 54.5 | 2,773 | 27.7 |
| DIA | 481.08 | 33.0 | 4,240 | 42.4 |
| GLD | 322.87 | 52.4 | 4,275 | 42.7 |
| OIH | 329.73 | 71.7 | 5,756 | 57.6 |
| MDY | 626.03 | 34.9 | 5,890 | 58.9 |
| SPY | 689.81 | 35.9 | 6,552 | 65.5 |
| QQQ | 608.45 | 56.0 | 8,521 | 85.2 |
| SMH | 400.06 | 104.6 | 9,222 | 92.2 |

## S2 — washout snapback, 3× index fund: **FAIL**

- Fails: PF 1.25 < 1.5; payoff 1.13 < 2.0; 2000-12 book 1.96% is only -0.14 pts over T-bills (< 2.0); 2013-26 book 3.20% is only +1.38 pts over T-bills (< 2.0); book max DD -22.0% deeper than -20.0%; worst trade -12.8% of equity < -8.0%; worst calendar year -13.2% < -10.0%
- Trades 38 · expectancy +2.1% per trade (on the 3× position) · PF 1.25 · win +53% · avg win +20% / avg loss -18% (payoff 1.13) · wins ≥ +25%: +35% of wins
- Worst trade -12.8% of equity · worst calendar year -13.2% · −20% high-water stops: 2
- ROBUST (spreads ×2, stop slippage 60bp): expectancy +1.9% → yes · STABLE (neighbours with positive expectancy): 8 of 8
- 2000-12: n 18, expectancy +0.7%, PF 1.07
- 2013-26: n 20, expectancy +3.4%, PF 1.49

| Book (35% per trade, T-bills idle) | CAGR | Max DD | T-bill CAGR |
|---|---|---|---|
| full | 2.60% | -22.0% | 1.95% |
| 2000-12 | 1.96% | -20.2% | 2.10% |
| 2013-26 | 3.20% | -22.0% | 1.81% |

| Episode | Trades | Expectancy | Win |
|---|---|---|---|
| 2000–02 | 6 | -4.1% | +33% |
| 2008–09 | 6 | +4.8% | +50% |
| 2020 | 4 | -9.7% | +25% |
| 2022 | 5 | +3.8% | +60% |

| Neighbour | Trades | Expectancy | PF |
|---|---|---|---|
| z -2.0 | 59 | +2.7% | 1.34 |
| z -3.0 | 28 | +3.7% | 1.44 |
| vix 20.0 | 45 | +0.8% | 1.10 |
| vix 30.0 | 30 | +3.9% | 1.51 |
| target 0.06 | 39 | +2.8% | 1.34 |
| target 0.1 | 38 | +2.2% | 1.28 |
| stop 0.02 | 40 | +5.2% | 1.82 |
| stop 0.04 | 35 | +1.0% | 1.11 |

- Synthetic 3× vs real funds (calendar years, synthetic − real): UPRO {'years': 18, 'mean_diff_pts': 0.16, 'worst_diff_pts': 3.05, 'daily_corr': 0.9983}; TQQQ {'years': 17, 'mean_diff_pts': 0.0, 'worst_diff_pts': 2.47, 'daily_corr': 0.999}
- Today (paper only, not a trade): SPY z -4.43 with VIX 35.89 on 2026-11-20; QQQ z -3.46 with VIX 35.89 on 2026-11-20

*lever_lab.py 1.2*
