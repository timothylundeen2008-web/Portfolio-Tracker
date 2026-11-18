"""
lm1_lab.py  (v1.0 — 2026-11-17)
───────────────────────────────
SWING BOOK ONLY. LM1, the leadership momentum system: one idea driving every
part — the strongest stocks in a rising market tend to keep leading — tested
as a whole BOOK against SPY on years no swing test has used.
Rules and bar: claude/momentum_system_2026-11-17.md (confirmed by Matt
2026-11-17: "a good place to start"). Charter: claude/two_books_charter.md.

RULES (frozen)
  Universe   S&P 500 members on the day; close > $10; 50-day dollar volume > $25M
  Leader     leader_screen rules (five uptrend rules, strength 80+ ranked across
             that day's liquid members)
  Market     new entries only when SPY closes above its 50- AND 200-day average
  Entry      buy-stop next session, one cent above the highest high of the last
             20 sessions (signal day included); a gap above it fills at the open
  Stop       entry - 2 x ATR(14) of the signal day; skipped if more than 10% below
             the order level. Closing-basis (a close at or below it sells at the
             next open) plus a disaster stop 1 x ATR below it, intraday
  Exit       next open after a close below the 50-day average, or after the
             strength rank closes below 50 ("leadership ended")
  Add        once: next open after the first close at +1.5R or better, buy half
             the original shares; the whole position's stop moves to the
             original entry price
  Never      sector-rotation exit, profit-ladder trims, time stop
  Size       10% of equity per new position (risk = 10% x stop distance);
             8 positions; 3 per sector; total open risk at most 12% of equity
  Ranking    when there are more leaders than open slots, strongest first; one
             order per open slot (no look-ahead: orders are placed before the
             fill is known, an unfilled order leaves its slot empty that day)
  Costs      5bp a side; 10bp extra on stop fills. Idle cash earns nothing.

JUDGED (fixed before any run)
  Evidence   2005-2016 (entries 2005-01-01 .. 2016-12-31). Halves 2005-10, 2011-16.
  PASS       100+ closed trades; expectancy > 0 and PF 1.3+ in BOTH halves; the
             $10k book beats SPY per year over 2005-2016; worst book drawdown in
             2005-2016 shallower than -25%.
  ROBUST     PASS, and evidence-period expectancy > 0 under the harsh
             missing-stock stress (stock_lab.stress).
  STABLE     3 of 4 nearby settings (exit on the 40- or 60-day; stop at 1.5 or
             2.5 x ATR) also beat SPY per year over 2005-2016. (The draft's
             strength 70/90 neighbours were replaced before any real run: a dry
             run showed they select the same stocks as strength 80.)
  Design     2017-2026 is reported but is NOT evidence: it shaped the design.
  Trials     1 system + 4 nearby settings = 5. Swing trials 76 -> 81.

DATA LIMIT: free prices miss 20-45% of 2005-2016 member-days (acquired,
bankrupt, renamed). Survivors are over-represented, which flatters any long
system; the harsh stress and the per-year coverage table are the counterweight.

Run:  python lm1_lab.py            (Actions: needs network; 30-120 minutes)
      python lm1_lab.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import leader_screen as ls
import stock_lab as sl
import swing_backtest as bt
import universe_probe as up

VERSION = "1.0"
DATA_START = "2003-06-01"
EVID_START, EVID_END = pd.Timestamp("2005-01-01"), pd.Timestamp("2017-01-01")
HALF_SPLIT = pd.Timestamp("2011-01-01")
HALVES = ("2005-10", "2011-16")
START_EQUITY = 10_000.0
SLOTS, SECTOR_MAX = 8, 3
POS_PCT, HEAT_PCT = 10.0, 12.0
ATR_MULT, MAX_STOP_PCT, DISASTER_ATR = 2.0, 10.0, 1.0
HH_N, RS_EXIT = 20, 50.0
ADD_R, ADD_FRAC = 1.5, 0.5
TICK = 0.01
COST_BPS, STOP_SLIP_BPS = 5.0, 10.0
BASE = {"exit_ma": 50, "rs_min": 80.0, "atr_mult": ATR_MULT}
NEIGHBOURS = {"exit40": {**BASE, "exit_ma": 40}, "exit60": {**BASE, "exit_ma": 60},
              "stop1.5": {**BASE, "atr_mult": 1.5}, "stop2.5": {**BASE, "atr_mult": 2.5}}
# 2026-11-17, before any real run: the strength neighbours (70+ / 90+) in the draft were replaced by stop
# width (1.5 / 2.5 x ATR). A dry run showed strength 70, 80 and 90 pick the same stocks, because orders go
# to the strongest leaders first and there are far more leaders than open slots, so they tested nothing.
TRIALS = 1 + len(NEIGHBOURS)
BAR = {"min_trades": 100, "min_pf": 1.3, "max_dd_pct": -25.0, "stable_min": 3}
PRIOR_SWING_TRIALS = 76
OUT_DATA, OUT_LOGS = Path("data/lm1_lab"), Path("logs/lm1_lab")


# ── panels ──────────────────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _pct_rank(frame: pd.DataFrame) -> pd.DataFrame:
    n = frame.notna().sum(axis=1)
    r = (frame.rank(axis=1, method="average") - 1).div((n - 1).where(n > 1), axis=0) * 100
    return r.where(n > 1, 50.0).where(frame.notna())


def build_panels(series: dict, masks: dict, spy: pd.DataFrame, sector_of: dict) -> dict:
    """Day x stock arrays on SPY's calendar. Every figure for day k uses data up to day k only.
    lead_base = liquid member with the five uptrend rules (strength applied per setting)."""
    cal = pd.DatetimeIndex(spy.index)
    tick = sorted(series)
    cols = {k: {} for k in ("O", "H", "L", "C", "atr", "sma40", "sma50", "sma60", "hh", "trend", "ok",
                            "r63", "r126", "r252")}
    last_k = np.full(len(tick), -1)
    first_k = np.full(len(tick), -1)
    for j, t in enumerate(tick):
        df = series[t]
        c, v = df["Close"], df["Volume"]
        s50, s150, s200 = c.rolling(50).mean(), c.rolling(150).mean(), c.rolling(200).mean()
        hi, lo = c.rolling(252).max(), c.rolling(252).min()
        trend = ((c > s50) & (c > s150) & (c > s200) & (s50 > s150) & (s150 > s200)
                 & (s200 > s200.shift(ls.MA_RISING_SESSIONS))
                 & (c >= hi * (1 - ls.NEAR_HIGH_PCT / 100)) & (c >= lo * (1 + ls.ABOVE_LOW_PCT / 100)))
        liquid = (c > ls.MIN_PRICE) & ((c * v).rolling(50).mean() > ls.MIN_DOLLAR_VOL)
        enough = pd.Series(np.arange(len(c)) >= ls.MIN_BARS - 1, index=c.index)
        member = pd.Series(masks[t], index=c.index)
        frame = {"O": df["Open"], "H": df["High"], "L": df["Low"], "C": c, "atr": _atr(df),
                 "sma40": c.rolling(40).mean(), "sma50": s50, "sma60": c.rolling(60).mean(),
                 "hh": df["High"].rolling(HH_N).max(), "trend": trend, "ok": liquid & enough & member,
                 **{f"r{n}": c / c.shift(n) - 1 for n in ls.RS_WINDOWS}}
        for k, s in frame.items():
            cols[k][t] = s.reindex(cal)
        pos = cal.get_indexer(pd.DatetimeIndex(df.index))
        pos = pos[pos >= 0]
        if len(pos):
            first_k[j], last_k[j] = pos.min(), pos.max()
    P = {k: pd.DataFrame(v, index=cal, columns=tick) for k, v in cols.items()}
    ok = P["ok"].fillna(False).astype(bool)
    trend = P["trend"].fillna(False).astype(bool)
    ranks = [_pct_rank(P[f"r{n}"].where(ok)) for n in ls.RS_WINDOWS]
    rs = _pct_rank(sum(ranks) / len(ranks))
    sc = bt.market_ok(spy["Close"]) & sl_fast(spy["Close"])
    secs = [sector_of.get(t) or f"OTHER:{t}" for t in tick]
    out = {"cal": cal, "tick": tick, "sector": secs, "first_k": first_k, "last_k": last_k,
           "rs": rs.to_numpy(dtype=float), "lead_base": (ok & trend).to_numpy(), "mkt": sc.to_numpy(dtype=bool),
           "spy": spy["Close"]}
    for k in ("O", "H", "L", "C", "atr", "sma40", "sma50", "sma60", "hh"):
        out[k] = P[k].to_numpy(dtype=float)
    out["C_ff"] = P["C"].ffill().to_numpy(dtype=float)
    return out


def sl_fast(spy_close: pd.Series) -> pd.Series:
    """SPY above its 50-day average (trailing)."""
    return (spy_close > spy_close.rolling(50).mean()).fillna(False)


# ── the book ────────────────────────────────────────────────────────────────

def simulate(P: dict, setting: dict, k0: int = 0) -> dict:
    """Day-by-day book. Order of a day: (1) at the open: exits and adds decided last night, then new
    entries from last night's orders; (2) intraday: disaster stops; (3) at the close: stop, leadership
    and add rules; marking; (4) after the close: tonight's orders."""
    O, H, L, C, Cf, atr, hh, rs = P["O"], P["H"], P["L"], P["C"], P["C_ff"], P["atr"], P["hh"], P["rs"]
    ma = P[f"sma{setting['exit_ma']}"]
    lead = P["lead_base"] & (np.nan_to_num(rs, nan=-1.0) >= setting["rs_min"])
    cal, secs, last_k = P["cal"], P["sector"], P["last_k"]
    nd = len(cal)
    cost, slip = COST_BPS / 1e4, STOP_SLIP_BPS / 1e4
    cash = START_EQUITY
    eq_prev = START_EQUITY
    pos: dict = {}
    orders: list = []
    trades: list = []
    eq_curve, expo = [], []

    def heat() -> float:
        return sum(sum(sh * max(0.0, px - p["stop"]) for sh, px in p["lots"]) for p in pos.values())

    def close_pos(j, k, px, reason, stop_fill):
        nonlocal cash
        p = pos.pop(j)
        sh = sum(s for s, _ in p["lots"])
        c_ = cost + (slip if stop_fill else 0.0)
        cash += sh * px * (1 - c_)
        p["proceeds"] += sh * px * (1 - c_)
        pnl = p["proceeds"] - p["paid"]
        trades.append({"ticker": P["tick"][j], "sector": secs[j], "entry_date": cal[p["k_in"]], "exit_date": cal[k],
                       "entry": p["entry"], "stop0": p["stop0"], "shares0": p["sh0"], "added": p["added"],
                       "r": pnl / (p["sh0"] * p["rps"]), "pnl": pnl, "reason": reason, "open": False,
                       "bars": k - p["k_in"]})

    for k in range(k0, nd):
        # (1) open: decisions from last night
        for j in list(pos):
            p = pos[j]
            o = O[k, j]
            if p["pending"] is None:
                continue
            if not np.isfinite(o):
                continue                                   # no bar today: act at the next bar
            if p["pending"][0] == "exit":
                close_pos(j, k, o, p["pending"][1], False)
            elif p["pending"][0] == "add":
                add_sh = math.floor(p["sh0"] * ADD_FRAC)
                need = add_sh * o * (1 + cost)
                if add_sh >= 1 and need <= cash:
                    cash -= need
                    p["paid"] += need
                    p["lots"].append((add_sh, o))
                    p["added"] = True
                    p["stop"] = p["entry"]
                    p["add_px"] = o
                else:
                    p["added"] = True                      # not affordable: the one add is spent
                p["pending"] = None
        for j, level, atr_sig in orders:
            if len(pos) >= SLOTS or j in pos:
                continue
            o, h = O[k, j], H[k, j]
            if not (np.isfinite(o) and np.isfinite(h)):
                continue
            if o >= level:
                fill = o
            elif h >= level:
                fill = level
            else:
                continue
            stop = fill - setting["atr_mult"] * atr_sig
            if not (np.isfinite(stop) and stop > 0) or (fill - stop) / fill * 100 > MAX_STOP_PCT:
                continue
            sh = math.floor(eq_prev * POS_PCT / 100 / fill)
            need = sh * fill * (1 + cost)
            if sh < 1 or need > cash or heat() + sh * (fill - stop) > eq_prev * HEAT_PCT / 100 + 1e-9:
                continue
            cash -= need
            pos[j] = {"k_in": k, "entry": fill, "stop0": stop, "stop": stop, "rps": fill - stop, "atr_e": atr_sig,
                      "sh0": sh, "lots": [(sh, fill)], "paid": need, "proceeds": 0.0, "added": False, "pending": None}
        # (2) intraday disaster stops (on the entry bar, a touch counts: the worse outcome)
        for j in list(pos):
            p = pos[j]
            d = p["stop"] - DISASTER_ATR * p["atr_e"]
            lo, o = L[k, j], O[k, j]
            if np.isfinite(lo) and lo <= d:
                px = d if (p["k_in"] == k or not np.isfinite(o) or o > d) else o
                close_pos(j, k, px, "disaster stop", True)
        # (3) close
        for j in list(pos):
            p = pos[j]
            c = C[k, j]
            if not np.isfinite(c):
                continue
            if k == last_k[j] and k < nd - 1:
                close_pos(j, k, c, "prices ended (acquired or delisted)", False)
                continue
            if p["pending"] is not None:
                continue
            if c <= p["stop"]:
                p["pending"] = ("exit", "closing-basis stop")
            elif (np.isfinite(ma[k, j]) and c < ma[k, j]) or (np.isfinite(rs[k, j]) and rs[k, j] < RS_EXIT):
                p["pending"] = ("exit", "leadership ended")
            elif not p["added"] and c >= p["entry"] + ADD_R * p["rps"]:
                p["pending"] = ("add",)
        mv = sum(sum(sh for sh, _ in p["lots"]) * Cf[k, j] for j, p in pos.items())
        eq = cash + mv
        eq_curve.append(eq)
        expo.append(mv / eq if eq > 0 else 0.0)
        eq_prev = eq
        # (4) tonight's orders
        orders = []
        if P["mkt"][k] and k < nd - 1:
            open_slots = SLOTS - len(pos)
            if open_slots > 0:
                cand = np.nonzero(lead[k])[0]
                cand = [j for j in cand if j not in pos and np.isfinite(hh[k, j]) and np.isfinite(atr[k, j])
                        and setting["atr_mult"] * atr[k, j] / (hh[k, j] + TICK) * 100 <= MAX_STOP_PCT]
                cand.sort(key=lambda j: (-rs[k, j], P["tick"][j]))
                count: dict = {}
                for p_j in pos:
                    count[secs[p_j]] = count.get(secs[p_j], 0) + 1
                for j in cand:
                    if len(orders) >= open_slots:
                        break
                    if count.get(secs[j], 0) >= SECTOR_MAX:
                        continue
                    count[secs[j]] = count.get(secs[j], 0) + 1
                    orders.append((j, float(hh[k, j]) + TICK, float(atr[k, j])))
    for j, p in pos.items():
        sh = sum(s for s, _ in p["lots"])
        pnl = p["proceeds"] + sh * Cf[nd - 1, j] - p["paid"]
        trades.append({"ticker": P["tick"][j], "sector": secs[j], "entry_date": cal[p["k_in"]], "exit_date": cal[nd - 1],
                       "entry": p["entry"], "stop0": p["stop0"], "shares0": p["sh0"], "added": p["added"],
                       "r": pnl / (p["sh0"] * p["rps"]), "pnl": pnl, "reason": "open at end", "open": True,
                       "bars": nd - 1 - p["k_in"]})
    eq_s = pd.Series(eq_curve, index=cal[k0:])
    return {"equity": eq_s, "exposure": pd.Series(expo, index=cal[k0:]), "trades": trades}


