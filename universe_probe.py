"""
universe_probe.py  (v1.1 — 2026-11-15)
──────────────────────────────────────
PROBE, not a backtest. Question: can a point-in-time S&P 500 stock universe be
built from FREE data, and how much of it still has price history?

WHY
  The swing backtest's stock scope uses today's top holdings, so it only sees
  survivors (fix_status N61). Before any stock setup is tested we need to know
  (a) which stocks were in the index on each past date, and (b) what share of
  them still have prices for the days they were members.

WHAT CHANGED IN v1.1
  1. MEMBERSHIP FILE BUG (v1.0). The source repo holds two files: the original
     (ends 2019-01-11) and "(Updated)" (runs to the present). v1.0 picked the
     original, so its report wrongly said free membership stops in 2019. v1.1
     prefers the Updated file.
  2. FAIRER MEASURE. v1.0 asked for 200+ bars in the calendar year, which
     marks a stock acquired in June as "missing" even with perfect data. v1.1
     counts, per ticker and year, the trading days it was actually a member
     (SPY's calendar) and calls it covered when prices exist for at least
     COVER_DAYS_PCT of those days. A year's coverage is weighted by member-days.
  3. THREE FREE SOURCES, reported cumulatively:
       Yahoo            the ticker as listed in the membership file
       + renames        a short hand-built map of tickers that were renamed
                        and still trade under a new symbol (RENAMES below)
       + Stooq          stooq.com daily CSVs, asked only for what is still missing
     Requiring bars inside the membership window is also the guard against a
     ticker later reused by a different company.
  4. STOOQ IS UNTRUSTED UNTIL PROVEN. A control ticker (AAPL) must come back
     first; an unknown reply format stops the Stooq leg and is reported as a
     data failure, never as "Stooq has nothing". Stooq caps daily requests:
     tickers are asked in a fixed random order and results are cached in
     data/universe/stooq_checked.csv, so a capped run is an unbiased partial
     sample and the next run resumes where it stopped.

OUTPUTS
  data/universe/sp500_membership.csv (+ .source.json)
  data/universe/coverage_by_year.csv      year x source, cumulative
  data/universe/ticker_coverage.csv       ticker x year: need, have per source
  data/universe/stooq_checked.csv         cache of Stooq replies
  logs/universe/probe_report.md
  Nothing downstream reads these files yet.

Run:  python universe_probe.py            (Actions: needs network)
      python universe_probe.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

VERSION = "v1.1"
SOURCE_REPO = "fja05680/sp500"
FILE_HINT = "historical components"
START_YEAR = 2005
COVER_DAYS_PCT = 90.0          # a ticker-year is covered when prices exist for >= 90% of its member-days
COVERAGE_BAR = 80.0            # a year is USABLE at >= 80% of member-days covered (fixed in v1.0)
CLEAN_BAR = 95.0               # ... and CLEAN at >= 95%
BATCH = 80
OUT_DIR = Path("data/universe")
LOG_DIR = Path("logs/universe")

STOOQ_URL = "https://stooq.com/q/d/l/?s={sym}&i=d"
STOOQ_CONTROL = "AAPL"
STOOQ_PAUSE = 0.4              # seconds between requests
STOOQ_MAX_SECONDS = 40 * 60    # stop asking after this long; the cache resumes next run
STOOQ_SEED = 20261115
SOURCES = ("yahoo", "renames", "stooq")

# Old ticker -> the symbol the SAME company trades under today (its Yahoo history
# continues under the new symbol). Hand-built and deliberately short: only plain
# renames. Mergers into a different company are left out. A wrong entry cannot
# invent coverage on its own: the mapped series must still have bars on the days
# the old ticker was a member.
RENAMES = {
    "FB": "META", "ANTM": "ELV", "WLP": "ELV", "ABC": "COR", "PCLN": "BKNG", "HCN": "WELL",
    "KORS": "CPRI", "WYN": "TNL", "TMK": "GL", "BBT": "TFC", "HRS": "LHX", "SYMC": "GEN",
    "NLOK": "GEN", "UTX": "RTX", "LUK": "JEF", "COH": "TPR", "HCP": "DOC", "PEAK": "DOC",
    "JEC": "J", "CTL": "LUMN", "KFT": "MDLZ", "CBG": "CBRE", "LTD": "BBWI", "LB": "BBWI",
    "DLPH": "APTV", "RE": "EG", "FLT": "CPAY", "PKI": "RVTY", "WLTW": "WTW", "ADS": "BFH",
    "DISCA": "WBD", "COG": "CTRA", "HFC": "DINO", "MYL": "VTRS", "GPS": "GAP", "BLL": "BALL",
    "FBHS": "FBIN", "CDAY": "DAY", "Q": "IQV", "DPS": "KDP", "JDSU": "VIAV",
}


# ── membership ──────────────────────────────────────────────────────────────

def _get(url: str, accept: str = "application/vnd.github+json", timeout: int = 60) -> bytes:
    h = {"User-Agent": "portfolio-tracker-universe-probe", "Accept": accept}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and "api.github.com" in url:
        h["Authorization"] = f"Bearer {tok}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def pick_file(listing: list) -> Optional[dict]:
    """The historical-components CSV to use: one marked "updated" beats one that is not
    (the unmarked file is the frozen 2019 original); then the newest "(MM-DD-YYYY)" stamp."""
    import re
    c = [x for x in listing if x.get("name", "").lower().endswith(".csv") and FILE_HINT in x["name"].lower()]

    def key(x):
        n = x["name"].lower()
        m = re.search(r"\((\d{2})-(\d{2})-(\d{4})\)", n)
        stamp = (m.group(3), m.group(1), m.group(2)) if m else ("0", "0", "0")
        return (1 if ("updated" in n or m) else 0, stamp)
    return sorted(c, key=key)[-1] if c else None


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


def intervals(mem: pd.DataFrame) -> dict:
    """ticker -> [(start, end)]: member from `start` up to but NOT including `end`
    (the first row that no longer lists it). end = None means still a member at the last row."""
    out, open_ = {}, {}
    for d, row in zip(mem["date"], mem["tickers"]):
        now = set(row)
        for t in [t for t in open_ if t not in now]:
            out.setdefault(t, []).append((open_.pop(t), d))
        for t in now:
            open_.setdefault(t, d)
    for t, s in open_.items():
        out.setdefault(t, []).append((s, None))
    return out


def yahoo_symbol(t: str) -> str:
    return t.replace(".", "-")


def stooq_symbol(t: str) -> str:
    return t.replace(".", "-").lower() + ".us"


# ── coverage ────────────────────────────────────────────────────────────────

def need_days(iv: dict, cal: pd.DatetimeIndex, start_year: int, last_day: pd.Timestamp) -> dict:
    """(ticker, year) -> the calendar's trading days on which the ticker was a member."""
    out = {}
    cal = cal[(cal >= pd.Timestamp(f"{start_year}-01-01")) & (cal <= last_day)]
    for t, spans in iv.items():
        for s, e in spans:
            days = cal[(cal >= s) & (cal < e)] if e is not None else cal[cal >= s]
            for y in sorted(set(days.year)):
                d = days[days.year == y]
                k = (t, int(y))
                out[k] = out[k].append(d) if k in out else d
    return out


