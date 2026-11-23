"""
m0t2_lab.py  (v1.0 — 2026-11-23)
─────────────────────────────────
Swing book only. Trial 98, pre-registered in claude/m0t2_lab_2026-11-23.md (Matt 2026-11-23:
"yes, to run analysis using 2%"). Bars are fixed BEFORE any run on real prices; a FAIL is final.

M0-T exactly as tested in trial 97 (m0t_lab.py: live M0, no sector-rotation exit, no ladder trims),
with ONE change: risk per trade doubled, keeping today's ratios —
  full signal 1% -> 2%; weaker (2-of-3, size_mult 0.5) 0.5% -> 1%; losing-streak mode 0.5% -> 1%.
Unchanged: 4 positions, 2 per sector, 8% open-risk (heat) cap, 30% position cap, costs, T-bill sweep,
$10,000 start. Trade-level results cannot change with sizing (same trades, same R); only which
trades the book can take and how big they are.

Reported, not trials: M0-T at the live 1% in the same run (must match trial 97's resimulation),
and how often the 30% / heat / cash caps held a trade below its intended risk.

Run:  python m0t2_lab.py            (Actions; needs yfinance)
      python m0t2_lab.py --selftest (offline)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import swing_backtest as bt
import m0t_lab as m0t

VERSION = "1.0"
OUT_DATA, OUT_LOGS = Path("data/m0t2_lab"), Path("logs/m0t2_lab")
TRIALS_BEFORE, TRIALS_HERE = 97, 1
RISK_TEST = (2.0, 1.0)            # (BASE_RISK_PCT, REDUCED_RISK_PCT) under test
RISK_LIVE = (1.0, 0.5)
BAR = dict(m0t.BAR, max_months_le_10=0)   # trial 97's bars + Matt's limit A: no month at -10% or worse


class risk_setting:
    """Temporarily set swing_backtest's risk globals; always restores them."""

    def __init__(self, base: float, reduced: float):
        self.new = (base, reduced)

    def __enter__(self):
        self.saved = (bt.BASE_RISK_PCT, bt.REDUCED_RISK_PCT)
        bt.BASE_RISK_PCT, bt.REDUCED_RISK_PCT = self.new
        return self

    def __exit__(self, *exc):
        bt.BASE_RISK_PCT, bt.REDUCED_RISK_PCT = self.saved
        return False


def verdict(ts: dict, book: dict, spy: dict, months_le_10: int) -> tuple:
    ver, f = m0t.verdict(ts, book, spy)
    f = list(f)
    if months_le_10 > BAR["max_months_le_10"]:
        f.append(f"{months_le_10} month(s) at -10% or worse (limit A allows {BAR['max_months_le_10']})")
    return ("PASS" if not f else "FAIL"), f


def sizing_check(p: dict, base: float) -> dict:
    """Realised risk at entry vs intended (base x size_mult; streak mode ignored, so 'held below'
    slightly overstates capping during streaks). Uses the prior close's equity, as the pass does."""
    eq = p["equity"]
    pos_of = {d: i for i, d in enumerate(eq.index)}
    real, ratio = [], []
    for tr, sh in p["taken"]:
        d = tr.entry_date if hasattr(tr, "entry_date") else None
        if d is None:
            continue
        i = pos_of.get(d)
        if not i:
            continue
        e0 = float(eq.iloc[i - 1])
        r = sh * tr.risk / e0 * 100
        real.append(r)
        ratio.append(r / (base * tr.size_mult))
    if not real:
        return {"n": 0}
    ratio = np.array(ratio)
    return {"n": len(real), "median_risk_pct": round(float(np.median(real)), 2),
            "mean_risk_pct": round(float(np.mean(real)), 2),
            "held_below_80pct_of_intended_pct": round(float((ratio < 0.8).mean()) * 100, 1)}


