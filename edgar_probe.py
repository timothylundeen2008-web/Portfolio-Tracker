"""
edgar_probe.py  (v1.0 — 2026-11-18)
───────────────────────────────────
PROBE, not a backtest. Can free SEC EDGAR data support two swing-book tests
without hindsight?
  Track A  earnings acceleration added to the leader rules (2010-2026)
  Track B  insider cluster buying (2006-2026)
Both need a map from each past S&P 500 ticker to the company's SEC number
(CIK) — including companies that were later acquired or delisted, which is
exactly what Yahoo lost. (Matt, 2026-11-18: "Let's look at all of them.")

WHAT IT DOES
  1. Current map: www.sec.gov/files/company_tickers.json (today's listings).
  2. Historical map: the SEC's quarterly Insider Transactions Data Sets
     (Forms 3/4/5, from 2006) record the issuer's CIK and the trading symbol
     AS FILED at the time. Every symbol/CIK pair is kept with its first and
     last filing date. A past member is mapped when its symbol was filed for
     a CIK within a year of its membership; a symbol that pointed to two
     companies inside that window takes the one with more filings, and is
     counted as ambiguous.
  3. Insider buys: open-market purchases (code P, acquired) by insiders of
     mapped S&P members on the day of the filing, and "clusters": 2+ and 3+
     different insiders buying within 30 days. Saved for track B.
  4. Fundamentals sample: companyfacts (data.sec.gov) for a fixed random
     sample of mapped members. For each member-year from 2010: could a
     year-over-year quarterly EPS change (and revenue change) have been
     computed from filings already filed by mid-year? Point in time by the
     SEC's own `filed` date.

BARS (fixed before the run)
  Mapping   a year is USABLE when 80%+ of S&P member-days map to a CIK.
  Track A   feasible when, in the sample, 80%+ of member-years 2010-2026 have
            point-in-time quarterly EPS growth.
  Track B   feasible when there are 100+ three-insider clusters among
            S&P members 2006-2026 (enough for a 100-trade test).

PRIVACY: the SEC requires a contact email in the User-Agent. It is read from
the SEC_CONTACT_EMAIL secret and never printed or written to any file.

Run:  python edgar_probe.py            (Actions; ~30-60 minutes)
      python edgar_probe.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

import universe_probe as up

VERSION = "1.0"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
INSIDER_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{y}q{q}_form345.zip"
INSIDER_ALT = "https://dcm.sec.gov/files/structureddata/data/insider-transactions-data-sets/{y}q{q}_form345.zip"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FIRST_Q, START_YEAR, FACTS_FROM = (2006, 1), 2006, 2010
MAP_WINDOW_DAYS = 365
CLUSTER_DAYS = 30
SAMPLE_N = 200
SAMPLE_SEED = 20261118
MIN_GAP = 0.11                       # seconds between SEC requests (< 10 per second)
MAP_BAR, FACTS_BAR, CLUSTER_BAR = 80.0, 80.0, 100
EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")
REV_TAGS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet")
MEMBERSHIP = Path("data/universe/sp500_membership.csv")
OUT_DATA, OUT_LOGS = Path("data/edgar"), Path("logs/edgar")


# ── HTTP ────────────────────────────────────────────────────────────────────

class SEC:
    """Polite SEC client: contact User-Agent, under 10 requests a second, retries on 429/5xx.
    The email never appears in errors or output."""

    def __init__(self, email: str, opener: Optional[Callable] = None, sleep: Callable = time.sleep):
        if not email or "@" not in email:
            raise ValueError("SEC_CONTACT_EMAIL is not set (a repository secret); the SEC refuses anonymous requests")
        self._ua = f"Portfolio-Tracker personal research {email}"
        self._open = opener or self._urlopen
        self._sleep = sleep
        self._last = 0.0
        self.requests = 0

    def _urlopen(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": self._ua, "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw

    def get(self, url: str, tries: int = 4) -> Optional[bytes]:
        """bytes, or None for a 404. Raises after repeated failures, with the email stripped."""
        for i in range(tries):
            wait = MIN_GAP - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                return self._open(url)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code in (403, 429, 500, 502, 503) and i < tries - 1:
                    self._sleep(2.0 * (i + 1))
                    continue
                raise RuntimeError(f"SEC HTTP {e.code} for {url}") from None
            except Exception as e:
                if i < tries - 1:
                    self._sleep(2.0 * (i + 1))
                    continue
                raise RuntimeError(f"SEC request failed for {url}: {type(e).__name__}") from None
        return None


# ── parsing ─────────────────────────────────────────────────────────────────

def parse_company_tickers(raw: bytes) -> pd.DataFrame:
    j = json.loads(raw)
    rows = [{"symbol": str(v["ticker"]).upper().replace(".", "-"), "cik": int(v["cik_str"])} for v in j.values()]
    if len(rows) < 5000:
        raise ValueError(f"company_tickers.json has only {len(rows)} rows")
    return pd.DataFrame(rows)


def _col(df: pd.DataFrame, *names: str) -> str:
    m = {c.upper().strip(): c for c in df.columns}
    for n in names:
        if n in m:
            return m[n]
    raise KeyError(f"none of {names} in columns {list(df.columns)[:20]}")


def _read(z: zipfile.ZipFile, stem: str, usecols: Optional[list] = None) -> pd.DataFrame:
    name = next((n for n in z.namelist() if Path(n).stem.upper() == stem), None)
    if name is None:
        raise KeyError(f"{stem} not in zip ({z.namelist()[:10]})")
    with z.open(name) as fh:
        return pd.read_csv(fh, sep="\t", dtype=str, quoting=3, on_bad_lines="skip", low_memory=False)


def _dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", format="mixed", dayfirst=False)


def parse_insider_zip(raw: bytes) -> tuple:
    """-> (submissions: accession, filed, cik, symbol, doc_type; purchases: accession, trans_date, shares, price, owner).
    Open-market purchases only (code P, acquired)."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    sub = _read(z, "SUBMISSION")
    s = pd.DataFrame({"accession": sub[_col(sub, "ACCESSION_NUMBER")],
                      "filed": _dates(sub[_col(sub, "FILING_DATE")]),
                      "cik": pd.to_numeric(sub[_col(sub, "ISSUERCIK")], errors="coerce"),
                      "symbol": sub[_col(sub, "ISSUERTRADINGSYMBOL")].fillna("").str.strip().str.upper()
                                  .str.replace(r"[./]", "-", regex=True),
                      "doc_type": sub[_col(sub, "DOCUMENT_TYPE")].fillna("")})
    s = s.dropna(subset=["cik", "filed"])
    s["cik"] = s["cik"].astype(int)
    nd = _read(z, "NONDERIV_TRANS")
    own = _read(z, "REPORTINGOWNER")
    t = pd.DataFrame({"accession": nd[_col(nd, "ACCESSION_NUMBER")],
                      "code": nd[_col(nd, "TRANS_CODE")].fillna("").str.strip().str.upper(),
                      "ad": nd[_col(nd, "TRANS_ACQUIRED_DISP_CD")].fillna("").str.strip().str.upper(),
                      "trans_date": _dates(nd[_col(nd, "TRANS_DATE")]),
                      "shares": pd.to_numeric(nd[_col(nd, "TRANS_SHARES")], errors="coerce"),
                      "price": pd.to_numeric(nd[_col(nd, "TRANS_PRICEPERSHARE")], errors="coerce")})
    t = t[(t["code"] == "P") & (t["ad"] == "A") & (t["shares"] > 0)]
    o = pd.DataFrame({"accession": own[_col(own, "ACCESSION_NUMBER")],
                      "owner": own[_col(own, "RPTOWNERCIK")].fillna(""),
                      "role": own[_col(own, "RPTOWNER_RELATIONSHIP")].fillna("")})
    o = o.drop_duplicates("accession")
    t = t.merge(o, on="accession", how="left")
    return s, t