# ── judging ─────────────────────────────────────────────────────────────────

def window_stats(eq: pd.Series, a: pd.Timestamp, b: pd.Timestamp) -> dict:
    return bt.series_stats(eq[(eq.index >= a) & (eq.index < b)])


def judge(sim: dict, spy: pd.Series, uncovered: dict) -> dict:
    tr = [t for t in sim["trades"] if not t["open"] and EVID_START <= t["entry_date"] < EVID_END]
    halves = {HALVES[0]: [t["r"] for t in tr if t["entry_date"] < HALF_SPLIT],
              HALVES[1]: [t["r"] for t in tr if t["entry_date"] >= HALF_SPLIT]}
    hs = {h: bt.trade_stats(v) for h, v in halves.items()}
    full = bt.trade_stats([t["r"] for t in tr])
    by_year: dict = {}
    for t in tr:
        by_year.setdefault(int(t["entry_date"].year), []).append(t["r"])
    st = sl.stress(by_year, uncovered)
    book = window_stats(sim["equity"], EVID_START, EVID_END)
    spyw = window_stats(spy, EVID_START, EVID_END)
    why = []
    if full.get("n", 0) < BAR["min_trades"]:
        why.append(f"{full.get('n', 0)} trades < {BAR['min_trades']}")
    for h in HALVES:
        if (hs[h].get("expectancy_R") or 0) <= 0:
            why.append(f"{h} expectancy {hs[h].get('expectancy_R')}R <= 0")
        if (hs[h].get("profit_factor") or 0) < BAR["min_pf"]:
            why.append(f"{h} PF {hs[h].get('profit_factor')} < {BAR['min_pf']}")
    beats = book.get("cagr_pct") is not None and spyw.get("cagr_pct") is not None and book["cagr_pct"] > spyw["cagr_pct"]
    if not beats:
        why.append(f"book {book.get('cagr_pct')}%/yr does not beat SPY {spyw.get('cagr_pct')}%/yr")
    dd = book.get("max_dd_pct")
    if dd is None or not np.isfinite(dd) or dd <= BAR["max_dd_pct"]:
        why.append(f"worst drawdown {book.get('max_dd_pct')}% not shallower than {BAR['max_dd_pct']}%")
    verdict = "FAIL" if why else ("ROBUST PASS" if (st.get("harsh_exp_R") or -1) > 0 else "PASS")
    return {"verdict": verdict, "why": "; ".join(why) or "meets every line of the bar", "full": full, "halves": hs,
            "stress": st, "book": book, "spy": spyw, "beats_spy": beats}


