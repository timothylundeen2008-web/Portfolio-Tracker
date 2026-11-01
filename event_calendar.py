"""
event_calendar.py  (v1.2 — Nov 2026: elections computed, 2027 dates, coverage check)   ── CLOSES GAP G5
──────────────────────────────────────────────────────────────────────────────
v1.2 (2026-11-01, fix_status N23):
  * US federal elections are COMPUTED from their legal rule (the Tuesday
    after the first Monday in November, even years), never typed, so they
    cannot go out of date: 2026-11-03 (midterms), 2028-11-07, ...
  * 2027 CPI, payrolls, PCE and GDP dates added, each copied from the
    official schedule page and cross-checked against a second official page
    on 2026-11-01 (sources beside each list). Until now 2027 had only FOMC,
    so CPI and payroll blackouts would have silently stopped in January.
  * coverage(): how far ahead each typed list runs. WARN within
    COVERAGE_WARN_DAYS of a list's last date, STALE once it has none ahead.
    The brief's data-health row reports it, so a list running out is seen
    weeks before it bites, not after.

Daily Step 8: "No NEW entries the day before a binary event for the affected
sleeve; no short premium entered into earnings with elevated IVR."

WHY AUTOMATE SOMETHING YOU COULD LOOK UP
  Because the rule fires on the day you are least likely to check. Event risk
  is asymmetric in a specific way: entering the day before surrenders your risk
  control (the stop, which gaps) and your edge (IV rank, which crushes)
  simultaneously. The cost of missing the check is concentrated in exactly the
  handful of sessions per quarter when it matters most.

WHAT IS SCHEDULED vs WHAT IS NOT
  FOMC, CPI, PCE, GDP and payrolls dates are published in advance — they are
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

CALENDAR_ASOF = "2026-11-01"
COVERAGE_WARN_DAYS = 45      # warn this long before a typed list runs out

# FOMC decision days (second day of each two-day meeting).
# v1.1 (2026-10-24): the last two 2026 dates were WRONG (11-04 / 12-16). The
# Fed's calendar says Oct 27-28 and Dec 8-9, so no blackout fired before the
# October meeting. Verified at federalreserve.gov/monetarypolicy/fomccalendars.htm.
FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
             "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]
# 2027 per the same page ("each meeting date is tentative until confirmed at
# the meeting immediately preceding it").
FOMC_2027 = ["2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
             "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08"]
FOMC_ALL = FOMC_2026 + FOMC_2027

# CPI release days (BLS, ~8:30am ET)
CPI_2026 = ["2026-01-13", "2026-02-11", "2026-03-11", "2026-04-10",
            "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
            "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10"]   # Oct 14 per bls.gov/schedule/2026
# 2027: bls.gov/schedule/news_release/cpi.htm, cross-checked with bls.gov/schedule/2027/home.htm (2026-11-01)
CPI_2027 = ["2027-01-13", "2027-02-11", "2027-03-10", "2027-04-13",
            "2027-05-12", "2027-06-10", "2027-07-14", "2027-08-11",
            "2027-09-14", "2027-10-14", "2027-11-10", "2027-12-10"]

# PCE (BEA) and nonfarm payrolls (BLS, first Friday typically)
PCE_2026 = ["2026-01-30", "2026-02-27", "2026-03-27", "2026-04-30",
            "2026-05-29", "2026-06-26", "2026-07-31", "2026-08-28",
            "2026-09-25", "2026-10-29", "2026-11-25", "2026-12-23"]   # Oct 29 per bea.gov/news/schedule
NFP_2026 = ["2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
            "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
            "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04"]
# 2027: bls.gov/schedule/news_release/empsit.htm, cross-checked with bls.gov/schedule/2027/home.htm (2026-11-01)
NFP_2027 = ["2027-01-08", "2027-02-05", "2027-03-05", "2027-04-02",
            "2027-05-07", "2027-06-04", "2027-07-02", "2027-08-06",
            "2027-09-03", "2027-10-08", "2027-11-05", "2027-12-03"]
# 2027 Personal Income and Outlays: bea.gov/news/schedule/next-year ("Year 2027"), cross-checked against
# eleven individual BEA release pages (BEA 27-06 ... 27-46) on 2026-11-01. Since 2026 it is released
# the same morning as GDP.
PCE_2027 = ["2027-01-28", "2027-02-25", "2027-03-31", "2027-04-29",
            "2027-05-27", "2027-06-25", "2027-07-29", "2027-08-25",
            "2027-09-30", "2027-10-28", "2027-11-24", "2027-12-22"]

# GDP estimates (BEA, 8:30am ET) — added v1.1; previously untracked.
# Advance / second / third, per bea.gov/news/schedule.
GDP_2026 = ["2026-02-20", "2026-03-13", "2026-04-09", "2026-04-30",
            "2026-05-28", "2026-06-25", "2026-07-30", "2026-08-26",
            "2026-09-30", "2026-10-29", "2026-11-25", "2026-12-23"]
# 2027 (advance / second / third, by quarter): bea.gov/news/schedule/next-year, 2026-11-01
GDP_2027 = ["2027-01-28", "2027-02-25", "2027-03-31", "2027-04-29",
            "2027-05-27", "2027-06-25", "2027-07-29", "2027-08-25",
            "2027-09-30", "2027-10-28", "2027-11-24", "2027-12-22"]

# Typed schedules, by event. coverage() reports how far ahead each runs.
SCHEDULES = {"FOMC": FOMC_ALL, "CPI": CPI_2026 + CPI_2027, "PCE": PCE_2026 + PCE_2027,
             "NFP": NFP_2026 + NFP_2027, "GDP": GDP_2026 + GDP_2027}
SCHEDULE_SOURCES = {
    "FOMC": "federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "CPI": "bls.gov/schedule/news_release/cpi.htm",
    "NFP": "bls.gov/schedule/news_release/empsit.htm",
    "PCE": "bea.gov/news/schedule",
    "GDP": "bea.gov/news/schedule",
}

EVENT_SLEEVES = {
    "FOMC": "ALL — especially USFR/SGOV (front end) and TLT (duration)",
    "CPI":  "ALL — moves the SHORT real rate, the regime's first input",
    "PCE":  "Rates-sensitive sleeves",
    "NFP":  "Rates-sensitive sleeves and growth",
    "GDP":  "Growth sleeves and the growth axis of the regime read",
    "ELECTION": "ALL — results arrive after the close, so the next session can gap through stops",
}


def us_election_days(first_year: int, last_year: int) -> list:
    """US federal general elections: the Tuesday after the first Monday in
    November of every even year (2 U.S.C. 7). Computed, so never stale."""
    out = []
    for y in range(first_year + (first_year % 2), last_year + 1, 2):
        d = date(y, 11, 1)
        while d.weekday() != 0:              # first Monday
            d += timedelta(days=1)
        out.append(d + timedelta(days=1))
    return out


def _computed_events(t: date, within_days: int) -> list:
    """(name, date, label) for rule-computed events inside the window."""
    out = []
    for d in us_election_days(t.year, (t + timedelta(days=within_days)).year):
        kind = "presidential" if d.year % 4 == 0 else "midterm"
        out.append(("ELECTION", d, f"US {kind} election"))
    return out


def coverage(today: date | None = None, warn_days: int = COVERAGE_WARN_DAYS) -> dict:
    """How far ahead each typed schedule runs. Status per event: OK, WARN
    (last date within warn_days), STALE (no date ahead). Overall = worst.
    Computed events (elections) never expire and are not listed."""
    t = today or date.today()
    rank = {"OK": 0, "WARN": 1, "STALE": 2}
    rows = {}
    for name, ds in SCHEDULES.items():
        future = [d for d in _parse(ds) if d >= t]
        last = max(_parse(ds)) if ds else None
        if not future:
            st, left = "STALE", None
        else:
            left = (max(future) - t).days
            st = "WARN" if left <= warn_days else "OK"
        rows[name] = {"last": last.isoformat() if last else None, "days_left": left, "status": st,
                      "source": SCHEDULE_SOURCES.get(name, "")}
    worst = max((r["status"] for r in rows.values()), key=lambda x: rank[x]) if rows else "STALE"
    short = sorted((n for n, r in rows.items() if r["status"] != "OK"), key=lambda n: rows[n]["days_left"] or -1)
    through = min((r["last"] for r in rows.values() if r["last"]), default=None)
    note = (f"all typed schedules run through at least {through}; elections computed" if worst == "OK" else
            "; ".join(f"{n} {'has no date ahead' if rows[n]['status'] == 'STALE' else 'ends ' + rows[n]['last']}"
                      f" — add the next year from {rows[n]['source']}" for n in short))
    return {"status": worst, "events": rows, "through": through, "note": note, "asof": CALENDAR_ASOF}


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
    for name, dates in SCHEDULES.items():
        for d in _parse(dates):
            days = (d - t).days
            if 0 <= days <= within_days:
                events.append({
                    "event": name, "date": d.isoformat(), "days_away": days,
                    "affects": EVENT_SLEEVES[name],
                    # The checklist's rule is 24–48h, so ≤2 days is the blackout
                    "blackout": days <= 2,
                })
    for name, d, label in _computed_events(t, within_days):          # v1.2: elections
        days = (d - t).days
        if 0 <= days <= within_days:
            events.append({"event": name, "date": d.isoformat(), "days_away": days, "label": label,
                           "affects": EVENT_SLEEVES[name], "blackout": days <= 2, "computed": True})
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
        "caveat": (f"Macro dates typed from the official schedules, as of {CALENDAR_ASOF} "
                   f"(coverage: {coverage()['note']}). Elections are computed. Earnings dates are "
                   f"yfinance estimates and are advisory, not authoritative."),
    }


def selftest() -> dict:
    f = []
    if us_election_days(2024, 2030) != [date(2024, 11, 5), date(2026, 11, 3), date(2028, 11, 7), date(2030, 11, 5)]:
        f.append(f"election rule: {us_election_days(2024, 2030)}")
    if us_election_days(2022, 2022) != [date(2022, 11, 8)]:
        f.append("when Nov 1 is a Tuesday the election is a week later (2022: Nov 8, not Nov 1)")
    if us_election_days(2027, 2027) or us_election_days(2032, 2032) != [date(2032, 11, 2)]:
        f.append("no election in odd years; 2032 is Nov 2 (Nov 1 is the first Monday)")
    ev = upcoming_macro(10, today=date(2026, 11, 1))
    el = [e for e in ev if e["event"] == "ELECTION"]
    if len(el) != 1 or el[0]["date"] != "2026-11-03" or el[0]["blackout"] is not True or "midterm" not in el[0]["label"]:
        f.append(f"the 11/3 midterms must appear, inside the blackout, labelled midterm: {el}")
    if [e["event"] for e in ev][:2] != ["ELECTION", "NFP"]:
        f.append(f"events nearest first (election 11/3, payrolls 11/6): {[e['event'] for e in ev]}")
    if not [e for e in upcoming_macro(3, today=date(2027, 1, 11)) if e["event"] == "CPI" and e["date"] == "2027-01-13"]:
        f.append("2027 CPI must be scheduled (Jan 13)")
    for name, ds in SCHEDULES.items():
        ps = _parse(ds)
        if len(ps) != len(ds) or ps != sorted(ps) or len(set(ps)) != len(ps):
            f.append(f"{name}: every date must parse, in order, no duplicates")
        if any(d.weekday() >= 5 for d in ps):
            f.append(f"{name}: a release date falls on a weekend")
        if name != "FOMC" and sum(1 for d in ps if d.year == 2027) != 12:
            f.append(f"{name}: 2027 must have 12 releases")
    if set(SCHEDULES) - set(EVENT_SLEEVES) or set(SCHEDULES) - set(SCHEDULE_SOURCES):
        f.append("every schedule needs an EVENT_SLEEVES entry and a source")
    cv = coverage(date(2026, 11, 1))
    if cv["status"] != "OK" or cv["through"] != "2027-12-03":
        f.append(f"coverage today: OK through the earliest list end (payrolls 2027-12-03): {cv['status']} {cv['through']}")
    cw = coverage(date(2027, 11, 15))
    if cw["status"] != "WARN" or "add the next year" not in cw["note"]:
        f.append(f"45 days before lists end, coverage must WARN and say what to add: {cw}")
    cs = coverage(date(2028, 1, 5))
    if cs["status"] != "STALE" or not all(r["status"] == "STALE" for r in cs["events"].values()):
        f.append(f"with no date ahead, coverage must be STALE: {cs['status']}")
    if not [e for e in upcoming_macro(3, today=date(2028, 11, 5)) if e["event"] == "ELECTION"]:
        f.append("elections must keep appearing after every typed list has expired (computed, not typed)")
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(selftest(), indent=2))
