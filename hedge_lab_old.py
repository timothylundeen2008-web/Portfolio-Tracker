"""
hedge_lab.py  (v1 — October 2026)
─────────────────────────────────
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

VERSION = "v1"
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

STRESS = [
    ("dotcom_2000", "2000-03-24", "2002-10-09", "Dot-com bust"),
    ("gfc_2008",    "2007-10-09", "2009-03-09", "Global financial crisis"),
    ("covid_2020",  "2020-02-19", "2020-03-23", "Covid crash"),
    ("rates_2022",  "2022-01-03", "2022-10-12", "Rates shock (closest analogue: positive stock/bond correlation)"),
    ("carry_2024",  "2024-07-16", "2024-08-05", "Yen-carry unwind (liquidity flush)"),
]
FULL = ("full_2005", "2005-01-03", None, "Full history: the cost of each rule in normal markets")
VARIANTS = ("V0", "V1", "V2", "V3")
VARIANT_LABEL = {"V0": "current book", "V1": "corr-gated TLT", "V2": "hedge trend rule",
                 "V3": "V1 + V2", "SPY": "", "6040": "60/40"}


# ── prices ──────────────────────────────────────────────────────────────────

def all_tickers() -> list[str]:
    s = {t for chain in PROXIES.values() for t in chain} | {t for c in BENCH.values() for t in c}
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


def render(res: pd.DataFrame, infos: list, base: dict, inc: dict, missing: list, asof: str) -> str:
    L = [f"# Hedge lab — {asof}",
         f"*{VERSION} · real prices (dividend-adjusted, Yahoo) · book = `{REGIME}` targets from "
         f"regime_classifier · −8% breaker simulated · costs {COST_BPS:.0f} bps per unit of turnover. "
         f"Desk research, not personalized advice.*", "",
         "## Variants",
         "| Code | Rule |", "|---|---|",
         "| V0 | Current book, unchanged |",
         f"| V1 | TLT → SGOV while TLT's {CORR_WINDOW}-day correlation with SPY is positive |",
         f"| V2 | GLD, SLV, RING, TLT each halved (→ SGOV) while below a falling {TREND_MA}-day average |",
         "| V3 | V1 then V2 |", "",
         "Book weights: " + ", ".join(f"{k} {v:g}" for k, v in base.items()), ""]
    L += ["## Verdict", *[f"- {x}" for x in verdicts(res, infos)], ""]

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

    order = [s[0] for s in STRESS] + [FULL[0], "inception"]
    cols = ["variant", "total_return_pct", "cagr_pct", "max_dd_pct", "worst_day_pct", "worst_20d_pct",
            "vol_ann_pct", "switch_days", "cost_pct", "breaker_days"]
    for key in order:
        info = next((i for i in infos if i["key"] == key), None)
        if key == "inception":
            info = inc or None
        if not info:
            continue
        L.append(f"## {info.get('label', key)} ({info.get('start', '?')} → {info.get('end', '?')})")
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
    missing = [t for t in all_tickers() if t not in closes]
    return {"results": res, "coverage": pd.DataFrame(cov_rows), "infos": infos, "inception": inc,
            "base": base, "missing": missing, "signals": sig, "rets": rets}


def write(out: dict, asof: str) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    num = out["results"].select_dtypes("number").columns
    out["results"].assign(**{c: out["results"][c].round(4) for c in num}).to_csv(OUT_DIR / "results.csv", index=False)
    out["coverage"].to_csv(OUT_DIR / "coverage.csv", index=False)
    md = render(out["results"], out["infos"], out["base"], out["inception"], out["missing"], asof)
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
        for s in ("## Verdict", "## Accuracy check", "Dot-com bust", "Full history", "## Known limits"):
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
