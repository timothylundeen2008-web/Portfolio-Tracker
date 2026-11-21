"""
engine_shadow.py  (v1.0 — 2026-11-13)
─────────────────────────────────────
Forward (out-of-sample) shadow of the Offense / Balanced / Defense engines.

WHY
  The offense lab tested 10 candidates on 2000–2026. O9 came closest to the
  bar (−19.3% max DD, Sharpe 0.79, beat SPY over the full window, missed
  2005–15). Rules chosen after seeing history can fit the past; the only
  evidence that cannot is a record kept from the day the rules were frozen.
  risk_policy §3's "compelling" bar already requires that record.

WHAT
  From SHADOW_START (2026-12-01) it books, every trading day, a hypothetical
  NAV for:
    O9   fast out / slow back in (offense_lab v1.2 rules, frozen)
    O7   three-state trend (offense_lab v1.1 rules, frozen)
    SPY  buy and hold
    MODEL_BOOK  the live model book NAV (data/model_book.csv), re-based
  The engines use offense_lab's own state machines and accounting, so the
  shadow is the lab's rule by construction. BALANCED inside an engine is the
  live regime's target_weights(gate=False) on each date (from model_book.csv),
  exactly as tested. Trades: one session late, 5bp per unit of turnover.

  Before SHADOW_START it only reports what each engine says today.
  The whole series is recomputed from prices on every run (no stored state to
  corrupt); nav.csv is the result, never an input.

GUARDS
  * Data failure is not a signal: if a signal input is missing, or the price
    feed does not reach the session that should be in it (N64), nothing is
    booked and the status says why.
  * No real money: this is a record, not an instruction.

Run:  python engine_shadow.py            (Actions: after the Consolidated Daily Brief)
      python engine_shadow.py --selftest
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import hedge_lab as hl
import offense_lab as ol

VERSION = "v1.1"     # v1.0.1 (N66): drop bars after the expected session; v1.1: O11 added
SHADOW_START = "2026-12-01"
ENGINES = ("O11", "O9", "O7")     # O11 = best of the lab (v1.4); O9 and O7 for comparison
FETCH_DAYS = 700                      # >= 200-day average + warm-up + slack
OUT_DIR = Path("data/engine_shadow")
LOG_DIR = Path("logs/engine_shadow")
BOOK_FILE = Path("data/model_book.csv")
NEEDED = ("SPY", "QQQ", *ol.SECTORS9)
STATE_WORDS = {"OFF": "OFFENSE", "BAL": "BALANCED", "DEF": "DEFENSE", "OUT": "FAST-EXIT"}


# ── inputs ─────────────────────────────────────────────────────────────────

def regime_by_date(book: Optional[pd.DataFrame]) -> pd.Series:
    if book is None or book.empty or "regime" not in book:
        return pd.Series(dtype=object)
    s = book.set_index(pd.to_datetime(book["date"]))["regime"].astype(str)
    return s[~s.index.duplicated(keep="last")].sort_index()


def balanced_fn(regimes: pd.Series, fallback: str):
    import regime_classifier as rc
    cache = {}

    def on(d) -> dict:
        r = regimes[regimes.index <= d]
        key = r.iloc[-1] if len(r) else fallback
        if key not in cache:
            cache[key] = {k: float(v) for k, v in rc.target_weights(key, gate=False).items()}
        return cache[key]
    return on


def expected_session(now_et: Optional[datetime] = None) -> Optional[date]:
    """The session whose bar must be in the data (same rule as the swing desk, N64)."""
    try:
        import market_time as mt
        n = now_et or mt.now_et()
        m = mt.minutes_since_close(n)
        if m is not None and m >= 30:
            return n.date()
        return mt.last_trading_day(n.date() - timedelta(days=1))
    except Exception:
        return None


# ── engine ─────────────────────────────────────────────────────────────────

def engine_states(data: dict) -> dict:
    return {k: ol.states(ol.CANDIDATES[k]["kind"], data["levels"], ol.MA, rets=data["rets"]) for k in ENGINES}


def weights_on_fn(st: pd.Series, cand: dict, bal_on):
    lagged = st.shift(ol.LAG)
    lagged.iloc[:ol.LAG] = st.iloc[0]
    m = lagged.to_dict()
    return lambda d: dict(ol.book_for(m[d], cand, bal_on(d)))


def run_shadow(data: dict, states: dict, bal_on, start: str = SHADOW_START,
               book: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """NAV per engine from `start` (100 on the first session). Empty before start."""
    days = data["cal"][data["cal"] >= pd.Timestamp(start)]
    if len(days) == 0:
        return pd.DataFrame()
    out = {}
    for k in ENGINES:
        sim = hl.simulate(days, data["rets"], weights_on_fn(states[k], ol.CANDIDATES[k], bal_on), None,
                          breaker=False, cost_bps=ol.COST_BPS)
        out[k] = sim["nav"] / sim["nav"].iloc[0] * 100
    spy = hl.simulate(days, data["rets"], lambda d: {"SPY": 100.0}, None, breaker=False, cost_bps=0.0)["nav"]
    out["SPY"] = spy / spy.iloc[0] * 100
    if book is not None and not book.empty and "nav" in book:
        b = book.set_index(pd.to_datetime(book["date"]))["nav"].astype(float)
        b = b[~b.index.duplicated(keep="last")].reindex(days).ffill()
        if b.notna().any():
            first = b.dropna().iloc[0]
            out["MODEL_BOOK"] = b / first * 100
    return pd.DataFrame(out).round(4)


def summarise(nav: pd.DataFrame) -> dict:
    res = {}
    for k in nav.columns:
        s = nav[k].dropna()
        if len(s) < 2:
            res[k] = {"since_start_pct": 0.0, "max_dd_pct": 0.0}
            continue
        res[k] = {"since_start_pct": round((s.iloc[-1] / s.iloc[0] - 1) * 100, 2),
                  "max_dd_pct": round(float((s / s.cummax() - 1).min()) * 100, 2),
                  "dd_now_pct": round(float(s.iloc[-1] / s.cummax().iloc[-1] - 1) * 100, 2)}
    return res


def today_read(states: dict, bal_on, asof: pd.Timestamp) -> list:
    rows = []
    for k in ENGINES:
        st = states[k]
        now = st.iloc[-1]
        prev = st.iloc[-2] if len(st) > 1 else now
        since = st[st != now]
        cand = ol.CANDIDATES[k]
        book = ol.book_for(now, cand, bal_on(asof))
        rows.append({"engine": k, "state": now, "word": STATE_WORDS.get(now, now),
                     "since": since.index[-1].date().isoformat() if len(since) else "start",
                     "switched_today": now != prev, "previous": prev,
                     "book_next": {t: w for t, w in sorted(book.items(), key=lambda x: -x[1]) if w > 0}})
    return rows


# ── output ─────────────────────────────────────────────────────────────────

def render(status: dict, reads: list, summ: dict, regime: str, asof: str) -> str:
    L = [f"# Engine shadow {VERSION} — {asof}", "",
         f"Forward record of the frozen engines from **{status.get('start', SHADOW_START)}** (offense_lab rules; no real money). "
         f"Live regime inside Balanced: `{regime}`.", ""]
    if status.get("error"):
        L += [f"**DATA FAILURE — nothing booked today:** {status['error']}", ""]
    if status.get("warning"):
        L += [f"**Data gap:** {status['warning']}", ""]
    L += ["## What each engine says", "", "| Engine | State | Since | Switch today | Holds from the next session |",
          "|---|---|---|---|---|"]
    for r in reads:
        bk = ", ".join(f"{t} {w:g}%" for t, w in list(r["book_next"].items())[:6])
        if len(r["book_next"]) > 6:
            bk += f" (+{len(r['book_next']) - 6} more)"
        sw = f"**yes** ({STATE_WORDS.get(r['previous'], r['previous'])} → {r['word']})" if r["switched_today"] else "no"
        L.append(f"| {r['engine']} {ol.CANDIDATES[r['engine']]['label']} | **{r['word']}** | {r['since']} | {sw} | {bk} |")
    L += [""]
    if not summ:
        L += [f"The forward record starts on {status.get('start', SHADOW_START)}; until then this page only reports the engines' reads."]
    else:
        L += ["## Since the start", "", "| Book | Return % | Max drawdown % | Drawdown now % |", "|---|---|---|---|"]
        for k, v in summ.items():
            L.append(f"| {k} | {v['since_start_pct']:+.2f} | {v['max_dd_pct']:.2f} | {v.get('dd_now_pct', 0):.2f} |")
        L += ["", "Judged at the monthly review against the offense-lab bar; a short record proves little either way."]
    L += ["", f"*engine_shadow.py {VERSION}. Research, not personalized advice.*"]
    return "\n".join(L) + "\n"


def write(nav: pd.DataFrame, reads: list, status: dict, md: str, asof: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if len(nav):
        nav.to_csv(OUT_DIR / "nav.csv", index_label="date")
    (OUT_DIR / "status.json").write_text(json.dumps({**status, "reads": reads}, indent=2, default=str))
    (LOG_DIR / "latest.md").write_text(md)
    (LOG_DIR / f"{asof}.md").write_text(md)


def build(closes: dict, book: Optional[pd.DataFrame], expected: Optional[date], asof: str,
          start: str = SHADOW_START) -> dict:
    status = {"version": VERSION, "asof": asof, "start": start, "error": None,
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if expected:      # N66: a run before the close settles must not read today's partial bar
        cut = pd.Timestamp(expected)
        closes = {t: (lambda x: x[x.index <= cut])(hl._norm(v)) for t, v in closes.items()
                  if v is not None and len(v)}
    missing = [t for t in NEEDED if t not in closes or closes[t] is None or not len(closes[t])]
    if missing:
        status["error"] = f"signal inputs missing: {', '.join(missing)}"
    data = ol.build_data(closes) if not missing else None
    if data is not None and data["levels"]["CREDIT"].dropna().empty:
        status["warning"] = ("credit pair (VWEHX/VFITX) missing: O11 used the plain 50-day exit today, "
                             "so its record matches O9's for this session")
    if data is not None:
        last = data["levels"][["SPY", "QQQ"]].dropna().index[-1].date()
        status["last_bar"] = last.isoformat()
        if expected and last < expected:
            status["error"] = f"prices end {last}, the {expected} session is missing (N64): nothing booked"
    regimes = regime_by_date(book)
    regime = regimes.iloc[-1] if len(regimes) else hl.REGIME
    bal_on = balanced_fn(regimes, hl.REGIME)
    if status["error"]:
        return {"status": status, "nav": pd.DataFrame(), "reads": [], "summary": {},
                "md": render(status, [], {}, regime, asof)}
    st = engine_states(data)
    reads = today_read(st, bal_on, data["cal"][-1])
    nav = run_shadow(data, st, bal_on, start, book)
    summ = summarise(nav) if len(nav) else {}
    return {"status": status, "nav": nav, "reads": reads, "summary": summ,
            "md": render(status, reads, summ, regime, asof)}


def main() -> int:
    tickers = sorted(set(ol.EXTRA_TICKERS) | set(hl.all_tickers()))
    start = (date.today() - timedelta(days=FETCH_DAYS)).isoformat()
    closes = hl.yf_fetch(tickers, start=start)
    book = pd.read_csv(BOOK_FILE) if BOOK_FILE.exists() else None
    exp = expected_session()
    asof = (exp or date.today()).isoformat()
    res = build(closes, book, exp, asof)
    write(res["nav"], res["reads"], res["status"], res["md"], asof)
    print(json.dumps({"status": res["status"], "reads": [{k: r[k] for k in ("engine", "word", "since",
                                                                              "switched_today")}
                                                         for r in res["reads"]], "summary": res["summary"]},
                     indent=2, default=str))
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    import os
    import tempfile
    f = []
    closes = ol._synthetic(n=3200)
    cal = hl._norm(closes["SPY"]).index
    start = cal[3000].date().isoformat()
    book = pd.DataFrame({"date": [cal[0].date().isoformat(), cal[3100].date().isoformat()],
                         "regime": ["neutral", "goldilocks"], "nav": [100.0, 103.0]})
    exp = cal[-1].date()
    r = build(closes, book, exp, "T", start=start)
    nav = r["nav"]
    if r["status"]["error"]:
        f.append(f"clean build failed: {r['status']['error']}")
    if nav.empty or nav.index[0] != pd.Timestamp(start) or not np.allclose(nav.iloc[0][["O9", "O7", "SPY"]], 100):
        f.append("every NAV starts at 100 on the shadow start")
    if (nav.index < pd.Timestamp(start)).any():
        f.append("nothing may be booked before the start")
    # the engine NAV equals the lab's own simulation over the same days (same rules, same accounting)
    data = ol.build_data(closes)
    st = engine_states(data)
    bal = balanced_fn(regime_by_date(book), hl.REGIME)
    days = data["cal"][data["cal"] >= pd.Timestamp(start)]
    lab = hl.simulate(days, data["rets"], weights_on_fn(st["O9"], ol.CANDIDATES["O9"], bal), None,
                      breaker=False, cost_bps=ol.COST_BPS)["nav"]
    if not np.allclose((lab / lab.iloc[0] * 100).to_numpy(), nav["O9"].to_numpy()):
        f.append("shadow O9 must equal the lab's simulation")
    if not st["O9"].equals(ol.states("fast", data["levels"], ol.MA, rets=data["rets"])):
        f.append("shadow states must be the lab's state machine")
    # Balanced follows the live regime by date
    import regime_classifier as rc
    if bal(cal[3050]) != {k: float(v) for k, v in rc.target_weights("neutral", gate=False).items()} or \
            bal(cal[3150]) != {k: float(v) for k, v in rc.target_weights("goldilocks", gate=False).items()}:
        f.append("Balanced must use the regime in force on each date")
    # one-session lag
    w = weights_on_fn(st["O7"], ol.CANDIDATES["O7"], bal)
    chg = [i for i in range(3001, len(cal)) if st["O7"].iloc[i] != st["O7"].iloc[i - 1]]
    if not chg:
        f.append("fixture produced no O7 switch after the start (lag test would be vacuous)")
    else:
        i = chg[0]
        if w(cal[i]) != ol.book_for(st["O7"].iloc[i - 1], ol.CANDIDATES["O7"], bal(cal[i])):
            f.append("weights must follow the state one session late")
    # N66: a bar after the expected session (intraday) is ignored, not read
    c3 = {t: pd.concat([v, pd.Series([v.iloc[-1] * 0.7], index=[v.index[-1] + pd.offsets.BDay(1)])])
          for t, v in closes.items()}
    r3 = build(c3, book, exp, "T", start=start)
    if r3["status"].get("last_bar") != exp.isoformat() or r3["status"]["error"] or \
            not r3["nav"].equals(nav) or [x["state"] for x in r3["reads"]] != [x["state"] for x in r["reads"]]:
        f.append(f"a partial bar after the expected session must be dropped: {r3['status'].get('last_bar')}")
    # v1.1: O11 is tracked; a missing credit pair is flagged, not hidden
    if "O11" not in nav or "O11" not in [x["engine"] for x in r["reads"]]:
        f.append("O11 must be in the shadow")
    c4 = {t: v for t, v in closes.items() if t not in ol.CREDIT_PAIR}
    r4 = build(c4, book, exp, "T", start=start)
    if r4["status"]["error"] or not r4["status"].get("warning") or "Data gap" not in r4["md"]:
        f.append("a missing credit pair must warn (O11 falls back to O9's exit), not fail the run")
    # pre-start: reads, no NAV
    r0 = build(closes, book, exp, "T", start=(cal[-1] + pd.Timedelta(days=30)).date().isoformat())
    if len(r0["nav"]) or not r0["reads"] or "starts on" not in r0["md"]:
        f.append("before the start: report the reads, book nothing")
    # N64: the feed short of the expected session books nothing
    r1 = build(closes, book, exp + timedelta(days=1), "T", start=start)
    if not r1["status"]["error"] or len(r1["nav"]) or "DATA FAILURE" not in r1["md"]:
        f.append("a feed one session short must book nothing and say so")
    # missing signal input
    c2 = dict(closes); c2.pop("XLK")
    r2 = build(c2, book, exp, "T", start=start)
    if not r2["status"]["error"] or "XLK" not in r2["status"]["error"]:
        f.append("a missing sector must block the run (breadth-free engines still need the full input set)")
    # model book is re-based to 100 at its first value inside the window
    if "MODEL_BOOK" not in nav or abs(nav["MODEL_BOOK"].dropna().iloc[0] - 100) > 1e-9:
        f.append("model book must be re-based to 100")
    # write
    tmp = tempfile.mkdtemp(); cwd = os.getcwd()
    try:
        os.chdir(tmp)
        write(r["nav"], r["reads"], r["status"], r["md"], "T")
        if not (Path(tmp) / "data/engine_shadow/nav.csv").exists() or "What each engine says" not in \
                (Path(tmp) / "logs/engine_shadow/latest.md").read_text():
            f.append("outputs not written")
    finally:
        os.chdir(cwd)
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        res = selftest()
        print(json.dumps(res, indent=2))
        sys.exit(0 if res["ok"] else 1)
    sys.exit(main())
