"""
edgar_data.py  (v1.0 — 2026-11-19)
───────────────────────────────────
The shared SEC data set behind tracks A (earnings acceleration) and B (insider
cluster buying). Built once in Actions, committed, then read by the labs, so no
lab calls the SEC. Fixes the problems the EDGAR probe found
(claude/edgar_probe_results_2026-11-19.md):

  E1  company number by DATE. Each member is mapped month by month, so a
      company that re-domiciled or reorganized (Transocean 2008, Ingersoll Rand
      2009, Express Scripts 2012, Mylan 2015, Xerox 2020) switches number on the
      right month, and a ticker that passed to another company (GAS: Nicor, then
      AGL Resources) is split correctly.
      Rule per member-month:
        a) PRE_RENAMES: the membership file shows a later ticker that another
           company used at the time (LUK listed as JEF) -> the old ticker first.
        b) the company filing under the member's ticker that month (else within
           6 months), most filings wins. When an acquirer later took the
           ticker (ACE as CB, Actavis as AGN), the target stays the member
           until the deal, which is what the index held.
        c) else the company filing under the ticker at the END of membership,
           if it filed at all that month (ticker unused then, or blank field).
        d) else the same steps for the as-traded ticker in RENAMES.
        e) else a hand-checked CIK in CIK_OVERRIDES (verified in the report by
           its own filings inside the span).
  E2  bankrupt and renamed members: RENAMES maps the membership file's later
      ticker (WAMUQ, FNMA, CITGQ, EKDKQ...) to the one that traded then.
      Ticker fields listing several classes ("CBS, CBS.A") are split.
  B   insiders = officers and directors only (10% owners and funds excluded).
  A   quarterly EPS as first filed; Q4 = full year minus 9-month year-to-date,
      known only when the 10-K was filed. Revenue with a wider tag list.

Quality gates (fixed before the run, not trials):
  mapping 95%+ of member-days in every year 2006-2026;
  EPS growth known by mid-year for 90%+ of member-years 2011-2026.
Anchor decisions and overrides are listed in the report for a hand check.

Lab API: load() -> EdgarData with .cik_for(ticker, date), .buys, .eps, .rev

Run:  python edgar_data.py            (Actions, needs secret SEC_CONTACT_EMAIL)
      python edgar_data.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

import edgar_probe as ep
import universe_probe as up

VERSION = "1.0"
START = pd.Timestamp("2006-01-01")
WIN = 6                                   # months either side for "filing under this ticker"
MAP_GATE, EPS_GATE, EPS_FROM = 95.0, 90.0, 2011
OUT, LOGS = Path("data/edgar"), Path("logs/edgar")
MEMBERSHIP = Path("data/universe/sp500_membership.csv")

# membership-file ticker -> ticker that traded at the time (checked against filings in the report)
RENAMES = {"WAMUQ": "WM", "FNMA": "FNM", "FMCC": "FRE", "CITGQ": "CIT", "EKDKQ": "EK", "ABKFQ": "ABK",
           "CCTYQ": "CC", "RSHCQ": "RSH", "BTUUQ": "BTU", "SUNEQ": "WFR", "ANRZQ": "ANR", "VSTNQ": "VC",
           "DCNAQ": "DCN", "KATE": "LIZ", "IAC": "IACI", "ATGE": "DV", "VIAV": "JDSU", "DXC": "CSC",
           "CMCSK": "CMCSA", "CCEP": "CCE", "VIAB": "VIA-B", "VIAC": "CBS", "LEHMQ": "LEH", "AABA": "YHOO"}
# membership file lists a later ticker AND another company used that ticker then (or the old ticker is needed
# to find the filings): ticker -> (date the member started using it, ticker before that)
PRE_RENAMES = {"JEF": ("2018-05-01", "LUK"), "WBA": ("2014-12-31", "WAG"), "LDOS": ("2013-09-30", "SAI"),
               "WYND": ("2018-06-01", "WYN"), "HSH": ("2012-06-28", "SLE"), "GOOGL": ("2015-10-02", "GOOG"),
               "BHGE": ("2017-07-03", "BHI"), "TMUS": ("2013-05-01", "PCS"), "MTLQQ": ("2009-07-10", "GM"),
               "CBRE": ("2018-03-20", "CBG"), "ES": ("2015-02-19", "NU"), "GHC": ("2013-11-18", "WPO"),
               "LB": ("2013-03-22", "LTD"), "MSI": ("2011-01-04", "MOT"), "SAF": ("2006-07-01", "SAFC"),
               "WELL": ("2018-02-28", "HCN"), "WM": ("2008-10-01", "WMI")}
# one company for the whole membership, where two companies shared the ticker in the same months
PINS = {"WM": 823768}            # Waste Management (WaMu kept filing as WM after its 2008 failure)
# last resort, each verified by the company's own filings inside the span
CIK_OVERRIDES = {"FNMA": 310522, "FMCC": 1026214, "CBS": 813828, "VIAC": 813828, "BIO": 12208, "HCA": 860730,
                 "CMCSK": 1166691, "LSI": 703360, "MOLX": 67472}
NOT_SEC_FILERS = {"FRC", "SBNY"}           # banks that filed with the FDIC, not the SEC
EPS_TAGS = ep.EPS_TAGS
REV_TAGS = ep.REV_TAGS + ("RevenuesNetOfInterestExpense", "InterestAndDividendIncomeOperating",
                          "Revenue", "OperatingRevenue",
                          "RegulatedAndUnregulatedOperatingRevenue", "ElectricUtilityRevenue",
                          "OilAndGasRevenue", "HealthCareOrganizationRevenue", "RealEstateRevenueNet",
                          "InterestIncomeExpenseNet", "TotalRevenuesAndOtherIncome")
_SYM = re.compile(r"^[A-Z]{1,5}(-[A-Z]{1,2})?$")


def month_no(d) -> int:
    d = pd.Timestamp(d)
    return d.year * 12 + d.month - 1


def month_ts(m: int) -> pd.Timestamp:
    return pd.Timestamp(year=m // 12, month=m % 12 + 1, day=1)


def split_symbols(s: str) -> list:
    """'CBS, CBS.A' -> ['CBS', 'CBS-A']; junk dropped."""
    out = []
    for tok in re.split(r"[,;/:\s]+", str(s or "").upper()):
        tok = tok.strip().replace(".", "-").strip("-()")
        if _SYM.match(tok) and tok not in ("NONE", "NA", "N-A") and tok not in out:
            out.append(tok)
    return out


# ── insider data ────────────────────────────────────────────────────────────

def parse_zip(raw: bytes) -> tuple:
    """-> (activity: symbol, cik, month, n;  buys: accession, filed, cik, trans_date, shares, price, owner, role).
    Buys = open-market purchases (P, acquired) by an officer or director."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    sub = ep._read(z, "SUBMISSION")
    s = pd.DataFrame({"accession": sub[ep._col(sub, "ACCESSION_NUMBER")],
                      "filed": ep._dates(sub[ep._col(sub, "FILING_DATE")]),
                      "cik": pd.to_numeric(sub[ep._col(sub, "ISSUERCIK")], errors="coerce"),
                      "raw": sub[ep._col(sub, "ISSUERTRADINGSYMBOL")].fillna("")}).dropna(subset=["cik", "filed"])
    s["cik"] = s["cik"].astype(int)
    s["month"] = s["filed"].dt.year * 12 + s["filed"].dt.month - 1
    ex = s.assign(symbol=s["raw"].map(split_symbols)).explode("symbol")
    ex["symbol"] = ex["symbol"].fillna("")              # blank ticker field still counts as activity
    act = ex.groupby(["symbol", "cik", "month"]).size().rename("n").reset_index()
    nd = ep._read(z, "NONDERIV_TRANS")
    own = ep._read(z, "REPORTINGOWNER")
    t = pd.DataFrame({"accession": nd[ep._col(nd, "ACCESSION_NUMBER")],
                      "code": nd[ep._col(nd, "TRANS_CODE")].fillna("").str.strip().str.upper(),
                      "ad": nd[ep._col(nd, "TRANS_ACQUIRED_DISP_CD")].fillna("").str.strip().str.upper(),
                      "trans_date": ep._dates(nd[ep._col(nd, "TRANS_DATE")]),
                      "shares": pd.to_numeric(nd[ep._col(nd, "TRANS_SHARES")], errors="coerce"),
                      "price": pd.to_numeric(nd[ep._col(nd, "TRANS_PRICEPERSHARE")], errors="coerce")})
    t = t[(t["code"] == "P") & (t["ad"] == "A") & (t["shares"] > 0)]
    o = pd.DataFrame({"accession": own[ep._col(own, "ACCESSION_NUMBER")],
                      "owner": own[ep._col(own, "RPTOWNERCIK")].fillna("").astype(str),
                      "role": own[ep._col(own, "RPTOWNER_RELATIONSHIP")].fillna("").astype(str)})
    r = o["role"].str.upper()
    o = o[r.str.contains("DIRECTOR") | r.str.contains("OFFICER")].sort_values(["accession", "owner"])
    o = o.drop_duplicates("accession")
    t = t.merge(o, on="accession", how="inner").merge(s[["accession", "filed", "cik"]], on="accession", how="inner")
    return act, t[["accession", "filed", "cik", "trans_date", "shares", "price", "owner", "role"]]


