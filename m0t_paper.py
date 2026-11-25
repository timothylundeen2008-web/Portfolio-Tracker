"""
m0t_paper.py  (v1.2 — 2026-11-25)
──────────────────────────────────
v1.2: independent review 2026-11-25 (claude/review_protocol.md).
      B1 a fund whose earlier M0 trade is still running in the backtest (taken by the book or not)
         gets no order: the backtest drops such signals, so an order would never reach the ledger.
      B2/M1 the backtest now places orders on their card (swing_backtest v1.4 SELECTION="plan"), the
         same way plan_orders does; plan_orders reserves cash per order and uses each fund's cost.
      M2 an unreadable orders_seen.csv stops the run (nothing written) instead of being emptied;
         the writer refuses to drop any earlier row.
      M3 fills and exits are frozen the night first booked (fills_seen.csv, append-only); later
         dividend back-adjustments are reported as restatements, not silently absorbed.
      m1 streak mode comes from run_portfolio's own end state.  m4 logs are named by the session.
      m5 a missing or zero volume on the last bar stops the run.  Reconciliation now runs both ways:
         an order seen the night before that the book never placed is reported.
v1.1: (1) positions are marked by DATE on the paper calendar (aligned()); v1.0 passed a calendar
      starting 2026-12-01 to run_portfolio while close_cal was laid out from 2022, and
      run_portfolio reads close_cal by POSITION, so open positions would have been marked with
      prices from years earlier. (2) A run before the close drops today's partial bar.

Swing book, PAPER ONLY. The forward record of M0-T (trial 97: live M0 with no sector-rotation exit
and no ladder trims) on its own $10,000 paper account from 2026-12-01, at the live sizing
(1% risk on 3-of-3, 0.5% on 2-of-3, halved after 3 straight losses). Matt 2026-11-23:
"Yes to building 1, 2, and 3".

The swing ACCOUNT stays in SGOV (swing_engine.py, MODE "cash"); this is a separate paper record.
It uses swing_backtest's and m0t_lab's own code, not a copy, so the forward record is the same
rules as the backtest:
  * signals and trade paths: bt.run (M0, stop B) -> m0t.resimulate(ladder=(), rotation=False);
  * the book: bt.run_portfolio with the T-bill sweep, starting with $10,000 on PAPER_START;
  * only trades whose entry session is on/after PAPER_START count.
The ledger is recomputed from PAPER_START every night (idempotent). Yahoo revises prices, so the
script also keeps an APPEND-ONLY log of every order the night it was first seen
(data/m0t_paper/orders_seen.csv) and reports any ledger trade that was never seen in advance.

Also shows what happens at the NEXT open: buy-stop orders from tonight's signals (with the
portfolio's slot / sector / heat / streak rules applied) and exits triggered at tonight's close.
The swing limits (-10% month, -20% from high) are checked and reported; a breach blocks new orders
on the tab and is flagged for review. The recomputed ledger itself does not enforce them (same as
the backtest), so any breach is visible, not hidden.

Run:  python m0t_paper.py            (Actions; needs yfinance)
      python m0t_paper.py --selftest (offline)
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import swing_backtest as bt
import swing_desk as sd
import m0t_lab as m0t

VERSION = "1.2"
PAPER_START = date(2026, 12, 1)
FETCH_START = "2022-01-01"        # >= 252 + 320 bars of warm-up before PAPER_START
START_EQUITY = 10_000.0
PARTIAL_BAR_MINUTES = 20          # a bar for today is treated as incomplete until 20 min after the close
MONTH_LIMIT, HWM_LIMIT = -10.0, -20.0
OUT_DATA, OUT_LOGS = Path("data/m0t_paper"), Path("logs/m0t_paper")
SEEN_COLS = ["first_seen", "signal_date", "ticker", "buy_stop", "stop", "conf", "risk_pct", "shares"]
SEEN_COLS_V11 = SEEN_COLS[:-1]    # v1.1 logs had no shares column: read as shares "na"
FILL_COLS = ["first_seen", "event", "ticker", "entry_date", "date", "price", "shares"]
RESTATE_TOL = 0.005               # a frozen price that later differs by > 0.5% is reported as restated


class DataFailure(RuntimeError):
    pass


def _log(msg: str) -> None:
    print(f"[m0t_paper {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def aligned(data: dict, cal: pd.DatetimeIndex) -> dict:
    """run_portfolio reads data[tk]["close_cal"].iloc[k] with k = position in the calendar it is GIVEN.
    When that calendar is a slice of the one close_cal was built on, re-lay close_cal on it by date."""
    return {tk: {**d, "close_cal": d["close_cal"].reindex(cal)} for tk, d in data.items()}


def universe() -> tuple:
    etfs = bt.SECTOR_ETFS + list(bt.OTHER_ETFS)
    sector_of = {s: s for s in bt.SECTOR_ETFS}
    sector_of.update(bt.OTHER_ETFS)
    return etfs, sector_of


# ── tonight's decisions (the last bar; bt.run never emits signals on it) ──────

def prior_stop(tr, last: int) -> float:
    """The stop in force when the last bar's close is judged (before any tightening on that bar)."""
    s = [st for (t, st) in tr.stops if t < last]
    return float(s[-1]) if s else float(tr.stops[0][1])


def exit_at_next_open(tr, arr: dict) -> Optional[str]:
    """M0-T end-of-day rules on the LAST bar, in simulate_trade's order (variant B, no rotation exit,
    no ladder). Returns the exit reason that fills at the next open, or None."""
    c = arr["Close"]
    j = len(c) - 1
    if not tr.still_open or j <= tr.entry_t - 1:
        return None
    stop = prior_stop(tr, j)
    held = j - tr.entry_t
    if c[j] <= stop:
        return "closing-basis stop"
    if tr.asset == "lev" and held >= bt.LEV_MAX_DAYS:
        return "leveraged 90-day cap"
    ma = arr["sma100"]
    if j >= 3 and np.isfinite(ma[j]) and c[j] < ma[j] and not (ma[j] > ma[j - 3]):
        return "trend: close below falling trail MA"
    return None


def tonight_signals(ohlcv: dict, res: dict, etfs: list, sector_of: dict, running: frozenset = frozenset()) -> list:
    """M0 signals on the last bar, built exactly as bt.signals_for_ticker builds them for any
    earlier bar (prefilter -> production detector -> confluence >= 2), plus SPY > 200-day.
    `running`: funds with an M0 trade still open in m0t.resimulate (taken by the book or not); the
    backtest skips their signals (one open trade per fund), so they are marked and never ordered."""
    out = []
    bench = ohlcv["SPY"]["Close"]
    mkt = bt.market_ok(bench)
    quads_by_sector = bt.rotation_proxy({k: v["Close"] for k, v in ohlcv.items()})
    for tk, df in ohlcv.items():
        if tk not in etfs or len(df) < bt.WINDOW:
            continue
        x = bt.indicators(df, bench)
        pf = bt.prefilters(df, x)
        t = len(df) - 1
        if not pf["M0"][t]:
            continue
        w = df.iloc[t - bt.WINDOW + 1:t + 1]
        m0 = sd.detect_rotation_reclaim(w, True)
        if not m0["is_setup"]:
            continue
        sec = sector_of.get(tk)
        q = quads_by_sector.get(sec) if sec else None
        quad = q.reindex(df.index).iloc[t] if q is not None else None
        rot = bt._rot_leg(quad)
        conf = int(rot) + 1 + int(bool(m0["volume_ok"]))
        if conf < 2:
            continue
        mk = bool(mkt.reindex(df.index).ffill().fillna(False).iloc[t])
        out.append({"ticker": tk, "signal_date": df.index[t].date().isoformat(), "buy_stop": round(float(m0["entry"]), 2),
                    "stop": round(float(m0["stop"]), 2), "conf": conf, "size_mult": 1.0 if conf == 3 else 0.5,
                    "sector": sec or f"OTHER:{tk}", "quad": quad, "mkt_ok": mk,
                    "asset": bt._asset(tk, True), "running": tk in running})
    return out


