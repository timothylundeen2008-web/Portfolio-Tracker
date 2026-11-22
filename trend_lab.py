"""
trend_lab.py  (v1.0 — 2026-11-21)
──────────────────────────────────
Swing book only. Pre-registered tests S3 and S4 of the swing-direction menu
(claude/swing_direction_options_2026-11-21.md). Pre-registration with bars:
claude/trend_lab_2026-11-21.md. Bars below are fixed BEFORE any run on real prices;
a FAIL is final. Built on the lever-lab lessons: size 3x positions for GAP risk, judge
payoff (avg win / avg loss) not win size, and test the writer and downloads end to end.

S3  LEVERAGED TREND. One sleeve per index (SPY -> synthetic 3x like UPRO; QQQ -> like TQQQ).
      ON at a close when, for 2 closes in a row: close > 200-day, 200-day rising (vs 20
        sessions ago) and close > 50-day. Enter at the next open.
      OFF when the index closes below its 50-day for 2 closes, OR the sleeve is -20% from
        its high since entry (hard trail) -> exit next open. After the hard trail, no
        re-entry until the ON condition has failed at least once (fresh trend).
      Size (gap risk): at entry, sleeve = min(40%, 15% / (3 x 20-day index vol, annualized))
        of equity; held without rebalancing until exit. Two sleeves -> at most 80% of equity in
        3x funds, typically ~45-70% in calm uptrends.
      Synthetic 3x: 3 x daily return - 2 x (T-bill + 0.5%/yr) - 0.95%/yr; 5bp a side.

S4  BEAR, FAILED RALLY, inverse 3x (like SPXU / SQQQ; Matt 2026-11-21: inverse funds OK,
      no margin shorts).
      Bear state at a close: close < 200-day, 200-day falling (vs 20 sessions ago), close < 50-day.
      Trigger: in a bear state, the day's high reaches within 1% of the falling 50-day and the
        index closes down on the day. Enter the inverse fund at the next open.
      Exits (index closes, executed next open): stop when the index closes more than 2% above
        its 50-day; target when the index is -10% from the entry open; once the index closes
        -5% or lower the stop moves to the entry; time stop after 30 sessions.
      One position at a time across SPY and QQQ (QQQ first if both trigger). Size 25% of equity.
      Synthetic inverse 3x: -3 x daily return + 4 x T-bill - 3 x 0.5%/yr - 0.95%/yr; 5bp a side,
        stops 10bp extra. Checked against real SPXU / SQQQ.
    Index puts were not modeled: one SPY or QQQ put near 0.70 delta costs ~$6,000+ on a
      $10,000 account (lever lab, 2026-11-21).

Run:  python trend_lab.py            (Actions; needs yfinance)
      python trend_lab.py --selftest (offline)
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from lever_lab import (trade_stats, nav_stats, hwm_stops, year_returns, _jsonable)

VERSION = "1.0"
OUT_DATA, OUT_LOGS = Path("data/trend_lab"), Path("logs/trend_lab")
TRIALS_BEFORE, TRIALS_HERE = 94, 2
START = "2000-01-01"
HALVES = (("2000-12", "2000-01-01", "2012-12-31"), ("2013-26", "2013-01-01", "2100-01-01"))
FIN_SPREAD, FEE, COST_BPS, STOP_BPS = 0.005, 0.0095, 5.0, 10.0

# S3 (pre-registered)
S3 = {"sma_long": 200, "sma_fast": 50, "slope": 20, "confirm": 2, "trail": 0.20, "cap": 0.40, "vol_target": 0.15,
      "vol_win": 20}
S3_BAR = {"min_trades": 30, "min_pf": 1.5, "min_payoff": 2.0, "max_dd": -30.0, "worst_2d": -15.0, "worst_year": -20.0}
S3_NEIGHBOURS = [("sma_long", 150), ("sma_long", 250), ("vol_target", 0.10), ("vol_target", 0.20),
                 ("trail", 0.15), ("trail", 0.25)]
# S4 (pre-registered)
S4 = {"sma_long": 200, "sma_fast": 50, "slope": 20, "touch": 0.99, "stop_band": 1.02, "target": 0.10, "be": 0.05,
      "days": 30, "size": 0.25}
S4_BAR = {"min_trades": 20, "min_half": 5, "min_pf": 1.5, "min_payoff": 2.0, "worst_trade_eq": -8.0, "max_dd": -15.0,
          "excess_pts": 1.0}
S4_NEIGHBOURS = [("touch", 0.98), ("touch", 1.00), ("target", 0.08), ("target", 0.12), ("stop_band", 1.01),
                 ("stop_band", 1.03)]
STRESS = {"spread_mult": 2.0, "extra_bps": 10.0, "stop_bps": 60.0}


def _log(msg: str) -> None:
    print(f"[trend_lab {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# ── synthetic leveraged funds ───────────────────────────────────────────────

def lev_daily(r: pd.Series, rf_d: pd.Series, k: float, spread_mult: float = 1.0) -> pd.Series:
    """Daily return of a k x fund (k = 3 or -3) from the index's daily return r.
    Long  (k>0): k r - (k-1)(rf + s) - fee.   Inverse (k<0): k r + (1-k) rf - |k| s - fee."""
    rf = rf_d.reindex(r.index).ffill().fillna(0.0)
    s = FIN_SPREAD * spread_mult / 252
    if k > 0:
        return k * r - (k - 1) * (rf + s) - FEE / 252
    return k * r + (1 - k) * rf - abs(k) * s - FEE / 252


def lev_check(idx_close: pd.Series, real: Optional[pd.Series], rf_d: pd.Series, k: float) -> dict:
    if real is None or real.dropna().empty:
        return {"note": "no data"}
    syn = lev_daily(idx_close.pct_change(), rf_d, k)
    both = pd.DataFrame({"syn": syn, "real": real.pct_change()}).dropna()
    if both.empty:
        return {"note": "no overlap"}
    y = (1 + both).resample("YE").prod() - 1
    d = (y["syn"] - y["real"]) * 100
    return {"years": int(len(y)), "mean_diff_pts": round(float(d.mean()), 2),
            "worst_diff_pts": round(float(d.abs().max()), 2), "daily_corr": round(float(both.corr().iloc[0, 1]), 4)}


def _position_path(df: pd.DataFrame, e: int, x: int, k: float, ld: np.ndarray, exit_at_open: bool) -> dict:
    """Value path (start 1.0) of a k x position entered at the open of bar e and exited at the open
    of bar x (exit_at_open) or marked at the close of bar x (data end)."""
    o, c, idx = df["Open"].to_numpy(), df["Close"].to_numpy(), df.index
    path, val = {}, 1.0
    for t in range(e, x + 1):
        if t == x and exit_at_open and t > e:
            val *= 1 + k * (o[t] / c[t - 1] - 1)          # overnight gap into the exit open
            path[idx[t]] = val
            break
        if t == e:
            # open -> close on the entry day, plus that day's financing and fee from the daily series
            carry = ld[t] - k * (c[t] / c[t - 1] - 1) if t > 0 else 0.0
            val *= 1 + k * (c[t] / o[t] - 1) + carry
        else:
            val *= 1 + ld[t]
        path[idx[t]] = val
    return path


# ═══════════════════════════════════════════════════════════════════════════
#  S3 — leveraged trend
# ═══════════════════════════════════════════════════════════════════════════

def s3_trades(name: str, df: pd.DataFrame, rf_d: pd.Series, p: dict = S3, spread_mult=1.0, extra_bps=0.0) -> list:
    c = df["Close"]
    sl, sf = c.rolling(p["sma_long"]).mean(), c.rolling(p["sma_fast"]).mean()
    on = (c > sl) & (sl > sl.shift(p["slope"])) & (c > sf)
    on2 = on.copy()
    for j in range(1, p["confirm"]):
        on2 &= on.shift(j, fill_value=False)
    off = c < sf
    off2 = off & off.shift(1, fill_value=False)
    vol = c.pct_change().rolling(p["vol_win"]).std() * math.sqrt(252)
    ld = lev_daily(c.pct_change(), rf_d, 3.0, spread_mult).fillna(0.0).to_numpy()
    onv, on2v, off2v, volv = on.to_numpy(), on2.to_numpy(), off2.to_numpy(), vol.to_numpy()
    n, out, t, armed = len(df), [], 0, True
    while t < n - 1:
        if not onv[t]:
            armed = True
        if not (armed and on2v[t] and np.isfinite(volv[t]) and volv[t] > 0):
            t += 1
            continue
        e = t + 1
        size = min(p["cap"], p["vol_target"] / (3 * volv[t]))
        val, peak, x, why = 1.0, 1.0, None, None
        for u in range(e, n):
            if u == e:
                val *= 1 + 3 * (df["Close"].iat[u] / df["Open"].iat[u] - 1) + (ld[u] - 3 * (c.iat[u] / c.iat[u - 1] - 1))
            else:
                val *= 1 + ld[u]
            peak = max(peak, val)
            if val / peak - 1 <= -p["trail"]:
                why = "trail"
            elif off2v[u]:
                why = "trend off"
            if why:
                if u + 1 < n:
                    x = u + 1
                break
        if x is None:
            x, why, at_open = n - 1, (why or "open at end"), False
        else:
            at_open = True
        path = _position_path(df, e, x, 3.0, ld, at_open)
        bps = 2 * (COST_BPS + extra_bps)
        fin = list(path.values())[-1] * (1 - bps / 1e4)
        path[df.index[x]] = fin
        out.append({"index": name, "signal": df.index[t], "entry_date": df.index[e], "exit_date": df.index[x],
                    "why": why, "size": float(size), "ret": fin - 1.0, "path": path, "sessions": int(x - e)})
        if why == "trail":
            armed = False
        t = x
    return out


def book(trades: list, cal: pd.DatetimeIndex, cash_r: pd.Series, size_key: Optional[str] = "size",
         fixed: Optional[float] = None) -> pd.Series:
    """Equity curve: each trade takes size x equity (prior close) at its entry; several can be open at
    once (one per index for S3). Idle cash earns T-bills."""
    cash, nav, prev = 10_000.0, [], 10_000.0
    cr = cash_r.reindex(cal).fillna(0.0).to_numpy()
    starts = {}
    for tr in trades:
        starts.setdefault(tr["entry_date"], []).append(tr)
    open_ = []
    for i, d in enumerate(cal):
        cash *= 1 + cr[i]
        for tr in starts.get(d, []):
            amt = (fixed if fixed is not None else tr[size_key]) * prev
            cash -= amt
            open_.append({"t": tr, "amt": amt, "v": 1.0})
        val, keep = 0.0, []
        for p in open_:
            p["v"] = p["t"]["path"].get(d, p["v"])
            if d >= p["t"]["exit_date"]:
                cash += p["amt"] * p["v"]
            else:
                val += p["amt"] * p["v"]
                keep.append(p)
        open_ = keep
        eq = cash + val
        nav.append(eq)
        prev = eq
    return pd.Series(nav, index=cal)


def worst_window(nav: pd.Series, days: int) -> float:
    return float(((nav / nav.shift(days)) - 1).min() * 100)


# ═══════════════════════════════════════════════════════════════════════════
#  S4 — bear, failed rally, inverse 3x
# ═══════════════════════════════════════════════════════════════════════════

def s4_trades(idx: dict, rf_d: pd.Series, p: dict = S4, spread_mult=1.0, stop_bps=STOP_BPS) -> list:
    sig = []
    pre = {}
    for name, df in idx.items():
        c, h = df["Close"], df["High"]
        sl, sf = c.rolling(p["sma_long"]).mean(), c.rolling(p["sma_fast"]).mean()
        bear = (c < sl) & (sl < sl.shift(p["slope"])) & (c < sf)
        trig = bear & (h >= p["touch"] * sf) & (c < c.shift(1))
        for d in df.index[trig.fillna(False).to_numpy()]:
            sig.append((d, 0 if name == "QQQ" else 1, name))
        pre[name] = (sf.to_numpy(), lev_daily(c.pct_change(), rf_d, -3.0, spread_mult).fillna(0.0).to_numpy())
    out, busy = [], pd.Timestamp.min
    for d, _pri, name in sorted(sig):
        if d <= busy:
            continue
        df = idx[name]
        sf, ld = pre[name]
        i = df.index.get_loc(d)
        if i + 1 >= len(df):
            continue
        o, c = df["Open"].to_numpy(), df["Close"].to_numpy()
        e = i + 1
        entry = o[e]
        be_on, x, why = False, None, None
        for u in range(e, len(df)):
            if c[u] <= entry * (1 - p["be"]):
                be_on = True
            if c[u] > sf[u] * p["stop_band"]:
                why = "stop"
            elif be_on and c[u] >= entry:
                why = "breakeven stop"
            elif c[u] <= entry * (1 - p["target"]):
                why = "target"
            elif u - e + 1 >= p["days"]:
                why = "time"
            if why:
                if u + 1 < len(df):
                    x = u + 1
                break
        if x is None:
            x, why, at_open = len(df) - 1, (why or "open at end"), False
        else:
            at_open = True
        path = _position_path(df, e, x, -3.0, ld, at_open)
        bps = 2 * COST_BPS + (stop_bps if why in ("stop", "breakeven stop") else 0.0)
        fin = list(path.values())[-1] * (1 - bps / 1e4)
        path[df.index[x]] = fin
        out.append({"index": name, "signal": d, "entry_date": df.index[e], "exit_date": df.index[x], "why": why,
                    "size": p["size"], "ret": fin - 1.0, "path": path, "sessions": int(x - e),
                    "idx_move": float(c[x] / entry - 1)})
        busy = df.index[x]
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  Verdicts
# ═══════════════════════════════════════════════════════════════════════════

def _halves(trades):
    return {h: [t for t in trades if pd.Timestamp(a) <= t["entry_date"] <= pd.Timestamp(b)] for h, a, b in HALVES}


def _eq_ret(t):
    return t["ret"] * t["size"] * 100


def s3_verdict(trades, nav, spy_tr, stress_nav, nb_navs) -> dict:
    st = trade_stats([t["ret"] for t in trades])
    hs = {h: trade_stats([t["ret"] for t in v]) for h, v in _halves(trades).items()}
    bk = {h: nav_stats(nav, a, b) for h, a, b in [("full", START, None)] + list(HALVES)}
    sp = {h: nav_stats(spy_tr, a, b) for h, a, b in [("full", START, None)] + list(HALVES)}
    yr = year_returns(nav[nav.index >= START])
    w2 = worst_window(nav[nav.index >= START], 2)
    f = []
    if st["n"] < S3_BAR["min_trades"]:
        f.append(f"n {st['n']} < {S3_BAR['min_trades']}")
    for h, s in hs.items():
        if not s["exp"] > 0:
            f.append(f"{h} expectancy {s['exp'] * 100:+.2f}% <= 0")
    if not st["pf"] >= S3_BAR["min_pf"]:
        f.append(f"PF {st['pf']:.2f} < {S3_BAR['min_pf']}")
    if not st["payoff"] >= S3_BAR["min_payoff"]:
        f.append(f"payoff {st['payoff']:.2f} < {S3_BAR['min_payoff']}")
    for h in bk:
        if not bk[h]["cagr"] > sp[h]["cagr"]:
            f.append(f"book {h} CAGR {bk[h]['cagr']:.2f}% <= SPY {sp[h]['cagr']:.2f}%")
    if not bk["full"]["max_dd"] > S3_BAR["max_dd"]:
        f.append(f"book max DD {bk['full']['max_dd']:.1f}% deeper than {S3_BAR['max_dd']}%")
    if not w2 >= S3_BAR["worst_2d"]:
        f.append(f"worst 2-session book loss {w2:.1f}% < {S3_BAR['worst_2d']}%")
    if len(yr) and not yr.min() >= S3_BAR["worst_year"]:
        f.append(f"worst year {yr.min():.1f}% < {S3_BAR['worst_year']}%")
    robust = nav_stats(stress_nav, START)["cagr"] > sp["full"]["cagr"]
    stable = sum(1 for v in nb_navs.values() if nav_stats(v, START)["cagr"] > sp["full"]["cagr"])
    return {"verdict": "PASS" if not f else "FAIL", "fails": f, "all": st, "halves": hs, "book": bk, "spy": sp,
            "worst_2d": w2, "worst_1d": worst_window(nav[nav.index >= START], 1),
            "worst_year": float(yr.min()) if len(yr) else float("nan"), "years": yr.round(1).to_dict(),
            "robust": bool(robust), "stress_cagr": nav_stats(stress_nav, START)["cagr"],
            "stable": f"{stable} of {len(nb_navs)}",
            "neighbours": {k: nav_stats(v, START) for k, v in nb_navs.items()},
            "hwm_stops": hwm_stops(nav[nav.index >= START]),
            "by_index": {k: trade_stats([t["ret"] for t in trades if t["index"] == k]) for k in ("SPY", "QQQ")},
            "exposure_mean": float(np.mean([t["size"] for t in trades])) if trades else float("nan")}


def s4_verdict(trades, nav, tb_nav, stress, nb) -> dict:
    st = trade_stats([t["ret"] for t in trades])
    hs = {h: trade_stats([t["ret"] for t in v]) for h, v in _halves(trades).items()}
    bk = {h: nav_stats(nav, a, b) for h, a, b in [("full", START, None)] + list(HALVES)}
    tb = {h: nav_stats(tb_nav, a, b) for h, a, b in [("full", START, None)] + list(HALVES)}
    worst = min([_eq_ret(t) for t in trades], default=0.0)
    f = []
    if st["n"] < S4_BAR["min_trades"]:
        f.append(f"n {st['n']} < {S4_BAR['min_trades']}")
    for h, s in hs.items():
        if s["n"] < S4_BAR["min_half"]:
            f.append(f"{h} n {s['n']} < {S4_BAR['min_half']}")
        if not s["exp"] > 0:
            f.append(f"{h} expectancy {s['exp'] * 100:+.2f}% <= 0")
    if not st["pf"] >= S4_BAR["min_pf"]:
        f.append(f"PF {st['pf']:.2f} < {S4_BAR['min_pf']}")
    if not st["payoff"] >= S4_BAR["min_payoff"]:
        f.append(f"payoff {st['payoff']:.2f} < {S4_BAR['min_payoff']}")
    if not worst >= S4_BAR["worst_trade_eq"]:
        f.append(f"worst trade {worst:.1f}% of equity < {S4_BAR['worst_trade_eq']}%")
    if not bk["full"]["max_dd"] > S4_BAR["max_dd"]:
        f.append(f"book max DD {bk['full']['max_dd']:.1f}% deeper than {S4_BAR['max_dd']}%")
    for h, a, b in HALVES:
        ex = bk[h]["cagr"] - tb[h]["cagr"]
        if not ex >= S4_BAR["excess_pts"]:
            f.append(f"{h} book only {ex:+.2f} pts over T-bills (< {S4_BAR['excess_pts']})")
    robust = trade_stats([t["ret"] for t in stress])["exp"] > 0 if stress else False
    stable = sum(1 for v in nb.values() if trade_stats([t["ret"] for t in v])["exp"] > 0)
    return {"verdict": "PASS" if not f else "FAIL", "fails": f, "all": st, "halves": hs, "book": bk, "tbill": tb,
            "worst_trade_eq": worst, "robust": bool(robust), "stress": trade_stats([t["ret"] for t in stress]),
            "stable": f"{stable} of {len(nb)}", "neighbours": {k: trade_stats([t["ret"] for t in v]) for k, v in nb.items()},
            "hwm_stops": hwm_stops(nav[nav.index >= START]), "years": year_returns(nav[nav.index >= START]).round(1).to_dict()}


# ═══════════════════════════════════════════════════════════════════════════
#  Run
# ═══════════════════════════════════════════════════════════════════════════

def _fetch(tickers, start):
    import yfinance as yf
    out = {}
    for attempt in range(4):
        need = [t for t in tickers if t not in out]
        if not need:
            break
        if attempt:
            _log(f"retry {attempt}: {', '.join(need)}")
            time.sleep(3)
        for t in need:                                # one at a time: avoids the cache lock seen 11-21
            try:
                df = yf.download(t, start=start, auto_adjust=True, progress=False, threads=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.dropna(subset=["Close"])
                idx = pd.to_datetime(df.index)
                df.index = (idx.tz_localize(None) if getattr(idx, "tz", None) else idx).normalize()
                if len(df) > 300:
                    out[t] = df[["Open", "High", "Low", "Close"]].astype(float)
            except Exception as e:
                _log(f"{t}: {type(e).__name__}")
    return out


REQUIRED = ["SPY", "QQQ", "^IRX"]
CHECK = ["UPRO", "TQQQ", "SPXU", "SQQQ"]


def run(data: dict) -> dict:
    spy, qqq = data["SPY"], data["QQQ"]
    cal_all = spy.index
    rf_d = (data["^IRX"]["Close"].reindex(cal_all).ffill() / 100 / 252).fillna(0.0)
    idx = {"SPY": spy, "QQQ": qqq}
    cal = cal_all[cal_all >= pd.Timestamp(START)]
    spy_tr = spy["Close"].reindex(cal)
    tb = (1 + rf_d.reindex(cal).fillna(0.0)).cumprod() * 10_000

    _log("S3: leveraged trend ...")
    def s3_all(p=S3, **kw):
        return [t for k, df in idx.items() for t in s3_trades(k, df, rf_d, p, **kw)
                if t["entry_date"] >= pd.Timestamp(START)]
    t3 = s3_all()
    nav3 = book(t3, cal, rf_d)
    stress3 = book(s3_all(spread_mult=STRESS["spread_mult"], extra_bps=STRESS["extra_bps"]), cal, rf_d)
    nb3 = {f"{k} {v}": book(s3_all({**S3, k: v}), cal, rf_d) for k, v in S3_NEIGHBOURS}
    v3 = s3_verdict(t3, nav3, spy_tr, stress3, nb3)

    _log("S4: bear failed rally ...")
    def s4_all(p=S4, **kw):
        return [t for t in s4_trades(idx, rf_d, p, **kw) if t["entry_date"] >= pd.Timestamp(START)]
    t4 = s4_all()
    nav4 = book(t4, cal, rf_d)
    stress4 = s4_all(spread_mult=STRESS["spread_mult"], stop_bps=STRESS["stop_bps"])
    nb4 = {f"{k} {v}": s4_all({**S4, k: v}) for k, v in S4_NEIGHBOURS}
    v4 = s4_verdict(t4, nav4, tb, stress4, nb4)

    navc = book(t3 + t4, cal, rf_d)                     # combined, report only
    comb = {"book": nav_stats(navc, START), "halves": {h: nav_stats(navc, a, b) for h, a, b in HALVES},
            "worst_2d": worst_window(navc, 2), "years": year_returns(navc).round(1).to_dict()}
    checks = {"UPRO": lev_check(spy["Close"], data["UPRO"]["Close"] if "UPRO" in data else None, rf_d, 3),
              "TQQQ": lev_check(qqq["Close"], data["TQQQ"]["Close"] if "TQQQ" in data else None, rf_d, 3),
              "SPXU": lev_check(spy["Close"], data["SPXU"]["Close"] if "SPXU" in data else None, rf_d, -3),
              "SQQQ": lev_check(qqq["Close"], data["SQQQ"]["Close"] if "SQQQ" in data else None, rf_d, -3)}
    live = {}
    for k, df in idx.items():
        c, h = df["Close"], df["High"]
        sl, sf = c.rolling(200).mean(), c.rolling(50).mean()
        live[k] = {"date": str(df.index[-1].date()), "close": round(float(c.iloc[-1]), 2),
                   "vs_200d_pct": round(float((c.iloc[-1] / sl.iloc[-1] - 1) * 100), 2),
                   "vs_50d_pct": round(float((c.iloc[-1] / sf.iloc[-1] - 1) * 100), 2),
                   "200d_rising": bool(sl.iloc[-1] > sl.iloc[-21]),
                   "s3_on": bool((c.iloc[-1] > sl.iloc[-1]) and (sl.iloc[-1] > sl.iloc[-21]) and (c.iloc[-1] > sf.iloc[-1])),
                   "s4_bear": bool((c.iloc[-1] < sl.iloc[-1]) and (sl.iloc[-1] < sl.iloc[-21]) and (c.iloc[-1] < sf.iloc[-1]))}
    return {"S3": {"verdict": v3, "nav": nav3, "trades": t3}, "S4": {"verdict": v4, "nav": nav4, "trades": t4},
            "combined": comb, "checks": checks, "live": live, "spy_full": nav_stats(spy_tr, START)}


def _pp(x, nd=1):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x * 100:+.{nd}f}%"


def render(r: dict, stamp: str) -> str:
    v3, v4 = r["S3"]["verdict"], r["S4"]["verdict"]
    L = [f"# Trend lab {VERSION} — {stamp}", "",
         f"Pre-registered in `claude/trend_lab_2026-11-21.md`. Trials {TRIALS_BEFORE} → {TRIALS_BEFORE + TRIALS_HERE}. "
         "Synthetic 3× and inverse 3× funds (checked against real ones below). Research, not personalized advice.", "",
         f"## S3 — leveraged trend (3× SPY / QQQ sleeves): **{v3['verdict']}**", "",
         f"- Fails: {'; '.join(v3['fails']) or 'none'}"]
    a = v3["all"]
    L += [f"- Trades {a['n']} · expectancy {_pp(a['exp'])} per trade (3× position) · PF {a['pf']:.2f} · win {_pp(a['win'], 0)} · "
          f"avg win {_pp(a['avg_win'], 0)} / avg loss {_pp(a['avg_loss'], 0)} (payoff {a['payoff']:.2f}) · wins ≥ +25%: "
          f"{_pp(a['big_win_share'], 0)} of wins · mean sleeve size {v3['exposure_mean'] * 100:.0f}% of equity",
          f"- By index: " + "; ".join(f"{k} n {s['n']}, exp {_pp(s['exp'])}, payoff {s['payoff']:.2f}" for k, s in v3["by_index"].items()),
          f"- Worst 1-session / 2-session book loss {v3['worst_1d']:.1f}% / {v3['worst_2d']:.1f}% · worst year "
          f"{v3['worst_year']:.1f}% · −20% high-water stops {v3['hwm_stops']}",
          f"- ROBUST (financing ×2, +10bp a side): CAGR {v3['stress_cagr']:.2f}% → {'yes' if v3['robust'] else 'no'} · "
          f"STABLE (neighbours beating SPY): {v3['stable']}"]
    for h, s in v3["halves"].items():
        L.append(f"- {h}: n {s['n']}, expectancy {_pp(s['exp'])}, PF {s['pf']:.2f}")
    L += ["", "| Book | CAGR | Max DD | SPY CAGR | SPY max DD |", "|---|---|---|---|---|"]
    for h in v3["book"]:
        L.append(f"| {h} | {v3['book'][h]['cagr']:.2f}% | {v3['book'][h]['max_dd']:.1f}% | {v3['spy'][h]['cagr']:.2f}% | "
                 f"{v3['spy'][h]['max_dd']:.1f}% |")
    L += ["", "| Neighbour | CAGR | Max DD |", "|---|---|---|"]
    L += [f"| {k} | {s['cagr']:.2f}% | {s['max_dd']:.1f}% |" for k, s in v3["neighbours"].items()]
    a = v4["all"]
    L += ["", f"## S4 — bear failed rally, inverse 3×: **{v4['verdict']}**", "",
          f"- Fails: {'; '.join(v4['fails']) or 'none'}",
          f"- Trades {a['n']} · expectancy {_pp(a['exp'])} per trade · PF {a['pf']:.2f} · win {_pp(a['win'], 0)} · avg win "
          f"{_pp(a['avg_win'], 0)} / avg loss {_pp(a['avg_loss'], 0)} (payoff {a['payoff']:.2f}) · wins ≥ +25%: "
          f"{_pp(a['big_win_share'], 0)} of wins",
          f"- Worst trade {v4['worst_trade_eq']:.1f}% of equity · −20% high-water stops {v4['hwm_stops']}",
          f"- ROBUST (spreads ×2, 60bp stop slippage): expectancy {_pp(v4['stress']['exp'])} → {'yes' if v4['robust'] else 'no'} · "
          f"STABLE (neighbours with positive expectancy): {v4['stable']}"]
    for h, s in v4["halves"].items():
        L.append(f"- {h}: n {s['n']}, expectancy {_pp(s['exp'])}, PF {s['pf']:.2f}")
    L += ["", "| Book (25% per trade) | CAGR | Max DD | T-bill CAGR |", "|---|---|---|---|"]
    for h in v4["book"]:
        L.append(f"| {h} | {v4['book'][h]['cagr']:.2f}% | {v4['book'][h]['max_dd']:.1f}% | {v4['tbill'][h]['cagr']:.2f}% |")
    L += ["", "| Neighbour | Trades | Expectancy | PF |", "|---|---|---|---|"]
    L += [f"| {k} | {s['n']} | {_pp(s['exp'])} | {s['pf']:.2f} |" for k, s in v4["neighbours"].items()]
    cb = r["combined"]
    L += ["", "## S3 + S4 together (report only)", "",
          f"- CAGR {cb['book']['cagr']:.2f}%, max DD {cb['book']['max_dd']:.1f}%, worst 2 sessions {cb['worst_2d']:.1f}% · "
          + "; ".join(f"{h} {s['cagr']:.2f}%" for h, s in cb["halves"].items())
          + f" · SPY {r['spy_full']['cagr']:.2f}% / {r['spy_full']['max_dd']:.1f}%",
          "", "## Synthetic vs real funds (calendar years, synthetic − real)", ""]
    L += [f"- {k}: {v}" for k, v in r["checks"].items()]
    L += ["", "## Today (paper only, not a trade)", ""]
    L += [f"- {k} {x['date']}: {x['vs_200d_pct']:+.2f}% vs 200-day ({'rising' if x['200d_rising'] else 'falling'}), "
          f"{x['vs_50d_pct']:+.2f}% vs 50-day · S3 ON: {'yes' if x['s3_on'] else 'no'} · S4 bear state: {'yes' if x['s4_bear'] else 'no'}"
          for k, x in r["live"].items()]
    L += ["", f"*trend_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def write_outputs(r: dict, stamp: str, out_data: Path, out_logs: Path) -> str:
    md = render(r, stamp)
    summ = {"version": VERSION, "asof": stamp, "trials": TRIALS_BEFORE + TRIALS_HERE, "S3": r["S3"]["verdict"],
            "S4": r["S4"]["verdict"], "combined": r["combined"], "checks": r["checks"], "live": r["live"],
            "spy_full": r["spy_full"]}
    js = json.dumps(_jsonable(summ), indent=1, default=str)            # serialize before writing anything
    out_data.mkdir(parents=True, exist_ok=True)
    out_logs.mkdir(parents=True, exist_ok=True)
    (out_logs / "latest.md").write_text(md)
    (out_logs / f"{stamp}.md").write_text(md)
    for k in ("S3", "S4"):
        pd.DataFrame([{a: b for a, b in t.items() if a != "path"} for t in r[k]["trades"]]).to_csv(
            out_data / f"{k}_trades.csv", index=False)
        r[k]["nav"].round(2).to_csv(out_data / f"{k}_nav.csv")
    (out_data / "summary.json").write_text(js)
    return md


def main(fetch=None) -> int:
    stamp = datetime.now(timezone.utc).date().isoformat()
    _log("fetching prices ...")
    data = (fetch or _fetch)(REQUIRED + CHECK, "1998-01-01")
    miss = [t for t in REQUIRED if t not in data]
    if miss:
        print(f"[trend_lab] DATA FAILURE: no prices for {', '.join(miss)}; nothing written. Rerun later.")
        return 1
    r = run(data)
    md = write_outputs(r, stamp, OUT_DATA, OUT_LOGS)
    print(md)
    return 0


# ═══════════════════════════════════════════════════════════════════════════
#  Selftest
# ═══════════════════════════════════════════════════════════════════════════

def _frame(close: np.ndarray, cal) -> pd.DataFrame:
    o = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, close) * 1.002, "Low": np.minimum(o, close) * 0.998,
                         "Close": close}, index=cal)


def selftest() -> dict:
    f = []
    cal = pd.bdate_range("2001-01-02", periods=900)
    rf0 = pd.Series(0.0, index=cal)
    # synthetic fund formulas
    r = pd.Series([0.01, -0.02], index=cal[:2])
    rf = pd.Series(0.04 / 252, index=cal[:2])
    L = lev_daily(r, rf, 3.0)
    if abs(L.iloc[0] - (0.03 - 2 * (0.04 / 252 + FIN_SPREAD / 252) - FEE / 252)) > 1e-12:
        f.append("3x long formula")
    I = lev_daily(r, rf, -3.0)
    if abs(I.iloc[0] - (-0.03 + 4 * 0.04 / 252 - 3 * FIN_SPREAD / 252 - FEE / 252)) > 1e-12:
        f.append("inverse 3x formula")
    # S3: a long steady uptrend enters once, rides, exits on the 50-day break
    up = np.r_[100 * np.exp(np.cumsum(np.full(500, 0.0008) + 0.004 * np.sin(np.arange(500) / 3))),
               np.zeros(400)]
    up[500:] = up[499] * np.exp(np.cumsum(np.full(400, -0.004)))
    df = _frame(up, cal)
    tr = s3_trades("SPY", df, rf0)
    if not tr or tr[0]["entry_date"] <= cal[200] or tr[0]["why"] not in ("trend off", "trail") or not tr[0]["ret"] > 0.25:
        f.append(f"S3: uptrend must enter after 200 sessions and exit with a big gain: "
                 f"{[(str(t['entry_date'].date()), t['why'], round(t['ret'], 2)) for t in tr]}")
    if tr and tr[0]["exit_date"] > cal[560]:
        f.append("S3: the 50-day break must exit within ~2 months of the top")
    if tr and not abs(tr[0]["size"] - min(S3["cap"], S3["vol_target"] / (3 * df["Close"].pct_change().rolling(20).std().iloc[
            cal.get_loc(tr[0]["signal"])] * math.sqrt(252)))) < 1e-12:
        f.append("S3: size = min(cap, vol target / (3 x 20-day vol)) at the signal")
    # confirmation: the signal is the 2nd ON close in a row; the exit is the open AFTER the 2nd OFF close
    cc = df["Close"]
    sl_, sf_ = cc.rolling(200).mean(), cc.rolling(50).mean()
    on_ = ((cc > sl_) & (sl_ > sl_.shift(20)) & (cc > sf_)).to_numpy()
    if tr:
        i0 = cal.get_loc(tr[0]["signal"])
        first_on = int(np.argmax(on_))
        if i0 != first_on + 1:
            f.append(f"S3: signal must be the 2nd ON close (first ON {first_on}, signal {i0})")
        x0 = cal.get_loc(tr[0]["exit_date"])
        if tr[0]["why"] == "trend off" and not (cc.iat[x0 - 1] < sf_.iat[x0 - 1] and cc.iat[x0 - 2] < sf_.iat[x0 - 2]
                                                  and not cc.iat[x0 - 3] < sf_.iat[x0 - 3]):
            f.append("S3: exit at the open after the 2nd close below the 50-day")
    # hard trail: a sudden -10% index day after entry -> 3x ~-30% -> trail exit, no immediate re-entry
    crash = up.copy()
    crash[350] = crash[349] * 0.90
    crash[351:] = crash[350] * up[351:] / up[350]
    trc = s3_trades("SPY", _frame(crash, cal), rf0)
    whys = [t["why"] for t in trc]
    if "trail" not in whys:
        f.append(f"S3: a -10% day must hit the -20% trail: {whys}")
    else:
        k = whys.index("trail")
        if k + 1 < len(trc):
            seg = _frame(crash, cal)["Close"]
            on = (seg > seg.rolling(200).mean()) & (seg.rolling(200).mean() > seg.rolling(200).mean().shift(20)) & (seg > seg.rolling(50).mean())
            between = on[(on.index > trc[k]["exit_date"]) & (on.index <= trc[k + 1]["signal"])]
            if between.all():
                f.append("S3: after the trail, re-entry needs the ON condition to fail first")
    # gap into exit: the exit bar contributes only the overnight move to its open
    fg = _frame(np.array([100, 100, 110, 99.0]), cal[:4])
    fg.loc[cal[3], "Open"] = 104.5
    p = _position_path(fg, 1, 3, 3.0, np.array([0, 0, 0.3, -0.3]), True)
    if abs(p[cal[3]] - (1 + 0.3) * (1 + 3 * (104.5 / 110 - 1))) > 1e-9:
        f.append(f"path: exit at the open of the exit bar, gap included: {p}")
    # re-arm: a trail exit while the trend stays ON must NOT re-enter until ON fails
    # (index -7% in 3 sessions -> 3x about -21% -> trail; the index stays above its 50-day throughout)
    ra = 100 * np.exp(np.cumsum(np.r_[np.full(400, 0.004), np.full(3, -0.025), np.full(497, 0.004)]))
    tra = s3_trades("SPY", _frame(ra, cal), rf0)
    ka = [t["why"] for t in tra]
    if "trail" not in ka:
        f.append(f"S3 re-arm fixture must hit the trail: {ka}")
    else:
        k = ka.index("trail")
        rc_ = pd.Series(ra, index=cal)
        on_ra = ((rc_ > rc_.rolling(200).mean()) & (rc_.rolling(200).mean() > rc_.rolling(200).mean().shift(20))
                 & (rc_ > rc_.rolling(50).mean()))
        if not on_ra[on_ra.index >= tra[k]["exit_date"]].all():
            f.append("S3 re-arm fixture: the trend must stay ON after the trail")
        if k + 1 < len(tra):
            f.append("S3: re-entry after the trail requires the ON condition to fail first")
    # S4: bear market with a failed rally to the 50-day -> inverse profit at the target
    dn = 100 * np.exp(np.cumsum(np.r_[np.full(300, 0.0005), np.full(150, -0.004), np.full(15, 0.006),
                                       np.full(435, -0.006)]))
    dfd = _frame(dn, cal)
    dfd["High"] = dfd[["Open", "Close"]].max(axis=1) * 1.015
    t4 = s4_trades({"SPY": dfd}, rf0)
    if not t4 or t4[0]["why"] != "target" or not t4[0]["ret"] > 0.25:
        f.append(f"S4: a failed rally then -10% must hit the target with > +25%: {[(t['why'], round(t['ret'], 2)) for t in t4]}")
    if t4 and t4[0]["entry_date"] != cal[cal.get_loc(t4[0]["signal"]) + 1]:
        f.append("S4: entry at the next open")
    # S4 stop: rally through the 50-day + 2%
    sq = 100 * np.exp(np.cumsum(np.r_[np.full(300, 0.0005), np.full(150, -0.004), np.full(8, 0.006), [-0.003],
                                       np.full(441, 0.006)]))
    dfs = _frame(sq, cal)
    dfs["High"] = dfs[["Open", "Close"]].max(axis=1) * 1.015
    t4s = s4_trades({"SPY": dfs}, rf0)
    if not t4s or t4s[0]["why"] != "stop" or not t4s[0]["ret"] < 0:
        f.append(f"S4: a squeeze through the 50-day must stop out at a loss: {[(t['why'], round(t['ret'], 2)) for t in t4s]}")
    # one at a time; QQQ first on ties
    two = s4_trades({"SPY": dfd, "QQQ": dfd.copy()}, rf0)
    if any(b["entry_date"] <= a["exit_date"] for a, b in zip(two, two[1:])) or (two and two[0]["index"] != "QQQ"):
        f.append("S4: one position at a time, QQQ first")
    # book: two overlapping trades sized off prior equity
    trs = [{"entry_date": cal[1], "exit_date": cal[3], "size": 0.4, "path": {cal[1]: 1.0, cal[2]: 1.1, cal[3]: 1.2}},
           {"entry_date": cal[2], "exit_date": cal[4], "size": 0.3, "path": {cal[2]: 1.0, cal[3]: 0.9, cal[4]: 0.8}}]
    nv = book(trs, cal[:6], rf0)
    # trade 1: 40% of 10,000 at cal[1]; trade 2: 30% of the cal[1] close equity (10,000) at cal[2]
    exp_final = 10_000 + 4_000 * 0.2 + 3_000 * (0.8 - 1)
    if abs(nv.iloc[-1] - exp_final) > 1e-6:
        f.append(f"book: {nv.iloc[-1]:.2f} vs {exp_final:.2f}")
    if abs(worst_window(pd.Series([100, 90, 81, 100.0]), 2) + 19.0) > 1e-9:
        f.append("worst 2-session window")
    # writer + main end to end on synthetic data (fake fetch), including a missing required ticker
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    big = pd.bdate_range("1998-01-02", periods=2600)
    g = np.random.default_rng(5)
    def walk(drift, vol):
        return _frame(100 * np.exp(np.cumsum(g.normal(drift, vol, len(big)))), big)
    fake = {"SPY": walk(0.0004, 0.011), "QQQ": walk(0.0005, 0.016), "^IRX": _frame(np.full(len(big), 2.0), big),
            "UPRO": walk(0.001, 0.03), "TQQQ": walk(0.001, 0.045)}
    try:
        rr = run(fake)
        md = write_outputs(rr, "2026-11-21", tmp / "d", tmp / "l")
        js = json.loads((tmp / "d" / "summary.json").read_text())
        if js["S3"]["verdict"] not in ("PASS", "FAIL") or "S3 —" not in md or not (tmp / "d" / "S4_trades.csv").exists():
            f.append("writer/main: outputs incomplete")
        if js["checks"]["SPXU"].get("note") != "no data":
            f.append("missing check funds must say 'no data', not fail")
    except Exception as e:
        f.append(f"run/writer crashed: {type(e).__name__}: {e}")
    import os
    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        rc = main(fetch=lambda t, s: {k: v for k, v in fake.items() if k != "^IRX"})
        if rc != 1 or (tmp / "data" / "trend_lab").exists():
            f.append("main: a missing required input must stop with nothing written")
    finally:
        os.chdir(cwd)
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        res = selftest()
        print(json.dumps(res, indent=2))
        sys.exit(0 if res["ok"] else 1)
    sys.exit(main())
