"""
rot3_lab.py  (v1.0 — 2026-11-20)
─────────────────────────────────
Track D: ROT3, sector leadership rotation (design: claude/system_review_2026-11-14.md
§6.3; pre-registration: claude/rot3_lab_2026-11-20.md). Approved by Matt 2026-11-18
("Let's look at all of them") and 2026-11-20 ("yes, please").

ROT3 (frozen before any run)
  Universe   the 11 SPDR sector ETFs + QQQ. A fund is eligible at a month-end only
             once it has 12 months of history (XLRE from late 2016, XLC from mid 2019).
  Signal     at each month-end close, rank by the average of the 3-, 6- and
             12-month total returns.
  Hold       the top 3, a third each; a pick held only if its month-end close is
             above its own 10-month average of month-end closes, else that third
             sits in T-bills (SGOV, spliced to ^IRX before it existed).
  Trade      the first session of the next month (weights set at that close, the
             same one-session lag the engine lab uses); 5bp a side.

USE A  long-term book: ROT3 replaces 50/50 QQQ/SPY as O11's Offense book. The
       Offense −8% stop measures the ROT3 book from its high since entry. Every
       other O11 rule unchanged. Balanced = today's regime book (C3), as in the
       offense lab.
       BAR A: engine CAGR above O11's in BOTH halves (2005–15, 2016–26) and max
       drawdown 2000–2026 no deeper than −20%.
USE B  swing book: ROT3 holds the swing book's idle cash instead of T-bills. Same
       trades as the live configuration (M0, stop B, SPY > 200-day filter, ETF
       universe; stock cards are paper-only), same sizing and limits; the sweep
       buys at the open with yesterday's idle cash and is sold at the open to fund
       entries (swing_backtest v1.3 accounting, 3bp a side). ROT3 is held as one
       fund whose open and close are built from its holdings.
       BAR B: full-window CAGR at least 2.0 points above the T-bill version, higher
       than the T-bill version in both halves, max drawdown no deeper than −20%
       (the swing book's high-water stand-down).
STABILITY (reported, not part of the bar): each use re-run with an 8- and a
       12-month trend average. STABLE = both neighbours also meet the bar.
TRIALS: 2 decisions + 4 neighbour runs = 6 (long-term 28 → 31, swing 81 → 84).
No tuning after the run: a FAIL is final for this design.

Run:  python rot3_lab.py            (Actions, ~20–40 min)
      python rot3_lab.py --selftest (offline)
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
UNIVERSE = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLU", "XLRE", "XLB", "XLC", "XLP", "QQQ")
LOOKBACK_M = (3, 6, 12)
TOP_N = 3
TREND_M = 10
NEIGHBOURS = (8, 12)
COST_BPS = 5.0
CASH = "SGOV"
BAR_A_DD = 20.0
BAR_B_EDGE, BAR_B_DD = 2.0, 20.0
HISTORY_START = "1998-01-01"
OUT_DIR, LOG_DIR = Path("data/rot3_lab"), Path("logs/rot3_lab")


# ── ROT3 signal ─────────────────────────────────────────────────────────────

def month_ends(levels: pd.DataFrame) -> pd.DataFrame:
    """Rows at the last trading day of each month in `levels`' index (values as of that close)."""
    idx = levels.index
    last = pd.Series(idx, index=idx).groupby(idx.to_period("M")).max()
    return levels.loc[last.to_numpy()]


def rot3_targets(me: pd.DataFrame, trend_m: int = TREND_M, top: int = TOP_N,
                 lookbacks: tuple = LOOKBACK_M) -> dict:
    """{month-end date: {ticker or CASH: weight %}}. Uses month-end closes up to that date only."""
    out = {}
    L = max(max(lookbacks), trend_m - 1)
    vals = me.to_numpy(dtype=float)
    cols = list(me.columns)
    for i, d in enumerate(me.index):
        if i < L:
            out[d] = {CASH: 100.0}
            continue
        scores = {}
        for j, t in enumerate(cols):
            win = vals[i - L:i + 1, j]
            if not np.isfinite(win).all():
                continue                                   # not enough history yet
            c = vals[i, j]
            scores[t] = float(np.mean([c / vals[i - k, j] - 1 for k in lookbacks]))
        picks = sorted(scores, key=lambda t: (-scores[t], t))[:top]
        w = {}
        for t in picks:
            j = cols.index(t)
            sma = float(np.mean(vals[i - trend_m + 1:i + 1, j]))
            key = t if vals[i, j] > sma else CASH
            w[key] = w.get(key, 0.0) + 100.0 / top
        missing = top - len(picks)
        if missing > 0:
            w[CASH] = w.get(CASH, 0.0) + 100.0 * missing / top
        out[d] = w
    return out


