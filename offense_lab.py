"""
offense_lab.py  (v1.3 — 2026-11-13)
───────────────────────────────────
v1.3: no new candidates. O9 (best so far: −19.3% max DD, Sharpe 0.79, missed
  2005–15 and, by 0.02 pts, 2016–26) gets the sensitivity check the bar would
  have run had it passed, widened to every parameter it has: the trend average
  (150 / 250), the fast-exit average (40 / 60), the Offense stop (−6 / −10%)
  and the cooldown (10 / 30 sessions), one at a time. Each run is a logged
  trial (8). Read it as "does O9's profile — drawdown inside −20%, CAGR above
  SPY over the full window — survive nearby settings?", not as a new search:
  the best cell is NOT adopted for being best.

v1.2: fast out, slow back in. v1.1's O7 was the best engine (beat SPY full
  and 2016–26, Sharpe 0.73) but its −25.7% came from one episode (2000: QQQ
  crashed while still above its 200-day), and O8's −8% stop with a quick
  50-day re-entry whipsawed to −33.6%. New candidates:
    O9   O7 with an asymmetric Offense exit. Leave Offense when QQQ closes
         below its 50-day for 2 closes OR the Offense book is −8% from its
         high since entry. Re-enter Offense only when SPY and QQQ are above
         their 200-day AND QQQ above its 50-day (2 closes each) AND at least
         20 sessions after a fast exit. SPY below its 200-day (2 closes)
         still means Defense. The fast exit goes to BALANCED.
    O10  O9 with the fast exit going to DEFENSE.
  Bar unchanged from v1.1 (−20% max drawdown, beat SPY full and both halves,
  robust at 150/250). 2 new trials.

v1.1 (Matt, 2026-11-13): "catch and pivot fast" — the book should detect a
  bear trend before its drawdown gets much past 8–10%, not ride a −33% one.
  So the drawdown bar becomes ABSOLUTE: max drawdown no deeper than −20%
  (room for gaps and the one-session lag past an −8% pivot), replacing
  "60% of SPY's". Return bar and robustness unchanged. New candidates,
  aimed at O2 (beat SPY in every window in v1.0, failed on drawdown only):
    O6  O2 + the production breaker on the engine's own NAV: at −8% from peak
        every risk sleeve is halved into SGOV; released above −5% with SPY
        above its 50-day for 2 closes (model_book rules)
    O7  three-state O2: Offense while SPY and QQQ > 200d; Defense while
        SPY < 200d; Balanced when mixed (SPY up, QQQ down)
    O8  O7 + a portfolio stop: at −8% from peak the WHOLE book pivots to
        Defense, held until SPY closes above its 50-day for 2 closes; the
        peak is re-based at the release so the next stop is measured afresh
  Guards (breaker / stop) act with the same one-session lag as the trend
  states. New report column: drawdown episodes beyond −10% and −15%.
  Trials: only candidates not run before are added to the trial log.

Offense / Balanced / Defense engine, battle test #1 (risk_policy §3:
"allocation must be able to beat SPY in bull markets and defend in bear
markets, with tested switch-in and switch-back rules").

WHY PRICE-BASED SWITCHING
  The regime classifier has no point-in-time history (fix_status N11), so it
  cannot be backtested. The engine's switches therefore use only signals that
  existed on the day: SPY and QQQ vs their 200-day averages and sector breadth.
  The regime classifier keeps its job INSIDE Balanced (today's book).

BOOKS
  OFFENSE_1X   50% QQQ / 50% SPY
  OFFENSE_15X  25% QQQ 2x, 25% SPY 2x, 25% QQQ, 25% SPY  (1.5x equity)
  OFFENSE_2X   50% QQQ 2x / 50% SPY 2x                     (2x equity)
  BALANCED     the live All-Weather book: target_weights(hedge_lab.REGIME)
  DEFENSE      60% SGOV / 20% GLD / 20% TLT
  2x sleeves are SYNTHETIC: 2 x daily return − (T-bill + 0.50%/yr) financing
  − 0.95%/yr fee. An accuracy table compares them with real SSO/QLD since 2006.

CANDIDATES (frozen before the first run)
  O1  SPY trend           SPY while SPY > 200d, else SGOV (reference)
  O2  two-mode            OFFENSE_1X while SPY and QQQ > 200d, else BALANCED
  O3  three-mode          OFFENSE_1X if SPY > 200d and >= 6 of 9 sectors > 200d;
                          DEFENSE if SPY < 200d and <= 3 of 9; else BALANCED
  O4  three-mode 1.5x     O3 with OFFENSE_15X
  O5  three-mode 2x       O3 with OFFENSE_2X
  Switches need 2 consecutive closes in the new state (the playbook's
  two-close rule) and are traded one session late: the state seen at the
  close of d-1 sets the weights held over d+1 (an evening read, a next-day
  trade). Costs: 5bp per unit of turnover. No circuit breaker inside the
  engines (they are the drawdown control); BALANCED-alone (V0) keeps it.

BAR (risk_policy §3 "compelling" bar, PROPOSED; fixed before this run)
  1. CAGR above SPY's over the full window (2000-01-03 →) AND in both halves
     (2005–2015, 2016–2026), net of costs and the switch lag;
  2. max drawdown no deeper than 60% of SPY's over the full window;
  3. ROBUST: 1 and 2 also hold with the 150-day and 250-day averages
     (risk_policy §8: nearby settings). Pass at 200 only = FRAGILE, not adoptable.
  Calendar years vs SPY are reported, not scored: no switching rule beats SPY
  every single year, and the report says how often and by how much it lags.
  Deflated Sharpe uses this lab's own trial log.

HONEST LIMITS
  * No regime gating (N11). * Synthetic leverage before SSO/QLD (2006) and for
    the whole history (one consistent model). * GLD before 2004 is gold futures
    (GC=F, from 2000-08); before that GLD earns nothing (coverage reported).
  * The BALANCED book is TODAY's weights held through history (as the hedge lab).
  * Trend rules lag fast crashes (2020, 2024): read the stress table.

Run:  python offense_lab.py            (needs yfinance + network: Actions)
      python offense_lab.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date
from pathlib import Path
from statistics import NormalDist
from typing import Callable, Optional

import numpy as np
import pandas as pd

import hedge_lab as hl
import model_book as mb

VERSION = "v1.3"
HISTORY_START = "1998-01-01"
EVAL_START = "2000-01-03"
HALVES = (("2005-15", "2005-01-03", "2015-12-31"), ("2016-26", "2016-01-01", None))
STRESS = [("dotcom_2000", "2000-03-24", "2002-10-09", "Dot-com bust"),
          ("gfc_2008", "2007-10-09", "2009-03-09", "Global financial crisis"),
          ("covid_2020", "2020-02-19", "2020-03-23", "Covid crash"),
          ("rates_2022", "2022-01-03", "2022-10-12", "Rates shock"),
          ("carry_2024", "2024-07-16", "2024-08-05", "Yen-carry unwind")]
MA = 200
ROBUST_MAS = (150, 250)
CONFIRM = 2
LAG = 1
COST_BPS = 5.0
LEV_FEE = 0.0095
LEV_SPREAD = 0.0050
BREADTH_ON, BREADTH_OFF = 6, 3
SECTORS9 = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLU", "XLB", "XLP")
BAR_MAX_DD = 20.0          # v1.1: absolute (Matt: pivot near −8–10%; −20% allows gaps and lag)
GUARD_TRIP = -8.0          # O6 breaker and O8 stop, % from the engine's peak (model_book.TRIGGER_DD)
GUARD_RELEASE_DD = -5.0    # O6 only (model_book.RELEASE_DD)
GUARD_SMA = 50
GUARD_CLOSES = 2
FAST_SMA = 50              # O9/O10: QQQ below its 50-day for 2 closes ends Offense
FAST_STOP = -8.0           # O9/O10: Offense book % from its high since entry
COOLDOWN = 20              # O9/O10: sessions after a fast exit before Offense may resume
DIAGNOSE = {"O9": [("ma", 150), ("ma", 250), ("fast_sma", 40), ("fast_sma", 60),
                   ("fast_stop", -6.0), ("fast_stop", -10.0), ("cooldown", 10), ("cooldown", 30)]}
OUT_DIR = Path("data/offense_lab")
LOG_DIR = Path("logs/offense_lab")

CHAINS = {**hl.PROXIES, "SPY": ["SPY"], "AGG": ["AGG", "VBMFX"]}
EXTRA_TICKERS = ["SPY", "QQQ", "AGG", "VBMFX", "SSO", "QLD", *SECTORS9]

OFFENSE_1X = {"QQQ": 50.0, "SPY": 50.0}
OFFENSE_15X = {"QQQ2X": 25.0, "SPY2X": 25.0, "QQQ": 25.0, "SPY": 25.0}
OFFENSE_2X = {"QQQ2X": 50.0, "SPY2X": 50.0}
DEFENSE = {"SGOV": 60.0, "GLD": 20.0, "TLT": 20.0}
CANDIDATES = {
    "O1": {"label": "SPY trend (SPY or T-bills)", "kind": "spy"},
    "O2": {"label": "Two-mode: growth when SPY & QQQ > 200d, else Balanced", "kind": "two", "off": OFFENSE_1X},
    "O3": {"label": "Three-mode 1x (trend + breadth)", "kind": "three", "off": OFFENSE_1X},
    "O4": {"label": "Three-mode 1.5x offense", "kind": "three", "off": OFFENSE_15X},
    "O5": {"label": "Three-mode 2x offense", "kind": "three", "off": OFFENSE_2X},
    "O6": {"label": "O2 + production −8% breaker", "kind": "two", "off": OFFENSE_1X, "guard": "breaker"},
    "O7": {"label": "Three-state O2: Offense / Balanced (mixed) / Defense (SPY < 200d)", "kind": "two3",
           "off": OFFENSE_1X},
    "O8": {"label": "O7 + −8% portfolio stop to Defense", "kind": "two3", "off": OFFENSE_1X, "guard": "stop"},
    "O9": {"label": "O7, fast exit (QQQ < 50d or −8%) to Balanced, slow re-entry", "kind": "fast",
           "off": OFFENSE_1X, "out": "BAL"},
    "O10": {"label": "O9 with the fast exit to Defense", "kind": "fast", "off": OFFENSE_1X, "out": "DEF"},
}
PRIOR_V10 = {"O1", "O2", "O3", "O4", "O5"}      # run in v1.0 (logged before the candidates column existed)


# ── data ────────────────────────────────────────────────────────────────────

def lev_returns(r: pd.Series, cash: pd.Series, k: float = 2.0) -> pd.Series:
    """Synthetic k-x daily ETF: k*r - (k-1)*(T-bill + spread) - fee."""
    return k * r - (k - 1) * (cash.fillna(0.0) + LEV_SPREAD / 252) - LEV_FEE / 252


def build_data(closes: dict) -> dict:
    spy = hl._norm(closes["SPY"])
    cal = pd.DatetimeIndex(spy.index)
    rets, srcs = hl.splice(closes, CHAINS, cal)
    cash = rets["SGOV"]
    rets["SPY2X"] = lev_returns(rets["SPY"], cash)
    rets["QQQ2X"] = lev_returns(rets["QQQ"], cash)
    lv = {}
    for t in ("SPY", "QQQ", *SECTORS9):
        s = closes.get(t)
        lv[t] = hl._norm(s).reindex(cal).ffill(limit=3) if s is not None and len(s) else pd.Series(np.nan, index=cal)
    return {"cal": cal, "rets": rets, "srcs": srcs, "levels": pd.DataFrame(lv, index=cal), "closes": closes}


# ── signals and states (value at d uses data up to and including d) ─────────

def above_ma(level: pd.Series, n: int) -> pd.Series:
    ma = level.rolling(n, min_periods=n).mean()
    out = level > ma
    return out.where(ma.notna())          # NaN until n bars of history


def confirm(raw: pd.Series, n: int, start) -> pd.Series:
    """The state changes only after `n` consecutive days of a new raw state."""
    out, cur, run_v, run_n = [], start, None, 0
    for v in raw.tolist():
        if v is None or (isinstance(v, float) and v != v):
            out.append(cur); run_v, run_n = None, 0
            continue
        if v == cur:
            run_v, run_n = None, 0
        else:
            run_n = run_n + 1 if v == run_v else 1
            run_v = v
            if run_n >= n:
                cur, run_v, run_n = v, None, 0
        out.append(cur)
    return pd.Series(out, index=raw.index, dtype=object)


def _two_up(s: pd.Series) -> pd.Series:
    """True on the 2nd consecutive close that is True (NaN counts as not)."""
    x = s.fillna(False).astype(bool)
    return x & x.shift(1, fill_value=False)


def _two_down(s: pd.Series) -> pd.Series:
    """True on the 2nd consecutive close that is known False."""
    x = (s == False) & s.notna()          # noqa: E712  (NaN is not "down")
    return x & x.shift(1, fill_value=False)


def states_fast(levels: pd.DataFrame, rets: pd.DataFrame, ma: int = MA, fast_sma: int = FAST_SMA,
                fast_stop: float = FAST_STOP, cooldown: int = COOLDOWN) -> pd.Series:
    """O9/O10 state machine: OFF / BAL / DEF / OUT (fast-exited). Value at d uses data <= d only."""
    spy_up, qqq_up = above_ma(levels["SPY"], ma), above_ma(levels["QQQ"], ma)
    q50 = above_ma(levels["QQQ"], fast_sma)
    known = spy_up.notna() & qqq_up.notna() & q50.notna()
    spy_dn2, qqq_dn2, q50_dn2 = _two_down(spy_up).to_numpy(), _two_down(qqq_up).to_numpy(), _two_down(q50).to_numpy()
    entry = (_two_up(spy_up) & _two_up(qqq_up) & _two_up(q50)).to_numpy()
    spy_up2 = _two_up(spy_up).to_numpy()
    r = rets.reindex(levels.index)
    idx = (1 + 0.5 * r["SPY"].fillna(0.0) + 0.5 * r["QQQ"].fillna(0.0)).cumprod().to_numpy()
    out, state, peak, out_i = [], "BAL", None, -10 ** 9
    kn = known.to_numpy()
    for i in range(len(levels)):
        if not kn[i]:
            out.append(state); continue
        if spy_dn2[i]:
            state = "DEF"
        elif state == "OFF":
            peak = max(peak, idx[i])
            if q50_dn2[i] or (idx[i] / peak - 1) * 100 <= fast_stop:
                state, out_i = "OUT", i
            elif qqq_dn2[i]:
                state = "BAL"
        elif entry[i] and (state != "OUT" or i - out_i >= cooldown):
            state, peak = "OFF", idx[i]
        elif state == "DEF" and spy_up2[i]:
            state = "BAL"
        out.append(state)
    return pd.Series(out, index=levels.index, dtype=object)


def states(kind: str, levels: pd.DataFrame, ma: int = MA, n_confirm: int = CONFIRM,
           rets: Optional[pd.DataFrame] = None, **fast) -> pd.Series:
    if kind == "fast":
        return states_fast(levels, rets, ma, **fast)
    spy_up = above_ma(levels["SPY"], ma)
    if kind == "spy":
        raw = spy_up.map(lambda x: None if x != x else ("OFF" if x else "CASH"))
        return confirm(raw, n_confirm, "CASH")
    qqq_up = above_ma(levels["QQQ"], ma)
    if kind == "two3":
        both = spy_up.notna() & qqq_up.notna()
        su, qu = spy_up.fillna(False).astype(bool), qqq_up.fillna(False).astype(bool)
        raw = pd.Series(np.where(both, np.where(su & qu, "OFF", np.where(~su, "DEF", "BAL")), None),
                        index=levels.index, dtype=object)
        return confirm(raw, n_confirm, "BAL")
    if kind == "two":
        both = spy_up.notna() & qqq_up.notna()
        raw = pd.Series(np.where(both, np.where(spy_up.fillna(False) & qqq_up.fillna(False), "OFF", "BAL"), None),
                        index=levels.index, dtype=object)
        return confirm(raw, n_confirm, "BAL")
    ups = pd.DataFrame({t: above_ma(levels[t], ma) for t in SECTORS9 if t in levels})
    have = ups.notna().sum(axis=1)
    breadth = ups.fillna(False).astype(int).sum(axis=1)
    ok = spy_up.notna() & (have >= len(SECTORS9))
    s_up = spy_up.fillna(False).astype(bool)
    raw = np.where(~ok, None, np.where(s_up & (breadth >= BREADTH_ON), "OFF",
                                       np.where(~s_up & (breadth <= BREADTH_OFF), "DEF", "BAL")))
    return confirm(pd.Series(raw, index=levels.index, dtype=object), n_confirm, "BAL")


def book_for(state: str, cand: dict, balanced: dict) -> dict:
    if cand["kind"] == "spy":
        return {"SPY": 100.0} if state == "OFF" else {"SGOV": 100.0}
    if state == "OUT":
        return DEFENSE if cand.get("out") == "DEF" else balanced
    return {"OFF": cand["off"], "DEF": DEFENSE}.get(state, balanced)


def weights_fn(st: pd.Series, cand: dict, balanced: dict, lag: int = LAG) -> Callable:
    """weights_on(d): the book for the state seen `lag` sessions before d."""
    lagged = st.shift(lag)
    lagged.iloc[:lag] = st.iloc[0]
    m = lagged.to_dict()
    return lambda d: dict(book_for(m[d], cand, balanced))


# ── stats ───────────────────────────────────────────────────────────────────

def window_stats(nav: pd.Series, start, end=None) -> dict:
    s = nav[nav.index >= pd.Timestamp(start)]
    if end is not None:
        s = s[s.index <= pd.Timestamp(end)]
    if len(s) < 2:
        return {}
    s = s / s.iloc[0]
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = s.iloc[-1] ** (1 / yrs) - 1 if yrs >= 1 else float("nan")
    dd = float((s / s.cummax() - 1).min())
    r = s.pct_change().dropna()
    return {"total_pct": round((s.iloc[-1] - 1) * 100, 2), "cagr_pct": round(cagr * 100, 2) if cagr == cagr else None,
            "max_dd_pct": round(dd * 100, 2), "vol_pct": round(float(r.std() * math.sqrt(252)) * 100, 2),
            "sharpe": round(float(r.mean() / r.std() * math.sqrt(252)), 2) if r.std() > 0 else None,
            "calmar": round(cagr / abs(dd), 2) if (dd < 0 and cagr == cagr) else None}


def year_returns(nav: pd.Series, start=EVAL_START) -> pd.Series:
    s = nav[nav.index >= pd.Timestamp(start)]
    y = s.resample("YE").last()
    first = s.iloc[0]
    return (y / y.shift(1).fillna(first) - 1) * 100


def deflated_sharpe(sr: float, n_obs: int, skew: float, kurt: float, sr_var: float, n_trials: int) -> float:
    """Bailey & López de Prado: P(true SR > 0) after selecting the best of n_trials."""
    nd = NormalDist()
    if n_trials < 2 or sr_var <= 0:
        sr0 = 0.0
    else:
        g = 0.5772156649
        sr0 = math.sqrt(sr_var) * ((1 - g) * nd.inv_cdf(1 - 1 / n_trials) + g * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    den = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    return float(nd.cdf((sr - sr0) * math.sqrt(max(1, n_obs - 1)) / den))


def bar_check(st: dict, spy: dict) -> list:
    """Reasons a result misses the bar ([] = meets it)."""
    why = []
    for k in ("full", "2005-15", "2016-26"):
        c, s = (st.get(k) or {}).get("cagr_pct"), (spy.get(k) or {}).get("cagr_pct")
        if c is None or s is None or not c > s:
            why.append(f"{k} CAGR {c}% ≤ SPY {s}%")
    d = (st.get("full") or {}).get("max_dd_pct")
    if d is None or abs(d) > BAR_MAX_DD + 1e-9:
        why.append(f"max DD {d}% deeper than −{BAR_MAX_DD:g}%")
    return why


def summary(nav: pd.Series) -> dict:
    out = {"full": window_stats(nav, EVAL_START)}
    for k, s, e in HALVES:
        out[k] = window_stats(nav, s, e)
    for k, s, e, _ in STRESS:
        out[k] = window_stats(nav, s, e)
    return out


# ── runs ────────────────────────────────────────────────────────────────────

def simulate(days, rets, weights_on, cost=COST_BPS) -> pd.Series:
    return hl.simulate(days, rets, weights_on, None, breaker=False, cost_bps=cost)["nav"]


def sim_guarded(days, rets: pd.DataFrame, weights_on: Callable, guard: str, spy_up50: pd.Series,
                cost: float = COST_BPS) -> pd.DataFrame:
    """hedge_lab.simulate's accounting plus a drawdown guard on the engine's own NAV.
    The guard state after the close of d-1 shapes the weights set at d (held over d+1):
    the same one-session lag as the trend states.
      breaker: risk sleeves halved into SGOV (model_book.apply_breaker); off above −5% with
               SPY > 50d for 2 closes
      stop:    the whole book in DEFENSE; off after SPY > 50d for 2 closes; peak re-based"""
    rows, prev = [], None
    nav = peak = mb.START_NAV
    g_prev, g_now, rc = False, False, 0
    for d in days:
        if prev is not None:
            r, have, tot = 0.0, 0.0, 0.0
            for t, wt in prev["w"].items():
                if wt <= 0:
                    continue
                tot += wt
                x = rets.at[d, t] if t in rets.columns else np.nan
                if x == x:
                    r += wt / 100.0 * float(x); have += wt
            nav *= 1 + r
            peak = max(peak, nav)
        base = weights_on(d)
        if g_prev:
            w = mb.apply_breaker(base, hl.REGIME) if guard == "breaker" else dict(DEFENSE)
        else:
            w = dict(base)
        w = {k: float(v) for k, v in w.items()}
        turn = 0.0
        if prev is not None:
            keys = set(w) | set(prev["w"])
            turn = sum(abs(w.get(k, 0.0) - prev["w"].get(k, 0.0)) for k in keys) / 2.0
            nav *= 1 - turn / 100.0 * cost / 1e4
            peak = max(peak, nav)
        dd = (nav / peak - 1) * 100
        v = spy_up50.get(d, np.nan)
        up50 = bool(v) if v == v else False          # unknown 50-day = no release
        if not g_now:
            g_now, rc = (dd <= GUARD_TRIP), 0
        else:
            ok = up50 and (guard == "stop" or dd > GUARD_RELEASE_DD)
            rc = rc + 1 if ok else 0
            if rc >= GUARD_CLOSES:
                g_now, rc = False, 0
                if guard == "stop":
                    peak = nav                      # the next stop is measured from the release
        rows.append({"date": d, "nav": nav, "peak": peak, "w": w, "turnover": turn, "guard": g_now,
                     "coverage": 1.0})
        prev = rows[-1]
        g_prev = g_now
    return pd.DataFrame(rows).set_index("date")


def dd_episodes(nav: pd.Series, depth: float, start=EVAL_START) -> int:
    """Distinct peak-to-new-peak drawdowns whose trough reached `depth` (%)."""
    s = nav[nav.index >= pd.Timestamp(start)]
    n, peak, hit = 0, -np.inf, False
    for v in s.to_numpy():
        if v >= peak:
            peak, hit = v, False
            continue
        if not hit and (v / peak - 1) * 100 <= depth:
            n, hit = n + 1, True
    return n


def run_candidate(key: str, data: dict, balanced: dict, ma: int = MA, lag: int = LAG, **fast) -> dict:
    cand = CANDIDATES[key]
    st = states(cand["kind"], data["levels"], ma, rets=data["rets"], **fast)
    days = data["cal"][data["cal"] >= pd.Timestamp(EVAL_START) - pd.Timedelta(days=10)]
    if cand.get("guard"):
        sim = sim_guarded(days, data["rets"], weights_fn(st, cand, balanced, lag), cand["guard"],
                          above_ma(data["levels"]["SPY"], GUARD_SMA))
    else:
        sim = hl.simulate(days, data["rets"], weights_fn(st, cand, balanced, lag), None, breaker=False,
                          cost_bps=COST_BPS)
    s_in = st.reindex(days)
    switches = int((s_in != s_in.shift(1)).iloc[1:].sum())
    share = s_in[s_in.index >= pd.Timestamp(EVAL_START)].value_counts(normalize=True).mul(100).round(1).to_dict()
    g = sim["guard"] if "guard" in sim else None
    guard_pct = round(float(g[g.index >= pd.Timestamp(EVAL_START)].mean()) * 100, 1) if g is not None else None
    trips = int((g.astype(int).diff() == 1).sum()) if g is not None else None
    if cand["kind"] == "fast":                       # report fast exits in the guard columns
        ev = s_in[s_in.index >= pd.Timestamp(EVAL_START)]
        trips = int(((ev == "OUT") & (ev.shift(1) != "OUT")).sum())
        guard_pct = round(float((ev == "OUT").mean()) * 100, 1)
    return {"nav": sim["nav"], "states": st, "switches": switches, "share": share, "guard_pct": guard_pct,
            "guard_trips": trips, "turnover": float(sim["turnover"].sum()),
            "coverage_min": float(sim["coverage"].min())}


def run_all(data: dict, balanced: dict) -> dict:
    days = data["cal"][data["cal"] >= pd.Timestamp(EVAL_START) - pd.Timedelta(days=10)]
    rets = data["rets"]
    navs = {"SPY": simulate(days, rets, lambda d: {"SPY": 100.0}, 0.0),
            "QQQ": simulate(days, rets, lambda d: {"QQQ": 100.0}, 0.0),
            "60/40": simulate(days, rets, lambda d: {"SPY": 60.0, "AGG": 40.0}, 0.0),
            "V0": hl.simulate(days, rets, lambda d: dict(balanced), hl._norm(data["closes"]["SPY"]),
                              breaker=True, cost_bps=COST_BPS)["nav"]}
    runs = {}
    for k in CANDIDATES:
        runs[k] = run_candidate(k, data, balanced)
        navs[k] = runs[k]["nav"]
    summ = {k: summary(v) for k, v in navs.items()}
    verdicts, robust_n = [], 0
    robust_runs = {}
    for k in CANDIDATES:
        why = bar_check(summ[k], summ["SPY"])
        row = {"candidate": k, "label": CANDIDATES[k]["label"], "reasons_200": "; ".join(why) or "meets bar"}
        if why:
            row["verdict"] = "FAIL"
        else:
            rob = []
            for m in ROBUST_MAS:
                rr = run_candidate(k, data, balanced, ma=m)
                robust_runs[(k, m)] = rr
                robust_n += 1
                w2 = bar_check(summary(rr["nav"]), summ["SPY"])
                if w2:
                    rob.append(f"MA {m}: " + "; ".join(w2))
            row["verdict"] = "PASS (robust)" if not rob else "FRAGILE (passes at 200-day only)"
            row["robustness"] = "; ".join(rob) or "holds at 150 and 250"
        yr = pd.DataFrame({"c": year_returns(navs[k]), "s": year_returns(navs["SPY"])}).dropna()
        row["years_beat_spy"] = f"{int((yr.c > yr.s).sum())} of {len(yr)}"
        row["worst_year_vs_spy_pts"] = round(float((yr.c - yr.s).min()), 1) if len(yr) else None
        row["switches"] = runs[k]["switches"]
        row["episodes_10"] = dd_episodes(navs[k], -10.0)
        row["episodes_15"] = dd_episodes(navs[k], -15.0)
        row["guard_trips"] = runs[k].get("guard_trips")
        row["guard_on_pct"] = runs[k].get("guard_pct")
        verdicts.append(row)
    robust_keys = [f"{k}@ma{m}" for (k, m) in robust_runs]
    diag = []
    for k, grid in DIAGNOSE.items():
        if k not in CANDIDATES:
            continue
        base = summ[k]
        diag.append({"candidate": k, "setting": "base (200 / 50 / −8% / 20)", **_diag_row(base, summ["SPY"]),
                     "episodes_15": dd_episodes(navs[k], -15.0)})
        for prm, val in grid:
            kw = {"ma": val} if prm == "ma" else {prm: val}
            rr = run_candidate(k, data, balanced, **kw)
            robust_keys.append(f"{k}@{prm}={val}")
            diag.append({"candidate": k, "setting": f"{prm} = {val}", **_diag_row(summary(rr["nav"]), summ["SPY"]),
                         "episodes_15": dd_episodes(rr["nav"], -15.0)})
    years = pd.DataFrame({k: year_returns(v) for k, v in navs.items()}).round(1)
    return {"navs": navs, "summ": summ, "runs": runs, "robust": robust_runs, "diag": pd.DataFrame(diag),
            "robust_keys": robust_keys,
            "verdicts": pd.DataFrame(verdicts), "years": years, "robust_n": robust_n,
            "episodes_spy": (dd_episodes(navs["SPY"], -10.0), dd_episodes(navs["SPY"], -15.0))}


def _diag_row(st: dict, spy: dict) -> dict:
    f, a, b = st.get("full") or {}, st.get("2005-15") or {}, st.get("2016-26") or {}
    why = bar_check(st, spy)
    profile = (f.get("max_dd_pct") is not None and abs(f["max_dd_pct"]) <= BAR_MAX_DD
               and (f.get("cagr_pct") or -99) > ((spy.get("full") or {}).get("cagr_pct") or 99))
    return {"cagr_full": f.get("cagr_pct"), "cagr_05_15": a.get("cagr_pct"), "cagr_16_26": b.get("cagr_pct"),
            "max_dd": f.get("max_dd_pct"), "sharpe": f.get("sharpe"), "calmar": f.get("calmar"),
            "keeps_profile": bool(profile), "bar": "PASS" if not why else "FAIL", "misses": "; ".join(why)}


def lev_accuracy(data: dict) -> pd.DataFrame:
    """Synthetic 2x vs the real fund, calendar years since inception."""
    rows = []
    for real, syn in (("SSO", "SPY2X"), ("QLD", "QQQ2X")):
        s = data["closes"].get(real)
        if s is None or not len(s):
            rows.append({"fund": real, "note": "no data"}); continue
        r_real = hl.ticker_returns(data["closes"], real, data["cal"])
        both = pd.DataFrame({"real": r_real, "syn": data["rets"][syn]}).dropna()
        if both.empty:
            continue
        y = (1 + both).resample("YE").prod() - 1
        diff = (y["syn"] - y["real"]) * 100
        rows.append({"fund": real, "years": len(y), "mean_diff_pts": round(float(diff.mean()), 2),
                     "worst_diff_pts": round(float(diff.abs().max()), 2),
                     "note": "synthetic minus real; positive = synthetic flatters"})
    return pd.DataFrame(rows)


def today_read(data: dict, out: dict) -> list:
    L = []
    for k, r in out["runs"].items():
        st = r["states"]
        last = st.index[-1]
        since = st[st != st.iloc[-1]]
        since_d = since.index[-1].date().isoformat() if len(since) else "start"
        L.append(f"- **{k}** ({CANDIDATES[k]['label']}): **{st.iloc[-1]}** as of {last.date()} (since {since_d})")
    return L


# ── report ──────────────────────────────────────────────────────────────────

def _f(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


NAMES = {"SPY": "SPY", "QQQ": "QQQ", "60/40": "60/40 SPY/AGG", "V0": "Balanced alone (today's book + breaker)",
         **{k: f"{k} {v['label']}" for k, v in CANDIDATES.items()}}


def render(out: dict, acc: pd.DataFrame, data: dict, n_trials: int, dsr: dict, asof: str) -> str:
    s = out["summ"]
    L = [f"# Offense engine lab {VERSION} — {asof}", "",
         f"Window {EVAL_START} → {data['cal'][-1].date()}; halves 2005–2015 and 2016–2026. "
         f"Switches need {CONFIRM} closes and trade {LAG} session late; {COST_BPS:g}bp per unit of turnover. "
         f"Trials logged to date (incl. this run): **{n_trials}**.", "",
         "## Verdicts against the bar (fixed before the run)",
         f"Bar (v1.1, Matt 2026-11-13): CAGR above SPY over the full window AND both halves, net of costs and lag; "
         f"max drawdown no deeper than −{BAR_MAX_DD:g}%; and the same at the 150- and 250-day averages (robustness). "
         f"The goal behind it: pivot before a drawdown gets much past 8–10%.", "",
         f"Drawdown episodes = distinct peak-to-new-peak declines reaching −10% / −15% "
         f"(SPY: {out['episodes_spy'][0]} / {out['episodes_spy'][1]}).", "",
         "| Candidate | Verdict | Years beating SPY | Worst year vs SPY | Episodes ≤ −10% / −15% | Guard trips (time on) | "
         "Switches | Reasons (200-day) | Robustness |",
         "|---|---|---|---|---|---|---|---|---|"]
    for _, r in out["verdicts"].iterrows():
        gt = r.get("guard_trips")
        guard = f"{int(gt)} ({_f(r.get('guard_on_pct'), 0)}%)" if gt == gt and gt is not None else "—"
        L.append(f"| {NAMES[r.candidate]} | **{r.verdict}** | {r.years_beat_spy} | {_f(r.worst_year_vs_spy_pts, 1)} pts | "
                 f"{r.episodes_10} / {r.episodes_15} | {guard} | "
                 f"{r.switches} | {r.reasons_200} | {r.get('robustness') or '—'} |")
    dg = out.get("diag")
    if dg is not None and len(dg):
        L += ["", "## Sensitivity (v1.3): does the best candidate's profile survive nearby settings?",
              "One parameter moved at a time. Profile = max drawdown inside −20% AND full-window CAGR above SPY. "
              "The best cell is not adopted for being best.", "",
              "| Candidate | Setting | CAGR full / 05–15 / 16–26 % | Max DD % | Sharpe | Calmar | Episodes ≤ −15% | "
              "Keeps profile | Bar | Misses |", "|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in dg.iterrows():
            L.append(f"| {r.candidate} | {r.setting} | {_f(r.cagr_full)} / {_f(r.cagr_05_15)} / {_f(r.cagr_16_26)} | "
                     f"{_f(r.max_dd)} | {_f(r.sharpe)} | {_f(r.calmar)} | {r.episodes_15} | "
                     f"{'yes' if r.keeps_profile else 'no'} | {r.bar} | {r.misses or '—'} |")
        n_ok = int(dg["keeps_profile"].iloc[1:].sum())
        L.append(f"\nProfile held in **{n_ok} of {len(dg) - 1}** nearby settings.")
    L += ["", "## Full window and halves", "",
          "| Book | CAGR full / 05–15 / 16–26 % | Max DD full % | Vol % | Sharpe | Calmar | DSR | Time in Offense / Balanced / Defense |",
          "|---|---|---|---|---|---|---|---|"]
    for k in ["SPY", "QQQ", "60/40", "V0", *CANDIDATES]:
        f, a, b = s[k]["full"], s[k]["2005-15"], s[k]["2016-26"]
        sh = out["runs"][k]["share"] if k in out["runs"] else {}
        mix = (f"{sh.get('OFF', 0):.0f} / {sh.get('BAL', 0) + sh.get('CASH', 0):.0f} / {sh.get('DEF', 0):.0f}%"
               + (f" + fast-exit {sh.get('OUT', 0):.0f}%" if "OUT" in sh else "") if sh else "—")
        L.append(f"| {NAMES[k]} | {_f(f.get('cagr_pct'))} / {_f(a.get('cagr_pct'))} / {_f(b.get('cagr_pct'))} | "
                 f"{_f(f.get('max_dd_pct'))} | {_f(f.get('vol_pct'))} | {_f(f.get('sharpe'))} | {_f(f.get('calmar'))} | "
                 f"{_f(dsr.get(k), 3)} | {mix} |")
    L += ["", "O1's middle share is time in T-bills.", "", "## Stress windows (max drawdown %, total return %)", "",
          "| Book | " + " | ".join(lbl for _, _, _, lbl in STRESS) + " |", "|---" * (len(STRESS) + 1) + "|"]
    for k in ["SPY", "QQQ", "60/40", "V0", *CANDIDATES]:
        cells = []
        for key, _, _, _ in STRESS:
            w = s[k].get(key) or {}
            cells.append(f"{_f(w.get('max_dd_pct'), 1)} / {_f(w.get('total_pct'), 1)}")
        L.append(f"| {NAMES[k]} | " + " | ".join(cells) + " |")
    yt = out["years"].copy()
    yt.index = [d.year for d in yt.index]
    L += ["", "## Calendar years (%)", "", "| Year | " + " | ".join(yt.columns) + " |", "|---" * (len(yt.columns) + 1) + "|"]
    for y, row in yt.iterrows():
        L.append(f"| {y} | " + " | ".join(_f(x, 1) for x in row.tolist()) + " |")
    L += ["", "## What each engine says today", ""]
    L += today_read(data, out)
    L += ["", "## Synthetic 2x vs the real funds (calendar years)", ""]
    for _, r in acc.iterrows():
        if "years" in r and r.get("years") == r.get("years"):
            L.append(f"- {r.fund}: {int(r.years)} years, mean {_f(r.mean_diff_pts)} pts/yr, worst {_f(r.worst_diff_pts)} pts ({r.note})")
        else:
            L.append(f"- {r.fund}: {r.get('note')}")
    cov = out["runs"]["O3"]["coverage_min"] if "O3" in out["runs"] else None
    L += ["", "## Honest limits",
          "- No regime gating: the classifier has no point-in-time history (N11). Balanced is today's book held through history.",
          "- 2x sleeves are synthetic over the whole window (one consistent model); see the accuracy table.",
          f"- Lowest daily sleeve coverage in O3: {_f(cov * 100 if cov is not None else None, 0)}% (GLD has no data before 2000-08).",
          "- Trend rules lag fast crashes: Covid 2020 and the 2024 carry unwind are the cases to read.",
          "", f"*offense_lab.py {VERSION}. Research, not personalized advice.*"]
    return "\n".join(L) + "\n"


def write(out: dict, data: dict, asof: str) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tl = OUT_DIR / "trial_log.csv"
    log = pd.read_csv(tl) if tl.exists() else pd.DataFrame(columns=["date", "version", "trials", "note"])
    prior = int(log["trials"].sum()) if len(log) else 0
    seen = set()
    for _, r in log.iterrows():
        c = r.get("candidates")
        if isinstance(c, str) and c:
            seen |= set(c.split(","))
        elif str(r.get("version")) == "v1.0":
            seen |= PRIOR_V10
    new = [k for k in [*CANDIDATES, *out.get("robust_keys", [])] if k not in seen]
    out["trials"] = len(new)
    n_trials = prior + out["trials"]
    srs, info = [], {}
    for k in CANDIDATES:
        r = out["navs"][k]
        r = r[r.index >= pd.Timestamp(EVAL_START)].pct_change().dropna()
        if len(r) > 10 and r.std() > 0:
            sr = float(r.mean() / r.std()); srs.append(sr)
            info[k] = (sr, len(r), float(r.skew()), float(r.kurt()) + 3.0)
    var = float(np.var(srs, ddof=1)) if len(srs) > 1 else 0.0
    dsr = {k: round(deflated_sharpe(*v, var, n_trials), 3) for k, v in info.items()}
    acc = lev_accuracy(data)
    rows = []
    for k, ss in out["summ"].items():
        for w, st in ss.items():
            rows.append({"book": k, "window": w, **st})
    pd.DataFrame(rows).to_csv(OUT_DIR / "results.csv", index=False)
    v = out["verdicts"].copy(); v["dsr"] = v["candidate"].map(dsr)
    v.to_csv(OUT_DIR / "verdicts.csv", index=False)
    out["years"].to_csv(OUT_DIR / "years.csv")
    if len(out.get("diag", [])):
        out["diag"].to_csv(OUT_DIR / "sensitivity.csv", index=False)
    pd.DataFrame(out["navs"]).round(4).to_csv(OUT_DIR / "nav.csv")
    acc.to_csv(OUT_DIR / "lev_accuracy.csv", index=False)
    pd.DataFrame({k: r["states"] for k, r in out["runs"].items()}).tail(30).to_csv(OUT_DIR / "states_recent.csv")
    row = pd.DataFrame([{"date": asof, "version": VERSION, "trials": out["trials"],
                         "note": f"new: {','.join(new) or 'none'}",
                         "candidates": ",".join(new)}])
    pd.concat([log, row]).to_csv(tl, index=False)
    md = render(out, acc, data, n_trials, dsr, asof)
    path = LOG_DIR / f"{asof}_report.md"
    path.write_text(md)
    return {"report": str(path), "dsr": dsr, "n_trials": n_trials}


def main() -> int:
    tickers = sorted(set(hl.all_tickers()) | set(EXTRA_TICKERS))
    closes = hl.yf_fetch(tickers, start=HISTORY_START)
    missing = [t for t in ("SPY", "QQQ", *SECTORS9, "^IRX") if t not in closes]
    print(f"[offense_lab] {VERSION}: {len(closes)} of {len(tickers)} tickers; required missing: {missing}")
    if missing:
        print("[offense_lab] DATA FAILURE: a signal input is missing; nothing written (a gap is not a result).")
        return 1
    import regime_classifier as rc
    balanced = {k: float(v) for k, v in rc.target_weights(hl.REGIME, gate=False).items()}
    data = build_data(closes)
    out = run_all(data, balanced)
    res = write(out, data, date.today().isoformat())
    print(json.dumps(res, indent=2))
    print(out["verdicts"][["candidate", "verdict", "years_beat_spy", "reasons_200"]].to_string(index=False))
    return 0


# ── selftest (offline, synthetic) ───────────────────────────────────────────

def _synthetic(seed: int = 5, n: int = 3200) -> dict:
    rng = np.random.default_rng(seed)
    cal = pd.bdate_range("1999-01-04", periods=n)
    reg = np.where((np.arange(n) // 500) % 2 == 0, 0.0007, -0.0006)       # alternating bull / bear
    mk = rng.normal(reg, 0.011)
    closes = {"SPY": pd.Series(100 * np.exp(np.cumsum(mk)), index=cal),
              "QQQ": pd.Series(100 * np.exp(np.cumsum(1.3 * mk + rng.normal(0, 0.006, n))), index=cal),
              "^IRX": pd.Series(3.0, index=cal)}
    for t in SECTORS9:
        closes[t] = pd.Series(100 * np.exp(np.cumsum(0.9 * mk + rng.normal(0, 0.006, n))), index=cal)
    for t in ("VUSTX", "GC=F", "XLK", "DVY", "XLE", "DBC", "SOXX", "SI=F", "GDX", "AQMIX", "VBMFX"):
        closes[t] = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0001, 0.008, n))), index=cal)
    return closes


def selftest() -> dict:
    import tempfile
    f = []
    # 1. confirmation: a one-day flip never switches; two days do
    raw = pd.Series(["B", "O", "B", "O", "O", "O", "D", "B", None, "D", "D"])
    got = confirm(raw, 2, "B").tolist()
    if got != ["B", "B", "B", "B", "O", "O", "O", "O", "O", "O", "D"]:
        f.append(f"confirm(): {got}")
    # 2. synthetic leverage formula
    r, c = pd.Series([0.01, -0.02]), pd.Series([0.0001, 0.0001])
    want = 2 * r - (c + LEV_SPREAD / 252) - LEV_FEE / 252
    if not np.allclose(lev_returns(r, c).to_numpy(), want.to_numpy()):
        f.append("2x synthetic formula")
    # 3. books sum to 100
    for nm, b in (("OFFENSE_1X", OFFENSE_1X), ("OFFENSE_15X", OFFENSE_15X), ("OFFENSE_2X", OFFENSE_2X), ("DEFENSE", DEFENSE)):
        if abs(sum(b.values()) - 100) > 1e-9:
            f.append(f"{nm} sums to {sum(b.values())}")
    # 4. MA is trailing and NaN until n bars
    lvl = pd.Series(np.arange(1, 301, dtype=float))
    a = above_ma(lvl, 200)
    if a.iloc[:199].notna().any() or not bool(a.iloc[250]):
        f.append("above_ma warm-up / direction")
    closes = _synthetic()
    data = build_data(closes)
    bal = {"VGT": 20.0, "GLD": 15.0, "SCHD": 15.0, "TLT": 15.0, "SGOV": 20.0, "XLE": 15.0}
    # 5. no look-ahead: states and weights at d are unchanged when the future is altered
    for kind in ("spy", "two", "three"):
        full = states(kind, data["levels"])
        cut = 2000
        lv2 = data["levels"].copy()
        lv2.iloc[cut + 1:] = lv2.iloc[cut + 1:] * 0.5            # crash everything after the cut
        part = states(kind, lv2)
        if not full.iloc[:cut + 1].equals(part.iloc[:cut + 1]):
            f.append(f"{kind}: states before the cut depend on later prices")
    st = states("three", data["levels"])
    wf = weights_fn(st, CANDIDATES["O3"], bal)
    days = data["cal"]
    chg = [i for i in range(1, len(st)) if st.iloc[i] != st.iloc[i - 1]]
    if not chg:
        f.append("synthetic bull/bear history produced no switch")
    else:
        i = chg[0]
        if wf(days[i]) != book_for(st.iloc[i - 1], CANDIDATES["O3"], bal) or \
                wf(days[i + 1]) != book_for(st.iloc[i], CANDIDATES["O3"], bal):
            f.append("weights must follow the state one session late (LAG = 1)")
    for want_state, want_book in (("OFF", OFFENSE_1X), ("DEF", DEFENSE), ("BAL", bal)):
        hit = [j for j in range(1, len(st)) if st.iloc[j - 1] == want_state]
        if hit and wf(days[hit[0]]) != want_book:
            f.append(f"state {want_state} must hold {want_book}, got {wf(days[hit[0]])}")
    if not {"OFF", "BAL", "DEF"} <= set(st.unique()):
        f.append(f"three-mode never visited all states on a bull/bear history: {set(st.unique())}")
    # 6. bar logic
    spy = {"full": {"cagr_pct": 8.0, "max_dd_pct": -50.0}, "2005-15": {"cagr_pct": 6.0}, "2016-26": {"cagr_pct": 12.0}}
    good = {"full": {"cagr_pct": 9.0, "max_dd_pct": -19.5}, "2005-15": {"cagr_pct": 7.0}, "2016-26": {"cagr_pct": 12.5}}
    if bar_check(good, spy):
        f.append(f"bar: a clear pass failed: {bar_check(good, spy)}")
    if not bar_check(dict(good, full={"cagr_pct": 9.0, "max_dd_pct": -20.5}), spy):
        f.append("bar v1.1: a −20.5% drawdown vs the −20% limit passed")
    if bar_check(dict(good, full={"cagr_pct": 9.0, "max_dd_pct": -20.0}), spy):
        f.append("bar v1.1: exactly −20% must pass")
    if not bar_check(dict(good, **{"2016-26": {"cagr_pct": 12.0}}), spy):
        f.append("bar: equal CAGR in a half must fail (strictly above)")
    # 6b. v1.1 three-state O2: SPY down -> Defense, mixed -> Balanced, both up -> Offense
    lv = pd.DataFrame({"SPY": np.r_[np.linspace(100, 200, 300), np.linspace(200, 120, 120)],
                       "QQQ": np.r_[np.linspace(100, 200, 260), np.linspace(200, 150, 160)]})
    s3 = states("two3", lv)
    if s3.iloc[250] != "OFF" or "DEF" not in set(s3.iloc[300:]) or "BAL" not in set(s3.iloc[255:330]):
        f.append(f"two3 states: {s3.iloc[[250, 280, 310, 419]].tolist()}")
    # 6d. v1.2 fast exit / slow re-entry (O9, O10)
    nf = 600
    ix = pd.bdate_range("2000-01-03", periods=nf)
    qq = np.r_[np.linspace(100, 300, 400), np.linspace(300, 270, 15), np.linspace(270, 330, 185)]
    lvf = pd.DataFrame({"SPY": np.linspace(100, 250, nf), "QQQ": qq}, index=ix)
    rf = lvf.pct_change().fillna(0.0)
    sf = states_fast(lvf, rf)
    first_out = next((i for i in range(nf) if sf.iloc[i] == "OUT"), None)
    if sf.iloc[399] != "OFF" or first_out is None or not 400 < first_out <= 415:
        f.append(f"fast exit: Offense by day 399 and OUT within the 15-day QQQ pullback: {sf.iloc[399]}, {first_out}")
    else:
        back = next((i for i in range(first_out, nf) if sf.iloc[i] == "OFF"), None)
        if back is None or back - first_out < COOLDOWN:
            f.append(f"re-entry must wait {COOLDOWN} sessions after a fast exit: out {first_out}, back {back}")
        if sf.iloc[first_out:first_out + 5].isin(["DEF"]).any():
            f.append("a QQQ pullback with SPY above its 200-day must not go to Defense")
    lvd = lvf.copy(); lvd.iloc[450:, 0] = np.linspace(250, 120, nf - 450)        # SPY breaks down
    sd = states_fast(lvd, lvd.pct_change().fillna(0.0))
    if sd.iloc[-1] != "DEF":
        f.append("SPY below its 200-day must mean Defense in the fast machine")
    lv8 = pd.DataFrame({"SPY": np.linspace(100, 250, nf), "QQQ": np.r_[np.linspace(100, 300, 400), np.full(nf - 400, 300.0)]},
                       index=ix)
    r8 = pd.DataFrame({"SPY": 0.0, "QQQ": 0.0}, index=ix); r8.iloc[420:440, :] = -0.005    # book bleeds -9.5%
    s8 = states_fast(lv8, r8)
    if "OUT" not in set(s8.iloc[420:445]):
        f.append("the −8% Offense-book stop must trigger a fast exit even when QQQ holds its 50-day")
    lv2 = lvf.copy(); lv2.iloc[421:] = lv2.iloc[421:] * 0.6
    if not states_fast(lv2, lv2.pct_change().fillna(0.0)).iloc[:421].equals(
            states_fast(lvf, rf).iloc[:421]):
        f.append("fast machine: states depend on later prices (look-ahead)")
    first_off = next((i for i in range(nf) if sf.iloc[i] == "OFF"), None)
    if first_off != 200:
        f.append(f"entry needs 2 closes: the 200-day is first known at bar 199, so Offense starts at 200, got {first_off}")
    bleed = next((i for i in range(nf) if s8.iloc[i] == "OUT"), None)
    want = 420 + next(n for n in range(1, 60) if (0.995 ** n - 1) * 100 <= FAST_STOP) - 1
    if bleed != want:
        f.append(f"the −8% stop must fire on the close that crosses it (bar {want}), got {bleed}")
    qv = np.r_[np.linspace(100, 300, 400), [286.0, 285.0], np.linspace(310, 400, nf - 402)]   # 2-close dip, fast rebound
    lvc = pd.DataFrame({"SPY": np.linspace(100, 250, nf), "QQQ": qv}, index=ix)
    sc = states_fast(lvc, lvc.pct_change().fillna(0.0))
    oc = next((i for i in range(nf) if sc.iloc[i] == "OUT"), None)
    bc = next((i for i in range(oc or 0, nf) if sc.iloc[i] == "OFF"), None) if oc else None
    if oc is None or bc is None or bc - oc != COOLDOWN:
        f.append(f"after a fast exit and an immediate rebound, Offense resumes exactly {COOLDOWN} sessions later: {oc}, {bc}")
    cO9, cO10 = CANDIDATES["O9"], CANDIDATES["O10"]
    if book_for("OUT", cO9, bal) != bal or book_for("OUT", cO10, bal) != DEFENSE or book_for("OFF", cO9, bal) != OFFENSE_1X:
        f.append("fast-exit books: O9 → Balanced, O10 → Defense, Offense unchanged")
    # 6c. guards: a steady 1%/day fall trips at -8%, acts one session late, and the stop re-bases its peak
    gd = pd.bdate_range("2020-01-01", periods=40)
    gr = pd.DataFrame({"X": np.r_[np.zeros(5), np.full(12, -0.01), np.full(23, 0.01)], "SGOV": 0.0, "GLD": 0.0,
                       "TLT": 0.0}, index=gd)
    up50 = pd.Series([False] * 25 + [True] * 15, index=gd)
    sb = sim_guarded(gd, gr, lambda d: {"X": 100.0}, "breaker", up50, cost=0.0)
    trip = sb.index[sb["guard"]][0]
    k = gd.get_loc(trip)
    if not (sb["nav"].iloc[k] / sb["peak"].iloc[k] - 1) * 100 <= GUARD_TRIP:
        f.append("breaker tripped before −8%")
    if sb["w"].iloc[k].get("X") != 100.0 or abs(sb["w"].iloc[k + 1].get("X", 0) - 50.0) > 1e-9:
        f.append("breaker must halve risk the session AFTER the trip close (lag 1)")
    ss = sim_guarded(gd, gr, lambda d: {"X": 100.0}, "stop", up50, cost=0.0)
    ks = gd.get_loc(ss.index[ss["guard"]][0])
    if ss["w"].iloc[ks + 1] != DEFENSE:
        f.append("the stop must move the whole book to DEFENSE the session after the trip")
    rel = [i for i in range(1, len(ss)) if ss["guard"].iloc[i - 1] and not ss["guard"].iloc[i]]
    if not rel or gd[rel[0]] < gd[26]:
        f.append("the stop may only release after 2 closes above the 50-day")
    elif abs(ss["peak"].iloc[rel[0]] - ss["nav"].iloc[rel[0]]) > 1e-9:
        f.append("the stop must re-base its peak at the release")
    if dd_episodes(pd.Series([100, 95, 89, 100, 101, 90, 85, 102], index=pd.bdate_range("2001-01-01", periods=8)),
                   -10.0, "2000-01-01") != 2:
        f.append("dd_episodes must count each peak-to-new-peak decline once")
    # 7. O1 in a market always above its average = SPY minus warm-up and costs
    up = {k: v for k, v in closes.items()}
    cal = data["cal"]
    up["SPY"] = pd.Series(100 * np.exp(np.cumsum(np.full(len(cal), 0.0004))), index=cal)
    d_up = build_data(up)
    r1 = run_candidate("O1", d_up, bal)
    st1 = r1["states"][r1["states"].index >= pd.Timestamp(EVAL_START)]
    if (st1 != "OFF").any() or r1["switches"] > 0:
        f.append("O1 in a steady uptrend must stay invested with no switches after warm-up")
    # 8. end to end: runs, writes, report has every section
    tmp = tempfile.mkdtemp(); cwd = os.getcwd()
    try:
        os.chdir(tmp)
        out = run_all(data, bal)
        res = write(out, data, "SELFTEST")
        md = Path(res["report"]).read_text()
        for sec in ("Verdicts against the bar", "Stress windows", "Calendar years", "What each engine says today",
                    "Synthetic 2x"):
            if sec not in md:
                f.append(f"report section missing: {sec}")
        if set(out["verdicts"]["candidate"]) != set(CANDIDATES):
            f.append("every candidate needs a verdict")
        if res["n_trials"] < len(CANDIDATES):
            f.append("trial count must include every candidate")
        res2 = write(out, data, "SELFTEST2")
        if res2["n_trials"] != res["n_trials"]:
            f.append(f"a rerun must not re-count candidates already tried: {res['n_trials']} -> {res2['n_trials']}")
        dg = out["diag"]
        if len(dg) != 1 + len(DIAGNOSE["O9"]) or "Sensitivity (v1.3)" not in md:
            f.append(f"sensitivity grid: {len(dg)} rows")
        if res["n_trials"] != len(CANDIDATES) + len(out["robust_keys"]):
            f.append(f"each sensitivity run is a trial: {res['n_trials']}")
        alt = run_candidate("O9", data, bal, cooldown=200)["states"]
        if alt.equals(out["runs"]["O9"]["states"]):
            f.append("the cooldown parameter must reach the state machine")
        for k in ("O6", "O7", "O8", "O9", "O10"):
            if k not in set(out["verdicts"]["candidate"]):
                f.append(f"{k} missing from the verdicts")
        nav = out["navs"]["O5"]
        if not (nav > 0).all():
            f.append("2x engine NAV went non-positive")
    finally:
        os.chdir(cwd)
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        r = selftest()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 1)
    sys.exit(main())
