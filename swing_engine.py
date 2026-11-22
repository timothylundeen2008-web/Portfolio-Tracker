"""
swing_engine.py  (v1.0 — 2026-11-22)
─────────────────────────────────────
The $10,000 swing account's ENGINE BOOK (Matt, 2026-11-22: "Good with your recommendation"):
the swing account mirrors the O11 model book — the only switching rule here that passed
testing — turned into whole-share order tickets for a $10,000 account. Paper from
2026-12-01; live target 2027-01-04 (go-live gate unchanged). Research, not personalized advice.

  Source of truth: the Consolidated Daily Brief (logs/brief/<session>_brief.json). For the
  session after each brief the account targets:
    - model.switch.next_book, when the engine switched at that close (N78), else
    - model.rows (the model book's weights).
  So the swing account and the model book can never disagree about what to hold.

  Rebalance triggers (fixed before the first paper day):
    1. the O11 state switched at the close (the whole book changes);
    2. any fund's target moved by 2.0 points or more since the last rebalance;
    3. first session of a month: any holding off target by 5.0 points or more of equity;
    4. the account holds nothing yet.
  Tickets: whole shares; sells before buys; buys scaled down to the cash available; trades
  under $100 skipped; fills at the next session's OPEN with 5bp slippage. Residual cash earns
  nothing (conservative). Idempotent: the whole ledger is recomputed from PAPER_START each run.

  Paper tracks beside it (no money): M0 cards (swing_agent / swing desk journal), radar flags
  (market_radar scoreboard), and S3 leveraged trend (shadow here; failed its test 2026-11-22,
  kept only as a forward record).

Run:  python swing_engine.py             (Actions, after the Daily Brief)
      python swing_engine.py --selftest  (offline)
"""
from __future__ import annotations

import glob
import json
import math
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

VERSION = "1.0"
PAPER_START = date(2026, 12, 1)
EQUITY0 = 10_000.0
MIN_TRADE = 100.0
SLIP_BPS = 5.0
TRIG_TARGET_PTS = 2.0
TRIG_DRIFT_PTS = 5.0
BRIEF_DIR = Path("logs/brief")
OUT_DATA, OUT_LOGS = Path("data/swing_engine"), Path("logs/swing_engine")
S3_SINCE = "2023-01-01"


