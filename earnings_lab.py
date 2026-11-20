"""
earnings_lab.py  (v1.0 — 2026-11-20)
─────────────────────────────────────
Track A: earnings acceleration added to leadership (swing book). Pre-registration:
claude/earnings_lab_2026-11-20.md. Approved by Matt 2026-11-18 ("Let's look at all
of them") and 2026-11-20 ("move to track A build and testing").

Data: point-in-time S&P 500 membership (data/universe/sp500_membership.csv), quarterly
diluted EPS as first filed with the SEC (edgar_data v1.3; Q4 = full year − 9 months,
known on the 10-K date), company number by month (edgar_data), prices from Yahoo.

RULES (frozen before any run)
  At each month-end close ME, a member is ELIGIBLE when, using only data known at ME:
    trend     close above its 50-day and 200-day averages, 200-day average higher than
              20 sessions ago;
    earnings  (A1 only) latest quarter's diluted EPS (filed ≤ ME, quarter ended within
              200 days) is positive and at least 25% above the same quarter a year
              earlier (which must be positive), AND that growth rate is higher than the
              previous quarter's year-over-year growth (also computed only from filings
              made by ME): earnings growing, and growing faster.
  Rank eligible members by strength = average of their 3-, 6- and 12-month returns;
  hold the top N (N = 10) in equal weight. If SPY closes ME below its 200-day average,
  hold T-bills instead (the swing book's market filter). Empty slots sit in T-bills.
  Trade at the open of the first session after ME; hold to the next rebalance open.
  Costs: 10bp per unit of turnover (5bp commission/spread + 5bp slippage).
CANDIDATES
  A1   the rule above (decision)
  A0   the same without the earnings condition (control: what earnings add)
  A1-5, A1-20   A1 holding 5 and 20 (stability, reported)
WINDOW 2011-01 to 2026-11 (EPS acceleration needs two years of filings); halves
  2011–18 and 2019–26.
BAR (A1)
  1. CAGR above SPY's over the full window and in both halves.
  2. CAGR above A0's in both halves (earnings must add something).
  3. Max drawdown (month-end) no deeper than −25%.
  ROBUST: still beats SPY over the full window when, each month, the share of
  earnings-passing members that have no free prices earns that month's worst pick
  (harsh missing-stock stress).
  STABLE (reported): A1-5 and A1-20 also meet 1 and 3.
TRIALS: 4 (swing 87 → 91). No re-tuning after the run.

Run:  python earnings_lab.py            (Actions, ~30–60 min)
      python earnings_lab.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

VERSION = "1.0"
TOP_N, NEIGHBOURS = 10, (5, 20)
MIN_GROWTH = 0.25
LOOKBACK = (63, 126, 252)
COST_BPS = 10.0
START = pd.Timestamp("2011-01-01")
HALF_SPLIT = pd.Timestamp("2019-01-01")
HALVES = ("2011-18", "2019-26")
MAX_DD = -25.0
DATA_START = "2009-06-01"
PRIOR_SWING_TRIALS = 87
OUT_DATA, OUT_LOGS = Path("data/earnings_lab"), Path("logs/earnings_lab")


# ── earnings (point in time) ────────────────────────────────────────────────

def _yoy(k: pd.DataFrame, row) -> Optional[float]:
    prior = k[(k["end"] - (row["end"] - pd.DateOffset(years=1))).abs().dt.days <= 20]
    if prior.empty:
        return None
    p = float(prior.iloc[-1]["val"])
    if not p > 0:
        return None
    return float(row["val"]) / p - 1


def eps_accelerating(q: pd.DataFrame, asof: pd.Timestamp) -> bool:
    """q: one company's quarters (end, val, filed). Only filings made by `asof` are used."""
    if q is None or q.empty:
        return False
    k = q[q["filed"] <= asof].sort_values("end")
    k = k.drop_duplicates("end", keep="first")
    if len(k) < 2:
        return False
    last = k.iloc[-1]
    if (asof - last["end"]).days > 200 or not last["val"] > 0:
        return False
    g1 = _yoy(k, last)
    if g1 is None or g1 < MIN_GROWTH:
        return False
    prev = k[k["end"] < last["end"] - pd.Timedelta(days=45)]
    if prev.empty:
        return False
    g2 = _yoy(k, prev.iloc[-1])
    return g2 is not None and g1 > g2


