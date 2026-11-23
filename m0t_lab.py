"""
m0t_lab.py  (v1.0 — 2026-11-23)
────────────────────────────────
Swing book only. Pre-registered test of shortlist item 1 (claude/swing_strategy_shortlist_2026-11-23.md;
Matt 2026-11-23: "I am good with moving with your recommendation"). Pre-registration with bars:
claude/m0t_lab_2026-11-23.md. Bars below are fixed BEFORE any run on real prices; a FAIL is final.

M0-T = the live M0 rule (swing_backtest M0, variant B, the live ETF universe incl. leveraged ETFs,
SPY above its 200-day at the signal) with exactly two changes, made by reusing swing_backtest's own
code, not a copy:
  1. NO sector-rotation exit (simulate_trade is passed no rotation quadrants; N74);
  2. NO 2R/4R/8R ladder trims (winners run).
Everything else is unchanged: buy-stop entry, closing-basis stop + 1xATR disaster stop, M0's own
100-day trailing average (exit below a falling one, tighten to a rising one), the leveraged 90-day
cap, costs, and the $10,000 portfolio pass (2% risk x confluence, 4 positions, 2 per sector, 8%
heat, 30% cap, idle cash in T-bills).

Baseline: live M0 on the same data and the same pass (recorded 2026-11-20: about 2.94%/yr).

Run:  python m0t_lab.py            (Actions; needs yfinance)
      python m0t_lab.py --selftest (offline)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import swing_backtest as bt

VERSION = "1.0"
OUT_DATA, OUT_LOGS = Path("data/m0t_lab"), Path("logs/m0t_lab")
TRIALS_BEFORE, TRIALS_HERE = 96, 1
BASELINE_RECORDED = 2.94
BAR = {"min_trades": 100, "min_half": 30, "min_pf": 1.3, "max_dd": -20.0}


def _log(msg: str) -> None:
    print(f"[m0t_lab {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def resimulate(res: dict, ladder: tuple = (), rotation: bool = False) -> tuple:
    """Re-run every M0 signal through bt.simulate_trade with the given ladder and with or without the
    rotation (thesis) exit, applying run()'s one-open-trade-per-ticker rule. Returns (trades, unfilled)."""
    saved = bt.LADDER
    bt.LADDER = tuple(ladder)
    try:
        trades, unfilled, busy = [], [], {}
        for sg in sorted((s for s in res["signals"] if s.setup == "M0"), key=lambda z: (z.ticker, z.setup, z.t)):
            d = res["data"][sg.ticker]
            key = (sg.ticker, sg.setup)
            if sg.t + 1 <= busy.get(key, -1):
                continue
            tr = bt.simulate_trade(sg, d["arr"], "B", d["quads"] if rotation else None, d["asset"])
            if tr is not None:
                trades.append(tr)
                busy[key] = tr.exit_t
            else:
                unfilled.append(sg)
        return trades, unfilled
    finally:
        bt.LADDER = saved


def entry_date(tr, data) -> pd.Timestamp:
    return data[tr.ticker]["index"][tr.entry_t]


def half_trades(trs: list, data: dict) -> dict:
    closed = [t for t in trs if not t.still_open]
    return {"full": bt.trade_stats([t.r_net for t in closed]),
            "2005-15": bt.trade_stats([t.r_net for t in closed if entry_date(t, data) < bt.HALF_SPLIT]),
            "2016-26": bt.trade_stats([t.r_net for t in closed if entry_date(t, data) >= bt.HALF_SPLIT])}


