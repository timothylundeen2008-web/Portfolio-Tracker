"""
xm_lab.py  (v1.0 — 2026-11-24)
──────────────────────────────
LONG-TERM book only. Pre-registered test XM (claude/xm_lab_2026-11-24.md; strategy_plan_2026-11-24.md
item 1; Matt 2026-11-24: "Let's do it"). Bars are fixed BEFORE any run on real prices; a FAIL is final.

Matt's point (2026-11-24): "it is rare that everything falls at the same time. things like KMLM, SGOV,
USFR, etc etc need to be leveraged and the portfolio should be optimized based on market conditions."
O11 decides WHEN to be defensive from two funds' trends, then holds FIXED books (Defense 60 SGOV /
20 GLD / 20 TLT even with gold 20% below its 200-day). XM keeps O11's switching and replaces the
fixed Balanced and Defense books with a monthly cross-asset momentum ranking.

Rule (XM-N):
  * O11 states exactly as live (offense_lab.states_fast, credit=True). Offense = 50 QQQ / 50 SPY.
  * In every other state (Balanced, fast-exit OUT, Defense) the book is the latest month-end ranking:
      - universe: SPY, QQQ, IWM, EFA, EEM, TLT, IEF, TIPS, gold, commodities, the dollar, managed
        futures (DBMF/KMLM, AQMIX before them), cash (SGOV / BIL / T-bills);
      - score = mean of the 1-, 3-, 6- and 12-month total returns (21/63/126/252 sessions);
      - a sleeve is eligible only if its score beats cash's score (absolute momentum) and it has a
        full 252-session history (a sleeve with no data yet is NOT ranked; nothing is filled with cash);
      - hold the top N eligible, equal weight; empty slots go to SGOV;
      - in DEFENSE the equity sleeves (SPY, QQQ, IWM, EFA, EEM) are excluded;
      - ranked at each month-end close, traded with the same 1-session lag as the engine.
  N = 3 (decision). N = 2 and N = 4: stability neighbours.
  Reported, not a trial: XM-3 alone (no engine), and coverage by year.

Guard: the same weight function with the XM books switched off must reproduce O11's NAV exactly.

Run:  python xm_lab.py            (Actions; needs yfinance)
      python xm_lab.py --selftest (offline)
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

import hedge_lab as hl
import offense_lab as ol

VERSION = "1.0"
OUT_DIR, LOG_DIR = Path("data/xm_lab"), Path("logs/xm_lab")
N_DECISION, N_NEIGHBOURS = 3, (2, 4)
TRIALS_BEFORE, TRIALS_HERE = 40, 3
LOOKBACKS = (21, 63, 126, 252)
XM_CHAINS = {
    "SPY": ["SPY"], "QQQ": ["QQQ"], "IWM": ["IWM", "NAESX"], "EFA": ["EFA", "VGTSX"], "EEM": ["EEM", "VEIEX"],
    "TLT": ["TLT", "VUSTX"], "IEF": ["IEF", "VFITX"], "TIPS": ["SCHP", "TIP", "VIPSX"],
    "GLD": ["GLD", "GC=F"], "CMDTY": ["PDBC", "DBC", "GSG"], "USD": ["UUP", "DX-Y.NYB"],
    "MF": ["DBMF", "KMLM", "AQMIX"], "CASH": ["SGOV", "BIL", "^IRX"],
}
EQUITY = ("SPY", "QQQ", "IWM", "EFA", "EEM")
CASH = "CASH"
PFX = "X:"                                   # column prefix for XM sleeves in the simulation frame
BAR = {"half_16_26_tol": 0.25, "max_dd": -20.0, "lag_pts": 10.0}


def xm_tickers() -> list:
    return sorted({t for c in XM_CHAINS.values() for t in c})


def month_ends(cal: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(cal, index=cal)
    return pd.DatetimeIndex(s.groupby([cal.year, cal.month]).max().values)


def scores(xr: pd.DataFrame, i: int) -> dict:
    """Blended momentum at row i (data through that close). Sleeves without a full 252-session
    window are absent (not ranked)."""
    out = {}
    for s in xr.columns:
        tot = []
        for L in LOOKBACKS:
            w = xr[s].iloc[i - L + 1:i + 1] if i - L + 1 >= 0 else None
            if w is None or len(w) < L or w.isna().any():
                break
            tot.append(float(np.prod(1 + w.to_numpy()) - 1))
        if len(tot) == len(LOOKBACKS):
            out[s] = float(np.mean(tot))
    return out


def rank_book(sc: dict, n: int, exclude=()) -> dict:
    """Top n sleeves whose score beats cash's; equal weight; empty slots in cash. Weights sum to 100."""
    cash = sc.get(CASH)
    elig = [(v, s) for s, v in sc.items() if s != CASH and s not in exclude and cash is not None and v > cash]
    picks = [s for v, s in sorted(elig, reverse=True)[:n]]
    w = {PFX + s: 100.0 / n for s in picks}
    if len(picks) < n:
        w[PFX + CASH] = w.get(PFX + CASH, 0.0) + 100.0 / n * (n - len(picks))
    return w


