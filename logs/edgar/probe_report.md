# EDGAR probe 1.0 — 2026-11-19

Can free SEC data support track A (earnings acceleration) and track B (insider clusters) without hindsight?

## 1. Mapping past S&P 500 members to SEC company numbers

Bar: a year is usable at 80% of member-days mapped. **Usable years: 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026.**

| Year | Member-days | Mapped | % | Usable |
|---|---|---|---|---|
| 2006 | 124746 | 121171 | 97.1 | yes |
| 2007 | 124744 | 120830 | 96.9 | yes |
| 2008 | 125841 | 122462 | 97.3 | yes |
| 2009 | 125690 | 123389 | 98.2 | yes |
| 2010 | 125537 | 123278 | 98.2 | yes |
| 2011 | 125242 | 123214 | 98.4 | yes |
| 2012 | 124242 | 122615 | 98.7 | yes |
| 2013 | 125241 | 123987 | 99.0 | yes |
| 2014 | 125534 | 124597 | 99.3 | yes |
| 2015 | 126147 | 125354 | 99.4 | yes |
| 2016 | 127356 | 126750 | 99.5 | yes |
| 2017 | 126995 | 126493 | 99.6 | yes |
| 2018 | 126917 | 126415 | 99.6 | yes |
| 2019 | 127260 | 126522 | 99.4 | yes |
| 2020 | 127767 | 127126 | 99.5 | yes |
| 2021 | 127260 | 126495 | 99.4 | yes |
| 2022 | 126437 | 125652 | 99.4 | yes |
| 2023 | 125750 | 125367 | 99.7 | yes |
| 2024 | 126757 | 126575 | 99.9 | yes |
| 2025 | 125752 | 125752 | 100.0 | yes |
| 2026 | 112171 | 112171 | 100.0 | yes |

How members were mapped: {'insider filings': 963, 'unmapped': 27, 'current SEC list': 8}. Ambiguous symbols (two companies in the window): 106.

## 2. Insider buying among S&P members (track B)

Bar: 100+ three-insider clusters 2006–2026. **Found: 947 three-insider clusters, 2083 two-insider.**

| Year | Open-market buys | 2-insider clusters | 3-insider clusters |
|---|---|---|---|
| 2006 | 3161 | 112 | 41 |
| 2007 | 3552 | 148 | 68 |
| 2008 | 5572 | 262 | 144 |
| 2009 | 1454 | 126 | 56 |
| 2010 | 1003 | 88 | 33 |
| 2011 | 1280 | 125 | 62 |
| 2012 | 1158 | 115 | 47 |
| 2013 | 925 | 80 | 26 |
| 2014 | 1150 | 70 | 29 |
| 2015 | 1201 | 101 | 54 |
| 2016 | 1445 | 102 | 53 |
| 2017 | 1150 | 84 | 41 |
| 2018 | 1150 | 99 | 41 |
| 2019 | 1067 | 101 | 47 |
| 2020 | 1709 | 112 | 44 |
| 2021 | 827 | 47 | 26 |
| 2022 | 1167 | 77 | 34 |
| 2023 | 1065 | 72 | 38 |
| 2024 | 817 | 52 | 18 |
| 2025 | 1437 | 79 | 35 |
| 2026 | 398 | 31 | 10 |

## 3. Point-in-time fundamentals (track A)

Sample: 196 companies, 2062 member-years from 2010. Bar: 80% of member-years with quarterly EPS growth known by mid-year. **Found: 92.5%.**

| Year | EPS growth known % | Revenue growth known % |
|---|---|---|
| 2010 | 66.1 | 38.1 |
| 2011 | 91.8 | 52.5 |
| 2012 | 91.1 | 53.7 |
| 2013 | 92.7 | 50.4 |
| 2014 | 92.9 | 51.6 |
| 2015 | 95.3 | 51.2 |
| 2016 | 94.5 | 47.2 |
| 2017 | 96.7 | 44.6 |
| 2018 | 95.0 | 55.0 |
| 2019 | 95.1 | 72.4 |
| 2020 | 94.0 | 73.5 |
| 2021 | 94.0 | 71.8 |
| 2022 | 94.0 | 63.2 |
| 2023 | 95.0 | 61.7 |
| 2024 | 94.2 | 61.2 |
| 2025 | 95.0 | 61.2 |
| 2026 | 94.1 | 62.2 |

## Verdict

- **Track A (earnings acceleration): FEASIBLE.**
- **Track B (insider clusters): FEASIBLE.**

## Notes

- 2026Q2 insider data set failed: SEC request failed for https://dcm.sec.gov/files/structureddata/data/insider-transactions-data-sets/2026q2_form345.zip: URLError
- 2026Q3 insider data set failed: SEC request failed for https://dcm.sec.gov/files/structureddata/data/insider-transactions-data-sets/2026q3_form345.zip: URLError
- 291 SEC requests; insider data sets read: 81.

*edgar_probe.py 1.0. Nothing reads these files yet.*
