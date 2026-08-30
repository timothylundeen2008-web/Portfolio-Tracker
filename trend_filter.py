"""
trend_filter.py  (v1 — August 2026)
───────────────────────────────────
The gold momentum gate, generalised to every sleeve.

WHY
───
regime_classifier._gold_trend_ok() already gates GLD: no tactical add
unless gold closes above a RISING 200-day. That logic is sound and it is
applied to exactly one ticker. Every other sleeve can be bought at full
weight while in a confirmed downtrend.

This module extends the same test universally. It is the Faber-style
tactical overlay, and the important thing about it is HOW it works: it does
not capture more upside. It avoids the worst drawdowns, and the compounding
benefit comes almost entirely from that. Avoiding a -50% year is worth more
than capturing an extra +10% year, because recovering from -50% requires
+100%.

THE RISING REQUIREMENT
──────────────────────
Price above a FALLING average is not confirmation — it is a bounce inside a
downtrend, which is the single most common way a trend filter gets
whipsawed. Both conditions are required, matching the existing gold gate
rather than inventing a looser standard for everything else.

FAIL DIRECTION
──────────────
Fails CLOSED, following _gold_trend_ok()'s own precedent: any data problem
returns False (no data -> no full weight). A trend filter that defaults to
"pass" when the feed breaks is not a filter.

DELIBERATELY NOT A BINARY
─────────────────────────
A hard on/off at the 200-day generates severe whipsaw: price oscillating
around the average produces repeated full-in/full-out swings, and the
transaction costs plus tax drag can exceed the drawdown protection. So the
gate returns a SCALAR (1.0 / 0.6 / 0.3) rather than 1 or 0. Partial
positions through ambiguous zones is what makes this survivable in practice.
"""

from __future__ import annotations

from typing import Callable, Optional

import pandas as pd

MA_DAYS = 200
SLOPE_LOOKBACK = 21          # ~1 month, matching the Trend Template's own test

# Scalars applied to a sleeve's weight. Not binary — see module docstring.
SCALAR_CONFIRMED = 1.00      # above a rising MA
SCALAR_AMBIGUOUS = 0.60      # above a falling MA, or just below a rising one
SCALAR_DOWNTREND = 0.30      # below a falling MA

# Sleeves exempt from trend gating. Cash and floating-rate instruments have
# no meaningful trend — gating them would be nonsense, and they are where
# gated weight gets PARKED, so gating them would create a circular problem.
EXEMPT = {"SGOV", "USFR", "BIL", "SHV"}


def assess_ticker(prices: pd.Series) -> dict:
    """
    Trend state for one ticker. Never raises.

    Returns state, scalar, and the numbers behind them so the decision is
    auditable rather than a bare multiplier.
    """
    out = {"state": "UNKNOWN", "scalar": SCALAR_DOWNTREND, "price": None,
           "ma": None, "rising": None, "gap_pct": None, "available": False,
           "detail": "Insufficient data — failing closed."}
    try:
        s = pd.Series(prices).astype(float).dropna()
        if len(s) < MA_DAYS + SLOPE_LOOKBACK:
            out["detail"] = (f"Need {MA_DAYS + SLOPE_LOOKBACK} sessions, "
                            f"have {len(s)}. Failing closed.")
            return out

        ma_series = s.rolling(MA_DAYS).mean().dropna()
        ma_now = float(ma_series.iloc[-1])
        ma_prior = float(ma_series.iloc[-1 - SLOPE_LOOKBACK])
        px = float(s.iloc[-1])
        rising = ma_now > ma_prior
        gap = (px / ma_now - 1) * 100

        out.update(price=round(px, 2), ma=round(ma_now, 2), rising=rising,
                   gap_pct=round(gap, 2), available=True)

        if gap > 0 and rising:
            out.update(state="CONFIRMED UPTREND", scalar=SCALAR_CONFIRMED)
            out["detail"] = (f"{gap:+.1f}% above a RISING {MA_DAYS}-day "
                            f"({ma_now:,.2f}). Full weight.")
        elif gap > 0 and not rising:
            out.update(state="ABOVE FALLING MA", scalar=SCALAR_AMBIGUOUS)
            out["detail"] = (f"{gap:+.1f}% above a FALLING {MA_DAYS}-day "
                            f"({ma_now:,.2f}) — a bounce inside a downtrend, "
                            f"not confirmation. Partial weight.")
        elif gap > -3 and rising:
            out.update(state="NEAR RISING MA", scalar=SCALAR_AMBIGUOUS)
            out["detail"] = (f"{gap:+.1f}% below a RISING {MA_DAYS}-day — a "
                            f"pullback within an uptrend. Partial weight.")
        else:
            out.update(state="DOWNTREND", scalar=SCALAR_DOWNTREND)
            out["detail"] = (f"{gap:+.1f}% below a "
                            f"{'rising' if rising else 'falling'} "
                            f"{MA_DAYS}-day ({ma_now:,.2f}). Reduced weight.")
        return out
    except Exception as e:
        out["detail"] = f"Trend check failed: {e}. Failing closed."
        return out