def weights_lookup(targets: dict) -> Callable:
    """w(d): the target from the latest month-end STRICTLY before d (all cash before the first)."""
    keys = sorted(targets)
    karr = np.array(keys, dtype="datetime64[ns]")

    def w(d) -> dict:
        i = int(np.searchsorted(karr, np.datetime64(pd.Timestamp(d)), side="left")) - 1
        return dict(targets[keys[i]]) if i >= 0 else {CASH: 100.0}
    return w


# ── use A: inside the O11 engine ───────────────────────────────────────────

def states_off(levels: pd.DataFrame, off_idx: np.ndarray, ma: int = ol.MA, fast_sma: int = ol.FAST_SMA,
               fast_stop: float = ol.FAST_STOP, cooldown: int = ol.COOLDOWN, credit: bool = True) -> pd.Series:
    """offense_lab.states_fast with the Offense stop measured on `off_idx` (the Offense book's own
    index) instead of 50/50 SPY/QQQ. Identical otherwise (selftest checks equality on 50/50)."""
    spy_up, qqq_up = ol.above_ma(levels["SPY"], ma), ol.above_ma(levels["QQQ"], ma)
    q50 = ol.above_ma(levels["QQQ"], fast_sma)
    known = spy_up.notna() & qqq_up.notna() & q50.notna()
    spy_dn2, qqq_dn2, q50_dn2 = ol._two_down(spy_up).to_numpy(), ol._two_down(qqq_up).to_numpy(), ol._two_down(q50).to_numpy()
    entry = (ol._two_up(spy_up) & ol._two_up(qqq_up) & ol._two_up(q50)).to_numpy()
    spy_up2 = ol._two_up(spy_up).to_numpy()
    if credit:
        c_up = ol.above_ma(levels["CREDIT"], ol.CREDIT_SMA) if "CREDIT" in levels else pd.Series(np.nan, index=levels.index)
        c_ok = (ol._two_down(c_up) | c_up.isna()).to_numpy()
    else:
        c_ok = np.ones(len(levels), dtype=bool)
    idx = np.asarray(off_idx, dtype=float)
    out, state, peak, out_i = [], "BAL", None, -10 ** 9
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
        elif state == "DEF" and spy_up2[i]:
            state = "BAL"
        out.append(state)
    return pd.Series(out, index=levels.index, dtype=object)


def engine_weights(st: pd.Series, rot_w: Callable, balanced: dict, lag: int = ol.LAG) -> Callable:
    """O11's books, with ROT3 as Offense. The state seen `lag` sessions before d sets d's weights."""
    lagged = st.shift(lag)
    lagged.iloc[:lag] = st.iloc[0]
    m = lagged.to_dict()
    o11 = ol.CANDIDATES["O11"]

    def w(d):
        s = m[d]
        return rot_w(d) if s == "OFF" else dict(ol.book_for(s, o11, balanced))
    return w


def add_universe_returns(data: dict) -> pd.DataFrame:
    rets = data["rets"].copy()
    for t in UNIVERSE:
        if t not in rets.columns or rets[t].isna().all():
            rets[t] = hl.ticker_returns(data["closes"], t, data["cal"])
    return rets


def universe_levels(closes: dict, cal: pd.DatetimeIndex) -> pd.DataFrame:
    lv = {}
    for t in UNIVERSE:
        s = closes.get(t)
        lv[t] = hl._norm(s).reindex(cal).ffill(limit=3) if s is not None and len(s) else pd.Series(np.nan, index=cal)
        if s is not None and len(s):
            lv[t][cal < hl._norm(s).index[0]] = np.nan
    return pd.DataFrame(lv, index=cal)


def run_use_a(data: dict, balanced: dict, trend_m: int = TREND_M) -> dict:
    cal = data["cal"]
    rets = add_universe_returns(data)
    lv = universe_levels(data["closes"], cal)
    targets = rot3_targets(month_ends(lv), trend_m)
    rot_w = weights_lookup(targets)
    days_all = cal
    alone = hl.simulate(days_all, rets, rot_w, None, breaker=False, cost_bps=COST_BPS)["nav"]
    st = states_off(data["levels"], alone.reindex(cal).to_numpy(), credit=True)
    days = cal[cal >= pd.Timestamp(ol.EVAL_START) - pd.Timedelta(days=10)]
    sim = hl.simulate(days, rets, engine_weights(st, rot_w, balanced), None, breaker=False, cost_bps=COST_BPS)
    ev = st.reindex(days)
    ev = ev[ev.index >= pd.Timestamp(ol.EVAL_START)]
    return {"nav": sim["nav"], "alone": alone, "states": st, "targets": targets,
            "share": ev.value_counts(normalize=True).mul(100).round(1).to_dict(),
            "fast_exits": int(((ev == "OUT") & (ev.shift(1) != "OUT")).sum())}


