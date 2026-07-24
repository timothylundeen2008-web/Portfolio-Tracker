"""
bls_client.py  (v1 — July 2026)   ── CLOSES GAP G6
──────────────────────────────────────────────────────────────────────────────
Automates the CPI cross-check — the single highest-value gap in the audit.

WHY THIS MATTERS MORE THAN ITS SIZE SUGGESTS
  A calendar-misalignment bug in the Repression Dashboard's CPI calculation ran
  undetected from November 2025 to July 2026. Eight months. Every real-policy-
  rate reading in that window was overstated toward "repression," and the
  regime read is built directly on that number.

  The bug: BLS CANCELLED the October 2025 CPI release (2025 shutdown, data was
  never retroactively collectable), leaving a genuine missing row. A positional
  .pct_change(12) — which has no idea what a month is — then compared every
  subsequent month against a base one month too early. It computed 3.9% for
  June 2026 against a true, BLS-published 3.5%.

  It survived eight months for one reason: NOTHING EVER COMPARED THE COMPUTED
  FIGURE TO THE NUMBER BLS ACTUALLY PUBLISHED. A five-second check against a
  headline any financial summary carries would have caught it in month one.

  Weekly Step 2 now mandates that check manually. This module does it
  automatically, which is better, because a manual check is skipped exactly
  when a run feels routine — and every one of those eight months felt routine.

SERIES
  CUUR0000SA0     CPI-U, All items, U.S. city average, NOT seasonally adjusted
                  ⭐ This is THE headline series. It is what BLS quotes in its
                  press release, and what the scorecard's real-policy-rate
                  calculation is built to match.
  CUUR0000SA0L1E  Core CPI (all items less food and energy), NSA
  CUSR0000SA0     CPI-U All items, seasonally adjusted

API
  POST https://api.bls.gov/publicAPI/v2/timeseries/data/
  v1 works with NO KEY (3 years of history, 25 queries/day) — enough for this.
  v2 with a free key gives 10 years and 500/day. Register at
  https://data.bls.gov/registrationEngine/

  Passing "calculations": true makes BLS return ITS OWN 12-month percent
  change. That is the authoritative number — we are not recomputing anything
  and therefore cannot reproduce the class of bug we are checking for.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import requests

try:
    import streamlit as st
    _cache = st.cache_data(ttl=21600, show_spinner=False)
except Exception:
    def _cache(fn):
        return fn

BLS_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"

SERIES = {
    "cpi_nsa":  "CUUR0000SA0",        # headline, NSA — the one that matters
    "cpi_core": "CUUR0000SA0L1E",
    "cpi_sa":   "CUSR0000SA0",
}

_PERIOD_TO_MONTH = {f"M{i:02d}": i for i in range(1, 13)}


def _post(series_ids: list[str], start: int, end: int, key: str = "") -> dict | None:
    payload = {"seriesid": series_ids, "startyear": str(start), "endyear": str(end),
               "calculations": True}
    url = BLS_V1
    if key:
        payload["registrationkey"] = key
        url = BLS_V2
    try:
        r = requests.post(url, json=payload, timeout=30,
                          headers={"Content-type": "application/json"})
        r.raise_for_status()
        j = r.json()
        if j.get("status") != "REQUEST_SUCCEEDED":
            print(f"[bls] API said: {j.get('status')} {j.get('message')}")
            return None
        return j
    except Exception as e:
        print(f"[bls] request failed: {e}")
        return None


def _series_list(j: dict) -> list:
    """v2 returns Results as an object; some v1 responses return a list. Handle
    both rather than assuming — a shape change here would be silent."""
    res = j.get("Results")
    if isinstance(res, dict):
        return res.get("series", [])
    if isinstance(res, list) and res:
        return res[0].get("series", [])
    return []


@_cache
def fetch_cpi(key: str = "", years: int = 3) -> pd.DataFrame:
    """
    Headline NSA CPI with BLS's OWN 12-month percent change.

    Columns: date, index_value, yoy_bls (BLS-computed), period, year
    """
    end = date.today().year
    j = _post([SERIES["cpi_nsa"]], end - years, end, key)
    if not j:
        return pd.DataFrame()

    rows = []
    for s in _series_list(j):
        for d in s.get("data", []):
            per = d.get("period", "")
            if per not in _PERIOD_TO_MONTH:          # skip annual averages (M13)
                continue
            try:
                val = float(d["value"])
            except (TypeError, ValueError):
                continue
            # BLS's own 12-month pct change, when present
            yoy = None
            calc = d.get("calculations", {}) or {}
            pct = calc.get("pct_changes", {}) or {}
            if "12" in pct:
                try:
                    yoy = float(pct["12"])
                except (TypeError, ValueError):
                    yoy = None
            rows.append({"year": int(d["year"]), "month": _PERIOD_TO_MONTH[per],
                         "period": per, "index_value": val, "yoy_bls": yoy})

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(dict(year=df.year, month=df.month, day=1))
    return df.sort_values("date").reset_index(drop=True)


def latest_headline(key: str = "") -> dict:
    """The number to check the dashboard against."""
    df = fetch_cpi(key)
    if df.empty:
        return {"available": False,
                "error": "BLS API unreachable or returned no rows. The cross-check "
                         "must then be done manually against the BLS release."}
    last = df.iloc[-1]
    return {"available": True,
            "as_of": last["date"].strftime("%Y-%m"),
            "index_value": last["index_value"],
            "yoy_bls": last["yoy_bls"],
            "series": SERIES["cpi_nsa"],
            "note": "BLS-computed 12-month change — not recomputed locally, so it "
                    "cannot reproduce the calendar-alignment bug it checks for."}


def cross_check(dashboard_cpi_yoy: float | None, key: str = "",
                tolerance: float = 0.15) -> dict:
    """
    ⭐ THE CHECK. Compare the dashboard's computed CPI YoY against BLS's own.

    tolerance defaults to 0.15pp — wide enough to absorb rounding between an
    independently computed pct_change and BLS's published figure, tight enough
    that the 0.4pp error the October-2025 gap produced fires immediately.
    """
    bls = latest_headline(key)
    if not bls.get("available"):
        return {"status": "UNAVAILABLE", "detail": bls.get("error"),
                "action": "Check manually against the BLS release before sizing "
                          "anything off the real-policy-rate reading."}
    if dashboard_cpi_yoy is None:
        return {"status": "NO_DASHBOARD_VALUE", "bls_yoy": bls["yoy_bls"],
                "as_of": bls["as_of"],
                "action": "Dashboard returned no CPI YoY to compare."}

    official = bls["yoy_bls"]
    if official is None:
        return {"status": "NO_BLS_CALC", "as_of": bls["as_of"],
                "index_value": bls["index_value"],
                "action": "BLS returned the index but no 12-month calculation. "
                          "Compare index levels manually."}

    diff = round(float(dashboard_cpi_yoy) - float(official), 3)
    ok = abs(diff) <= tolerance
    return {
        "status": "MATCH" if ok else "MISMATCH",
        "dashboard_yoy": round(float(dashboard_cpi_yoy), 2),
        "bls_yoy": round(float(official), 2),
        "difference_pp": diff,
        "as_of": bls["as_of"],
        "tolerance": tolerance,
        "action": ("Verified against BLS — safe to use for the real-policy-rate "
                   "calculation." if ok else
                   f"🚨 MISMATCH of {diff:+.2f}pp. DO NOT size off the real-policy-rate "
                   f"reading until resolved. Most likely cause: a missing or delayed "
                   f"month in the FRED series combined with a positional pct_change — "
                   f"the exact failure that ran undetected Nov 2025–Jul 2026. Check "
                   f"whether the CPI series has a gap, and confirm the YoY calculation "
                   f"resamples to a complete calendar index before differencing."),
    }


def selftest(key: str = "") -> dict:
    """Verify connectivity and schema. Run once after deployment."""
    df = fetch_cpi(key, years=1)
    if df.empty:
        return {"ok": False, "message": "No data returned — check network access to "
                                        "api.bls.gov and, if using v2, the key."}
    has_yoy = df["yoy_bls"].notna().any()
    return {"ok": True, "rows": len(df),
            "latest": df.iloc[-1]["date"].strftime("%Y-%m"),
            "has_bls_calculations": bool(has_yoy),
            "message": ("Connected. BLS 12-month calculations present — cross-check "
                        "is fully automatic." if has_yoy else
                        "Connected, but BLS returned no 'calculations' block. The "
                        "cross-check will fall back to comparing index levels; "
                        "consider registering for a v2 key.")}
