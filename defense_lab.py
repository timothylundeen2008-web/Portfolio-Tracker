"""
defense_lab.py  (v1.0 — 2026-11-20)
────────────────────────────────────
Long-term book. Matt, 2026-11-20: "we should also be making sure that those positions
we are moving to are not tanking either. for example, 2022 ... double check
positioning for changing to ensure we preserve capital and maximize gains no matter
the market regime/condition. there are plenty of ETF's to leverage such as KMLM,
SGOV, etc."  Pre-registration: claude/defense_lab_2026-11-20.md (D1 design from
system_review_2026-11-14.md §6.1, plus the trend-checked versions he asked for).

The O11 switching rules are NOT changed. Only what each state holds changes.

CANDIDATES (frozen before any run)
  D0  baseline = live O11 Defense: 60 SGOV / 20 GLD / 20 TLT.
  D1  Defense 50 SGOV / 20 GLD / 15 DBMF / 15 TLT; TLT held only while in trend.
  D2  Defense 45 SGOV / 20 GLD / 20 TLT / 7.5 DBMF / 7.5 KMLM; EVERY non-cash sleeve
      held only while in trend ("never move into something that is falling").
  B1  Balanced: every non-cash sleeve of today's regime book (C3) held only while in
      trend; Defense stays D0 ("don't sit in a Balanced book that is falling").
  In trend = the sleeve's total-return level closed above its 200-day average on 2
  consecutive closes; out of trend after 2 consecutive closes below. A sleeve out of
  trend sits in SGOV. The trend state seen at a close is used for the next session's
  weights (the same one-session lag as the engine). Cash sleeves (SGOV, USFR) exempt.
BARS (vs O11 with D0, 2000–2026, 5bp costs)
  D1, D2: full CAGR ≥ O11's; each half (2005–15, 2016–26) ≥ O11's − 0.10 pts; max
          drawdown no deeper than O11's; calendar 2022 at least 2.0 points better.
  B1:     full CAGR ≥ O11's; each half ≥ O11's − 0.10; max drawdown no deeper than
          O11's; FEWER drawdown episodes past −10% than O11.
  ROBUST: a candidate that meets its bar is re-run with 150- and 250-day trend
          averages; ROBUST if both also meet it.
TRIALS: 3 + 2 per candidate that meets its bar (long-term 31 → 34 + robustness runs).
Caveat (conservative): managed futures run on AQMIX from 2010 and T-bills before, so
D1/D2 get no credit for trend-following in 2008.

Run:  python defense_lab.py            (Actions, ~10–20 min)
      python defense_lab.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

import hedge_lab as hl
import offense_lab as ol

VERSION = "1.0"
TREND_MA, ROBUST_MAS, CONFIRM = 200, (150, 250), 2
CASH_SLEEVES = {"SGOV", "USFR"}
D0 = {"SGOV": 60.0, "GLD": 20.0, "TLT": 20.0}
CANDIDATES = {
    "D1": {"label": "Defense 50 SGOV / 20 GLD / 15 DBMF / 15 TLT, TLT trend-checked",
           "defense": {"SGOV": 50.0, "GLD": 20.0, "DBMF": 15.0, "TLT": 15.0}, "gate_def": ("TLT",), "gate_bal": False},
    "D2": {"label": "Defense 45 SGOV / 20 GLD / 20 TLT / 7.5 DBMF / 7.5 KMLM, every sleeve trend-checked",
           "defense": {"SGOV": 45.0, "GLD": 20.0, "TLT": 20.0, "DBMF": 7.5, "KMLM": 7.5},
           "gate_def": ("GLD", "TLT", "DBMF", "KMLM"), "gate_bal": False},
    "B1": {"label": "Balanced with every sleeve trend-checked; Defense unchanged",
           "defense": D0, "gate_def": (), "gate_bal": True},
}
BAR_HALF_TOL, BAR_2022 = 0.10, 2.0
OUT_DIR, LOG_DIR = Path("data/defense_lab"), Path("logs/defense_lab")


# ── trend gates ─────────────────────────────────────────────────────────────

def sleeve_levels(rets: pd.DataFrame) -> pd.DataFrame:
    """Total-return level of each sleeve; NaN before its first return."""
    out = {}
    for c in rets.columns:
        r = rets[c]
        first = r.first_valid_index()
        lv = (1 + r.fillna(0.0)).cumprod()
        if first is None:
            lv[:] = np.nan
        else:
            lv[lv.index < first] = np.nan
        out[c] = lv
    return pd.DataFrame(out, index=rets.index)


def trend_states(levels: pd.DataFrame, cols, ma: int = TREND_MA) -> pd.DataFrame:
    """True = in trend (2 closes above the MA), False = out (2 closes below); unknown history = out."""
    out = {}
    for c in cols:
        if c not in levels:
            out[c] = pd.Series(False, index=levels.index)
            continue
        up = ol.above_ma(levels[c], ma)
        raw = up.map(lambda x: None if x != x else ("IN" if x else "OUT"))
        out[c] = ol.confirm(raw, CONFIRM, "OUT") == "IN"
    return pd.DataFrame(out, index=levels.index)


def gate(book: dict, gated, ok: dict) -> dict:
    """Sleeves in `gated` that are out of trend move to SGOV."""
    w = {}
    for k, v in book.items():
        if k in gated and k not in CASH_SLEEVES and not ok.get(k, False):
            w["SGOV"] = w.get("SGOV", 0.0) + v
        else:
            w[k] = w.get(k, 0.0) + v
    return w


def weights_fn(st: pd.Series, trend: pd.DataFrame, cand: dict, balanced: dict, lag: int = ol.LAG) -> Callable:
    """O11's state and every trend gate as seen `lag` sessions before d."""
    s_l = st.shift(lag)
    s_l.iloc[:lag] = st.iloc[0]
    t_l = trend.shift(lag).fillna(False).astype(bool)
    sm, tm = s_l.to_dict(), t_l.to_dict("index")
    bal_gated = tuple(k for k in balanced if k not in CASH_SLEEVES) if cand["gate_bal"] else ()

    def w(d):
        s, ok = sm[d], tm[d]
        if s == "OFF":
            return dict(ol.OFFENSE_1X)
        if s == "DEF":
            return gate(cand["defense"], cand["gate_def"], ok)
        return gate(balanced, bal_gated, ok)
    return w