def bar_a(st: dict, base: dict) -> list:
    why = []
    for k in ("2005-15", "2016-26"):
        c, b = (st.get(k) or {}).get("cagr_pct"), (base.get(k) or {}).get("cagr_pct")
        if c is None or b is None or not c > b:
            why.append(f"{k} CAGR {c}% ≤ O11 {b}%")
    d = (st.get("full") or {}).get("max_dd_pct")
    if d is None or abs(d) > BAR_A_DD + 1e-9:
        why.append(f"max DD {d}% deeper than −{BAR_A_DD:g}%")
    return why


# ── use B: swing idle cash ─────────────────────────────────────────────────

def rot3_fund(opens: pd.DataFrame, closes: pd.DataFrame, rate: np.ndarray, rot_w: Callable,
              cal: pd.DatetimeIndex) -> tuple:
    """ROT3 as one fund on `cal`: (open, close) arrays starting at 100.
    Weights held over day k were set at close k-1 (rot_w(cal[k-1])). Cash earns rate[k-1].
    A holding with no bar that day contributes 0. Costs 5bp on turnover, taken on the day traded."""
    n = len(cal)
    o = opens.reindex(cal).to_numpy(dtype=float)
    c = closes.reindex(cal).to_numpy(dtype=float)
    cols = list(closes.columns)
    col_i = {t: j for j, t in enumerate(cols)}
    op, cl = np.full(n, np.nan), np.full(n, np.nan)
    cl[0] = op[0] = 100.0
    prev_w = rot_w(cal[0])
    for k in range(1, n):
        w = prev_w
        gap = ret = 0.0
        for t, wt in w.items():
            f = wt / 100.0
            if t == CASH:
                ret += f * (rate[k - 1] if np.isfinite(rate[k - 1]) else 0.0)
                continue
            j = col_i.get(t)
            if j is None:
                continue
            cp, oo, cc = c[k - 1, j], o[k, j], c[k, j]
            if np.isfinite(cp) and cp > 0 and np.isfinite(cc):
                ret += f * (cc / cp - 1)
                if np.isfinite(oo):
                    gap += f * (oo / cp - 1)
        new_w = rot_w(cal[k])
        turn = sum(abs(new_w.get(t, 0.0) - w.get(t, 0.0)) for t in set(new_w) | set(w)) / 2.0
        op[k] = cl[k - 1] * (1 + gap)
        cl[k] = cl[k - 1] * (1 + ret) * (1 - turn / 100.0 * COST_BPS / 1e4)
        prev_w = new_w
    return op, cl


def bar_b(rot: dict, tb: dict, hwm_breach: bool) -> list:
    why = []
    c, b = (rot.get("full") or {}).get("cagr_pct"), (tb.get("full") or {}).get("cagr_pct")
    if c is None or b is None or not c >= b + BAR_B_EDGE - 1e-9:
        why.append(f"full CAGR {c}% < T-bill version {b}% + {BAR_B_EDGE:g}")
    for k in ("2005-15", "2016-26"):
        c, b = (rot.get(k) or {}).get("cagr_pct"), (tb.get(k) or {}).get("cagr_pct")
        if c is None or b is None or not c > b:
            why.append(f"{k} CAGR {c}% ≤ T-bill version {b}%")
    d = (rot.get("full") or {}).get("max_dd_pct")
    if d is None or abs(d) > BAR_B_DD + 1e-9 or hwm_breach:
        why.append(f"max DD {d}% deeper than −{BAR_B_DD:g}% (stand-down)")
    return why