def streak_reduced(closed: list) -> bool:
    """run_portfolio's streak rule replayed over closed trades in exit order."""
    losses = wins = 0
    reduced = False
    for tr in closed:
        if tr["r"] < -bt.SCRATCH_R:
            losses, wins = losses + 1, 0
        elif tr["r"] > bt.SCRATCH_R:
            wins, losses = wins + 1, 0
        if losses >= bt.STREAK_LOSSES:
            reduced = True
        if reduced and wins >= bt.STREAK_RESET_WINS:
            reduced = False
    return reduced


def plan_orders(sigs: list, open_pos: list, exits: dict, equity: float, cash: float, reduced: bool,
                blocked: Optional[str]) -> list:
    """Apply run_portfolio's selection rules to tonight's signals: rank (confluence, tighter stop),
    4 slots, 2 per sector, one per ticker, 8% heat, 30% cap, whole shares. Positions exiting at the
    open free their slot only after the open (the backtest settles exits first, so they do free it)."""
    staying = [p for p in open_pos if p["ticker"] not in exits]
    held = {p["ticker"] for p in staying}
    sec_n: dict = {}
    for p in staying:
        sec_n[p["sector"]] = sec_n.get(p["sector"], 0) + 1
    heat = sum(p["shares"] * max(0.0, p["entry"] - p["stop"]) for p in staying)
    slots = bt.MAX_POSITIONS - len(staying)
    out = []
    for s in sorted(sigs, key=lambda z: (-z["conf"], (z["buy_stop"] - z["stop"]) / z["buy_stop"], z["ticker"])):
        o = dict(s)
        rps = s["buy_stop"] - s["stop"]
        risk_pct = (bt.REDUCED_RISK_PCT if reduced else bt.BASE_RISK_PCT) * s["size_mult"]
        o["risk_pct"] = risk_pct
        why = None
        if blocked:
            why = blocked
        elif not s["mkt_ok"]:
            why = "SPY below its 200-day: no new entries"
        elif s.get("running"):
            why = "an earlier M0 trade on this fund is still running in the backtest (one per fund)"
        elif s["ticker"] in held:
            why = "already held"
        elif slots <= 0:
            why = "no free slot (4 positions)"
        elif sec_n.get(s["sector"], 0) >= bt.MAX_PER_SECTOR:
            why = "2 already in this sector"
        sh = 0
        if why is None:
            slots -= 1                                   # an order uses its slot even if it never fills
            sh = math.floor(equity * risk_pct / 100 / rps) if rps > 0 else 0
            sh = min(sh, math.floor(equity * bt.MAX_POSITION_PCT / 100 / s["buy_stop"]))
            bps = bt.COST_BPS[s.get("asset", "etf")]
            sh = min(sh, math.floor(max(0.0, cash) / (s["buy_stop"] * (1 + bps / 1e4))))
            if sh < 1:
                why = "size rounds to 0 shares"
            elif heat + sh * rps > equity * bt.HEAT_CAP_PCT / 100 + 1e-6:
                why = "would exceed the 8% open-risk cap"
            else:
                heat += sh * rps
                cash -= sh * s["buy_stop"] * (1 + bps / 1e4)     # each order's cost is set aside
                held.add(s["ticker"])
                sec_n[s["sector"]] = sec_n.get(s["sector"], 0) + 1
        o["shares"] = sh if why is None else 0
        o["status"] = "ORDER" if why is None else "no order"
        o["why"] = why or f"buy-stop {s['buy_stop']}, stop {s['stop']}, {sh} sh ≈ ${sh * s['buy_stop']:,.0f}, risk ≈ ${sh * rps:,.0f}"
        out.append(o)
    return out


# ── the book ───────────────────────────────────────────────────────────────

