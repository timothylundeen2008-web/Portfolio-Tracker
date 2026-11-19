# EDGAR data 1.1 — 2026-11-19

Shared SEC data for tracks A and B, with the probe's fixes (company number by date, renamed and bankrupt members, officers and directors only, Q4 derived).

## Mapping (gate 95% of member-days every year): **PASS**

| Year | Member-days | Mapped % |
|---|---|---|
| 2006 | 124746 | 99.3 |
| 2007 | 124744 | 99.4 |
| 2008 | 125841 | 99.3 |
| 2009 | 125690 | 99.3 |
| 2010 | 125537 | 99.2 |
| 2011 | 125242 | 99.1 |
| 2012 | 124242 | 99.2 |
| 2013 | 125241 | 99.1 |
| 2014 | 125534 | 99.1 |
| 2015 | 126147 | 99.1 |
| 2016 | 127356 | 99.1 |
| 2017 | 126995 | 99.2 |
| 2018 | 126917 | 99.2 |
| 2019 | 127260 | 99.0 |
| 2020 | 127767 | 99.0 |
| 2021 | 127260 | 99.2 |
| 2022 | 126437 | 98.8 |
| 2023 | 125750 | 99.1 |
| 2024 | 126757 | 99.2 |
| 2025 | 125752 | 99.2 |
| 2026 | 30683 | 99.2 |

Member-months by method: {'end-of-membership company': 1739, 'not an SEC filer': 69, 'override': 24, 'pinned': 243, 'rename: end-of-membership company': 21, 'rename: ticker at the time': 773, 'ticker at the time': 117053, 'unmapped': 953, 'was BHI: ticker at the time': 138, 'was CBG: ticker at the time': 136, 'was GM: ticker at the time': 42, 'was GOOG: ticker at the time': 114, 'was HCN: ticker at the time': 109, 'was LTD: ticker at the time': 86, 'was LUK: ticker at the time': 129, 'was MOT: ticker at the time': 60, 'was NU: ticker at the time': 71, 'was PCS: ticker at the time': 47, 'was SAFC: ticker at the time': 6, 'was SAI: ticker at the time': 45, 'was SLE: ticker at the time': 77, 'was WAG: ticker at the time': 107, 'was WPO: ticker at the time': 71, 'was WYN: ticker at the time': 142}

Unmapped or not SEC filers (member-months): ARNC 2006-01..2016-04 (124), BEAM 2008-12..2010-06 (3), BF.B 2006-01..2026-03 (243), BRK.B 2010-10..2026-03 (160), CAR 2006-01..2006-03 (3), CPRI 2016-04..2017-02 (2), FOXA 2006-01..2026-03 (243), FRC 2019-01..2023-05 (53), KDP 2011-09..2011-09 (1), NWSA 2013-07..2026-03 (153), SBNY 2021-12..2023-03 (16), SPGI 2007-10..2012-11 (16), TGNA 2010-07..2013-08 (4), TPR 2016-03..2016-03 (1)

### Tickers later taken by another company (check against index history)

The company filing under the ticker at the time is used. If the index actually held the later company (as with Leucadia listed as JEF), add the ticker to PRE_RENAMES.

| Ticker | Months | CIK used | Later company (already filing under another ticker) |
|---|---|---|---|
| AGN | 2013-09..2015-04 | 850693 | 1578845 |
| ARNC | 2020-01..2020-02 | 4281 | 1790982 |
| CB | 2006-01..2016-01 | 20171 | 896159 |
| DOC | 2024-03..2024-03 | 1574540 | 765880 |
| GAS | 2011-12..2011-12 | 72020 | 1004155 |
| IR | 2017-04..2020-03 | 1466258 | 1699150 |
| JCI | 2006-01..2016-07 | 53669 | 833444 |
| L | 2006-01..2006-11 | 1082114 | 60086 |
| MRK | 2006-01..2009-09 | 64978 | 310158 |
| O | 2015-05..2026-03 | 726728 | 1104485 |
| PLD | 2006-01..2011-07 | 899881 | 1045609 |

### Overrides and renames, checked against the company's own filings

