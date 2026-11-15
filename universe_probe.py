"""
universe_probe.py  (v1.0 — 2026-11-14)
──────────────────────────────────────
PROBE, not a backtest. Question: can a point-in-time S&P 500 stock universe be
built from free data, and how much of it does Yahoo still have prices for?

WHY
  The swing backtest's stock scope uses today's top holdings, so it only sees
  survivors (fix_status N61). Before any stock setup is tested or a leader
  screener is trusted, we need to know (a) which stocks were in the index on
  each past date, and (b) what share of them still have price history.

WHAT IT DOES
  1. Finds the historical-membership file in the public dataset SOURCE_REPO
     (one row per change date: date, comma-separated tickers) and saves a copy
     to data/universe/sp500_membership.csv with its source noted.
  2. For the first membership date of each year from START_YEAR, downloads
     Yahoo prices for every ticker that was ever a member and reports, per
     year, the share of that year's members with at least MIN_BARS bars in
     that year.
  3. Writes data/universe/coverage_by_year.csv and logs/universe/probe_report.md.

  A year under COVERAGE_BAR is marked NOT USABLE: Yahoo drops most delisted
  companies, and a test on the survivors alone would flatter every setup.
  Nothing downstream reads these files yet.

Run:  python universe_probe.py            (Actions: needs network)
      python universe_probe.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

VERSION = "v1.0"
SOURCE_REPO = "fja05680/sp500"
FILE_HINT = "historical components"
START_YEAR = 2005
MIN_BARS = 200
COVERAGE_BAR = 80.0
BATCH = 80
OUT_DIR = Path("data/universe")
LOG_DIR = Path("logs/universe")


# ── membership ──────────────────────────────────────────────────────────────

def _get(url: str, accept: str = "application/vnd.github+json") -> bytes:
    h = {"User-Agent": "portfolio-tracker-universe-probe", "Accept": accept}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and "api.github.com" in url:
        h["Authorization"] = f"Bearer {tok}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
        return r.read()


def pick_file(listing: list) -> Optional[dict]:
    """The newest CSV whose name mentions the historical components."""
    c = [x for x in listing if x.get("name", "").lower().endswith(".csv") and FILE_HINT in x["name"].lower()]
    def stamp(x):                      # "(MM-DD-YYYY)" in the name -> sortable date; undated names sort first
        import re
        m = re.search(r"\((\d{2})-(\d{2})-(\d{4})\)", x["name"])
        return (m.group(3), m.group(1), m.group(2)) if m else ("0", "0", "0")
    return sorted(c, key=stamp)[-1] if c else None


def fetch_membership() -> tuple:
    listing = json.loads(_get(f"https://api.github.com/repos/{SOURCE_REPO}/contents"))
    f = pick_file(listing)
    if f is None:
        raise RuntimeError(f"no '{FILE_HINT}' csv in {SOURCE_REPO}: {[x.get('name') for x in listing][:20]}")
    raw = _get(f["download_url"], accept="*/*")
    return raw.decode("utf-8", errors="replace"), f["name"]


def parse_membership(text: str) -> pd.DataFrame:
    """-> DataFrame(date, tickers: list[str]) sorted by date. Raises on an unexpected shape."""
    df = pd.read_csv(io.StringIO(text))
    cols = {c.lower().strip(): c for c in df.columns}
    if "date" not in cols or "tickers" not in cols:
        raise ValueError(f"expected columns date,tickers; got {list(df.columns)}")
    out = pd.DataFrame({"date": pd.to_datetime(df[cols["date"]], errors="coerce"),
                        "tickers": df[cols["tickers"]].astype(str).map(
                            lambda s: sorted({t.strip().upper() for t in s.split(",") if t.strip()}))})
    out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if out.empty or out["tickers"].map(len).median() < 300:
        raise ValueError("membership rows do not look like ~500 tickers per date")
    return out


def members_on(mem: pd.DataFrame, d) -> list:
    """Members in force on date d (the last row on or before d)."""
    r = mem[mem["date"] <= pd.Timestamp(d)]
    return list(r.iloc[-1]["tickers"]) if len(r) else []


def yahoo_symbol(t: str) -> str:
    return t.replace(".", "-")


# ── coverage ────────────────────────────────────────────────────────────────

def bars_by_year(closes: dict) -> pd.DataFrame:
    """ticker x year -> number of daily bars."""
    rows = {}
    for t, s in closes.items():
        s = pd.Series(s).dropna()
        if len(s):
            rows[t] = s.groupby(pd.to_datetime(s.index).year).size()
    return pd.DataFrame(rows).T.fillna(0).astype(int) if rows else pd.DataFrame()


def coverage(mem: pd.DataFrame, bars: pd.DataFrame, start_year: int = START_YEAR,
             end_year: Optional[int] = None) -> pd.DataFrame:
    end_year = end_year or mem["date"].max().year
    out = []
    for y in range(start_year, end_year + 1):
        m = members_on(mem, f"{y}-01-15")
        if not m:
            continue
        need = MIN_BARS if y < end_year else 20            # the current year is partial
        have = [t for t in m if yahoo_symbol(t) in bars.index and y in bars.columns
                and bars.at[yahoo_symbol(t), y] >= need]
        miss = sorted(set(m) - set(have))
        pct = round(len(have) / len(m) * 100, 1)
        out.append({"year": y, "members": len(m), "with_prices": len(have), "coverage_pct": pct,
                    "usable": pct >= COVERAGE_BAR, "missing_sample": ", ".join(miss[:12])})
    return pd.DataFrame(out)


def fetch_closes(tickers: list, start: str) -> dict:
    import yfinance as yf
    out = {}
    syms = sorted({yahoo_symbol(t) for t in tickers})
    for i in range(0, len(syms), BATCH):
        batch = syms[i:i + BATCH]
        try:
            df = yf.download(batch, start=start, auto_adjust=True, progress=False, threads=True)
            cl = df["Close"] if "Close" in df else df
            if isinstance(cl, pd.Series):
                cl = cl.to_frame(batch[0])
            for t in cl.columns:
                s = cl[t].dropna()
                if len(s):
                    out[t] = s
        except Exception as e:
            print(f"[universe_probe] batch {i // BATCH} failed: {type(e).__name__}: {e}")
        print(f"[universe_probe] {min(i + BATCH, len(syms))}/{len(syms)} symbols requested, {len(out)} with data")
    return out


# ── report ──────────────────────────────────────────────────────────────────

def render(cov: pd.DataFrame, mem: pd.DataFrame, source: str, n_ever: int, n_priced: int, asof: str) -> str:
    ok = cov[cov.usable]
    L = [f"# Point-in-time universe probe {VERSION} — {asof}", "",
         f"Source: `{SOURCE_REPO}` / `{source}`. Membership rows: {len(mem)} "
         f"({mem['date'].min().date()} → {mem['date'].max().date()}). "
         f"Tickers ever in the index since {START_YEAR}: {n_ever}; with any Yahoo history: {n_priced} "
         f"({n_priced / max(n_ever, 1) * 100:.0f}%).", "",
         f"A year is USABLE when at least {COVERAGE_BAR:.0f}% of that January's members have "
         f"{MIN_BARS}+ daily bars in the year.", "",
         "| Year | Members | With prices | Coverage % | Usable | Missing (sample) |", "|---|---|---|---|---|---|"]
    for _, r in cov.iterrows():
        L.append(f"| {r.year} | {r.members} | {r.with_prices} | {r.coverage_pct:.1f} | "
                 f"{'yes' if r.usable else '**no**'} | {r.missing_sample} |")
    L += ["", f"**Usable years: {len(ok)} of {len(cov)}**"
          + (f" (first usable year {int(ok.year.min())})." if len(ok) else "."),
          "", "Read: missing names are mostly companies that were acquired, renamed or went bankrupt. "
          "A stock test on the usable years still under-counts failures by the uncovered share, "
          "and says so in its report.", "", f"*universe_probe.py {VERSION}. A probe; nothing reads these files yet.*"]
    return "\n".join(L) + "\n"


def main() -> int:
    text, name = fetch_membership()
    mem = parse_membership(text)
    print(f"[universe_probe] {VERSION}: {name}: {len(mem)} rows, {mem['date'].min().date()} → {mem['date'].max().date()}")
    since = mem[mem["date"] >= pd.Timestamp(f"{START_YEAR - 1}-12-01")]
    ever = sorted({t for row in since["tickers"] for t in row} | set(members_on(mem, f"{START_YEAR}-01-15")))
    closes = fetch_closes(ever, f"{START_YEAR}-01-01")
    if len(closes) < 100:
        print("[universe_probe] DATA FAILURE: almost no prices returned; nothing written (a gap is not a result).")
        return 1
    cov = coverage(mem, bars_by_year(closes))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    asof = date.today().isoformat()
    mem.assign(tickers=mem["tickers"].map(",".join), date=mem["date"].dt.strftime("%Y-%m-%d")).to_csv(
        OUT_DIR / "sp500_membership.csv", index=False)
    (OUT_DIR / "sp500_membership.source.json").write_text(json.dumps(
        {"repo": SOURCE_REPO, "file": name, "fetched": asof, "rows": len(mem)}, indent=2))
    cov.to_csv(OUT_DIR / "coverage_by_year.csv", index=False)
    md = render(cov, mem, name, len(ever), len(closes), asof)
    (LOG_DIR / "probe_report.md").write_text(md)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    f = []
    names = [f"T{i:03d}" for i in range(520)]
    text = "date,tickers\n" + "\n".join(
        f'{d},"{",".join(names[k:k + 500])}"' for d, k in (("2005-01-03", 0), ("2006-06-01", 10), ("2007-03-01", 20)))
    mem = parse_membership(text)
    if len(mem) != 3 or len(mem.iloc[0]["tickers"]) != 500:
        f.append("parse: 3 rows of 500 tickers")
    if "T000" not in members_on(mem, "2006-01-15") or "T000" in members_on(mem, "2007-01-15"):
        f.append("members_on must use the last row on or before the date (no look-ahead)")
    if members_on(mem, "2004-01-01"):
        f.append("no members before the first row")
    try:
        parse_membership("a,b\n1,2\n"); f.append("an unexpected file shape must raise")
    except ValueError:
        pass
    try:
        parse_membership('date,tickers\n2005-01-03,"A,B,C"\n'); f.append("a 3-ticker file must be refused")
    except ValueError:
        pass
    if yahoo_symbol("BRK.B") != "BRK-B":
        f.append("Yahoo symbol mapping")
    idx5, idx6 = pd.bdate_range("2005-01-03", "2005-12-30"), pd.bdate_range("2006-01-02", "2006-12-29")
    closes = {t: pd.Series(1.0, index=idx5.append(idx6)) for t in names[:450]}     # 450 survive both years
    closes.update({t: pd.Series(1.0, index=idx5[:100]) for t in names[450:500]})   # 50 die mid-2005
    cov = coverage(mem, bars_by_year(closes), 2005, 2007).set_index("year")
    if cov.loc[2005, "with_prices"] != 450 or cov.loc[2005, "coverage_pct"] != 90.0 or not cov.loc[2005, "usable"]:
        f.append(f"2005 coverage: 450 of 500 with a full year = 90%: {cov.loc[2005].to_dict()}")
    if cov.loc[2006, "with_prices"] != 450 or cov.loc[2006, "members"] != 500:
        f.append("2006 members are the 2005 row (the June change comes later)")
    few = coverage(mem, bars_by_year({t: closes[t] for t in names[:300]}), 2005, 2007).set_index("year")
    if few.loc[2005, "usable"]:
        f.append("60% coverage must be marked not usable")
    lst = [{"name": "README.md"}, {"name": "S&P 500 Historical Components & Changes(11-01-2025).csv"},
           {"name": "S&P 500 Historical Components & Changes(08-01-2026).csv"}, {"name": "sp500.csv"}]
    if (pick_file(lst) or {}).get("name", "").find("2026") < 0 or pick_file([{"name": "x.csv"}]) is not None:
        f.append("pick_file: newest historical-components csv, or None")
    md = render(cov.reset_index(), mem, "x.csv", 520, 500, "T")
    if "Usable years" not in md or "| 2005 |" not in md:
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
