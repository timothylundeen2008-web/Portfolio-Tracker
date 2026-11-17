"""
stock_lab.py  (v1.0 — 2026-11-16)
─────────────────────────────────
SWING BOOK ONLY. Historical test of the STOCK setups on the stocks that were
actually in the S&P 500 on each past date (fix_status N61; build plan item 3).

THE QUESTION
  The leader screen lists strong stocks every night, but the one live setup
  (M0) rarely fires on them: leaders are extended above the average M0 wants
  them to be reclaiming. Do the breakout-type setups make money on stocks,
  after costs, on a universe that is not chosen with hindsight? And does
  restricting them to leaders help?

WHAT IS TESTED — frozen 2026-11-16, before the first run
  Universe   S&P 500 members by date (data/universe/sp500_membership.csv).
             A signal counts only on a day the stock was a member.
  Window     signals from 2017-01-01 (the years free prices cover: 83% of
             member-days in 2017 rising to 99% in 2026; universe probe v1.1).
             Halves: 2017-2021 and 2022-2026.
  Setups     M0 Rotation Reclaim, M1 VCP, M2 Breakout — detected by the
             PRODUCTION functions through swing_backtest.signals_for_ticker —
             and PG Power Gap (new, system_review_2026-11-14 §6.5):
               signal day: gap up >= 8%, volume >= 3x its 50-day average,
               close in the top third of the day's range, close above the
               200-day; entry: next-session buy-stop one cent above the signal
               day's high; stop: the signal day's low; exits: the production
               order with a 10-day EMA trail, capped at 40 sessions.
  Leaders    each setup is also run on leaders only: the leader_screen.py
             rules (price > $10, $25M dollar volume, five uptrend rules,
             strength 80+ on 3/6/12-month ranks), recomputed for every past
             day across that day's members. A selftest proves this daily
             version equals leader_screen's own functions.
  Candidates 7 = 7 trials: M0 all; M1 all / leaders; M2 all / leaders;
             PG all / leaders.
  Live rules applied as they are today: long only; no new entry while SPY
             closes below its 200-day; confluence 2-of-3 or better
             (rotation, structure, volume); stop method B (closing-basis stop
             plus a disaster stop 1 x ATR below); thesis exit when the
             stock's sector rotates to Weakening/Lagging; 2R/4R/8R ladder;
             5bp a side and 10bp slippage on stop fills.

THE BAR — fixed before the run (the existing swing bar, on these halves)
  PASS    100+ closed trades, 30+ in each half, and in EACH half
          expectancy above 0 and profit factor 1.3 or better.
  ROBUST  PASS, and full-window expectancy still above 0 under the harsh
          missing-stock stress (below).
  Leader filter HELPS when the leaders-only version has higher expectancy
          than the all-members version in both halves (reported, not a bar).

MISSING-STOCK STRESS (reported for every candidate)
  Free prices do not exist for some past members (acquired, bankrupt,
  renamed). For each year the uncovered share u of member-days is measured in
  this run. Phantom trades are added in proportion, n x u / (1 - u):
    neutral  each phantom trade earns 0R
    harsh    each phantom trade loses the candidate's own average loss
  Harsh is deliberately severe: most vanished members were acquired, usually
  at a premium.

HONEST LIMITS (printed in the report)
  * Ten years, one long bull market with three sharp falls (late 2018, 2020,
    2022). No 2008. A PASS here is weaker evidence than M0's ETF pass.
  * Regime gating is not tested (no regime history, N11). Flow is not in the
    rotation leg (no flow history).
  * No earnings history: stock trades include earnings gaps the live rules
    avoid, and PG's "exit before earnings" rule cannot be tested.
  * Sectors are today's GICS sectors, assumed constant. Stocks with no known
    sector have no rotation leg and no thesis exit; their share is reported.
  * The 0.25 x ATR entry limit is not modelled (N58): a gap through the
    buy-stop fills at the open here; live, it would not fill.
  * Portfolio figures use the live sizing (1% / 0.5% risk, 4 positions, 2 per
    sector, 8% heat) with idle cash earning nothing.

Run:  python stock_lab.py            (Actions: needs network; 30-90 minutes)
      python stock_lab.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

import leader_screen as ls
import swing_backtest as bt
import swing_desk as sd
import universe_probe as up

VERSION = "1.0"
DATA_START = "2015-06-01"                     # ~400 bars before the first signal
TEST_START = pd.Timestamp("2017-01-01")
HALF_SPLIT = pd.Timestamp("2022-01-01")
HALVES = ("2017-21", "2022-26")
BAR = {"min_trades": 100, "min_per_half": 30, "min_pf": 1.3}
SETUPS = ("M0", "M1", "M2", "PG")
CANDIDATES = (("M0", "all"), ("M1", "all"), ("M1", "leaders"), ("M2", "all"), ("M2", "leaders"),
              ("PG", "all"), ("PG", "leaders"))
VARIANT = "B"                                 # the live stop method
PG_GAP_PCT = 8.0
PG_VOL_MULT = 3.0
PG_CLOSE_TOP = 1 / 3                          # close in the top third of the day's range
PG_MAX_DAYS = 40
PG_TICK = 0.01
PRIOR_SWING_TRIALS = 59                       # swing_backtest v1.0-v1.3 (fix_status addendum 2026-11-15)
MEMBERSHIP = Path("data/universe/sp500_membership.csv")
SECTORS = Path("data/universe/sp500_sectors.csv")
SECTOR_CACHE = Path("data/universe/sector_cache.csv")
OUT_DATA = Path("data/stock_lab")
OUT_LOGS = Path("logs/stock_lab")
YAHOO_SECTOR_ETF = {"technology": "XLK", "financial services": "XLF", "healthcare": "XLV",
                    "consumer cyclical": "XLY", "consumer defensive": "XLP", "communication services": "XLC",
                    "industrials": "XLI", "energy": "XLE", "utilities": "XLU", "real estate": "XLRE",
                    "basic materials": "XLB"}

bt.TRAIL.setdefault("PG", ("EMA", 10))        # PG trails on the 10-day EMA, like M2


# ── universe ────────────────────────────────────────────────────────────────

def load_membership(path: Path = MEMBERSHIP) -> tuple:
    """-> (membership frame, ticker -> [(start, end)])."""
    mem = up.parse_membership(path.read_text())
    return mem, up.intervals(mem)


def members_in_window(iv: dict, start: pd.Timestamp) -> list:
    return sorted(t for t, spans in iv.items() if any(e is None or e > start for _, e in spans))


def member_mask(index: pd.DatetimeIndex, spans: list) -> np.ndarray:
    """True on the days the stock was a member (end date exclusive)."""
    m = np.zeros(len(index), dtype=bool)
    for s, e in spans:
        m |= (index >= s) & ((index < e) if e is not None else True)
    return m


def allowed_mask(index: pd.DatetimeIndex, member: np.ndarray, market_open: np.ndarray) -> np.ndarray:
    """Days on which a signal may count: a member that day, inside the test window, market filter open."""
    return member & (index >= TEST_START) & market_open


def symbol_for(ticker: str, have: set) -> Optional[str]:
    """The Yahoo symbol holding this member's prices: its own, else its renamed successor."""
    y = up.yahoo_symbol(ticker)
    if y in have:
        return y
    r = up.RENAMES.get(ticker)
    return r if r in have else None


