"""
swing_exits.py  (v1 — September 2026)
─────────────────────────────────────
Open-position management for the swing book. RECOMMENDS; never acts.

exit_rules.py governs the All-Weather book (ATR trail, falling 200-day).
Swings follow the procedure's own rules, which differ: the trail is the
card's EMA, the ladder is 2R/4R/8R, and bursts have a day count. So this
module exists rather than bending exit_rules.py to a second job.

The four triggers, run IN ORDER, EACH reported -- the order matters and the
brief says so. Any one is sufficient:

    1. STRUCTURAL   close through the stop           -> EXIT (STOP_HIT)
    2. THESIS       regime hostile to the side, or
                    sector rotated against it        -> EXIT regardless of P&L
    3. TREND        close below a FALLING trail MA   -> EXIT
                    close below a RISING trail MA    -> TIGHTEN (never loosen)
    4. LADDER       R >= next untrimmed rung         -> TRIM 25% of original size
    (bursts)        day >= 5 or close < 5 EMA        -> EXIT (M2c only)

Every recommendation carries pending_confirmation=True. The journal only
changes when you confirm from the tab or chat.

Not wired yet (stated, not hidden): the Danger Composite >= 7 "sell into
strength ahead of the ladder" override. exit_rules.py computes its pieces
for the AW book; porting it to per-position swing data is Phase 4 work.
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from swing_desk import REGIME_DIRECTION

LADDER = (2.0, 4.0, 8.0)
BURST_MAX_DAYS = 5
LONG_HOSTILE_QUADS = {"Weakening", "Lagging"}
SHORT_HOSTILE_QUADS = {"Improving", "Leading"}


def _ma(close: pd.Series, spec: str) -> Optional[pd.Series]:
    m = re.search(r"(\d+)\s*(EMA|SMA)", spec or "", re.I)
    if not m:
        return None
    n, kind = int(m.group(1)), m.group(2).upper()
    return close.ewm(span=n, adjust=False).mean() if kind == "EMA" else close.rolling(n).mean()


def manage_one(ticker: str, pos: dict, df: pd.DataFrame, regime_key: str,
               sector_quadrant: Optional[str] = None, today=None) -> dict:
    """One open position -> triggers + a single recommendation."""
    side, long = pos["side"], pos["side"] == "long"
    close = float(df["Close"].iloc[-1])
    entry, stop = float(pos["avg_entry"]), float(pos["stop"])
    rps = float(pos.get("risk_per_share") or abs(entry - stop)) or 1e-9
    R = ((close - entry) if long else (entry - close)) / rps
    days_held = int(len(df.loc[df.index > pd.Timestamp(pos["entry_ts"]).tz_localize(None)]) ) \
        if pos.get("entry_ts") is not None else None

    trig = {}
    rec, why = "HOLD", []

    # 1 structural
    hit = close <= stop if long else close >= stop
    trig["structural"] = f"HIT — close {close:.2f} vs stop {stop:.2f}" if hit else f"clear ({close:.2f} vs {stop:.2f})"
    if hit:
        rec, why = "EXIT", [f"structural stop hit at {stop:.2f}; never moved, no exceptions"]

    # 2 thesis
    direction = REGIME_DIRECTION.get(regime_key, ("both", 0.5))[0]
    regime_hostile = (long and direction == "short") or ((not long) and direction == "long")
    sector_hostile = (sector_quadrant in (LONG_HOSTILE_QUADS if long else SHORT_HOSTILE_QUADS))
    if regime_hostile or sector_hostile:
        trig["thesis"] = ("regime " + regime_key + " closes the " + side + " book" if regime_hostile else
                          f"sector rotated to {sector_quadrant}")
        if rec == "HOLD":
            rec, why = "EXIT", [trig["thesis"] + " — fires regardless of P&L; 'still going up' is not a reason to hold"]
    else:
        trig["thesis"] = f"clear (regime {regime_key} permits {side}; sector {sector_quadrant or 'n/a'})"

    # 3 trend
    ma = _ma(df["Close"], pos.get("trail") or "")
    new_stop = None
    if ma is not None and ma.notna().iloc[-1]:
        mv, rising = float(ma.iloc[-1]), bool(ma.iloc[-1] > ma.iloc[-4])
        below = close < mv if long else close > mv
        if below and not rising:
            trig["trend"] = f"close {'below' if long else 'above'} a FALLING {pos['trail']} ({mv:.2f})"
            if rec == "HOLD":
                rec, why = "EXIT", [trig["trend"] + " — trend break"]
        elif below and rising:
            trig["trend"] = f"close {'below' if long else 'above'} a RISING {pos['trail']} ({mv:.2f}) — tighten only"
            tight = mv if long else mv
            if (long and tight > stop) or ((not long) and tight < stop):
                new_stop = round(tight, 2)
                if rec == "HOLD":
                    rec, why = "TIGHTEN", [f"stop to {new_stop} (the rising {pos['trail']}); below a rising MA you tighten, you do not exit"]
        else:
            trig["trend"] = f"clear (close {close:.2f} vs {pos['trail']} {mv:.2f}, {'rising' if rising else 'falling'})"
    else:
        trig["trend"] = "no trail MA (burst) or not parseable"

    # bursts: time stop / 5 EMA
    if (pos.get("setup") or "").startswith("M2c"):
        e5 = float(df["Close"].ewm(span=5, adjust=False).mean().iloc[-1])
        burst_out = (days_held is not None and days_held >= BURST_MAX_DAYS) or (close < e5 if long else close > e5)
        trig["burst"] = (f"day {days_held}/{BURST_MAX_DAYS}, close {close:.2f} vs 5 EMA {e5:.2f}"
                         + (" — EXIT" if burst_out else " — clear"))
        if burst_out and rec == "HOLD":
            rec, why = "EXIT", ["burst trade is done: exit into strength, no trailing by rule"]

    # 4 ladder
    trims = int(pos.get("trims") or 0)
    rung = LADDER[trims] if trims < len(LADDER) else None
    if rung is None:
        trig["ladder"] = "all three tranches trimmed; final 25% runs on the trail"
    elif R >= rung:
        trig["ladder"] = f"R = {R:.2f} ≥ {rung:.0f}R, tranche {trims+1} untrimmed"
        if rec == "HOLD":
            qty = round(float(pos.get("shares_taken") or pos["shares"]) * 0.25, 2)
            rec, why = "TRIM", [f"trim 25% of original size ({qty} sh) at {rung:.0f}R; ladder is 2R/4R/8R, 25% runs"]
    else:
        trig["ladder"] = f"R = {R:.2f}, next rung {rung:.0f}R at {entry + rung*rps if long else entry - rung*rps:.2f}"

    return {"ticker": ticker, "setup": pos.get("setup"), "side": side, "entry": round(entry, 2),
            "stop": stop, "current": round(close, 2), "R": round(R, 2), "days_held": days_held,
            "shares": pos["shares"], "trail": pos.get("trail"), "triggers": trig,
            "recommendation": rec, "new_stop": new_stop, "why": "; ".join(why) if why else "all four triggers clear",
            "pending_confirmation": rec != "HOLD",
            "trigger_note": None, "decline_consequence": None}


def manage(positions: dict, ohlcv: dict, regime_key: str, sector_quadrants: Optional[dict] = None) -> list[dict]:
    out = []
    for tk, pos in positions.items():
        df = ohlcv.get(tk)
        if df is None or df.empty:
            out.append({"ticker": tk, "recommendation": "NO DATA", "pending_confirmation": False,
                        "why": "no price data — the desk does not guess; check the position manually"})
            continue
        out.append(manage_one(tk, pos, df, regime_key, (sector_quadrants or {}).get(tk)))
    order = {"EXIT": 0, "TRIM": 1, "TIGHTEN": 2, "HOLD": 3, "NO DATA": 4}
    return sorted(out, key=lambda r: order.get(r["recommendation"], 9))


def selftest() -> dict:
    import numpy as np
    f = []
    idx = pd.bdate_range("2026-01-01", periods=120)
    up = pd.Series(np.linspace(50, 80, 120), index=idx)
    df = pd.DataFrame({"Close": up, "High": up * 1.01, "Low": up * 0.99, "Volume": 1e6})
    base = {"side": "long", "avg_entry": 60.0, "stop": 57.0, "risk_per_share": 3.0, "shares": 100,
            "shares_taken": 100, "trims": 0, "trail": "10 EMA", "setup": "M2 Breakout",
            "entry_ts": pd.Timestamp("2026-03-01", tz="UTC")}
    r = manage_one("AAA", base, df, "goldilocks", "Leading")
    if r["recommendation"] != "TRIM" or r["R"] < 6:
        f.append(f"6R+ untrimmed should TRIM: {r['recommendation']} R={r['R']}")
    r = manage_one("AAA", dict(base, trims=3), df, "goldilocks", "Leading")
    if r["recommendation"] != "HOLD":
        f.append("fully laddered runner should HOLD")
    r = manage_one("AAA", base, df, "growth_scare", "Leading")
    if r["recommendation"] != "EXIT" or "regime" not in r["why"]:
        f.append(f"hostile regime must EXIT via thesis: {r}")
    r = manage_one("AAA", base, df, "goldilocks", "Lagging")
    if r["recommendation"] != "EXIT":
        f.append("sector rotated to Lagging must EXIT")
    # stop hit
    dn = pd.Series(np.linspace(80, 55, 120), index=idx)
    ddf = pd.DataFrame({"Close": dn, "High": dn * 1.01, "Low": dn * 0.99, "Volume": 1e6})
    r = manage_one("AAA", base, ddf, "goldilocks", "Leading")
    if r["recommendation"] != "EXIT" or "HIT" not in r["triggers"]["structural"]:
        f.append("stop hit must EXIT")
    # short side ladder
    sp = {**base, "side": "short", "avg_entry": 80.0, "stop": 84.0, "risk_per_share": 4.0, "setup": "M2b Parabolic Short",
          "trail": "10 EMA"}
    r = manage_one("SSS", sp, ddf, "growth_scare", "Lagging")
    if r["R"] < 6 or r["recommendation"] != "TRIM":
        f.append(f"short at 6R should TRIM: {r['recommendation']} R={r['R']}")
    # burst day count
    b = dict(base, setup="M2c Burst", trail="none", entry_ts=pd.Timestamp(idx[-8], tz="UTC"))
    r = manage_one("BBB", b, df, "goldilocks", "Leading")
    if r["recommendation"] != "EXIT" or "burst" not in r["why"]:
        f.append(f"burst past day 5 must EXIT: {r}")
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2))