def cik_at(lookup, t: str, d: pd.Timestamp, last_mapped: pd.Timestamp) -> Optional[int]:
    """Company number for member t at d. The SEC month map ends with the last insider data set
    (2026-03); after that the last known number is carried forward (members added later stay unmapped)."""
    c = lookup(t, d)
    if c is None and d > last_mapped:
        c = lookup(t, last_mapped)
    return c


# ── panels and selection ────────────────────────────────────────────────────

def month_end_index(cal: pd.DatetimeIndex) -> list:
    s = pd.Series(cal, index=cal)
    return list(s.groupby(cal.to_period("M")).max())


def tech_panel(close: pd.DataFrame) -> dict:
    """Trend and strength, each value using closes up to that day only."""
    s50, s200 = close.rolling(50, min_periods=50).mean(), close.rolling(200, min_periods=200).mean()
    trend = (close > s50) & (close > s200) & (s200 > s200.shift(20))
    strength = sum(close / close.shift(n) - 1 for n in LOOKBACK) / len(LOOKBACK)
    return {"trend": trend, "strength": strength}


def members_at(iv: dict, d: pd.Timestamp) -> list:
    return sorted(t for t, spans in iv.items() if any(a <= d and (b is None or d < b) for a, b in spans))


def select(d: pd.Timestamp, members: list, tp: dict, eps_ok: Optional[dict], n: int) -> list:
    """Top n eligible members at month-end d by strength. eps_ok None = no earnings condition (A0)."""
    tr, st = tp["trend"], tp["strength"]
    if d not in tr.index:
        return []
    row_t, row_s = tr.loc[d], st.loc[d]
    cand = []
    for t in members:
        if t not in row_t.index or not bool(row_t[t]) or not np.isfinite(row_s[t]):
            continue
        if eps_ok is not None and not eps_ok.get(t, False):
            continue
        cand.append((float(row_s[t]), t))
    cand.sort(key=lambda x: (-x[0], x[1]))
    return [t for _, t in cand[:n]]


# ── portfolio ───────────────────────────────────────────────────────────────

def backtest(picks: dict, opens: pd.DataFrame, close: pd.DataFrame, mkt_ok: dict, rate: pd.Series,
             n: int, mes: list) -> pd.DataFrame:
    """Monthly open-to-open. picks: {ME: [tickers]}. Weight 1/n each, rest in T-bills.
    Returns per period: start, end, ret, picks, worst (worst pick return)."""
    cal = opens.index
    rows, prev_w = [], {}
    for i, me in enumerate(mes[:-1]):
        k0 = cal.searchsorted(me, side="right")
        k1 = cal.searchsorted(mes[i + 1], side="right")
        if k0 >= len(cal) or k1 >= len(cal):
            break
        d0, d1 = cal[k0], cal[k1]
        p = picks.get(me, []) if mkt_ok.get(me, False) else []
        w = {t: 1.0 / n for t in p}
        rets = {}
        for t in p:
            o0 = opens[t].iloc[k0]
            o1 = opens[t].iloc[k1]
            if not np.isfinite(o1):                      # left the data mid-period: last close
                c = close[t].iloc[k0:k1 + 1].dropna()
                o1 = c.iloc[-1] if len(c) else o0
            rets[t] = float(o1 / o0 - 1) if np.isfinite(o0) and o0 > 0 else 0.0
        days = cal[k0:k1]
        cash_r = float(np.prod(1 + rate.reindex(days).ffill().fillna(0.0).to_numpy()) - 1)
        cash_w = 1.0 - sum(w.values())
        turn = sum(abs(w.get(t, 0.0) - prev_w.get(t, 0.0)) for t in set(w) | set(prev_w))
        r = sum(w[t] * rets[t] for t in p) + cash_w * cash_r - turn * COST_BPS / 1e4
        rows.append({"me": me, "start": d0, "end": d1, "ret": r, "n_picks": len(p),
                     "worst": min(rets.values()) if rets else np.nan, "picks": ",".join(p), "turnover": turn})
        prev_w = w
    return pd.DataFrame(rows)


