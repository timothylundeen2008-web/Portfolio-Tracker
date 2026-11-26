# Capacity lab 1.0.2 — M0-T with leveraged twins — 2026-11-26

Pre-registered in `claude/cap_lab_2026-11-25.md`. Swing trials 99 → 104. Research, not personalized advice.

## K3 (twins, 8 slots): **FAIL**
- Fails: full CAGR 3.81% <= SPY 10.66%; 2005-15 CAGR 5.72% <= SPY 7.34%; 2016-26 CAGR 2.08% <= SPY 14.18%; max DD -21.03% not shallower than -20.0%; the −20% high-water stop triggered; 1 month(s) at −10% or worse (worst -12.02%); 2016-26 trade PF 0.51 < 1.3
- Neighbours (beat SPY full, DD > −20%): K3-6: full CAGR 4.53% <= SPY 10.66%; K3-10: full CAGR 1.97% <= SPY 10.66%; max DD -21.49% not shallower than -20.0%
- Guard (k = 1 transform reproduces K0): max gap $0.000000
- Window 2005-04-12 → 2026-11-25; M0-T trades (SPY above its 200-day): 2105; twins used: DIA~UDOW, EEM~EDC, EFA~EFO, GDX~NUGT, GLD~UGL, IBB~BIB, ITA~DFEN, ITB~NAIL, IYT~TPOR, KRE~DPST, MDY~MIDU, SLV~AGQ, TLT~TMF, XBI~LABU, XHB~NAIL, XLB~UYM, XLC~LTL, XLE~ERX, XLI~DUSL, XLP~UGE, XLRE~DRN, XLU~UTSL, XLV~CURE, XLY~WANT, XOP~GUSH, XRT~RETL

| | K3 | K3-6 | K3-10 | K1 | K2 | K0 | SPY |
|---|---|---|---|---|---|---|---|
| CAGR 2005–26 | 3.81% | 4.53% | 1.97% | 5.64% | 3.46% | 3.63% | 10.66% |
| CAGR 2005–15 | 5.72% | 4.65% | 1.63% | 6.01% | 3.21% | 3.32% | 7.34% |
| CAGR 2016–26 | 2.08% | 4.51% | 2.31% | 5.37% | 3.78% | 4.01% | 14.18% |
| Max DD | -21.03% | -18.08% | -21.49% | -18.97% | -14.26% | -12.30% | -55.19% |
| Trades taken / year | 16.0 | 26.7 | 7.0 | 33.5 | 17.8 | 17.8 | |
| … per week | 0.31 | 0.51 | 0.14 | 0.64 | 0.34 | 0.34 | |
| Avg open positions | 2.79 | 4.29 | 1.38 | 5.5 | 2.94 | 2.94 | |
| Avg invested % | 19.6 | 30.3 | 9.1 | 60.2 | 22.1 | 35.3 | |
| Worst month | -12.02 | -11.95 | -18.9 | -10.12 | -6.87 | -5.83 | |
| Months ≤ −10% | 1 | 1 | 1 | 1 | 0 | 0 | |
| −20% stop triggered | True | False | True | False | False | False | |
| Worst losing run | 51 | 41 | 10 | 50 | 23 | 23 | |
| Signals skipped % | 83.6 | 72.5 | 92.8 | 65.6 | 81.7 | 81.7 | |
| 2008 | -8.41% | -7.02% | -8.51% | -6.87% | -6.82% | -5.79% | |
| 2020 | 0.34% | 2.23% | 0.34% | 1.40% | 1.13% | 0.87% | |
| 2022 | 1.99% | -6.72% | 1.99% | -5.20% | -2.79% | -1.94% | |
| Trade PF 2005-15 | 2.03 | 1.92 | 1.94 | 2.12 | 1.88 | 1.89 | |
| Expectancy 2005-15 (R) | 0.511 | 0.469 | 0.416 | 0.544 | 0.474 | 0.461 | |
| Trade PF 2016-26 | 0.51 | 1.71 | None | 1.81 | 1.8 | 2.09 | |
| Expectancy 2016-26 (R) | -0.343 | 0.374 | None | 0.398 | 0.403 | 0.506 | |

Trade PF and expectancy are on the trades each book took (twin-expressed, net of costs). Shared-backtest note: an order rejected for cash or heat still uses up a slot (as in trial 97; works against capacity).

Twins are modelled (k × daily return − fee − borrowing), not real price histories. K0 = M0-T reference with the swing limits on (not a trial).

*cap_lab.py 1.0.2*
