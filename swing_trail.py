"""
swing_trail.py  (v1 — September 2026)
─────────────────────────────────────
Which moving average trails the position -- and WHY, from the stock's own data.

The procedure allows 10 EMA (aggressive) or 20 EMA (patient) on Method 2
trades. The desk default is aggressive (10 EMA). But "aggressive" is only
right when the stock actually RESPECTS the 10 EMA during its advances; a
name that dips through the 10 and recovers every week will stop you out of
a working trend three times before it fails. So the guidance is measured:

    during the stock's most recent advance (bars where the 20 EMA was rising),
    what fraction of closes sat BELOW the 10 EMA?  below the 20 EMA?

Low violation rate on the 10 -> it respects it -> trail the 10.
High violation rate on the 10 but low on the 20 -> trail the 20.
High on both -> it does not trend cleanly on this timeframe; the setup is
suspect and the card says so.

Setup-specific rules from the procedure override the data read:
    M1 VCP              -> 50-day SMA
    M2c Momentum Burst  -> NO trail (exit day 3-5 or first close < 5 EMA)
    M2b Parabolic Short -> cover at 10 EMA, then 20 EMA
    M2b Failed-BO Short -> cover at base low

One legitimate switch, stated once: after the 2R trim, aggressive -> patient
is allowed (you are protecting a runner, not a stop). Patient -> aggressive
is never recommended mid-trade; that is tightening dressed up as strategy.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

DEFAULT = "10 EMA"
RESPECT_THRESHOLD_10 = 0.20     # > 20% of closes below the 10 EMA during the run = does not respect it
RESPECT_THRESHOLD_20 = 0.15
SLOW_ADR_PCT = 4.0              # below this the 10 EMA sits inside daily noise
LOOKBACK = 60


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def respect_stats(df: pd.DataFrame, lookback: int = LOOKBACK) -> Optional[dict]:
    """Violation rates of the 10/20 EMA during the last advance (20 EMA rising)."""
    if df is None or len(df) < lookback + 25:
        return None
    c = df["Close"]
    e10, e20 = _ema(c, 10), _ema(c, 20)
    rising = (e20 > e20.shift(3)).tail(lookback)
    run = rising[rising].index
    if len(run) < 15:
        return {"bars_in_advance": int(len(run)), "usable": False}
    below10 = float((c.loc[run] < e10.loc[run]).mean())
    below20 = float((c.loc[run] < e20.loc[run]).mean())
    return {"bars_in_advance": int(len(run)), "usable": True,
            "pct_below_10ema": round(below10, 3), "pct_below_20ema": round(below20, 3)}


def trail_guidance(setup: str, df: Optional[pd.DataFrame] = None, adr_pct: Optional[float] = None,
                   trims_done: int = 0) -> dict:
    """
    Returns {"trail", "default", "recommended", "why", "stats", "switch_note"}.
    `trail` is what goes on the card. `recommended` may differ from the
    desk default -- when it does, the card shows both and the reason.
    """
    out = {"default": DEFAULT, "stats": None, "switch_note": None}

    fixed = {
        "M1 VCP": ("50 SMA", "Method 1 trails the 50-day; a VCP leader is a multi-week hold and the 10 EMA would shake it out."),
        "M2c Burst": ("none — exit day 3-5 or first close < 5 EMA", "Burst trades are not trend trades. No trail by rule."),
        "M2b Parabolic Short": ("cover at 10 EMA, then 20 EMA", "Parabolic reversal targets are the EMAs themselves, not a trail."),
        "M2b Failed-BO Short": ("cover at base low", "Failed-breakout target is the base low; stop above the failed high."),
    }
    if setup in fixed:
        t, why = fixed[setup]
        return dict(out, trail=t, recommended=t, why=why)

    # Method 2 Breakout / EP: data decides between aggressive and patient
    stats = respect_stats(df) if df is not None else None
    out["stats"] = stats
    reasons = []
    rec = DEFAULT
    if adr_pct is not None and adr_pct < SLOW_ADR_PCT:
        rec = "20 EMA"
        reasons.append(f"ADR {adr_pct:.1f}% < {SLOW_ADR_PCT}%: the 10 EMA sits inside normal daily noise on a mover this slow")
    if stats and stats.get("usable"):
        b10, b20 = stats["pct_below_10ema"], stats["pct_below_20ema"]
        if b10 > RESPECT_THRESHOLD_10 and b20 <= RESPECT_THRESHOLD_20:
            rec = "20 EMA"
            reasons.append(f"during its last advance it closed below the 10 EMA {b10:.0%} of the time but below the 20 only {b20:.0%}: it respects the 20, not the 10")
        elif b10 > RESPECT_THRESHOLD_10 and b20 > RESPECT_THRESHOLD_20:
            rec = "20 EMA"
            reasons.append(f"closed below the 10 EMA {b10:.0%} and the 20 EMA {b20:.0%} of its advance — it does not trend cleanly on the daily; treat the setup as suspect and expect the trail to fire early")
        else:
            reasons.append(f"respected the 10 EMA during its last advance (below it only {b10:.0%} of bars) — aggressive trail is earned")
    elif df is not None:
        reasons.append("not enough of a recent advance to measure EMA respect; default applies")

    if trims_done >= 1 and rec == DEFAULT:
        out["switch_note"] = ("First ladder trim is done: switching the remainder to the 20 EMA is the one "
                              "legitimate mid-trade loosening — it protects a runner, it does not rescue a stop.")

    why = "; ".join(reasons) if reasons else "desk default — aggressive"
    return dict(out, trail=rec, recommended=rec, why=why)


def selftest() -> dict:
    import numpy as np
    f = []
    idx = pd.bdate_range("2026-01-01", periods=140)
    # clean trend: never dips below 10 EMA
    clean = pd.Series(np.linspace(50, 90, 140), index=idx)
    df_clean = pd.DataFrame({"Close": clean, "High": clean * 1.01, "Low": clean * 0.99})
    g = trail_guidance("M2 Breakout", df_clean, adr_pct=5.0)
    if g["trail"] != "10 EMA":
        f.append(f"clean trend should trail 10 EMA: {g}")
    # choppy up-trend: weekly dips through the 10 but holds the 20
    rng = np.random.default_rng(3)
    base = np.linspace(50, 80, 140)
    wobble = 2.2 * np.sin(np.arange(140) / 2.2) + rng.normal(0, 0.3, 140)
    ch = pd.Series(base + wobble, index=idx)
    df_ch = pd.DataFrame({"Close": ch, "High": ch * 1.01, "Low": ch * 0.99})
    g2 = trail_guidance("M2 Breakout", df_ch, adr_pct=5.0)
    if g2["trail"] != "20 EMA":
        f.append(f"choppy trend should recommend 20 EMA: {g2}")
    if trail_guidance("M2 Breakout", df_clean, adr_pct=2.5)["trail"] != "20 EMA":
        f.append("slow ADR should push to 20 EMA")
    if trail_guidance("M1 VCP")["trail"] != "50 SMA":
        f.append("M1 must trail the 50 SMA")
    if "5 EMA" not in trail_guidance("M2c Burst")["trail"]:
        f.append("burst has no trail")
    if not trail_guidance("M2 EP", df_clean, adr_pct=6.0, trims_done=1)["switch_note"]:
        f.append("post-trim switch note missing")
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2))
