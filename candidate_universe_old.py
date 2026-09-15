"""
candidate_universe.py  (v1 — August 2026)
─────────────────────────────────────────
The single source of truth for WHAT CAN BE HELD and WHAT IT ACTUALLY IS.

WHY THIS EXISTS
───────────────
Until now the framework had two disconnected universes:

    BASE_WEIGHTS / REGIMES   15 core sleeves, regime-governed
    SATELLITE_UNIVERSE       20 tactical candidates, separately screened

Nothing compared across them, so a genuinely better instrument for a role
could never displace an incumbent just because the incumbent happened to be
written into BASE_WEIGHTS first. This module unifies them.

THE TWO IDEAS THAT MAKE "CONSIDER EVERYTHING" SAFE
──────────────────────────────────────────────────
1. ROLE. Candidates compete only WITHIN a functional role. You do not swap
   TLT for TQQQ -- they do different jobs. Comparing US_GROWTH against
   US_GROWTH is a real question; comparing it against DURATION is a
   category error that would let a momentum ranking quietly destroy the
   portfolio's diversification.

2. LOOK-THROUGH EXPOSURE. A ticker is not its label. VOO is ~33% tech.
   QQQ is ~50%. VGT is ~100%. TQQQ is 3x a ~50%-tech index = ~150% tech
   exposure per dollar held. Someone holding VOO + VGT + QQQ + SCHG + TQQQ
   holds FIVE tickers and ONE bet. Without look-through, a "diversified"
   five-position sleeve can be more concentrated than a single position.

⚠ SECTOR WEIGHTS ARE APPROXIMATE AND DRIFT
──────────────────────────────────────────
The sector splits below are approximate, sourced from published fund
composition and rounded. They drift as indices rebalance and as constituent
prices move -- tech's share of the S&P has moved many points in a single
year. They are good enough for CONCENTRATION WARNINGS (is this book 60%
tech?) and NOT good enough for precise risk modelling. Refresh periodically;
treat the outputs as directional. Never fabricate precision this data
cannot support.
"""

from __future__ import annotations

from typing import Optional

# ── Functional roles. Candidates compete only within a role. ────────────────
ROLE_US_BROAD = "US_BROAD"            # total-market / S&P core
ROLE_US_GROWTH = "US_GROWTH"          # growth-tilted equity
ROLE_US_TECH = "US_TECH"              # concentrated technology
ROLE_SEMIS = "SEMIS"                  # semiconductor-specific
ROLE_DEFENSIVE_EQ = "DEFENSIVE_EQ"    # dividend / low-vol / staples-ish
ROLE_SECTOR_CYCLICAL = "SECTOR_CYCLICAL"
ROLE_SMALL_CAP = "SMALL_CAP"
ROLE_METALS = "METALS"
ROLE_COMMODITY = "COMMODITY"
ROLE_DURATION = "DURATION"
ROLE_CASH = "CASH"
ROLE_TREND = "TREND"
ROLE_INNOVATION = "INNOVATION"

# Roles whose weight is governed by the regime classifier at Level 1 and
# should NOT be displaced by momentum ranking. Substitution WITHIN these
# roles is fine (a better duration instrument is still duration); reweighting
# ACROSS them is the classifier's job, not this module's.
REGIME_GOVERNED_ROLES = {ROLE_METALS, ROLE_COMMODITY, ROLE_DURATION,
                         ROLE_CASH, ROLE_TREND}