def analyse(ohlcv: dict, rates: dict) -> dict:
    etfs = bt.SECTOR_ETFS + list(bt.OTHER_ETFS)
    sector_of = {s: s for s in bt.SECTOR_ETFS}
    sector_of.update(bt.OTHER_ETFS)
    m0t._log(f"M0 signals on {len(ohlcv)} funds ...")
    res = bt.run(ohlcv, etfs, [], sector_of, setups=("M0",), variants=("B",), verbose=False)
    cal, data = res["cal"], res["data"]
    sw, gaps = bt.sweep_inputs(ohlcv, rates, cal)
    start = cal[bt.WINDOW] if len(cal) > bt.WINDOW else cal[0]
    spy = bt.half_stats(ohlcv["SPY"]["Close"].reindex(cal).ffill(), start)
    t_tr, t_uf = m0t.resimulate(res, ladder=(), rotation=False)
    sel = [t for t in t_tr if t.mkt_ok]
    ufs = [g for g in t_uf if g.mkt_ok]
    for tr in sel:                                   # entry dates for the sizing check
        try:
            tr.entry_date = data[tr.ticker]["index"][tr.entry_t]
        except Exception:
            pass

    def book(base_red):
        with risk_setting(*base_red):
            p = bt.run_portfolio(sel, ufs, data, cal, sector_of, sweep={"mode": "TBILL", **sw})
        return p, bt.half_stats(p["equity"], start)

    m0t._log("M0-T at 2% (trial 98) and at the live 1% (reference) ...")
    p2, h2 = book(RISK_TEST)
    p1, h1 = book(RISK_LIVE)
    restored = (bt.BASE_RISK_PCT, bt.REDUCED_RISK_PCT) == RISK_LIVE
    ts = m0t.half_trades(sel, data)
    ver, fails = verdict(ts, h2, spy, p2["months_le_-10pct"])

    def pack(p, h, base):
        worst_m = p["equity"].resample("ME").last().pct_change().dropna()
        return {"book": h, "exposure_avg_pct": p["exposure_avg_pct"], "heat_max_pct": p["heat_max_pct"],
                "trades_taken": p["trades_taken"], "months_le_-10pct": p["months_le_-10pct"],
                "hwm_-20pct_breached": p["hwm_-20pct_breached"],
                "worst_month_pct": round(float(worst_m.min()) * 100, 2) if len(worst_m) else None,
                "taken_trades": m0t.half_trades([t for t, _s in p["taken"]], data)["full"],
                "sizing": sizing_check(p, base)}

    return {"version": VERSION, "verdict": ver, "fails": fails, "globals_restored": bool(restored),
            "gaps": gaps, "trades": ts, "m0t_2pct": pack(p2, h2, RISK_TEST[0]),
            "m0t_1pct": pack(p1, h1, RISK_LIVE[0]), "spy": spy,
            "equity": {"m0t_2pct": p2["equity"], "m0t_1pct": p1["equity"]}}


def _c(x):
    return "—" if x is None else f"{x:.2f}%"


