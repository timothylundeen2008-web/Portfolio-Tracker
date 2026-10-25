"""
signal_outcomes.py  (v2 — October 2026: wired into the daily brief)
──────────────────────────────────────────────────────────────────────────────
DOES THIS FRAMEWORK ACTUALLY WORK?

Every other module analyzes the present. This one measures whether past
analysis was right. Without base rates you cannot tell a framework that WORKS
and is having a normal losing stretch from one that DOESN'T work but feels
rigorous because the process is elaborate.

v1 existed but nothing called it, so no history accumulated (fix_status N4).
v2 is called by daily_brief.py every session and writes
data/signal_outcomes.csv, which the brief workflow commits.

WHAT IS LOGGED (one row per signal, at the session it fires)
  From the daily log (logs/daily_log.csv), which was written at the time,
  so replaying it is NOT hindsight:
    regime_weekly       the model portfolio's should-hold weights each Friday,
                        scored against the BASE allocation  -> "does the
                        regime overlay add value over holding base?"
    regime_transition   a regime change CONFIRMED on two closes, scored as the
                        new should-hold vs the old one
    gold_gate_pass/fail the checklist gold gate flipping state (GLD)
    kmlm_increase/reduce the KMLM stance flipping into INCREASE / REDUCE
    hy_crisis_override  HY OAS > 5% and +0.5pp in two weeks (HYG, short)
  From the swing desk (logs/swing/cards_history.csv, written at the time):
    confluence_3of3/2of3 an entry-permitted card's FIRST appearance
                        (same ticker+setup suppressed for 10 sessions)
  From Money Flow (data/rotation_summary.json, today only — not stored daily
  upstream, so these start accumulating now):
    stealth_flag        a sector newly labelled Stealth / Strong Stealth
    flow_divergence     Tier A accumulation (long) / distribution (short),
                        only when the Flow Map's measurability test passes

  Rows from a day whose core regime inputs were missing (a data failure) are
  skipped, so an outage can never become a "signal".

HOW IT IS SCORED
  Ticker signals: forward return of the subject minus SPY over 1/4/12 weeks
  (5/21/63 sessions), signed by direction.
  Portfolio signals (subject "PORT"): forward return of the signal's weights
  minus the forward return of its benchmark weights, daily rebalanced.

STATISTICAL HONESTY (enforced in the output)
  - Under MIN_SAMPLE observations no hit rate is reported.
  - Benchmark-relative, never absolute.
  - Weekly portfolio snapshots overlap at 4w/12w horizons; 30 overlapping
    observations are worth far fewer independent ones. Flagged in the output.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd

STORE = os.environ.get("SIGNAL_LOG", "data/signal_outcomes.csv")
HORIZONS = {"1w": 5, "4w": 21, "12w": 63}     # trading sessions
MIN_SAMPLE = 20                                # below this, no rate is reported
DEDUPE_SESSIONS = 10                           # same ticker signal suppressed this long
COLUMNS = ["signal_id", "date", "signal_type", "subject", "direction",
           "price_at_signal", "benchmark_at_signal", "context", "notes", "source"]

SIGNAL_TYPES = [
    "regime_weekly", "regime_transition",
    "gold_gate_pass", "gold_gate_fail",
    "kmlm_increase", "kmlm_reduce",
    "hy_crisis_override",
    "confluence_3of3", "confluence_2of3",
    "stealth_flag", "flow_divergence",
    "regime_call",                       # v1 name, kept so old rows still score
]


# ── Storage ───────────────────────────────────────────────────────────────────

def _load(path: str = None) -> pd.DataFrame:
    p = path or STORE
    if not os.path.exists(p):
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(p)
    except Exception:
        return pd.DataFrame(columns=COLUMNS)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[COLUMNS]


def _save(df: pd.DataFrame, path: str = None) -> None:
    p = path or STORE
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        df.sort_values(["date", "signal_type", "subject"]).to_csv(p, index=False)
    except Exception as e:
        print(f"[signal_outcomes] write failed: {e}")


def _sid(d: str, signal_type: str, subject: str) -> str:
    return f"{d}_{signal_type}_{subject}".replace(" ", "")


def _row(d: str, signal_type: str, subject: str, direction: str, context: str = "",
         notes: Optional[dict] = None, price=None, source: str = "") -> dict:
    return {"signal_id": _sid(d, signal_type, subject), "date": d, "signal_type": signal_type,
            "subject": subject, "direction": direction, "price_at_signal": price,
            "benchmark_at_signal": None, "context": context,
            "notes": json.dumps(notes) if isinstance(notes, dict) else (notes or ""),
            "source": source}


def record(signal_type: str, subject: str, direction: str = "long",
           price: float | None = None, benchmark_price: float | None = None,
           context: str = "", notes: str = "", when: str | None = None) -> str:
    """Log one signal (v1 API, kept). Idempotent per (date, type, subject)."""
    d = when or date.today().isoformat()
    r = _row(d, signal_type, subject, direction, context, notes, price, "manual")
    r["benchmark_at_signal"] = benchmark_price
    record_rows([r])
    return r["signal_id"]


def record_rows(rows: list[dict], path: str = None) -> int:
    """Append rows, replacing any with the same signal_id. Returns rows added."""
    if not rows:
        return 0
    df = _load(path)
    new = pd.DataFrame(rows, columns=COLUMNS)
    added = int((~new["signal_id"].isin(df["signal_id"])).sum())
    df = pd.concat([df[~df["signal_id"].isin(new["signal_id"])], new], ignore_index=True)
    _save(df, path)
    return added


# ── Deriving signals (pure: no I/O) ───────────────────────────────────────────

def _valid_log(log: pd.DataFrame, upto: str) -> pd.DataFrame:
    """Daily-log rows usable as signal evidence: on or before `upto`, one per
    date, and NOT a data-failure day (core inputs missing)."""
    if log is None or log.empty or "regime" not in log or "et_date" not in log:
        return pd.DataFrame()
    lg = log.copy()
    lg["et_date"] = lg["et_date"].astype(str)
    lg = lg[lg["et_date"] <= upto].sort_values("et_date").drop_duplicates("et_date", keep="last")
    core = [c for c in ("short_real_rate", "hy_oas") if c in lg.columns]
    if core:
        lg = lg[lg[core].notna().all(axis=1)]
    if "regime_label" in lg.columns:
        lg = lg[~lg["regime_label"].astype(str).str.contains("DATA FAILURE", na=False)]
    return lg.reset_index(drop=True)


def _weights_on(book: Optional[pd.DataFrame], d: str) -> Optional[dict]:
    if book is None or getattr(book, "empty", True):
        return None
    b = book.assign(_d=pd.to_datetime(book["date"]).dt.strftime("%Y-%m-%d"))
    m = b[b["_d"] == d]
    if m.empty:
        return None
    w = m["weights"].iloc[-1]
    return json.loads(w) if isinstance(w, str) else dict(w)


def _base_weights() -> dict:
    try:
        import regime_classifier as rc
        return dict(rc.BASE_WEIGHTS)
    except Exception:
        return {}


def from_daily_log(log: pd.DataFrame, upto: str, book: Optional[pd.DataFrame] = None) -> list[dict]:
    """Every log-derived signal on or before `upto`. Idempotent by signal_id,
    so the same call serves both the one-time backfill and the daily step."""
    lg = _valid_log(log, upto)
    if lg.empty:
        return []
    rows, base = [], _base_weights()
    regs = lg["regime"].astype(str).tolist()
    dates = lg["et_date"].tolist()
    for i, d in enumerate(dates):
        # regime_weekly — Fridays, scored vs BASE
        if datetime.strptime(d, "%Y-%m-%d").weekday() == 4:
            w = _weights_on(book, d)
            if w:
                rows.append(_row(d, "regime_weekly", "PORT", "long", f"regime={regs[i]}",
                                 {"weights": w, "bench_weights": base, "bench": "BASE"}, source="daily_log"))
        # regime_transition — confirmed on the 2nd consecutive close
        if i >= 2 and regs[i] == regs[i - 1] and regs[i - 1] != regs[i - 2]:
            w_new, w_old = _weights_on(book, d), _weights_on(book, dates[i - 2])
            if w_new and w_old:
                rows.append(_row(d, "regime_transition", "PORT", "long",
                                 f"{regs[i - 2]} -> {regs[i]} (confirmed)",
                                 {"weights": w_new, "bench_weights": w_old, "bench": regs[i - 2]},
                                 source="daily_log"))
        if i == 0:
            continue
        prev, cur = lg.iloc[i - 1], lg.iloc[i]
        # gold gate flips
        if "gold_gate" in lg.columns:
            g0, g1 = str(prev.get("gold_gate", "")), str(cur.get("gold_gate", ""))
            p0, p1 = g0.upper().startswith("PASS"), g1.upper().startswith("PASS")
            f0, f1 = g0.upper().startswith("FAIL"), g1.upper().startswith("FAIL")
            if p1 and f0:
                rows.append(_row(d, "gold_gate_pass", "GLD", "long", "gate FAIL -> PASS", source="daily_log"))
            elif f1 and p0:
                rows.append(_row(d, "gold_gate_fail", "GLD", "short", "gate PASS -> FAIL", source="daily_log"))
        # KMLM stance flips
        if "kmlm_stance" in lg.columns:
            k0, k1 = str(prev.get("kmlm_stance", "")).upper(), str(cur.get("kmlm_stance", "")).upper()
            if "INCREASE" in k1 and "INCREASE" not in k0:
                rows.append(_row(d, "kmlm_increase", "KMLM", "long", f"{k0 or '?'} -> {k1}", source="daily_log"))
            elif "REDUCE" in k1 and "REDUCE" not in k0:
                rows.append(_row(d, "kmlm_reduce", "KMLM", "short", f"{k0 or '?'} -> {k1}", source="daily_log"))
        # HY crisis override (first day it fires)
        try:
            hy1, m1 = float(cur.get("hy_oas")), float(cur.get("hy_oas_mom_2w"))
            hy0, m0 = float(prev.get("hy_oas")), float(prev.get("hy_oas_mom_2w"))
            if hy1 > 5.0 and m1 > 0.5 and not (hy0 > 5.0 and m0 > 0.5):
                rows.append(_row(d, "hy_crisis_override", "HYG", "short", f"HY OAS {hy1:.2f}%",
                                 source="daily_log"))
        except (TypeError, ValueError):
            pass
    return rows


def _recent(existing: pd.DataFrame, rows: list[dict], signal_type: str, subject: str,
            d: str, sessions: int = DEDUPE_SESSIONS) -> bool:
    """True if the same (type, subject) fired within `sessions` business days
    before `d`, in the store or earlier in this batch."""
    lo = (pd.Timestamp(d) - pd.offsets.BDay(sessions)).strftime("%Y-%m-%d")
    pool = [(r["date"], r["signal_type"], r["subject"]) for r in rows]
    if existing is not None and not existing.empty:
        pool += list(zip(existing["date"].astype(str), existing["signal_type"].astype(str),
                         existing["subject"].astype(str)))
    return any(lo <= dd < d and t == signal_type and s == subject for dd, t, s in pool)


def from_swing_cards(cards: pd.DataFrame, upto: str, existing: pd.DataFrame = None) -> list[dict]:
    """Entry-permitted swing cards, first appearance only."""
    if cards is None or cards.empty:
        return []
    c = cards.copy()
    c["date"] = c["date"].astype(str)
    c = c[(c["date"] <= upto) & (c["entry_permitted"].astype(str).str.lower() == "true")].sort_values("date")
    rows = []
    for r in c.itertuples():
        st = {"3-of-3": "confluence_3of3", "2-of-3": "confluence_2of3"}.get(str(r.confluence))
        if not st:
            continue
        subj = str(r.ticker)
        if _recent(existing, rows, st, subj, r.date):
            continue
        rows.append(_row(r.date, st, subj, "short" if str(r.side) == "short" else "long",
                         f"{r.setup} · regime={r.regime}", price=getattr(r, "close", None),
                         source="swing_cards"))
    return rows


def from_rotation(rot: dict, d: str, existing: pd.DataFrame = None) -> list[dict]:
    """Money Flow signals for today (the upstream summary is not kept daily)."""
    rows = []
    for s in (rot or {}).get("sectors", []) or []:
        lab = str(s.get("stealth_label") or "").lower()
        if lab in ("stealth", "strong stealth") and not _recent(existing, rows, "stealth_flag", s["ticker"], d):
            rows.append(_row(d, "stealth_flag", s["ticker"], "long",
                             f"{s.get('stealth_label')} · {s.get('quadrant')} · accum {s.get('accumulation_score')}",
                             source="rotation"))
    for x in (rot or {}).get("flow_divergences", []) or []:
        v = str(x.get("verdict") or "")
        # Only divergences that pass the Flow Map's measurability test (Money
        # Flow publish v2.1 tags them). No tag = an older publish = not scored.
        if not x.get("divergence") or "UNRELIABLE" in v.upper() or x.get("measurable") is not True:
            continue
        side = "long" if v.upper().startswith("ACCUMULATION") else "short" if v.upper().startswith("DISTRIBUTION") else None
        if side and not _recent(existing, rows, "flow_divergence", x["ticker"], d):
            rows.append(_row(d, "flow_divergence", x["ticker"], side,
                             f"{v} · flow {x.get('net_flow_pct_aum')}% AUM", source="rotation"))
    return rows


# ── Evaluation ────────────────────────────────────────────────────────────────

def _norm(s) -> pd.Series:
    s = pd.Series(s).astype(float).dropna()
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    s.index = pd.to_datetime(s.index).normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def _fetch_series(tickers: list[str], start: str) -> dict:
    out = {}
    if not tickers:
        return out
    try:
        import yfinance as yf
        raw = yf.download(sorted(set(tickers)), start=start, interval="1d",
                          auto_adjust=True, progress=False, threads=True, timeout=40)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].rename(
            columns={"Close": tickers[0]})
        for t in close.columns:
            out[t] = _norm(close[t])
    except Exception as e:
        print(f"[signal_outcomes] fetch failed: {e}")
    return out


def _fwd(s: pd.Series, d: pd.Timestamp, n: int) -> Optional[float]:
    i = s.index.searchsorted(d)
    if i >= len(s) or i + n >= len(s):
        return None
    return float(s.iloc[i + n] / s.iloc[i] - 1) * 100


def _port_fwd(closes: dict, weights: dict, d: pd.Timestamp, n: int) -> Optional[float]:
    """Daily-rebalanced forward return of `weights` over n sessions from d.
    None if under 95% of the weight is priced over the window."""
    cal = closes.get("SPY")
    if cal is None or cal.empty:
        return None
    i = cal.index.searchsorted(d)
    if i >= len(cal) or i + n >= len(cal):
        return None
    days = cal.index[i:i + n + 1]
    tot = sum(float(w) for w in weights.values() if float(w) > 0)
    nav = 1.0
    for a, b in zip(days[:-1], days[1:]):
        r, have = 0.0, 0.0
        for t, w in weights.items():
            w = float(w)
            s = closes.get(t)
            if w <= 0 or s is None or a not in s.index or b not in s.index:
                continue
            r += w / 100.0 * (float(s.loc[b]) / float(s.loc[a]) - 1)
            have += w
        if tot and have / tot < 0.95:
            return None
        nav *= 1 + r
    return (nav - 1) * 100


def evaluate(benchmark: str = "SPY", closes: Optional[dict] = None,
             path: str = None, fetch: bool = True) -> pd.DataFrame:
    """Forward absolute and benchmark-relative returns for every logged signal.
    `closes` ({ticker: Series}) is used first; missing tickers are fetched
    when `fetch` is True."""
    df = _load(path)
    if df.empty:
        return pd.DataFrame()
    cl = {t: _norm(s) for t, s in (closes or {}).items() if s is not None and len(s)}
    need = set()
    for r in df.itertuples():
        if r.subject == "PORT":
            try:
                n = json.loads(r.notes or "{}")
                need |= set(n.get("weights", {})) | set(n.get("bench_weights", {}))
            except Exception:
                pass
        elif isinstance(r.subject, str):
            need.add(r.subject)
    need |= {benchmark, "SPY"}
    missing = sorted(t for t in need if t not in cl)
    if missing and fetch:
        cl.update(_fetch_series(missing, str(min(df["date"]))))
    b = cl.get(benchmark, pd.Series(dtype=float))
    out = []
    for r in df.to_dict("records"):
        d = pd.Timestamp(r["date"])
        for h, n in HORIZONS.items():
            ret = rel = None
            if r["subject"] == "PORT":
                try:
                    nt = json.loads(r["notes"] or "{}")
                    ret = _port_fwd(cl, nt.get("weights", {}), d, n)
                    bench = _port_fwd(cl, nt.get("bench_weights", {}), d, n)
                    rel = None if ret is None or bench is None else ret - bench
                except Exception:
                    pass
            else:
                s = cl.get(r["subject"])
                if s is not None and len(s):
                    ret = _fwd(s, d, n)
                    br = _fwd(b, d, n) if len(b) else None
                    rel = None if ret is None or br is None else ret - br
            r[f"ret_{h}"] = None if ret is None else round(ret, 2)
            r[f"rel_{h}"] = None if rel is None else round(rel, 2)
        out.append(r)
    return pd.DataFrame(out)


def base_rates(benchmark: str = "SPY", horizon: str = "4w", closes: Optional[dict] = None,
               path: str = None, fetch: bool = True, ev: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Per-signal-type observations, hit rate (only at MIN_SAMPLE+), mean and
    median signed relative return, and a plain-language verdict."""
    ev = evaluate(benchmark, closes, path, fetch) if ev is None else ev
    col = f"rel_{horizon}"
    if ev.empty or col not in ev.columns:
        return pd.DataFrame()
    out = []
    for stype, g in ev.groupby("signal_type"):
        logged = len(g)
        g = g[pd.to_numeric(g[col], errors="coerce").notna()]
        n = len(g)
        rec = {"signal_type": stype, "logged": logged, "n": n, "hit_rate": None,
               "avg_rel": None, "med_rel": None}
        if n:
            sign = g["direction"].map({"long": 1, "short": -1}).fillna(1)
            adj = pd.to_numeric(g[col]) * sign
            hit = float((adj > 0).mean() * 100)
            rec.update(hit_rate=round(hit, 1) if n >= MIN_SAMPLE else None,
                       avg_rel=round(float(adj.mean()), 2), med_rel=round(float(adj.median()), 2))
            if n < MIN_SAMPLE:
                rec["verdict"] = f"INSUFFICIENT — {n}/{MIN_SAMPLE} scored, no rate reported"
            elif hit >= 60 and adj.mean() > 0.5:
                rec["verdict"] = "EDGE — keep and consider sizing up"
            elif hit <= 45 or adj.mean() < -0.5:
                rec["verdict"] = "NEGATIVE — candidate for removal from the checklist"
            else:
                rec["verdict"] = "NOISE — no demonstrated edge; keep logging or drop"
        else:
            rec["verdict"] = f"WAITING — {logged} logged, none past the {horizon} horizon yet"
        out.append(rec)
    return pd.DataFrame(out).sort_values(["n", "logged"], ascending=False)