def build_books(xr: pd.DataFrame, n: int) -> tuple:
    """{month_end: book} for all states (full) and for Defense (no equities), plus the scores."""
    pos = {d: i for i, d in enumerate(xr.index)}
    full, dfn, sc_all = {}, {}, {}
    for me in month_ends(xr.index):
        sc = scores(xr, pos[me])
        sc_all[me] = sc
        full[me] = rank_book(sc, n)
        dfn[me] = rank_book(sc, n, exclude=EQUITY)
    return full, dfn, sc_all


def make_weights(st: pd.Series, full: dict, dfn: dict, balanced: dict, mode: str) -> Callable:
    """weights_on(d), with O11's 1-session lag on the state and the same lag on the monthly ranking
    (the book used on d is the latest month-end STRICTLY before d).
    mode 'o11': the live books (guard). 'xm': Offense in OFF, XM otherwise. 'alone': XM always."""
    lagged = st.shift(ol.LAG)
    lagged.iloc[:ol.LAG] = st.iloc[0]
    sm = lagged.to_dict()
    mes = sorted(full)
    me_idx = pd.DatetimeIndex(mes)
    cash_book = {PFX + CASH: 100.0}

    def latest(books, d):
        k = me_idx.searchsorted(d, side="left") - 1
        return books[mes[k]] if k >= 0 else cash_book

    def w(d):
        s = sm[d]
        if mode == "o11":
            return dict(ol.book_for(s, ol.CANDIDATES["O11"], balanced))
        if mode == "alone":
            return dict(latest(full, d))
        if s == "OFF":
            return dict(ol.OFFENSE_1X)
        return dict(latest(dfn if s == "DEF" else full, d))
    return w


def judge(nav: pd.Series, spy_nav: pd.Series) -> dict:
    s = ol.summary(nav)
    both = pd.DataFrame({"book": ol.year_returns(nav), "spy": ol.year_returns(spy_nav)}).dropna()
    down, up = both[both.spy < 0], both[both.spy >= 0]
    return {"summ": s, "years": both,
            "down_years_beaten": int((down.book > down.spy).sum()), "down_years": int(len(down)),
            "up_lags_gt10": [int(d.year) for d, r in up.iterrows() if r.book - r.spy < -BAR["lag_pts"]],
            "losing_years": [int(d.year) for d, r in both.iterrows() if r.book < 0]}


def bar(c: dict, base: dict, full_bar: bool = True) -> list:
    why = []
    s, b = c["summ"], base["summ"]
    g = lambda x, h, f: x.get(h, {}).get(f)

    def ge(h, f, tol):
        a_, b_ = g(s, h, f), g(b, h, f)
        return a_ is not None and b_ is not None and a_ >= b_ + tol - 1e-9

    if not ge("full", "cagr_pct", 0.01):
        why.append(f"full CAGR {g(s, 'full', 'cagr_pct')}% not above O11 {g(b, 'full', 'cagr_pct')}%")
    if not ge("2005-15", "cagr_pct", 0.0):
        why.append(f"2005-15 CAGR {g(s, '2005-15', 'cagr_pct')}% below O11 {g(b, '2005-15', 'cagr_pct')}%")
    if not ge("2016-26", "cagr_pct", -BAR["half_16_26_tol"]):
        why.append(f"2016-26 CAGR {g(s, '2016-26', 'cagr_pct')}% < O11 {g(b, '2016-26', 'cagr_pct')}% − {BAR['half_16_26_tol']}")
    dd = g(s, "full", "max_dd_pct")
    if dd is None or not dd > BAR["max_dd"]:
        why.append(f"max DD {dd}% deeper than {BAR['max_dd']}%")
    if full_bar:
        if c["down_years_beaten"] < c["down_years"]:
            why.append(f"beat SPY in {c['down_years_beaten']} of {c['down_years']} down years (needs all)")
        if len(c["up_lags_gt10"]) > len(base["up_lags_gt10"]):
            why.append(f"{len(c['up_lags_gt10'])} up years trailing SPY by >10 pts vs O11's {len(base['up_lags_gt10'])}")
        if len(c["losing_years"]) > len(base["losing_years"]):
            why.append(f"{len(c['losing_years'])} losing years vs O11's {len(base['losing_years'])}")
    return why