def have_days(series, days: pd.DatetimeIndex) -> int:
    if series is None or len(series) == 0:
        return 0
    return int(pd.DatetimeIndex(pd.to_datetime(series.index)).normalize().isin(days).sum())


def ticker_table(need: dict, by_source: dict) -> pd.DataFrame:
    """One row per (ticker, year): need, and bars held on those days per source."""
    rows = []
    for (t, y), days in sorted(need.items()):
        r = {"ticker": t, "year": y, "need": len(days)}
        for s in SOURCES:
            r[s] = have_days((by_source.get(s) or {}).get(t), days)
        rows.append(r)
    return pd.DataFrame(rows, columns=["ticker", "year", "need", *SOURCES])


def coverage(tt: pd.DataFrame, stooq_complete: bool = True) -> pd.DataFrame:
    """Per year, cumulative across sources, weighted by member-days."""
    out = []
    if tt.empty:
        return pd.DataFrame()
    ok = lambda col: tt[col] >= tt["need"] * COVER_DAYS_PCT / 100.0
    c1 = ok("yahoo")
    c2 = c1 | ok("renames")
    c3 = c2 | ok("stooq")
    for y, g in tt.groupby("year"):
        tot = g["need"].sum()
        pct = lambda m: round(float(g.loc[m.loc[g.index], "need"].sum()) / tot * 100, 1) if tot else 0.0
        best = pct(c3)
        miss = g.loc[~c3.loc[g.index]].sort_values("need", ascending=False)["ticker"].tolist()
        out.append({"year": int(y), "members": int(len(g)), "yahoo_pct": pct(c1), "plus_renames_pct": pct(c2),
                    "plus_stooq_pct": best, "usable": best >= COVERAGE_BAR, "clean": best >= CLEAN_BAR,
                    "stooq_complete": bool(stooq_complete), "still_missing": len(miss),
                    "missing_sample": ", ".join(miss[:10])})
    return pd.DataFrame(out)


