"""
engine_layer.py  (v1.0 — 2026-11-13)
────────────────────────────────────
The model book's switching layer: engine O11, adopted by Matt on 2026-11-13
("option 2") as an explicit, recorded exception to the offense-lab bar. O11
missed only 2005–15 (5.29% vs SPY 7.06%/yr); it beat SPY over 2000–2026
(9.51% vs 8.20%) with a −19.3% max drawdown, robust in 7 of 8 nearby settings.
See claude/offense_engine.md. It is still judged on its forward record.

WHAT IT DECIDES
  OFFENSE   50% QQQ / 50% SPY            while SPY and QQQ are above their 200-day
  BALANCED  the live regime book          when mixed, and after a fast exit
  DEFENSE   60% SGOV / 20% GLD / 20% TLT  while SPY is below its 200-day
  Fast out: QQQ below its 50-day for 2 closes AND credit (VWEHX/VFITX below its
  50-day for 2 closes) confirms, OR the Offense book −8% from its high since
  entry. Slow back in: SPY and QQQ above their 200-day and QQQ above its 50-day
  (2 closes each), and 20 sessions after a fast exit.

  The state machine is offense_lab.states_fast itself (no copy to drift).
  Timing as tested: the state seen at a session's close is traded the next
  session, so the weights booked on day d use the state of the session BEFORE d.

DATA
  Needs ~3 years of SPY, QQQ, VWEHX, VFITX closes (the state is path-dependent:
  the Offense high and the cooldown carry). Missing credit falls back to the
  plain 50-day exit (never holds Offense on a gap). Missing SPY or QQQ = no
  state: the caller keeps yesterday's state and says so (a gap is not a signal).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

import offense_lab as ol

VERSION = "v1.0"
ENGINE = "O11"
TICKERS = ("SPY", "QQQ", *ol.CREDIT_PAIR)
HISTORY = "5y"
WORDS = {"OFF": "OFFENSE", "BAL": "BALANCED", "DEF": "DEFENSE", "OUT": "FAST-EXIT (Balanced)"}


def _close(x) -> pd.Series:
    if x is None:
        return pd.Series(dtype=float)
    if isinstance(x, pd.DataFrame):
        x = x["Close"] if "Close" in x else x.iloc[:, 0]
    s = pd.Series(x).dropna().astype(float)
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def states(prices: dict) -> Optional[pd.Series]:
    """O11 state per session (value at d uses closes <= d). None if SPY/QQQ are missing."""
    spy, qqq = _close(prices.get("SPY")), _close(prices.get("QQQ"))
    if len(spy) < ol.MA + 5 or len(qqq) < ol.MA + 5:
        return None
    cal = spy.index
    lv = pd.DataFrame({"SPY": spy, "QQQ": qqq.reindex(cal).ffill(limit=3)}, index=cal)
    a, b = (_close(prices.get(t)) for t in ol.CREDIT_PAIR)
    lv["CREDIT"] = (a / b).reindex(cal).ffill(limit=3) if len(a) and len(b) else np.nan
    rets = lv[["SPY", "QQQ"]].pct_change()
    cand = ol.CANDIDATES[ENGINE]
    return ol.states_fast(lv, rets, ol.MA, credit=bool(cand.get("credit")))


def credit_ok(prices: dict) -> bool:
    return all(len(_close(prices.get(t))) > ol.CREDIT_SMA for t in ol.CREDIT_PAIR)


def state_for(st: Optional[pd.Series], d) -> Optional[str]:
    """The state that sets the weights booked on session d: the last state strictly before d."""
    if st is None or st.empty:
        return None
    prior = st[st.index < pd.Timestamp(d).normalize()]
    return str(prior.iloc[-1]) if len(prior) else None


def overlay(state: Optional[str], balanced: dict) -> dict:
    """The book for a state. BALANCED / FAST-EXIT / unknown -> the live regime book."""
    if state == "OFF":
        return dict(ol.OFFENSE_1X)
    if state == "DEF":
        return dict(ol.DEFENSE)
    return dict(balanced)


def read(st: Optional[pd.Series], prices: Optional[dict] = None) -> dict:
    """Today's read for the brief and alerts: state at the last close, since when, switch today."""
    if st is None or st.empty:
        return {"available": False, "engine": ENGINE,
                "conclusion": f"Engine {ENGINE} unavailable: SPY/QQQ history missing — yesterday's state is held."}
    now, prev = str(st.iloc[-1]), str(st.iloc[-2]) if len(st) > 1 else str(st.iloc[-1])
    since = st[st != now]
    out = {"available": True, "engine": ENGINE, "version": VERSION, "state": now, "word": WORDS.get(now, now),
           "asof": st.index[-1].date().isoformat(), "previous": prev, "switched": now != prev,
           "since": since.index[-1].date().isoformat() if len(since) else None,
           "credit_data": credit_ok(prices or {}) if prices is not None else None}
    if out["switched"]:
        out["conclusion"] = (f"Engine {ENGINE} SWITCHED {WORDS.get(prev, prev)} → {WORDS.get(now, now)} at the "
                             f"{out['asof']} close: the model book moves at the next session.")
    else:
        out["conclusion"] = f"Engine {ENGINE}: {WORDS.get(now, now)}" + (f" since {out['since']}" if out["since"] else "") + "."
    if out["credit_data"] is False:
        out["conclusion"] += " Credit funds missing: the 50-day exit runs without credit confirmation today."
    return out


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    f = []
    closes = ol._synthetic(n=1500)
    data = ol.build_data(closes)
    lab = ol.states("fast", data["levels"], ol.MA, rets=data["rets"], credit=True)
    st = states(closes)
    if st is None:
        f.append("states() returned None on complete data")
    else:
        common = st.index.intersection(lab.index)
        if not st.reindex(common).equals(lab.reindex(common)):
            f.append("engine_layer states must equal offense_lab O11 states")
        chg = [i for i in range(1, len(st)) if st.iloc[i] != st.iloc[i - 1]]
        if not chg:
            f.append("synthetic history produced no switch")
        else:
            i = chg[0]
            if state_for(st, st.index[i]) != st.iloc[i - 1] or state_for(st, st.index[i + 1]) != st.iloc[i]:
                f.append("weights on day d must use the state of the session before d (one-session lag)")
        r = read(st, closes)
        if not r["available"] or r["state"] != st.iloc[-1]:
            f.append("read(): today's state")
    bal = {"VGT": 50.0, "SGOV": 50.0}
    if overlay("OFF", bal) != ol.OFFENSE_1X or overlay("DEF", bal) != ol.DEFENSE or overlay("OUT", bal) != bal \
            or overlay("BAL", bal) != bal or overlay(None, bal) != bal:
        f.append("overlay mapping")
    if states({k: v for k, v in closes.items() if k != "QQQ"}) is not None:
        f.append("missing QQQ must give no state")
    no_credit = {k: v for k, v in closes.items() if k not in ol.CREDIT_PAIR}
    s2 = states(no_credit)
    lab_plain = ol.states("fast", data["levels"].drop(columns=["CREDIT"]), ol.MA, rets=data["rets"], credit=True)
    if s2 is None or not s2.equals(lab_plain.reindex(s2.index)):
        f.append("missing credit must fall back to the plain 50-day exit")
    if read(s2, no_credit)["credit_data"] is not False or "Credit funds missing" not in read(s2, no_credit)["conclusion"]:
        f.append("missing credit must be said")
    if read(None)["available"]:
        f.append("no state: read() must say unavailable")
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    import json
    import sys
    r = selftest()
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["ok"] else 1)
