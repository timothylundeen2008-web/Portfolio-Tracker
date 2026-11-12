"""
swing_journal.py  (v1 — September 2026)
───────────────────────────────────────
ONE journal, TWO writers, ZERO actions.

The Swing Desk Agent recommends; you confirm from the dashboard tab or from
chat; both append to the same append-only CSV. Everything the agent needs
to know about YOU is derived from this file and never typed:

    pe_step()            Progressive Exposure step from your last closed trades
    heat_used_pct()      open risk vs equity, for the 15% cap
    equity()             starting equity + realized P&L  (your choice: equity
                         refreshes from realized results, not a typed number)
    open_positions()     what swing_exits.py manages tomorrow
    expectancy_by_setup() the gap-analysis engine's raw material

WHY APPEND-ONLY
  A ledger you can edit is a ledger you will edit after a bad trade. Every
  row is an event with a timestamp and a source; nothing is ever rewritten.
  "Realized R" is computed from the events, never stored as an opinion.

WHY THE AGENT NEVER WRITES TAKE / EXIT ROWS
  The execution boundary lives here. swing_agent.py writes briefs and
  cards_history; only the two human-driven surfaces (tab, chat) call
  record_*() below. If a TAKE row ever appears with source='agent', that is
  a bug to be treated as a breach.

STORAGE
  Through storage_backend (github -> local -> session), same as every other
  accumulating file in this repo. Names are relative to DATA_DIR.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from storage_backend import read_df, write_df, read_json, write_json

JOURNAL = "swing_journal.csv"
CONFIG = "swing_config.json"
WATCHLIST = "swing_watchlist.csv"

COLUMNS = ["event_id", "ts", "source", "ticker", "event", "setup", "side",
           "price", "shares", "stop", "planned_entry", "risk_per_share",
           "realized_pnl", "exit_trigger", "regime_at_entry", "confluence",
           "trail", "card_date", "note"]

EVENTS = {"TAKE", "TRIM", "EXIT", "STOP_HIT", "TIGHTEN", "PASS", "WATCH",
          "DECLINE", "RESET"}
HUMAN_SOURCES = {"tab", "chat"}

# Progressive Exposure — the table from swing_trading_agent_prompt.md.
# Step goes DOWN immediately on losses, UP only on streaks. Asymmetric on purpose.
PROGRESSIVE_EXPOSURE = {0: 0.0, 1: 0.5, 2: 1.0, 3: 2.0}     # step -> risk %
RISK_ON_REGIMES = {"goldilocks", "inflationary_repression"}
SCRATCH_R = 0.15      # |R| below this is a scratch: neither win nor loss

DEFAULT_CONFIG = {
    "starting_equity": None,       # set once; equity() = this + realized P&L
    "max_positions": 4,            # architecture doc: small account, 4 max
    "heat_cap_pct": 15.0,
    "max_position_pct": 30.0,      # concentration permitted only at tight stops
    "notional_cap_pct": 25.0,      # architecture doc: notional per name
    "atr_pct_band": [2.0, 7.0],    # stops the desk drifting to vol just because it fits the math
    "trail_default": "10 EMA",     # Matt: start aggressive; swing_trail.py advises per setup
    "new_campaign_step": 1,        # procedure Part 3: every new campaign starts at 0.5% risk
    "min_sample_per_setup": 20,    # below this, expectancy is a number, not evidence
}


# ── Config ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(read_json(CONFIG) or {})
    return cfg


def save_config(**updates) -> dict:
    cfg = load_config()
    unknown = set(updates) - set(DEFAULT_CONFIG)
    if unknown:
        raise KeyError(f"unknown config keys: {sorted(unknown)}")
    cfg.update(updates)
    write_json(CONFIG, cfg, "swing_config: update")
    return cfg


# ── Raw journal I/O ─────────────────────────────────────────────────────────

def load() -> pd.DataFrame:
    df = read_df(JOURNAL)
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNS)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNS].copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    for c in ("price", "shares", "stop", "planned_entry", "risk_per_share", "realized_pnl"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("ts").reset_index(drop=True)


def _append(row: dict, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    if row["event"] not in EVENTS:
        raise ValueError(f"unknown event {row['event']}")
    if row["source"] not in HUMAN_SOURCES:
        # The execution boundary. Nothing automated writes decisions.
        raise PermissionError(f"journal decisions must come from {HUMAN_SOURCES}, got {row['source']!r}")
    base = {c: None for c in COLUMNS}
    base.update(row)
    base["event_id"] = base["event_id"] or uuid.uuid4().hex[:12]
    base["ts"] = base["ts"] or datetime.now(timezone.utc).isoformat(timespec="seconds")
    df = load() if df is None else df
    df = pd.concat([df, pd.DataFrame([base])], ignore_index=True)
    write_df(JOURNAL, df, f"swing_journal: {base['event']} {base['ticker'] or ''}")
    return df


# ── Decisions (called ONLY by the tab and by chat) ──────────────────────────

def record_take(source: str, ticker: str, price: float, shares: float, stop: float, *,
                setup: str, side: str, planned_entry: float, regime: str,
                confluence: str, trail: str, card_date: str, note: str = "") -> pd.DataFrame:
    if shares <= 0 or price <= 0:
        raise ValueError("shares and price must be positive")
    if (side == "long" and stop >= price) or (side == "short" and stop <= price):
        raise ValueError(f"stop {stop} is on the wrong side of a {side} entry at {price}")
    return _append({"source": source, "ticker": ticker.upper(), "event": "TAKE",
                    "setup": setup, "side": side, "price": price, "shares": shares,
                    "stop": stop, "planned_entry": planned_entry,
                    "risk_per_share": abs(price - stop), "regime_at_entry": regime,
                    "confluence": confluence, "trail": trail, "card_date": card_date,
                    "note": note})


def record_exit(source: str, ticker: str, price: float, shares: Optional[float] = None, *,
                trigger: str, partial: bool = False, note: str = "") -> pd.DataFrame:
    """
    TRIM (partial) or EXIT/STOP_HIT (full). realized_pnl is computed here from
    the position's average entry -- never supplied by the caller.
    """
    pos = open_positions().get(ticker.upper())
    if not pos:
        raise ValueError(f"no open swing position in {ticker}")
    sh = float(shares) if shares else pos["shares"]
    if sh > pos["shares"] + 1e-9:
        raise ValueError(f"{ticker}: trying to close {sh} of {pos['shares']} shares")
    sign = 1 if pos["side"] == "long" else -1
    pnl = round(sign * (price - pos["avg_entry"]) * sh, 2)
    event = "TRIM" if partial and sh < pos["shares"] else ("STOP_HIT" if trigger == "structural" else "EXIT")
    return _append({"source": source, "ticker": ticker.upper(), "event": event,
                    "setup": pos["setup"], "side": pos["side"], "price": price,
                    "shares": sh, "realized_pnl": pnl, "exit_trigger": trigger,
                    "note": note})


def record_tighten(source: str, ticker: str, new_stop: float, note: str = "") -> pd.DataFrame:
    """Stops move UP (long) or DOWN (short) only. The other direction is refused here, not in the UI."""
    pos = open_positions().get(ticker.upper())
    if not pos:
        raise ValueError(f"no open swing position in {ticker}")
    if (pos["side"] == "long" and new_stop <= pos["stop"]) or \
       (pos["side"] == "short" and new_stop >= pos["stop"]):
        raise ValueError(f"{ticker}: stops never move against the position "
                         f"(current {pos['stop']}, requested {new_stop})")
    return _append({"source": source, "ticker": ticker.upper(), "event": "TIGHTEN",
                    "stop": new_stop, "note": note})


def record_decision(source: str, ticker: str, decision: str, card_date: str, note: str = "") -> pd.DataFrame:
    """PASS / WATCH on a card, DECLINE on an open-position recommendation. These feed the review."""
    if decision not in ("PASS", "WATCH", "DECLINE"):
        raise ValueError(decision)
    return _append({"source": source, "ticker": ticker.upper(), "event": decision,
                    "card_date": card_date, "note": note})


def record_reset(source: str, note: str = "") -> pd.DataFrame:
    """After 3+ consecutive losses (step 0), you acknowledge the reset to re-enter at step 1."""
    return _append({"source": source, "ticker": None, "event": "RESET", "note": note})


# ── Derived state (never stored) ────────────────────────────────────────────

def open_positions(df: Optional[pd.DataFrame] = None) -> dict:
    """{ticker: {shares, avg_entry, stop, side, setup, trail, entry_ts, risk_per_share,
                 trims, regime_at_entry, confluence}} for every position not fully closed."""
    df = load() if df is None else df
    out = {}
    for _, r in df.iterrows():
        tk = r["ticker"]
        if r["event"] == "TAKE":
            p = out.get(tk) or {"shares": 0.0, "cost": 0.0, "side": r["side"], "setup": r["setup"],
                                "trail": r["trail"], "entry_ts": r["ts"], "stop": r["stop"],
                                "risk_per_share": r["risk_per_share"], "trims": 0,
                                "regime_at_entry": r["regime_at_entry"], "confluence": r["confluence"],
                                "shares_taken": 0.0}
            p["shares"] += r["shares"]; p["cost"] += r["shares"] * r["price"]
            p["shares_taken"] += r["shares"]
            # a later add never loosens the stop
            p["stop"] = max(p["stop"], r["stop"]) if r["side"] == "long" else min(p["stop"], r["stop"])
            out[tk] = p
        elif r["event"] in ("TRIM", "EXIT", "STOP_HIT") and tk in out:
            out[tk]["shares"] -= r["shares"]
            if r["event"] == "TRIM":
                out[tk]["trims"] += 1
            if out[tk]["shares"] <= 1e-9:
                del out[tk]
        elif r["event"] == "TIGHTEN" and tk in out:
            out[tk]["stop"] = r["stop"]
    for p in out.values():
        p["avg_entry"] = round(p["cost"] / p["shares_taken"], 4) if p["shares_taken"] else None
        p["shares"] = round(p["shares"], 4)
    return out


def closed_trades(df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    One row per completed round trip: ticker, setup, side, regime, opened, closed,
    planned_risk ($ = shares_taken x risk/share), realized_pnl, R, exit_trigger
    (the trigger on the FINAL closing row), duration_days.
    """
    df = load() if df is None else df
    rows, live = [], {}
    for _, r in df.iterrows():
        tk = r["ticker"]
        if r["event"] == "TAKE":
            t = live.get(tk) or {"ticker": tk, "setup": r["setup"], "side": r["side"],
                                 "regime": r["regime_at_entry"], "confluence": r["confluence"],
                                 "opened": r["ts"], "shares": 0.0, "shares_taken": 0.0,
                                 "planned_risk": 0.0, "realized_pnl": 0.0, "slippage": []}
            t["shares"] += r["shares"]; t["shares_taken"] += r["shares"]
            t["planned_risk"] += r["shares"] * r["risk_per_share"]
            if pd.notna(r["planned_entry"]) and r["planned_entry"]:
                t["slippage"].append((r["price"] - r["planned_entry"]) / r["planned_entry"] * 100)
            live[tk] = t
        elif r["event"] in ("TRIM", "EXIT", "STOP_HIT") and tk in live:
            t = live[tk]; t["shares"] -= r["shares"]
            t["realized_pnl"] += float(r["realized_pnl"] or 0)
            if t["shares"] <= 1e-9:
                t["closed"] = r["ts"]; t["exit_trigger"] = r["exit_trigger"]
                t["R"] = round(t["realized_pnl"] / t["planned_risk"], 3) if t["planned_risk"] else None
                t["duration_days"] = (t["closed"] - t["opened"]).days
                t["slippage_pct"] = round(sum(t["slippage"]) / len(t["slippage"]), 3) if t["slippage"] else None
                del t["slippage"], t["shares"]
                rows.append(t); del live[tk]
    return pd.DataFrame(rows)


