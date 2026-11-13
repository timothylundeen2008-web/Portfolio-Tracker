"""
offense_lab.py  (v1.0 — 2026-11-13)
───────────────────────────────────
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

VERSION = "v1.0"
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
BAR_DD_FRAC = 0.60
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
}


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


def states(kind: str, levels: pd.DataFrame, ma: int = MA, n_confirm: int = CONFIRM) -> pd.Series:
    spy_up = above_ma(levels["SPY"], ma)
    if kind == "spy":
        raw = spy_up.map(lambda x: None if x != x else ("OFF" if x else "CASH"))
        return confirm(raw, n_confirm, "CASH")
    qqq_up = above_ma(levels["QQQ"], ma)
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
    d, ds = (st.get("full") or {}).get("max_dd_pct"), (spy.get("full") or {}).get("max_dd_pct")
    lim = abs(ds or 0) * BAR_DD_FRAC
    if d is None or abs(d) > lim + 1e-9:
        why.append(f"max DD {d}% deeper than {lim:.1f}% ({BAR_DD_FRAC:.0%} of SPY's {ds}%)")
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


def run_candidate(key: str, data: dict, balanced: dict, ma: int = MA, lag: int = LAG) -> dict:
    cand = CANDIDATES[key]
    st = states(cand["kind"], data["levels"], ma)
    days = data["cal"][data["cal"] >= pd.Timestamp(EVAL_START) - pd.Timedelta(days=10)]
    sim = hl.simulate(days, data["rets"], weights_fn(st, cand, balanced, lag), None, breaker=False, cost_bps=COST_BPS)
    s_in = st.reindex(days)
    switches = int((s_in != s_in.shift(1)).iloc[1:].sum())
    share = s_in[s_in.index >= pd.Timestamp(EVAL_START)].value_counts(normalize=True).mul(100).round(1).to_dict()
    return {"nav": sim["nav"], "states": st, "switches": switches, "share": share,
            "turnover": float(sim["turnover"].sum()), "coverage_min": float(sim["coverage"].min())}


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
    verdicts, trials = [], len(CANDIDATES)
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
                trials += 1
                w2 = bar_check(summary(rr["nav"]), summ["SPY"])
                if w2:
                    rob.append(f"MA {m}: " + "; ".join(w2))
            row["verdict"] = "PASS (robust)" if not rob else "FRAGILE (passes at 200-day only)"
            row["robustness"] = "; ".join(rob) or "holds at 150 and 250"
        yr = pd.DataFrame({"c": year_returns(navs[k]), "s": year_returns(navs["SPY"])}).dropna()
        row["years_beat_spy"] = f"{int((yr.c > yr.s).sum())} of {len(yr)}"
        row["worst_year_vs_spy_pts"] = round(float((yr.c - yr.s).min()), 1) if len(yr) else None
        row["switches"] = runs[k]["switches"]
        verdicts.append(row)
    years = pd.DataFrame({k: year_returns(v) for k, v in navs.items()}).round(1)
    return {"navs": navs, "summ": summ, "runs": runs, "robust": robust_runs,
            "verdicts": pd.DataFrame(verdicts), "years": years, "trials": trials}


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
         f"Bar: CAGR above SPY over the full window AND both halves, net of costs and lag; max drawdown no deeper "
         f"than {BAR_DD_FRAC:.0%} of SPY's; and the same at the 150- and 250-day averages (robustness).", "",
         "| Candidate | Verdict | Years beating SPY | Worst year vs SPY | Switches | Reasons (200-day) | Robustness |",
         "|---|---|---|---|---|---|---|"]
    for _, r in out["verdicts"].iterrows():
        L.append(f"| {NAMES[r.candidate]} | **{r.verdict}** | {r.years_beat_spy} | {_f(r.worst_year_vs_spy_pts, 1)} pts | "
                 f"{r.switches} | {r.reasons_200} | {r.get('robustness') or '—'} |")
    L += ["", "## Full window and halves", "",
          "| Book | CAGR full / 05–15 / 16–26 % | Max DD full % | Vol % | Sharpe | Calmar | DSR | Time in Offense / Balanced / Defense |",
          "|---|---|---|---|---|---|---|---|"]
    for k in ["SPY", "QQQ", "60/40", "V0", *CANDIDATES]:
        f, a, b = s[k]["full"], s[k]["2005-15"], s[k]["2016-26"]
        sh = out["runs"][k]["share"] if k in out["runs"] else {}
        mix = (f"{sh.get('OFF', 0):.0f} / {sh.get('BAL', 0) + sh.get('CASH', 0):.0f} / {sh.get('DEF', 0):.0f}%"
               if sh else "—")
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
    prior = int(pd.read_csv(tl)["trials"].sum()) if tl.exists() else 0
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
    pd.DataFrame(out["navs"]).round(4).to_csv(OUT_DIR / "nav.csv")
    acc.to_csv(OUT_DIR / "lev_accuracy.csv", index=False)
    pd.DataFrame({k: r["states"] for k, r in out["runs"].items()}).tail(30).to_csv(OUT_DIR / "states_recent.csv")
    row = pd.DataFrame([{"date": asof, "version": VERSION, "trials": out["trials"],
                         "note": "O1-O5 at 200d; +2 robustness runs per passer"}])
    (pd.concat([pd.read_csv(tl), row]) if tl.exists() else row).to_csv(tl, index=False)
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
    good = {"full": {"cagr_pct": 9.0, "max_dd_pct": -29.0}, "2005-15": {"cagr_pct": 7.0}, "2016-26": {"cagr_pct": 12.5}}
    if bar_check(good, spy):
        f.append(f"bar: a clear pass failed: {bar_check(good, spy)}")
    if not bar_check(dict(good, full={"cagr_pct": 9.0, "max_dd_pct": -31.0}), spy):
        f.append("bar: 31% drawdown vs a 30% limit passed")
    if not bar_check(dict(good, **{"2016-26": {"cagr_pct": 12.0}}), spy):
        f.append("bar: equal CAGR in a half must fail (strictly above)")
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
