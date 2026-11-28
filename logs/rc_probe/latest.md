# Regime classifier replay — data probe 1.0.1 — 2026-11-28

Looks at no returns and decides nothing. Research, not personalized advice.

## What it means
- HY OAS full history NOT available (current series 2023-11-28 → 2026-11-26; snapshots failed or truncated): the replay needs a proxy or a file, and every credit threshold would have to be restated — weaker evidence.
- Earliest possible replay start is set by DFII10 (2003-01-02) plus the 63-session momentum and the 200-day gates, i.e. about one year later.
- Growth series with ALFRED vintages from 2005 or earlier: PAYEMS, RSAFS, UMCSENT — a point-in-time growth composite is possible.
- CAPE sources usable: yale_shiller_xls, datahub_sp500_csv.
- Sleeves that start after 2006 (need a stand-in or start later): SLV 2006-04-28, SHV 2007-01-11, BIL 2007-05-30, SCHP 2010-08-05, SCHD 2011-10-20, RING 2012-02-02, USFR 2014-02-04, PDBC 2014-11-07, DBMF 2019-05-08, SGOV 2020-06-01, KMLM 2020-12-02

## FRED inputs (current API)
| Series | What | First | Last | N | Note |
|---|---|---|---|---|---|
| DFF | fed funds (short real rate) | 1954-07-01 | 2026-11-26 | 26447 |  |
| CPIAUCNS | CPI NSA (YoY) | 1913-01-01 | 2026-10-01 | 1365 |  |
| CPIAUCSL | CPI SA (3m, 1m) | 1947-01-01 | 2026-10-01 | 957 |  |
| DFII10 | 10y real yield | 2003-01-02 | 2026-11-25 | 5979 |  |
| T10YIE | 10y breakeven | 2003-01-02 | 2026-11-27 | 5980 |  |
| DGS10 | 10y nominal | 1962-01-02 | 2026-11-25 | 16210 |  |
| DGS2 | 2y nominal | 1976-06-01 | 2026-11-25 | 12618 |  |
| DTWEXBGS | broad dollar (current) | 2006-01-02 | 2026-11-20 | 5236 |  |
| DTWEXB | broad dollar (old, discontinued) | 1995-01-04 | 2019-12-31 | 6328 |  |
| BAMLH0A0HYM2 | HY OAS | 2023-11-28 | 2026-11-26 | 786 |  |
| BAMLC0A0CM | IG OAS | 2023-11-28 | 2026-11-26 | 785 |  |
| BAA10Y | Moody's BAA − 10y (proxy) | 1986-01-02 | 2026-11-24 | 10224 |  |
| AAA10Y | Moody's AAA − 10y (proxy) | 1983-01-03 | 2026-11-24 | 10971 |  |
| PAYEMS | payrolls (growth) | 1939-01-01 | 2026-10-01 | 1054 |  |
| ICSA | initial claims (growth) | 1967-01-07 | 2026-11-21 | 3125 |  |
| RSAFS | retail sales (growth) | 1992-01-01 | 2026-10-01 | 418 |  |
| UMCSENT | sentiment (growth) | 1952-11-01 | 2026-10-01 | 678 |  |

## ALFRED snapshots (before the April 2026 cut)
| Series | Snapshot | First | Last | N | 2008-12-15 | 2007 low | Full |
|---|---|---|---|---|---|---|---|
| BAMLH0A0HYM2 | 2026-03-31 | 2023-11-28 | 2026-03-31 | 613 | None | None | False  |
| BAMLH0A0HYM2 | 2025-12-31 | 2023-11-28 | 2025-12-31 | 548 | None | None | False  |
| BAMLC0A0CM | 2026-03-31 | 2023-11-28 | 2026-03-31 | 612 | — | — | —  |
| BAMLC0A0CM | 2025-12-31 | 2023-11-28 | 2025-12-31 | 547 | — | — | —  |

## Point-in-time (ALFRED vintages)
| Series | First vintage | Vintages | Note |
|---|---|---|---|
| PAYEMS | 1955-05-06 | 861 |  |
| ICSA | 2009-05-28 | 908 |  |
| RSAFS | 2001-06-13 | 327 |  |
| UMCSENT | 1998-07-31 | 339 |  |
| CPIAUCSL | 1972-07-21 | 671 |  |

## CAPE sources
| Source | Reached | Detail |
|---|---|---|
| yale_shiller_xls | True | {"bytes": 1628672, "note": "Excel file fetched; parsing left to the replay build"} |
| datahub_sp500_csv | True | {"bytes": 123851, "columns": ["Date", "SP500", "Dividend", "Earnings", "Consumer Price Index", "Long Interest Rate", "Real Price", "Real Dividend", "Real Earnings", "PE10"], "cape": {"ok": true, "first": "1871-01-01", "last": "2026-09-01", "n": 1869}, "last_value": 0.0} |

## Prices (yfinance, first date)
| Ticker | First | Last | N |
|---|---|---|---|
| VGT | 2004-01-30 | 2026-11-27 | 5744 |
| SMH | 2000-06-05 | 2026-11-27 | 6661 |
| QQQ | 1999-03-10 | 2026-11-27 | 6974 |
| GLD | 2004-11-18 | 2026-11-27 | 5541 |
| SLV | 2006-04-28 | 2026-11-27 | 5179 |
| RING | 2012-02-02 | 2026-11-27 | 3727 |
| XLE | 1998-12-22 | 2026-11-27 | 7026 |
| PDBC | 2014-11-07 | 2026-11-27 | 3031 |
| SCHD | 2011-10-20 | 2026-11-27 | 3798 |
| XLV | 1998-12-22 | 2026-11-27 | 7026 |
| XLU | 1998-12-22 | 2026-11-27 | 7026 |
| SGOV | 2020-06-01 | 2026-11-27 | 1633 |
| USFR | 2014-02-04 | 2026-11-27 | 3224 |
| TLT | 2002-07-30 | 2026-11-27 | 6123 |
| KMLM | 2020-12-02 | 2026-11-27 | 1504 |
| DBMF | 2019-05-08 | 2026-11-27 | 1901 |
| SCHP | 2010-08-05 | 2026-11-27 | 4104 |
| SPY | 1993-01-29 | 2026-11-27 | 8516 |
| XLY | 1998-12-22 | 2026-11-27 | 7026 |
| XLI | 1998-12-22 | 2026-11-27 | 7026 |
| XLF | 1998-12-22 | 2026-11-27 | 7026 |
| XLP | 1998-12-22 | 2026-11-27 | 7026 |
| BIL | 2007-05-30 | 2026-11-27 | 4907 |
| SHV | 2007-01-11 | 2026-11-27 | 5002 |

*rc_probe.py 1.0.1*
