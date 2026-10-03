"""
model_book.py  (v1 — October 2026)
──────────────────────────────────
The MODEL PORTFOLIO: what you SHOULD hold, tracked as if it were real, so
the framework can be battle-tested before any real money follows it.

WHY
───
The old portfolio section read a position ledger. Nobody has real positions
yet, so the ledger aged and every stop / drift / "authorized today" line
described positions that do not exist. The model book replaces that with
the framework's own answer, every session:

  should_hold   = the current regime's targets, after the entry gate
                  (blocked adds parked in SGOV), after the circuit breaker
  NAV           = the value of holding yesterday's should_hold through
                  today's closes (daily rebalanced to target — a model,
                  not a broker statement; no costs, no taxes)
  drawdown      = NAV vs its running peak

PORTFOLIO-LEVEL CIRCUIT BREAKER
  The regime engine reacts to credit and rates; in a fast crash those can
  lag equities by days or weeks (March 2020: HY crossed 5% only after the
  S&P was already down ~15-20%). The breaker reacts to the BOOK itself:

    WARN     drawdown <= -5%          flagged, no change
    ON       drawdown <= -8% on a close
             -> every risk sleeve is HALVED and the freed weight parked
                in SGOV. Exempt: cash (SGOV, USFR), trend (KMLM), and TLT
                when the regime is liquidity_crisis (the crash hedge).
                Weekday-authorized, like a stop.
    RELEASE  drawdown back above -5% AND SPY closes above its 50-day,
             on 2 consecutive closes -> breaker OFF; re-risking happens
             through the normal entry gate, never all at once.

  Drawdown is measured on the book as actually held (breaker included),
  so a breaker that did its job lets drawdown recover naturally.

PERSISTENCE
  data/model_book.csv, one row per session (idempotent per session). On the
  first run it is RECONSTRUCTED from logs/daily_log.csv (the regime each
  day) and the price history the brief already fetched — gated with only
  the prices available on each day, breaker simulated — so the drawdown has
  a real peak to measure against from day one. Reconstructed rows are
  labelled as such.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

BOOK_FILE = Path("data/model_book.csv")
START_NAV = 100.0
WARN_DD = -5.0
TRIGGER_DD = -8.0
RELEASE_DD = -5.0
RELEASE_CLOSES = 2
BREAKER_SCALE = 0.5
RISK_EXEMPT = {"SGOV", "USFR", "BIL", "SHV", "KMLM"}
PARK = "SGOV"
COLS = ["date", "regime", "nav", "peak", "drawdown_pct", "breaker", "release_count",
        "warn", "source", "weights"]


# ── pure pieces ─────────────────────────────────────────────────────────────

def apply_breaker(weights: dict, regime_key: Optional[str]) -> dict:
    """Halve every risk sleeve, park the freed weight in SGOV."""
    out, freed = {}, 0.0
    for t, w in weights.items():
        exempt = t in RISK_EXEMPT or (t == "TLT" and regime_key == "liquidity_crisis")
        nw = w if exempt else round(w * BREAKER_SCALE, 2)
        freed += w - nw
        out[t] = nw
    out[PARK] = round(out.get(PARK, 0.0) + freed, 2)
    return out


def next_breaker(state: str, release_count: int, dd: float, spy_above_50: Optional[bool]) -> tuple:
    """(state, release_count) after today's close."""
    if state != "ON":
        return ("ON", 0) if dd <= TRIGGER_DD else ("OFF", 0)
    ok = dd > RELEASE_DD and bool(spy_above_50)
    rc = release_count + 1 if ok else 0
    return ("OFF", 0) if rc >= RELEASE_CLOSES else ("ON", rc)


def _close(prices: dict, t: str) -> pd.Series:
    df = prices.get(t)
    if df is None or getattr(df, "empty", True):
        return pd.Series(dtype=float)
    s = df["Close"] if "Close" in getattr(df, "columns", []) else df
    s = pd.Series(s).astype(float).dropna()
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    s.index = pd.to_datetime(s.index).normalize()
    return s[~s.index.duplicated(keep="last")]


def _day_return(closes: dict, t: str, d0, d1) -> Optional[float]:
    s = closes.get(t)
    if s is None or s.empty or d0 not in s.index or d1 not in s.index:
        return None
    a, b = float(s.loc[d0]), float(s.loc[d1])
    return b / a - 1 if a else None


def _spy_above_50(closes: dict, d) -> Optional[bool]:
    s = closes.get("SPY")
    if s is None or s.empty:
        return None
    s = s[s.index <= d]
    if len(s) < 50:
        return None
    return bool(s.iloc[-1] > s.tail(50).mean())