def run(data: dict, cand: dict, balanced: dict, ma: int = TREND_MA) -> dict:
    rets = data["rets"]
    st = ol.states_fast(data["levels"], rets, credit=True)
    cols = set(cand["gate_def"]) | (set(balanced) - CASH_SLEEVES if cand["gate_bal"] else set())
    tr = trend_states(sleeve_levels(rets), sorted(cols), ma)
    days = data["cal"][data["cal"] >= pd.Timestamp(ol.EVAL_START) - pd.Timedelta(days=10)]
    sim = hl.simulate(days, rets, weights_fn(st, tr, cand, balanced), None, breaker=False, cost_bps=ol.COST_BPS)
    return {"nav": sim["nav"], "states": st, "trend": tr, "weights": sim["w"]}


# ── judging ─────────────────────────────────────────────────────────────────

def year_ret(nav: pd.Series, y: int):
    yr = ol.year_returns(nav)
    s = yr[yr.index.year == y]
    return float(s.iloc[0]) if len(s) else None


def bar(key: str, c: dict, base: dict) -> list:
    why = []
    s, b = c["summ"], base["summ"]
    cf, bf = s["full"].get("cagr_pct"), b["full"].get("cagr_pct")
    if cf is None or bf is None or cf < bf - 1e-9:
        why.append(f"full CAGR {cf}% < O11 {bf}%")
    for h, _, _ in ol.HALVES:
        ch, bh = s[h].get("cagr_pct"), b[h].get("cagr_pct")
        if ch is None or bh is None or ch < bh - BAR_HALF_TOL - 1e-9:
            why.append(f"{h} CAGR {ch}% < O11 {bh}% − {BAR_HALF_TOL}")
    cd, bd = s["full"].get("max_dd_pct"), b["full"].get("max_dd_pct")
    if cd is None or bd is None or cd < bd - 1e-9:
        why.append(f"max DD {cd}% deeper than O11 {bd}%")
    if key.startswith("D"):
        c22, b22 = c["y2022"], base["y2022"]
        if c22 is None or b22 is None or c22 < b22 + BAR_2022 - 1e-9:
            why.append(f"2022 {c22}% not ≥ O11 {b22}% + {BAR_2022}")
    else:
        if not c["ep10"] < base["ep10"]:
            why.append(f"{c['ep10']} episodes past −10% vs O11 {base['ep10']} (needs fewer)")
    return why


