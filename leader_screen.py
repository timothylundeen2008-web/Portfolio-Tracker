"""
leader_screen.py  (v1.4 — 2026-11-16)
─────────────────────────────────────
SWING BOOK ONLY. Each evening: rank the S&P 500 and list the 25 strongest
stocks that are in a confirmed uptrend, with the setup each is closest to.
It is a WATCHLIST. It places nothing in the journal and creates no order.

WHY
  The swing desk's stock cards come from each sector's ten largest holdings.
  That is a list of the biggest stocks, not the strongest. This module finds
  the leaders across the whole index (swing_build_plan_2026-11-14.md §2).

RULES — fixed 2026-11-14 in the build plan, before any test. Do not tune here.
  Universe     current S&P 500 members (State Street's daily SPY holdings file;
               fallback: the last row of data/universe/sp500_membership.csv)
  Liquidity    close > $10 and 50-day average dollar volume > $25M
  Uptrend      all five must hold:
                 1 close above its 50-, 150- and 200-day averages
                 2 50-day above 150-day above 200-day
                 3 200-day average higher than 21 sessions ago
                 4 close within 25% of its 52-week closing high
                 5 close at least 30% above its 52-week closing low
  Strength     percentile rank, across the liquid universe, of the average of
               the stock's 3-, 6- and 12-month return ranks. Leaders: 80+.
  Output       the top 25 by strength

  Shown, NOT filters (untested): tightness (10-day range / 50-day range),
  the sector's rotation quadrant from Money Flow, the next earnings date.

THE PICK COLUMN
  Each leader is passed through swing_desk.evaluate() — the same function the
  nightly swing brief and the backtest use — so a setup shown here is the
  setup that code would produce. A setup marked LIVE is one the swing rules
  already trade (M0). Anything else is WATCH ONLY: M1/M2/EP are not proven on
  stocks (fix_status N61; universe_probe_results_2026-11-16.md).
  When no setup fires, the nearest pivot (highest close of the prior 20
  sessions) and the distance to it are shown.

EVIDENCE
  This filter has NOT been backtested. Every night's list is appended to
  data/leaders/history.csv with the close, so its forward returns against SPY
  can be scored without hindsight. functions here are pure so the stock
  backtest can import the identical filter.

DATA RULES
  A feed that stops short of the expected session, or prices fewer than 90%
  of the universe, is a DATA FAILURE: nothing is written and the previous
  list stays, dated. A gap is never shown as "no leaders".

v1.1 (after the first real run, f14cda5, 2026-11-16 3:53 PM ET)
  1. INTRADAY BAR. That run was started before the close, so Yahoo's last bar
     was a part-day bar and the list was stamped with a session that had not
     finished. Bars after the expected session are now dropped before anything
     is computed (the same rule engine_shadow uses, N66). A run before
     4:30 PM ET therefore reports the PREVIOUS session.
  2. SECTORS. State Street's holdings file has no sector column, so every
     sector and rotation reading was blank. Sectors now come from
     data/universe/sp500_sectors.csv (GICS sectors from the public
     fja05680/sp500 list), refreshed on each run when the source is reachable.
  3. EARNINGS. Yahoo returns the LAST report date for some stocks. A date in
     the past is no longer shown as if it were the next one.

v1.2 (Matt, 2026-11-16: include the Nasdaq names)
  The Nasdaq-100 members that are NOT in the S&P 500 (about 15, mostly foreign
  companies listed in the US) join the ranking. They are marked † and
  "outside the tested universe": the free record of past index membership
  covers the S&P 500 only, so these can be watched and logged forward but
  cannot be part of the historical stock test. Source: the constituents table
  on Wikipedia's Nasdaq-100 page; a good copy is saved to
  data/universe/ndx_members.csv and used when the page cannot be read. If
  neither exists the screen runs on the S&P 500 alone and says so.
  The list is also read by the nightly swing brief (swing_agent), which scans
  each leader with the desk's own rules: see load_latest().

v1.3 (after the first v1.2 run, 2026-11-16 7:14 PM ET)
  The Wikipedia page was reached (10 tables) but none matched: v1.2 looked for
  a header cell named Ticker/Symbol in the first row. v1.3 no longer depends
  on the header. It takes the table column that holds 90-110 distinct
  ticker-shaped values of which at least 60 are S&P 500 members (the two
  indexes share about 85 names), and it prints every table's size and first
  row when nothing matches, so a miss can be diagnosed from the log.
  (The workflow also failed to commit that run: see leader_screen.yml.)

v1.4 (after the v1.3 run, e5435f4)
  v1.3's printout showed why nothing matched: the Nasdaq-100 article no longer
  carries the members table (its ten tables are the infobox, records, yearly
  returns, milestones and navigation boxes). The table lives in a separate
  article, "List of NASDAQ-100 companies" (one table: Ticker, Company,
  ICB Industry, ICB Subsector). v1.4 reads that page first and the old one
  second. The reader itself is unchanged.

Run:  python leader_screen.py            (Actions: needs network)
      python leader_screen.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

VERSION = "v1.4"
MIN_PRICE = 10.0
MIN_DOLLAR_VOL = 25_000_000.0
NEAR_HIGH_PCT = 25.0           # within 25% of the 52-week closing high
ABOVE_LOW_PCT = 30.0           # at least 30% above the 52-week closing low
MA_RISING_SESSIONS = 21
RS_WINDOWS = (63, 126, 252)    # 3, 6, 12 months
RS_MIN = 80.0
TOP_N = 25
MIN_BARS = 253
TIGHT_FLAG = 0.40              # display flag only — judgment, untested
PIVOT_LOOKBACK = 20
NEAR_PIVOT_PCT = 3.0
BASE_MAX_RANGE_PCT = 15.0      # same cap swing_desk.detect_breakout uses for a base
MIN_COVERAGE = 0.90
BATCH = 100
OUT_DIR = Path("data/leaders")
LOG_DIR = Path("logs/leaders")
MEMBERSHIP_CSV = Path("data/universe/sp500_membership.csv")
SECTORS_CSV = Path("data/universe/sp500_sectors.csv")
SECTORS_URL = "https://raw.githubusercontent.com/fja05680/sp500/master/sp500.csv"
NDX_CSV = Path("data/universe/ndx_members.csv")
NDX_URLS = ("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies",
            "https://en.wikipedia.org/wiki/Nasdaq-100")
NDX_RANGE = (90, 110)          # a parsed Nasdaq-100 list outside this size is refused
NDX_MIN_SP500_OVERLAP = 60     # the two indexes share about 85 names; a column sharing fewer is not it
SP500, NDX = "S&P 500", "Nasdaq-100"

SECTOR_ETF = {"information technology": "XLK", "technology": "XLK", "financials": "XLF", "health care": "XLV",
              "consumer discretionary": "XLY", "communication services": "XLC", "industrials": "XLI",
              "consumer staples": "XLP", "energy": "XLE", "utilities": "XLU", "real estate": "XLRE",
              "materials": "XLB", "telecommunications": "XLC", "basic materials": "XLB"}
HIST_COLS = ["date", "rank", "ticker", "close", "rs", "tightness", "sector", "quadrant", "setup", "live",
             "trigger", "stop", "spy_close", "market_ok", "version", "index"]


# ── universe ────────────────────────────────────────────────────────────────

def parse_spy_holdings(raw: bytes) -> list:
    """[{ticker, name, sector, weight}] from State Street's daily SPY holdings workbook.
    Tickers come back in Yahoo form (BRK.B -> BRK-B). Raises ValueError on an unknown layout."""
    grid = pd.read_excel(io.BytesIO(raw), header=None)
    hdr = None
    for i in range(min(len(grid), 40)):
        cells = [str(c).strip().lower() for c in grid.iloc[i].tolist()]
        if "weight" in cells and "ticker" in cells:
            hdr = i
            break
    if hdr is None:
        raise ValueError("no header row with 'Ticker' and 'Weight' in the first 40 rows")
    df = grid.iloc[hdr + 1:].copy()
    df.columns = [str(c).strip().lower() for c in grid.iloc[hdr].tolist()]
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df = df[(df["weight"] > 0) & df["ticker"].str.match(r"^[A-Z]{1,5}([.\-/][A-Z]{1,2})?$")]
    if len(df) < 400:
        raise ValueError(f"only {len(df)} holdings parsed — not the full S&P 500 basket")
    out = []
    for r in df.sort_values("weight", ascending=False).to_dict("records"):
        sec = str(r.get("sector", "") or "").strip()
        out.append({"ticker": re.sub(r"[./]", "-", r["ticker"]), "name": str(r.get("name", "") or "").strip(),
                    "sector": "" if sec.lower() in ("nan", "-", "unassigned") else sec,
                    "weight": float(r["weight"])})
    return out


def membership_fallback(path: Path = MEMBERSHIP_CSV) -> tuple:
    m = pd.read_csv(path)
    last = m.iloc[-1]
    tk = [t.strip().upper().replace(".", "-") for t in str(last["tickers"]).split(",") if t.strip()]
    if len(tk) < 400:
        raise ValueError("membership file's last row is not ~500 tickers")
    return [{"ticker": t, "name": "", "sector": "", "weight": 0.0} for t in sorted(set(tk))], str(last["date"])


def load_universe(fetch_raw: Optional[Callable] = None) -> tuple:
    """-> (rows, source note). Live holdings first; the committed membership file if that fails."""
    try:
        if fetch_raw is None:
            import macro_flags as mf
            raw = mf._get(mf.SPY_HOLDINGS_URL).content
        else:
            raw = fetch_raw()
        rows = parse_spy_holdings(raw)
        return rows, f"State Street SPY daily holdings ({len(rows)} names)"
    except Exception as e:
        rows, asof = membership_fallback()
        return rows, (f"FALLBACK: committed membership file as of {asof} ({len(rows)} names, no sectors) — "
                      f"live holdings failed: {type(e).__name__}: {str(e)[:90]}")


def parse_sector_list(text: str) -> dict:
    """ticker (Yahoo form) -> GICS sector, from either the source's sp500.csv
    (Symbol, GICS Sector) or our own committed file (ticker, sector). Raises on a bad shape."""
    df = pd.read_csv(io.StringIO(text))
    cols = {c.lower().strip(): c for c in df.columns}
    tk = cols.get("ticker") or cols.get("symbol")
    sc = cols.get("sector") or cols.get("gics sector")
    if not tk or not sc:
        raise ValueError(f"no ticker/sector columns in {list(df.columns)}")
    out = {re.sub(r"[./]", "-", str(t).strip().upper()): str(s).strip()
           for t, s in zip(df[tk], df[sc]) if str(s).strip() and str(s).strip().lower() != "nan"}
    known = {s for s in out.values() if s.lower() in SECTOR_ETF}
    if len(out) < 400 or len(known) < 10:
        raise ValueError(f"sector list looks wrong: {len(out)} tickers, {len(known)} known sectors")
    return out


def load_sectors(fetch_text: Optional[Callable] = None, path: Path = SECTORS_CSV, refresh: bool = True) -> tuple:
    """-> (ticker -> sector, note). Tries the public list first and saves a good copy;
    otherwise the committed file. Never raises: sectors are context, not a filter."""
    if refresh:
        try:
            if fetch_text is None:
                import urllib.request
                req = urllib.request.Request(SECTORS_URL, headers={"User-Agent": "portfolio-tracker-leader-screen"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    text = r.read().decode("utf-8", errors="replace")
            else:
                text = fetch_text()
            sec = parse_sector_list(text)
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(sorted(sec.items()), columns=["ticker", "sector"]).to_csv(path, index=False)
            return sec, f"sectors: public S&P 500 list, refreshed ({len(sec)} names)"
        except Exception as e:
            why = f"{type(e).__name__}: {str(e)[:70]}"
    else:
        why = "refresh off"
    try:
        sec = parse_sector_list(path.read_text())
        return sec, f"sectors: committed file ({len(sec)} names; live refresh failed: {why})"
    except Exception as e:
        return {}, f"sectors UNAVAILABLE ({type(e).__name__}); sector and rotation columns are blank"


def apply_sectors(universe: list, sectors: dict) -> int:
    """Fill a blank sector from the list. Returns how many names have a sector afterwards."""
    for u in universe:
        if not u.get("sector"):
            u["sector"] = sectors.get(u["ticker"], "")
    return sum(1 for u in universe if u.get("sector"))


# ── Nasdaq-100 add-ons ──────────────────────────────────────────────────────

def parse_ndx_html(html: str, sp500: Optional[set] = None) -> list:
    """[{ticker, sector}] from the constituents table of Wikipedia's Nasdaq-100 page.
    Header-independent: the column holding 90-110 distinct ticker-shaped values, of which
    (when `sp500` is given) at least 60 are S&P 500 members. A column under a Ticker/Symbol
    header wins a tie. Raises ValueError, describing every table, when nothing qualifies."""
    from html.parser import HTMLParser

    class T(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tables, self.cur, self.row, self.cell, self.depth = [], None, None, None, 0
            self.kinds, self.header_rows = [], []      # header_rows[i] = indexes of all-<th> rows in table i
            self.cur_hdr = set()

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self.depth += 1
                if self.depth == 1:
                    self.cur, self.cur_hdr = [], set()
            elif self.depth == 1 and tag == "tr":
                self.row, self.kinds = [], []
            elif self.depth == 1 and tag in ("td", "th") and self.row is not None:
                self.cell = []
                self.kinds.append(tag)
            elif tag == "br" and self.cell is not None:
                self.cell.append(" ")

        def handle_endtag(self, tag):
            if tag == "table":
                if self.depth == 1 and self.cur is not None:
                    self.tables.append(self.cur)
                    self.header_rows.append(self.cur_hdr)
                    self.cur = None
                self.depth = max(self.depth - 1, 0)
            elif self.depth == 1 and tag in ("td", "th") and self.cell is not None and self.row is not None:
                self.row.append(" ".join("".join(self.cell).split()))
                self.cell = None
            elif self.depth == 1 and tag == "tr" and self.row is not None:
                if self.row:
                    if self.kinds and all(k == "th" for k in self.kinds):
                        self.cur_hdr.add(len(self.cur))
                    self.cur.append(self.row)
                self.row = None

        def handle_data(self, data):
            if self.cell is not None:
                self.cell.append(data)

    p = T()
    p.feed(html or "")
    tick_re = re.compile(r"^[A-Z]{1,5}([.\-][A-Z]{1,2})?$")
    best = None                                   # (score, table, column)
    for tb, hdr in zip(p.tables, p.header_rows):
        if len(tb) < NDX_RANGE[0]:
            continue
        width = max(len(r) for r in tb)
        for ci in range(width):
            vals = [r[ci].strip().upper() for i, r in enumerate(tb) if len(r) > ci and i not in hdr]
            tick = {re.sub(r"[./]", "-", v) for v in vals if tick_re.match(v)}
            if not (NDX_RANGE[0] <= len(tick) <= NDX_RANGE[1]):
                continue
            overlap = len(tick & sp500) if sp500 else len(tick)
            if sp500 and overlap < NDX_MIN_SP500_OVERLAP:
                continue
            named = any(c.strip().lower() in ("ticker", "symbol", "ticker symbol") for r in tb[:3] for c in r[ci:ci + 1])
            score = (1 if named else 0, overlap)
            if best is None or score > best[0]:
                best = (score, tb, ci, hdr)
    if best is None:
        desc = "; ".join(f"{len(tb)} rows, first {[c[:14] for c in tb[0][:5]]}" for tb in p.tables[:12])
        raise ValueError(f"no table column with {NDX_RANGE[0]}-{NDX_RANGE[1]} tickers"
                         + (f" sharing {NDX_MIN_SP500_OVERLAP}+ with the S&P 500" if sp500 else "")
                         + f" ({len(p.tables)} tables: {desc})")
    _, tb, ti, hdr = best
    si = None
    for hr in tb[:3]:                             # the sector column, if a header names one
        head = [c.lower() for c in hr]
        si = next((i for i, c in enumerate(head) if "sector" in c and "sub" not in c), None)
        if si is None:
            si = next((i for i, c in enumerate(head) if "industry" in c and "sub" not in c), None)
        if si is not None:
            break
    seen, out = set(), []
    for i, r in enumerate(tb):
        if len(r) <= ti or i in hdr:
            continue
        t = r[ti].strip().upper()
        if not tick_re.match(t):
            continue
        t = re.sub(r"[./]", "-", t)
        if t in seen:
            continue
        seen.add(t)
        sec = r[si].strip() if si is not None and len(r) > si else ""
        out.append({"ticker": t, "sector": sec})
    return out


def _http_text(url: str) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": "portfolio-tracker-leader-screen/1.4 (personal research; github actions)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def load_ndx(fetch_html: Optional[Callable] = None, path: Path = NDX_CSV, refresh: bool = True,
             sp500: Optional[set] = None) -> tuple:
    """fetch_html(url) -> page text (tests inject it).
    -> (rows, note). Live pages first (a good parse is saved); then the saved copy; then nothing.
    Never raises: without it the screen runs on the S&P 500 alone and the note says so."""
    why = "refresh off"
    if refresh:
        try:
            get = fetch_html or _http_text
            rows, errs = None, []
            for url in NDX_URLS:                  # the first page that yields a plausible list wins
                try:
                    rows = parse_ndx_html(get(url), sp500)
                    break
                except Exception as e:
                    errs.append(f"{url.rsplit('/', 1)[-1]}: {type(e).__name__}: {str(e)[:700]}")
            if rows is None:
                raise ValueError(" || ".join(errs))
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows, columns=["ticker", "sector"]).assign(fetched=date.today().isoformat()).to_csv(
                path, index=False)
            return rows, f"Nasdaq-100: Wikipedia, read today ({len(rows)} names)"
        except Exception as e:
            why = f"{type(e).__name__}: {str(e)[:70]}"
            print(f"[leader_screen] Nasdaq-100 page not usable: {type(e).__name__}: {str(e)[:1500]}")
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
        rows = [{"ticker": t, "sector": s} for t, s in zip(df["ticker"], df["sector"])]
        if not (NDX_RANGE[0] <= len(rows) <= NDX_RANGE[1]):
            raise ValueError(f"{len(rows)} rows")
        asof = df["fetched"].iloc[0] if "fetched" in df.columns else "unknown date"
        return rows, f"Nasdaq-100: saved copy from {asof} ({len(rows)} names; live read failed: {why})"
    except Exception:
        return [], f"Nasdaq-100 NOT INCLUDED — the list could not be read ({why}); S&P 500 only"


def add_ndx(universe: list, ndx_rows: list) -> int:
    """Tag S&P rows, append Nasdaq-100 members that are not already there. Returns how many were added."""
    have = {u["ticker"] for u in universe}
    for u in universe:
        u.setdefault("index", SP500)
    n = 0
    for r in ndx_rows:
        if r["ticker"] not in have:
            sec = r.get("sector", "")
            universe.append({"ticker": r["ticker"], "name": "", "weight": 0.0, "index": NDX,
                             "sector": sec if sec.lower() in SECTOR_ETF else ""})
            have.add(r["ticker"]); n += 1
    return n


def load_latest(path: Optional[Path] = None) -> Optional[dict]:
    """The last healthy list, for the swing brief. None when there is none or it cannot be read."""
    try:
        j = json.loads((path or OUT_DIR / "latest.json").read_text())
        return j if j.get("ok") and j.get("session") and isinstance(j.get("leaders"), list) else None
    except Exception:
        return None


def cut_to_session(df: Optional[pd.DataFrame], expected: Optional[date]) -> Optional[pd.DataFrame]:
    """Drop bars dated after the expected session: a run before the close gets a part-day bar."""
    if df is None or expected is None or df.empty:
        return df
    return df[pd.DatetimeIndex(df.index).normalize() <= pd.Timestamp(expected)]


# ── per-stock numbers ───────────────────────────────────────────────────────

def metrics(df: Optional[pd.DataFrame]) -> Optional[dict]:
    """Everything the filter needs for one stock, from its own bars up to the last one. None if too short."""
    if df is None or len(df) < MIN_BARS or not {"High", "Low", "Close", "Volume"} <= set(df.columns):
        return None
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    px = float(c.iloc[-1])
    if not np.isfinite(px) or px <= 0:
        return None
    s50, s150, s200 = c.rolling(50).mean(), c.rolling(150).mean(), c.rolling(200).mean()
    hi52, lo52 = float(c.tail(252).max()), float(c.tail(252).min())
    r10 = float(h.tail(10).max() - l.tail(10).min())
    r50 = float(h.tail(50).max() - l.tail(50).min())
    prior = c.iloc[-PIVOT_LOOKBACK - 1:-1]
    m = {"close": px, "dollar_vol": float((c * v).tail(50).mean()),
         "sma50": float(s50.iloc[-1]), "sma150": float(s150.iloc[-1]), "sma200": float(s200.iloc[-1]),
         "sma200_prev": float(s200.iloc[-1 - MA_RISING_SESSIONS]),
         "hi52": hi52, "lo52": lo52,
         "from_high_pct": (px / hi52 - 1) * 100, "above_low_pct": (px / lo52 - 1) * 100,
         "tightness": (r10 / r50) if r50 > 0 else None,
         "pivot": float(prior.max()), "base_range_pct": float((prior.max() / prior.min() - 1) * 100)}
    for n in RS_WINDOWS:
        m[f"ret{n}"] = float(px / c.iloc[-1 - n] - 1) * 100
    return m


def trend_checks(m: dict) -> dict:
    """The five fixed uptrend rules. All must be True."""
    return {
        "above 50/150/200-day": m["close"] > m["sma50"] and m["close"] > m["sma150"] and m["close"] > m["sma200"],
        "50 > 150 > 200": m["sma50"] > m["sma150"] > m["sma200"],
        "200-day rising": m["sma200"] > m["sma200_prev"],
        f"within {NEAR_HIGH_PCT:.0f}% of 52w high": m["close"] >= m["hi52"] * (1 - NEAR_HIGH_PCT / 100),
        f"{ABOVE_LOW_PCT:.0f}%+ above 52w low": m["close"] >= m["lo52"] * (1 + ABOVE_LOW_PCT / 100),
    }


def _pct_rank(s: pd.Series) -> pd.Series:
    """0 = weakest, 100 = strongest; ties share the average rank."""
    n = s.notna().sum()
    if n <= 1:
        return pd.Series(50.0, index=s.index).where(s.notna())
    return (s.rank(method="average") - 1) / (n - 1) * 100


def rank(mets: dict) -> pd.DataFrame:
    """One row per stock with numbers: liquidity, strength rank across the LIQUID universe,
    the five trend checks, and `leader`. Sorted strongest first."""
    rows = []
    for t, m in mets.items():
        if m is None:
            continue
        ch = trend_checks(m)
        rows.append({"ticker": t, **m, "liquid": m["close"] > MIN_PRICE and m["dollar_vol"] > MIN_DOLLAR_VOL,
                     "trend_ok": all(ch.values()), "failed": [k for k, ok in ch.items() if not ok]})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    liq = df["liquid"]
    blend = pd.concat([_pct_rank(df.loc[liq, f"ret{n}"]) for n in RS_WINDOWS], axis=1).mean(axis=1)
    df["rs"] = _pct_rank(blend).reindex(df.index)
    df["leader"] = liq & df["trend_ok"] & (df["rs"] >= RS_MIN)
    return df.sort_values(["rs", "ticker"], ascending=[False, True], na_position="last").reset_index(drop=True)


# ── the pick column ─────────────────────────────────────────────────────────

def setup_status(ticker: str, df: pd.DataFrame, m: dict, *, regime_key: str, bench: Optional[pd.Series],
                 quadrant: Optional[str], market_ok: Optional[bool], earnings_48h: bool,
                 equity: float, risk_pct: float, evaluate: Optional[Callable] = None) -> dict:
    """What the swing desk's own evaluator makes of this stock today, or the nearest pivot."""
    if evaluate is None:
        import swing_desk
        evaluate = swing_desk.evaluate
    out = {"setup": None, "live": False, "trigger": None, "stop": None, "stop_pct": None,
           "confluence": None, "note": ""}
    try:
        r = evaluate(ticker, df, regime_key, bench=bench, sector_quadrant=quadrant, equity=equity,
                     risk_pct=risk_pct, market_ok=market_ok, earnings_within_48h=earnings_48h, is_etf=False)
    except Exception as e:
        out["note"] = f"evaluator error: {type(e).__name__}: {str(e)[:80]}"
        r = {}
    card = r.get("card")
    if card:
        out.update(setup=card["setup"], live=bool(card.get("live")) and market_ok is True,
                   trigger=card["entry"], stop=card["stop"], stop_pct=card["stop_pct"],
                   confluence=card.get("confluence"))
        out["note"] = ("live setup" if out["live"] else
                       "live setup, but the market filter is closed or unknown" if card.get("live") else
                       "watch only — this setup is not proven on stocks")
        return out
    dist = (m["pivot"] / m["close"] - 1) * 100
    based = m["base_range_pct"] <= BASE_MAX_RANGE_PCT
    if r.get("setup"):                      # a setup fired but was refused (confluence, earnings)
        out["setup"] = r["setup"]
        out["note"] = (r.get("avoid_reason") or "refused")[:140]
    elif dist < 0:
        out["note"] = f"closed {-dist:.1f}% above its 20-day pivot {m['pivot']:.2f} with no setup confirmed"
    elif based and dist <= NEAR_PIVOT_PCT:
        out.update(setup="Near pivot", trigger=round(m["pivot"], 2))
        out["note"] = f"{dist:.1f}% below its 20-day pivot; base {m['base_range_pct']:.0f}% wide"
    elif based:
        out.update(setup="Basing", trigger=round(m["pivot"], 2))
        out["note"] = f"{dist:.1f}% below its 20-day pivot; base {m['base_range_pct']:.0f}% wide"
    else:
        out["note"] = f"no base: last 20 sessions span {m['base_range_pct']:.0f}% (over {BASE_MAX_RANGE_PCT:.0f}%)"
    return out