def run_use_b(trend_ms=(TREND_M, *NEIGHBOURS)) -> dict:
    import swing_backtest as sb
    etfs = sb.SECTOR_ETFS + list(sb.OTHER_ETFS)
    sector_of = {s: s for s in sb.SECTOR_ETFS}
    sector_of.update(sb.OTHER_ETFS)
    ohlcv = sb.fetch_ohlcv(sorted(set(etfs)))
    if "SPY" not in ohlcv:
        raise RuntimeError("no SPY history for the swing run")
    rates = sb.fetch_ohlcv(["^IRX"])
    res = sb.run(ohlcv, etfs, [], sector_of, setups=("M0",), variants=("B",), verbose=False)
    cal = res["cal"]
    sel = [t for t in res["trades"]["B"] if t.setup == "M0" and t.mkt_ok]
    uf = [g for g in res["unfilled"] if g.setup == "M0" and g.mkt_ok]
    sw, gaps = sb.sweep_inputs(ohlcv, rates, cal)
    start = cal[sb.WINDOW] if len(cal) > sb.WINDOW else cal[0]
    tb = sb.run_portfolio(sel, uf, res["data"], cal, sector_of, sweep={"mode": "TBILL", **sw})
    long = sb.fetch_ohlcv(list(UNIVERSE), start=HISTORY_START)
    O = pd.DataFrame({t: v["Open"] for t, v in long.items()})
    C = pd.DataFrame({t: v["Close"] for t, v in long.items()})
    out = {"tbill": tb, "tbill_h": sb.half_stats(tb["equity"], start), "start": start, "gaps": gaps,
           "trades": len(sel), "runs": {}, "missing": [t for t in UNIVERSE if t not in long],
           "spy_h": sb.half_stats(ohlcv["SPY"]["Close"].reindex(cal).ffill(), start)}
    for tm in trend_ms:
        targets = rot3_targets(month_ends(C), tm)
        op, cl = rot3_fund(O, C, sw["rate"], weights_lookup(targets), cal)
        p = sb.run_portfolio(sel, uf, res["data"], cal, sector_of,
                             sweep={"mode": "SPY", "open": op, "close": cl, "rate": sw["rate"], "ok": sw["ok"]})
        h = sb.half_stats(p["equity"], start)
        out["runs"][tm] = {"port": p, "h": h, "why": bar_b(h, out["tbill_h"], p["hwm_-20pct_breached"]),
                           "fund": pd.Series(cl, index=cal)}
    return out


# ── report ──────────────────────────────────────────────────────────────────