# ── the engine ──────────────────────────────────────────────────────────────

def advance(book: pd.DataFrame, session: date, regime_by_date: dict, prices: dict,
            weights_fn: Callable, today_regime: str, today_weights: Optional[dict] = None) -> pd.DataFrame:
    """Roll the book forward to `session`.

    regime_by_date: {date: regime_key} (any calendar dates; the latest on or
    before each trading day applies). weights_fn(regime_key, asof_date) ->
    gated should-hold weights using only data up to asof_date.
    today_weights overrides weights_fn for `session` (the live, fully-signalled
    targets)."""
    closes = {t: _close(prices, t) for t in prices}
    spy = closes.get("SPY")
    cal = sorted(set(spy.index)) if spy is not None and not spy.empty else []
    sess = pd.Timestamp(session).normalize()
    book = book.copy() if book is not None and not book.empty else pd.DataFrame(columns=COLS)
    if not book.empty:
        book["date"] = pd.to_datetime(book["date"]).dt.normalize()
        book = book[book["date"] < sess].sort_values("date")
    rkeys = sorted((pd.Timestamp(k).normalize(), v) for k, v in regime_by_date.items())

    def regime_on(d):
        r = None
        for k, v in rkeys:
            if k <= d:
                r = v
            else:
                break
        return r

    if book.empty:
        first = rkeys[0][0] if rkeys else sess
        days = [d for d in cal if first <= d <= sess] or [sess]
        source = "reconstructed"
    else:
        last = book["date"].iloc[-1]
        days = [d for d in cal if last < d <= sess] or ([sess] if sess > last else [])
        source = "live"
    rows = book.to_dict("records")
    for d in days:
        is_today = d == sess
        reg = today_regime if is_today else (regime_on(d) or today_regime)
        if rows:
            prev = rows[-1]
            w_prev = json.loads(prev["weights"]) if isinstance(prev["weights"], str) else prev["weights"]
            r = 0.0
            for t, w in w_prev.items():
                dr = _day_return(closes, t, pd.Timestamp(prev["date"]), d)
                r += (w / 100.0) * (dr or 0.0)
            nav = float(prev["nav"]) * (1 + r)
            peak = max(float(prev["peak"]), nav)
            state, rc = next_breaker(prev["breaker"], int(prev["release_count"]),
                                     (nav / peak - 1) * 100, _spy_above_50(closes, d))
        else:
            nav, peak, state, rc = START_NAV, START_NAV, "OFF", 0
        dd = (nav / peak - 1) * 100
        base_w = today_weights if (is_today and today_weights) else weights_fn(reg, d)
        w = apply_breaker(base_w, reg) if state == "ON" else dict(base_w)
        rows.append({"date": d, "regime": reg, "nav": round(nav, 4), "peak": round(peak, 4),
                     "drawdown_pct": round(dd, 2), "breaker": state, "release_count": rc,
                     "warn": dd <= WARN_DD, "source": "live" if is_today else source,
                     "weights": json.dumps({k: round(float(v), 2) for k, v in w.items()})})
    out = pd.DataFrame(rows, columns=COLS)
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out


def load(path: Path = BOOK_FILE) -> pd.DataFrame:
    try:
        return pd.read_csv(path) if Path(path).exists() else pd.DataFrame(columns=COLS)
    except Exception:
        return pd.DataFrame(columns=COLS)


def save(book: pd.DataFrame, path: Path = BOOK_FILE) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    book.to_csv(path, index=False)