def assess_universe(fetch_prices: Callable, tickers: list[str],
                    period: str = "2y") -> dict:
    """Trend state for every ticker."""
    out = {"states": {}, "missing": [], "detail": ""}
    for tk in tickers:
        if tk in EXEMPT:
            out["states"][tk] = {
                "state": "EXEMPT", "scalar": 1.0, "available": True,
                "detail": "Cash/floating-rate — no meaningful trend to gate, "
                         "and this is where gated weight gets parked."}
            continue
        try:
            px = fetch_prices(tk, period)
            px = pd.Series(px.squeeze() if hasattr(px, "squeeze") else px)
            out["states"][tk] = assess_ticker(px)
            if not out["states"][tk]["available"]:
                out["missing"].append(tk)
        except Exception as e:
            out["states"][tk] = assess_ticker(pd.Series(dtype=float))
            out["missing"].append(f"{tk} ({type(e).__name__})")

    confirmed = [t for t, s in out["states"].items()
                 if s["state"] == "CONFIRMED UPTREND"]
    down = [t for t, s in out["states"].items() if s["state"] == "DOWNTREND"]
    out["detail"] = (f"{len(confirmed)} in confirmed uptrends, {len(down)} in "
                     f"downtrends, of {len(tickers)} sleeves.")
    if down:
        out["detail"] += f" Reduced: {', '.join(down)}."
    return out


def apply_gates(weights: dict, trends: dict, park_in: str = "SGOV") -> dict:
    """
    Apply trend scalars, parking the freed weight in cash.

    Parking matters. Without it, gating simply shrinks the book below 100%
    invested — which converts a trend filter into an unintended and
    undisclosed market-timing call. The freed weight goes somewhere explicit.
    """
    gated, freed = {}, 0.0
    for tk, w in weights.items():
        sc = trends.get("states", {}).get(tk, {}).get("scalar", 1.0)
        gated[tk] = round(w * sc, 2)
        freed += w - gated[tk]

    if freed > 0:
        gated[park_in] = round(gated.get(park_in, 0) + freed, 2)

    total = sum(gated.values())
    if abs(total - 100) > 0.01 and total > 0:
        gated = {t: round(w / total * 100, 2) for t, w in gated.items()}
    return gated


def render(st, trends: dict, weights: dict = None):
    st.markdown("### Trend Filter")
    st.caption(
        "The gold momentum gate, applied to every sleeve. Price above a "
        "RISING 200-day earns full weight; above a FALLING one earns partial "
        "— a bounce inside a downtrend is not confirmation. Scalars rather "
        "than on/off, because a hard binary at the average generates whipsaw "
        "whose costs can exceed the drawdown protection."
    )
    if not trends.get("states"):
        st.error("No trend data.")
        return
    st.caption(trends["detail"])

    colour = {"CONFIRMED UPTREND": "#16a34a", "NEAR RISING MA": "#d97706",
              "ABOVE FALLING MA": "#d97706", "DOWNTREND": "#dc2626",
              "EXEMPT": "#6b7280", "UNKNOWN": "#6b7280"}
    for tk, s in sorted(trends["states"].items(),
                        key=lambda kv: -kv[1].get("scalar", 0)):
        c = colour.get(s["state"], "#6b7280")
        st.markdown(
            f"<span style='color:{c};'>●</span> <b>{tk}</b> "
            f"<span style='color:{c};'>{s['state']}</span> "
            f"<span style='color:#9ca3af;'>× {s.get('scalar', 1.0):.2f}</span>",
            unsafe_allow_html=True)
        st.caption(s.get("detail", ""))

    if weights:
        gated = apply_gates(weights, trends)
        st.markdown("#### Weight impact")
        for tk in sorted(weights, key=lambda t: -(abs(gated.get(t, 0) - weights[t]))):
            d = gated.get(tk, 0) - weights[tk]
            if abs(d) < 0.1:
                continue
            c = "#16a34a" if d > 0 else "#dc2626"
            st.markdown(f"<b>{tk}</b> {weights[tk]:.1f}% → {gated[tk]:.1f}% "
                        f"<span style='color:{c};'>({d:+.1f})</span>",
                        unsafe_allow_html=True)


def selftest() -> dict:
    import numpy as np
    failures = []
    idx = pd.bdate_range("2023-01-01", periods=400)

    up = pd.Series(np.linspace(100, 200, 400), index=idx)
    r = assess_ticker(up)
    if r["state"] != "CONFIRMED UPTREND" or r["scalar"] != 1.0:
        failures.append(f"uptrend got {r['state']}")

    down = pd.Series(np.linspace(200, 100, 400), index=idx)
    r = assess_ticker(down)
    if r["state"] != "DOWNTREND" or r["scalar"] != SCALAR_DOWNTREND:
        failures.append(f"downtrend got {r['state']}")

    # Bounce inside a downtrend: long decline, sharp recent rally that lifts
    # price above a still-FALLING average. Must NOT earn full weight.
    bounce = pd.Series(list(np.linspace(200, 100, 360))
                       + list(np.linspace(100, 145, 40)), index=idx)
    r = assess_ticker(bounce)
    if r["scalar"] == SCALAR_CONFIRMED:
        failures.append(f"bounce in downtrend earned full weight: {r['state']}")

    # Fail closed on short history
    r = assess_ticker(pd.Series(np.linspace(100, 110, 50)))
    if r["available"] or r["scalar"] != SCALAR_DOWNTREND:
        failures.append("short history did not fail closed")

    # Gating must preserve 100% and park freed weight
    def fake(tk, period="2y"):
        return {"A": up, "B": down, "SGOV": up}[tk]
    tr = assess_universe(fake, ["A", "B", "SGOV"])
    gated = apply_gates({"A": 50, "B": 40, "SGOV": 10}, tr)
    if abs(sum(gated.values()) - 100) > 0.5:
        failures.append(f"gated weights sum to {sum(gated.values())}")
    if gated["SGOV"] <= 10:
        failures.append("freed weight was not parked in cash")
    if gated["B"] >= 40:
        failures.append("downtrending sleeve was not reduced")

    return {"ok": not failures, "failures": failures,
            "gated_example": gated}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2, default=str))