# ── Yahoo ───────────────────────────────────────────────────────────────────

def fetch_yahoo(symbols: list, start: str) -> dict:
    import yfinance as yf
    out = {}
    syms = sorted(set(symbols))
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
            print(f"[universe_probe] yahoo batch {i // BATCH} failed: {type(e).__name__}: {e}")
        print(f"[universe_probe] yahoo {min(i + BATCH, len(syms))}/{len(syms)} requested, {len(out)} with data")
    return out


# ── Stooq ───────────────────────────────────────────────────────────────────

def parse_stooq(body: str) -> tuple:
    """-> (status, Series or None). status: ok | no_data | limit | unknown."""
    b = (body or "").strip()
    low = b[:200].lower()
    if "exceeded the daily hits limit" in low or "daily hits limit" in low:
        return "limit", None
    if not b or low.startswith("no data") or low.startswith("brak danych"):
        return "no_data", None
    head = b.splitlines()[0].lower().replace(" ", "")
    if not head.startswith("date,") or "close" not in head:
        return "unknown", None
    try:
        df = pd.read_csv(io.StringIO(b))
        df.columns = [c.strip().lower() for c in df.columns]
        s = pd.Series(pd.to_numeric(df["close"], errors="coerce").values,
                      index=pd.to_datetime(df["date"], errors="coerce")).dropna()
        s = s[s.index.notna()].sort_index()
        return ("ok", s) if len(s) else ("no_data", None)
    except Exception:
        return "unknown", None


def _stooq_http(sym: str) -> str:
    return _get(STOOQ_URL.format(sym=sym), accept="text/csv,*/*", timeout=30).decode("utf-8", errors="replace")


def load_cache(path: Path) -> dict:
    """ticker -> status for replies that are final (ok or no_data)."""
    if not path.exists():
        return {}
    try:
        c = pd.read_csv(path)
        return {r.ticker: r.status for r in c.itertuples() if r.status in ("ok", "no_data")}
    except Exception:
        return {}


