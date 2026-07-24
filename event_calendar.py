"""
event_calendar.py  (v1 — July 2026)   ── CLOSES GAP G5
──────────────────────────────────────────────────────────────────────────────
Daily Step 8: "No NEW entries the day before a binary event for the affected
sleeve; no short premium entered into earnings with elevated IVR."

WHY AUTOMATE SOMETHING YOU COULD LOOK UP
  Because the rule fires on the day you are least likely to check. Event risk
  is asymmetric in a specific way: entering the day before surrenders your risk
  control (the stop, which gaps) and your edge (IV rank, which crushes)
  simultaneously. The cost of missing the check is concentrated in exactly the
  handful of sessions per quarter when it matters most.

WHAT IS SCHEDULED vs WHAT IS NOT
  FOMC, CPI, PCE and payrolls dates are published in advance — they are
  hardcoded here, dated, and flagged for annual re-verification. Wrong dates
  would be worse than none, so the vintage is always displayed.

  Per-holding earnings dates are not centrally published for free. yfinance
  exposes an estimated next-earnings date per ticker, which is usually right
  and occasionally stale — treated as ADVISORY here, never authoritative.

⚠ RE-VERIFY EVERY JANUARY
  federalreserve.gov/monetarypolicy/fomccalendars.htm
  bls.gov/schedule/news_release/cpi.htm
  bea.gov/news/schedule
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

CALENDAR_ASOF = "2026-01-15"

# FOMC decision days (second day of each two-day meeting)
FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
             "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16"]

# CPI release days (BLS, ~8:30am ET)
CPI_2026 = ["2026-01-13", "2026-02-11", "2026-03-11", "2026-04-10",
            "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
            "2026-09-11", "2026-10-13", "2026-11-10", "2026-12-10"]

# PCE (BEA) and nonfarm payrolls (BLS, first Friday typically)
PCE_2026 = ["2026-01-30", "2026-02-27", "2026-03-27", "2026-04-30",
            "2026-05-29", "2026-06-26", "2026-07-31", "2026-08-28",
            "2026-09-25", "2026-10-30", "2026-11-25", "2026-12-23"]
NFP_2026 = ["2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
            "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
            "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04"]

EVENT_SLEEVES = {
    "FOMC": "ALL — especially USFR/SGOV (front end) and TLT (duration)",
    "CPI":  "ALL — moves the SHORT real rate, the regime's first input",
    "PCE":  "Rates-sensitive sleeves",
    "NFP":  "Rates-sensitive sleeves and growth",
}


def _parse(ds: list[str]) -> list[date]:
    out = []
    for d in ds:
        try:
            out.append(datetime.strptime(d, "%Y-%m-%d").date())
        except ValueError:
            continue
    return out


def upcoming_macro(within_days: int = 7, today: date | None = None) -> list[dict]:
    """Scheduled macro events inside the window, nearest first."""
    t = today or date.today()
    events = []
    for name, dates in (("FOMC", FOMC_2026), ("CPI", CPI_2026),
                        ("PCE", PCE_2026), ("NFP", NFP_2026)):
        for d in _parse(dates):
            days = (d - t).days
            if 0 <= days <= within_days:
                events.append({
                    "event": name, "date": d.isoformat(), "days_away": days,
                    "affects": EVENT_SLEEVES[name],
                    # The checklist's rule is 24–48h, so ≤2 days is the blackout
                    "blackout": days <= 2,
                })
    return sorted(events, key=lambda e: e["days_away"])


def earnings_dates(tickers: list[str]) -> dict:
    """
    Best-effort next-earnings date per ticker. ADVISORY ONLY.

    yfinance's estimate is usually correct and sometimes stale. A missing or
    wrong date must never be read as "no earnings" — confirm anything inside
    the 48h window against the company's IR page before entering.
    """
    out = {}
    try:
        import yfinance as yf
    except ImportError:
        return out
    for tk in tickers:
        try:
            cal = yf.Ticker(tk).calendar
            dt = None
            if isinstance(cal, dict):
                v = cal.get("Earnings Date")
                if isinstance(v, (list, tuple)) and v:
                    dt = v[0]
                elif v:
                    dt = v
            elif isinstance(cal, pd.DataFrame) and not cal.empty:
                if "Earnings Date" in cal.index:
                    dt = cal.loc["Earnings Date"].iloc[0]
            if dt is not None:
                d = pd.to_datetime(dt).date()
                out[tk] = {"date": d.isoformat(), "days_away": (d - date.today()).days}
        except Exception:
            continue
    return out


def event_check(holdings: list[str] | None = None, within_days: int = 7) -> dict:
    """
    ⭐ The Daily Step 8 answer: is a new entry authorized right now?

    Returns clear_for_entry plus the specific reason when it is False.
    """
    macro = upcoming_macro(within_days)
    blackout = [e for e in macro if e["blackout"]]

    earn_flags = []
    if holdings:
        for tk, info in earnings_dates(holdings).items():
            if 0 <= info["days_away"] <= 2:
                earn_flags.append({"ticker": tk, **info})

    clear = not blackout and not earn_flags
    reasons = ([f"{e['event']} in {e['days_away']}d ({e['date']})" for e in blackout]
               + [f"{e['ticker']} earnings in {e['days_away']}d" for e in earn_flags])

    return {
        "clear_for_entry": clear,
        "blackout_events": blackout,
        "earnings_flags": earn_flags,
        "upcoming": macro,
        "calendar_asof": CALENDAR_ASOF,
        "message": ("✅ No binary events within 48h — new entries authorized on "
                    "setup quality." if clear else
                    "🚫 NO NEW ENTRIES in affected sleeves: " + "; ".join(reasons) +
                    ". Event days gap through stops and crush IV — entering now "
                    "surrenders both your risk control and your edge. Existing "
                    "positions with proper stops are fine; the rule is about NEW risk."),
        "caveat": (f"Macro dates hardcoded as-of {CALENDAR_ASOF} — re-verify each "
                   f"January at federalreserve.gov and bls.gov. Earnings dates are "
                   f"yfinance estimates and are advisory, not authoritative."),
    }