def _f(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


def latest_picks(targets: dict) -> tuple:
    """The holdings in force now: the last COMPLETED month-end (a partial month's last day is not one)."""
    keys = sorted(targets)
    cur = keys[-1].to_period("M")
    done = [k for k in keys if k.to_period("M") < cur]
    d = done[-1] if done else keys[-1]
    return d, targets[d]


def render(A: dict, B: dict, stamp: str, n_trials: dict) -> str:
    L = [f"# ROT3 lab {VERSION} — {stamp}", "",
         "Track D. Rules and bars fixed before the run (claude/rot3_lab_2026-11-20.md). No tuning after it. "
         "Research, not personalized advice.", ""]
    if A:
        o = A["summ"]["O11"]
        L += ["## Use A — ROT3 as O11's Offense book (long-term)", "",
              f"**Verdict: {A['verdict']}**" + (f" — {A['why']}" if A["why"] else ""), "",
              "| Book | CAGR 2000–26 | 2005–15 | 2016–26 | Max DD | Sharpe |", "|---|---|---|---|---|---|"]
        for k in ("ROT3-engine", "O11", "ROT3 alone", "SPY", "QQQ"):
            x = A["summ"][k]
            L.append(f"| {k} | {_f(x['full'].get('cagr_pct'))}% | {_f(x['2005-15'].get('cagr_pct'))}% | "
                     f"{_f(x['2016-26'].get('cagr_pct'))}% | {_f(x['full'].get('max_dd_pct'), 1)}% | {_f(x['full'].get('sharpe'))} |")
        L += ["", f"Engine time in each state (2000+): {A['share']}; fast exits: {A['fast_exits']}.",
              f"O11 reproduced: {_f(o['full'].get('cagr_pct'))}% / {_f(o['2005-15'].get('cagr_pct'))}% / "
              f"{_f(o['2016-26'].get('cagr_pct'))}%, max DD {_f(o['full'].get('max_dd_pct'), 1)}% "
              "(offense lab with C3: 9.55 / 5.38 / 14.90, −19.3).", "",
              "Stability (8- and 12-month trend average): " +
              "; ".join(f"{m}-month: {'meets bar' if not w else '; '.join(w)}" for m, w in A["neighbours"].items()) +
              f" → **{'STABLE' if A['stable'] else 'NOT STABLE'}**", ""]
        yr = A["years"]
        L += ["Calendar years, ROT3-engine minus O11 (points): " +
              ", ".join(f"{y.year} {v:+.1f}" for y, v in (yr["ROT3-engine"] - yr["O11"]).dropna().items()), ""]
        d, w = latest_picks(A["targets"])
        L += [f"Latest ROT3 picks (month-end {d.date()}): " + ", ".join(f"{t} {v:.0f}%" for t, v in w.items()), ""]
    if B:
        tb = B["tbill_h"]
        L += ["## Use B — ROT3 for the swing book's idle cash", "",
              f"Same {B['trades']} M0 ETF trades (stop B, SPY > 200-day filter) in both books. Window from "
              f"{B['start'].date()}.", "",
              "| Idle cash | CAGR full | 2005–15 | 2016–26 | Max DD | Avg in idle fund | Verdict |", "|---|---|---|---|---|---|---|",
              f"| T-bills | {_f(tb['full'].get('cagr_pct'))}% | {_f(tb['2005-15'].get('cagr_pct'))}% | "
              f"{_f(tb['2016-26'].get('cagr_pct'))}% | {_f(tb['full'].get('max_dd_pct'), 1)}% | — | baseline |"]
        for tm, r in B["runs"].items():
            h, p = r["h"], r["port"]
            lab = f"ROT3 ({tm}-month trend)" + ("" if tm == TREND_M else ", stability")
            ver = ("PASS" if not r["why"] else "FAIL") if tm == TREND_M else ("meets bar" if not r["why"] else "misses")
            L.append(f"| {lab} | {_f(h['full'].get('cagr_pct'))}% | {_f(h['2005-15'].get('cagr_pct'))}% | "
                     f"{_f(h['2016-26'].get('cagr_pct'))}% | {_f(h['full'].get('max_dd_pct'), 1)}% | {p['sweep_avg_pct']}% | {ver} |")
        sp = B["spy_h"]
        L.append(f"| SPY buy & hold | {_f(sp['full'].get('cagr_pct'))}% | {_f(sp['2005-15'].get('cagr_pct'))}% | "
                 f"{_f(sp['2016-26'].get('cagr_pct'))}% | {_f(sp['full'].get('max_dd_pct'), 1)}% | — | reference |")
        main = B["runs"][TREND_M]
        L += ["", f"**Verdict: {B['verdict']}**" + (f" — {'; '.join(main['why'])}" if main["why"] else ""),
              f"Stability: **{'STABLE' if B['stable'] else 'NOT STABLE'}**.", ""]
        if B["gaps"] or B["missing"]:
            L += [f"Data notes: {B['gaps']} missing: {B['missing']}", ""]
    L += [f"Trials this run: {n_trials['new']} (long-term engine {n_trials['lt']}, swing {n_trials['swing']}).", "",
          f"*rot3_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def main() -> int:
    stamp = date.today().isoformat()
    tickers = sorted(set(hl.all_tickers()) | set(ol.EXTRA_TICKERS) | set(UNIVERSE))
    closes = hl.yf_fetch(tickers, start=ol.HISTORY_START)
    need = ("SPY", "QQQ", *ol.SECTORS9, "^IRX", *ol.CREDIT_PAIR)
    missing = [t for t in need if t not in closes]
    print(f"[rot3_lab] {VERSION}: {len(closes)} of {len(tickers)} tickers; required missing: {missing}")
    if missing:
        print("[rot3_lab] DATA FAILURE: a signal input is missing; nothing written (a gap is not a result).")
        return 1
    import regime_classifier as rc
    balanced = {k: float(v) for k, v in rc.target_weights(hl.REGIME, gate=False).items()}
    data = ol.build_data(closes)
    # equality check: our state machine reproduces production O11 on the 50/50 Offense index
    r = data["rets"].reindex(data["cal"])
    idx50 = (1 + 0.5 * r["SPY"].fillna(0.0) + 0.5 * r["QQQ"].fillna(0.0)).cumprod().to_numpy()
    same = states_off(data["levels"], idx50, credit=True).equals(ol.states_fast(data["levels"], data["rets"], credit=True))
    print(f"[rot3_lab] state machine matches offense_lab O11 on 50/50: {same}")
    if not same:
        print("[rot3_lab] STOP: the engine copy diverges from production; nothing written.")
        return 1
    o11 = ol.run_candidate("O11", data, balanced)
    days = data["cal"][data["cal"] >= pd.Timestamp(ol.EVAL_START) - pd.Timedelta(days=10)]
    A = {}
    runs = {m: run_use_a(data, balanced, m) for m in (TREND_M, *NEIGHBOURS)}
    navs = {"ROT3-engine": runs[TREND_M]["nav"], "O11": o11["nav"],
            "ROT3 alone": runs[TREND_M]["alone"].reindex(days),
            "SPY": ol.simulate(days, data["rets"], lambda d: {"SPY": 100.0}, 0.0),
            "QQQ": ol.simulate(days, data["rets"], lambda d: {"QQQ": 100.0}, 0.0)}
    A["summ"] = {k: ol.summary(v) for k, v in navs.items()}
    A["why"] = "; ".join(bar_a(A["summ"]["ROT3-engine"], A["summ"]["O11"]))
    A["neighbours"] = {m: bar_a(ol.summary(runs[m]["nav"]), A["summ"]["O11"]) for m in NEIGHBOURS}
    A["verdict"] = "PASS" if not A["why"] else "FAIL"
    A["stable"] = not A["why"] and all(not w for w in A["neighbours"].values())
    A.update({k: runs[TREND_M][k] for k in ("share", "fast_exits", "targets")})
    A["years"] = pd.DataFrame({k: ol.year_returns(v) for k, v in navs.items()}).round(2)
    try:
        B = run_use_b()
        main_b = B["runs"][TREND_M]
        B["verdict"] = "PASS" if not main_b["why"] else "FAIL"
        B["stable"] = not main_b["why"] and all(not B["runs"][m]["why"] for m in NEIGHBOURS)
    except Exception as e:
        print(f"[rot3_lab] use B could not run: {type(e).__name__}: {e}")
        B = {}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tl = OUT_DIR / "trial_log.csv"
    log = pd.read_csv(tl) if tl.exists() else pd.DataFrame(columns=["date", "version", "trials", "note"])
    first = not (log["version"].astype(str) == VERSION).any() if len(log) else True
    new = (3 if A else 0) + (3 if B else 0) if first else 0
    n_trials = {"new": new, "lt": f"28 → {28 + (3 if A else 0)}" if first else "unchanged",
                "swing": f"81 → {81 + (3 if B else 0)}" if first else "unchanged"}
    pd.concat([log, pd.DataFrame([{"date": stamp, "version": VERSION, "trials": new,
                                   "note": "ROT3 use A (+8/12-month) and use B (+8/12-month)"}])]).to_csv(tl, index=False)
    rows = []
    for k, ss in A["summ"].items():
        for w, st in ss.items():
            rows.append({"use": "A", "book": k, "window": w, **st})
    if B:
        for nm, h in [("T-bills", B["tbill_h"])] + [(f"ROT3 {m}m", B["runs"][m]["h"]) for m in B["runs"]]:
            for w, st in h.items():
                rows.append({"use": "B", "book": nm, "window": w, **st})
    pd.DataFrame(rows).to_csv(OUT_DIR / "results.csv", index=False)
    pd.DataFrame(navs).round(4).to_csv(OUT_DIR / "nav_use_a.csv")
    A["years"].to_csv(OUT_DIR / "years_use_a.csv")
    pd.DataFrame([{"month_end": d.date(), **w} for d, w in sorted(A["targets"].items())]).to_csv(
        OUT_DIR / "picks.csv", index=False)
    if B:
        pd.DataFrame({"T-bills": B["tbill"]["equity"], **{f"ROT3 {m}m": B["runs"][m]["port"]["equity"] for m in B["runs"]}}
                     ).round(2).to_csv(OUT_DIR / "equity_use_b.csv")
    pd.DataFrame([{"use": "A", "verdict": A["verdict"], "stable": A["stable"], "reasons": A["why"] or "meets bar"},
                  {"use": "B", "verdict": B.get("verdict", "NOT RUN"), "stable": B.get("stable"),
                   "reasons": "; ".join(B["runs"][TREND_M]["why"]) if B else "use B did not run"}]
                 ).to_csv(OUT_DIR / "verdicts.csv", index=False)
    md = render(A, B, stamp, n_trials)
    (LOG_DIR / f"{stamp}_report.md").write_text(md)
    (LOG_DIR / "latest.md").write_text(md)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _me_frame(vals: dict, start="2010-01-31", n=24) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="ME")
    return pd.DataFrame({t: v(np.arange(n)) for t, v in vals.items()}, index=idx)


def selftest() -> dict:
    f = []
    # 1. month_ends picks the last trading day of each month
    cal = pd.bdate_range("2020-01-01", "2020-04-30")
    lv = pd.DataFrame({"A": np.arange(len(cal), dtype=float)}, index=cal)
    me = month_ends(lv)
    if list(me.index.strftime("%m-%d")) != ["01-31", "02-28", "03-31", "04-30"]:
        f.append(f"month_ends: {list(me.index.date)}")
    # 2. ranking, trend filter, eligibility, cash slots
    me = _me_frame({"UP1": lambda i: 100 * 1.05 ** i, "UP2": lambda i: 100 * 1.03 ** i,
                    "UP3": lambda i: 100 * 1.01 ** i, "FLAT": lambda i: 100 + 0 * i,
                    "DOWN": lambda i: 100 * 0.97 ** i,
                    "NEW": lambda i: np.where(i < 15, np.nan, 100 * 1.10 ** i)}, n=30)
    tg = rot3_targets(me)
    d = me.index[12]
    if set(tg[d]) != {"UP1", "UP2", "UP3"} or abs(sum(tg[d].values()) - 100) > 1e-9:
        f.append(f"top 3 by average 3/6/12-month return: {tg[d]}")
    if tg[me.index[11]] != {CASH: 100.0}:
        f.append("no picks before 12 months of history")
    if "NEW" in tg[me.index[26]] or "NEW" not in tg[me.index[27]]:
        f.append(f"a new fund is eligible only after 12 months: {tg[me.index[26]]}, {tg[me.index[27]]}")
    tg_n = rot3_targets(me[["NEW", "UP3"]], top=2)
    if "NEW" in tg_n[me.index[26]]:
        f.append("a fund without 12 months of history is never picked, even with free slots")
    # the score is the AVERAGE of 3/6/12-month returns, not the 12-month alone
    px_x = [100, 110, 125, 140, 160, 180, 200, 195, 190, 185, 180, 172, 160]     # +60% / 12m, falling lately
    px_y = [100 * 1.022 ** i for i in range(13)]                                  # steady +30% / 12m
    me_s = pd.DataFrame({"X": px_x, "Y": px_y}, index=pd.date_range("2015-01-31", periods=13, freq="ME"))
    if set(rot3_targets(me_s, trend_m=10, top=1)[me_s.index[-1]]) != {"Y"}:
        f.append("ranking uses the average of the 3-, 6- and 12-month returns")
    me2 = me.copy()
    me2.iloc[-1, me2.columns.get_loc("UP1")] = 50.0            # crash below its 10-month average at the last month-end
    tg2 = rot3_targets(me2)
    last = tg2[me2.index[-1]]
    if "UP1" in last:
        f.append(f"a pick below its 10-month average sits in cash: {last}")
    me3 = _me_frame({"A": lambda i: 100 * 0.98 ** i, "B": lambda i: 100 * 0.97 ** i,
                     "C": lambda i: 100 * 0.96 ** i, "D": lambda i: 100 * 0.95 ** i})
    if rot3_targets(me3)[me3.index[-1]] != {CASH: 100.0}:
        f.append("all picks in downtrends -> all cash")
    me4 = _me_frame({"A": lambda i: 100 * 1.02 ** i, "B": lambda i: 100 * 1.01 ** i})
    w4 = rot3_targets(me4)[me4.index[-1]]
    if abs(w4.get(CASH, 0) - 100 / 3) > 1e-9:
        f.append(f"fewer eligible funds than slots -> the empty slot is cash: {w4}")
    # 3. no look-ahead: weights on a month-end day are the previous month's target
    look = weights_lookup({pd.Timestamp("2020-01-31"): {"A": 100.0}, pd.Timestamp("2020-02-28"): {"B": 100.0}})
    if look("2020-01-31") != {CASH: 100.0} or look("2020-02-03") != {"A": 100.0} or look("2020-02-28") != {"A": 100.0} \
            or look("2020-03-02") != {"B": 100.0}:
        f.append("weights must come from the latest month-end strictly before the day")
    # 4. engine copy equals production O11 on the 50/50 index
    closes = ol._synthetic()
    data = ol.build_data(closes)
    r = data["rets"].reindex(data["cal"])
    idx50 = (1 + 0.5 * r["SPY"].fillna(0.0) + 0.5 * r["QQQ"].fillna(0.0)).cumprod().to_numpy()
    for cr in (True, False):
        if not states_off(data["levels"], idx50, credit=cr).equals(ol.states_fast(data["levels"], data["rets"], credit=cr)):
            f.append(f"states_off must equal offense_lab.states_fast on 50/50 (credit={cr})")
    st = states_off(data["levels"], idx50)
    if "OFF" not in set(st) or "DEF" not in set(st):
        f.append("synthetic data should visit Offense and Defense")
    # the stop follows the Offense index given
    crash = idx50.copy()
    offs = np.where(st.to_numpy() == "OFF")[0]
    if len(offs):
        i0 = offs[len(offs) // 2]
        crash[i0:] = crash[i0:] * 0.85
        st2 = states_off(data["levels"], crash)
        if st2.iloc[i0] != "OUT":
            f.append("a −15% drop in the Offense index must trigger the −8% stop that day")
    # 5. engine weights: ROT3 only in Offense; lagged one session
    bal = {"SGOV": 50.0, "TLT": 50.0}
    states = pd.Series(["BAL", "OFF", "OFF", "DEF", "OUT"], index=pd.bdate_range("2021-01-04", periods=5), dtype=object)
    ew = engine_weights(states, lambda d: {"XLK": 100.0}, bal)
    seq = [ew(d) for d in states.index]
    if seq[1] != bal or seq[2] != {"XLK": 100.0} or seq[4] != ol.DEFENSE:
        f.append(f"engine weights lag one session and use ROT3 only in Offense: {seq}")
    # 6. ROT3 fund: open/close arithmetic, cash leg, costs
    cal = pd.bdate_range("2021-01-04", periods=4)
    C = pd.DataFrame({"A": [10.0, 11.0, 11.0, 12.1]}, index=cal)
    O = pd.DataFrame({"A": [10.0, 10.5, 11.0, 11.0]}, index=cal)
    rate = np.full(4, 0.0001)
    wl = lambda d: {"A": 100.0} if d >= cal[0] else {CASH: 100.0}
    op, cl = rot3_fund(O, C, rate, wl, cal)
    if abs(cl[1] - 110.0) > 1e-9 or abs(op[1] - 105.0) > 1e-9 or abs(cl[3] - 121.0) > 1e-9:
        f.append(f"fund arithmetic: open {op}, close {cl}")
    wl2 = lambda d: {CASH: 100.0} if d < cal[2] else {"A": 100.0}
    op2, cl2 = rot3_fund(O, C, rate, wl2, cal)
    exp2 = 100 * 1.0001 * 1.0001 * (1 - 5e-4)            # day 2: cash return, then switch cost (100% turnover)
    if abs(cl2[2] - exp2) > 1e-9 or abs(cl2[3] - exp2 * 1.1) > 1e-9:
        f.append(f"cash leg and cost: {cl2}, expected {exp2}")
    # fund equals the engine's daily-rebalanced simulation on closes
    nav = hl.simulate(cal, pd.DataFrame({"A": C["A"].pct_change(), CASH: pd.Series(rate, index=cal).shift(1)}, index=cal),
                      wl2, None, breaker=False, cost_bps=COST_BPS)["nav"].to_numpy()
    if not np.allclose(cl2 / cl2[0], nav / nav[0], rtol=1e-9):
        f.append(f"fund close path must match hedge_lab.simulate: {cl2 / cl2[0]} vs {nav / nav[0]}")
    # 7. the sweep holds the fund: with no trades the book tracks the fund less one sweep cost
    import swing_backtest as sb
    cal = pd.bdate_range("2021-01-04", periods=6)
    opn = np.array([100, 101, 102, 103, 104, 105.0]); cls = np.array([100, 102, 103, 104, 105, 106.0])
    p = sb.run_portfolio([], [], {}, cal, {}, sweep={"mode": "SPY", "open": opn, "close": cls,
                                                     "rate": np.zeros(6), "ok": np.ones(6, dtype=bool)})
    exp = 10_000 * (1 - sb.COST_BPS["etf"] / 1e4) / 101 * 106
    if abs(p["equity"].iloc[-1] - exp) > 0.01:
        f.append(f"sweep into the fund: {p['equity'].iloc[-1]:.2f} vs {exp:.2f}")
    # 8. bars
    good = {"full": {"cagr_pct": 10.0, "max_dd_pct": -15.0}, "2005-15": {"cagr_pct": 6.0}, "2016-26": {"cagr_pct": 15.0}}
    base = {"full": {"cagr_pct": 9.5}, "2005-15": {"cagr_pct": 5.4}, "2016-26": {"cagr_pct": 14.9}}
    if bar_a(good, base) or not bar_a({**good, "2005-15": {"cagr_pct": 5.0}}, base) \
            or not bar_a({**good, "full": {"cagr_pct": 10.0, "max_dd_pct": -21.0}}, base):
        f.append("bar A: both halves above O11, DD inside −20%")
    tb = {"full": {"cagr_pct": 5.0}, "2005-15": {"cagr_pct": 4.0}, "2016-26": {"cagr_pct": 6.0}}
    ok = {"full": {"cagr_pct": 7.0, "max_dd_pct": -18.0}, "2005-15": {"cagr_pct": 4.5}, "2016-26": {"cagr_pct": 9.0}}
    if bar_b(ok, tb, False) or not bar_b({**ok, "full": {"cagr_pct": 6.9, "max_dd_pct": -18.0}}, tb, False) \
            or not bar_b(ok, tb, True) or not bar_b({**ok, "2005-15": {"cagr_pct": 3.9}}, tb, False):
        f.append("bar B: +2 pts full, both halves above, DD inside −20%")
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        r = selftest()
        print(json.dumps(r, indent=2, default=str))
        sys.exit(0 if r["ok"] else 1)
    sys.exit(main())
