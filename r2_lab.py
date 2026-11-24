"""
r2_lab.py  (v1.0 — 2026-11-24)
───────────────────────────────
LONG-TERM book only. Pre-registered test R2 (claude/r2_lab_2026-11-24.md; Matt 2026-11-24: "start with
2 and then 3"). Bars are fixed BEFORE any run on real prices; a FAIL is final.

Diagnosis (2026-11-24, from saved NAVs): O11's up-year lags (2006 −12.9, 2015 −13.4, 2019 −14.3 pts vs
SPY) came mostly from DEFENSE days (−7.5, −8.7, −12.2 log-pts). Of 50 Defense spells, the 41 lasting
<= 40 sessions cost ~88 pts vs SPY (whipsaws); the 5 long bear spells earned ~+85.

R2 = the live O11 engine with ONE change: Defense is entered only when SPY has closed below its 200-day
on 2 consecutive closes (as now) AND SPY's 200-day SMA is below its own value L sessions earlier
(a falling trend, not a dip under a rising one). If SPY is below a RISING 200-day, the other O11 rules
act as now (QQQ 2 closes below its 200-day -> Balanced; the 50-day / −8% fast exit -> OUT). Once in
Defense, the exit is unchanged (SPY 2 closes back above its 200-day -> Balanced).

  L = 20 sessions (decision). L = 10 and L = 40: stability neighbours.

Guard: with the slope filter off, the R2 machine must reproduce O11's states and NAV exactly.

Run:  python r2_lab.py            (Actions; needs yfinance)
      python r2_lab.py --selftest (offline)
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import hedge_lab as hl
import offense_lab as ol

VERSION = "1.0"
OUT_DIR, LOG_DIR = Path("data/r2_lab"), Path("logs/r2_lab")
K_DECISION, K_NEIGHBOURS = 20, (10, 40)        # slope lookback L (sessions)
TRIALS_BEFORE, TRIALS_HERE = 37, 3
BAR = {"half_05_15_gain": 0.0, "half_16_26_tol": 0.25, "full_gain": 0.0, "max_dd": -20.0, "lag_pts": 10.0}


def ma_falling(level: pd.Series, ma: int, lookback: Optional[int]) -> pd.Series:
    """True where the `ma`-day SMA is below its own value `lookback` sessions earlier.
    lookback None = filter off (always True), which must reproduce O11."""
    if lookback is None:
        return pd.Series(True, index=level.index)
    m = level.rolling(ma, min_periods=ma).mean()
    return (m < m.shift(lookback)).fillna(False)


def states_r2(levels: pd.DataFrame, rets: pd.DataFrame, lookback: Optional[int], ma: int = ol.MA,
              fast_sma: int = ol.FAST_SMA, fast_stop: float = ol.FAST_STOP, cooldown: int = ol.COOLDOWN) -> tuple:
    """offense_lab.states_fast(credit=True) with one change: the Defense branch also needs SPY's 200-day
    to be falling. Returns (states, list of dates a Defense entry was blocked by the filter)."""
    spy_up, qqq_up = ol.above_ma(levels["SPY"], ma), ol.above_ma(levels["QQQ"], ma)
    q50 = ol.above_ma(levels["QQQ"], fast_sma)
    known = spy_up.notna() & qqq_up.notna() & q50.notna()
    spy_dn2, qqq_dn2, q50_dn2 = ol._two_down(spy_up).to_numpy(), ol._two_down(qqq_up).to_numpy(), ol._two_down(q50).to_numpy()
    entry = (ol._two_up(spy_up) & ol._two_up(qqq_up) & ol._two_up(q50)).to_numpy()
    spy_up2 = ol._two_up(spy_up).to_numpy()
    c_up = ol.above_ma(levels["CREDIT"], ol.CREDIT_SMA) if "CREDIT" in levels else pd.Series(np.nan, index=levels.index)
    c_ok = (ol._two_down(c_up) | c_up.isna()).to_numpy()
    falling = ma_falling(levels["SPY"], ma, lookback).to_numpy()
    r = rets.reindex(levels.index)
    idx = (1 + 0.5 * r["SPY"].fillna(0.0) + 0.5 * r["QQQ"].fillna(0.0)).cumprod().to_numpy()
    out, state, peak, out_i, blocked = [], "BAL", None, -10 ** 9, []
    kn = known.to_numpy()
    for i in range(len(levels)):
        if not kn[i]:
            out.append(state); continue
        if spy_dn2[i] and falling[i]:                                   # R2: Defense needs a falling 200-day
            state = "DEF"
        else:
            if spy_dn2[i] and state != "DEF":
                blocked.append(levels.index[i])
            if state == "OFF":
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
    return pd.Series(out, index=levels.index, dtype=object), blocked


def def_spells(st: pd.Series, nav: pd.Series, spy_nav: pd.Series) -> pd.DataFrame:
    """Defense spells from EVAL_START: sessions, book and SPY return over the spell (from the prior close)."""
    st = st[st.index >= pd.Timestamp(ol.EVAL_START)]
    rows, start = [], None
    prev = None
    for d, s in st.items():
        if s == "DEF" and prev != "DEF":
            start = d
        if prev == "DEF" and s != "DEF" and start is not None:
            rows.append((start, last))
        prev, last = s, d
    if prev == "DEF" and start is not None:
        rows.append((start, last))
    out = []
    for a, b in rows:
        i = nav.index.searchsorted(a)
        p = nav.index[max(i - 1, 0)]
        out.append({"from": a.date().isoformat(), "to": b.date().isoformat(),
                    "sessions": int(((st.index >= a) & (st.index <= b)).sum()),
                    "book_pct": round((nav.asof(b) / nav.asof(p) - 1) * 100, 2),
                    "spy_pct": round((spy_nav.asof(b) / spy_nav.asof(p) - 1) * 100, 2)})
    return pd.DataFrame(out, columns=["from", "to", "sessions", "book_pct", "spy_pct"])


def run(data: dict, balanced: dict, k: Optional[int]) -> dict:
    st, blocked = states_r2(data["levels"], data["rets"], k)
    cand = ol.CANDIDATES["O11"]
    days = data["cal"][data["cal"] >= pd.Timestamp(ol.EVAL_START) - pd.Timedelta(days=10)]
    sim = hl.simulate(days, data["rets"], ol.weights_fn(st, cand, balanced), None, breaker=False, cost_bps=ol.COST_BPS)
    return {"nav": sim["nav"], "states": st, "blocked": blocked}


def judge(nav: pd.Series, spy_nav: pd.Series, st: pd.Series) -> dict:
    s = ol.summary(nav)
    yr, ys = ol.year_returns(nav), ol.year_returns(spy_nav)
    both = pd.DataFrame({"book": yr, "spy": ys}).dropna()
    down = both[both.spy < 0]
    up = both[both.spy >= 0]
    sp = def_spells(st, nav, spy_nav)
    short = sp[sp.sessions <= 40]
    return {"summ": s, "years": both, "spells": sp,
            "down_years_beaten": int((down.book > down.spy).sum()), "down_years": int(len(down)),
            "up_lags_gt10": [int(d.year) for d, r in up.iterrows() if r.book - r.spy < -BAR["lag_pts"]],
            "losing_years": [int(d.year) for d, r in both.iterrows() if r.book < 0],
            "def_spells": int(len(sp)), "short_spells": int(len(short)),
            "short_spell_cost_pts": round(float((short.book_pct - short.spy_pct).sum()), 1) if len(short) else 0.0}


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
        if not len(c["up_lags_gt10"]) < len(base["up_lags_gt10"]):
            why.append(f"{len(c['up_lags_gt10'])} up years trailing SPY by >10 pts; needs fewer than O11's {len(base['up_lags_gt10'])}")
        if len(c["losing_years"]) > len(base["losing_years"]):
            why.append(f"{len(c['losing_years'])} losing years vs O11's {len(base['losing_years'])}")
    return why


def analyse(data: dict, balanced: dict) -> dict:
    o11 = ol.run_candidate("O11", data, balanced)
    g = run(data, balanced, None)                                  # filter off -> must be O11
    st_gap = int((g["states"] != o11["states"]).sum())
    nav_gap = float((g["nav"] / o11["nav"] - 1).abs().max())
    guard = st_gap == 0 and nav_gap < 1e-9
    spy_nav = (1 + data["rets"]["SPY"].reindex(o11["nav"].index).fillna(0.0)).cumprod()
    base = judge(o11["nav"], spy_nav, o11["states"])
    res = {"O11": {**base, "blocked": [], "nav": o11["nav"]}}
    for k in (K_DECISION, *K_NEIGHBOURS):
        r = run(data, balanced, k)
        res[f"L{k}"] = {**judge(r["nav"], spy_nav, r["states"]), "nav": r["nav"],
                        "blocked": sorted({d.date().isoformat()[:7] for d in r["blocked"]})}
    dec = res[f"L{K_DECISION}"]
    why = bar(dec, base)
    nb = {f"L{k}": bar(res[f"L{k}"], base, full_bar=False) for k in K_NEIGHBOURS}
    stable = all(not v for v in nb.values())
    verdict = "FAIL" if why else ("PASS (stable)" if stable else "PASS (not stable)")
    return {"version": VERSION, "verdict": verdict, "fails": why, "neighbours": nb, "stable": stable,
            "guard": {"ok": bool(guard), "state_diffs": st_gap, "nav_gap": nav_gap}, "res": res,
            "spy": ol.summary(spy_nav)}


def _c(x):
    return "—" if x is None else f"{x:.2f}%"


def render(a: dict, stamp: str) -> str:
    res = a["res"]
    cols = ["O11", f"L{K_DECISION}", *[f"L{k}" for k in K_NEIGHBOURS]]
    L = [f"# R2 lab {VERSION} — Defense only on a falling 200-day — {stamp}", "",
         f"Pre-registered in `claude/r2_lab_2026-11-24.md`. Long-term engine trials {TRIALS_BEFORE} → "
         f"{TRIALS_BEFORE + TRIALS_HERE}. Research, not personalized advice.", "",
         f"## R2 (L = {K_DECISION} sessions): **{a['verdict']}**", "",
         f"- Fails: {'; '.join(a['fails']) or 'none'}",
         "- Neighbours (bars 1–4): " + "; ".join(f"{k}: {'meets' if not v else '; '.join(v)}" for k, v in a["neighbours"].items()),
         f"- Guard (filter off reproduces O11 exactly): {'yes' if a['guard']['ok'] else '**NO — result not valid**'} "
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
    L.append("| Defense spells (≤ 40 sessions) | " + " | ".join(f"{res[c]['def_spells']} ({res[c]['short_spells']})" for c in cols) + " | — |")
    L.append("| Short spells' cost vs SPY, pts | " + " | ".join(f"{res[c]['short_spell_cost_pts']:+.1f}" for c in cols) + " | — |")
    k = f"L{K_DECISION}"
    if res[k]["blocked"]:
        L += ["", f"**L = {K_DECISION}: months with a blocked Defense entry (SPY below a rising 200-day):** " + ", ".join(res[k]["blocked"])]
    yb, yk = res["O11"]["years"], res[k]["years"]
    diff = (yk["book"] - yb["book"]).round(1)
    moved = diff[diff.abs() >= 0.1]
    if len(moved):
        L += ["", "**Years that changed vs O11 (points):** " + ", ".join(f"{d.year} {v:+.1f}" for d, v in moved.items())]
    big = res[k]["spells"]
    big = big[big.sessions > 40]
    if len(big):
        L += ["", f"**L = {K_DECISION} long Defense spells (> 40 sessions):** " +
              "; ".join(f"{r['from']} → {r['to']} ({r['sessions']}): book {r['book_pct']:+.1f}%, SPY {r['spy_pct']:+.1f}%" for _i, r in big.iterrows())]
    L += ["", f"*r2_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def write_outputs(a: dict, stamp: str, out_dir: Path = OUT_DIR, log_dir: Path = LOG_DIR) -> str:
    md = render(a, stamp)
    navs = pd.DataFrame({k: v["nav"] for k, v in a["res"].items()})
    years = pd.DataFrame({k: v["years"]["book"] for k, v in a["res"].items()})
    years["SPY"] = a["res"]["O11"]["years"]["spy"]
    js = {"version": VERSION, "asof": stamp, "verdict": a["verdict"], "fails": a["fails"], "neighbours": a["neighbours"],
          "stable": a["stable"], "guard": a["guard"], "trials": TRIALS_BEFORE + TRIALS_HERE, "spy": a["spy"],
          "books": {k: {kk: (vv.to_dict("records") if kk == "spells" else vv) for kk, vv in v.items() if kk not in ("nav", "years")}
                    for k, v in a["res"].items()}}
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
    missing = [t for t in ("SPY", "QQQ", "^IRX", *ol.CREDIT_PAIR) if t not in closes]
    print(f"[r2_lab] {VERSION}: {len(closes)} of {len(tickers)} tickers; required missing: {missing}")
    if missing:
        print("[r2_lab] DATA FAILURE: a signal input is missing; nothing written.")
        return 1
    import regime_classifier as rc
    balanced = {k: float(v) for k, v in rc.target_weights(hl.REGIME, gate=False).items()}
    data = ol.build_data(closes)
    a = analyse(data, balanced)
    if not a["guard"]["ok"]:
        print("[r2_lab] GUARD FAILED: the filter off does not reproduce O11; nothing written.")
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
    lv = data["levels"]
    base = ol.states_fast(lv, data["rets"], credit=True)
    s0, b0 = states_r2(lv, data["rets"], None)
    if not s0.equals(base) or b0:
        f.append("filter off must reproduce O11's states exactly")
    s20, b20 = states_r2(lv, data["rets"], 20)
    if not b20:
        f.append("fixture: L = 20 should block some Defense entries")
    fall = ma_falling(lv["SPY"], ol.MA, 20)
    sdn = ol._two_down(ol.above_ma(lv["SPY"], ol.MA))
    # every DEF entry under R2 has SPY 2 closes below AND a falling 200-day
    ent = s20[(s20 == "DEF") & (s20.shift(1) != "DEF")].index
    if any(not (sdn[d] and fall[d]) for d in ent):
        f.append("a Defense entry without the full condition")
    if not len(ent):
        f.append("fixture: R2 should still enter Defense sometimes")
    # blocked days really had a rising (not falling) 200-day
    if any(fall[d] for d in b20):
        f.append("a blocked day had a falling 200-day")
    # R2 equals O11 until the first blocked Defense entry
    if b20:
        first = min(b20)
        if (s20[s20.index < first] != base[base.index < first]).any():
            f.append("R2 must equal O11 before its first blocked entry")
    # once in Defense, R2 leaves only on SPY 2 closes back above its 200-day (as O11)
    sup2 = ol._two_up(ol.above_ma(lv["SPY"], ol.MA))
    ex = s20[(s20 != "DEF") & (s20.shift(1) == "DEF")].index
    if any(not sup2[d] for d in ex):
        f.append("Defense exit without SPY 2 closes above its 200-day")
    # ma_falling semantics
    up = pd.Series(np.linspace(1, 300, 400), index=pd.bdate_range("2001-01-01", periods=400))
    if bool(ma_falling(up, 200, 20).iloc[-1]) or not bool(ma_falling(up[::-1].set_axis(up.index), 200, 20).iloc[-1]):
        f.append("ma_falling: rising line not falling, falling line falling")
    if bool(ma_falling(up, 200, 20).iloc[150]):
        f.append("ma_falling: unknown 200-day counts as not falling")
    # hand-built case: SPY dips below a RISING 200-day -> no Defense; below a FALLING one -> Defense
    def case(kind):
        n = 420
        ix = pd.bdate_range("2001-01-01", periods=n)
        if kind == "dip":
            spy = np.linspace(100, 200, n); spy[380:395] = spy[379] * 0.80   # brief deep dip, 200-day still rising
        else:
            spy = np.r_[np.linspace(100, 200, 250), np.linspace(200, 120, n - 250)]   # trend turns down
        lvx = pd.DataFrame({"SPY": spy, "QQQ": spy, "CREDIT": np.linspace(100, 120, n)}, index=ix)
        rx = pd.DataFrame({"SPY": 0.0, "QQQ": 0.0}, index=ix)
        return states_r2(lvx, rx, 20)[0], ol.states_fast(lvx, rx, credit=True)
    r_dip, o_dip = case("dip")
    r_bear, o_bear = case("bear")
    if "DEF" not in set(o_dip) or "DEF" in set(r_dip):
        f.append("hand case: a dip under a rising 200-day must not reach Defense under R2 (O11 does)")
    if "DEF" not in set(r_bear):
        f.append("hand case: a falling 200-day must reach Defense")
    # bar logic
    def fake(c05, cf, c16, dd, dyb=6, lags=3, losing=6):
        return {"summ": {"full": {"cagr_pct": cf, "max_dd_pct": dd}, "2005-15": {"cagr_pct": c05}, "2016-26": {"cagr_pct": c16}},
                "down_years_beaten": dyb, "down_years": 6, "up_lags_gt10": list(range(lags)), "losing_years": list(range(losing))}
    o = fake(5.38, 9.35, 14.39, -19.3)
    if bar(fake(5.5, 9.6, 14.3, -19.0, lags=2), o):
        f.append("bar: a clean pass must pass")
    for bad, why in ((fake(5.3, 9.6, 14.4, -19.0, lags=2), "05-15 below"), (fake(5.5, 9.35, 14.4, -19.0, lags=2), "full not above"),
                     (fake(5.5, 9.6, 14.1, -19.0, lags=2), "16-26 −0.29"), (fake(5.5, 9.6, 14.4, -20.1, lags=2), "DD"),
                     (fake(5.5, 9.6, 14.4, -19.0, dyb=5, lags=2), "down year"), (fake(5.5, 9.6, 14.4, -19.0, lags=3), "lags not fewer"),
                     (fake(5.5, 9.6, 14.4, -19.0, lags=2, losing=7), "more losing years")):
        if not bar(bad, o):
            f.append(f"bar must fail: {why}")
    tmp = Path(tempfile.mkdtemp())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            a = analyse(data, balanced)
        if not a["guard"]["ok"]:
            f.append(f"analyse: guard must hold on the fixture {a['guard']}")
        md = write_outputs(a, "2026-11-24", tmp / "d", tmp / "l")
        js = json.loads((tmp / "d" / "summary.json").read_text())
        if js["verdict"] not in ("FAIL", "PASS (stable)", "PASS (not stable)") or "R2" not in md or not (tmp / "d" / "years.csv").exists():
            f.append("writer: outputs incomplete")
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc_ = main(fetch=lambda tks, start=None: {})
            if rc_ != 1 or (tmp / "data" / "r2_lab").exists():
                f.append("main: missing data must stop with nothing written")
        finally:
            os.chdir(cwd)
    except Exception as e:
        import traceback
        f.append(f"analyse/writer crashed: {type(e).__name__}: {e} {traceback.format_exc()[-300:]}")
    return {"ok": not f, "failures": f, "version": VERSION, "fixture": {"blocked_L20": len(b20), "def_entries_L20": len(ent)}}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r_ = selftest()
        print(json.dumps(r_, indent=2, default=str))
        sys.exit(0 if r_["ok"] else 1)
    sys.exit(main())
