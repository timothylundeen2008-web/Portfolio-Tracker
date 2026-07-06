"""
regime_classifier.py
====================
Shared macro-regime engine for the Repression Dashboard and the All-Weather
Portfolio Dashboard.

Core idea implemented here (per the crux correction):
  There are TWO different "real yields" and they must never be conflated.

    1. SHORT real policy rate  = EFFR (DFF) - trailing CPI YoY   -> repression gauge
    2. LONG  real market yield = DFII10 (10y TIPS yield)         -> duration friend/foe

  The SIGN of (1) and the DIRECTION (momentum) of (2), combined with HY credit
  spreads and the 60-day stock/bond correlation, place us in one of four regime
  quadrants, each of which maps to a target portfolio tilt.

The module is dependency-injected: pass your existing fetchers in, or let it
fall back to the inline implementations so it runs standalone.

FRED series used:
  DFF          Effective Federal Funds Rate (daily)
  CPIAUCSL     CPI (index; YoY computed here)
  DFII10       10y TIPS real yield
  T10YIE       10y breakeven inflation
  DGS10, DGS2  nominal 10y / 2y (for 2s10s)
  BAMLH0A0HYM2 ICE BofA US High Yield OAS
  BAMLC0A0CM   ICE BofA US Corporate (IG) OAS
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

try:
    import requests  # only needed if you use the inline FRED fetcher
except Exception:  # pragma: no cover
    requests = None

FED_TARGET_INFLATION = 2.0

FRED_SERIES = {
    "eff_funds": "DFF",
    "cpi_index": "CPIAUCSL",
    "real_10y": "DFII10",
    "breakeven_10y": "T10YIE",
    "nom_10y": "DGS10",
    "nom_2y": "DGS2",
    "hy_oas": "BAMLH0A0HYM2",
    "ig_oas": "BAMLC0A0CM",
}

# --------------------------------------------------------------------------- #
#  Regime definitions + target tilts
# --------------------------------------------------------------------------- #
# Weights are the *base* All-Weather sleeve. Each regime supplies an overlay
# that shifts weights. Overlays are expressed as additive deltas (in %) and are
# normalized back to 100% after applying, so they stay internally consistent.

BASE_WEIGHTS = {
    "VGT": 20, "SMH": 4, "QQQ": 4,          # growth / tech
    "GLD": 12, "SLV": 5, "RING": 5,          # precious metals
    "XLE": 5, "PDBC": 3,                      # commodities / energy
    "SCHD": 13, "XLV": 4, "XLU": 3,          # defensive equity
    "SGOV": 5, "USFR": 3,                     # cash
    "TLT": 10, "KMLM": 4,                     # duration (contingent) + trend
}

REGIMES = {
    "inflationary_repression": {
        "label": "Inflationary Repression",
        "blurb": (
            "Negative SHORT real rate + POSITIVE, RISING long real yield. Debt "
            "eroded via inflation overshoot at the front end; long end NOT "
            "suppressed. Real assets and trend win; long duration bleeds."
        ),
        "overlay": {
            "TLT": -10,          # turn contingent duration OFF
            "KMLM": +4,          # lean into trend
            "SGOV": -3, "USFR": -3,   # cash bleeds in real terms
            "GLD": +3, "PDBC": +2, "XLE": +2,
            "SMH": -1,           # rate-sensitive growth trimmed
        },
    },
    "liquidity_crisis": {
        "label": "Liquidity Crisis",
        "blurb": (
            "HY spreads blowing out, long real yields FALLING (flight to "
            "quality). Duration and cash are the shock absorbers; metals may "
            "sell off first before rallying."
        ),
        "overlay": {
            "TLT": +6,           # switch/boost contingent duration
            "SGOV": +4, "USFR": +2,
            "KMLM": +2,
            "VGT": -6, "SMH": -2, "QQQ": -2,
            "SLV": -2, "RING": -2,
        },
    },
    "stagflation": {
        "label": "Stagflation",
        "blurb": (
            "Negative short real rate WITH growth rolling over (2s10s "
            "re-steepening from inversion). Gold, trend, and defensives; cut "
            "cyclical growth and energy demand risk."
        ),
        "overlay": {
            "GLD": +4, "KMLM": +3,
            "SCHD": +2, "XLV": +2, "XLU": +1,
            "VGT": -5, "SMH": -2, "QQQ": -2, "XLE": -3,
            "TLT": -1,
        },
    },
    "goldilocks": {
        "label": "Goldilocks / Reflation",
        "blurb": (
            "Positive real rates, tight credit, stable inflation. Normalize "
            "toward growth; trim hedges and reduce trend."
        ),
        "overlay": {
            "VGT": +4, "QQQ": +3, "SMH": +2,
            "KMLM": -2, "TLT": -4,
            "GLD": -3, "SLV": -2,
            "SGOV": +2,
        },
    },
    "neutral": {
        "label": "Neutral / Transition",
        "blurb": (
            "Signals are mixed or transitioning between quadrants. Hold the "
            "base allocation and wait for confirmation before rebalancing."
        ),
        "overlay": {},
    },
}


# --------------------------------------------------------------------------- #
#  Inline fetchers (fallbacks). Pass your own to override.
# --------------------------------------------------------------------------- #
def _inline_fetch_fred(series_id: str, api_key: str,
                       start: str = "2015-01-01") -> pd.Series:
    """Minimal FRED fetch mirroring the dashboard's existing pattern."""
    if requests is None:
        return pd.Series(dtype=float)
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "observation_start": start,
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        idx, val = [], []
        for o in obs:
            if o["value"] in (".", "", None):
                continue
            idx.append(pd.to_datetime(o["date"]))
            val.append(float(o["value"]))
        return pd.Series(val, index=idx, name=series_id)
    except Exception:
        return pd.Series(dtype=float)


