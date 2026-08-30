"""
relative_strength.py  (v1 — August 2026)
────────────────────────────────────────
Momentum ranking across the sleeve universe.

WHY THIS IS THE HIGHEST-VALUE ADDITION
──────────────────────────────────────
Momentum is the most robustly documented anomaly in markets — it survives
out-of-sample, across asset classes, across decades, and across countries,
which is more than can be said for most factors.

The Rotation Dashboard already computes RRG quadrants. NOTHING feeds that
into All-Weather's portfolio construction. The sleeves are held at fixed
base weights plus fixed regime overlays, with no mechanism to overweight
what is working and underweight what is not. This module closes that gap.

METHODOLOGY
───────────
A composite of 3/6/12-month total return, weighted toward the intermediate
window. The 12-month leg deliberately SKIPS the most recent month — the
standard academic construction (12-1 momentum), because the very short term
exhibits REVERSAL rather than continuation and including it degrades the
signal. This is one of the most replicated findings in the literature and
one of the easiest to get wrong.

    3-month   30%   captures recent acceleration
    6-month   40%   the intermediate window with the strongest evidence
    12-1      30%   the classic long-horizon momentum leg

Ranked into quartiles across the universe. Q1 = strongest.

WHAT THIS IS NOT
────────────────
Momentum is a RELATIVE ranking, not a directional forecast. In a bear
market the top quartile is simply what is falling least — the rank says
nothing about whether the absolute return will be positive. That is exactly
why trend_filter.py exists alongside this: RS says WHICH sleeves, the trend
gate says WHETHER to hold them at all. Using RS alone in a downtrend is how
you end up fully invested in the best-performing losers.
"""

from __future__ import annotations

from typing import Callable, Optional

import pandas as pd

# Composite weights. Intermediate-weighted, per the evidence.
RS_WEIGHTS = {"m3": 0.30, "m6": 0.40, "m12_1": 0.30}

TRADING_DAYS = {"m1": 21, "m3": 63, "m6": 126, "m12": 252}

# Overweight/underweight applied to base weight, by quartile. Deliberately
# modest — momentum decays, and a ranking that swings weights violently
# generates turnover that eats the premium it is chasing.
QUARTILE_TILT = {1: 1.30, 2: 1.10, 3: 0.90, 4: 0.70}


def _total_return(prices: pd.Series, days: int,
                  skip_recent: int = 0) -> Optional[float]:
    """Percent return over `days`, optionally ending `skip_recent` days back."""
    try:
        s = prices.dropna()
        end_idx = -1 - skip_recent
        start_idx = end_idx - days
        if len(s) < abs(start_idx):
            return None
        return float(s.iloc[end_idx] / s.iloc[start_idx] - 1) * 100
    except Exception:
        return None


def score_ticker(prices: pd.Series) -> Optional[dict]:
    """
    Composite RS score for one ticker. None when history is insufficient —
    never a partial score, because a composite missing its 12-month leg is
    a different metric, not a slightly worse version of the same one.
    """
    m3 = _total_return(prices, TRADING_DAYS["m3"])
    m6 = _total_return(prices, TRADING_DAYS["m6"])
    # 12-1: twelve months ending one month ago
    m12_1 = _total_return(prices, TRADING_DAYS["m12"] - TRADING_DAYS["m1"],
                          skip_recent=TRADING_DAYS["m1"])

    if None in (m3, m6, m12_1):
        return None

    composite = (RS_WEIGHTS["m3"] * m3 + RS_WEIGHTS["m6"] * m6
                 + RS_WEIGHTS["m12_1"] * m12_1)
    return {"m3": round(m3, 2), "m6": round(m6, 2), "m12_1": round(m12_1, 2),
            "composite": round(composite, 2)}


def rank_universe(fetch_prices: Callable, tickers: list[str],
                  period: str = "2y") -> dict:
    """
    Score and rank every ticker. Returns a dict, always.

    Tickers that fail to fetch or lack history are named in `missing` and
    excluded from ranking — they are NOT scored zero, which would place them
    artificially mid-pack and corrupt every other ticker's quartile.
    """
    out = {"scores": {}, "missing": [], "ranked": [], "quartiles": {},
           "detail": ""}

    for tk in tickers:
        try:
            px = fetch_prices(tk, period)
            px = pd.Series(px.squeeze() if hasattr(px, "squeeze") else px)
            px = px.astype(float).dropna()
            sc = score_ticker(px)
            if sc is None:
                out["missing"].append(f"{tk} (insufficient history)")
            else:
                out["scores"][tk] = sc
        except Exception as e:
            out["missing"].append(f"{tk} ({type(e).__name__})")

    if not out["scores"]:
        out["detail"] = "No tickers could be ranked — RS layer is dark."
        return out

    ranked = sorted(out["scores"].items(),
                    key=lambda kv: -kv[1]["composite"])
    out["ranked"] = [tk for tk, _ in ranked]

    n = len(ranked)
    for i, (tk, _) in enumerate(ranked):
        # 1-indexed quartile: 1 = strongest
        q = min(4, int(i / n * 4) + 1)
        out["quartiles"][tk] = q

    out["detail"] = (f"Ranked {n} of {len(tickers)} tickers. "
                     f"Strongest: {ranked[0][0]} "
                     f"({ranked[0][1]['composite']:+.1f}). "
                     f"Weakest: {ranked[-1][0]} "
                     f"({ranked[-1][1]['composite']:+.1f}).")
    if out["missing"]:
        out["detail"] += f" Excluded: {', '.join(out['missing'])}."
    return out