def verdict(ts: dict, book: dict, spy: dict) -> tuple:
    f = []
    if ts["full"].get("n", 0) < BAR["min_trades"]:
        f.append(f"n {ts['full'].get('n', 0)} < {BAR['min_trades']}")
    for h in ("2005-15", "2016-26"):
        s = ts[h]
        if s.get("n", 0) < BAR["min_half"]:
            f.append(f"{h} n {s.get('n', 0)} < {BAR['min_half']}")
        if not s.get("expectancy_R", -1) > 0:
            f.append(f"{h} expectancy {s.get('expectancy_R')}R <= 0")
        if not s.get("profit_factor", 0) >= BAR["min_pf"]:
            f.append(f"{h} PF {s.get('profit_factor')} < {BAR['min_pf']}")
    for h in ("full", "2005-15", "2016-26"):
        c, cs = book[h].get("cagr_pct"), spy[h].get("cagr_pct")
        if c is None or cs is None or not c > cs:
            f.append(f"book {h} CAGR {c}% <= SPY {cs}%")
    dd = book["full"].get("max_dd_pct")
    if dd is None or not dd > BAR["max_dd"]:
        f.append(f"book max DD {dd}% deeper than {BAR['max_dd']}%")
    return ("PASS" if not f else "FAIL"), f


def exit_mix(trs: list) -> dict:
    out = {}
    for t in trs:
        out.setdefault(t.exit_reason, []).append(t.r_net)
    return {k: {"n": len(v), "mean_R": round(float(np.nanmean(v)), 3)} for k, v in sorted(out.items(), key=lambda kv: -len(kv[1]))}


def analyse(ohlcv: dict, rates: dict) -> dict:
    etfs = bt.SECTOR_ETFS + list(bt.OTHER_ETFS)
    sector_of = {s: s for s in bt.SECTOR_ETFS}
    sector_of.update(bt.OTHER_ETFS)
    _log(f"M0 signals on {len(ohlcv)} funds ...")
    res = bt.run(ohlcv, etfs, [], sector_of, setups=("M0",), variants=("B",), verbose=False)
    cal, data = res["cal"], res["data"]
    sw, gaps = bt.sweep_inputs(ohlcv, rates, cal)
    start = cal[bt.WINDOW] if len(cal) > bt.WINDOW else cal[0]
    spy = bt.half_stats(ohlcv["SPY"]["Close"].reindex(cal).ffill(), start)

    def book(trs, uf):
        sel = [t for t in trs if t.mkt_ok]
        ufs = [g for g in uf if g.mkt_ok]
        p = bt.run_portfolio(sel, ufs, data, cal, sector_of, sweep={"mode": "TBILL", **sw})
        return p, bt.half_stats(p["equity"], start), sel

    base_tr = [t for t in res["trades"]["B"] if t.setup == "M0"]
    base_uf = [g for g in res["unfilled"] if g.setup == "M0"]
    pb, hb, selb = book(base_tr, base_uf)
    _log("M0-T: no rotation exit, no ladder ...")
    t_tr, t_uf = resimulate(res, ladder=(), rotation=False)
    pt, ht, selt = book(t_tr, t_uf)
    # diagnostics (report only, not trials): each change alone
    d1_tr, d1_uf = resimulate(res, ladder=bt.LADDER, rotation=False)          # rotation exit removed only
    p1, h1, _s1 = book(d1_tr, d1_uf)
    d2_tr, d2_uf = resimulate(res, ladder=(), rotation=True)                  # ladder removed only
    p2, h2, _s2 = book(d2_tr, d2_uf)
    # guard: the resimulation with both rules ON must reproduce run()'s own M0 trades exactly
    g_tr, _g = resimulate(res, ladder=bt.LADDER, rotation=True)
    guard = (len(g_tr) == len(base_tr) and
             all(abs(a.r_net - b.r_net) < 1e-12 and a.exit_t == b.exit_t for a, b in
                 zip(sorted(g_tr, key=lambda z: (z.ticker, z.entry_t)), sorted(base_tr, key=lambda z: (z.ticker, z.entry_t)))))
    ts_t, ts_b = half_trades(selt, data), half_trades(selb, data)
    ver, fails = verdict(ts_t, ht, spy)
    return {"version": VERSION, "verdict": ver, "fails": fails, "guard_reproduces_m0": bool(guard),
            "baseline_recorded_cagr": BASELINE_RECORDED, "gaps": gaps,
            "m0t": {"trades": ts_t, "book": ht, "exposure_avg_pct": pt["exposure_avg_pct"],
                    "months_le_-10pct": pt["months_le_-10pct"], "hwm_-20pct_breached": pt["hwm_-20pct_breached"],
                    "trades_taken": pt["trades_taken"], "exit_mix": exit_mix(selt),
                    "median_hold": float(np.median([t.exit_t - t.entry_t for t in selt])) if selt else None},
            "m0": {"trades": ts_b, "book": hb, "exposure_avg_pct": pb["exposure_avg_pct"],
                   "months_le_-10pct": pb["months_le_-10pct"], "hwm_-20pct_breached": pb["hwm_-20pct_breached"],
                   "trades_taken": pb["trades_taken"], "exit_mix": exit_mix(selb),
                   "median_hold": float(np.median([t.exit_t - t.entry_t for t in selb])) if selb else None},
            "diag_no_rotation_only": {"book": h1, "trades": half_trades([t for t in d1_tr if t.mkt_ok], data)["full"]},
            "diag_no_ladder_only": {"book": h2, "trades": half_trades([t for t in d2_tr if t.mkt_ok], data)["full"]},
            "spy": spy, "equity": {"m0t": pt["equity"], "m0": pb["equity"]}}


