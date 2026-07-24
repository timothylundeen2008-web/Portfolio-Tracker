"""
position_ledger.py  (v1 — July 2026)   ── CLOSES GAP G1
──────────────────────────────────────────────────────────────────────────────
What you actually own, what it risks, and where it exits.

WHY THIS IS THE BIGGEST GAP THE AUDIT FOUND
  Nothing in this system recorded holdings. Not entry prices, not stops, not
  share counts, not option DTEs. The consequence was that the checklist steps
  most directly connected to money were the ones with the least support:

    Daily Step 6   stop checks, options mechanics, 15% portfolio heat cap
    Weekly Step 7  position review, stop trailing, invalidation sentences
    Weekly Step 8  drift bands vs regime targets

  Five checklist items, all unusable, all about real risk rather than analysis.
  Portfolio heat in particular — the single number bounding how much a bad
  correlated week can cost — was literally not computable.

  Note the distinction Weekly Step 8 depends on: slider weights answer "does my
  INTENDED allocation match the regime target," which drifts by zero by
  construction. Only a real ledger answers "does my ACTUAL account match it,"
  which is the question band rebalancing exists to catch.

DESIGN
  - One row per position; options carry extra fields and are handled separately
  - ATR computed from live data, so "within 1 ATR of stop" is real
  - Heat = Σ (entry − stop) × shares ÷ equity, the checklist's own definition
  - Every position REQUIRES an invalidation sentence. Weekly Step 7: "if you
    cannot fill the blank, the position has no thesis — exit it." Enforced here
    rather than left to discipline.
  - Stops may never be lowered. The setter refuses, and says why.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

from storage_backend import read_df, write_df

LEDGER = "positions.csv"
OPTIONS = "options_book.csv"

COLUMNS = ["ticker", "shares", "entry_price", "entry_date", "stop", "stop_basis",
           "thesis", "invalidation", "sleeve", "last_updated"]
OPT_COLUMNS = ["ticker", "strategy", "expiry", "strike", "contracts",
               "credit_received", "opened_date", "notes", "last_updated"]

HEAT_CAP_PCT = 15.0            # Daily Step 6
DRIFT_BAND_REL = 0.20          # Weekly Step 8: ±20% RELATIVE


# ── Ledger CRUD ───────────────────────────────────────────────────────────────

def load_positions() -> pd.DataFrame:
    df = read_df(LEDGER)
    return df if not df.empty else pd.DataFrame(columns=COLUMNS)


def load_options() -> pd.DataFrame:
    df = read_df(OPTIONS)
    return df if not df.empty else pd.DataFrame(columns=OPT_COLUMNS)


def add_position(ticker: str, shares: float, entry_price: float, stop: float,
                 invalidation: str, entry_date: str | None = None,
                 stop_basis: str = "structure", thesis: str = "",
                 sleeve: str = "") -> dict:
    """
    Add or replace a position.

    `invalidation` is MANDATORY — Weekly Step 7's rule is that a position
    without a written invalidation condition can never be wrong, and therefore
    can never be managed. Rejecting it here is the difference between a system
    and a collection of opinions.
    """
    if not invalidation or not invalidation.strip():
        return {"ok": False, "error":
                "Invalidation sentence is required. Complete: 'This position is "
                "invalidated when ______.' If you cannot fill that blank, the "
                "position has no thesis and should not be opened."}
    if stop >= entry_price and shares > 0:
        return {"ok": False, "error":
                f"Stop {stop} is at or above entry {entry_price} for a long. "
                f"Check the direction, or enter negative shares for a short."}

    df = load_positions()
    df = df[df["ticker"] != ticker] if not df.empty else df
    row = {"ticker": ticker.upper(), "shares": shares, "entry_price": entry_price,
           "entry_date": entry_date or date.today().isoformat(), "stop": stop,
           "stop_basis": stop_basis, "thesis": thesis,
           "invalidation": invalidation.strip(), "sleeve": sleeve,
           "last_updated": datetime.now().isoformat(timespec="seconds")}
    write_df(LEDGER, pd.concat([df, pd.DataFrame([row])], ignore_index=True))
    return {"ok": True, "position": row}


def update_stop(ticker: str, new_stop: float, basis: str = "") -> dict:
    """
    Trail a stop UP. Lowering is refused.

    Daily Step 6: 'Never move a stop DOWN.' The stop was set before entry, on
    structure, when you were objective — moving it down converts a controlled
    1% loss into an uncontrolled one, which is the single most account-
    destructive habit in trading. A rule enforced only by willpower is enforced
    exactly when you least want it to be, so it is enforced here instead.
    """
    df = load_positions()
    m = df["ticker"] == ticker.upper()
    if not m.any():
        return {"ok": False, "error": f"No open position in {ticker}."}
    cur = float(df.loc[m, "stop"].iloc[0])
    if new_stop < cur:
        return {"ok": False, "error":
                f"REFUSED: {new_stop} is below the current stop {cur}. Stops trail "
                f"UP, never down. If the thesis has changed, close the position "
                f"instead of widening the risk."}
    df.loc[m, "stop"] = new_stop
    if basis:
        df.loc[m, "stop_basis"] = basis
    df.loc[m, "last_updated"] = datetime.now().isoformat(timespec="seconds")
    write_df(LEDGER, df)
    return {"ok": True, "old_stop": cur, "new_stop": new_stop}


def close_position(ticker: str) -> dict:
    df = load_positions()
    if df.empty or not (df["ticker"] == ticker.upper()).any():
        return {"ok": False, "error": f"No open position in {ticker}."}
    write_df(LEDGER, df[df["ticker"] != ticker.upper()])
    return {"ok": True, "closed": ticker.upper()}


# ── Live valuation, ATR, heat ─────────────────────────────────────────────────

def _fetch_ohlc(tickers: list[str], period: str = "3mo") -> dict:
    if not tickers:
        return {}
    try:
        import yfinance as yf
        raw = yf.download(tickers, period=period, interval="1d", auto_adjust=True,
                          progress=False, threads=True, timeout=40)
        out = {}
        if isinstance(raw.columns, pd.MultiIndex):
            lvl0 = set(raw.columns.get_level_values(0))
            if "Close" in lvl0:
                for t in raw["Close"].columns:
                    out[t] = pd.DataFrame({"High": raw["High"][t], "Low": raw["Low"][t],
                                           "Close": raw["Close"][t]}).dropna()
            else:
                for t in lvl0:
                    out[t] = raw[t][["High", "Low", "Close"]].dropna()
        else:
            out[tickers[0]] = raw[["High", "Low", "Close"]].dropna()
        return out
    except Exception as e:
        print(f"[ledger] price fetch failed: {e}")
        return {}


def atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range — the unit the checklist's '1 ATR from stop' uses."""
    if len(df) < period + 1:
        return float("nan")
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def evaluate_positions(equity: float | None = None) -> dict:
    """
    The whole Daily-Step-6 / Weekly-Step-7 picture in one call.

    Returns per-position live price, P&L, distance-to-stop in ATR units, and
    an alert level — plus portfolio heat against the 15% cap.
    """
    pos = load_positions()
    if pos.empty:
        return {"positions": pd.DataFrame(), "heat_pct": 0.0, "heat_ok": True,
                "equity": equity, "alerts": [],
                "message": "Ledger is empty. Add positions to enable stop checks, "
                           "heat, and true drift bands."}

    data = _fetch_ohlc([t for t in pos["ticker"].unique()])
    rows, alerts = [], []

    for _, p in pos.iterrows():
        tk = p["ticker"]
        d = data.get(tk)
        last = float(d["Close"].iloc[-1]) if d is not None and len(d) else np.nan
        a = atr(d) if d is not None else np.nan

        shares = float(p["shares"]); entry = float(p["entry_price"]); stop = float(p["stop"])
        risk_per_share = max(entry - stop, 0.0)
        risk_dollars = risk_per_share * abs(shares)
        mkt_value = last * shares if last == last else np.nan
        pnl = (last - entry) * shares if last == last else np.nan
        pnl_pct = ((last / entry - 1) * 100) if last == last and entry else np.nan

        atr_to_stop = ((last - stop) / a) if (last == last and a == a and a > 0) else np.nan
        if last == last and last <= stop:
            level, note = "STOP HIT", "EXIT NOW — Daily Step 6 authorizes this trade"
            alerts.append(f"🚨 {tk}: STOP HIT at {last:.2f} (stop {stop:.2f}) — exit, full stop.")
        elif atr_to_stop == atr_to_stop and atr_to_stop <= 1.0:
            level, note = "WITHIN 1 ATR", f"{atr_to_stop:.2f} ATR from stop"
            alerts.append(f"⚠️ {tk}: {atr_to_stop:.2f} ATR from stop — watch closely.")
        else:
            level, note = "OK", (f"{atr_to_stop:.1f} ATR from stop"
                                 if atr_to_stop == atr_to_stop else "ATR unavailable")

        rows.append({"ticker": tk, "sleeve": p.get("sleeve", ""), "shares": shares,
                     "entry": entry, "last": round(last, 2) if last == last else None,
                     "stop": stop, "atr": round(a, 2) if a == a else None,
                     "atr_to_stop": round(atr_to_stop, 2) if atr_to_stop == atr_to_stop else None,
                     "mkt_value": round(mkt_value, 0) if mkt_value == mkt_value else None,
                     "pnl": round(pnl, 0) if pnl == pnl else None,
                     "pnl_pct": round(pnl_pct, 1) if pnl_pct == pnl_pct else None,
                     "risk_$": round(risk_dollars, 0), "status": level, "note": note,
                     "invalidation": p.get("invalidation", "")})

    df = pd.DataFrame(rows)
    eq = equity or float(df["mkt_value"].sum(skipna=True) or 0)
    heat = (df["risk_$"].sum() / eq * 100) if eq else float("nan")
    heat_ok = heat <= HEAT_CAP_PCT if heat == heat else True
    if heat == heat and not heat_ok:
        alerts.append(f"🚨 Portfolio heat {heat:.1f}% exceeds the {HEAT_CAP_PCT}% cap — "
                      f"reduce size before adding any new risk.")

    return {"positions": df, "heat_pct": round(heat, 2) if heat == heat else None,
            "heat_ok": heat_ok, "equity": round(eq, 0), "alerts": alerts,
            "message": f"{len(df)} positions · heat {heat:.1f}% of {eq:,.0f}"
                       if heat == heat else f"{len(df)} positions"}