def coverage_by_year(iv: dict, series: dict, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Per year from TEST_START: member-days in the index vs member-days with a price bar."""
    cal = cal[cal >= TEST_START]
    need: dict = {}
    have: dict = {}
    for t, spans in iv.items():
        m = member_mask(cal, spans)
        if not m.any():
            continue
        days = cal[m]
        got = days.isin(series[t].index) if t in series else np.zeros(len(days), dtype=bool)
        for y in np.unique(days.year):
            sel = days.year == y
            need[y] = need.get(y, 0) + int(sel.sum())
            have[y] = have.get(y, 0) + int(got[sel].sum())
    return pd.DataFrame([{"year": int(y), "member_days": need[y], "priced_days": have[y],
                          "covered_pct": round(have[y] / need[y] * 100, 1)} for y in sorted(need)])


# ── sectors ─────────────────────────────────────────────────────────────────

def sector_map(tickers: list, lookup: Optional[Callable] = None, sectors_csv: Path = SECTORS,
               cache_csv: Path = SECTOR_CACHE, max_seconds: float = 600.0) -> tuple:
    """ticker -> sector ETF. Today's S&P list first, then the cache, then a best-effort lookup
    (Yahoo) for stocks that have left the index. -> (map, note). Never raises."""
    out, src = {}, {}
    try:
        for t, s in ls.parse_sector_list(sectors_csv.read_text()).items():
            etf = ls.SECTOR_ETF.get(s.lower())
            if etf:
                out[t.replace("-", ".")] = etf
                out[t] = etf
    except Exception as e:
        print(f"[stock_lab] sector list unreadable: {type(e).__name__}: {e}")
    cache = {}
    try:
        c = pd.read_csv(cache_csv, dtype=str).fillna("")
        cache = dict(zip(c["ticker"], c["etf"]))
    except Exception:
        pass
    todo = [t for t in tickers if t not in out and t not in cache]
    found = 0
    if lookup is not None and todo:
        t0, fails = time.monotonic(), 0
        for t in todo:
            if time.monotonic() - t0 > max_seconds or fails >= 25:
                break
            try:
                etf = lookup(t)
            except Exception:
                etf = None
            if etf:
                cache[t], found, fails = etf, found + 1, 0
            else:
                cache[t], fails = "", fails + 1          # remembered as unknown; not asked again
        try:
            cache_csv.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(sorted(cache.items()), columns=["ticker", "etf"]).to_csv(cache_csv, index=False)
        except Exception:
            pass
    for t in tickers:
        if t not in out and cache.get(t):
            out[t] = cache[t]
    known = sum(1 for t in tickers if t in out)
    return out, f"sector known for {known} of {len(tickers)} stocks ({found} looked up this run)"


def yahoo_sector(ticker: str) -> Optional[str]:
    import yfinance as yf
    sym = up.RENAMES.get(ticker, up.yahoo_symbol(ticker))
    info = yf.Ticker(sym).info or {}
    time.sleep(0.25)
    return YAHOO_SECTOR_ETF.get(str(info.get("sector", "")).strip().lower())


# ── leaders, for every past day ─────────────────────────────────────────────

def leader_panel(series: dict, masks: dict, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """dates x tickers, True where the stock was a leader at that close under leader_screen's rules,
    ranked against that day's liquid members only. Trailing data only."""
    cols = {}
    for t, df in series.items():
        c, v = df["Close"], df["Volume"]
        s50, s150, s200 = c.rolling(50).mean(), c.rolling(150).mean(), c.rolling(200).mean()
        hi, lo = c.rolling(252).max(), c.rolling(252).min()
        trend = ((c > s50) & (c > s150) & (c > s200) & (s50 > s150) & (s150 > s200)
                 & (s200 > s200.shift(ls.MA_RISING_SESSIONS))
                 & (c >= hi * (1 - ls.NEAR_HIGH_PCT / 100)) & (c >= lo * (1 + ls.ABOVE_LOW_PCT / 100)))
        liquid = (c > ls.MIN_PRICE) & ((c * v).rolling(50).mean() > ls.MIN_DOLLAR_VOL)
        enough = pd.Series(np.arange(len(c)) >= ls.MIN_BARS - 1, index=c.index)
        member = pd.Series(masks[t], index=c.index)
        ok = liquid & enough & member
        cols[t] = {"trend": trend.reindex(cal).fillna(False).astype(bool),
                   "ok": ok.reindex(cal).fillna(False).astype(bool),
                   **{f"r{n}": (c / c.shift(n) - 1).reindex(cal) for n in ls.RS_WINDOWS}}
    if not cols:
        return pd.DataFrame(index=cal)
    ok = pd.DataFrame({t: d["ok"] for t, d in cols.items()})
    trend = pd.DataFrame({t: d["trend"] for t, d in cols.items()})

    def pct_rank(frame: pd.DataFrame) -> pd.DataFrame:
        n = frame.notna().sum(axis=1)
        r = (frame.rank(axis=1, method="average") - 1).div((n - 1).where(n > 1), axis=0) * 100
        return r.where(n > 1, 50.0).where(frame.notna())

    ranks = [pct_rank(pd.DataFrame({t: d[f"r{n}"] for t, d in cols.items()}).where(ok)) for n in ls.RS_WINDOWS]
    blend = sum(ranks) / len(ranks)
    rs = pct_rank(blend)
    return (ok & trend & (rs >= ls.RS_MIN)).fillna(False)


# ── signals ─────────────────────────────────────────────────────────────────

def pg_signals(tk: str, df: pd.DataFrame, x: pd.DataFrame, allowed: np.ndarray,
               quads: Optional[pd.Series]) -> list:
    o, h, l, c, v = (df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close", "Volume"))
    pc = np.r_[np.nan, c[:-1]]
    vol50, s200 = x["vol50"].to_numpy(), x["sma200"].to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = (o / pc - 1) * 100
        rng = h - l
        hit = ((gap >= PG_GAP_PCT - 1e-9) & (v >= PG_VOL_MULT * vol50 - 1e-6) & (vol50 > 0)
               & (rng > 0) & (c >= h - rng * PG_CLOSE_TOP - 1e-9) & (c > s200) & allowed)
    qv = quads.reindex(df.index).to_numpy() if quads is not None else None
    out = []
    for t in np.nonzero(hit)[0]:
        if t < bt.WINDOW - 1 or t >= len(df) - 1:
            continue
        rot = bt._rot_leg(qv[t]) if qv is not None else False
        conf = int(rot) + 2                              # structure + volume are part of the definition
        level = float(h[t]) + PG_TICK
        out.append(bt.Signal(tk, int(t), "PG", "stop", level, float(l[t]), conf,
                             1.0 if conf == 3 else 0.5, rot, None, level))
    return out


def build_signals(tk: str, df: pd.DataFrame, bench: pd.Series, quads: Optional[pd.Series],
                  allowed: np.ndarray) -> tuple:
    """-> (signals, indicator frame). `allowed` = member that day, in the test window, market filter open."""
    x = bt.indicators(df, bench)
    pf = bt.prefilters(df, x)
    for s in ("M1", "M2", "M0"):
        pf[s] = pf[s] & allowed
    pf["M2c"] = np.zeros(len(df), dtype=bool)
    pf["PB"] = np.zeros(len(df), dtype=bool)
    sig = bt.signals_for_ticker(tk, df, x, pf, bench, quads, False, setups=("M1", "M2", "M0"))
    sig += pg_signals(tk, df, x, allowed, quads)
    return sig, x


def simulate(sig, d: dict, last_bar_is_end: bool):
    """One trade under stop method B. PG is capped at PG_MAX_DAYS sessions. A stock whose prices
    end before the test does (acquired, delisted) is closed at its last close."""
    arr, n = d["arr"], len(d["arr"]["Close"])
    cap = None
    if sig.setup == "PG":
        cap = sig.t + 1 + PG_MAX_DAYS + 1               # bars [0, entry + PG_MAX_DAYS]
        if cap < n:
            arr = {k: v[:cap] for k, v in arr.items()}
        else:
            cap = None
    q = d["quads"][:len(arr["Close"])] if d["quads"] is not None else None
    tr = bt.simulate_trade(sig, arr, VARIANT, q, d["asset"])
    if tr is None or not tr.still_open:
        return tr
    if cap is None and last_bar_is_end:
        return tr                                         # genuinely open at the end of the test
    # forced close at the last available close: the "mark" becomes a real, costed exit
    t, kind, frac, px, _ = tr.events[-1]
    bps = bt.COST_BPS[d["asset"]]
    tr.events[-1] = (t, "exit", frac, px, bps)
    tr.still_open = False
    tr.exit_reason = "PG: 40-session cap" if cap is not None else "prices ended (acquired or delisted)"
    gross = sum(f * p for _, k, f, p, _b in tr.events if k != "entry")
    cost = sum(f * p * b / 1e4 for _, _k, f, p, b in tr.events)
    tr.r_net = (gross - tr.entry - cost) / tr.risk
    return tr


def trades_for(signals: list, data: dict, setup: str, leaders_only: bool, end: pd.Timestamp) -> tuple:
    """One open trade per stock and setup at a time, as in swing_backtest.run. -> (trades, unfilled)."""
    trades, unfilled, busy = [], [], {}
    for sg in sorted((s for s in signals if s.setup == setup and (s.leader or not leaders_only)),
                     key=lambda z: (z.ticker, z.t)):
        if sg.t + 1 <= busy.get(sg.ticker, -1):
            continue
        d = data[sg.ticker]
        tr = simulate(sg, d, d["index"][-1] >= end)
        if tr is None:
            unfilled.append(sg)
        else:
            tr.leader = bool(getattr(sg, "leader", False))
            trades.append(tr)
            busy[sg.ticker] = tr.exit_t
    return trades, unfilled


# ── statistics ──────────────────────────────────────────────────────────────

def _half(d: pd.Timestamp) -> str:
    return HALVES[0] if d < HALF_SPLIT else HALVES[1]


def stress(rs_by_year: dict, uncovered: dict) -> dict:
    """Missing-stock stress. rs_by_year: year -> list of R; uncovered: year -> share of member-days
    with no prices (0..1). Phantom trades n*u/(1-u) per year at 0R (neutral) and at the candidate's
    own average loss (harsh)."""
    allr = np.array([r for rs in rs_by_year.values() for r in rs], dtype=float)
    if len(allr) == 0:
        return {"phantom": 0.0}
    losses = allr[allr < -bt.SCRATCH_R]
    wins = allr[allr > bt.SCRATCH_R]
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    ph = sum(len(rs) * min(max(uncovered.get(y, 0.0), 0.0), 0.95) / (1 - min(max(uncovered.get(y, 0.0), 0.0), 0.95))
             for y, rs in rs_by_year.items())
    tot, n = float(allr.sum()), len(allr)
    gp, gl = float(wins.sum()), float(-losses.sum())
    return {"phantom": round(ph, 1), "avg_loss_R": round(avg_loss, 2),
            "neutral_exp_R": round(tot / (n + ph), 3),
            "harsh_exp_R": round((tot + ph * avg_loss) / (n + ph), 3),
            "harsh_pf": round(gp / (gl + ph * abs(avg_loss)), 2) if (gl + ph * abs(avg_loss)) > 0 else float("inf")}


def judge(full: dict, halves: dict, st: dict) -> tuple:
    why = []
    if full.get("n", 0) < BAR["min_trades"]:
        why.append(f"{full.get('n', 0)} trades < {BAR['min_trades']}")
    for nm in HALVES:
        h = halves.get(nm, {"n": 0})
        if h.get("n", 0) < BAR["min_per_half"]:
            why.append(f"{nm}: {h.get('n', 0)} trades < {BAR['min_per_half']}")
            continue
        if h.get("expectancy_R", 0) <= 0:
            why.append(f"{nm}: expectancy {h.get('expectancy_R')}R <= 0")
        if h.get("profit_factor", 0) < BAR["min_pf"]:
            why.append(f"{nm}: profit factor {h.get('profit_factor')} < {BAR['min_pf']}")
    if why:
        return "FAIL", "; ".join(why)
    if st.get("harsh_exp_R", -1) > 0:
        return "ROBUST PASS", "meets the bar and survives the harsh missing-stock stress"
    return "PASS", f"meets the bar; harsh missing-stock stress turns expectancy to {st.get('harsh_exp_R')}R"


def evaluate(signals: list, data: dict, cal: pd.DatetimeIndex, sector_of: dict, uncovered: dict,
             end: pd.Timestamp, portfolio: bool = True) -> dict:
    rows, year_rows, trade_rows, ports = [], [], [], {}
    for setup, scope in CANDIDATES:
        trs, unf = trades_for(signals, data, setup, scope == "leaders", end)
        closed = [t for t in trs if not t.still_open]
        dt = lambda t: data[t.ticker]["index"][t.entry_t]
        full = bt.trade_stats([t.r_net for t in closed])
        halves = {h: bt.trade_stats([t.r_net for t in closed if _half(dt(t)) == h]) for h in HALVES}
        by_year: dict = {}
        for t in closed:
            by_year.setdefault(int(dt(t).year), []).append(t.r_net)
        st = stress(by_year, uncovered)
        verdict, why = judge(full, halves, st)
        held = [t.exit_t - t.entry_t for t in closed]
        row = {"setup": setup, "scope": scope, "verdict": verdict, "why": why, "signals": len(trs) + len(unf),
               "filled": len(trs), "open_at_end": len(trs) - len(closed),
               "avg_bars_held": round(float(np.mean(held)), 1) if held else None,
               "no_sector_pct": round(100 * sum(1 for t in closed if not sector_of.get(t.ticker)) / len(closed), 1) if closed else None,
               **{f"full_{k}": v for k, v in full.items()},
               **{f"{h}_{k}": v for h in HALVES for k, v in halves[h].items()},
               **{f"stress_{k}": v for k, v in st.items()}}
        if portfolio:
            p = bt.run_portfolio(trs, unf, data, cal, sector_of)
            eq = p["equity"][p["equity"].index >= TEST_START]
            ss = bt.series_stats(eq)
            row.update({"port_cagr_pct": ss.get("cagr_pct"), "port_max_dd_pct": ss.get("max_dd_pct"),
                        "port_sharpe": ss.get("sharpe"), "port_trades": p["trades_taken"],
                        "port_exposure_pct": p["exposure_avg_pct"], "port_hwm_20_breached": p["hwm_-20pct_breached"]})
            ports[(setup, scope)] = eq
        rows.append(row)
        for y in sorted(by_year):
            s = bt.trade_stats(by_year[y])
            year_rows.append({"setup": setup, "scope": scope, "year": y, **s})
        for t in closed:
            trade_rows.append({"setup": setup, "scope": scope, "ticker": t.ticker, "entry_date": dt(t).date().isoformat(),
                               "exit_date": data[t.ticker]["index"][t.exit_t].date().isoformat(),
                               "entry": round(t.entry, 4), "stop": round(t.stop0, 4), "conf": t.conf,
                               "r_net": round(t.r_net, 3), "exit_reason": t.exit_reason,
                               "leader": bool(getattr(t, "leader", False))})
    res = pd.DataFrame(rows)
    helps = []
    for setup in ("M1", "M2", "PG"):
        a = res[(res.setup == setup) & (res.scope == "all")]
        b = res[(res.setup == setup) & (res.scope == "leaders")]
        if len(a) and len(b):
            a, b = a.iloc[0], b.iloc[0]
            enough = all((b.get(f"{h}_n") or 0) >= BAR["min_per_half"] for h in HALVES)
            better = all((b.get(f"{h}_expectancy_R") or -9) > (a.get(f"{h}_expectancy_R") or -9) for h in HALVES)
            helps.append({"setup": setup, "leader_filter": "HELPS" if (enough and better) else
                          ("too few leader trades to say" if not enough else "does not help"),
                          **{f"{h}_all": a.get(f"{h}_expectancy_R") for h in HALVES},
                          **{f"{h}_leaders": b.get(f"{h}_expectancy_R") for h in HALVES}})
    return {"results": res, "by_year": pd.DataFrame(year_rows), "trades": pd.DataFrame(trade_rows),
            "leader_filter": pd.DataFrame(helps), "ports": ports}


# ── run ─────────────────────────────────────────────────────────────────────

def run(ohlcv: dict, iv: dict, sector_of: dict, portfolio: bool = True, verbose: bool = True) -> dict:
    """ohlcv: Yahoo symbol -> OHLCV (must include SPY and the sector ETFs)."""
    spy = ohlcv["SPY"]
    cal = pd.DatetimeIndex(spy.index)
    end = cal[-1]
    bench = spy["Close"]
    mkt = bt.market_ok(bench)
    quads_by_sector = bt.rotation_proxy({k: v["Close"] for k, v in ohlcv.items()})
    have = set(ohlcv)
    members = members_in_window(iv, TEST_START)
    series = {t: ohlcv[symbol_for(t, have)] for t in members if symbol_for(t, have)}
    masks = {t: member_mask(pd.DatetimeIndex(df.index), iv[t]) for t, df in series.items()}
    cov = coverage_by_year(iv, series, cal)
    uncovered = {int(r.year): 1 - r.covered_pct / 100 for r in cov.itertuples()}
    if verbose:
        print(f"[stock_lab] {len(members)} members since {TEST_START.date()}, {len(series)} with prices; "
              f"computing leaders for every day")
    leaders = leader_panel(series, masks, cal)
    data, signals = {}, []
    for i, (tk, df) in enumerate(sorted(series.items())):
        idx = pd.DatetimeIndex(df.index)
        mk = mkt.reindex(idx).ffill().fillna(False).to_numpy(dtype=bool)
        allowed = allowed_mask(idx, masks[tk], mk)
        q = quads_by_sector.get(sector_of.get(tk)) if sector_of.get(tk) else None
        sig, x = build_signals(tk, df, bench, q, allowed)
        lead = leaders[tk].reindex(idx).fillna(False).to_numpy(dtype=bool) if tk in leaders else np.zeros(len(idx), bool)
        for s in sig:
            s.leader = bool(lead[s.t])                    # a leader at the signal close
            s.mkt_ok = True
        arr = {k: df[k].to_numpy(dtype=float, copy=True) for k in ("Open", "High", "Low", "Close")}
        for col in ("atr14", "sma5", "ema5", "ema10", "sma50", "sma100"):
            arr[col] = x[col].to_numpy(dtype=float, copy=True)
        data[tk] = {"arr": arr, "quads": q.reindex(idx).to_numpy() if q is not None else None, "index": idx,
                    "asset": "stock", "close_cal": df["Close"].reindex(cal).ffill()}
        signals.extend(sig)
        if verbose and (i + 1) % 25 == 0:
            print(f"[stock_lab] {i + 1}/{len(series)} stocks, {len(signals)} signals so far")
    out = evaluate(signals, data, cal, sector_of, uncovered, end, portfolio)
    spy_w = bench[bench.index >= TEST_START]
    out.update({"coverage": cov, "members": len(members), "priced": len(series), "signals_n": len(signals),
                "leader_days_pct": round(float(leaders.to_numpy().sum()) / max(sum(int(m[pd.DatetimeIndex(series[t].index) >= TEST_START].sum()) for t, m in masks.items()), 1) * 100, 1),
                "spy": bt.series_stats(spy_w), "start": str(spy_w.index[0].date()), "end": str(end.date()),
                "market_open_pct": round(float(mkt[mkt.index >= TEST_START].mean()) * 100, 1)})
    return out


# ── report ──────────────────────────────────────────────────────────────────

def _f(v, nd=2, suffix=""):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    return f"{v:.{nd}f}{suffix}" if isinstance(v, (int, float, np.floating)) else str(v)


def render(out: dict, sec_note: str, stamp: str, trials_before: int) -> str:
    r = out["results"]
    L = [f"# Stock setup test — {stamp} (stock_lab v{VERSION})", "",
         f"Point-in-time S&P 500 members, signals {out['start']} → {out['end']}. Swing book only.", "",
         "**Bar (fixed before the run):** PASS = 100+ closed trades, 30+ in each half, and in each half "
         "expectancy above 0 and profit factor 1.3+. ROBUST PASS = also positive under the harsh "
         "missing-stock stress.", "",
         "## Verdicts", "",
         "| Setup | Stocks | Verdict | Trades | Win % | Expectancy (R) | 2017-21 exp / PF | 2022-26 exp / PF | "
         "Harsh-stress exp | Why |", "|---|---|---|---|---|---|---|---|---|---|"]
    for x in r.to_dict("records"):
        L.append(f"| {bt.SETUP_NAMES.get(x['setup'], 'PG Power Gap')} | {x['scope']} | **{x['verdict']}** | "
                 f"{x.get('full_n', 0)} | {_f(x.get('full_win_rate'), 1)} | {_f(x.get('full_expectancy_R'), 3)} | "
                 f"{_f(x.get('2017-21_expectancy_R'), 3)} / {_f(x.get('2017-21_profit_factor'))} | "
                 f"{_f(x.get('2022-26_expectancy_R'), 3)} / {_f(x.get('2022-26_profit_factor'))} | "
                 f"{_f(x.get('stress_harsh_exp_R'), 3)} | {x['why']} |")
    L += ["", "## Does the leader filter help?", ""]
    lf = out["leader_filter"]
    if len(lf):
        L += ["| Setup | Result | 2017-21 all → leaders (R) | 2022-26 all → leaders (R) |", "|---|---|---|---|"]
        for x in lf.to_dict("records"):
            L.append(f"| {x['setup']} | **{x['leader_filter']}** | {_f(x['2017-21_all'], 3)} → {_f(x['2017-21_leaders'], 3)} | "
                     f"{_f(x['2022-26_all'], 3)} → {_f(x['2022-26_leaders'], 3)} |")
    if "port_cagr_pct" in r.columns:
        L += ["", "## As a $10,000 book (live sizing, idle cash earning nothing)", "",
              "| Setup | Stocks | Return / yr | Worst drawdown | Sharpe | Trades taken | Avg invested | −20% breach |",
              "|---|---|---|---|---|---|---|---|"]
        for x in r.to_dict("records"):
            L.append(f"| {x['setup']} | {x['scope']} | {_f(x.get('port_cagr_pct'), 2, '%')} | "
                     f"{_f(x.get('port_max_dd_pct'), 1, '%')} | {_f(x.get('port_sharpe'))} | {x.get('port_trades')} | "
                     f"{_f(x.get('port_exposure_pct'), 0, '%')} | {'YES' if x.get('port_hwm_20_breached') else 'no'} |")
        sp = out["spy"]
        L += ["", f"SPY over the same window: {_f(sp.get('cagr_pct'), 2, '%')} a year, worst drawdown "
                  f"{_f(sp.get('max_dd_pct'), 1, '%')}. The market filter was open {out['market_open_pct']}% of sessions."]
    L += ["", "## Trade detail", "",
          "| Setup | Stocks | Signals | Filled | Avg win R | Avg loss R | Worst R | Longest losing streak | Avg bars held | "
          "No-sector trades |", "|---|---|---|---|---|---|---|---|---|---|"]
    for x in r.to_dict("records"):
        L.append(f"| {x['setup']} | {x['scope']} | {x['signals']} | {x['filled']} | {_f(x.get('full_avg_win_R'))} | "
                 f"{_f(x.get('full_avg_loss_R'))} | {_f(x.get('full_worst_R'))} | {_f(x.get('full_max_consec_losses'), 0)} | "
                 f"{_f(x.get('avg_bars_held'), 1)} | {_f(x.get('no_sector_pct'), 1, '%')} |")
    L += ["", "## Missing-stock stress", "",
          "| Setup | Stocks | Phantom trades added | Neutral exp (R) | Harsh exp (R) | Harsh PF |", "|---|---|---|---|---|---|"]
    for x in r.to_dict("records"):
        L.append(f"| {x['setup']} | {x['scope']} | {_f(x.get('stress_phantom'), 1)} | {_f(x.get('stress_neutral_exp_R'), 3)} | "
                 f"{_f(x.get('stress_harsh_exp_R'), 3)} | {_f(x.get('stress_harsh_pf'))} |")
    L += ["", "## Data", "",
          f"- {out['members']} stocks were members at some point in the window; {out['priced']} have prices.",
          f"- {sec_note}.",
          f"- A member-day was a leader day {out['leader_days_pct']}% of the time.", "",
          "| Year | Member-days | With prices | Covered |", "|---|---|---|---|"]
    L += [f"| {x.year} | {x.member_days} | {x.priced_days} | {x.covered_pct}% |" for x in out["coverage"].itertuples()]
    L += ["", "## Limits", "",
          "- Ten years, one long bull market with three sharp falls. No 2008. A pass here is weaker evidence than "
          "M0's pass on ETFs over 2005-2026.",
          "- No earnings history: trades include earnings gaps the live rules avoid; PG's exit-before-earnings rule is untested.",
          "- Regime gating and flow are not tested. Sectors are today's, assumed constant.",
          "- A gap through the buy-stop fills at the open here; the live 0.25×ATR limit would skip it.",
          "- Harsh stress is deliberately severe; most vanished members were acquired.", "",
          f"Trials: {len(CANDIDATES)} in this run; {trials_before + len(CANDIDATES)} swing trials to date "
          f"({PRIOR_SWING_TRIALS} in swing_backtest). A pass is 1 of that many tried.", ""]
    return "\n".join(L)


def prior_lab_trials() -> int:
    try:
        return int(pd.read_csv(OUT_DATA / "trial_log.csv")["trials"].sum())
    except Exception:
        return 0


def main() -> int:
    mem, iv = load_membership()
    members = members_in_window(iv, TEST_START)
    syms = sorted({up.yahoo_symbol(t) for t in members} | {v for k, v in up.RENAMES.items() if k in members}
                  | set(bt.SECTOR_ETFS) | {"SPY"})
    print(f"[stock_lab] v{VERSION}: {len(members)} members since {TEST_START.date()}; fetching {len(syms)} symbols from {DATA_START}")
    ohlcv = {}
    for i in range(0, len(syms), 150):
        ohlcv.update(bt.fetch_ohlcv(syms[i:i + 150], start=DATA_START))
        print(f"[stock_lab] {min(i + 150, len(syms))}/{len(syms)} requested, {len(ohlcv)} with data")
    if "SPY" not in ohlcv or sum(1 for e in bt.SECTOR_ETFS if e in ohlcv) < 9:
        print("[stock_lab] DATA FAILURE: SPY or the sector ETFs are missing; nothing written.")
        return 1
    have = set(ohlcv)
    priced = [t for t in members if symbol_for(t, have)]
    if len(priced) < 0.6 * len(members):
        print(f"[stock_lab] DATA FAILURE: prices for only {len(priced)} of {len(members)} members; nothing written.")
        return 1
    sector_of, sec_note = sector_map(priced, lookup=yahoo_sector)
    print(f"[stock_lab] {sec_note}")
    out = run(ohlcv, iv, sector_of)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_LOGS.mkdir(parents=True, exist_ok=True)
    before = PRIOR_SWING_TRIALS + prior_lab_trials()
    out["results"].to_csv(OUT_DATA / "results.csv", index=False)
    out["by_year"].to_csv(OUT_DATA / "by_year.csv", index=False)
    out["trades"].to_csv(OUT_DATA / "trades.csv", index=False)
    out["leader_filter"].to_csv(OUT_DATA / "leader_filter.csv", index=False)
    out["coverage"].to_csv(OUT_DATA / "coverage.csv", index=False)
    if out["ports"]:
        pd.DataFrame({f"{s}_{c}": e for (s, c), e in out["ports"].items()}).round(2).to_csv(OUT_DATA / "equity.csv")
    tl = OUT_DATA / "trial_log.csv"
    row = pd.DataFrame([{"date": stamp, "version": VERSION, "trials": len(CANDIDATES) if prior_lab_trials() == 0 else 0,
                         "note": "7 candidates" if prior_lab_trials() == 0 else "re-run of the same 7 candidates"}])
    (pd.concat([pd.read_csv(tl), row]) if tl.exists() else row).to_csv(tl, index=False)
    md = render(out, sec_note, stamp, before)
    (OUT_LOGS / f"{stamp}_report.md").write_text(md)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _mk(close: np.ndarray, vol: np.ndarray, start: str = "2015-06-01", band: float = 0.01) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(close))
    o = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, close) * (1 + band), "Low": np.minimum(o, close) * (1 - band),
                         "Close": close, "Volume": vol}, index=idx)