def holdings_share(sim: pd.DataFrame, st: pd.Series) -> dict:
    """Average weight per XM sleeve on non-Offense days (what XM actually held)."""
    lag = st.shift(ol.LAG).reindex(sim.index)
    rows = [w for d, w in sim["w"].items() if lag.get(d) not in ("OFF", None)]
    if not rows:
        return {}
    df = pd.DataFrame(rows).fillna(0.0)
    m = df.mean().sort_values(ascending=False)
    return {k.replace(PFX, ""): round(float(v), 1) for k, v in m.items() if v >= 0.5}


def analyse(data: dict, xr: pd.DataFrame, balanced: dict) -> dict:
    st = ol.states_fast(data["levels"], data["rets"], credit=True)
    rets = data["rets"].copy()
    for s in xr.columns:
        rets[PFX + s] = xr[s].reindex(rets.index)
    days = data["cal"][data["cal"] >= pd.Timestamp(ol.EVAL_START) - pd.Timedelta(days=10)]
    o11 = ol.run_candidate("O11", data, balanced)
    sim = lambda wf: hl.simulate(days, rets, wf, None, breaker=False, cost_bps=ol.COST_BPS)
    full3, dfn3, sc3 = build_books(xr, N_DECISION)
    g = sim(make_weights(st, full3, dfn3, balanced, "o11"))
    nav_gap = float((g["nav"] / o11["nav"] - 1).abs().max())
    guard = nav_gap < 1e-9
    spy_nav = (1 + data["rets"]["SPY"].reindex(o11["nav"].index).fillna(0.0)).cumprod()
    base = judge(o11["nav"], spy_nav)
    res = {"O11": {**base, "nav": o11["nav"]}}
    sims = {}
    for n in (N_DECISION, *N_NEIGHBOURS):
        full, dfn, _sc = (full3, dfn3, sc3) if n == N_DECISION else build_books(xr, n)
        sims[n] = sim(make_weights(st, full, dfn, balanced, "xm"))
        res[f"XM{n}"] = {**judge(sims[n]["nav"], spy_nav), "nav": sims[n]["nav"],
                         "held": holdings_share(sims[n], st),
                         "turnover_pct_yr": round(float(sims[n]["turnover"].sum()) / max(1, len(sims[n]) / 252), 1)}
    alone = sim(make_weights(st, full3, dfn3, balanced, "alone"))
    res["XM3 alone"] = {**judge(alone["nav"], spy_nav), "nav": alone["nav"], "held": {}, "turnover_pct_yr": None}
    dec = res[f"XM{N_DECISION}"]
    why = bar(dec, base)
    nb = {f"XM{n}": bar(res[f"XM{n}"], base, full_bar=False) for n in N_NEIGHBOURS}
    stable = all(not v for v in nb.values())
    verdict = "FAIL" if why else ("PASS (stable)" if stable else "PASS (not stable)")
    # coverage: rankable sleeves at each year's first month-end
    cov = {}
    for me, sc in sorted(sc3.items()):
        if me.year not in cov and me >= pd.Timestamp(ol.EVAL_START):
            cov[me.year] = sorted(sc)
    latest_me = max(sc3)
    return {"version": VERSION, "verdict": verdict, "fails": why, "neighbours": nb, "stable": stable,
            "guard": {"ok": bool(guard), "nav_gap": nav_gap}, "res": res, "spy": ol.summary(spy_nav),
            "coverage": cov, "latest": {"month_end": latest_me.date().isoformat(),
                                        "scores": {k: round(v * 100, 2) for k, v in sorted(sc3[latest_me].items(), key=lambda kv: -kv[1])},
                                        "book": {k.replace(PFX, ""): round(v, 1) for k, v in full3[latest_me].items()},
                                        "defense_book": {k.replace(PFX, ""): round(v, 1) for k, v in dfn3[latest_me].items()}}}


def _c(x):
    return "—" if x is None else f"{x:.2f}%"