def _log(msg: str) -> None:
    print(f"[swing_engine {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# ── targets from the briefs ─────────────────────────────────────────────────

def target_from_brief(b: dict) -> Optional[dict]:
    """{'session', 'weights', 'state', 'switched'} for the session AFTER the brief's session."""
    m = b.get("model") or {}
    sw = m.get("switch") or {}
    eng = m.get("engine") or {}
    if sw.get("next_book"):
        w = {k: float(v) for k, v in sw["next_book"].items() if float(v) > 0}
        state, switched = sw.get("to"), True
    else:
        w = {r["ticker"]: float(r["weight"]) for r in (m.get("rows") or []) if float(r.get("weight") or 0) > 0}
        state, switched = eng.get("state"), False
    if not w:
        return None
    tot = sum(w.values())
    w = {k: v * 100.0 / tot for k, v in w.items()}          # normalize (rounding)
    return {"session": str(b.get("session")), "weights": w, "state": state, "switched": switched}


def load_targets(brief_dir: Path = BRIEF_DIR) -> dict:
    out = {}
    for f in sorted(glob.glob(str(brief_dir / "*_brief.json"))):
        try:
            t = target_from_brief(json.load(open(f)))
            if t:
                out[t["session"]] = t
        except Exception:
            continue
    return out


# ── the paper ledger ────────────────────────────────────────────────────────

def _px(prices: dict, t: str, d: pd.Timestamp, col: str) -> Optional[float]:
    df = prices.get(t)
    if df is None or d not in df.index:
        return None
    v = float(df.at[d, col])
    return v if np.isfinite(v) and v > 0 else None


def plan_tickets(target: dict, shares: dict, cash: float, prices: dict, d: pd.Timestamp) -> tuple:
    """Desired whole shares at the close of d; returns (tickets, missing). Tickets are deltas."""
    eq = cash + sum(n * (_px(prices, t, d, "Close") or 0.0) for t, n in shares.items())
    missing = [t for t in set(target["weights"]) | set(shares) if _px(prices, t, d, "Close") is None]
    if missing:
        return [], missing
    want = {t: math.floor(w / 100 * eq / _px(prices, t, d, "Close")) for t, w in target["weights"].items()}
    tickets = []
    for t in sorted(set(want) | set(shares)):
        delta = want.get(t, 0) - shares.get(t, 0)
        px = _px(prices, t, d, "Close")
        if delta and abs(delta) * px >= MIN_TRADE:
            tickets.append({"ticker": t, "side": "BUY" if delta > 0 else "SELL", "shares": int(abs(delta)),
                            "est_price": round(px, 2), "est_value": round(abs(delta) * px, 2)})
        elif delta and want.get(t, 0) == 0:                  # always close a position that leaves the book
            tickets.append({"ticker": t, "side": "SELL", "shares": int(abs(delta)),
                            "est_price": round(px, 2), "est_value": round(abs(delta) * px, 2)})
    return tickets, []


def fill(tickets: list, shares: dict, cash: float, prices: dict, d: pd.Timestamp) -> tuple:
    """Execute at d's open: sells first, then buys scaled to cash. Returns (shares, cash, fills, missing)."""
    shares, fills, missing = dict(shares), [], []
    for tk in [x for x in tickets if x["side"] == "SELL"]:
        o = _px(prices, tk["ticker"], d, "Open")
        if o is None:
            missing.append(tk["ticker"])
            continue
        n = min(tk["shares"], shares.get(tk["ticker"], 0))
        px = o * (1 - SLIP_BPS / 1e4)
        cash += n * px
        shares[tk["ticker"]] = shares.get(tk["ticker"], 0) - n
        fills.append({**tk, "shares": n, "fill": round(px, 4)})
    for tk in [x for x in tickets if x["side"] == "BUY"]:
        o = _px(prices, tk["ticker"], d, "Open")
        if o is None:
            missing.append(tk["ticker"])
            continue
        px = o * (1 + SLIP_BPS / 1e4)
        n = min(tk["shares"], int(cash // px))
        if n <= 0:
            continue
        cash -= n * px
        shares[tk["ticker"]] = shares.get(tk["ticker"], 0) + n
        fills.append({**tk, "shares": n, "fill": round(px, 4)})
    return {t: n for t, n in shares.items() if n > 0}, cash, fills, missing


def _weights_now(shares, cash, prices, d):
    vals = {t: n * (_px(prices, t, d, "Close") or 0.0) for t, n in shares.items()}
    eq = cash + sum(vals.values())
    return ({t: v / eq * 100 for t, v in vals.items()}, eq) if eq > 0 else ({}, eq)


def should_rebalance(target: dict, last_target: Optional[dict], shares: dict, cash: float, prices: dict,
                     d: pd.Timestamp, prev_d: Optional[pd.Timestamp]) -> Optional[str]:
    if not shares:
        return "account holds nothing yet"
    if target.get("switched"):
        return f"engine switched → {target.get('state')}"
    if last_target is not None:
        keys = set(target["weights"]) | set(last_target["weights"])
        mv = max(abs(target["weights"].get(k, 0) - last_target["weights"].get(k, 0)) for k in keys)
        if mv >= TRIG_TARGET_PTS:
            return f"model target moved {mv:.1f} pts"
    if prev_d is None or d.month != prev_d.month:
        w, _eq = _weights_now(shares, cash, prices, d)
        keys = set(target["weights"]) | set(w)
        dr = max(abs(target["weights"].get(k, 0) - w.get(k, 0)) for k in keys)
        if dr >= TRIG_DRIFT_PTS:
            return f"month start: drift {dr:.1f} pts"
    return None


def simulate(targets: dict, prices: dict, cal: pd.DatetimeIndex, start: date = PAPER_START) -> dict:
    """Recompute the paper ledger. Decisions at each close (from that session's brief) produce tickets
    for the next session's open. The first decision is the session before `start`."""
    sess = [d for d in cal]
    first = [i for i, d in enumerate(sess) if d.date() >= start]
    if not first:
        return {"rows": [], "pending": None, "events": [], "started": False}
    i0 = max(first[0] - 1, 0)
    shares, cash, last_target, pending = {}, EQUITY0, None, None
    rows, events, gaps = [], [], []
    for i in range(i0, len(sess)):
        d = sess[i]
        if pending and pending["for"] == d.date().isoformat():
            shares, cash, fills, miss = fill(pending["tickets"], shares, cash, prices, d)
            events.append({"date": d.date().isoformat(), "kind": "fill", "why": pending["why"], "fills": fills})
            if miss:
                gaps.append({"date": d.date().isoformat(), "missing_open": miss})
            pending = None
        if d.date() >= start:
            w, eq = _weights_now(shares, cash, prices, d)
            rows.append({"date": d.date().isoformat(), "equity": round(eq, 2), "cash": round(cash, 2),
                         "holdings": json.dumps({t: int(n) for t, n in sorted(shares.items())})})
        tgt = targets.get(d.date().isoformat())
        if tgt is None:
            if d.date() >= start - timedelta(days=4):
                gaps.append({"date": d.date().isoformat(), "missing_brief": True})
            continue
        why = should_rebalance(tgt, last_target, shares, cash, prices, d, sess[i - 1] if i > i0 else None)
        if why:
            tickets, miss = plan_tickets(tgt, shares, cash, prices, d)
            if miss:
                gaps.append({"date": d.date().isoformat(), "missing_close": miss})
                continue
            nxt = sess[i + 1].date().isoformat() if i + 1 < len(sess) else _next_trading(d.date()).isoformat()
            pending = {"for": nxt, "why": why, "tickets": tickets, "decided": d.date().isoformat(),
                       "state": tgt.get("state"), "weights": tgt["weights"]}
            last_target = tgt
    return {"rows": rows, "pending": pending, "events": events, "gaps": gaps, "started": True,
            "shares": shares, "cash": cash, "last_target": last_target}


def _next_trading(d: date) -> date:
    try:
        import market_time as mt
        n = d + timedelta(days=1)
        for _ in range(10):
            if mt.is_trading_day(n):
                return n
            n += timedelta(days=1)
        return n
    except Exception:
        n = d + timedelta(days=1)
        while n.weekday() >= 5:
            n += timedelta(days=1)
        return n


def preview(target: dict, prices: dict, d: pd.Timestamp) -> dict:
    t, miss = plan_tickets(target, {}, EQUITY0, prices, d)
    spent = sum(x["est_value"] for x in t)
    return {"tickets": t, "missing": miss, "cash_left": round(EQUITY0 - spent, 2)}


# ── S3 shadow (paper only) ──────────────────────────────────────────────────

def s3_shadow(spy: pd.DataFrame, qqq: pd.DataFrame, irx: pd.Series) -> dict:
    import trend_lab as tl
    rf = (irx.reindex(spy.index).ffill() / 100 / 252).fillna(0.0)
    out = {"sleeves": {}, "trades_since_start": [], "nav": None}
    since = []
    for name, df in (("SPY", spy), ("QQQ", qqq)):
        trs = tl.s3_trades(name, df, rf)
        last = trs[-1] if trs else None
        c = df["Close"]
        sl, sf = c.rolling(200).mean(), c.rolling(50).mean()
        on = bool((c.iloc[-1] > sl.iloc[-1]) and (sl.iloc[-1] > sl.iloc[-21]) and (c.iloc[-1] > sf.iloc[-1]))
        holding = bool(last and last["why"] == "open at end")
        out["sleeves"][name] = {"on_today": on, "holding": holding,
                                "entry": str(last["entry_date"].date()) if holding else None,
                                "size_pct": round(last["size"] * 100, 1) if holding else None,
                                "open_ret_pct": round(last["ret"] * 100, 1) if holding else None,
                                "vs_200d_pct": round(float((c.iloc[-1] / sl.iloc[-1] - 1) * 100), 2),
                                "vs_50d_pct": round(float((c.iloc[-1] / sf.iloc[-1] - 1) * 100), 2)}
        since += [t for t in trs if t["entry_date"].date() >= PAPER_START]
    out["trades_since_start"] = [{"index": t["index"], "entry": str(t["entry_date"].date()),
                                  "exit": str(t["exit_date"].date()), "why": t["why"], "size_pct": round(t["size"] * 100, 1),
                                  "ret_pct": round(t["ret"] * 100, 1)} for t in since]
    cal = spy.index[spy.index.date >= PAPER_START]
    if len(cal):
        nav = tl.book(since, cal, rf)
        out["nav"] = {"equity": round(float(nav.iloc[-1]), 2), "ret_pct": round(float(nav.iloc[-1] / EQUITY0 - 1) * 100, 2)}
    return out


# ── run ─────────────────────────────────────────────────────────────────────

def _fetch(tickers, start):
    import yfinance as yf
    out = {}
    for attempt in range(4):
        need = [t for t in tickers if t not in out]
        if not need:
            break
        if attempt:
            _log(f"retry {attempt}: {', '.join(need)}")
            time.sleep(3)
        for t in need:
            try:
                df = yf.download(t, start=start, auto_adjust=False, progress=False, threads=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.dropna(subset=["Close"])
                ix = pd.to_datetime(df.index)
                df.index = (ix.tz_localize(None) if getattr(ix, "tz", None) else ix).normalize()
                if len(df):
                    out[t] = df[["Open", "High", "Low", "Close"]].astype(float)
            except Exception as e:
                _log(f"{t}: {type(e).__name__}")
    return out


def build(targets: dict, prices: dict, s3: Optional[dict], today_session: Optional[str]) -> dict:
    cal = None
    for df in prices.values():
        cal = df.index if cal is None else cal.union(df.index)
    spy_ix = prices["SPY"].index if "SPY" in prices else cal
    cal = spy_ix                                             # trading calendar = SPY's sessions
    last = max(targets) if targets else None
    sim = simulate(targets, prices, cal)
    out = {"version": VERSION, "paper_start": PAPER_START.isoformat(), "latest_brief": last,
           "price_date": str(cal[-1].date()) if len(cal) else None, "s3": s3}
    if last:
        tgt = targets[last]
        out["target"] = {"for_session": _next_trading(date.fromisoformat(last)).isoformat(), "state": tgt["state"],
                         "switched": tgt["switched"], "weights": {k: round(v, 2) for k, v in tgt["weights"].items()}}
        d = pd.Timestamp(last)
        if d in cal and _next_trading(date.fromisoformat(last)) < PAPER_START:
            out["preview"] = preview(tgt, prices, d)
            out["preview"]["priced_at"] = last
    out["ledger"] = sim["rows"]
    out["pending"] = sim.get("pending")
    out["events"] = sim.get("events", [])[-10:]
    out["gaps"] = sim.get("gaps", [])
    if sim["rows"]:
        eq = sim["rows"][-1]["equity"]
        out["equity"] = {"now": eq, "ret_pct": round((eq / EQUITY0 - 1) * 100, 2),
                         "peak": max(r["equity"] for r in sim["rows"])}
        out["equity"]["dd_pct"] = round((eq / out["equity"]["peak"] - 1) * 100, 2)
    stale = bool(today_session and last and last < today_session)
    out["stale_brief"] = stale
    return out


def _s3_word(v: dict) -> str:
    if v["holding"]:
        return f"HOLDING since {v['entry']} ({v['open_ret_pct']:+.1f}%, {v['size_pct']:.0f}% of equity)"
    return "ON" if v["on_today"] else "OFF"


def render(r: dict) -> str:
    L = [f"# Swing account — engine book (paper) · {r.get('latest_brief')}", "",
         f"*swing_engine.py {VERSION}. The $10,000 swing account mirrors the O11 model book. Paper from "
         f"{r['paper_start']}; live target 2027-01-04. Research, not personalized advice.*", ""]
    if r.get("stale_brief"):
        L += ["⚠ The latest daily brief is older than the last session — tickets below may be stale.", ""]
    t = r.get("target")
    if t:
        L += [f"**Target for {t['for_session']}** — engine {t['state']}{' (SWITCHED)' if t['switched'] else ''}: "
              + " / ".join(f"{k} {v:g}" for k, v in sorted(t["weights"].items(), key=lambda kv: -kv[1])), ""]
    pv = r.get("preview")
    if pv:
        L += [f"**Preview (paper starts {r['paper_start']}): a $10,000 account would buy, at the {pv['priced_at']} close:**", "",
              "| Fund | Shares | ≈ Price | ≈ Value |", "|---|---|---|---|"]
        L += [f"| {x['ticker']} | {x['shares']} | {x['est_price']:,.2f} | {x['est_value']:,.0f} |" for x in pv["tickets"]]
        L += [f"", f"Cash left ≈ ${pv['cash_left']:,.0f}" + (f" · no price for {', '.join(pv['missing'])}" if pv["missing"] else ""), ""]
    pd_ = r.get("pending")
    if pd_:
        L += [f"**Orders for the {pd_['for']} open** ({pd_['why']}; decided at the {pd_['decided']} close):", "",
              "| Side | Fund | Shares | ≈ Price | ≈ Value |", "|---|---|---|---|---|"]
        L += [f"| {x['side']} | {x['ticker']} | {x['shares']} | {x['est_price']:,.2f} | {x['est_value']:,.0f} |" for x in pd_["tickets"]]
        L.append("")
    elif r.get("ledger"):
        L += ["**No orders for the next session** — the account is on target.", ""]
    if r.get("equity"):
        e = r["equity"]
        last = r["ledger"][-1]
        L += [f"**Paper account:** ${e['now']:,.0f} ({e['ret_pct']:+.2f}% since {r['paper_start']}; "
              f"{e['dd_pct']:+.2f}% from peak) · holdings {last['holdings']} · cash ${last['cash']:,.0f}", ""]
    if r.get("gaps"):
        L += ["**Data gaps:** " + "; ".join(json.dumps(g) for g in r["gaps"][-5:]) +
              " — a gap holds the previous position; it is not a signal.", ""]
    s3 = r.get("s3")
    if s3:
        L += ["**Paper tracks (no money):**", "",
              "- S3 leveraged trend (failed its test 2026-11-22; forward record only): " + "; ".join(
                  f"{k} {_s3_word(v)} ({v['vs_200d_pct']:+.1f}% vs 200-day)" for k, v in s3["sleeves"].items())
              + (f" · since {r['paper_start']}: {len(s3['trades_since_start'])} trades, paper equity ${s3['nav']['equity']:,.0f}"
                 if s3.get("nav") else ""),
              "- M0 cards: Swing Desk brief and journal (paper).",
              "- Radar flags: scored automatically in `logs/radar/latest.md`.", ""]
    return "\n".join(L) + "\n"


def write_outputs(r: dict, stamp: str, out_data: Path = OUT_DATA, out_logs: Path = OUT_LOGS) -> str:
    from lever_lab import _jsonable
    md = render(r)
    js = json.dumps(_jsonable(r), indent=1, default=str)
    out_data.mkdir(parents=True, exist_ok=True)
    out_logs.mkdir(parents=True, exist_ok=True)
    (out_logs / "latest.md").write_text(md)
    (out_logs / f"{stamp}.md").write_text(md)
    (out_data / "latest.json").write_text(js)
    pd.DataFrame(r.get("ledger") or [], columns=["date", "equity", "cash", "holdings"]).to_csv(out_data / "ledger.csv", index=False)
    return md


def main(fetch: Optional[Callable] = None, brief_dir: Path = BRIEF_DIR) -> int:
    targets = load_targets(brief_dir)
    if not targets:
        print("[swing_engine] DATA FAILURE: no daily brief found; nothing written.")
        return 1
    tickers = sorted({t for x in targets.values() for t in x["weights"]} | {"SPY"})
    _log(f"{len(targets)} briefs; fetching {len(tickers)} funds ...")
    f = fetch or _fetch
    prices = f(tickers, "2026-10-01")
    if "SPY" not in prices:
        print("[swing_engine] DATA FAILURE: no SPY prices (trading calendar); nothing written.")
        return 1
    s3 = None
    try:
        hist = f(["SPY", "QQQ", "^IRX"], S3_SINCE) if fetch is None else fetch(["SPY", "QQQ", "^IRX"], S3_SINCE)
        if all(k in hist for k in ("SPY", "QQQ", "^IRX")):
            s3 = s3_shadow(hist["SPY"], hist["QQQ"], hist["^IRX"]["Close"])
    except Exception as e:
        _log(f"S3 shadow skipped: {type(e).__name__}: {e}")
    try:
        import market_time as mt
        today = mt.last_trading_day(mt.now_et().date()).isoformat()
    except Exception:
        today = None
    r = build(targets, prices, s3, today)
    md = write_outputs(r, datetime.now(timezone.utc).date().isoformat())
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    f = []
    cal = pd.bdate_range("2026-11-23", "2027-01-29")
    def px(level, drift=0.0):
        c = level * np.exp(np.cumsum(np.full(len(cal), drift)))
        return pd.DataFrame({"Open": c * 0.999, "High": c * 1.01, "Low": c * 0.99, "Close": c}, index=cal)
    prices = {"SPY": px(690), "SGOV": px(100.5, 0.00015), "GLD": px(320, 0.001), "TLT": px(88, -0.0005),
              "QQQ": px(600, 0.001), "XLU": px(43)}
    s = lambda d: d.isoformat() if isinstance(d, date) else d
    dfn = lambda: {"SGOV": 60.0, "GLD": 20.0, "TLT": 20.0}
    targets = {}
    for d in cal:
        targets[s(d.date())] = {"session": s(d.date()), "weights": dfn(), "state": "DEF", "switched": False}
    # brief parsing: a switch uses next_book; otherwise rows
    b_sw = {"session": "2026-11-20", "model": {"switch": {"next_book": {"SGOV": 60.0, "GLD": 20.0, "TLT": 20.0}, "to": "DEF"},
                                              "rows": [{"ticker": "VGT", "weight": 100.0}], "engine": {"state": "OUT"}}}
    t1 = target_from_brief(b_sw)
    if t1["weights"] != {"SGOV": 60.0, "GLD": 20.0, "TLT": 20.0} or not t1["switched"] or t1["state"] != "DEF":
        f.append(f"brief: a switch must use next_book: {t1}")
    b_rows = {"session": "2026-11-19", "model": {"rows": [{"ticker": "A", "weight": 49.9}, {"ticker": "B", "weight": 50.0},
                                                        {"ticker": "C", "weight": 0.0}], "engine": {"state": "OUT"}}}
    t2 = target_from_brief(b_rows)
    if set(t2["weights"]) != {"A", "B"} or abs(sum(t2["weights"].values()) - 100) > 1e-9 or t2["switched"]:
        f.append(f"brief: rows, zero weights dropped, normalized: {t2}")
    # ledger: first decision on the session before PAPER_START, fill at PAPER_START open
    sim = simulate(targets, prices, cal)
    fills = [e for e in sim["events"] if e["kind"] == "fill"]
    if not fills or fills[0]["date"] != "2026-12-01" or fills[0]["why"] != "account holds nothing yet":
        f.append(f"ledger: first fill at the 2026-12-01 open: {fills[:1]}")
    if sim["rows"][0]["date"] != "2026-12-01":
        f.append("ledger: rows start on the paper start")
    h = json.loads(sim["rows"][0]["holdings"])
    if not (h.get("SGOV") and h.get("GLD") and h.get("TLT")):
        f.append(f"ledger: holds the three Defense funds: {h}")
    eq0 = sim["rows"][0]["equity"]
    if not 9_900 < eq0 < 10_050:
        f.append(f"ledger: day-1 equity near $10,000 (slippage only): {eq0}")
    w, _ = _weights_now(sim["shares"], sim["cash"], prices, cal[cal.date >= PAPER_START][0])
    if abs(w.get("SGOV", 0) - 60) > 2 or abs(w.get("GLD", 0) - 20) > 4:
        f.append(f"ledger: whole shares land near target: {w}")
    # no churn: same target every day -> exactly one fill until a month start with drift < 5 pts
    if len(fills) != 1:
        f.append(f"ledger: unchanged target must not trade again: {[(e['date'], e['why']) for e in fills]}")
    # switch -> rebalance next open
    t2s = dict(targets)
    sw_day = "2026-12-15"
    for d in cal:
        if s(d.date()) >= sw_day:
            t2s[s(d.date())] = {"session": s(d.date()), "weights": {"QQQ": 50.0, "SPY": 50.0}, "state": "OFF",
                                "switched": s(d.date()) == sw_day}
    sim2 = simulate(t2s, prices, cal)
    f2 = [e for e in sim2["events"] if e["kind"] == "fill"]
    if len(f2) != 2 or f2[1]["date"] != "2026-12-16" or not f2[1]["why"].startswith("engine switched"):
        f.append(f"switch: one rebalance at the next open: {[(e['date'], e['why']) for e in f2]}")
    hs = json.loads(sim2["rows"][-1]["holdings"])
    if set(hs) != {"QQQ", "SPY"}:
        f.append(f"switch: the old book is fully sold: {hs}")
    # target move >= 2 pts triggers; < 2 does not
    t3 = dict(targets)
    for d in cal:
        if s(d.date()) >= "2026-12-10":
            t3[s(d.date())] = {**targets[s(d.date())], "weights": {"SGOV": 58.5, "GLD": 21.5, "TLT": 20.0}}
    if len([e for e in simulate(t3, prices, cal)["events"] if e["kind"] == "fill"]) != 1:
        f.append("trigger: a 1.5-pt target move must not trade")
    for d in cal:
        if s(d.date()) >= "2026-12-10":
            t3[s(d.date())] = {**targets[s(d.date())], "weights": {"SGOV": 57.5, "GLD": 22.5, "TLT": 20.0}}
    f3 = [e for e in simulate(t3, prices, cal)["events"] if e["kind"] == "fill"]
    if len(f3) != 2 or "target moved" not in f3[1]["why"]:
        f.append(f"trigger: a 2.5-pt target move must trade: {[(e['date'], e['why']) for e in f3]}")
    # month-start drift: GLD rallies hard -> January first session rebalances
    p4 = dict(prices)
    g = prices["GLD"].copy()
    g.loc[g.index >= "2026-12-15"] *= 1.6                  # GLD +60% mid-December -> ~29% of equity by January
    p4["GLD"] = g
    f4 = [e for e in simulate(targets, p4, cal)["events"] if e["kind"] == "fill"]
    jan = [d for d in cal if d.year == 2027]
    if not any(e["why"].startswith("month start") and e["date"] == jan[1].date().isoformat() for e in f4):
        f.append(f"trigger: month-start drift >= 5 pts rebalances at the next open: {[(e['date'], e['why']) for e in f4]}")
    # missing close for a target fund -> no tickets, gap recorded, no crash
    p5 = dict(prices)
    p5["TLT"] = prices["TLT"].drop(pd.Timestamp("2026-11-30"))
    sim5 = simulate(targets, p5, cal)
    if not any(g.get("missing_close") == ["TLT"] for g in sim5["gaps"]):
        f.append(f"gap: a missing close is recorded, not traded: {sim5['gaps'][:2]}")
    # fills: sells before buys; buys never exceed cash
    sh, cash, fl, _m = fill([{"ticker": "GLD", "side": "BUY", "shares": 100, "est_price": 320, "est_value": 32000},
                             {"ticker": "SGOV", "side": "SELL", "shares": 10, "est_price": 100, "est_value": 1000}],
                            {"SGOV": 10}, 500.0, prices, cal[0])
    if fl[0]["side"] != "SELL" or cash < 0 or sh.get("GLD", 0) * prices["GLD"].at[cal[0], "Open"] > 1_500 + 1e-6:
        f.append(f"fill: sells first, buys capped by cash: {fl} cash {cash}")
    # tiny trades skipped (XLU 230 -> 232 shares = $86)
    tk, _ = plan_tickets({"weights": {"XLU": 100.0}}, {"XLU": 230}, 100.0, prices, cal[0])
    if tk:
        f.append(f"plan: trades under ${MIN_TRADE:.0f} skipped: {tk}")
    # buys fill at the OPEN plus slippage
    _sh, _c, fb, _m = fill([{"ticker": "XLU", "side": "BUY", "shares": 10, "est_price": 43, "est_value": 430}], {},
                           1_000.0, prices, cal[0])
    if abs(fb[0]["fill"] - round(prices["XLU"].at[cal[0], "Open"] * (1 + SLIP_BPS / 1e4), 4)) > 1e-9:
        f.append(f"fill: buys at the open + {SLIP_BPS}bp: {fb}")
    # preview before paper start
    pre = {k: v.reindex(v.index.union([pd.Timestamp("2026-11-20")])).bfill().loc[:"2026-11-20"] for k, v in prices.items()}
    r = build({"2026-11-20": {**t1, "session": "2026-11-20"}}, pre, None, "2026-11-20")
    if not r.get("preview") or not r["preview"]["tickets"] or r["ledger"]:
        f.append(f"preview: before the paper start show $10k tickets, no ledger: {r.get('preview')}")
    # idempotent: two runs give the same ledger
    if simulate(targets, prices, cal)["rows"] != sim["rows"]:
        f.append("ledger must be identical on rerun")
    # writer + main end to end, and the no-brief abort
    import tempfile, os
    tmp = Path(tempfile.mkdtemp())
    (tmp / "logs" / "brief").mkdir(parents=True)
    (tmp / "logs" / "brief" / "2026-11-20_brief.json").write_text(json.dumps(b_sw))
    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        fake = pre
        rc = main(fetch=lambda t, st: {k: fake[k] for k in t if k in fake}, brief_dir=tmp / "logs" / "brief")
        js = json.loads((tmp / "data" / "swing_engine" / "latest.json").read_text())
        if rc != 0 or not js.get("preview") or not (tmp / "logs" / "swing_engine" / "latest.md").exists():
            f.append("main: preview run must write outputs")
        rc2 = main(fetch=lambda t, st: {k: fake[k] for k in t if k in fake}, brief_dir=tmp / "nope")
        if rc2 != 1:
            f.append("main: no brief -> DATA FAILURE")
    except Exception as e:
        f.append(f"main crashed: {type(e).__name__}: {e}")
    finally:
        os.chdir(cwd)
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        res = selftest()
        print(json.dumps(res, indent=2))
        sys.exit(0 if res["ok"] else 1)
    sys.exit(main())
