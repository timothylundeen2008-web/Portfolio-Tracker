"""
hedge_lab.py  (v1.2 — October 2026)
───────────────────────────────────
v1.2 (2026-10-31): CONVEXITY SLEEVE TEST. Two specs disagree: risk_policy.md
  (PROPOSED) caps premium at 1% of NAV per YEAR; the built convexity_sleeve.py
  + risk_budget.py spend 2.00/1.25/0.50/0% of NAV per QUARTER by VIX's
  quartile in its own 1-year range. Both are tested (SLEEVES), each under the
  current breaker (B0) and the tiered release (B3), to inform the B0-vs-B3
  decision: does a sleeve close B3's dot-com gap without giving back its
  return? Puts are priced with convexity_sleeve._bs_put_approx (copied here:
  Black-Scholes, VIX as implied vol, the module's skew markup that errs
  expensive) on SPY, rolled at 60 days left, harvested at 3x/5x/10x of cost
  per the module's ladder, with OPTION_COST_PCT on every trade. No free
  historical option chain exists, so every option value is a MODEL mark.

v1.1 (2026-10-31): BREAKER RELEASE TEST. The v1 run showed the −8% circuit
  breaker, not the hedge sleeves, does most of the protecting, and that it
  latches: ON for 78% of the dot-com window and 27% of all sessions since
  2005, because release needs the book back above −5% while running at half
  risk. v1.1 tests five release rules on today's book (B0 = production; see
  BREAKER_RULES) over the stress windows, new ROUND-TRIP windows (peak to one
  year after the trough: stress windows end at the trough, where no release
  rule can act), and the full history. Any rule that releases on market trend
  re-measures the next trip from the release point; without that, a release
  while the book is still more than 8% below its old peak would re-trip the
  next day. The bar is fixed before the run (BREAKER_BAR_*). The v1 hedge
  sleeve tests are unchanged.

Real-price test bench for hedge rules. Answers one question with actual
history instead of opinion: "if the model book had followed rule X, what
would it have gained or lost in the episodes that matter, and what would the
rule have cost in normal markets?"

WHY
───
On 2026-10-30 the model book fell 1.65% while SPY fell 1.8%, holding only
~23% in growth sleeves. The hedges did not hedge: GLD / SLV / RING (18%) fell
with stocks, TLT (7%) rose 0.4% with a +0.14 stock/bond correlation, and the
brief's own "hold trend" column showed all four in DOWNTREND. Two candidate
rules follow from that. Before either touches the model book, they have to
earn it on real prices: one day is an anecdote, and the stress tab's
hand-estimated returns (fix_status N6) cannot test a rule at all.

WHAT IT TESTS
─────────────
  V0  current      the live book: target_weights(REGIME) from
                   regime_classifier (read live, so it stays in sync)
  V1  corr_tlt     TLT moves to SGOV while TLT's 60-day return correlation
                   with SPY is positive (TLT is beta, not ballast)
  V2  hedge_trend  each hedge sleeve (GLD, SLV, RING, TLT) is halved, freed
                   weight to SGOV, while it closes below a FALLING 200-day
  V3  both         V1 then V2
  SPY, 60/40       benchmarks (60% SPY / 40% AGG, daily rebalanced)

  Every variant carries the model book's own −8% circuit breaker, using
  model_book.apply_breaker / next_breaker, so the breaker is identical.

WINDOWS
  Stress:  dot-com 2000-02, GFC 2007-09, Covid 2020, rates 2022, carry 2024
  Full:    2005-01-03 to today (the cost of each rule in normal markets)
  Inception: the model book's own stored weights since 2026-08-12, with each
           rule applied on top. V0 here must reproduce the recorded NAV:
           that is the harness's accuracy check against production.

NO LOOKAHEAD
  Weights for day d are decided from closes up to and including d and are
  held from d to d+1, exactly as model_book.advance does. The selftest
  changes future prices and asserts no earlier weight moves.

PROXIES  (each labelled in the report; nothing is silently filled)
  Many sleeves did not exist in 2000 or 2008. Each sleeve has a chain; on
  every day the first ticker with a valid return is used:
    native  the sleeve's own ticker
    proxy   another ETF, fund, or future with the same job
    cash    a return synthesized from the 13-week T-bill yield (^IRX)
    none    no data: the sleeve earns 0% that day and is counted UNCOVERED
  A window with more than LOW_COVERAGE_PCT of the book uncovered is labelled
  LOW COVERAGE and excluded from the verdict counts.

  Known limit: KMLM (trend following) runs on AQMIX from 2010 and as cash
  before that. That UNDERSTATES the book's 2008 hedge in every variant
  equally, so it biases absolute numbers, not the comparison between rules.

  Not simulated: the entry gate (in transition_ambiguous it only touches
  SCHD +1, XLV +1, KMLM +3 vs base). Costs: COST_BPS per unit of one-way
  turnover from weight changes; drift rebalancing is free, as in the book.

Outputs
  data/hedge_lab/results.csv     one row per window x variant
  data/hedge_lab/coverage.csv    data source mix per window and sleeve
  logs/hedge_lab/<date>_report.md
Run:  python hedge_lab.py            (needs Yahoo; runs in GitHub Actions)
      python hedge_lab.py --selftest (offline, synthetic)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

import model_book as mb

VERSION = "v1.2"
REGIME = "transition_ambiguous"
HISTORY_START = "1999-01-01"

HEDGES = ("GLD", "SLV", "RING", "TLT")      # sleeves whose job is to offset equity losses
PARK = "SGOV"
CORR_WINDOW = 60
TREND_MA = 200
TREND_SLOPE_LAG = 20                        # 200-day MA "falling" = below its value 20 sessions ago
TREND_SCALE = 0.5
COST_BPS = 5.0
LOW_COVERAGE_PCT = 10.0
REPLAY_TOLERANCE = 0.25                     # NAV points, inception replay vs data/model_book.csv

OUT_DIR = Path("data/hedge_lab")
LOG_DIR = Path("logs/hedge_lab")

PROXIES = {
    "VGT":  ["VGT", "XLK"],
    "SMH":  ["SMH", "SOXX", "XLK"],
    "QQQ":  ["QQQ"],
    "GLD":  ["GLD", "GC=F"],
    "SLV":  ["SLV", "SI=F"],
    "RING": ["RING", "GDX", "VGPMX"],
    "XLE":  ["XLE"],
    "PDBC": ["PDBC", "DBC", "GSG"],
    "SCHD": ["SCHD", "DVY", "VIVAX"],
    "XLV":  ["XLV"],
    "XLU":  ["XLU"],
    "SGOV": ["SGOV", "BIL", "^IRX"],
    "USFR": ["USFR", "BIL", "^IRX"],
    "TLT":  ["TLT", "VUSTX"],
    "KMLM": ["KMLM", "AQMIX", "^IRX"],
}
BENCH = {"SPY": ["SPY"], "AGG": ["AGG", "VBMFX"]}
CASH_TICKER = "^IRX"
VIX_TICKER = "^VIX"                         # v1.2: implied vol for pricing the convexity sleeve

# ── convexity sleeve test (v1.2) — structure from Markets convexity_sleeve.py v1 ──
OTM_PCT = 8.0                               # convexity_sleeve.OTM_TARGET_PCT
SPREAD_SHORT_OTM_PCT = 20.0                 # convexity_sleeve.SPREAD_SHORT_OTM_PCT
TENOR_DAYS = 135                            # convexity_sleeve.TENOR_DAYS_TARGET
ROLL_AT_DAYS = 60                           # convexity_sleeve.ROLL_AT_DAYS
HARVEST_LADDER = [(3.0, 0.25), (5.0, 0.25), (10.0, 0.30)]   # multiple of cost, share of the original position
CONVEXITY_BY_QUARTILE = {1: 2.00, 2: 1.25, 3: 0.50, 4: 0.00}  # risk_budget.py, % of NAV per QUARTER
VIX_RANK_LOOKBACK = 252
OPTION_COST_PCT = 3.0                       # bid/ask + fees, % of premium, charged on every buy and sell
DAYS_PER_ROLL = TENOR_DAYS - ROLL_AT_DAYS   # 75 calendar days between purchases
SLEEVES = {
    "none": None,
    "C1":  {"label": "policy 1%/yr, 8% OTM puts", "mode": "fixed", "annual_pct": 1.0, "spread": False},
    "C1s": {"label": "policy 1%/yr, 8%/20% put spread", "mode": "fixed", "annual_pct": 1.0, "spread": True},
    "C2":  {"label": "designed: VIX-quartile schedule per quarter, 8% OTM puts", "mode": "quartile", "spread": False},
}
CONVEXITY_BREAKERS = ("B0", "B3")

STRESS = [
    ("dotcom_2000", "2000-03-24", "2002-10-09", "Dot-com bust"),
    ("gfc_2008",    "2007-10-09", "2009-03-09", "Global financial crisis"),
    ("covid_2020",  "2020-02-19", "2020-03-23", "Covid crash"),
    ("rates_2022",  "2022-01-03", "2022-10-12", "Rates shock (closest analogue: positive stock/bond correlation)"),
    ("carry_2024",  "2024-07-16", "2024-08-05", "Yen-carry unwind (liquidity flush)"),
]
FULL = ("full_2005", "2005-01-03", None, "Full history: the cost of each rule in normal markets")
ROUND_TRIP_SESSIONS = 252                  # round-trip window = peak to one year after the trough

# ── breaker release test (v1.1) ──
GROWTH = ("VGT", "SMH", "QQQ")             # sleeves that move with QQQ; every other risk sleeve is "core"
RELEASE_MA = 200
BREAKERS = ("B0", "B1", "B2", "B3", "B4")
BREAKER_RULES = {
    "B0": "Current: book back above −5% and SPY above its 50-day",
    "B1": "SPY above its 200-day",
    "B2": "SPY and QQQ both above their 200-days",
    "B3": "Tiered: growth sleeves (VGT, SMH, QQQ) return when QQQ is above its 200-day; every other risk sleeve when SPY is",
    "B4": "B3, and each sleeve gets its weight back only when its own price is above its 200-day (until then that half waits in SGOV)",
}
BREAKER_SHORT = {"B0": "current", "B1": "SPY 200-day", "B2": "SPY and QQQ 200-day",
                 "B3": "tiered by sleeve", "B4": "tiered + own trend"}
BREAKER_BAR_CAGR = 0.25                   # must add at least this many pts/yr over the full history ...
BREAKER_BAR_DD = 1.0                       # ... and never deepen max drawdown by more than this in any stress or round-trip window

VARIANTS = ("V0", "V1", "V2", "V3")
VARIANT_LABEL = {"V0": "current book", "V1": "corr-gated TLT", "V2": "hedge trend rule",
                 "V3": "V1 + V2", "SPY": "", "6040": "60/40"}


# ── prices ──────────────────────────────────────────────────────────────────

def all_tickers() -> list[str]:
    s = {t for chain in PROXIES.values() for t in chain} | {t for c in BENCH.values() for t in c} | {VIX_TICKER}
    return sorted(s)


def yf_fetch(tickers: list[str], start: str = HISTORY_START) -> dict:
    """{ticker: Close Series}, dividend-adjusted. Missing tickers are omitted
    (the coverage table shows the hole); one retry per missing ticker."""
    import yfinance as yf
    out: dict = {}

    def take(df, t):
        if df is None or df.empty:
            return
        if isinstance(df.columns, pd.MultiIndex):
            if t in df.columns.get_level_values(0):
                sub = df[t]
            elif t in df.columns.get_level_values(-1):
                sub = df.xs(t, axis=1, level=-1)
            else:
                return
        else:
            sub = df
        if "Close" in sub.columns:
            s = sub["Close"].dropna()
            if len(s):
                out[t] = s

    try:
        df = yf.download(tickers, start=start, auto_adjust=True, progress=False,
                         group_by="ticker", threads=True)
        for t in tickers:
            take(df, t)
    except Exception as e:
        print(f"[hedge_lab] batch download failed: {type(e).__name__}: {e}")
    for t in [t for t in tickers if t not in out]:
        try:
            take(yf.download(t, start=start, auto_adjust=True, progress=False), t)
        except Exception as e:
            print(f"[hedge_lab] {t}: {type(e).__name__}: {e}")
    return out


def _norm(s: pd.Series) -> pd.Series:
    s = pd.Series(s).astype(float).dropna()
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def ticker_returns(closes: dict, t: str, cal: pd.DatetimeIndex) -> pd.Series:
    """Daily return of one ticker on the trading calendar. ^IRX (a yield in %)
    becomes a cash return: yesterday's yield / 252. NaN where it has no data."""
    s = closes.get(t)
    if s is None or len(s) == 0:
        return pd.Series(np.nan, index=cal)
    s = _norm(s)
    first = s.index[0]
    lvl = s.reindex(cal).ffill(limit=3)
    if t == CASH_TICKER:
        r = lvl.shift(1) / 100.0 / 252.0
    else:
        r = lvl.pct_change(fill_method=None)
    r[cal <= first] = np.nan
    return r


