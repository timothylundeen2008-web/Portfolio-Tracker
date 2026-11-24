"""
r1_lab.py  (v1.0 — 2026-11-23)
───────────────────────────────
LONG-TERM book only. Pre-registered test R1 (claude/r1_lab_2026-11-23.md; proposed in
claude/system_review_2026-11-14.md §6.2; Matt 2026-11-23: "Yes to building 1, 2, and 3").
Bars are fixed BEFORE any run on real prices; a FAIL is final.

R1 = the live O11 engine with ONE change: after a FAST exit (state OUT: QQQ below its 50-day with
credit confirming, or the −8% Offense stop), Offense may resume BEFORE the 20-session cooldown is
up when breadth thrusts: at least K of the 9 original sector ETFs close above their 50-day SMA on
2 consecutive closes, AND SPY and QQQ close above their 200-day SMA on 2 consecutive closes.
Everything else is O11 exactly (offense_lab.states_fast, credit=True): same books, 1-session lag,
5bp costs, the same Balanced (regime) book, history from 2000.

  K = 7 of 9 (decision; the 11-14 spec's "9 of 11" scaled to the 9 sectors with 2000+ history).
  K = 6 and K = 8: stability neighbours.

Guard: with K = 10 (never true) the R1 state machine must reproduce O11's states and NAV exactly.

Run:  python r1_lab.py            (Actions; needs yfinance)
      python r1_lab.py --selftest (offline)
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import hedge_lab as hl
import offense_lab as ol

VERSION = "1.0"
OUT_DIR, LOG_DIR = Path("data/r1_lab"), Path("logs/r1_lab")
K_DECISION, K_NEIGHBOURS = 7, (6, 8)
BREADTH_SMA = 50
TRIALS_BEFORE, TRIALS_HERE = 34, 3
BAR = {"half_05_15_gain": 0.5, "half_16_26_tol": 0.25, "max_dd": -20.0, "lag_pts": 10.0}


def breadth_up2(levels: pd.DataFrame, k: int) -> pd.Series:
    """True on a close where >= k of the 9 sectors are above their 50-day, for the 2nd close running.
    A sector without a known 50-day counts as not above; all 9 must be known."""
    ups = pd.DataFrame({t: ol.above_ma(levels[t], BREADTH_SMA) for t in ol.SECTORS9})
    known = ups.notna().all(axis=1)
    cnt = ups.fillna(False).astype(int).sum(axis=1)
    ok = known & (cnt >= k)
    return ok & ok.shift(1, fill_value=False)


def states_r1(levels: pd.DataFrame, rets: pd.DataFrame, k: int, ma: int = ol.MA, fast_sma: int = ol.FAST_SMA,
              fast_stop: float = ol.FAST_STOP, cooldown: int = ol.COOLDOWN) -> tuple:
    """offense_lab.states_fast(credit=True) with one added branch: in OUT before the cooldown ends,
    a breadth thrust (above) re-enters Offense. Returns (states, list of early re-entry dates)."""
    spy_up, qqq_up = ol.above_ma(levels["SPY"], ma), ol.above_ma(levels["QQQ"], ma)
    q50 = ol.above_ma(levels["QQQ"], fast_sma)
    known = spy_up.notna() & qqq_up.notna() & q50.notna()
    spy_dn2, qqq_dn2, q50_dn2 = ol._two_down(spy_up).to_numpy(), ol._two_down(qqq_up).to_numpy(), ol._two_down(q50).to_numpy()
    entry = (ol._two_up(spy_up) & ol._two_up(qqq_up) & ol._two_up(q50)).to_numpy()
    spy_up2, qqq_up2 = ol._two_up(spy_up).to_numpy(), ol._two_up(qqq_up).to_numpy()
    c_up = ol.above_ma(levels["CREDIT"], ol.CREDIT_SMA) if "CREDIT" in levels else pd.Series(np.nan, index=levels.index)
    c_ok = (ol._two_down(c_up) | c_up.isna()).to_numpy()
    thrust = breadth_up2(levels, k).to_numpy()
    r = rets.reindex(levels.index)
    idx = (1 + 0.5 * r["SPY"].fillna(0.0) + 0.5 * r["QQQ"].fillna(0.0)).cumprod().to_numpy()
    out, state, peak, out_i, early = [], "BAL", None, -10 ** 9, []
    kn = known.to_numpy()
    for i in range(len(levels)):
        if not kn[i]:
            out.append(state); continue
        if spy_dn2[i]:
            state = "DEF"
        elif state == "OFF":
            peak = max(peak, idx[i])
            if (q50_dn2[i] and c_ok[i]) or (idx[i] / peak - 1) * 100 <= fast_stop:
                state, out_i = "OUT", i
            elif qqq_dn2[i]:
                state = "BAL"
        elif entry[i] and (state != "OUT" or i - out_i >= cooldown):
            state, peak = "OFF", idx[i]
        elif state == "OUT" and i - out_i < cooldown and thrust[i] and spy_up2[i] and qqq_up2[i]:
            state, peak = "OFF", idx[i]                                  # R1: breadth-thrust re-entry
            early.append(levels.index[i])
        elif state == "DEF" and spy_up2[i]:
            state = "BAL"
        out.append(state)
    return pd.Series(out, index=levels.index, dtype=object), early


def run(data: dict, balanced: dict, k: int) -> dict:
    st, early = states_r1(data["levels"], data["rets"], k)
    cand = ol.CANDIDATES["O11"]
    days = data["cal"][data["cal"] >= pd.Timestamp(ol.EVAL_START) - pd.Timedelta(days=10)]
    sim = hl.simulate(days, data["rets"], ol.weights_fn(st, cand, balanced), None, breaker=False, cost_bps=ol.COST_BPS)
    return {"nav": sim["nav"], "states": st, "early": early}


def judge(nav: pd.Series, spy_nav: pd.Series) -> dict:
    s = ol.summary(nav)
    yr, ys = ol.year_returns(nav), ol.year_returns(spy_nav)
    both = pd.DataFrame({"book": yr, "spy": ys}).dropna()
    down = both[both.spy < 0]
    up = both[both.spy >= 0]
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

    if not ge("2005-15", "cagr_pct", BAR["half_05_15_gain"]):
        why.append(f"2005-15 CAGR {g(s, '2005-15', 'cagr_pct')}% < O11 {g(b, '2005-15', 'cagr_pct')}% + {BAR['half_05_15_gain']}")
    if not ge("full", "cagr_pct", 0.0):
        why.append(f"full CAGR {g(s, 'full', 'cagr_pct')}% < O11 {g(b, 'full', 'cagr_pct')}%")
    if not ge("2016-26", "cagr_pct", -BAR["half_16_26_tol"]):
        why.append(f"2016-26 CAGR {g(s, '2016-26', 'cagr_pct')}% < O11 {g(b, '2016-26', 'cagr_pct')}% − {BAR['half_16_26_tol']}")
    dd = g(s, "full", "max_dd_pct")
    if dd is None or not dd > BAR["max_dd"]:
        why.append(f"max DD {dd}% deeper than {BAR['max_dd']}%")
    if full_bar:
        if c["down_years_beaten"] < c["down_years"]:
            why.append(f"beat SPY in {c['down_years_beaten']} of {c['down_years']} down years (needs all)")
        if len(c["up_lags_gt10"]) > len(base["up_lags_gt10"]):
            why.append(f"{len(c['up_lags_gt10'])} up years trailing SPY by >10 pts vs O11 {len(base['up_lags_gt10'])}")
    return why


def analyse(data: dict, balanced: dict) -> dict:
    o11 = ol.run_candidate("O11", data, balanced)
    g = run(data, balanced, 10)                                   # never true -> must be O11
    st_gap = int((g["states"] != o11["states"]).sum())
    nav_gap = float((g["nav"] / o11["nav"] - 1).abs().max())
    guard = st_gap == 0 and nav_gap < 1e-9 and not g["early"]
    spy_nav = (1 + data["rets"]["SPY"].reindex(o11["nav"].index).fillna(0.0)).cumprod()
    base = judge(o11["nav"], spy_nav)
    res = {"O11": {**base, "early": [], "nav": o11["nav"]}}
    for k in (K_DECISION, *K_NEIGHBOURS):
        r = run(data, balanced, k)
        res[f"K{k}"] = {**judge(r["nav"], spy_nav), "early": [d.date().isoformat() for d in r["early"]], "nav": r["nav"]}
    dec = res[f"K{K_DECISION}"]
    why = bar(dec, base)
    nb = {f"K{k}": bar(res[f"K{k}"], base, full_bar=False) for k in K_NEIGHBOURS}
    stable = all(not v for v in nb.values())
    verdict = "FAIL" if why else ("PASS (stable)" if stable else "PASS (not stable)")
    return {"version": VERSION, "verdict": verdict, "fails": why, "neighbours": nb, "stable": stable,
            "guard": {"ok": bool(guard), "state_diffs": st_gap, "nav_gap": nav_gap}, "res": res,
            "spy": ol.summary(spy_nav)}


def _c(x):
    return "—" if x is None else f"{x:.2f}%"


def render(a: dict, stamp: str) -> str:
    res = a["res"]
    cols = ["O11", f"K{K_DECISION}", *[f"K{k}" for k in K_NEIGHBOURS]]
    L = [f"# R1 lab {VERSION} — breadth-thrust re-entry — {stamp}", "",
         f"Pre-registered in `claude/r1_lab_2026-11-23.md`. Long-term engine trials {TRIALS_BEFORE} → "
         f"{TRIALS_BEFORE + TRIALS_HERE}. Research, not personalized advice.", "",
         f"## R1 (K = {K_DECISION} of 9): **{a['verdict']}**", "",
         f"- Fails: {'; '.join(a['fails']) or 'none'}",
         "- Neighbours (bars 1–4): " + "; ".join(f"{k}: {'meets' if not v else '; '.join(v)}" for k, v in a["neighbours"].items()),
         f"- Guard (K = 10 reproduces O11 exactly): {'yes' if a['guard']['ok'] else '**NO — result not valid**'} "
         f"({a['guard']['state_diffs']} state diffs, NAV gap {a['guard']['nav_gap']:.1e})", "",
         "| | " + " | ".join(cols) + " | SPY |", "|---" * (len(cols) + 2) + "|"]
    for h in ("full", "2005-15", "2016-26"):
        L.append(f"| CAGR {h} | " + " | ".join(_c(res[c]["summ"][h].get("cagr_pct")) for c in cols) +
                 f" | {_c(a['spy'][h].get('cagr_pct'))} |")
    L.append("| Max DD | " + " | ".join(_c(res[c]["summ"]["full"].get("max_dd_pct")) for c in cols) +
             f" | {_c(a['spy']['full'].get('max_dd_pct'))} |")
    L.append("| Down years beaten | " + " | ".join(f"{res[c]['down_years_beaten']} of {res[c]['down_years']}" for c in cols) + " | — |")
    L.append("| Up years >10 pts behind | " + " | ".join(", ".join(map(str, res[c]["up_lags_gt10"])) or "none" for c in cols) + " | — |")
    L.append("| Losing years | " + " | ".join(", ".join(map(str, res[c]["losing_years"])) or "none" for c in cols) + " | — |")
    L.append("| Early re-entries | " + " | ".join(str(len(res[c]["early"])) for c in cols) + " | — |")
    k = f"K{K_DECISION}"
    if res[k]["early"]:
        L += ["", f"**K = {K_DECISION} early re-entries:** " + ", ".join(res[k]["early"])]
    yb, yk = res["O11"]["years"], res[k]["years"]
    diff = (yk["book"] - yb["book"]).round(1)
    moved = diff[diff.abs() >= 0.1]
    if len(moved):
        L += ["", f"**Years that changed vs O11 (points):** " + ", ".join(f"{d.year} {v:+.1f}" for d, v in moved.items())]
    L += ["", f"*r1_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def write_outputs(a: dict, stamp: str, out_dir: Path = OUT_DIR, log_dir: Path = LOG_DIR) -> str:
    md = render(a, stamp)
    navs = pd.DataFrame({k: v["nav"] for k, v in a["res"].items()})
    years = pd.DataFrame({k: v["years"]["book"] for k, v in a["res"].items()})
    years["SPY"] = a["res"]["O11"]["years"]["spy"]
    js = {"version": VERSION, "asof": stamp, "verdict": a["verdict"], "fails": a["fails"], "neighbours": a["neighbours"],
          "stable": a["stable"], "guard": a["guard"], "trials": TRIALS_BEFORE + TRIALS_HERE, "spy": a["spy"],
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
    tickers = sorted(set(hl.all_tickers()) | set(ol.EXTRA_TICKERS))
    closes = (fetch or hl.yf_fetch)(tickers, start=ol.HISTORY_START)
    missing = [t for t in ("SPY", "QQQ", *ol.SECTORS9, "^IRX", *ol.CREDIT_PAIR) if t not in closes]
    print(f"[r1_lab] {VERSION}: {len(closes)} of {len(tickers)} tickers; required missing: {missing}")
    if missing:
        print("[r1_lab] DATA FAILURE: a signal input is missing; nothing written.")
        return 1
    import regime_classifier as rc
    balanced = {k: float(v) for k, v in rc.target_weights(hl.REGIME, gate=False).items()}
    data = ol.build_data(closes)
    a = analyse(data, balanced)
    if not a["guard"]["ok"]:
        print("[r1_lab] GUARD FAILED: K = 10 does not reproduce O11; nothing written.")
        return 1
    print(write_outputs(a, stamp))
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    import contextlib, io, os, tempfile
    f = []
    closes = ol._synthetic()
    data = ol.build_data(closes)
    balanced = {"SGOV": 40.0, "TLT": 30.0, "GLD": 30.0}
    base = ol.states_fast(data["levels"], data["rets"], credit=True)
    s10, e10 = states_r1(data["levels"], data["rets"], 10)
    if not s10.equals(base) or e10:
        f.append("K = 10 must reproduce O11's states exactly")
    s7, e7 = states_r1(data["levels"], data["rets"], 7)
    s0, e0 = states_r1(data["levels"], data["rets"], 0)
    if not e0:
        f.append("fixture: K = 0 should produce early re-entries")
    for kk in (0, 5, 7, 8, 9):
        sk, ek = states_r1(data["levels"], data["rets"], kk)
        prev = sk.shift(1)
        if any(prev.get(d) != "OUT" for d in ek):
            f.append(f"K={kk}: early re-entries must come only from OUT")
            break
        pos = {d: i for i, d in enumerate(sk.index)}
        late = []
        for d in ek:                               # inside the cooldown: OUT began < 20 sessions earlier
            i = pos[d]
            j = i - 1
            while j >= 0 and sk.iloc[j] == "OUT":
                j -= 1
            if i - (j + 1) >= ol.COOLDOWN:
                late.append(d)
        if late:
            f.append(f"K={kk}: early re-entry on {late[0].date()} after the cooldown")
            break
    # early re-entry only inside the cooldown, and only with SPY and QQQ 2 closes above 200d + breadth
    lv = data["levels"]
    su2 = ol._two_up(ol.above_ma(lv["SPY"], ol.MA))
    qu2 = ol._two_up(ol.above_ma(lv["QQQ"], ol.MA))
    for d in e7:
        if not (su2[d] and qu2[d] and breadth_up2(lv, 7)[d]):
            f.append(f"early re-entry on {d.date()} without the full condition")
            break
    # states differ from O11 only from an early re-entry onwards
    if e7:
        first = min(e7)
        if (s7[s7.index < first] != base[base.index < first]).any():
            f.append("R1 must equal O11 before its first early re-entry")
    # breadth needs 2 closes and all 9 known
    t = pd.DataFrame({s: [1.0] * 60 for s in ol.SECTORS9}, index=pd.bdate_range("2020-01-01", periods=60))
    t.iloc[-1, 0] = 0.0
    lv2 = t.copy(); lv2.iloc[-2:] = 2.0
    b = breadth_up2(lv2, 9)
    if not bool(b.iloc[-1]) or bool(b.iloc[-2]):
        f.append("breadth_up2: true only on the 2nd close above")
    lv3 = lv2.copy(); lv3.iloc[:, 3] = np.nan
    if bool(breadth_up2(lv3, 1).iloc[-1]):
        f.append("breadth_up2: an unknown sector must block")
    # hand-built case: the fast exit at ~day 300, sectors fall below their 50-day, then recover only AFTER
    # the cooldown while QQQ stays below its 50-day: R1 must NOT re-enter; inside the cooldown it must.
    def case(jump_day):
        n = 420
        ix = pd.bdate_range("2001-01-01", periods=n)
        up = np.linspace(100, 200, n)
        q = up.copy(); q[300:] = up[299] * 0.90
        sec = up.copy(); sec[300:] = up[299] * 0.85; sec[jump_day:] = up[299] * 1.30
        cr = np.linspace(100, 120, n); cr[290:] = np.linspace(cr[289], cr[289] * 0.9, n - 290)
        lvx = pd.DataFrame({"SPY": up, "QQQ": q, "CREDIT": cr, **{t: sec for t in ol.SECTORS9}}, index=ix)
        rx = pd.DataFrame({"SPY": 0.0, "QQQ": 0.0}, index=ix)
        return states_r1(lvx, rx, 7)
    st_late, e_late = case(330)
    st_early, e_early = case(310)
    if "OUT" not in set(st_late.iloc[295:310]):
        f.append("hand case: the fast exit must happen")
    if e_late:
        f.append(f"hand case: no early re-entry after the cooldown (got {e_late[0].date()})")
    if not e_early:
        f.append("hand case: a thrust inside the cooldown must re-enter")
    # bar logic
    def fake(c05, cf, c16, dd, dyb=6, lags=3):
        return {"summ": {"full": {"cagr_pct": cf, "max_dd_pct": dd}, "2005-15": {"cagr_pct": c05}, "2016-26": {"cagr_pct": c16}},
                "down_years_beaten": dyb, "down_years": 6, "up_lags_gt10": list(range(lags))}
    o = fake(5.38, 9.36, 14.40, -19.3)
    if bar(fake(5.9, 9.4, 14.2, -19.0), o):
        f.append("bar: a clean pass must pass")
    for bad, why in ((fake(5.8, 9.4, 14.4, -19.0), "05-15 +0.42 < 0.5"), (fake(5.9, 9.3, 14.4, -19.0), "full lower"),
                     (fake(5.9, 9.4, 14.1, -19.0), "16-26 −0.3"), (fake(5.9, 9.4, 14.4, -20.1), "DD"),
                     (fake(5.9, 9.4, 14.4, -19.0, dyb=5), "down year"), (fake(5.9, 9.4, 14.4, -19.0, lags=4), "lags")):
        if not bar(bad, o):
            f.append(f"bar must fail: {why}")
    # analyse + writer + abort on the fixture
    tmp = Path(tempfile.mkdtemp())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            a = analyse(data, balanced)
        if not a["guard"]["ok"]:
            f.append(f"analyse: guard must hold on the fixture {a['guard']}")
        md = write_outputs(a, "2026-11-23", tmp / "d", tmp / "l")
        js = json.loads((tmp / "d" / "summary.json").read_text())
        if js["verdict"] not in ("FAIL", "PASS (stable)", "PASS (not stable)") or "R1" not in md or not (tmp / "d" / "years.csv").exists():
            f.append("writer: outputs incomplete")
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc_ = main(fetch=lambda tks, start=None: {})
            if rc_ != 1 or (tmp / "data" / "r1_lab").exists():
                f.append("main: missing data must stop with nothing written")
        finally:
            os.chdir(cwd)
    except Exception as e:
        f.append(f"analyse/writer crashed: {type(e).__name__}: {e}")
    return {"ok": not f, "failures": f, "version": VERSION, "fixture_early": {"K0": len(e0), "K7": len(e7)}}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r_ = selftest()
        print(json.dumps(r_, indent=2, default=str))
        sys.exit(0 if r_["ok"] else 1)
    sys.exit(main())