def _inline_fetch_prices(ticker: str, period: str = "1y") -> pd.Series:
    """Fallback price fetch via yfinance (used for stock/bond correlation)."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, progress=False,
                         auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float)
        return df["Close"].dropna()
    except Exception:
        return pd.Series(dtype=float)


# --------------------------------------------------------------------------- #
#  Signal computation
# --------------------------------------------------------------------------- #
@dataclass
class SignalSet:
    short_real_rate: Optional[float] = None      # EFFR - CPI YoY
    long_real_yield: Optional[float] = None      # DFII10 level
    long_real_mom_3m: Optional[float] = None     # change over ~63 sessions
    breakeven_10y: Optional[float] = None
    cpi_yoy: Optional[float] = None
    eff_funds: Optional[float] = None
    spread_2s10s: Optional[float] = None
    spread_2s10s_mom_3m: Optional[float] = None
    hy_oas: Optional[float] = None
    hy_oas_mom_2w: Optional[float] = None
    ig_oas: Optional[float] = None
    stock_bond_corr_60d: Optional[float] = None
    asof: Optional[_dt.date] = None
    notes: list = field(default_factory=list)

    def as_row(self) -> pd.DataFrame:
        d = {k: v for k, v in self.__dict__.items()
             if k not in ("notes", "asof")}
        return pd.DataFrame([d])


def _last(s: pd.Series):
    return None if s is None or s.empty else float(s.iloc[-1])


def _delta(s: pd.Series, sessions: int):
    if s is None or len(s.dropna()) <= sessions:
        return None
    s = s.dropna()
    return float(s.iloc[-1] - s.iloc[-1 - sessions])


def compute_signals(
    fred_api_key: str = "",
    fetch_fred: Callable = _inline_fetch_fred,
    fetch_prices: Callable = _inline_fetch_prices,
    start: str = "2015-01-01",
) -> SignalSet:
    """Pull the raw series and derive the two real yields + companions."""
    sig = SignalSet(asof=_dt.date.today())

    eff = fetch_fred(FRED_SERIES["eff_funds"], fred_api_key, start)
    cpi = fetch_fred(FRED_SERIES["cpi_index"], fred_api_key, start)
    r10 = fetch_fred(FRED_SERIES["real_10y"], fred_api_key, start)
    be10 = fetch_fred(FRED_SERIES["breakeven_10y"], fred_api_key, start)
    n10 = fetch_fred(FRED_SERIES["nom_10y"], fred_api_key, start)
    n2 = fetch_fred(FRED_SERIES["nom_2y"], fred_api_key, start)
    hy = fetch_fred(FRED_SERIES["hy_oas"], fred_api_key, start)
    ig = fetch_fred(FRED_SERIES["ig_oas"], fred_api_key, start)

    # --- CPI YoY from the index (resample to month-end so YoY is robust to
    #     whatever frequency the fetcher returns) ---
    if cpi is not None and not cpi.empty:
        cpi_m = cpi.resample("ME").last().dropna()
        if len(cpi_m) > 12:
            sig.cpi_yoy = _last(cpi_m.pct_change(12) * 100)

    sig.eff_funds = _last(eff)

    # --- SIGNAL 1: SHORT real policy rate (the repression gauge) ---
    if sig.eff_funds is not None and sig.cpi_yoy is not None:
        sig.short_real_rate = round(sig.eff_funds - sig.cpi_yoy, 2)

    # --- SIGNAL 2: LONG real yield level + momentum (duration gauge) ---
    sig.long_real_yield = _last(r10)
    sig.long_real_mom_3m = _delta(r10, 63)   # ~3 months of trading days

    sig.breakeven_10y = _last(be10)

    # --- 2s10s + its momentum ---
    if n10 is not None and n2 is not None and not n10.empty and not n2.empty:
        curve = (n10 - n2).dropna()
        sig.spread_2s10s = _last(curve)
        sig.spread_2s10s_mom_3m = _delta(curve, 63)

    # --- Credit spreads ---
    sig.hy_oas = _last(hy)
    sig.hy_oas_mom_2w = _delta(hy, 10)
    sig.ig_oas = _last(ig)

    # --- SIGNAL: stock/bond 60d correlation (the KMLM-sizing signal) ---
    spy = fetch_prices("SPY", "1y")
    tlt = fetch_prices("TLT", "1y")
    if spy is not None and tlt is not None and len(spy) > 65 and len(tlt) > 65:
        rets = pd.DataFrame({
            "spy": spy.pct_change(),
            "tlt": tlt.pct_change(),
        }).dropna()
        if len(rets) > 60:
            sig.stock_bond_corr_60d = round(
                float(rets["spy"].tail(60).corr(rets["tlt"].tail(60))), 2)

    return sig


# --------------------------------------------------------------------------- #
#  Fed reaction function: hard vs soft repression
# --------------------------------------------------------------------------- #
def fed_reaction_flag(sig: SignalSet) -> dict:
    """
    Soft repression  = Fed HOLDING/HIKING into above-target inflation, long real
                       yield positive (inflation overshoot erodes debt).
    Hard repression  = Fed CUTTING/CAPPING while inflation high AND long real
                       yield suppressed toward/below zero (yield-curve control).
    """
    inflation_hot = (sig.cpi_yoy or 0) > FED_TARGET_INFLATION + 0.5
    long_real = sig.long_real_yield
    long_real_pos = long_real is not None and long_real > 0.5

    if inflation_hot and long_real_pos:
        state = "SOFT repression (inflation overshoot)"
        detail = ("Fed tolerating / fighting above-target inflation while the "
                  "long end stays positive. Long duration is NOT safe here.")
    elif inflation_hot and long_real is not None and long_real < 0.25:
        state = "HARD repression (yield suppression / YCC risk)"
        detail = ("Long real yields pinned low despite hot inflation — classic "
                  "financial-repression signature. Nominal bonds bleed slowly.")
    else:
        state = "Not repressive"
        detail = "Inflation near target or real yields unremarkable."
    return {"state": state, "detail": detail}


# --------------------------------------------------------------------------- #
#  The 4-quadrant classifier
# --------------------------------------------------------------------------- #
def classify_regime(sig: SignalSet) -> dict:
    """Return the regime key, label, blurb, and drivers list."""
    drivers = []

    hy = sig.hy_oas
    hy_rising = (sig.hy_oas_mom_2w or 0) > 0.5
    long_mom = sig.long_real_mom_3m
    short_real = sig.short_real_rate
    curve_resteep = (sig.spread_2s10s_mom_3m or 0) > 0.15

    # 1) Liquidity crisis OVERRIDES everything else.
    if hy is not None and hy > 5.0 and hy_rising:
        drivers.append(f"HY OAS {hy:.2f}% and widening (> 500 bps)")
        if long_mom is not None and long_mom < 0:
            drivers.append("Long real yield falling (flight to quality)")
        return _regime("liquidity_crisis", drivers)

    # 2) Inflationary repression: neg short real + rising long real.
    if short_real is not None and short_real < 0 and (long_mom or 0) > 0:
        drivers.append(f"Short real rate {short_real:+.2f}% (negative)")
        drivers.append("Long real yield rising (duration headwind)")
        return _regime("inflationary_repression", drivers)

    # 3) Stagflation: neg short real + growth rolling over.
    if short_real is not None and short_real < 0 and curve_resteep:
        drivers.append(f"Short real rate {short_real:+.2f}% (negative)")
        drivers.append("2s10s re-steepening from inversion (growth risk)")
        return _regime("stagflation", drivers)

    # 4) Goldilocks: positive real, tight credit.
    if (short_real is not None and short_real >= 0
            and hy is not None and hy < 3.5):
        drivers.append(f"Short real rate {short_real:+.2f}% (positive)")
        drivers.append(f"HY OAS {hy:.2f}% (tight credit)")
        return _regime("goldilocks", drivers)

    drivers.append("Signals mixed / transitioning")
    return _regime("neutral", drivers)


def _regime(key: str, drivers: list) -> dict:
    r = REGIMES[key]
    return {"key": key, "label": r["label"], "blurb": r["blurb"],
            "drivers": drivers}


# --------------------------------------------------------------------------- #
#  Target weights for a regime
# --------------------------------------------------------------------------- #
def target_weights(regime_key: str) -> dict:
    """Apply the regime overlay to the base sleeve and renormalize to 100%."""
    w = dict(BASE_WEIGHTS)
    for t, d in REGIMES[regime_key]["overlay"].items():
        w[t] = max(0, w.get(t, 0) + d)
    total = sum(w.values())
    if total <= 0:
        return w
    return {t: round(v * 100 / total, 1) for t, v in w.items()}


# --------------------------------------------------------------------------- #
#  KMLM sizing signal (explicit, for the portfolio app)
# --------------------------------------------------------------------------- #
def kmlm_signal(sig: SignalSet) -> dict:
    """
    Trend-following (KMLM) wants sustained cross-asset trends, especially
    inflationary ones. Its single best 'own more of me' tell is the stock/bond
    correlation flipping POSITIVE (60/40 breaks). Choppy/mean-reverting tape and
    V-reversals are its enemy.
    """
    score = 0
    reasons = []
    corr = sig.stock_bond_corr_60d
    if corr is not None:
        if corr > 0.2:
            score += 2
            reasons.append(f"Stock/bond corr {corr:+.2f} POSITIVE — 60/40 "
                           "breaking, trend earns its keep (INCREASE)")
        elif corr < -0.3:
            score -= 1
            reasons.append(f"Stock/bond corr {corr:+.2f} strongly negative — "
                           "diversification working, less need for trend")

    if sig.cpi_yoy is not None and sig.short_real_rate is not None:
        if sig.cpi_yoy > FED_TARGET_INFLATION and sig.short_real_rate < 0:
            score += 1
            reasons.append("Inflation above target with negative short real "
                           "rate — inflationary trend backdrop (INCREASE)")

    if (sig.long_real_mom_3m or 0) > 0:
        score += 1
        reasons.append("Long real yields rising (bond downtrend) — trend "
                       "tailwind (INCREASE)")

    if score >= 3:
        stance = "INCREASE KMLM"
        funding = ("Fund from CASH first (SGOV/USFR — they bleed negative real "
                   "return), then rate-sensitive growth (SMH/QQQ). Do NOT sell "
                   "metals/energy in this regime.")
    elif score <= 0:
        stance = "REDUCE KMLM"
        funding = ("Rotate proceeds back to growth (VGT/QQQ) or cash. Trend is "
                   "prone to whipsaw in this tape.")
    else:
        stance = "HOLD KMLM"
        funding = "No change warranted yet."

    return {"stance": stance, "score": score, "reasons": reasons,
            "funding": funding}


# --------------------------------------------------------------------------- #
#  One-call convenience for either app
# --------------------------------------------------------------------------- #
def full_assessment(fred_api_key: str = "", **kw) -> dict:
    sig = compute_signals(fred_api_key, **kw)
    regime = classify_regime(sig)
    return {
        "signals": sig,
        "regime": regime,
        "fed": fed_reaction_flag(sig),
        "targets": target_weights(regime["key"]),
        "kmlm": kmlm_signal(sig),
    }
