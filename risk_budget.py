"""
risk_budget.py  (v1 — July 2026)
================================
Position sizing and hedge budgeting CONDITIONED ON MARKET STATE, not fixed.

WHY NOT A FIXED VOL TARGET
--------------------------
A constant target (say 12%) is better than nothing, but it is not
return-optimizing, because it ignores the two things that actually determine
how much risk you should be carrying:

  1. How CONFIDENT is the regime read?
     Sizing to conviction is the whole Druckenmiller point. A confirmed regime
     with complete data and cross-asset agreement earns a bigger book than an
     ambiguous one with a missing DFII10 momentum and a hollow score. A fixed
     target treats those two states identically, which means it is
     simultaneously too small in the clear case and too large in the murky one.

  2. What is the regime's own risk STANCE?
     Goldilocks and liquidity_crisis do not deserve the same gross exposure.

WHY NOT A FIXED HEDGE BUDGET EITHER
-----------------------------------
Protection is a PURCHASE. The return-maximizing rule for any purchase is buy
more when it is cheap and less when it is expensive. A fixed 2%-of-NAV-per-
quarter overpays badly in a high-VIX regime and underbuys in a low one — and
the low-VIX moments are precisely when you want the convexity, because that is
when a crowded unwind is cheapest to insure against.

So the budget scales INVERSELY with the price of vol:

    VIX in the bottom quartile of its own 1-year range  ->  2.00% of NAV
    2nd quartile                                        ->  1.25%
    3rd quartile                                        ->  0.50%
    top quartile                                        ->  0.00%

Zero in the top quartile is deliberate. Buying index puts after VIX has already
spiked is insuring the house while it is burning: you pay the loss twice, once
in the drawdown and once in the premium.

DISCRETE STATES, NOT CONTINUOUS FUNCTIONS
-----------------------------------------
Everything here snaps to a small number of buckets. Continuous feedback between
a signal and a position size is the fastest route to an overfitted system that
backtests beautifully and cannot be executed. Four confidence tiers, seven
regime stances, four vol quartiles. All of it loggable, all of it backtestable,
none of it a curve to fit.

WORKED EXAMPLE — 2026-07-29
---------------------------
    regime      transition_ambiguous  (short real +0.10%, inside the band)
    confidence  LOW    — hollow score (0 of 4 top-weight points), DFII10
                         momentum present but the primary gauge is in-band,
                         and cross-asset inputs disagree 3-to-1
    stance      -1     (transition: neither directional bet confirmed)
    vol target  11.0 base, -1 stance, x0.80 confidence  ->  8.0%
    -> a materially smaller book than a fixed 12% would have carried into a
       Nasdaq-100 correction, arrived at by rule rather than by nerve.

    VIX ~18-19 is mid-range on a 1-year lookback that includes the Iran-war
    spikes, so it lands in Q2 or Q3 depending on the actual history -> 1.25% or
    0.50% of NAV. Either way the reading is the same: buy SOME convexity, not
    the maximum, because vol is cheap-ish rather than cheap. Pass the real
    VIX series to pin the quartile — do not assume it.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
#  Tunables
# --------------------------------------------------------------------------- #
BASE_VOL_TARGET = 11.0          # annualized %, the neutral-state anchor
VOL_TARGET_FLOOR = 6.0
VOL_TARGET_CEILING = 15.0

# Regime stance: how much annualized vol the regime itself justifies adding or
# removing from the base. Signed percentage points.
REGIME_STANCE = {
    "goldilocks":              +2.0,   # confirmed positive real + tight credit
    "hard_repression":          0.0,   # debasement trade works; own it at base
    "inflationary_repression": -1.0,   # real assets work but duration bleeds
    "transition_ambiguous":    -1.0,   # primary gauge in-band: express neither
    "neutral":                 -1.0,   # mixed signals
    "stagflation":             -2.0,   # growth rolling over
    "liquidity_crisis":        -4.0,   # credit leads equities; get small
}

# Confidence tiers -> multiplier on the stance-adjusted target.
CONFIDENCE_TIERS = [
    (75, "HIGH",     1.15),
    (50, "MODERATE", 1.00),
    (25, "LOW",      0.80),
    (0,  "DEGRADED", 0.65),
]

# Convexity budget as % of NAV, by VIX quartile within its own 1-year range.
CONVEXITY_BY_QUARTILE = {1: 2.00, 2: 1.25, 3: 0.50, 4: 0.00}

# Sizing scalar bounds. Uncapped vol-targeting levers you into a low-vol melt-up
# and is the mechanism behind most vol-target blowups.
SCALAR_MIN, SCALAR_MAX = 0.30, 1.30


# --------------------------------------------------------------------------- #
#  Confidence
# --------------------------------------------------------------------------- #
def regime_confidence(regime_key: str,
                      missing: Optional[list] = None,
                      top_weight_earned: int = 0,
                      top_weight_total: int = 4,
                      cross_asset_agreement: Optional[float] = None,
                      drivers: Optional[list] = None) -> dict:
    """
    Score 0-100 for how much the regime read can be trusted.

    Inputs mirror what the existing stack already produces:
        missing                 repression_score()["missing"]
        top_weight_earned/total score_meta.band_with_context()
        cross_asset_agreement   cross_asset.divergence()["agreement_pct"]
        drivers                 classify_regime()["drivers"] — scanned for the
                                degraded-data warning FIX 5 emits

    Deliberately harsh. The failure mode this guards against is a confident
    tilt built on an incomplete read, which is how the system got to a
    growth-additive overlay on a -2.19% Dow day.
    """
    score = 100.0
    reasons = []

    # Data completeness — each missing component is a real hole.
    n_missing = len(missing or [])
    if n_missing:
        pen = min(40.0, 12.0 * n_missing)
        score -= pen
        reasons.append(f"-{pen:.0f}: {n_missing} score component(s) missing "
                       f"({', '.join((missing or [])[:4])})")

    # Degraded-classification warnings surfaced by the classifier itself.
    deg = [d for d in (drivers or []) if "⚠" in str(d) or "degraded" in str(d).lower()
           or "unavailable" in str(d).lower()]
    if deg:
        score -= 15.0
        reasons.append(f"-15: classifier flagged degradation ({deg[0]})")

    # Hollow score — the heaviest penalty, because the band label overstates
    # the read when none of the top-weight gauges fired.
    if top_weight_total > 0:
        share = top_weight_earned / top_weight_total
        if share == 0:
            score -= 30.0
            reasons.append(f"-30: hollow score, 0 of {top_weight_total} "
                           f"top-weight points earned")
        elif share < 0.5:
            score -= 15.0
            reasons.append(f"-15: only {top_weight_earned} of "
                           f"{top_weight_total} top-weight points earned")

    # The transition state is inherently low-confidence by definition.
    if regime_key == "transition_ambiguous":
        score -= 15.0
        reasons.append("-15: short real policy rate inside the transition band")
    elif regime_key == "neutral":
        score -= 10.0
        reasons.append("-10: regime is neutral / mixed")

    # Cross-asset agreement, when available.
    if cross_asset_agreement is not None:
        if cross_asset_agreement < 60:
            score -= 15.0
            reasons.append(f"-15: cross-asset agreement only "
                           f"{cross_asset_agreement:.0f}%")
        elif cross_asset_agreement >= 90:
            score += 5.0
            reasons.append(f"+5: cross-asset agreement "
                           f"{cross_asset_agreement:.0f}%")

    score = max(0.0, min(100.0, score))
    tier, mult = "DEGRADED", 0.65
    for threshold, name, m in CONFIDENCE_TIERS:
        if score >= threshold:
            tier, mult = name, m
            break

    return {"score": round(score, 1), "tier": tier, "multiplier": mult,
            "reasons": reasons}


# --------------------------------------------------------------------------- #
#  Vol target
# --------------------------------------------------------------------------- #
def vol_target(regime_key: str, confidence: dict,
               base: float = BASE_VOL_TARGET) -> dict:
    """Annualized vol target, conditioned on regime stance and confidence."""
    stance = REGIME_STANCE.get(regime_key, -1.0)
    stance_adj = base + stance
    target = stance_adj * confidence["multiplier"]
    target = max(VOL_TARGET_FLOOR, min(VOL_TARGET_CEILING, target))
    return {
        "regime": regime_key,
        "base": base,
        "stance_adj_pp": stance,
        "after_stance": round(stance_adj, 2),
        "confidence_tier": confidence["tier"],
        "confidence_multiplier": confidence["multiplier"],
        "target_vol_pct": round(target, 2),
        "detail": (f"{base:.1f}% base {stance:+.1f}pp stance "
                   f"({regime_key}) x{confidence['multiplier']:.2f} "
                   f"{confidence['tier']} confidence = "
                   f"{target:.1f}% annualized vol target"),
    }


def realized_vol(returns: pd.Series, window: int = 20,
                 periods_per_year: int = 252) -> Optional[float]:
    """Annualized realized vol from a daily return series. None when short."""
    try:
        r = pd.Series(returns).astype(float).dropna()
        if len(r) < window:
            return None
        return float(r.iloc[-window:].std(ddof=1) * np.sqrt(periods_per_year) * 100.0)
    except Exception:
        return None


def sizing_scalar(target_pct: float, realized_pct: Optional[float]) -> dict:
    """
    The multiplier to apply to risk-sleeve weights.

    Returns scalar 1.0 with available=False when realized vol is unknown —
    NOT a guess. An unknown denominator must not silently resize the book.
    """
    if realized_pct is None or realized_pct <= 0:
        return {"available": False, "scalar": 1.0, "realized_vol_pct": None,
                "detail": "Realized vol unavailable — scalar held at 1.00. "
                          "Weights unchanged; this is a degraded state, not a "
                          "neutral reading."}
    raw = target_pct / realized_pct
    capped = max(SCALAR_MIN, min(SCALAR_MAX, raw))
    return {
        "available": True, "scalar": round(capped, 3),
        "raw_scalar": round(raw, 3),
        "realized_vol_pct": round(realized_pct, 2),
        "was_capped": abs(capped - raw) > 1e-9,
        "detail": (f"target {target_pct:.1f}% / realized {realized_pct:.1f}% = "
                   f"{raw:.2f}, applied {capped:.2f} "
                   f"(bounds {SCALAR_MIN:.2f}-{SCALAR_MAX:.2f})"),
    }


# --------------------------------------------------------------------------- #
#  Convexity budget
# --------------------------------------------------------------------------- #
def vol_quartile(vix_now: Optional[float],
                 vix_history: Optional[pd.Series] = None,
                 lookback: int = 252) -> dict:
    """Which quartile of its own 1-year range VIX currently sits in."""
    out = {"available": False, "quartile": None, "pct_rank": None,
           "vix": vix_now, "detail": ""}
    if vix_now is None:
        out["detail"] = "VIX unavailable."
        return out
    try:
        h = pd.Series(vix_history).astype(float).dropna() if vix_history is not None \
            else pd.Series(dtype=float)
        if len(h) < 60:
            out["detail"] = (f"VIX history too short ({len(h)} obs, need 60) — "
                             f"cannot rank. Level is {vix_now:.1f}.")
            return out
        h = h.iloc[-lookback:]
        rank = float((h <= vix_now).mean()) * 100.0
        q = 1 if rank < 25 else 2 if rank < 50 else 3 if rank < 75 else 4
        out.update(available=True, quartile=q, pct_rank=round(rank, 1))
        out["detail"] = (f"VIX {vix_now:.1f} is the {rank:.0f}th percentile of "
                         f"its trailing {len(h)}-session range "
                         f"({h.min():.1f}-{h.max():.1f}) -> Q{q}")
        return out
    except Exception as e:
        out["detail"] = f"VIX ranking failed: {e}"
        return out


def convexity_budget(vq: dict, regime_key: str = "",
                     nav: float | None = None) -> dict:
    """
    Hedge spend as % of NAV, priced off vol rather than fixed.

    Two overrides:
      * liquidity_crisis   -> 0% NEW spend. Hold what you own; do not buy
                             protection into a crisis you are already in.
      * unavailable rank   -> fall back to Q2 (1.25%), the middle of the
                             schedule, and say so. Refusing to hedge because
                             a data feed is down is its own risk.
    """
    if not vq.get("available"):
        pct = CONVEXITY_BY_QUARTILE[2]
        detail = (f"Vol rank unavailable ({vq.get('detail','')}) — defaulting to "
                  f"the Q2 schedule ({pct:.2f}% of NAV). Restore VIX history to "
                  f"price this properly.")
        q = None
    elif regime_key == "liquidity_crisis":
        pct, q = 0.0, vq["quartile"]
        detail = ("Liquidity crisis: 0% NEW convexity spend. Protection is "
                  "expensive precisely because the event is underway. Hold "
                  "existing hedges and monetize into weakness rather than "
                  "adding.")
    else:
        q = vq["quartile"]
        pct = CONVEXITY_BY_QUARTILE[q]
        rationale = {
            1: "vol is in the cheapest quartile of its own year — this is the "
               "window the budget exists for",
            2: "vol is cheap-ish; buy some, not the maximum",
            3: "vol is getting expensive; token spend only",
            4: "vol is in its most expensive quartile — buying index protection "
               "here is insuring the house while it burns. Spend nothing and "
               "reduce exposure directly instead.",
        }[q]
        detail = f"{vq['detail']} -> {pct:.2f}% of NAV ({rationale})."

    out = {"pct_of_nav": pct, "quartile": q, "regime": regime_key,
           "detail": detail}
    if nav:
        out["dollar_budget"] = round(nav * pct / 100.0, 2)
    return out


# --------------------------------------------------------------------------- #
#  One-call orchestration
# --------------------------------------------------------------------------- #
def budget(regime_key: str,
           missing: Optional[list] = None,
           top_weight_earned: int = 0,
           top_weight_total: int = 4,
           drivers: Optional[list] = None,
           cross_asset_agreement: Optional[float] = None,
           portfolio_returns: Optional[pd.Series] = None,
           vix_now: Optional[float] = None,
           vix_history: Optional[pd.Series] = None,
           nav: Optional[float] = None) -> dict:
    """
    The single entry point. Everything is optional; whatever is missing
    degrades that one component and is reported, rather than raising.
    """
    conf = regime_confidence(regime_key, missing, top_weight_earned,
                             top_weight_total, cross_asset_agreement, drivers)
    vt = vol_target(regime_key, conf)
    rv = realized_vol(portfolio_returns) if portfolio_returns is not None else None
    scal = sizing_scalar(vt["target_vol_pct"], rv)
    vq = vol_quartile(vix_now, vix_history)
    cvx = convexity_budget(vq, regime_key, nav)

    return {
        "confidence": conf,
        "vol_target": vt,
        "sizing": scal,
        "vol_quartile": vq,
        "convexity": cvx,
        "summary": (
            f"{regime_key} · {conf['tier']} confidence ({conf['score']:.0f}/100) "
            f"· vol target {vt['target_vol_pct']:.1f}% "
            f"· risk scalar {scal['scalar']:.2f}"
            f"{'' if scal['available'] else ' (held, realized vol unknown)'} "
            f"· convexity {cvx['pct_of_nav']:.2f}% of NAV"
        ),
    }


def selftest() -> dict:
    """Exercise the two states that matter: today, and a clean goldilocks."""
    today = budget(
        "transition_ambiguous",
        missing=[],
        top_weight_earned=0, top_weight_total=4,
        drivers=["Short real rate +0.10% inside ±0.25% band"],
        cross_asset_agreement=25.0,
        vix_now=18.5,
        vix_history=pd.Series(np.concatenate([
            np.random.default_rng(0).normal(17, 3, 200).clip(11, 40),
            np.array([31, 28, 24, 21, 19, 18.5]),
        ])),
        nav=100_000,
    )
    clean = budget(
        "goldilocks", missing=[], top_weight_earned=4, top_weight_total=4,
        drivers=[], cross_asset_agreement=95.0, vix_now=13.0,
        vix_history=pd.Series(np.random.default_rng(1).normal(17, 3, 250).clip(11, 40)),
        nav=100_000,
    )
    failures = []
    if today["vol_target"]["target_vol_pct"] >= clean["vol_target"]["target_vol_pct"]:
        failures.append("Ambiguous regime did not get a smaller vol target "
                        "than a clean goldilocks")
    if today["confidence"]["tier"] not in ("LOW", "DEGRADED"):
        failures.append(f"Today's confidence tier was "
                        f"{today['confidence']['tier']}, expected LOW/DEGRADED")
    return {"ok": not failures, "failures": failures,
            "today": today["summary"], "clean_goldilocks": clean["summary"],
            "today_convexity": today["convexity"]["detail"]}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2, default=str))