def render(r: dict, stamp: str) -> str:
    a, b = r["m0t_2pct"], r["m0t_1pct"]
    L = [f"# M0-T at 2% risk (trial 98) — m0t2_lab {VERSION} — {stamp}", "",
         f"Pre-registered in `claude/m0t2_lab_2026-11-23.md`. Trials {TRIALS_BEFORE} → {TRIALS_BEFORE + TRIALS_HERE}. "
         "Research, not personalized advice.", "",
         f"## Verdict: **{r['verdict']}**", "",
         f"- Fails: {'; '.join(r['fails']) or 'none'}", "",
         "| | M0-T 2% (test) | M0-T 1% (live setting) | SPY |", "|---|---|---|---|"]
    for h in ("full", "2005-15", "2016-26"):
        L.append(f"| Book CAGR {h} | {_c(a['book'][h].get('cagr_pct'))} | {_c(b['book'][h].get('cagr_pct'))} | "
                 f"{_c(r['spy'][h].get('cagr_pct'))} |")
    L.append(f"| Book max DD | {_c(a['book']['full'].get('max_dd_pct'))} | {_c(b['book']['full'].get('max_dd_pct'))} | "
             f"{_c(r['spy']['full'].get('max_dd_pct'))} |")
    for k, lab in (("worst_month_pct", "Worst month %"), ("months_le_-10pct", "Months ≤ −10%"),
                   ("hwm_-20pct_breached", "−20% from high breached"), ("exposure_avg_pct", "Average invested %"),
                   ("heat_max_pct", "Max open risk %"), ("trades_taken", "Trades taken")):
        L.append(f"| {lab} | {a[k]} | {b[k]} | — |")
    for k, lab in (("median_risk_pct", "Median risk at entry %"),
                   ("held_below_80pct_of_intended_pct", "Entries held below 80% of intended risk (caps), %")):
        L.append(f"| {lab} | {a['sizing'].get(k)} | {b['sizing'].get(k)} | — |")
    L += ["", "| Trades (closed, filtered — identical at any risk) | n | Win % | Avg win R | Avg loss R | Expectancy R | PF |",
          "|---|---|---|---|---|---|---|"]
    for h in ("full", "2005-15", "2016-26"):
        s = r["trades"][h]
        L.append(f"| {h} | {s.get('n')} | {s.get('win_rate')} | {s.get('avg_win_R')} | {s.get('avg_loss_R')} | "
                 f"{s.get('expectancy_R')} | {s.get('profit_factor')} |")
    L += ["", "| Trades the book actually took | n | Expectancy R | PF |", "|---|---|---|---|"]
    for nm, x in (("2%", a), ("1%", b)):
        s = x["taken_trades"]
        L.append(f"| {nm} | {s.get('n')} | {s.get('expectancy_R')} | {s.get('profit_factor')} |")
    L += ["", f"Reference check: the 1% column should match trial 97's M0-T (3.79% / −11.92% on 2026-11-23 prices).",
          f"Risk settings restored after the run: {'yes' if r['globals_restored'] else '**NO**'}"]
    if r.get("gaps"):
        L += ["", "Data gaps: " + "; ".join(r["gaps"])]
    L += ["", f"*m0t2_lab.py {VERSION}*"]
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
        pd.DataFrame(eq).round(2).to_csv(out_data / "equity.csv")
    (out_data / "summary.json").write_text(js)
    return md