# ── The universe ────────────────────────────────────────────────────────────
# sectors: look-through exposure, fractions summing to ~1.0 BEFORE leverage.
# leverage: daily-reset multiple. 1.0 = unleveraged.
# core: currently in BASE_WEIGHTS (an incumbent, not necessarily the best).
UNIVERSE = {
    # ── US broad ────────────────────────────────────────────────────────────
    "VOO":  {"name": "Vanguard S&P 500", "role": ROLE_US_BROAD, "leverage": 1.0,
             "expense": 0.03, "core": False,
             "sectors": {"tech": 0.33, "financials": 0.11, "healthcare": 0.10,
                        "cons_disc": 0.10, "comm_svcs": 0.09,
                        "industrials": 0.08, "staples": 0.06, "energy": 0.03,
                        "utilities": 0.02, "materials": 0.02, "reits": 0.02,
                        "other": 0.04}},
    "IVV":  {"name": "iShares Core S&P 500", "role": ROLE_US_BROAD,
             "leverage": 1.0, "expense": 0.03, "core": False,
             "sectors": {"tech": 0.33, "financials": 0.11, "healthcare": 0.10,
                        "cons_disc": 0.10, "comm_svcs": 0.09,
                        "industrials": 0.08, "staples": 0.06, "energy": 0.03,
                        "utilities": 0.02, "materials": 0.02, "reits": 0.02,
                        "other": 0.04}},

    # ── US growth ───────────────────────────────────────────────────────────
    "SCHG": {"name": "Schwab US Large-Cap Growth", "role": ROLE_US_GROWTH,
             "leverage": 1.0, "expense": 0.04, "core": False,
             "sectors": {"tech": 0.45, "cons_disc": 0.15, "comm_svcs": 0.13,
                        "healthcare": 0.09, "industrials": 0.07,
                        "financials": 0.05, "other": 0.06}},
    "VUG":  {"name": "Vanguard Growth", "role": ROLE_US_GROWTH, "leverage": 1.0,
             "expense": 0.04, "core": False,
             "sectors": {"tech": 0.47, "cons_disc": 0.15, "comm_svcs": 0.12,
                        "healthcare": 0.08, "industrials": 0.07,
                        "financials": 0.05, "other": 0.06}},
    "QQQ":  {"name": "Nasdaq-100", "role": ROLE_US_GROWTH, "leverage": 1.0,
             "expense": 0.20, "core": True,
             "sectors": {"tech": 0.50, "comm_svcs": 0.16, "cons_disc": 0.13,
                        "healthcare": 0.06, "industrials": 0.05,
                        "staples": 0.05, "other": 0.05}},

    # ── Concentrated tech ───────────────────────────────────────────────────
    "VGT":  {"name": "Vanguard Info Tech", "role": ROLE_US_TECH, "leverage": 1.0,
             "expense": 0.09, "core": True, "sectors": {"tech": 1.00}},
    "XLK":  {"name": "Technology SPDR", "role": ROLE_US_TECH, "leverage": 1.0,
             "expense": 0.09, "core": False, "sectors": {"tech": 1.00}},
    "IGV":  {"name": "iShares Expanded Tech-Software", "role": ROLE_US_TECH,
             "leverage": 1.0, "expense": 0.41, "core": False,
             "sectors": {"tech": 1.00}},
    "TQQQ": {"name": "ProShares UltraPro QQQ", "role": ROLE_US_GROWTH,
             "leverage": 3.0, "expense": 0.84, "core": False,
             "sectors": {"tech": 0.50, "comm_svcs": 0.16, "cons_disc": 0.13,
                        "healthcare": 0.06, "industrials": 0.05,
                        "staples": 0.05, "other": 0.05}},

    # ── Semiconductors ──────────────────────────────────────────────────────
    "SMH":  {"name": "VanEck Semiconductors", "role": ROLE_SEMIS,
             "leverage": 1.0, "expense": 0.35, "core": True,
             "sectors": {"tech": 1.00}},
    "SOXX": {"name": "iShares Semiconductor", "role": ROLE_SEMIS,
             "leverage": 1.0, "expense": 0.35, "core": False,
             "sectors": {"tech": 1.00}},
    "SOXL": {"name": "Direxion Daily Semiconductor Bull", "role": ROLE_SEMIS,
             "leverage": 3.0, "expense": 0.75, "core": False,
             "sectors": {"tech": 1.00}},

    # ── Defensive equity ────────────────────────────────────────────────────
    "SCHD": {"name": "Schwab US Dividend Equity", "role": ROLE_DEFENSIVE_EQ,
             "leverage": 1.0, "expense": 0.06, "core": True,
             "sectors": {"financials": 0.19, "staples": 0.18, "healthcare": 0.15,
                        "industrials": 0.13, "energy": 0.11, "tech": 0.10,
                        "cons_disc": 0.06, "other": 0.08}},
    "XLV":  {"name": "Health Care SPDR", "role": ROLE_DEFENSIVE_EQ,
             "leverage": 1.0, "expense": 0.09, "core": True,
             "sectors": {"healthcare": 1.00}},
    "XLU":  {"name": "Utilities SPDR", "role": ROLE_DEFENSIVE_EQ,
             "leverage": 1.0, "expense": 0.09, "core": True,
             "sectors": {"utilities": 1.00}},

    # ── Cyclical sectors ────────────────────────────────────────────────────
    "XLF":  {"name": "Financials SPDR", "role": ROLE_SECTOR_CYCLICAL,
             "leverage": 1.0, "expense": 0.09, "core": False,
             "sectors": {"financials": 1.00}},
    "XLI":  {"name": "Industrials SPDR", "role": ROLE_SECTOR_CYCLICAL,
             "leverage": 1.0, "expense": 0.09, "core": False,
             "sectors": {"industrials": 1.00}},
    "XLY":  {"name": "Consumer Discretionary SPDR", "role": ROLE_SECTOR_CYCLICAL,
             "leverage": 1.0, "expense": 0.09, "core": False,
             "sectors": {"cons_disc": 1.00}},
    "XLC":  {"name": "Communication Services SPDR", "role": ROLE_SECTOR_CYCLICAL,
             "leverage": 1.0, "expense": 0.09, "core": False,
             "sectors": {"comm_svcs": 1.00}},
    "XLB":  {"name": "Materials SPDR", "role": ROLE_SECTOR_CYCLICAL,
             "leverage": 1.0, "expense": 0.09, "core": False,
             "sectors": {"materials": 1.00}},
    "XLRE": {"name": "Real Estate SPDR", "role": ROLE_SECTOR_CYCLICAL,
             "leverage": 1.0, "expense": 0.09, "core": False,
             "sectors": {"reits": 1.00}},
    "XLE":  {"name": "Energy SPDR", "role": ROLE_SECTOR_CYCLICAL,
             "leverage": 1.0, "expense": 0.09, "core": True,
             "sectors": {"energy": 1.00}},

    # ── Small cap / innovation ──────────────────────────────────────────────
    "IWM":  {"name": "Russell 2000", "role": ROLE_SMALL_CAP, "leverage": 1.0,
             "expense": 0.19, "core": False,
             "sectors": {"financials": 0.18, "industrials": 0.17,
                        "healthcare": 0.16, "tech": 0.14, "cons_disc": 0.11,
                        "energy": 0.06, "reits": 0.06, "other": 0.12}},
    "ARKK": {"name": "ARK Innovation", "role": ROLE_INNOVATION, "leverage": 1.0,
             "expense": 0.75, "core": False,
             "sectors": {"tech": 0.40, "healthcare": 0.25, "cons_disc": 0.15,
                        "financials": 0.12, "other": 0.08}},

    # ── Regime-governed sleeves ─────────────────────────────────────────────
    "GLD":  {"name": "SPDR Gold", "role": ROLE_METALS, "leverage": 1.0,
             "expense": 0.40, "core": True, "sectors": {"gold": 1.00}},
    "SLV":  {"name": "iShares Silver", "role": ROLE_METALS, "leverage": 1.0,
             "expense": 0.50, "core": True, "sectors": {"silver": 1.00}},
    "RING": {"name": "iShares Gold Miners", "role": ROLE_METALS, "leverage": 1.0,
             "expense": 0.39, "core": True, "sectors": {"materials": 1.00}},
    "PDBC": {"name": "Invesco Optimum Yield Commodity", "role": ROLE_COMMODITY,
             "leverage": 1.0, "expense": 0.59, "core": True,
             "sectors": {"commodity": 1.00}},
    "TLT":  {"name": "iShares 20+ Year Treasury", "role": ROLE_DURATION,
             "leverage": 1.0, "expense": 0.15, "core": True,
             "sectors": {"treasury": 1.00}},
    "SGOV": {"name": "iShares 0-3 Month Treasury", "role": ROLE_CASH,
             "leverage": 1.0, "expense": 0.09, "core": True,
             "sectors": {"cash": 1.00}},
    "USFR": {"name": "WisdomTree Floating Rate Treasury", "role": ROLE_CASH,
             "leverage": 1.0, "expense": 0.15, "core": True,
             "sectors": {"cash": 1.00}},
    "KMLM": {"name": "KFA Mount Lucas Managed Futures", "role": ROLE_TREND,
             "leverage": 1.0, "expense": 0.90, "core": True,
             "sectors": {"managed_futures": 1.00}},
}

