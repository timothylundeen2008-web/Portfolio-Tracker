"""
correlation_monitor.py  (v1 — July 2026)
========================================
Rolling correlation across the ACTUAL sleeves, with a sign-flip alert.

WHY
---
On 2026-07-29 equities fell 1.5%, the 30-year yield rose 10bp to its highest
level since 2007, and gold was flat. Stocks down, bonds down, the metal that is
supposed to hedge both doing nothing. A book can hold a dozen tickers and be
one factor, and the only way to know is to measure it.

The existing stack already reasons about stock/bond correlation inside
kmlm_signal(). This generalizes it: every sleeve pair, rolling, with an alert
when a pair that was NEGATIVELY correlated (i.e. actually diversifying) crosses
into positive territory.

THE DECISION THIS GATES
-----------------------
Whether the intermediate-Treasury sleeve counts as ballast or as beta. If the
equity/duration correlation has been positive for a month, the sleeve is not
hedging anything — it is a second helping of the same risk with a lower
expected return, and the honest response is to cut it rather than to keep
calling it diversification.

Second use: the effective-diversification count. A portfolio of N sleeves whose
average pairwise correlation is rho behaves roughly like

    N_eff = N / (1 + (N - 1) * rho)

independent bets. Twelve sleeves at rho = 0.8 is 1.5 bets wearing a costume.
"""

from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd

DEFAULT_WINDOW = 60
FLIP_ALERT_PERSISTENCE = 15   # sessions a sign flip must hold before alerting

# Pairs whose correlation carries a specific portfolio decision. Extend freely;
# the reason string is what makes the alert actionable rather than trivia.
WATCHED_PAIRS = [
    ("VGT", "TLT", "Growth vs long duration. Positive = the bond sleeve has "
                   "stopped being ballast and is now a second helping of "
                   "duration-sensitive risk. This is the 2022 signature."),
    ("VGT", "GLD", "Growth vs gold. Positive = the metal is trading as a risk "
                   "asset, not a hedge — usually means real yields are driving "
                   "both."),
    ("VGT", "KMLM", "Growth vs trend. Trend earns its fee by staying near zero "
                    "or negative here. Sustained positive correlation means the "
                    "sleeve has become expensive beta."),
    ("TLT", "GLD", "Duration vs gold. Both are long-real-rate expressions; a "
                   "high positive correlation means the 'diversified' defensive "
                   "block is one bet."),
    ("XLE", "VGT", "Energy vs growth. Low correlation is why the energy sleeve "
                   "is worth holding at all."),
]


def _returns(prices: pd.DataFrame) -> pd.DataFrame:
    px = prices.copy()
    px.index = pd.to_datetime(px.index)
    return px.sort_index().astype(float).pct_change().dropna(how="all")


def rolling_matrix(prices: pd.DataFrame,
                   window: int = DEFAULT_WINDOW) -> Optional[pd.DataFrame]:
    """Current correlation matrix over the trailing `window` sessions."""
    r = _returns(prices)
    if len(r) < window:
        return None
    return r.iloc[-window:].corr()


def average_pairwise(corr: Optional[pd.DataFrame]) -> Optional[float]:
    """Mean off-diagonal correlation."""
    if corr is None or corr.empty:
        return None
    a = corr.to_numpy(dtype=float)
    n = a.shape[0]
    if n < 2:
        return None
    mask = ~np.eye(n, dtype=bool)
    vals = a[mask]
    vals = vals[~np.isnan(vals)]
    return float(vals.mean()) if vals.size else None


def effective_bets(n_sleeves: int, rho: Optional[float]) -> Optional[float]:
    """How many independent bets N correlated sleeves actually represent."""
    if rho is None or n_sleeves < 1:
        return None
    denom = 1.0 + (n_sleeves - 1) * rho
    if denom <= 0:
        return float(n_sleeves)
    return round(n_sleeves / denom, 2)


def pair_history(prices: pd.DataFrame, a: str, b: str,
                 window: int = DEFAULT_WINDOW) -> pd.Series:
    """Rolling correlation series for one pair. Empty when data is missing."""
    if a not in prices.columns or b not in prices.columns:
        return pd.Series(dtype=float)
    r = _returns(prices[[a, b]]).dropna()
    if len(r) < window + 1:
        return pd.Series(dtype=float)
    return r[a].rolling(window).corr(r[b]).dropna()