def stooq_leg(missing: list, cache: dict, http: Callable = _stooq_http, pause: float = STOOQ_PAUSE,
              max_seconds: float = STOOQ_MAX_SECONDS, clock: Callable = time.monotonic,
              sleep: Callable = time.sleep) -> dict:
    """Ask Stooq for each still-missing ticker, in a fixed random order.
    -> {series, rows (ticker, status, first, last, bars), state, note, asked, skipped_cached}
    state: complete | capped (daily limit or time budget) | failed (control ticker or reply format)."""
    out = {"series": {}, "rows": [], "state": "complete", "note": "", "asked": 0, "skipped_cached": 0}
    try:
        st, s = parse_stooq(http(stooq_symbol(STOOQ_CONTROL)))
    except Exception as e:
        out.update(state="failed", note=f"control request failed: {type(e).__name__}: {str(e)[:120]}")
        return out
    if st == "limit":
        out.update(state="capped", note="daily request limit already reached at the control request")
        return out
    if st != "ok" or len(s) < 1000:
        out.update(state="failed", note=f"control ticker {STOOQ_CONTROL} did not return a price history "
                                        f"(reply read as '{st}'); Stooq's format or access has changed")
        return out
    order = sorted(set(missing))
    random.Random(STOOQ_SEED).shuffle(order)
    t0, unknown = clock(), 0
    for t in order:
        if cache.get(t) == "no_data":           # final answer from an earlier run
            out["rows"].append({"ticker": t, "status": "no_data", "first": "", "last": "", "bars": 0})
            out["skipped_cached"] += 1
            continue
        if clock() - t0 > max_seconds:
            out.update(state="capped", note=f"time budget of {int(max_seconds // 60)} min reached")
            break
        try:
            st, s = parse_stooq(http(stooq_symbol(t)))
        except Exception as e:
            st, s = "error", None
            print(f"[universe_probe] stooq {t}: {type(e).__name__}: {str(e)[:80]}")
        out["asked"] += 1
        if st == "limit":
            out.update(state="capped", note="Stooq's daily request limit reached")
            break
        if st in ("unknown", "error"):
            unknown += 1
            if unknown >= 10 and unknown > out["asked"] * 0.5:
                out.update(state="failed", note="most replies were unreadable; stopped")
                break
            continue                             # not cached: asked again next run
        if st == "ok":
            out["series"][t] = s
            out["rows"].append({"ticker": t, "status": "ok", "first": s.index[0].date().isoformat(),
                                "last": s.index[-1].date().isoformat(), "bars": int(len(s))})
        else:
            out["rows"].append({"ticker": t, "status": "no_data", "first": "", "last": "", "bars": 0})
        if out["asked"] % 50 == 0:
            print(f"[universe_probe] stooq {out['asked']} asked, {len(out['series'])} with history")
        sleep(pause)
    return out


# ── report ──────────────────────────────────────────────────────────────────

def render(cov: pd.DataFrame, mem: pd.DataFrame, source: str, counts: dict, stooq: dict, asof: str) -> str:
    n_use, n_clean = int(cov["usable"].sum()), int(cov["clean"].sum())
    L = [f"# Point-in-time universe probe {VERSION} — {asof}", "",
         f"Membership: `{SOURCE_REPO}` / `{source}`, {len(mem)} rows, "
         f"{mem['date'].min().date()} → {mem['date'].max().date()}.", "",
         f"Tickers in the index at any time since {START_YEAR}: **{counts['ever']}**. "
         f"Yahoo has history for {counts['yahoo']}; {counts['renames']} more resolve through the rename map; "
         f"Stooq was asked for {stooq['asked']} of the {counts['to_stooq']} still missing "
         f"({counts['stooq_ok']} with history, {stooq['skipped_cached']} already known empty).", ""]
    if stooq["state"] == "failed":
        L += [f"> **Stooq leg FAILED — a data failure, not a result:** {stooq['note']}. "
              f"The Stooq column below equals the column before it.", ""]
    elif stooq["state"] == "capped":
        L += [f"> **Stooq leg INCOMPLETE:** {stooq['note']}. {counts['stooq_left']} tickers not yet asked. "
              f"Tickers are asked in a fixed random order, so the hit rate so far "
              f"({counts['stooq_hit_pct']:.0f}% of those asked) is a fair sample. "
              f"Run the probe again tomorrow; it resumes from the cache.", ""]
    L += [f"Measure: for each ticker and year, the trading days it was an index member. It is covered when "
          f"prices exist for at least {COVER_DAYS_PCT:.0f}% of them. A year's figure is the covered share of "
          f"member-days. USABLE at {COVERAGE_BAR:.0f}%, CLEAN at {CLEAN_BAR:.0f}%. Columns are cumulative.", "",
          "| Year | Tickers | Yahoo % | + renames % | + Stooq % | Verdict | Still missing | Sample |",
          "|---|---|---|---|---|---|---|---|"]
    for r in cov.itertuples():
        v = "CLEAN" if r.clean else ("usable" if r.usable else "**no**")
        L.append(f"| {r.year} | {r.members} | {r.yahoo_pct:.1f} | {r.plus_renames_pct:.1f} | "
                 f"{r.plus_stooq_pct:.1f} | {v} | {r.still_missing} | {r.missing_sample} |")
    L += ["", f"**Usable years: {n_use} of {len(cov)}; clean years: {n_clean}.**", "",
          "Read: a stock test may use the usable years, and must state the uncovered share as the amount by "
          "which it still under-counts failures. A year that is not usable is not tested.", "",
          f"Rename map ({len(RENAMES)} entries, hand-built): "
          + ", ".join(f"{a}→{b}" for a, b in sorted(RENAMES.items())) + ".", "",
          f"*universe_probe.py {VERSION}. A probe; nothing reads these files yet.*"]
    return "\n".join(L) + "\n"