def render(a: dict, stamp: str) -> str:
    res = a["res"]
    cols = ["O11", f"XM{N_DECISION}", *[f"XM{n}" for n in N_NEIGHBOURS], "XM3 alone"]
    L = [f"# XM lab {VERSION} — cross-asset momentum in place of the fixed Balanced/Defense books — {stamp}", "",
         f"Pre-registered in `claude/xm_lab_2026-11-24.md`. Long-term engine trials {TRIALS_BEFORE} → "
         f"{TRIALS_BEFORE + TRIALS_HERE}. Research, not personalized advice.", "",
         f"## XM (N = {N_DECISION}) inside O11: **{a['verdict']}**", "",
         f"- Fails: {'; '.join(a['fails']) or 'none'}",
         "- Neighbours (bars 1–4): " + "; ".join(f"{k}: {'meets' if not v else '; '.join(v)}" for k, v in a["neighbours"].items()),
         f"- Guard (XM off reproduces O11 exactly): {'yes' if a['guard']['ok'] else '**NO — result not valid**'} "
         f"(NAV gap {a['guard']['nav_gap']:.1e})", "",
         "| | " + " | ".join(cols) + " | SPY |", "|---" * (len(cols) + 2) + "|"]
    for h in ("full", "2005-15", "2016-26"):
        L.append(f"| CAGR {h} | " + " | ".join(_c(res[c]["summ"][h].get("cagr_pct")) for c in cols) +
                 f" | {_c(a['spy'][h].get('cagr_pct'))} |")
    L.append("| Max DD | " + " | ".join(_c(res[c]["summ"]["full"].get("max_dd_pct")) for c in cols) +
             f" | {_c(a['spy']['full'].get('max_dd_pct'))} |")
    for k, lab in (("dotcom_2000", "2000–02"), ("gfc_2008", "2007–09"), ("covid_2020", "Covid 2020"), ("rates_2022", "2022")):
        L.append(f"| {lab} | " + " | ".join(_c(res[c]["summ"].get(k, {}).get("total_pct")) for c in cols) +
                 f" | {_c(a['spy'].get(k, {}).get('total_pct'))} |")
    L.append("| Down years beaten | " + " | ".join(f"{res[c]['down_years_beaten']} of {res[c]['down_years']}" for c in cols) + " | — |")
    L.append("| Up years >10 pts behind | " + " | ".join(", ".join(map(str, res[c]["up_lags_gt10"])) or "none" for c in cols) + " | — |")
    L.append("| Losing years | " + " | ".join(", ".join(map(str, res[c]["losing_years"])) or "none" for c in cols) + " | — |")
    k = f"XM{N_DECISION}"
    L += ["", f"**What XM{N_DECISION} held when not in Offense (average %):** " +
          ", ".join(f"{s} {v}" for s, v in res[k]["held"].items()),
          f"**Turnover:** {res[k]['turnover_pct_yr']}% of the book a year (one-way)."]
    yb, yk = res["O11"]["years"], res[k]["years"]
    diff = (yk["book"] - yb["book"]).round(1)
    L += ["", "**Years vs O11 (points):** " + ", ".join(f"{d.year} {v:+.1f}" for d, v in diff.items() if abs(v) >= 0.1)]
    first = {}
    for y, ss in a["coverage"].items():
        for s in ss:
            first.setdefault(s, y)
    missing = [s for s in XM_CHAINS if s not in first]
    L += ["", "**Coverage (first year each sleeve could be ranked):** " +
          ", ".join(f"{s} {y}" for s, y in sorted(first.items(), key=lambda kv: kv[1])) +
          (f"; never: {', '.join(missing)}" if missing else "")]
    lt = a["latest"]
    L += ["", f"**Latest ranking ({lt['month_end']}):** scores % " +
          ", ".join(f"{s} {v:+.1f}" for s, v in lt["scores"].items()),
          f"- XM{N_DECISION} book: " + ", ".join(f"{s} {v}" for s, v in lt["book"].items()) +
          " · Defense version: " + ", ".join(f"{s} {v}" for s, v in lt["defense_book"].items()),
          "", f"*xm_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def write_outputs(a: dict, stamp: str, out_dir: Path = OUT_DIR, log_dir: Path = LOG_DIR) -> str:
    md = render(a, stamp)
    navs = pd.DataFrame({k: v["nav"] for k, v in a["res"].items()})
    years = pd.DataFrame({k: v["years"]["book"] for k, v in a["res"].items()})
    years["SPY"] = a["res"]["O11"]["years"]["spy"]
    js = {"version": VERSION, "asof": stamp, "verdict": a["verdict"], "fails": a["fails"], "neighbours": a["neighbours"],
          "stable": a["stable"], "guard": a["guard"], "trials": TRIALS_BEFORE + TRIALS_HERE, "spy": a["spy"],
          "coverage": {str(k): v for k, v in a["coverage"].items()}, "latest": a["latest"],
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


def main(fetch=None) -> int:
    stamp = date.today().isoformat()
    tickers = sorted(set(hl.all_tickers()) | set(ol.EXTRA_TICKERS) | set(xm_tickers()))
    closes = (fetch or hl.yf_fetch)(tickers, start=ol.HISTORY_START)
    missing = [t for t in ("SPY", "QQQ", "^IRX", *ol.CREDIT_PAIR) if t not in closes]
    print(f"[xm_lab] {VERSION}: {len(closes)} of {len(tickers)} tickers; required missing: {missing}")
    gone = [t for t in xm_tickers() if t not in closes]
    if gone:
        print(f"[xm_lab] note: no prices for {', '.join(gone)} (their sleeves use the next ticker in the chain)")
    if missing:
        print("[xm_lab] DATA FAILURE: a signal input is missing; nothing written.")
        return 1
    import regime_classifier as rc
    balanced = {k: float(v) for k, v in rc.target_weights(hl.REGIME, gate=False).items()}
    data = ol.build_data(closes)
    xr, _src = hl.splice(closes, XM_CHAINS, data["cal"])
    a = analyse(data, xr, balanced)
    if not a["guard"]["ok"]:
        print("[xm_lab] GUARD FAILED: XM off does not reproduce O11; nothing written.")
        return 1
    print(write_outputs(a, stamp))
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _fixture():
    closes = ol._synthetic(n=3400)
    cal = closes["SPY"].index
    rng = np.random.default_rng(11)
    n = len(cal)
    for t in xm_tickers():
        if t not in closes and t != "^IRX":
            closes[t] = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0001, 0.007, n))), index=cal)
    closes["DBMF"] = closes["DBMF"].iloc[1500:]            # managed futures: no data for the first 1,500 sessions
    closes.pop("KMLM", None)
    closes.pop("AQMIX", None)
    return closes


