# EDGAR data 1.3 — 2026-11-20

Shared SEC data for tracks A and B, with the probe's fixes (company number by date, renamed and bankrupt members, officers and directors only, Q4 derived).

## Mapping (gate 95% of member-days every year): **PASS**

| Year | Member-days | Mapped % |
|---|---|---|
| 2006 | 124746 | 100.0 |
| 2007 | 124744 | 100.0 |
| 2008 | 125841 | 100.0 |
| 2009 | 125690 | 100.0 |
| 2010 | 125537 | 100.0 |
| 2011 | 125242 | 100.0 |
| 2012 | 124242 | 100.0 |
| 2013 | 125241 | 100.0 |
| 2014 | 125534 | 100.0 |
| 2015 | 126147 | 100.0 |
| 2016 | 127356 | 100.0 |
| 2017 | 126995 | 100.0 |
| 2018 | 126917 | 100.0 |
| 2019 | 127260 | 99.8 |
| 2020 | 127767 | 99.8 |
| 2021 | 127260 | 99.8 |
| 2022 | 126437 | 99.6 |
| 2023 | 125750 | 99.9 |
| 2024 | 126757 | 100.0 |
| 2025 | 125752 | 100.0 |
| 2026 | 30683 | 100.0 |

Member-months by method: {'end-of-membership company': 1628, 'not an SEC filer': 69, 'override': 24, 'pinned': 683, 'rename: end-of-membership company': 21, 'rename: ticker at the time': 773, 'ticker at the time': 117639, 'unmapped': 3, 'was BHI: ticker at the time': 138, 'was CBG: ticker at the time': 136, 'was GM: ticker at the time': 42, 'was GOOG: ticker at the time': 114, 'was HCN: ticker at the time': 109, 'was LTD: ticker at the time': 86, 'was LUK: ticker at the time': 129, 'was MOT: ticker at the time': 60, 'was NU: ticker at the time': 71, 'was PCS: ticker at the time': 47, 'was SAFC: ticker at the time': 6, 'was SAI: ticker at the time': 45, 'was SLE: ticker at the time': 77, 'was WAG: ticker at the time': 107, 'was WPO: ticker at the time': 71, 'was WYN: ticker at the time': 142}

Unmapped or not SEC filers (member-months): CAR 2006-01..2006-03 (3), FRC 2019-01..2023-05 (53), SBNY 2021-12..2023-03 (16)

### Tickers later taken by another company (check against index history)

The company filing under the ticker at the time is used. If the index actually held the later company (as with Leucadia listed as JEF), add the ticker to PRE_RENAMES.

| Ticker | Months | CIK used | Later company (already filing under another ticker) |
|---|---|---|---|
| AGN | 2013-09..2015-04 | 850693 | 1578845 |
| CB | 2006-01..2016-01 | 20171 | 896159 |
| GAS | 2011-12..2011-12 | 72020 | 1004155 |
| IR | 2017-04..2020-03 | 1466258 | 1699150 |
| JCI | 2006-01..2016-07 | 53669 | 833444 |
| MRK | 2006-01..2009-09 | 64978 | 310158 |
| O | 2015-05..2026-03 | 726728 | 1104485 |
| PLD | 2006-01..2011-07 | 899881 | 1045609 |

### Overrides and renames, checked against the company's own filings