def build(ohlcv: dict, rates: dict, paper_start: date = PAPER_START, seen: Optional[pd.DataFrame] = None,
          sweep_mode: str = "TBILL", fills: Optional[pd.DataFrame] = None) -> dict:
    etfs, sector_of = universe()
    res = bt.run(ohlcv, etfs, [], sector_of, setups=("M0",), variants=("B",), verbose=False)
    data, cal_all = res["data"], res["cal"]
    asof = cal_all[-1]
    trs, unf = m0t.resimulate(res, ladder=(), rotation=False)
    p0 = pd.Timestamp(paper_start)
    ent = lambda tr: data[tr.ticker]["index"][tr.entry_t]
    sel = [t for t in trs if t.mkt_ok and ent(t) >= p0]
    ufs = [g for g in unf if g.mkt_ok and g.t + 1 < len(data[g.ticker]["index"])
           and data[g.ticker]["index"][g.t + 1] >= p0]
    live = asof >= p0
    out = {"version": VERSION, "asof": asof.date().isoformat(), "paper_start": paper_start.isoformat(),
           "mode": "paper" if live else "preview", "start_equity": START_EQUITY,
           "sizing": f"{bt.BASE_RISK_PCT:g}% / {bt.BASE_RISK_PCT * 0.5:g}% (3-of-3 / 2-of-3), "
                     f"{bt.REDUCED_RISK_PCT:g}% x confluence after {bt.STREAK_LOSSES} straight losses"}
    equity, cash, open_pos, closed, eq_rows = START_EQUITY, START_EQUITY, [], [], []
    spy_ret, reduced, placed = None, False, []
    if live:
        cal = cal_all[cal_all >= p0]
        sw, gaps = bt.sweep_inputs(ohlcv, rates, cal)
        out["gaps"] = gaps
        p = bt.run_portfolio(sel, ufs, aligned(data, cal), cal, sector_of, start_equity=START_EQUITY,
                             sweep=None if sweep_mode == "CASH0" else {"mode": sweep_mode, **sw},
                             limits=(MONTH_LIMIT, HWM_LIMIT))
        eq = p["equity"]
        equity = float(eq.iloc[-1])
        reduced = bool(p["reduced"])
        placed = [(d.date().isoformat(), tk, kind, int(sh)) for d, tk, kind, sh in p["placed"]]
        for tr, sh in p["taken"]:
            idx = data[tr.ticker]["index"]
            row = {"ticker": tr.ticker, "sector": sector_of.get(tr.ticker) or f"OTHER:{tr.ticker}",
                   "signal_date": idx[tr.signal_t].date().isoformat(), "entry_date": idx[tr.entry_t].date().isoformat(),
                   "entry": round(tr.entry, 2), "shares": int(sh), "conf": tr.conf, "stop0": round(tr.stop0, 2)}
            if tr.still_open:
                a = data[tr.ticker]["arr"]
                last = len(a["Close"]) - 1
                row.update({"stop": round(float(tr.stops[-1][1]), 2),
                            "disaster_stop": round(float(tr.stops[-1][1] - bt.DISASTER_ATR * a["atr14"][tr.signal_t]), 2),
                            "close": round(float(a["Close"][last]), 2),
                            "open_R": round((a["Close"][last] - tr.entry) / tr.risk, 2),
                            "value": round(sh * float(a["Close"][last]), 2),
                            "exit_next_open": exit_at_next_open(tr, a)})
                open_pos.append(row)
            else:
                px = [e for e in tr.events if e[1] != "entry"]
                row.update({"exit_date": idx[tr.exit_t].date().isoformat(), "exit_reason": tr.exit_reason,
                            "exit": round(float(px[-1][3]), 2) if px else None, "r": round(float(tr.r_net), 3),
                            "pnl": round(float(tr.r_net) * tr.risk * sh, 2)})
                closed.append(row)
        invested = sum(r["value"] for r in open_pos)
        cash = equity - invested
        eq_rows = [{"date": d.date().isoformat(), "equity": round(float(v), 2)} for d, v in eq.items()]
        spy = ohlcv["SPY"]["Close"]
        spy = spy[spy.index >= p0]
        if len(spy) >= 2:
            # SPY from the first session's OPEN, like the account (which can trade from that open)
            spy0 = float(ohlcv["SPY"]["Open"][ohlcv["SPY"].index >= p0].iloc[0])
            spy_ret = round((float(spy.iloc[-1]) / spy0 - 1) * 100, 2)
        m = eq[eq.index >= pd.Timestamp(asof.year, asof.month, 1)]
        prev = eq[eq.index < pd.Timestamp(asof.year, asof.month, 1)]
        base = float(prev.iloc[-1]) if len(prev) else START_EQUITY
        out["month_pct"] = round((float(m.iloc[-1]) / base - 1) * 100, 2) if len(m) else 0.0
        hi = eq.cummax().clip(lower=START_EQUITY)            # the $10,000 start counts as a high
        out["dd_from_high_pct"] = round((equity / float(hi.iloc[-1]) - 1) * 100, 2)
        out["max_dd_pct"] = round(float((eq / hi - 1).min()) * 100, 2)
        out["exposure_avg_pct"] = p["exposure_avg_pct"]
    else:
        out.update({"month_pct": 0.0, "dd_from_high_pct": 0.0, "max_dd_pct": 0.0})
    closed.sort(key=lambda r: (r["exit_date"], r["ticker"]))
    blocked = None
    if out["max_dd_pct"] <= HWM_LIMIT:                    # sticky, as in run_portfolio's limits gate
        blocked = "−20% from the high: STOP and review (restart only with Matt's approval)"
    elif out["month_pct"] <= MONTH_LIMIT:
        blocked = "−10% this month: no new entries until next month"
    exits = {r["ticker"]: r["exit_next_open"] for r in open_pos if r.get("exit_next_open")}
    running = frozenset(t.ticker for t in trs if t.still_open)
    sigs = tonight_signals(ohlcv, res, etfs, sector_of, running)
    orders = plan_orders(sigs, open_pos, exits, equity, cash + sum(
        r["value"] for r in open_pos if r["ticker"] in exits), reduced, blocked)
    if exits and any(o["status"] == "ORDER" for o in orders):
        for o in orders:
            if o["status"] == "ORDER":
                o["why"] += " · size may change if a sell at the open changes the 3-loss streak"
    # reconciliation, both ways
    unseen, unplaced = [], []
    if seen is not None and len(seen) and live:
        keys = set(zip(seen["signal_date"].astype(str), seen["ticker"].astype(str)))
        first = str(seen["first_seen"].min())
        for r in open_pos + closed:
            if r["signal_date"] >= first and (r["signal_date"], r["ticker"]) not in keys:
                unseen.append(f"{r['ticker']} (signal {r['signal_date']})")
        # every order printed on a night the book could act on must have been placed by the book
        prev = cal_all[cal_all < p0]
        lo = prev[-1].date().isoformat() if len(prev) else paper_start.isoformat()
        pk = {(d, tk): sh for d, tk, _k, sh in placed}
        ordered_sh = {(str(a_), str(b_)): str(c_) for a_, b_, c_ in seen[["signal_date", "ticker", "shares"]].to_numpy()}
        for d, tk in sorted(keys):
            if not (lo <= d < out["asof"]):
                continue
            if (d, tk) not in pk:
                unplaced.append(f"{tk} (signal {d})")
            elif ordered_sh.get((d, tk), "na") not in ("na", str(pk[(d, tk)])):
                unplaced.append(f"{tk} (signal {d}): ordered {ordered_sh[(d, tk)]} sh, book placed {pk[(d, tk)]}")
    restated = []
    if fills is not None and len(fills):
        fz = {(r.event, r.ticker, r.entry_date): r for r in fills.itertuples()}
        for r in open_pos + closed:
            for ev, px, d in (("entry", r["entry"], r["entry_date"]), ("exit", r.get("exit"), r.get("exit_date"))):
                f0 = fz.get((ev, r["ticker"], r["entry_date"]))
                if f0 is None or px is None:
                    continue
                if abs(float(f0.price) / px - 1) > RESTATE_TOL or (ev == "entry" and int(float(f0.shares)) != r["shares"]):
                    restated.append(f"{r['ticker']} {ev} {d}: booked {float(f0.price):.2f} × {int(float(f0.shares))} sh, "
                                    f"now {px:.2f} × {r['shares']} sh")
    out.update({"equity": round(equity, 2), "cash": round(cash, 2),
                "ret_pct": round((equity / START_EQUITY - 1) * 100, 2), "spy_ret_pct": spy_ret,
                "open": open_pos, "closed": closed, "exits_next_open": exits, "orders": orders,
                "limit_block": blocked, "streak_reduced": reduced, "placed": placed,
                "unseen_trades": unseen, "unplaced_orders": unplaced, "restated": restated, "equity_curve": eq_rows,
                "closed_stats": bt.trade_stats([r["r"] for r in closed]) if closed else {"n": 0},
                "expected": {"expectancy_R": 0.44, "profit_factor": 1.83, "win_rate": 28.4,
                             "source": "trial 97 backtest, 2005–2026"}})
    return out


def drop_partial(ohlcv: dict, today) -> dict:
    """Remove a bar dated `today` from every frame (an intraday run sees a partial daily bar)."""
    t = pd.Timestamp(today)
    return {k: v[v.index.normalize() != t] for k, v in ohlcv.items()}


def update_seen(seen: pd.DataFrame, orders: list, first_seen: str) -> pd.DataFrame:
    rows = [{"first_seen": first_seen, "signal_date": o["signal_date"], "ticker": o["ticker"],
             "buy_stop": o["buy_stop"], "stop": o["stop"], "conf": o["conf"], "risk_pct": o["risk_pct"],
             "shares": o["shares"]} for o in orders if o["status"] == "ORDER"]
    new = pd.DataFrame(rows, columns=SEEN_COLS).astype(str)
    allr = pd.concat([seen, new], ignore_index=True) if len(seen) else new
    return allr.drop_duplicates(subset=["signal_date", "ticker"], keep="first").reset_index(drop=True)


def _load_log(path: Path, cols: list) -> pd.DataFrame:
    """Append-only logs: a missing file is empty; a file that will not parse is a DATA FAILURE
    (never silently replaced by an empty log)."""
    if not path.exists():
        return pd.DataFrame(columns=cols)
    try:
        df = pd.read_csv(path, dtype=str, on_bad_lines="error")
    except Exception as e:
        raise DataFailure(f"{path} will not parse ({type(e).__name__}: {e})") from e
    if cols == SEEN_COLS and list(df.columns) == SEEN_COLS_V11:
        df["shares"] = "na"                              # migrate a v1.1 log
    if list(df.columns) != cols or df.isna().any().any():
        raise DataFailure(f"{path} has unexpected columns or blank cells")
    return df