def coverage(path: str = None) -> dict:
    """Honest status: how far from being able to say anything at all."""
    df = _load(path)
    if df.empty:
        return {"signals": 0, "ready": False, "by_type": {},
                "message": "No signals logged yet."}
    by_type = df.groupby("signal_type").size().to_dict()
    ready = [k for k, v in by_type.items() if v >= MIN_SAMPLE]
    oldest = str(min(df["date"]))
    weeks = (date.today() - datetime.strptime(oldest, "%Y-%m-%d").date()).days / 7
    return {"signals": len(df), "by_type": by_type, "types_ready": ready,
            "weeks_of_history": round(weeks, 1), "since": oldest, "ready": bool(ready),
            "message": (f"{len(ready)} signal type(s) have {MIN_SAMPLE}+ observations. " if ready else
                        f"No signal type has {MIN_SAMPLE}+ observations yet. ")
                       + "Overlapping horizons are correlated — treat early readings as directional."}


def scorecard(closes: Optional[dict] = None, path: str = None, fetch: bool = True) -> dict:
    """What the daily brief prints: coverage plus base rates at 1w and 4w."""
    cov = coverage(path)
    if not cov["signals"]:
        return {"coverage": cov, "rates": {}}
    ev = evaluate("SPY", closes, path, fetch)
    return {"coverage": cov,
            "rates": {h: base_rates(horizon=h, ev=ev).to_dict("records") for h in ("1w", "4w", "12w")}}


