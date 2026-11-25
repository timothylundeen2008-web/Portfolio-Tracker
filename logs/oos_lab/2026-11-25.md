# OOS lab 1.1.2 — out-of-sample replay 1963–1999 — 2026-11-25

Pre-registered in `claude/oos_lab_2026-11-25.md`. Long-term engine trials 43 → 47. Research, not personalized advice.

## Engine (O11-R vs the market): **FAIL**
- Fails: beat the market in 5 of 8 down years
- Time in each state (1963–99): OFF 53%, DEF 24%, OUT 22%, BAL 1%

## XM (N = 3) vs O11-R: **FAIL**
- Fails: full CAGR 11.75% not above O11-R 12.0%; 1982-99 CAGR 13.46% < O11-R 14.1% − 0.25; max DD -22.33% deeper than -20.0%; beat the market in 6 of 8 down years
- Neighbours (bars X1–X3): XM2-R: 1982-99 CAGR 13.11% < O11-R 14.1% − 0.25; max DD -20.22% deeper than -20.0%; XM4-R: full CAGR 11.7% not above O11-R 12.0%; 1982-99 CAGR 13.67% < O11-R 14.1% − 0.25

| | O11-R | XM3-R | XM2-R | XM4-R | 60/40 | Market |
|---|---|---|---|---|---|---|
| CAGR 1963–99 | 12.00% | 11.75% | 12.04% | 11.70% | 10.75% | 12.73% |
| CAGR 1963–81 | 10.05% | 10.15% | 11.04% | 9.87% | 6.49% | 8.16% |
| CAGR 1982–99 | 14.10% | 13.46% | 13.11% | 13.67% | 15.42% | 17.77% |
| Max DD | -17.90% | -22.33% | -20.22% | -17.62% | -31.88% | -48.16% |
| 1966 bear | -3.94% | -3.38% | -3.47% | -3.35% | -11.95% | -19.79% |
| 1969–70 bear | -8.02% | -11.07% | -15.27% | -8.90% | -25.90% | -36.45% |
| 1973–74 bear | 15.49% | 34.55% | 52.00% | 26.58% | -31.64% | -47.86% |
| 1977–81 inflation | 37.89% | 36.39% | 35.44% | 39.51% | 40.49% | 66.45% |
| 1987 crash | -15.08% | -20.22% | -15.50% | -16.13% | -19.85% | -32.56% |
| 1990 bear | -4.29% | -5.35% | -7.25% | -4.39% | -13.10% | -20.48% |
| Down years beaten | 5 of 8 | 6 of 8 | 5 of 8 | 6 of 8 | 7 of 8 | 0 of 8 |
| Up years >10 pts behind | 5 | 4 | 5 | 5 | 4 | 0 |
| Losing years | 1966, 1969, 1977, 1981, 1990, 1994 | 1966, 1969, 1977, 1990, 1994 | 1966, 1969, 1977, 1990, 1994 | 1966, 1969, 1977, 1990, 1994 | 1966, 1969, 1973, 1974, 1977, 1990, 1994 | 1966, 1969, 1973, 1974, 1977, 1981, 1990, 1994 |

## Data checks (N89)
- French market vs Yahoo SPY, daily 1994–99: correlation 0.954, mean |difference| 23.2 bp over 1515 days
- SPY (Yahoo): 2000-01-05 +0.18%, 2000-01-06 -1.61%, 2000-01-07 +5.81%
- ^GSPC: 2000-01-05 +0.19%, 2000-01-06 +0.10%, 2000-01-07 +2.71%
- QQQ (Yahoo): 2000-01-05 -2.55%, 2000-01-06 -6.87%, 2000-01-07 +12.37%
- French market: 2000-01-05 -0.07%, 2000-01-06 -0.72%, 2000-01-07 +3.23%

*oos_lab.py 1.1.2*
