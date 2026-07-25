"""
treasury_data.py  (v1 — July 2026)   ── CLOSES GAPS G2 and G3
──────────────────────────────────────────────────────────────────────────────
Two Treasury-market checks the checklist asks for but nothing computed.

G2 — AUCTION BID-TO-COVER (Daily Step 4)
  Auction demand is a leading indicator of debt-sustainability stress: the same
  category of signal as HY spread velocity, but for the Treasury market itself.
  The checklist is explicit that a SINGLE weak print is noise — dealer
  positioning, a heavy concurrent corporate calendar, and settlement mechanics
  all distort one auction. The trend across 2–3 consecutive auctions is signal.
  This module therefore reports the trailing series and its trend, not a number.

  Source: TreasuryDirect TA_WS API. Free, no key. Field: bidToCoverRatio.

G3 — BULL STEEPENING (Daily Step 5)
  Steepening FROM inversion driven by the 2-year COLLAPSING means the market is
  pricing the Fed cutting into deterioration — historically the most violent
  regime-shift signal there is, and the checklist says it demands immediate
  reallocation review rather than a note for the weekend.

  Distinguishing bull from bear steepening needs the 2-year LEVEL and its
  VELOCITY, not just the 2s10s spread. DGS2 is already on FRED, so this was
  always closeable — it simply had not been wired.

⚠ VERIFY ON FIRST RUN
  The TreasuryDirect endpoint shape is documented but could not be reached from
  the build environment. Run selftest() once after deploying. It reports exactly
  what it found so the constants can be corrected, and fails loudly rather than
  returning a plausible wrong number.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import requests

try:
    import streamlit as st
    _cache = st.cache_data(ttl=21600, show_spinner=False)
except Exception:
    def _cache(fn):
        return fn

TD_BASE = "https://www.treasurydirect.gov/TA_WS/securities"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"

SOFT_BTC = 2.30          # below this = softening (checklist Daily Step 4)
STRESSED_BTC = 2.00      # below this = stressed
_HEADERS = {"User-Agent": "AllWeatherDashboard/1.0 (research)"}


# ─────────────────────────────────────────────────────────────────────────────
#  G2 — AUCTION DEMAND
# ─────────────────────────────────────────────────────────────────────────────

@_cache
def fetch_auctions(security_type: str = "Note", days: int = 400) -> pd.DataFrame:
    """
    Recent auction results.

    Returns: auction_date, security_term, cusip, bid_to_cover, offering_amt
    Empty DataFrame on any failure — callers must treat empty as "unknown",
    never as "no stress".
    """
    url = f"{TD_BASE}/auctioned"
    params = {"format": "json", "type": security_type, "days": days}
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[treasury] auction fetch failed: {e}")
        return pd.DataFrame()

    if not isinstance(data, list) or not data:
        return pd.DataFrame()

    rows = []
    for d in data:
        btc = d.get("bidToCoverRatio")
        try:
            btc = float(btc) if btc not in (None, "") else None
        except (TypeError, ValueError):
            btc = None
        if btc is None:
            continue
        try:
            adate = pd.to_datetime(str(d.get("auctionDate", ""))[:10])
        except Exception:
            continue
        rows.append({"auction_date": adate,
                     "security_type": d.get("securityType"),
                     "security_term": d.get("securityTerm"),
                     "cusip": d.get("cusip"),
                     "bid_to_cover": btc,
                     "offering_amt": d.get("offeringAmount")})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("auction_date").reset_index(drop=True)


def auction_demand(term: str = "10-Year", lookback: int = 4) -> dict:
    """
    Bid-to-cover trend for one tenor.

    Deliberately returns a TREND, not a reading. The checklist's own rule is
    that two-plus consecutive soft auctions is the threshold for a weekly
    discussion, and one print is never a same-day trigger.
    """
    df = fetch_auctions("Note")
    if df.empty:
        return {"available": False,
                "message": "TreasuryDirect returned no data — record bid-to-cover "
                           "manually on auction days. Unknown is not the same as calm."}

    sel = df[df["security_term"].astype(str).str.strip() == term]
    if sel.empty:
        terms = sorted(df["security_term"].dropna().unique())[:10]
        return {"available": False,
                "message": f"No {term} auctions found. Available terms: {terms}"}

    recent = sel.tail(lookback)
    latest = recent.iloc[-1]
    btc = float(latest["bid_to_cover"])
    avg = float(recent["bid_to_cover"].mean())

    if btc < STRESSED_BTC:
        level = "STRESSED"
    elif btc < SOFT_BTC:
        level = "SOFTENING"
    else:
        level = "NORMAL"

    soft_run = 0
    for v in reversed(recent["bid_to_cover"].tolist()):
        if v < SOFT_BTC:
            soft_run += 1
        else:
            break

    trend = "flat"
    if len(recent) >= 3:
        x = np.arange(len(recent))
        slope = float(np.polyfit(x, recent["bid_to_cover"].to_numpy(), 1)[0])
        trend = "deteriorating" if slope < -0.05 else "improving" if slope > 0.05 else "flat"

    return {"available": True, "term": term,
            "latest_date": latest["auction_date"].date().isoformat(),
            "latest_btc": round(btc, 2), "trailing_avg": round(avg, 2),
            "level": level, "trend": trend, "consecutive_soft": soft_run,
            "history": recent[["auction_date", "bid_to_cover"]].to_dict("records"),
            "message": (f"{term}: {btc:.2f} ({level}), {lookback}-auction avg "
                        f"{avg:.2f}, trend {trend}."
                        + (f" ⚠ {soft_run} consecutive auctions below {SOFT_BTC} — "
                           f"raise at the weekly review." if soft_run >= 2 else
                           " Single prints are noise; the trend is the signal."))}


# ─────────────────────────────────────────────────────────────────────────────
#  G3 — BULL vs BEAR STEEPENING
# ─────────────────────────────────────────────────────────────────────────────

def _fred_series(series_id: str, start: str = "2023-01-01",
                 api_key: str = "") -> pd.Series:
    """
    Fetch one FRED series.

    ⚠ HISTORICAL BUG, FIXED HERE: this function previously called ONLY the
    keyless CSV endpoint, with no api_key parameter and no fallback to the
    authenticated API. That meant curve_signal() (bull/bear steepening,
    Daily Step 5) could NEVER benefit from a FRED_API_KEY no matter how it was
    set — it simply never read one. If the keyless CSV endpoint is blocked or
    throttled on a given host, this item was unavailable with no way to fix it
    short of editing code. It now tries fred_client (API-first when a key is
    present, keyless CSV fallback) and only falls back to the original
    direct-CSV call if fred_client itself is unavailable.
    """
    try:
        from fred_client import fetch_fred as _ff
        s = _ff(series_id, api_key, start)
        if s is not None and not s.empty:
            return s
    except ImportError:
        pass
    except Exception as e:
        print(f"[treasury] fred_client path failed for {series_id}: {e}")

    # Fallback: original direct keyless CSV call, in case fred_client.py isn't
    # deployed yet. Kept so this module still degrades gracefully on its own.
    try:
        r = requests.get(FRED_CSV, params={"id": series_id, "cosd": start},
                         headers=_HEADERS, timeout=30)
        r.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(r.text))
        dcol, vcol = df.columns[0], df.columns[1]
        df[vcol] = pd.to_numeric(df[vcol], errors="coerce")
        s = pd.Series(df[vcol].values, index=pd.to_datetime(df[dcol])).dropna()
        return s
    except Exception as e:
        print(f"[treasury] direct CSV also failed for {series_id}: {e}")
        return pd.Series(dtype=float)


@_cache
def curve_signal(lookback_days: int = 10, api_key: str = "") -> dict:
    """
    Classify the curve move — the distinction Daily Step 5 actually asks for.

      BULL STEEPENING   2y falling fast, spread widening
                        → Fed cutting into deterioration. The violent one.
                          Demands immediate reallocation review.
      BEAR STEEPENING   10y rising faster than 2y
                        → term premium / inflation / supply concern.
      BULL FLATTENING   10y falling faster → growth scare, duration bid.
      BEAR FLATTENING   2y rising faster → Fed hiking expectations.
    """
    two, ten = (_fred_series("DGS2", api_key=api_key),
               _fred_series("DGS10", api_key=api_key))
    if two.empty or ten.empty:
        return {"available": False,
                "message": "FRED unavailable — classify the curve move manually."}

    spread = (ten - two).dropna()
    if len(spread) < lookback_days + 1 or len(two) < lookback_days + 1:
        return {"available": False, "message": "Insufficient curve history."}

    d2 = float(two.iloc[-1] - two.iloc[-1 - lookback_days])
    d10 = float(ten.iloc[-1] - ten.iloc[-1 - lookback_days])
    dspread = float(spread.iloc[-1] - spread.iloc[-1 - lookback_days])
    steepening = dspread > 0.05
    flattening = dspread < -0.05

    if steepening and d2 < -0.10:
        regime, urgency = "BULL STEEPENING", "HIGH"
        note = ("2-year collapsing while the curve widens — the market is pricing the "
                "Fed cutting INTO deterioration. Historically the most violent "
                "regime-shift signal there is. Daily Step 5: this demands an immediate "
                "reallocation review, not a note for the weekend.")
    elif steepening and d10 > 0.10:
        regime, urgency = "BEAR STEEPENING", "MEDIUM"
        note = ("Long end selling off faster than the front — term premium, inflation, "
                "or supply concern rather than a growth call. Cross-check against the "
                "DXY divergence in Daily Step 4: yields up with the dollar down is the "
                "debt-confidence signature.")
    elif flattening and d10 < -0.10:
        regime, urgency = "BULL FLATTENING", "MEDIUM"
        note = "Long end rallying — growth scare or duration bid. Watch DFII10 momentum."
    elif flattening and d2 > 0.10:
        regime, urgency = "BEAR FLATTENING", "LOW"
        note = "Front end repricing hawkish — supports the USFR overweight."
    else:
        regime, urgency = "NO CLEAR SIGNAL", "LOW"
        note = ("Move is within noise. The checklist's own filter applies: moves that "
                "revert within 1–2 weeks are noise, only sustained moves are signal.")

    return {"available": True, "regime": regime, "urgency": urgency,
            "spread_now": round(float(spread.iloc[-1]), 3),
            "spread_chg": round(dspread, 3),
            "two_yr": round(float(two.iloc[-1]), 3), "two_yr_chg": round(d2, 3),
            "ten_yr": round(float(ten.iloc[-1]), 3), "ten_yr_chg": round(d10, 3),
            "lookback_days": lookback_days, "note": note,
            "message": f"{regime} — 2y {d2:+.2f}pp, 10y {d10:+.2f}pp, "
                       f"spread {dspread:+.2f}pp over {lookback_days} sessions."}


def selftest() -> dict:
    """Verify both endpoints. Run once after deployment."""
    out = {}
    a = fetch_auctions("Note", days=200)
    out["auctions"] = {
        "ok": not a.empty, "rows": len(a),
        "terms_found": sorted(a["security_term"].dropna().unique().tolist())[:8] if not a.empty else [],
        "message": ("TreasuryDirect reachable." if not a.empty else
                    "TreasuryDirect returned nothing. Verify the endpoint at "
                    "treasurydirect.gov/TA_WS/securities/auctioned?format=json&type=Note "
                    "— if the shape has changed, correct TD_BASE/params here. The "
                    "Fiscal Data API (fiscaldata.treasury.gov, dataset "
                    "'treasury-securities-auctions-data') is an alternative source.")}
    c = curve_signal()
    out["curve"] = {"ok": c.get("available", False), "message": c.get("message")}
    return out