def check_flips(prices: pd.DataFrame, window: int = DEFAULT_WINDOW,
                pairs: Iterable[tuple] = tuple(WATCHED_PAIRS),
                persistence: int = FLIP_ALERT_PERSISTENCE) -> list[dict]:
    """
    Detect pairs that have crossed from negative to positive correlation and
    STAYED there for `persistence` sessions.

    Persistence matters: a single-day cross is noise, and an alert that fires on
    noise gets ignored, which is worse than no alert.
    """
    alerts = []
    for a, b, reason in pairs:
        h = pair_history(prices, a, b, window)
        if len(h) < persistence + 1:
            continue
        recent = h.iloc[-persistence:]
        prior = h.iloc[:-persistence]
        if prior.empty:
            continue
        now = float(recent.mean())
        was = float(prior.iloc[-persistence:].mean()) if len(prior) >= persistence \
            else float(prior.mean())

        if now > 0.10 and was <= 0.0 and (recent > 0).all():
            alerts.append({
                "pair": f"{a}/{b}", "severity": "HIGH",
                "now": round(now, 2), "was": round(was, 2),
                "reason": reason,
                "detail": (f"{a}/{b} correlation has been positive for "
                           f"{persistence} consecutive sessions "
                           f"({was:+.2f} -> {now:+.2f}). {reason}")})
        elif now > 0.60 and was < 0.40:
            alerts.append({
                "pair": f"{a}/{b}", "severity": "MODERATE",
                "now": round(now, 2), "was": round(was, 2),
                "reason": reason,
                "detail": (f"{a}/{b} correlation has risen sharply "
                           f"({was:+.2f} -> {now:+.2f}) and is now high. "
                           f"{reason}")})
    return alerts


def report(prices: pd.DataFrame, window: int = DEFAULT_WINDOW) -> dict:
    """
    One-call summary for the dashboard.

    `prices` is a DataFrame of adjusted closes, one column per sleeve ticker.
    The All-Weather app already fetches per-ticker series — concatenate them
    into a frame and pass it here.
    """
    out = {"window": window, "available": False, "matrix": None,
           "avg_pairwise": None, "effective_bets": None, "n_sleeves": 0,
           "alerts": [], "headline": "", "detail": ""}

    if prices is None or getattr(prices, "empty", True):
        out["detail"] = "No price frame supplied."
        return out

    corr = rolling_matrix(prices, window)
    if corr is None:
        out["detail"] = (f"Need {window} sessions of overlapping history; "
                         f"have {len(prices)}.")
        return out

    rho = average_pairwise(corr)
    n = corr.shape[0]
    neff = effective_bets(n, rho)
    alerts = check_flips(prices, window)

    out.update(available=True, matrix=corr, avg_pairwise=round(rho, 3)
               if rho is not None else None, effective_bets=neff,
               n_sleeves=n, alerts=alerts)

    diversification = ("weak" if (rho or 0) > 0.65 else
                       "moderate" if (rho or 0) > 0.35 else "healthy")
    out["headline"] = (f"{n} sleeves, average pairwise correlation "
                       f"{rho:+.2f} -> ~{neff} effective bets "
                       f"({diversification} diversification)"
                       + (f" · {len(alerts)} correlation alert(s)" if alerts else ""))
    out["detail"] = (
        f"Trailing {window} sessions. "
        + (f"{len(alerts)} watched pair(s) have flipped or tightened: "
           + "; ".join(a["pair"] for a in alerts) + "."
           if alerts else "No watched pair has flipped sign.")
        + (" Average correlation above 0.65 means the sleeve count is "
           "cosmetic — consolidate rather than adding more tickers."
           if (rho or 0) > 0.65 else "")
    )
    return out


def selftest() -> dict:
    """
    Synthetic frame containing a genuine correlation REGIME CHANGE: TLT hedges
    equities for the first stretch (negative correlation), then stops hedging
    and co-moves (positive) — the 2022/2026 signature. The flip must be caught.
    """
    rng = np.random.default_rng(7)
    n_hedge, n_broken = 200, 40
    n = n_hedge + n_broken
    idx = pd.bdate_range("2026-01-01", periods=n)
    shock = rng.normal(0, 0.01, n)

    # TLT: -0.7 beta to the equity shock, then +0.8 beta.
    tlt_beta = np.concatenate([np.full(n_hedge, -0.7), np.full(n_broken, 0.8)])
    tlt_ret = tlt_beta * shock + rng.normal(0, 0.002, n)

    frame = pd.DataFrame({
        "VGT": 100 * np.cumprod(1 + shock),
        "TLT": 100 * np.cumprod(1 + tlt_ret),
        "XLE": 100 * np.cumprod(1 + rng.normal(0, 0.012, n)),
        "KMLM": 100 * np.cumprod(1 + rng.normal(0, 0.007, n)),
    }, index=idx)

    rep = report(frame)
    failures = []
    if not rep["available"]:
        failures.append(f"Report unavailable: {rep['detail']}")
    else:
        h = pair_history(frame, "VGT", "TLT")
        if h.empty:
            failures.append("VGT/TLT pair history empty")
        elif float(h.iloc[-1]) <= 0:
            failures.append(f"Engineered flip not reflected: latest correlation "
                            f"{float(h.iloc[-1]):+.2f}, expected positive")
        if not any(a["pair"] == "VGT/TLT" for a in rep["alerts"]):
            failures.append("VGT/TLT sign flip did not raise an alert")
        if rep["effective_bets"] is None:
            failures.append("effective_bets not computed")
    return {"ok": not failures, "failures": failures,
            "headline": rep.get("headline"), "detail": rep.get("detail"),
            "alerts": [{"pair": a["pair"], "severity": a["severity"],
                        "was": a["was"], "now": a["now"]}
                       for a in rep.get("alerts", [])]}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2, default=str))