def load_seen(out_data: Path = OUT_DATA) -> pd.DataFrame:
    return _load_log(out_data / "orders_seen.csv", SEEN_COLS)


def load_fills(out_data: Path = OUT_DATA) -> pd.DataFrame:
    return _load_log(out_data / "fills_seen.csv", FILL_COLS)


def update_fills(fills: pd.DataFrame, r: dict) -> pd.DataFrame:
    """Freeze each entry and exit the first night it is booked (keyed by event, fund, entry date)."""
    rows = []
    for x in r["open"] + r["closed"]:
        rows.append({"first_seen": r["asof"], "event": "entry", "ticker": x["ticker"], "entry_date": x["entry_date"],
                     "date": x["entry_date"], "price": x["entry"], "shares": x["shares"]})
        if x.get("exit_date"):
            rows.append({"first_seen": r["asof"], "event": "exit", "ticker": x["ticker"], "entry_date": x["entry_date"],
                         "date": x["exit_date"], "price": x["exit"], "shares": x["shares"]})
    new = pd.DataFrame(rows, columns=FILL_COLS).astype(str)
    allr = pd.concat([fills, new], ignore_index=True) if len(fills) else new
    return allr.drop_duplicates(subset=["event", "ticker", "entry_date"], keep="first").reset_index(drop=True)


def _keeps_all(old: pd.DataFrame, new: pd.DataFrame, key: list) -> bool:
    if not len(old):
        return True
    k_new = set(map(tuple, new[key].astype(str).to_numpy()))
    return all(tuple(k) in k_new for k in old[key].astype(str).to_numpy())


def render(r: dict) -> str:
    spy = "—" if r["spy_ret_pct"] is None else f"{r['spy_ret_pct']:+.2f}%"
    L = [f"# M0-T paper record — {r['asof']} ({'PAPER' if r['mode'] == 'paper' else 'PREVIEW: starts ' + r['paper_start']})", "",
         "Paper only, no money. The swing account itself stays in SGOV. Research, not personalized advice.", "",
         f"- Account: **${r['equity']:,.2f}** on $10,000 ({r['ret_pct']:+.2f}%); SPY since start: {spy}",
         f"- This month {r['month_pct']:+.2f}% (limit −10%) · from the high {r['dd_from_high_pct']:+.2f}% (limit −20%)"
         + (f" · **{r['limit_block']}**" if r["limit_block"] else ""),
         f"- Sizing: {r['sizing']}" + (" · **streak mode on (half size)**" if r["streak_reduced"] else ""), ""]
    if r["open"]:
        L += ["## Open positions", "", "| Fund | Since | Shares | Entry | Close | Stop | Disaster stop | Open R | Next open |",
              "|---|---|---|---|---|---|---|---|---|"]
        for p in r["open"]:
            L.append(f"| {p['ticker']} | {p['entry_date']} | {p['shares']} | {p['entry']} | {p['close']} | {p['stop']} | "
                     f"{p['disaster_stop']} | {p['open_R']:+.2f} | {('SELL: ' + p['exit_next_open']) if p['exit_next_open'] else 'hold'} |")
        L.append("")
    L += ["## Orders for the next open", ""]
    if r["orders"]:
        L += ["| Fund | Status | Confluence | Detail |", "|---|---|---|---|"]
        for o in r["orders"]:
            L.append(f"| {o['ticker']} | {o['status']} | {o['conf']}-of-3 | {o['why']} |")
    else:
        L.append("No M0 signal at tonight's close.")
    if r["closed"]:
        s = r["closed_stats"]
        L += ["", f"## Closed trades: {s.get('n')} · win {s.get('win_rate')}% · expectancy {s.get('expectancy_R')}R · "
              f"PF {s.get('profit_factor')} (backtest: {r['expected']['expectancy_R']}R, PF {r['expected']['profit_factor']})", "",
              "| Fund | In | Out | Why | R | P&L |", "|---|---|---|---|---|---|"]
        for c in r["closed"][-20:]:
            L.append(f"| {c['ticker']} | {c['entry_date']} | {c['exit_date']} | {c['exit_reason']} | {c['r']:+.2f} | ${c['pnl']:+,.2f} |")
    if r.get("unplaced_orders"):
        L += ["", "**Reconciliation:** orders printed the night before that the book did not place: " + ", ".join(r["unplaced_orders"])]
    if r.get("restated"):
        L += ["", "**Restated since first booked** (Yahoo back-adjusts for dividends; the frozen record is "
              "data/m0t_paper/fills_seen.csv): " + "; ".join(r["restated"])]
    if r.get("unseen_trades"):
        L += ["", "**Reconciliation:** trades not seen as orders the night before (price revision?): " + ", ".join(r["unseen_trades"])]
    if r.get("gaps"):
        L += ["", "Data gaps: " + "; ".join(r["gaps"])]
    L += ["", f"*m0t_paper.py {VERSION}*"]
    return "\n".join(L) + "\n"


def write_outputs(r: dict, seen: pd.DataFrame, stamp: str, out_data: Path = OUT_DATA, out_logs: Path = OUT_LOGS,
                  fills: Optional[pd.DataFrame] = None) -> str:
    from lever_lab import _jsonable
    md = render(r)
    js = json.dumps(_jsonable(r), indent=1, default=str)
    seen2 = update_seen(seen, r["orders"], r["asof"])
    fills = fills if fills is not None else pd.DataFrame(columns=FILL_COLS)
    fills2 = update_fills(fills, r) if r["mode"] == "paper" else fills
    if not _keeps_all(seen, seen2, ["signal_date", "ticker"]) or not _keeps_all(fills, fills2, ["event", "ticker", "entry_date"]):
        raise DataFailure("an append-only log would lose an earlier row; nothing written")
    out_data.mkdir(parents=True, exist_ok=True)
    out_logs.mkdir(parents=True, exist_ok=True)
    (out_data / "summary.json").write_text(js)
    seen2.to_csv(out_data / "orders_seen.csv", index=False)
    if len(fills2):
        fills2.to_csv(out_data / "fills_seen.csv", index=False)
    (out_logs / "latest.md").write_text(md)
    (out_logs / f"{stamp}.md").write_text(md)
    return md


