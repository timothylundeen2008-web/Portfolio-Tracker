"""
refine_lab.py  (v1.0 — 2026-11-17)
──────────────────────────────────
SWING BOOK ONLY. Can the stock setups be fixed with rules that have a reason,
judged on years the fixes were not built on? (stock_lab results 2026-11-17;
Matt: "complete 1 first", 2026-11-17.)

WHY THESE FOUR CHANGES — from the stock_lab v1.0 trades (run 61bf3f5), no
new trials spent:
  * 73% of 2-of-3 M0 stock trades were entered with the stock's sector
    already Weakening/Lagging and sold by the sector-rotation ("thesis") exit
    within three days, at about 0R: the entry and exit rules contradict each
    other (fix_status N74; production swing_exits has the same pair).
  * The edge sits in long holds: M0 trades held 60+ days averaged +3.2R,
    those held 4-30 days lost 0.3-0.6R. M1: +4.9R past 60 days.
  * The losing years were 2018, 2022 and 2025: choppy or falling markets in
    which SPY sat above its 200-day much of the time.

THE RULE SETS — frozen 2026-11-17, before any run
  V0     the live rules (stock_lab v1.0). Reference; not a new trial.
  H1     rotation leg REQUIRED at entry (sector Improving or Leading).
  H2     no sector-rotation exit; trades end on the closing-basis stop, the
         disaster stop, the trail MA rule or the ladder.
  H12    H1 + H2.
  H123   H12 + a faster market filter: a new entry also needs SPY to close
         above its 50-day average (on top of the 200-day rule).
  H1234  H123, leaders only (leader_screen rules, recomputed every day).
  Setups: M0 Rotation Reclaim and M1 VCP. (M2 fires too rarely to judge;
  PG lost in both halves of stock_lab and is not revisited.)
  New trials: 5 rule sets x 2 setups = 10. Swing trials 66 -> 76.

DEVELOPMENT / HOLDOUT — fixed before any run
  Development  signals 2017-01-01 .. 2021-12-31. Choices are made here only.
  Holdout      signals 2022-01-01 onward. Used once, for the verdict.
  Selection    per setup, among V0 and the five rule sets: eligible if
               development has 50+ closed trades, expectancy above 0 and
               profit factor 1.3+. The eligible set with the most R per year
               in development is SELECTED (R per year ~ return at fixed risk).
               No eligible set: the setup FAILS without looking at holdout.
  Verdict      the selected set, on holdout: PASS = 30+ closed trades,
               expectancy above 0, profit factor 1.3+. ROBUST PASS = also above
               0 under the harsh missing-stock stress on holdout years.
  Beats SPY    reported label: the $10k book (live sizing) earns more per year
               than SPY over the holdout.
  ETF guard    the desk's rules are shared by ETFs and stocks, so the selected
               rule set (without the leader filter, which is stock-only) is
               also run for M0 on the ETF universe 2005-2026. It must still
               meet the existing ETF bar (100+ trades, 30+ per half,
               expectancy > 0 and PF 1.3+ in 2005-15 and 2016-26). If it does
               not, the change may apply to stock cards only.
  Holdout figures for every rule set are printed for transparency, marked
  "not used for the verdict".

WHAT FOLLOWS (decided before the run)
  ROBUST PASS  the rule set goes to paper trading on stock cards at half risk,
               and the production change is put to Matt. Stock cards stay
               paper-only until then (Matt, 2026-11-17).
  PASS         paper trading at half risk only after Matt's review.
  FAIL         recorded; stock cards stay paper-only; no further tuning on
               this window.

LIMITS: as stock_lab (ten years, no 2008, no earnings history, today's
sectors, no 0.25 x ATR limit), plus: the development half has five years.

Run:  python refine_lab.py            (Actions: needs network; 30-90 minutes)
      python refine_lab.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import stock_lab as sl
import swing_backtest as bt
import universe_probe as up

VERSION = "1.0"
DEV_END = pd.Timestamp("2022-01-01")        # development: entries before this date
SETUPS = ("M0", "M1")
RULESETS = {                                 # rot = rotation leg required; thesis = sector exit on;
    "V0":    {"rot": False, "thesis": True,  "fast": False, "leaders": False},   # fast = SPY > 50-day
    "H1":    {"rot": True,  "thesis": True,  "fast": False, "leaders": False},
    "H2":    {"rot": False, "thesis": False, "fast": False, "leaders": False},
    "H12":   {"rot": True,  "thesis": False, "fast": False, "leaders": False},
    "H123":  {"rot": True,  "thesis": False, "fast": True,  "leaders": False},
    "H1234": {"rot": True,  "thesis": False, "fast": True,  "leaders": True},
}
NEW_TRIALS = len(SETUPS) * (len(RULESETS) - 1)
SEL = {"min_trades": 50, "min_pf": 1.3}
HOLD = {"min_trades": 30, "min_pf": 1.3}
FAST_SMA = 50
ETF_START = "2004-01-01"
OUT_DATA = Path("data/refine_lab")
OUT_LOGS = Path("logs/refine_lab")
PRIOR_SWING_TRIALS = 66                      # swing_backtest 59 + stock_lab 7


# ── preparation ─────────────────────────────────────────────────────────────

def fast_ok(spy_close: pd.Series) -> pd.Series:
    """True where SPY closed above its 50-day average. Trailing data only."""
    return (spy_close > spy_close.rolling(FAST_SMA).mean()).fillna(False)


def prepare_stocks(ohlcv: dict, iv: dict, sector_of: dict, verbose: bool = True) -> dict:
    """Signals and trade data for M0 and M1 on point-in-time members, exactly as stock_lab builds them,
    plus `leader` and `fast` flags on each signal."""
    spy = ohlcv["SPY"]
    cal = pd.DatetimeIndex(spy.index)
    bench = spy["Close"]
    mkt, fast = bt.market_ok(bench), fast_ok(bench)
    quads_by_sector = bt.rotation_proxy({k: v["Close"] for k, v in ohlcv.items()})
    have = set(ohlcv)
    members = sl.members_in_window(iv, sl.TEST_START)
    series = {t: ohlcv[sl.symbol_for(t, have)] for t in members if sl.symbol_for(t, have)}
    masks = {t: sl.member_mask(pd.DatetimeIndex(df.index), iv[t]) for t, df in series.items()}
    cov = sl.coverage_by_year(iv, series, cal)
    uncovered = {int(r.year): 1 - r.covered_pct / 100 for r in cov.itertuples()}
    leaders = sl.leader_panel(series, masks, cal)
    data, signals = {}, []
    for i, (tk, df) in enumerate(sorted(series.items())):
        idx = pd.DatetimeIndex(df.index)
        mk = mkt.reindex(idx).ffill().fillna(False).to_numpy(dtype=bool)
        fk = fast.reindex(idx).ffill().fillna(False).to_numpy(dtype=bool)
        allowed = sl.allowed_mask(idx, masks[tk], mk)
        q = quads_by_sector.get(sector_of.get(tk)) if sector_of.get(tk) else None
        sig, x = sl.build_signals(tk, df, bench, q, allowed)
        lead = leaders[tk].reindex(idx).fillna(False).to_numpy(dtype=bool) if tk in leaders else np.zeros(len(idx), bool)
        for s in sig:
            s.leader, s.fast, s.mkt_ok = bool(lead[s.t]), bool(fk[s.t]), True
        data[tk] = _data(df, x, q, cal, "stock")
        signals.extend(s for s in sig if s.setup in SETUPS)
        if verbose and (i + 1) % 50 == 0:
            print(f"[refine_lab] {i + 1}/{len(series)} stocks, {len(signals)} M0/M1 signals")
    return {"signals": signals, "data": data, "cal": cal, "end": cal[-1], "uncovered": uncovered,
            "coverage": cov, "members": len(members), "priced": len(series), "spy": bench}


def _data(df: pd.DataFrame, x: pd.DataFrame, q: Optional[pd.Series], cal: pd.DatetimeIndex, asset: str) -> dict:
    idx = pd.DatetimeIndex(df.index)
    arr = {k: df[k].to_numpy(dtype=float, copy=True) for k in ("Open", "High", "Low", "Close")}
    for col in ("atr14", "sma5", "ema5", "ema10", "sma50", "sma100"):
        arr[col] = x[col].to_numpy(dtype=float, copy=True)
    return {"arr": arr, "quads": q.reindex(idx).to_numpy() if q is not None else None, "index": idx,
            "asset": asset, "close_cal": df["Close"].reindex(cal).ffill()}


def prepare_etfs(ohlcv: dict, verbose: bool = True) -> dict:
    """M0 signals on the swing_backtest ETF universe, 2005 onward, with the 200-day market filter
    applied at the signal (as live) and the `fast` flag attached."""
    etfs, _stocks, sector_of = bt.universe()
    spy = ohlcv["SPY"]
    cal = pd.DatetimeIndex(spy.index)
    bench = spy["Close"]
    mkt, fast = bt.market_ok(bench), fast_ok(bench)
    quads_by_sector = bt.rotation_proxy({k: v["Close"] for k, v in ohlcv.items()})
    data, signals = {}, []
    for tk in sorted(t for t in etfs if t in ohlcv):
        df = ohlcv[tk]
        idx = pd.DatetimeIndex(df.index)
        x = bt.indicators(df, bench)
        pf = bt.prefilters(df, x)
        mk = mkt.reindex(idx).ffill().fillna(False).to_numpy(dtype=bool)
        fk = fast.reindex(idx).ffill().fillna(False).to_numpy(dtype=bool)
        pf["M0"] = pf["M0"] & mk
        for s_ in ("M1", "M2", "M2c", "PB"):
            pf[s_] = np.zeros(len(df), dtype=bool)
        sec = sector_of.get(tk)
        q = quads_by_sector.get(sec) if sec else None
        sig = bt.signals_for_ticker(tk, df, x, pf, bench, q, True, setups=("M0",))
        for s in sig:
            s.leader, s.fast, s.mkt_ok = False, bool(fk[s.t]), True
        data[tk] = _data(df, x, q, cal, bt._asset(tk, True))
        signals.extend(sig)
    if verbose:
        print(f"[refine_lab] ETF universe: {len(data)} ETFs, {len(signals)} M0 signals")
    return {"signals": signals, "data": data, "cal": cal, "end": cal[-1], "sector_of": sector_of}


# ── rule sets ───────────────────────────────────────────────────────────────

def keep(sig, rules: dict) -> bool:
    """Entry rules of a rule set, applied to a signal."""
    if rules["rot"] and not sig.rot_ok:
        return False
    if rules["fast"] and not getattr(sig, "fast", False):
        return False
    if rules["leaders"] and not getattr(sig, "leader", False):
        return False
    return True


def trades_under(signals: list, data: dict, setup: str, rules: dict, end: pd.Timestamp) -> tuple:
    """Trades for one setup under one rule set. One open trade per stock and setup at a time.
    thesis=False removes the sector-rotation exit (the simulator reads sector quadrants only for it)."""
    trades, unfilled, busy = [], [], {}
    for sg in sorted((s for s in signals if s.setup == setup and keep(s, rules)), key=lambda z: (z.ticker, z.t)):
        if sg.t + 1 <= busy.get(sg.ticker, -1):
            continue
        d = data[sg.ticker]
        if not rules["thesis"]:
            d = {**d, "quads": None}
        tr = sl.simulate(sg, d, d["index"][-1] >= end)
        if tr is None:
            unfilled.append(sg)
        else:
            tr.leader = bool(getattr(sg, "leader", False))
            trades.append(tr)
            busy[sg.ticker] = tr.exit_t
    return trades, unfilled


def _date(tr, data) -> pd.Timestamp:
    return data[tr.ticker]["index"][tr.entry_t]


def split_stats(trades: list, data: dict, split: pd.Timestamp) -> dict:
    closed = [t for t in trades if not t.still_open]
    dev = [t.r_net for t in closed if _date(t, data) < split]
    hold = [t.r_net for t in closed if _date(t, data) >= split]
    return {"dev": bt.trade_stats(dev), "hold": bt.trade_stats(hold), "full": bt.trade_stats(dev + hold)}


def r_per_year(stats: dict, years: float) -> float:
    n, e = stats.get("n", 0), stats.get("expectancy_R")
    return round(n * e / years, 2) if n and e is not None else 0.0


def eligible(dev: dict) -> tuple:
    why = []
    if dev.get("n", 0) < SEL["min_trades"]:
        why.append(f"{dev.get('n', 0)} development trades < {SEL['min_trades']}")
    if (dev.get("expectancy_R") or 0) <= 0:
        why.append(f"development expectancy {dev.get('expectancy_R')}R <= 0")
    if (dev.get("profit_factor") or 0) < SEL["min_pf"]:
        why.append(f"development PF {dev.get('profit_factor')} < {SEL['min_pf']}")
    return (not why), "; ".join(why)


def select(rows: list) -> Optional[dict]:
    """rows: [{name, dev, dev_r_per_year, ...}] for ONE setup. The eligible row with the most
    development R per year; ties go to the simpler rule set (earlier in RULESETS)."""
    order = list(RULESETS)
    ok = [r for r in rows if eligible(r["dev"])[0]]
    if not ok:
        return None
    return sorted(ok, key=lambda r: (-r["dev_r_per_year"], order.index(r["name"])))[0]


def holdout_verdict(hold: dict, harsh: Optional[float]) -> tuple:
    why = []
    if hold.get("n", 0) < HOLD["min_trades"]:
        why.append(f"{hold.get('n', 0)} holdout trades < {HOLD['min_trades']}")
    if (hold.get("expectancy_R") or 0) <= 0:
        why.append(f"holdout expectancy {hold.get('expectancy_R')}R <= 0")
    if (hold.get("profit_factor") or 0) < HOLD["min_pf"]:
        why.append(f"holdout PF {hold.get('profit_factor')} < {HOLD['min_pf']}")
    if why:
        return "FAIL", "; ".join(why)
    if harsh is not None and harsh > 0:
        return "ROBUST PASS", "meets the holdout bar and survives the harsh missing-stock stress"
    return "PASS", f"meets the holdout bar; harsh stress gives {harsh}R"


def etf_guard(trades: list, data: dict) -> tuple:
    """The existing ETF bar (swing_backtest.BAR, halves split 2016) for M0 on ETFs."""
    closed = [t for t in trades if not t.still_open]
    halves = {"2005-15": [t.r_net for t in closed if _date(t, data) < bt.HALF_SPLIT],
              "2016-26": [t.r_net for t in closed if _date(t, data) >= bt.HALF_SPLIT]}
    st = {k: bt.trade_stats(v) for k, v in halves.items()}
    why = []
    if len(closed) < bt.BAR["min_trades"]:
        why.append(f"{len(closed)} trades < {bt.BAR['min_trades']}")
    for k, s in st.items():
        if s.get("n", 0) < bt.BAR["min_per_half"]:
            why.append(f"{k}: {s.get('n', 0)} trades")
        else:
            if (s.get("expectancy_R") or 0) <= 0:
                why.append(f"{k} expectancy {s.get('expectancy_R')}R")
            if (s.get("profit_factor") or 0) < bt.BAR["min_pf"]:
                why.append(f"{k} PF {s.get('profit_factor')}")
    return (not why), ("meets the ETF bar" if not why else "; ".join(why)), st


def book(trades: list, unfilled: list, prep: dict, sector_of: dict, split: pd.Timestamp) -> dict:
    p = bt.run_portfolio(trades, unfilled, prep["data"], prep["cal"], sector_of)
    eq = p["equity"]
    dev, hold = eq[(eq.index >= sl.TEST_START) & (eq.index < split)], eq[eq.index >= split]
    return {"dev": bt.series_stats(dev), "hold": bt.series_stats(hold),
            "full": bt.series_stats(eq[eq.index >= sl.TEST_START]),
            "hwm_breach": bool(((eq / eq.cummax() - 1) <= -0.20).any()), "exposure": p["exposure_avg_pct"]}


# ── experiment ──────────────────────────────────────────────────────────────

def experiment(prep: dict, sector_of: dict, etf_prep: Optional[dict] = None, portfolio: bool = True) -> dict:
    dev_years = (DEV_END - sl.TEST_START).days / 365.25
    rows = []
    for setup in SETUPS:
        for name, rules in RULESETS.items():
            trs, unf = trades_under(prep["signals"], prep["data"], setup, rules, prep["end"])
            ss = split_stats(trs, prep["data"], DEV_END)
            hold_by_year: dict = {}
            for t in trs:
                if not t.still_open and _date(t, prep["data"]) >= DEV_END:
                    hold_by_year.setdefault(int(_date(t, prep["data"]).year), []).append(t.r_net)
            st = sl.stress(hold_by_year, prep["uncovered"])
            row = {"setup": setup, "name": name, **rules, "dev": ss["dev"], "hold": ss["hold"], "full": ss["full"],
                   "dev_r_per_year": r_per_year(ss["dev"], dev_years), "hold_harsh_R": st.get("harsh_exp_R"),
                   "eligible": eligible(ss["dev"])[0], "eligible_why": eligible(ss["dev"])[1],
                   "_trades": trs, "_unfilled": unf}
            if portfolio:
                row["book"] = book(trs, unf, prep, sector_of, DEV_END)
            rows.append(row)
    spy = prep["spy"]
    spy_hold = bt.series_stats(spy[spy.index >= DEV_END])
    spy_dev = bt.series_stats(spy[(spy.index >= sl.TEST_START) & (spy.index < DEV_END)])
    verdicts = []
    for setup in SETUPS:
        mine = [r for r in rows if r["setup"] == setup]
        pick = select(mine)
        if pick is None:
            verdicts.append({"setup": setup, "selected": None, "verdict": "FAIL",
                             "why": "no rule set met the development bar; holdout not used", "beats_spy": None,
                             "etf_guard": None, "etf_why": ""})
            continue
        v, why = holdout_verdict(pick["hold"], pick["hold_harsh_R"])
        bk = pick.get("book") or {}
        beats = None
        if bk.get("hold", {}).get("cagr_pct") is not None and spy_hold.get("cagr_pct") is not None:
            beats = bk["hold"]["cagr_pct"] > spy_hold["cagr_pct"]
        g_ok, g_why = None, ""
        rules = {k: pick[k] for k in ("rot", "thesis", "fast")} | {"leaders": False}
        if etf_prep is not None and pick["name"] != "V0":
            et, _ = trades_under(etf_prep["signals"], etf_prep["data"], "M0", rules, etf_prep["end"])
            g_ok, g_why, _st = etf_guard(et, etf_prep["data"])
        verdicts.append({"setup": setup, "selected": pick["name"], "verdict": v, "why": why, "beats_spy": beats,
                         "etf_guard": g_ok, "etf_why": g_why or ("unchanged live rules" if pick["name"] == "V0" else "")})
    return {"rows": rows, "verdicts": verdicts, "spy_hold": spy_hold, "spy_dev": spy_dev}


# ── report ──────────────────────────────────────────────────────────────────

_f = sl._f
LABEL = {"V0": "live rules", "H1": "rotation required", "H2": "no rotation exit", "H12": "H1 + H2",
         "H123": "H12 + SPY > 50-day", "H1234": "H123, leaders only"}


def render(out: dict, prep: dict, sec_note: str, stamp: str, before: int) -> str:
    L = [f"# Setup refinement test — {stamp} (refine_lab v{VERSION})", "",
         "Swing book only. Point-in-time S&P 500 members. Rule sets chosen on **2017–2021** only; "
         "judged once on **2022 onward**.", "",
         "## Verdicts", "", "| Setup | Rule set chosen on 2017–21 | Holdout verdict | Why | Book beats SPY 2022+ | ETF guard |",
         "|---|---|---|---|---|---|"]
    for v in out["verdicts"]:
        sel = f"{v['selected']} ({LABEL[v['selected']]})" if v["selected"] else "none eligible"
        g = "—" if v["etf_guard"] is None else ("holds" if v["etf_guard"] else "**fails**")
        b = "—" if v["beats_spy"] is None else ("**yes**" if v["beats_spy"] else "no")
        L.append(f"| {v['setup']} | {sel} | **{v['verdict']}** | {v['why']} | {b} | {g}: {v['etf_why']} |")
    L += ["", "## Development 2017–2021 (where the choice was made)", "",
          "| Setup | Rule set | Trades | Win % | Exp (R) | PF | R per year | Eligible |", "|---|---|---|---|---|---|---|---|"]
    for r in out["rows"]:
        d = r["dev"]
        L.append(f"| {r['setup']} | {r['name']} ({LABEL[r['name']]}) | {d.get('n', 0)} | {_f(d.get('win_rate'), 1)} | "
                 f"{_f(d.get('expectancy_R'), 3)} | {_f(d.get('profit_factor'))} | {_f(r['dev_r_per_year'], 1)} | "
                 f"{'yes' if r['eligible'] else 'no — ' + r['eligible_why']} |")
    L += ["", "## Holdout 2022 onward — every rule set, NOT used for the verdict", "",
          "| Setup | Rule set | Trades | Exp (R) | PF | Harsh stress (R) |", "|---|---|---|---|---|---|"]
    for r in out["rows"]:
        h = r["hold"]
        L.append(f"| {r['setup']} | {r['name']} | {h.get('n', 0)} | {_f(h.get('expectancy_R'), 3)} | "
                 f"{_f(h.get('profit_factor'))} | {_f(r['hold_harsh_R'], 3)} |")
    if out["rows"] and "book" in out["rows"][0]:
        L += ["", "## As a $10,000 book (live sizing, 1% / 0.5% risk, idle cash earning nothing)", "",
              "| Setup | Rule set | 2017–21 / yr | 2022+ / yr | Worst drawdown (all) | Avg invested | −20% breach |",
              "|---|---|---|---|---|---|---|"]
        for r in out["rows"]:
            b = r["book"]
            L.append(f"| {r['setup']} | {r['name']} | {_f(b['dev'].get('cagr_pct'), 2, '%')} | "
                     f"{_f(b['hold'].get('cagr_pct'), 2, '%')} | {_f(b['full'].get('max_dd_pct'), 1, '%')} | "
                     f"{_f(b['exposure'], 0, '%')} | {'YES' if b['hwm_breach'] else 'no'} |")
        L += ["", f"SPY: {_f(out['spy_dev'].get('cagr_pct'), 2, '%')} a year in 2017–21, "
                  f"{_f(out['spy_hold'].get('cagr_pct'), 2, '%')} a year from 2022."]
    L += ["", "## How the chosen sets' trades ended (all years)", ""]
    for v in out["verdicts"]:
        if not v["selected"]:
            continue
        r = next(x for x in out["rows"] if x["setup"] == v["setup"] and x["name"] == v["selected"])
        mix = pd.Series([t.exit_reason for t in r["_trades"] if not t.still_open]).value_counts()
        L.append(f"- {v['setup']} {v['selected']}: " + "; ".join(f"{k} {n}" for k, n in mix.items()))
    L += ["", "## Data", "",
          f"- {prep['members']} members since 2017; {prep['priced']} priced. {sec_note}.",
          "- Holdout coverage: " + ", ".join(f"{int(x.year)} {x.covered_pct}%" for x in prep["coverage"].itertuples()
                                            if x.year >= DEV_END.year) + ".",
          "", "## Limits", "",
          "- Ten years, one long bull market with three sharp falls; no 2008. Five development years.",
          "- No earnings history; sectors are today's; the 0.25×ATR entry limit is not modelled.",
          "- The ETF guard re-runs M0 on ETFs 2005–2026 with the chosen rules (leader filter excluded).", "",
          f"Trials: {NEW_TRIALS} new in this run; {before + NEW_TRIALS} swing trials to date.", ""]
    return "\n".join(L)


def flat_rows(out: dict) -> pd.DataFrame:
    rows = []
    for r in out["rows"]:
        x = {k: r[k] for k in ("setup", "name", "rot", "thesis", "fast", "leaders", "dev_r_per_year",
                                "hold_harsh_R", "eligible", "eligible_why")}
        for part in ("dev", "hold", "full"):
            x.update({f"{part}_{k}": v for k, v in r[part].items()})
        if "book" in r:
            for part in ("dev", "hold", "full"):
                x.update({f"book_{part}_{k}": v for k, v in r["book"][part].items()})
            x["book_hwm_breach"] = r["book"]["hwm_breach"]
            x["book_exposure_pct"] = r["book"]["exposure"]
        rows.append(x)
    return pd.DataFrame(rows)


def prior_trials() -> int:
    try:
        return int(pd.read_csv(OUT_DATA / "trial_log.csv")["trials"].sum())
    except Exception:
        return 0


def main() -> int:
    mem, iv = sl.load_membership()
    members = sl.members_in_window(iv, sl.TEST_START)
    syms = sorted({up.yahoo_symbol(t) for t in members} | {v for k, v in up.RENAMES.items() if k in members}
                  | set(bt.SECTOR_ETFS) | {"SPY"})
    print(f"[refine_lab] v{VERSION}: {len(members)} members; fetching {len(syms)} symbols from {sl.DATA_START}")
    ohlcv = {}
    for i in range(0, len(syms), 150):
        ohlcv.update(bt.fetch_ohlcv(syms[i:i + 150], start=sl.DATA_START))
        print(f"[refine_lab] {min(i + 150, len(syms))}/{len(syms)} requested, {len(ohlcv)} with data")
    if "SPY" not in ohlcv or sum(1 for e in bt.SECTOR_ETFS if e in ohlcv) < 9:
        print("[refine_lab] DATA FAILURE: SPY or the sector ETFs are missing; nothing written.")
        return 1
    have = set(ohlcv)
    priced = [t for t in members if sl.symbol_for(t, have)]
    if len(priced) < 0.6 * len(members):
        print(f"[refine_lab] DATA FAILURE: prices for only {len(priced)} of {len(members)}; nothing written.")
        return 1
    sector_of, sec_note = sl.sector_map(priced, lookup=sl.yahoo_sector)
    print(f"[refine_lab] {sec_note}")
    prep = prepare_stocks(ohlcv, iv, sector_of)
    etfs, _s, _sec = bt.universe()
    etf_ohlcv = bt.fetch_ohlcv(sorted(set(etfs) | {"SPY"}), start=ETF_START)
    etf_prep = prepare_etfs(etf_ohlcv) if "SPY" in etf_ohlcv and len(etf_ohlcv) >= 15 else None
    if etf_prep is None:
        print("[refine_lab] ETF history incomplete: the ETF guard will read 'not run'.")
    out = experiment(prep, sector_of, etf_prep)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_LOGS.mkdir(parents=True, exist_ok=True)
    before = PRIOR_SWING_TRIALS + prior_trials()
    flat_rows(out).to_csv(OUT_DATA / "results.csv", index=False)
    pd.DataFrame(out["verdicts"]).to_csv(OUT_DATA / "verdicts.csv", index=False)
    tl = OUT_DATA / "trial_log.csv"
    first = prior_trials() == 0
    row = pd.DataFrame([{"date": stamp, "version": VERSION, "trials": NEW_TRIALS if first else 0,
                         "note": "5 rule sets x M0, M1" if first else "re-run of the same rule sets"}])
    (pd.concat([pd.read_csv(tl), row]) if tl.exists() else row).to_csv(tl, index=False)
    md = render(out, prep, sec_note, stamp, PRIOR_SWING_TRIALS + (0 if first else NEW_TRIALS))
    (OUT_LOGS / f"{stamp}_report.md").write_text(md)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

class _S:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def selftest() -> dict:
    f = []
    # entry rules
    base = dict(rot_ok=True, fast=True, leader=True)
    for name, rules in RULESETS.items():
        if not keep(_S(**base), rules):
            f.append(f"{name}: a signal meeting every condition must be kept")
    if keep(_S(**{**base, "rot_ok": False}), RULESETS["H1"]) or not keep(_S(**{**base, "rot_ok": False}), RULESETS["V0"]) \
            or not keep(_S(**{**base, "rot_ok": False}), RULESETS["H2"]):
        f.append("rotation leg: required in H1/H12/H123/H1234 only")
    if keep(_S(**{**base, "fast": False}), RULESETS["H123"]) or not keep(_S(**{**base, "fast": False}), RULESETS["H12"]):
        f.append("fast market filter: H123 and H1234 only")
    if keep(_S(**{**base, "leader": False}), RULESETS["H1234"]) or not keep(_S(**{**base, "leader": False}), RULESETS["H123"]):
        f.append("leader filter: H1234 only")
    if NEW_TRIALS != 10:
        f.append("10 new trials")
    # fast_ok is trailing
    s = pd.Series(np.r_[np.linspace(100, 150, 200), np.linspace(150, 120, 60)], index=pd.bdate_range("2020-01-01", periods=260))
    fk = fast_ok(s)
    if fk.iloc[:49].any() or not fk.iloc[150] or fk.iloc[-1]:
        f.append("fast_ok: above a 50-day average in the climb, below it after the fall, nothing before 50 bars")
    s2 = s.copy(); s2.iloc[-1] = 999
    if not fast_ok(s2).iloc[:-1].equals(fk.iloc[:-1]):
        f.append("fast_ok must use trailing data only")
    # selection and verdicts
    def row(name, n, e, pf, rpy):
        return {"name": name, "dev": {"n": n, "expectancy_R": e, "profit_factor": pf}, "dev_r_per_year": rpy}
    rows = [row("V0", 900, 0.10, 1.31, 18.0), row("H1", 300, 0.30, 1.8, 18.0), row("H2", 700, 0.20, 1.5, 28.0),
            row("H12", 200, 0.50, 2.1, 20.0), row("H123", 49, 0.9, 3.0, 40.0), row("H1234", 120, 0.40, 1.29, 9.6)]
    pk = select(rows)
    if pk is None or pk["name"] != "H2":
        f.append(f"select: most R/yr among eligible (H123 has 49 trades, H1234 PF 1.29): {pk and pk['name']}")
    if select([row("H1", 300, 0.3, 1.8, 18.0), row("V0", 900, 0.1, 1.31, 18.0)])["name"] != "V0":
        f.append("select: a tie goes to the simpler rule set")
    if select([row("V0", 900, -0.01, 1.4, -1.0), row("H1", 20, 1.0, 3.0, 4.0)]) is not None:
        f.append("select: none eligible -> None")
    if r_per_year({"n": 100, "expectancy_R": 0.25}, 5.0) != 5.0 or r_per_year({"n": 0}, 5.0) != 0.0:
        f.append("R per year")
    ok_h = {"n": 40, "expectancy_R": 0.2, "profit_factor": 1.5}
    for h, harsh, want in ((ok_h, 0.05, "ROBUST PASS"), (ok_h, -0.01, "PASS"), (ok_h, None, "PASS"),
                           ({**ok_h, "n": 29}, 0.5, "FAIL"), ({**ok_h, "profit_factor": 1.29}, 0.5, "FAIL"),
                           ({**ok_h, "expectancy_R": 0.0}, 0.5, "FAIL")):
        if holdout_verdict(h, harsh)[0] != want:
            f.append(f"holdout_verdict({h}, {harsh}) must be {want}")

    # end to end on synthetic data: V0 must reproduce stock_lab's own trades exactly
    rng = np.random.default_rng(5)
    n = 2900
    cal = pd.bdate_range("2015-06-01", periods=n)
    spy = sl._mk(200 * np.cumprod(1 + rng.normal(0.0004, 0.009, n)), np.full(n, 5e7))
    oh = {"SPY": spy}
    for i, e in enumerate(bt.SECTOR_ETFS):
        oh[e] = sl._mk(50 * np.cumprod(1 + rng.normal(0.0002 + 0.00006 * i, 0.011, n)), np.full(n, 1e7))
    iv, sec = {}, {}
    for i in range(36):
        cc = (30 + i) * np.cumprod(1 + rng.normal(0.0006, 0.021, n))
        oh[f"Q{i:02d}"] = sl._mk(cc, rng.uniform(1e6, 3e6, n), band=0.02)
        iv[f"Q{i:02d}"] = [(pd.Timestamp("2010-01-04"), None)]
        sec[f"Q{i:02d}"] = bt.SECTOR_ETFS[i % 11]
    iv["Q01"] = [(pd.Timestamp("2010-01-04"), pd.Timestamp("2020-03-02"))]
    prep = prepare_stocks(oh, iv, sec, verbose=False)
    for setup in SETUPS:
        mine, _ = trades_under(prep["signals"], prep["data"], setup, RULESETS["V0"], prep["end"])
        ref, _ = sl.trades_for(prep["signals"], prep["data"], setup, False, prep["end"])
        if [(t.ticker, t.entry_t, round(t.r_net, 9)) for t in mine] != [(t.ticker, t.entry_t, round(t.r_net, 9)) for t in ref]:
            f.append(f"V0 must reproduce stock_lab's {setup} trades exactly")
    m0 = {k: trades_under(prep["signals"], prep["data"], "M0", r, prep["end"])[0] for k, r in RULESETS.items()}
    if not m0["V0"]:
        f.append("fixture: M0 should trade")
    else:
        if any(t.exit_reason.startswith("thesis") for k in ("H2", "H12", "H123", "H1234") for t in m0[k]):
            f.append("no sector-rotation exits when thesis is off")
        if not any(t.exit_reason.startswith("thesis") for t in m0["V0"]):
            f.append("fixture: the live rules should show sector-rotation exits")
        sig_of = {(s.ticker, s.t): s for s in prep["signals"] if s.setup == "M0"}
        if any(not sig_of[(t.ticker, t.entry_t - 1)].rot_ok for k in ("H1", "H12", "H123", "H1234") for t in m0[k]):
            f.append("every H1-family trade must come from a signal with the rotation leg")
        if any(not sig_of[(t.ticker, t.entry_t - 1)].fast for k in ("H123", "H1234") for t in m0[k]):
            f.append("H123 trades need SPY above its 50-day on the signal day")
        fk2 = fast_ok(spy["Close"])
        for t in m0["H123"][:50]:
            if not fk2.loc[prep["data"][t.ticker]["index"][t.entry_t - 1]]:
                f.append("the fast flag must match SPY's own 50-day on the signal day")
                break
        if any(not t.leader for t in m0["H1234"]) or len(m0["H1234"]) > len(m0["H123"]):
            f.append("H1234 is a leaders-only subset of H123's signals")
        if len(m0["H1"]) > len(m0["V0"]):
            f.append("H1 cannot have more trades than V0")
        q1 = [t for k in m0 for t in m0[k] if t.ticker == "Q01"]
        if any(prep["data"]["Q01"]["index"][t.entry_t] > pd.Timestamp("2020-03-03") for t in q1):
            f.append("no trade after a stock left the index")
    out = experiment(prep, sec, etf_prep=None, portfolio=True)
    if len(out["rows"]) != len(SETUPS) * len(RULESETS) or len(out["verdicts"]) != len(SETUPS):
        f.append("one row per setup and rule set; one verdict per setup")
    for r in out["rows"]:
        dev_n = sum(1 for t in r["_trades"] if not t.still_open and _date(t, prep["data"]) < DEV_END)
        if r["dev"].get("n", 0) != dev_n:
            f.append("development stats must use entries before 2022 only")
            break
    for v in out["verdicts"]:
        mine = [r for r in out["rows"] if r["setup"] == v["setup"]]
        p = select(mine)
        if (p is None) != (v["selected"] is None) or (p and p["name"] != v["selected"]):
            f.append("the verdict must use the development selection")
    # ETF guard on synthetic ETFs
    eo = {"SPY": spy}
    for i, e in enumerate(t for t in bt.SECTOR_ETFS + list(bt.OTHER_ETFS) if t != "SPY"):
        eo[e] = sl._mk(40 * np.cumprod(1 + rng.normal(0.0004, 0.012, n)), np.full(n, 1e7), start="2015-06-01")
    ep = prepare_etfs(eo, verbose=False)
    if any(s.setup != "M0" for s in ep["signals"]):
        f.append("ETF guard: M0 only")
    mk = bt.market_ok(spy["Close"])
    if any(not mk.loc[ep["data"][s.ticker]["index"][s.t]] for s in ep["signals"]):
        f.append("ETF guard signals need SPY above its 200-day")
    ok_, why_, st_ = etf_guard([], ep["data"])
    if ok_ or "0 trades" not in why_:
        f.append("etf_guard with no trades fails")
    md = render(out, prep, "test", "T", PRIOR_SWING_TRIALS)
    if "## Verdicts" not in md or "NOT used for the verdict" not in md or "76 swing trials" not in md:
        f.append("report")
    fr = flat_rows(out)
    if len(fr) != 12 or "dev_expectancy_R" not in fr.columns or "book_hold_cagr_pct" not in fr.columns:
        f.append("results table")
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
