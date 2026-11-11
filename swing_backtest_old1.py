"""
swing_backtest.py  (v1.0 — 2026-11-11)
──────────────────────────────────────
Historical test bench for the swing desk. Answers one question before real
money goes in on 2027-01-04: which end-of-day, long-only setups made money
after costs, in both halves of history, and which stop method executes them
better?

WHAT IT TESTS (frozen before the first run; see FROZEN below)
  Setups   M1 VCP, M2 Breakout, M2c Momentum Burst, M0 Rotation Reclaim
           -- detected by the PRODUCTION functions in swing_desk.py, so the
           test covers exactly what the desk would have emitted --
           plus PB Pullback-in-uptrend (new, defined here, not yet live).
           Dropped: shorts (Matt: long only) and the Episodic Pivot's
           opening-range entry (needs intraday).
  Stops    A  resting GTC stop-market at the structure/ATR stop.
           B  closing-basis stop (exit next open when a CLOSE breaks the
              stop) + a resting disaster stop-market 1 x ATR(14) below it.
  Exits    production swing_exits order: structural -> thesis (sector
           rotation turns Weakening/Lagging) -> trend (close below a FALLING
           trail MA exits, below a RISING one tightens) -> 2R/4R/8R ladder.
           Bursts: day 5 or first close < 5 EMA. Leveraged ETFs: 90-day cap.
  Fills    signals on day t's close; orders work on day t+1 only.
           Buy-stops fill at the level, or at the open on a gap through it.
           Market entries fill at the next open. Stops gap-fill at the open.
           When a daily bar cannot show whether entry or stop came first,
           the WORSE outcome is assumed. Costs: 3bp/side ETFs, 5bp stocks
           and leveraged ETFs, +10bp slippage on every stop fill.
  Sizing   portfolio pass: $10,000, 2% base risk x confluence multiple
           (3-of-3 = 1.0, 2-of-3 = 0.5, production), 1% after 3 straight
           losses until 2 straight wins, max 4 positions, max 2 per sector,
           8% heat, 30% position cap, no margin (cash only).

HONEST LIMITS (printed in every report)
  * Regime gating is NOT tested: no point-in-time regime history exists yet
    (fix_status N11). Signals are taken in every regime.
  * Sector rotation replicates Money Flow's default RRG (rotation_math v3,
    1-year ratio, 6-month/1-year momentum vs the equal-weight sector mean),
    recomputed daily from trailing returns. Flow (Tier A) is NOT in the
    rotation leg here: no point-in-time flow history before Aug 2026.
  * The stock universe is TODAY's top-10 holdings of each sector ETF:
    survivorship bias. Stock results are an upper bound, labelled
    INDICATIVE, and cannot pass the go-live bar on their own.
  * No earnings or FOMC/CPI blackout history: stock trades include earnings
    gaps the live rules would avoid.
  * Loss limits (-10% month, -20% from high-water) are measured, not
    enforced, so every trade stays countable.

Run:  python swing_backtest.py           (needs yfinance + network: Actions)
      python -c "import swing_backtest as b; print(b.selftest())"  (offline)
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import NormalDist
from typing import Optional

import numpy as np
import pandas as pd

import swing_desk as sd

VERSION = "1.0"

# ── FROZEN parameters (changing any of these is a new trial; log it) ────────
START = "2004-01-01"            # data start; first signals need ~320 bars
HALF_SPLIT = pd.Timestamp("2016-01-01")
WINDOW = 320                    # bars handed to the production detectors
START_EQUITY = 10_000.0
BASE_RISK_PCT = 2.0
REDUCED_RISK_PCT = 1.0
STREAK_LOSSES, STREAK_RESET_WINS = 3, 2
SCRATCH_R = 0.15
MAX_POSITIONS, MAX_PER_SECTOR = 4, 2
HEAT_CAP_PCT, MAX_POSITION_PCT = 8.0, 30.0
COST_BPS = {"etf": 3.0, "stock": 5.0, "lev": 5.0}
STOP_SLIP_BPS = 10.0
DISASTER_ATR = 1.0
LADDER = (2.0, 4.0, 8.0)
BURST_MAX_DAYS = 5
LEV_MAX_DAYS = 90
PB_RSI_MAX, PB_ATR_STOP, PB_MAX_DAYS = 10.0, 2.0, 10
DOLLAR_VOL_MIN = 3_000_000
EPS = 1e-9

# Pass bar, fixed before the first run (risk_policy.md §5)
BAR = {"min_trades": 100, "min_per_half": 30, "min_pf": 1.3}

SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLU", "XLRE", "XLB", "XLC", "XLP"]
OTHER_ETFS = {   # ticker -> sector ETF whose rotation it follows (None = no sector)
    "SPY": None, "QQQ": "XLK", "IWM": None, "DIA": None, "MDY": None,
    "SMH": "XLK", "IGV": "XLK", "XBI": "XLV", "IBB": "XLV", "KRE": "XLF",
    "XHB": "XLY", "ITB": "XLY", "XRT": "XLY", "XOP": "XLE", "OIH": "XLE",
    "GDX": "XLB", "XME": "XLB", "IYT": "XLI", "ITA": "XLI",
    "GLD": None, "SLV": None, "TLT": None, "EEM": None, "EFA": None,
    "TQQQ": "XLK", "SOXL": "XLK", "TECL": "XLK", "UPRO": None, "TNA": None, "FAS": "XLF",
}
LEVERAGED = {"TQQQ", "SOXL", "TECL", "UPRO", "TNA", "FAS"}
FALLBACK_CONSTITUENTS = {
    "XLK": ["NVDA", "AAPL", "MSFT", "AVGO", "AMD"], "XLF": ["JPM", "BAC", "GS"],
    "XLE": ["XOM", "CVX", "COP"], "XLV": ["LLY", "UNH", "JNJ"], "XLI": ["GE", "CAT", "HON"],
    "XLY": ["AMZN", "HD", "MCD"], "XLB": ["LIN", "FCX", "NUE"], "XLP": ["PG", "KO", "WMT"],
}

SETUPS = ("M1", "M2", "M2c", "M0", "PB")
SETUP_NAMES = {"M1": "M1 VCP", "M2": "M2 Breakout", "M2c": "M2c Burst",
               "M0": "M0 Rotation", "PB": "PB Pullback"}
TRAIL = {"M1": ("SMA", 50), "M2": ("EMA", 10), "M0": ("SMA", 100), "M2c": None, "PB": None}
VARIANTS = ("A", "B")

OUT_DATA = os.path.join("data", "swing_backtest")
OUT_LOGS = os.path.join("logs", "swing_backtest")


# ═══════════════════════════════════════════════════════════════════════════
# Indicators (vectorised; definitions match swing_desk exactly)
# ═══════════════════════════════════════════════════════════════════════════

def rsi(close: pd.Series, n: int = 2) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn > 0, 100.0)


def indicators(df: pd.DataFrame, bench: Optional[pd.Series]) -> pd.DataFrame:
    c, h, l, v, o = df["Close"], df["High"], df["Low"], df["Volume"], df["Open"]
    x = pd.DataFrame(index=df.index)
    for n in (5, 20, 50, 100, 150, 200):
        x[f"sma{n}"] = c.rolling(n).mean()
    for n in (5, 10, 20):
        x[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    x["atr14"] = tr.rolling(14).mean()
    x["adr20"] = ((h / l - 1) * 100).rolling(20).mean()
    x["dvol20"] = (c * v).rolling(20).mean()
    x["vol50"] = v.rolling(50).mean()
    x["vol20"] = v.rolling(20).mean()
    x["vol10"] = v.rolling(10).mean()
    rng = (h - l).replace(0, np.nan)
    mfv = ((c - l) - (h - c)) / rng * v
    x["cmf20"] = mfv.fillna(0).rolling(20).sum() / v.rolling(20).sum().clip(lower=1)
    x["rsi2"] = rsi(c, 2)
    x["hi252"] = c.rolling(252).max()
    x["lo252"] = c.rolling(252).min()
    if bench is not None:
        b = bench.reindex(df.index).ffill()
        r3, r6 = c / c.shift(63) - 1, c / c.shift(126) - 1
        b3, b6 = b / b.shift(63) - 1, b / b.shift(126) - 1
        x["rs_rank"] = np.clip(50 + (0.6 * (r3 - b3) + 0.4 * (r6 - b6)) * 133, 0, 100)
    else:
        x["rs_rank"] = np.nan
    return x


def rotation_proxy(closes: dict) -> dict:
    """Point-in-time replica of Money Flow's DEFAULT RRG (rotation_math v3,
    "3M toggle"): RS_tf = (1 + sector return) / (1 + equal-weight mean of all
    sector returns) x 100 over tf trading days; RS-Ratio = RS_1y (252d);
    RS-Momentum = RS_6m (126d) / RS_1y x 100. Quadrants as classify_quadrant.
    The rotation leg (long) passes in Improving or Leading <=> momentum >= 100.
    Computed from trailing returns only, so it is available on any past day."""
    secs = {s: closes[s] for s in SECTOR_ETFS if s in closes}
    if not secs:
        return {}
    px = pd.DataFrame(secs).sort_index()

    def rs(n):
        perf = px / px.shift(n) - 1
        bm = perf.mean(axis=1, skipna=True)
        return (1 + perf).div(1 + bm, axis=0) * 100

    ratio = rs(252)
    mom = rs(126) / ratio * 100
    out = {}
    for s in px.columns:
        r_, m_ = ratio[s], mom[s]
        quad = pd.Series(np.where(r_ >= 100, np.where(m_ >= 100, "Leading", "Weakening"),
                                  np.where(m_ >= 100, "Improving", "Lagging")), index=px.index, dtype=object)
        quad[r_.isna() | m_.isna()] = None
        out[s] = quad
    return out


# ═══════════════════════════════════════════════════════════════════════════
# New setup: PB Pullback-in-uptrend (frozen spec; production gets it in build #2)
# ═══════════════════════════════════════════════════════════════════════════

def detect_pullback(df: pd.DataFrame) -> dict:
    """Long-only mean reversion inside an uptrend.
    Uptrend: close > SMA200, SMA50 > SMA200, SMA200 higher than 20 bars ago.
    Pullback: RSI(2) < 10.  Liquidity: 20-day $ volume >= $3M.
    Entry: next open (market). Stop: fill - 2 x ATR(14).
    Exit: first close above SMA5, or 10 bars. Volume leg: CMF(20) > 0."""
    c = df["Close"]
    if len(c) < 221:
        return {"is_setup": False, "reason": "need ~220 bars"}
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    r2 = float(rsi(c, 2).iloc[-1])
    dvol = float((c * df["Volume"]).tail(20).mean())
    up = bool(c.iloc[-1] > s200.iloc[-1] and s50.iloc[-1] > s200.iloc[-1] and s200.iloc[-1] > s200.iloc[-21])
    ok = up and r2 < PB_RSI_MAX and dvol >= DOLLAR_VOL_MIN
    return {"is_setup": ok, "rsi2": round(r2, 1), "uptrend": up, "dollar_vol": round(dvol),
            "volume_ok": sd._cmf(df) > 0,
            "reason": ("Pullback in uptrend" if ok else "not in an uptrend" if not up else
                       f"RSI(2) {r2:.0f} >= {PB_RSI_MAX:.0f}" if r2 >= PB_RSI_MAX else "illiquid")}


# ═══════════════════════════════════════════════════════════════════════════
# Prefilters: NECESSARY conditions only (selftest proves they never drop a
# day the production detector fires). They exist purely for speed.
# ═══════════════════════════════════════════════════════════════════════════

def prefilters(df: pd.DataFrame, x: pd.DataFrame) -> dict:
    c, v = df["Close"], df["Volume"]
    uf = ((x["adr20"] >= sd.ADR_MIN_PCT - 1e-6) & (x["dvol20"] >= sd.DOLLAR_VOL_MIN - 1)
          & (c > x["sma20"] - EPS) & (c > x["sma50"] - EPS))
    volr = v / x["vol50"]
    vol_ok = volr >= sd.BREAKOUT_VOL_MULT - 1e-6
    prior19 = c.shift(1).rolling(19).max()
    prior3 = c.shift(1).rolling(3).max()
    prior_move = (c.shift(19) / c.shift(59) - 1) * 100
    m2 = uf & vol_ok & (c > prior19 - EPS) & (prior_move >= 30 - 1e-6)
    m2c = uf & vol_ok & (c > prior3 - EPS)
    tt = ((c > x["sma50"] - EPS) & (c > x["sma150"] - EPS) & (c > x["sma200"] - EPS)
          & (x["sma150"] > x["sma200"] - EPS) & (x["sma200"] > x["sma200"].shift(21) - EPS)
          & (x["sma50"] > x["sma150"] - EPS) & (c >= x["lo252"] * 1.25 - 1e-6)
          & (c >= x["hi252"] * 0.75 - 1e-6) & (x["rs_rank"] >= 70 - 0.01))
    m1 = tt & (x["vol10"] < x["vol50"] * 0.8 + 1)
    m0 = ((c > x["sma100"] - EPS) & (x["sma100"] >= x["sma100"].shift(10) * 0.995 - 1e-6)
          & (c <= x["sma100"] * 1.10 + 1e-6))
    pb = ((c > x["sma200"]) & (x["sma50"] > x["sma200"]) & (x["sma200"] > x["sma200"].shift(20))
          & (x["rsi2"] < PB_RSI_MAX) & (x["dvol20"] >= DOLLAR_VOL_MIN))
    f = lambda s: s.fillna(False).to_numpy(dtype=bool)
    return {"uf": f(uf), "M2": f(m2), "M2c": f(m2c), "M1": f(m1), "M0": f(m0), "PB": f(pb)}


# ═══════════════════════════════════════════════════════════════════════════
# Signals
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    ticker: str
    t: int                       # bar index of the signal close
    setup: str
    entry_type: str              # "stop" (buy-stop at level) | "open" (market)
    level: float                 # buy-stop level (ignored for "open")
    stop: Optional[float]        # fixed initial stop (None -> computed at fill: PB)
    conf: int
    size_mult: float
    rot_ok: bool
    max_entry: Optional[float] = None   # VCP: void if the fill is > 5% past the pivot


def _rot_leg(quad: Optional[str]) -> bool:
    return quad in ("Improving", "Leading")


def signals_for_ticker(tk: str, df: pd.DataFrame, x: pd.DataFrame, pf: dict,
                       bench: Optional[pd.Series], quads: Optional[pd.Series],
                       is_etf: bool, setups=SETUPS) -> list:
    """Every setup evaluated independently on every prefiltered day, using
    only bars <= t. M0 keeps its production precondition: only for ETFs or
    stocks failing the M2 universe filter, and only when no M1/M2/M2c
    candidate fired that day."""
    out = []
    n = len(df)
    vol = df["Volume"].to_numpy()
    vol50 = x["vol50"].to_numpy()
    rs = x["rs_rank"].to_numpy()
    bench_al = bench.reindex(df.index).ffill() if bench is not None else None
    qv = quads.reindex(df.index).to_numpy() if quads is not None else None
    any_day = np.zeros(n, dtype=bool)
    for s in setups:
        any_day |= pf[s]
    for t in np.nonzero(any_day)[0]:
        if t < WINDOW - 1 or t >= n - 1:
            continue
        w = df.iloc[t - WINDOW + 1:t + 1]
        bw = bench_al.iloc[t - WINDOW + 1:t + 1] if bench_al is not None else None
        quad = qv[t] if qv is not None else None
        rot = _rot_leg(quad)
        vol_leg = bool(vol[t] >= sd.BREAKOUT_VOL_MULT * vol50[t]) if vol50[t] > 0 else False
        fired = []
        if pf["M1"][t] and "M1" in setups:
            tt = sd.trend_template(w, bw)
            if tt["passes"]:
                vcp = sd.detect_vcp(w)
                px = float(w["Close"].iloc[-1])
                if vcp["is_vcp"] and px <= vcp["pivot"] * 1.05:
                    stop = vcp["pivot"] * (1 - min(sd.MAX_STOP_PCT_M1, max(3.0, vcp["last_contraction_pct"] + 1)) / 100)
                    fired.append(("M1", "stop", vcp["pivot"], stop, vol_leg, vcp["pivot"] * 1.05))
        if pf["uf"][t]:
            if pf["M2"][t] and "M2" in setups:
                bo = sd.detect_breakout(w)
                if bo["is_setup"]:
                    fired.append(("M2", "open", 0.0, float(w["Low"].iloc[-1]), vol_leg, None))
            if pf["M2c"][t] and "M2c" in setups:
                mb = sd.detect_momentum_burst(w)
                if mb["is_setup"]:
                    fired.append(("M2c", "open", 0.0, mb["bar_low"], vol_leg, None))
        if pf["M0"][t] and "M0" in setups and not fired and (is_etf or not pf["uf"][t]):
            rs_ok = is_etf or (not np.isnan(rs[t]) and round(float(rs[t])) >= sd.M0_RS_FLOOR)
            if rs_ok:
                m0 = sd.detect_rotation_reclaim(w, is_etf)
                if m0["is_setup"]:
                    fired.append(("M0", "stop", m0["entry"], m0["stop"], m0["volume_ok"], None))
        if pf["PB"][t] and "PB" in setups:
            pb = detect_pullback(w)
            if pb["is_setup"]:
                fired.append(("PB", "open", 0.0, None, pb["volume_ok"], None))
        for setup, et, level, stop, vleg, mx in fired:
            conf = int(rot) + 1 + int(bool(vleg))
            if conf < 2:
                continue
            out.append(Signal(tk, int(t), setup, et, float(level), stop, conf,
                              1.0 if conf == 3 else 0.5, rot, mx))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Trade path (independent of the portfolio: fills, exits, stop history)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Trade:
    ticker: str
    setup: str
    variant: str
    signal_t: int
    entry_t: int
    entry: float
    stop0: float
    conf: int
    size_mult: float
    asset: str
    events: list = field(default_factory=list)    # (t, kind, frac, price, bps)
    stops: list = field(default_factory=list)     # (t, stop) whenever it changes
    exit_t: int = -1
    exit_reason: str = ""
    r_net: float = float("nan")
    still_open: bool = False


def _asset(tk: str, is_etf: bool) -> str:
    return "lev" if tk in LEVERAGED else ("etf" if is_etf else "stock")


def simulate_trade(sig: Signal, arr: dict, variant: str, quads: Optional[np.ndarray],
                   asset: str) -> Optional[Trade]:
    o, h, l, c = arr["Open"], arr["High"], arr["Low"], arr["Close"]
    atr = arr["atr14"]
    n = len(c)
    d = sig.t + 1
    if d >= n:
        return None
    bps = COST_BPS[asset]
    # ── entry on day d only ─────────────────────────────────────────────
    if sig.entry_type == "open":
        fill, intraday_fill = o[d], False
    else:
        if o[d] >= sig.level:
            fill, intraday_fill = o[d], False
        elif h[d] >= sig.level:
            fill, intraday_fill = sig.level, True
        else:
            return None                                   # buy-stop never triggered
    if sig.max_entry is not None and fill > sig.max_entry:
        return None                                       # VCP: chasing, void
    stop = sig.stop if sig.stop is not None else fill - PB_ATR_STOP * atr[sig.t]
    if not np.isfinite(stop) or fill <= stop:
        return None
    risk = fill - stop
    atr_e = atr[sig.t] if np.isfinite(atr[sig.t]) else risk
    tr = Trade(sig.ticker, sig.setup, variant, sig.t, d, float(fill), float(stop),
               sig.conf, sig.size_mult, asset)
    tr.events.append((d, "entry", 1.0, float(fill), bps))
    tr.stops.append((d, float(stop)))
    rem, trims = 1.0, 0
    pending = None                                        # ("exit", reason) | ("trim",)
    trail = TRAIL[sig.setup]
    ma = None
    if trail is not None:
        ma = arr[f"{trail[0].lower()}{trail[1]}"]

    def close_out(t, px, reason, stop_fill):
        nonlocal rem
        tr.events.append((t, "exit", rem, float(px), bps + (STOP_SLIP_BPS if stop_fill else 0.0)))
        rem = 0.0
        tr.exit_t, tr.exit_reason = t, reason

    for j in range(d, n):
        # 1. pending orders execute at the open
        if j > d and pending is not None:
            if pending[0] == "exit":
                close_out(j, o[j], pending[1], False)
                break
            if pending[0] == "trim":
                q = min(0.25, rem)
                tr.events.append((j, "trim", q, float(o[j]), bps))
                rem -= q
                trims += 1
            pending = None
        # 2. resting stops (intraday). On the entry bar a stop touched after an
        #    intraday fill is assumed hit (worse outcome).
        if variant == "A":
            if l[j] <= stop:
                px = stop if (j == d or o[j] > stop) else o[j]
                close_out(j, px, "stop", True)
                break
        else:
            disaster = stop - DISASTER_ATR * atr_e
            if l[j] <= disaster:
                px = disaster if (j == d or o[j] > disaster) else o[j]
                close_out(j, px, "disaster stop", True)
                break
        # 3. end-of-day rules, production order; one action per day
        held = j - d
        R_close = (c[j] - fill) / risk
        if variant == "B" and c[j] <= stop:
            pending = ("exit", "closing-basis stop")
            continue
        if sig.setup != "PB" and quads is not None and quads[j] is not None and not _rot_leg(quads[j]):
            pending = ("exit", "thesis: sector Weakening/Lagging")
            continue
        if sig.setup == "PB":
            if c[j] > arr["sma5"][j]:
                pending = ("exit", "PB: close above 5 SMA")
                continue
            if held >= PB_MAX_DAYS:
                pending = ("exit", "PB: time stop")
                continue
        if sig.setup == "M2c" and (held >= BURST_MAX_DAYS or c[j] < arr["ema5"][j]):
            pending = ("exit", "burst: day 5 / close < 5 EMA")
            continue
        if asset == "lev" and held >= LEV_MAX_DAYS:
            pending = ("exit", "leveraged 90-day cap")
            continue
        if ma is not None and j >= 3 and np.isfinite(ma[j]) and c[j] < ma[j]:
            rising = ma[j] > ma[j - 3]
            if not rising:
                pending = ("exit", "trend: close below falling trail MA")
                continue
            if ma[j] > stop:
                stop = float(ma[j])
                tr.stops.append((j, stop))
                continue
        if sig.setup != "PB" and trims < len(LADDER) and rem > 0.25 + 1e-9 and R_close >= LADDER[trims]:
            pending = ("trim",)
    if rem > 0:
        tr.events.append((n - 1, "mark", rem, float(c[n - 1]), 0.0))
        tr.still_open, tr.exit_t, tr.exit_reason = True, n - 1, "open at end"
    gross = sum(f * p for t, k, f, p, b in tr.events if k != "entry")
    cost = sum(f * p * b / 1e4 for t, k, f, p, b in tr.events)
    tr.r_net = (gross - fill - cost) / risk
    return tr


# ═══════════════════════════════════════════════════════════════════════════
# Statistics
# ═══════════════════════════════════════════════════════════════════════════

def trade_stats(rs: list) -> dict:
    r = np.array([x for x in rs if np.isfinite(x)], dtype=float)
    n = len(r)
    if n == 0:
        return {"n": 0}
    wins, losses = r[r > SCRATCH_R], r[r < -SCRATCH_R]
    gp, gl = wins.sum(), -losses.sum()
    streak = best = 0
    for x in r:
        if x < -SCRATCH_R:
            streak += 1
            best = max(best, streak)
        elif x > SCRATCH_R:
            streak = 0
    return {"n": n, "win_rate": round(len(wins) / n * 100, 1),
            "avg_win_R": round(float(wins.mean()), 2) if len(wins) else 0.0,
            "avg_loss_R": round(float(losses.mean()), 2) if len(losses) else 0.0,
            "expectancy_R": round(float(r.mean()), 3),
            "profit_factor": round(float(gp / gl), 2) if gl > 0 else (float("inf") if gp > 0 else 0.0),
            "worst_R": round(float(r.min()), 2), "best_R": round(float(r.max()), 2),
            "max_consec_losses": best}


def deflated_sharpe(sr: float, n_obs: int, skew: float, kurt: float, sr_var: float, n_trials: int) -> float:
    """Bailey & López de Prado (2014). sr, sr_var on the SAME (per-period)
    scale. Probability the true Sharpe exceeds the best expected from
    n_trials unskilled trials."""
    if n_obs < 3 or not np.isfinite(sr):
        return float("nan")
    nd = NormalDist()
    g = 0.5772156649
    n_trials = max(int(n_trials), 1)
    if n_trials == 1 or sr_var <= 0:
        sr0 = 0.0
    else:
        sr0 = math.sqrt(sr_var) * ((1 - g) * nd.inv_cdf(1 - 1 / n_trials)
                                   + g * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    den = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if den <= 0:
        return float("nan")
    return nd.cdf((sr - sr0) * math.sqrt(n_obs - 1) / math.sqrt(den))


def series_stats(eq: pd.Series) -> dict:
    eq = eq.dropna()
    if len(eq) < 2 or eq.iloc[0] <= 0:
        return {}
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else float("nan")
    dd = eq / eq.cummax() - 1
    r = eq.pct_change().dropna()
    vol = r.std() * math.sqrt(252)
    return {"cagr_pct": round(cagr * 100, 2), "max_dd_pct": round(float(dd.min()) * 100, 2),
            "vol_pct": round(vol * 100, 2),
            "sharpe": round(float(r.mean() / r.std() * math.sqrt(252)), 2) if r.std() > 0 else float("nan"),
            "calmar": round(cagr / abs(dd.min()), 2) if dd.min() < 0 else float("nan")}


# ═══════════════════════════════════════════════════════════════════════════
# Portfolio pass
# ═══════════════════════════════════════════════════════════════════════════

def run_portfolio(trades: list, signals_unfilled: list, data: dict, cal: pd.DatetimeIndex,
                  sector_of: dict, start_equity: float = START_EQUITY,
                  heat_cap_pct: float = HEAT_CAP_PCT) -> dict:
    """Daily walk. Orders are allocated to slots BEFORE their fill is known:
    an order that does not fill still used its slot that day (no look-ahead
    in selection). Exits at the open and intraday stops on held positions
    settle before new entries."""
    cal_pos = {d: i for i, d in enumerate(cal)}
    idx_maps = {tk: data[tk]["index"] for tk in data}

    def cal_t(tk, t):
        return cal_pos.get(idx_maps[tk][t])

    by_day_orders: dict = {}
    for tr in trades:
        k = cal_t(tr.ticker, tr.entry_t)
        if k is not None:
            by_day_orders.setdefault(k, []).append(("fill", tr))
    for sig in signals_unfilled:
        if sig.t + 1 < len(idx_maps[sig.ticker]):
            k = cal_t(sig.ticker, sig.t + 1)
            if k is not None:
                by_day_orders.setdefault(k, []).append(("nofill", sig))

    cash = start_equity
    pos: dict = {}                    # id -> dict(tr, shares, events_by_cal, stops)
    equity_prev = start_equity
    eq_curve, expo, heat_curve = [], [], []
    closed_r: list = []
    losses = wins = 0
    reduced = False
    taken = []
    for k, day in enumerate(cal):
        # 1. events on held positions (exits/trims at open, stops intraday)
        for pid in list(pos):
            p = pos[pid]
            for t, kind, frac, px, bps in p["events"].get(k, []):
                if kind == "entry":
                    continue
                sh = p["shares0"] * frac
                cash += sh * px * (1 - bps / 1e4)
                p["shares"] -= sh
            for t, s in p["stopchg"].get(k, []):
                p["stop"] = s
            if p["shares"] <= 1e-9:
                tr = p["tr"]
                closed_r.append(tr.r_net)
                if tr.r_net < -SCRATCH_R:
                    losses, wins = losses + 1, 0
                elif tr.r_net > SCRATCH_R:
                    wins, losses = wins + 1, 0
                if losses >= STREAK_LOSSES:
                    reduced = True
                if reduced and wins >= STREAK_RESET_WINS:
                    reduced = False
                del pos[pid]
        # 2. new orders, ranked like production (confluence, then tighter stop)
        orders = by_day_orders.get(k, [])

        def rank(o):
            obj = o[1]
            if o[0] == "fill":
                return (-obj.conf, (obj.entry - obj.stop0) / obj.entry)
            return (-obj.conf, 1.0)
        orders.sort(key=rank)
        heat = sum(p["shares"] * max(0.0, p["entry"] - p["stop"]) for p in pos.values())
        sec_count: dict = {}
        for p in pos.values():
            sec_count[p["sector"]] = sec_count.get(p["sector"], 0) + 1
        held_tk = {p["tr"].ticker for p in pos.values()}
        slots = MAX_POSITIONS - len(pos)
        for kind, obj in orders:
            if slots <= 0:
                break
            tk = obj.ticker
            sec = sector_of.get(tk) or f"OTHER:{tk}"
            if tk in held_tk or sec_count.get(sec, 0) >= MAX_PER_SECTOR:
                continue
            slots -= 1
            if kind == "nofill":
                continue
            tr = obj
            risk_pct = (REDUCED_RISK_PCT if reduced else BASE_RISK_PCT) * tr.size_mult
            rps = tr.entry - tr.stop0
            shares = math.floor(equity_prev * risk_pct / 100 / rps)
            shares = min(shares, math.floor(equity_prev * MAX_POSITION_PCT / 100 / tr.entry))
            bps = COST_BPS[tr.asset]
            shares = min(shares, math.floor(cash / (tr.entry * (1 + bps / 1e4))))
            if shares < 1 or (heat + shares * rps) > equity_prev * heat_cap_pct / 100 + 1e-6:
                continue
            cash -= shares * tr.entry * (1 + bps / 1e4)
            heat += shares * rps
            ev, sc = {}, {}
            for e in tr.events:
                kk = cal_t(tk, e[0])
                if kk is not None:
                    ev.setdefault(kk, []).append(e)
            for t, s in tr.stops[1:]:
                kk = cal_t(tk, t)
                if kk is not None:
                    sc.setdefault(kk, []).append((t, s))
            pid = f"{tk}:{tr.entry_t}:{tr.setup}"
            pos[pid] = {"tr": tr, "shares0": shares, "shares": shares, "entry": tr.entry,
                        "stop": tr.stop0, "sector": sec, "events": ev, "stopchg": sc}
            taken.append((tr, shares))
            held_tk.add(tk)
            sec_count[sec] = sec_count.get(sec, 0) + 1
            # same-day events on the new position (stop on the entry bar)
            p = pos[pid]
            for t, kind2, frac, px, b2 in ev.get(k, []):
                if kind2 == "entry":
                    continue
                sh = shares * frac
                cash += sh * px * (1 - b2 / 1e4)
                p["shares"] -= sh
            if p["shares"] <= 1e-9:
                closed_r.append(tr.r_net)
                if tr.r_net < -SCRATCH_R:
                    losses, wins = losses + 1, 0
                elif tr.r_net > SCRATCH_R:
                    wins, losses = wins + 1, 0
                if losses >= STREAK_LOSSES:
                    reduced = True
                del pos[pid]
        # 3. mark to market at the close
        mv = 0.0
        for p in pos.values():
            tk = p["tr"].ticker
            px = data[tk]["close_cal"].iloc[k]
            if not np.isfinite(px):
                px = p["entry"]
            mv += p["shares"] * px
        eq = cash + mv
        if cash < -1e-6:
            raise AssertionError(f"cash went negative on {day}: {cash}")
        eq_curve.append(eq)
        expo.append(mv / eq if eq > 0 else 0.0)
        heat_curve.append(sum(p["shares"] * max(0.0, p["entry"] - p["stop"]) for p in pos.values()) / eq * 100
                          if eq > 0 else 0.0)
        equity_prev = eq
    eq_s = pd.Series(eq_curve, index=cal)
    monthly = eq_s.resample("ME").last().pct_change().dropna()
    dd = eq_s / eq_s.cummax() - 1
    return {"equity": eq_s, "exposure_avg_pct": round(float(np.mean(expo)) * 100, 1),
            "heat_max_pct": round(float(np.max(heat_curve)) if heat_curve else 0.0, 2),
            "trades_taken": len(taken), "taken": taken,
            "months_le_-10pct": int((monthly <= -0.10).sum()),
            "hwm_-20pct_breached": bool((dd <= -0.20).any()),
            "stats": series_stats(eq_s)}


# ═══════════════════════════════════════════════════════════════════════════
# Data
# ═══════════════════════════════════════════════════════════════════════════

def universe() -> tuple:
    stocks, sector_of = {}, {}
    path = os.path.join("data", "rotation_summary.json")
    cons = None
    try:
        with open(path) as fh:
            cons = json.load(fh).get("constituents")
    except Exception:
        cons = None
    cons = cons or FALLBACK_CONSTITUENTS
    for etf, names in cons.items():
        for tk in names:
            stocks[tk] = etf
    for s in SECTOR_ETFS:
        sector_of[s] = s
    for tk, s in OTHER_ETFS.items():
        sector_of[tk] = s
    sector_of.update(stocks)
    etfs = SECTOR_ETFS + list(OTHER_ETFS)
    return etfs, sorted(stocks), sector_of


def fetch_ohlcv(tickers: list, start: str = START) -> dict:
    import yfinance as yf
    out = {}

    def take(df, t):
        if df is None or len(df) == 0:
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
        cols = ["Open", "High", "Low", "Close", "Volume"]
        if not all(cc in sub.columns for cc in cols):
            return
        sub = sub[cols].dropna(subset=["Open", "High", "Low", "Close"])
        sub = sub[(sub["High"] > 0) & (sub["Low"] > 0)]
        if len(sub) < WINDOW + 50:
            return
        idx = pd.to_datetime(sub.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        sub.index = idx.normalize()
        out[t] = sub[~sub.index.duplicated(keep="last")].sort_index().astype(float)

    try:
        df = yf.download(tickers, start=start, auto_adjust=True, progress=False,
                         group_by="ticker", threads=True)
        for t in tickers:
            take(df, t)
    except Exception as e:
        print(f"[swing_backtest] batch download failed: {type(e).__name__}: {e}")
    for t in [t for t in tickers if t not in out]:
        try:
            take(yf.download(t, start=start, auto_adjust=True, progress=False), t)
        except Exception as e:
            print(f"[swing_backtest] {t}: {type(e).__name__}: {e}")
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Orchestration
# ═══════════════════════════════════════════════════════════════════════════

def run(ohlcv: dict, etfs: list, stocks: list, sector_of: dict, setups=SETUPS,
        variants=VARIANTS, verbose: bool = True) -> dict:
    bench = ohlcv["SPY"]["Close"] if "SPY" in ohlcv else None
    quads_by_sector = rotation_proxy({k: v["Close"] for k, v in ohlcv.items()})
    cal = ohlcv["SPY"].index if "SPY" in ohlcv else sorted(set().union(*[v.index for v in ohlcv.values()]))
    cal = pd.DatetimeIndex(cal)
    data, sigs = {}, []
    for i, tk in enumerate(sorted(ohlcv)):
        df = ohlcv[tk]
        is_etf = tk in etfs
        x = indicators(df, bench)
        pf = prefilters(df, x)
        sec = sector_of.get(tk)
        q = quads_by_sector.get(sec) if sec else None
        qv = q.reindex(df.index).to_numpy() if q is not None else None
        arr = {k: df[k].to_numpy(dtype=float, copy=True) for k in ("Open", "High", "Low", "Close")}
        for col in ("atr14", "sma5", "ema5", "ema10", "sma50", "sma100"):
            arr[col] = x[col].to_numpy(dtype=float, copy=True)
        data[tk] = {"arr": arr, "quads": qv, "index": df.index, "asset": _asset(tk, is_etf),
                    "close_cal": df["Close"].reindex(cal).ffill()}
        s = signals_for_ticker(tk, df, x, pf, bench, q, is_etf, setups)
        sigs.extend(s)
        if verbose:
            print(f"[{i + 1}/{len(ohlcv)}] {tk}: {len(s)} signals")
    # One open trade per (ticker, setup, variant) at a time: a setup that keeps
    # firing while a trade is open is the same idea, not a new trade. Without
    # this the trade statistics would count overlapping duplicates.
    trades = {v: [] for v in variants}
    unfilled = []
    busy_until: dict = {}
    for sg in sorted(sigs, key=lambda z: (z.ticker, z.setup, z.t)):
        d = data[sg.ticker]
        for v in variants:
            key = (sg.ticker, sg.setup, v)
            if sg.t + 1 <= busy_until.get(key, -1):
                continue
            tr = simulate_trade(sg, d["arr"], v, d["quads"], d["asset"])
            if tr is not None:
                trades[v].append(tr)
                busy_until[key] = tr.exit_t
            elif v == variants[0]:
                unfilled.append(sg)
    return {"signals": sigs, "trades": trades, "unfilled": unfilled, "data": data, "cal": cal}


def summarise(res: dict, sector_of: dict, ohlcv: dict) -> dict:
    rows = []
    cal = res["cal"]
    data = res["data"]
    for v, trs in res["trades"].items():
        for s in SETUPS + ("ALL",):
            sub = [t for t in trs if (s == "ALL" or t.setup == s) and not t.still_open]
            for scope in ("all", "etf+lev", "stock"):
                sc = [t for t in sub if scope == "all" or (scope == "stock") == (t.asset == "stock")]
                for half in ("full", "2005-15", "2016-26"):
                    hh = [t for t in sc if half == "full" or
                          ((data[t.ticker]["index"][t.entry_t] < HALF_SPLIT) == (half == "2005-15"))]
                    st = trade_stats([t.r_net for t in hh])
                    held = [t.exit_t - t.entry_t for t in hh]
                    st.update({"variant": v, "setup": s, "scope": scope, "half": half,
                               "avg_bars_held": round(float(np.mean(held)), 1) if held else None})
                    rows.append(st)
    table = pd.DataFrame(rows)
    # verdicts against the frozen bar
    verdicts = []
    for v in res["trades"]:
        for s in SETUPS:
            def g(scope, half):
                r = table[(table.variant == v) & (table.setup == s) & (table.scope == scope) & (table.half == half)]
                return r.iloc[0].to_dict() if len(r) else {"n": 0}

            def passes(scope):
                full, a, b = g(scope, "full"), g(scope, "2005-15"), g(scope, "2016-26")
                why = []
                if full.get("n", 0) < BAR["min_trades"]:
                    why.append(f"n {full.get('n', 0)} < {BAR['min_trades']}")
                for nm, hf in (("2005-15", a), ("2016-26", b)):
                    if hf.get("n", 0) < BAR["min_per_half"]:
                        why.append(f"{nm} n {hf.get('n', 0)} < {BAR['min_per_half']}")
                    else:
                        if hf.get("expectancy_R", 0) <= 0:
                            why.append(f"{nm} expectancy {hf.get('expectancy_R')}R <= 0")
                        if hf.get("profit_factor", 0) < BAR["min_pf"]:
                            why.append(f"{nm} PF {hf.get('profit_factor')} < {BAR['min_pf']}")
                return (not why), why
            ok_all, why_all = passes("all")
            ok_etf, why_etf = passes("etf+lev")
            if ok_etf:
                verdict = "PASS"
            elif ok_all:
                verdict = "INDICATIVE (stock-dependent; survivorship bias)"
            else:
                verdict = "FAIL"
            verdicts.append({"variant": v, "setup": s, "verdict": verdict,
                             "etf_reasons": "; ".join(why_etf) or "meets bar",
                             "all_reasons": "; ".join(why_all) or "meets bar"})
    # portfolios: each setup alone, and all setups combined, per variant
    ports = {}
    for v, trs in res["trades"].items():
        for s in SETUPS + ("ALL",):
            sel = [t for t in trs if s == "ALL" or t.setup == s]
            uf = [g for g in res["unfilled"] if s == "ALL" or g.setup == s]
            ports[(v, s)] = run_portfolio(sel, uf, data, cal, sector_of)
    # deflated Sharpe across the portfolio trials run in this pass
    srs, info = [], {}
    for key, p in ports.items():
        r = p["equity"].pct_change().dropna()
        r = r[r.index >= cal[WINDOW]] if len(cal) > WINDOW else r
        if len(r) > 10 and r.std() > 0:
            sr = float(r.mean() / r.std())
            info[key] = (sr, len(r), float(r.skew()), float(r.kurt()) + 3.0)
            srs.append(sr)
    sr_var = float(np.var(srs, ddof=1)) if len(srs) > 1 else 0.0
    n_trials = prior_trials() + len(info)
    for key, (sr, nobs, sk, ku) in info.items():
        ports[key]["dsr"] = round(deflated_sharpe(sr, nobs, sk, ku, sr_var, n_trials), 3)
    bench = {}
    for b in ("SPY", "QQQ"):
        if b in ohlcv:
            s = ohlcv[b]["Close"].reindex(cal).ffill()
            s = s[s.index >= cal[WINDOW]] if len(cal) > WINDOW else s
            bench[b] = series_stats(s)
    return {"table": table, "verdicts": pd.DataFrame(verdicts), "ports": ports,
            "bench": bench, "n_trials": n_trials, "trials_this_run": len(info)}


def prior_trials() -> int:
    p = os.path.join(OUT_DATA, "trial_log.csv")
    try:
        return int(pd.read_csv(p)["trials"].sum())
    except Exception:
        return 0


def exit_mix(trades: list) -> pd.DataFrame:
    rows = [{"setup": t.setup, "variant": t.variant, "reason": t.exit_reason, "r": t.r_net}
            for t in trades if not t.still_open]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return (df.groupby(["variant", "setup", "reason"])["r"]
            .agg(n="count", avg_R="mean").round(2).reset_index())


def write_outputs(res: dict, summ: dict, ohlcv: dict, stamp: str) -> str:
    os.makedirs(OUT_DATA, exist_ok=True)
    os.makedirs(OUT_LOGS, exist_ok=True)
    data = res["data"]
    trows = []
    for v, trs in res["trades"].items():
        for t in trs:
            ix = data[t.ticker]["index"]
            trows.append({"variant": v, "setup": t.setup, "ticker": t.ticker, "asset": t.asset,
                          "signal_date": ix[t.signal_t].date(), "entry_date": ix[t.entry_t].date(),
                          "exit_date": ix[t.exit_t].date(), "entry": round(t.entry, 4),
                          "stop0": round(t.stop0, 4), "conf": t.conf, "r_net": round(t.r_net, 3),
                          "exit_reason": t.exit_reason, "still_open": t.still_open})
    pd.DataFrame(trows).to_csv(os.path.join(OUT_DATA, "trades.csv"), index=False)
    summ["table"].to_csv(os.path.join(OUT_DATA, "setup_stats.csv"), index=False)
    summ["verdicts"].to_csv(os.path.join(OUT_DATA, "verdicts.csv"), index=False)
    prow = []
    eqs = {}
    for (v, s), p in summ["ports"].items():
        prow.append({"variant": v, "setup": s, **p["stats"], "dsr": p.get("dsr"),
                     "exposure_avg_pct": p["exposure_avg_pct"], "heat_max_pct": p["heat_max_pct"],
                     "trades_taken": p["trades_taken"], "months_le_-10pct": p["months_le_-10pct"],
                     "hwm_-20pct_breached": p["hwm_-20pct_breached"]})
        eqs[f"{s}_{v}"] = p["equity"]
    pd.DataFrame(prow).to_csv(os.path.join(OUT_DATA, "portfolio_stats.csv"), index=False)
    pd.DataFrame(eqs).round(2).to_csv(os.path.join(OUT_DATA, "equity.csv"))
    tl = os.path.join(OUT_DATA, "trial_log.csv")
    row = pd.DataFrame([{"date": stamp, "version": VERSION, "trials": summ["trials_this_run"],
                         "note": "5 setups + ALL x stop A/B portfolios"}])
    prev = pd.concat([pd.read_csv(tl), row]) if os.path.exists(tl) else row
    prev.to_csv(tl, index=False)
    md = render_report(res, summ, ohlcv, stamp)
    path = os.path.join(OUT_LOGS, f"{stamp}_report.md")
    with open(path, "w") as fh:
        fh.write(md)
    return path


def _fmt(x, nd=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:.{nd}f}" if isinstance(x, (float, np.floating)) else str(x)


def render_report(res: dict, summ: dict, ohlcv: dict, stamp: str) -> str:
    t = summ["table"]
    L = [f"# Swing backtest v{VERSION} — {stamp}", "",
         f"Universe: {len(ohlcv)} tickers with data. Signals: {len(res['signals'])}. "
         f"History from {res['cal'][0].date()} to {res['cal'][-1].date()}; halves split at {HALF_SPLIT.date()}.",
         f"Trials logged to date (incl. this run): **{summ['n_trials']}** — every Deflated Sharpe below is "
         f"deflated for that count.", "",
         "**Honest limits:** regime gating untested (no point-in-time regime history, N11); rotation = "
         "replica of Money Flow's default RRG, price only (no Tier A flow history); stock universe = today's top holdings (survivorship bias → stock results are "
         "an upper bound); no earnings/FOMC/CPI blackouts; loss limits measured, not enforced.", "",
         "## Verdicts against the frozen bar",
         f"Bar: ≥{BAR['min_trades']} trades, ≥{BAR['min_per_half']} per half, expectancy > 0 and profit "
         f"factor ≥ {BAR['min_pf']} in BOTH halves, net of costs. PASS requires the ETF + leveraged-ETF "
         f"universe alone to meet it.", "",
         "| Stop | Setup | Verdict | ETF+lev reasons | All-universe reasons |", "|---|---|---|---|---|"]
    for _, r in summ["verdicts"].iterrows():
        L.append(f"| {r.variant} | {SETUP_NAMES[r.setup]} | **{r.verdict}** | {r.etf_reasons} | {r.all_reasons} |")
    L += ["", "## Trade statistics (net R per trade, full history)", "",
          "| Stop | Setup | Scope | n | Win % | Avg win R | Avg loss R | Expectancy R | PF | Worst R | Max losing streak | Bars held |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in t[t.half == "full"].iterrows():
        if r.get("n", 0) == 0:
            continue
        L.append(f"| {r.variant} | {SETUP_NAMES.get(r.setup, r.setup)} | {r.scope} | {int(r.n)} | {_fmt(r.win_rate, 1)} | "
                 f"{_fmt(r.avg_win_R)} | {_fmt(r.avg_loss_R)} | {_fmt(r.expectancy_R, 3)} | {_fmt(r.profit_factor)} | "
                 f"{_fmt(r.worst_R)} | {int(r.max_consec_losses)} | {_fmt(r.avg_bars_held, 1)} |")
    L += ["", "## By half (all universe)", "",
          "| Stop | Setup | Half | n | Win % | Expectancy R | PF |", "|---|---|---|---|---|---|---|"]
    for _, r in t[(t.half != "full") & (t.scope == "all")].iterrows():
        if r.get("n", 0) == 0:
            continue
        L.append(f"| {r.variant} | {SETUP_NAMES.get(r.setup, r.setup)} | {r.half} | {int(r.n)} | "
                 f"{_fmt(r.win_rate, 1)} | {_fmt(r.expectancy_R, 3)} | {_fmt(r.profit_factor)} |")
    L += ["", "## Portfolio pass ($10,000, 2% base risk, production sizing)", "",
          "| Stop | Setups | CAGR % | Max DD % | Vol % | Sharpe | Calmar | DSR | Exposure % | Max heat % | Trades | Months ≤ −10% | −20% HWM breached |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (v, s), p in summ["ports"].items():
        st = p["stats"]
        L.append(f"| {v} | {SETUP_NAMES.get(s, 'ALL combined')} | {_fmt(st.get('cagr_pct'))} | {_fmt(st.get('max_dd_pct'))} | "
                 f"{_fmt(st.get('vol_pct'))} | {_fmt(st.get('sharpe'))} | {_fmt(st.get('calmar'))} | {_fmt(p.get('dsr'), 3)} | "
                 f"{p['exposure_avg_pct']} | {p['heat_max_pct']} | {p['trades_taken']} | {p['months_le_-10pct']} | "
                 f"{'yes' if p['hwm_-20pct_breached'] else 'no'} |")
    L += ["", "Benchmarks over the same window (buy and hold, dividends included):", ""]
    for b, st in summ["bench"].items():
        L.append(f"- **{b}**: CAGR {_fmt(st.get('cagr_pct'))}%, max DD {_fmt(st.get('max_dd_pct'))}%, "
                 f"Sharpe {_fmt(st.get('sharpe'))}")
    mix = exit_mix([tr for v in res["trades"].values() for tr in v])
    if len(mix):
        L += ["", "## How trades ended (does the thesis exit cut winners?)", "",
              "| Stop | Setup | Exit reason | n | Avg R |", "|---|---|---|---|---|"]
        for _, r in mix.iterrows():
            L.append(f"| {r.variant} | {SETUP_NAMES[r.setup]} | {r.reason} | {int(r.n)} | {_fmt(r.avg_R)} |")
    L += ["", "## Stop-method rule (fixed before the run)",
          "Variant B (closing-basis + disaster stop) is preferred only where its expectancy is at least "
          "variant A's in BOTH halves; otherwise A.", "",
          f"*Generated by swing_backtest.py v{VERSION}. Research, not personalized advice.*"]
    return "\n".join(L) + "\n"


def main() -> int:
    etfs, stocks, sector_of = universe()
    tickers = sorted(set(etfs + stocks))
    print(f"[swing_backtest] v{VERSION}: fetching {len(tickers)} tickers from {START}")
    ohlcv = fetch_ohlcv(tickers)
    missing = [t for t in tickers if t not in ohlcv]
    print(f"[swing_backtest] data for {len(ohlcv)} of {len(tickers)}; missing: {missing}")
    if "SPY" not in ohlcv:
        print("[swing_backtest] DATA FAILURE: no SPY history; nothing written.")
        return 1
    res = run(ohlcv, etfs, stocks, sector_of)
    summ = summarise(res, sector_of, ohlcv)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = write_outputs(res, summ, ohlcv, stamp)
    print(f"[swing_backtest] report: {path}")
    print(summ["verdicts"].to_string(index=False))
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# Selftest (offline, synthetic data)
# ═══════════════════════════════════════════════════════════════════════════

def _bars(close: np.ndarray, vol: np.ndarray, band: float = 0.02, start="2010-01-04",
          opens: Optional[np.ndarray] = None) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(close))
    c = pd.Series(close, index=idx, dtype=float)
    o = pd.Series(opens, index=idx, dtype=float) if opens is not None else c.shift(1).fillna(c)
    df = pd.DataFrame({"Open": o, "Close": c, "High": c * (1 + band), "Low": c * (1 - band),
                       "Volume": np.asarray(vol, dtype=float)}, index=idx)
    df["High"] = df[["Open", "Close", "High"]].max(axis=1)
    df["Low"] = df[["Open", "Close", "Low"]].min(axis=1)
    return df


def _walk(seed: int, n: int = 900, drift: float = 0.0006, vol: float = 0.02, spikes: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, n)
    c = 50 * np.exp(np.cumsum(r))
    v = rng.lognormal(14, 0.4, n)
    if spikes:
        k = rng.choice(n, n // 12, replace=False)
        v[k] *= rng.uniform(1.6, 4.0, len(k))
    return _bars(c, v, band=float(rng.uniform(0.008, 0.03)))


def _arr(df: pd.DataFrame) -> dict:
    x = indicators(df, None)
    a = {k: df[k].to_numpy(dtype=float, copy=True) for k in ("Open", "High", "Low", "Close")}
    for col in ("atr14", "sma5", "ema5", "ema10", "sma50", "sma100"):
        a[col] = x[col].to_numpy(dtype=float, copy=True)
    return a


def selftest() -> dict:
    f = []
    # 1. prefilters never drop a day the production detector fires
    misses = {"M2": 0, "M2c": 0, "M0": 0, "M1": 0, "PB": 0}
    fires = dict.fromkeys(misses, 0)
    for seed in range(6):
        df = _walk(seed, drift=0.0004 + 0.0003 * (seed % 3), vol=0.012 + 0.006 * (seed % 3))
        bench = pd.Series(50 * np.exp(np.cumsum(np.full(len(df), 0.0002))), index=df.index)
        x = indicators(df, bench)
        pf = prefilters(df, x)
        for t in range(WINDOW - 1, len(df) - 1, 2):
            w = df.iloc[t - WINDOW + 1:t + 1]
            bw = bench.iloc[t - WINDOW + 1:t + 1]
            uf = sd.universe_filter(w)["passes"]
            if uf != bool(pf["uf"][t]) and uf:
                f.append(f"uf prefilter dropped a passing day (seed {seed}, t {t})")
            if uf and sd.detect_breakout(w)["is_setup"]:
                fires["M2"] += 1
                misses["M2"] += int(not pf["M2"][t])
            if uf and sd.detect_momentum_burst(w)["is_setup"]:
                fires["M2c"] += 1
                misses["M2c"] += int(not pf["M2c"][t])
            if sd.detect_rotation_reclaim(w, True)["is_setup"]:
                fires["M0"] += 1
                misses["M0"] += int(not pf["M0"][t])
            tt = sd.trend_template(w, bw)
            if tt["passes"] and sd.detect_vcp(w)["is_vcp"]:
                fires["M1"] += 1
                misses["M1"] += int(not pf["M1"][t])
            if detect_pullback(w)["is_setup"]:
                fires["PB"] += 1
                misses["PB"] += int(not pf["PB"][t])
    for k in misses:
        if misses[k]:
            f.append(f"prefilter {k} dropped {misses[k]} of {fires[k]} detector fires")
    # breakout fixture (prior +35%, 6% base, 2.4x volume): the last bar fires; the prefilter must keep it
    bo = _bars(np.concatenate([np.linspace(45, 50, 230), np.linspace(50, 75, 50),
                               np.linspace(74.5, 76.5, 19), [79.0]]),
               np.concatenate([np.full(299, 2e6), [5e6]]), band=0.025)
    xb = indicators(bo, None)
    if not sd.detect_breakout(bo)["is_setup"] or not prefilters(bo, xb)["M2"][-1]:
        f.append("prefilter M2 dropped the production breakout fixture")
    else:
        fires["M2"] += 1
    if min(fires["M2c"], fires["M0"], fires["PB"]) == 0:
        f.append(f"selftest walks produced too few fires to prove the prefilters: {fires}")

    # 2. no look-ahead: changing bars after t must not change signals at <= t
    df = _walk(11, drift=0.0008)
    bench = df["Close"] * 0 + 50
    x = indicators(df, bench)
    sig_a = signals_for_ticker("T", df, x, prefilters(df, x), bench, None, True)
    df2 = df.copy()
    cut = len(df) - 120
    df2.iloc[cut + 1:, df2.columns.get_loc("Close")] *= 1.5
    df2.iloc[cut + 1:, df2.columns.get_loc("High")] *= 1.5
    df2.iloc[cut + 1:, df2.columns.get_loc("Volume")] *= 3
    x2 = indicators(df2, bench)
    sig_b = signals_for_ticker("T", df2, x2, prefilters(df2, x2), bench, None, True)
    ka = {(s.t, s.setup, round(s.level, 6)) for s in sig_a if s.t <= cut}
    kb = {(s.t, s.setup, round(s.level, 6)) for s in sig_b if s.t <= cut}
    if ka != kb:
        f.append(f"look-ahead: signals at or before t changed when later bars changed ({len(ka ^ kb)} differ)")
    # per-signal check: every bar AFTER a signal's t is perturbed; the signal must survive
    ts = sorted({s.t for s in sig_a})
    for t0 in ts[:: max(1, len(ts) // 8)][:8]:
        d3 = df.copy()
        for col, k in (("Close", 1.4), ("High", 1.45), ("Low", 1.35), ("Open", 1.4), ("Volume", 4.0)):
            d3.iloc[t0 + 1:, d3.columns.get_loc(col)] *= k
        x3 = indicators(d3, bench)
        s3 = {(s.t, s.setup, round(s.level, 6)) for s in
              signals_for_ticker("T", d3, x3, prefilters(d3, x3), bench, None, True) if s.t == t0}
        s0 = {(s.t, s.setup, round(s.level, 6)) for s in sig_a if s.t == t0}
        if s0 != s3:
            f.append(f"look-ahead: signal at bar {t0} depends on later bars")
            break

    # 3. fills and stops on hand-built bars
    n = 30
    close = np.full(n, 100.0)
    df = _bars(close, np.full(n, 1e6), band=0.01)
    a = _arr(df)
    a["atr14"][:] = 2.0
    # buy-stop above the day's high never fills
    s = Signal("Z", 5, "M0", "stop", 105.0, 95.0, 3, 1.0, True)
    if simulate_trade(s, a, "A", None, "etf") is not None:
        f.append("buy-stop above the high must not fill")
    # gap through the buy-stop fills at the open
    a2 = {k: v.copy() for k, v in a.items()}
    a2["Open"][6], a2["High"][6], a2["Low"][6], a2["Close"][6] = 103.0, 104.0, 102.5, 103.5
    tr = simulate_trade(Signal("Z", 5, "M0", "stop", 101.0, 95.0, 3, 1.0, True), a2, "A", None, "etf")
    if tr is None or abs(tr.entry - 103.0) > 1e-9:
        f.append(f"gap through a buy-stop must fill at the open: {tr and tr.entry}")
    # variant A: intraday touch of the stop exits at the stop
    a3 = {k: v.copy() for k, v in a.items()}
    a3["Low"][10] = 94.0
    tr = simulate_trade(Signal("Z", 5, "M2", "open", 0.0, 95.0, 3, 1.0, True), a3, "A", None, "etf")
    if tr is None or tr.exit_reason != "stop" or abs(tr.events[-1][3] - 95.0) > 1e-9:
        f.append(f"variant A must exit at the stop on an intraday touch: {tr and (tr.exit_reason, tr.events[-1])}")
    # variant B: same intraday dip with a close back above -> no exit
    tr = simulate_trade(Signal("Z", 5, "M2", "open", 0.0, 95.0, 3, 1.0, True), a3, "B", None, "etf")
    if tr is None or tr.exit_reason in ("closing-basis stop", "disaster stop"):
        f.append(f"variant B must ignore an intraday dip that closes above the stop: {tr and tr.exit_reason}")
    # variant B: close below the stop -> exit at the NEXT open
    a4 = {k: v.copy() for k, v in a.items()}
    a4["Low"][10], a4["Close"][10] = 94.0, 94.5
    a4["Open"][11] = 94.2
    tr = simulate_trade(Signal("Z", 5, "M2", "open", 0.0, 95.0, 3, 1.0, True), a4, "B", None, "etf")
    if tr is None or tr.exit_reason != "closing-basis stop" or tr.exit_t != 11 or abs(tr.events[-1][3] - 94.2) > 1e-9:
        f.append(f"variant B close below stop must exit at the next open: {tr and (tr.exit_reason, tr.exit_t)}")
    # variant B: disaster stop (stop - 1 ATR = 93) hit intraday
    a5 = {k: v.copy() for k, v in a.items()}
    a5["atr14"][:] = 2.0
    a5["Low"][10] = 92.0
    tr = simulate_trade(Signal("Z", 5, "M2", "open", 0.0, 95.0, 3, 1.0, True), a5, "B", None, "etf")
    if tr is None or tr.exit_reason != "disaster stop" or abs(tr.events[-1][3] - 93.0) > 1e-9:
        f.append(f"variant B disaster stop must fill at stop - 1 ATR: {tr and (tr.exit_reason, tr.events[-1])}")
    # gap below the stop fills at the open (worse than the stop)
    a6 = {k: v.copy() for k, v in a.items()}
    a6["Open"][10], a6["Low"][10] = 90.0, 89.5
    tr = simulate_trade(Signal("Z", 5, "M2", "open", 0.0, 95.0, 3, 1.0, True), a6, "A", None, "etf")
    if tr is None or abs(tr.events[-1][3] - 90.0) > 1e-9:
        f.append("a gap below the stop must fill at the open, not the stop")
    # entry bar: buy-stop filled intraday and the stop touched the same bar -> stopped (worse)
    a7 = {k: v.copy() for k, v in a.items()}
    a7["High"][6], a7["Low"][6] = 102.0, 94.0
    tr = simulate_trade(Signal("Z", 5, "M0", "stop", 101.0, 95.0, 3, 1.0, True), a7, "A", None, "etf")
    if tr is None or tr.exit_t != 6 or tr.exit_reason != "stop":
        f.append("ambiguous entry bar must assume the stop was hit")
    # ladder: steady rise -> trims of 25% and fractions sum to 1
    up = np.linspace(100, 160, 60)
    dfu = _bars(up, np.full(60, 1e6), band=0.002)
    au = _arr(dfu)
    tr = simulate_trade(Signal("U", 5, "M2", "open", 0.0, float(up[5]) - 2.0, 3, 1.0, True), au, "A", None, "etf")
    tot = sum(e[2] for e in tr.events if e[1] != "entry")
    trims = [e for e in tr.events if e[1] == "trim"]
    if abs(tot - 1.0) > 1e-9 or len(trims) != 3 or any(abs(e[2] - 0.25) > 1e-9 for e in trims):
        f.append(f"ladder: expected 3 trims of 25% and fractions summing to 1, got {len(trims)} / {tot}")
    # R accounting on a known path: entry 100, stop 95, exit at 110 -> +2R minus costs
    a8 = {k: v.copy() for k, v in a.items()}
    a8["Open"][6] = 100.0
    a8["Close"][8] = 94.0
    a8["Open"][9] = 110.0
    tr = simulate_trade(Signal("Z", 5, "M2", "open", 0.0, 95.0, 3, 1.0, True), a8, "B", None, "etf")
    exp_r = (110.0 - 100.0 - (100.0 + 110.0) * 3e-4) / 5.0
    if tr is None or abs(tr.r_net - exp_r) > 1e-9:
        f.append(f"R accounting: expected {exp_r:.4f}, got {tr and tr.r_net}")

    # 4. portfolio constraints on random walks
    ohl = {f"S{i}": _walk(100 + i, n=700, drift=0.0007) for i in range(10)}
    ohl["SPY"] = _walk(99, n=700, drift=0.0004)
    sector_of = {tk: ("XLK" if i % 2 else "XLF") for i, tk in enumerate(sorted(ohl))}
    res = run(ohl, ["SPY"], [k for k in ohl if k != "SPY"], sector_of, verbose=False)
    for v in VARIANTS:
        last = {}
        for tr in sorted(res["trades"][v], key=lambda z: (z.ticker, z.setup, z.entry_t)):
            k2 = (tr.ticker, tr.setup)
            if k2 in last and tr.entry_t <= last[k2]:
                f.append(f"overlapping trades in {k2} (variant {v}): duplicates inflate the statistics")
                break
            last[k2] = tr.exit_t
        p = run_portfolio(res["trades"][v], res["unfilled"], res["data"], res["cal"], sector_of)
        if p["heat_max_pct"] > HEAT_CAP_PCT + 0.6:   # stops only tighten; marks can't add heat beyond entry risk
            f.append(f"heat {p['heat_max_pct']}% exceeds the {HEAT_CAP_PCT}% cap")
        held = {}
        for tr, sh in p["taken"]:
            for d in range(tr.entry_t, tr.exit_t):          # held at the close
                day = res["data"][tr.ticker]["index"][d]
                held.setdefault(day, []).append(tr)
        if any(len(v2) > MAX_POSITIONS for v2 in held.values()):
            f.append("more than 4 positions held at once")
        if any(max(pd.Series([sector_of[t.ticker] for t in v2]).value_counts()) > MAX_PER_SECTOR
               for v2 in held.values()):
            f.append("more than 2 positions in one sector")
        if (p["equity"] <= 0).any():
            f.append("equity went to zero or below")
    # 4b. hand-built day: 8 filled orders on one day across 3 sectors. Checks
    #     max positions, the sector cap, the cash limit and a (tightened) heat cap.
    m = 40
    pdata, trs, sec = {}, [], {}
    cal = pd.bdate_range("2020-01-01", periods=m)
    for i in range(8):
        tk = f"P{i}"
        sec[tk] = ("XLK", "XLF", "XLE")[i % 3]
        pdata[tk] = {"index": cal, "close_cal": pd.Series(100.0, index=cal)}
        tr = Trade(tk, "M2", "A", 4, 5, 100.0, 99.0 - i * 0.1, 3, 1.0, "etf")   # tight stops -> big size
        tr.events = [(5, "entry", 1.0, 100.0, 3.0), (30, "exit", 1.0, 100.0, 3.0)]
        tr.stops = [(5, tr.stop0)]
        tr.exit_t, tr.r_net = 30, 0.0
        trs.append(tr)
    if True:
        p = run_portfolio(trs, [], pdata, cal, sec)
        if p["trades_taken"] > MAX_POSITIONS:
            f.append(f"took {p['trades_taken']} positions on one day (max {MAX_POSITIONS})")
        secs = pd.Series([sec[tr.ticker] for tr, sh in p["taken"]]).value_counts()
        if len(secs) and secs.max() > MAX_PER_SECTOR:
            f.append("sector cap not enforced on a crowded day")
        notional = sum(sh * tr.entry for tr, sh in p["taken"])
        if notional > START_EQUITY * 1.0001:
            f.append(f"bought ${notional:,.0f} with ${START_EQUITY:,.0f}: cash limit not enforced")
        # wide stops (small notional) across 4 sectors: only the position cap can bind
        wide, sec4 = [], {}
        for i, tr in enumerate(trs):
            w2 = Trade(tr.ticker, "M2", "A", 4, 5, 100.0, 50.0, 3, 1.0, "etf")
            w2.events, w2.stops, w2.exit_t, w2.r_net = tr.events, [(5, 50.0)], 30, 0.0
            wide.append(w2)
            sec4[tr.ticker] = ("XLK", "XLF", "XLE", "XLV")[i % 4]
        pw = run_portfolio(wide, [], pdata, cal, sec4, heat_cap_pct=100.0)   # isolate the position cap
        if pw["trades_taken"] != MAX_POSITIONS:
            f.append(f"wide-stop day took {pw['trades_taken']} positions, expected exactly {MAX_POSITIONS}")
        p2 = run_portfolio(trs, [], pdata, cal, sec, heat_cap_pct=0.5)
        if p2["heat_max_pct"] > 0.5 + 1e-6 or p2["trades_taken"] == 0:
            f.append(f"heat {p2['heat_max_pct']}% vs a 0.5% cap ({p2['trades_taken']} taken)")
    # 4c. rotation leg = Money Flow's default RRG (rotation_math v3), checked by hand
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2015-01-01", periods=400)
    closes = {s: pd.Series(50 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 400))), index=idx) for s in SECTOR_ETFS}
    q = rotation_proxy(closes)
    perf = {s: {k: (closes[s].iloc[-1] / closes[s].iloc[-1 - k] - 1) * 100 for k in (126, 252)} for s in closes}
    bm = {k: float(np.mean([perf[s][k] for s in perf])) for k in (126, 252)}
    for s in closes:
        r_ = (1 + perf[s][252] / 100) / (1 + bm[252] / 100) * 100
        m_ = (1 + perf[s][126] / 100) / (1 + bm[126] / 100) * 100 / r_ * 100
        exp = ("Leading" if m_ >= 100 else "Weakening") if r_ >= 100 else ("Improving" if m_ >= 100 else "Lagging")
        if q[s].iloc[-1] != exp:
            f.append(f"rotation quadrant for {s} is {q[s].iloc[-1]}, rotation_math formula gives {exp}")
            break
    # 5. deflated Sharpe behaves
    a_ = deflated_sharpe(0.10, 1000, 0.0, 3.0, 0.001, 10)
    b_ = deflated_sharpe(0.10, 1000, 0.0, 3.0, 0.001, 1000)
    c_ = deflated_sharpe(0.05, 1000, 0.0, 3.0, 0.001, 10)
    if not (a_ > b_ and a_ > c_ and 0 <= b_ <= 1):
        f.append(f"deflated Sharpe ordering wrong: {a_}, {b_}, {c_}")
    # 6. streak rule inside the portfolio: three losses cut size to 1%
    st = trade_stats([-1, -1, -1, 2, 0.1, -1])
    if st["max_consec_losses"] != 3 or st["n"] != 6:
        f.append(f"trade_stats streak/scratch handling wrong: {st}")
    return {"ok": not f, "failures": f, "detector_fires_checked": fires}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        r = selftest()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 1)
    sys.exit(main())
