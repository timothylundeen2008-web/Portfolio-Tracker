"""
decision_page.py  (v1.0 — 2026-11-25)
─────────────────────────────────────
Strategy plan item 3 (claude/strategy_plan_2026-11-24.md): ONE decision page. For each book — what we
hold, why, and what would change it. Everything else in the app is supporting detail.

Read-only. It computes nothing new: every number comes from a file a nightly job already wrote
(model_book.csv, engine_shadow, the consolidated brief, the radar metrics, the swing account, the M0-T
paper record, alerts). Each source shows its as-of date; a source that is missing or more than one
session behind is flagged, and the decisions it feeds are named as blocked (a data gap is not a signal).

The "what would change it" lines restate the live O11 rules (offense_lab.states_fast) for the current
state, with today's distances from the radar's metrics. They are a reading of the rules, not a forecast.

Model portfolio and paper records only. Research, not personalized advice.

    import decision_page; decision_page.render(st)          # in app.py
    python decision_page.py --selftest

v1.0.1 (independent review): a switch is decided by the engine STATE (O11 state vs the model book's
engine column, or switched_today), never by comparing weights (the model book holds the GATED regime
weights, engine_shadow lists ungated ones, so BAL/OUT always "differed"); odd or corrupt files degrade to
"unreadable"/"missing" instead of breaking the tab; the fast-exit wording names the missing-credit case.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

VERSION = "1.0.1"
START_LT, START_SW = 100_000.0, 10_000.0
WORD = {"OFF": "OFFENSE", "BAL": "BALANCED", "DEF": "DEFENSE", "OUT": "OUT (fast exit → Balanced book)"}

EVIDENCE = [  # static, dated: update when a lab result changes the record
    ("Long-term engine O11", "kept",
     "63 years never used to build it: 1928–62 9.4%/yr vs market 8.4%, worst drop −36% vs −84%; "
     "1963–99 12.0% vs 12.7%, −18% vs −48%. Cost: whipsaw in sideways markets (two fixes failed: R2, G lab).",
     "claude/g_lab_2026-11-25.md, claude/oos_lab_2026-11-25.md"),
    ("Swing M0-T (ETFs)", "paper from 2026-12-01",
     "Best trade edge found (+0.44R, PF 1.8, 2005–26), but the $10k book returned 3.6%/yr vs SPY 10.7% "
     "(trial 97, corrected 2026-11-25). Paper record is the clean test.",
     "claude/m0t_lab_2026-11-23.md"),
    ("Swing account", "cash (SGOV)", "Stays in SGOV until a swing rule passes its bar.", "claude/two_books_charter.md"),
]
EVIDENCE_ASOF = "2026-11-25"


# ── reading ─────────────────────────────────────────────────────────────────

def _json(p: Path) -> Optional[dict]:
    try:
        j = json.loads(p.read_text())
        return j if isinstance(j, dict) else None
    except Exception:
        return None


def _dicts(x) -> list:
    return [y for y in x if isinstance(y, dict)] if isinstance(x, list) else []


def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else None
    except Exception:
        return None


def _d(x) -> Optional[date]:
    try:
        return date.fromisoformat(str(x)[:10])
    except Exception:
        return None


def expected_session(today: date) -> date:
    """The oldest session a nightly output may describe and still be current: the previous trading day
    (tonight's run may not have happened yet)."""
    try:
        import market_time as mt
        return mt.last_trading_day(today - timedelta(days=1))
    except Exception:
        d = today - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d


def latest_brief(root: Path) -> tuple:
    """(brief, its date). The date is None when the newest brief file cannot be read."""
    d = root / "logs" / "brief"
    files = sorted(d.glob("????-??-??_brief.json")) if d.exists() else []
    if not files:
        return None, None
    b = _json(files[-1])
    return (b, files[-1].name[:10] if b is not None else None)


def model_last(root: Path) -> Optional[dict]:
    p = root / "data" / "model_book.csv"
    try:
        df = pd.read_csv(p)
        r = df.iloc[-1].to_dict()
        w = json.loads(r.get("weights") or "{}")
        r["weights"] = {str(k): float(v) for k, v in w.items() if _num(v) is not None and float(v) > 0} if isinstance(w, dict) else {}
        r["nav"] = _num(r.get("nav"))
        r["drawdown_pct"] = _num(r.get("drawdown_pct"))
        r["first_date"] = str(df["date"].iloc[0])
        return r if r["nav"] is not None else None
    except Exception:
        return None


def radar_dist(root: Path) -> dict:
    try:
        m = pd.read_csv(root / "data" / "radar" / "latest_metrics.csv", index_col=0)
        asof = (_json(root / "data" / "radar" / "latest.json") or {}).get("asof")
        out = {"asof": asof}
        for t in ("SPY", "QQQ"):
            if t in m.index and _num(m.loc[t, "vs_200d"]) is not None:
                out[t] = float(m.loc[t, "vs_200d"])
        return out
    except Exception:
        return {}


def what_changes(state: str, dist: dict) -> list:
    """The live O11 rules (offense_lab.states_fast) that would move the book from `state`."""
    spy = f" (SPY now {dist['SPY']:+.1f}% vs its 200-day)" if "SPY" in dist else ""
    qqq = f" (QQQ now {dist['QQQ']:+.1f}% vs its 200-day)" if "QQQ" in dist else ""
    to_def = "→ **Defense** (60 SGOV / 20 GLD / 20 TLT) on 2 closes with SPY below its 200-day" + spy
    to_off = ("→ **Offense** (50 QQQ / 50 SPY) on 2 closes with SPY and QQQ above their 200-day and QQQ above "
              "its 50-day" + qqq)
    if state == "DEF":
        return ["→ **Balanced** (the regime book) on 2 closes with SPY back above its 200-day" + spy,
                to_off + " — can follow directly if all three hold"]
    if state == "BAL":
        return [to_off, to_def]
    if state == "OFF":
        return ["→ **OUT** (Balanced book, 20-session cooldown) on 2 closes with QQQ below its 50-day while credit "
                "confirms (or credit data is missing), or the Offense book −8% from its high", "→ **Balanced** on 2 closes with QQQ below its 200-day" + qqq,
                to_def]
    if state == "OUT":
        return [to_off + ", but only after the 20-session cooldown", to_def]
    return ["state unknown — the engine output is missing"]


def build_view(root: Path = Path("."), today: Optional[date] = None) -> dict:
    root = Path(root)
    if today is None:
        try:
            import market_time as mt
            today = mt.et_date()
        except Exception:
            today = date.today()
    exp = expected_session(today)
    brief, brief_date = latest_brief(root)
    mb = model_last(root)
    eng = _json(root / "data" / "engine_shadow" / "status.json")
    o11 = next((r for r in _dicts((eng or {}).get("reads")) if r.get("engine") == "O11"), None)
    swe = _json(root / "data" / "swing_engine" / "latest.json")
    pap = _json(root / "data" / "m0t_paper" / "summary.json")
    alr = _json(root / "logs" / "alerts" / "latest.json")
    dist = radar_dist(root)

    def src(name, asof, feeds):
        a = _d(asof)
        status = "missing" if a is None else ("stale" if a < exp else "ok")
        return {"source": name, "asof": str(a) if a else "—", "status": status, "feeds": feeds}
    sources = [src("Model book", (mb or {}).get("date"), "long-term book"),
               src("Engine (O11)", (eng or {}).get("last_bar"), "long-term book"),
               src("Daily brief", brief_date, "regime, data health, events"),
               src("Radar metrics", dist.get("asof"), "distances to the trend lines"),
               src("Swing account", (swe or {}).get("price_date"), "swing book"),
               src("M0-T paper record", (pap or {}).get("asof"), "swing book"),
               src("Alerts", (alr or {}).get("date"), "risk alerts")]
    dh = _dicts((brief or {}).get("data_health"))
    sw_health = next((x for x in dh if x.get("input") == "Swing brief"), None)
    if sw_health:
        sources.append(src("Swing desk brief", sw_health.get("asof"), "swing stand-downs and exits"))
    blocked = [s for s in sources if s["status"] != "ok"]
    health = [x for x in dh if x.get("status") not in ("OK", "UNUSED") and x.get("input") != "Swing brief"]  # already a source

    state = (o11 or {}).get("state") or (mb or {}).get("engine")
    nav = (mb or {}).get("nav")
    model = (brief or {}).get("model") if isinstance((brief or {}).get("model"), dict) else {}
    bench = model.get("benchmarks") if isinstance(model.get("benchmarks"), dict) else {}
    held = (mb or {}).get("weights") or {}
    held_state = (mb or {}).get("engine")
    has_held_state = isinstance(held_state, str) and held_state in WORD
    switching = bool((o11 or {}).get("switched_today")) or (
        bool(o11) and has_held_state and o11.get("state") != held_state) or (
        # the model book's engine column is empty: a state that began after its last row is still pending
        bool(o11) and not has_held_state and bool(o11.get("since")) and bool((mb or {}).get("date"))
        and str(o11.get("since")) > str((mb or {}).get("date")))
    nxt_state = (o11 or {}).get("state")
    if not switching:
        nxt = None
    elif nxt_state in ("BAL", "OUT"):
        nxt = "the Balanced book (regime weights set by tonight's brief)"
    else:
        nb = (o11 or {}).get("book_next")
        nxt = {k: float(v) for k, v in nb.items() if _num(v)} if isinstance(nb, dict) and nb else WORD.get(nxt_state, nxt_state)
    lt = {"state": state, "word": WORD.get(state, state or "unknown"), "since": (o11 or {}).get("since"),
          "switched_today": bool((o11 or {}).get("switched_today")),
          "held": held, "held_asof": (mb or {}).get("date"), "held_state": held_state,
          "next": nxt,
          "value": round(START_LT * nav / 100.0, 2) if nav is not None else None, "dd_pct": (mb or {}).get("drawdown_pct"),
          "since_start": {"date": bench.get("since"), "model": bench.get("model_pct"), "spy": bench.get("spy_pct"),
                          "sixty_forty": bench.get("sixty_forty_pct")},
          "regime": ((brief or {}).get("regime") or {}).get("key"),
          "why": ("The O11 engine sets the whole book from the trend of SPY and QQQ (2-close rules, acted on "
                  "the next session). The regime only shapes the Balanced book."),
          "changes": what_changes(state or "", dist), "dist": dist}

    tgt = (swe or {}).get("target") if isinstance((swe or {}).get("target"), dict) else {}
    sw = {"account_mode": (swe or {}).get("mode"),
          "account_target": tgt.get("weights") if isinstance(tgt.get("weights"), dict) else None,
          "account_state": tgt.get("state")}
    if pap:
        sw.update({"paper_mode": pap.get("mode"), "paper_start": pap.get("paper_start"), "equity": pap.get("equity"),
                   "ret_pct": pap.get("ret_pct"), "spy_ret_pct": pap.get("spy_ret_pct"),
                   "month_pct": pap.get("month_pct"), "max_dd_pct": pap.get("max_dd_pct"),
                   "limit_block": pap.get("limit_block"), "open": _dicts(pap.get("open")),
                   "orders": _dicts(pap.get("orders")),
                   "exits": list(pap.get("exits_next_open") or []) if isinstance(pap.get("exits_next_open"), (list, dict)) else [],
                   "recon": [str(x) for k in ("unseen_trades", "unplaced_orders", "restated")
                             for x in (pap.get(k) if isinstance(pap.get(k), list) else [])],
                   "expected": pap.get("expected") if isinstance(pap.get("expected"), dict) else {}})
    events = (brief or {}).get("next48") if isinstance((brief or {}).get("next48"), dict) else {}
    return {"version": VERSION, "today": str(today), "expected_session": str(exp), "sources": sources,
            "blocked": blocked, "health": health, "alerts": _dicts((alr or {}).get("findings")),
            "lt": lt, "sw": sw, "events": events, "evidence": EVIDENCE, "evidence_asof": EVIDENCE_ASOF}


# ── rendering ───────────────────────────────────────────────────────────────

def _book_df(w: dict, total: float) -> pd.DataFrame:
    rows = sorted(((k, float(v)) for k, v in (w or {}).items()), key=lambda x: -x[1])
    return pd.DataFrame([{"Fund": k, "Weight %": round(v, 1), "Dollars": round(total * v / 100.0)} for k, v in rows])


def _pct(x, signed=True):
    return "—" if x is None else (f"{x:+.2f}%" if signed else f"{x:.2f}%")


def render(st, root: Path = Path("."), view: Optional[dict] = None) -> dict:
    v = view or build_view(root)
    lt, sw = v["lt"], v["sw"]
    st.subheader("📍 Decision page — what we hold, why, and what would change it")
    st.caption(f"Model portfolio and paper records only — research, not personalized advice. Read-only: every number "
               f"comes from last night's jobs. decision_page {v['version']} · today {v['today']} ET.")

    if v["blocked"] or v["health"] or v["alerts"]:
        lines = [f"**{s['source']}** {s['status']} (as of {s['asof']}) → blocks: {s['feeds']}" for s in v["blocked"]]
        lines += [f"**{h.get('input')}** {h.get('status')} (as of {h.get('asof')}) {h.get('note') or ''}".strip()
                  for h in v["health"]]
        lines += [f"🔔 {a.get('title')} ({a.get('state')})" for a in v["alerts"]]
        st.warning("**Needs attention**\n\n" + "\n".join(f"- {x}" for x in lines))

    st.markdown("### Long-term book — $100,000 model")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Engine O11", lt["word"], f"since {lt['since']}" if lt["since"] else None)
    c2.metric("Model book", f"${lt['value']:,.0f}" if lt["value"] is not None else "missing",
              _pct(lt["dd_pct"]) + " from peak" if lt["dd_pct"] is not None else None, delta_color="off")
    ss = lt["since_start"]
    c3.metric(f"Since {ss.get('date') or 'start'}", _pct(ss.get("model")),
              f"SPY {_pct(ss.get('spy'))} · 60/40 {_pct(ss.get('sixty_forty'))}", delta_color="off")
    c4.metric("Regime (shapes Balanced)", lt["regime"] or "—")
    st.markdown(f"**Hold** (as of the {lt['held_asof']} close):")
    st.dataframe(_book_df(lt["held"], lt["value"] or 0.0), hide_index=True, use_container_width=True)
    if lt["next"]:
        nx = lt["next"] if isinstance(lt["next"], str) else ", ".join(f"{k} {v_:g}%" for k, v_ in lt["next"].items())
        st.error(f"**Switch:** the engine moved to {lt['word']}; from the next session the book becomes {nx}.")
    st.markdown(f"**Why:** {lt['why']}")
    st.markdown("**What would change it:**\n" + "\n".join(f"- {x}" for x in lt["changes"]))
    if lt["dist"].get("asof"):
        st.caption(f"Distances from the radar metrics as of {lt['dist']['asof']}.")

    st.markdown("### Swing book — $10,000")
    st.markdown(f"**Account:** {sw.get('account_state') or '—'} → " +
                (", ".join(f"{k} {v_:g}%" for k, v_ in (sw.get("account_target") or {}).items()) or "—"))
    if sw.get("paper_mode"):
        pm = "PREVIEW (record starts " + str(sw.get("paper_start")) + ")" if sw["paper_mode"] == "preview" else "LIVE paper"
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("M0-T paper record", pm)
        d2.metric("Paper equity", f"${(sw.get('equity') or 0):,.0f}", _pct(sw.get("ret_pct")) + f" (SPY {_pct(sw.get('spy_ret_pct'))})",
                  delta_color="off")
        d3.metric("This month (limit −10%)", _pct(sw.get("month_pct")))
        d4.metric("Max drawdown (limit −20%)", _pct(sw.get("max_dd_pct")))
        if sw.get("limit_block"):
            st.error(f"**Limit:** {sw['limit_block']}")
        orders = [o for o in sw.get("orders") or [] if o.get("status") == "ORDER"]
        if orders:
            st.markdown("**Orders for the next open:**")
            st.dataframe(pd.DataFrame([{k: o.get(k) for k in ("ticker", "conf", "buy_stop", "stop", "shares", "risk_pct")}
                                       for o in orders]), hide_index=True, use_container_width=True)
        else:
            why = sorted({o.get("why") for o in sw.get("orders") or [] if o.get("why")})
            st.markdown("**No orders for the next open.**" + (f" Signals blocked: {'; '.join(why)}." if why else
                                                                " No M0 signal tonight."))
        if sw.get("open"):
            st.markdown("**Open paper positions:**")
            st.dataframe(pd.DataFrame(sw["open"]), hide_index=True, use_container_width=True)
        if sw.get("exits"):
            st.warning("**Exits at the next open:** " + ", ".join(map(str, sw["exits"])))
        if sw.get("recon"):
            st.warning("**Reconciliation:** " + "; ".join(map(str, sw["recon"])))
        ex = sw.get("expected") or {}
        if ex:
            st.caption(f"Backtest expectation to judge the record against: {ex.get('expectancy_R')}R per trade, "
                       f"profit factor {ex.get('profit_factor')}, win rate {ex.get('win_rate')}% ({ex.get('source')}).")
    ev = v["events"]
    if ev.get("conclusion"):
        st.info(f"**Next 48 hours:** {ev['conclusion']}")

    with st.expander("Evidence behind each book", expanded=False):
        st.dataframe(pd.DataFrame([{"Book / rule": a, "Status": b, "Evidence": c, "Record": d} for a, b, c, d in v["evidence"]]),
                     hide_index=True, use_container_width=True)
        st.caption(f"Evidence lines as of {v['evidence_asof']}.")
    with st.expander("Sources and as-of dates", expanded=False):
        st.dataframe(pd.DataFrame(v["sources"]), hide_index=True, use_container_width=True)
        st.caption(f"A source older than the {v['expected_session']} session is stale; tonight's jobs may not have run yet.")
    return v


# ── selftest ────────────────────────────────────────────────────────────────

def _fixture(root: Path, state: str = "DEF", stale_swing: bool = True) -> None:
    (root / "data" / "engine_shadow").mkdir(parents=True)
    (root / "data" / "swing_engine").mkdir(parents=True)
    (root / "data" / "m0t_paper").mkdir(parents=True)
    (root / "data" / "radar").mkdir(parents=True)
    (root / "logs" / "brief").mkdir(parents=True)
    (root / "logs" / "alerts").mkdir(parents=True)
    w = {"SGOV": 60.0, "GLD": 20.0, "TLT": 20.0}
    pd.DataFrame([{"date": "2026-08-12", "regime": "neutral", "nav": 100.0, "drawdown_pct": 0.0, "weights": json.dumps({"SPY": 100.0}), "engine": "OFF"},
                  {"date": "2026-11-24", "regime": "credit_stress", "nav": 92.7869, "drawdown_pct": -9.02, "weights": json.dumps(w), "engine": state}]
                 ).to_csv(root / "data" / "model_book.csv", index=False)
    (root / "data" / "engine_shadow" / "status.json").write_text(json.dumps(
        {"last_bar": "2026-11-24", "reads": [{"engine": "O11", "state": state, "since": "2026-11-20", "switched_today": False, "book_next": w}]}))
    (root / "data" / "radar" / "latest.json").write_text(json.dumps({"asof": "2026-11-24"}))
    pd.DataFrame({"vs_200d": [-1.621, -6.495]}, index=["SPY", "QQQ"]).to_csv(root / "data" / "radar" / "latest_metrics.csv")
    (root / "data" / "swing_engine" / "latest.json").write_text(json.dumps(
        {"mode": "cash", "price_date": "2026-11-24", "target": {"state": "CASH (no swing rule has passed yet)", "weights": {"SGOV": 100.0}},
         "preview": {"tickets": []}}))
    (root / "data" / "m0t_paper" / "summary.json").write_text(json.dumps(
        {"asof": "2026-11-24", "mode": "preview", "paper_start": "2026-12-01", "equity": 10000.0, "ret_pct": 0.0, "spy_ret_pct": None,
         "month_pct": 0.0, "max_dd_pct": 0.0, "limit_block": None, "open": [], "exits_next_open": {},
         "orders": [{"ticker": "XLRE", "status": "no order", "why": "SPY below its 200-day: no new entries"}],
         "unseen_trades": [], "unplaced_orders": [], "restated": [],
         "expected": {"expectancy_R": 0.44, "profit_factor": 1.83, "win_rate": 28.4, "source": "trial 97"}}))
    (root / "logs" / "brief" / "2026-11-24_brief.json").write_text(json.dumps(
        {"regime": {"key": "credit_stress"},
         "model": {"benchmarks": {"since": "2026-08-12", "model_pct": -7.21, "spy_pct": -6.72, "sixty_forty_pct": -4.06}},
         "data_health": [{"input": "Swing brief", "asof": "2026-11-20" if stale_swing else "2026-11-24", "status": "STALE" if stale_swing else "OK"},
                         {"input": "Position ledger", "asof": "2026-07-26", "status": "UNUSED"},
                         {"input": "macro_flags", "asof": None, "status": "WARN", "note": "cape stale"}],
         "next48": {"conclusion": "Binary event inside the window: PCE."}}))
    (root / "logs" / "alerts" / "latest.json").write_text(json.dumps(
        {"date": "2026-11-25", "findings": [{"key": "DATA_FAIL", "title": "Data failure: 2 input(s) block decisions", "state": "active"}]}))


def selftest() -> dict:
    import tempfile
    f = []
    tmp = Path(tempfile.mkdtemp())
    _fixture(tmp / "a")
    v = build_view(tmp / "a", today=date(2026, 11, 25))
    lt, sw = v["lt"], v["sw"]
    if lt["word"] != "DEFENSE" or lt["since"] != "2026-11-20" or lt["next"] is not None:
        f.append(f"long-term state: {lt['word']} since {lt['since']}, next {lt['next']}")
    if abs(lt["value"] - 92786.9) > 0.5 or lt["dd_pct"] != -9.02:
        f.append(f"model book value ${lt['value']} / dd {lt['dd_pct']} (want $92,786.90 / −9.02)")
    if not any("SPY now -1.6%" in x for x in lt["changes"]) or not any("Balanced" in x for x in lt["changes"]):
        f.append(f"DEF: what would change it must name the 200-day reclaim with today's distance ({lt['changes']})")
    names = {s["source"]: s["status"] for s in v["sources"]}
    if names.get("Swing desk brief") != "stale" or names.get("Model book") != "ok" or names.get("Alerts") != "ok":
        f.append(f"source status: {names}")
    if [h["input"] for h in v["health"]] != ["macro_flags"]:
        f.append(f"data health must list non-OK inputs except UNUSED and the swing brief (a source): {[h['input'] for h in v['health']]}")
    if sw.get("paper_mode") != "preview" or sw.get("account_target") != {"SGOV": 100.0}:
        f.append(f"swing view: {sw}")
    # the rules restated for every state match offense_lab.states_fast's transitions
    for stt, must in (("BAL", ("Offense", "Defense")), ("OFF", ("OUT", "Balanced", "Defense")), ("OUT", ("cooldown", "Defense")),
                      ("DEF", ("Balanced", "Offense"))):
        txt = " ".join(what_changes(stt, {"SPY": 1.0, "QQQ": 2.0}))
        if not all(m in txt for m in must):
            f.append(f"what_changes({stt}) must mention {must}: {txt}")
    if "unknown" not in what_changes("", {})[0]:
        f.append("unknown state must say the engine output is missing")
    # a switch shows the next book
    _fixture(tmp / "b", state="DEF")                     # the model book still holds Defense ...
    es = json.loads((tmp / "b" / "data" / "engine_shadow" / "status.json").read_text())
    es["reads"][0].update({"state": "OFF", "switched_today": True, "book_next": {"QQQ": 50.0, "SPY": 50.0}})
    (tmp / "b" / "data" / "engine_shadow" / "status.json").write_text(json.dumps(es))   # ... the engine moved to Offense
    vb = build_view(tmp / "b", today=date(2026, 11, 25))
    if vb["lt"]["next"] != {"QQQ": 50.0, "SPY": 50.0}:
        f.append(f"an engine state different from the model book's must be shown as a switch ({vb['lt']['next']})")
    es["reads"][0].update({"state": "BAL"})
    (tmp / "b" / "data" / "engine_shadow" / "status.json").write_text(json.dumps(es))
    if "Balanced book" not in str(build_view(tmp / "b", today=date(2026, 11, 25))["lt"]["next"]):
        f.append("a switch to Balanced must name the Balanced book, not engine_shadow's ungated weights")
    es["reads"][0].update({"state": "OFF"})
    (tmp / "b" / "data" / "engine_shadow" / "status.json").write_text(json.dumps(es))
    # v1.0.1: BAL with the model book's gated weights != engine_shadow's ungated list must NOT be a switch
    _fixture(tmp / "c", state="BAL")
    es = json.loads((tmp / "c" / "data" / "engine_shadow" / "status.json").read_text())
    es["reads"][0]["book_next"] = {"SCHD": 14.0, "KMLM": 7.0, "SCHP": 5.0, "SGOV": 3.0}
    (tmp / "c" / "data" / "engine_shadow" / "status.json").write_text(json.dumps(es))
    if build_view(tmp / "c", today=date(2026, 11, 25))["lt"]["next"] is not None:
        f.append("same state, different weight lists: must not show a switch")
    # an empty engine column on the model book: a state that began after its last row is a pending switch
    _fixture(tmp / "e", state="DEF")
    mbe = pd.read_csv(tmp / "e" / "data" / "model_book.csv"); mbe["engine"] = ""
    mbe.to_csv(tmp / "e" / "data" / "model_book.csv", index=False)
    ese = json.loads((tmp / "e" / "data" / "engine_shadow" / "status.json").read_text())
    ese["reads"][0].update({"state": "OFF", "since": "2026-11-25", "book_next": {"QQQ": 50.0, "SPY": 50.0}})
    (tmp / "e" / "data" / "engine_shadow" / "status.json").write_text(json.dumps(ese))
    if build_view(tmp / "e", today=date(2026, 11, 26))["lt"]["next"] != {"QQQ": 50.0, "SPY": 50.0}:
        f.append("with an empty engine column, a state newer than the model book must still show as a switch")
    ese["reads"][0].update({"since": "2026-11-20"})
    (tmp / "e" / "data" / "engine_shadow" / "status.json").write_text(json.dumps(ese))
    if build_view(tmp / "e", today=date(2026, 11, 26))["lt"]["next"] is not None:
        f.append("with an empty engine column, an old state must not show as a switch")
    # odd and corrupt files degrade instead of crashing or looking healthy
    _fixture(tmp / "d")
    (tmp / "d" / "data" / "engine_shadow" / "status.json").write_text(json.dumps({"last_bar": "2026-11-24", "reads": {"x": 1}}))
    (tmp / "d" / "logs" / "alerts" / "latest.json").write_text(json.dumps({"date": "2026-11-25", "findings": "oops"}))
    (tmp / "d" / "data" / "m0t_paper" / "summary.json").write_text(json.dumps({"asof": "2026-11-24", "mode": "preview",
        "orders": ["x"], "open": None, "exits_next_open": "x", "unplaced_orders": "y", "expected": "z"}))
    pd.read_csv(tmp / "d" / "data" / "model_book.csv").assign(nav=float("nan")).to_csv(tmp / "d" / "data" / "model_book.csv", index=False)
    pd.DataFrame({"vs_200d": [float("nan"), -6.0]}, index=["SPY", "QQQ"]).to_csv(tmp / "d" / "data" / "radar" / "latest_metrics.csv")
    (tmp / "d" / "logs" / "brief" / "2026-11-24_brief.json").write_text("{not json")
    try:
        vd = build_view(tmp / "d", today=date(2026, 11, 25))
        st_d = {s["source"]: s["status"] for s in vd["sources"]}
        if st_d.get("Daily brief") != "missing" or st_d.get("Model book") != "missing" or vd["lt"]["value"] is not None:
            f.append(f"a corrupt brief / NaN model book must show as missing, not ok/$100,000 ({st_d}, {vd['lt']['value']})")
        if any("nan" in x.lower() for x in vd["lt"]["changes"]) or vd["lt"]["next"] is not None:
            f.append("NaN distances must be omitted and no switch shown")
    except Exception as e:
        f.append(f"odd files crashed build_view: {type(e).__name__}: {e}")
    # stale detection: model book two sessions behind
    vs = build_view(tmp / "a", today=date(2026, 11, 27))
    if {s["source"]: s["status"] for s in vs["sources"]}.get("Model book") != "stale":
        f.append("a model book older than the previous session must be stale")
    # missing everything: no crash, all missing, state unknown
    (tmp / "empty").mkdir()
    ve = build_view(tmp / "empty", today=date(2026, 11, 25))
    if any(s["status"] != "missing" for s in ve["sources"]) or "unknown" not in ve["lt"]["changes"][0]:
        f.append("an empty store must show every source missing and the state unknown")
    # rendering with a stub Streamlit (and the real one if available)
    class Stub:
        def __init__(self): self.calls = []
        def __getattr__(self, n):
            def fn(*a, **k):
                self.calls.append((n, a))
                return [self for _ in range(a[0])] if n == "columns" and a and isinstance(a[0], int) else _Ctx(self)
            return fn
    class _Ctx:
        def __init__(self, s): self.s = s
        def __enter__(self): return self.s
        def __exit__(self, *a): return False
    for root in (tmp / "a", tmp / "b", tmp / "c", tmp / "d", tmp / "empty"):
        try:
            stb = Stub()
            render(stb, root, build_view(root, today=date(2026, 11, 25)))
            text = " ".join(str(a) for _, args in stb.calls for a in args)
            if root.name == "a" and ("Needs attention" not in text or "Swing desk brief" not in text or "92,787" not in text):
                f.append("render: the attention box, the stale swing brief and the book value must show")
            if root.name == "b" and "Switch" not in text:
                f.append("render: a switch must be shown")
        except Exception as e:
            import traceback
            f.append(f"render crashed on {root.name}: {type(e).__name__}: {e} {traceback.format_exc()[-300:]}")
    try:
        from streamlit.testing.v1 import AppTest
        script = (f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
                  "import streamlit as st, decision_page as dp\nfrom datetime import date\nfrom pathlib import Path\n"
                  f"dp.render(st, Path({str(tmp / 'a')!r}), dp.build_view(Path({str(tmp / 'a')!r}), today=date(2026, 11, 25)))\n")
        sp = tmp / "app_dp.py"
        sp.write_text(script)
        at = AppTest.from_file(str(sp)).run(timeout=60)
        if at.exception:
            f.append(f"AppTest exception: {at.exception[0].message if at.exception else ''}")
        elif not any("DEFENSE" in str(m.value) for m in at.metric):
            f.append("AppTest: the engine metric must read DEFENSE")
    except ImportError:
        pass
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 1)
    print(json.dumps(build_view(), indent=1, default=str)[:4000])