def main(fetch=None) -> int:
    stamp = datetime.now(timezone.utc).date().isoformat()
    etfs = bt.SECTOR_ETFS + list(bt.OTHER_ETFS)
    fetch = fetch or bt.fetch_ohlcv
    m0t._log("fetching prices ...")
    ohlcv = fetch(sorted(set(etfs)))
    for attempt in range(3):
        miss = sorted(set(etfs) - set(ohlcv))
        if not miss:
            break
        m0t._log(f"retry {attempt + 1}: {', '.join(miss)}")
        for t in miss:
            ohlcv.update(fetch([t]))
    miss = sorted(set(etfs) - set(ohlcv))
    if miss or "SPY" not in ohlcv:
        print(f"[m0t2_lab] DATA FAILURE: no prices for {', '.join(miss) or 'SPY'} after retries; nothing written.")
        return 1
    rates = fetch(["^IRX"])
    r = analyse(ohlcv, rates)
    if not r["globals_restored"]:
        print("[m0t2_lab] GUARD FAILED: risk settings were not restored; nothing written.")
        return 1
    md = write_outputs(r, stamp)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    import contextlib, io, os, tempfile
    f = []
    etfs = ["SPY", "XLK", "XLE", "XLF", "XLV", "XLU", "XLI"]
    ohl = {tk: bt._walk(i + 3, n=1400, drift=0.0005 + 0.0002 * i) for i, tk in enumerate(etfs)}
    irx = pd.DataFrame({"Open": 4.0, "High": 4.0, "Low": 4.0, "Close": 4.0, "Volume": 0}, index=ohl["SPY"].index)
    # risk_setting restores even on error
    try:
        with risk_setting(9.0, 9.0):
            raise RuntimeError
    except RuntimeError:
        pass
    if (bt.BASE_RISK_PCT, bt.REDUCED_RISK_PCT) != RISK_LIVE:
        f.append("risk_setting must restore the live globals after an exception")
    saved = (bt.SECTOR_ETFS, bt.OTHER_ETFS)
    bt.SECTOR_ETFS, bt.OTHER_ETFS = etfs, {}
    tmp = Path(tempfile.mkdtemp())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            r = analyse(ohl, {"^IRX": irx})
            # reference: the 1% book here must equal m0t_lab's M0-T book on the same fixture
            r97 = m0t.analyse(ohl, {"^IRX": irx})
        a, b = r["m0t_2pct"], r["m0t_1pct"]
        if not r["globals_restored"]:
            f.append("analyse must restore the risk globals")
        if abs((b["book"]["full"].get("cagr_pct") or 0) - (r97["m0t"]["book"]["full"].get("cagr_pct") or 0)) > 1e-9:
            f.append("1% reference must reproduce m0t_lab's M0-T book exactly")
        if b["trades_taken"] < 3:
            f.append(f"fixture: need taken trades, got {b['trades_taken']}")
        if not (b["sizing"].get("median_risk_pct") or 0) <= 1.0 + 1e-9:
            f.append(f"1% book: median risk {b['sizing'].get('median_risk_pct')} must be <= 1%")
        if not (a["sizing"].get("median_risk_pct") or 0) > (b["sizing"].get("median_risk_pct") or 0):
            f.append("2% book must size larger than the 1% book")
        if not (a["sizing"].get("median_risk_pct") or 0) <= 2.0 + 1e-9:
            f.append("2% book: median risk must be <= 2%")
        if a["heat_max_pct"] > bt.HEAT_CAP_PCT + 0.6:
            f.append(f"2% book heat {a['heat_max_pct']} exceeds the {bt.HEAT_CAP_PCT}% cap")
        md = write_outputs(r, "2026-11-23", tmp / "d", tmp / "l")
        js = json.loads((tmp / "d" / "summary.json").read_text())
        if js["verdict"] not in ("PASS", "FAIL") or "trial 98" not in md or not (tmp / "d" / "equity.csv").exists():
            f.append("writer: outputs incomplete")
    except Exception as e:
        f.append(f"analyse/writer crashed: {type(e).__name__}: {e}")
    finally:
        bt.SECTOR_ETFS, bt.OTHER_ETFS = saved
    # verdict: limit A
    ok_ts = {"full": {"n": 200}, "2005-15": {"n": 80, "expectancy_R": 0.2, "profit_factor": 1.5},
             "2016-26": {"n": 80, "expectancy_R": 0.1, "profit_factor": 1.4}}
    bk = {h: {"cagr_pct": 12.0, "max_dd_pct": -15.0} for h in ("full", "2005-15", "2016-26")}
    sp = {h: {"cagr_pct": 10.0} for h in ("full", "2005-15", "2016-26")}
    if verdict(ok_ts, bk, sp, 0)[0] != "PASS":
        f.append("verdict: clean pass must pass")
    if verdict(ok_ts, bk, sp, 1)[0] != "FAIL":
        f.append("verdict: one month at -10% must fail (limit A)")
    if verdict(ok_ts, dict(bk, full={"cagr_pct": 12.0, "max_dd_pct": -20.5}), sp, 0)[0] != "FAIL":
        f.append("verdict: -20.5% drawdown must fail")
    # main: missing data stops with nothing written
    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc_ = main(fetch=lambda tks, start=None: {})
        if rc_ != 1 or (tmp / "data" / "m0t2_lab").exists():
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