def symbol_spans(subs: pd.DataFrame) -> pd.DataFrame:
    """symbol, cik, first, last, n — from as-filed insider submissions."""
    s = subs[subs["symbol"].str.match(r"^[A-Z]{1,5}(-[A-Z]{1,2})?$", na=False)]
    g = s.groupby(["symbol", "cik"])["filed"].agg(["min", "max", "count"]).reset_index()
    return g.rename(columns={"min": "first", "max": "last", "count": "n"})


def map_members(iv: dict, spans: pd.DataFrame, current: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    """One row per (member ticker, membership span) with its CIK and how it was found."""
    cur = dict(zip(current["symbol"], current["cik"]))
    by_sym = {s: g for s, g in spans.groupby("symbol")}
    rows = []
    w = pd.Timedelta(days=MAP_WINDOW_DAYS)
    for tk, sp in iv.items():
        y = up.yahoo_symbol(tk)
        for a, b in sp:
            if b is not None and b <= start:
                continue
            a2, b2 = max(a, start), (b or pd.Timestamp.today().normalize())
            cik, how, amb = None, "unmapped", False
            g = by_sym.get(y)
            if g is not None:
                hit = g[(g["last"] >= a2 - w) & (g["first"] <= b2 + w)]
                if len(hit):
                    hit = hit.sort_values("n", ascending=False)
                    cik, how, amb = int(hit.iloc[0]["cik"]), "insider filings", hit["cik"].nunique() > 1
            if cik is None and b is None and y in cur:
                cik, how = int(cur[y]), "current SEC list"
            rows.append({"ticker": tk, "start": a2, "end": b, "cik": cik, "how": how, "ambiguous": amb})
    return pd.DataFrame(rows)


def mapping_coverage(mapped: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.DataFrame:
    out = {}
    for r in mapped.itertuples():
        days = cal[(cal >= r.start) & ((cal < r.end) if r.end is not None and not pd.isna(r.end) else True)]
        for y, n in pd.Series(1, index=days).groupby(days.year).sum().items():
            d = out.setdefault(int(y), [0, 0])
            d[0] += int(n)
            d[1] += int(n) if r.cik is not None and not pd.isna(r.cik) else 0
    return pd.DataFrame([{"year": y, "member_days": v[0], "mapped_days": v[1],
                          "mapped_pct": round(v[1] / v[0] * 100, 1), "usable": v[1] / v[0] * 100 >= MAP_BAR}
                         for y, v in sorted(out.items())])


def clusters(buys: pd.DataFrame, min_insiders: int) -> pd.DataFrame:
    """A cluster fires on the filing date when min_insiders different owners have bought the same
    company in the trailing CLUSTER_DAYS (by transaction date, known by filing date). One cluster per
    company per 30 days."""
    out = []
    for cik, g in buys.sort_values("filed").groupby("cik"):
        last_fire = None
        for filed in g["filed"].drop_duplicates():
            win = g[(g["filed"] <= filed) & (g["trans_date"] >= filed - pd.Timedelta(days=CLUSTER_DAYS))]
            if win["owner"].nunique() >= min_insiders and (last_fire is None or filed - last_fire > pd.Timedelta(days=CLUSTER_DAYS)):
                out.append({"cik": cik, "ticker": g["ticker"].iloc[0], "date": filed, "insiders": win["owner"].nunique(),
                            "value": float((win["shares"] * win["price"]).sum())})
                last_fire = filed
    return pd.DataFrame(out, columns=["cik", "ticker", "date", "insiders", "value"])


# ── fundamentals ────────────────────────────────────────────────────────────

def quarterly(facts: dict, tags: tuple, unit_prefix: str) -> pd.DataFrame:
    """3-month values (80-100 day duration) for the first tag that has any: end, val, filed."""
    g = (facts.get("facts") or {}).get("us-gaap") or {}
    for tag in tags:
        units = (g.get(tag) or {}).get("units") or {}
        for u, vals in units.items():
            if not u.startswith(unit_prefix):
                continue
            df = pd.DataFrame(vals)
            if df.empty or not {"start", "end", "val", "filed"} <= set(df.columns):
                continue
            df["start"], df["end"], df["filed"] = (pd.to_datetime(df[c], errors="coerce") for c in ("start", "end", "filed"))
            dur = (df["end"] - df["start"]).dt.days
            q = df[(dur >= 80) & (dur <= 100)].dropna(subset=["end", "filed"])
            if len(q):
                q = q.sort_values("filed").drop_duplicates("end", keep="first")      # the value as first filed
                return q[["end", "val", "filed"]].assign(tag=tag).reset_index(drop=True)
    return pd.DataFrame(columns=["end", "val", "filed", "tag"])


def yoy_known(q: pd.DataFrame, asof: pd.Timestamp) -> bool:
    """Could a year-over-year quarterly change have been computed on `asof` from what had been filed?
    Needs the latest quarter filed by then and the same quarter a year earlier."""
    k = q[q["filed"] <= asof]
    if k.empty:
        return False
    last = k.sort_values("end").iloc[-1]
    if (asof - last["end"]).days > 200:
        return False
    prior = k[(k["end"] - (last["end"] - pd.DateOffset(years=1))).abs().dt.days <= 20]
    return len(prior) > 0


def facts_coverage(sample: pd.DataFrame, get_facts: Callable) -> pd.DataFrame:
    """sample: ticker, cik, start, end. One row per member-year from FACTS_FROM."""
    rows = []
    cache: dict = {}
    for r in sample.itertuples():
        if r.cik not in cache:
            try:
                f = get_facts(int(r.cik))
            except Exception as e:
                f = {"_error": f"{type(e).__name__}"}
            cache[r.cik] = (quarterly(f or {}, EPS_TAGS, "USD"), quarterly(f or {}, REV_TAGS, "USD"),
                            (f or {}).get("_error") or ("" if f else "no companyfacts"))
        eps, rev, err = cache[r.cik]
        end = r.end if r.end is not None and not pd.isna(r.end) else pd.Timestamp.today().normalize()
        for y in range(max(FACTS_FROM, r.start.year), end.year + 1):
            asof = pd.Timestamp(f"{y}-06-30")
            if not (r.start <= asof < end):
                continue
            rows.append({"ticker": r.ticker, "cik": r.cik, "year": y, "eps_yoy": yoy_known(eps, asof),
                         "rev_yoy": yoy_known(rev, asof), "error": err})
    return pd.DataFrame(rows, columns=["ticker", "cik", "year", "eps_yoy", "rev_yoy", "error"])


# ── run ─────────────────────────────────────────────────────────────────────

def quarters(today: date) -> list:
    out, (y, q) = [], FIRST_Q
    while (y, q) < (today.year, (today.month - 1) // 3 + 1):
        out.append((y, q))
        y, q = (y + (q == 4), q % 4 + 1)
    return out


def render(cov: pd.DataFrame, mapped: pd.DataFrame, cl2: pd.DataFrame, cl3: pd.DataFrame, buys: pd.DataFrame,
           fc: pd.DataFrame, notes: list, stamp: str) -> str:
    usable = cov[cov["usable"]]["year"].tolist()
    L = [f"# EDGAR probe {VERSION} — {stamp}", "",
         "Can free SEC data support track A (earnings acceleration) and track B (insider clusters) without hindsight?", "",
         "## 1. Mapping past S&P 500 members to SEC company numbers", "",
         f"Bar: a year is usable at {MAP_BAR:.0f}% of member-days mapped. **Usable years: "
         f"{', '.join(map(str, usable)) or 'none'}.**", "",
         "| Year | Member-days | Mapped | % | Usable |", "|---|---|---|---|---|"]
    L += [f"| {r.year} | {r.member_days} | {r.mapped_days} | {r.mapped_pct} | {'yes' if r.usable else 'no'} |" for r in cov.itertuples()]
    how = mapped["how"].value_counts().to_dict()
    L += ["", f"How members were mapped: {how}. Ambiguous symbols (two companies in the window): "
              f"{int(mapped['ambiguous'].sum())}.", "",
          "## 2. Insider buying among S&P members (track B)", "",
          f"Bar: 100+ three-insider clusters 2006–2026. **Found: {len(cl3)} three-insider clusters, {len(cl2)} two-insider.**", "",
          "| Year | Open-market buys | 2-insider clusters | 3-insider clusters |", "|---|---|---|---|"]
    by = lambda d, col: d.groupby(d[col].dt.year).size() if len(d) else pd.Series(dtype=int)
    b, c2, c3 = by(buys, "filed"), by(cl2, "date"), by(cl3, "date")
    for y in sorted(set(b.index) | set(c2.index) | set(c3.index)):
        L.append(f"| {y} | {int(b.get(y, 0))} | {int(c2.get(y, 0))} | {int(c3.get(y, 0))} |")
    L += ["", "## 3. Point-in-time fundamentals (track A)", ""]
    if len(fc):
        f2 = fc.groupby("year")[["eps_yoy", "rev_yoy"]].mean().mul(100).round(1)
        tot = fc["eps_yoy"].mean() * 100
        L += [f"Sample: {fc['cik'].nunique()} companies, {len(fc)} member-years from {FACTS_FROM}. Bar: {FACTS_BAR:.0f}% "
              f"of member-years with quarterly EPS growth known by mid-year. **Found: {tot:.1f}%.**", "",
              "| Year | EPS growth known % | Revenue growth known % |", "|---|---|---|"]
        L += [f"| {y} | {r.eps_yoy} | {r.rev_yoy} |" for y, r in f2.iterrows()]
        errs = fc.drop_duplicates("cik")["error"].replace("", np.nan).dropna().value_counts().to_dict()
        if errs:
            L += ["", f"Companies with no usable facts: {errs}."]
    else:
        L += ["No fundamentals sample was taken (see notes)."]
    a_ok = len(fc) and fc["eps_yoy"].mean() * 100 >= FACTS_BAR and all(cov[cov.year >= FACTS_FROM]["usable"])
    b_ok = len(cl3) >= CLUSTER_BAR
    L += ["", "## Verdict", "",
          f"- **Track A (earnings acceleration): {'FEASIBLE' if a_ok else 'NOT FEASIBLE as specified'}.**",
          f"- **Track B (insider clusters): {'FEASIBLE' if b_ok else 'NOT FEASIBLE as specified'}.**"]
    L += ["", "## Notes", ""] + [f"- {n}" for n in notes] + ["", f"*edgar_probe.py {VERSION}. Nothing reads these files yet.*"]
    return "\n".join(L) + "\n"


def main() -> int:
    sec = SEC(os.environ.get("SEC_CONTACT_EMAIL", "").strip())
    notes = []
    raw = sec.get(TICKERS_URL)
    if raw is None:
        print("[edgar_probe] DATA FAILURE: company_tickers.json not found")
        return 1
    current = parse_company_tickers(raw)
    print(f"[edgar_probe] current SEC list: {len(current)} symbols")
    mem = up.parse_membership(MEMBERSHIP.read_text())
    iv = up.intervals(mem)
    start = pd.Timestamp(f"{START_YEAR}-01-01")
    subs_all, buys_all, missing_q = [], [], []
    t0 = time.monotonic()
    for (y, q) in quarters(date.today()):
        try:
            z = sec.get(INSIDER_URL.format(y=y, q=q)) or sec.get(INSIDER_ALT.format(y=y, q=q))
        except Exception as e:
            notes.append(f"{y}Q{q} insider data set failed: {e}")
            continue
        if z is None:
            missing_q.append(f"{y}Q{q}")
            continue
        try:
            s, t = parse_insider_zip(z)
        except Exception as e:
            notes.append(f"{y}Q{q} insider data set unreadable: {type(e).__name__}: {str(e)[:300]}")
            continue
        subs_all.append(s[["accession", "filed", "cik", "symbol"]])
        buys_all.append(t.merge(s[["accession", "filed", "cik"]], on="accession", how="inner"))
        print(f"[edgar_probe] {y}Q{q}: {len(s)} filings, {len(t)} open-market buys ({time.monotonic() - t0:.0f}s)")
    if missing_q:
        notes.append(f"Insider data sets not published (404): {', '.join(missing_q)}")
    if not subs_all:
        print("[edgar_probe] DATA FAILURE: no insider data set could be read; nothing written")
        print("\n".join(notes))
        return 1
    subs = pd.concat(subs_all, ignore_index=True)
    spans = symbol_spans(subs)
    mapped = map_members(iv, spans, current, start)
    import yfinance as yf                                       # SPY calendar only
    cal = pd.DatetimeIndex(yf.download("SPY", start=f"{START_YEAR}-01-01", progress=False, auto_adjust=True).index)
    cov = mapping_coverage(mapped, cal)
    ok_map = mapped.dropna(subset=["cik"]).copy()
    ok_map["cik"] = ok_map["cik"].astype(int)
    buys = pd.concat(buys_all, ignore_index=True)
    tick_of = {}
    for r in ok_map.itertuples():
        tick_of.setdefault(r.cik, r.ticker)
    spans_by_cik = ok_map.groupby("cik")
    keep = []
    for cik, g in buys.groupby("cik"):
        if cik not in tick_of:
            continue
        sp = spans_by_cik.get_group(cik)
        inside = np.zeros(len(g), dtype=bool)
        for r in sp.itertuples():
            e = r.end if r.end is not None and not pd.isna(r.end) else pd.Timestamp("2100-01-01")
            inside |= ((g["filed"] >= r.start) & (g["filed"] < e)).to_numpy()
        keep.append(g[inside].assign(ticker=tick_of[cik]))
    buys_sp = pd.concat(keep, ignore_index=True) if keep else buys.iloc[:0].assign(ticker="")
    cl2, cl3 = clusters(buys_sp, 2), clusters(buys_sp, 3)
    pool = ok_map[ok_map["end"].isna() | (ok_map["end"] > pd.Timestamp(f"{FACTS_FROM}-07-01"))]
    rng = random.Random(SAMPLE_SEED)
    sample = pool.iloc[sorted(rng.sample(range(len(pool)), min(SAMPLE_N, len(pool))))]

    def get_facts(cik: int):
        r = sec.get(FACTS_URL.format(cik=cik))
        return json.loads(r) if r else None
    fc = facts_coverage(sample, get_facts)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_LOGS.mkdir(parents=True, exist_ok=True)
    spans.to_csv(OUT_DATA / "symbol_cik_spans.csv", index=False)
    mapped.to_csv(OUT_DATA / "member_cik_map.csv", index=False)
    cov.to_csv(OUT_DATA / "mapping_coverage.csv", index=False)
    cols = ["filed", "trans_date", "ticker", "cik", "owner", "role", "shares", "price"]
    buys_sp[[c for c in cols if c in buys_sp.columns]].sort_values("filed").to_csv(OUT_DATA / "insider_buys_sp500.csv", index=False)
    cl3.to_csv(OUT_DATA / "clusters_3.csv", index=False)
    cl2.to_csv(OUT_DATA / "clusters_2.csv", index=False)
    fc.to_csv(OUT_DATA / "facts_sample.csv", index=False)
    notes.append(f"{sec.requests} SEC requests; insider data sets read: {len(subs_all)}.")
    md = render(cov, mapped, cl2, cl3, buys_sp, fc, notes, date.today().isoformat())
    (OUT_LOGS / "probe_report.md").write_text(md)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _zip(sub_rows, trans_rows, owner_rows) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SUBMISSION.tsv", "ACCESSION_NUMBER\tFILING_DATE\tPERIOD_OF_REPORT\tDOCUMENT_TYPE\tISSUERCIK\tISSUERNAME\tISSUERTRADINGSYMBOL\n"
                   + "\n".join("\t".join(r) for r in sub_rows) + "\n")
        z.writestr("NONDERIV_TRANS.tsv", "ACCESSION_NUMBER\tNONDERIV_TRANS_SK\tSECURITY_TITLE\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES\tTRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD\n"
                   + "\n".join("\t".join(r) for r in trans_rows) + "\n")
        z.writestr("REPORTINGOWNER.tsv", "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\tRPTOWNER_RELATIONSHIP\n"
                   + "\n".join("\t".join(r) for r in owner_rows) + "\n")
    return buf.getvalue()


def selftest() -> dict:
    f = []
    # client: email required, never in errors; 404 -> None; retry on 429
    try:
        SEC("")
        f.append("no email must be refused")
    except ValueError:
        pass
    calls = []

    def opener(url):
        calls.append(url)
        if "missing" in url:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        if "busy" in url and len(calls) < 3:
            raise urllib.error.HTTPError(url, 429, "slow", {}, None)
        if "dead" in url:
            raise urllib.error.HTTPError(url, 500, "x", {}, None)
        return b"ok"
    sec = SEC("someone@example.com", opener=opener, sleep=lambda s: None)
    if sec.get("https://x/missing") is not None or sec.get("https://x/busy") != b"ok":
        f.append("404 -> None; 429 retried")
    try:
        sec.get("https://x/dead")
        f.append("a dead endpoint must raise")
    except RuntimeError as e:
        if "someone@example.com" in str(e) or "example.com" in str(e):
            f.append("the email must never appear in an error")
    if "example.com" in sec._ua and "someone@example.com" not in sec._ua:
        f.append("user agent must carry the email")
    # pacing: at most 10 per second
    slept = []
    s2 = SEC("a@b.co", opener=lambda u: b"x", sleep=lambda s: slept.append(s))
    for _ in range(5):
        s2.get("https://x/y")
    if len(slept) < 3 or min(slept) <= 0 or max(slept) > MIN_GAP + 1e-9:
        f.append(f"requests must be paced: {slept}")
    # company tickers
    ct = {str(i): {"cik_str": 1000 + i, "ticker": f"T{i}", "title": "x"} for i in range(6000)}
    ct["9999"] = {"cik_str": 1067983, "ticker": "BRK.B", "title": "Berkshire"}
    d = parse_company_tickers(json.dumps(ct).encode())
    if len(d) != 6001 or "BRK-B" not in set(d.symbol):
        f.append("company tickers: Yahoo-style symbols")
    try:
        parse_company_tickers(json.dumps({"0": ct["0"]}).encode())
        f.append("a tiny ticker list must be refused")
    except ValueError:
        pass
    # insider zip
    subs = [["a1", "05-JAN-2015", "2015-01-02", "4", "111", "Old Co", "OLD"],
            ["a2", "2015-01-20", "2015-01-15", "4", "111", "Old Co", "OLD"],
            ["a3", "10-FEB-2015", "2015-02-05", "4", "111", "Old Co", "old"],
            ["a4", "11-FEB-2015", "2015-02-05", "4", "222", "Other", "OLD"],
            ["a5", "12-FEB-2015", "2015-02-06", "4", "333", "Brk", "BRK.B"]]
    trans = [["a1", "1", "Common", "02-JAN-2015", "P", "1000", "10.0", "A"],
             ["a2", "1", "Common", "15-JAN-2015", "P", "500", "10.5", "A"],
             ["a2", "2", "Common", "15-JAN-2015", "S", "500", "10.5", "D"],
             ["a3", "1", "Common", "05-FEB-2015", "P", "200", "11.0", "A"],
             ["a4", "1", "Common", "05-FEB-2015", "A", "200", "0", "A"],
             ["a5", "1", "Common", "06-FEB-2015", "P", "0", "11.0", "A"]]
    owners = [["a1", "9001", "CEO", "Officer"], ["a2", "9002", "CFO", "Officer"], ["a3", "9003", "Dir", "Director"],
              ["a4", "9004", "x", "Director"], ["a5", "9005", "y", "Director"]]
    s, t = parse_insider_zip(_zip(subs, trans, owners))
    if len(s) != 5 or s.loc[s.accession == "a3", "symbol"].iloc[0] != "OLD" or s.loc[s.accession == "a5", "symbol"].iloc[0] != "BRK-B":
        f.append("submissions: symbols upper-cased, BRK.B -> BRK-B")
    if s["filed"].isna().any():
        f.append("both date styles must parse")
    if sorted(t["accession"]) != ["a1", "a2", "a3"]:
        f.append(f"only open-market purchases with shares (P, acquired): {sorted(t['accession'])}")
    try:
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("SUBMISSION.tsv", "ACC\tX\n1\t2\n")
        parse_insider_zip(bad.getvalue())
        f.append("an unexpected layout must raise with the column names")
    except KeyError as e:
        if "ACC" not in str(e):
            f.append("the error must list the columns found")
    # spans and mapping
    sp = symbol_spans(s)
    if len(sp) != 3 or int(sp[(sp.symbol == "OLD") & (sp.cik == 111)]["n"].iloc[0]) != 3:
        f.append(f"symbol spans: {sp.to_dict('records')}")
    iv = {"OLD": [(pd.Timestamp("2014-06-02"), pd.Timestamp("2016-01-04"))],
          "BRK.B": [(pd.Timestamp("2010-01-04"), None)],
          "NEW": [(pd.Timestamp("2020-01-02"), None)],
          "GONE": [(pd.Timestamp("2008-01-02"), pd.Timestamp("2012-01-03"))],
          "EARLY": [(pd.Timestamp("1999-01-04"), pd.Timestamp("2004-01-02"))]}
    cur = pd.DataFrame({"symbol": ["NEW", "OLD"], "cik": [444, 999]})
    m = map_members(iv, sp, cur, pd.Timestamp("2006-01-01")).set_index("ticker")
    if m.loc["OLD", "cik"] != 111 or not m.loc["OLD", "ambiguous"] or m.loc["OLD", "how"] != "insider filings":
        f.append("a past member maps by its as-filed symbol, the busier CIK wins, and the clash is flagged")
    if m.loc["BRK.B", "cik"] != 333 or m.loc["NEW", "cik"] != 444 or m.loc["NEW", "how"] != "current SEC list":
        f.append("current members fall back to today's SEC list")
    if not pd.isna(m.loc["GONE", "cik"]) or "EARLY" in m.index:
        f.append("an unmatched past member stays unmapped; members gone before 2006 are not counted")
    m2 = map_members({"OLD": [(pd.Timestamp("2019-01-02"), pd.Timestamp("2020-01-02"))]}, sp, cur, pd.Timestamp("2006-01-01"))
    if not pd.isna(m2.iloc[0]["cik"]):
        f.append("a symbol filed 4 years away from the membership must not map (ticker reuse)")
    cal = pd.bdate_range("2014-01-01", "2016-12-31")
    cv = mapping_coverage(map_members({"OLD": iv["OLD"], "GONE2": [(pd.Timestamp("2014-06-02"), pd.Timestamp("2016-01-04"))]},
                                      sp, cur, pd.Timestamp("2006-01-01")), cal).set_index("year")
    if cv.loc[2015, "mapped_pct"] != 50.0 or cv.loc[2015, "usable"]:
        f.append(f"coverage: half the member-days mapped is 50%, not usable: {cv.loc[2015].to_dict()}")
    # clusters
    buys = pd.DataFrame({"cik": [1] * 4 + [2] * 2, "ticker": ["A"] * 4 + ["B"] * 2,
                         "filed": pd.to_datetime(["2015-01-05", "2015-01-12", "2015-01-20", "2015-03-30", "2015-01-05", "2015-06-05"]),
                         "trans_date": pd.to_datetime(["2015-01-02", "2015-01-09", "2015-01-16", "2015-03-27", "2015-01-02", "2015-06-02"]),
                         "owner": ["o1", "o2", "o3", "o1", "o7", "o8"], "shares": 100.0, "price": 10.0})
    c3, c2 = clusters(buys, 3), clusters(buys, 2)
    if len(c3) != 1 or c3.iloc[0]["date"] != pd.Timestamp("2015-01-20") or c3.iloc[0]["insiders"] != 3:
        f.append(f"3-insider cluster fires on the third filing: {c3.to_dict('records')}")
    if len(c2) != 1 or c2.iloc[0]["date"] != pd.Timestamp("2015-01-12"):
        f.append(f"2-insider: one per company per 30 days; B's buys are 5 months apart: {c2.to_dict('records')}")
    same = buys.copy(); same["owner"] = "o1"
    if len(clusters(same, 3)) != 0 or len(clusters(same, 2)) != 0:
        f.append("one insider buying three times is not a cluster")
    late = buys.copy(); late.loc[2, "filed"] = pd.Timestamp("2015-03-01")
    if len(clusters(late, 3)) != 0:
        f.append("a buy filed after the 30-day window does not complete the cluster")
    # fundamentals
    def fact(start, end, val, filed, fp="Q1"):
        return {"start": start, "end": end, "val": val, "filed": filed, "fp": fp, "form": "10-Q"}
    facts = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        fact("2014-01-01", "2014-03-31", 1.0, "2014-05-01"),
        fact("2014-01-01", "2014-12-31", 4.0, "2015-02-20", "FY"),
        fact("2015-01-01", "2015-03-31", 1.2, "2015-05-01"),
        fact("2015-01-01", "2015-03-31", 1.25, "2016-05-01"),
        fact("2016-01-01", "2016-03-31", 1.4, "2016-08-15")]}},
        "Revenues": {"units": {"USD": [fact("2015-01-01", "2015-03-31", 100, "2015-05-01")]}}}}}
    q = quarterly(facts, EPS_TAGS, "USD")
    if len(q) != 3 or q.loc[q.end == pd.Timestamp("2015-03-31"), "val"].iloc[0] != 1.2:
        f.append("quarterly: 3-month values only, as first filed (no restatement look-ahead)")
    if not yoy_known(q, pd.Timestamp("2015-06-30")) or yoy_known(q, pd.Timestamp("2015-04-15")):
        f.append("YoY known only after the quarter is filed")
    if yoy_known(q, pd.Timestamp("2016-06-30")):
        f.append("a quarter filed after the as-of date must not count (2016Q1 filed in August)")
    if quarterly({}, EPS_TAGS, "USD").shape[0] != 0 or quarterly(facts, REV_TAGS, "USD")["tag"].iloc[0] != "Revenues":
        f.append("missing facts -> empty; revenue tag found")
    smp = pd.DataFrame([{"ticker": "OLD", "cik": 111, "start": pd.Timestamp("2014-07-01"), "end": pd.Timestamp("2016-01-04")}])
    fc = facts_coverage(smp, lambda c: facts)
    if list(fc["year"]) != [2015] or not fc["eps_yoy"].iloc[0] or fc["rev_yoy"].iloc[0]:
        f.append(f"facts coverage: one member-year (2015), EPS yes, revenue no: {fc.to_dict('records')}")
    fe = facts_coverage(smp, lambda c: (_ for _ in ()).throw(RuntimeError("x")))
    if len(fe) != 1 or fe["eps_yoy"].iloc[0] or not fe["error"].iloc[0]:
        f.append("a fetch error is recorded, not fatal")
    if quarters(date(2006, 8, 1)) != [(2006, 1), (2006, 2)]:
        f.append("quarters: only finished quarters")
    md = render(cv.reset_index(), m.reset_index(), c2, c3, buys.assign(filed=buys["filed"]), fc, ["n"], "T")
    if "Track A" not in md or "Track B" not in md or "Usable years" not in md:
        f.append("report")
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        r = selftest()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 1)
    sys.exit(main())