# ── Drift bands (Weekly Step 8) ───────────────────────────────────────────────

def drift_vs_targets(target_weights: dict, equity: float | None = None) -> dict:
    """
    LIVE weights vs regime targets, with ±20% relative bands.

    This is the real version of Weekly Step 8 — computed from actual market
    value, not from sidebar sliders (whose drift is zero by construction).
    """
    ev = evaluate_positions(equity)
    df = ev["positions"]
    if df.empty:
        return {"available": False,
                "message": "No positions — drift bands need a ledger. Falling back "
                           "to slider weights answers a weaker question."}

    eq = ev["equity"] or 1
    live = {}
    for _, r in df.iterrows():
        key = r["sleeve"] or r["ticker"]
        live[key] = live.get(key, 0.0) + (r["mkt_value"] or 0) / eq * 100

    rows = []
    for tk, tgt in target_weights.items():
        cur = live.get(tk, 0.0)
        if tgt == 0:
            breach = cur > 1.0
            rel = np.nan
        else:
            rel = (cur - tgt) / tgt
            breach = abs(rel) > DRIFT_BAND_REL
        rows.append({"sleeve": tk, "target_%": round(tgt, 1), "live_%": round(cur, 1),
                     "rel_drift_%": round(rel * 100, 1) if rel == rel else None,
                     "in_band": not breach,
                     "action": "REBALANCE" if breach else "hold"})
    out = pd.DataFrame(rows).sort_values("rel_drift_%", key=abs, ascending=False,
                                         na_position="last")
    breaches = out[~out["in_band"]]["sleeve"].tolist()
    return {"available": True, "table": out, "breaches": breaches,
            "message": (f"BAND BREACH: {', '.join(breaches)} — Weekly Step 8 authorizes "
                        f"a rebalance." if breaches else
                        "All sleeves within ±20% relative band — no rebalance trigger.")}