def selftest() -> dict:
    import tempfile
    f = []
    n = 2900                                           # 2015-06 -> 2026-07
    idx = pd.bdate_range("2015-06-01", periods=n)
    rng = np.random.default_rng(0)

    # membership masks and intervals
    spans = [(pd.Timestamp("2017-03-01"), pd.Timestamp("2018-03-01")), (pd.Timestamp("2020-01-02"), None)]
    m = member_mask(idx, spans)
    if m[idx.get_loc(pd.Timestamp("2017-02-28"))] or not m[idx.get_loc(pd.Timestamp("2017-03-01"))] or \
            m[idx.get_loc(pd.Timestamp("2018-03-01"))] or not m[idx.get_loc(pd.Timestamp("2018-02-28"))] or not m[-1]:
        f.append("member_mask: start inclusive, end exclusive, open-ended to the last bar")
    ones = np.ones(len(idx), dtype=bool)
    am = allowed_mask(idx, ones, ones)
    k0 = idx.searchsorted(TEST_START)
    if am[:k0].any() or not am[k0:].all() or allowed_mask(idx, m, ones).sum() != (m & (idx >= TEST_START)).sum():
        f.append("allowed_mask: nothing before the test window; membership respected")
    mo = ones.copy(); mo[k0 + 5] = False
    if allowed_mask(idx, ones, mo)[k0 + 5] or not allowed_mask(idx, ones, mo)[k0 + 6]:
        f.append("allowed_mask: a closed market filter blocks that day only")
    iv = {"OLD": [(pd.Timestamp("2010-01-04"), pd.Timestamp("2016-06-01"))],
          "IN": [(pd.Timestamp("2010-01-04"), None)], "LEFT": [(pd.Timestamp("2010-01-04"), pd.Timestamp("2019-01-02"))]}
    if members_in_window(iv, TEST_START) != ["IN", "LEFT"]:
        f.append("a stock that left before the window is not in the universe")
    if symbol_for("FB", {"META"}) != "META" or symbol_for("BRK.B", {"BRK-B"}) != "BRK-B" or symbol_for("ZZZ", {"META"}) is not None:
        f.append("symbol_for: own symbol, then the renamed successor, else None")

    # coverage: LEFT has prices for half its member-days in 2018
    cal = idx
    full_df = _mk(100 * np.cumprod(1 + rng.normal(0.0003, 0.01, n)), np.full(n, 2e6))
    half_df = full_df[(full_df.index < "2018-07-02")]
    cov = coverage_by_year(iv, {"IN": full_df, "LEFT": half_df}, cal).set_index("year")
    d18 = len(idx[(idx >= "2018-01-01") & (idx <= "2018-12-31")])
    h18 = len(idx[(idx >= "2018-01-01") & (idx < "2018-07-02")])
    if cov.loc[2018, "member_days"] != 2 * d18 or cov.loc[2018, "priced_days"] != d18 + h18 or \
            cov.loc[2019, "member_days"] != len(idx[(idx >= "2019-01-01") & (idx <= "2019-12-31")]) + 1 or 2016 in cov.index:
        f.append(f"coverage_by_year: {cov.loc[2018].to_dict()}")

    # leaders for every day must equal leader_screen's own functions on that day's data
    uni = {}
    for i in range(60):
        drift = -0.0006 + i * 0.00004
        c = (20 + i) * np.cumprod(1 + drift + rng.normal(0, 0.006, 700))
        uni[f"S{i:02d}"] = _mk(c, np.full(700, 3e6 if i % 7 else 1e3))
    uni["S05"] = uni["S05"].iloc[300:]                # too new for a while
    cal2 = pd.bdate_range("2015-06-01", periods=700)
    masks = {t: np.ones(len(d), dtype=bool) for t, d in uni.items()}
    p0 = leader_panel(uni, masks, cal2)
    both = [t for t in p0.columns if p0.loc[cal2[640], t] and p0.loc[cal2[660], t]]
    gone = both[0] if both else "S58"
    masks[gone] = (pd.DatetimeIndex(uni[gone].index) < cal2[650])       # a leader leaves the index
    panel = leader_panel(uni, masks, cal2)
    for day in (cal2[400], cal2[620], cal2[660], cal2[-1]):
        mets = {t: ls.metrics(d[d.index <= day]) for t, d in uni.items()
                if masks[t][pd.DatetimeIndex(d.index).get_indexer([day])[0]]}
        tb = ls.rank(mets)
        want = set(tb.loc[tb["leader"], "ticker"]) if len(tb) else set()
        got = set(panel.columns[panel.loc[day].to_numpy()])
        if want != got:
            f.append(f"leader_panel != leader_screen on {day.date()}: only screen {sorted(want - got)[:5]}, only panel {sorted(got - want)[:5]}")
            break
    if not panel.loc[cal2[620]].any():
        f.append("fixture: there should be leaders")
    if not both:
        f.append("fixture: some stock should be a leader on both sides of the exit date")
    elif panel.loc[cal2[660], gone] or not panel.loc[cal2[640], gone]:
        f.append("a stock is never a leader on a day it is not a member")
    if panel.iloc[:ls.MIN_BARS - 1].to_numpy().any():
        f.append("no leaders before a year of history exists")
    moved = dict(uni); moved["S30"] = uni["S30"].copy()
    moved["S30"].iloc[-1, moved["S30"].columns.get_loc("Close")] *= 3
    if not leader_panel(moved, masks, cal2).iloc[:-1].equals(panel.iloc[:-1]):
        f.append("leader_panel must use trailing data only (a later price changed an earlier day)")

    # PG detection
    c = np.full(700, 50.0); v = np.full(700, 1e6)
    c[:500] = np.linspace(30, 50, 500)
    df = _mk(c.copy(), v.copy())
    def gap_day(d, t, gap=0.10, volx=4.0, close_pos=0.9, rng_pct=0.04):
        pc = d["Close"].iloc[t - 1]; o = pc * (1 + gap); lo = o * (1 - 0.005); hi = lo * (1 + rng_pct)
        d.iloc[t, [d.columns.get_loc(k) for k in ("Open", "High", "Low", "Close", "Volume")]] = \
            [o, hi, lo, lo + (hi - lo) * close_pos, d["Volume"].iloc[t - 1] * volx]
    good = df.copy(); gap_day(good, 600)
    x = bt.indicators(good, None)
    allow = np.ones(700, dtype=bool)
    sg = pg_signals("T", good, x, allow, None)
    if len(sg) != 1 or sg[0].t != 600 or abs(sg[0].level - (good["High"].iloc[600] + PG_TICK)) > 1e-9 or \
            abs(sg[0].stop - good["Low"].iloc[600]) > 1e-9 or sg[0].conf != 2 or sg[0].entry_type != "stop":
        f.append(f"PG: one signal at the gap day with entry above its high and stop at its low: {sg}")
    for label, kw in (("gap 7%", {"gap": 0.07}), ("volume 2.5x", {"volx": 2.5}), ("close mid-range", {"close_pos": 0.5})):
        bad = df.copy(); gap_day(bad, 600, **kw)
        if pg_signals("T", bad, bt.indicators(bad, None), allow, None):
            f.append(f"PG must not fire: {label}")
    edge = df.copy(); gap_day(edge, 600, gap=0.08, volx=3.2, close_pos=0.67)
    if len(pg_signals("T", edge, bt.indicators(edge, None), allow, None)) != 1:
        f.append("PG fires at exactly an 8% gap and a close just inside the top third")
    below = df.copy(); below.iloc[450:, :4] *= 0.5; gap_day(below, 600)
    if pg_signals("T", below, bt.indicators(below, None), allow, None):
        f.append("PG must not fire below the 200-day")
    no = allow.copy(); no[600] = False
    if pg_signals("T", good, x, no, None):
        f.append("PG must respect the allowed mask (membership, window, market filter)")
    lead_q = pd.Series("Leading", index=good.index, dtype=object)
    if pg_signals("T", good, x, allow, lead_q)[0].conf != 3:
        f.append("PG in a Leading sector is 3-of-3")

    # PG trade: 40-session cap, costed exit; delisting close; genuinely open trades stay open
    run_up = good.copy()
    after = np.arange(601, 700)
    base = run_up["Close"].iloc[600]
    path = base * (1 + 0.004 * (after - 600))
    run_up.iloc[601:, run_up.columns.get_loc("Open")] = np.r_[base * 1.01, path[:-1]]
    run_up.iloc[601:, run_up.columns.get_loc("Close")] = path
    run_up.iloc[601:, run_up.columns.get_loc("High")] = np.maximum(run_up["Open"].iloc[601:], path) * 1.003
    run_up.iloc[601:, run_up.columns.get_loc("Low")] = np.minimum(run_up["Open"].iloc[601:], path) * 0.997
    xr = bt.indicators(run_up, None)
    s1 = pg_signals("T", run_up, xr, allow, None)[0]
    arr = {k: run_up[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close")}
    for col in ("atr14", "sma5", "ema5", "ema10", "sma50", "sma100"):
        arr[col] = xr[col].to_numpy(dtype=float)
    dd = {"arr": arr, "quads": None, "asset": "stock", "index": pd.DatetimeIndex(run_up.index)}
    tr = simulate(s1, dd, True)
    if tr is None or tr.still_open or tr.exit_t > tr.entry_t + PG_MAX_DAYS:
        f.append(f"PG must be closed by session {PG_MAX_DAYS}: {None if tr is None else (tr.exit_t - tr.entry_t, tr.exit_reason)}")
    elif tr.exit_reason == "PG: 40-session cap":
        ev = tr.events[-1]
        gross = sum(fr * p for _, k, fr, p, _b in tr.events if k != "entry")
        cost = sum(fr * p * b / 1e4 for _, _k, fr, p, b in tr.events)
        if ev[1] != "exit" or ev[4] != bt.COST_BPS["stock"] or abs(tr.r_net - (gross - tr.entry - cost) / tr.risk) > 1e-9 or \
                ev[0] != tr.entry_t + PG_MAX_DAYS:
            f.append("the 40-session exit must be a costed exit at that session's close")
    else:
        f.append(f"fixture: a steady climb should end at the 40-session cap, got '{tr.exit_reason}'")
    short = {**dd, "arr": {k: a[:612] for k, a in arr.items()}, "index": dd["index"][:612]}
    td = simulate(s1, short, False)
    if td is None or td.still_open or "prices ended" not in td.exit_reason or td.events[-1][1] != "exit":
        f.append("a stock whose prices end mid-trade is closed at its last close, with a cost")
    te = simulate(s1, short, True)
    if te is None or not te.still_open:
        f.append("a trade still running at the end of the test stays open and is not counted")

    # stress arithmetic and the bar
    st = stress({2017: [1.0, 1.0, -1.0, -1.0], 2018: [2.0, -1.0]}, {2017: 0.20, 2018: 0.0})
    if st["phantom"] != 1.0 or st["avg_loss_R"] != -1.0 or abs(st["neutral_exp_R"] - 1 / 7) > 1e-3 or \
            abs(st["harsh_exp_R"] - 0.0) > 1e-9 or abs(st["harsh_pf"] - 4 / 4) > 1e-9:
        f.append(f"stress arithmetic: {st}")
    ok_h = {"n": 60, "expectancy_R": 0.2, "profit_factor": 1.5}
    cases = (({"n": 120}, {HALVES[0]: ok_h, HALVES[1]: ok_h}, {"harsh_exp_R": 0.05}, "ROBUST PASS"),
             ({"n": 120}, {HALVES[0]: ok_h, HALVES[1]: ok_h}, {"harsh_exp_R": -0.01}, "PASS"),
             ({"n": 99}, {HALVES[0]: ok_h, HALVES[1]: ok_h}, {"harsh_exp_R": 0.05}, "FAIL"),
             ({"n": 120}, {HALVES[0]: ok_h, HALVES[1]: {**ok_h, "profit_factor": 1.29}}, {"harsh_exp_R": 0.05}, "FAIL"),
             ({"n": 120}, {HALVES[0]: {**ok_h, "expectancy_R": 0.0}, HALVES[1]: ok_h}, {"harsh_exp_R": 0.05}, "FAIL"),
             ({"n": 120}, {HALVES[0]: ok_h, HALVES[1]: {**ok_h, "n": 29}}, {"harsh_exp_R": 0.05}, "FAIL"))
    for full, hv, s_, want in cases:
        if judge(full, hv, s_)[0] != want:
            f.append(f"judge({full}, …) must be {want}, got {judge(full, hv, s_)[0]}")
    if _half(pd.Timestamp("2021-12-31")) != HALVES[0] or _half(pd.Timestamp("2022-01-03")) != HALVES[1]:
        f.append("half split at 2022-01-01")

    # sector map: list, then cache, then lookup; unknown is remembered
    tmp = Path(tempfile.mkdtemp())
    names = ["A" + chr(65 + i // 26) + chr(65 + i % 26) for i in range(420)]
    secs = list(ls.SECTOR_ETF)[:11]
    (tmp / "s.csv").write_text("ticker,sector\n" + "\n".join(f"{t},{secs[i % 11].title()}" for i, t in enumerate(names)))
    asked = []
    def look(t):
        asked.append(t)
        return {"GONE1": "XLE"}.get(t)
    sm, note = sector_map([names[0], "GONE1", "GONE2"], lookup=look, sectors_csv=tmp / "s.csv", cache_csv=tmp / "c.csv")
    if sm.get(names[0]) != ls.SECTOR_ETF[secs[0]] or sm.get("GONE1") != "XLE" or "GONE2" in sm or asked != ["GONE1", "GONE2"]:
        f.append(f"sector_map: {sm} asked {asked}")
    asked.clear()
    sm2, _ = sector_map([names[0], "GONE1", "GONE2"], lookup=look, sectors_csv=tmp / "s.csv", cache_csv=tmp / "c.csv")
    if asked or sm2.get("GONE1") != "XLE":
        f.append("sector_map must reuse its cache and not ask again")

    # end to end on a synthetic index: membership, window, market filter, verdict table
    cal3 = pd.bdate_range("2015-06-01", periods=n)
    spy = _mk(200 * np.cumprod(1 + rng.normal(0.0004, 0.008, n)), np.full(n, 5e7))
    oh = {"SPY": spy}
    for i, e in enumerate(bt.SECTOR_ETFS):
        oh[e] = _mk(50 * np.cumprod(1 + rng.normal(0.0002 + 0.00005 * i, 0.009, n)), np.full(n, 1e7))
    iv3, sec3 = {}, {}
    for i in range(24):
        cc = (30 + i) * np.cumprod(1 + rng.normal(0.0005, 0.02, n))
        d = _mk(cc, rng.uniform(1e6, 3e6, n), band=0.02)
        for t in rng.choice(np.arange(700, n - 60), size=10, replace=False):
            gap_day(d, int(t), gap=0.09 + 0.02 * rng.random(), volx=4.0)
            d.iloc[int(t) + 1:, :4] *= d["Close"].iloc[int(t)] / d["Close"].iloc[int(t) - 1] / (1 + 0)  # carry the gap forward
        oh[f"Q{i:02d}"] = d
        iv3[f"Q{i:02d}"] = [(pd.Timestamp("2010-01-04"), None)]
        sec3[f"Q{i:02d}"] = bt.SECTOR_ETFS[i % 11]
    iv3["Q00"] = [(pd.Timestamp("2010-01-04"), pd.Timestamp("2019-06-03"))]
    iv3["NOPX"] = [(pd.Timestamp("2010-01-04"), None)]
    out = run(oh, iv3, sec3, portfolio=True, verbose=False)
    res = out["results"]
    if len(res) != len(CANDIDATES) or set(res["verdict"]) - {"FAIL", "PASS", "ROBUST PASS"}:
        f.append("one verdict per candidate")
    tr_ = out["trades"]
    if len(tr_) == 0 or len(tr_[tr_.setup == "PG"]) == 0:
        f.append("fixture: the synthetic index should produce PG trades")
    else:
        if (pd.to_datetime(tr_["entry_date"]) < TEST_START).any():
            f.append("no trade before the test window")
        q0 = tr_[tr_.ticker == "Q00"]
        if len(q0) and (pd.to_datetime(q0["entry_date"]) > pd.Timestamp("2019-06-04")).any():
            f.append("no new trade in a stock after it left the index")
        mk = bt.market_ok(spy["Close"])
        sig_day_ok = True
        for r_ in tr_.itertuples():
            k = cal3.get_loc(pd.Timestamp(r_.entry_date))
            if not bool(mk.iloc[k - 1]):
                sig_day_ok = False
                break
        if not sig_day_ok:
            f.append("no trade signalled while SPY was below its 200-day")
        ld = tr_[tr_.scope == "leaders"]
        if len(ld) and not ld["leader"].all():
            f.append("leaders-only trades must all be flagged as leader signals")
        for (su, sc_, tk_), g in tr_.groupby(["setup", "scope", "ticker"]):
            g = g.sort_values("entry_date")
            if (pd.to_datetime(g["entry_date"]).iloc[1:].to_numpy() < pd.to_datetime(g["exit_date"]).iloc[:-1].to_numpy()).any():
                f.append(f"overlapping trades in {tk_} {su} {sc_}: one open trade per stock and setup")
                break
        a_n = len(tr_[(tr_.setup == "PG") & (tr_.scope == "all")]); l_n = len(tr_[(tr_.setup == "PG") & (tr_.scope == "leaders")])
        if l_n > a_n:
            f.append("leaders-only cannot have more trades than all members")
    if out["priced"] != 24 or out["members"] != 25 or "port_cagr_pct" not in res.columns:
        f.append(f"members {out['members']} / priced {out['priced']}; portfolio columns present")
    cv = out["coverage"].set_index("year")
    if not (90 < cv.loc[2020, "covered_pct"] < 100):
        f.append(f"coverage must reflect the unpriced member NOPX: {cv.loc[2020].to_dict()}")
    md = render(out, "sector known for 24 of 24 stocks (0 looked up this run)", "T", PRIOR_SWING_TRIALS)
    if "## Verdicts" not in md or "Missing-stock stress" not in md or "66 swing trials" not in md or "PG Power Gap" not in md:
        f.append("report sections")
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