def _streak(closed: pd.DataFrame, reset_ts=None) -> tuple[str, int]:
    """('win'|'loss'|'none', length) of the run at the tail, ignoring scratches, after any RESET."""
    if closed.empty:
        return "none", 0
    c = closed.sort_values("closed")
    if reset_ts is not None:
        c = c[c["closed"] > reset_ts]
    kind, n = "none", 0
    for R in reversed(c["R"].tolist()):
        if R is None or abs(R) < SCRATCH_R:
            continue
        k = "win" if R > 0 else "loss"
        if kind == "none":
            kind, n = k, 1
        elif k == kind:
            n += 1
        else:
            break
    return kind, n


def pe_step(regime_key: Optional[str] = None, df: Optional[pd.DataFrame] = None) -> dict:
    """
    Progressive Exposure step, derived. Returns step, risk %, and the reason
    in words so the brief can print WHY you are at this step.
    """
    df = load() if df is None else df
    cfg = load_config()
    closed = closed_trades(df)
    resets = df[df["event"] == "RESET"]
    reset_ts = resets["ts"].max() if not resets.empty else None
    kind, n = _streak(closed, reset_ts)

    if closed.empty or (reset_ts is not None and kind == "none"):
        step = int(cfg["new_campaign_step"])
        why = ("New campaign: no closed swing trades yet. Procedure Part 3 starts every "
               "campaign at 0.5% risk regardless of how good the setups look."
               if closed.empty else "Reset acknowledged; back at step 1 until results speak.")
    elif kind == "loss" and n >= 3:
        step, why = 0, (f"{n} consecutive losses: cash / paper only. The market is telling you the "
                        f"environment changed before any indicator did. Record a RESET to re-enter at step 1.")
    elif kind == "loss" and n == 2:
        step, why = 1, "2 consecutive losses: stepped down to 0.5% immediately."
    elif kind == "loss":
        step, why = 1, "Last trade a loss: 0.5% until a winner."
    elif kind == "win" and n >= 3:
        if regime_key in RISK_ON_REGIMES:
            step, why = 3, f"{n} consecutive winners in a risk-on regime ({regime_key}): max 2.0%."
        else:
            step, why = 2, (f"{n} consecutive winners, but regime {regime_key} is not risk-on: "
                            f"step 3 needs both. Holding at 1.0%.")
    else:
        step, why = 2, f"{n} winner(s) in a row: 1.0%."
    return {"step": step, "risk_pct": PROGRESSIVE_EXPOSURE[step], "streak": f"{kind}:{n}",
            "closed_trades": int(len(closed)), "why": why,
            "last_5_R": [r for r in closed.sort_values("closed")["R"].tail(5).tolist()] if not closed.empty else []}