def splice(closes: dict, chains: dict, cal: pd.DatetimeIndex) -> tuple:
    """(returns, source) DataFrames, one column per sleeve. source holds the
    ticker actually used each day ('' where none)."""
    rets, srcs = {}, {}
    for sleeve, chain in chains.items():
        r = pd.Series(np.nan, index=cal)
        src = pd.Series("", index=cal, dtype=object)
        for t in chain:
            rt = ticker_returns(closes, t, cal)
            fill = r.isna() & rt.notna()
            r[fill] = rt[fill]
            src[fill] = t
        rets[sleeve], srcs[sleeve] = r, src
    return pd.DataFrame(rets, index=cal), pd.DataFrame(srcs, index=cal)


def source_class(sleeve: str, t: str) -> str:
    if not t:
        return "none"
    if t == sleeve:
        return "native"
    if t == CASH_TICKER:
        return "cash"
    return "proxy"


# ── signals (value at d uses data up to and including d) ────────────────────

def signals(rets: pd.DataFrame, spy_ret: pd.Series) -> dict:
    lvl = (1 + rets.fillna(0.0)).cumprod()
    down = {}
    for h in HEDGES:
        ma = lvl[h].rolling(TREND_MA, min_periods=TREND_MA).mean()
        d = (lvl[h] < ma) & (ma < ma.shift(TREND_SLOPE_LAG))
        down[h] = d.fillna(False).astype(bool)
    corr = spy_ret.rolling(CORR_WINDOW, min_periods=CORR_WINDOW).corr(rets["TLT"])
    return {"down": down, "corr": corr, "corr_pos": (corr > 0).fillna(False).astype(bool)}


def apply_variant(base: dict, v: str, sig: dict, d) -> tuple:
    """(weights, list of rule notes) for variant v on day d. Weights sum is preserved."""
    w = {k: float(x) for k, x in base.items()}
    w.setdefault(PARK, 0.0)
    notes = []
    if v in ("V1", "V3") and bool(sig["corr_pos"].get(d, False)) and w.get("TLT", 0) > 0:
        w[PARK] += w["TLT"]
        notes.append(f"TLT→SGOV (corr {sig['corr'].get(d, float('nan')):+.2f})")
        w["TLT"] = 0.0
    if v in ("V2", "V3"):
        for h in HEDGES:
            if w.get(h, 0) > 0 and bool(sig["down"][h].get(d, False)):
                freed = w[h] * (1 - TREND_SCALE)
                w[h] -= freed
                w[PARK] += freed
                notes.append(f"{h} halved")
    return w, notes


# ── simulation (mirrors model_book.advance) ─────────────────────────────────

def simulate(days: pd.DatetimeIndex, rets: pd.DataFrame, weights_on: Callable,
             spy_close: Optional[pd.Series], breaker: bool = True,
             cost_bps: float = COST_BPS) -> pd.DataFrame:
    """weights_on(d) -> base weights held from d to the next day.
    NAV at d = NAV at d-1 x (1 + sum w_{d-1} r_d). Breaker state is set at d's
    close and applied to the weights held into d+1, as in the model book."""
    spy_closes = {"SPY": spy_close} if spy_close is not None else {}
    rows, prev = [], None
    for d in days:
        if prev is None:
            nav = gross = peak = mb.START_NAV
            state, rc, cov = "OFF", 0, 1.0
        else:
            r, have, tot = 0.0, 0.0, 0.0
            for t, wt in prev["w"].items():
                if wt <= 0:
                    continue
                tot += wt
                x = rets.at[d, t] if t in rets.columns else np.nan
                if x == x:
                    r += wt / 100.0 * float(x)
                    have += wt
            cov = have / tot if tot else 1.0
            nav = prev["nav"] * (1 + r)
            gross = prev["gross"] * (1 + r)
            peak = max(prev["peak"], nav)
            if breaker:
                state, rc = mb.next_breaker(prev["state"], prev["rc"], (nav / peak - 1) * 100,
                                            mb._spy_above_50(spy_closes, d) if spy_closes else None)
        base = weights_on(d)
        w = mb.apply_breaker(base, REGIME) if (breaker and state == "ON") else dict(base)
        w = {k: float(v) for k, v in w.items()}
        turn = 0.0
        if prev is not None:
            keys = set(w) | set(prev["w"])
            turn = sum(abs(w.get(k, 0.0) - prev["w"].get(k, 0.0)) for k in keys) / 2.0
            nav *= 1 - turn / 100.0 * cost_bps / 1e4
            peak = max(peak, nav)
        rows.append({"date": d, "nav": nav, "gross": gross, "peak": peak, "state": state, "rc": rc,
                     "w": w, "turnover": turn, "coverage": cov})
        prev = rows[-1]
    out = pd.DataFrame(rows).set_index("date")
    out["dd"] = (out["nav"] / out["peak"] - 1) * 100
    return out


# ── breaker release rules (v1.1) ────────────────────────────────────────────

def release_signals(closes: dict, cal: pd.DatetimeIndex, rets: pd.DataFrame) -> dict:
    """Trend states at each close (value at d uses data up to and including d):
    SPY and QQQ above their 200-day, and each sleeve's own (spliced) price above
    its 200-day. Missing data reads as NOT above, which keeps the breaker on."""
    def above(s):
        if s is None or len(s) == 0:
            return pd.Series(False, index=cal)
        x = _norm(s).reindex(cal).ffill(limit=3)
        ma = x.rolling(RELEASE_MA, min_periods=RELEASE_MA).mean()
        return (x > ma).fillna(False).astype(bool)
    lvl = (1 + rets.fillna(0.0)).cumprod()
    own = {}
    for s in rets.columns:
        ma = lvl[s].rolling(RELEASE_MA, min_periods=RELEASE_MA).mean()
        own[s] = ((lvl[s] > ma) & rets[s].notna()).fillna(False).astype(bool)
    return {"spy200": above(closes.get("SPY")), "qqq200": above(closes.get("QQQ")), "above200": own}


def _release_ok(rule: str, group: str, d, sig: dict) -> bool:
    spy = bool(sig["spy200"].get(d, False))
    qqq = bool(sig["qqq200"].get(d, False))
    if rule == "B1":
        return spy
    if rule == "B2":
        return spy and qqq
    return qqq if group == "growth" else spy          # B3, B4


def simulate_release(days: pd.DatetimeIndex, rets: pd.DataFrame, base: dict, rule: str,
                     sig: dict, cost_bps: float = COST_BPS) -> pd.DataFrame:
    """Same NAV accounting and −8% trip as simulate(), with release rule B1-B4.
    Groups: 'growth' (GROWTH) and 'core' (every other non-exempt sleeve). The
    trip halves both groups. Each group releases after RELEASE_CLOSES
    consecutive closes of its condition. When no group is on, the drawdown
    reference resets to the NAV at that close, so the next trip is measured
    from the release point. B4 also holds each released sleeve at half until
    its own price closes above its 200-day."""
    group = {s: ("growth" if s in GROWTH else "core") for s in base}
    risk = {s for s, w in base.items() if w > 0 and s not in mb.RISK_EXEMPT}
    on = {"growth": False, "core": False}
    rc = {"growth": 0, "core": 0}
    pending: set = set()
    rows, prev, ref_peak, trips = [], None, mb.START_NAV, 0
    for d in days:
        if prev is None:
            nav = gross = mb.START_NAV
            cov = 1.0
        else:
            r, have, tot = 0.0, 0.0, 0.0
            for t, wt in prev["w"].items():
                if wt <= 0:
                    continue
                tot += wt
                x = rets.at[d, t] if t in rets.columns else np.nan
                if x == x:
                    r += wt / 100.0 * float(x)
                    have += wt
            cov = have / tot if tot else 1.0
            nav = prev["nav"] * (1 + r)
            gross = prev["gross"] * (1 + r)
        ref_peak = max(ref_peak, nav)
        dd_ref = (nav / ref_peak - 1) * 100
        if prev is not None:
            if not any(on.values()):
                if dd_ref <= mb.TRIGGER_DD:
                    on = {"growth": True, "core": True}
                    rc = {"growth": 0, "core": 0}
                    pending = set()
                    trips += 1
            else:
                for g in ("growth", "core"):
                    if not on[g]:
                        continue
                    rc[g] = rc[g] + 1 if _release_ok(rule, g, d, sig) else 0
                    if rc[g] >= mb.RELEASE_CLOSES:
                        on[g], rc[g] = False, 0
                        if rule == "B4":
                            pending |= {s for s in risk if group[s] == g}
                if not any(on.values()):
                    ref_peak = nav                      # the next trip is measured from here
        if rule == "B4" and pending:
            pending = {s for s in pending if not bool(sig["above200"].get(s, pd.Series(dtype=bool)).get(d, False))}
        w, freed = {}, 0.0
        for s, wt in base.items():
            wt = float(wt)
            half = s in risk and (on[group[s]] or s in pending)
            w[s] = wt * mb.BREAKER_SCALE if half else wt
            freed += wt - w[s]
        w[PARK] = w.get(PARK, 0.0) + freed
        turn = 0.0
        if prev is not None:
            keys = set(w) | set(prev["w"])
            turn = sum(abs(w.get(k, 0.0) - prev["w"].get(k, 0.0)) for k in keys) / 2.0
            nav *= 1 - turn / 100.0 * cost_bps / 1e4
        rows.append({"date": d, "nav": nav, "gross": gross, "w": w, "turnover": turn, "coverage": cov,
                     "state": "ON" if any(on.values()) else "OFF", "pending": len(pending),
                     "growth_on": on["growth"], "core_on": on["core"], "trips": trips})
        prev = rows[-1]
    return pd.DataFrame(rows).set_index("date")