LEVERAGED = {t for t, m in UNIVERSE.items() if m["leverage"] > 1.0}


def by_role(role: str) -> list[str]:
    return [t for t, m in UNIVERSE.items() if m["role"] == role]


def role_of(ticker: str) -> Optional[str]:
    return UNIVERSE.get(ticker, {}).get("role")


def is_leveraged(ticker: str) -> bool:
    return UNIVERSE.get(ticker, {}).get("leverage", 1.0) > 1.0


def leverage_of(ticker: str) -> float:
    return UNIVERSE.get(ticker, {}).get("leverage", 1.0)


def all_roles() -> list[str]:
    seen = []
    for m in UNIVERSE.values():
        if m["role"] not in seen:
            seen.append(m["role"])
    return seen


def selftest() -> dict:
    failures = []
    for t, m in UNIVERSE.items():
        tot = sum(m["sectors"].values())
        if abs(tot - 1.0) > 0.02:
            failures.append(f"{t}: sectors sum to {tot:.3f}, expected ~1.0")
        for k in ("name", "role", "leverage", "expense", "core", "sectors"):
            if k not in m:
                failures.append(f"{t}: missing '{k}'")
    if LEVERAGED != {"TQQQ", "SOXL"}:
        failures.append(f"LEVERAGED is {LEVERAGED}, expected TQQQ/SOXL")
    for t in LEVERAGED:
        if UNIVERSE[t]["leverage"] != 3.0:
            failures.append(f"{t} leverage {UNIVERSE[t]['leverage']}, expected 3.0")
    # Every role must have at least one member
    for r in all_roles():
        if not by_role(r):
            failures.append(f"role {r} has no members")
    return {"ok": not failures, "failures": failures,
            "universe_size": len(UNIVERSE), "roles": len(all_roles()),
            "leveraged": sorted(LEVERAGED),
            "core_incumbents": sorted(t for t, m in UNIVERSE.items() if m["core"])}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2, default=str))