def spells(states: pd.Series, nav: pd.Series, state: str, start=ol.EVAL_START) -> pd.DataFrame:
    """Return of the book over each spell spent in `state` (the spell's own days, one-session lag)."""
    s = states.shift(ol.LAG).reindex(nav.index)
    s = s[s.index >= pd.Timestamp(start)]
    rows, cur, a, prev = [], None, None, None
    for d, v in s.items():
        if v != cur:
            if cur == state and a is not None:
                rows.append((a, prev))
            cur, a = v, d
        prev = d
    if cur == state and a is not None:
        rows.append((a, prev))
    out = []
    for a, b in rows:
        i = nav.index.get_loc(a)
        n0 = nav.iloc[i - 1] if i > 0 else nav.iloc[i]
        out.append({"from": a.date(), "to": b.date(), "sessions": int(((nav.index >= a) & (nav.index <= b)).sum()),
                    "return_pct": round((nav.loc[b] / n0 - 1) * 100, 2)})
    return pd.DataFrame(out, columns=["from", "to", "sessions", "return_pct"])


def summarise(nav: pd.Series, states: pd.Series) -> dict:
    return {"summ": ol.summary(nav), "y2022": None if nav is None else (round(year_ret(nav, 2022), 2) if year_ret(nav, 2022) is not None else None),
            "ep10": ol.dd_episodes(nav, -10.0), "ep15": ol.dd_episodes(nav, -15.0),
            "def_spells": spells(states, nav, "DEF"), "bal_spells": spells(states, nav, "BAL"),
            "out_spells": spells(states, nav, "OUT")}


# ── report ──────────────────────────────────────────────────────────────────

