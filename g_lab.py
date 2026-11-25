"""
g_lab.py  (v1.0 — 2026-11-25)
─────────────────────────────
LONG-TERM book only. "Graduated Defense", pre-registered in claude/g_lab_2026-11-25.md before any run.
Matt 2026-11-25: when the market goes sideways the engine struggles to keep up — sharpen that response.

Diagnosis: O11's short Defense spells (<= 40 sessions) cost ~81 log pts vs the market in 1963–99 and
~88 in 2000–26; long bear spells earned back ~81 / ~85. Any 2 closes below the 200-day send the whole
book to Defense, however shallow the dip.

Rule G-b: O11 unchanged except —
  * 2 consecutive closes at least b% below SPY's 200-day -> Defense (from any state), as today;
  * 2 closes below the 200-day but NOT 2 closes b% below it -> Offense steps down to Balanced;
    OUT keeps its state and cooldown; Balanced and Defense keep theirs.
  b = 0 reproduces O11 exactly (guard, same code path).
Candidates (long-term trials 47 -> 50): G3 (decision), G2, G4 (neighbours).

Windows: H 1928–62 hold-out (Ken French daily market + T-bills; Offense = market, Balanced = 50/50
market/cash, Defense = cash) DECIDES. R 1963–99 (oos_lab data and books) and L 2000–26 (offense_lab
data, credit, live Balanced book) are guards. Any data failure aborts with nothing written.

v1.0.1 (independent review, before any real run): L aborts on a held sleeve with no return (from
2000-09, after gold's first data); spell table attributes days with the simulator's lag (state at d-2);
H checks for missing dates and the end date; strict JSON; report notes (no credit series in H/R; windows
measured from the previous close, so L differs from offense_lab's tables by one day); new tests for the
OUT cooldown and the weight lag.

v1.0.2 (first real run stopped on a data check; nothing written): L's coverage rule now separates a
sleeve that did not EXIST yet (PDBC's commodity chain starts 2006, gold 2000-08: known, labelled, carried
by every O11 result alike, reported) from a HOLE in data that exists (> 3 sessions: abort). Every fund the
books hold today must download (3 attempts); a missing one (e.g. DBMF, which would otherwise fall back
silently to its proxy) aborts.

Run:  python g_lab.py            (Actions; FRED_API_KEY secret)
      python g_lab.py --selftest (offline)
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

import hedge_lab as hl
import offense_lab as ol
import oos_lab as oos

VERSION = "1.0.2"
OUT_DIR, LOG_DIR = Path("data/g_lab"), Path("logs/g_lab")
TRIALS_BEFORE, TRIALS_HERE = 47, 3
BAND_DECISION, BAND_NEIGHBOURS = 3.0, (2.0, 4.0)
H_START, H_END = "1928-01-03", "1962-12-31"
H_WINDOWS = [("crash_1929", "1929-09-03", "1932-06-01", "1929–32"), ("bear_1937", "1937-03-06", "1938-03-31", "1937–38"),
             ("war_1940", "1940-01-02", "1942-04-28", "1940–42"), ("bear_1946", "1946-05-29", "1947-05-19", "1946–47"),
             ("chop_1953", "1953-01-02", "1953-12-31", "1953"), ("bear_1957", "1957-07-15", "1957-10-22", "1957"),
             ("crash_1962", "1962-03-15", "1962-06-26", "1962")]
H_BOOKS = {"OFF": {"MKT": 100.0}, "BAL": {"MKT": 50.0, "CASH": 50.0}, "DEF": {"CASH": 100.0}}


def h_book(state: str) -> dict:
    """Hold-out books: OUT (fast exit) holds Balanced, as O11 does (out = "BAL")."""
    return dict(H_BOOKS["DEF" if state == "DEF" else ("OFF" if state == "OFF" else "BAL")])
BAR = {"h_cagr_gain": 0.25, "h_dd_tol": 2.0, "guard_cagr_tol": 0.25, "max_dd": -20.0, "stress_tol": 3.0}
MAX_HOLE = 3                     # sessions: a longer run of missing returns in a sleeve that exists aborts L
FETCH_TRIES = 3
LEN_BUCKETS = [0, 20, 40, 80, 10 ** 6]
LEN_LABELS = ["≤20", "21–40", "41–80", ">80"]


# ── the rule ────────────────────────────────────────────────────────────────

def deep_below(level: pd.Series, n: int, band_pct: float) -> pd.Series:
    """True when the close is at least band% below its n-day average; NaN until n bars (like above_ma)."""
    ma = level.rolling(n, min_periods=n).mean()
    out = ~(level > ma * (1 - band_pct / 100.0))
    return out.where(ma.notna())


def states_g(levels: pd.DataFrame, rets: pd.DataFrame, band_pct: float, ma: int = ol.MA,
             fast_sma: int = ol.FAST_SMA, fast_stop: float = ol.FAST_STOP, cooldown: int = ol.COOLDOWN,
             credit: bool = False) -> pd.Series:
    """offense_lab.states_fast with the graduated Defense trigger. Value at d uses data <= d only."""
    spy_up, qqq_up = ol.above_ma(levels["SPY"], ma), ol.above_ma(levels["QQQ"], ma)
    q50 = ol.above_ma(levels["QQQ"], fast_sma)
    known = spy_up.notna() & qqq_up.notna() & q50.notna()
    spy_dn2, qqq_dn2, q50_dn2 = ol._two_down(spy_up).to_numpy(), ol._two_down(qqq_up).to_numpy(), ol._two_down(q50).to_numpy()
    deep = deep_below(levels["SPY"], ma, band_pct)
    deep2 = (deep.fillna(False).astype(bool) & deep.shift(1).fillna(False).astype(bool) & deep.notna()).to_numpy()
    entry = (ol._two_up(spy_up) & ol._two_up(qqq_up) & ol._two_up(q50)).to_numpy()
    spy_up2 = ol._two_up(spy_up).to_numpy()
    if credit:
        c_up = ol.above_ma(levels["CREDIT"], ol.CREDIT_SMA) if "CREDIT" in levels else pd.Series(np.nan, index=levels.index)
        c_ok = (ol._two_down(c_up) | c_up.isna()).to_numpy()
    else:
        c_ok = np.ones(len(levels), dtype=bool)
    r = rets.reindex(levels.index)
    idx = (1 + 0.5 * r["SPY"].fillna(0.0) + 0.5 * r["QQQ"].fillna(0.0)).cumprod().to_numpy()
    out, state, peak, out_i = [], "BAL", None, -10 ** 9
    kn = known.to_numpy()
    for i in range(len(levels)):
        if not kn[i]:
            out.append(state); continue
        if spy_dn2[i] and deep2[i]:
            state = "DEF"
        elif spy_dn2[i]:                      # shallow: Offense steps down; others keep their state
            if state == "OFF":
                state = "BAL"
        elif state == "OFF":
            peak = max(peak, idx[i])
            if (q50_dn2[i] and c_ok[i]) or (idx[i] / peak - 1) * 100 <= fast_stop:
                state, out_i = "OUT", i
            elif qqq_dn2[i]:
                state = "BAL"
        elif entry[i] and (state != "OUT" or i - out_i >= cooldown):
            state, peak = "OFF", idx[i]
        elif state == "DEF" and spy_up2[i]:
            state = "BAL"
        out.append(state)
    return pd.Series(out, index=levels.index, dtype=object)


# ── generic statistics ──────────────────────────────────────────────────────

def stats(nav: pd.Series, a: str, b: Optional[str]) -> dict:
    return oos.stats(nav, a, b)


def years(nav: pd.Series, a: str, b: str) -> pd.Series:
    s = oos.window(nav, a, b)
    ye = s.groupby(s.index.year).last()
    out = ye.pct_change() * 100
    return out[(out.index >= pd.Timestamp(a).year) & (out.index <= pd.Timestamp(b).year)].dropna()


def judge(nav: pd.Series, mkt: pd.Series, a: str, b: str, windows: list) -> dict:
    yb, ym = years(nav, a, b), years(mkt, a, b)
    both = pd.DataFrame({"book": yb, "mkt": ym}).dropna()
    down, up = both[both.mkt < 0], both[both.mkt >= 0]
    return {"full": stats(nav, a, b), **{k: stats(nav, s, e) for k, s, e, _ in windows},
            "down_beaten": int((down.book > down.mkt).sum()), "down_years": int(len(down)),
            "up_lags": int((up.book - up.mkt < -10).sum()), "losing": int((both.book < 0).sum()),
            "years": both}


def spell_edges(st: pd.Series, nav: pd.Series, mkt: pd.Series, a: str, b: str) -> pd.DataFrame:
    """Edge vs the market (log pts) of each non-Offense spell, by state and length. Day d's return is earned
    on the weights set at d-1, which come from the state at d-2 (hedge_lab.simulate + the 1-session lag)."""
    d = pd.DataFrame({"st": st.shift(ol.LAG + 1), "m": mkt.pct_change(), "o": nav.pct_change()})
    d = d[(d.index >= pd.Timestamp(a)) & (d.index <= pd.Timestamp(b))].dropna()
    d["grp"] = (d.st != d.st.shift()).cumsum()
    sp = d.groupby("grp").agg(st=("st", "first"), n=("m", "size"),
                              m=("m", lambda x: float(np.log1p(x).sum() * 100)), o=("o", lambda x: float(np.log1p(x).sum() * 100)))
    sp = sp[sp.st != "OFF"].copy()
    sp["edge"] = sp.o - sp.m
    sp["len"] = pd.cut(sp.n, LEN_BUCKETS, labels=LEN_LABELS)
    g = sp.groupby(["st", "len"], observed=True).agg(spells=("n", "size"), edge=("edge", "sum")).reset_index()
    g["edge"] = g["edge"].round(1)
    return g


# ── windows ─────────────────────────────────────────────────────────────────

def _lag_weights(st: pd.Series, book_of: Callable) -> Callable:
    lagged = st.shift(ol.LAG)
    lagged.iloc[:ol.LAG] = st.iloc[0]
    m = lagged.to_dict()
    return lambda d: dict(book_of(m[d], d))


def run_H(ff3: pd.DataFrame, bands: tuple) -> dict:
    cal = ff3.index[ff3.index <= pd.Timestamp(H_END)]
    mkt = (ff3["Mkt-RF"].reindex(cal) + ff3["RF"].reindex(cal)) / 100.0
    rets = pd.DataFrame({"MKT": mkt, "CASH": ff3["RF"].reindex(cal) / 100.0}, index=cal)
    lvl = (1 + mkt.fillna(0.0)).cumprod()
    levels, eng = pd.DataFrame({"SPY": lvl, "QQQ": lvl}), pd.DataFrame({"SPY": mkt, "QQQ": mkt})
    days = cal[cal >= pd.Timestamp(H_START) - pd.Timedelta(days=10)]

    def sim(st):
        out = hl.simulate(days, rets, _lag_weights(st, lambda s, d: h_book(s)),
                          None, breaker=False, cost_bps=ol.COST_BPS)
        short = out.index[(out["coverage"] < 1 - 1e-12) & (out.index >= pd.Timestamp(H_START))]
        if len(short):
            raise oos.DataFailure(f"H: a held sleeve had no return on {len(short)} days (first {short[0].date()})")
        return out["nav"]
    mk = hl.simulate(days, rets, lambda d: {"MKT": 100.0}, None, breaker=False, cost_bps=ol.COST_BPS)["nav"]
    res = {"Market": {"nav": mk}}
    st0 = ol.states_fast(levels, eng, credit=True)
    res["O11"] = {"nav": sim(st0), "st": st0}
    for b in (0.0, BAND_DECISION, *BAND_NEIGHBOURS):
        st = states_g(levels, eng, b, credit=True)
        res[f"G{b:g}"] = {"nav": sim(st), "st": st}
    return {"res": res, "mkt": mk, "a": H_START, "b": H_END, "windows": H_WINDOWS}


def run_R(d: dict, bands: tuple) -> dict:
    st0 = ol.states_fast(d["levels"], d["eng_rets"], credit=True)
    days = d["cal"][d["cal"] >= pd.Timestamp(oos.EVAL_START) - pd.Timedelta(days=10)]

    def sim(st):
        out = hl.simulate(days, d["rets"], oos.make_weights(st, d["rets"], "o11"), None, breaker=False, cost_bps=ol.COST_BPS)
        short = out.index[(out["coverage"] < 1 - 1e-12) & (out.index >= pd.Timestamp(oos.EVAL_START))]
        if len(short):
            raise oos.DataFailure(f"R: a held sleeve had no return on {len(short)} days (first {short[0].date()})")
        return out["nav"]
    mk = sim_market = hl.simulate(days, d["rets"], oos.make_weights(st0, d["rets"], "mkt"), None, breaker=False,
                                  cost_bps=ol.COST_BPS)["nav"]
    res = {"Market": {"nav": sim_market}, "O11": {"nav": sim(st0), "st": st0}}
    for b in (0.0, BAND_DECISION, *BAND_NEIGHBOURS):
        st = states_g(d["levels"], d["eng_rets"], b, credit=True)
        res[f"G{b:g}"] = {"nav": sim(st), "st": st}
    return {"res": res, "mkt": mk, "a": oos.EVAL_START, "b": oos.EVAL_END, "windows": oos.WINDOWS}


def run_L(data: dict, balanced: dict, bands: tuple) -> dict:
    cand = ol.CANDIDATES["O11"]
    days = data["cal"][data["cal"] >= pd.Timestamp(ol.EVAL_START) - pd.Timedelta(days=10)]
    o = ol.run_candidate("O11", data, balanced)
    mk = ol.simulate(days, data["rets"], lambda d: {"SPY": 100.0}, 0.0)
    res = {"Market": {"nav": mk}, "O11": {"nav": o["nav"], "st": o["states"]}}
    for b in (0.0, BAND_DECISION, *BAND_NEIGHBOURS):
        st = states_g(data["levels"], data["rets"], b, credit=True)
        sim = hl.simulate(days, data["rets"], ol.weights_fn(st, cand, balanced), None, breaker=False, cost_bps=ol.COST_BPS)
        res[f"G{b:g}"] = {"nav": sim["nav"], "st": st}
    end = str(data["cal"][-1].date())
    return {"res": res, "mkt": mk, "a": ol.EVAL_START, "b": end, "windows": ol.STRESS,
            "not_yet": not_yet_existing(data["rets"], book_sleeves(balanced), days[0])}


def book_sleeves(balanced: dict) -> dict:
    """Every sleeve any 2000–26 O11 book can hold, with its largest weight."""
    w: dict = {}
    for book in (balanced, ol.DEFENSE, ol.OFFENSE_1X):
        for k, v in book.items():
            w[k] = max(w.get(k, 0.0), float(v))
    return w


def not_yet_existing(rets: pd.DataFrame, sleeves: dict, start) -> list:
    """Sleeves whose whole proxy chain starts after `start` (they earn 0% until then, as in offense_lab)."""
    out = []
    for k, w in sleeves.items():
        s = rets[k] if k in rets else pd.Series(dtype=float)
        first = s.first_valid_index()
        if first is None or first > pd.Timestamp(start) + pd.Timedelta(days=7):
            out.append({"sleeve": k, "weight": w, "from": None if first is None else str(first.date())})
    return out


def check_L(data: dict, balanced: dict, closes: dict) -> list:
    """Abort reasons for the 2000–26 window: a fund the books hold today did not download, or a sleeve that
    already exists has a run of more than MAX_HOLE sessions with no return."""
    bad = []
    sleeves = book_sleeves(balanced)
    chains = ol.CHAINS
    natives = sorted({chains.get(k, [k])[0] for k in sleeves} - {"^IRX"})
    miss = [t for t in natives if t not in closes]
    if miss:
        bad.append(f"2000–26 funds held today did not download: {', '.join(miss)} (a proxy would stand in silently)")
    rets = data["rets"]
    lo = pd.Timestamp(ol.EVAL_START) - pd.Timedelta(days=10)
    for k in sleeves:
        if k not in rets:
            bad.append(f"2000–26 sleeve {k} has no return series")
            continue
        s = rets[k][rets.index >= lo]
        first = s.first_valid_index()
        if first is None:
            bad.append(f"2000–26 sleeve {k} has no data at all")
            continue
        na = s[s.index >= first].isna()
        if na.any():
            run = na.groupby((~na).cumsum()).sum().max()
            if run > MAX_HOLE:
                bad.append(f"2000–26 sleeve {k} is missing {int(run)} sessions in a row after its data starts ({str(first.date())})")
    return bad


# ── bars ────────────────────────────────────────────────────────────────────

def guard_ok(w: dict) -> float:
    """Max |NAV gap| between G0 and O11 over the window (must be 0)."""
    a, b = w["res"]["G0"]["nav"], w["res"]["O11"]["nav"]
    return float((a - b).abs().max())


def h_bar(g: dict, o: dict) -> list:
    why = []
    gc, oc = g["full"].get("cagr_pct"), o["full"].get("cagr_pct")
    if gc is None or oc is None or gc < oc + BAR["h_cagr_gain"] - 1e-9:
        why.append(f"H1 CAGR {gc}% < O11 {oc}% + {BAR['h_cagr_gain']}")
    gd, od = g["full"].get("max_dd_pct"), o["full"].get("max_dd_pct")
    if gd is None or od is None or gd < od - BAR["h_dd_tol"] - 1e-9:
        why.append(f"H2 max DD {gd}% deeper than O11 {od}% − {BAR['h_dd_tol']}")
    return why


def h_bar_full(g: dict, o: dict) -> list:
    why = h_bar(g, o)
    if g["down_beaten"] < o["down_beaten"]:
        why.append(f"H3 down years beaten {g['down_beaten']} < O11 {o['down_beaten']} (of {o['down_years']})")
    if g["up_lags"] > o["up_lags"]:
        why.append(f"H4 up years >10 pts behind {g['up_lags']} > O11 {o['up_lags']}")
    return why


def guard_bar(tag: str, g: dict, o: dict, stress_keys: tuple = ()) -> list:
    why = []
    gc, oc = g["full"].get("cagr_pct"), o["full"].get("cagr_pct")
    if gc is None or oc is None or gc < oc - BAR["guard_cagr_tol"] - 1e-9:
        why.append(f"{tag}1 CAGR {gc}% < O11 {oc}% − {BAR['guard_cagr_tol']}")
    gd = g["full"].get("max_dd_pct")
    if gd is None or not gd > BAR["max_dd"]:
        why.append(f"{tag}2 max DD {gd}% not shallower than {BAR['max_dd']}%")
    for k in stress_keys:
        a_, b_ = g.get(k, {}).get("total_pct"), o.get(k, {}).get("total_pct")
        if a_ is None or b_ is None or a_ < b_ - BAR["stress_tol"] - 1e-9:
            why.append(f"{tag}3 {k} {a_}% worse than O11 {b_}% − {BAR['stress_tol']}")
    return why


def analyse(H: dict, R: dict, L: dict) -> dict:
    out = {"version": VERSION, "windows": {}}
    for name, w in (("H", H), ("R", R), ("L", L)):
        js = {k: judge(v["nav"], w["mkt"], w["a"], w["b"], w["windows"]) for k, v in w["res"].items()}
        sp = {k: spell_edges(w["res"][k]["st"], w["res"][k]["nav"], w["mkt"], w["a"], w["b"]) for k in ("O11", f"G{BAND_DECISION:g}")}
        share = {}
        for k in ("O11", f"G{BAND_DECISION:g}"):
            s_ = w["res"][k]["st"]
            s_ = s_[(s_.index >= pd.Timestamp(w["a"])) & (s_.index <= pd.Timestamp(w["b"]))]
            share[k] = {**{x: round(float(y) * 100, 1) for x, y in s_.value_counts(normalize=True).items()},
                        "switches_per_yr": round(float((s_ != s_.shift()).iloc[1:].sum()) / max(1e-9, (s_.index[-1] - s_.index[0]).days / 365.25), 1)}
        out["windows"][name] = {"judge": js, "spells": sp, "share": share, "guard_gap": guard_ok(w), "a": w["a"], "b": w["b"]}
    gk = f"G{BAND_DECISION:g}"
    H_, R_, L_ = (out["windows"][x]["judge"] for x in ("H", "R", "L"))
    guards_exact = all(out["windows"][x]["guard_gap"] < 1e-9 for x in ("H", "R", "L"))
    fails = h_bar_full(H_[gk], H_["O11"]) + guard_bar("R", R_[gk], R_["O11"]) + \
        guard_bar("L", L_[gk], L_["O11"], ("gfc_2008", "covid_2020"))
    nb = {f"G{b:g}": h_bar(H_[f"G{b:g}"], H_["O11"]) for b in BAND_NEIGHBOURS}
    stable = all(not v for v in nb.values())
    if not guards_exact:
        verdict = "INVALID (guard: G0 differs from O11)"
    elif fails:
        verdict = "FAIL"
    else:
        verdict = "PASS (stable)" if stable else "PASS (not stable)"
    out.update({"verdict": verdict, "fails": fails, "neighbours": nb, "stable": stable, "guards_exact": guards_exact,
                "not_yet": L.get("not_yet", [])})
    return out


# ── output ──────────────────────────────────────────────────────────────────

def _p(x):
    return "—" if x is None else f"{x:.2f}%"


def render(a: dict, stamp: str) -> str:
    gk = f"G{BAND_DECISION:g}"
    cols = ["O11", gk, *[f"G{b:g}" for b in BAND_NEIGHBOURS], "Market"]
    L = [f"# G lab {VERSION} — graduated Defense — {stamp}", "",
         f"Pre-registered in `claude/g_lab_2026-11-25.md`. Long-term trials {TRIALS_BEFORE} → {TRIALS_BEFORE + TRIALS_HERE}. "
         "Research, not personalized advice.", "",
         f"## {gk} (Defense only at 2 closes ≥ {BAND_DECISION:g}% below the 200-day): **{a['verdict']}**",
         f"- Fails: {'; '.join(a['fails']) or 'none'}",
         "- Neighbours (H1–H2): " + "; ".join(f"{k}: {'meets' if not v else '; '.join(v)}" for k, v in a["neighbours"].items()),
         "- Guard (G0 = O11 exactly): " + ", ".join(f"{x} gap {a['windows'][x]['guard_gap']:.2e}" for x in ("H", "R", "L")),
         "- Notes: H and R have no credit series, so O11's 50-day exit there is unconfirmed (as in the OOS lab). "
         "Every window is measured from the previous close, so L's figures differ from offense_lab's tables by one day's return; "
         "G and O11 are measured the same way."]
    if a.get("not_yet"):
        L.append("- 2000–26 sleeves that did not exist yet (0% until then, identical for O11 and every G; labelled as in offense_lab): " +
                 ", ".join(f"{x['sleeve']} {x['weight']:g}% from {x['from'] or 'never'}" for x in a["not_yet"]))
    names = {"H": f"H — hold-out {H_START[:4]}–{H_END[:4]} (decides)", "R": "R — 1963–99 (guard)", "L": "L — 2000–26 (guard, live bar)"}
    for x in ("H", "R", "L"):
        w = a["windows"][x]
        js = w["judge"]
        L += ["", f"## {names[x]}", "", "| | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
        L.append("| CAGR | " + " | ".join(_p(js[c]["full"].get("cagr_pct")) for c in cols) + " |")
        L.append("| Max DD | " + " | ".join(_p(js[c]["full"].get("max_dd_pct")) for c in cols) + " |")
        for k, val in js["O11"].items():
            if isinstance(val, dict) and k != "full" and "total_pct" in val:
                L.append(f"| {k} | " + " | ".join(_p(js[c].get(k, {}).get("total_pct")) for c in cols) + " |")
        L.append("| Down years beaten | " + " | ".join(f"{js[c]['down_beaten']} of {js[c]['down_years']}" for c in cols) + " |")
        L.append("| Up years >10 pts behind | " + " | ".join(str(js[c]["up_lags"]) for c in cols) + " |")
        L.append("| Losing years | " + " | ".join(str(js[c]["losing"]) for c in cols) + " |")
        L.append("")
        L.append("State share / switches per year: " + "; ".join(f"{k}: " + ", ".join(f"{s} {v}" for s, v in d_.items()) for k, d_ in w["share"].items()))
        for k in ("O11", gk):
            sp = w["spells"][k]
            L.append(f"- {k} non-Offense spells (edge vs market, log pts): " +
                     ", ".join(f"{r.st} {r.len} ×{r.spells} {r.edge:+.1f}" for r in sp.itertuples()))
        yb = pd.DataFrame({"O11": js["O11"]["years"]["book"], gk: js[gk]["years"]["book"], "Mkt": js["O11"]["years"]["mkt"]})
        big = yb[(yb[gk] - yb["O11"]).abs() > 5]
        if len(big):
            L.append("- Years where " + gk + " and O11 differ by > 5 pts: " +
                     ", ".join(f"{int(i)} ({r.O11:+.1f} → {r[gk]:+.1f}; mkt {r.Mkt:+.1f})" for i, r in big.iterrows()))
    L += ["", f"*g_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def _clean(x):
    """Strict JSON: NaN/inf -> None, numpy scalars -> Python, everything else str()."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    if x is None or isinstance(x, str):
        return x
    return str(x)