def run_breaker_window(key, start, end, label, base, rets, srcs, sig, spy_close):
    cal = rets.index
    days = cal[(cal >= pd.Timestamp(start)) & (cal <= (pd.Timestamp(end) if end else cal[-1]))]
    if len(days) < 2:
        return [], {"key": key, "label": label, "error": "no sessions in range"}
    cov, _ = coverage_for(days, base, srcs)
    rows = []
    for b in BREAKERS:
        if b == "B0":
            sim = simulate(days, rets, lambda d: dict(base), spy_close)
            on = sim["state"] == "ON"
            trips = int((on & ~on.shift(1, fill_value=False)).sum())
            pend = 0
        else:
            sim = simulate_release(days, rets, base, b, sig)
            on = sim["state"] == "ON"
            trips = int(sim["trips"].iloc[-1])
            pend = int((sim["pending"] > 0).sum())
        m = metrics(sim["nav"], sim["turnover"])
        m.update({"window": key, "breaker": b, "breaker_days": int(on.sum()),
                  "breaker_on_pct": round(float(on.mean() * 100), 1), "trips": trips, "gated_days": pend,
                  "start": days[0].date().isoformat(), "end": days[-1].date().isoformat()})
        rows.append(m)
    return rows, {"key": key, "label": label, "start": days[0].date().isoformat(),
                  "end": days[-1].date().isoformat(), "coverage": cov,
                  "low_coverage": cov["none"] > LOW_COVERAGE_PCT}


def round_trips(cal: pd.DatetimeIndex) -> list:
    out = []
    for key, s, e, label in STRESS:
        later = cal[cal >= pd.Timestamp(e)]
        if not len(later):
            continue
        i = cal.get_loc(later[0])
        end = cal[min(i + ROUND_TRIP_SESSIONS, len(cal) - 1)]
        out.append((f"{key}_rt", s, end.date().isoformat(), f"{label}: peak to one year after the trough"))
    return out


def breaker_verdicts(bres: pd.DataFrame, binfos: list) -> list[str]:
    keys = [i["key"] for i in binfos
            if i["key"] != FULL[0] and not i.get("low_coverage") and not i.get("error")]

    def val(w, b, col):
        x = bres[(bres["window"] == w) & (bres["breaker"] == b)][col]
        return float(x.iloc[0]) if len(x) and x.iloc[0] == x.iloc[0] else None

    out = []
    c0 = val(FULL[0], "B0", "cagr_pct")
    t0, p0 = val(FULL[0], "B0", "trips"), val(FULL[0], "B0", "breaker_on_pct")
    for b in BREAKERS[1:]:
        cb = val(FULL[0], b, "cagr_pct")
        deeper = []
        for w in keys:
            a, z = val(w, b, "max_dd_pct"), val(w, "B0", "max_dd_pct")
            if a is not None and z is not None:
                deeper.append((z - a, w))       # positive = deeper than B0
        worst = max(deeper) if deeper else (0.0, "")
        gain = (cb - c0) if (cb is not None and c0 is not None) else None
        earns = gain is not None and gain >= BREAKER_BAR_CAGR and worst[0] <= BREAKER_BAR_DD
        parts = [f"**{b} ({BREAKER_SHORT[b]})**:"]
        if gain is not None:
            parts.append(f"full history {abs(gain):.2f} pts/yr {'more' if gain >= 0 else 'less'} return than B0")
        if deeper:
            if worst[0] > 0:
                parts.append(f"· worst window {worst[0]:.1f} pts deeper drawdown than B0 ({worst[1]})")
            else:
                parts.append(f"· never deeper drawdown than B0 across {len(deeper)} windows")
        tb, pb = val(FULL[0], b, "trips"), val(FULL[0], b, "breaker_on_pct")
        if tb is not None and t0 is not None:
            parts.append(f"· trips {int(tb)} (B0 {int(t0)}) · breaker on {pb:.0f}% of sessions (B0 {p0:.0f}%)")
        parts.append(f"→ **{'EARNS A PLACE' if earns else 'does not meet the bar'}**")
        out.append(" ".join(parts) + ".")
    out.append(f"The bar, fixed before the run: at least +{BREAKER_BAR_CAGR:.2f} pts/yr over the full history "
               f"AND no stress or round-trip window more than {BREAKER_BAR_DD:.0f} pt deeper than B0. "
               "Five rules were set in advance; tuning thresholds until one passes would fit the past, not the future.")
    return out


def render_breakers(bres: pd.DataFrame, binfos: list) -> list[str]:
    L = ["## Breaker release test (v1.1)",
         "All rules trip the same way (book down 8% → every risk sleeve halved, freed weight to SGOV; "
         "SGOV, USFR, KMLM exempt). They differ only in how the book gets its risk back. "
         "B1–B4 measure the next trip from the release point.", "",
         "| Rule | Release (2 consecutive closes) |", "|---|---|",
         *[f"| {b} | {BREAKER_RULES[b]} |" for b in BREAKERS], "",
         "### Verdict", *[f"- {x}" for x in breaker_verdicts(bres, binfos)], ""]
    order = [FULL[0]] + [k for k, *_ in round_trips_keys(binfos)] + [s[0] for s in STRESS]
    for key in order:
        info = next((i for i in binfos if i["key"] == key), None)
        if not info:
            continue
        L.append(f"### {info.get('label', key)} ({info.get('start', '?')} → {info.get('end', '?')})")
        if info.get("error"):
            L += [f"- ⚠ {info['error']}", ""]
            continue
        if info.get("low_coverage"):
            L.append("⚠ **LOW COVERAGE** — excluded from the verdict")
        L += ["| Rule | Return | CAGR | Max DD | Worst 20d | Breaker on | Trips | Waiting on own trend (days) | Cost |",
              "|---|---|---|---|---|---|---|---|---|"]
        for _, r in bres[bres["window"] == key].iterrows():
            L.append(f"| {r['breaker']} | {_f(r.get('total_return_pct'))} | {_f(r.get('cagr_pct'))} | "
                     f"{_f(r.get('max_dd_pct'))} | {_f(r.get('worst_20d_pct'))} | {_f(r.get('breaker_on_pct'), 0)} | "
                     f"{int(r['trips'])} | {int(r['gated_days'])} | {_f(r.get('cost_pct'), 2)} |")
        L.append("")
    return L


def round_trips_keys(binfos: list) -> list:
    return [(i["key"],) for i in binfos if i["key"].endswith("_rt")]


# ── convexity sleeve (v1.2) ─────────────────────────────────────────────────

def bs_put(spot: float, strike: float, iv: float, days: float, r: float = 0.04) -> Optional[float]:
    """Copy of Markets convexity_sleeve._bs_put_approx (v1): Black-Scholes put
    with a crude skew markup (+1 vol point per 1% out of the money, capped at
    12) so the estimate errs toward too expensive. At or past expiry returns
    intrinsic value."""
    try:
        if spot <= 0 or strike <= 0:
            return None
        if days <= 0:
            return max(strike - spot, 0.0)
        if iv <= 0:
            return None
        t = days / 365.0
        sigma = iv / 100.0
        otm_pct = max(0.0, (spot - strike) / spot * 100)
        sigma = sigma + min(otm_pct * 1.0, 12.0) / 100.0
        d1 = (math.log(spot / strike) + (r + sigma ** 2 / 2) * t) / (sigma * math.sqrt(t))
        d2 = d1 - sigma * math.sqrt(t)
        ncdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
        return strike * math.exp(-r * t) * ncdf(-d2) - spot * ncdf(-d1)
    except Exception:
        return None


def sleeve_market(closes: dict, cal: pd.DatetimeIndex) -> dict:
    """SPY level, VIX, a cash rate and VIX's percentile rank in its own trailing
    year, each on the trading calendar (value at d uses data up to d)."""
    def on_cal(t):
        s = closes.get(t)
        if s is None or len(s) == 0:
            return pd.Series(np.nan, index=cal)
        return _norm(s).reindex(cal).ffill(limit=3)
    vix = on_cal(VIX_TICKER)
    rank = vix.rolling(VIX_RANK_LOOKBACK, min_periods=60).apply(
        lambda h: float((h <= h[-1]).mean()) * 100.0, raw=True)
    irx = on_cal(CASH_TICKER)
    return {"spy": on_cal("SPY"), "vix": vix, "vix_rank": rank, "rate": (irx / 100.0).fillna(0.04)}


def _quartile(rank: float) -> Optional[int]:
    if rank != rank:
        return None
    return 1 if rank < 25 else 2 if rank < 50 else 3 if rank < 75 else 4


def roll_budget_pct(cfg: dict, d, mkt: dict) -> float:
    """% of NAV to spend at one purchase. Fixed mode spreads the annual budget
    over purchases DAYS_PER_ROLL apart; quartile mode applies risk_budget's
    per-quarter schedule pro rata (unranked VIX falls back to Q2, as there)."""
    frac = DAYS_PER_ROLL / 365.0
    if cfg["mode"] == "fixed":
        return cfg["annual_pct"] * frac
    q = _quartile(float(mkt["vix_rank"].get(d, np.nan))) or 2
    return CONVEXITY_BY_QUARTILE[q] * DAYS_PER_ROLL / (365.0 / 4)


def unit_value(tr: dict, d, mkt: dict) -> float:
    """Model mark of one unit of the tranche at d's close."""
    s, v, r = float(mkt["spy"].get(d, np.nan)), float(mkt["vix"].get(d, np.nan)), float(mkt["rate"].get(d, 0.04))
    if s != s:
        return tr["last_value"]
    if v != v:
        v = tr["last_iv"]
    left = (tr["expiry"] - d).days
    p = bs_put(s, tr["k1"], v, left, r) or 0.0
    if tr.get("k2"):
        p -= bs_put(s, tr["k2"], v, left, r) or 0.0
        p = min(max(p, 0.0), tr["k1"] - tr["k2"])
    tr["last_value"], tr["last_iv"] = p, v
    return p


