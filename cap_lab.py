"""
cap_lab.py  (v1.0 — 2026-11-25)
───────────────────────────────
SWING book only. Capacity: M0-T with leveraged twins and more slots. Pre-registered in
claude/cap_lab_2026-11-25.md BEFORE any run on prices. Swing trials 99 -> 104. FAIL is final.

Matt 2026-11-25: "does it matter considering the number of trades? … what if we could average 4-5
trades a week where risk is manageable and returns can compound over time?" / "i think leverage should
be included in the swing book."

Trial 97 (corrected): 2,101 M0-T signals 2005–26 (~96/yr) at +0.44R, but the $10k book took 385 (~18/yr)
at ~0.4% realized risk -> 3.6%/yr. The constraint is cash: tight ETF stops need ~1/3 of the account per
1%-risk position. A leveraged twin carries the same risk with ~1/k of the cash.

Twin model (validated in lever_lab: synthetic vs real UPRO/TQQQ corr 0.998): the twin's level is
    L[t] = L[t-1] * (1 + k * r[t] - c[t]),   c[t] = fee/252 + (k-1) * (T-bill[t] + spread/252)
and a price p seen on the underlying's bar t maps to L(p, t) = L[t-1] * (1 + k * (p / C[t-1] - 1) - c[t]).
Entries, stops and exits are decided on the UNDERLYING exactly as in M0-T; only the instrument held changes.
Underlyings whose leveraged version is already a universe member (SPY, QQQ, XLK, SMH, IWM, XLF) get no twin.

Run:  python cap_lab.py            (Actions)
      python cap_lab.py --selftest (offline)
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import swing_backtest as bt
import m0t_lab as m0t

VERSION = "1.0.2"
OUT_DIR, LOG_DIR = Path("data/cap_lab"), Path("logs/cap_lab")
TRIALS_BEFORE, TRIALS_HERE = 99, 5
FEE, SPREAD = 0.0095, 0.0050                     # lever_lab's synthetic leveraged-fund costs (per year)
LIMITS = (-10.0, -20.0)                          # swing limits "A" inside the book
TWINS = {"DIA": ("UDOW", 3), "MDY": ("MIDU", 3), "XLE": ("ERX", 2), "XLV": ("CURE", 3), "XLI": ("DUSL", 3),
         "XLY": ("WANT", 3), "XLU": ("UTSL", 3), "XLRE": ("DRN", 3), "XLB": ("UYM", 2), "XLP": ("UGE", 2),
         "XLC": ("LTL", 2), "IBB": ("BIB", 2), "XBI": ("LABU", 3), "KRE": ("DPST", 3), "ITB": ("NAIL", 3),
         "XHB": ("NAIL", 3), "XRT": ("RETL", 3), "IYT": ("TPOR", 3), "ITA": ("DFEN", 3), "GDX": ("NUGT", 2),
         "GLD": ("UGL", 2), "SLV": ("AGQ", 2), "TLT": ("TMF", 3), "EEM": ("EDC", 3), "EFA": ("EFO", 2),
         "XOP": ("GUSH", 2)}
def twin_name(und: str) -> str:
    """One held ticker per underlying (ITB~NAIL, XHB~NAIL), sorting where the underlying does."""
    return f"{und}~{TWINS[und][0]}"


def is_twin(tk: str) -> bool:
    return "~" in tk


HAS_MEMBER = {"SPY": "UPRO", "QQQ": "TQQQ", "XLK": "TECL", "SMH": "SOXL", "IWM": "TNA", "XLF": "FAS"}
CANDIDATES = {"K3": {"twins": True, "slots": 8, "role": "decision"},
              "K3-6": {"twins": True, "slots": 6, "role": "neighbour"},
              "K3-10": {"twins": True, "slots": 10, "role": "neighbour"},
              "K1": {"twins": False, "slots": 8, "role": "attribution: slots alone"},
              "K2": {"twins": True, "slots": 4, "role": "attribution: twins alone"}}
BAR = {"min_pf": 1.3, "max_dd": -20.0}


def _log(m: str) -> None:
    print(f"[cap_lab {datetime.now(timezone.utc):%H:%M:%S}] {m}", flush=True)


@contextlib.contextmanager
def slots(n: int):
    old = bt.MAX_POSITIONS
    bt.MAX_POSITIONS = n
    try:
        yield
    finally:
        bt.MAX_POSITIONS = old


# ── the twin ────────────────────────────────────────────────────────────────

class Twin:
    """Level and price map of a k-times twin on the underlying's own bar index."""

    def __init__(self, close: np.ndarray, rate: np.ndarray, k: float, fee: float = FEE, spread: float = SPREAD):
        self.k = float(k)
        n = len(close)
        self.C = np.asarray(close, dtype=float)
        r = np.zeros(n)
        r[1:] = self.C[1:] / self.C[:-1] - 1.0
        self.c = fee / 252.0 + (self.k - 1.0) * (np.nan_to_num(np.asarray(rate, dtype=float)) + spread / 252.0)
        self.c[0] = 0.0
        L = np.empty(n)
        L[0] = self.C[0]
        for t in range(1, n):
            L[t] = L[t - 1] * (1.0 + self.k * r[t] - self.c[t])
        self.L = L
        self.S = np.ones(n)

    # The k = 1 guard has L = C, so S = 1 and the guard does not exercise the rebase; the rebase is covered
    # by the unit test and by the in-trade k× check in the selftest (review 3, m2).
    def rebase(self, points) -> None:
        """Scale only, like a split between holdings: from each entry bar d the twin is quoted so that
        its last close equals the underlying's (C[d-1]). Returns and R are unchanged; whole-share
        rounding then sees a realistic price instead of wherever the synthetic level drifted."""
        for d in sorted(set(points)):
            if 1 <= d < len(self.C):
                self.S[d:] = self.C[d - 1] / self.L[d - 1]

    @property
    def level(self) -> np.ndarray:
        return self.L * self.S

    def price(self, p: float, t: int) -> float:
        """A price seen on the underlying's bar t, expressed in the twin."""
        if t <= 0:
            return float(p) / self.C[0] * self.L[0] * self.S[0]
        return float(self.S[t] * self.L[t - 1] * (1.0 + self.k * (p / self.C[t - 1] - 1.0) - self.c[t]))


