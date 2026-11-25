# XM lab 1.0 — cross-asset momentum in place of the fixed Balanced/Defense books — 2026-11-25

Pre-registered in `claude/xm_lab_2026-11-24.md`. Long-term engine trials 40 → 43. Research, not personalized advice.

## XM (N = 3) inside O11: **FAIL**

- Fails: 2016-26 CAGR 13.52% < O11 14.36% − 0.25; max DD -22.15% deeper than -20.0%
- Neighbours (bars 1–4): XM2: max DD -25.66% deeper than -20.0%; XM4: full CAGR 9.11% not above O11 9.35%; 2005-15 CAGR 4.6% below O11 5.38%; max DD -21.5% deeper than -20.0%
- Guard (XM off reproduces O11 exactly): yes (NAV gap 0.0e+00)

| | O11 | XM3 | XM2 | XM4 | XM3 alone | SPY |
|---|---|---|---|---|---|---|
| CAGR full | 9.35% | 9.54% | 9.94% | 9.11% | 10.15% | 7.99% |
| CAGR 2005-15 | 5.38% | 6.00% | 6.14% | 4.60% | 11.85% | 7.06% |
| CAGR 2016-26 | 14.36% | 13.52% | 14.47% | 14.28% | 9.93% | 14.22% |
| Max DD | -19.34% | -22.15% | -25.66% | -21.50% | -22.46% | -55.19% |
| 2000–02 | -6.76% | -10.05% | -7.96% | -8.11% | -13.26% | -47.52% |
| 2007–09 | -10.20% | -7.03% | -9.53% | -13.17% | 12.59% | -55.19% |
| Covid 2020 | -8.00% | -5.55% | -4.14% | -6.88% | 1.58% | -33.72% |
| 2022 | -10.75% | 6.52% | 14.08% | 4.40% | 9.52% | -24.50% |
| Down years beaten | 6 of 6 | 6 of 6 | 6 of 6 | 6 of 6 | 5 of 6 | — |
| Up years >10 pts behind | 2006, 2015, 2019 | 2006, 2015, 2019 | 2006, 2015, 2019 | 2006, 2015, 2019 | 2015, 2016, 2019, 2023, 2024 | — |
| Losing years | 2000, 2007, 2011, 2015, 2018, 2022 | 2000, 2001, 2006, 2011, 2015, 2022 | 2000, 2001, 2006, 2011, 2015, 2018, 2026 | 2000, 2005, 2006, 2008, 2011, 2015 | 2000, 2001, 2011, 2015, 2016, 2018, 2026 | — |

**What XM3 held when not in Offense (average %):** TLT 15.1, GLD 14.3, IEF 12.7, USD 9.4, CMDTY 7.7, TIPS 6.8, QQQ 6.6, EEM 6.6, EFA 4.8, MF 4.7, IWM 4.7, SPY 3.4, CASH 3.3
**Turnover:** 733.3% of the book a year (one-way).

**Years vs O11 (points):** 2000 -2.8, 2001 -4.2, 2002 +7.5, 2003 +4.7, 2004 +3.2, 2005 +1.1, 2006 -13.7, 2007 +9.0, 2008 +3.8, 2009 -1.3, 2010 +0.6, 2011 -1.0, 2012 +6.0, 2013 +6.0, 2014 +2.9, 2015 -3.1, 2016 -1.8, 2017 +1.0, 2018 +3.0, 2019 -14.1, 2020 +5.1, 2021 +0.7, 2022 +10.9, 2023 -7.8, 2024 +0.7, 2025 -4.6, 2026 -3.8

**Coverage (first year each sleeve could be ranked):** CASH 2000, EEM 2000, EFA 2000, IEF 2000, IWM 2000, SPY 2000, TLT 2000, USD 2000, QQQ 2001, GLD 2002, TIPS 2002, CMDTY 2008, MF 2011

**Latest ranking (2026-11-24):** scores % USD +5.7, MF +4.7, CMDTY +3.2, CASH +1.7, IEF -0.7, TIPS -1.3, SPY -1.4, EFA -1.6, IWM -1.7, TLT -1.9, QQQ -6.1, EEM -7.9, GLD -16.9
- XM3 book: USD 33.3, MF 33.3, CMDTY 33.3 · Defense version: USD 33.3, MF 33.3, CMDTY 33.3

*xm_lab.py 1.0*
