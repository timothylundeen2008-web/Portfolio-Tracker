"""
lever_lab.py  (v1.1 — 2026-11-21)
──────────────────────────────────
Swing book only. Two pre-registered tests of "bigger wins per trade" (Matt, 2026-11-21:
"aiming for possible swing trade wins and/or trading options wins that are north of
25% for each win … fine increasing risk as long as it doesn't kill the account and the
risk is far less than the reward"). Pre-registration: claude/lever_lab_2026-11-21.md.
Bars below are fixed BEFORE any run on real prices; a FAIL is final.

S1  OPTIONS ON M0. The only passing swing rule (ETF M0 Rotation Reclaim, swing_backtest
    variant B, SPY > 200-day at the signal), expressed as bought calls instead of shares.
      Contract: delta 0.70, 60 calendar days to expiry, strike solved from the delta.
      Price: Black-Scholes on the dividend-adjusted series (dividends are inside the
        series, so q = 0), rate = 3-month T-bill (^IRX). MODEL VALUES: no historical
        option prices exist in the project (N12).
      Implied volatility (point-in-time): max(VIX x (60d realized vol of the fund /
        60d realized vol of SPY), 1.10 x 20d realized vol of the fund).
      Spread: half-spread on each side as a share of the premium — 1.5% for the most
        liquid option ETFs (TIER1), 3% for the rest.
      S1a (mirror): the option follows the stock trade's own events (entry, ladder trims,
        stops, exits); time stop at 21 days to expiry.
      S1b (option-native exits, swing_build_plan §7): stock closes through its initial
        stop -> sell next open; the option closes at +100% or more -> sell half next
        open, then the rest exits on a close below the 10-day EMA; time stop at 21 days
        to expiry. No sector-rotation exit.
    Book: 5% of equity in premium per trade, at most 4 open (20% premium at risk),
      idle cash in T-bills. Run on the AFFORDABLE funds only: one contract at today's
      price and implied volatility costs <= 5% of $10,000. Trade-level evidence uses
      every M0 fund.

S2  WASHOUT SNAPBACK in a 3x index fund (synthetic 3x of SPY or QQQ: 3 x daily return
    - 2 x (T-bill + 0.5%/yr) - 0.95%/yr fee).
      Signal at a close: 5-session return z <= -2.5 (z = 5-day return / (daily vol over
        the 252 sessions before the window x sqrt 5)) AND VIX close >= 25.
      Entry: next open. One position at a time across SPY and QQQ (if both fire, the
        more negative z). Size: 35% of equity.
      Exits (index closes, executed next open): stop at -3% from the entry open;
        target at +8%; once a close is +5% or more the stop moves to the entry;
        time stop after 15 sessions.
      Costs: 5bp a side; stop exits 10bp extra.
    Index calls were dropped before the run: one 0.70-delta SPY or QQQ call costs
      ~$6,000, 60% of a $10,000 account.

v1.1 (2026-11-21): the first run was killed after 9 minutes (runner shutdown) — every option
  trade carried its own ~5,800-entry date map (hundreds of millions of entries in all). One shared
  map per fund now; progress lines are printed. Added a DELTA SWEEP (0.50-0.90, report only, not a
  bar and not a trial): delta is a design choice to research, and cheaper deltas make more funds
  affordable on $10k. Rules and bars are unchanged from v1.0.

Run:  python lever_lab.py            (Actions: needs yfinance)
      python lever_lab.py --selftest (offline)
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Optional

import numpy as np
import pandas as pd

VERSION = "1.1"
ND = NormalDist()
OUT_DATA, OUT_LOGS = Path("data/lever_lab"), Path("logs/lever_lab")
TRIALS_BEFORE = 91
TRIALS_HERE = 3                 # S1a, S1b, S2 (neighbours and stresses are diagnostics)

# ── S1 constants (pre-registered) ──────────────────────────────────────────
S1_DELTA, S1_DTE, S1_TIME_STOP_DTE = 0.70, 60, 21
S1_PREMIUM_PCT, S1_MAX_OPEN = 5.0, 4
S1_ACCOUNT = 10_000.0
TIER1 = {"SPY", "QQQ", "IWM", "DIA", "GLD", "TLT", "EEM", "EFA", "XLF", "XLE", "XLK", "SMH", "GDX", "SLV",
         "XLV", "XLU", "XLP", "XLI", "XLY", "XOP", "KRE"}
HALF_SPREAD = {"t1": 0.015, "t2": 0.03}
IV_FLOOR_MULT, RV_LONG, RV_SHORT = 1.10, 60, 20
HARSH_IV_MULT, HARSH_SPREAD_MULT = 1.20, 2.0
S1_NEIGHBOURS = [("dte", 45), ("dte", 90), ("delta", 0.60), ("delta", 0.75)]
DELTA_SWEEP = (0.50, 0.60, 0.70, 0.75, 0.80, 0.90)      # v1.1: report only
S1_HALVES = (("2005-15", "2005-01-01", "2015-12-31"), ("2016-26", "2016-01-01", "2100-01-01"))
S1_BAR = {"min_trades": 100, "min_half": 30, "min_pf": 1.3, "min_payoff": 2.0, "max_dd": -30.0}

# ── S2 constants (pre-registered) ──────────────────────────────────────────
S2_Z, S2_VIX, S2_STOP, S2_TARGET, S2_BE, S2_DAYS = -2.5, 25.0, 0.03, 0.08, 0.05, 15
S2_SIZE, S2_LEV, S2_FEE, S2_SPREAD = 0.35, 3.0, 0.0095, 0.0050
S2_COST_BPS, S2_STOP_BPS = 5.0, 10.0
S2_HALVES = (("2000-12", "2000-01-01", "2012-12-31"), ("2013-26", "2013-01-01", "2100-01-01"))
S2_BAR = {"min_trades": 30, "min_half": 10, "min_pf": 1.5, "min_payoff": 2.0, "excess_pts": 2.0,
          "max_dd": -20.0, "worst_trade_eq": -8.0, "worst_year": -10.0}
S2_NEIGHBOURS = [("z", -2.0), ("z", -3.0), ("vix", 20.0), ("vix", 30.0), ("target", 0.06), ("target", 0.10),
                 ("stop", 0.02), ("stop", 0.04)]
S2_STRESS = {"spread_mult": 2.0, "stop_bps": 60.0}


# ═══════════════════════════════════════════════════════════════════════════
#  Black-Scholes
# ═══════════════════════════════════════════════════════════════════════════

def bs_call(S: float, K: float, T: float, r: float, sig: float) -> float:
    if T <= 0 or sig <= 0:
        return max(S - K, 0.0)
    v = sig * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sig * sig) * T) / v
    return S * ND.cdf(d1) - K * math.exp(-r * T) * ND.cdf(d1 - v)


def bs_delta(S, K, T, r, sig) -> float:
    if T <= 0 or sig <= 0:
        return 1.0 if S > K else 0.0
    return ND.cdf((math.log(S / K) + (r + 0.5 * sig * sig) * T) / (sig * math.sqrt(T)))


def strike_for_delta(S, delta, T, r, sig) -> float:
    return S * math.exp(-ND.inv_cdf(delta) * sig * math.sqrt(T) + (r + 0.5 * sig * sig) * T)


def iv_series(close: pd.Series, spy: pd.Series, vix: pd.Series) -> pd.Series:
    """Point-in-time implied-vol proxy (annualized fraction)."""
    r = close.pct_change()
    rs = spy.reindex(close.index).ffill().pct_change()
    rv_l = r.rolling(RV_LONG).std() * math.sqrt(252)
    rv_ls = rs.rolling(RV_LONG).std() * math.sqrt(252)
    rv_s = r.rolling(RV_SHORT).std() * math.sqrt(252)
    ratio = (rv_l / rv_ls).clip(0.5, 4.0)
    v = vix.reindex(close.index).ffill() / 100.0
    return np.maximum(v * ratio, IV_FLOOR_MULT * rv_s).ffill()


def half_spread(tk: str, mult: float = 1.0) -> float:
    return HALF_SPREAD["t1" if tk in TIER1 else "t2"] * mult


# ═══════════════════════════════════════════════════════════════════════════
#  S1 — one option trade
# ═══════════════════════════════════════════════════════════════════════════

def option_trade(tk: str, dates: pd.DatetimeIndex, o: np.ndarray, c: np.ndarray, ema10: np.ndarray,
                 iv: np.ndarray, rate: np.ndarray, entry_t: int, entry_px: float, stop0: float,
                 events: Optional[list], mode: str, delta=S1_DELTA, dte=S1_DTE,
                 iv_mult_entry: float = 1.0, spread_mult: float = 1.0) -> Optional[dict]:
    """Returns cost (per contract, incl. spread), sales [(t, frac, net)], marks {t: (rem, mid)}, ret."""
    n = len(c)
    sig0 = float(iv[entry_t]) * iv_mult_entry
    r0 = float(rate[entry_t]) if np.isfinite(rate[entry_t]) else 0.0
    if not (np.isfinite(sig0) and sig0 > 0 and entry_px > 0):
        return None
    expiry = dates[entry_t] + pd.Timedelta(days=dte)
    T0 = dte / 365.0
    K = strike_for_delta(entry_px, delta, T0, r0, sig0)
    h = half_spread(tk, spread_mult)
    mid0 = bs_call(entry_px, K, T0, r0, sig0)
    cost = mid0 * (1 + h)

    def mid(t, S):
        T = max((expiry - dates[t]).days, 0) / 365.0
        sg = float(iv[t]) if np.isfinite(iv[t]) else sig0
        rr = float(rate[t]) if np.isfinite(rate[t]) else r0
        return bs_call(float(S), K, T, rr, sg)

    def dte_at(t):
        return (expiry - dates[t]).days

    sales, marks, rem = [], {}, 1.0

    def sell(t, frac, S, why):
        nonlocal rem
        frac = min(frac, rem)
        if frac <= 1e-12:
            return
        sales.append((t, frac, mid(t, S) * (1 - h), why))
        rem -= frac

    if mode == "mirror":
        ev = {}
        for (t, k, f, p, _b) in events or []:
            if k != "entry":
                ev.setdefault(t, []).append((k, f, p))
        for t in range(entry_t, n):
            for (k, f, p) in ev.get(t, []):
                if k == "mark":                         # still open at the data end: mark, no sale
                    continue
                sell(t, f if k == "trim" else rem, p, k)
            if rem <= 1e-12:
                break
            if dte_at(t) <= S1_TIME_STOP_DTE:
                sell(t, rem, c[t], "time stop")
                break
            marks[t] = (rem, mid(t, c[t]))
    else:                                               # native exits
        pending, halved = None, False
        for t in range(entry_t, n):
            if t > entry_t and pending is not None:
                sell(t, rem if pending == "all" else 0.5, o[t], pending)
                if pending == "half":
                    halved = True
                pending = None
                if rem <= 1e-12:
                    break
            if dte_at(t) <= S1_TIME_STOP_DTE:
                sell(t, rem, c[t], "time stop")
                break
            m = mid(t, c[t])
            marks[t] = (rem, m)
            if c[t] <= stop0:
                pending = "all"
            elif not halved and m >= 2.0 * cost:
                pending = "half"
            elif halved and np.isfinite(ema10[t]) and c[t] < ema10[t]:
                pending = "all"
    if rem > 1e-12:                                     # data end: marked at the last close, flagged open
        last = max(marks) if marks else entry_t
        sales.append((last, rem, mid(last, c[last]) * (1 - h), "open at end"))
        rem = 0.0
    proceeds = sum(f * px for _t, f, px, _w in sales)
    exit_t = max(t for t, *_ in sales)
    return {"ticker": tk, "entry_t": entry_t, "exit_t": exit_t, "entry_date": dates[entry_t],
            "exit_date": dates[exit_t], "K": K, "cost": cost, "sales": sales, "marks": marks,
            "ret": proceeds / cost - 1.0, "open": any(w == "open at end" for *_x, w in sales),
            "hold_days": int(exit_t - entry_t)}


# ═══════════════════════════════════════════════════════════════════════════
#  Shared statistics
# ═══════════════════════════════════════════════════════════════════════════

def trade_stats(rets) -> dict:
    r = np.asarray([x for x in rets if np.isfinite(x)], dtype=float)
    if not len(r):
        return {"n": 0, "exp": float("nan"), "pf": float("nan"), "win": float("nan"), "payoff": float("nan"),
                "avg_win": float("nan"), "avg_loss": float("nan"), "big_win_share": float("nan")}
    w, l = r[r > 0], r[r <= 0]
    pf = w.sum() / -l.sum() if l.sum() < 0 else float("inf")
    aw, al = (w.mean() if len(w) else 0.0), (l.mean() if len(l) else 0.0)
    return {"n": int(len(r)), "exp": float(r.mean()), "pf": float(pf), "win": float(len(w) / len(r)),
            "avg_win": float(aw), "avg_loss": float(al),
            "payoff": float(aw / -al) if al < 0 else float("inf"),
            "big_win_share": float((w >= 0.25).sum() / len(w)) if len(w) else 0.0}


def nav_stats(nav: pd.Series, start=None, end=None) -> dict:
    s = nav.dropna()
    if start is not None:
        s = s[s.index >= pd.Timestamp(start)]
    if end is not None:
        s = s[s.index <= pd.Timestamp(end)]
    if len(s) < 2:
        return {"cagr": float("nan"), "max_dd": float("nan")}
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else float("nan")
    dd = (s / s.cummax() - 1).min()
    return {"cagr": float(cagr * 100), "max_dd": float(dd * 100)}


def hwm_stops(nav: pd.Series, depth: float = -20.0) -> int:
    """Times the live −20%-from-high-water rule would have halted the book (counted, not enforced)."""
    n, peak, armed = 0, -np.inf, True
    for v in nav.dropna().to_numpy():
        if v > peak:
            peak, armed = v, True
        if armed and (v / peak - 1) * 100 <= depth:
            n, armed = n + 1, False
    return n


def year_returns(nav: pd.Series) -> pd.Series:
    y = nav.dropna().resample("YE").last()
    first = nav.dropna().iloc[0]
    return (y / y.shift(1).fillna(first) - 1) * 100


# ═══════════════════════════════════════════════════════════════════════════
#  S1 — book
# ═══════════════════════════════════════════════════════════════════════════

def s1_book(opts: list, cal: pd.DatetimeIndex, cash_r: pd.Series, premium_pct=S1_PREMIUM_PCT,
            max_open=S1_MAX_OPEN, allowed: Optional[set] = None) -> tuple:
    """Daily NAV. Each option trade: on its entry date, premium = pct x equity (prior close), if a slot is
    free. Marks at mid; sales at net. Idle cash earns T-bills."""
    by_entry = {}
    for k, x in enumerate(opts):
        if allowed is not None and x["ticker"] not in allowed:
            continue
        by_entry.setdefault(x["entry_date"], []).append(k)
    cash, nav, taken = 10_000.0, [], []
    open_pos = []                                      # dicts: x, units, last
    cr = cash_r.reindex(cal).fillna(0.0).to_numpy()
    prev_eq = cash
    for i, d in enumerate(cal):
        cash *= 1 + cr[i]
        for k in sorted(by_entry.get(d, []), key=lambda k: opts[k]["ticker"]):
            if len(open_pos) >= max_open:
                continue
            x = opts[k]
            prem = premium_pct / 100 * prev_eq
            if prem > cash or x["cost"] <= 0:
                continue
            cash -= prem
            open_pos.append({"x": x, "units": prem / x["cost"], "last": prem})
            taken.append(k)
        mark, still = 0.0, []
        for p in open_pos:
            x, units = p["x"], p["units"]
            t = x["_dates"].get(d)
            if t is not None:
                for (ts, fr, px, _w) in x["sales"]:
                    if ts == t:
                        cash += units * fr * px
                if t >= x["exit_t"]:
                    continue                           # fully sold
                if t in x["marks"]:
                    rem, m = x["marks"][t]
                    p["last"] = units * rem * m
            mark += p["last"]
            still.append(p)
        open_pos = still
        eq = cash + mark
        nav.append(eq)
        prev_eq = eq
    return pd.Series(nav, index=cal), taken


# ═══════════════════════════════════════════════════════════════════════════
#  S2 — washout snapback
# ═══════════════════════════════════════════════════════════════════════════

def washout_z(close: pd.Series) -> pd.Series:
    r = close.pct_change()
    sd = r.rolling(252).std().shift(5)
    return (close / close.shift(5) - 1) / (sd * math.sqrt(5))


def s2_signals(idx: dict, vix: pd.Series, z_thr=S2_Z, vix_thr=S2_VIX) -> pd.DataFrame:
    rows = []
    for name, df in idx.items():
        z = washout_z(df["Close"])
        v = vix.reindex(df.index).ffill()
        hit = (z <= z_thr) & (v >= vix_thr)
        for d in df.index[hit.fillna(False).to_numpy()]:
            rows.append({"date": d, "index": name, "z": float(z.loc[d]), "vix": float(v.loc[d])})
    return pd.DataFrame(rows, columns=["date", "index", "z", "vix"])


def s2_trades(idx: dict, vix: pd.Series, cash: pd.Series, z_thr=S2_Z, vix_thr=S2_VIX, stop=S2_STOP,
              target=S2_TARGET, be=S2_BE, days=S2_DAYS, spread_mult=1.0, stop_bps=S2_STOP_BPS) -> list:
    """One position at a time across indices. Return of the 3x position, net, per trade, plus its daily
    path of position value (start 1.0) for the book."""
    sig = s2_signals(idx, vix, z_thr, vix_thr)
    if sig.empty:
        return []
    cal = idx[next(iter(idx))].index
    for df in idx.values():
        cal = cal.union(df.index)
    fin = (cash.reindex(cal).ffill().fillna(0.0) + S2_SPREAD * spread_mult / 252)
    out, busy_until = [], pd.Timestamp.min
    for d, g in sig.sort_values(["date", "z"]).groupby("date"):
        if d <= busy_until:
            continue
        s = g.iloc[0]
        df = idx[s["index"]]
        ix = df.index.get_loc(d)
        if ix + 1 >= len(df):
            continue
        o, c = df["Open"].to_numpy(), df["Close"].to_numpy()
        e = ix + 1
        entry = o[e]
        stp, path, val = entry * (1 - stop), {}, 1.0
        exit_t, why = None, None
        for t in range(e, len(df)):
            # value at today's close
            if t == e:
                ret_idx = c[t] / entry - 1
            else:
                ret_idx = c[t] / c[t - 1] - 1
            f = fin.loc[df.index[t]]
            val *= 1 + S2_LEV * ret_idx - (S2_LEV - 1) * f - S2_FEE / 252
            path[df.index[t]] = val
            if c[t] >= entry * (1 + be):
                stp = max(stp, entry)
            if c[t] <= stp:
                why = "stop" if stp < entry else "breakeven stop"
            elif c[t] >= entry * (1 + target):
                why = "target"
            elif t - e + 1 >= days:
                why = "time"
            if why and t + 1 < len(df):
                g_ret = o[t + 1] / c[t] - 1               # overnight gap into the exit open
                val *= 1 + S2_LEV * g_ret
                exit_t = t + 1
                path[df.index[exit_t]] = val
                break
            if why:                                       # data end
                exit_t = t
                break
        if exit_t is None:
            exit_t, why = len(df) - 1, "open at end"
        bps = S2_COST_BPS * 2 + (stop_bps if why in ("stop", "breakeven stop") else 0.0)
        val *= 1 - bps / 1e4
        path[df.index[exit_t]] = val
        out.append({"index": s["index"], "signal": d, "entry_date": df.index[e], "exit_date": df.index[exit_t],
                    "z": float(s["z"]), "vix": float(s["vix"]), "why": why, "ret": val - 1.0,
                    "idx_ret": float(o[exit_t] / entry - 1) if exit_t > e else float(c[exit_t] / entry - 1),
                    "path": path, "sessions": int(exit_t - e)})
        busy_until = df.index[exit_t]
    return out


def s2_book(trades: list, cal: pd.DatetimeIndex, cash_r: pd.Series, size=S2_SIZE) -> pd.Series:
    cash, nav, pos = 10_000.0, [], None             # pos: dict trade, amt, v
    cr = cash_r.reindex(cal).fillna(0.0).to_numpy()
    starts = {t["entry_date"]: t for t in trades}
    prev = cash
    for i, d in enumerate(cal):
        cash *= 1 + cr[i]
        if pos is None and d in starts:
            amt = size * prev
            cash -= amt
            pos = {"t": starts[d], "amt": amt, "v": 1.0}
        val = 0.0
        if pos is not None:
            pos["v"] = pos["t"]["path"].get(d, pos["v"])   # a date missing from the path holds the last value
            val = pos["amt"] * pos["v"]
            if d >= pos["t"]["exit_date"]:
                cash += val
                val, pos = 0.0, None
        eq = cash + val
        nav.append(eq)
        prev = eq
    return pd.Series(nav, index=cal)


def lev_check(idx_close: pd.Series, real: Optional[pd.Series], cash: pd.Series) -> dict:
    if real is None or real.dropna().empty:
        return {"note": "no data"}
    r = idx_close.pct_change()
    syn = S2_LEV * r - (S2_LEV - 1) * (cash.reindex(r.index).ffill().fillna(0) + S2_SPREAD / 252) - S2_FEE / 252
    both = pd.DataFrame({"syn": syn, "real": real.pct_change()}).dropna()
    if both.empty:
        return {"note": "no overlap"}
    y = (1 + both).resample("YE").prod() - 1
    d = (y["syn"] - y["real"]) * 100
    return {"years": int(len(y)), "mean_diff_pts": round(float(d.mean()), 2),
            "worst_diff_pts": round(float(d.abs().max()), 2),
            "daily_corr": round(float(both.corr().iloc[0, 1]), 4)}


# ═══════════════════════════════════════════════════════════════════════════
#  Verdicts
# ═══════════════════════════════════════════════════════════════════════════

def _halfsplit(items, key, halves):
    return {h: [x for x in items if pd.Timestamp(a) <= pd.Timestamp(x[key]) <= pd.Timestamp(b)]
            for h, a, b in halves}


def s1_verdict(opts: list, nav: pd.Series, spy: pd.Series, harsh: list, nb_navs: dict) -> dict:
    allst = trade_stats([x["ret"] for x in opts])
    halves = _halfsplit(opts, "entry_date", S1_HALVES)
    hs = {h: trade_stats([x["ret"] for x in v]) for h, v in halves.items()}
    hh = {h: trade_stats([x["ret"] for x in v]) for h, v in _halfsplit(harsh, "entry_date", S1_HALVES).items()}
    book = {h: nav_stats(nav, a, b) for h, a, b in [("full", "2005-01-01", None)] + list(S1_HALVES)}
    spyb = {h: nav_stats(spy, a, b) for h, a, b in [("full", "2005-01-01", None)] + list(S1_HALVES)}
    fails = []
    if allst["n"] < S1_BAR["min_trades"]:
        fails.append(f"n {allst['n']} < {S1_BAR['min_trades']}")
    for h, st in hs.items():
        if st["n"] < S1_BAR["min_half"]:
            fails.append(f"{h} n {st['n']} < {S1_BAR['min_half']}")
        if not st["exp"] > 0:
            fails.append(f"{h} expectancy {st['exp']:+.3f} <= 0")
        if not st["pf"] >= S1_BAR["min_pf"]:
            fails.append(f"{h} PF {st['pf']:.2f} < {S1_BAR['min_pf']}")
    if not allst["payoff"] >= S1_BAR["min_payoff"]:
        fails.append(f"payoff {allst['payoff']:.2f} < {S1_BAR['min_payoff']}")
    for h in book:
        if not book[h]["cagr"] > spyb[h]["cagr"]:
            fails.append(f"book {h} CAGR {book[h]['cagr']:.2f}% <= SPY {spyb[h]['cagr']:.2f}%")
    if not book["full"]["max_dd"] > S1_BAR["max_dd"]:
        fails.append(f"book max DD {book['full']['max_dd']:.1f}% deeper than {S1_BAR['max_dd']}%")
    robust = all(st["exp"] > 0 for st in hh.values())
    stable_n = sum(1 for v in nb_navs.values() if nav_stats(v, "2005-01-01")["cagr"] > spyb["full"]["cagr"])
    return {"verdict": "PASS" if not fails else "FAIL", "fails": fails, "all": allst, "halves": hs,
            "harsh_halves": hh, "robust": robust, "stable": f"{stable_n} of {len(nb_navs)}",
            "book": book, "spy": spyb, "hwm_stops": hwm_stops(nav[nav.index >= "2005-01-01"])}


def s2_verdict(trades: list, nav: pd.Series, tbill_nav: pd.Series, stress: list, nb: dict) -> dict:
    allst = trade_stats([t["ret"] for t in trades])
    halves = _halfsplit(trades, "entry_date", S2_HALVES)
    hs = {h: trade_stats([t["ret"] for t in v]) for h, v in halves.items()}
    book = {h: nav_stats(nav, a, b) for h, a, b in [("full", "2000-01-01", None)] + list(S2_HALVES)}
    tb = {h: nav_stats(tbill_nav, a, b) for h, a, b in [("full", "2000-01-01", None)] + list(S2_HALVES)}
    yr = year_returns(nav[nav.index >= "2000-01-01"])
    worst_eq = min([t["ret"] * S2_SIZE * 100 for t in trades], default=0.0)
    fails = []
    if allst["n"] < S2_BAR["min_trades"]:
        fails.append(f"n {allst['n']} < {S2_BAR['min_trades']}")
    for h, st in hs.items():
        if st["n"] < S2_BAR["min_half"]:
            fails.append(f"{h} n {st['n']} < {S2_BAR['min_half']}")
        if not st["exp"] > 0:
            fails.append(f"{h} expectancy {st['exp'] * 100:+.2f}% <= 0")
    if not allst["pf"] >= S2_BAR["min_pf"]:
        fails.append(f"PF {allst['pf']:.2f} < {S2_BAR['min_pf']}")
    if not allst["payoff"] >= S2_BAR["min_payoff"]:
        fails.append(f"payoff {allst['payoff']:.2f} < {S2_BAR['min_payoff']}")
    for h, a, b in S2_HALVES:
        ex = book[h]["cagr"] - tb[h]["cagr"]
        if not ex >= S2_BAR["excess_pts"]:
            fails.append(f"{h} book {book[h]['cagr']:.2f}% is only {ex:+.2f} pts over T-bills (< {S2_BAR['excess_pts']})")
    if not book["full"]["max_dd"] > S2_BAR["max_dd"]:
        fails.append(f"book max DD {book['full']['max_dd']:.1f}% deeper than {S2_BAR['max_dd']}%")
    if not worst_eq >= S2_BAR["worst_trade_eq"]:
        fails.append(f"worst trade {worst_eq:.1f}% of equity < {S2_BAR['worst_trade_eq']}%")
    if len(yr) and not yr.min() >= S2_BAR["worst_year"]:
        fails.append(f"worst calendar year {yr.min():.1f}% < {S2_BAR['worst_year']}%")
    robust = trade_stats([t["ret"] for t in stress])["exp"] > 0 if stress else False
    stable_n = sum(1 for v in nb.values() if trade_stats([t["ret"] for t in v])["exp"] > 0)
    return {"verdict": "PASS" if not fails else "FAIL", "fails": fails, "all": allst, "halves": hs,
            "book": book, "tbill": tb, "robust": robust, "stable": f"{stable_n} of {len(nb)}",
            "worst_trade_eq": worst_eq, "worst_year": float(yr.min()) if len(yr) else float("nan"),
            "hwm_stops": hwm_stops(nav[nav.index >= "2000-01-01"])}


# ═══════════════════════════════════════════════════════════════════════════
#  Run (Actions)
# ═══════════════════════════════════════════════════════════════════════════

def _log(msg: str) -> None:
    print(f"[lever_lab {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def _yf_close(tickers, start):
    import yfinance as yf
    df = yf.download(tickers, start=start, auto_adjust=True, progress=False, group_by="ticker", threads=True)
    out = {}
    for t in tickers:
        try:
            sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
            sub = sub.dropna(subset=["Close"])
            sub.index = pd.to_datetime(sub.index).tz_localize(None).normalize() \
                if getattr(sub.index, "tz", None) else pd.to_datetime(sub.index).normalize()
            if len(sub):
                out[t] = sub[["Open", "High", "Low", "Close"]].astype(float)
        except Exception:
            pass
    return out


def run_s1(ohlcv: dict, vix: pd.Series, irx: pd.Series, cash_d: pd.Series) -> dict:
    import swing_backtest as bt
    etfs = [t for t in bt.SECTOR_ETFS + list(bt.OTHER_ETFS) if t not in bt.LEVERAGED]
    sector_of = {**{s: s for s in bt.SECTOR_ETFS}, **{t: s for t, s in bt.OTHER_ETFS.items()}}
    ohl = {t: v for t, v in ohlcv.items() if t in etfs}
    _log(f"S1: M0 signals on {len(ohl)} funds ...")
    res = bt.run(ohl, etfs, [], sector_of, setups=("M0",), variants=("B",), verbose=False)
    trs = [t for t in res["trades"]["B"] if t.mkt_ok and t.asset == "etf"]
    _log(f"S1: {len(trs)} M0 trades with SPY above its 200-day")
    spy = ohl["SPY"]["Close"]
    prep, dmap = {}, {}
    for tk, df in ohl.items():
        iv = iv_series(df["Close"], spy, vix).to_numpy()
        rate = (irx.reindex(df.index).ffill() / 100.0).to_numpy()
        ema10 = df["Close"].ewm(span=10, adjust=False).mean().to_numpy()
        prep[tk] = (df.index, df["Open"].to_numpy(), df["Close"].to_numpy(), ema10, iv, rate)
        dmap[tk] = {dd: i for i, dd in enumerate(df.index)}       # ONE map per fund, shared by its trades

    def build(mode, delta=S1_DELTA, dte=S1_DTE, ivm=1.0, spm=1.0):
        out = []
        for t in trs:
            d = prep[t.ticker]
            if d[0][t.entry_t] < pd.Timestamp("2005-01-01"):
                continue
            x = option_trade(t.ticker, d[0], d[1], d[2], d[3], d[4], d[5], t.entry_t, t.entry, t.stop0,
                             t.events, mode, delta, dte, ivm, spm)
            if x is not None:
                x["_dates"] = dmap[t.ticker]
                x["stock_r"] = t.r_net
                out.append(x)
        return out

    # affordable funds: one contract at today's price and IV <= premium cap on $10k (depends on delta)
    def affordable(delta=S1_DELTA, dte=S1_DTE):
        a, rows = set(), []
        for tk, (dates, o, c, e, iv, rate) in prep.items():
            S, sg, rr = c[-1], iv[-1], (rate[-1] if np.isfinite(rate[-1]) else 0.04)
            if not (np.isfinite(S) and np.isfinite(sg)):
                continue
            K = strike_for_delta(S, delta, dte / 365, rr, sg)
            one = bs_call(S, K, dte / 365, rr, sg) * 100 * (1 + half_spread(tk))
            ok = one <= S1_PREMIUM_PCT / 100 * S1_ACCOUNT
            rows.append({"ticker": tk, "price": round(float(S), 2), "iv": round(float(sg) * 100, 1),
                         "one_contract": round(one, 0), "pct_of_10k": round(one / S1_ACCOUNT * 100, 1), "affordable": ok})
            if ok:
                a.add(tk)
        return a, rows
    afford, feas = affordable()
    cal = spy.index[spy.index >= pd.Timestamp("2005-01-01")]
    out = {"n_stock_trades": len(trs), "afford": sorted(afford), "feas": feas}
    for mode, key in (("mirror", "S1a"), ("native", "S1b")):
        _log(f"S1: {key} base, harsh and neighbours ...")
        opts = build(mode)
        nav, taken = s1_book(opts, cal, cash_d, allowed=afford)
        nav_all, _ = s1_book(opts, cal, cash_d)
        harsh = build(mode, ivm=HARSH_IV_MULT, spm=HARSH_SPREAD_MULT)
        nbs = {}
        for kind, v in S1_NEIGHBOURS:
            o2 = build(mode, delta=v if kind == "delta" else S1_DELTA, dte=v if kind == "dte" else S1_DTE)
            nbs[f"{kind} {v}"] = s1_book(o2, cal, cash_d, allowed=afford)[0]
        ver = s1_verdict(opts, nav, spy.reindex(cal), harsh, nbs)
        ver["book_all_funds"] = nav_stats(nav_all, "2005-01-01")
        ver["taken"] = len(taken)
        ver["hold_median"] = float(np.median([x["hold_days"] for x in opts])) if opts else float("nan")
        ver["years"] = year_returns(nav).round(1).to_dict()
        # DELTA SWEEP — report only (not a bar, not a trial). Each delta uses its own affordable set.
        sweep = []
        for dl in DELTA_SWEEP:
            o3 = opts if dl == S1_DELTA else build(mode, delta=dl)
            af, _rows = affordable(dl)
            nv = s1_book(o3, cal, cash_d, allowed=af)[0]
            st3 = trade_stats([x["ret"] for x in o3])
            sweep.append({"delta": dl, "n": st3["n"], "exp": st3["exp"], "pf": st3["pf"], "payoff": st3["payoff"],
                          "big_win_share": st3["big_win_share"], "afford_n": len(af),
                          "book": nav_stats(nv, "2005-01-01"),
                          "book_all": nav_stats(s1_book(o3, cal, cash_d)[0], "2005-01-01")})
            del o3
        ver["delta_sweep"] = sweep
        _log(f"S1: {key} done — {ver['verdict']}")
        out[key] = {"verdict": ver, "nav": nav, "opts": opts}
    stock = trade_stats([t.r_net for t in trs if prep[t.ticker][0][t.entry_t] >= pd.Timestamp("2005-01-01")])
    out["stock_R"] = stock
    return out


def run_s2(idx: dict, vix: pd.Series, cash_d: pd.Series, real: dict) -> dict:
    cal = idx["SPY"].index[idx["SPY"].index >= pd.Timestamp("2000-01-01")]
    trades = [t for t in s2_trades(idx, vix, cash_d) if t["entry_date"] >= pd.Timestamp("2000-01-01")]
    nav = s2_book(trades, cal, cash_d)
    tb = (1 + cash_d.reindex(cal).fillna(0.0)).cumprod() * 10_000
    stress = [t for t in s2_trades(idx, vix, cash_d, spread_mult=S2_STRESS["spread_mult"],
                                   stop_bps=S2_STRESS["stop_bps"]) if t["entry_date"] >= pd.Timestamp("2000-01-01")]
    nb = {}
    for kind, v in S2_NEIGHBOURS:
        kw = {"z": {"z_thr": v}, "vix": {"vix_thr": v}, "target": {"target": v}, "stop": {"stop": v}}[kind]
        nb[f"{kind} {v}"] = [t for t in s2_trades(idx, vix, cash_d, **kw) if t["entry_date"] >= pd.Timestamp("2000-01-01")]
    ver = s2_verdict(trades, nav, tb, stress, nb)
    ver["years"] = year_returns(nav).round(1).to_dict()
    ver["neighbours"] = {k: trade_stats([t["ret"] for t in v]) for k, v in nb.items()}
    ver["stress"] = trade_stats([t["ret"] for t in stress])
    ver["lev_check"] = {"UPRO": lev_check(idx["SPY"]["Close"], real.get("UPRO"), cash_d),
                        "TQQQ": lev_check(idx["QQQ"]["Close"], real.get("TQQQ"), cash_d)}
    eps = {"2000–02": ("2000-01-01", "2002-12-31"), "2008–09": ("2008-01-01", "2009-06-30"),
           "2020": ("2020-01-01", "2020-12-31"), "2022": ("2022-01-01", "2022-12-31")}
    ver["episodes"] = {k: trade_stats([t["ret"] for t in trades if pd.Timestamp(a) <= t["entry_date"] <= pd.Timestamp(b)])
                       for k, (a, b) in eps.items()}
    live = {}
    for name, df in idx.items():
        z = washout_z(df["Close"])
        live[name] = {"date": str(df.index[-1].date()), "z": round(float(z.iloc[-1]), 2),
                      "vix": round(float(vix.reindex(df.index).ffill().iloc[-1]), 2)}
    ver["live"] = live
    return {"verdict": ver, "nav": nav, "trades": trades}


def _p(x, nd=2, pct=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x * 100:+.{nd}f}%" if pct else f"{x:.{nd}f}"


def render(s1: dict, s2: dict, stamp: str) -> str:
    L = [f"# Lever lab {VERSION} — {stamp}", "",
         f"Pre-registered in `claude/lever_lab_2026-11-21.md`. Trials {TRIALS_BEFORE} → {TRIALS_BEFORE + TRIALS_HERE}. "
         "Option values are Black-Scholes MODEL prices (no historical option data). Research, not personalized advice.", ""]
    for key in ("S1a", "S1b"):
        v = s1[key]["verdict"]
        a = v["all"]
        L += [f"## {key} — {'mirror the M0 trade' if key == 'S1a' else 'option-native exits'}: **{v['verdict']}**", ""]
        L += [f"- Fails: {'; '.join(v['fails']) or 'none'}",
              f"- Trades {a['n']} · expectancy {_p(a['exp'], 1, True)} of premium · PF {_p(a['pf'])} · win {_p(a['win'], 0, True)} "
              f"· avg win {_p(a['avg_win'], 0, True)} / avg loss {_p(a['avg_loss'], 0, True)} (payoff {_p(a['payoff'])}) "
              f"· wins ≥ +25%: {_p(a['big_win_share'], 0, True)} of wins · median hold {v['hold_median']:.0f} sessions"]
        for h, st in v["halves"].items():
            hh = v["harsh_halves"].get(h, {})
            L.append(f"- {h}: n {st['n']}, expectancy {_p(st['exp'], 1, True)}, PF {_p(st['pf'])}; harsh stress expectancy "
                     f"{_p(hh.get('exp'), 1, True)}")
        L.append(f"- ROBUST (harsh stress > 0 both halves): {'yes' if v['robust'] else 'no'} · STABLE (neighbours beating SPY): {v['stable']}")
        L += ["", "| Book (affordable funds, 5% premium, max 4) | CAGR | Max DD | SPY CAGR |", "|---|---|---|---|"]
        for h in v["book"]:
            L.append(f"| {h} | {v['book'][h]['cagr']:.2f}% | {v['book'][h]['max_dd']:.1f}% | {v['spy'][h]['cagr']:.2f}% |")
        L += [f"", f"- Same book on every M0 fund (fractional contracts, not buyable at $10k): "
                   f"CAGR {v['book_all_funds']['cagr']:.2f}%, max DD {v['book_all_funds']['max_dd']:.1f}%",
              f"- Times the live −20% high-water stop would have halted the book: {v['hwm_stops']}", ""]
        if v.get("delta_sweep"):
            L += ["**Delta sweep (report only — not a bar, not a trial; each delta has its own affordable funds):**", "",
                  "| Delta | Trades | Expectancy | PF | Payoff | Wins ≥ +25% | Affordable funds | Book CAGR | Book max DD | Every-fund CAGR |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
            for w in v["delta_sweep"]:
                L.append(f"| {w['delta']:.2f} | {w['n']} | {_p(w['exp'], 1, True)} | {_p(w['pf'])} | {_p(w['payoff'])} | "
                         f"{_p(w['big_win_share'], 0, True)} | {w['afford_n']} | {w['book']['cagr']:.2f}% | "
                         f"{w['book']['max_dd']:.1f}% | {w['book_all']['cagr']:.2f}% |")
            L.append("")
    st = s1["stock_R"]
    L += [f"Reference — the same M0 trades in shares: n {st['n']}, expectancy {st['exp']:+.3f}R, PF {_p(st['pf'])}.", "",
          f"Affordable funds (one 0.70-delta, 60-day call ≤ 5% of $10,000 today): {', '.join(s1['afford']) or 'none'}", "",
          "| Fund | Price | IV % | One contract $ | % of $10k |", "|---|---|---|---|---|"]
    for f in sorted(s1["feas"], key=lambda f: f["one_contract"]):
        L.append(f"| {f['ticker']} | {f['price']} | {f['iv']} | {f['one_contract']:,.0f} | {f['pct_of_10k']} |")
    v = s2["verdict"]
    a = v["all"]
    L += ["", f"## S2 — washout snapback, 3× index fund: **{v['verdict']}**", "",
          f"- Fails: {'; '.join(v['fails']) or 'none'}",
          f"- Trades {a['n']} · expectancy {_p(a['exp'], 1, True)} per trade (on the 3× position) · PF {_p(a['pf'])} · win {_p(a['win'], 0, True)} "
          f"· avg win {_p(a['avg_win'], 0, True)} / avg loss {_p(a['avg_loss'], 0, True)} (payoff {_p(a['payoff'])}) · wins ≥ +25%: "
          f"{_p(a['big_win_share'], 0, True)} of wins",
          f"- Worst trade {v['worst_trade_eq']:.1f}% of equity · worst calendar year {v['worst_year']:.1f}% · "
          f"−20% high-water stops: {v['hwm_stops']}",
          f"- ROBUST (spreads ×2, stop slippage 60bp): expectancy {_p(v['stress']['exp'], 1, True)} → {'yes' if v['robust'] else 'no'} "
          f"· STABLE (neighbours with positive expectancy): {v['stable']}"]
    for h, st in v["halves"].items():
        L.append(f"- {h}: n {st['n']}, expectancy {_p(st['exp'], 1, True)}, PF {_p(st['pf'])}")
    L += ["", "| Book (35% per trade, T-bills idle) | CAGR | Max DD | T-bill CAGR |", "|---|---|---|---|"]
    for h in v["book"]:
        L.append(f"| {h} | {v['book'][h]['cagr']:.2f}% | {v['book'][h]['max_dd']:.1f}% | {v['tbill'][h]['cagr']:.2f}% |")
    L += ["", "| Episode | Trades | Expectancy | Win |", "|---|---|---|---|"]
    for k, st in v["episodes"].items():
        L.append(f"| {k} | {st['n']} | {_p(st['exp'], 1, True)} | {_p(st['win'], 0, True)} |")
    L += ["", "| Neighbour | Trades | Expectancy | PF |", "|---|---|---|---|"]
    for k, st in v["neighbours"].items():
        L.append(f"| {k} | {st['n']} | {_p(st['exp'], 1, True)} | {_p(st['pf'])} |")
    L += ["", f"- Synthetic 3× vs real funds (calendar years, synthetic − real): UPRO {v['lev_check']['UPRO']}; "
              f"TQQQ {v['lev_check']['TQQQ']}",
          "- Today (paper only, not a trade): " + "; ".join(
              f"{k} z {x['z']} with VIX {x['vix']} on {x['date']}" for k, x in v["live"].items()), "",
          f"*lever_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def main() -> int:
    import swing_backtest as bt
    stamp = datetime.now(timezone.utc).date().isoformat()
    etfs = [t for t in bt.SECTOR_ETFS + list(bt.OTHER_ETFS) if t not in bt.LEVERAGED]
    _log("fetching prices ...")
    ohlcv = bt.fetch_ohlcv(sorted(set(etfs)), start="2003-06-01")
    misc = _yf_close(["^VIX", "^IRX", "SPY", "QQQ", "UPRO", "TQQQ"], "1998-01-01")
    if "^VIX" not in misc or "^IRX" not in misc or "SPY" not in ohlcv or "QQQ" not in misc:
        print("[lever_lab] DATA FAILURE: VIX, IRX, SPY or QQQ missing; nothing written.")
        return 1
    vix = misc["^VIX"]["Close"]
    irx = misc["^IRX"]["Close"]
    cal_all = misc["SPY"].index
    cash_d = (irx.reindex(cal_all).ffill() / 100.0 / 252).fillna(0.0)
    missing = sorted(set(etfs) - set(ohlcv))
    s1 = run_s1(ohlcv, vix, irx, cash_d)
    _log("S2: washout snapback ...")
    s2 = run_s2({"SPY": misc["SPY"], "QQQ": misc["QQQ"]}, vix, cash_d,
                {k: misc[k]["Close"] for k in ("UPRO", "TQQQ") if k in misc})
    md = render(s1, s2, stamp)
    if missing:
        md += f"\nNo data for: {', '.join(missing)}\n"
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_LOGS.mkdir(parents=True, exist_ok=True)
    (OUT_LOGS / "latest.md").write_text(md)
    (OUT_LOGS / f"{stamp}.md").write_text(md)
    for key in ("S1a", "S1b"):
        pd.DataFrame([{k: x[k] for k in ("ticker", "entry_date", "exit_date", "K", "cost", "ret", "hold_days", "open", "stock_r")}
                      for x in s1[key]["opts"]]).to_csv(OUT_DATA / f"{key}_trades.csv", index=False)
        s1[key]["nav"].round(2).to_csv(OUT_DATA / f"{key}_nav.csv")
    pd.DataFrame([{k: t[k] for k in t if k != "path"} for t in s2["trades"]]).to_csv(OUT_DATA / "S2_trades.csv", index=False)
    s2["nav"].round(2).to_csv(OUT_DATA / "S2_nav.csv")

    def _j(v):
        return {k: (_j(x) if isinstance(x, dict) else x) for k, x in v.items() if k not in ("opts", "nav", "trades")}
    summ = {"version": VERSION, "asof": stamp, "trials": TRIALS_BEFORE + TRIALS_HERE,
            "S1a": s1["S1a"]["verdict"], "S1b": s1["S1b"]["verdict"], "S2": s2["verdict"],
            "stock_R": s1["stock_R"], "afford": s1["afford"], "feas": s1["feas"]}
    (OUT_DATA / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
    print(md)
    return 0


# ═══════════════════════════════════════════════════════════════════════════
#  Selftest (offline)
# ═══════════════════════════════════════════════════════════════════════════

def selftest() -> dict:
    f = []
    # Black-Scholes sanity
    S, T, r, sg = 100.0, 60 / 365, 0.04, 0.25
    K = strike_for_delta(S, 0.70, T, r, sg)
    if abs(bs_delta(S, K, T, r, sg) - 0.70) > 1e-6 or not K < S:
        f.append(f"strike for delta 0.70 must give delta 0.70 below spot: {K}")
    c = bs_call(S, K, T, r, sg)
    if not (max(S - K, 0) < c < S):
        f.append("call price must sit between intrinsic and spot")
    if abs(bs_call(S, 100, 1.0, 0.0, 0.2) - 7.9656) > 1e-3:
        f.append("ATM 1-year 20% vol call must be 7.9656 (textbook)")
    if bs_call(120, 100, 0, 0.04, 0.3) != 20.0:
        f.append("expired call = intrinsic")
    # IV model: floor and VIX ratio
    idx = pd.bdate_range("2020-01-01", periods=300)
    rng = np.random.default_rng(1)
    spy = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), index=idx)
    fund = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300))), index=idx)
    ivs = iv_series(fund, spy, pd.Series(20.0, index=idx))
    rv20 = fund.pct_change().rolling(20).std() * math.sqrt(252)
    if not (ivs.dropna() >= IV_FLOOR_MULT * rv20.reindex(ivs.dropna().index) - 1e-12).all():
        f.append("IV must never sit below 1.10 x 20d realized vol")
    if not 0.30 < float(ivs.iloc[-1]) < 0.60:
        f.append(f"a fund with twice SPY's vol and VIX 20 should read ~40% IV: {ivs.iloc[-1]:.3f}")
    # S1 native: a rising stock doubles the option -> half sold, rest exits on EMA break
    n = 80
    d = pd.bdate_range("2021-01-04", periods=n)
    up = np.r_[np.linspace(100, 115, 20), np.linspace(115, 112, 60)]
    o_ = np.r_[up[0], up[:-1]]
    ema = pd.Series(up).ewm(span=10, adjust=False).mean().to_numpy()
    iv_ = np.full(n, 0.20)
    rt = np.full(n, 0.0)
    x = option_trade("XLF", d, o_, up, ema, iv_, rt, 0, 100.0, 95.0, None, "native")
    whys = [w for *_a, w in x["sales"]]
    if "half" not in whys or not x["ret"] > 0.5:
        f.append(f"native: a +15% move must double a 0.70-delta call and sell half: {whys} {x['ret']:.2f}")
    if x["sales"][0][1] != 0.5:
        f.append("native: the profit sale is exactly half")
    # time stop at 21 DTE on a flat stock
    flat = np.full(n, 100.0)
    y = option_trade("XLF", d, flat, flat, flat, iv_, rt, 0, 100.0, 90.0, None, "native")
    if [w for *_a, w in y["sales"]] != ["time stop"] or (d[y["exit_t"]] - d[0]).days < S1_DTE - S1_TIME_STOP_DTE:
        f.append(f"native: flat stock must exit by the 21-DTE time stop: {y['sales']}")
    if not y["ret"] < 0:
        f.append("a flat stock must lose premium (decay + spread)")
    # stop: stock closes through stop0 -> all sold next open
    dn = np.r_[np.full(5, 100.0), np.full(n - 5, 94.0)]
    z = option_trade("XLF", d, dn, dn, dn, iv_, rt, 0, 100.0, 95.0, None, "native")
    if z["sales"][0][0] != 6 or z["sales"][0][1] != 1.0:
        f.append(f"native: close through the stop sells all at the next open: {z['sales']}")
    # mirror follows trims and exit
    ev = [(0, "entry", 1.0, 100.0, 3), (5, "trim", 0.25, 104.0, 3), (10, "exit", 0.75, 103.0, 3)]
    m = option_trade("XLF", d, up, up, ema, iv_, rt, 0, 100.0, 95.0, ev, "mirror")
    if [(t, round(q, 2)) for t, q, *_r in m["sales"]] != [(5, 0.25), (10, 0.75)]:
        f.append(f"mirror: sales must follow the stock's trims and exit: {m['sales']}")
    # spreads: tier 2 costs more; harsh doubles
    if not half_spread("ITB") > half_spread("XLF") or half_spread("XLF", 2.0) != 2 * half_spread("XLF"):
        f.append("spread tiers")
    # stats
    ts = trade_stats([1.0, 0.3, -0.5, -0.5])
    if abs(ts["pf"] - 1.3) > 1e-9 or abs(ts["payoff"] - 1.3) > 1e-9 or ts["big_win_share"] != 1.0:
        f.append(f"trade_stats: {ts}")
    nav = pd.Series([100, 120, 90, 130, 100, 78], index=pd.bdate_range("2020-01-01", periods=6))
    if abs(nav_stats(nav)["max_dd"] - (78 / 130 - 1) * 100) > 1e-9 or hwm_stops(nav) != 2:
        f.append(f"nav_stats / hwm_stops: {nav_stats(nav)} {hwm_stops(nav)}")
    # S2: washout detection and exits on a synthetic crash and bounce
    cal = pd.bdate_range("2010-01-04", periods=400)
    base = 100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0.0003, 0.008, 400)))
    base[300:305] = base[299] * np.array([0.97, 0.94, 0.91, 0.89, 0.88])
    base[305:] = base[304] * np.exp(np.cumsum(np.r_[0.03, np.full(94, 0.004)]))
    dfi = pd.DataFrame({"Open": np.r_[base[0], base[:-1]], "Close": base}, index=cal)
    vix = pd.Series(np.where(np.arange(400) >= 300, 40.0, 15.0), index=cal)
    cash = pd.Series(0.0, index=cal)
    sig = s2_signals({"SPY": dfi}, vix)
    if sig.empty or not ((sig["date"] >= cal[300]) & (sig["date"] <= cal[310])).all():
        f.append(f"S2: the crash must fire, and only there: {sig['date'].tolist()[:3]}")
    trs = s2_trades({"SPY": dfi}, vix, cash)
    # day 2 of the crash fires, the next day keeps falling -> stop (the falling knife); a later signal
    # re-enters and the bounce hits the +8% target (+20% or more on 3x)
    if [t["why"] for t in trs] != ["stop", "target"] or not trs[1]["ret"] > 0.2 or not -0.15 < trs[0]["ret"] < -0.05:
        f.append(f"S2: knife then bounce: {[(t['why'], round(t['ret'], 3)) for t in trs]}")
    if trs and trs[0]["entry_date"] != cal[cal.get_loc(trs[0]["signal"]) + 1]:
        f.append("S2: entry is the next open after the signal")
    if len(trs) == 2 and trs[1]["signal"] < trs[0]["exit_date"]:
        f.append("S2: no new trade while one is open")
    nav2 = s2_book(trs, cal, cash)
    exp_nav = 10_000 * (1 + S2_SIZE * trs[0]["ret"]) * (1 + S2_SIZE * trs[1]["ret"]) if len(trs) == 2 else 0
    if abs(nav2.iloc[-1] - exp_nav) > 1e-6:
        f.append(f"S2 book: 35% per trade, compounding: {nav2.iloc[-1]:.2f} vs {exp_nav:.2f}")
    # S2 stop on a continued fall
    fall = base.copy()
    fall[305:] = base[304] * np.exp(np.cumsum(np.full(95, -0.01)))
    dff = pd.DataFrame({"Open": np.r_[fall[0], fall[:-1]], "Close": fall}, index=cal)
    trf = s2_trades({"SPY": dff}, vix, cash)
    if not trf or trf[0]["why"] != "stop" or not -0.15 < trf[0]["ret"] < -0.05:
        f.append(f"S2: a continued fall must stop out near -3% x 3: {[(t['why'], round(t['ret'], 3)) for t in trf]}")
    # breakeven: a close +5% or more moves the stop to the entry; a fall back exits there, not at -3%
    be = base.copy()
    be[305:] = base[304] * np.exp(np.cumsum(np.r_[0.03, 0.025, -0.02, -0.03, -0.03, np.full(90, -0.01)]))
    dfb = pd.DataFrame({"Open": np.r_[be[0], be[:-1]], "Close": be}, index=cal)
    trb = [t for t in s2_trades({"SPY": dfb}, vix, cash) if t["entry_date"] >= cal[305]]
    if not trb or trb[0]["why"] != "breakeven stop":
        f.append(f"S2: +5% then a fall must exit at the breakeven stop: {[(t['why'], round(t['ret'], 3)) for t in trb]}")
    # one position at a time across indices
    two = s2_trades({"SPY": dfi, "QQQ": dfi.copy()}, vix, cash)
    ov = any(b["entry_date"] <= a["exit_date"] for a, b in zip(two, two[1:]))
    if ov:
        f.append("S2: positions must not overlap across indices")
    # S1 book: slots and premium
    opts = []
    for k in range(6):
        opts.append({"ticker": f"T{k}", "entry_date": cal[10], "exit_t": 5, "cost": 1.0, "sales": [(5, 1.0, 2.0, "x")],
                     "marks": {t: (1.0, 1.0) for t in range(0, 5)}, "_dates": {cal[10 + t]: t for t in range(0, 6)}})
    nb, taken = s1_book(opts, cal[:30], pd.Series(0.0, index=cal))
    if len(taken) != S1_MAX_OPEN or abs(nb.iloc[-1] - 10_000 * (1 + S1_MAX_OPEN * S1_PREMIUM_PCT / 100)) > 1e-6:
        f.append(f"S1 book: 4 slots of 5% each, each doubling, must add 20%: {len(taken)} {nb.iloc[-1]:.2f}")
    nb2, _ = s1_book(opts, cal[:30], pd.Series(0.0, index=cal), allowed={"T0"})
    if abs(nb2.iloc[-1] - 10_500) > 1e-6:
        f.append("S1 book: the affordable filter must drop other funds")
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 1)
    sys.exit(main())