def _f(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


def render(res: dict, today: dict, stamp: str, n_new: int) -> str:
    L = [f"# Defense lab {VERSION} — {stamp}", "",
         "What each O11 state moves into, checked for falling holdings. O11's switching rules unchanged. "
         "Rules and bars fixed before the run (claude/defense_lab_2026-11-20.md). Research, not personalized advice.", "",
         "| Book | Verdict | CAGR 2000–26 | 2005–15 | 2016–26 | Max DD | 2022 | Episodes past −10% / −15% | Worst Defense spell | Worst Balanced/fast-exit spell |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for k in ("D0", *CANDIDATES):
        r = res[k]
        s = r["summ"]
        wd = r["def_spells"]["return_pct"].min() if len(r["def_spells"]) else None
        wb = min([x for x in (r["bal_spells"]["return_pct"].min() if len(r["bal_spells"]) else None,
                              r["out_spells"]["return_pct"].min() if len(r["out_spells"]) else None) if x is not None], default=None)
        L.append(f"| {k}{' (live O11)' if k == 'D0' else ''} | {r.get('verdict', 'baseline')} | {_f(s['full'].get('cagr_pct'))}% | "
                 f"{_f(s['2005-15'].get('cagr_pct'))}% | {_f(s['2016-26'].get('cagr_pct'))}% | {_f(s['full'].get('max_dd_pct'), 1)}% | "
                 f"{_f(r['y2022'], 1)}% | {r['ep10']} / {r['ep15']} | {_f(wd, 1)}% | {_f(wb, 1)}% |")
    L += [""]
    for k in CANDIDATES:
        r = res[k]
        L.append(f"- **{k}** — {CANDIDATES[k]['label']}: **{r['verdict']}**" + (f" ({'; '.join(r['why'])})" if r["why"] else "")
                 + (f"; robustness: {r['robust_note']}" if r.get("robust_note") else ""))
    L += ["", "## Every Defense spell (book return while in Defense)", "",
          "| From | To | Sessions | D0 | D1 | D2 |", "|---|---|---|---|---|---|"]
    d0 = res["D0"]["def_spells"]
    for i, row in d0.iterrows():
        vals = [res[k]["def_spells"]["return_pct"].iloc[i] if i < len(res[k]["def_spells"]) else None for k in ("D0", "D1", "D2")]
        L.append(f"| {row['from']} | {row['to']} | {row['sessions']} | " + " | ".join(f"{_f(v, 1)}%" for v in vals) + " |")
    L += ["", "## Calendar years vs D0 (points)", ""]
    yrs = pd.DataFrame({k: ol.year_returns(res[k]["nav"]) for k in res})
    for k in CANDIDATES:
        d = (yrs[k] - yrs["D0"]).dropna()
        L.append(f"- {k}: " + ", ".join(f"{i.year} {v:+.1f}" for i, v in d.items()))
    L += ["", "## Today's read (what the trend checks say now)", ""]
    for k, v in today.items():
        L.append(f"- {k}: {v}")
    L += ["", f"Trials this run: {n_new}.", "",
          "Caveat: managed futures (DBMF, KMLM) run on AQMIX from 2010 and T-bills before, so 2008 gives D1/D2 no "
          "trend-following credit.", "", f"*defense_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def main() -> int:
    stamp = date.today().isoformat()
    tickers = sorted(set(hl.all_tickers()) | set(ol.EXTRA_TICKERS))
    closes = hl.yf_fetch(tickers, start=ol.HISTORY_START)
    need = ("SPY", "QQQ", "^IRX", *ol.CREDIT_PAIR, "GLD", "TLT")
    missing = [t for t in need if t not in closes]
    print(f"[defense_lab] {VERSION}: {len(closes)} of {len(tickers)} tickers; required missing: {missing}")
    if missing:
        print("[defense_lab] DATA FAILURE: a required input is missing; nothing written.")
        return 1
    import regime_classifier as rc
    balanced = {k: float(v) for k, v in rc.target_weights(hl.REGIME, gate=False).items()}
    data = ol.build_data(closes)
    o11 = ol.run_candidate("O11", data, balanced)
    base_run = run(data, {"defense": D0, "gate_def": (), "gate_bal": False}, balanced)
    gap = float((base_run["nav"] / o11["nav"] - 1).abs().max())
    print(f"[defense_lab] D0 reproduces offense_lab O11: max NAV gap {gap:.2e}")
    if gap > 1e-6:
        print("[defense_lab] STOP: the baseline does not reproduce O11; nothing written.")
        return 1
    res = {"D0": {**summarise(base_run["nav"], base_run["states"]), "nav": base_run["nav"]}}
    n_new = 0
    for k, cand in CANDIDATES.items():
        r = run(data, cand, balanced)
        n_new += 1
        res[k] = {**summarise(r["nav"], r["states"]), "nav": r["nav"], "trend": r["trend"]}
        res[k]["why"] = bar(k, res[k], res["D0"])
        if res[k]["why"]:
            res[k]["verdict"] = "FAIL"
            continue
        notes = []
        for m in ROBUST_MAS:
            rr = run(data, cand, balanced, ma=m)
            n_new += 1
            w2 = bar(k, {**summarise(rr["nav"], rr["states"])}, res["D0"])
            notes.append(f"{m}-day: {'meets bar' if not w2 else '; '.join(w2)}")
            if w2:
                res[k].setdefault("fragile", True)
        res[k]["verdict"] = "PASS (fragile)" if res[k].get("fragile") else "PASS (robust)"
        res[k]["robust_note"] = "; ".join(notes)
    lv = sleeve_levels(data["rets"])
    tr = trend_states(lv, ["GLD", "TLT", "DBMF", "KMLM"])
    last = tr.index[-1]
    st = ol.states_fast(data["levels"], data["rets"], credit=True)
    today = {"as of": str(last.date()), "O11 state at this close": st.iloc[-1]}
    for c in ("GLD", "TLT", "DBMF", "KMLM"):
        ma = lv[c].rolling(TREND_MA).mean().iloc[-1]
        today[c] = f"{'IN' if tr[c].iloc[-1] else 'OUT of'} trend ({(lv[c].iloc[-1] / ma - 1) * 100:+.1f}% vs its 200-day)"
    today["D2 Defense would hold"] = ", ".join(f"{k} {v:g}%" for k, v in
                                              gate(CANDIDATES["D2"]["defense"], CANDIDATES["D2"]["gate_def"],
                                                   tr.iloc[-1].to_dict()).items())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tl = OUT_DIR / "trial_log.csv"
    first = not tl.exists()
    row = pd.DataFrame([{"date": stamp, "version": VERSION, "trials": n_new if first else 0,
                         "note": "D1, D2, B1 + robustness for passes" if first else "re-run"}])
    (pd.concat([pd.read_csv(tl), row]) if tl.exists() else row).to_csv(tl, index=False)
    rows = []
    for k, r in res.items():
        for w, s in r["summ"].items():
            rows.append({"book": k, "window": w, **s})
    pd.DataFrame(rows).to_csv(OUT_DIR / "results.csv", index=False)
    pd.DataFrame({k: r["nav"] for k, r in res.items()}).round(4).to_csv(OUT_DIR / "nav.csv")
    pd.concat({k: r["def_spells"] for k, r in res.items()}).to_csv(OUT_DIR / "defense_spells.csv")
    pd.DataFrame([{"book": k, "verdict": res[k]["verdict"], "reasons": "; ".join(res[k]["why"]) or "meets bar",
                   "robustness": res[k].get("robust_note", "")} for k in CANDIDATES]).to_csv(OUT_DIR / "verdicts.csv", index=False)
    md = render(res, today, stamp, n_new if first else 0)
    (LOG_DIR / f"{stamp}_report.md").write_text(md)
    (LOG_DIR / "latest.md").write_text(md)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    f = []
    idx = pd.bdate_range("2020-01-01", periods=400)
    # sleeve levels: NaN before first data, compounding after
    r = pd.DataFrame({"A": [np.nan] * 10 + [0.01] * 390}, index=idx)
    lv = sleeve_levels(r)
    if not lv["A"].iloc[:10].isna().all() or abs(lv["A"].iloc[11] - 1.01 ** 2) > 1e-12:
        f.append("sleeve levels compound from the first return")
    # trend: 2-close confirmation in and out
    up = pd.Series(np.r_[np.linspace(100, 150, 250), np.linspace(150, 90, 150)], index=idx)
    t = trend_states(pd.DataFrame({"X": up}), ["X"])["X"]
    first_in = t.idxmax()
    if first_in != idx[200]:                                 # MA exists from bar 199; 2nd close above is bar 200
        f.append(f"in trend on the 2nd close above the 200-day: {first_in}")
    ma = up.rolling(200).mean()
    below = (up < ma)
    k_out = int(np.argmax((below & below.shift(1, fill_value=False)).to_numpy()))
    if t.iloc[k_out] or not t.iloc[k_out - 1]:
        f.append("out of trend on the 2nd close below")
    if trend_states(pd.DataFrame({"X": up}), ["MISSING"])["MISSING"].any():
        f.append("a sleeve with no data is never in trend")
    # gate
    g = gate({"SGOV": 45.0, "GLD": 20.0, "TLT": 20.0, "DBMF": 15.0}, ("GLD", "TLT", "DBMF"), {"GLD": True, "TLT": False, "DBMF": False})
    if g != {"SGOV": 80.0, "GLD": 20.0} or abs(sum(g.values()) - 100) > 1e-9:
        f.append(f"falling sleeves move to SGOV: {g}")
    if gate({"SGOV": 50.0, "USFR": 50.0}, ("SGOV", "USFR"), {}) != {"SGOV": 50.0, "USFR": 50.0}:
        f.append("cash sleeves are exempt")
    # weights: lag on both the state and the trend gate
    days = pd.bdate_range("2021-01-04", periods=4)
    st = pd.Series(["BAL", "DEF", "DEF", "OFF"], index=days, dtype=object)
    tr = pd.DataFrame({"TLT": [True, True, False, False], "GLD": True}, index=days)
    cand = CANDIDATES["D2"]
    bal = {"VGT": 50.0, "SGOV": 50.0}
    w = weights_fn(st, tr, cand, bal)
    if w(days[1]) != bal:
        f.append("day 2 trades day 1's state (Balanced)")
    w2 = w(days[2])
    if w2.get("TLT") != 20.0 or w2.get("DBMF") is not None:
        f.append(f"day 3: Defense with TLT still in trend as of day 2, DBMF out (no data): {w2}")
    w3 = w(days[3])
    if "TLT" in w3:
        f.append(f"day 4: TLT left the trend on day 3, so it is in SGOV: {w3}")
    wb = weights_fn(pd.Series(["BAL"] * 4, index=days, dtype=object),
                    pd.DataFrame({"VGT": [True, False, False, False]}, index=days), CANDIDATES["B1"], bal)
    if wb(days[1]) != bal or wb(days[2]) != {"SGOV": 100.0}:
        f.append(f"B1 gates every Balanced sleeve: {wb(days[1])}, {wb(days[2])}")
    if weights_fn(st, tr, CANDIDATES["D1"], bal)(days[3]).get("GLD") != 20.0:
        f.append("D1 gates only TLT (GLD held regardless)")
    # end-to-end on synthetic data: D0 reproduces O11 exactly; candidates run
    closes = ol._synthetic()
    data = ol.build_data(closes)
    balanced = {"SGOV": 40.0, "TLT": 30.0, "GLD": 30.0}
    o11 = ol.run_candidate("O11", data, balanced)
    b0 = run(data, {"defense": D0, "gate_def": (), "gate_bal": False}, balanced)
    if float((b0["nav"] / o11["nav"] - 1).abs().max()) > 1e-9:
        f.append("D0 must reproduce offense_lab O11 exactly")
    r2 = run(data, CANDIDATES["D2"], balanced)
    defd = r2["states"].shift(1).reindex(r2["weights"].index) == "DEF"
    held = r2["weights"][defd]
    if len(held) and not all(abs(sum(x.values()) - 100) < 1e-6 for x in held):
        f.append("Defense weights must sum to 100")
    # spells
    nav = pd.Series([100, 101, 99, 98, 100, 102.0], index=pd.bdate_range("2001-01-01", periods=6))
    sts = pd.Series(["BAL", "DEF", "DEF", "BAL", "DEF", "DEF"], index=nav.index, dtype=object)
    sp = spells(sts, nav, "DEF", start="2001-01-01")
    if list(sp["return_pct"].round(2)) != [round((98 / 101 - 1) * 100, 2), round((102 / 100 - 1) * 100, 2)] or list(sp["sessions"]) != [2, 1]:
        f.append(f"spell returns with the one-session lag: {sp.to_dict('records')}")
    # bars
    def mk(full, h1, h2, dd, y22, ep):
        return {"summ": {"full": {"cagr_pct": full, "max_dd_pct": dd}, "2005-15": {"cagr_pct": h1},
                         "2016-26": {"cagr_pct": h2}}, "y2022": y22, "ep10": ep}
    base = mk(9.36, 5.38, 14.40, -19.3, -11.0, 12)
    if bar("D2", mk(9.40, 5.30, 14.40, -19.0, -8.5, 12), base):
        f.append(f"a D candidate meeting every clause passes: {bar('D2', mk(9.40, 5.30, 14.40, -19.0, -8.5, 12), base)}")
    if not bar("D2", mk(9.40, 5.30, 14.40, -19.0, -9.5, 12), base):
        f.append("2022 must be at least 2 points better")
    if not bar("D1", mk(9.40, 5.20, 14.40, -19.0, -8.0, 12), base):
        f.append("a half more than 0.10 below O11 fails")
    if not bar("B1", mk(9.40, 5.38, 14.40, -19.0, -11.0, 12), base) or bar("B1", mk(9.40, 5.38, 14.40, -19.0, -11.0, 11), base):
        f.append("B1 needs fewer −10% episodes, not the 2022 clause")
    if not bar("D2", mk(9.40, 5.38, 14.40, -19.5, -8.0, 12), base):
        f.append("a deeper max drawdown fails")
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        res = selftest()
        print(json.dumps(res, indent=2, default=str))
        sys.exit(0 if res["ok"] else 1)
    sys.exit(main())