def selftest() -> dict:
    import contextlib, io, os, tempfile
    f = []
    closes = _fixture()
    data = ol.build_data(closes)
    xr, _src = hl.splice(closes, XM_CHAINS, data["cal"])
    balanced = {"SGOV": 40.0, "TLT": 30.0, "GLD": 30.0}
    st = ol.states_fast(data["levels"], data["rets"], credit=True)
    full, dfn, sc = build_books(xr, 3)
    # books: sum 100, at most N risk sleeves, every pick beats cash, Defense has no equity
    for me in list(full)[300 // 21:]:
        for bk, ex in ((full[me], ()), (dfn[me], EQUITY)):
            if abs(sum(bk.values()) - 100) > 1e-9:
                f.append(f"book {me.date()} sums to {sum(bk.values())}"); break
            picks = [k.replace(PFX, "") for k in bk if k != PFX + CASH]
            if len(picks) > 3 or any(sc[me][p] <= sc[me][CASH] for p in picks) or any(p in ex for p in picks):
                f.append(f"book {me.date()} breaks the rules: {bk}"); break
    if not any(len(b) > 1 for b in full.values()):
        f.append("fixture: XM should pick risk sleeves sometimes")
    # an unavailable sleeve is never ranked (MF before its data has 252 sessions)
    mf_start = closes["DBMF"].index[0]
    early = [me for me in sc if me < mf_start + pd.Timedelta(days=360)]
    if any("MF" in sc[me] for me in early):
        f.append("a sleeve without a full 252-session history was ranked")
    if not any("MF" in sc[me] for me in sc):
        f.append("fixture: MF should become rankable")
    # scores match a direct calculation
    me = list(sc)[-1]
    i = list(xr.index).index(me)
    want = np.mean([np.prod(1 + xr["SPY"].iloc[i - L + 1:i + 1].to_numpy()) - 1 for L in LOOKBACKS])
    if abs(sc[me]["SPY"] - want) > 1e-12:
        f.append("score must be the mean of the 1/3/6/12-month returns through the month-end close")
    # rank_book cases
    rb = rank_book({"A": 0.10, "B": 0.05, "C": 0.02, "D": 0.20, "CASH": 0.03}, 3, exclude=("D",))
    if rb != {PFX + "A": 100 / 3, PFX + "B": 100 / 3, PFX + "CASH": 100 / 3}:
        f.append(f"rank_book: excluded / below-cash handling {rb}")
    if rank_book({"A": -0.1, "CASH": 0.01}, 3) != {PFX + "CASH": 100.0}:
        f.append("rank_book: nothing beats cash -> all cash")
    # weights: monthly book changes only on the first session after a month-end; lag 1 on the state
    w = make_weights(st, full, dfn, balanced, "alone")
    days = data["cal"][300:]
    mes = set(full)
    prev = None
    for d_prev, d in zip(days[:-1], days[1:]):
        cur = w(d)
        if prev is not None and cur != prev and d_prev not in mes:
            f.append(f"XM book changed on {d.date()} without a month-end on the previous session"); break
        prev = cur
    me0 = sorted(mes)[20]
    nxt = data["cal"][data["cal"] > me0][0]
    if w(me0) == full[me0] and full[me0] != w(data["cal"][data["cal"] < me0][-1]):
        f.append("the month-end's own book must not be held on the month-end itself")
    if w(nxt) != full[me0]:
        f.append("the book from a month-end must be held from the next session")
    wx = make_weights(st, full, dfn, balanced, "xm")
    lag = st.shift(1)
    for d in days[::7]:
        s = lag[d]
        got = wx(d)
        if s == "OFF" and got != ol.OFFENSE_1X:
            f.append(f"{d.date()}: OFF must hold the Offense book"); break
        if s == "DEF" and any(k.replace(PFX, "") in EQUITY for k in got):
            f.append(f"{d.date()}: Defense held equities {got}"); break
        if s in ("BAL", "OUT") and not all(k.startswith(PFX) for k in got):
            f.append(f"{d.date()}: {s} must hold the XM book, got {got}"); break
    if not {"BAL", "OUT", "DEF", "OFF"} <= set(lag.dropna().iloc[300:]):
        f.append("fixture: all four states should occur")
    # guard + analyse on the fixture
    tmp = Path(tempfile.mkdtemp())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            a = analyse(data, xr, balanced)
        if not a["guard"]["ok"]:
            f.append(f"guard must hold on the fixture {a['guard']}")
        if a["res"]["XM3"]["summ"]["full"]["cagr_pct"] == a["res"]["O11"]["summ"]["full"]["cagr_pct"]:
            f.append("XM must differ from O11 on the fixture")
        md = write_outputs(a, "2026-11-24", tmp / "d", tmp / "l")
        js = json.loads((tmp / "d" / "summary.json").read_text())
        if js["verdict"] not in ("FAIL", "PASS (stable)", "PASS (not stable)") or "XM" not in md:
            f.append("writer: outputs incomplete")
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc_ = main(fetch=lambda tks, start=None: {})
            if rc_ != 1 or (tmp / "data" / "xm_lab").exists():
                f.append("main: missing data must stop with nothing written")
        finally:
            os.chdir(cwd)
    except Exception as e:
        import traceback
        f.append(f"analyse/writer crashed: {type(e).__name__}: {e} {traceback.format_exc()[-400:]}")
    # bar logic
    def fake(c05, cf, c16, dd, dyb=6, lags=3, losing=6):
        return {"summ": {"full": {"cagr_pct": cf, "max_dd_pct": dd}, "2005-15": {"cagr_pct": c05}, "2016-26": {"cagr_pct": c16}},
                "down_years_beaten": dyb, "down_years": 6, "up_lags_gt10": list(range(lags)), "losing_years": list(range(losing))}
    o = fake(5.38, 9.35, 14.36, -19.3)
    if bar(fake(5.5, 9.6, 14.2, -19.0), o):
        f.append("bar: a clean pass must pass")
    for bad, why in ((fake(5.3, 9.6, 14.4, -19.0), "05-15"), (fake(5.5, 9.35, 14.4, -19.0), "full not above"),
                     (fake(5.5, 9.6, 14.1, -19.0), "16-26"), (fake(5.5, 9.6, 14.4, -20.1), "DD"),
                     (fake(5.5, 9.6, 14.4, -19.0, dyb=5), "down year"), (fake(5.5, 9.6, 14.4, -19.0, lags=4), "lags"),
                     (fake(5.5, 9.6, 14.4, -19.0, losing=7), "losing years")):
        if not bar(bad, o):
            f.append(f"bar must fail: {why}")
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r_ = selftest()
        print(json.dumps(r_, indent=2, default=str))
        sys.exit(0 if r_["ok"] else 1)
    sys.exit(main())