# ── build ───────────────────────────────────────────────────────────────────

def _quadrants(rotation: Optional[dict]) -> dict:
    return {str(s.get("ticker")): s.get("quadrant") for s in ((rotation or {}).get("sectors") or [])}


def build(universe: list, ohlcv: dict, *, spy: Optional[pd.DataFrame], regime_key: str, rotation: Optional[dict],
          expected: Optional[date], source: str, earnings: Optional[Callable] = None,
          equity: float = 10_000.0, risk_pct: float = 1.0, evaluate: Optional[Callable] = None,
          market_ok_fn: Optional[Callable] = None) -> dict:
    """-> the result dict. result['ok'] False means a data failure: write nothing."""
    res = {"version": VERSION, "ok": False, "source": source, "universe_n": len(universe), "regime": regime_key,
           "leaders": [], "problems": []}
    spy = cut_to_session(spy, expected)
    ohlcv = {t: cut_to_session(df, expected) for t, df in ohlcv.items()}
    if spy is None or len(spy) < MIN_BARS:
        res["problems"].append("SPY history missing or short")
        return res
    session = pd.Timestamp(spy.index[-1]).date()
    res["session"] = session.isoformat()
    if expected is not None and session < expected:
        res["problems"].append(f"prices stop at {session}; the {expected} session is not in the feed yet")
        return res
    fresh, stale = {}, []
    for t, df in ohlcv.items():
        if df is None or df.empty:
            continue
        (fresh.__setitem__(t, df) if pd.Timestamp(df.index[-1]).date() == session else stale.append(t))
    want = [u["ticker"] for u in universe]
    priced = [t for t in want if t in fresh]
    res["ndx_extra_n"] = sum(1 for u in universe if u.get("index") == NDX)
    res.update(priced_n=len(priced), stale=sorted(stale)[:20], stale_n=len(stale),
               missing=sorted(set(want) - set(fresh) - set(stale))[:20])
    if len(priced) < MIN_COVERAGE * max(len(want), 1):
        res["problems"].append(f"only {len(priced)} of {len(want)} stocks have a bar for {session} "
                               f"(need {MIN_COVERAGE:.0%})")
        return res

    mets = {t: metrics(fresh[t]) for t in priced}
    table = rank(mets)
    res["too_new_n"] = sum(1 for v in mets.values() if v is None)
    if table.empty:
        res["problems"].append("no stock had enough history to rank")
        return res
    res.update(ranked_n=int(table["rs"].notna().sum()), liquid_n=int(table["liquid"].sum()),
               trend_n=int((table["liquid"] & table["trend_ok"]).sum()), leaders_n=int(table["leader"].sum()))
    if market_ok_fn is None:
        import swing_desk
        market_ok_fn = swing_desk.market_ok
    mkt = market_ok_fn(spy["Close"])
    res["market"] = {"ok": mkt, "spy_close": round(float(spy["Close"].iloc[-1]), 2),
                     "spy_sma200": round(float(spy["Close"].tail(200).mean()), 2)}
    top = table[table["leader"]].head(TOP_N)
    meta = {u["ticker"]: u for u in universe}
    quad = _quadrants(rotation)
    earn = {}
    if earnings is not None and len(top):
        try:
            earn = earnings(top["ticker"].tolist()) or {}
        except Exception as e:
            res["problems"].append(f"earnings lookup failed ({type(e).__name__}); dates not shown")
    res["earnings_known_n"] = sum(1 for v in earn.values() if v["days_away"] >= 0)
    res["sector_known_n"] = sum(1 for t in top["ticker"] if meta.get(t, {}).get("sector"))
    for i, r in enumerate(top.to_dict("records"), 1):
        t = r["ticker"]
        sec = meta.get(t, {}).get("sector", "")
        etf = SECTOR_ETF.get(sec.lower())
        q = quad.get(etf) if etf else None
        e = earn.get(t)
        if e and e["days_away"] < 0:        # Yahoo gave the last report, not the next one
            e = None
        e48 = bool(e and 0 <= e["days_away"] <= 2)
        st = setup_status(t, fresh[t], r, regime_key=regime_key, bench=spy["Close"], quadrant=q, market_ok=mkt,
                          earnings_48h=e48, equity=equity, risk_pct=risk_pct, evaluate=evaluate)
        res["leaders"].append({
            "rank": i, "ticker": t, "name": meta.get(t, {}).get("name", ""), "sector": sec, "sector_etf": etf,
            "index": meta.get(t, {}).get("index", SP500),
            "tested_universe": meta.get(t, {}).get("index", SP500) == SP500,
            "quadrant": q, "close": round(r["close"], 2), "rs": round(r["rs"], 1),
            "ret_3m": round(r["ret63"], 1), "ret_6m": round(r["ret126"], 1), "ret_12m": round(r["ret252"], 1),
            "from_high_pct": round(r["from_high_pct"], 1),
            "tightness": None if r["tightness"] is None else round(r["tightness"], 2),
            "tight": r["tightness"] is not None and r["tightness"] <= TIGHT_FLAG,
            "dollar_vol_m": round(r["dollar_vol"] / 1e6, 0),
            "earnings": e["date"] if e else None, "earnings_days": e["days_away"] if e else None,
            "earnings_48h": e48, **st})
    res["ok"] = True
    return res