def stats(periods: pd.DataFrame, col: str = "ret", a=None, b=None) -> dict:
    p = periods
    if a is not None:
        p = p[p["start"] >= a]
    if b is not None:
        p = p[p["start"] < b]
    if len(p) < 2:
        return {}
    nav = (1 + p[col]).cumprod()
    yrs = (p["end"].iloc[-1] - p["start"].iloc[0]).days / 365.25
    cagr = nav.iloc[-1] ** (1 / yrs) - 1
    dd = float((nav / nav.cummax() - 1).min())
    dd = min(dd, float(nav.iloc[0] - 1))
    return {"cagr_pct": round(cagr * 100, 2), "max_dd_pct": round(dd * 100, 1), "months": int(len(p))}


def windows(periods: pd.DataFrame, col: str = "ret") -> dict:
    return {"full": stats(periods, col, START), HALVES[0]: stats(periods, col, START, HALF_SPLIT),
            HALVES[1]: stats(periods, col, HALF_SPLIT)}


def judge(a1: dict, a0: dict, spy: dict) -> list:
    why = []
    for k in ("full", *HALVES):
        c, s = (a1.get(k) or {}).get("cagr_pct"), (spy.get(k) or {}).get("cagr_pct")
        if c is None or s is None or not c > s:
            why.append(f"{k} CAGR {c}% ≤ SPY {s}%")
    for k in HALVES:
        c, z = (a1.get(k) or {}).get("cagr_pct"), (a0.get(k) or {}).get("cagr_pct")
        if c is None or z is None or not c > z:
            why.append(f"{k} CAGR {c}% ≤ no-earnings control {z}%")
    d = (a1.get("full") or {}).get("max_dd_pct")
    if d is None or d < MAX_DD:
        why.append(f"max DD {d}% deeper than {MAX_DD}%")
    return why


def stressed(periods: pd.DataFrame, unpriced_share: dict, spy_ret: pd.Series) -> pd.DataFrame:
    """Harsh: the unpriced share u of each invested month earns that month's worst pick;
    neutral: earns SPY. Months in T-bills are unchanged."""
    p = periods.copy()
    u = p["me"].map(lambda m: unpriced_share.get(m, 0.0)).fillna(0.0)
    inv = p["n_picks"] > 0
    worst = p["worst"].fillna(0.0)
    p["harsh"] = np.where(inv, (1 - u) * p["ret"] + u * worst, p["ret"])
    p["neutral"] = np.where(inv, (1 - u) * p["ret"] + u * spy_ret.reindex(p.index).fillna(0.0), p["ret"])
    return p


# ── run ─────────────────────────────────────────────────────────────────────

def _f(x, nd=2):
    return "—" if x is None else f"{x:.{nd}f}"