def equity(df: Optional[pd.DataFrame] = None) -> dict:
    """Starting equity + realized P&L. Unrealized is reported separately by swing_exits, never added here."""
    cfg = load_config()
    df = load() if df is None else df
    realized = float(pd.to_numeric(df["realized_pnl"], errors="coerce").fillna(0).sum())
    start = cfg.get("starting_equity")
    if start is None:
        return {"equity": None, "starting_equity": None, "realized_pnl": realized,
                "note": "starting_equity not set in swing_config.json — the desk cannot size."}
    return {"equity": round(float(start) + realized, 2), "starting_equity": float(start),
            "realized_pnl": round(realized, 2), "note": "equity = starting + realized P&L"}


def heat_used_pct(df: Optional[pd.DataFrame] = None) -> dict:
    """Σ shares × max(0, entry − stop) / equity. A stop above entry contributes zero heat."""
    df = load() if df is None else df
    eq = equity(df)["equity"]
    pos = open_positions(df)
    per = {}
    for tk, p in pos.items():
        sign = 1 if p["side"] == "long" else -1
        risk = max(0.0, sign * (p["avg_entry"] - p["stop"])) * p["shares"]
        per[tk] = round(risk, 2)
    total = sum(per.values())
    return {"heat_dollars": round(total, 2),
            "heat_pct": round(total / eq * 100, 2) if eq else None,
            "per_position": per, "open_count": len(pos),
            "slots_open": max(0, int(load_config()["max_positions"]) - len(pos))}