class Activity:
    """Monthly filing counts per (cik, ticker) and per cik, with windowed sums."""

    def __init__(self, act: pd.DataFrame):
        a = act.groupby(["symbol", "cik", "month"])["n"].sum().reset_index()
        self.by_sym = {}                          # symbol -> {cik: {month: n}}
        for (sym, cik), g in a.groupby(["symbol", "cik"]):
            self.by_sym.setdefault(sym, {})[int(cik)] = dict(zip(g["month"].astype(int), g["n"].astype(int)))
        tot = a.groupby(["cik", "month"])["n"].sum().reset_index()
        self.any = {int(c): dict(zip(g["month"].astype(int), g["n"].astype(int))) for c, g in tot.groupby("cik")}

    @staticmethod
    def _sum(d: dict, m: int, w: int) -> int:
        return sum(d.get(k, 0) for k in range(m - w, m + w + 1)) if d else 0

    def on(self, cik: int, sym: str, m: int, w: int = WIN) -> int:
        return self._sum(self.by_sym.get(sym, {}).get(cik, {}), m, w)

    def total(self, cik: int, m: int, w: int = 0) -> int:
        return self._sum(self.any.get(cik, {}), m, w)

    def filers(self, sym: str, m: int, w: int = WIN) -> dict:
        return {c: self._sum(d, m, w) for c, d in self.by_sym.get(sym, {}).items() if self._sum(d, m, w) > 0}