| Ticker | Method | CIK | Filings by that CIK inside the span |
|---|---|---|---|
| ABKFQ | rename ABK | 874501 | 378 |
| ANRZQ | rename ANR | 1301063 | 66 |
| ARNC | pinned | 4281 | 1338 |
| ATGE | rename DV | 730464 | 229 |
| BTUUQ | rename BTU | 1064728 | 398 |
| CCEP | rename CCE | 1491675 | 30 |
| CCTYQ | rename CC | 104599 | 254 |
| CITGQ | rename CIT | 1171825 | 270 |
| CMCSK | rename CMCSA | 1166691 | 27 |
| DCNAQ | rename DCN | 26780 | 15 |
| DOC | pinned | 765880 | 75 |
| DXC | rename CSC | 23082 | 553 |
| EKDKQ | rename EK | 31235 | 357 |
| FMCC | override | 1026214 | 0 |
| FMCC | rename FRE | 1026214 | 33 |
| FNMA | rename FNM | 310522 | 257 |
| IAC | rename IACI | 891103 | 170 |
| KATE | rename LIZ | 352363 | 338 |
| L | pinned | 60086 | 2026 |
| RSHCQ | rename RSH | 96289 | 441 |
| SUNEQ | rename WFR | 945436 | 193 |
| VIAV | rename JDSU | 912093 | 639 |
| VSTNQ | rename VC | 1111335 | 4 |
| WAMUQ | rename WM | 933136 | 343 |
| WM | pinned | 823768 | 1769 |

## Insider buying, officers and directors only (track B)

15328 open-market buys at S&P members; clusters: 916 with 3+ insiders, 2013 with 2+.

| Year | Buys | 2+ clusters | 3+ clusters |
|---|---|---|---|
| 2006 | 841 | 117 | 45 |
| 2007 | 1215 | 149 | 70 |
| 2008 | 1651 | 256 | 129 |
| 2009 | 892 | 121 | 56 |
| 2010 | 680 | 88 | 30 |
| 2011 | 862 | 119 | 59 |
| 2012 | 712 | 102 | 45 |
| 2013 | 574 | 70 | 25 |
| 2014 | 500 | 65 | 27 |
| 2015 | 763 | 92 | 51 |
| 2016 | 745 | 101 | 51 |
| 2017 | 633 | 83 | 40 |
| 2018 | 717 | 93 | 38 |
| 2019 | 725 | 103 | 49 |
| 2020 | 822 | 115 | 44 |
| 2021 | 534 | 47 | 26 |
| 2022 | 614 | 71 | 31 |
| 2023 | 665 | 70 | 38 |
| 2024 | 404 | 50 | 18 |
| 2025 | 618 | 75 | 34 |
| 2026 | 161 | 26 | 10 |

## Point-in-time EPS (gate 90% of member-years 2011+): **PASS (95.8%)**

| Year | EPS growth known % | Revenue growth known % | Member-years |
|---|---|---|---|
| 2006 | 0.0 | 0.0 | 500.0 |
| 2007 | 0.0 | 0.0 | 497.0 |
| 2008 | 0.0 | 0.0 | 502.0 |
| 2009 | 2.4 | 2.2 | 502.0 |
| 2010 | 69.0 | 68.4 | 500.0 |
| 2011 | 93.4 | 92.4 | 498.0 |
| 2012 | 94.0 | 94.8 | 499.0 |
| 2013 | 96.4 | 96.2 | 499.0 |
| 2014 | 96.4 | 96.6 | 499.0 |
| 2015 | 97.0 | 96.4 | 501.0 |
| 2016 | 95.5 | 97.0 | 507.0 |
| 2017 | 94.9 | 97.3 | 511.0 |
| 2018 | 95.5 | 97.5 | 511.0 |
| 2019 | 95.5 | 99.4 | 507.0 |
| 2020 | 96.1 | 100.0 | 507.0 |
| 2021 | 95.2 | 99.6 | 505.0 |
| 2022 | 96.1 | 99.2 | 507.0 |
| 2023 | 97.2 | 99.6 | 505.0 |
| 2024 | 96.6 | 99.6 | 506.0 |
| 2025 | 96.8 | 99.6 | 503.0 |

## Notes

- 2026Q2: not published (404)
- 2026Q3: not published (404)
- companyfacts missing for 88 companies: {'no companyfacts': 88}
- 1066 SEC requests; 81 insider data sets read; last filing month 2026-03.

*edgar_data.py 1.3. Read by the track A and B labs via edgar_data.load().*