def coverage(iv: dict, series: dict, cal: pd.DatetimeIndex, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
    cal = cal[(cal >= a) & (cal < b)]
    need, have = {}, {}
    for t, spans in iv.items():
        m = sl.member_mask(cal, spans)
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


def run_all(P: dict, uncovered: dict, k0: int) -> dict:
    out = {"base": None, "neighbours": {}}
    sim = simulate(P, BASE, k0)
    out["base"] = {"sim": sim, "judge": judge(sim, P["spy"], uncovered)}
    for name, s in NEIGHBOURS.items():
        sm = simulate(P, s, k0)
        out["neighbours"][name] = {"sim": sm, "judge": judge(sm, P["spy"], uncovered)}
    n_beat = sum(1 for v in out["neighbours"].values() if v["judge"]["beats_spy"])
    out["stable"] = n_beat >= BAR["stable_min"]
    out["n_beat"] = n_beat
    v = out["base"]["judge"]["verdict"]
    out["final"] = v if v == "FAIL" else (v + (" and STABLE" if out["stable"] else " but NOT STABLE"))
    return out


# ── report ──────────────────────────────────────────────────────────────────

_f = sl._f


def render(out: dict, P: dict, cov: pd.DataFrame, note: str, stamp: str, before: int) -> str:
    b = out["base"]
    j, eq = b["judge"], b["sim"]["equity"]
    spy = P["spy"]
    L = [f"# LM1 leadership momentum — {stamp} (lm1_lab v{VERSION})", "",
         "Swing book only. Point-in-time S&P 500 members. **Evidence: 2005–2016.** 2017–2026 is the design period "
         "and is reported only.", "", f"## Verdict: **{out['final']}**", "", f"{j['why']}.", "",
         "| Line of the bar | Needed | LM1 |", "|---|---|---|",
         f"| Closed trades 2005–16 | 100+ | {j['full'].get('n', 0)} |"]
    for h in HALVES:
        s = j["halves"][h]
        L.append(f"| {h}: expectancy / PF | > 0 / 1.3+ | {_f(s.get('expectancy_R'), 3)}R / {_f(s.get('profit_factor'))} |")
    L += [f"| Book per year vs SPY, 2005–16 | beat SPY | {_f(j['book'].get('cagr_pct'), 2, '%')} vs {_f(j['spy'].get('cagr_pct'), 2, '%')} |",
          f"| Worst book drawdown, 2005–16 | shallower than −25% | {_f(j['book'].get('max_dd_pct'), 1, '%')} (SPY {_f(j['spy'].get('max_dd_pct'), 1, '%')}) |",
          f"| Harsh missing-stock stress (robust) | > 0 | {_f(j['stress'].get('harsh_exp_R'), 3)}R |",
          f"| Nearby settings beating SPY (stable) | 3 of 4 | {out['n_beat']} of 4 |", "",
          "## The book by period", "", "| Period | LM1 / yr | SPY / yr | LM1 worst DD | SPY worst DD | LM1 Sharpe |",
          "|---|---|---|---|---|---|"]
    for lab, a, z in (("2005–2010", EVID_START, HALF_SPLIT), ("2011–2016", HALF_SPLIT, EVID_END),
                      ("**2005–2016 (evidence)**", EVID_START, EVID_END),
                      ("2017–2026 (design, not evidence)", EVID_END, pd.Timestamp("2100-01-01"))):
        s, q = window_stats(eq, a, z), window_stats(spy, a, z)
        L.append(f"| {lab} | {_f(s.get('cagr_pct'), 2, '%')} | {_f(q.get('cagr_pct'), 2, '%')} | {_f(s.get('max_dd_pct'), 1, '%')} | "
                 f"{_f(q.get('max_dd_pct'), 1, '%')} | {_f(s.get('sharpe'))} |")
    yr = eq.resample("YE").last().pct_change().dropna() * 100
    sy = spy.resample("YE").last().pct_change().dropna() * 100
    L += ["", "## Calendar years", "", "| Year | LM1 | SPY | Avg invested |", "|---|---|---|---|"]
    ex = b["sim"]["exposure"].groupby(b["sim"]["exposure"].index.year).mean() * 100
    for y in yr.index:
        L.append(f"| {y.year} | {yr[y]:+.1f}% | {sy.get(y, float('nan')):+.1f}% | {ex.get(y.year, float('nan')):.0f}% |")
    tr = pd.DataFrame(b["sim"]["trades"])
    if len(tr):
        ev = tr[(~tr["open"]) & (tr["entry_date"] >= EVID_START) & (tr["entry_date"] < EVID_END)]
        L += ["", "## Trades, 2005–2016", "",
              f"- {len(ev)} closed trades; win rate {_f(j['full'].get('win_rate'), 1, '%')}; average win "
              f"{_f(j['full'].get('avg_win_R'))}R, average loss {_f(j['full'].get('avg_loss_R'))}R; longest losing run "
              f"{j['full'].get('max_consec_losses')}; median hold {int(ev['bars'].median()) if len(ev) else 0} sessions; "
              f"{int(ev['added'].sum()) if len(ev) else 0} trades added to.",
              "- How they ended: " + "; ".join(f"{k} {n}" for k, n in ev["reason"].value_counts().items()) + "."]
    L += ["", "## Nearby settings (stability)", "",
          "| Setting | 2005–16 / yr | Worst DD | Trades | Beats SPY | Verdict on its own |", "|---|---|---|---|---|---|",
          f"| base (exit 50-day, stop 2 x ATR) | {_f(j['book'].get('cagr_pct'), 2, '%')} | {_f(j['book'].get('max_dd_pct'), 1, '%')} | "
          f"{j['full'].get('n', 0)} | {'yes' if j['beats_spy'] else 'no'} | {j['verdict']} |"]
    for name, v in out["neighbours"].items():
        q = v["judge"]
        L.append(f"| {name} | {_f(q['book'].get('cagr_pct'), 2, '%')} | {_f(q['book'].get('max_dd_pct'), 1, '%')} | "
                 f"{q['full'].get('n', 0)} | {'yes' if q['beats_spy'] else 'no'} | {q['verdict']} |")
    L += ["", "## Data", "", f"- {note}", "", "| Year | Member-days | With prices | Covered |", "|---|---|---|---|"]
    L += [f"| {x.year} | {x.member_days} | {x.priced_days} | {x.covered_pct}% |" for x in cov.itertuples()]
    L += ["", "## Limits", "",
          "- Free prices miss many 2005–2016 members; survivors are over-represented, which flatters a long system. "
          "The harsh stress is the counterweight.",
          "- No earnings history (live rules avoid holding stocks through earnings); sectors are today's GICS sectors.",
          "- A gap above the buy-stop fills at the open; the live 0.25×ATR entry limit is not modelled.",
          "- Idle cash earns nothing here; live it would sit in T-bills.", "",
          f"Trials: {TRIALS} in this run; {before + TRIALS} swing trials to date.", ""]
    return "\n".join(L)


def prior_trials() -> int:
    try:
        return int(pd.read_csv(OUT_DATA / "trial_log.csv")["trials"].sum())
    except Exception:
        return 0


def main() -> int:
    mem, iv = sl.load_membership()
    members = sl.members_in_window(iv, EVID_START)
    syms = sorted({up.yahoo_symbol(t) for t in members} | {v for k, v in up.RENAMES.items() if k in members} | {"SPY"})
    print(f"[lm1_lab] v{VERSION}: {len(members)} members since {EVID_START.date()}; fetching {len(syms)} symbols from {DATA_START}")
    ohlcv = {}
    for i in range(0, len(syms), 150):
        ohlcv.update(bt.fetch_ohlcv(syms[i:i + 150], start=DATA_START))
        print(f"[lm1_lab] {min(i + 150, len(syms))}/{len(syms)} requested, {len(ohlcv)} with data")
    if "SPY" not in ohlcv:
        print("[lm1_lab] DATA FAILURE: no SPY; nothing written.")
        return 1
    have = set(ohlcv)
    series = {t: ohlcv[sl.symbol_for(t, have)] for t in members if sl.symbol_for(t, have)}
    if len(series) < 0.5 * len(members):
        print(f"[lm1_lab] DATA FAILURE: prices for only {len(series)} of {len(members)}; nothing written.")
        return 1
    sector_of, sec_note = sl.sector_map(sorted(series), lookup=sl.yahoo_sector)
    masks = {t: sl.member_mask(pd.DatetimeIndex(df.index), iv[t]) for t, df in series.items()}
    spy = ohlcv["SPY"]
    print(f"[lm1_lab] {len(series)} members priced; {sec_note}; building panels")
    P = build_panels(series, masks, spy, sector_of)
    cov = coverage(iv, series, P["cal"], EVID_START, EVID_END)
    uncovered = {int(r.year): 1 - r.covered_pct / 100 for r in cov.itertuples()}
    k0 = int(P["cal"].searchsorted(EVID_START))
    out = run_all(P, uncovered, k0)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_LOGS.mkdir(parents=True, exist_ok=True)
    first = prior_trials() == 0
    before = PRIOR_SWING_TRIALS + (0 if first else TRIALS)
    pd.DataFrame(out["base"]["sim"]["trades"]).to_csv(OUT_DATA / "trades.csv", index=False)
    eqs = {"LM1": out["base"]["sim"]["equity"], **{k: v["sim"]["equity"] for k, v in out["neighbours"].items()},
           "SPY": P["spy"][P["spy"].index >= EVID_START]}
    pd.DataFrame(eqs).round(2).to_csv(OUT_DATA / "equity.csv")
    cov.to_csv(OUT_DATA / "coverage.csv", index=False)
    summ = {"verdict": out["final"], "base": {k: v for k, v in out["base"]["judge"].items()},
            "neighbours": {k: v["judge"] for k, v in out["neighbours"].items()}, "n_beat": out["n_beat"]}
    (OUT_DATA / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
    tl = OUT_DATA / "trial_log.csv"
    row = pd.DataFrame([{"date": stamp, "version": VERSION, "trials": TRIALS if first else 0,
                         "note": "LM1 + 4 nearby settings" if first else "re-run"}])
    (pd.concat([pd.read_csv(tl), row]) if tl.exists() else row).to_csv(tl, index=False)
    note = f"{len(members)} members since 2005; {len(series)} priced; {sec_note}."
    md = render(out, P, cov, note, stamp, before)
    (OUT_LOGS / f"{stamp}_report.md").write_text(md)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _panel(n_days: int, prices: dict, lead: dict = None, rs: dict = None, mkt=None, sectors=None, atr=1.0) -> dict:
    """A hand-built panel: prices = ticker -> (O, H, L, C) arrays."""
    cal = pd.bdate_range("2005-01-03", periods=n_days)
    tick = sorted(prices)
    nt = len(tick)
    P = {"cal": cal, "tick": tick, "sector": [(sectors or {}).get(t, f"S{t}") for t in tick],
         "first_k": np.zeros(nt, int), "last_k": np.full(nt, n_days - 1)}
    for i, key in enumerate(("O", "H", "L", "C")):
        P[key] = np.column_stack([np.asarray(prices[t][i], dtype=float) for t in tick])
    P["C_ff"] = pd.DataFrame(P["C"]).ffill().to_numpy()
    P["atr"] = np.full((n_days, nt), float(atr))
    for m in (40, 50, 60):
        P[f"sma{m}"] = np.zeros((n_days, nt))                    # below every price: never an exit
    P["hh"] = pd.DataFrame(P["H"]).rolling(HH_N, min_periods=1).max().to_numpy()
    P["rs"] = np.column_stack([np.asarray((rs or {}).get(t, np.full(n_days, 95.0)), dtype=float) for t in tick])
    P["lead_base"] = np.column_stack([np.asarray((lead or {}).get(t, np.ones(n_days, bool)), dtype=bool) for t in tick])
    P["mkt"] = np.ones(n_days, bool) if mkt is None else np.asarray(mkt, bool)
    P["spy"] = pd.Series(np.linspace(100, 110, n_days), index=cal)
    return P


def _flat(n, px=100.0):
    a = np.full(n, px)
    return [a.copy(), a + 0.5, a - 0.5, a.copy()]


def selftest() -> dict:
    f = []
    n = 60
    # ── entry: buy-stop above the 20-day high; a gap fills at the open ──
    o, h, l, c = _flat(n)
    h[30] = 103.0                            # day 31 trades through the level 100.51
    P = _panel(n, {"A": [o, h, l, c]}, lead={"A": np.r_[np.zeros(29, bool), np.ones(n - 29, bool)]})
    r = simulate(P, BASE)
    t0 = r["trades"][0] if r["trades"] else None
    if not t0 or t0["entry_date"] != P["cal"][30] or abs(t0["entry"] - (100.5 + TICK)) > 1e-9:
        f.append(f"entry: buy-stop at the 20-day high + 1c, the session after the first leader day: {t0}")
    if t0 and abs(t0["stop0"] - (t0["entry"] - 2.0)) > 1e-9:
        f.append("initial stop = entry - 2 x ATR")
    if t0 and t0["shares0"] != math.floor(START_EQUITY * 0.10 / t0["entry"]):
        f.append(f"size = 10% of equity: {t0['shares0']}")
    o2, h2, l2, c2 = _flat(n)
    o2[30], h2[30], l2[30], c2[30] = 104.0, 105.0, 103.5, 104.5
    o2[31:], h2[31:], l2[31:], c2[31:] = 104.5, 105.0, 104.0, 104.5
    P2 = _panel(n, {"A": [o2, h2, l2, c2]}, lead={"A": np.r_[np.zeros(29, bool), np.ones(n - 29, bool)]})
    t2 = simulate(P2, BASE)["trades"]
    if not t2 or abs(t2[0]["entry"] - 104.0) > 1e-9:
        f.append("a gap above the buy-stop fills at the open")
    # no leader / market closed / stop too wide -> no trade
    if simulate(_panel(n, {"A": [o, h, l, c]}, lead={"A": np.zeros(n, bool)}), BASE)["trades"]:
        f.append("no trade without a leader signal")
    if simulate(_panel(n, {"A": [o, h, l, c]}, mkt=np.zeros(n, bool)), BASE)["trades"]:
        f.append("no trade while the market filter is closed")
    if simulate(_panel(n, {"A": [o, h, l, c]}, atr=6.0), BASE)["trades"]:
        f.append("no trade when 2 x ATR is more than 10% below the order level")
    if simulate(_panel(n, {"A": [o, h, l, c]}, rs={"A": np.full(n, 75.0)}), BASE)["trades"]:
        f.append("no trade below strength 80")
    tw = simulate(_panel(n, {"A": [o, h, l, c]}, atr=4.5), NEIGHBOURS["stop2.5"])["trades"]
    tn = simulate(_panel(n, {"A": [o, h, l, c]}, atr=4.5), NEIGHBOURS["stop1.5"])["trades"]
    if tw or not tn or abs(tn[0]["stop0"] - (tn[0]["entry"] - 1.5 * 4.5)) > 1e-9:
        f.append("stop width follows the setting: 2.5 x 4.5 = 11.25% skipped, 1.5 x 4.5 kept")
    # look-ahead: the order level must come from the signal day, not the fill day
    o3, h3, l3, c3 = _flat(n)
    h3[30] = 130.0
    P3 = _panel(n, {"A": [o3, h3, l3, c3]}, lead={"A": np.r_[np.zeros(29, bool), np.ones(n - 29, bool)]})
    t3 = simulate(P3, BASE)["trades"]
    if not t3 or t3[0]["entry_date"] != P3["cal"][30] or abs(t3[0]["entry"] - 100.51) > 1e-9:
        f.append("the order placed on day 29 uses day 29's 20-day high (no look-ahead)")
    # ── closing-basis stop: a close at or below sells at the next open ──
    o4, h4, l4, c4 = _flat(n)
    h4[30] = 101.0
    c4[35], l4[35], o4[36] = 98.4, 98.3, 97.0           # stop 98.51; disaster 97.51 not touched on day 35
    P4 = _panel(n, {"A": [o4, h4, l4, c4]}, lead={"A": np.r_[np.zeros(29, bool), np.ones(n - 29, bool)]})
    t4 = simulate(P4, BASE)["trades"]
    if not t4 or t4[0]["reason"] != "closing-basis stop" or t4[0]["exit_date"] != P4["cal"][36]:
        f.append(f"closing-basis stop exits at the next open: {t4[:1]}")
    elif abs(t4[0]["r"] - ((97.0 * (1 - 5e-4) * t4[0]['shares0'] - 100.51 * (1 + 5e-4) * t4[0]['shares0']) / (t4[0]['shares0'] * 2.0))) > 1e-6:
        f.append(f"R must include costs: {t4[0]['r']}")
    # ── disaster stop intraday ──
    o5, h5, l5, c5 = _flat(n)
    h5[30] = 101.0
    o5[33], l5[33], c5[33] = 99.0, 96.0, 99.0           # disaster = 98.51 - 1 = 97.51
    P5 = _panel(n, {"A": [o5, h5, l5, c5]}, lead={"A": np.r_[np.zeros(29, bool), np.ones(n - 29, bool)]})
    t5 = simulate(P5, BASE)["trades"]
    if not t5 or t5[0]["reason"] != "disaster stop" or t5[0]["exit_date"] != P5["cal"][33]:
        f.append("disaster stop fires intraday")
    o5b = o5.copy(); o5b[33] = 96.5
    t5b = simulate(_panel(n, {"A": [o5b, h5, l5, c5]}, lead={"A": np.r_[np.zeros(29, bool), np.ones(n - 29, bool)]}), BASE)["trades"]
    if not t5b or t5b[0]["reason"] != "disaster stop":
        f.append("a gap below the disaster stop exits at the open")
    else:
        sh = t5b[0]["shares0"]
        want = (96.5 * (1 - 15e-4) * sh - 100.51 * (1 + 5e-4) * sh) / (sh * 2.0)
        if abs(t5b[0]["r"] - want) > 1e-6:
            f.append("a gap through the disaster stop fills at the open, with slippage")
    # ── leadership exit: close below the 50-day, or strength below 50 ──
    for label, kw in (("50-day", {}), ("strength", {"rs": {"A": np.r_[np.full(40, 95.0), np.full(n - 40, 45.0)]}})):
        o6, h6, l6, c6 = _flat(n)
        h6[30] = 101.0
        P6 = _panel(n, {"A": [o6, h6, l6, c6]}, lead={"A": np.r_[np.zeros(29, bool), np.ones(n - 29, bool)]}, **kw)
        if label == "50-day":
            P6["sma50"][40, 0] = 200.0
        t6 = simulate(P6, BASE)["trades"]
        if not t6 or t6[0]["reason"] != "leadership ended" or t6[0]["exit_date"] != P6["cal"][41]:
            f.append(f"leadership exit ({label}) at the next open: {t6[:1]}")
    o6b, h6b, l6b, c6b = _flat(n)
    h6b[30] = 101.0
    P6b = _panel(n, {"A": [o6b, h6b, l6b, c6b]}, lead={"A": np.r_[np.zeros(29, bool), np.ones(n - 29, bool)]})
    P6b["sma60"][40, 0] = 200.0
    if simulate(P6b, BASE)["trades"][0]["reason"] == "leadership ended" or \
            simulate(P6b, NEIGHBOURS["exit60"])["trades"][0]["reason"] != "leadership ended":
        f.append("the exit average follows the setting (50 base, 60 for exit60)")
    # ── add at +1.5R: half the shares, stop to entry ──
    o7, h7, l7, c7 = _flat(n)
    h7[30] = 101.0
    c7[38], h7[38] = 103.6, 103.7                      # entry 100.51, 1R = 2.0, +1.5R = 103.51
    o7[39:], h7[39:], l7[39:], c7[39:] = 104.0, 104.5, 103.5, 104.0
    c7[45], l7[45], o7[46] = 100.4, 100.3, 100.2        # back below entry: the moved stop closes it
    P7 = _panel(n, {"A": [o7, h7, l7, c7]}, lead={"A": np.r_[np.zeros(29, bool), np.ones(n - 29, bool)]})
    t7 = simulate(P7, BASE)["trades"]
    if not t7 or not t7[0]["added"] or t7[0]["reason"] != "closing-basis stop" or t7[0]["exit_date"] != P7["cal"][46]:
        f.append(f"add once at +1.5R, then the stop sits at the entry price: {t7[:1]}")
    else:
        sh0 = t7[0]["shares0"]; add = math.floor(sh0 * ADD_FRAC)
        paid = sh0 * 100.51 * (1 + 5e-4) + add * 104.0 * (1 + 5e-4)
        got = (sh0 + add) * 100.2 * (1 - 5e-4)
        if abs(t7[0]["pnl"] - (got - paid)) > 1e-6:
            f.append("add bought at the next open; the whole position sold together")
    # ── slots, ranking, sector cap, heat ──
    many = {f"T{i}": _flat(n) for i in range(12)}
    for v in many.values():
        v[1][30] = 101.0
    rsd = {f"T{i}": np.full(n, 99.0 - i) for i in range(12)}
    leadd = {t: np.r_[np.zeros(29, bool), np.ones(n - 29, bool)] for t in many}
    Pm = _panel(n, many, lead=leadd, rs=rsd, sectors={t: f"S{i % 6}" for i, t in enumerate(many)}, atr=0.5)
    tm = simulate(Pm, BASE)
    held = sorted({x["ticker"] for x in tm["trades"]})
    if held != sorted(f"T{i}" for i in range(8)):
        f.append(f"8 slots, strongest first: {held}")
    Ps = _panel(n, many, lead=leadd, rs=rsd, sectors={t: "SAME" for t in many}, atr=0.5)
    if len({x["ticker"] for x in simulate(Ps, BASE)["trades"]}) != SECTOR_MAX:
        f.append("at most 3 per sector")
    Ph = _panel(n, many, lead=leadd, rs=rsd, atr=4.5)      # stop 9% -> 0.9% risk each; 12% heat allows 13 -> slots bind
    Ph2 = _panel(n, many, lead=leadd, rs=rsd, atr=4.9)
    if len({x["ticker"] for x in simulate(Ph, BASE)["trades"]}) != 8:
        f.append("heat at 0.9% a position leaves 8 slots binding")
    ex = simulate(Ph2, BASE)
    if any(e > 1.0 + 1e-9 for e in ex["exposure"]):
        f.append("never more than fully invested (no margin)")
    # ── prices end: a held stock that stops trading is sold at its last close ──
    o8, h8, l8, c8 = _flat(n)
    h8[30] = 101.0
    P8 = _panel(n, {"A": [o8, h8, l8, c8], "B": _flat(n)}, lead={"A": np.r_[np.zeros(29, bool), np.ones(n - 29, bool)],
                                                                 "B": np.zeros(n, bool)})
    for k_ in ("O", "H", "L", "C"):
        P8[k_][45:, 0] = np.nan
    P8["C_ff"] = pd.DataFrame(P8["C"]).ffill().to_numpy()
    P8["last_k"][0] = 44
    t8 = simulate(P8, BASE)["trades"]
    if not t8 or not t8[0]["reason"].startswith("prices ended") or t8[0]["exit_date"] != P8["cal"][44]:
        f.append("a stock whose prices end is closed at its last close")
    # ── cash accounting: the book equals cash + positions every day ──
    eqv = tm["equity"]
    if eqv.iloc[0] != START_EQUITY or (eqv <= 0).any():
        f.append("equity curve starts at $10,000 and stays positive")

    # ── panels: leader flag and strength equal leader_screen's own functions ──
    rng = np.random.default_rng(1)
    cal = pd.bdate_range("2003-06-02", periods=700)
    series, masks = {}, {}
    for i in range(50):
        cc = (20 + i) * np.cumprod(1 + (-0.0006 + i * 0.00005) + rng.normal(0, 0.006, 700))
        d = pd.DataFrame({"Open": cc, "High": cc * 1.01, "Low": cc * 0.99, "Close": cc,
                          "Volume": np.full(700, 3e6 if i % 9 else 1e3)}, index=cal)
        series[f"S{i:02d}"] = d
        masks[f"S{i:02d}"] = np.ones(700, bool)
    masks["S48"] = np.asarray(cal < cal[600])
    spy = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": np.linspace(100, 150, 700), "Volume": 1e8}, index=cal)
    PP = build_panels(series, masks, spy, {})
    for day in (cal[300], cal[560], cal[650]):
        k = cal.get_loc(day)
        mets = {t: ls.metrics(d[d.index <= day]) for t, d in series.items() if masks[t][k]}
        tb = ls.rank(mets)
        want = set(tb.loc[tb["leader"], "ticker"]) if len(tb) else set()
        got = {PP["tick"][j] for j in np.nonzero(PP["lead_base"][k] & (np.nan_to_num(PP["rs"][k], nan=-1) >= 80))[0]}
        if want != got:
            f.append(f"panel leaders != leader_screen on {day.date()}: {sorted(want ^ got)[:6]}")
            break
        rs_tb = tb.set_index("ticker")["rs"].dropna()
        rs_pp = pd.Series(PP["rs"][k], index=PP["tick"]).dropna()
        if not np.allclose(rs_tb.sort_index().to_numpy(), rs_pp.reindex(rs_tb.index).sort_index().to_numpy(), atol=1e-6):
            f.append("panel strength must equal leader_screen's strength")
            break
    s2 = dict(series); s2["S10"] = series["S10"].copy(); s2["S10"].iloc[-1, 3] *= 4
    PP2 = build_panels(s2, masks, spy, {})
    if not np.array_equal(PP2["lead_base"][:-1], PP["lead_base"][:-1]) or \
            not np.allclose(np.nan_to_num(PP2["rs"][:-1]), np.nan_to_num(PP["rs"][:-1])):
        f.append("panels must use trailing data only")
    k660 = cal.get_loc(cal[660])
    if PP["lead_base"][k660, PP["tick"].index("S48")]:
        f.append("no leader on a day the stock is not a member")
    mk = PP["mkt"]
    if mk[:199].any():
        f.append("market filter needs the 200-day average")

    # ── judging ──
    eq = pd.Series(np.linspace(10_000, 30_000, 3000), index=pd.bdate_range("2005-01-03", periods=3000))
    spy_s = pd.Series(np.linspace(100, 200, 3000), index=eq.index)
    trs = [{"entry_date": pd.Timestamp("2006-03-01"), "r": 1.0, "open": False}] * 60 + \
          [{"entry_date": pd.Timestamp("2006-03-01"), "r": -0.5, "open": False}] * 30 + \
          [{"entry_date": pd.Timestamp("2013-03-01"), "r": 1.0, "open": False}] * 30 + \
          [{"entry_date": pd.Timestamp("2013-03-01"), "r": -0.5, "open": False}] * 20 + \
          [{"entry_date": pd.Timestamp("2018-03-01"), "r": -5.0, "open": False}] * 50
    jj = judge({"equity": eq, "trades": trs}, spy_s, {2006: 0.3, 2013: 0.1})
    if jj["full"]["n"] != 140 or jj["verdict"] not in ("PASS", "ROBUST PASS"):
        f.append(f"judge: only 2005-16 trades count; a strong book passes: {jj['verdict']} {jj['why']}")
    flat_eq = pd.Series(10_000.0, index=eq.index)
    if judge({"equity": flat_eq, "trades": trs}, spy_s, {})["verdict"] != "FAIL":
        f.append("a book that does not beat SPY fails")
    dd_eq = eq.copy(); dd_eq.iloc[1000:1200] *= 0.7
    if judge({"equity": dd_eq, "trades": trs}, spy_s, {})["verdict"] != "FAIL":
        f.append("a -30% drawdown fails")
    few = [t for t in trs if t["entry_date"].year < 2011]
    if judge({"equity": eq, "trades": few}, spy_s, {})["verdict"] != "FAIL":
        f.append("a half with no trades fails")
    if TRIALS != 5:
        f.append("5 trials")
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