def apply_tilt(base_weights: dict, rs: dict,
               tilt_map: dict = None) -> dict:
    """
    Apply RS quartile tilts to base weights, then RENORMALISE to 100%.

    Renormalisation matters: without it, a universe where most sleeves land
    in the bottom quartiles would silently shrink the book to well under
    100% invested, turning a relative-strength tilt into an accidental
    market-timing call. Tilts here are RELATIVE, not directional.
    """
    tilt_map = tilt_map or QUARTILE_TILT
    tilted = {}
    for tk, w in base_weights.items():
        q = rs.get("quartiles", {}).get(tk)
        mult = tilt_map.get(q, 1.0) if q else 1.0
        tilted[tk] = w * mult

    total = sum(tilted.values())
    if total <= 0:
        return dict(base_weights)
    return {tk: round(w / total * 100, 2) for tk, w in tilted.items()}


def render(st, rs: dict, base_weights: dict = None):
    """Render the RS ranking panel."""
    st.markdown("### Relative Strength Ranking")
    st.caption(
        "Composite 3/6/12-1 month momentum, ranked across the sleeve "
        "universe. The 12-month leg skips the most recent month — short-term "
        "returns exhibit REVERSAL, not continuation, and including that month "
        "degrades the signal."
    )

    if not rs.get("scores"):
        st.error(rs.get("detail", "No RS data."))
        return

    st.caption(rs["detail"])

    rows = []
    for tk in rs["ranked"]:
        sc = rs["scores"][tk]
        q = rs["quartiles"][tk]
        rows.append({
            "Ticker": tk, "Quartile": f"Q{q}",
            "Composite": sc["composite"],
            "3M": sc["m3"], "6M": sc["m6"], "12-1M": sc["m12_1"],
            "Tilt": f"{QUARTILE_TILT.get(q, 1.0):.2f}x",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if base_weights:
        tilted = apply_tilt(base_weights, rs)
        st.markdown("#### Weight impact")
        diffs = [(tk, base_weights[tk], tilted.get(tk, 0),
                  tilted.get(tk, 0) - base_weights[tk])
                 for tk in base_weights]
        diffs.sort(key=lambda x: -abs(x[3]))
        for tk, b, t, d in diffs[:10]:
            if abs(d) < 0.1:
                continue
            colour = "#16a34a" if d > 0 else "#dc2626"
            st.markdown(
                f"<b>{tk}</b> {b:.1f}% → {t:.1f}% "
                f"<span style='color:{colour};'>({d:+.1f})</span>",
                unsafe_allow_html=True)

    st.info(
        "**RS is a RELATIVE ranking, not a directional forecast.** In a bear "
        "market the top quartile is simply what is falling least. Pair this "
        "with the trend filter — RS says WHICH sleeves, the trend gate says "
        "WHETHER to hold them at all."
    )


def selftest() -> dict:
    import numpy as np
    failures = []

    idx = pd.bdate_range("2024-01-01", periods=300)
    # Strong uptrend, weak downtrend, flat
    strong = pd.Series(np.linspace(100, 200, 300), index=idx)
    weak = pd.Series(np.linspace(200, 100, 300), index=idx)
    flat = pd.Series(np.full(300, 100.0), index=idx)

    def fake_fetch(tk, period="2y"):
        return {"STRONG": strong, "WEAK": weak, "FLAT": flat}[tk]

    rs = rank_universe(fake_fetch, ["STRONG", "WEAK", "FLAT"])
    if rs["ranked"][0] != "STRONG":
        failures.append(f"strongest ranked {rs['ranked'][0]}, expected STRONG")
    if rs["ranked"][-1] != "WEAK":
        failures.append(f"weakest ranked {rs['ranked'][-1]}, expected WEAK")

    # 12-1 must skip the last month: a series that spikes ONLY in the final
    # month should not have that spike dominate the 12-1 leg.
    spike = pd.Series(list(np.full(279, 100.0)) + list(np.linspace(100, 300, 21)),
                      index=idx)
    sc = score_ticker(spike)
    if sc is None or abs(sc["m12_1"]) > 5:
        failures.append(f"12-1 leg contaminated by final-month spike: "
                        f"{sc['m12_1'] if sc else None}")

    # Renormalisation must preserve 100%
    base = {"STRONG": 40, "WEAK": 30, "FLAT": 30}
    tilted = apply_tilt(base, rs)
    if abs(sum(tilted.values()) - 100) > 0.5:
        failures.append(f"tilted weights sum to {sum(tilted.values())}")
    if tilted["STRONG"] <= base["STRONG"]:
        failures.append("strong ticker was not overweighted")

    # Missing data must not be scored zero
    bad = rank_universe(lambda *a, **k: None, ["X", "Y"])
    if bad["scores"]:
        failures.append("fabricated scores from failed fetches")

    return {"ok": not failures, "failures": failures,
            "ranked": rs["ranked"]}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2, default=str))