def simulate_book(days: pd.DatetimeIndex, rets: pd.DataFrame, base: dict, rule: str, sig: dict,
                  mkt: Optional[dict] = None, sleeve: Optional[dict] = None,
                  spy_close: Optional[pd.Series] = None, cost_bps: float = COST_BPS) -> pd.DataFrame:
    """The book (core sleeves, daily rebalanced) plus an optional convexity
    sleeve, under breaker rule B0 (production) or B1-B4. With sleeve=None this
    reproduces simulate() for B0 and simulate_release() for B1-B4 exactly
    (asserted in the selftest). The breaker sees the TOTAL book (core +
    options), as the model book measures drawdown on what is actually held.
    Option trades happen at d's close: premium comes out of the core, harvest
    and roll proceeds go back into it and are rebalanced to target weights."""
    spy_closes = {"SPY": spy_close} if spy_close is not None else {}
    group = {s: ("growth" if s in GROWTH else "core") for s in base}
    risk = {s for s, w in base.items() if w > 0 and s not in mb.RISK_EXEMPT}
    on = {"growth": False, "core": False}
    rc_g = {"growth": 0, "core": 0}
    pending: set = set()
    state, rc = "OFF", 0
    rows, prev, peak, ref_peak, trips = [], None, mb.START_NAV, mb.START_NAV, 0
    core = gross = mb.START_NAV
    tr = None
    paid = harvested = 0.0
    n_harvest = n_buys = 0
    oc = OPTION_COST_PCT / 100.0
    for d in days:
        sval = 0.0
        if prev is not None:
            r = 0.0
            for t, wt in prev["w"].items():
                if wt <= 0:
                    continue
                x = rets.at[d, t] if t in rets.columns else np.nan
                if x == x:
                    r += wt / 100.0 * float(x)
            core = core * (1 + r)
            gross = gross * (1 + r)
            if tr is not None:
                sval = tr["units"] * unit_value(tr, d, mkt)
        total = core + sval
        # ── breaker state at d's close (on the total book) ──
        if rule == "B0":
            if prev is not None:
                peak = max(peak, total)
                state, rc = mb.next_breaker(state, rc, (total / peak - 1) * 100,
                                            mb._spy_above_50(spy_closes, d) if spy_closes else None)
        else:
            ref_peak = max(ref_peak, total)
            dd_ref = (total / ref_peak - 1) * 100
            if prev is not None:
                if not any(on.values()):
                    if dd_ref <= mb.TRIGGER_DD:
                        on = {"growth": True, "core": True}
                        rc_g = {"growth": 0, "core": 0}
                        pending = set()
                        trips += 1
                else:
                    for g in ("growth", "core"):
                        if not on[g]:
                            continue
                        rc_g[g] = rc_g[g] + 1 if _release_ok(rule, g, d, sig) else 0
                        if rc_g[g] >= mb.RELEASE_CLOSES:
                            on[g], rc_g[g] = False, 0
                            if rule == "B4":
                                pending |= {s for s in risk if group[s] == g}
                    if not any(on.values()):
                        ref_peak = total
            if rule == "B4" and pending:
                pending = {s for s in pending
                           if not bool(sig["above200"].get(s, pd.Series(dtype=bool)).get(d, False))}
            state = "ON" if any(on.values()) else "OFF"
        # ── convexity sleeve trades at d's close ──
        if sleeve is not None:
            if tr is not None:
                vpu = tr["last_value"] if prev is not None else unit_value(tr, d, mkt)
                for i, (mult, share) in enumerate(HARVEST_LADDER):
                    if i not in tr["done"] and vpu >= mult * tr["cost"] and tr["units"] > 0:
                        sell = min(tr["units0"] * share, tr["units"])
                        core += sell * vpu * (1 - oc)
                        harvested += sell * vpu * (1 - oc)
                        tr["units"] -= sell
                        tr["done"].add(i)
                        n_harvest += 1
                if (tr["expiry"] - d).days <= ROLL_AT_DAYS:
                    core += tr["units"] * vpu * (1 - oc)
                    harvested += tr["units"] * vpu * (1 - oc)
                    tr = None
            if tr is None:
                s_now, v_now = float(mkt["spy"].get(d, np.nan)), float(mkt["vix"].get(d, np.nan))
                budget = (core) * roll_budget_pct(sleeve, d, mkt) / 100.0
                if budget > 0 and s_now == s_now and v_now == v_now:
                    k1 = s_now * (1 - OTM_PCT / 100.0)
                    k2 = s_now * (1 - SPREAD_SHORT_OTM_PCT / 100.0) if sleeve.get("spread") else None
                    tr = {"k1": k1, "k2": k2, "expiry": d + pd.Timedelta(days=TENOR_DAYS),
                          "last_value": 0.0, "last_iv": v_now, "done": set()}
                    price = unit_value(tr, d, mkt)
                    if price > 0:
                        cost = price * (1 + oc)
                        tr.update(units=budget / cost, units0=budget / cost, cost=cost)
                        core -= budget
                        paid += budget
                        n_buys += 1
                    else:
                        tr = None
            sval = tr["units"] * tr["last_value"] if tr is not None else 0.0
        # ── core weights held into d+1 ──
        b = dict(base)
        if rule == "B0":
            w = mb.apply_breaker(b, REGIME) if state == "ON" else b
            w = {k: float(v) for k, v in w.items()}
        else:
            w, freed = {}, 0.0
            for s, wt in b.items():
                wt = float(wt)
                half = s in risk and (on[group[s]] or s in pending)
                w[s] = wt * mb.BREAKER_SCALE if half else wt
                freed += wt - w[s]
            w[PARK] = w.get(PARK, 0.0) + freed
        turn = 0.0
        if prev is not None:
            keys = set(w) | set(prev["w"])
            turn = sum(abs(w.get(k, 0.0) - prev["w"].get(k, 0.0)) for k in keys) / 2.0
            core *= 1 - turn / 100.0 * cost_bps / 1e4
        total = core + sval
        if rule == "B0":
            peak = max(peak, total)
        rows.append({"date": d, "nav": total, "core": core, "sleeve": sval, "gross": gross, "w": w,
                     "turnover": turn, "state": state, "pending": len(pending), "trips": trips,
                     "paid": paid, "harvested": harvested, "n_harvest": n_harvest, "n_buys": n_buys})
        prev = rows[-1]
    out = pd.DataFrame(rows).set_index("date")
    if rule == "B0":
        on_ = out["state"] == "ON"
        out["trips"] = (on_ & ~on_.shift(1, fill_value=False)).cumsum()
    return out


def run_convexity_window(key, start, end, label, base, rets, sig, mkt, spy_close):
    cal = rets.index
    days = cal[(cal >= pd.Timestamp(start)) & (cal <= (pd.Timestamp(end) if end else cal[-1]))]
    if len(days) < 2:
        return [], {"key": key, "label": label, "error": "no sessions in range"}
    rows = []
    yrs = max((days[-1] - days[0]).days / 365.25, 1e-9)
    for b in CONVEXITY_BREAKERS:
        for c, cfg in SLEEVES.items():
            sim = simulate_book(days, rets, base, b, sig, mkt, cfg, spy_close)
            m = metrics(sim["nav"], sim["turnover"])
            avg_nav = float(sim["nav"].mean())
            m.update({"window": key, "breaker": b, "sleeve": c,
                      "breaker_on_pct": round(float((sim["state"] == "ON").mean() * 100), 1),
                      "trips": int(sim["trips"].iloc[-1]),
                      "premium_pct_yr": float(sim["paid"].iloc[-1] / avg_nav * 100 / yrs) if cfg else 0.0,
                      "premium_total_pct": float(sim["paid"].iloc[-1] / mb.START_NAV * 100) if cfg else 0.0,
                      "returned_total_pct": float(sim["harvested"].iloc[-1] / mb.START_NAV * 100) if cfg else 0.0,
                      "harvests": int(sim["n_harvest"].iloc[-1]),
                      "start": days[0].date().isoformat(), "end": days[-1].date().isoformat()})
            rows.append(m)
    vix_ok = float(mkt["vix"].reindex(days).notna().mean() * 100)
    return rows, {"key": key, "label": label, "start": days[0].date().isoformat(),
                  "end": days[-1].date().isoformat(), "vix_coverage_pct": round(vix_ok, 1)}


def convexity_verdicts(cres: pd.DataFrame, cinfos: list, binfos: list) -> list[str]:
    low = {i["key"] for i in binfos if i.get("low_coverage")}
    keys = [i["key"] for i in cinfos if i["key"] != FULL[0] and i["key"] not in low and not i.get("error")]

    def val(w, b, c, col):
        x = cres[(cres["window"] == w) & (cres["breaker"] == b) & (cres["sleeve"] == c)][col]
        return float(x.iloc[0]) if len(x) and x.iloc[0] == x.iloc[0] else None

    out = []
    c0 = val(FULL[0], "B0", "none", "cagr_pct")
    for b in CONVEXITY_BREAKERS:
        for c in SLEEVES:
            if b == "B0" and c == "none":
                continue
            cb = val(FULL[0], b, c, "cagr_pct")
            deeper = [(val(w, "B0", "none", "max_dd_pct") - val(w, b, c, "max_dd_pct"), w) for w in keys
                      if val(w, b, c, "max_dd_pct") is not None and val(w, "B0", "none", "max_dd_pct") is not None]
            worst = max(deeper) if deeper else (0.0, "")
            gain = (cb - c0) if (cb is not None and c0 is not None) else None
            earns = gain is not None and gain >= BREAKER_BAR_CAGR and worst[0] <= BREAKER_BAR_DD
            prem = val(FULL[0], b, c, "premium_pct_yr")
            parts = [f"**{b} + {c}** ({BREAKER_SHORT[b]}{'' if c == 'none' else ', ' + SLEEVES[c]['label']}):",
                     f"full history {abs(gain):.2f} pts/yr {'more' if gain >= 0 else 'less'} return than B0 alone"
                     if gain is not None else ""]
            if prem:
                parts.append(f"(premium {prem:.2f}% of NAV/yr)")
            if deeper:
                parts.append(f"· worst window {worst[0]:.1f} pts deeper than B0 alone ({worst[1]})" if worst[0] > 0
                             else f"· never deeper than B0 alone across {len(deeper)} windows")
            parts.append(f"→ **{'EARNS A PLACE' if earns else 'does not meet the bar'}**")
            out.append(" ".join(p for p in parts if p) + ".")
    # the specific question: does a sleeve close B3's dot-com gap?
    g = []
    for c in SLEEVES:
        a, z = val("dotcom_2000_rt", "B3", c, "max_dd_pct"), val("dotcom_2000_rt", "B0", "none", "max_dd_pct")
        if a is not None and z is not None:
            g.append(f"{c} {a:.1f}%")
    if g:
        out.append(f"Dot-com round trip, B3 max drawdown by sleeve: {' · '.join(g)} "
                   f"(B0 alone {val('dotcom_2000_rt', 'B0', 'none', 'max_dd_pct'):.1f}%).")
    out.append(f"Same bar as the breaker test, fixed before the run, measured against B0 with no sleeve: "
               f"at least +{BREAKER_BAR_CAGR:.2f} pts/yr over the full history AND no stress or round-trip "
               f"window more than {BREAKER_BAR_DD:.0f} pt deeper.")
    return out