def twin_trade(tr, tw: Twin, ticker: str, asset_cost: Optional[str]):
    """The same trade held in the twin. asset_cost None keeps the underlying's costs (guard)."""
    x = copy.deepcopy(tr)
    x.ticker = ticker
    d = tr.entry_t
    plan = tr.stop0 + tr.risk
    x.entry = tw.price(tr.entry, d)
    x.stop0 = tw.price(tr.stop0, d)
    x.risk = tw.price(plan, d) - tw.price(tr.stop0, d)
    base_bps = bt.COST_BPS[tr.asset]
    ev = []
    for (t, kind, frac, px, bps) in tr.events:
        nb = bps if (asset_cost is None or bps == 0) else bps - base_bps + bt.COST_BPS[asset_cost]
        ev.append((t, kind, frac, tw.price(px, t), nb))
    x.events = ev
    x.stops = [(t, tw.price(s, t)) for (t, s) in tr.stops]
    if asset_cost is not None:
        x.asset = asset_cost
    fill = x.events[0][3]
    gross = sum(f * p for t, k, f, p, b in x.events if k != "entry")
    cost = sum(f * p * b / 1e4 for t, k, f, p, b in x.events)
    x.r_net = (gross - fill - cost) / x.risk if x.risk > 0 else float("nan")
    x.rank_frac = tr.risk / plan if plan > 0 else 1.0       # ranks as the underlying would
    return x


def twin_signal(sg, tw: Twin, ticker: str):
    x = copy.deepcopy(sg)
    x.ticker = ticker
    d = sg.t + 1
    x.level = tw.price(sg.level, d)
    x.stop = tw.price(sg.stop, d) if sg.stop is not None else None
    x.plan_entry = tw.price(sg.plan_entry, d) if sg.plan_entry is not None else None
    if sg.max_entry is not None:
        x.max_entry = tw.price(sg.max_entry, d)
    pe = sg.plan_entry if sg.plan_entry is not None else sg.level
    x.rank_frac = (pe - sg.stop) / pe if sg.stop is not None and pe > 0 else None
    return x


def build_twins(res: dict, trs: list, ufs: list, rate_cal: np.ndarray, sector_of: dict,
                identity: bool = False) -> tuple:
    """Trades, unfilled signals, data and sectors with every twinable underlying held in its twin.
    identity=True: k = 1, no fee, the underlying's own name and costs (the guard's path)."""
    cal, data = res["cal"], res["data"]
    rate_by_date = pd.Series(rate_cal, index=cal)
    data2, sec2, tw_of = dict(data), dict(sector_of), {}
    for und, (name, k) in TWINS.items():
        if und not in data:
            continue
        idx = data[und]["index"]
        close = data[und]["arr"]["Close"]
        rate = rate_by_date.reindex(idx).fillna(0.0).to_numpy()
        tk = twin_name(und)
        if tk in data2:
            raise ValueError(f"twin ticker {tk} for {und} is already in the data")
        if identity:          # the real names and the real code path; k = 1, no fee, the underlying's costs
            tw, asset = Twin(close, rate, 1.0, fee=0.0, spread=0.0), None
        else:
            tw, asset = Twin(close, rate, k), "lev"
        mine = [t for t in trs if t.ticker == und]
        pts = {t.entry_t for t in mine} | {g.t + 1 for g in ufs if g.ticker == und}
        for t in mine:
            if any(t.entry_t < q <= t.exit_t for q in pts):
                raise ValueError(f"{und}: a rebase would fall inside an open trade (bars {t.entry_t}-{t.exit_t})")
        tw.rebase(pts)
        tw_of[und] = (tw, tk, asset)
        data2[tk] = {**data[und], "index": idx, "asset": asset or data[und]["asset"],
                     "close_cal": pd.Series(tw.level, index=idx).reindex(cal).ffill()}
        sec2[tk] = sector_of.get(und)
    out_t = [twin_trade(t, *tw_of[t.ticker]) if t.ticker in tw_of else t for t in trs]
    out_u = [twin_signal(g, tw_of[g.ticker][0], tw_of[g.ticker][1]) if g.ticker in tw_of else g for g in ufs]
    return out_t, out_u, data2, sec2