# ── Options book (Daily Step 6) ───────────────────────────────────────────────

def add_option(ticker: str, strategy: str, expiry: str, strike: float,
               contracts: int, credit_received: float, notes: str = "") -> dict:
    df = load_options()
    row = {"ticker": ticker.upper(), "strategy": strategy, "expiry": expiry,
           "strike": strike, "contracts": contracts,
           "credit_received": credit_received, "opened_date": date.today().isoformat(),
           "notes": notes, "last_updated": datetime.now().isoformat(timespec="seconds")}
    write_df(OPTIONS, pd.concat([df, pd.DataFrame([row])], ignore_index=True))
    return {"ok": True, "option": row}


def check_options_rules(current_marks: dict | None = None) -> dict:
    """
    The three mechanical rules from Daily Step 6, evaluated.

      close at 50% of max profit · close/roll at 21 DTE · close at 2× credit lost

    DTE is computed automatically. The 50%-profit and 2×-credit rules need a
    current mark, which no free API provides reliably for options chains —
    pass `current_marks` as {row_index: mark} if you have them, or check those
    two manually. DTE alone catches the one that escalates fastest: past 21 DTE
    gamma risk compounds and you lose control of the position.
    """
    df = load_options()
    if df.empty:
        return {"actions": [], "table": pd.DataFrame(),
                "message": "No options positions logged."}

    today = date.today()
    rows, actions = [], []
    for i, o in df.iterrows():
        try:
            dte = (datetime.strptime(str(o["expiry"]), "%Y-%m-%d").date() - today).days
        except Exception:
            dte = None
        credit = float(o.get("credit_received") or 0)
        mark = (current_marks or {}).get(i)

        rule = []
        if dte is not None and dte <= 21:
            rule.append("21-DTE: close or roll")
            actions.append(f"⚠️ {o['ticker']} {o['strike']} {o['expiry']} — {dte} DTE, "
                           f"close or roll (gamma risk escalates past here).")
        if mark is not None and credit:
            if mark <= credit * 0.5:
                rule.append("50% profit: close")
                actions.append(f"✅ {o['ticker']} {o['strike']} — at 50% max profit, close it.")
            if mark >= credit * 2:
                rule.append("2× credit lost: close")
                actions.append(f"🚨 {o['ticker']} {o['strike']} — lost 2× credit, close it.")

        rows.append({"ticker": o["ticker"], "strategy": o.get("strategy", ""),
                     "expiry": o["expiry"], "strike": o.get("strike"),
                     "contracts": o.get("contracts"), "dte": dte,
                     "credit": credit, "mark": mark,
                     "rule_triggered": "; ".join(rule) or "none"})

    return {"actions": actions, "table": pd.DataFrame(rows),
            "message": f"{len(rows)} option positions · {len(actions)} rule trigger(s)"}