def _choose(act: Activity, sym: str, m: int, anchor: Optional[int]) -> tuple:
    """(b) the company filing under the ticker that month (else within 6 months), most filings wins;
    (c) else the end-of-membership company if it filed at all that month (ticker unused then, or blank)."""
    for w in (1, WIN):
        here = act.filers(sym, m, w)
        if here:
            return max(here, key=lambda c: (here[c], -c)), "ticker at the time"
    if anchor is not None and act.total(anchor, m, 1) > 0:
        return anchor, "end-of-membership company"
    return None, ""


def anchor_for(act: Activity, sym: str, end_m: int) -> Optional[int]:
    """Company filing under `sym` nearest the end of membership (within 24 months before it)."""
    best = None
    for w in (WIN, 12, 24):
        cands = {c: sum(d.get(k, 0) for k in range(end_m - w, end_m + 1)) for c, d in act.by_sym.get(sym, {}).items()}
        cands = {c: n for c, n in cands.items() if n > 0}
        if cands:
            best = max(cands, key=lambda c: (cands[c], -c))
            break
    return best


def map_months(iv: dict, act: Activity, last_m: int) -> pd.DataFrame:
    rows = []
    s0 = month_no(START)
    for tk, spans in iv.items():
        y = up.yahoo_symbol(tk)
        alt = RENAMES.get(tk) or RENAMES.get(y)
        for a, b in spans:
            if b is not None and b <= START:
                continue
            m0 = max(month_no(a), s0)
            m1 = month_no((b - pd.Timedelta(days=1)) if b is not None else month_ts(last_m))
            anc = anchor_for(act, y, m1)
            anc_alt = anchor_for(act, alt, m1) if alt else None
            pre = PRE_RENAMES.get(tk) or PRE_RENAMES.get(y)
            for m in range(m0, m1 + 1):
                cik, how = None, ""
                if tk in PINS:
                    cik, how = PINS[tk], "pinned"
                elif pre and m < month_no(pre[0]):
                    cik, how = _choose(act, pre[1], m, None)
                    how = f"was {pre[1]}: {how}" if cik is not None else ""
                if cik is None:
                    cik, how = _choose(act, y, m, anc)
                if cik is None and alt:
                    cik, how = _choose(act, alt, m, anc_alt)
                    how = f"rename {alt}: {how}" if cik is not None else ""
                if cik is None and (tk in CIK_OVERRIDES or y in CIK_OVERRIDES):
                    oc = CIK_OVERRIDES.get(tk, CIK_OVERRIDES.get(y))
                    cik, how = oc, "override"
                if cik is None:
                    how = "not an SEC filer" if y in NOT_SEC_FILERS else "unmapped"
                rows.append({"ticker": tk, "span_start": a, "span_end": b, "month": m, "cik": cik, "how": how})
    return pd.DataFrame(rows, columns=["ticker", "span_start", "span_end", "month", "cik", "how"])