def main(fetch=None, out_data: Path = OUT_DATA, out_logs: Path = OUT_LOGS, expect_session: Optional[str] = "auto") -> int:
    etfs, _s = universe()
    fetch = fetch or bt.fetch_ohlcv
    _log("fetching prices ...")
    ohlcv = fetch(sorted(set(etfs)), FETCH_START)
    for attempt in range(3):
        miss = sorted(set(etfs) - set(ohlcv))
        if not miss:
            break
        _log(f"retry {attempt + 1}: {', '.join(miss)}")
        for t in miss:
            ohlcv.update(fetch([t], FETCH_START))
    miss = sorted(set(etfs) - set(ohlcv))
    if miss or "SPY" not in ohlcv:
        print(f"[m0t_paper] DATA FAILURE: no prices for {', '.join(miss) or 'SPY'} after retries; nothing written.")
        return 1
    if expect_session == "auto":
        import market_time as mt
        today = mt.now_et().date()
        if mt.is_trading_day(today) and (mt.minutes_since_close() or 0) < PARTIAL_BAR_MINUTES:
            ohlcv = drop_partial(ohlcv, today)   # run before (or just after) the close: today's bar is incomplete
            expect_session = mt.last_trading_day(today - pd.Timedelta(days=1)).isoformat()
            _log(f"run before today's close is final: using bars through {expect_session}")
        else:
            expect_session = mt.last_trading_day(today).isoformat()
    last = ohlcv["SPY"].index[-1].date().isoformat()
    stale = sorted(t for t, df in ohlcv.items() if df.index[-1] != ohlcv["SPY"].index[-1])
    if stale:
        print(f"[m0t_paper] DATA FAILURE: last bar differs from SPY's ({last}) for {', '.join(stale)}; nothing written.")
        return 1
    if expect_session and last < expect_session:
        print(f"[m0t_paper] DATA FAILURE: prices end {last}, expected the {expect_session} session; nothing written.")
        return 1
    novol = sorted(t for t, df in ohlcv.items() if not (np.isfinite(df["Volume"].iloc[-1]) and df["Volume"].iloc[-1] > 0))
    if novol:
        print(f"[m0t_paper] DATA FAILURE: no volume on the {last} bar for {', '.join(novol)}; nothing written.")
        return 1
    rates = fetch(["^IRX"], FETCH_START)
    try:
        seen, fills = load_seen(out_data), load_fills(out_data)
        r = build(ohlcv, rates, seen=seen, fills=fills)
        md = write_outputs(r, seen, r["asof"], out_data, out_logs, fills=fills)
    except DataFailure as e:
        print(f"[m0t_paper] DATA FAILURE: {e}; nothing written.")
        return 1
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _fixture(n=1100, k=None):
    etfs, _s = universe()
    keep = ["SPY", "XLK", "XLE", "XLF", "XLV", "XLU", "XLI", "QQQ", "TQQQ", "SMH"] if k is None else k
    return {tk: bt._walk(i + 3, n=n, drift=0.0005 + 0.0002 * (i % 4)) for i, tk in enumerate(keep)}


def prev_session(r: dict) -> str:
    """The session before r's as-of date (from its equity curve)."""
    days = [x["date"] for x in r["equity_curve"]]
    return days[-2] if len(days) >= 2 else r["asof"]