def _c(x):
    return "—" if x is None else f"{x:.2f}%"


def render(r: dict, stamp: str) -> str:
    L = [f"# M0-T lab {VERSION} — {stamp}", "",
         f"Pre-registered in `claude/m0t_lab_2026-11-23.md`. Trials {TRIALS_BEFORE} → {TRIALS_BEFORE + TRIALS_HERE}. "
         "Research, not personalized advice.", "",
         f"## M0-T (no sector-rotation exit, no ladder trims): **{r['verdict']}**", "",
         f"- Fails: {'; '.join(r['fails']) or 'none'}",
         f"- Guard — the resimulation reproduces live M0 exactly with both rules on: "
         f"{'yes' if r['guard_reproduces_m0'] else '**NO — result not valid**'}", "",
         "| | M0-T | M0 (live rule) | SPY |", "|---|---|---|---|"]
    for h in ("full", "2005-15", "2016-26"):
        L.append(f"| Book CAGR {h} | {_c(r['m0t']['book'][h].get('cagr_pct'))} | {_c(r['m0']['book'][h].get('cagr_pct'))} | "
                 f"{_c(r['spy'][h].get('cagr_pct'))} |")
    L.append(f"| Book max DD | {_c(r['m0t']['book']['full'].get('max_dd_pct'))} | {_c(r['m0']['book']['full'].get('max_dd_pct'))} | "
             f"{_c(r['spy']['full'].get('max_dd_pct'))} |")
    for k, lab in (("exposure_avg_pct", "Average invested"), ("trades_taken", "Trades taken by the $10k book"),
                   ("median_hold", "Median hold (sessions)"), ("months_le_-10pct", "Months ≤ −10%")):
        L.append(f"| {lab} | {r['m0t'][k]} | {r['m0'][k]} | — |")
    L += ["", "| Trades (closed, filtered) | n | Win % | Avg win R | Avg loss R | Expectancy R | PF |", "|---|---|---|---|---|---|---|"]
    for nm in ("m0t", "m0"):
        for h in ("full", "2005-15", "2016-26"):
            s = r[nm]["trades"][h]
            L.append(f"| {'M0-T' if nm == 'm0t' else 'M0'} {h} | {s.get('n')} | {s.get('win_rate')} | {s.get('avg_win_R')} | "
                     f"{s.get('avg_loss_R')} | {s.get('expectancy_R')} | {s.get('profit_factor')} |")
    L += ["", "**Diagnostics (report only, not trials):**",
          f"- Rotation exit removed only: book {_c(r['diag_no_rotation_only']['book']['full'].get('cagr_pct'))}, "
          f"expectancy {r['diag_no_rotation_only']['trades'].get('expectancy_R')}R",
          f"- Ladder removed only: book {_c(r['diag_no_ladder_only']['book']['full'].get('cagr_pct'))}, "
          f"expectancy {r['diag_no_ladder_only']['trades'].get('expectancy_R')}R",
          f"- M0 baseline recorded 2026-11-20: {r['baseline_recorded_cagr']}%/yr; this run: "
          f"{_c(r['m0']['book']['full'].get('cagr_pct'))}", "",
          "**How M0-T trades ended:** " + "; ".join(f"{k} {v['n']} ({v['mean_R']:+.2f}R)" for k, v in r["m0t"]["exit_mix"].items())]
    if r.get("gaps"):
        L += ["", "Data gaps: " + "; ".join(r["gaps"])]
    L += ["", f"*m0t_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def write_outputs(r: dict, stamp: str, out_data: Path = OUT_DATA, out_logs: Path = OUT_LOGS) -> str:
    from lever_lab import _jsonable
    md = render(r, stamp)
    eq = r.pop("equity", None)
    js = json.dumps(_jsonable({**r, "trials": TRIALS_BEFORE + TRIALS_HERE, "asof": stamp}), indent=1, default=str)
    out_data.mkdir(parents=True, exist_ok=True)
    out_logs.mkdir(parents=True, exist_ok=True)
    (out_logs / "latest.md").write_text(md)
    (out_logs / f"{stamp}.md").write_text(md)
    if eq:
        pd.DataFrame({k: v for k, v in eq.items()}).round(2).to_csv(out_data / "equity.csv")
    (out_data / "summary.json").write_text(js)
    return md


def main(fetch=None) -> int:
    stamp = datetime.now(timezone.utc).date().isoformat()
    etfs = bt.SECTOR_ETFS + list(bt.OTHER_ETFS)
    fetch = fetch or bt.fetch_ohlcv
    _log("fetching prices ...")
    ohlcv = fetch(sorted(set(etfs)))
    for attempt in range(3):
        miss = sorted(set(etfs) - set(ohlcv))
        if not miss:
            break
        _log(f"retry {attempt + 1}: {', '.join(miss)}")
        for t in miss:
            ohlcv.update(fetch([t]))
    miss = sorted(set(etfs) - set(ohlcv))
    if miss or "SPY" not in ohlcv:
        print(f"[m0t_lab] DATA FAILURE: no prices for {', '.join(miss) or 'SPY'} after retries; nothing written.")
        return 1
    rates = fetch(["^IRX"])
    r = analyse(ohlcv, rates)
    if not r["guard_reproduces_m0"]:
        print("[m0t_lab] GUARD FAILED: the resimulation does not reproduce live M0; nothing written.")
        return 1
    md = write_outputs(r, stamp)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    f = []
    etfs = ["SPY", "XLK", "XLE", "XLF", "XLV", "XLU", "XLI"]
    ohl = {tk: bt._walk(i + 3, n=1400, drift=0.0005 + 0.0002 * i) for i, tk in enumerate(etfs)}
    sector_of = {t: t for t in etfs}
    res = bt.run(ohl, etfs, [], sector_of, setups=("M0",), variants=("B",), verbose=False)
    base = [t for t in res["trades"]["B"] if t.setup == "M0"]
    if len(base) < 5:
        f.append(f"fixture: need M0 trades, got {len(base)}")
    # guard: both rules on reproduces run() exactly
    g, _u = resimulate(res, ladder=bt.LADDER, rotation=True)
    key = lambda z: (z.ticker, z.entry_t)
    if len(g) != len(base) or any(a.r_net != b.r_net or a.exit_t != b.exit_t for a, b in zip(sorted(g, key=key), sorted(base, key=key))):
        f.append("resimulate(ladder on, rotation on) must reproduce run() exactly")
    # M0-T: no rotation exits, no trims
    t, _u = resimulate(res, ladder=(), rotation=False)
    if any(tr.exit_reason.startswith("thesis") for tr in t):
        f.append("M0-T must never exit on the sector-rotation rule")
    if any(k == "trim" for tr in t for (_t, k, *_r) in tr.events):
        f.append("M0-T must never trim")
    if not any(tr.exit_reason.startswith("thesis") for tr in base):
        f.append("fixture: the baseline should contain rotation exits")
    # LADDER restored even after use
    if bt.LADDER != (2.0, 4.0, 8.0):
        f.append(f"bt.LADDER must be restored: {bt.LADDER}")
    # no overlapping trades per ticker
    by = {}
    for tr in t:
        by.setdefault(tr.ticker, []).append(tr)
    for tk, v in by.items():
        v = sorted(v, key=lambda z: z.entry_t)
        if any(b.entry_t <= a.exit_t for a, b in zip(v, v[1:])):
            f.append(f"overlapping trades for {tk}")
            break
    # verdict logic
    ok_ts = {"full": {"n": 200}, "2005-15": {"n": 80, "expectancy_R": 0.2, "profit_factor": 1.5},
             "2016-26": {"n": 80, "expectancy_R": 0.1, "profit_factor": 1.4}}
    bk = {h: {"cagr_pct": 12.0, "max_dd_pct": -15.0} for h in ("full", "2005-15", "2016-26")}
    sp = {h: {"cagr_pct": 10.0} for h in ("full", "2005-15", "2016-26")}
    if verdict(ok_ts, bk, sp)[0] != "PASS":
        f.append("verdict: a clean pass must pass")
    bad = dict(ok_ts, **{"2016-26": {"n": 80, "expectancy_R": 0.1, "profit_factor": 1.2}})
    if verdict(bad, bk, sp)[0] != "FAIL":
        f.append("verdict: PF 1.2 in a half must fail")
    bk2 = dict(bk, full={"cagr_pct": 12.0, "max_dd_pct": -21.0})
    if verdict(ok_ts, bk2, sp)[0] != "FAIL":
        f.append("verdict: -21% drawdown must fail")
    bk3 = dict(bk, **{"2005-15": {"cagr_pct": 9.0, "max_dd_pct": -10.0}})
    if verdict(ok_ts, bk3, sp)[0] != "FAIL":
        f.append("verdict: trailing SPY in a half must fail")
    # analyse + writer end to end on the fixture (T-bills from a flat ^IRX)
    import tempfile, contextlib, io
    tmp = Path(tempfile.mkdtemp())
    try:
        irx = pd.DataFrame({"Open": 4.0, "High": 4.0, "Low": 4.0, "Close": 4.0, "Volume": 0}, index=ohl["SPY"].index)
        saved = (bt.SECTOR_ETFS, bt.OTHER_ETFS)
        bt.SECTOR_ETFS, bt.OTHER_ETFS = etfs, {}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                r = analyse(ohl, {"^IRX": irx})
        finally:
            bt.SECTOR_ETFS, bt.OTHER_ETFS = saved
        if not r["guard_reproduces_m0"]:
            f.append("analyse: guard must hold on the fixture")
        md = write_outputs(r, "2026-11-23", tmp / "d", tmp / "l")
        js = json.loads((tmp / "d" / "summary.json").read_text())
        if js["verdict"] not in ("PASS", "FAIL") or "M0-T" not in md or not (tmp / "d" / "equity.csv").exists():
            f.append("writer: outputs incomplete")
    except Exception as e:
        f.append(f"analyse/writer crashed: {type(e).__name__}: {e}")
    # main: a missing fund stops with nothing written
    import os
    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):          # N82: keep the deliberate abort out of the log
            rc_ = main(fetch=lambda tks, start=None: {})
        if rc_ != 1 or (tmp / "data" / "m0t_lab").exists():
            f.append("main: missing data must stop with nothing written")
    finally:
        os.chdir(cwd)
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        res_ = selftest()
        print(json.dumps(res_, indent=2))
        sys.exit(0 if res_["ok"] else 1)
    sys.exit(main())