# ── Self-test (no network) ────────────────────────────────────────────────────

def selftest() -> dict:
    import tempfile
    f = []
    idx = pd.bdate_range("2026-08-03", periods=90)
    rng = np.random.default_rng(7)
    base = _base_weights() or {"SPY": 60, "SGOV": 40}
    closes = {t: pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(idx)))), index=idx)
              for t in set(base) | {"SPY", "GLD", "KMLM", "HYG", "XLK", "NVDA"}}
    dates = [d.strftime("%Y-%m-%d") for d in idx[:40]]
    regs = ["transition_ambiguous"] * 15 + ["restrictive_tightening"] * 25
    gold = ["FAIL"] * 20 + ["PASS — GLD above rising 200d"] * 20
    kml = ["HOLD KMLM"] * 10 + ["INCREASE KMLM"] * 30
    log = pd.DataFrame({"et_date": dates, "regime": regs, "gold_gate": gold, "kmlm_stance": kml,
                        "short_real_rate": 0.3, "hy_oas": 3.0, "hy_oas_mom_2w": 0.1})
    log.loc[25, ["short_real_rate", "hy_oas"]] = np.nan          # an outage day
    log.loc[25, "regime"] = "neutral"
    alt = dict(base)
    book = pd.DataFrame({"date": dates, "weights": [json.dumps(base if r == "transition_ambiguous" else alt)
                                                    for r in regs]})
    rows = from_daily_log(log, dates[-1], book)
    types = [r["signal_type"] for r in rows]
    if types.count("regime_transition") != 1:
        f.append(f"exactly one confirmed transition expected: {types}")
    if "gold_gate_pass" not in types or "kmlm_increase" not in types:
        f.append(f"gate and KMLM flips must be logged: {types}")
    if any(r["date"] == dates[25] for r in rows):
        f.append("an outage row must never produce a signal")
    if not [r for r in rows if r["signal_type"] == "regime_weekly"]:
        f.append("Friday portfolio snapshots must be logged")
    # outage row 'neutral' between two restrictive rows must not create transitions
    if [r for r in rows if r["signal_type"] == "regime_transition" and "neutral" in r["context"]]:
        f.append("a data-failure regime must not create a transition")
    cards = pd.DataFrame({"date": [dates[30], dates[31], dates[38]], "ticker": ["NVDA"] * 3,
                          "setup": ["M0 Rotation"] * 3, "side": ["long"] * 3, "confluence": ["3-of-3"] * 3,
                          "close": [1, 1, 1], "regime": ["x"] * 3, "entry_permitted": [True, True, True]})
    sc = from_swing_cards(cards, dates[-1])
    if len(sc) != 1:
        f.append(f"repeat cards within {DEDUPE_SESSIONS} sessions must be suppressed: {len(sc)}")
    rot = {"sectors": [{"ticker": "XLK", "stealth_label": "Stealth", "quadrant": "Leading", "accumulation_score": 40}],
           "flow_divergences": [{"ticker": "HYG", "verdict": "ACCUMULATION (price down, money in)", "divergence": True,
                                 "measurable": True},
                                {"ticker": "XLK", "verdict": "ACCUMULATION (price down, money in)", "divergence": True},
                                {"ticker": "TLT", "verdict": "UNRELIABLE — new source", "divergence": True}]}
    rr = from_rotation(rot, dates[-1])
    if sorted(r["signal_type"] for r in rr) != ["flow_divergence", "stealth_flag"]:
        f.append(f"rotation signals wrong: {[r['signal_type'] for r in rr]}")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "sig.csv")
        n1 = record_rows(rows + sc + rr, p)
        n2 = record_rows(rows + sc + rr, p)
        if n1 == 0 or n2 != 0:
            f.append(f"recording must be idempotent: first {n1}, second {n2}")
        ev = evaluate(closes=closes, path=p, fetch=False)
        if ev[ev["signal_type"] == "regime_weekly"]["rel_1w"].dropna().empty:
            f.append("portfolio signals must score against their benchmark weights")
        same = ev[(ev["signal_type"] == "regime_weekly")]["rel_1w"].dropna()
        if not same.empty and same.abs().max() > 1e-6:
            f.append("weights identical to base must score ~0 relative")
        br = base_rates(ev=ev, horizon="1w")
        if br.empty or br["hit_rate"].notna().any():
            f.append("no hit rate may be reported under MIN_SAMPLE")
        s = scorecard(closes, p, fetch=False)
        if not s["coverage"]["signals"] or "1w" not in s["rates"]:
            f.append("scorecard must carry coverage and rates")
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    print(json.dumps(selftest(), indent=2, default=str))