# ── books and statistics ───────────────────────────────────────────────────

def book(trs, ufs, data, cal, sector_of, sw, n_slots: int) -> dict:
    sel = [t for t in trs if t.mkt_ok]
    usel = [g for g in ufs if g.mkt_ok]
    with slots(n_slots):
        p = bt.run_portfolio(sel, usel, data, cal, sector_of, sweep={"mode": "TBILL", **sw}, limits=LIMITS)
    p["sel"] = sel
    return p


def open_positions(p: dict, data: dict, cal) -> float:
    pos_of = {d: i for i, d in enumerate(cal)}
    cnt = np.zeros(len(cal))
    for tr, _sh in p["taken"]:
        idx = data[tr.ticker]["index"]
        a, b = pos_of.get(idx[tr.entry_t]), pos_of.get(idx[min(tr.exit_t, len(idx) - 1)])
        if a is not None and b is not None:
            cnt[a:b + 1] += 1
    return float(cnt.mean())


def worst_run(p: dict, data: dict) -> int:
    rs = sorted(((data[tr.ticker]["index"][min(tr.exit_t, len(data[tr.ticker]["index"]) - 1)], tr.r_net)
                 for tr, _ in p["taken"] if not tr.still_open), key=lambda z: z[0])
    best = cur = 0
    for _d, r in rs:
        cur = cur + 1 if r < -bt.SCRATCH_R else (cur if abs(r) <= bt.SCRATCH_R else 0)
        best = max(best, cur)
    return best


def summarize(p: dict, data: dict, cal, start) -> dict:
    eq = p["equity"]
    hs = bt.half_stats(eq, start)
    e = eq[eq.index >= start]
    m = e.resample("ME").last()
    mret = (m / m.shift(1).fillna(e.iloc[0]) - 1) * 100
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    taken = [tr for tr, _ in p["taken"] if data[tr.ticker]["index"][tr.entry_t] >= start]
    n_sig = sum(1 for t in p["sel"] if data[t.ticker]["index"][t.entry_t] >= start)
    stress = {}
    for k_, a, b in (("2008", "2008-01-01", "2008-12-31"), ("2020", "2020-01-01", "2020-12-31"), ("2022", "2022-01-01", "2022-12-31")):
        s = e[(e.index >= a) & (e.index <= b)]
        stress[k_] = round((s.iloc[-1] / s.iloc[0] - 1) * 100, 2) if len(s) > 1 else None
    return {"book": hs, "trades_taken": len(taken), "per_year": round(len(taken) / yrs, 1) if yrs > 0 else None,
            "per_week": round(len(taken) / yrs / 52.0, 2) if yrs > 0 else None,
            "avg_open": round(open_positions(p, data, cal), 2), "exposure_avg_pct": p.get("exposure_avg_pct"),
            "worst_month_pct": round(float(mret.min()), 2) if len(mret) else None,
            "months_le_-10pct": int((mret <= -10).sum()), "hwm_halted": bool(p.get("hwm_-20pct_breached")),
            "worst_losing_run": worst_run(p, data), "stress": stress,
            "trades_held": m0t.half_trades([tr for tr, _ in p["taken"]], data),
            "skipped_pct": round(100.0 * (1 - len(taken) / max(1, n_sig)), 1),
            "placed": len(p.get("placed") or [])}


