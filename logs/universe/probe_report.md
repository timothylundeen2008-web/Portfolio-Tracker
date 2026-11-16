# Point-in-time universe probe v1.1 — 2026-11-16

Membership: `fja05680/sp500` / `S&P 500 Historical Components & Changes (Updated).csv`, 2720 rows, 1996-01-02 → 2026-08-18.

Tickers in the index at any time since 2005: **977**. Yahoo has history for 684; 23 more resolve through the rename map; Stooq was asked for 0 of the 348 still missing (0 with history, 0 already known empty).

> **Stooq leg FAILED — a data failure, not a result:** control ticker AAPL did not return a price history (reply read as 'unknown'); Stooq's format or access has changed. The Stooq column below equals the column before it.

Measure: for each ticker and year, the trading days it was an index member. It is covered when prices exist for at least 90% of them. A year's figure is the covered share of member-days. USABLE at 80%, CLEAN at 95%. Columns are cumulative.

| Year | Tickers | Yahoo % | + renames % | + Stooq % | Verdict | Still missing | Sample |
|---|---|---|---|---|---|---|---|
| 2005 | 511 | 53.3 | 55.3 | 55.3 | **no** | 229 | AABA, ABI, ABKFQ, ABS, ACS, ACV, ADCT, AET, AGN, ALTR |
| 2006 | 527 | 55.8 | 57.8 | 57.8 | **no** | 233 | AABA, ABI, ABKFQ, ACS, ADCT, AGN, AET, APC, ALTR, BMET |
| 2007 | 533 | 58.2 | 60.3 | 60.3 | **no** | 221 | AABA, ABI, ABKFQ, ACS, AET, APOL, AGN, ALTR, APC, AVP |
| 2008 | 531 | 60.8 | 63.2 | 63.2 | **no** | 199 | AABA, ACS, ACAS, AET, AGN, ANDV, ALTR, ESV, EMC, APC |
| 2009 | 524 | 63.2 | 65.8 | 65.8 | **no** | 185 | AABA, ACS, AET, AGN, AKS, ANDV, ALTR, APC, APOL, BIG |
| 2010 | 513 | 65.4 | 68.0 | 68.0 | **no** | 171 | AABA, AET, AGN, APC, AKS, ALTR, ANDV, ARG, APOL, ARNC |
| 2011 | 515 | 66.4 | 69.0 | 69.0 | **no** | 163 | AABA, AET, AGN, ALTR, ANDV, APOL, APC, ARG, ARNC, AVB |
| 2012 | 514 | 68.5 | 71.1 | 71.1 | **no** | 153 | AABA, AET, AGN, ALTR, ANDV, APC, ARNC, ARG, APOL, BMC |
| 2013 | 515 | 70.7 | 73.3 | 73.3 | **no** | 140 | AABA, ADT, AET, AGN, ALTR, ALXN, ANDV, APC, ARG, ARNC |
| 2014 | 513 | 71.7 | 74.7 | 74.7 | **no** | 134 | AABA, ADT, AET, AGN, ALTR, ALXN, ANDV, APC, ARG, ARNC |
| 2015 | 529 | 73.5 | 76.5 | 76.5 | **no** | 134 | AABA, ADT, AET, AGN, ALXN, ANDV, XL, APC, ARG, ARNC |
| 2016 | 533 | 76.6 | 79.8 | 79.8 | **no** | 116 | AABA, AET, AGN, ALXN, CBS, ANDV, APC, ARNC, AVB, ATVI |
| 2017 | 533 | 79.4 | 82.8 | 82.8 | usable | 100 | AET, AGN, ALXN, ANDV, EQR, APC, ARNC, ATVI, AVB, CA |
| 2018 | 529 | 81.3 | 85.0 | 85.0 | usable | 85 | AGN, ALXN, ARNC, APC, ANSS, COG, CELG, CERN, ATVI, AVB |
| 2019 | 533 | 83.8 | 87.3 | 87.3 | usable | 69 | ABMD, AGN, ALXN, ANSS, ARNC, XEC, ATVI, AVB, BK, CERN |
| 2020 | 525 | 87.2 | 90.0 | 90.0 | usable | 56 | ABMD, ALXN, ANSS, ATVI, BK, AVB, CMA, CERN, EQR, DISH |
| 2021 | 526 | 89.1 | 91.3 | 91.3 | usable | 51 | ABMD, ANSS, ATVI, DISH, AVB, BK, CERN, CTLT, CMA, DFS |
| 2022 | 527 | 91.7 | 93.3 | 93.3 | usable | 41 | ANSS, CDAY, ATVI, AVB, BK, CTLT, CMA, DFS, CTRA, WRK |
| 2023 | 522 | 94.2 | 94.9 | 94.9 | usable | 30 | ANSS, AVB, CDAY, BK, CMA, CTLT, EQR, CTRA, DFS, EA |
| 2024 | 523 | 95.5 | 95.6 | 95.6 | CLEAN | 25 | ANSS, AVB, BK, DFS, CTRA, HES, FI, EQR, EA, KVUE |
| 2025 | 524 | 96.9 | 96.9 | 96.9 | CLEAN | 19 | AVB, BK, CTRA, HOLX, DAY, EA, EQR, MMC, WBD, KVUE |
| 2026 | 520 | 98.7 | 98.7 | 98.7 | CLEAN | 12 | PSKY, WBD, KVUE, AVB, EQR, EA, BK, CTRA, HOLX, SATS |

**Usable years: 10 of 22; clean years: 3.**

Read: a stock test may use the usable years, and must state the uncovered share as the amount by which it still under-counts failures. A year that is not usable is not tested.

Rename map (41 entries, hand-built): ABC→COR, ADS→BFH, ANTM→ELV, BBT→TFC, BLL→BALL, CBG→CBRE, CDAY→DAY, COG→CTRA, COH→TPR, CTL→LUMN, DISCA→WBD, DLPH→APTV, DPS→KDP, FB→META, FBHS→FBIN, FLT→CPAY, GPS→GAP, HCN→WELL, HCP→DOC, HFC→DINO, HRS→LHX, JDSU→VIAV, JEC→J, KFT→MDLZ, KORS→CPRI, LB→BBWI, LTD→BBWI, LUK→JEF, MYL→VTRS, NLOK→GEN, PCLN→BKNG, PEAK→DOC, PKI→RVTY, Q→IQV, RE→EG, SYMC→GEN, TMK→GL, UTX→RTX, WLP→ELV, WLTW→WTW, WYN→TNL.

*universe_probe.py v1.1. A probe; nothing reads these files yet.*