def render(res: dict, spy: dict, verdict: str, why: list, robust: bool, stable: bool, cov: pd.DataFrame,
           notes: list, stamp: str, trials: str) -> str:
    L = [f"# Earnings lab {VERSION} — {stamp}", "",
         "Track A: earnings acceleration added to leadership. Rules and bar fixed before the run "
         "(claude/earnings_lab_2026-11-20.md). Research, not personalized advice.", "",
         f"## Verdict: **{verdict}**" + (f" — {'; '.join(why)}" if why else "")
         + f" · {'ROBUST' if robust else 'NOT ROBUST'} · {'STABLE' if stable else 'NOT STABLE'}", "",
         "| Book | CAGR 2011–26 | 2011–18 | 2019–26 | Max DD (month-end) | Avg picks | Avg turnover / month |",
         "|---|---|---|---|---|---|---|"]
    for k, r in res.items():
        w = r["w"]
        L.append(f"| {k} | {_f(w['full'].get('cagr_pct'))}% | {_f(w[HALVES[0]].get('cagr_pct'))}% | "
                 f"{_f(w[HALVES[1]].get('cagr_pct'))}% | {_f(w['full'].get('max_dd_pct'), 1)}% | "
                 f"{r['p']['n_picks'].mean():.1f} | {r['p']['turnover'].mean() * 100:.0f}% |")
    L.append(f"| SPY | {_f(spy['full'].get('cagr_pct'))}% | {_f(spy[HALVES[0]].get('cagr_pct'))}% | "
             f"{_f(spy[HALVES[1]].get('cagr_pct'))}% | {_f(spy['full'].get('max_dd_pct'), 1)}% | — | — |")
    a1 = res["A1"]
    L += ["", f"Missing-stock stress on A1: neutral {_f(a1['neutral']['full'].get('cagr_pct'))}%/yr, "
              f"harsh {_f(a1['harsh']['full'].get('cagr_pct'))}%/yr (SPY {_f(spy['full'].get('cagr_pct'))}%).", "",
          "Calendar years, A1 vs SPY (points): " + ", ".join(f"{y} {v:+.1f}" for y, v in a1["years"].items()), "",
          "## Price coverage of members (month-ends)", "", "| Year | Members | Priced % | Earnings-passing | Priced % |",
          "|---|---|---|---|---|"]
    L += [f"| {r.year} | {r.members} | {r.priced_pct} | {r.eps_pass} | {r.eps_priced_pct} |" for r in cov.itertuples()]
    L += ["", f"Latest picks (month-end {a1['latest'][0]}): {a1['latest'][1] or 'none (market filter or no eligible names)'}", "",
          "## Notes", ""] + [f"- {n}" for n in notes] + ["", f"Trials: {trials}.", "", f"*earnings_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def main() -> int:
    import edgar_data as ed
    import stock_lab as sl
    import swing_backtest as bt
    import universe_probe as up
    notes = []
    D = ed.load()
    mem, iv = sl.load_membership()
    members = sl.members_in_window(iv, START - pd.Timedelta(days=30))
    syms = sorted({up.yahoo_symbol(t) for t in members} | {v for k, v in up.RENAMES.items() if k in members} | {"SPY"})
    print(f"[earnings_lab] v{VERSION}: {len(members)} members since 2011; fetching {len(syms)} symbols")
    ohlcv = {}
    for i in range(0, len(syms), 150):
        ohlcv.update(bt.fetch_ohlcv(syms[i:i + 150], start=DATA_START))
        print(f"[earnings_lab] {min(i + 150, len(syms))}/{len(syms)} requested, {len(ohlcv)} with data")
    rates = bt.fetch_ohlcv(["^IRX"], start=DATA_START)
    if "SPY" not in ohlcv:
        print("[earnings_lab] DATA FAILURE: no SPY; nothing written.")
        return 1
    have = set(ohlcv)
    series = {t: ohlcv[sl.symbol_for(t, have)] for t in members if sl.symbol_for(t, have)}
    cal = ohlcv["SPY"].index
    close = pd.DataFrame({t: s["Close"] for t, s in series.items()}).reindex(cal)
    opens = pd.DataFrame({t: s["Open"] for t, s in series.items()}).reindex(cal)
    tp = tech_panel(close)
    spy_c = ohlcv["SPY"]["Close"]
    mkt = spy_c > spy_c.rolling(200).mean()
    irx = rates.get("^IRX")
    rate = (irx["Close"] / 100 / 252).clip(lower=0).reindex(cal).ffill().fillna(0.0) if irx is not None else pd.Series(0.0, index=cal)
    if irx is None:
        notes.append("^IRX missing: T-bills earn 0%.")
    mes = [m for m in month_end_index(cal) if m >= START - pd.Timedelta(days=31)]
    eps_by_cik = {int(c): g for c, g in D.eps.groupby("cik")}
    last_mapped = pd.Timestamp(year=int(D.months["month"].max()) // 12, month=int(D.months["month"].max()) % 12 + 1, day=1) \
        + pd.offsets.MonthEnd(0)
    notes.append(f"SEC company map runs to {last_mapped.date()}; later months carry each member's last known company number.")
    picks = {k: {} for k in ("A1", "A0", "A1-5", "A1-20")}
    unpriced, cov_rows = {}, []
    for me in mes:
        mem_now = members_at(iv, me)
        ok = {}
        for t in mem_now:
            c = cik_at(D.cik_for, t, me, last_mapped)
            ok[t] = eps_accelerating(eps_by_cik.get(c), me) if c is not None else False
        passing = [t for t in mem_now if ok[t]]
        priced_now = [t for t in mem_now if t in close.columns and np.isfinite(close.at[me, t])]
        pp = [t for t in passing if t in priced_now]
        unpriced[me] = (1 - len(pp) / len(passing)) if passing else 0.0
        cov_rows.append({"me": me, "members": len(mem_now), "priced": len(priced_now), "eps_pass": len(passing),
                         "eps_priced": len(pp)})
        picks["A1"][me] = select(me, mem_now, tp, ok, TOP_N)
        picks["A0"][me] = select(me, mem_now, tp, None, TOP_N)
        picks["A1-5"][me] = select(me, mem_now, tp, ok, 5)
        picks["A1-20"][me] = select(me, mem_now, tp, ok, 20)
    mkt_ok = {me: bool(mkt.get(me, False)) for me in mes}
    spy_frame = pd.DataFrame({"SPY": ohlcv["SPY"]["Open"]}).reindex(cal)
    spy_close = pd.DataFrame({"SPY": spy_c}).reindex(cal)
    spy_p = backtest({me: ["SPY"] for me in mes}, spy_frame, spy_close, {me: True for me in mes}, rate, 1, mes)
    spy_w = windows(spy_p)
    res = {}
    for k, n in (("A1", TOP_N), ("A0", TOP_N), ("A1-5", 5), ("A1-20", 20)):
        p = backtest(picks[k], opens, close, mkt_ok, rate, n, mes)
        res[k] = {"p": p, "w": windows(p)}
    a1 = res["A1"]
    sp = stressed(a1["p"], unpriced, spy_p["ret"])            # same month-ends, same row order
    a1["harsh"], a1["neutral"] = windows(sp, "harsh"), windows(sp, "neutral")
    yr = pd.DataFrame({"a": a1["p"].set_index("start")["ret"], "s": spy_p.set_index("start")["ret"]})
    yr = yr[yr.index >= START]
    ya = (1 + yr).groupby(yr.index.year).prod() - 1
    a1["years"] = ((ya["a"] - ya["s"]) * 100).round(1).to_dict()
    last_me = [m for m in mes if m in picks["A1"]][-1]
    a1["latest"] = (str(last_me.date()), ", ".join(picks["A1"][last_me]) if mkt_ok.get(last_me) else "")
    why = judge(a1["w"], res["A0"]["w"], spy_w)
    verdict = "PASS" if not why else "FAIL"
    hs = (a1["harsh"]["full"] or {}).get("cagr_pct")
    robust = not why and hs is not None and hs > (spy_w["full"].get("cagr_pct") or 99)
    stable = not why and all(
        not [x for x in judge(res[k]["w"], res["A0"]["w"], spy_w) if "control" not in x] for k in ("A1-5", "A1-20"))
    cov = pd.DataFrame(cov_rows)
    cov["year"] = cov["me"].dt.year
    cy = cov[cov["me"] >= START].groupby("year").sum(numeric_only=True)
    cy = pd.DataFrame({"year": cy.index, "members": (cy["members"] / cov.groupby("year").size().reindex(cy.index)).round(0).astype(int),
                       "priced_pct": (cy["priced"] / cy["members"] * 100).round(1),
                       "eps_pass": (cy["eps_pass"] / cov.groupby("year").size().reindex(cy.index)).round(0).astype(int),
                       "eps_priced_pct": (cy["eps_priced"] / cy["eps_pass"].clip(lower=1) * 100).round(1)})
    notes.append(f"{len(series)} of {len(members)} members since 2011 have free prices.")
    stamp = date.today().isoformat()
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_LOGS.mkdir(parents=True, exist_ok=True)
    tl = OUT_DATA / "trial_log.csv"
    first = not tl.exists()
    row = pd.DataFrame([{"date": stamp, "version": VERSION, "trials": 4 if first else 0,
                         "note": "A1, A0 control, A1 top-5 and top-20" if first else "re-run"}])
    (pd.concat([pd.read_csv(tl), row]) if tl.exists() else row).to_csv(tl, index=False)
    trials = f"4 new (swing {PRIOR_SWING_TRIALS} → {PRIOR_SWING_TRIALS + 4})" if first else "none new (re-run)"
    for k, r in res.items():
        r["p"].to_csv(OUT_DATA / f"periods_{k}.csv", index=False)
    cy.to_csv(OUT_DATA / "coverage.csv", index=False)
    (OUT_DATA / "summary.json").write_text(json.dumps(
        {"verdict": verdict, "why": why, "robust": robust, "stable": stable,
         "books": {k: r["w"] for k, r in res.items()}, "spy": spy_w,
         "a1_harsh": a1["harsh"], "a1_neutral": a1["neutral"]}, indent=1, default=str))
    md = render(res, spy_w, verdict, why, robust, stable, cy, notes, stamp, trials)
    (OUT_LOGS / f"{stamp}_report.md").write_text(md)
    (OUT_LOGS / "latest.md").write_text(md)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    f = []
    T = pd.Timestamp

    def q(rows):
        return pd.DataFrame([{"end": T(e), "val": v, "filed": T(fd)} for e, v, fd in rows])
    base = [("2013-03-31", 1.00, "2013-05-01"), ("2013-06-30", 1.00, "2013-08-01"),
            ("2014-03-31", 1.20, "2014-05-01"), ("2014-06-30", 1.40, "2014-08-01")]
    if not eps_accelerating(q(base), T("2014-08-31")):
        f.append("+40% after +20%: accelerating")
    if eps_accelerating(q(base), T("2014-07-31")):
        f.append("before the Q2 filing only +20% is known: not ≥ 25%")
    slow = [("2013-03-31", 1.00, "2013-05-01"), ("2013-06-30", 1.00, "2013-08-01"),
            ("2014-03-31", 1.50, "2014-05-01"), ("2014-06-30", 1.30, "2014-08-01")]
    if eps_accelerating(q(slow), T("2014-08-31")):
        f.append("+30% after +50%: growing but slowing, must fail")
    neg = [("2013-03-31", -1.0, "2013-05-01"), ("2013-06-30", 0.10, "2013-08-01"),
           ("2014-03-31", 0.50, "2014-05-01"), ("2014-06-30", 0.50, "2014-08-01")]
    if eps_accelerating(q(neg), T("2014-08-31")):
        f.append("a negative or tiny base year must not pass on its own")
    stale = base
    if eps_accelerating(q(stale), T("2015-06-30")):
        f.append("a latest quarter over 200 days old must fail")
    late = [r for r in base[:3]] + [("2014-06-30", 1.40, "2015-03-01")]
    if eps_accelerating(q(late), T("2014-08-31")):
        f.append("a quarter filed after the as-of date must not be used")
    small = [("2013-03-31", 1.00, "2013-05-01"), ("2013-06-30", 1.00, "2013-08-01"),
             ("2014-03-31", 1.10, "2014-05-01"), ("2014-06-30", 1.20, "2014-08-01")]
    if eps_accelerating(q(small), T("2014-08-31")):
        f.append("+20% after +10%: accelerating but under 25%, must fail")
    if eps_accelerating(None, T("2014-08-31")) or eps_accelerating(q(base[:1]), T("2014-08-31")):
        f.append("no data -> fails")
    # selection
    idx = pd.bdate_range("2012-01-02", periods=320)
    n = len(idx)
    up_fast = pd.Series(np.linspace(50, 150, n), index=idx)
    up_slow = pd.Series(np.linspace(50, 80, n), index=idx)
    down = pd.Series(np.linspace(150, 60, n), index=idx)
    close = pd.DataFrame({"F": up_fast, "S": up_slow, "D": down, "X": up_fast * 1.0})
    close.loc[idx[-1], "X"] = np.nan
    tp = tech_panel(close)
    d = idx[-1]
    sel = select(d, ["F", "S", "D", "X"], tp, None, 2)
    if sel != ["F", "S"]:
        f.append(f"downtrends excluded, unpriced excluded, ranked by strength: {sel}")
    if select(d, ["F", "S", "D"], tp, {"F": False, "S": True}, 2) != ["S"]:
        f.append("the earnings condition removes F")
    if select(d, ["S", "D"], tp, None, 2) != ["S"] or select(d, ["F"], tp, None, 1, ) != ["F"]:
        f.append("only members passed in are eligible")
    s = tech_panel(close)["strength"]
    exp = np.mean([up_fast.iloc[-1] / up_fast.iloc[-1 - k] - 1 for k in LOOKBACK])
    if abs(s["F"].iloc[-1] - exp) > 1e-12:
        f.append("strength = mean of 3/6/12-month returns")
    v = np.r_[np.full(250, 100.0), np.linspace(100, 40, 150), np.linspace(40, 120, 20)]
    vt = tech_panel(pd.DataFrame({"V": v}, index=pd.bdate_range("2012-01-02", periods=len(v))))["trend"]["V"]
    if vt.iloc[-1]:
        f.append("a spike above a FALLING 200-day is not a trend")
    if tp["trend"]["F"].iloc[150]:
        f.append("no trend reading before 200 + 20 sessions of history")
    lk = lambda t, d: {("A", T("2026-03-31")): 7}.get((t, d))
    if cik_at(lk, "A", T("2026-07-31"), T("2026-03-31")) != 7 or cik_at(lk, "A", T("2025-07-31"), T("2026-03-31")) is not None:
        f.append("company number carried forward only after the map ends")
    # members_at
    iv = {"A": [(T("2010-01-01"), T("2013-01-01"))], "B": [(T("2012-06-01"), None)]}
    if members_at(iv, T("2012-12-31")) != ["A", "B"] or members_at(iv, T("2013-01-01")) != ["B"]:
        f.append("membership end date is exclusive")
    # backtest: one pick, open to open, costs, T-bills for the rest, market filter
    cal = pd.bdate_range("2014-01-01", "2014-04-30")
    mes = month_end_index(cal)
    op = pd.DataFrame({"A": np.linspace(100, 130, len(cal))}, index=cal)
    cl = op.copy()
    rate = pd.Series(0.0001, index=cal)
    bt0 = backtest({mes[0]: ["A"], mes[1]: ["A"]}, op, cl, {mes[0]: True, mes[1]: False}, rate, 2, mes)
    k0, k1 = cal.searchsorted(mes[0], side="right"), cal.searchsorted(mes[1], side="right")
    ra = op["A"].iloc[k1] / op["A"].iloc[k0] - 1
    cash = (1.0001 ** (k1 - k0)) - 1
    exp0 = 0.5 * ra + 0.5 * cash - 0.5 * COST_BPS / 1e4
    if abs(bt0["ret"].iloc[0] - exp0) > 1e-12:
        f.append(f"period return: half in the pick, half in T-bills, cost on turnover: {bt0['ret'].iloc[0]} vs {exp0}")
    k2 = cal.searchsorted(mes[2], side="right")
    exp1 = (1.0001 ** (k2 - k1)) - 1 - 0.5 * COST_BPS / 1e4
    if abs(bt0["ret"].iloc[1] - exp1) > 1e-12 or bt0["n_picks"].iloc[1] != 0:
        f.append("market filter closed: all T-bills, selling costs paid")
    if bt0["start"].iloc[0] != cal[k0] or bt0["start"].iloc[0] <= mes[0]:
        f.append("trade at the first open after the month-end")
    gone = op.copy()
    gone.iloc[k0 + 5:, 0] = np.nan
    cl2 = gone.copy()
    bt1 = backtest({mes[0]: ["A"]}, gone, cl2, {mes[0]: True}, rate, 1, mes[:2])
    if abs(bt1["ret"].iloc[0] - (gone["A"].iloc[k0 + 4] / gone["A"].iloc[k0] - 1 - COST_BPS / 1e4)) > 1e-12:
        f.append("a pick that leaves the data mid-period exits at its last close")
    # judge and stress
    w = lambda full, h1, h2, dd: {"full": {"cagr_pct": full, "max_dd_pct": dd}, HALVES[0]: {"cagr_pct": h1}, HALVES[1]: {"cagr_pct": h2}}
    spy = w(12.0, 11.0, 13.0, -24.0)
    if judge(w(14, 12, 15, -20), w(13, 11.5, 14, -22), spy):
        f.append("a clean candidate passes")
    if not judge(w(14, 10.5, 15, -20), w(13, 10, 14, -22), spy) or not judge(w(14, 12, 15, -20), w(13, 12.5, 14, -22), spy) \
            or not judge(w(14, 12, 15, -26), w(13, 11.5, 14, -22), spy):
        f.append("each clause of the bar can fail on its own")
    per = pd.DataFrame({"me": [T("2014-01-31"), T("2014-02-28")], "ret": [0.05, 0.0], "n_picks": [10, 0], "worst": [-0.2, np.nan]})
    stp = stressed(per, {T("2014-01-31"): 0.3, T("2014-02-28"): 0.5}, pd.Series([0.01, 0.01]))
    if abs(stp["harsh"].iloc[0] - (0.7 * 0.05 + 0.3 * -0.2)) > 1e-12 or stp["harsh"].iloc[1] != 0.0:
        f.append(f"harsh stress: unpriced share earns the worst pick; T-bill months unchanged: {stp['harsh'].tolist()}")
    nav = pd.DataFrame({"start": pd.date_range("2011-01-03", periods=24, freq="MS"),
                        "end": pd.date_range("2011-02-01", periods=24, freq="MS"), "ret": [0.01] * 24})
    st = stats(nav, "ret", START)
    if abs(st["cagr_pct"] - round(((1.01 ** 24) ** (365.25 / (nav['end'].iloc[-1] - nav['start'].iloc[0]).days) - 1) * 100, 2)) > 1e-9:
        f.append("CAGR over the measured span")
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