def bar_check(s: dict, spy: dict, full: bool = True) -> list:
    why = []
    for h in ("full", "2005-15", "2016-26") if full else ("full",):
        c, cs = s["book"][h].get("cagr_pct"), spy[h].get("cagr_pct")
        if c is None or cs is None or not c > cs:
            why.append(f"{h} CAGR {c}% <= SPY {cs}%")
    dd = s["book"]["full"].get("max_dd_pct")
    if dd is None or not dd > BAR["max_dd"]:
        why.append(f"max DD {dd}% not shallower than {BAR['max_dd']}%")
    if full:
        if s["hwm_halted"]:
            why.append("the −20% high-water stop triggered")
        if s["months_le_-10pct"] > 0:
            why.append(f"{s['months_le_-10pct']} month(s) at −10% or worse (worst {s['worst_month_pct']}%)")
        for h in ("2005-15", "2016-26"):
            pf = s["trades_held"][h].get("profit_factor")
            if pf is None or not pf >= BAR["min_pf"]:
                why.append(f"{h} trade PF {pf} < {BAR['min_pf']}")
    return why


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
    trs, ufs = m0t.resimulate(res, ladder=(), rotation=False)
    _log("K0 reference and guard ...")
    p0 = book(trs, ufs, data, cal, sector_of, sw, 4)
    gt, gu, gd, gs = build_twins(res, trs, ufs, sw["rate"], sector_of, identity=True)
    pg = book(gt, gu, gd, cal, gs, sw, 4)
    guard_gap = float((pg["equity"] - p0["equity"]).abs().max())
    twt, twu, twd, tws = build_twins(res, trs, ufs, sw["rate"], sector_of)
    out = {"K0": summarize(p0, data, cal, start)}
    for key, c in CANDIDATES.items():
        _log(f"{key}: twins {c['twins']}, {c['slots']} slots ...")
        if c["twins"]:
            p = book(twt, twu, twd, cal, tws, sw, c["slots"])
            out[key] = summarize(p, twd, cal, start)
        else:
            p = book(trs, ufs, data, cal, sector_of, sw, c["slots"])
            out[key] = summarize(p, data, cal, start)
    fails = bar_check(out["K3"], spy)
    nb = {k: bar_check(out[k], spy, full=False) for k in ("K3-6", "K3-10")}
    stable = all(not v for v in nb.values())
    if guard_gap > 1e-6:
        verdict = "INVALID (guard: the k = 1 transform does not reproduce K0)"
    elif fails:
        verdict = "FAIL"
    else:
        verdict = "PASS (stable)" if stable else "PASS (not stable)"
    signals = sum(1 for t in trs if t.mkt_ok and data[t.ticker]["index"][t.entry_t] >= start)
    twinned = sorted({t.ticker for t in twt if is_twin(t.ticker)})
    return {"version": VERSION, "verdict": verdict, "fails": fails, "neighbours": nb, "stable": stable,
            "guard_gap": guard_gap, "gaps": gaps, "spy": spy, "books": out, "signals_filled": signals,
            "twins_used": twinned, "start": str(start.date()), "end": str(cal[-1].date()),
            "equity": {k: None for k in out}}


# ── output ──────────────────────────────────────────────────────────────────

def _c(x):
    return "—" if x is None else f"{x:.2f}%"