| Ticker | Method | CIK | Filings by that CIK inside the span |
|---|---|---|---|
| ABKFQ | rename ABK | 874501 | 378 |
| ANRZQ | rename ANR | 1301063 | 66 |
| ATGE | rename DV | 730464 | 229 |
| BTUUQ | rename BTU | 1064728 | 398 |
| CCEP | rename CCE | 1491675 | 30 |
| CCTYQ | rename CC | 104599 | 254 |
| CITGQ | rename CIT | 1171825 | 270 |
| CMCSK | rename CMCSA | 1166691 | 27 |
| DCNAQ | rename DCN | 26780 | 15 |
| DXC | rename CSC | 23082 | 553 |
| EKDKQ | rename EK | 31235 | 357 |
| FMCC | override | 1026214 | 0 |
| FMCC | rename FRE | 1026214 | 33 |
| FNMA | rename FNM | 310522 | 257 |
| IAC | rename IACI | 891103 | 170 |
| KATE | rename LIZ | 352363 | 338 |
| RSHCQ | rename RSH | 96289 | 441 |
| SUNEQ | rename WFR | 945436 | 193 |
| VIAV | rename JDSU | 912093 | 639 |
| VSTNQ | rename VC | 1111335 | 4 |
| WAMUQ | rename WM | 933136 | 343 |
| WM | pinned | 823768 | 1769 |

## Insider buying, officers and directors only (track B)

15227 open-market buys at S&P members; clusters: 912 with 3+ insiders, 1997 with 2+.

| Year | Buys | 2+ clusters | 3+ clusters |
|---|---|---|---|
| 2006 | 833 | 116 | 45 |
| 2007 | 1207 | 148 | 70 |
| 2008 | 1640 | 256 | 129 |
| 2009 | 887 | 121 | 56 |
| 2010 | 679 | 88 | 30 |
| 2011 | 855 | 119 | 59 |
| 2012 | 701 | 100 | 45 |
| 2013 | 558 | 66 | 25 |
| 2014 | 490 | 61 | 26 |
| 2015 | 758 | 90 | 50 |
| 2016 | 737 | 99 | 49 |
| 2017 | 632 | 83 | 40 |
| 2018 | 716 | 93 | 38 |
| 2019 | 724 | 103 | 49 |
| 2020 | 820 | 115 | 44 |
| 2021 | 533 | 47 | 26 |
| 2022 | 609 | 71 | 31 |
| 2023 | 665 | 70 | 38 |
| 2024 | 404 | 50 | 18 |
| 2025 | 618 | 75 | 34 |
| 2026 | 161 | 26 | 10 |

## Point-in-time EPS (gate 90% of member-years 2011+): **PASS (95.8%)**

| Year | EPS growth known % | Revenue growth known % | Member-years |
|---|---|---|---|
| 2006 | 0.0 | 0.0 | 497.0 |
| 2007 | 0.0 | 0.0 | 494.0 |
| 2008 | 0.0 | 0.0 | 498.0 |
| 2009 | 2.4 | 1.8 | 498.0 |
| 2010 | 67.1 | 40.2 | 495.0 |
| 2011 | 92.7 | 53.5 | 493.0 |
| 2012 | 94.3 | 55.2 | 495.0 |
| 2013 | 96.2 | 52.9 | 495.0 |
| 2014 | 96.4 | 54.1 | 495.0 |
| 2015 | 97.0 | 53.5 | 497.0 |
| 2016 | 95.6 | 51.9 | 503.0 |
| 2017 | 95.3 | 49.3 | 507.0 |
| 2018 | 95.9 | 54.8 | 507.0 |
| 2019 | 95.0 | 71.4 | 503.0 |
| 2020 | 95.6 | 68.8 | 503.0 |
| 2021 | 95.0 | 66.9 | 502.0 |
| 2022 | 96.2 | 63.2 | 503.0 |
| 2023 | 97.4 | 62.9 | 501.0 |
| 2024 | 96.8 | 62.9 | 502.0 |
| 2025 | 97.0 | 62.9 | 499.0 |
| 2026 | 100.0 | 37.5 | 8.0 |

## Notes

- 2026Q2: not published (404)
- 2026Q3: not published (404)
- companyfacts missing for 89 companies: {'no companyfacts': 89}
- 1068 SEC requests; 81 insider data sets read; last filing month 2026-03.

*edgar_data.py 1.1. Read by the track A and B labs via edgar_data.load().*
