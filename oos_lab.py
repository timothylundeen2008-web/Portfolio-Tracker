"""
oos_lab.py  (v1.1 — 2026-11-25; no real-data run before this version)
───────────────────────────────
v1.1 (independent review, before any real run; recorded in the pre-registration):
  * gold is a World Bank MONTHLY AVERAGE: its month-m return already contains part of month m's
    end, so XM ranks gold on returns lagged one month (through month m-1). Books still earn the
    unlagged spread return (a smoothing limitation that flatters gold's drawdowns in every book);
  * 10-yr return = exact par-bond repricing (convexity included), not the duration approximation;
  * data guards: every source must reach 1999-12-31, gold months must be contiguous, no NaN in any
    return the books can hold, and every simulated day must have full coverage, else abort;
  * each window starts from the PREVIOUS close (the first day's return is counted);
  * the size file's block must be titled value-weighted.
v1.1.1 (plumbing only; first real run aborted on a download timeout): each source is fetched with up to
  4 attempts, a 180 s read timeout and a growing pause, and a failure names the source.

LONG-TERM book only. Out-of-sample replay, 1963–1999, pre-registered in claude/oos_lab_2026-11-25.md
(strategy_plan_2026-11-24.md item 2; Matt 2026-11-25: "retest XM as one fixed in advance candidate",
then chose "1962–1999 daily"). Bars are fixed BEFORE any run on real data; a FAIL is final.

Every engine rule so far was built and judged on 2000–2026 (43 looks). This replays the SAME rules on
37 years none of them has seen: the 1966 and 1969–70 bears, the 1970s inflation, 1973–74, 1987, 1990.

Data (free; fetched in Actions; any failure aborts with nothing written):
  * US market total return, daily: Ken French, Mkt-RF + RF (from 1926).
  * US small caps, daily: Ken French, Portfolios Formed on ME, value-weighted "Lo 30".
  * T-bills, daily: Ken French RF.
  * 10-year Treasury, daily: FRED DGS10 yield (from 1962-01-02) -> total return = carry + the exact
    price change of yesterday's 10-year par bond at today's yield (semiannual coupons).
  * Gold: World Bank monthly average price (datahub core/gold-prices), used from 1971-09 (after the
    dollar left gold); each month's return spread evenly over its trading days (smooths daily moves).
Not available free for these years and therefore absent: QQQ (Nasdaq-100 starts 1985), credit funds,
managed futures, TIPS, commodities, the dollar, international stocks.

Translations, fixed in advance:
  * Engine (O11, offense_lab.states_fast): SPY and QQQ levels both = the US market total-return index;
    no credit series (treated as confirming, as offense_lab does when credit is missing).
  * Offense = 100% US market (the 50/50 QQQ/SPY book with both legs = the market).
  * Balanced (today's transition_ambiguous book mapped by asset class): market 50 / 10-yr 12 /
    gold 18 / cash 20 (trend funds 12 and commodities 3 do not exist -> cash).
  * Defense: cash 60 / gold 20 / 10-yr 20.
  * Before gold exists (to 1971-08), any gold weight sits in cash.
  * XM-N: xm_lab's own scores() and rank_book() on sleeves MKT, SMALL, BOND10, GOLD, CASH; Defense
    excludes MKT and SMALL; month-end ranking used from the next session; N = 3 (decision), 2 and 4.
Candidates (trials 43 -> 47): O11-R (engine evidence), XM3-R (decision), XM2-R, XM4-R (neighbours).
Benchmarks: US market buy-and-hold; 60/40 market / 10-yr (rebalanced daily).

Run:  python oos_lab.py            (Actions)
      python oos_lab.py --selftest (offline)
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

import hedge_lab as hl
import offense_lab as ol
import xm_lab as xm

VERSION = "1.1.1"
OUT_DIR, LOG_DIR = Path("data/oos_lab"), Path("logs/oos_lab")
TRIALS_BEFORE, TRIALS_HERE = 43, 4
EVAL_START, EVAL_END = "1963-01-02", "1999-12-31"
HALVES = (("1963-81", "1963-01-02", "1981-12-31"), ("1982-99", "1982-01-01", "1999-12-31"))
WINDOWS = [("bear_1966", "1966-02-09", "1966-10-07", "1966 bear"),
           ("bear_1969", "1968-11-29", "1970-05-26", "1969–70 bear"),
           ("bear_1973", "1973-01-11", "1974-10-03", "1973–74 bear"),
           ("infl_1977", "1977-01-03", "1981-12-31", "1977–81 inflation"),
           ("crash_1987", "1987-08-25", "1987-12-04", "1987 crash"),
           ("bear_1990", "1990-07-16", "1990-10-11", "1990 bear")]
GOLD_FROM = "1971-09-01"
N_DECISION, N_NEIGHBOURS = 3, (2, 4)
SLEEVES = ("MKT", "SMALL", "BOND10", "GOLD", "CASH")
OFF_BOOK = {"MKT": 100.0}
BAL_BOOK = {"MKT": 50.0, "BOND10": 12.0, "GOLD": 18.0, "CASH": 20.0}
DEF_BOOK = {"CASH": 60.0, "GOLD": 20.0, "BOND10": 20.0}
XM_EQUITY = ("MKT", "SMALL")
BAR = {"eng_cagr_tol": 1.0, "dd_ratio": 0.5, "half_tol": 0.25, "max_dd": -20.0}
FRENCH = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
URLS = {"ff3": FRENCH + "F-F_Research_Data_Factors_daily_CSV.zip",
        "size": FRENCH + "Portfolios_Formed_on_ME_daily_CSV.zip",
        "dgs10": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
        "gold": "https://datahub.io/core/gold-prices/_r/-/data/monthly.csv"}


# ── parsing and return construction ─────────────────────────────────────────

def parse_french(text: str, cols: tuple, title: Optional[str] = None) -> pd.DataFrame:
    """First block of a Ken French daily CSV (header row containing `cols`, then YYYYMMDD rows), in %.
    If `title` is given, one of the 3 lines above the header must contain it (e.g. "Value Weight")."""
    lines = text.splitlines()
    hdr = None
    for i, ln in enumerate(lines):
        parts = [p.strip() for p in ln.split(",")]
        if all(c in parts for c in cols):
            hdr, start = parts, i + 1
            break
    if hdr is None:
        raise ValueError(f"columns {cols} not found")
    if title and not any(title.lower() in x.lower() for x in lines[max(0, start - 4):start - 1]):
        raise ValueError(f"first block with {cols} is not titled '{title}'")
    rows = []
    for ln in lines[start:]:
        parts = [p.strip() for p in ln.split(",")]
        if not parts or not parts[0].isdigit() or len(parts[0]) != 8:
            if rows:
                break                                   # end of the first block
            continue
        rows.append(parts)
    df = pd.DataFrame(rows, columns=hdr[:len(rows[0])] if rows else hdr)
    df.index = pd.to_datetime(df.iloc[:, 0], format="%Y%m%d")
    out = df[list(cols)].astype(float)
    out[out <= -99.0] = np.nan                         # French codes missing as -99.99
    return out


def par_price(coupon, yld, periods: int = 20):
    """Price per 1 of face of a bond paying coupon/2 semiannually for `periods` halves, at yield `yld`."""
    h = yld / 2.0
    disc = (1.0 + h) ** (-periods)
    return (coupon / 2.0) * (1.0 - disc) / h + disc


def bond_returns(yld: pd.Series, cal: pd.DatetimeIndex) -> pd.Series:
    """Daily total return of a 10-year constant-maturity par bond from its yield (%): one day's carry
    plus the exact repricing of yesterday's par bond (coupon = yesterday's yield) at today's yield.
    NaN before data and across gaps of more than 5 sessions."""
    y = yld.reindex(cal).ffill(limit=5) / 100.0
    y0 = y.shift(1)
    r = y0 / 252.0 + (par_price(y0, y) - 1.0)
    first = yld.dropna().index.min()
    r[cal <= first] = np.nan
    return r


def gold_daily(monthly: pd.Series, cal: pd.DatetimeIndex, start: str = GOLD_FROM) -> pd.Series:
    """Monthly price -> daily returns: each month's return spread evenly (geometrically) over its
    trading days. NaN before `start` (gold not freely priced)."""
    m = monthly.copy()
    m.index = m.index.to_period("M")
    mret = m.pct_change()
    r = pd.Series(np.nan, index=cal)
    per = cal.to_period("M")
    for p in pd.unique(per):
        if p not in mret.index or not np.isfinite(mret.get(p, np.nan)):
            continue
        days = cal[per == p]
        r[days] = (1.0 + mret[p]) ** (1.0 / len(days)) - 1.0
    r[cal < pd.Timestamp(start)] = np.nan
    return r


def build(ff3: pd.DataFrame, size: pd.DataFrame, dgs10: pd.Series, gold: pd.Series) -> dict:
    cal = ff3.index[ff3.index <= pd.Timestamp(EVAL_END)]
    rf = ff3["RF"].reindex(cal) / 100.0
    mkt = (ff3["Mkt-RF"].reindex(cal) + ff3["RF"].reindex(cal)) / 100.0
    rets = pd.DataFrame({"MKT": mkt, "SMALL": size["Lo 30"].reindex(cal) / 100.0,
                         "BOND10": bond_returns(dgs10, cal), "GOLD": gold_daily(gold, cal), "CASH": rf}, index=cal)
    rank = rets.copy()
    rank["GOLD"] = gold_daily(gold.shift(1), cal)       # month m holds month m-1's return: no average leak
    lvl = (1 + mkt.fillna(0.0)).cumprod()
    levels = pd.DataFrame({"SPY": lvl, "QQQ": lvl}, index=cal)
    eng_rets = pd.DataFrame({"SPY": mkt, "QQQ": mkt}, index=cal)
    return {"cal": cal, "rets": rets, "rank": rank, "levels": levels, "eng_rets": eng_rets}


# ── books and weights ───────────────────────────────────────────────────────

def avail(book: dict, d, rets: pd.DataFrame) -> dict:
    """Move weight on sleeves with no data yet (gold before 1971-09) into cash."""
    out = {}
    for k, v in book.items():
        kk = k if (k == "CASH" or rets[k].loc[:d].notna().any()) else "CASH"
        out[kk] = out.get(kk, 0.0) + v
    return out


def xm_books(rets: pd.DataFrame, n: int) -> tuple:
    """Month-end XM books via xm_lab's own scores() and rank_book() (same scoring code as the 2000–26 test).
    Pass the RANKING frame (gold lagged one month), not the holding frame."""
    pos = {d: i for i, d in enumerate(rets.index)}
    full, dfn = {}, {}
    for me in xm.month_ends(rets.index):
        sc = xm.scores(rets, pos[me])
        full[me] = {k.replace(xm.PFX, ""): v for k, v in xm.rank_book(sc, n).items()}
        dfn[me] = {k.replace(xm.PFX, ""): v for k, v in xm.rank_book(sc, n, exclude=XM_EQUITY).items()}
    return full, dfn


def make_weights(st: pd.Series, rets: pd.DataFrame, mode: str, full: Optional[dict] = None,
                 dfn: Optional[dict] = None) -> Callable:
    """Same lag rules as xm_lab.make_weights: state seen at d-1; book from the latest month-end < d."""
    lagged = st.shift(ol.LAG)
    lagged.iloc[:ol.LAG] = st.iloc[0]
    sm = lagged.to_dict()
    mes = sorted(full) if full else []
    me_idx = pd.DatetimeIndex(mes)

    def latest(books, d):
        k = me_idx.searchsorted(d, side="left") - 1
        return books[mes[k]] if k >= 0 else {"CASH": 100.0}

    def w(d):
        if mode == "mkt":
            return dict(OFF_BOOK)
        if mode == "6040":
            return {"MKT": 60.0, "BOND10": 40.0} if rets["BOND10"].loc[:d].notna().any() else {"MKT": 60.0, "CASH": 40.0}
        s = sm[d]
        if s == "OFF":
            return dict(OFF_BOOK)
        if mode == "o11":
            return avail(DEF_BOOK if s == "DEF" else BAL_BOOK, d, rets)
        return dict(latest(dfn if s == "DEF" else full, d))
    return w


# ── statistics and bars ─────────────────────────────────────────────────────

def window(nav: pd.Series, a: str, b: Optional[str] = None) -> pd.Series:
    """nav from the last close BEFORE `a` (the base, so a's first day counts) through `b`."""
    before = nav.index[nav.index < pd.Timestamp(a)]
    lo = before[-1] if len(before) else nav.index[0]
    return nav[(nav.index >= lo) & ((nav.index <= pd.Timestamp(b)) if b else True)]


def stats(nav: pd.Series, a: str, b: Optional[str] = None) -> dict:
    s = window(nav, a, b)
    if len(s) < 2:
        return {}
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    tot = s.iloc[-1] / s.iloc[0] - 1
    dd = (s / s.cummax() - 1).min()
    return {"cagr_pct": round(((1 + tot) ** (1 / yrs) - 1) * 100, 2) if yrs > 0.9 else None,
            "total_pct": round(tot * 100, 2), "max_dd_pct": round(float(dd) * 100, 2)}


def judge(nav: pd.Series, mkt_nav: pd.Series) -> dict:
    out = {"full": stats(nav, EVAL_START, EVAL_END)}
    for k, a, b in HALVES:
        out[k] = stats(nav, a, b)
    for k, a, b, _ in WINDOWS:
        out[k] = stats(nav, a, b)
    nv, mk = window(nav, EVAL_START, EVAL_END), window(mkt_nav, EVAL_START, EVAL_END)
    y0, y1 = pd.Timestamp(EVAL_START).year, pd.Timestamp(EVAL_END).year

    def yr(s_):                                        # calendar years; base = the prior year's last close
        ye = s_[s_.index <= pd.Timestamp(EVAL_END)].groupby(s_.index[s_.index <= pd.Timestamp(EVAL_END)].year).last()
        out_ = ye.pct_change() * 100
        return out_[(out_.index >= y0) & (out_.index <= y1)].dropna()
    both = pd.DataFrame({"book": yr(nv), "mkt": yr(mk)}).dropna()
    down, up = both[both.mkt < 0], both[both.mkt >= 0]
    return {"summ": out, "years": both,
            "down_years_beaten": int((down.book > down.mkt).sum()), "down_years": int(len(down)),
            "up_lags_gt10": [int(d) for d, r in up.iterrows() if r.book - r.mkt < -10],
            "losing_years": [int(d) for d, r in both.iterrows() if r.book < 0]}


def engine_bar(o: dict, m: dict) -> list:
    why = []
    c, cm = o["summ"]["full"].get("cagr_pct"), m["summ"]["full"].get("cagr_pct")
    if c is None or cm is None or c < cm - BAR["eng_cagr_tol"] - 1e-9:
        why.append(f"CAGR {c}% more than {BAR['eng_cagr_tol']} pt below the market's {cm}%")
    dd, dm = o["summ"]["full"].get("max_dd_pct"), m["summ"]["full"].get("max_dd_pct")
    if dd is None or dm is None or not dd > dm * BAR["dd_ratio"]:
        why.append(f"max DD {dd}% not shallower than half the market's {dm}%")
    if o["down_years_beaten"] < o["down_years"]:
        why.append(f"beat the market in {o['down_years_beaten']} of {o['down_years']} down years")
    return why


def xm_bar(x: dict, o: dict, full_bar: bool = True) -> list:
    why = []
    g = lambda d, h, f: d["summ"].get(h, {}).get(f)
    xf, of = g(x, "full", "cagr_pct"), g(o, "full", "cagr_pct")
    if xf is None or of is None or not xf > of + 0.01 - 1e-9:
        why.append(f"full CAGR {g(x, 'full', 'cagr_pct')}% not above O11-R {g(o, 'full', 'cagr_pct')}%")
    for h, _a, _b in HALVES:
        a_, b_ = g(x, h, "cagr_pct"), g(o, h, "cagr_pct")
        if a_ is None or b_ is None or a_ < b_ - BAR["half_tol"] - 1e-9:
            why.append(f"{h} CAGR {a_}% < O11-R {b_}% − {BAR['half_tol']}")
    dd = g(x, "full", "max_dd_pct")
    if dd is None or not dd > BAR["max_dd"]:
        why.append(f"max DD {dd}% deeper than {BAR['max_dd']}%")
    if full_bar:
        if x["down_years_beaten"] < x["down_years"]:
            why.append(f"beat the market in {x['down_years_beaten']} of {x['down_years']} down years")
        if len(x["losing_years"]) > len(o["losing_years"]):
            why.append(f"{len(x['losing_years'])} losing years vs O11-R's {len(o['losing_years'])}")
    return why


class DataFailure(RuntimeError):
    pass


def check_returns(d: dict) -> list:
    """No NaN in any return a book can hold over the evaluation window (gold before its data excepted)."""
    r = d["rets"]
    w = r[(r.index >= pd.Timestamp(EVAL_START)) & (r.index <= pd.Timestamp(EVAL_END))]
    bad = []
    for c in w.columns:
        cw = w[c] if c != "GOLD" else w.loc[w.index >= pd.Timestamp(GOLD_FROM), c]
        if cw.isna().any():
            bad.append(f"{c}: {int(cw.isna().sum())} missing days (first {cw[cw.isna()].index[0].date()})")
    if w.index[-1] < pd.Timestamp(EVAL_END) - pd.Timedelta(days=5):
        bad.append(f"calendar ends {w.index[-1].date()}")
    return bad


def analyse(d: dict) -> dict:
    st = ol.states_fast(d["levels"], d["eng_rets"], credit=True)
    days = d["cal"][d["cal"] >= pd.Timestamp(EVAL_START) - pd.Timedelta(days=10)]

    def sim(wf):
        out = hl.simulate(days, d["rets"], wf, None, breaker=False, cost_bps=ol.COST_BPS)
        short = out.index[(out["coverage"] < 1.0 - 1e-12) & (out.index >= pd.Timestamp(EVAL_START))]
        if len(short):
            raise DataFailure(f"a held sleeve had no return on {len(short)} days (first {short[0].date()})")
        return out
    mk = sim(make_weights(st, d["rets"], "mkt"))["nav"]
    res = {"Market": {**judge(mk, mk), "nav": mk}}
    s64 = sim(make_weights(st, d["rets"], "6040"))["nav"]
    res["60/40"] = {**judge(s64, mk), "nav": s64}
    o = sim(make_weights(st, d["rets"], "o11"))["nav"]
    res["O11-R"] = {**judge(o, mk), "nav": o}
    for n in (N_DECISION, *N_NEIGHBOURS):
        full, dfn = xm_books(d["rank"], n)
        nv = sim(make_weights(st, d["rets"], "xm", full, dfn))["nav"]
        res[f"XM{n}-R"] = {**judge(nv, mk), "nav": nv}
    st_eval = st[st.index >= pd.Timestamp(EVAL_START)]
    share = st_eval.value_counts(normalize=True).round(3).to_dict()
    e_why = engine_bar(res["O11-R"], res["Market"])
    x_why = xm_bar(res[f"XM{N_DECISION}-R"], res["O11-R"])
    nb = {f"XM{n}-R": xm_bar(res[f"XM{n}-R"], res["O11-R"], full_bar=False) for n in N_NEIGHBOURS}
    stable = all(not v for v in nb.values())
    return {"version": VERSION, "engine": {"verdict": "FAIL" if e_why else "PASS", "fails": e_why},
            "xm": {"verdict": "FAIL" if x_why else ("PASS (stable)" if stable else "PASS (not stable)"),
                   "fails": x_why, "neighbours": nb, "stable": stable},
            "state_share": share, "res": res}


# ── data checks (reported; N89) ─────────────────────────────────────────────

def _pct(x):
    x = float(x)
    return round(x * 100, 2) if np.isfinite(x) else None


def data_checks(ff3: pd.DataFrame, yahoo: dict) -> dict:
    out = {}
    mkt = (ff3["Mkt-RF"] + ff3["RF"]) / 100.0
    spy = yahoo.get("SPY")
    if spy is not None and len(spy):
        r = hl._norm(spy).pct_change()
        both = pd.DataFrame({"french": mkt, "spy": r}).dropna()
        both = both[(both.index >= "1994-01-01") & (both.index <= "1999-12-31")]
        if len(both) > 100:
            out["french_vs_spy_1994_99"] = {"corr": round(float(both.corr().iloc[0, 1]), 4),
                                            "mean_abs_diff_bp": round(float((both.french - both.spy).abs().mean()) * 1e4, 1),
                                            "n": int(len(both))}
    days = ["2000-01-05", "2000-01-06", "2000-01-07"]
    row = {}
    for nm, ser in (("SPY (Yahoo)", yahoo.get("SPY")), ("^GSPC", yahoo.get("^GSPC")), ("QQQ (Yahoo)", yahoo.get("QQQ"))):
        if ser is not None and len(ser):
            r = hl._norm(ser).pct_change()
            row[nm] = {dd: _pct(r.get(pd.Timestamp(dd), np.nan)) for dd in days}
    row["French market"] = {dd: _pct(mkt.get(pd.Timestamp(dd), np.nan)) for dd in days}
    out["jan_2000"] = row
    return out


# ── output ──────────────────────────────────────────────────────────────────

def _c(x):
    return "—" if x is None else f"{x:.2f}%"


def render(a: dict, chk: dict, stamp: str) -> str:
    res = a["res"]
    cols = ["O11-R", f"XM{N_DECISION}-R", *[f"XM{n}-R" for n in N_NEIGHBOURS], "60/40", "Market"]
    L = [f"# OOS lab {VERSION} — out-of-sample replay 1963–1999 — {stamp}", "",
         f"Pre-registered in `claude/oos_lab_2026-11-25.md`. Long-term engine trials {TRIALS_BEFORE} → "
         f"{TRIALS_BEFORE + TRIALS_HERE}. Research, not personalized advice.", "",
         f"## Engine (O11-R vs the market): **{a['engine']['verdict']}**",
         f"- Fails: {'; '.join(a['engine']['fails']) or 'none'}",
         f"- Time in each state (1963–99): " + ", ".join(f"{k} {v * 100:.0f}%" for k, v in a["state_share"].items()), "",
         f"## XM (N = {N_DECISION}) vs O11-R: **{a['xm']['verdict']}**",
         f"- Fails: {'; '.join(a['xm']['fails']) or 'none'}",
         "- Neighbours (bars X1–X3): " + "; ".join(f"{k}: {'meets' if not v else '; '.join(v)}" for k, v in a["xm"]["neighbours"].items()), "",
         "| | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    rows = [("CAGR 1963–99", "full", "cagr_pct"), ("CAGR 1963–81", "1963-81", "cagr_pct"), ("CAGR 1982–99", "1982-99", "cagr_pct"),
            ("Max DD", "full", "max_dd_pct")] + [(lab, k, "total_pct") for k, _a, _b, lab in WINDOWS]
    for lab, h, f in rows:
        L.append(f"| {lab} | " + " | ".join(_c(res[c]["summ"].get(h, {}).get(f)) for c in cols) + " |")
    L.append("| Down years beaten | " + " | ".join(f"{res[c]['down_years_beaten']} of {res[c]['down_years']}" for c in cols) + " |")
    L.append("| Up years >10 pts behind | " + " | ".join(str(len(res[c]["up_lags_gt10"])) for c in cols) + " |")
    L.append("| Losing years | " + " | ".join(", ".join(map(str, res[c]["losing_years"])) or "none" for c in cols) + " |")
    L += ["", "## Data checks (N89)"]
    fs = chk.get("french_vs_spy_1994_99")
    L.append(f"- French market vs Yahoo SPY, daily 1994–99: " +
             (f"correlation {fs['corr']}, mean |difference| {fs['mean_abs_diff_bp']} bp over {fs['n']} days" if fs else "not available"))
    for nm, v in chk.get("jan_2000", {}).items():
        L.append(f"- {nm}: " + ", ".join(f"{k} {x:+.2f}%" for k, x in v.items() if x is not None))
    L += ["", f"*oos_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def write_outputs(a: dict, chk: dict, stamp: str, out_dir: Path = OUT_DIR, log_dir: Path = LOG_DIR) -> str:
    md = render(a, chk, stamp)
    navs = pd.DataFrame({k: v["nav"] for k, v in a["res"].items()})
    years = pd.DataFrame({k: v["years"]["book"] for k, v in a["res"].items()})
    js = {"version": VERSION, "asof": stamp, "engine": a["engine"], "xm": a["xm"], "state_share": a["state_share"],
          "trials": TRIALS_BEFORE + TRIALS_HERE, "data_checks": chk,
          "books": {k: {kk: vv for kk, vv in v.items() if kk not in ("nav", "years")} for k, v in a["res"].items()}}
    text = json.dumps(js, indent=1, default=str)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    navs.round(4).to_csv(out_dir / "nav.csv")
    years.round(2).to_csv(out_dir / "years.csv")
    (out_dir / "summary.json").write_text(text)
    (log_dir / "latest.md").write_text(md)
    (log_dir / f"{stamp}.md").write_text(md)
    return md


def http_get(url: str) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research; portfolio-tracker oos_lab)"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def fetch_source(get, key: str, tries: int = 4, pause: float = 10.0) -> bytes:
    """One source with retries; the last error is re-raised naming the source."""
    import time
    last = None
    for i in range(tries):
        try:
            return get(URLS[key])
        except Exception as e:                 # timeouts, resets, HTTP errors
            last = e
            print(f"[oos_lab] {key}: attempt {i + 1} of {tries} failed ({type(e).__name__}: {e})")
            if i < tries - 1 and pause:
                time.sleep(pause * (i + 1))
    raise RuntimeError(f"{key} ({URLS[key]}) failed {tries} times: {type(last).__name__}: {last}")


def unzip_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        return z.read(name).decode("latin-1")


def load_all(get=http_get, pause: float = 10.0) -> tuple:
    ff3 = parse_french(unzip_text(fetch_source(get, "ff3", pause=pause)), ("Mkt-RF", "RF"))
    size = parse_french(unzip_text(fetch_source(get, "size", pause=pause)), ("Lo 30",), title="Value Weight")
    dg = pd.read_csv(io.BytesIO(fetch_source(get, "dgs10", pause=pause)))
    dg.columns = [c.strip().upper() for c in dg.columns]
    dcol = [c for c in dg.columns if "DATE" in c][0]
    dgs10 = pd.Series(pd.to_numeric(dg["DGS10"], errors="coerce").to_numpy(), index=pd.to_datetime(dg[dcol])).dropna()
    gd = pd.read_csv(io.BytesIO(fetch_source(get, "gold", pause=pause)))
    gd.columns = [c.strip().lower() for c in gd.columns]
    gold = pd.Series(pd.to_numeric(gd["price"], errors="coerce").to_numpy(), index=pd.to_datetime(gd["date"].astype(str).str[:7])).dropna()
    return ff3, size, dgs10, gold


def main(get=http_get, yahoo_fetch=None, pause: float = 10.0) -> int:
    stamp = date.today().isoformat()
    try:
        ff3, size, dgs10, gold = load_all(get, pause)
    except Exception as e:
        print(f"[oos_lab] DATA FAILURE: {type(e).__name__}: {e}; nothing written.")
        return 1
    problems = []
    ev = ff3.index[(ff3.index >= "1962-01-01") & (ff3.index <= EVAL_END)]
    if ff3.index.min() > pd.Timestamp("1960-01-01") or ff3.index.max() < pd.Timestamp(EVAL_END) or ff3.loc[ev].isna().any().any():
        problems.append(f"French factors do not cover 1962–99 cleanly (end {ff3.index.max().date()})")
    sz = size["Lo 30"].reindex(ev)
    if sz.isna().any():
        problems.append(f"French size portfolio missing {int(sz.isna().sum())} of the factor file's days in 1962–99")
    if dgs10.index.min() > pd.Timestamp("1962-01-31") or dgs10.index.max() < pd.Timestamp(EVAL_END) - pd.Timedelta(days=5):
        problems.append(f"DGS10 covers {dgs10.index.min().date()} → {dgs10.index.max().date()}")
    need = pd.period_range("1971-07", "1999-12", freq="M")
    have = set(gold.index.to_period("M"))
    miss = [str(m) for m in need if m not in have]
    if miss or gold.index.to_period("M").duplicated().any():
        problems.append(f"gold monthly series not contiguous 1971-07 → 1999-12 (missing {', '.join(miss[:5])}{'…' if len(miss) > 5 else ''})")
    print(f"[oos_lab] {VERSION}: French {ff3.index.min().date()}→{ff3.index.max().date()}, size {size.index.min().date()}, "
          f"DGS10 {dgs10.index.min().date()}, gold {gold.index.min().date()}→{gold.index.max().date()}")
    if problems:
        print("[oos_lab] DATA FAILURE: " + "; ".join(problems) + "; nothing written.")
        return 1
    d = build(ff3, size, dgs10, gold)
    bad = check_returns(d)
    if bad:
        print("[oos_lab] DATA FAILURE: " + "; ".join(bad) + "; nothing written.")
        return 1
    try:
        a = analyse(d)
    except DataFailure as e:
        print(f"[oos_lab] DATA FAILURE: {e}; nothing written.")
        return 1
    try:
        yahoo = (yahoo_fetch or hl.yf_fetch)(["SPY", "^GSPC", "QQQ"], start="1993-01-01")
    except Exception:
        yahoo = {}
    chk = data_checks(ff3, yahoo)
    print(write_outputs(a, chk, stamp))
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _french_text(df: pd.DataFrame, extra_block: bool = True, title: str = "  Value Weight Returns -- Daily") -> str:
    L = ["This file was created by CMPT_ME_BEME_RETS using the 202610 CRSP database.", "", title,
         "," + ",".join(df.columns)]
    L += [d.strftime("%Y%m%d") + "," + ",".join(f"{v:.2f}" for v in row) for d, row in zip(df.index, df.to_numpy())]
    if extra_block:
        L += ["", "  Equal Weighted Returns -- Daily", "," + ",".join(df.columns)]
        L += [d.strftime("%Y%m%d") + "," + ",".join("99.00" for _ in row) for d, row in zip(df.index, df.to_numpy())]
    L += ["", "Copyright 2026 Eugene F. Fama and Kenneth R. French"]
    return "\n".join(L)


def _fixture(seed: int = 7):
    rng = np.random.default_rng(seed)
    cal = pd.bdate_range("1955-01-03", "1999-12-31")
    n = len(cal)
    reg = np.where((np.arange(n) // 700) % 2 == 0, 0.05, -0.04)
    ff3 = pd.DataFrame({"Mkt-RF": rng.normal(reg, 0.9), "SMB": rng.normal(0, 0.4, n), "HML": rng.normal(0, 0.4, n),
                        "RF": 0.02}, index=cal).round(2)
    size = pd.DataFrame({"<= 0": 0.0, "Lo 30": (ff3["Mkt-RF"] * 1.1 + rng.normal(0.01, 0.5, n)).round(2),
                         "Med 40": 0.0, "Hi 30": 0.0}, index=cal)
    ycal = cal[cal >= "1962-01-02"]
    dgs10 = pd.Series(4.0 + np.cumsum(rng.normal(0, 0.03, len(ycal))), index=ycal).clip(lower=1.0)
    months = pd.period_range("1960-01", "1999-12", freq="M").to_timestamp()
    gold = pd.Series(35.0 * np.exp(np.cumsum(np.r_[np.zeros(140), rng.normal(0.008, 0.05, len(months) - 140)])), index=months)
    return ff3, size, dgs10, gold


def selftest() -> dict:
    import contextlib, os, tempfile
    f = []
    ff3, size, dgs10, gold = _fixture()
    # parse_french: first block only, values, dates
    p = parse_french(_french_text(ff3), ("Mkt-RF", "RF"))
    if not np.allclose(p["Mkt-RF"].to_numpy(), ff3["Mkt-RF"].to_numpy()) or p.index[0] != ff3.index[0]:
        f.append("parse_french must read the first block exactly")
    ps = parse_french(_french_text(size), ("Lo 30",), title="Value Weight")
    if len(ps) != len(size) or ps["Lo 30"].max() > 50:
        f.append("parse_french must stop at the second (equal-weight) block")
    try:
        parse_french(_french_text(size, title="  Equal Weight Returns -- Daily"), ("Lo 30",), title="Value Weight")
        f.append("parse_french must refuse a first block that is not value-weighted")
    except ValueError:
        pass
    try:
        parse_french("a,b\n1,2", ("Lo 30",))
        f.append("parse_french must raise on missing columns")
    except ValueError:
        pass
    # bond returns: a flat yield earns carry only; a 1-pt rise loses about the duration
    cal = pd.bdate_range("1962-01-02", periods=300)
    flat = bond_returns(pd.Series(6.0, index=cal), cal)
    if abs(flat.iloc[5] - 0.06 / 252) > 1e-12 or not np.isnan(flat.iloc[0]):
        f.append("bond_returns: flat yield = carry; NaN on the first day")
    # textbook value: a 6% 10-year semiannual par bond repriced at 7% is worth 92.894 (and 107.79 at 5%)
    jump = pd.Series(6.0, index=cal); jump.iloc[100:] = 7.0
    rj = bond_returns(jump, cal).iloc[100]
    if abs(rj - (0.06 / 252 + 0.92894 - 1)) > 2e-5:
        f.append(f"bond_returns: 6% -> 7% should return {0.06 / 252 - 0.07106:.5f} (got {rj:.5f})")
    dn = pd.Series(6.0, index=cal); dn.iloc[100:] = 5.0
    if abs(bond_returns(dn, cal).iloc[100] - (0.06 / 252 + 1.07795 - 1)) > 2e-5:
        f.append("bond_returns: 6% -> 5% should return about +7.80% (convexity included)")
    gap = pd.Series(6.0, index=cal).drop(cal[150:160])
    if not bond_returns(gap, cal).iloc[150:160].isna().any():
        f.append("bond_returns: a gap of more than 5 sessions must leave NaN (caught by check_returns)")
    # gold: monthly return spread over the month's days; NaN before 1971-09
    gc = pd.bdate_range("1971-06-01", "1972-12-29")
    gm = pd.Series([100.0, 110.0], index=pd.to_datetime(["1972-01-01", "1972-02-01"]))
    gd = gold_daily(gm, gc)
    feb = gd[(gd.index >= "1972-02-01") & (gd.index < "1972-03-01")]
    if abs((1 + feb).prod() - 1.10) > 1e-9 or gd[gd.index < "1971-09-01"].notna().any():
        f.append("gold_daily: month compounds to the monthly return; NaN before 1971-09")
    # build + books
    d = build(ff3, size, dgs10, gold)
    r = d["rets"]
    if r["BOND10"][r.index < "1962-01-03"].notna().any() or r["GOLD"][r.index < "1971-09-01"].notna().any():
        f.append("sleeves must be NaN before their data")
    if not np.allclose(r["MKT"].dropna().iloc[:5].to_numpy(), ((ff3["Mkt-RF"] + ff3["RF"]) / 100).iloc[:5].to_numpy()):
        f.append("MKT = (Mkt-RF + RF) / 100")
    b70 = avail(BAL_BOOK, pd.Timestamp("1970-06-01"), r)
    b80 = avail(BAL_BOOK, pd.Timestamp("1980-06-02"), r)
    if b70.get("GOLD") or abs(b70["CASH"] - 38.0) > 1e-9 or b80.get("GOLD") != 18.0 or abs(sum(b70.values()) - 100) > 1e-9:
        f.append(f"avail: gold weight in cash before 1971-09 ({b70}, {b80})")
    # ranking frame: gold's month-m return is month m-1's (no monthly-average leak); holdings are unlagged
    rk = d["rank"]["GOLD"]
    for mth in ("1975-03", "1984-07"):
        hm = (1 + r["GOLD"][mth]).prod() - 1
        rm_ = (1 + rk[mth]).prod() - 1
        prev_m = (pd.Period(mth, "M") - 1).strftime("%Y-%m")
        if abs(rm_ - ((1 + r["GOLD"][prev_m]).prod() - 1)) > 1e-9 or abs(rm_ - hm) < 1e-12:
            f.append(f"rank frame: gold in {mth} must carry {prev_m}'s return")
            break
    full, dfn = xm_books(d["rank"], 3)
    mes = sorted(full)
    early = [me for me in mes if me < pd.Timestamp("1972-08-01")]
    if any("GOLD" in full[me] for me in early):
        f.append("gold cannot be ranked before 252 sessions of lagged data")
    if any(abs(sum(full[me].values()) - 100) > 1e-9 for me in mes):
        f.append("XM books must sum to 100")
    if any(k in XM_EQUITY for me in mes for k in dfn[me]):
        f.append("XM Defense books must hold no equities")
    # lag equality with xm_lab.make_weights ('alone' mode = the ranking only)
    st = ol.states_fast(d["levels"], d["eng_rets"], credit=True)
    pf = {me: {xm.PFX + k: v for k, v in b.items()} for me, b in full.items()}
    w_x = xm.make_weights(st, pf, pf, {}, "alone")
    w_mine = make_weights(st, r, "xm", full, dfn)
    pd_ = {me: {xm.PFX + k: v for k, v in b.items()} for me, b in dfn.items()}
    w_xd = xm.make_weights(st, pd_, pd_, {}, "alone")
    w_o11 = make_weights(st, r, "o11")
    lag = st.shift(1)
    seen_st = set()
    for dd in d["cal"][d["cal"] >= "1965-01-04"][::7]:
        s_ = lag[dd]
        seen_st.add(s_)
        mine_w = {xm.PFX + k: v for k, v in w_mine(dd).items()}
        if s_ in ("BAL", "OUT") and mine_w != w_x(dd):
            f.append(f"{dd.date()}: XM book lag differs from xm_lab.make_weights"); break
        if s_ == "DEF" and mine_w != w_xd(dd):
            f.append(f"{dd.date()}: XM Defense book lag differs from xm_lab.make_weights"); break
        if s_ == "OFF" and (w_mine(dd) != OFF_BOOK or w_o11(dd) != OFF_BOOK):
            f.append(f"{dd.date()}: OFF must hold the Offense book"); break
        if s_ == "DEF" and w_o11(dd) != avail(DEF_BOOK, dd, r):
            f.append(f"{dd.date()}: O11-R Defense book"); break
        if s_ in ("BAL", "OUT") and w_o11(dd) != avail(BAL_BOOK, dd, r):
            f.append(f"{dd.date()}: O11-R Balanced book"); break
    if not {"OFF", "BAL", "DEF"} <= seen_st:
        f.append(f"fixture: the lag checks must see OFF, BAL and DEF days ({seen_st})")
    if not {"OFF", "BAL", "DEF"} <= set(st[st.index >= "1965-01-01"]):
        f.append("fixture: engine states should vary")
    # judge / stats on a known NAV: +10% every calendar year, base = the prior year-end close
    yc = pd.bdate_range("1962-06-01", "1999-12-31")
    yc = yc[~((yc.month == 1) & (yc.day == 1))]                  # markets are shut on New Year's Day
    yrs_ = yc.year - 1962
    frac = np.array([(dd - pd.Timestamp(f"{dd.year - 1}-12-31")).days / 365.0 for dd in yc])
    nav10 = pd.Series(100 * 1.10 ** (yrs_ + frac - 0.5), index=yc)
    j10 = judge(nav10, nav10 * 0 + 100)
    yv = j10["years"]["book"]
    if yv.index[0] != 1963 or yv.index[-1] != 1999 or (yv - 10).abs().max() > 0.15:
        f.append(f"judge: calendar years must be 1963..1999 at +10% (got {yv.index[0]}..{yv.index[-1]}, max err {(yv - 10).abs().max():.3f})")
    if abs(j10["summ"]["full"]["cagr_pct"] - 10.0) > 0.1 or abs(j10["summ"]["1982-99"]["cagr_pct"] - 10.0) > 0.1:
        f.append(f"stats: full/half CAGR should be 10% ({j10['summ']['full']}, {j10['summ']['1982-99']})")
    w0 = window(nav10, "1963-01-02", "1963-12-31")
    if w0.index[0] != pd.Timestamp("1962-12-31"):
        f.append("window: the base must be the last close before the start")
    dropj = nav10.copy()
    dropj[(dropj.index >= "1974-01-01") & (dropj.index < "1975-01-01")] *= 0.5
    jd = judge(dropj, nav10)
    if abs(jd["summ"]["bear_1973"]["total_pct"]) < 1 or jd["down_years"] != 0:
        f.append("judge: windows / down-year counting")
    # data guards
    if check_returns(d):
        f.append(f"check_returns: the clean fixture must pass ({check_returns(d)})")
    d_bad = dict(d, rets=d["rets"].copy())
    d_bad["rets"].loc["1975-03-03":"1975-03-20", "SMALL"] = np.nan
    if not any("SMALL" in z for z in check_returns(d_bad)):
        f.append("check_returns: missing small-cap days must be caught")
    d_bad2 = dict(d, rets=d["rets"].copy())
    d_bad2["rets"].loc["1980-06-02":"1980-06-30", "MKT"] = np.nan
    try:
        st_b = ol.states_fast(d["levels"], d["eng_rets"], credit=True)
        days_b = d["cal"][d["cal"] >= pd.Timestamp(EVAL_START) - pd.Timedelta(days=10)]
        cov = hl.simulate(days_b, d_bad2["rets"], make_weights(st_b, d_bad2["rets"], "mkt"), None, breaker=False)["coverage"]
        if not (cov < 1).any():
            f.append("fixture: coverage should drop when MKT is missing")
        analyse(d_bad2)
        f.append("analyse: a held sleeve with no return must raise DataFailure")
    except DataFailure:
        pass
    # bars
    def fake(cf, c1, c2, dd, dyb=5, dy=5, losing=4):
        return {"summ": {"full": {"cagr_pct": cf, "max_dd_pct": dd}, "1963-81": {"cagr_pct": c1}, "1982-99": {"cagr_pct": c2}},
                "down_years_beaten": dyb, "down_years": dy, "losing_years": list(range(losing))}
    m = fake(10.0, 6.0, 17.0, -45.0)
    if engine_bar(fake(9.2, 7, 12, -20.0), m) or not engine_bar(fake(8.9, 7, 12, -20.0), m) or \
            not engine_bar(fake(9.5, 7, 12, -23.0), m) or not engine_bar(fake(9.5, 7, 12, -20.0, dyb=4), m):
        f.append("engine_bar logic")
    o = fake(9.0, 7.0, 11.0, -19.0)
    if xm_bar(fake(9.2, 7.0, 10.8, -19.5), o) or not xm_bar(fake(9.0, 7.0, 11.0, -19.0), o) or \
            not xm_bar(fake(9.2, 6.7, 11.0, -19.0), o) or not xm_bar(fake(9.2, 7.0, 11.0, -20.5), o) or \
            not xm_bar(fake(9.2, 7.0, 11.0, -19.0, losing=5), o):
        f.append("xm_bar logic")
    # analyse, writer, abort paths
    tmp = Path(tempfile.mkdtemp())
    try:
        a = analyse(d)
        if a["res"]["Market"]["summ"]["full"]["cagr_pct"] == a["res"]["O11-R"]["summ"]["full"]["cagr_pct"]:
            f.append("O11-R must differ from the market")
        chk = data_checks(ff3, {})
        md = write_outputs(a, chk, "2026-11-25", tmp / "d", tmp / "l")
        if "Engine" not in md or not (tmp / "d" / "summary.json").exists():
            f.append("writer: outputs incomplete")
        texts = {URLS["ff3"]: _zip(_french_text(ff3)), URLS["size"]: _zip(_french_text(size)),
                 URLS["dgs10"]: ("observation_date,DGS10\n" + "\n".join(f"{i.date()},{v:.2f}" for i, v in dgs10.items())).encode(),
                 URLS["gold"]: ("Date,Price\n" + "\n".join(f"{i.strftime('%Y-%m')},{v:.4f}" for i, v in gold.items())).encode()}
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc_ok = main(get=lambda u: texts[u], yahoo_fetch=lambda t, start=None: {})
                rc_bad = main(get=lambda u: (_ for _ in ()).throw(OSError("blocked")), pause=0)
                short = dict(texts); short[URLS["dgs10"]] = b"observation_date,DGS10\n1975-01-02,7.0\n"
                os.rename("data", "data_ok")
                rc_short = main(get=lambda u: short[u], yahoo_fetch=lambda t, start=None: {})
                g2 = dict(texts)
                g2[URLS["gold"]] = ("Date,Price\n" + "\n".join(f"{i.strftime('%Y-%m')},{v:.4f}" for i, v in gold.items()
                                                               if not ("1980-01" <= i.strftime('%Y-%m') <= "1980-10"))).encode()
                rc_gold = main(get=lambda u: g2[u], yahoo_fetch=lambda t, start=None: {})
                d2 = dict(texts)
                d2[URLS["dgs10"]] = ("observation_date,DGS10\n" + "\n".join(f"{i.date()},{v:.2f}" for i, v in dgs10.items()
                                                                         if i < pd.Timestamp("1985-01-01"))).encode()
                rc_d2 = main(get=lambda u: d2[u], yahoo_fetch=lambda t, start=None: {})
                f3 = dict(texts); f3[URLS["ff3"]] = _zip(_french_text(ff3[ff3.index < "1990-07-01"]))
                rc_f3 = main(get=lambda u: f3[u], yahoo_fetch=lambda t, start=None: {})
            # a source that times out twice then answers must still give a full run
            flaky = {"n": 0}

            def get_flaky(u):
                if u == URLS["gold"] and flaky["n"] < 2:
                    flaky["n"] += 1
                    raise TimeoutError("The read operation timed out")
                return texts[u]
            os.rename("data_ok", "data_keep")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_flaky = main(get=get_flaky, yahoo_fetch=lambda t, start=None: {}, pause=0)
            if rc_flaky != 0 or not (tmp / "data" / "oos_lab" / "summary.json").exists() or "gold: attempt 2 of 4" not in buf.getvalue():
                f.append("fetch_source: two timeouts then success must still run (and log the attempts)")
            import shutil
            shutil.rmtree(tmp / "data")
            os.rename("data_keep", "data_ok")
            # a source that never answers stops the run, names the source, writes nothing
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                rc_dead = main(get=lambda u: (_ for _ in ()).throw(TimeoutError("timed out")) if u == URLS["size"] else texts[u], pause=0)
            if rc_dead != 1 or "size (" not in buf2.getvalue() or (tmp / "data" / "oos_lab").exists():
                f.append("fetch_source: a dead source must stop the run and be named")
            if rc_ok != 0 or not (tmp / "data_ok" / "oos_lab" / "summary.json").exists():
                f.append("main: a clean run must write outputs")
            if rc_bad != 1 or rc_short != 1 or rc_gold != 1 or rc_d2 != 1 or rc_f3 != 1 or (tmp / "data" / "oos_lab").exists():
                f.append("main: blocked or short data must stop with nothing written")
        finally:
            os.chdir(cwd)
    except Exception as e:
        import traceback
        f.append(f"analyse/writer/main crashed: {type(e).__name__}: {e} {traceback.format_exc()[-400:]}")
    return {"ok": not f, "failures": f, "version": VERSION}


def _zip(text: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("data.CSV", text)
    return b.getvalue()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r_ = selftest()
        print(json.dumps(r_, indent=2, default=str))
        sys.exit(0 if r_["ok"] else 1)
    sys.exit(main())