def selftest() -> dict:
    import contextlib, io, os, tempfile
    f = []
    ohl = _fixture()
    irx = pd.DataFrame({"Open": 4.0, "High": 4.0, "Low": 4.0, "Close": 4.0, "Volume": 0}, index=ohl["SPY"].index)
    rates = {"^IRX": irx}
    etfs, sector_of = universe()
    cal = ohl["SPY"].index
    ps = cal[len(cal) - 300].date()                    # paper start 300 sessions before the end
    with contextlib.redirect_stdout(io.StringIO()):
        r = build(ohl, rates, paper_start=ps)
    if r["mode"] != "paper":
        f.append("mode must be paper after the start date")
    if not (r["closed"] or r["open"]):
        f.append("fixture: need paper trades")
    if any(c["entry_date"] < ps.isoformat() for c in r["closed"] + r["open"]):
        f.append("no trade may enter before the paper start")
    # 1. the paper book, run on its own short calendar, must equal the same trades run on the FULL
    #    calendar the prices are laid out on (CASH0, so nothing accrues before the start): marking is by date.
    with contextlib.redirect_stdout(io.StringIO()):
        r0 = build(ohl, rates, paper_start=ps, sweep_mode="CASH0")
    res = bt.run(ohl, etfs, [], sector_of, setups=("M0",), variants=("B",), verbose=False)
    trs, unf = m0t.resimulate(res, ladder=(), rotation=False)
    p0 = pd.Timestamp(ps)
    sel = [t for t in trs if t.mkt_ok and res["data"][t.ticker]["index"][t.entry_t] >= p0]
    ufs = [g for g in unf if g.mkt_ok and g.t + 1 < len(res["data"][g.ticker]["index"]) and res["data"][g.ticker]["index"][g.t + 1] >= p0]
    pf = bt.run_portfolio(sel, ufs, res["data"], res["cal"], sector_of)
    full_eq = pf["equity"][pf["equity"].index >= p0]
    mine = pd.Series({pd.Timestamp(x["date"]): x["equity"] for x in r0["equity_curve"]})
    gap = float((mine - full_eq.reindex(mine.index)).abs().max())
    if not (gap < 0.02 and len(mine) == len(full_eq)):
        f.append(f"paper book must match the full-calendar pass day by day (max gap ${gap:,.2f})")
    if not r0["open"] and not r0["closed"]:
        f.append("fixture: the identity check needs trades")
    # an open position is marked at ITS close on the last day
    for o in r["open"]:
        px = float(ohl[o["ticker"]]["Close"].iloc[-1])
        if abs(o["close"] - round(px, 2)) > 0.011:
            f.append(f"open {o['ticker']} marked at {o['close']}, its last close is {px:.2f}")
            break
    if bt.LADDER != (2.0, 4.0, 8.0):
        f.append("bt.LADDER must be restored")
    if any(c["exit_reason"].startswith("thesis") for c in r["closed"]):
        f.append("M0-T never exits on rotation")
    # 2. preview before the start: no ledger, $10k
    with contextlib.redirect_stdout(io.StringIO()):
        rp = build(ohl, rates, paper_start=(cal[-1] + pd.Timedelta(days=30)).date())
    if rp["mode"] != "preview" or rp["closed"] or rp["open"] or rp["equity"] != START_EQUITY:
        f.append("preview must show an empty $10,000 account")
    # 3 + 4. on consecutive nights of a small fixture: tonight_signals == the signals bt.run emits
    #        for that bar once one more bar exists; exit_at_next_open == the exit simulate_trade takes.
    sm = _fixture(n=800, k=["SPY", "XLK", "XLE", "XLF", "TQQQ", "SMH"])
    scal = sm["SPY"].index
    runs = {}

    def run_at(cut):
        if cut not in runs:
            sub = {k: v.iloc[:cut + 1] for k, v in sm.items()}
            with contextlib.redirect_stdout(io.StringIO()):
                rs_ = bt.run(sub, etfs, [], sector_of, setups=("M0",), variants=("B",), verbose=False)
                tt, _u = m0t.resimulate(rs_, ladder=(), rotation=False)
            runs[cut] = (sub, rs_, tt)
        return runs[cut]

    hits = misses = agree = checked = 0
    for cut in range(len(scal) - 61, len(scal) - 1):
        sub, rs, t1 = run_at(cut)
        _n, rn, t2 = run_at(cut + 1)
        mine = {(s_["ticker"], round(s_["buy_stop"], 2)) for s_ in tonight_signals(sub, rs, etfs, sector_of)}
        theirs = {(g.ticker, round(g.level, 2)) for g in rn["signals"] if g.t == cut}
        misses += int(mine != theirs)
        hits += len(theirs)
        by2 = {(t.ticker, t.entry_t): t for t in t2}
        j = cut + 1
        for tr in [t for t in t1 if t.still_open]:
            nx = by2.get((tr.ticker, tr.entry_t))
            if nx is None or (nx.exit_t == j and nx.exit_reason == "disaster stop"):
                continue                                 # intraday stop on the new bar: not knowable tonight
            theirs_x = nx.exit_reason if (nx.exit_t == j and not nx.still_open) else None
            checked += 1
            agree += int(exit_at_next_open(tr, rs["data"][tr.ticker]["arr"]) == theirs_x)
    if misses:
        f.append(f"tonight_signals disagrees with bt.run on {misses} nights")
    if hits < 3:
        f.append(f"fixture: too few last-bar signals to prove tonight_signals ({hits})")
    if checked < 20:
        f.append(f"fixture: too few open-trade nights to prove exit_at_next_open ({checked})")
    elif agree != checked:
        f.append(f"exit_at_next_open disagrees with simulate_trade on {checked - agree} of {checked}")
    # 5. order planning rules
    base_sig = {"signal_date": "2026-12-02", "buy_stop": 100.0, "stop": 95.0, "conf": 3, "size_mult": 1.0, "mkt_ok": True, "quad": "Leading"}
    s = [dict(base_sig, ticker=f"T{i}", sector="XLK" if i < 3 else f"S{i}") for i in range(6)]
    o = plan_orders(s, [], {}, 10_000.0, 10_000.0, False, None)
    st_ = [x["status"] for x in o]
    if st_.count("ORDER") != 4 or sum(1 for x in o if x["status"] == "ORDER" and x["sector"] == "XLK") != 2:
        f.append(f"plan_orders: 4 slots, 2 per sector: {st_}")
    if o[0]["shares"] != 20:                           # $100 risk / $5 = 20 sh ($2,000 < 30% cap)
        f.append(f"plan_orders: 1% of $10k / $5 risk = 20 sh, got {o[0]['shares']}")
    o2 = plan_orders(s[:1], [], {}, 10_000.0, 10_000.0, True, None)
    if o2[0]["shares"] != 10:
        f.append("plan_orders: streak mode halves size")
    tight = [dict(base_sig, ticker="T", sector="XLK", stop=99.5)]
    if plan_orders(tight, [], {}, 10_000.0, 10_000.0, False, None)[0]["shares"] != 30:
        f.append("plan_orders: 30% cap must bind on a tight stop")
    if plan_orders(s[:1], [], {}, 10_000.0, 10_000.0, False, "−10% this month")[0]["status"] != "no order":
        f.append("plan_orders: a limit block must stop orders")
    if plan_orders([dict(base_sig, ticker="T", sector="XLK", mkt_ok=False)], [], {}, 1e4, 1e4, False, None)[0]["status"] != "no order":
        f.append("plan_orders: SPY below 200-day must stop orders")
    full = [{"ticker": f"H{i}", "sector": f"Q{i}", "shares": 10, "entry": 100.0, "stop": 95.0} for i in range(4)]
    if plan_orders(s[:1], full, {}, 1e4, 1e4, False, None)[0]["status"] != "no order":
        f.append("plan_orders: 4 open positions leave no slot")
    if plan_orders(s[:1], full, {"H0": "closing-basis stop"}, 1e4, 1e4, False, None)[0]["status"] != "ORDER":
        f.append("plan_orders: a position exiting at the open frees its slot")
    # 5b. review findings B1/B2/M1 (2026-11-25): every ORDER printed on a night must be exactly what the
    #     next night's book places for that signal date (fund and shares), and nothing else.
    rcal = sm["SPY"].index
    rps_ = rcal[len(rcal) - 150].date()
    prev, n_ord, bad_nights = None, 0, []
    for cut in range(len(rcal) - 120, len(rcal)):
        sub = {k_: v.iloc[:cut + 1] for k_, v in sm.items()}
        with contextlib.redirect_stdout(io.StringIO()):
            rr_ = build(sub, rates, paper_start=rps_)
        if prev is not None:
            mine_o = {(o["ticker"], o["shares"]) for o in prev["orders"] if o["status"] == "ORDER"}
            theirs_o = {(tk, sh) for dd, tk, _k, sh in rr_["placed"] if dd == prev["asof"]}
            n_ord += len(mine_o)
            if mine_o != theirs_o:
                bad_nights.append(f"{prev['asof']}: ordered {sorted(mine_o)}, book placed {sorted(theirs_o)}")
        prev = rr_
    if bad_nights:
        f.append("orders vs next night's book: " + "; ".join(bad_nights[:3]))
    if n_ord < 5:
        f.append(f"fixture: too few ORDER rows to prove the replay ({n_ord})")
    # B2: an order that never fills still takes its slot and sector place; ranking uses the card only
    rc = pd.bdate_range("2026-12-01", periods=5)
    tks = ["A", "B", "C", "D", "E"]
    sec_t = {t_: f"S{t_}" for t_ in tks}
    dat = {t_: {"index": rc, "close_cal": pd.Series(100.0, index=rc), "asset": "etf"} for t_ in tks}
    stops_ = {"A": 97.0, "B": 96.5, "C": 96.0, "D": 95.5, "E": 95.0}

    def mk(t_, stop, fill):
        tr_ = bt.Trade(t_, "M0", "B", 0, 1, fill, stop, 3, 1.0, "etf", 100.0 - stop, True)
        tr_.events += [(1, "entry", 1.0, fill, 3.0), (4, "mark", 1.0, 100.0, 0.0)]
        tr_.stops.append((1, stop)); tr_.still_open = True; tr_.exit_t = 4; tr_.r_net = 0.0
        return tr_
    pb = bt.run_portfolio([mk(t_, stops_[t_], 100.0) for t_ in "BCDE"],
                          [bt.Signal("A", 0, "M0", "stop", 100.0, 97.0, 3, 1.0, True, None, 100.0)], dat, rc, sec_t)
    sig5 = [{"ticker": t_, "signal_date": str(rc[0].date()), "buy_stop": 100.0, "stop": stops_[t_], "conf": 3,
             "size_mult": 1.0, "sector": sec_t[t_], "quad": "Leading", "mkt_ok": True} for t_ in tks]
    po = plan_orders(sig5, [], {}, 1e4, 1e4, False, None)
    if sorted(tr_.ticker for tr_, _ in pb["taken"]) != ["B", "C", "D"] or \
            [x["ticker"] for x in po if x["status"] == "ORDER"] != ["A", "B", "C", "D"]:
        f.append("B2: the book must place A (tightest card, no fill) and skip E, like plan_orders")
    # M1: a gap open above the buy-stop does not change the share count set by the card
    pg = bt.run_portfolio([mk("A", 99.0, 104.0)], [], dat, rc, sec_t)
    og = plan_orders([dict(sig5[0], stop=99.0)], [], {}, 1e4, 1e4, False, None)
    if pg["taken"][0][1] != og[0]["shares"]:
        f.append(f"M1: gap fill {pg['taken'][0][1]} sh vs ordered {og[0]['shares']}")
    # B1: a fund with a running backtest trade gets no order
    if plan_orders([dict(sig5[0], running=True)], [], {}, 1e4, 1e4, False, None)[0]["status"] != "no order":
        f.append("B1: a fund with a running backtest trade must get no order")
    # cash is set aside per order
    big = [dict(sig5[i], stop=99.0, sector=f"Z{i}") for i in range(4)]
    if sum(x["shares"] * x["buy_stop"] for x in plan_orders(big, [], {}, 1e4, 1e4, False, None)) > 1e4:
        f.append("plan_orders must not spend the same cash twice")
    # legacy selection reproduces trial 97-era behaviour (unfilled order ranked last)
    saved_sel = bt.SELECTION
    try:
        bt.SELECTION = "legacy"
        pl = bt.run_portfolio([mk(t_, stops_[t_], 100.0) for t_ in "BCDE"],
                              [bt.Signal("A", 0, "M0", "stop", 100.0, 97.0, 3, 1.0, True, None, 100.0)], dat, rc, sec_t)
        if sorted(tr_.ticker for tr_, _ in pl["taken"]) != ["B", "C", "D", "E"]:
            f.append("legacy selection must reproduce v1.3")
    finally:
        bt.SELECTION = saved_sel
    # second review (2026-11-25): run_portfolio in "plan" must not let anything after the open feed
    # an order placed the night before
    c30 = pd.bdate_range("2020-01-01", periods=30)
    d30 = {f"T{i}": {"index": c30, "close_cal": pd.Series(100.0, index=c30), "asset": "etf"} for i in range(8)}
    s30 = {f"T{i}": f"S{i}" for i in range(8)}

    def mkx(tk, et, xt, xpx, why, stop=95.0, conf=3, entry=100.0, plan=100.0):
        tr_ = bt.Trade(tk, "M0", "B", et - 1, et, entry, stop, conf, 1.0, "etf", plan - stop)
        tr_.events = [(et, "entry", 1.0, entry, 3.0), (xt, "exit", 1.0, xpx, 3.0)]
        tr_.stops = [(et, stop)]; tr_.exit_t = xt; tr_.exit_reason = why
        tr_.r_net = (xpx - entry) / (plan - stop)
        return tr_
    # (a) an entry-bar stop on one new position must not halve the next order's size that day
    pa = bt.run_portfolio([mkx("T0", 1, 3, 90.0, "closing-basis stop"), mkx("T1", 2, 4, 90.0, "closing-basis stop"),
                           mkx("T2", 10, 10, 95.0, "stop", stop=96.0), mkx("T3", 10, 20, 100.0, "closing-basis stop")],
                          [], d30, c30, s30, heat_cap_pct=100.0)
    if dict((t_.ticker, sh_) for t_, sh_ in pa["taken"]).get("T3") != 19:
        f.append("plan: a same-day stop changed a later order's size (streak look-ahead)")
    # (b) its sale proceeds must not fund a later order the same day; sizing uses last night's money
    pb2 = bt.run_portfolio([mkx("T0", 1, 25, 100.0, "closing-basis stop", stop=50.0), mkx("T1", 1, 25, 100.0, "closing-basis stop", stop=50.0),
                            mkx("T2", 10, 10, 99.0, "stop", stop=99.0), mkx("T3", 10, 20, 100.0, "closing-basis stop", stop=80.0)],
                           [], d30, c30, s30, heat_cap_pct=100.0)
    if dict((t_.ticker, sh_) for t_, sh_ in pb2["taken"]).get("T3") != 4:
        f.append("plan: same-day stop proceeds funded a later order (cash look-ahead)")
    # (c) an earlier fill's gap must not change a later order's planned size (fill may be clipped)
    for gp in (100.0, 110.0):
        pc_ = bt.run_portfolio([mkx("T0", 1, 25, 100.0, "closing-basis stop", stop=99.5), mkx("T1", 1, 25, 100.0, "closing-basis stop", stop=99.5),
                                mkx("T2", 10, 20, 100.0, "closing-basis stop", stop=99.0, entry=gp),
                                mkx("T3", 10, 20, 100.0, "closing-basis stop", stop=98.9)], [], d30, c30, s30, heat_cap_pct=100.0)
        if [x[3] for x in pc_["placed"] if x[1] == "T3"] != [10]:
            f.append(f"plan: T2 filling at {gp} changed T3's planned size"); break
    # (d) the end-of-data mark must not free slots for the last day's orders
    n30 = len(c30)

    def mko(tk, et, stop):
        tr_ = bt.Trade(tk, "M0", "B", et - 1, et, 100.0, stop, 3, 1.0, "etf", 100.0 - stop)
        tr_.events = [(et, "entry", 1.0, 100.0, 3.0), (n30 - 1, "mark", 1.0, 100.0, 0.0)]
        tr_.stops = [(et, stop)]; tr_.still_open = True; tr_.exit_t = n30 - 1; tr_.r_net = 0.0
        return tr_
    s30b = dict(s30, T0="A", T1="A", T2="B", T3="B", T4="C")
    pd_ = bt.run_portfolio([mko("T0", 1, 99.5), mko("T1", 1, 99.5), mko("T2", 2, 99.5), mko("T3", 2, 99.5), mko("T4", n30 - 1, 99.0)],
                           [], d30, c30, s30b, heat_cap_pct=100.0)
    if any(t_.ticker == "T4" for t_, _ in pd_["taken"]):
        f.append("plan: the end-of-data mark freed a slot for the last day's orders")
    # (e) the swing limits gate the book itself, like the printed orders
    lc = pd.bdate_range("2020-01-01", periods=40)
    ld = {"A": {"index": lc, "close_cal": pd.Series(np.r_[np.full(5, 100.0), np.full(35, 30.0)], index=lc), "asset": "etf"},
          "B": {"index": lc, "close_cal": pd.Series(100.0, index=lc), "asset": "etf"}}
    ta = bt.Trade("A", "M0", "B", 0, 1, 100.0, 99.0, 3, 1.0, "etf", 1.0)     # 30% cap: 30 sh; 100 -> 30 = -21%
    ta.events = [(1, "entry", 1.0, 100.0, 3.0), (39, "mark", 1.0, 30.0, 0.0)]; ta.stops = [(1, 99.0)]
    ta.still_open = True; ta.exit_t = 39; ta.r_net = -0.67
    tb_ = mkx("B", 20, 30, 100.0, "closing-basis stop", stop=99.0)
    lim_on = bt.run_portfolio([ta, tb_], [], ld, lc, {"A": "SA", "B": "SB"}, heat_cap_pct=100.0, limits=(-10.0, -20.0))
    lim_off = bt.run_portfolio([ta, tb_], [], ld, lc, {"A": "SA", "B": "SB"}, heat_cap_pct=100.0)
    if any(t_.ticker == "B" for t_, _ in lim_on["taken"]) or not any(t_.ticker == "B" for t_, _ in lim_off["taken"]):
        f.append("limits: after a −20% close the book must place no new orders (and does without limits)")
    # (e2) the paper build must hand the same limits to the book
    got_kw, orig_rp = {}, bt.run_portfolio

    def spy_rp(*a_, **k_):
        got_kw.update(k_)
        return orig_rp(*a_, **k_)
    bt.run_portfolio = spy_rp
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            build(ohl, rates, paper_start=ps)
    finally:
        bt.run_portfolio = orig_rp
    if got_kw.get("limits") != (MONTH_LIMIT, HWM_LIMIT):
        f.append(f"build must pass limits={(MONTH_LIMIT, HWM_LIMIT)} to run_portfolio (got {got_kw.get('limits')})")
    # (f) a v1.1 orders log (no shares column) still loads
    tmp_mig = Path(tempfile.mkdtemp())
    (tmp_mig / "orders_seen.csv").write_text(",".join(SEEN_COLS_V11) + "\n2026-12-01,2026-12-01,XLF,1,0.9,3,1\n")
    try:
        if list(load_seen(tmp_mig)["shares"]) != ["na"]:
            f.append("a v1.1 orders log must load with shares 'na'")
    except DataFailure:
        f.append("a v1.1 orders log must load (migration)")
    # partial bar
    dp = drop_partial({"A": ohl["SPY"]}, cal[-1].date())["A"]
    if dp.index[-1] != cal[-2] or len(dp) != len(cal) - 1:
        f.append("drop_partial must remove only today's bar")
    # streak replay
    if not streak_reduced([{"r": -1.0}] * 3) or streak_reduced([{"r": -1.0}] * 3 + [{"r": 1.0}] * 2):
        f.append("streak_reduced: 3 losses on, 2 wins off")
    # 6. writer, append-only seen log, reconciliation, abort paths
    tmp = Path(tempfile.mkdtemp())
    try:
        seen0 = pd.DataFrame(columns=SEEN_COLS)
        write_outputs(r, seen0, "2026-12-02", tmp / "d", tmp / "l")
        s1 = load_seen(tmp / "d")
        n_orders = sum(1 for o in r["orders"] if o["status"] == "ORDER")
        if len(s1) != n_orders:
            f.append(f"seen log: {len(s1)} rows for {n_orders} orders")
        r2 = dict(r, orders=[dict(o, buy_stop=999.0) for o in r["orders"]])
        write_outputs(r2, s1, "2026-12-03", tmp / "d", tmp / "l")
        s2 = load_seen(tmp / "d")
        if len(s2) != len(s1) or (len(s2) and float(s2["buy_stop"].iloc[0]) == 999.0):
            f.append("seen log must keep the FIRST sighting of an order")
        # M2: a corrupted log stops the run; the writer never drops an earlier row
        (tmp / "bad").mkdir()
        (tmp / "bad" / "orders_seen.csv").write_text(",".join(SEEN_COLS) + "\n2026-12-01,2026-12-01,XLF,1,0.9,3,1\n<<<<<<< HEAD\n\"x,\n")
        try:
            load_seen(tmp / "bad")
            f.append("M2: a corrupted orders_seen.csv must raise")
        except DataFailure:
            pass
        fake_old = pd.DataFrame([{"first_seen": "2026-01-01", "signal_date": "2026-01-01", "ticker": "QQQ", "buy_stop": "1",
                                  "stop": "0.5", "conf": "3", "risk_pct": "1"}])
        if _keeps_all(fake_old, update_seen(pd.DataFrame(columns=SEEN_COLS), [], "x"), ["signal_date", "ticker"]):
            f.append("M2: _keeps_all must catch a dropped row")
        # M3: fills frozen on first booking; a later restatement is reported, not absorbed
        if r["open"] or r["closed"]:
            fl = update_fills(pd.DataFrame(columns=FILL_COLS), r)
            x0 = (r["open"] + r["closed"])[0]
            fl.loc[(fl.event == "entry") & (fl.ticker == x0["ticker"]) & (fl.entry_date == x0["entry_date"]), "price"] = str(x0["entry"] * 1.03)
            with contextlib.redirect_stdout(io.StringIO()):
                rf = build(ohl, rates, paper_start=ps, fills=fl)
            if not any(x0["ticker"] in z for z in rf["restated"]):
                f.append("M3: a booked entry that later changes by 3% must be reported as restated")
            if update_fills(fl, r).loc[lambda z: (z.event == "entry") & (z.ticker == x0["ticker"]) & (z.entry_date == x0["entry_date"]), "price"].iloc[0] != fl.loc[(fl.event == "entry") & (fl.ticker == x0["ticker"]) & (fl.entry_date == x0["entry_date"]), "price"].iloc[0]:
                f.append("M3: the fills log must keep the first booking")
        # reverse reconciliation: an order seen the night before that the book never placed is reported
        ghost = pd.DataFrame([{"first_seen": r["asof"], "signal_date": prev_session(r), "ticker": "XLU",
                               "buy_stop": "1", "stop": "0.5", "conf": "3", "risk_pct": "1", "shares": "na"}])
        with contextlib.redirect_stdout(io.StringIO()):
            rg = build(ohl, rates, paper_start=ps, seen=ghost)
        if not any("XLU" in z for z in rg["unplaced_orders"]):
            f.append("reconciliation: an order the book never placed must be reported")
        plc = [x for x in r["placed"] if x[0] < r["asof"] and x[3] > 0]
        if plc:
            d0, tk0, _k0, sh0 = plc[-1]
            wrong = pd.DataFrame([{"first_seen": d0, "signal_date": d0, "ticker": tk0, "buy_stop": "1", "stop": "0.5",
                                   "conf": "3", "risk_pct": "1", "shares": str(sh0 + 1)}])
            with contextlib.redirect_stdout(io.StringIO()):
                rw = build(ohl, rates, paper_start=ps, seen=wrong)
            if not any(tk0 in z and "ordered" in z for z in rw["unplaced_orders"]):
                f.append("reconciliation: a share count different from the printed order must be reported")
        else:
            f.append("fixture: need a placed order to test share reconciliation")
        js = json.loads((tmp / "d" / "summary.json").read_text())
        if "equity" not in js or not (tmp / "l" / "latest.md").exists():
            f.append("writer: outputs incomplete")
        if r["closed"] or r["open"]:
            fake = pd.DataFrame([{"first_seen": "2000-01-01", "signal_date": "1999-01-01", "ticker": "ZZZ",
                                  "buy_stop": 1, "stop": 0.5, "conf": 3, "risk_pct": 1, "shares": "na"}])
            with contextlib.redirect_stdout(io.StringIO()):
                rr = build(ohl, rates, paper_start=ps, seen=fake)
            if len(rr["unseen_trades"]) != len(rr["closed"]) + len(rr["open"]):
                f.append("reconciliation: trades with no prior order sighting must be listed")
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc1 = main(fetch=lambda tks, start=None: {})
                stale = dict(ohl, XLK=ohl["XLK"].iloc[:-1])
                full_u = {t: ohl.get(t, ohl["XLK"]) for t in etfs}
                full_u["XLK"] = stale["XLK"]
                rc2 = main(fetch=lambda tks, start=None: {t: full_u[t] for t in tks if t in full_u}, expect_session=None)
                full_ok = {t: ohl.get(t, ohl["XLK"]) for t in etfs}
                full_ok["^IRX"] = irx
                rc3 = main(fetch=lambda tks, start=None: {t: full_ok[t] for t in tks if t in full_ok},
                           expect_session=(cal[-1] + pd.Timedelta(days=1)).date().isoformat())
                nov = {t: v.copy() for t, v in full_ok.items()}
                nov["XLK"].iloc[-1, nov["XLK"].columns.get_loc("Volume")] = 0
                rc4 = main(fetch=lambda tks, start=None: {t: nov[t] for t in tks if t in nov}, expect_session=None)
            if rc1 != 1 or rc2 != 1 or rc3 != 1 or rc4 != 1 or (tmp / "data" / "m0t_paper").exists():
                f.append(f"main: missing / stale / old data / no volume must stop with nothing written ({rc1}, {rc2}, {rc3}, {rc4})")
        finally:
            os.chdir(cwd)
    except Exception as e:
        import traceback
        f.append(f"writer/main crashed: {type(e).__name__}: {e} {traceback.format_exc()[-300:]}")
    return {"ok": not f, "failures": f, "version": VERSION, "fixture": {"closed": len(r["closed"]), "open": len(r["open"]),
            "orders": len(r["orders"]), "signal_hits": hits, "exit_checks": checked}}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        res_ = selftest()
        print(json.dumps(res_, indent=2))
        sys.exit(0 if res_["ok"] else 1)
    sys.exit(main())
