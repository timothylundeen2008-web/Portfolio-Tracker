# Point-in-time universe probe v1.0 — 2026-11-15

Source: `fja05680/sp500` / `S&P 500 Historical Components & Changes.csv`. Membership rows: 2595 (1996-01-02 → 2019-01-11). Tickers ever in the index since 2005: 854; with any Yahoo history: 490 (57%).

A year is USABLE when at least 80% of that January's members have 200+ daily bars in the year.

| Year | Members | With prices | Coverage % | Usable | Missing (sample) |
|---|---|---|---|---|---|
| 2005 | 501 | 254 | 50.7 | **no** | AABA, ABC, ABI-200811, ABKFQ-201304, ABS-200606, ACS-201002, ACV-201105, ADCT-201012, AET, AGN, AGN-201503, ALTR-201512 |
| 2006 | 501 | 267 | 53.3 | **no** | AABA, ABC, ABI-200811, ABKFQ-201304, ABS-200606, ACS-201002, ACV-201105, ADCT-201012, AET, AGN, AGN-201503, ALTR-201512 |
| 2007 | 501 | 275 | 54.9 | **no** | AABA, ABC, ABI-200811, ABKFQ-201304, ACS-201002, ADCT-201012, AET, AGN, AGN-201503, ALTR-201512, ANTM, APC |
| 2008 | 502 | 293 | 58.4 | **no** | AABA, ABC, ABI-200811, ABKFQ-201304, ACAS-201701, ACS-201002, AET, AGN, AGN-201503, ALTR-201512, ANDV, ANTM |
| 2009 | 501 | 302 | 60.3 | **no** | AABA, ABC, ACAS-201701, ACS-201002, AET, AGN, AGN-201503, AKS, ALTR-201512, ANDV, ANTM, APC |
| 2010 | 501 | 312 | 62.3 | **no** | AABA, ABC, ACS-201002, AET, AGN, AGN-201503, AKS, ALTR-201512, ANDV, ANTM, APC, APOL-201702 |
| 2011 | 501 | 321 | 64.1 | **no** | AABA, ABC, AET, AGN, AGN-201503, AKS, ALTR-201512, ANDV, ANTM, APC, APOL-201702, ARG-201605 |
| 2012 | 501 | 333 | 66.5 | **no** | AABA, ABC, AET, AGN, AGN-201503, ALTR-201512, ANDV, ANRZQ-201607, ANTM, APC, APOL-201702, ARG-201605 |
| 2013 | 501 | 346 | 69.1 | **no** | AABA, ABC, ADT-201604, AET, AGN, AGN-201503, ALTR-201512, ALXN, ANDV, ANTM, APC, APOL-201702 |
| 2014 | 502 | 351 | 69.9 | **no** | AABA, ABC, ADS, ADT-201604, AET, AGN, AGN-201503, ALTR-201512, ALXN, ANDV, ANTM, APC |
| 2015 | 504 | 358 | 71.0 | **no** | AABA, ABC, ADS, ADT-201604, AET, AGN, AGN-201503, ALTR-201512, ALXN, ANDV, ANTM, APC |
| 2016 | 514 | 374 | 72.8 | **no** | AABA, ABC, ADS, ADT-201604, AET, AET-201811, AGN, ALXN, ANDV, ANDV-201809, ANTM, APC |
| 2017 | 516 | 393 | 76.2 | **no** | AABA, ABC, ADS, AET, AET-201811, AGN, ALXN, ANDV, ANDV-201809, ANTM, APC, ARNC |
| 2018 | 514 | 408 | 79.4 | **no** | ABC, ADS, AET, AET-201811, AGN, ALXN, ANDV, ANDV-201809, ANSS, ANTM, APC, ARNC |
| 2019 | 504 | 419 | 83.1 | yes | ABC, ABMD, ADS, AGN, ALXN, ANSS, ANTM, APC, ARNC, ATVI, AVB, BHGE |

**Usable years: 1 of 15** (first usable year 2019).

Read: missing names are mostly companies that were acquired, renamed or went bankrupt. A stock test on the usable years still under-counts failures by the uncovered share, and says so in its report.

*universe_probe.py v1.0. A probe; nothing reads these files yet.*