def render_convexity(cres: pd.DataFrame, cinfos: list, binfos: list) -> list[str]:
    L = ["## Convexity sleeve test (v1.2)",
         f"Puts on SPY, {OTM_PCT:.0f}% out of the money, {TENOR_DAYS} days to expiry, rolled at {ROLL_AT_DAYS} days left "
         f"(a purchase every {DAYS_PER_ROLL} days), sold 25% / 25% / 30% at 3× / 5× / 10× cost, the rest held to the roll. "
         f"Premium comes out of the book; proceeds go back in at target weights. {OPTION_COST_PCT:.0f}% trading cost "
         "on every option buy and sell. **Every option value is a model mark** (convexity_sleeve's Black-Scholes "
         "with VIX and its skew markup); there is no free historical option chain to check it against.", "",
         "| Sleeve | Budget and structure |", "|---|---|",
         "| none | No options |",
         *[f"| {c} | {cfg['label']} |" for c, cfg in SLEEVES.items() if cfg], "",
         "The policy (`risk_policy.md`, PROPOSED) caps premium at 1% of NAV per year; the built module "
         "(`risk_budget.py`) spends up to 2% per quarter. Both are tested because they disagree.", "",
         "### Verdict", *[f"- {x}" for x in convexity_verdicts(cres, cinfos, binfos)], ""]
    order = [FULL[0]] + [k for (k,) in round_trips_keys(cinfos)] + [s[0] for s in STRESS]
    for key in order:
        info = next((i for i in cinfos if i["key"] == key), None)
        if not info:
            continue
        L.append(f"### {info.get('label', key)} ({info.get('start', '?')} → {info.get('end', '?')})")
        if info.get("error"):
            L += [f"- ⚠ {info['error']}", ""]
            continue
        if info.get("vix_coverage_pct", 100) < 99:
            L.append(f"⚠ VIX available on {info['vix_coverage_pct']}% of sessions")
        L += ["| Breaker + sleeve | Return | CAGR | Max DD | Worst 20d | Premium/yr | Paid | Returned | Harvests | Breaker on |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in cres[cres["window"] == key].iterrows():
            L.append(f"| {r['breaker']} + {r['sleeve']} | {_f(r.get('total_return_pct'))} | {_f(r.get('cagr_pct'))} | "
                     f"{_f(r.get('max_dd_pct'))} | {_f(r.get('worst_20d_pct'))} | {_f(r.get('premium_pct_yr'), 2)} | "
                     f"{_f(r.get('premium_total_pct'), 1)} | {_f(r.get('returned_total_pct'), 1)} | "
                     f"{int(r['harvests'])} | {_f(r.get('breaker_on_pct'), 0)} |")
        L.append("")
    return L


def bench_nav(days: pd.DatetimeIndex, rets: pd.DataFrame, mix: dict) -> pd.Series:
    r = sum(rets[t].reindex(days).fillna(0.0) * (w / 100.0) for t, w in mix.items())
    r.iloc[0] = 0.0
    return mb.START_NAV * (1 + r).cumprod()


def metrics(nav: pd.Series, turnover: Optional[pd.Series] = None) -> dict:
    nav = nav.dropna()
    if len(nav) < 2:
        return {}
    r = nav.pct_change().dropna()
    dd = (nav / nav.cummax() - 1) * 100
    yrs = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    tot = (nav.iloc[-1] / nav.iloc[0] - 1) * 100
    m = {"total_return_pct": tot,
         "cagr_pct": ((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1) * 100 if yrs >= 1 else np.nan,
         "max_dd_pct": float(dd.min()),
         "worst_day_pct": float(r.min() * 100),
         "worst_20d_pct": float(((nav / nav.shift(20) - 1) * 100).min()) if len(nav) > 20 else np.nan,
         "vol_ann_pct": float(r.std() * math.sqrt(252) * 100),
         "sessions": len(nav)}
    if turnover is not None:
        t = turnover.reindex(nav.index).fillna(0.0)
        m["switch_days"] = int((t > 1e-9).sum())
        m["turnover_pct"] = float(t.sum())
        m["cost_pct"] = float(t.sum() / 100.0 * COST_BPS / 1e4 * 100)
    return m


# ── windows ─────────────────────────────────────────────────────────────────

def coverage_for(days, base: dict, srcs: pd.DataFrame) -> tuple:
    """(summary {class: % of book}, per-sleeve rows) over the window, weighted by base weight."""
    tot = sum(v for v in base.values() if v > 0)
    acc = {"native": 0.0, "proxy": 0.0, "cash": 0.0, "none": 0.0}
    per = []
    for s, wt in base.items():
        if wt <= 0 or s not in srcs.columns:
            continue
        col = srcs.loc[days, s]
        cls = col.map(lambda t: source_class(s, t))
        shares = cls.value_counts(normalize=True).to_dict()
        for k in acc:
            acc[k] += wt / tot * 100 * shares.get(k, 0.0)
        used = [t for t in dict.fromkeys(col.tolist()) if t]
        per.append({"sleeve": s, "weight": wt, "sources": " → ".join(used) or "none",
                    "native_pct": round(shares.get("native", 0) * 100, 1),
                    "proxy_pct": round(shares.get("proxy", 0) * 100, 1),
                    "cash_pct": round(shares.get("cash", 0) * 100, 1),
                    "none_pct": round(shares.get("none", 0) * 100, 1)})
    return {k: round(v, 1) for k, v in acc.items()}, per


def run_window(key, start, end, label, base, rets, srcs, sig, spy_close, bench_rets):
    cal = rets.index
    days = cal[(cal >= pd.Timestamp(start)) & (cal <= (pd.Timestamp(end) if end else cal[-1]))]
    if len(days) < 2:
        return [], [], {"key": key, "label": label, "error": "no sessions in range"}
    cov, per = coverage_for(days, base, srcs)
    rows = []
    for v in VARIANTS:
        sim = simulate(days, rets, lambda d, v=v: apply_variant(base, v, sig, d)[0], spy_close)
        m = metrics(sim["nav"], sim["turnover"])
        m.update({"window": key, "variant": v, "breaker_days": int((sim["state"] == "ON").sum()),
                  "gross_return_pct": (sim["gross"].iloc[-1] / sim["gross"].iloc[0] - 1) * 100})
        rows.append(m)
    for name, mix in (("SPY", {"SPY": 100}), ("6040", {"SPY": 60, "AGG": 40})):
        m = metrics(bench_nav(days, bench_rets, mix))
        m.update({"window": key, "variant": name})
        rows.append(m)
    for r in rows:
        r.update({"start": days[0].date().isoformat(), "end": days[-1].date().isoformat()})
    info = {"key": key, "label": label, "start": days[0].date().isoformat(),
            "end": days[-1].date().isoformat(), "coverage": cov,
            "low_coverage": cov["none"] > LOW_COVERAGE_PCT}
    return rows, [dict(window=key, **p) for p in per], info


def run_inception(book_path: Path, rets, sig, bench_rets) -> tuple:
    """Each rule applied on top of the model book's own stored weights. V0 must
    reproduce the recorded NAV (no breaker re-simulation: stored weights
    already include it)."""
    if not book_path.exists():
        return [], {"key": "inception", "error": f"{book_path} not found"}
    book = pd.read_csv(book_path)
    book["date"] = pd.to_datetime(book["date"]).dt.normalize()
    book = book.dropna(subset=["weights"]).sort_values("date")
    wmap = {d: json.loads(w) for d, w in zip(book["date"], book["weights"])}
    days = pd.DatetimeIndex([d for d in book["date"] if d in rets.index])
    if len(days) < 2:
        return [], {"key": "inception", "error": "model book dates not in the price calendar"}
    rows, v0nav = [], None
    for v in VARIANTS:
        # gross of costs for every variant, matching how the model book is recorded
        sim = simulate(days, rets, lambda d, v=v: apply_variant(wmap[d], v, sig, d)[0], None,
                       breaker=False, cost_bps=0.0)
        if v == "V0":
            v0nav = sim["nav"]
        m = metrics(sim["nav"], sim["turnover"])
        m.update({"window": "inception", "variant": v})
        rows.append(m)
    for name, mix in (("SPY", {"SPY": 100}), ("6040", {"SPY": 60, "AGG": 40})):
        m = metrics(bench_nav(days, bench_rets, mix))
        m.update({"window": "inception", "variant": name})
        rows.append(m)
    rec = book.set_index("date")["nav"].reindex(days).astype(float)
    rec = rec / rec.iloc[0] * mb.START_NAV
    diff = float((v0nav - rec).abs().max())
    for r in rows:
        r.update({"start": days[0].date().isoformat(), "end": days[-1].date().isoformat()})
    return rows, {"key": "inception", "label": "Model book since inception (stored weights, before costs)",
                  "start": days[0].date().isoformat(), "end": days[-1].date().isoformat(),
                  "replay_max_diff": round(diff, 4), "replay_ok": diff <= REPLAY_TOLERANCE,
                  "recorded_last": round(float(book["nav"].iloc[-1]), 4),
                  "replayed_last": round(float(v0nav.iloc[-1] / mb.START_NAV * book["nav"].iloc[0]), 4)}


# ── verdicts (rules applied to the numbers; no free text) ───────────────────

def verdicts(res: pd.DataFrame, infos: list) -> list[str]:
    ok_stress = [i["key"] for i in infos
                 if i["key"] in {s[0] for s in STRESS} and not i.get("low_coverage") and not i.get("error")]
    out = []

    def val(w, v, col):
        x = res[(res["window"] == w) & (res["variant"] == v)][col]
        return float(x.iloc[0]) if len(x) and x.iloc[0] == x.iloc[0] else None

    for v in ("V1", "V2", "V3"):
        better, deltas = 0, []
        for w in ok_stress:
            a, b = val(w, v, "max_dd_pct"), val(w, "V0", "max_dd_pct")
            if a is None or b is None:
                continue
            deltas.append(a - b)          # positive = shallower drawdown than V0
            better += (a - b) >= 1.0
        fc, f0 = val(FULL[0], v, "cagr_pct"), val(FULL[0], "V0", "cagr_pct")
        fd, f0d = val(FULL[0], v, "max_dd_pct"), val(FULL[0], "V0", "max_dd_pct")
        sw = val(FULL[0], v, "switch_days")
        def depth(x):
            return f"{abs(x):.1f} pts {'shallower' if x >= 0 else 'deeper'}"
        parts = [f"**{v} ({VARIANT_LABEL[v]})**: max drawdown at least 1 pt shallower than V0 in "
                 f"{better} of {len(deltas)} stress windows"]
        if deltas:
            parts.append(f"(on average {depth(float(np.mean(deltas)))})")
        if fc is not None and f0 is not None:
            parts.append(f"· full history: {abs(fc - f0):.2f} pts/yr {'more' if fc >= f0 else 'less'} return after costs")
        if fd is not None and f0d is not None:
            parts.append(f"with a max drawdown {depth(fd - f0d)}")
        if sw is not None:
            parts.append(f"· {int(sw)} weight-change days")
        out.append(" ".join(parts) + ".")
    excluded = [i["key"] for i in infos if i.get("low_coverage")]
    if excluded:
        out.append(f"Excluded from the counts for LOW COVERAGE (> {LOW_COVERAGE_PCT:.0f}% of the book "
                   f"with no data): {', '.join(excluded)}.")
    out.append("Rule for reading this: a hedge rule earns a place only if it cuts drawdown in most "
               "stress windows AND costs little over the full history. One without the other is a trade-off "
               "for Matt to choose, not an improvement.")
    return out


# ── report ──────────────────────────────────────────────────────────────────

def _f(x, nd=1, pct=True, sign=False):
    if x is None or (isinstance(x, float) and x != x):
        return "n/a"
    s = f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"
    return s + ("%" if pct else "")


def render(res: pd.DataFrame, infos: list, base: dict, inc: dict, missing: list, asof: str,
           bres: Optional[pd.DataFrame] = None, binfos: Optional[list] = None,
           cres: Optional[pd.DataFrame] = None, cinfos: Optional[list] = None) -> str:
    L = [f"# Hedge lab — {asof}",
         f"*{VERSION} · real prices (dividend-adjusted, Yahoo) · book = `{REGIME}` targets from "
         f"regime_classifier · −8% breaker simulated · costs {COST_BPS:.0f} bps per unit of turnover. "
         f"Desk research, not personalized advice.*", "",
         "Book weights: " + ", ".join(f"{k} {v:g}" for k, v in base.items()), ""]
    if inc:
        L += ["## Accuracy check — replay of the model book since inception"]
        if inc.get("error"):
            L.append(f"- ⚠ {inc['error']}")
        else:
            L.append(f"- {inc['start']} → {inc['end']}: replayed V0 vs recorded NAV, largest gap "
                     f"**{inc['replay_max_diff']:.4f}** NAV points (tolerance {REPLAY_TOLERANCE}) → "
                     f"**{'PASS' if inc['replay_ok'] else 'FAIL'}**. Recorded last {inc['recorded_last']}, "
                     f"replayed last {inc['replayed_last']}.")
            if not inc["replay_ok"]:
                L.append("- A FAIL means the harness and the model book disagree on returns; do not use "
                         "the results below until it is explained.")
        L.append("")

    if bres is not None and binfos:
        L += render_breakers(bres, binfos)
    if cres is not None and cinfos:
        L += render_convexity(cres, cinfos, binfos or [])

    L += ["## Hedge sleeve rules (v1, unchanged)",
          "| Code | Rule |", "|---|---|",
          "| V0 | Current book, unchanged |",
          f"| V1 | TLT → SGOV while TLT's {CORR_WINDOW}-day correlation with SPY is positive |",
          f"| V2 | GLD, SLV, RING, TLT each halved (→ SGOV) while below a falling {TREND_MA}-day average |",
          "| V3 | V1 then V2 |", "",
          "### Verdict", *[f"- {x}" for x in verdicts(res, infos)], ""]

    order = [s[0] for s in STRESS] + [FULL[0], "inception"]
    cols = ["variant", "total_return_pct", "cagr_pct", "max_dd_pct", "worst_day_pct", "worst_20d_pct",
            "vol_ann_pct", "switch_days", "cost_pct", "breaker_days"]
    for key in order:
        info = next((i for i in infos if i["key"] == key), None)
        if key == "inception":
            info = inc or None
        if not info:
            continue
        L.append(f"### {info.get('label', key)} ({info.get('start', '?')} → {info.get('end', '?')})")
        if info.get("error"):
            L += [f"- ⚠ {info['error']}", ""]
            continue
        if info.get("coverage"):
            c = info["coverage"]
            flag = " · ⚠ **LOW COVERAGE** — excluded from the verdict" if info.get("low_coverage") else ""
            L.append(f"Data: native {c['native']}% · proxy {c['proxy']}% · T-bill cash {c['cash']}% · "
                     f"none {c['none']}% of the book{flag}")
        sub = res[res["window"] == key]
        L += ["", "| Variant | Return | CAGR | Max DD | Worst day | Worst 20d | Vol | Change days | Cost | Breaker days |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in sub.iterrows():
            L.append(f"| {r['variant']} {VARIANT_LABEL.get(r['variant'], '')} | {_f(r.get('total_return_pct'))} | "
                     f"{_f(r.get('cagr_pct'))} | {_f(r.get('max_dd_pct'))} | {_f(r.get('worst_day_pct'))} | "
                     f"{_f(r.get('worst_20d_pct'))} | {_f(r.get('vol_ann_pct'))} | "
                     f"{'' if pd.isna(r.get('switch_days')) else int(r['switch_days'])} | "
                     f"{'' if pd.isna(r.get('cost_pct')) else _f(r['cost_pct'], 2)} | "
                     f"{'' if pd.isna(r.get('breaker_days')) else int(r['breaker_days'])} |")
        L.append("")
    if missing:
        L += ["## Data health", f"- Tickers Yahoo returned nothing for: {', '.join(missing)}. "
              "Any sleeve relying on them falls to the next ticker in its chain; see data/hedge_lab/coverage.csv.", ""]
    L += ["## Known limits",
          "- Convexity sleeve: option values are model marks (Black-Scholes, VIX as implied vol, the module's skew "
          "markup, 3% trading cost), on SPY's dividend-adjusted price. Real puts in a crash can fill worse or "
          "better; treat sleeve results as direction and size of effect, not a quote.",
          "- KMLM runs on AQMIX from 2010 and T-bill cash before that, which understates the 2008 hedge in "
          "every variant equally.",
          "- The entry gate is not simulated (in this regime it moves only SCHD +1, XLV +1, KMLM +3 vs base).",
          "- The stress windows test today's book through past markets; they are not a replay of what the "
          "regime classifier would have chosen then (that needs full-history HY OAS, fix_status N11).", ""]
    return "\n".join(L)


# ── entry points ────────────────────────────────────────────────────────────

def build(closes: dict, book_path: Path = mb.BOOK_FILE, base: Optional[dict] = None) -> dict:
    if base is None:
        import regime_classifier as rc
        base = rc.target_weights(REGIME, gate=False)
    base = {k: float(v) for k, v in base.items()}
    spy = closes.get("SPY")
    if spy is None or len(spy) == 0:
        raise RuntimeError("SPY history missing: the trading calendar cannot be built")
    spy = _norm(spy)
    cal = pd.DatetimeIndex(spy.index)
    rets, srcs = splice(closes, PROXIES, cal)
    bench_rets, _ = splice(closes, BENCH, cal)
    sig = signals(rets, bench_rets["SPY"])
    rows, cov_rows, infos = [], [], []
    for key, s, e, label in STRESS + [FULL]:
        r, c, i = run_window(key, s, e, label, base, rets, srcs, sig, spy, bench_rets)
        rows += r; cov_rows += c; infos.append(i)
    inc_rows, inc = run_inception(Path(book_path), rets, sig, bench_rets)
    rows += inc_rows
    res = pd.DataFrame(rows)
    # v1.1: breaker release test over the full history, round trips and stress windows
    sig.update(release_signals(closes, cal, rets))
    brows, binfos = [], []
    for key, s, e, label in [FULL] + round_trips(cal) + STRESS:
        r, i = run_breaker_window(key, s, e, label, base, rets, srcs, sig, spy)
        brows += r; binfos.append(i)
    # v1.2: convexity sleeve test, under B0 and B3, same windows
    mkt = sleeve_market(closes, cal)
    crows, cinfos = [], []
    for key, s, e, label in [FULL] + round_trips(cal) + STRESS:
        r, i = run_convexity_window(key, s, e, label, base, rets, sig, mkt, spy)
        crows += r; cinfos.append(i)
    missing = [t for t in all_tickers() if t not in closes]
    return {"results": res, "coverage": pd.DataFrame(cov_rows), "infos": infos, "inception": inc,
            "base": base, "missing": missing, "signals": sig, "rets": rets,
            "breakers": pd.DataFrame(brows), "breaker_infos": binfos,
            "convexity": pd.DataFrame(crows), "convexity_infos": cinfos, "market": mkt}


def write(out: dict, asof: str) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    num = out["results"].select_dtypes("number").columns
    out["results"].assign(**{c: out["results"][c].round(4) for c in num}).to_csv(OUT_DIR / "results.csv", index=False)
    out["coverage"].to_csv(OUT_DIR / "coverage.csv", index=False)
    b = out.get("breakers")
    if b is not None and not b.empty:
        bn = b.select_dtypes("number").columns
        b.assign(**{c: b[c].round(4) for c in bn}).to_csv(OUT_DIR / "breaker_results.csv", index=False)
    cx = out.get("convexity")
    if cx is not None and not cx.empty:
        cn = cx.select_dtypes("number").columns
        cx.assign(**{c: cx[c].round(4) for c in cn}).to_csv(OUT_DIR / "convexity_results.csv", index=False)
    md = render(out["results"], out["infos"], out["base"], out["inception"], out["missing"], asof,
                out.get("breakers"), out.get("breaker_infos"), cx, out.get("convexity_infos"))
    p = LOG_DIR / f"{asof}_report.md"
    p.write_text(md)
    return {"report": str(p), "results": str(OUT_DIR / "results.csv")}


def run() -> dict:
    closes = yf_fetch(all_tickers())
    asof = date.today().isoformat()
    out = build(closes)
    paths = write(out, asof)
    print(json.dumps({"asof": asof, **paths, "missing": out["missing"],
                      "replay": {k: out["inception"].get(k) for k in ("replay_max_diff", "replay_ok", "error")}},
                     indent=2))
    return out


# ── selftest (offline, synthetic) ───────────────────────────────────────────

def selftest() -> dict:
    import tempfile
    f = []
    rng = np.random.default_rng(11)
    cal = pd.bdate_range("1999-01-04", "2026-10-30")
    n = len(cal)

    def path(mu, sd, start_i=0, shocks=None):
        r = rng.normal(mu, sd, n)
        if shocks is not None:
            r = r + shocks
        s = pd.Series(100 * np.exp(np.cumsum(r)), index=cal)
        return s.iloc[start_i:]

    spy_r = rng.normal(0.0003, 0.011, n)
    closes = {"SPY": pd.Series(100 * np.exp(np.cumsum(spy_r)), index=cal)}
    # TLT: negatively correlated with SPY for the first half, positively after
    half = n // 2
    tlt_r = np.where(np.arange(n) < half, -0.6 * spy_r, 0.8 * spy_r) + rng.normal(0, 0.004, n)
    closes["VUSTX"] = pd.Series(100 * np.exp(np.cumsum(tlt_r)), index=cal)
    closes["TLT"] = closes["VUSTX"].iloc[cal.get_loc(pd.Timestamp("2002-07-30")):]
    # GLD: steady decline for its last 400 sessions (a falling 200-day), flat before
    g = np.concatenate([rng.normal(0.0002, 0.008, n - 400), rng.normal(-0.002, 0.004, 400)])
    closes["GC=F"] = pd.Series(100 * np.exp(np.cumsum(g)), index=cal).iloc[cal.get_loc(pd.Timestamp("2000-08-30")):]
    closes["GLD"] = closes["GC=F"].loc["2004-11-18":]
    for t in ["XLK", "QQQ", "SI=F", "GDX", "XLE", "DBC", "DVY", "XLV", "XLU", "AQMIX", "VBMFX", "SOXX"]:
        closes[t] = path(0.0002, 0.01)
    closes["^IRX"] = pd.Series(4.0, index=cal)
    closes["^VIX"] = pd.Series(np.clip(18 + np.cumsum(rng.normal(0, 0.6, n)) * 0.05, 9, 80), index=cal)
    for t in ["VGT", "SMH", "SLV", "RING", "PDBC", "SCHD", "SGOV", "USFR", "KMLM", "BIL", "AGG"]:
        closes[t] = path(0.0002, 0.01, start_i=n - 900)
    base = {"VGT": 17.0, "SMH": 3.0, "QQQ": 3.0, "GLD": 10.0, "SLV": 4.0, "RING": 4.0, "XLE": 5.0,
            "PDBC": 3.0, "SCHD": 14.0, "XLV": 5.0, "XLU": 3.0, "SGOV": 8.0, "USFR": 7.0, "TLT": 7.0, "KMLM": 7.0}

    tmp = tempfile.mkdtemp()
    cwd = os.getcwd()
    try:
        os.chdir(tmp)
        os.makedirs("data")
        # a model book over the last 60 sessions, built by model_book itself
        book_days = cal[-60:]
        prices = {t: pd.DataFrame({"Close": closes[t]}) for t in base if t in closes}
        prices["SPY"] = pd.DataFrame({"Close": closes["SPY"]})
        rb = {book_days[0].date(): REGIME}
        # weights alternate day to day, so a same-day vs next-day timing error cannot hide
        alt_w = dict(base, TLT=0.0, SGOV=15.0, GLD=4.0, VGT=23.0)
        bk = mb.advance(pd.DataFrame(), book_days[-1].date(), rb, prices,
                        lambda k, d: dict(base) if pd.Timestamp(d).toordinal() % 2 == 0 else dict(alt_w), REGIME,
                        today_weights=dict(base) if pd.Timestamp(book_days[-1]).toordinal() % 2 == 0 else dict(alt_w))
        bk.to_csv("data/model_book.csv", index=False)

        out = build(closes, Path("data/model_book.csv"), base=base)
        res, sig, rets = out["results"], out["signals"], out["rets"]

        # 1. weights always sum to the base total, every variant, every day tested
        for v in VARIANTS:
            for d in rets.index[-500::37]:
                w, _ = apply_variant(base, v, sig, d)
                if abs(sum(w.values()) - sum(base.values())) > 1e-9:
                    f.append(f"{v} weights do not sum to 100 on {d.date()}: {sum(w.values())}")
                    break

        # 2. V1: TLT kept while correlation is negative, moved to SGOV once it turns positive
        d_neg, d_pos = rets.index[half - 50], rets.index[-50]
        if apply_variant(base, "V1", sig, d_neg)[0]["TLT"] != 7.0:
            f.append(f"V1 moved TLT while corr was {sig['corr'].get(d_neg):+.2f}")
        w_pos = apply_variant(base, "V1", sig, d_pos)[0]
        if w_pos["TLT"] != 0.0 or abs(w_pos["SGOV"] - 15.0) > 1e-9:
            f.append(f"V1 must move TLT to SGOV when corr is {sig['corr'].get(d_pos):+.2f}: {w_pos['TLT']}, {w_pos['SGOV']}")

        # 3. V2: GLD halved in its falling-200-day stretch, untouched before it
        if apply_variant(base, "V2", sig, rets.index[-20])[0]["GLD"] != 5.0:
            f.append("V2 must halve GLD below a falling 200-day")
        if apply_variant(base, "V2", sig, rets.index[n - 900])[0]["GLD"] != 10.0 and not sig["down"]["GLD"].iloc[n - 900]:
            f.append("V2 halved GLD without a downtrend")

        # 4. no lookahead: a jump in prices after day k (big enough to flip every
        #    trend and correlation signal) must leave every signal up to k unchanged
        k = n - 300
        alt = {t: s.copy() for t, s in closes.items()}
        for t in ("VUSTX", "TLT", "GC=F", "GLD", "SLV", "SI=F", "GDX", "RING", "SPY"):
            s = alt[t].copy()
            m = s.index > cal[k]
            if m.sum():
                s[m] = s[m].to_numpy() * np.linspace(3.0, 4.0, int(m.sum()))
            alt[t] = s
        r2, _ = splice(alt, PROXIES, cal)
        b2, _ = splice(alt, BENCH, cal)
        sig2 = signals(r2, b2["SPY"])
        upto = cal[:k + 1]
        flipped_after = any(bool((sig["down"][h].loc[cal[k + 1:k + 5]] != sig2["down"][h].loc[cal[k + 1:k + 5]]).any())
                            for h in HEDGES)
        if not flipped_after:
            f.append("lookahead test is too weak: the perturbation flipped no signal after day k")
        for h in HEDGES:
            if not sig["down"][h].loc[upto].equals(sig2["down"][h].loc[upto]):
                f.append(f"lookahead: {h} trend signal up to day k changed when later prices changed")
        c1, c2 = sig["corr"].loc[upto], sig2["corr"].loc[upto]
        if not np.allclose(c1.fillna(0).to_numpy(), c2.fillna(0).to_numpy()):
            f.append("lookahead: TLT correlation up to day k changed when later prices changed")
        # v1.1: the same for the breaker release signals (SPY/QQQ and each sleeve vs its 200-day)
        #     Pushed both down (x0.3) and up (x3) so a one-day peek flips whichever
        #     state the series was in; each index and sleeve must flip at least once.
        rs1 = release_signals(closes, cal, rets)
        after = cal[k + 1:k + 5]
        flipped = {n: False for n in ("spy200", "qqq200")}
        flipped_own = False
        for fac in (0.3, 3.0):
            alt_r = {t: s.copy() for t, s in closes.items()}
            for t in alt_r:
                s = alt_r[t]
                m = s.index > cal[k]
                if m.sum():
                    s[m] = s[m].to_numpy() * fac
            r3, _ = splice(alt_r, PROXIES, cal)
            rs2 = release_signals(alt_r, cal, r3)
            for n in flipped:
                flipped[n] |= bool((rs1[n].loc[after] != rs2[n].loc[after]).any())
                if not rs1[n].loc[upto].equals(rs2[n].loc[upto]):
                    f.append(f"lookahead: {n} up to day k changed when later prices changed (x{fac})")
            for s in base:
                flipped_own |= bool((rs1["above200"][s].loc[after] != rs2["above200"][s].loc[after]).any())
                if not rs1["above200"][s].loc[upto].equals(rs2["above200"][s].loc[upto]):
                    f.append(f"lookahead: {s} own-trend signal up to day k changed when later prices changed (x{fac})")
                    break
        if not all(flipped.values()) or not flipped_own:
            f.append(f"release-signal lookahead test is too weak: flips after day k {flipped}, own {flipped_own}")

        # 12. timing: weights chosen on day d earn day d+1's return, never day d's
        tdays = cal[-6:]
        tr = pd.DataFrame(0.0, index=tdays, columns=["XLE", "SGOV"])
        tr.loc[tdays[3], "XLE"] = 0.10
        on_jump = simulate(tdays, tr, lambda d: {"XLE": 100.0} if d == tdays[3] else {"SGOV": 100.0},
                           None, breaker=False, cost_bps=0.0)
        before_jump = simulate(tdays, tr, lambda d: {"XLE": 100.0} if d == tdays[2] else {"SGOV": 100.0},
                               None, breaker=False, cost_bps=0.0)
        if abs(on_jump["nav"].iloc[-1] - 100.0) > 1e-9:
            f.append(f"timing: weights set on the jump day must not earn that day's return ({on_jump['nav'].iloc[-1]:.4f})")
        if abs(before_jump["nav"].iloc[-1] - 110.0) > 1e-9:
            f.append(f"timing: weights set the day before must earn the jump ({before_jump['nav'].iloc[-1]:.4f})")

        # 5. proxy splice and coverage labels
        srcs = splice(closes, PROXIES, cal)[1]
        if srcs.at[pd.Timestamp("2001-06-01"), "TLT"] != "VUSTX" or srcs.at[pd.Timestamp("2010-06-01"), "TLT"] != "TLT":
            f.append("TLT chain must use VUSTX before inception and TLT after")
        if srcs.at[pd.Timestamp("2000-04-03"), "GLD"] != "":
            f.append("GLD before any gold data must be uncovered ('none'), not filled")
        if srcs.at[pd.Timestamp("2005-06-01"), "SGOV"] != "^IRX":
            f.append("SGOV before BIL must use the T-bill cash return")
        dot = next(i for i in out["infos"] if i["key"] == "dotcom_2000")
        if dot["coverage"]["none"] <= 0:
            f.append("dot-com window must report the uncovered gold months")

        # 6. metrics on a known path: 100 -> 120 -> 60 -> 90 has a -50% max drawdown
        mm = metrics(pd.Series([100.0, 120.0, 60.0, 90.0], index=cal[:4]))
        if abs(mm["max_dd_pct"] + 50.0) > 1e-9 or abs(mm["total_return_pct"] + 10.0) > 1e-9:
            f.append(f"metrics wrong on a known path: {mm}")

        # 7. inception replay reproduces the model book's own NAV
        inc = out["inception"]
        if inc.get("error") or not inc.get("replay_ok"):
            f.append(f"inception replay must match model_book: {inc}")

        # 8. breaker: a −20% crash trips it and halves risk sleeves, exactly as model_book does
        crash = rets.copy()
        days = cal[-30:]
        crash.loc[days[5], :] = -0.20
        sim = simulate(days, crash, lambda d: dict(base), closes["SPY"])
        on = sim[sim["state"] == "ON"]
        if on.empty:
            f.append("a −20% day must trip the breaker")
        else:
            w_on = on["w"].iloc[0]
            if abs(w_on["VGT"] - 8.5) > 1e-9 or w_on["KMLM"] != 7.0:
                f.append(f"breaker must halve VGT and exempt KMLM: {w_on['VGT']}, {w_on['KMLM']}")

        # 9. costs: a variant that changes weights pays for it; V0 with fixed weights pays nothing
        full = res[res["window"] == FULL[0]].set_index("variant")
        if full.at["V0", "switch_days"] != 0 and full.at["V0", "breaker_days"] == 0:
            f.append("V0 with no breaker trips must have no weight changes")
        if full.at["V2", "switch_days"] <= 0:
            f.append("V2 must register weight changes on the GLD downtrend")
        if not (full.at["V2", "cost_pct"] > 0):
            f.append("V2 weight changes must cost something")

        # 10. report renders with every section
        md = render(res, out["infos"], base, inc, out["missing"], "2026-10-31")
        for s in ("### Verdict", "## Accuracy check", "Dot-com bust", "Full history", "## Known limits"):
            if s not in md:
                f.append(f"report missing: {s}")
        # 11. a LOW COVERAGE window is labelled and dropped from the verdict counts
        lo = [dict(i, low_coverage=True) if i["key"] == "dotcom_2000" else i for i in out["infos"]]
        md_lo = render(res, lo, base, inc, out["missing"], "2026-10-31")
        n_ok = sum(1 for i in out["infos"] if i["key"] in {s[0] for s in STRESS} and not i.get("low_coverage"))
        if "LOW COVERAGE" not in md_lo or "dotcom_2000" not in " ".join(verdicts(res, lo)):
            f.append("a low-coverage window must be labelled and named as excluded")
        if f"of {n_ok - 1} stress windows" not in " ".join(verdicts(res, lo)):
            f.append("a low-coverage window must be excluded from the verdict counts")

        # ── v1.1 breaker release rules, on a hand-made crash with known answers ──
        # day 2: every risk sleeve −30% (book ≈ −23%) → trip at day 2's close.
        # QQQ above its 200-day from day 4, SPY from day 6; GLD's own trend from day 9.
        bd = cal[-14:]
        br = pd.DataFrame(0.0, index=bd, columns=list(base))
        risk_s = [s for s in base if s not in mb.RISK_EXEMPT]
        br.loc[bd[2], risk_s] = -0.30

        def bsig(qqq_from=4, spy_from=6, gld_from=9):
            mk = lambda k: pd.Series([i >= k for i in range(len(bd))], index=bd)
            own = {s: pd.Series(True, index=bd) for s in base}
            own["GLD"] = mk(gld_from)
            return {"spy200": mk(spy_from), "qqq200": mk(qqq_from), "above200": own}

        def wt(sim, i, s):
            return round(sim["w"].iloc[i][s], 6)

        s1 = simulate_release(bd, br, base, "B1", bsig(), cost_bps=0.0)
        if s1["state"].iloc[2] != "ON" or wt(s1, 2, "VGT") != 8.5:
            f.append(f"B1: a −23% day must trip the breaker and halve VGT: {s1['state'].iloc[2]}, {wt(s1, 2, 'VGT')}")
        if s1["state"].iloc[6] != "ON" or s1["state"].iloc[7] != "OFF" or wt(s1, 7, "VGT") != 17.0:
            f.append("B1: must release on the 2nd consecutive close with SPY above its 200-day (day 7), not before")
        if (s1["state"].iloc[8:] == "ON").any() or int(s1["trips"].iloc[-1]) != 1:
            f.append("B1: after release the next trip must be measured from the release point (no instant re-trip)")
        if abs(sum(s1["w"].iloc[3].values()) - 100.0) > 1e-9:
            f.append("breaker weights must still sum to 100")

        s2 = simulate_release(bd, br, base, "B2", bsig(qqq_from=99), cost_bps=0.0)
        if (s2["state"].iloc[3:] != "ON").any():
            f.append("B2: must stay on while QQQ is below its 200-day, even with SPY above")

        s3 = simulate_release(bd, br, base, "B3", bsig(), cost_bps=0.0)
        if not (wt(s3, 5, "VGT") == 17.0 and wt(s3, 5, "SCHD") == 7.0):
            f.append(f"B3: growth back on day 5 (QQQ) while core still halved: VGT {wt(s3, 5, 'VGT')}, SCHD {wt(s3, 5, 'SCHD')}")
        if not (wt(s3, 7, "SCHD") == 14.0 and wt(s3, 7, "GLD") == 10.0):
            f.append("B3: core back on day 7 (SPY)")

        s4 = simulate_release(bd, br, base, "B4", bsig(), cost_bps=0.0)
        if not (wt(s4, 7, "SCHD") == 14.0 and wt(s4, 7, "GLD") == 5.0 and wt(s4, 9, "GLD") == 10.0):
            f.append(f"B4: GLD must wait for its own 200-day (day 9): day7 {wt(s4, 7, 'GLD')}, day9 {wt(s4, 9, 'GLD')}")
        if s4["state"].iloc[8] != "OFF" or int(s4["pending"].iloc[8]) != 1:
            f.append("B4: the breaker is off once both groups release; GLD alone is still waiting")

        br2 = br.copy()
        br2.loc[bd[10], risk_s] = -0.30
        s5 = simulate_release(bd, br2, base, "B1", bsig(), cost_bps=0.0)
        if int(s5["trips"].iloc[-1]) != 2 or s5["state"].iloc[10] != "ON":
            f.append("a fresh −8% fall after a release must trip the breaker again")

        bres, binfos = out["breakers"], out["breaker_infos"]
        if set(bres["breaker"]) != set(BREAKERS):
            f.append(f"breaker results must cover {BREAKERS}: {sorted(set(bres['breaker']))}")
        if not any(i["key"].endswith("_rt") for i in binfos):
            f.append("round-trip windows missing")
        md_b = render(res, out["infos"], base, inc, out["missing"], "2026-10-31", bres, binfos)
        for s in ("## Breaker release test", "The bar, fixed before the run", "one year after the trough"):
            if s not in md_b:
                f.append(f"breaker report missing: {s}")
        # B0 in the breaker test must be the same simulation as V0 in the v1 tables
        v0 = res[(res["window"] == FULL[0]) & (res["variant"] == "V0")]["total_return_pct"].iloc[0]
        b0 = bres[(bres["window"] == FULL[0]) & (bres["breaker"] == "B0")]["total_return_pct"].iloc[0]
        if abs(v0 - b0) > 1e-9:
            f.append(f"B0 must equal V0 over the full history: {b0} vs {v0}")

        # ── v1.2 convexity sleeve ──
        # C1. pricing identical to Markets convexity_sleeve._bs_put_approx (values recorded from the module)
        ref = [((100, 92, 20, 135, 0.04), 2.835016760347333), ((100, 80, 20, 135, 0.04), 0.9222614629830659),
               ((100, 92, 45, 60, 0.02), 4.70514666281165), ((70, 92, 60, 100, 0.01), 24.439285547898216),
               ((100, 92, 12, 10, 0.05), 0.005269386664160547)]
        for a, want in ref:
            got = bs_put(*a)
            if got is None or abs(got - want) > 1e-12:
                f.append(f"bs_put{a} = {got}, convexity_sleeve gives {want}")
        if bs_put(80, 92, 30, 0) != 12.0 or bs_put(100, 92, 30, -5) != 0.0:
            f.append("bs_put at or past expiry must be intrinsic value")

        # C2. with no sleeve, simulate_book reproduces the existing engines exactly
        fdays = cal[-1500:]
        sb0 = simulate_book(fdays, rets, base, "B0", sig, None, None, closes["SPY"])
        s00 = simulate(fdays, rets, lambda d: dict(base), closes["SPY"])
        if float((sb0["nav"] - s00["nav"]).abs().max()) > 1e-9:
            f.append("simulate_book B0 without a sleeve must equal simulate()")
        sb3 = simulate_book(fdays, rets, base, "B3", sig, None, None, closes["SPY"])
        s33 = simulate_release(fdays, rets, base, "B3", sig)
        if float((sb3["nav"] - s33["nav"]).abs().max()) > 1e-9:
            f.append("simulate_book B3 without a sleeve must equal simulate_release()")

        # hand-made market: 3 calm years, then a 35% crash over 10 sessions with VIX 15 -> 60
        hd = pd.bdate_range("2010-01-04", periods=900)
        spy_h = pd.Series(100.0, index=hd) * np.exp(np.linspace(0, 0.15, len(hd)))
        vix_h = pd.Series(15.0, index=hd)
        cr = 780
        spy_h.iloc[cr:cr + 10] = spy_h.iloc[cr - 1] * np.linspace(0.965, 0.65, 10)
        spy_h.iloc[cr + 10:] = spy_h.iloc[cr - 1] * 0.65
        vix_h.iloc[cr:] = np.linspace(25, 60, 10).tolist() + [60.0] * (len(hd) - cr - 10)
        rank_h = vix_h.rolling(VIX_RANK_LOOKBACK, min_periods=60).apply(
            lambda h: float((h <= h[-1]).mean()) * 100.0, raw=True)
        mkt_h = {"spy": spy_h, "vix": vix_h, "vix_rank": rank_h, "rate": pd.Series(0.03, index=hd)}
        hr = pd.DataFrame(0.0, index=hd, columns=list(base))
        for _s in base:
            if _s not in mb.RISK_EXEMPT:
                hr[_s] = spy_h.pct_change().fillna(0.0).to_numpy()
        hsig = {"spy200": pd.Series(False, index=hd), "qqq200": pd.Series(False, index=hd),
                "above200": {s: pd.Series(False, index=hd) for s in base}}

        # C3. the policy sleeve spends ~1% of NAV a year in a calm market, buying every 75 days
        calm = hd[:cr]
        c1 = simulate_book(calm, hr, base, "B0", hsig, mkt_h, SLEEVES["C1"], spy_h)
        yrs = (calm[-1] - calm[0]).days / 365.25
        spend = c1["paid"].iloc[-1] / c1["nav"].mean() * 100 / yrs
        if not 0.9 <= spend <= 1.15:
            f.append(f"C1 must spend about 1% of NAV a year in a calm market: {spend:.3f}%")
        expect_buys = int((calm[-1] - calm[0]).days // DAYS_PER_ROLL) + 1
        if abs(int(c1["n_buys"].iloc[-1]) - expect_buys) > 1:
            f.append(f"C1 must buy every {DAYS_PER_ROLL} days: {int(c1['n_buys'].iloc[-1])} buys vs ~{expect_buys}")
        none_calm = simulate_book(calm, hr, base, "B0", hsig, mkt_h, None, spy_h)
        if not c1["nav"].iloc[-1] < none_calm["nav"].iloc[-1]:
            f.append("in a calm market the sleeve must cost money")

        # C4. the designed schedule: cheap VIX buys the most, expensive VIX buys nothing
        q_mkt = {"vix_rank": pd.Series([10.0, 40.0, 60.0, 90.0], index=hd[:4])}
        got_q = [round(roll_budget_pct(SLEEVES["C2"], hd[i], q_mkt), 6) for i in range(4)]
        want_q = [round(CONVEXITY_BY_QUARTILE[q] * DAYS_PER_ROLL / (365.0 / 4), 6) for q in (1, 2, 3, 4)]
        if got_q != want_q:
            f.append(f"C2 budget by VIX quartile wrong: {got_q} vs {want_q}")

        # C5. in the crash the puts pay: harvests fire, and the book falls less than without them
        c1c = simulate_book(hd, hr, base, "B0", hsig, mkt_h, SLEEVES["C1"], spy_h)
        nc = simulate_book(hd, hr, base, "B0", hsig, mkt_h, None, spy_h)
        if int(c1c["n_harvest"].iloc[-1]) < 1:
            f.append("a 35% crash with VIX at 60 must trigger at least the first harvest")
        dd_with = float((c1c["nav"] / c1c["nav"].cummax() - 1).min())
        dd_without = float((nc["nav"] / nc["nav"].cummax() - 1).min())
        if not dd_with > dd_without:
            f.append(f"the sleeve must reduce the crash drawdown: {dd_with:.4f} vs {dd_without:.4f}")

        # C6. a put spread's value never exceeds its width
        trs = {"k1": 92.0, "k2": 80.0, "expiry": hd[0] + pd.Timedelta(days=100), "last_value": 0.0, "last_iv": 60.0}
        crash_mkt = {"spy": pd.Series(50.0, index=hd), "vix": pd.Series(80.0, index=hd), "rate": pd.Series(0.03, index=hd)}
        if unit_value(trs, hd[0], crash_mkt) > 12.0 + 1e-9:
            f.append("a put spread must cap at its width")

        # C7. no lookahead: changing SPY and VIX after day k leaves the sleeve and book unchanged up to k
        kk = cr - 5
        spy_alt, vix_alt = spy_h.copy(), vix_h.copy()
        spy_alt.iloc[kk + 1:] *= 0.5
        vix_alt.iloc[kk + 1:] = 70.0
        mkt_alt = {"spy": spy_alt, "vix": vix_alt, "rate": mkt_h["rate"],
                   "vix_rank": vix_alt.rolling(VIX_RANK_LOOKBACK, min_periods=60).apply(
                       lambda h: float((h <= h[-1]).mean()) * 100.0, raw=True)}
        hr_alt = hr.copy()
        for _s in base:
            if _s not in mb.RISK_EXEMPT:
                hr_alt[_s] = spy_alt.pct_change().fillna(0.0).to_numpy()
        # C1 (fixed budget), so options are held whatever VIX does; C2 buys nothing when VIX is flat
        a1 = simulate_book(hd, hr, base, "B0", hsig, mkt_h, SLEEVES["C1"], spy_h)
        a2 = simulate_book(hd, hr_alt, base, "B0", hsig, mkt_alt, SLEEVES["C1"], spy_alt)
        if not a1["sleeve"].iloc[kk] > 0:
            f.append("lookahead test is too weak: no options held on day k")
        if float((a1["nav"].iloc[:kk + 1] - a2["nav"].iloc[:kk + 1]).abs().max()) > 1e-9:
            f.append("lookahead: sleeve or book value up to day k changed when later SPY/VIX changed")
        if float((a1["nav"].iloc[kk + 1:] - a2["nav"].iloc[kk + 1:]).abs().max()) < 1e-6:
            f.append("lookahead test is too weak: the perturbation changed nothing after day k")

        # C9. sleeve_market (SPY, VIX, VIX rank, rate from real closes) uses nothing after day d
        km = len(cal) - 400
        alt_m = {t: s.copy() for t, s in closes.items()}
        for t in ("SPY", "^VIX", "^IRX"):
            s_ = alt_m[t]
            mm_ = s_.index > cal[km]
            s_[mm_] = s_[mm_].to_numpy() * 2.5
        m1, m2 = sleeve_market(closes, cal), sleeve_market(alt_m, cal)
        upto_m = cal[:km + 1]
        for nm in ("spy", "vix", "vix_rank", "rate"):
            x1, x2 = m1[nm].loc[upto_m].fillna(-1), m2[nm].loc[upto_m].fillna(-1)
            if not np.allclose(x1.to_numpy(), x2.to_numpy()):
                f.append(f"lookahead: sleeve_market {nm} up to day k changed when later prices changed")
        if np.allclose(m1["vix_rank"].loc[cal[km + 1:km + 30]].fillna(-1).to_numpy(),
                       m2["vix_rank"].loc[cal[km + 1:km + 30]].fillna(-1).to_numpy()):
            f.append("sleeve_market lookahead test is too weak: VIX rank did not change after day k")

        # C8. the full run covers every breaker x sleeve combination, and the report shows it
        cxr = out["convexity"]
        combos = set(zip(cxr["breaker"], cxr["sleeve"]))
        want_c = {(b_, c_) for b_ in CONVEXITY_BREAKERS for c_ in SLEEVES}
        if combos != want_c:
            f.append(f"convexity results must cover {sorted(want_c)}: {sorted(combos)}")
        md_c = render(res, out["infos"], base, inc, out["missing"], "2026-10-31", bres, binfos,
                      cxr, out["convexity_infos"])
        for s in ("## Convexity sleeve test", "model mark", "Dot-com round trip, B3 max drawdown by sleeve"):
            if s not in md_c:
                f.append(f"convexity report missing: {s}")
        # B0 + none in the convexity test must equal B0 in the breaker test
        x0 = cxr[(cxr["window"] == FULL[0]) & (cxr["breaker"] == "B0") & (cxr["sleeve"] == "none")]["total_return_pct"].iloc[0]
        if abs(x0 - b0) > 1e-9:
            f.append(f"B0 + no sleeve must equal B0 in the breaker test: {x0} vs {b0}")
    finally:
        os.chdir(cwd)
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        print(json.dumps(selftest(), indent=2))
        sys.exit(0)
    run()