def summary(book: pd.DataFrame) -> dict:
    """Today's model state + what changed vs the prior session."""
    if book is None or book.empty:
        return {"available": False}
    b = book.sort_values("date")
    t = b.iloc[-1]
    w = json.loads(t["weights"])
    prev = json.loads(b.iloc[-2]["weights"]) if len(b) > 1 else {}
    changes = []
    for k in sorted(set(w) | set(prev)):
        d = round(float(w.get(k, 0)) - float(prev.get(k, 0)), 1)
        if abs(d) >= 0.1 and prev:
            changes.append({"ticker": k, "from": float(prev.get(k, 0)), "to": float(w.get(k, 0)), "change": d})
    nav = b["nav"].astype(float)
    def ret(n):
        return round((nav.iloc[-1] / nav.iloc[-1 - n] - 1) * 100, 2) if len(nav) > n else None
    prev_state = b.iloc[-2]["breaker"] if len(b) > 1 else "OFF"
    return {"available": True, "date": t["date"], "regime": t["regime"], "weights": w,
            "nav": float(t["nav"]), "peak": float(t["peak"]), "drawdown_pct": float(t["drawdown_pct"]),
            "breaker": t["breaker"], "breaker_changed": t["breaker"] != prev_state,
            "release_count": int(t["release_count"]), "warn": bool(t["warn"]),
            "ret_5d": ret(5), "ret_20d": ret(20), "sessions": len(b),
            "since": b.iloc[0]["date"], "reconstructed_sessions": int((b["source"] == "reconstructed").sum()),
            "changes": changes}


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    import numpy as np
    f = []
    w = {"VGT": 20, "SGOV": 10, "KMLM": 8, "TLT": 10, "GLD": 52}
    b = apply_breaker(w, "credit_stress")
    if b["VGT"] != 10 or b["KMLM"] != 8 or b["TLT"] != 5 or abs(sum(b.values()) - 100) > 0.01:
        f.append(f"breaker halving wrong: {b}")
    if apply_breaker(w, "liquidity_crisis")["TLT"] != 10:
        f.append("TLT is exempt from the breaker in liquidity_crisis")
    if next_breaker("OFF", 0, -8.1, False) != ("ON", 0) or next_breaker("OFF", 0, -7.9, False) != ("OFF", 0):
        f.append("trigger at -8%")
    if next_breaker("ON", 0, -4.0, True) != ("ON", 1) or next_breaker("ON", 1, -4.0, True) != ("OFF", 0):
        f.append("release needs 2 qualifying closes")
    if next_breaker("ON", 1, -4.0, False) != ("ON", 0) or next_breaker("ON", 1, -6.0, True) != ("ON", 0):
        f.append("release counter resets unless BOTH conditions hold")

    # crash path: risk asset falls 25% over 30 sessions, then recovers
    idx = pd.bdate_range("2026-01-01", periods=140)
    risk = np.r_[np.full(60, 100.0), np.linspace(100, 75, 30), np.linspace(75, 110, 50)]
    prices = {"SPY": pd.DataFrame({"Close": risk}, index=idx),
              "VGT": pd.DataFrame({"Close": risk}, index=idx),
              "SGOV": pd.DataFrame({"Close": np.linspace(100, 101, 140)}, index=idx),
              "KMLM": pd.DataFrame({"Close": np.full(140, 30.0)}, index=idx)}
    wf = lambda reg, d: {"VGT": 80.0, "SGOV": 10.0, "KMLM": 10.0}
    book = advance(pd.DataFrame(), idx[-1].date(), {idx[0]: "restrictive_tightening"}, prices, wf,
                   "restrictive_tightening")
    if len(book) != 140 or (book["source"] == "reconstructed").sum() != 139:
        f.append(f"reconstruction length/source wrong: {len(book)}")
    on = book[book["breaker"] == "ON"]
    if on.empty:
        f.append("an 80%-risk book in a -25% crash must trip the breaker")
    else:
        first = on.index[0]
        if book.loc[first, "drawdown_pct"] > TRIGGER_DD:
            f.append("breaker turned on before -8%")
        wts = json.loads(book.loc[first, "weights"])
        if wts["VGT"] != 40 or wts["SGOV"] != 50:
            f.append(f"breaker weights wrong on trigger day: {wts}")
        unbroken = 80 * 0.25
        if book["drawdown_pct"].min() <= -unbroken * 0.98:
            f.append(f"breaker did not reduce the drawdown: {book['drawdown_pct'].min()}")
    if book["breaker"].iloc[-1] != "OFF":
        f.append("breaker must release after the recovery")
    # idempotent per session: re-running the same session changes nothing
    again = advance(book, idx[-1].date(), {idx[0]: "restrictive_tightening"}, prices, wf, "restrictive_tightening")
    if len(again) != len(book) or abs(float(again["nav"].iloc[-1]) - float(book["nav"].iloc[-1])) > 1e-9:
        f.append("re-running a session must be idempotent")
    # live day uses today's weights override
    nxt = idx[-1] + pd.offsets.BDay(1)
    p2 = {k: pd.concat([v, pd.DataFrame({"Close": [v["Close"].iloc[-1]]}, index=[nxt])]) for k, v in prices.items()}
    live = advance(book, nxt.date(), {}, p2, wf, "credit_stress", today_weights={"SGOV": 60.0, "VGT": 40.0})
    if live["source"].iloc[-1] != "live" or json.loads(live["weights"].iloc[-1]).get("SGOV") != 60.0:
        f.append("today's row must be live and use today's weights")
    s = summary(live)
    if not s["available"] or not s["changes"] or s["regime"] != "credit_stress":
        f.append(f"summary wrong: {s}")
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    print(json.dumps(selftest(), indent=2))