def expectancy_by_setup(regime_key: Optional[str] = None, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Per setup: n, hit rate, avg win R, avg loss R, expectancy R, avg loss vs 1R, slippage. Flags thin samples."""
    closed = closed_trades(load() if df is None else df)
    if closed.empty:
        return pd.DataFrame(columns=["setup", "n", "hit_rate", "avg_win_R", "avg_loss_R",
                                     "expectancy_R", "stops_honored", "avg_slippage_pct", "evidence"])
    if regime_key:
        closed = closed[closed["regime"] == regime_key]
    min_n = int(load_config()["min_sample_per_setup"])
    rows = []
    for setup, g in closed.groupby("setup"):
        R = g["R"].dropna()
        wins, losses = R[R > 0], R[R <= 0]
        rows.append({"setup": setup, "n": int(len(R)),
                     "hit_rate": round(len(wins) / len(R), 3) if len(R) else None,
                     "avg_win_R": round(wins.mean(), 2) if len(wins) else None,
                     "avg_loss_R": round(losses.mean(), 2) if len(losses) else None,
                     "expectancy_R": round(R.mean(), 3) if len(R) else None,
                     # if the average loser is worse than -1R, stops are not being honored
                     "stops_honored": bool(losses.mean() >= -1.05) if len(losses) else None,
                     "avg_slippage_pct": round(g["slippage_pct"].dropna().mean(), 3) if g["slippage_pct"].notna().any() else None,
                     "evidence": "yes" if len(R) >= min_n else f"no (n<{min_n})"})
    return pd.DataFrame(rows).sort_values("n", ascending=False).reset_index(drop=True)


def pending_from_brief(brief: dict, df: Optional[pd.DataFrame] = None) -> list[dict]:
    """
    Which of a brief's cards / recommendations have NO journal decision yet.
    Rolled into the next brief as UNCONFIRMED -- the desk assumed nothing.
    """
    df = load() if df is None else df
    day = brief.get("date")
    decided = set(df[(df["card_date"] == day)]["ticker"].dropna()) | set(open_positions(df))
    out = []
    for c in brief.get("cards", []):
        if c["ticker"] not in decided:
            out.append({"ticker": c["ticker"], "kind": "card", "setup": c.get("setup"), "date": day})
    for p in brief.get("open_positions", []):
        if p.get("recommendation") and p["recommendation"] != "HOLD":
            after = df[(df["ticker"] == p["ticker"]) & (df["ts"] >= pd.Timestamp(brief["generated_at"]))]
            if after.empty:
                out.append({"ticker": p["ticker"], "kind": "recommendation",
                            "recommendation": p["recommendation"], "date": day})
    return out


# ── Watchlist — "the ability to add others at any time" ─────────────────────

WL_COLUMNS = ["ticker", "added_ts", "source", "reason", "expires"]


def watchlist() -> pd.DataFrame:
    df = read_df(WATCHLIST)
    if df is None or df.empty:
        return pd.DataFrame(columns=WL_COLUMNS)
    df = df[[c for c in WL_COLUMNS if c in df.columns]].copy()
    if "expires" in df.columns:
        exp = pd.to_datetime(df["expires"], errors="coerce", utc=True)
        df = df[exp.isna() | (exp >= pd.Timestamp.now(tz="UTC"))]
    return df.reset_index(drop=True)


def watchlist_add(source: str, ticker: str, reason: str = "", expires: Optional[str] = None) -> pd.DataFrame:
    if source not in HUMAN_SOURCES:
        raise PermissionError("watchlist entries come from the tab or chat")
    df = watchlist()
    tk = ticker.strip().upper()
    df = df[df["ticker"] != tk]
    df = pd.concat([df, pd.DataFrame([{"ticker": tk, "added_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                       "source": source, "reason": reason, "expires": expires}])], ignore_index=True)
    write_df(WATCHLIST, df, f"swing_watchlist: add {tk}")
    return df


def watchlist_remove(ticker: str) -> pd.DataFrame:
    df = watchlist()
    df = df[df["ticker"] != ticker.strip().upper()].reset_index(drop=True)
    write_df(WATCHLIST, df, f"swing_watchlist: remove {ticker.upper()}")
    return df


# ── Selftest (session backend; touches nothing durable) ─────────────────────

def selftest() -> dict:
    import os
    os.environ["SWING_JOURNAL_SELFTEST"] = "1"
    f = []
    global JOURNAL, CONFIG, WATCHLIST
    J0, C0, W0 = JOURNAL, CONFIG, WATCHLIST
    JOURNAL, CONFIG, WATCHLIST = "_selftest_swing_journal.csv", "_selftest_swing_config.json", "_selftest_swing_watchlist.csv"
    try:
        write_df(JOURNAL, pd.DataFrame(columns=COLUMNS)); write_json(CONFIG, {})
        write_df(WATCHLIST, pd.DataFrame(columns=WL_COLUMNS))
        save_config(starting_equity=10_000.0)

        if pe_step("goldilocks")["step"] != 1:
            f.append("new campaign must be step 1")
        # execution boundary
        try:
            _append({"source": "agent", "ticker": "X", "event": "TAKE"}); f.append("agent wrote a TAKE row")
        except PermissionError:
            pass
        # a round trip: long 100 @ 50, stop 48, exit 56 -> pnl 600, planned risk 200, R = 3
        record_take("tab", "AAA", 50, 100, 48, setup="M2 Breakout", side="long", planned_entry=49.8,
                    regime="goldilocks", confluence="3-of-3", trail="10 EMA", card_date="2026-09-14")
        h = heat_used_pct()
        if abs(h["heat_pct"] - 2.0) > 0.01:
            f.append(f"heat should be 2.0%, got {h['heat_pct']}")
        try:
            record_tighten("tab", "AAA", 47); f.append("stop moved DOWN was accepted")
        except ValueError:
            pass
        record_tighten("chat", "AAA", 51)
        if heat_used_pct()["heat_pct"] != 0.0:
            f.append("stop above entry must give zero heat")
        record_exit("chat", "AAA", 56, trigger="ladder", partial=False)
        ct = closed_trades()
        if len(ct) != 1 or abs(ct.iloc[0]["R"] - 3.0) > 1e-6:
            f.append(f"round trip R should be 3.0: {ct.to_dict('records')}")
        if abs(equity()["equity"] - 10_600) > 0.01:
            f.append(f"equity must be starting + realized: {equity()}")
        if pe_step("transition_ambiguous")["step"] != 2:
            f.append("1 winner -> step 2")
        # three losers -> step 0; reset -> step 1
        for i, tk in enumerate(("BBB", "CCC", "DDD")):
            record_take("tab", tk, 100, 10, 95, setup="M1 VCP", side="long", planned_entry=100,
                        regime="goldilocks", confluence="2-of-3", trail="50 SMA", card_date="2026-09-15")
            record_exit("tab", tk, 95, trigger="structural")
        ps = pe_step("goldilocks")
        if ps["step"] != 0:
            f.append(f"3 losses -> step 0, got {ps}")
        record_reset("chat", "acknowledged")
        if pe_step("goldilocks")["step"] != 1:
            f.append("after RESET -> step 1")
        ex = expectancy_by_setup()
        if ex[ex.setup == "M1 VCP"].iloc[0]["stops_honored"] is not True:
            f.append("losses at exactly -1R should count as stops honored")
        # short side sign
        record_take("tab", "SSS", 100, 10, 105, setup="M2b Parabolic Short", side="short", planned_entry=100,
                    regime="growth_scare", confluence="3-of-3", trail="10 EMA", card_date="2026-09-16")
        record_exit("tab", "SSS", 90, trigger="ladder")
        if abs(closed_trades().iloc[-1]["R"] - 2.0) > 1e-6:
            f.append("short round trip R should be +2.0")
        # watchlist
        watchlist_add("chat", "pltr", "EP candidate on contract news")
        if "PLTR" not in set(watchlist()["ticker"]):
            f.append("watchlist add failed")
        watchlist_remove("PLTR")
        if len(watchlist()):
            f.append("watchlist remove failed")
        # pending detection
        b = {"date": "2026-09-17", "generated_at": datetime.now(timezone.utc).isoformat(),
             "cards": [{"ticker": "EEE", "setup": "M2 Breakout"}], "open_positions": []}
        if [p["ticker"] for p in pending_from_brief(b)] != ["EEE"]:
            f.append("pending_from_brief should flag EEE")
        record_decision("tab", "EEE", "PASS", "2026-09-17")
        if pending_from_brief(b):
            f.append("PASS should clear pending")
    finally:
        JOURNAL, CONFIG, WATCHLIST = J0, C0, W0
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2))