def main() -> int:
    text, name = fetch_membership()
    mem = parse_membership(text)
    print(f"[universe_probe] {VERSION}: {name}: {len(mem)} rows, {mem['date'].min().date()} → {mem['date'].max().date()}")
    iv_all = intervals(mem)
    first = pd.Timestamp(f"{START_YEAR}-01-01")
    iv = {t: [(max(s, first), e) for s, e in sp if e is None or e > first] for t, sp in iv_all.items()}
    iv = {t: sp for t, sp in iv.items() if sp}
    ever = sorted(iv)
    start = f"{START_YEAR}-01-01"

    ycl = fetch_yahoo([yahoo_symbol(t) for t in ever] + ["SPY"], start)
    if len(ycl) < 100 or "SPY" not in ycl:
        print("[universe_probe] DATA FAILURE: almost no Yahoo prices or no SPY calendar; nothing written "
              "(a gap is not a result).")
        return 1
    cal = pd.DatetimeIndex(pd.to_datetime(ycl["SPY"].index)).normalize()
    need = need_days(iv, cal, START_YEAR, cal[-1])
    yahoo = {t: ycl[yahoo_symbol(t)] for t in ever if yahoo_symbol(t) in ycl}

    # renames: only for tickers Yahoo does not carry under their own symbol
    want = {t: RENAMES[t] for t in ever if t not in yahoo and t in RENAMES}
    rcl = fetch_yahoo(sorted(set(want.values()) - set(ycl)), start) if want else {}
    rcl = {**ycl, **rcl}
    renames = {t: rcl[n] for t, n in want.items() if n in rcl}

    tt0 = ticker_table(need, {"yahoo": yahoo, "renames": renames, "stooq": {}})
    okcol = lambda c: tt0[c] >= tt0["need"] * COVER_DAYS_PCT / 100.0
    short = tt0.loc[~(okcol("yahoo") | okcol("renames")), "ticker"]
    to_stooq = sorted(set(short))                      # any ticker with at least one uncovered year

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = OUT_DIR / "stooq_checked.csv"
    cache = load_cache(cache_path)
    sq = stooq_leg(to_stooq, cache)
    print(f"[universe_probe] stooq leg: {sq['state']} — {sq['note'] or 'all asked'}; "
          f"{sq['asked']} asked, {len(sq['series'])} with history")
    if sq["rows"]:
        old = pd.read_csv(cache_path) if cache_path.exists() else pd.DataFrame()
        new = pd.DataFrame(sq["rows"])
        pd.concat([old[~old["ticker"].isin(new["ticker"])] if len(old) else old, new]).sort_values("ticker").to_csv(
            cache_path, index=False)

    tt = ticker_table(need, {"yahoo": yahoo, "renames": renames, "stooq": sq["series"]})
    cov = coverage(tt, stooq_complete=sq["state"] == "complete")
    asof = date.today().isoformat()
    mem.assign(tickers=mem["tickers"].map(",".join), date=mem["date"].dt.strftime("%Y-%m-%d")).to_csv(
        OUT_DIR / "sp500_membership.csv", index=False)
    (OUT_DIR / "sp500_membership.source.json").write_text(json.dumps(
        {"repo": SOURCE_REPO, "file": name, "fetched": asof, "rows": len(mem),
         "last_row": mem["date"].max().date().isoformat()}, indent=2))
    cov.to_csv(OUT_DIR / "coverage_by_year.csv", index=False)
    tt.to_csv(OUT_DIR / "ticker_coverage.csv", index=False)
    answered = sq["asked"] + sq["skipped_cached"]
    counts = {"ever": len(ever), "yahoo": len(yahoo), "renames": len(renames), "to_stooq": len(to_stooq),
              "stooq_ok": len(sq["series"]), "stooq_left": max(len(to_stooq) - answered, 0),
              "stooq_hit_pct": (len(sq["series"]) / sq["asked"] * 100) if sq["asked"] else 0.0}
    md = render(cov, mem, name, counts, sq, asof)
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
    try:
        parse_membership("a,b\n1,2\n"); f.append("an unexpected file shape must raise")
    except ValueError:
        pass
    try:
        parse_membership('date,tickers\n2005-01-03,"A,B,C"\n'); f.append("a 3-ticker file must be refused")
    except ValueError:
        pass
    if yahoo_symbol("BRK.B") != "BRK-B" or stooq_symbol("BRK.B") != "brk-b.us":
        f.append("symbol mapping")

    # file choice: the v1.0 bug was picking the frozen original over "(Updated)"
    real = [{"name": "sp500.csv"}, {"name": "S&P 500 Historical Components & Changes (Updated).csv"},
            {"name": "S&P 500 Historical Components & Changes.csv"}]
    for lst in (real, real[::-1]):
        if "Updated" not in (pick_file(lst) or {}).get("name", ""):
            f.append("pick_file must prefer the Updated file whatever the listing order")
    lst = [{"name": "S&P 500 Historical Components & Changes(11-01-2025).csv"},
           {"name": "S&P 500 Historical Components & Changes(08-01-2026).csv"},
           {"name": "S&P 500 Historical Components & Changes.csv"}]
    if "2026" not in (pick_file(lst) or {}).get("name", "") or pick_file([{"name": "x.csv"}]) is not None:
        f.append("pick_file: newest dated csv beats the undated one; None when nothing matches")

    # intervals: T000 leaves at the 2006-06-01 row (end exclusive); T510 joins then and stays
    iv = intervals(mem)
    if iv["T000"] != [(pd.Timestamp("2005-01-03"), pd.Timestamp("2006-06-01"))] or \
            iv["T509"] != [(pd.Timestamp("2006-06-01"), None)]:
        f.append(f"intervals: {iv['T000']} / {iv['T509']}")
    m2 = parse_membership("date,tickers\n" + "\n".join(
        f'{d},"{",".join(names[:400] + x)}"' for d, x in (("2005-01-03", ["ZZ"]), ("2005-06-01", []), ("2006-01-03", ["ZZ"]))))
    if len(intervals(m2)["ZZ"]) != 2:
        f.append("a ticker that leaves and returns must get two intervals")

    cal = pd.bdate_range("2005-01-03", "2007-12-31")
    need = need_days(iv, cal, 2005, cal[-1])
    n05, n06 = len(pd.bdate_range("2005-01-03", "2005-12-30")), len(pd.bdate_range("2006-01-02", "2006-05-31"))
    if len(need[("T000", 2005)]) != n05 or len(need[("T000", 2006)]) != n06 or ("T000", 2007) in need:
        f.append("need_days: member-days only, the exit date excluded")
    if ("T509", 2005) in need or need[("T509", 2006)][0] != pd.Timestamp("2006-06-01"):
        f.append("need_days: nothing before the join date")

    full = pd.Series(1.0, index=cal)
    # T000 acquired 2006-05-31 with complete prices: covered in BOTH years (v1.0 called 2006 missing)
    yahoo = {t: full for t in names[10:460]}
    yahoo["T000"] = full[:"2006-05-31"]
    # T001: bars only AFTER it left the index (a reused ticker) -> not covered
    yahoo["T001"] = full["2006-07-01":]
    # T002: 80% of its 2005 days -> below the 90% rule
    yahoo["T002"] = full[:"2006-05-31"].iloc[::5].index.to_series().pipe(lambda s: full.drop(s.index)[:"2006-05-31"])
    renames = {"T003": full}
    stooq = {"T004": full, "T000": full}
    tt = ticker_table(need, {"yahoo": yahoo, "renames": renames, "stooq": stooq})
    row = lambda t, y: tt[(tt.ticker == t) & (tt.year == y)].iloc[0]
    if row("T000", 2006)["yahoo"] != n06 or row("T000", 2006)["need"] != n06:
        f.append("a stock acquired mid-year with full prices must show have == need")
    if row("T001", 2005)["yahoo"] != 0:
        f.append("bars outside the membership window must not count (ticker reuse)")
    if not (0.75 * n05 < row("T002", 2005)["yahoo"] < 0.85 * n05):
        f.append(f"T002 fixture should hold ~80% of days: {row('T002', 2005)['yahoo']} of {n05}")
    cov = coverage(tt).set_index("year")
    g05 = tt[tt.year == 2005]
    tot = g05["need"].sum()
    exp_y = round((450 + 1) * n05 / tot * 100, 1)             # T010..T459 and T000
    exp_r = round((450 + 2) * n05 / tot * 100, 1)             # + T003
    exp_s = round((450 + 3) * n05 / tot * 100, 1)             # + T004 (T000 already counted once)
    got = (cov.loc[2005, "yahoo_pct"], cov.loc[2005, "plus_renames_pct"], cov.loc[2005, "plus_stooq_pct"])
    if got != (exp_y, exp_r, exp_s):
        f.append(f"2005 cumulative coverage {got} != {(exp_y, exp_r, exp_s)}")
    if not cov.loc[2005, "usable"] or cov.loc[2005, "clean"]:
        f.append("90.6% must be usable and not clean")
    thin = coverage(ticker_table(need, {"yahoo": {t: full for t in names[:300]}, "renames": {}, "stooq": {}}))
    if thin.set_index("year").loc[2005, "usable"]:
        f.append("60% coverage must be marked not usable")
    if cov.loc[2005, "still_missing"] != 500 - 453 or "T001" not in tt[tt.yahoo == 0].ticker.values:
        f.append(f"still_missing count: {cov.loc[2005, 'still_missing']}")

    # Stooq replies
    csv_ok = "Date,Open,High,Low,Close,Volume\n" + "\n".join(
        f"{d.date()},1,1,1,{i + 1},100" for i, d in enumerate(pd.bdate_range("2000-01-03", periods=1500)))
    st, s = parse_stooq(csv_ok)
    if st != "ok" or len(s) != 1500 or s.iloc[-1] != 1500:
        f.append("parse_stooq: a price file")
    for body, exp in (("No data", "no_data"), ("", "no_data"), ("Exceeded the daily hits limit", "limit"),
                      ("<html><body>Get your apikey</body></html>", "unknown"), ("Date,Close\n", "no_data")):
        if parse_stooq(body)[0] != exp:
            f.append(f"parse_stooq({body[:20]!r}) must be {exp}, got {parse_stooq(body)[0]}")

    clk = {"t": 0.0}
    tick = lambda: clk.__setitem__("t", clk["t"] + 1.0) or clk["t"]
    nosleep = lambda x: None
    have = {"aapl.us", "t004.us", "t007.us"}
    calls = []

    def http(sym):
        calls.append(sym)
        return csv_ok if sym in have else "No data"
    miss = [f"T{i:03d}" for i in range(20)]
    r = stooq_leg(miss, {}, http=http, sleep=nosleep, clock=lambda: 0.0)
    if r["state"] != "complete" or sorted(r["series"]) != ["T004", "T007"] or r["asked"] != 20 or len(r["rows"]) != 20:
        f.append(f"stooq_leg complete run: {r['state']} {sorted(r['series'])} asked {r['asked']}")
    order1 = calls[1:]
    calls.clear()
    stooq_leg(miss, {}, http=http, sleep=nosleep, clock=lambda: 0.0)
    if calls[1:] != order1 or order1 == [stooq_symbol(t) for t in miss]:
        f.append("stooq order must be random but the same on every run")
    # cache: known-empty tickers are not asked again; found ones are re-asked (their bars are needed)
    calls.clear()
    r2 = stooq_leg(miss, {"T000": "no_data", "T004": "ok"}, http=http, sleep=nosleep, clock=lambda: 0.0)
    if "t000.us" in calls or "t004.us" not in calls or r2["skipped_cached"] != 1 or r2["asked"] != 19:
        f.append("cache: skip known-empty, re-ask found")
    # control fails -> a data failure, nothing asked
    r3 = stooq_leg(miss, {}, http=lambda s_: "<html>apikey</html>", sleep=nosleep, clock=lambda: 0.0)
    if r3["state"] != "failed" or r3["asked"] != 0 or r3["series"]:
        f.append("a control ticker that does not return prices must fail the leg")
    r3b = stooq_leg(miss, {}, http=lambda s_: (_ for _ in ()).throw(OSError("blocked")), sleep=nosleep, clock=lambda: 0.0)
    if r3b["state"] != "failed":
        f.append("a network error on the control must fail the leg")
    # daily limit mid-run -> capped, what was found is kept, the capped ticker is not cached as empty
    n = {"k": 0}

    def http_cap(sym):
        n["k"] += 1
        return "Exceeded the daily hits limit" if n["k"] > 6 else (csv_ok if sym in have else "No data")
    r4 = stooq_leg(miss, {}, http=http_cap, sleep=nosleep, clock=lambda: 0.0)
    if r4["state"] != "capped" or len(r4["rows"]) != 5 or r4["asked"] != 6:
        f.append(f"daily limit: capped with 5 answered rows, got {r4['state']} rows {len(r4['rows'])} asked {r4['asked']}")
    # time budget
    r5 = stooq_leg(miss, {}, http=http, sleep=nosleep, clock=tick, max_seconds=5)
    if r5["state"] != "capped" or r5["asked"] >= 20:
        f.append("time budget must stop the leg")
    # unreadable replies after a good control -> failed, and never cached as empty
    r6 = stooq_leg(miss, {}, http=lambda s_: csv_ok if s_ == "aapl.us" else "<html>", sleep=nosleep, clock=lambda: 0.0)
    if r6["state"] != "failed" or r6["rows"]:
        f.append("unreadable replies must fail the leg and cache nothing")

    counts = {"ever": 520, "yahoo": 451, "renames": 1, "to_stooq": 60, "stooq_ok": 2, "stooq_left": 40,
              "stooq_hit_pct": 10.0}
    md = render(cov.reset_index(), mem, "x.csv", counts, r4, "T")
    if "INCOMPLETE" not in md or "| 2005 |" not in md or "usable" not in md:
        f.append("report: capped leg")
    if "FAILED" not in render(cov.reset_index(), mem, "x.csv", counts, r3, "T"):
        f.append("report: failed leg")
    if any(k == v for k, v in RENAMES.items()) or any("." in v for v in RENAMES.values()):
        f.append("rename map sanity")
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