def coverage(mm: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Member-days mapped by year (a member-day is mapped when its month is)."""
    cal = cal[cal >= START]
    cm = pd.Series(cal.year * 12 + cal.month - 1, index=cal)
    out = {}
    for (tk, a, b), g in mm.groupby(["ticker", "span_start", "span_end"], dropna=False):
        e = b if b is not None and not pd.isna(b) else pd.Timestamp("2100-01-01")
        days = cm[(cm.index >= a) & (cm.index < e)]
        mapped = set(g.loc[g["cik"].notna(), "month"].astype(int))
        for y, mm_ in days.groupby(days.index.year):
            d = out.setdefault(int(y), [0, 0])
            d[0] += len(mm_)
            d[1] += int(mm_.isin(mapped).sum())
    return pd.DataFrame([{"year": y, "member_days": v[0], "mapped_days": v[1], "mapped_pct": round(v[1] / v[0] * 100, 1),
                          "pass": v[1] / v[0] * 100 >= MAP_GATE} for y, v in sorted(out.items())])


def attach_buys(buys: pd.DataFrame, mm: pd.DataFrame) -> pd.DataFrame:
    """Keep buys at companies that were S&P members that month; tag with the member ticker."""
    key = mm.dropna(subset=["cik"]).assign(cik=lambda d: d["cik"].astype(int)).drop_duplicates(["cik", "month"])
    b = buys.assign(month=buys["filed"].dt.year * 12 + buys["filed"].dt.month - 1)
    b = b.merge(key[["cik", "month", "ticker"]], on=["cik", "month"], how="inner")
    return b.drop(columns="month").drop_duplicates("accession").sort_values("filed").reset_index(drop=True)


# ── fundamentals ────────────────────────────────────────────────────────────

def _facts_rows(facts: dict, tags: tuple, unit_prefix: str) -> pd.DataFrame:
    g = (facts.get("facts") or {}).get("us-gaap") or {}
    for tag in tags:
        for u, vals in ((g.get(tag) or {}).get("units") or {}).items():
            if not u.startswith(unit_prefix):
                continue
            df = pd.DataFrame(vals)
            if df.empty or not {"start", "end", "val", "filed"} <= set(df.columns):
                continue
            for c in ("start", "end", "filed"):
                df[c] = pd.to_datetime(df[c], errors="coerce")
            df = df.dropna(subset=["start", "end", "filed", "val"])
            if len(df):
                return df.assign(tag=tag, dur=(df["end"] - df["start"]).dt.days)
    return pd.DataFrame(columns=["start", "end", "val", "filed", "tag", "dur"])


def quarters_pit(facts: dict, tags: tuple, unit_prefix: str = "USD") -> pd.DataFrame:
    """3-month values as first filed, plus Q4 derived as full year minus 9-month YTD (same start),
    known on the later of the two filing dates. -> end, val, filed, derived, tag"""
    df = _facts_rows(facts, tags, unit_prefix)
    if df.empty:
        return pd.DataFrame(columns=["end", "val", "filed", "derived", "tag"])
    first = lambda d: d.sort_values("filed").drop_duplicates(["start", "end"], keep="first")
    q = first(df[(df.dur >= 80) & (df.dur <= 100)])
    fy = first(df[(df.dur >= 350) & (df.dur <= 380)])
    ytd9 = first(df[(df.dur >= 260) & (df.dur <= 285)])
    out = [q.assign(derived=False)[["end", "val", "filed", "derived", "tag"]]]
    have = set(q["end"])
    der = []
    for r in fy.itertuples():
        if r.end in have:
            continue
        n = ytd9[(ytd9["start"] - r.start).abs().dt.days <= 7]
        if len(n):
            n = n.iloc[0]
            der.append({"end": r.end, "val": float(r.val) - float(n["val"]), "filed": max(r.filed, n["filed"]),
                        "derived": True, "tag": r.tag})
    if der:
        out.append(pd.DataFrame(der))
    res = pd.concat(out, ignore_index=True).sort_values("end")
    return res.drop_duplicates("end", keep="first").reset_index(drop=True)


# ── run ─────────────────────────────────────────────────────────────────────

class EdgarData:
    def __init__(self, months: pd.DataFrame, buys: pd.DataFrame, eps: pd.DataFrame, rev: pd.DataFrame):
        self.months, self.buys, self.eps, self.rev = months, buys, eps, rev
        k = months.dropna(subset=["cik"])
        self._ix = {(t, int(m)): int(c) for t, m, c in zip(k["ticker"], k["month"], k["cik"])}

    def cik_for(self, ticker: str, d) -> Optional[int]:
        return self._ix.get((ticker, month_no(d)))


def load(root: Path = Path(".")) -> EdgarData:
    d = root / OUT
    months = pd.read_csv(d / "member_cik_months.csv.gz", parse_dates=["span_start", "span_end"])
    buys = pd.read_csv(d / "insider_buys_od.csv", parse_dates=["filed", "trans_date"])
    eps = pd.read_csv(d / "eps_quarterly.csv.gz", parse_dates=["end", "filed"])
    rev = pd.read_csv(d / "rev_quarterly.csv.gz", parse_dates=["end", "filed"])
    return EdgarData(months, buys, eps, rev)


def render(cov, mm, buys, cl2, cl3, fc, decisions, ovr, notes, stamp) -> str:
    bad = cov[~cov["pass"]]["year"].tolist()
    L = [f"# EDGAR data {VERSION} — {stamp}", "",
         "Shared SEC data for tracks A and B, with the probe's fixes (company number by date, renamed and "
         "bankrupt members, officers and directors only, Q4 derived).", "",
         f"## Mapping (gate {MAP_GATE:.0f}% of member-days every year): **{'PASS' if not bad else 'FAIL ' + str(bad)}**", "",
         "| Year | Member-days | Mapped % |", "|---|---|---|"]
    L += [f"| {r.year} | {r.member_days} | {r.mapped_pct} |" for r in cov.itertuples()]
    how = mm.groupby(mm["how"].str.replace(r"^rename \S+: ", "rename: ", regex=True))["month"].size().to_dict()
    L += ["", f"Member-months by method: {how}", ""]
    um = mm[mm["cik"].isna()].groupby("ticker")["month"].agg(["min", "max", "size"])
    L += ["Unmapped or not SEC filers (member-months): "
          + (", ".join(f"{t} {month_ts(r['min']).strftime('%Y-%m')}..{month_ts(r['max']).strftime('%Y-%m')} ({r['size']})"
                       for t, r in um.iterrows()) or "none"), "",
          "### Tickers later taken by another company (check against index history)", "",
          "The company filing under the ticker at the time is used. If the index actually held the later company "
          "(as with Leucadia listed as JEF), add the ticker to PRE_RENAMES.", "",
          "| Ticker | Months | CIK used | Later company (already filing under another ticker) |", "|---|---|---|---|"]
    L += [f"| {d['ticker']} | {d['from']}..{d['to']} | {d['cik']} | {d['other'] or '—'} |" for d in decisions] or ["| none | | | |"]
    L += ["", "### Overrides and renames, checked against the company's own filings", "",
          "| Ticker | Method | CIK | Filings by that CIK inside the span |", "|---|---|---|---|"]
    L += [f"| {o['ticker']} | {o['how']} | {o['cik']} | {o['filings']} |" for o in ovr] or ["| none | | | |"]
    L += ["", "## Insider buying, officers and directors only (track B)", "",
          f"{len(buys)} open-market buys at S&P members; clusters: {len(cl3)} with 3+ insiders, {len(cl2)} with 2+.", "",
          "| Year | Buys | 2+ clusters | 3+ clusters |", "|---|---|---|---|"]
    yb = buys.groupby(buys["filed"].dt.year).size()
    y2 = cl2.groupby(pd.to_datetime(cl2["date"]).dt.year).size() if len(cl2) else pd.Series(dtype=int)
    y3 = cl3.groupby(pd.to_datetime(cl3["date"]).dt.year).size() if len(cl3) else pd.Series(dtype=int)
    L += [f"| {y} | {int(yb.get(y, 0))} | {int(y2.get(y, 0))} | {int(y3.get(y, 0))} |" for y in sorted(yb.index)]
    if len(fc):
        f2 = fc[fc.year >= EPS_FROM]
        tot = f2["eps_yoy"].mean() * 100
        L += ["", f"## Point-in-time EPS (gate {EPS_GATE:.0f}% of member-years {EPS_FROM}+): "
                  f"**{'PASS' if tot >= EPS_GATE else 'FAIL'} ({tot:.1f}%)**", "",
              "| Year | EPS growth known % | Revenue growth known % | Member-years |", "|---|---|---|---|"]
        g = fc.groupby("year").agg(eps=("eps_yoy", "mean"), rev=("rev_yoy", "mean"), n=("eps_yoy", "size"))
        L += [f"| {y} | {r.eps * 100:.1f} | {r.rev * 100:.1f} | {r.n} |" for y, r in g.iterrows()]
    L += ["", "## Notes", ""] + [f"- {n}" for n in notes] + ["", f"*edgar_data.py {VERSION}. Read by the track A and B labs via edgar_data.load().*"]
    return "\n".join(L) + "\n"


def anchor_decisions(mm: pd.DataFrame, act: Activity) -> list:
    """Spans where the ticker belonged to one company and was later taken by another that was already
    filing under a different ticker (ACE took CB, Actavis took AGN, Leucadia became JEF). Rule (b) keeps the
    company filing under the ticker at the time; listed so each can be checked against index history."""
    out = []
    for (tk, s0), g in mm.groupby(["ticker", "span_start"]):
        y = up.yahoo_symbol(tk)
        anc = anchor_for(act, y, int(g["month"].max()))
        if anc is None:
            continue
        hit = g[(g["how"] == "ticker at the time") & (g["cik"] != anc)]
        hit = hit[[act.total(anc, int(m), 1) - act.on(anc, y, int(m), 1) - act.on(anc, "", int(m), 1) > 0 for m in hit["month"]]]
        if len(hit):
            out.append({"ticker": tk, "from": month_ts(int(hit["month"].min())).strftime("%Y-%m"),
                        "to": month_ts(int(hit["month"].max())).strftime("%Y-%m"),
                        "cik": ", ".join(str(int(c)) for c in sorted(hit["cik"].unique())), "other": str(anc)})
    return out


def override_checks(mm: pd.DataFrame, act: Activity) -> list:
    out = []
    o = mm[mm["how"].str.startswith("override") | mm["how"].str.startswith("rename") | (mm["how"] == "pinned")]
    for (tk, how0, cik), g in o.assign(h=o["how"].str.split(":").str[0]).groupby(["ticker", "h", "cik"]):
        n = sum(act.total(int(cik), int(m)) for m in g["month"])
        out.append({"ticker": tk, "how": how0, "cik": int(cik), "filings": n})
    return out


def main() -> int:
    sec = ep.SEC(os.environ.get("SEC_CONTACT_EMAIL", "").strip())
    notes = []
    mem = up.parse_membership(MEMBERSHIP.read_text())
    iv = up.intervals(mem)
    acts, buys_l, t0 = [], [], time.monotonic()
    for (y, q) in ep.quarters(date.today()):
        try:
            z = sec.get(ep.INSIDER_URL.format(y=y, q=q))
        except Exception as e:
            notes.append(f"{y}Q{q}: {e}")
            continue
        if z is None:
            notes.append(f"{y}Q{q}: not published (404)")
            continue
        try:
            a, b = parse_zip(z)
        except Exception as e:
            notes.append(f"{y}Q{q} unreadable: {type(e).__name__}: {str(e)[:300]}")
            continue
        acts.append(a)
        buys_l.append(b)
        print(f"[edgar_data] {y}Q{q}: {int(a['n'].sum())} filings, {len(b)} officer/director buys ({time.monotonic() - t0:.0f}s)")
    if not acts:
        print("[edgar_data] DATA FAILURE: no insider data set read; nothing written")
        return 1
    act = Activity(pd.concat(acts, ignore_index=True))
    last_m = max(max(d) for d in act.any.values())
    mm = map_months(iv, act, last_m)
    import yfinance as yf
    cal = pd.DatetimeIndex(yf.download("SPY", start="2006-01-01", progress=False, auto_adjust=True).index)
    cal = cal[cal <= month_ts(last_m) + pd.offsets.MonthEnd(0)]
    cov = coverage(mm, cal)
    buys = attach_buys(pd.concat(buys_l, ignore_index=True), mm)
    cl2, cl3 = ep.clusters(buys, 2), ep.clusters(buys, 3)
    eps_l, rev_l, err = [], [], {}
    ciks = sorted(mm["cik"].dropna().astype(int).unique())
    print(f"[edgar_data] companyfacts for {len(ciks)} companies")
    for i, c in enumerate(ciks):
        try:
            r = sec.get(ep.FACTS_URL.format(cik=c))
            f = json.loads(r) if r else None
        except Exception as e:
            err[c] = type(e).__name__
            continue
        if not f:
            err[c] = "no companyfacts"
            continue
        eps_l.append(quarters_pit(f, EPS_TAGS).assign(cik=c))
        rev_l.append(quarters_pit(f, REV_TAGS).assign(cik=c))
        if i % 200 == 0:
            print(f"[edgar_data]   {i}/{len(ciks)} ({time.monotonic() - t0:.0f}s)")
    eps = pd.concat(eps_l, ignore_index=True) if eps_l else pd.DataFrame(columns=["end", "val", "filed", "derived", "tag", "cik"])
    rev = pd.concat(rev_l, ignore_index=True) if rev_l else eps.iloc[:0]
    if err:
        notes.append(f"companyfacts missing for {len(err)} companies: {dict(list(pd.Series(err).value_counts().items()))}")
    fc = facts_cov(mm, eps, rev)
    OUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    mm.to_csv(OUT / "member_cik_months.csv.gz", index=False)
    cov.to_csv(OUT / "mapping_coverage.csv", index=False)
    buys.to_csv(OUT / "insider_buys_od.csv", index=False)
    cl2.to_csv(OUT / "clusters_2.csv", index=False)
    cl3.to_csv(OUT / "clusters_3.csv", index=False)
    eps[["cik", "end", "val", "filed", "derived", "tag"]].to_csv(OUT / "eps_quarterly.csv.gz", index=False)
    rev[["cik", "end", "val", "filed", "derived", "tag"]].to_csv(OUT / "rev_quarterly.csv.gz", index=False)
    for old in ("insider_buys_sp500.csv", "member_cik_map.csv"):          # probe files superseded
        if (OUT / old).exists():
            (OUT / old).unlink()
    notes.append(f"{sec.requests} SEC requests; {len(acts)} insider data sets read; last filing month "
                 f"{month_ts(last_m).strftime('%Y-%m')}.")
    md = render(cov, mm, buys, cl2, cl3, fc, anchor_decisions(mm, act), override_checks(mm, act), notes, date.today().isoformat())
    (LOGS / "data_report.md").write_text(md)
    print(md)
    gate_ok = bool(cov["pass"].all()) and len(fc) and fc[fc.year >= EPS_FROM]["eps_yoy"].mean() * 100 >= EPS_GATE
    print(f"[edgar_data] quality gates: {'PASS' if gate_ok else 'FAIL'}")
    return 0


def facts_cov(mm: pd.DataFrame, eps: pd.DataFrame, rev: pd.DataFrame) -> pd.DataFrame:
    """Every member-year (member on June 30): was YoY quarterly EPS / revenue growth computable then?"""
    E = {c: g for c, g in eps.groupby("cik")}
    R = {c: g for c, g in rev.groupby("cik")}
    rows = []
    k = mm.dropna(subset=["cik"])
    jun = k[k["month"] % 12 == 5]
    for r in jun.drop_duplicates(["ticker", "month"]).itertuples():
        y = r.month // 12
        asof = pd.Timestamp(f"{y}-06-30")
        e, v = E.get(int(r.cik)), R.get(int(r.cik))
        rows.append({"ticker": r.ticker, "cik": int(r.cik), "year": y,
                     "eps_yoy": bool(e is not None and ep.yoy_known(e, asof)),
                     "rev_yoy": bool(v is not None and ep.yoy_known(v, asof))})
    return pd.DataFrame(rows, columns=["ticker", "cik", "year", "eps_yoy", "rev_yoy"])


# ── selftest ────────────────────────────────────────────────────────────────

def _act(rows) -> Activity:
    """rows: (symbol, cik, 'YYYY-MM', n)"""
    return Activity(pd.DataFrame([{"symbol": s, "cik": c, "month": month_no(pd.Timestamp(m + "-01")), "n": n}
                                  for s, c, m, n in rows]))


def _monthly(sym, cik, a, b, n=3):
    return [(sym, cik, p.strftime("%Y-%m"), n) for p in pd.period_range(a, b, freq="M")]


def selftest() -> dict:
    f = []
    if split_symbols("CBS, CBS.A") != ["CBS", "CBS-A"] or split_symbols("NONE") != [] or split_symbols("brk.b") != ["BRK-B"]:
        f.append(f"split_symbols: {split_symbols('CBS, CBS.A')}")
    if split_symbols("BIO / BIO.B") != ["BIO", "BIO-B"] or split_symbols("") != []:
        f.append("split_symbols separators")
    # zip: officer/director only, all owners considered, multi-symbol activity
    subs = [["a1", "05-JAN-2015", "2015-01-02", "4", "111", "X", "CBS, CBS.A"],
            ["a2", "2015-01-20", "2015-01-15", "4", "111", "X", "CBS"],
            ["a3", "10-FEB-2015", "2015-02-05", "4", "111", "X", ""]]
    trans = [["a1", "1", "C", "02-JAN-2015", "P", "1000", "10", "A"],
             ["a2", "1", "C", "15-JAN-2015", "P", "500", "10", "A"],
             ["a3", "1", "C", "05-FEB-2015", "P", "200", "11", "A"]]
    owners = [["a1", "9001", "Fund", "TenPercentOwner"], ["a1", "9002", "CEO", "Director,Officer"],
              ["a2", "9003", "Fund2", "TenPercentOwner"], ["a3", "9004", "Dir", "DirectorOther"]]
    act_df, b = parse_zip(ep._zip(subs, trans, owners))
    if sorted(b["accession"]) != ["a1", "a3"] or b.loc[b.accession == "a1", "owner"].iloc[0] != "9002":
        f.append(f"buys: officers/directors only, joint filing keeps the officer: {b[['accession', 'owner']].values.tolist()}")
    a = Activity(act_df)
    m15 = month_no("2015-01-15")
    if a.on(111, "CBS", m15, 0) != 2 or a.on(111, "CBS-A", m15, 0) != 1 or a.total(111, month_no("2015-02-01")) != 1:
        f.append("activity: each class symbol counted; blank symbol still counts as company activity")
    # E1: CIK change inside one span (Transocean-style)
    act = _act(_monthly("RIG", 1, "2006-01", "2008-12") + _monthly("RIG", 2, "2009-01", "2012-12"))
    iv = {"RIG": [(pd.Timestamp("2006-01-02"), pd.Timestamp("2012-07-02"))]}
    mm = map_months(iv, act, month_no("2012-12-01")).set_index("month")
    if mm.loc[month_no("2007-06-01"), "cik"] != 1 or mm.loc[month_no("2010-06-01"), "cik"] != 2:
        f.append("E1: company number must switch by date")
    # renamed after the fact: LUK listed as JEF while Jefferies Group used JEF (PRE_RENAMES)
    act = _act(_monthly("LUK", 96, "2006-01", "2018-04") + _monthly("JEF", 96, "2018-05", "2020-12")
               + _monthly("JEF", 108, "2006-01", "2013-03", 5))
    mm = map_months({"JEF": [(pd.Timestamp("2007-08-27"), pd.Timestamp("2019-09-26"))]}, act, month_no("2020-12-01")).set_index("month")
    for mo, want in (("2010-06-01", 96), ("2015-06-01", 96), ("2019-06-01", 96)):
        if mm.loc[month_no(mo), "cik"] != want:
            f.append(f"JEF {mo}: Leucadia is the member: {mm.loc[month_no(mo)].to_dict()}")
    # acquirer later takes the ticker (ACE as CB): the target stays the member until the deal; listed for review
    act = _act(_monthly("CB", 20, "2006-01", "2016-01") + _monthly("ACE", 89, "2006-01", "2016-01")
               + _monthly("CB", 89, "2016-02", "2020-12"))
    iv = {"CB": [(pd.Timestamp("2006-01-02"), None)]}
    mm = map_months(iv, act, month_no("2020-12-01"))
    mi = mm.set_index("month")
    if mi.loc[month_no("2010-06-01"), "cik"] != 20 or mi.loc[month_no("2018-06-01"), "cik"] != 89:
        f.append("CB: old Chubb until the deal, then the merged company")
    dec = anchor_decisions(mm, act)
    if len(dec) != 1 or dec[0]["other"] != "89" or dec[0]["cik"] != "20":
        f.append(f"CB must be listed for review: {dec}")
    # ticker unused at the time, end company filing under another symbol -> end company
    act = _act(_monthly("OLDT", 55, "2006-01", "2009-12") + _monthly("NEWT", 55, "2010-01", "2014-12"))
    mm = map_months({"NEWT": [(pd.Timestamp("2006-01-02"), pd.Timestamp("2014-12-01"))]}, act, month_no("2014-12-01"))
    if set(mm["cik"]) != {55} or "end-of-membership company" not in set(mm["how"]):
        f.append("renamed member with an unused ticker maps to the end company")
    # ticker passed to another company: GAS
    act = _act(_monthly("GAS", 72, "2006-01", "2011-12") + _monthly("ATG", 100, "2006-01", "2011-12")
               + _monthly("GAS", 100, "2012-01", "2016-07"))
    iv = {"GAS": [(pd.Timestamp("2006-01-02"), pd.Timestamp("2011-12-13")), (pd.Timestamp("2011-12-13"), pd.Timestamp("2016-07-01"))]}
    mm = map_months(iv, act, month_no("2016-07-01"))
    s1 = mm[mm.span_start == pd.Timestamp("2006-01-02")]
    s2 = mm[mm.span_start == pd.Timestamp("2011-12-13")]
    if set(s1["cik"]) != {72} or set(s2[s2.month >= month_no("2012-01-01")]["cik"]) != {100}:
        f.append(f"GAS: Nicor then AGL: {set(s1['cik'])}, {set(s2['cik'])}")
    act = _act(_monthly("WM", 933, "2006-01", "2009-03", 9) + _monthly("WMI", 823, "2006-01", "2008-09")
               + _monthly("WM", 823, "2008-10", "2010-12"))
    mm = map_months({"WM": [(pd.Timestamp("2006-01-02"), None)]}, act, month_no("2010-12-01"))
    if set(mm["cik"]) != {823768}:
        f.append("WM is pinned to Waste Management")
    # bankrupt rename + override + FDIC
    act = _act(_monthly("WM", 5, "2006-01", "2008-09") + _monthly("", 310522, "2006-01", "2008-09", 1))
    iv = {"WAMUQ": [(pd.Timestamp("2006-01-02"), pd.Timestamp("2008-09-30"))],
          "FNMA": [(pd.Timestamp("2006-01-02"), pd.Timestamp("2008-09-11"))],
          "SBNY": [(pd.Timestamp("2021-12-20"), pd.Timestamp("2023-03-15"))],
          "ZZZ": [(pd.Timestamp("2006-01-02"), pd.Timestamp("2006-06-01"))]}
    mm = map_months(iv, act, month_no("2023-03-01"))
    g = mm.groupby("ticker")
    if set(g.get_group("WAMUQ")["cik"]) != {5} or not g.get_group("WAMUQ")["how"].str.startswith("rename WM").all():
        f.append("bankrupt member maps through RENAMES")
    if set(g.get_group("FNMA")["cik"]) != {310522}:
        f.append("FNMA maps (rename FNM has no filer here, override)")
    if set(g.get_group("SBNY")["how"]) != {"not an SEC filer"} or g.get_group("ZZZ")["cik"].notna().any():
        f.append("FDIC filers labelled; unknown stays unmapped")
    oc = override_checks(mm, act)
    if not any(o["ticker"] == "FNMA" and o["filings"] > 0 for o in oc):
        f.append("override check must count the company's own filings")
    # coverage
    cal = pd.bdate_range("2006-01-02", "2008-12-31")
    cv = coverage(mm, cal).set_index("year")
    if not (80 < cv.loc[2006, "mapped_pct"] < 85) or cv.loc[2006, "pass"]:
        f.append(f"coverage counts unmapped member-days: {cv.loc[2006].to_dict()}")
    # buys attach only while a member, with the member ticker
    buys = pd.DataFrame({"accession": ["x1", "x2", "x3"], "filed": pd.to_datetime(["2007-05-01", "2009-05-01", "2007-05-02"]),
                         "cik": [5, 5, 999], "trans_date": pd.to_datetime(["2007-04-28", "2009-04-28", "2007-04-30"]),
                         "shares": 1.0, "price": 1.0, "owner": "o", "role": "Director"})
    ab = attach_buys(buys, mm)
    if list(ab["accession"]) != ["x1"] or ab["ticker"].iloc[0] != "WAMUQ":
        f.append(f"buys: only while a member: {ab[['accession', 'ticker']].values.tolist()}")
    # fundamentals: Q4 derived, known only at 10-K filing; restatement ignored
    def fct(s, e, v, filed):
        return {"start": s, "end": e, "val": v, "filed": filed, "form": "10-Q"}
    facts = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        fct("2014-01-01", "2014-03-31", 1.0, "2014-05-01"), fct("2014-04-01", "2014-06-30", 1.0, "2014-08-01"),
        fct("2014-07-01", "2014-09-30", 1.0, "2014-11-01"), fct("2014-01-01", "2014-09-30", 3.0, "2014-11-01"),
        fct("2014-01-01", "2014-12-31", 4.5, "2015-02-25"), fct("2014-01-01", "2014-12-31", 4.0, "2016-02-25"),
        fct("2015-01-01", "2015-03-31", 1.3, "2015-05-01")]}}}}}
    q = quarters_pit(facts, EPS_TAGS)
    q4 = q[q.end == pd.Timestamp("2014-12-31")]
    if len(q4) != 1 or abs(q4["val"].iloc[0] - 1.5) > 1e-9 or not q4["derived"].iloc[0] or q4["filed"].iloc[0] != pd.Timestamp("2015-02-25"):
        f.append(f"Q4 = FY as first filed (4.5) − 9M (3.0) = 1.5, known 2015-02-25: {q4.to_dict('records')}")
    if len(q) != 5:
        f.append(f"5 quarters expected: {len(q)}")
    if not ep.yoy_known(q, pd.Timestamp("2015-06-30")):
        f.append("YoY known mid-2015")
    if len(quarters_pit({}, EPS_TAGS)) != 0:
        f.append("no facts -> empty")
    # facts coverage over member-years
    mm2 = pd.DataFrame({"ticker": "A", "span_start": pd.Timestamp("2014-01-02"), "span_end": pd.NaT,
                        "month": [month_no("2015-06-01"), month_no("2016-06-01")], "cik": [7, 7], "how": "x"})
    fc = facts_cov(mm2, q.assign(cik=7), q.iloc[:0].assign(cik=7))
    if list(fc["year"]) != [2015, 2016] or not fc["eps_yoy"].iloc[0] or fc["eps_yoy"].iloc[1]:
        f.append(f"facts coverage by member-year: {fc.to_dict('records')}")
    # loader round trip
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / OUT
        p.mkdir(parents=True)
        mm.to_csv(p / "member_cik_months.csv.gz", index=False)
        ab.to_csv(p / "insider_buys_od.csv", index=False)
        q.assign(cik=7).to_csv(p / "eps_quarterly.csv.gz", index=False)
        q.assign(cik=7).to_csv(p / "rev_quarterly.csv.gz", index=False)
        D = load(Path(td))
        if D.cik_for("WAMUQ", "2007-03-15") != 5 or D.cik_for("WAMUQ", "2009-03-15") is not None:
            f.append("loader cik_for by date")
    md = render(cv.reset_index(), mm, ab, ep.clusters(ab, 2), ep.clusters(ab, 3), fc,
                anchor_decisions(mm, act), oc, ["n"], "T")
    if "Mapping" not in md or "later taken" not in md:
        f.append("report")
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        r = selftest()
        print(json.dumps(r, indent=2, default=str))
        sys.exit(0 if r["ok"] else 1)
    sys.exit(main())