def render(r: dict, stamp: str) -> str:
    cols = ["K3", "K3-6", "K3-10", "K1", "K2", "K0"]
    b, spy = r["books"], r["spy"]
    L = [f"# Capacity lab {VERSION} — M0-T with leveraged twins — {stamp}", "",
         f"Pre-registered in `claude/cap_lab_2026-11-25.md`. Swing trials {TRIALS_BEFORE} → {TRIALS_BEFORE + TRIALS_HERE}. "
         "Research, not personalized advice.", "",
         f"## K3 (twins, 8 slots): **{r['verdict']}**",
         f"- Fails: {'; '.join(r['fails']) or 'none'}",
         "- Neighbours (beat SPY full, DD > −20%): " + "; ".join(f"{k}: {'meets' if not v else '; '.join(v)}" for k, v in r["neighbours"].items()),
         f"- Guard (k = 1 transform reproduces K0): max gap ${r['guard_gap']:.6f}",
         f"- Window {r['start']} → {r['end']}; M0-T trades (SPY above its 200-day): {r['signals_filled']}; twins used: {', '.join(r['twins_used'])}",
         "", "| | " + " | ".join(cols) + " | SPY |", "|---" * (len(cols) + 2) + "|"]
    for lab, h in (("CAGR 2005–26", "full"), ("CAGR 2005–15", "2005-15"), ("CAGR 2016–26", "2016-26")):
        L.append(f"| {lab} | " + " | ".join(_c(b[c]["book"][h].get("cagr_pct")) for c in cols) + f" | {_c(spy[h].get('cagr_pct'))} |")
    L.append("| Max DD | " + " | ".join(_c(b[c]["book"]["full"].get("max_dd_pct")) for c in cols) + f" | {_c(spy['full'].get('max_dd_pct'))} |")
    rows = [("Trades taken / year", "per_year"), ("… per week", "per_week"), ("Avg open positions", "avg_open"),
            ("Avg invested %", "exposure_avg_pct"), ("Worst month", "worst_month_pct"), ("Months ≤ −10%", "months_le_-10pct"),
            ("−20% stop triggered", "hwm_halted"), ("Worst losing run", "worst_losing_run"),
            ("Signals skipped %", "skipped_pct")]
    for lab, k in rows:
        L.append(f"| {lab} | " + " | ".join(str(b[c].get(k)) for c in cols) + " | |")
    for yr in ("2008", "2020", "2022"):
        L.append(f"| {yr} | " + " | ".join(_c(b[c]["stress"].get(yr)) for c in cols) + " | |")
    for h in ("2005-15", "2016-26"):
        L.append(f"| Trade PF {h} | " + " | ".join(str(b[c]["trades_held"][h].get("profit_factor")) for c in cols) + " | |")
        L.append(f"| Expectancy {h} (R) | " + " | ".join(str(b[c]["trades_held"][h].get("expectancy_R")) for c in cols) + " | |")
    if r["gaps"]:
        L += ["", "Data gaps: " + "; ".join(r["gaps"])]
    L += ["", "Trade PF and expectancy are on the trades each book took (twin-expressed, net of costs). "
          "Shared-backtest note: an order rejected for cash or heat still uses up a slot (as in trial 97; works against capacity).",
          "", "Twins are modelled (k × daily return − fee − borrowing), not real price histories. "
          "K0 = M0-T reference with the swing limits on (not a trial).", "", f"*cap_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def _jsonable(v):
    if isinstance(v, dict):
        return {(k.date().isoformat() if isinstance(k, pd.Timestamp) else str(k)): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return float(v) if np.isfinite(v) else None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    return v


def write_outputs(r: dict, stamp: str, out_dir: Path = OUT_DIR, log_dir: Path = LOG_DIR) -> str:
    md = render(r, stamp)
    js = json.dumps(_jsonable({k: v for k, v in r.items() if k != "equity"}), indent=1, default=str, allow_nan=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(js)
    (log_dir / "latest.md").write_text(md)
    (log_dir / f"{stamp}.md").write_text(md)
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
        print(f"[cap_lab] DATA FAILURE: no prices for {', '.join(miss) or 'SPY'} after retries; nothing written.")
        return 1
    rates = {}
    for attempt in range(3):
        rates = fetch(["^IRX"]) or {}
        if "^IRX" in rates and len(rates["^IRX"]):
            break
        _log(f"retry {attempt + 1}: ^IRX")
    irx = (rates or {}).get("^IRX")
    last = ohlcv["SPY"].index[-1]
    # zero-yield prints (2009–15, 2020–21) are dropped by the fetch and forward-filled: immaterial; a series
    # that is empty, starts late or ends early is not
    if irx is None or not len(irx) or irx.index[0] > max(ohlcv["SPY"].index[0], pd.Timestamp("2005-01-01")) + pd.Timedelta(days=90) or \
            irx.index[-1] < last - pd.Timedelta(days=7):
        print("[cap_lab] DATA FAILURE: no T-bill yield (^IRX): twin borrowing costs unknown; nothing written.")
        return 1
    r = analyse(ohlcv, rates)
    if r["verdict"].startswith("INVALID"):
        print(f"[cap_lab] {r['verdict']} (gap ${r['guard_gap']:.6f}); nothing written.")
        return 1
    md = write_outputs(r, stamp)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    import os, tempfile
    import m0t_paper as mp
    f = []
    # 1. twin arithmetic
    C = np.array([100.0, 101.0, 99.0, 102.0, 102.0])
    tw = Twin(C, np.zeros(5), 3.0, fee=0.0, spread=0.0)
    if abs(tw.L[1] / tw.L[0] - 1.03) > 1e-12 or abs(tw.L[2] / tw.L[1] - (1 + 3 * (99 / 101 - 1))) > 1e-12:
        f.append("twin level must compound k × the daily return")
    if abs(tw.price(C[3], 3) - tw.L[3]) > 1e-9 or abs(tw.price(C[2] * 1.01, 3) - tw.L[2] * 1.03) > 1e-9:
        f.append("twin price map: the close maps to the level; +1% on the underlying is +3% on the twin")
    tc = Twin(C, np.full(5, 0.04 / 252), 3.0)
    want_c = FEE / 252 + 2 * (0.04 / 252 + SPREAD / 252)
    if abs(tc.c[2] - want_c) > 1e-15 or not tc.L[4] < tw.L[4]:
        f.append("twin costs: fee + (k−1) × (T-bill + spread) every day")
    tr_ = Twin(C, np.zeros(5), 3.0, fee=0.0, spread=0.0)
    tr_.rebase([3])
    if abs(tr_.level[2] - tw.L[2]) > 1e-9 or abs(tr_.price(C[2], 3) - C[2]) > 1e-9 or \
            abs(tr_.level[4] / tr_.level[3] - tw.L[4] / tw.L[3]) > 1e-12 or abs(tr_.price(C[3], 3) / tr_.level[3] - 1) > 1e-12:
        f.append("rebase: scale only from the entry bar (last close = the underlying's), returns unchanged")
    ti = Twin(C, np.full(5, 0.04 / 252), 1.0, fee=0.0, spread=0.0)
    if np.abs(ti.L - C).max() > 1e-9 or abs(ti.price(100.5, 2) - 100.5) > 1e-9:
        f.append("k = 1 with no fee must be the identity")
    # 2. real fixture: bt.run on synthetic funds incl. a twinable underlying and a leveraged member
    ohl = mp._fixture(n=900, k=["SPY", "XLE", "XLU", "XLV", "QQQ", "TQQQ", "XLK", "XHB", "ITB"])
    ohl["ITB"] = ohl["ITB"].iloc[60:]                     # ITB starts later than XHB (as in real history)
    etfs = list(ohl)
    sector_of = {"XLE": "XLE", "XLU": "XLU", "XLV": "XLV", "QQQ": "XLK", "TQQQ": "XLK", "XLK": "XLK",
                 "XHB": "XHB", "ITB": "ITB"}
    with contextlib.redirect_stdout(io.StringIO()):
        res = bt.run(ohl, etfs, [], sector_of, setups=("M0",), variants=("B",), verbose=False)
    cal = res["cal"]
    irx = {"^IRX": pd.DataFrame({"Open": 4.0, "High": 4.0, "Low": 4.0, "Close": 4.0, "Volume": 0}, index=cal)}
    sw, _g = bt.sweep_inputs(ohl, irx, cal)
    trs, ufs = m0t.resimulate(res, ladder=(), rotation=False)
    if not any(t.ticker in TWINS for t in trs):
        f.append("fixture: needs trades on a twinable underlying")
    p0 = book(trs, ufs, res["data"], cal, sector_of, sw, 4)
    gt, gu, gd, gs = build_twins(res, trs, ufs, sw["rate"], sector_of, identity=True)
    pg = book(gt, gu, gd, cal, gs, sw, 4)
    if float((pg["equity"] - p0["equity"]).abs().max()) > 1e-6:
        f.append(f"guard: the k = 1 transform must reproduce K0 (gap {float((pg['equity'] - p0['equity']).abs().max()):.4f})")
    if any(abs(a.r_net - b.r_net) > 1e-9 for a, b in zip(gt, trs)):
        f.append("guard: identical trades must keep identical R")
    if any(a.ticker != b.ticker for a, b in zip(trs, gt) if a.ticker not in TWINS) or \
            {b.ticker for a, b in zip(trs, gt) if a.ticker in TWINS} - {twin_name(u) for u in TWINS}:
        f.append("guard must run under the real twin names (the renaming is part of the path)")
    twt, twu, twd, tws = build_twins(res, trs, ufs, sw["rate"], sector_of)
    names = {t.ticker for t in twt}
    # inside every twin trade the twin's daily move is exactly k × the underlying's less costs (no rebase mid-trade)
    rate_s = pd.Series(sw["rate"], index=cal)
    bad_ = 0
    for a, b in zip(trs, twt):
        if not is_twin(b.ticker):
            continue
        k_ = TWINS[a.ticker][1]
        idx_ = twd[b.ticker]["index"]
        lv = twd[b.ticker]["close_cal"].reindex(idx_).to_numpy()
        cu = res["data"][a.ticker]["arr"]["Close"]
        rt = rate_s.reindex(idx_).fillna(0.0).to_numpy()
        for j in range(a.entry_t + 1, a.exit_t + 1):
            want = 1 + k_ * (cu[j] / cu[j - 1] - 1) - (FEE / 252 + (k_ - 1) * (rt[j] + SPREAD / 252))
            if abs(lv[j] / lv[j - 1] - want) > 1e-9:
                bad_ += 1
    if bad_:
        f.append(f"twin level inside a trade must move k × the underlying less costs ({bad_} bars off)")
    # ITB and XHB share NAIL: each keeps its own held ticker, dates and level (review BLOCKER)
    if twin_name("ITB") == twin_name("XHB"):
        f.append("ITB and XHB must not share a held ticker")
    for u in ("ITB", "XHB"):
        tk_ = twin_name(u)
        if not twd[tk_]["index"].equals(res["data"][u]["index"]):
            f.append(f"{tk_} must use {u}'s own dates")
    itb = [(a, b) for a, b in zip(trs, twt) if a.ticker == "ITB"]
    if not itb:
        f.append("fixture: needs ITB trades")
    for a, b in itb:
        d_ = res["data"]["ITB"]["index"][a.entry_t]
        lvl = twd[b.ticker]["close_cal"].get(d_)
        if b.ticker != twin_name("ITB") or lvl is None or abs(lvl / b.entry - 1) > 0.25:
            f.append(f"ITB trade must be marked on ITB's own twin level ({b.ticker}, {lvl} vs entry {b.entry:.2f})")
            break
    # a rebase point inside an open trade must stop the build (review 3, m1)
    tw_tr = next(a for a in trs if a.ticker in TWINS and a.exit_t > a.entry_t + 1)
    inj = copy.deepcopy(next(g for g in ufs) if ufs else None)
    if inj is not None:
        inj.ticker, inj.t = tw_tr.ticker, tw_tr.entry_t       # its entry bar t+1 falls inside the trade
        try:
            build_twins(res, trs, ufs + [inj], sw["rate"], sector_of)
            f.append("a rebase inside an open trade must raise")
        except ValueError:
            pass
    # a twin signal with no stop on the card ranks at 1.0, as its underlying does (review 3, m3)
    sg0 = copy.deepcopy(next(g for g in ufs))
    sg0.stop = None
    tw0 = Twin(np.array([100.0, 101.0, 102.0, 103.0] * 50), np.zeros(200), 3.0)
    sg0.t = 5
    if twin_signal(sg0, tw0, "X~Y").rank_frac is not None:
        f.append("a twin signal with no stop must leave rank_frac unset (rank falls back to 1.0)")
    old_tn = twin_name
    try:
        globals()["twin_name"] = lambda u: f"{TWINS[u][0]}*"
        try:
            build_twins(res, trs, ufs, sw["rate"], sector_of)
            f.append("a shared twin ticker must raise, not overwrite")
        except ValueError:
            pass
    finally:
        globals()["twin_name"] = old_tn
    if any(t in names for t in TWINS if t in ohl):
        f.append("every twinable underlying must be held in its twin")
    if not {"XLE~ERX", "XLU~UTSL", "XLV~CURE"} & names:
        f.append(f"twins must appear under their own names ({sorted(names)})")
    if any(t.ticker.startswith(tuple(f"{u}~" for u in HAS_MEMBER)) for t in twt) or \
            ("QQQ" in {t.ticker for t in trs} and "QQQ" not in names):
        f.append("an underlying with a leveraged member (QQQ, XLK) must not get a twin")
    if "TQQQ" in {t.ticker for t in trs} and "TQQQ" not in names:
        f.append("leveraged members trade as they are")
    # a twin trade: 1/k of the cash for the same 1% risk; R ~ the underlying's (small moves), costs charged
    pairs = [(a, b) for a, b in zip(trs, twt) if a.ticker in TWINS]
    a, b = pairs[0]
    k = TWINS[a.ticker][1]
    frac_u = a.risk / (a.stop0 + a.risk)
    frac_t = b.risk / (b.stop0 + b.risk)
    if not (abs(frac_t / frac_u - k) < 0.05 * k):
        f.append(f"twin stop distance must be ~k × the underlying's ({frac_t:.4f} vs {k} × {frac_u:.4f})")
    if b.asset != "lev" or b.events[0][4] != bt.COST_BPS["lev"]:
        f.append("twin positions pay the leveraged cost")
    ok_r = [abs(x.r_net - y.r_net) < 0.6 + 0.5 * abs(x.r_net) for x, y in pairs if not x.still_open]
    if sum(ok_r) < 0.8 * len(ok_r):
        f.append("twin R should track the underlying's R (same trade, k × the stop distance)")
    # candidates run, limits passed, slots honoured
    got = {}
    orig = bt.run_portfolio

    def spy_rp(*a_, **k_):
        got["limits"] = k_.get("limits"); got["slots"] = bt.MAX_POSITIONS
        return orig(*a_, **k_)
    bt.run_portfolio = spy_rp
    try:
        book(twt, twu, twd, cal, tws, sw, 8)
    finally:
        bt.run_portfolio = orig
    if got.get("limits") != LIMITS or got.get("slots") != 8 or bt.MAX_POSITIONS != 4:
        f.append(f"book must pass the swing limits and set (then restore) the slot count ({got}, now {bt.MAX_POSITIONS})")
    p8 = book(twt, twu, twd, cal, tws, sw, 8)
    p1 = book(twt, twu, twd, cal, tws, sw, 1)
    st0 = cal[min(len(cal) - 1, 260)]
    s8, s1 = summarize(p8, twd, cal, st0), summarize(p1, twd, cal, st0)
    if not s8["avg_open"] >= 0 or s8["trades_taken"] < 1:
        f.append("summarize: open positions / trades taken")
    if not (s1["trades_taken"] < s8["trades_taken"] and s1["avg_open"] <= 1.0 + 1e-9):
        f.append(f"a binding slot count must cut trades ({s1['trades_taken']} vs {s8['trades_taken']}, avg open {s1['avg_open']})")
    # selection: with one slot and limits off, the twin book must take the same trades as M0-T (review MAJOR)
    def picks(t_, u_, d_, s_):
        with slots(1):
            pp = bt.run_portfolio([t for t in t_ if t.mkt_ok], [g for g in u_ if g.mkt_ok], d_, cal, s_,
                                  sweep={"mode": "TBILL", **sw}, limits=None)
        return sorted((d_[tr.ticker]["index"][tr.entry_t], tr.ticker.split("~")[0]) for tr, _ in pp["taken"])
    pk0, pk3 = picks(trs, ufs, res["data"], sector_of), picks(twt, twu, twd, tws)
    if pk0 != pk3:
        f.append(f"twins must rank as their underlyings ({len(set(pk0) ^ set(pk3))} picks differ)")
    n_taken_closed = sum(1 for tr, _ in p8["taken"] if not tr.still_open)
    if s8["trades_held"]["full"].get("n") != n_taken_closed:
        f.append("trade PF must be on the trades the book took (review MAJOR)")
    if not 0 <= s8["skipped_pct"] < 100 or not s1["skipped_pct"] > s8["skipped_pct"]:
        f.append("skipped share of signals")
    # the guard runs the real transform: a k = 1 map that is off by 0.1% must make the run INVALID
    old_price = Twin.price
    try:
        Twin.price = lambda self, p_, t_: old_price(self, p_, t_) * (1.001 if self.k == 1.0 else 1.0)
        with contextlib.redirect_stdout(io.StringIO()):
            rb = analyse(ohl, irx)
        if not rb["verdict"].startswith("INVALID"):
            f.append(f"guard must use the twin transform itself (broken k = 1 map gave {rb['verdict']})")
    finally:
        Twin.price = old_price
    # bars
    spyx = {"full": {"cagr_pct": 10.0}, "2005-15": {"cagr_pct": 7.0}, "2016-26": {"cagr_pct": 14.0}}

    def S(c, c1, c2, dd=-15.0, halted=False, m10=0, pf=1.5):
        return {"book": {"full": {"cagr_pct": c, "max_dd_pct": dd}, "2005-15": {"cagr_pct": c1}, "2016-26": {"cagr_pct": c2}},
                "hwm_halted": halted, "months_le_-10pct": m10, "worst_month_pct": -11.0 if m10 else -5.0,
                "trades_held": {"2005-15": {"profit_factor": pf}, "2016-26": {"profit_factor": pf}}}
    if bar_check(S(11, 8, 15), spyx) or not bar_check(S(11, 6, 15), spyx) or not bar_check(S(11, 8, 15, dd=-21), spyx) or \
            not bar_check(S(11, 8, 15, halted=True), spyx) or not bar_check(S(11, 8, 15, m10=1), spyx) or \
            not bar_check(S(11, 8, 15, pf=1.2), spyx) or bar_check(S(11, 6, 13), spyx, full=False):
        f.append("bar logic")
    # main: clean run writes; missing data / no T-bill stop with nothing written
    tmp = Path(tempfile.mkdtemp())
    cwd = os.getcwd()
    old_sect, old_other = bt.SECTOR_ETFS, bt.OTHER_ETFS
    try:
        os.chdir(tmp)
        bt.SECTOR_ETFS = ["XLE", "XLU", "XLV", "XLK"]
        bt.OTHER_ETFS = {"SPY": None, "QQQ": "XLK", "TQQQ": "XLK", "XHB": "XHB", "ITB": "ITB"}
        allp = {**ohl, **irx}
        with contextlib.redirect_stdout(io.StringIO()):
            rc_ok = main(fetch=lambda tks, start=None: {t: allp[t] for t in tks if t in allp})
        if rc_ok != 0 or not (tmp / "data" / "cap_lab" / "summary.json").exists():
            f.append(f"main: a clean synthetic run must write outputs (rc {rc_ok})")
        else:
            js = json.loads((tmp / "data" / "cap_lab" / "summary.json").read_text())
            if js["guard_gap"] > 1e-6 or set(js["books"]) != {"K0", *CANDIDATES}:
                f.append("main: guard exact and every candidate reported")
        import shutil
        shutil.rmtree(tmp / "data", ignore_errors=True)
        with contextlib.redirect_stdout(io.StringIO()):
            rc_m = main(fetch=lambda tks, start=None: {t: allp[t] for t in tks if t in allp and t != "XLU"})
            rc_r = main(fetch=lambda tks, start=None: {t: allp[t] for t in tks if t in allp and t != "^IRX"})
            emp = {**allp, "^IRX": irx["^IRX"].iloc[:0]}
            rc_e = main(fetch=lambda tks, start=None: {t: emp[t] for t in tks if t in emp})
            short = {**allp, "^IRX": irx["^IRX"].iloc[:-30]}
            rc_s = main(fetch=lambda tks, start=None: {t: short[t] for t in tks if t in short})
            late = {**allp, "^IRX": irx["^IRX"].iloc[100:]}
            rc_l = main(fetch=lambda tks, start=None: {t: late[t] for t in tks if t in late})
            rc_s = rc_s if rc_l == 1 else 0
            old_price = Twin.price
            try:
                Twin.price = lambda self, p_, t_: old_price(self, p_, t_) * (1.001 if self.k == 1.0 else 1.0)
                rc_i = main(fetch=lambda tks, start=None: {t: allp[t] for t in tks if t in allp})
            finally:
                Twin.price = old_price
        if (rc_m, rc_r, rc_e, rc_s, rc_i) != (1, 1, 1, 1, 1) or (tmp / "data" / "cap_lab").exists():
            f.append(f"main: a missing fund, a missing / empty / short T-bill series or an INVALID guard must stop "
                     f"with nothing written ({rc_m}, {rc_r}, {rc_e}, {rc_s}, {rc_i})")
    except Exception as e:
        import traceback
        f.append(f"pipeline crashed: {type(e).__name__}: {e} {traceback.format_exc()[-500:]}")
    finally:
        os.chdir(cwd)
        bt.SECTOR_ETFS, bt.OTHER_ETFS = old_sect, old_other
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r_ = selftest()
        print(json.dumps(r_, indent=2, default=str))
        sys.exit(0 if r_["ok"] else 1)
    sys.exit(main())