# ── report ──────────────────────────────────────────────────────────────────

def render_md(res: dict) -> str:
    if not res.get("ok"):
        return (f"# Swing leaders — DATA FAILURE\n\n{'; '.join(res.get('problems') or ['unknown'])}.\n\n"
                "Nothing was written. The previous list stays in place with its own date. "
                "A data failure is not a signal.\n")
    mk = res["market"]
    state = {True: "OPEN", False: "CLOSED", None: "UNKNOWN"}[mk["ok"]]
    L = [f"# Swing leaders — session {res['session']}", "",
         f"**Market filter {state}:** SPY {mk['spy_close']:.2f} vs its 200-day {mk['spy_sma200']:.2f}. "
         + ("New swing entries are allowed." if mk["ok"] else "No new swing entries; this is a watchlist only."),
         f"Regime `{res['regime']}`. Swing book only; nothing here touches the long-term book.", "",
         f"**Funnel:** {res['universe_n']} in the index → {res['priced_n']} priced → {res['ranked_n']} liquid and "
         f"ranked → {res['trend_n']} in a confirmed uptrend → **{res['leaders_n']} leaders** (strength 80+); "
         f"top {min(TOP_N, res['leaders_n'])} shown.", ""]
    if not res["leaders"]:
        L += ["**No stock passes all the rules today.** That is a real reading (prices were complete), "
              "and usually means the market is weak.", ""]
    else:
        L += ["| # | Stock | Sector (rotation) | Close | Strength | 3m / 6m / 12m % | From high | Tight | Pick | "
              "Trigger | Stop | Earnings |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for x in res["leaders"]:
            pick = (f"**{x['setup']} — LIVE**" if x["live"] else
                    f"{x['setup']} (watch)" if x["setup"] else "—")
            sec = (x["sector"] or "—") + (f" ({x['quadrant']})" if x["quadrant"] else "")
            tight = "—" if x["tightness"] is None else f"{x['tightness']:.2f}" + (" ✓" if x["tight"] else "")
            trig = "—" if x["trigger"] is None else f"{x['trigger']:.2f}"
            stop = "—" if x["stop"] is None else f"{x['stop']:.2f} ({x['stop_pct']:.1f}%)"
            earn = "—" if not x["earnings"] else (f"**{x['earnings']} ⚠ 48h**" if x["earnings_48h"]
                                                  else f"{x['earnings']} ({x['earnings_days']}d)")
            dag = "" if x.get("tested_universe", True) else " †"
            L.append(f"| {x['rank']} | **{x['ticker']}**{dag} | {sec} | {x['close']:.2f} | {x['rs']:.0f} | "
                     f"{x['ret_3m']:+.0f} / {x['ret_6m']:+.0f} / {x['ret_12m']:+.0f} | {x['from_high_pct']:+.1f}% | "
                     f"{tight} | {pick} | {trig} | {stop} | {earn} |")
        L += ["", "**Why each pick reads as it does**", ""]
        L += [f"- **{x['ticker']}**: {x['note']}" for x in res["leaders"]]
    live = [x["ticker"] for x in res["leaders"] if x["live"]]
    L += ["", "**How to read this**",
          "- **LIVE** means the stock shows the one setup the swing rules already trade (M0). "
          "The order ticket still comes from the nightly swing brief, not from this list."
          + (f" Live today: {', '.join(live)}." if live else " None today."),
          "- **(watch)** setups and **Near pivot / Basing** are not proven on stocks. Watch them; do not trade them yet.",
          "- **Strength** is the stock's rank in the index on 3-, 6- and 12-month returns (100 = strongest).",
          f"- **Tight** is the 10-day range over the 50-day range; ✓ at {TIGHT_FLAG:.2f} or less. A display flag, untested.",
          "- **Earnings** dates are Yahoo estimates. Confirm on the company's site before any entry.",
          *(["- **†** a Nasdaq-100 stock that is not in the S&P 500. It is outside the universe the historical "
             "stock test can cover, so its record is forward-only."]
            if any(not x.get("tested_universe", True) for x in res["leaders"]) else []), "",
          "**Data**",
          f"- Universe: {res['source']}.",
          f"- {res.get('ndx_extra_n', 0)} Nasdaq-100 stocks outside the S&P 500 were ranked alongside it.",
          f"- Sector known for {res.get('sector_known_n', 0)} of {len(res['leaders'])} shown; next earnings date "
          f"known for {res.get('earnings_known_n', 0)} (— means Yahoo has not published one).",
          f"- {res['universe_n'] - res['priced_n']} not priced for this session"
          + (f" (stale: {', '.join(res['stale'][:8])})" if res.get("stale") else "")
          + (f" (missing: {', '.join(res['missing'][:8])})" if res.get("missing") else "")
          + f"; {res.get('too_new_n', 0)} with under a year of history."]
    L += [f"- {p}" for p in res.get("problems") or []]
    L += ["", f"*leader_screen.py {VERSION}. This filter has not been backtested; each night's list is logged to "
              "`data/leaders/history.csv` so its forward results can be scored.*"]
    return "\n".join(L) + "\n"


def history_rows(res: dict) -> pd.DataFrame:
    mk = res["market"]
    return pd.DataFrame([{"date": res["session"], "rank": x["rank"], "ticker": x["ticker"], "close": x["close"],
                          "rs": x["rs"], "tightness": x["tightness"], "sector": x["sector"],
                          "quadrant": x["quadrant"], "setup": x["setup"], "live": x["live"],
                          "trigger": x["trigger"], "stop": x["stop"], "spy_close": mk["spy_close"],
                          "market_ok": mk["ok"], "version": VERSION, "index": x.get("index", SP500)}
                         for x in res["leaders"]], columns=HIST_COLS)


def write(res: dict, out_dir: Path = OUT_DIR, log_dir: Path = LOG_DIR) -> bool:
    """Writes only a healthy result. A re-run for the same session replaces that session's rows."""
    if not res.get("ok"):
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(json.dumps(res, indent=1, default=str))
    md = render_md(res)
    (log_dir / f"{res['session']}.md").write_text(md)
    (log_dir / "latest.md").write_text(md)
    hp = out_dir / "history.csv"
    new = history_rows(res)
    if hp.exists():
        old = pd.read_csv(hp, dtype={"date": str})
        if "index" not in old.columns:           # rows written before v1.2 were all S&P 500
            old["index"] = SP500
        new = pd.concat([old[old["date"] != res["session"]], new], ignore_index=True)
    new.sort_values(["date", "rank"]).to_csv(hp, index=False)
    return True


def fetch_all(tickers: list) -> dict:
    import swing_agent
    out = {}
    tk = sorted(set(tickers))
    for i in range(0, len(tk), BATCH):
        out.update(swing_agent._default_fetch(tk[i:i + BATCH], period="2y"))
        print(f"[leader_screen] {min(i + BATCH, len(tk))}/{len(tk)} requested, {len(out)} with data")
    return out


def main() -> int:
    import swing_agent
    import event_calendar as ec
    universe, source = load_universe()
    sectors, sec_note = load_sectors()
    ndx_rows, ndx_note = load_ndx(sp500={u["ticker"] for u in universe})
    n_ndx = add_ndx(universe, ndx_rows)
    n_sec = apply_sectors(universe, sectors)
    source += f"; {sec_note}; {ndx_note}, {n_ndx} not in the S&P 500"
    print(f"[leader_screen] {VERSION}: universe: {source}; sector known for {n_sec} of {len(universe)}")
    ohlcv = fetch_all([u["ticker"] for u in universe] + ["SPY"])
    try:
        markets, rotation = swing_agent._read_bridges()
    except Exception as e:
        print(f"[leader_screen] bridges unreadable: {type(e).__name__}: {e}")
        markets, rotation = {}, {}
    regime_key = ((markets or {}).get("regime") or {}).get("key") or "neutral"
    try:
        cfg = json.loads(Path("data/swing_config.json").read_text())
    except Exception:
        cfg = {}
    res = build(universe, ohlcv, spy=ohlcv.get("SPY"), regime_key=regime_key, rotation=rotation,
                expected=swing_agent.expected_session(), source=source, earnings=ec.earnings_dates,
                equity=float(cfg.get("starting_equity", 10_000.0)), risk_pct=float(cfg.get("base_risk_pct", 1.0)))
    if not ((markets or {}).get("regime") or {}).get("key"):
        res["problems"].append("Markets bridge gave no regime; 'neutral' assumed for the pick column")
    print(render_md(res))
    if not write(res):
        print("[leader_screen] DATA FAILURE — nothing written.")
        return 1
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _bars(drift: float, n: int = 520, start: float = 50.0, vol: float = 2_000_000, seed: int = 0,
          noise: float = 0.004, end: str = "2026-11-13") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = start * np.cumprod(1 + drift + rng.normal(0, noise, n))
    idx = pd.bdate_range(end=end, periods=n)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": vol}, index=idx)


def selftest() -> dict:
    import tempfile
    f = []
    # holdings workbook
    abc = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    names = ["Z" + abc[i // 26] + abc[i % 26] for i in range(498)] + ["BRK.B", "BF.B"]
    hold = pd.DataFrame({"Name": [f"Co {t}" for t in names], "Ticker": names, "Identifier": "x", "SEDOL": "y",
                         "Weight": np.linspace(7.0, 0.01, 500), "Sector": ["Information Technology"] * 250 + ["Energy"] * 250})
    cash = pd.DataFrame({"Name": ["US DOLLAR"], "Ticker": ["-"], "Identifier": ["-"], "SEDOL": ["-"],
                         "Weight": [0.05], "Sector": ["-"]})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.concat([hold, cash]).to_excel(w, index=False, startrow=4)
    rows = parse_spy_holdings(buf.getvalue())
    tk = [r["ticker"] for r in rows]
    if len(rows) != 500 or "BRK-B" not in tk or "-" in tk or rows[0]["ticker"] != "ZAA" or \
            rows[0]["sector"] != "Information Technology":
        f.append(f"holdings parse: {len(rows)} rows, first {rows[0] if rows else None}")
    try:
        b2 = io.BytesIO()
        with pd.ExcelWriter(b2, engine="openpyxl") as w:
            hold.head(50).to_excel(w, index=False)
        parse_spy_holdings(b2.getvalue()); f.append("a 50-name file must be refused")
    except ValueError:
        pass
    u, src = load_universe(fetch_raw=lambda: buf.getvalue())
    if len(u) != 500 or "State Street" not in src:
        f.append("load_universe live path")

    # metrics and the five rules
    up = _bars(0.0015, seed=1)
    m = metrics(up)
    if m is None or not all(trend_checks(m).values()):
        f.append(f"a steady uptrend must pass all five rules: {trend_checks(m) if m else None}")
    if metrics(up.tail(200)) is not None:
        f.append("under a year of bars must return None")
    exp = float(up["Close"].iloc[-1] / up["Close"].iloc[-64] - 1) * 100
    if abs(m["ret63"] - exp) > 1e-9 or abs(m["pivot"] - float(up["Close"].iloc[-21:-1].max())) > 1e-9:
        f.append("3-month return is 63 sessions back; the pivot excludes today")
    spike = up.copy()
    spike.iloc[-1, spike.columns.get_loc("Close")] = float(up["Close"].max()) * 1.2
    if metrics(spike)["pivot"] >= metrics(spike)["close"]:
        f.append("the pivot is the prior 20 sessions' high and must exclude today's close")
    dn = _bars(-0.0010, seed=2)
    if all(trend_checks(metrics(dn)).values()):
        f.append("a downtrend must fail")
    base = dict(m)
    for key, val, name in (("sma200_prev", base["sma200"] * 1.01, "200-day rising"),
                           ("hi52", base["close"] * 1.40, "within 25% of 52w high"),
                           ("lo52", base["close"] / 1.20, "30%+ above 52w low"),
                           ("sma150", base["sma50"] * 1.01, "50 > 150 > 200"),
                           ("sma50", base["close"] * 1.01, "above 50/150/200-day")):
        ch = trend_checks({**base, key: val})
        if ch[name] or sum(not v for v in ch.values()) < 1:
            f.append(f"rule '{name}' must fail when {key} is moved")
    edge = trend_checks({**base, "hi52": base["close"] / 0.75, "lo52": base["close"] / 1.30})
    if not edge["within 25% of 52w high"] or not edge["30%+ above 52w low"]:
        f.append("exactly 25% below the high and 30% above the low both pass")

    # ranking: strength is cross-sectional, over liquid stocks only
    mets = {}
    for i in range(100):
        d = _bars(-0.0005 + i * 0.00003, seed=100 + i, noise=0.0)
        mets[f"T{i:02d}"] = metrics(d)
    mets["THIN"] = metrics(_bars(0.004, seed=7, vol=1_000, noise=0.0005))       # strongest, but illiquid
    mets["PENNY"] = metrics(_bars(0.004, seed=8, start=0.4, noise=0.0005))       # strongest, but under $10
    mets["NEW"] = None
    t = rank(mets).set_index("ticker")
    if t.loc["THIN", "liquid"] or t.loc["PENNY", "liquid"] or t.loc["THIN", "leader"] or pd.notna(t.loc["THIN", "rs"]):
        f.append("illiquid and sub-$10 stocks are not ranked and never leaders")
    if "NEW" in t.index:
        f.append("a stock without metrics is left out")
    if t.loc["T99", "rs"] != 100.0 or t.loc["T00", "rs"] != 0.0 or not (t["rs"].dropna().between(0, 100)).all():
        f.append(f"strength must run 0..100 across the liquid set: T99 {t.loc['T99', 'rs']}, T00 {t.loc['T00', 'rs']}")
    if t.loc["T79", "rs"] >= RS_MIN or t.loc["T80", "rs"] < RS_MIN:
        f.append(f"the 80 line: T79 {t.loc['T79', 'rs']:.1f} T80 {t.loc['T80', 'rs']:.1f}")
    lead = t[t["leader"]]
    if not len(lead) or not (lead["rs"] >= RS_MIN).all() or not lead["trend_ok"].all() or not lead["liquid"].all():
        f.append("a leader needs liquidity, all five rules and strength 80+")
    if t.loc["T99", "trend_ok"] and not t.loc["T99", "leader"]:
        f.append("the strongest liquid uptrend must be a leader")
    weak_but_trending = t[(t["trend_ok"]) & (t["rs"] < RS_MIN)]
    if len(weak_but_trending) and weak_but_trending["leader"].any():
        f.append("an uptrend below strength 80 is not a leader")
    if list(rank(mets)["rs"].dropna()) != sorted(rank(mets)["rs"].dropna(), reverse=True):
        f.append("output is sorted strongest first")

    # build: universe of 500 synthetic stocks
    uni = [{"ticker": f"U{i:03d}", "name": f"Co {i}", "sector": "Energy" if i % 2 else "Information Technology",
            "weight": 0.2} for i in range(500)]
    ohl = {x["ticker"]: _bars(-0.0006 + i * 0.000006, seed=1000 + i, noise=0.0008) for i, x in enumerate(uni)}
    spy = _bars(0.0006, seed=5, start=400)
    rot = {"sectors": [{"ticker": "XLE", "quadrant": "Leading"}, {"ticker": "XLK", "quadrant": "Lagging"}]}
    calls = []

    def fake_eval(ticker, df, regime_key, **kw):
        calls.append((ticker, kw))
        if ticker == "U499":
            return {"setup": "M0 Rotation", "card": {"setup": "M0 Rotation", "live": True, "entry": 101.0, "stop": 95.0,
                                                    "stop_pct": 5.94, "confluence": "3-of-3"}}
        if ticker == "U498":
            return {"setup": "M1 VCP", "card": {"setup": "M1 VCP", "live": False, "entry": 50.0, "stop": 47.0,
                                               "stop_pct": 6.0, "confluence": "2-of-3"}}
        if ticker == "U497":
            return {"setup": "M2 Breakout", "card": None, "avoid_reason": "Earnings within 48h — no new entry."}
        return {"setup": None, "card": None, "avoid_reason": "Not a setup."}
    earn = lambda tks: {"U497": {"date": "2026-11-14", "days_away": 1}, "U496": {"date": "2026-12-20", "days_away": 37}}
    kw = dict(spy=spy, regime_key="transition_ambiguous", rotation=rot, expected=date(2026, 11, 13), source="test",
              earnings=earn, evaluate=fake_eval, market_ok_fn=lambda c: True)
    res = build(uni, ohl, **kw)
    if not res["ok"] or len(res["leaders"]) != TOP_N or res["leaders"][0]["ticker"] != "U499":
        f.append(f"build: ok {res['ok']}, {len(res['leaders'])} leaders, first "
                 f"{res['leaders'][0]['ticker'] if res['leaders'] else None}")
    else:
        L = {x["ticker"]: x for x in res["leaders"]}
        if [x["rank"] for x in res["leaders"]] != list(range(1, TOP_N + 1)) or \
                [x["rs"] for x in res["leaders"]] != sorted([x["rs"] for x in res["leaders"]], reverse=True):
            f.append("leaders are ranked 1..25 by strength")
        if not L["U499"]["live"] or L["U499"]["trigger"] != 101.0 or L["U499"]["quadrant"] != "Leading":
            f.append(f"a live card must show as LIVE with its trigger and quadrant: {L['U499']}")
        if L["U498"]["live"] or L["U498"]["setup"] != "M1 VCP" or "not proven" not in L["U498"]["note"]:
            f.append("an untested setup is watch-only")
        if L["U497"]["setup"] != "M2 Breakout" or L["U497"]["live"] or not L["U497"]["earnings_48h"] or \
                L["U497"]["trigger"] is not None:
            f.append("a refused setup shows the refusal, no trigger")
        if not dict(calls)["U497"]["earnings_within_48h"] or dict(calls)["U496"]["earnings_within_48h"]:
            f.append("the 48-hour earnings flag must reach the evaluator")
        if dict(calls)["U499"]["sector_quadrant"] != "Leading" or dict(calls)["U498"]["sector_quadrant"] != "Lagging":
            f.append("the sector's quadrant must reach the evaluator")
        if dict(calls)["U499"].get("is_etf") is not False:
            f.append("stocks are evaluated as stocks")
        if res["leaders_n"] < TOP_N or res["priced_n"] != 500 or res["trend_n"] < res["leaders_n"]:
            f.append("funnel counts")
        md = render_md(res)
        if "M0 Rotation — LIVE" not in md or "M1 VCP (watch)" not in md or "⚠ 48h" not in md or \
                "Live today: U499" not in md or "Funnel" not in md:
            f.append("report content")
    # market filter closed: a live setup is not shown as LIVE
    r2 = build(uni, ohl, **{**kw, "market_ok_fn": lambda c: False})
    if any(x["live"] for x in r2["leaders"]) or "CLOSED" not in render_md(r2) or "Live today" in render_md(r2):
        f.append("with the market filter closed nothing is LIVE")
    r2b = build(uni, ohl, **{**kw, "market_ok_fn": lambda c: None})
    if any(x["live"] for x in r2b["leaders"]) or "UNKNOWN" not in render_md(r2b):
        f.append("an unknown market filter is not open")
    # nearest pivot when nothing fires
    r3 = build(uni, ohl, **{**kw, "evaluate": lambda *a, **k: {"setup": None, "card": None}})
    for x in r3["leaders"]:
        mm = metrics(ohl[x["ticker"]])
        d = (mm["pivot"] / mm["close"] - 1) * 100
        want = (None if d < 0 or mm["base_range_pct"] > BASE_MAX_RANGE_PCT else
                "Near pivot" if d <= NEAR_PIVOT_PCT else "Basing")
        if x["setup"] != want or (want and x["trigger"] != round(mm["pivot"], 2)) or x["live"] or x["stop"] is not None:
            f.append(f"pivot status for {x['ticker']}: {x['setup']} vs {want}")
            break
    # evaluator crash is contained
    def boom(*a, **k): raise RuntimeError("x")
    r4 = build(uni, ohl, **{**kw, "evaluate": boom})
    if not r4["ok"] or len(r4["leaders"]) != TOP_N:
        f.append("an evaluator error on one stock must not sink the list")
    # data failures
    r5 = build(uni, ohl, **{**kw, "expected": date(2026, 11, 16)})
    if r5["ok"] or "not in the feed" not in " ".join(r5["problems"]) or "DATA FAILURE" not in render_md(r5):
        f.append("a feed short of the expected session is a data failure")
    part = {t: d for i, (t, d) in enumerate(ohl.items()) if i % 5}
    r6 = build(uni, part, **kw)
    if r6["ok"]:
        f.append("80% of the universe priced is below the 90% floor")
    stale = dict(ohl); stale.update({x["ticker"]: ohl[x["ticker"]].iloc[:-1] for x in uni[:30]})
    r7 = build(uni, stale, **kw)
    if not r7["ok"] or r7["stale_n"] != 30 or r7["priced_n"] != 470 or any(x["ticker"] in r7["stale"] for x in r7["leaders"]):
        f.append("stale tickers are dropped and counted; 94% still runs")
    if build(uni, ohl, **{**kw, "spy": None})["ok"]:
        f.append("no SPY is a data failure")
    # no leaders is a real reading
    allweak = {x["ticker"]: _bars(-0.001, seed=3000 + i, noise=0.0005) for i, x in enumerate(uni)}
    r8 = build(uni, allweak, **kw)
    if not r8["ok"] or r8["leaders"] or "No stock passes" not in render_md(r8):
        f.append("a weak market gives an empty, healthy list")
    # earnings failure is reported, not fatal
    def earn_boom(t): raise OSError("x")
    r9 = build(uni, ohl, **{**kw, "earnings": earn_boom})
    if not r9["ok"] or not any("earnings" in p for p in r9["problems"]):
        f.append("an earnings lookup failure is reported and the list still builds")

    # v1.1: a part-day bar after the expected session is dropped, and changes nothing
    intr = {t: pd.concat([d, d.tail(1).set_axis([pd.Timestamp("2026-11-16")]) * 1.5]) for t, d in ohl.items()}
    spy_i = pd.concat([spy, spy.tail(1).set_axis([pd.Timestamp("2026-11-16")]) * 0.5])
    calls.clear()
    ri = build(uni, intr, **{**kw, "spy": spy_i})
    if not ri["ok"] or ri["session"] != "2026-11-13" or ri["market"] != res["market"] or \
            [(x["ticker"], x["close"], x["rs"]) for x in ri["leaders"]] != [(x["ticker"], x["close"], x["rs"]) for x in res["leaders"]]:
        f.append(f"an intraday bar must be dropped: session {ri.get('session')}")
    if any(len(c[1]) and pd.Timestamp("2026-11-16") in c[1].get("bench", pd.Series(dtype=float)).index for c in calls):
        f.append("the evaluator must not see the part-day bar")
    if cut_to_session(spy_i, None) is not spy_i or len(cut_to_session(spy_i, date(2026, 11, 13))) != len(spy):
        f.append("cut_to_session")
    # v1.1: sectors from the list fill blanks only
    src_csv = "Symbol,Security,GICS Sector\n" + "\n".join(
        f"{n},Co,{'Energy' if i % 11 == 0 else list(SECTOR_ETF)[i % 12].title()}" for i, n in enumerate(names))
    sec = parse_sector_list(src_csv)
    if sec.get("BRK-B") is None or len(sec) != 500:
        f.append("sector list: tickers in Yahoo form")
    try:
        parse_sector_list("Symbol,GICS Sector\nA,Energy\n"); f.append("a 1-row sector list must be refused")
    except ValueError:
        pass
    td = Path(tempfile.mkdtemp())
    s1, n1 = load_sectors(fetch_text=lambda: src_csv, path=td / "s.csv")
    if len(s1) != 500 or "refreshed" not in n1 or not (td / "s.csv").exists():
        f.append("load_sectors: refresh and save")
    def _fail(): raise OSError("offline")
    s2, n2 = load_sectors(fetch_text=_fail, path=td / "s.csv")
    if s2 != s1 or "committed file" not in n2:
        f.append("load_sectors: fall back to the committed file")
    s3, n3 = load_sectors(fetch_text=_fail, path=td / "none.csv")
    if s3 != {} or "UNAVAILABLE" not in n3:
        f.append("load_sectors: no source is reported, never raised")
    u2 = [{"ticker": "ZAA", "sector": ""}, {"ticker": "ZAB", "sector": "Utilities"}, {"ticker": "QQQQ", "sector": ""}]
    if apply_sectors(u2, {"ZAA": "Energy", "ZAB": "Energy"}) != 2 or u2[0]["sector"] != "Energy" or u2[1]["sector"] != "Utilities":
        f.append("apply_sectors fills blanks only")
    # v1.1: a past earnings date is not shown as the next one
    past = lambda tks: {"U499": {"date": "2026-11-06", "days_away": -10}, "U498": {"date": "2026-12-01", "days_away": 15}}
    rp = build(uni, ohl, **{**kw, "earnings": past})
    P = {x["ticker"]: x for x in rp["leaders"]}
    if P["U499"]["earnings"] is not None or P["U498"]["earnings"] != "2026-12-01" or rp["earnings_known_n"] != 1 or \
            "2026-11-06" in render_md(rp):
        f.append("a past earnings date must not be shown")
    if res.get("sector_known_n") != TOP_N or "Sector known for 25 of 25" not in render_md(res):
        f.append("sector coverage is reported")

    # v1.2: Nasdaq-100 add-ons
    ndx_names = names[:85] + ["QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH", "QI", "QJ", "QK", "QL", "QM", "QN", "QO", "QP"]
    def page(rows, hdr="<th>Ticker</th><th>Company</th><th>ICB Industry<sup>[1]</sup></th>"):
        body = "".join(f"<tr><td><a href='/x'>{t}</a></td><td>Co <b>{t}</b></td><td>{'Technology' if i % 2 else 'Telecommunications'}</td></tr>"
                       for i, t in enumerate(rows))
        return ("<html><table class='infobox'><tr><th>Constituents</th><td>101</td></tr></table>"
                "<table id='changes'><tr><th>Date</th><th>Ticker</th></tr><tr><td>x</td><td>ABC</td></tr></table>"
                f"<table id='constituents'><tr>{hdr}</tr>{body}</table></html>")
    nd = parse_ndx_html(page(ndx_names))
    sub = parse_ndx_html(page(ndx_names, "<th>Ticker</th><th>Company</th><th>ICB Industry</th>").replace(
        "<th>Ticker</th>", "<th>ICB Subsector</th><th>Ticker</th>").replace("<tr><td><a", "<tr><td>Widgets</td><td><a"))
    if len(sub) != 101 or sub[0]["sector"] not in ("Technology", "Telecommunications"):
        f.append(f"the sector column must not be the sub-sector: {sub[0] if sub else None}")
    if len(nd) != 101 or nd[0]["ticker"] != ndx_names[0] or nd[-1] != {"ticker": "QP", "sector": "Telecommunications"} or \
            "BRK-B" in {r["ticker"] for r in nd}:
        f.append(f"Nasdaq-100 table parse: {len(nd)} rows, last {nd[-1] if nd else None}")
    alt = ("<table><tr><th>Company</th><th>Symbol</th><th>GICS Sector</th></tr>"
           + "".join(f"<tr><td>Co {t}</td><td>{t}</td><td>Energy</td></tr>" for t in ndx_names) + "</table>")
    if [r["ticker"] for r in parse_ndx_html(alt)] != ndx_names or parse_ndx_html(alt)[0]["sector"] != "Energy":
        f.append("Nasdaq-100 parse must follow the header, not a fixed column order")
    for bad in (page(ndx_names[:40]), page(ndx_names + [f"R{c}" for c in "ABCDEFGHIJKLMNOPQRST"]), "<html></html>"):
        try:
            parse_ndx_html(bad); f.append("an implausible Nasdaq-100 table must be refused")
        except ValueError:
            pass
    # v1.3: header-independent, anchored on overlap with the S&P 500
    spset = {re.sub(r"[./]", "-", n) for n in names}
    nohdr = alt.replace("Symbol", "Code")                       # no Ticker/Symbol header at all
    if [r["ticker"] for r in parse_ndx_html(nohdr, spset)] != ndx_names:
        f.append("the ticker column must be found without a Ticker/Symbol header")
    caption = alt.replace("<table><tr>", "<table><tr><th colspan='3'>Components</th></tr><tr>")
    cp = parse_ndx_html(caption, spset)
    if [r["ticker"] for r in cp] != ndx_names or cp[0]["sector"] != "Energy":
        f.append("a title row above the header must not break the parse")
    other = [f"X{a}{b}" for a in "ABCDEFGHIJ" for b in "ABCDEFGHIJ"]            # 100 tickers, none in the S&P 500
    decoy = ("<table><tr><th>Ticker</th></tr>" + "".join(f"<tr><td>{t}</td></tr>" for t in other) + "</table>")
    try:
        parse_ndx_html(decoy, spset); f.append("a 100-ticker table sharing nothing with the S&P 500 must be refused")
    except ValueError as e:
        if "100 rows" not in str(e) and "101 rows" not in str(e):
            f.append(f"a miss must describe the tables it saw: {str(e)[:120]}")
    both = decoy.replace("</table>", "</table>" + nohdr, 1)
    if [r["ticker"] for r in parse_ndx_html(both, spset)] != ndx_names:
        f.append("with a decoy table present the real one must be chosen")
    nd_dir = Path(tempfile.mkdtemp())
    # two qualifying tables: a weaker list (62 shared, no header) must lose to the real one (85 shared)
    weak_names = names[100:162] + [f"W{a}{b}" for a in "ABCDEF" for b in "ABCDEF"]
    weak = "<table>" + "".join(f"<tr><td>{t}</td></tr>" for t in weak_names) + "</table>"
    for html2 in (weak + nohdr, nohdr + weak):
        if [r["ticker"] for r in parse_ndx_html(html2, spset)] != ndx_names:
            f.append("of two plausible tables the one sharing more with the S&P 500 must win")
    n0, _ = load_ndx(fetch_html=lambda u: both, path=Path(tempfile.mkdtemp()) / "n.csv", sp500=spset)
    if [r["ticker"] for r in n0] != ndx_names:
        f.append("load_ndx must pass the S&P 500 set to the parser")
    n1, note1 = load_ndx(fetch_html=lambda u: page(ndx_names), path=nd_dir / "n.csv", sp500=spset)
    _failu = lambda u: _fail()
    n2, note2 = load_ndx(fetch_html=_failu, path=nd_dir / "n.csv")
    n3, note3 = load_ndx(fetch_html=_failu, path=nd_dir / "none.csv")
    # v1.4: the list article is tried first; the old article (no members table) is the second try
    real_shape = ("<table class='wikitable sortable' id='constituents'><tbody><tr><th>Ticker</th><th>Company</th>"
                  "<th>ICB Industry</th><th>ICB Subsector</th></tr>"
                  + "".join(f"<tr><td><a href='/q'>{t}</a></td><td><a>Co {t}</a></td><td>Technology</td><td>Software</td></tr>"
                            for t in ndx_names) + "</tbody></table>")
    no_members = "<table><tr><th>Year</th><th>Closing level</th></tr>" + "<tr><td>1985</td><td>132</td></tr>" * 42 + "</table>"
    seen_urls = []
    def by_url(u):
        seen_urls.append(u)
        return real_shape if "List_of_NASDAQ-100" in u else no_members
    nl, notel = load_ndx(fetch_html=by_url, path=Path(tempfile.mkdtemp()) / "n.csv", sp500=spset)
    if [r["ticker"] for r in nl] != ndx_names or nl[0]["sector"] != "Technology" or seen_urls != [NDX_URLS[0]]:
        f.append(f"the list article must be read first and be enough: {seen_urls}")
    seen_urls.clear()
    def second_only(u):
        seen_urls.append(u)
        return no_members if "List_of_NASDAQ-100" in u else real_shape
    n2nd, _ = load_ndx(fetch_html=second_only, path=Path(tempfile.mkdtemp()) / "n.csv", sp500=spset)
    if [r["ticker"] for r in n2nd] != ndx_names or len(seen_urls) != 2:
        f.append("when the first page has no members table the second page is tried")
    nn, noten = load_ndx(fetch_html=lambda u: no_members, path=Path(tempfile.mkdtemp()) / "n.csv", sp500=spset)
    if nn != [] or "NOT INCLUDED" not in noten:
        f.append("no page with a members table: S&P 500 only, said plainly")
    if len(n1) != 101 or "read today" not in note1 or [r["ticker"] for r in n2] != [r["ticker"] for r in n1] or \
            "saved copy" not in note2 or n3 != [] or "NOT INCLUDED" not in note3:
        f.append("load_ndx: live, then the saved copy, then S&P only with a plain note")
    u3 = [{"ticker": t, "name": "", "sector": "", "weight": 1.0} for t in names]
    added = add_ndx(u3, n1)
    extra = [u for u in u3 if u["index"] == NDX]
    if added != 16 or len(u3) != 516 or {u["ticker"] for u in extra} != set(ndx_names[85:]) or \
            any(u["index"] != SP500 for u in u3[:500]) or extra[0]["sector"] not in ("Technology", "Telecommunications"):
        f.append(f"add_ndx: only the 16 names outside the S&P 500 are added and tagged: {added}")
    if add_ndx([{"ticker": "A", "sector": ""}], []) != 0:
        f.append("no Nasdaq list adds nothing")
    uni_n = [dict(x) for x in uni] + [{"ticker": "QA", "name": "", "sector": "Technology", "weight": 0.0, "index": NDX}]
    ohl_n = dict(ohl); ohl_n["QA"] = _bars(0.004, seed=77, noise=0.0008)
    rn = build(uni_n, ohl_n, **kw)
    N = {x["ticker"]: x for x in rn["leaders"]}
    if rn["leaders"][0]["ticker"] != "QA" or N["QA"]["tested_universe"] or N["QA"]["index"] != NDX or \
            not N["U499"]["tested_universe"] or rn["ndx_extra_n"] != 1 or "**QA** †" not in render_md(rn) or \
            "outside the universe" not in render_md(rn) or "†" in render_md(res):
        f.append("a Nasdaq-only leader is ranked with the rest and marked outside the tested universe")
    hn = history_rows(rn)
    if hn.loc[hn.ticker == "QA", "index"].iloc[0] != NDX or list(hn.columns) != HIST_COLS:
        f.append("history records the index")
    lp = Path(tempfile.mkdtemp())
    write(rn, lp / "o", lp / "l")
    if (load_latest(lp / "o" / "latest.json") or {}).get("session") != "2026-11-13" or load_latest(lp / "x.json") is not None:
        f.append("load_latest returns the last healthy list or None")
    (lp / "bad.json").write_text(json.dumps({"ok": False, "session": "2026-11-13", "leaders": []}))
    if load_latest(lp / "bad.json") is not None:
        f.append("load_latest must not return a failed build")
    old_h = pd.read_csv(lp / "o" / "history.csv").drop(columns=["index"]); old_h["date"] = "2026-11-12"
    old_h.to_csv(lp / "o" / "history.csv", index=False)
    write(rn, lp / "o", lp / "l")
    hh = pd.read_csv(lp / "o" / "history.csv")
    if len(hh) != 2 * len(rn["leaders"]) or set(hh.loc[hh.date == "2026-11-12", "index"]) != {SP500}:
        f.append("history written before v1.2 is kept and read as S&P 500")

    # write: healthy only; a re-run replaces the same session's rows
    d = Path(tempfile.mkdtemp())
    if write(r5, d / "o", d / "l") or (d / "o").exists():
        f.append("a failed build writes nothing")
    write(res, d / "o", d / "l"); write(res, d / "o", d / "l")
    h = pd.read_csv(d / "o" / "history.csv")
    if len(h) != TOP_N or list(h.columns) != HIST_COLS or not (d / "l" / "2026-11-13.md").exists() or \
            json.loads((d / "o" / "latest.json").read_text())["session"] != "2026-11-13":
        f.append(f"write: {len(h)} history rows after two runs of one session")
    ohl2 = {t: _bars(-0.0006 + i * 0.000006, seed=1000 + i, noise=0.0008, end="2026-11-16") for i, t in enumerate(ohl)}
    res2 = build(uni, ohl2, **{**kw, "spy": _bars(0.0006, seed=5, start=400, end="2026-11-16"),
                               "expected": date(2026, 11, 16)})
    write(res2, d / "o", d / "l")
    h = pd.read_csv(d / "o" / "history.csv")
    if len(h) != 2 * TOP_N or sorted(h["date"].unique()) != ["2026-11-13", "2026-11-16"]:
        f.append("a new session appends to the history")
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