def write_outputs(a: dict, H: dict, R: dict, L: dict, stamp: str, out_dir: Path = OUT_DIR, log_dir: Path = LOG_DIR) -> str:
    md = render(a, stamp)
    js = {"version": VERSION, "asof": stamp, "verdict": a["verdict"], "fails": a["fails"], "neighbours": a["neighbours"],
          "stable": a["stable"], "guards_exact": a["guards_exact"], "trials": TRIALS_BEFORE + TRIALS_HERE,
          "not_yet_existing_2000_26": a.get("not_yet", []),
          "windows": {x: {"guard_gap": w["guard_gap"], "share": w["share"],
                          "judge": {k: {kk: vv for kk, vv in v.items() if kk != "years"} for k, v in w["judge"].items()},
                          "spells": {k: v.to_dict(orient="records") for k, v in w["spells"].items()}}
                      for x, w in a["windows"].items()}}
    text = json.dumps(_clean(js), indent=1, allow_nan=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    for x, w in (("H", H), ("R", R), ("L", L)):
        pd.DataFrame({k: v["nav"] for k, v in w["res"].items()}).round(4).to_csv(out_dir / f"nav_{x}.csv")
    (out_dir / "summary.json").write_text(text)
    (log_dir / "latest.md").write_text(md)
    (log_dir / f"{stamp}.md").write_text(md)
    return md


# ── main ────────────────────────────────────────────────────────────────────

def check_h(ff3: pd.DataFrame) -> list:
    w = ff3[(ff3.index >= "1926-07-01") & (ff3.index <= H_END)]
    bad = []
    if ff3.index.min() > pd.Timestamp("1926-07-31"):
        bad.append(f"French factors start {ff3.index.min().date()}")
    if w[["Mkt-RF", "RF"]].isna().any().any():
        bad.append("French factors have gaps in 1926–62")
    if len(w) < 9000:
        bad.append(f"only {len(w)} French days in 1926–62")
    if len(w):
        gaps = w.index.to_series().diff().dt.days
        if (gaps > 15).any():
            bad.append(f"French factors skip {int(gaps.max())} days before {gaps.idxmax().date()} (missing dates)")
        if w.index.max() < pd.Timestamp("1962-12-28"):
            bad.append(f"French factors end {w.index.max().date()} inside the hold-out")
    return bad


def main(get=oos.http_get, yahoo_fetch=None, balanced: Optional[dict] = None, pause: float = 10.0,
         fred_key: Optional[str] = None) -> int:
    stamp = date.today().isoformat()
    fred_key = os.environ.get("FRED_API_KEY", "").strip() if fred_key is None else fred_key
    print(f"[g_lab] {VERSION}: DGS10 source {'FRED API (key set)' if fred_key else 'FRED CSV link'}")
    try:
        ff3, size, dgs10, gold = oos.load_all(get, pause, fred_key)
    except Exception as e:
        print(f"[g_lab] DATA FAILURE: {type(e).__name__}: {e}; nothing written.")
        return 1
    bad = check_h(ff3)
    d = oos.build(ff3, size, dgs10, gold)
    bad += oos.check_returns(d)
    tickers = sorted(set(hl.all_tickers()) | set(ol.EXTRA_TICKERS))
    fetch = yahoo_fetch or hl.yf_fetch
    closes: dict = {}
    for attempt in range(FETCH_TRIES):
        want = [t for t in tickers if t not in closes]
        if not want:
            break
        try:
            got = fetch(want, start=ol.HISTORY_START)
            closes.update({k: v for k, v in got.items() if v is not None and len(v)})
        except Exception as e:
            print(f"[g_lab] Yahoo attempt {attempt + 1}: {type(e).__name__}: {e}")
        left = [t for t in tickers if t not in closes]
        if left and attempt < FETCH_TRIES - 1:
            print(f"[g_lab] Yahoo attempt {attempt + 1}: {len(left)} tickers missing ({', '.join(left[:8])}); retrying")
            if pause:
                import time
                time.sleep(pause * (attempt + 1))
    missing = [t for t in ("SPY", "QQQ", *ol.SECTORS9, "^IRX", *ol.CREDIT_PAIR) if t not in closes]
    if missing:
        bad.append(f"2000–26 signal inputs missing: {', '.join(missing)}")
    if bad:
        print("[g_lab] DATA FAILURE: " + "; ".join(bad) + "; nothing written.")
        return 1
    if balanced is None:
        import regime_classifier as rc
        balanced = {k: float(v) for k, v in rc.target_weights(hl.REGIME, gate=False).items()}
    bands = (0.0, BAND_DECISION, *BAND_NEIGHBOURS)
    ldata = ol.build_data(closes)
    bad_l = check_L(ldata, balanced, closes)
    if bad_l:
        print("[g_lab] DATA FAILURE: " + "; ".join(bad_l) + "; nothing written.")
        return 1
    try:
        H = run_H(ff3, bands)
        R = run_R(d, bands)
        L = run_L(ldata, balanced, bands)
    except oos.DataFailure as e:
        print(f"[g_lab] DATA FAILURE: {e}; nothing written.")
        return 1
    a = analyse(H, R, L)
    print(write_outputs(a, H, R, L, stamp))
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _levels_from(path: np.ndarray, start: str = "2000-01-03") -> tuple:
    cal = pd.bdate_range(start, periods=len(path))
    lv = pd.Series(path, index=cal)
    levels = pd.DataFrame({"SPY": lv, "QQQ": lv})
    rets = levels.pct_change()
    return levels, rets


def selftest() -> dict:
    import contextlib, tempfile
    f = []
    rng = np.random.default_rng(11)
    # 1. b = 0 reproduces states_fast exactly (with and without credit, on a choppy random path)
    for seed in (1, 2, 3):
        r_ = np.random.default_rng(seed)
        n = 2500
        reg = np.where((np.arange(n) // 300) % 3 == 0, -0.0008, 0.0006)
        p = 100 * np.exp(np.cumsum(r_.normal(reg, 0.011)))
        q = 100 * np.exp(np.cumsum(r_.normal(1.2 * reg, 0.014)))
        cal = pd.bdate_range("2000-01-03", periods=n)
        lv = pd.DataFrame({"SPY": p, "QQQ": q, "CREDIT": 100 * np.exp(np.cumsum(r_.normal(0, 0.003, n)))}, index=cal)
        rt = lv.pct_change()
        for cr in (False, True):
            a0, b0 = ol.states_fast(lv, rt, credit=cr), states_g(lv, rt, 0.0, credit=cr)
            if not a0.equals(b0):
                f.append(f"b=0 must equal states_fast (seed {seed}, credit {cr}): {int((a0 != b0).sum())} days differ")
        g3 = states_g(lv, rt, 3.0, credit=True)
        if g3.equals(ol.states_fast(lv, rt, credit=True)):
            f.append(f"fixture seed {seed}: b=3 should differ from O11 somewhere")
    # 2. hand-built paths around a flat 200-day average
    base = 100.0 + 0.02 * np.arange(400)                      # gentle uptrend: above the 50- and 200-day,
                                                              # price ~2 above its 200-day (dips stay inside −8%)

    def path_with(dips: dict) -> pd.Series:
        p = base.copy()
        for i, v in dips.items():
            p[i] = v
        lv_, rt_ = _levels_from(p)
        return states_g(lv_, rt_, 3.0), ol.states_fast(lv_, rt_)
    i0 = 330
    ma_at = pd.Series(base).rolling(200).mean().iloc[i0]
    shallow = ma_at * 0.99                                    # 1% below the 200-day
    deep = ma_at * 0.95                                       # 5% below
    gs, os_ = path_with({i0: shallow, i0 + 1: shallow})
    if os_.iloc[i0 + 1] != "DEF" or gs.iloc[i0 + 1] != "BAL":
        f.append(f"shallow 2-close dip: O11 {os_.iloc[i0 + 1]} (want DEF), G3 {gs.iloc[i0 + 1]} (want BAL)")
    gd, _ = path_with({i0: deep, i0 + 1: deep})
    if gd.iloc[i0 + 1] != "DEF":
        f.append(f"deep 2-close dip must go to Defense (got {gd.iloc[i0 + 1]})")
    for seq in ((deep, shallow), (shallow, deep)):
        gm, _ = path_with({i0: seq[0], i0 + 1: seq[1]})
        if gm.iloc[i0 + 1] == "DEF":
            f.append("one deep close beside a shallow one must not be Defense (2 deep closes needed)")
            break
    if h_book("OUT") != H_BOOKS["BAL"] or h_book("BAL") != H_BOOKS["BAL"] or h_book("DEF") != H_BOOKS["DEF"] or h_book("OFF") != H_BOOKS["OFF"]:
        f.append("hold-out books: OUT and BAL hold Balanced, DEF cash, OFF the market")
    if gs.iloc[i0 - 1] != "OFF":
        f.append(f"fixture: the hand path must be in Offense before the dip (got {gs.iloc[i0 - 1]})")
    # DEF stays DEF on a later shallow dip; leaves only on 2 closes back above
    p2 = base.copy(); p2[i0:i0 + 3] = deep; p2[i0 + 3:i0 + 6] = shallow
    lv2, rt2 = _levels_from(p2)
    s2 = states_g(lv2, rt2, 3.0)
    if not (s2.iloc[i0 + 2] == "DEF" and s2.iloc[i0 + 5] == "DEF"):
        f.append(f"Defense must hold through a shallow phase ({s2.iloc[i0 + 2]}, {s2.iloc[i0 + 5]})")
    if s2.iloc[i0 + 7] == "DEF" or s2.iloc[i0 + 6] != "DEF":
        f.append(f"Defense must end on the 2nd close back above, not before ({s2.iloc[i0 + 6]}, {s2.iloc[i0 + 7]})")
    # OUT keeps its state (and cooldown) on a shallow dip
    p3 = base.copy()
    ma3 = pd.Series(p3).rolling(200).mean()
    p3[i0 + 12:i0 + 14] = ma3.iloc[i0 + 12] * 0.99
    lv3, rt3 = _levels_from(p3)
    lv3["QQQ"] = lv3["SPY"].copy()
    lv3.iloc[i0 - 3:i0 + 15, lv3.columns.get_loc("QQQ")] = 100.0     # QQQ below its 50-day: fast exit
    s3 = states_g(lv3, lv3.pct_change(), 3.0)
    o3 = s3.iloc[i0:i0 + 12]
    if "OUT" in set(o3) and s3.iloc[i0 + 13] not in ("OUT",):
        f.append(f"OUT must keep its state on a shallow dip (got {s3.iloc[i0 + 13]})")
    if "OUT" not in set(o3):
        f.append("fixture: the OUT path did not produce a fast exit")
    # T2: weights on day d come from the state at d-1 (no look-ahead), with O11's lag
    st_h = pd.Series(["OFF", "OFF", "DEF", "DEF", "BAL", "OFF", "OUT"], index=pd.bdate_range("1930-01-02", periods=7))
    wl = _lag_weights(st_h, lambda s_, d_: h_book(s_))
    for k_ in range(1, 7):
        if wl(st_h.index[k_]) != h_book(st_h.iloc[k_ - 1]):
            f.append(f"weights on {st_h.index[k_].date()} must come from the state the session before"); break
    # spell table lag: Defense state on days 5–7 is HELD on days 7–9 (weights set at d-1 from the state at d-2)
    c12 = pd.bdate_range("2001-01-02", periods=12)
    st12 = pd.Series(["OFF"] * 12, index=c12); st12.iloc[5:8] = "DEF"
    mr = np.zeros(12); mr[9] = 0.10                             # the market jumps on day 9: Defense misses it
    br = mr.copy(); br[7:10] = 0.0
    sp12 = spell_edges(st12, pd.Series(np.cumprod(1 + br), index=c12), pd.Series(np.cumprod(1 + mr), index=c12),
                       str(c12[1].date()), str(c12[-1].date()))
    de = sp12[sp12.st == "DEF"]
    if len(de) != 1 or abs(float(de.edge.iloc[0]) + 9.5) > 0.05:
        f.append(f"spell_edges must attribute day d to the state at d-2 (DEF edge {de.edge.tolist()}, want −9.5)")
    # T1: OUT keeps its cooldown through a shallow dip (a dip must not restart or end the cooldown)
    n4 = 500
    p4 = 100.0 + 0.02 * np.arange(n4)
    q4 = p4.copy()
    t_out = 300
    q4[t_out - 1:t_out + 1] = q4[t_out - 1] * 0.9                   # QQQ 2 closes below its 50-day -> OUT
    ma4 = pd.Series(p4).rolling(200).mean()
    p4[t_out + 5:t_out + 7] = ma4.iloc[t_out + 5] * 0.99            # SPY shallow dip during the cooldown
    cal4 = pd.bdate_range("2001-01-02", periods=n4)
    lv4 = pd.DataFrame({"SPY": p4, "QQQ": q4}, index=cal4)
    s4 = states_g(lv4, lv4.pct_change(), 3.0)
    o4 = ol.states_fast(lv4, lv4.pct_change())
    first_off = next((i for i in range(t_out + 1, n4) if s4.iloc[i] == "OFF"), None)
    if s4.iloc[t_out] != "OUT" or s4.iloc[t_out + 6] != "OUT":
        f.append(f"fixture T1: expected OUT through the dip ({s4.iloc[t_out]}, {s4.iloc[t_out + 6]})")
    elif first_off != t_out + ol.COOLDOWN:
        f.append(f"OUT cooldown: Offense must resume exactly {ol.COOLDOWN} sessions after the exit (got {None if first_off is None else first_off - t_out})")
    if o4.iloc[t_out + 6] != "DEF":
        f.append("fixture T1: O11 should be in Defense on that dip")
    # 3. bars
    def J(c, dd, dyb=3, dy=4, lags=2, **w):
        return {"full": {"cagr_pct": c, "max_dd_pct": dd}, "down_beaten": dyb, "down_years": dy, "up_lags": lags, **w}
    o = J(8.0, -30.0)
    if h_bar_full(J(8.3, -31.5), o) or not h_bar_full(J(8.2, -30.0), o) or not h_bar_full(J(8.3, -32.5), o) or \
            not h_bar_full(J(8.3, -30.0, dyb=2), o) or not h_bar_full(J(8.3, -30.0, lags=3), o):
        f.append("h_bar logic")
    ol_ = J(10.0, -19.0, gfc_2008={"total_pct": -10.0}, covid_2020={"total_pct": -12.0})
    if guard_bar("L", J(9.8, -19.5, gfc_2008={"total_pct": -12.5}, covid_2020={"total_pct": -14.0}), ol_, ("gfc_2008", "covid_2020")) or \
            not guard_bar("L", J(9.7, -19.0, gfc_2008={"total_pct": -10.0}, covid_2020={"total_pct": -12.0}), ol_, ("gfc_2008", "covid_2020")) or \
            not guard_bar("L", J(10.0, -20.5, gfc_2008={"total_pct": -10.0}, covid_2020={"total_pct": -12.0}), ol_, ("gfc_2008", "covid_2020")) or \
            not guard_bar("L", J(10.0, -19.0, gfc_2008={"total_pct": -10.0}, covid_2020={"total_pct": -15.5}), ol_, ("gfc_2008", "covid_2020")):
        f.append("guard_bar logic")
    # 4. full pipeline on synthetic data: H, R, L, guard exact, writer, abort paths
    ff3, size, dgs10, gold = oos._fixture()
    ff3_long = ff3.copy()
    cal_h = pd.bdate_range("1926-07-01", "1954-12-31")
    rng2 = np.random.default_rng(3)
    early = pd.DataFrame({"Mkt-RF": rng2.normal(np.where((np.arange(len(cal_h)) // 600) % 2 == 0, 0.05, -0.05), 1.0),
                          "SMB": 0.0, "HML": 0.0, "RF": 0.01}, index=cal_h).round(2)
    ff3_long = pd.concat([early, ff3[ff3.index > cal_h[-1]]])
    size_long = pd.concat([pd.DataFrame({"<= 0": 0.0, "Lo 30": (early["Mkt-RF"] * 1.1).round(2), "Med 40": 0.0, "Hi 30": 0.0}, index=cal_h),
                           size[size.index > cal_h[-1]]])
    texts = {oos.URLS["ff3"]: oos._zip(oos._french_text(ff3_long)), oos.URLS["size"]: oos._zip(oos._french_text(size_long)),
             oos.URLS["dgs10"]: ("observation_date,DGS10\n" + "\n".join(f"{i.date()},{v:.2f}" for i, v in dgs10.items())).encode(),
             oos.URLS["gold"]: ("Date,Price\n" + "\n".join(f"{i.strftime('%Y-%m')},{v:.4f}" for i, v in gold.items())).encode()}
    syn = ol._synthetic()
    syn["AGG"], syn["TLT"], syn["GLD"] = syn["VBMFX"], syn["VUSTX"], syn["GC=F"]
    syn["SGOV"] = pd.Series(100 * np.exp(np.cumsum(np.full(len(syn["SPY"]), 0.0001))), index=syn["SPY"].index)
    late = syn["DBC"].copy()
    syn["PDBC"] = late[late.index >= "2006-02-06"]                    # a sleeve that did not exist before 2006
    syn["DBC"] = late[late.index >= "2006-02-06"]
    bal = {"SPY": 45.0, "AGG": 30.0, "SGOV": 20.0, "PDBC": 5.0}
    tmp = Path(tempfile.mkdtemp())
    cwd = os.getcwd()
    try:
        os.chdir(tmp)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc_ok = main(get=lambda u: texts[u], yahoo_fetch=lambda t, start=None: {k: v for k, v in syn.items()},
                         balanced=bal, pause=0, fred_key="")
        if rc_ok != 0:
            f.append("main: a clean synthetic run must succeed: " + buf.getvalue()[-500:])
        else:
            js = json.loads((tmp / "data" / "g_lab" / "summary.json").read_text())
            if not js["guards_exact"]:
                f.append(f"guard: G0 must equal O11 in every window ({[js['windows'][x]['guard_gap'] for x in 'HRL']})")
            if not (tmp / "logs" / "g_lab" / "latest.md").exists() or "hold-out" not in (tmp / "logs" / "g_lab" / "latest.md").read_text():
                f.append("writer: report missing")
            h = js["windows"]["H"]["judge"]
            if h["G3"]["full"]["cagr_pct"] == h["O11"]["full"]["cagr_pct"]:
                f.append("fixture: G3 should differ from O11 in H")
            ny = {x["sleeve"]: x["from"] for x in js.get("not_yet_existing_2000_26", [])}
            if ny.get("PDBC") != "2006-02-07" or "PDBC 5% from 2006-02-07" not in (tmp / "logs" / "g_lab" / "latest.md").read_text():
                f.append(f"a sleeve that did not exist yet must be allowed and reported ({ny})")
        import shutil
        shutil.rmtree(tmp / "data", ignore_errors=True)
        with contextlib.redirect_stdout(io.StringIO()):
            rc_y = main(get=lambda u: texts[u], yahoo_fetch=lambda t, start=None: {k: v for k, v in syn.items() if k != "QQQ"},
                        balanced=bal, pause=0, fred_key="")
            short_ff = dict(texts); short_ff[oos.URLS["ff3"]] = oos._zip(oos._french_text(ff3))     # starts 1955
            rc_h = main(get=lambda u: short_ff[u], yahoo_fetch=lambda t, start=None: dict(syn), balanced=bal, pause=0, fred_key="")
            rc_n = main(get=lambda u: (_ for _ in ()).throw(TimeoutError("timed out")), balanced=bal, pause=0, fred_key="")
            rc_z = main(get=lambda u: texts[u], yahoo_fetch=lambda t, start=None: dict(syn), balanced={"SPY": 50.0, "ZZZ": 50.0},
                        pause=0, fred_key="")
            no_dbmf = {k: v for k, v in syn.items() if k != "SGOV"}           # a held native fails to download
            rc_dl = main(get=lambda u: texts[u], yahoo_fetch=lambda t, start=None: {k: v for k, v in no_dbmf.items() if k in t},
                         balanced=bal, pause=0, fred_key="")
            holey = dict(syn)
            a_ = holey["VBMFX"]; holey["AGG"] = a_.drop(a_.index[2000:2006])     # 6 sessions missing in a sleeve that exists
            holey["VBMFX"] = holey["AGG"]
            rc_hole = main(get=lambda u: texts[u], yahoo_fetch=lambda t, start=None: {k: v for k, v in holey.items() if k in t},
                           balanced=bal, pause=0, fred_key="")
            hole = dict(texts)
            hole[oos.URLS["ff3"]] = oos._zip(oos._french_text(ff3_long[(ff3_long.index < "1940-01-01") | (ff3_long.index > "1940-03-31")]))
            rc_g = main(get=lambda u: hole[u], yahoo_fetch=lambda t, start=None: dict(syn), balanced=bal, pause=0, fred_key="")
        if rc_y != 1 or rc_h != 1 or rc_n != 1 or rc_z != 1 or rc_g != 1 or rc_dl != 1 or rc_hole != 1 or (tmp / "data" / "g_lab").exists():
            f.append(f"main: missing Yahoo input / short French history / dead source / dead Balanced sleeve / missing dates / "
                     f"held fund not downloaded / hole in data must stop with nothing written "
                     f"({rc_y}, {rc_h}, {rc_n}, {rc_z}, {rc_g}, {rc_dl}, {rc_hole})")
    except Exception as e:
        import traceback
        f.append(f"pipeline crashed: {type(e).__name__}: {e} {traceback.format_exc()[-600:]}")
    finally:
        os.chdir(cwd)
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r_ = selftest()
        print(json.dumps(r_, indent=2, default=str))
        sys.exit(0 if r_["ok"] else 1)
    sys.exit(main())
