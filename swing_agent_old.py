"""
swing_agent.py  (v1 — September 2026)
─────────────────────────────────────
The Swing Desk Agent's daily run. Runs Part 2 of swing_trading_procedure.md
in order, writes ONE brief, and stops. It never places, sizes into, or
closes anything: every card and every exit recommendation carries
pending_confirmation=True and waits for a journal decision from the tab or
from chat.

    python swing_agent.py            # today's brief -> logs/swing/
    python swing_agent.py --dry      # print, don't write
    python swing_agent.py --selftest

WHAT IT WRITES
    logs/swing/YYYY-MM-DD_brief.json    the contract both surfaces read
    logs/swing/YYYY-MM-DD_brief.md      human-readable render of the same
    logs/swing/cards_history.csv        every card, every day, with the close
                                        that day -- the raw material for the
                                        weekly forward-return review

DETERMINISM BOUNDARY
    Every number here comes from swing_desk / swing_screener / swing_journal /
    swing_exits / swing_trail. Fields that end in _note, teaching_question,
    what_would_make_this_wrong, regime_read and question_of_the_day are
    reserved for swing_annotate.py (Phase 5) and are None until it runs.
    validate() refuses any brief whose numeric fields changed after annotation.

WHAT IT REFUSES TO DO (and says so in the brief instead)
    - size anything when starting_equity is unset
    - assume a confluence leg whose data was not supplied
    - produce a long card in a regime that closes the long book
    - produce more cards than there are slots (extras go to "watch")
    - enter within 48h of FOMC/CPI (EPs exempt) or the ticker's own earnings
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

import swing_desk
import swing_exits
import swing_journal as sj
import swing_screener
import swing_trail

LOG_DIR = Path(os.environ.get("SWING_LOG_DIR", "logs/swing"))
LLM_FIELDS = {"why_note", "what_would_make_this_wrong", "instrument_note", "teaching_question",
              "trigger_note", "decline_consequence", "regime_read", "question_of_the_day"}
BREADTH_HALVE_BELOW = 40.0      # % of proxy universe above 200-day
BREADTH_TAILWIND_ABOVE = 50.0
# If more than this fraction of requested tickers come back missing or with a
# stale last bar, the run is a DATA FAILURE, not a "no setups" day.
DATA_FAIL_FRACTION = 0.20


# ── Inputs ──────────────────────────────────────────────────────────────────

def _clean_ohlcv(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Drop rows with no Close, de-duplicate and sort the index.

    Sept 2026 fix: yfinance can return a final bar whose OHLC is NaN but whose
    Volume is filled (0). `dropna(how="all")` keeps that row, so Close.iloc[-1]
    is NaN and every comparison against it is False. From 2026-09-14 that made
    every name fail the Trend Template and read breadth as 0.0%, and the brief
    reported it as "no setups" for nine sessions."""
    if df is None or df.empty or "Close" not in df.columns:
        return df
    df = df.dropna(subset=["Close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _default_fetch(tickers: list[str], period: str = "2y") -> dict:
    import yfinance as yf
    out = {}
    if not tickers:
        return out
    raw = yf.download(sorted(set(tickers)), period=period, auto_adjust=True, progress=False, group_by="ticker")
    for t in set(tickers):
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = _clean_ohlcv(df.dropna(how="all"))
            if df is not None and not df.empty:
                out[t] = df
        except Exception:
            continue
    return out


def _data_health(raw: dict, clean: dict, requested: list[str]) -> dict:
    """Did the price fetch actually work? Separates 'the market gave no setups'
    from 'the data never arrived' -- two states that demand opposite reads.

    missing    requested but absent/empty after cleaning
    nan_last   names whose RAW last bar had a NaN close (cleaned, but counted)
    stale      names whose last bar is older than the most common last bar"""
    req = sorted(set(requested))
    missing = [t for t in req if clean.get(t) is None or clean[t].empty]
    nan_last = sorted(t for t, d in raw.items()
                      if d is not None and not d.empty and "Close" in d.columns and pd.isna(d["Close"].iloc[-1]))
    last = {t: clean[t].index[-1] for t in req if t not in missing}
    stale, ref = [], None
    if last:
        ref = pd.Series(list(last.values())).mode().iloc[0]
        stale = sorted(t for t, d in last.items() if d < ref)
    bad = len(missing) + len(stale)
    frac = bad / len(req) if req else 0.0
    return {"requested": len(req), "missing": missing, "stale": stale, "nan_last_cleaned": nan_last,
            "last_bar": str(ref.date()) if ref is not None and hasattr(ref, "date") else (str(ref) if ref is not None else None),
            "bad_fraction": round(frac, 3), "failed": bool(req) and frac > DATA_FAIL_FRACTION}


def _read_bridges() -> tuple[dict, dict]:
    import markets_bridge, rotation_bridge
    return markets_bridge.read(), rotation_bridge.read_summary()


def _breadth_proxy(ohlcv: dict, universe: list[str]) -> dict:
    """% of the constituent proxy universe above its 200-day. Labelled as a proxy, not the S&P."""
    above = tot = 0
    for tk in universe:
        df = ohlcv.get(tk)
        if df is None or len(df) < 200:
            continue
        px, ma = df["Close"].iloc[-1], df["Close"].rolling(200).mean().iloc[-1]
        if pd.isna(px) or pd.isna(ma):
            continue                      # unknown is not "below" -- never count it
        tot += 1
        above += int(px > ma)
    pct = round(above / tot * 100, 1) if tot else None
    return {"pct_above_200": pct, "n": tot, "source": f"{tot}-name sector-constituent proxy (not the full S&P 500)",
            "size_cut": bool(pct is not None and pct < BREADTH_HALVE_BELOW),
            "read": (None if pct is None else "tailwind" if pct >= BREADTH_TAILWIND_ABOVE
                     else "headwind — most breakouts fail; planned size halved again" if pct < BREADTH_HALVE_BELOW
                     else "mixed")}


# ── The run ─────────────────────────────────────────────────────────────────

def build_brief(fetch_ohlcv: Optional[Callable] = None, bridges: Optional[tuple] = None,
                today: Optional[date] = None, earnings_lookup: Optional[Callable] = None,
                macro_lookup: Optional[Callable] = None) -> dict:
    fetch = fetch_ohlcv or _default_fetch
    if today is None:
        try:
            import market_time as mt
            today = mt.et_date()          # the runner's clock is UTC; 8pm ET is already tomorrow there
        except Exception:
            today = date.today()
    markets, rotation = bridges or _read_bridges()
    cfg = sj.load_config()
    journal = sj.load()

    brief = {"date": today.isoformat(), "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "annotated": False, "refusals": [], "data_gaps": []}

    # ── 1. Regime gate ────────────────────────────────────────────────────
    if not markets.get("available"):
        regime_key = "unknown"
        brief["refusals"].append("Markets bridge unavailable: regime unknown, no new cards. "
                                 "The desk does not scan without Level 1.")
    else:
        regime_key = markets["regime"]["key"]
        if markets.get("very_stale"):
            brief["refusals"].append(f"Markets summary very stale ({markets.get('age_hours')}h): "
                                     "cards suppressed until republished.")
    direction, size_mult = swing_desk.REGIME_DIRECTION.get(regime_key, ("both", 0.5))
    trip = markets.get("tripwires") or []
    brief["regime"] = {"key": regime_key, "label": (markets.get("regime") or {}).get("label"),
                       "direction": direction, "size_mult": size_mult,
                       "long_book": "open" if direction in ("long", "both") else "CLOSED",
                       "short_book": "open" if direction in ("short", "both") else "closed",
                       "drivers": (markets.get("regime") or {}).get("drivers", []),
                       "fed_posture": markets.get("fed_posture"), "tripwires": trip,
                       "bridge_age_hours": markets.get("age_hours"), "regime_read": None}
    cards_allowed = not brief["refusals"]

    # ── 2b. Own results: PE step, equity, heat ─────────────────────────────
    pe = sj.pe_step(regime_key, journal)
    eq = sj.equity(journal)
    heat = sj.heat_used_pct(journal)
    brief["exposure"] = {**pe, "equity": eq["equity"], "starting_equity": eq["starting_equity"],
                         "realized_pnl": eq["realized_pnl"], "heat_used_pct": heat["heat_pct"],
                         "heat_cap_pct": cfg["heat_cap_pct"], "open_count": heat["open_count"],
                         "slots_open": heat["slots_open"], "max_positions": cfg["max_positions"]}
    if eq["equity"] is None:
        brief["refusals"].append(eq["note"]); cards_allowed = False
    if pe["step"] == 0:
        brief["refusals"].append("Progressive Exposure step 0: " + pe["why"]); cards_allowed = False

    # ── 3. Rotation: hunting grounds ───────────────────────────────────────
    # max_long=5 so LEADING sectors are not crowded out by the Improving-first
    # ranking: Improving feeds M0/M2 (early phase), Leading feeds M1 VCP
    # (confirmed-leader phase). One method per phase -- see 12 Sep review.
    sel = swing_screener.select_sectors(rotation, max_long=5, max_short=3)
    cands = swing_screener.expand_candidates(sel, rotation.get("constituents", {}))
    all_meta = {**cands["short"], **cands["long"]}
    for r in sel.get("reasons", []):
        brief["data_gaps"].append("Rotation: " + r)
    if rotation.get("available") and rotation.get("sectors") and all(r.get("quadrant") is None for r in rotation["sectors"]):
        brief["data_gaps"].append("Rotation rows carry no `quadrant` — the publisher is not running rotation_math.run_pipeline(). "
                                  "Rotation leg cannot pass until fixed.")
    constituents = rotation.get("constituents", {}) or {}
    sector_of = {tk: etf for etf, names in constituents.items() for tk in names}
    quad_of_sector = {r["ticker"]: r.get("quadrant") for r in rotation.get("sectors", []) if r.get("ticker")}

    # watchlist: coverage, not confluence — quadrant only if its sector is published
    wl = sj.watchlist()
    for _, w in wl.iterrows():
        tk = w["ticker"]
        if tk in all_meta:
            continue
        sec = sector_of.get(tk, tk if tk in quad_of_sector else None)
        all_meta[tk] = {"sector": sec, "quadrant": quad_of_sector.get(sec), "accumulation_score": None,
                        "stealth": None, "tier_a": False, "is_etf": tk in quad_of_sector,
                        "watchlist_reason": w.get("reason")}
    brief["hunting_grounds"] = {"long": [{"ticker": s["ticker"], "quadrant": s.get("quadrant"),
                                          "direction": s.get("rotation_direction"), "stealth": s.get("stealth_label"),
                                          "feeds": "M1 VCP (confirmed leaders)" if s.get("quadrant") == "Leading"
                                                   else "M0 rotation reclaim / M2 breakout (early phase)"}
                                         for s in sel["long"]],
                                "short": [{"ticker": s["ticker"], "quadrant": s.get("quadrant"),
                                           "direction": s.get("rotation_direction")} for s in sel["short"]],
                                "watchlist": wl["ticker"].tolist(), "candidates": sorted(all_meta)}

    # ── prices: candidates + open positions + breadth proxy, one batch ─────
    opens = sj.open_positions(journal)
    breadth_universe = sorted({t for names in constituents.values() for t in names})
    tickers = sorted(set(all_meta) | set(opens) | set(breadth_universe) | {"SPY"})
    raw_ohlcv = fetch(tickers) if tickers else {}
    ohlcv = {t: _clean_ohlcv(d) for t, d in raw_ohlcv.items()}
    health = _data_health(raw_ohlcv, ohlcv, tickers)
    brief["data_health"] = health
    if health["nan_last_cleaned"]:
        brief["data_gaps"].append(f"Price feed returned a NaN last close for {len(health['nan_last_cleaned'])} names "
                                  f"(dropped the empty bar, used the prior close).")
    if health["failed"]:
        brief["refusals"].append(
            f"DATA FAILURE: {len(health['missing'])} missing + {len(health['stale'])} stale of "
            f"{health['requested']} tickers ({health['bad_fraction']:.0%}). No cards until the price feed is healthy; "
            f"today's scan is NOT a 'no setups' verdict.")
        cards_allowed = False
    stale_set = set(health["stale"])
    bench = (ohlcv.get("SPY") if ohlcv.get("SPY") is not None else pd.DataFrame()).get("Close")
    brief["breadth"] = _breadth_proxy(ohlcv, breadth_universe)
    breadth_mult = 0.5 if brief["breadth"]["size_cut"] else 1.0

    # ── 6. Events ──────────────────────────────────────────────────────────
    import event_calendar as ec
    macro = (macro_lookup or ec.upcoming_macro)(2)
    blackout = [e for e in macro if e.get("blackout")]
    earn = (earnings_lookup or ec.earnings_dates)(sorted(all_meta)) if all_meta else {}
    brief["events"] = {"blackout": blackout, "earnings_48h": {t: v for t, v in earn.items() if 0 <= v["days_away"] <= 2},
                       "caveat": "earnings dates are yfinance estimates — confirm on the IR page before entering"}

    # ── 4/5/7/8. Scan, score, size, invalidate ─────────────────────────────
    cards, watch, avoid, errors = [], [], [], []
    for tk in sorted(all_meta):
        df = ohlcv.get(tk)
        if df is None or len(df) < 60:
            errors.append({"ticker": tk, "error": "insufficient history"}); continue
        if tk in stale_set:
            errors.append({"ticker": tk, "error": f"stale last bar {df.index[-1]} (expected {health['last_bar']})"}); continue
        m = all_meta[tk]
        try:
            r = swing_desk.evaluate(tk, df, regime_key, bench=bench, sector_quadrant=m.get("quadrant"),
                                    tier_a_confirmed=bool(m.get("stealth")),
                                    equity=eq["equity"] or 0.0, pe_step=pe["step"],
                                    heat_used_pct=heat["heat_pct"] or 0.0,
                                    earnings_within_48h=tk in brief["events"]["earnings_48h"],
                                    is_etf=bool(m.get("is_etf")))
        except Exception as e:
            errors.append({"ticker": tk, "error": f"{type(e).__name__}: {e}"}); continue
        base = {"ticker": tk, "sector": m.get("sector"), "sector_quadrant": m.get("quadrant"),
                "from_watchlist": "watchlist_reason" in m, "close": round(float(df["Close"].iloc[-1]), 2)}
        if not r["card"]:
            reason = r["avoid_reason"] or "no setup"
            (watch if "Watchlist only" in reason or "Watchlist it" in reason else avoid).append(
                {**base, "setup": r.get("setup"), "reason": reason})
            continue
        c, sz = r["card"], r["card"]["size"]
        adr = (r["detail"].get("universe") or {}).get("adr_pct")
        tg = swing_trail.trail_guidance(c["setup"], df, adr)
        shares = sz["shares"]
        if breadth_mult < 1.0 and shares:
            shares = int(shares * breadth_mult)
        legs = r["confluence"]
        card = {**base, "setup": c["setup"], "side": c["side"], "confluence": c["confluence"],
                "legs": {**legs["legs"], "missing": legs.get("missing", [])},
                "entry": c["entry"], "stop": c["stop"], "stop_pct": c["stop_pct"],
                "risk_per_share": c["risk_per_share"], "risk_pct": round(c["risk_pct"] * c["regime_mult"] * legs["size_mult"] * breadth_mult, 3),
                "shares": shares, "notional": round(shares * c["entry"], 2),
                "notional_pct": round(shares * c["entry"] / eq["equity"] * 100, 1) if eq["equity"] else None,
                "heat_after": sz.get("heat_after_pct"), "blocked_by_heat": sz.get("blocked_by_heat"),
                "targets": c["targets"], "trail": tg["trail"], "trail_why": tg["why"], "trail_stats": tg["stats"],
                "instrument": c["instrument"], "invalidated_when": c["invalidated_when"],
                "why": c["why"], "adr_pct": adr,
                "event_risk": ("EP — catalyst already happened" if c["setup"] == "M2 EP" else
                               "; ".join(f"{e['event']} in {e['days_away']}d" for e in blackout) or "clear"),
                "entry_permitted": True, "entry_block_reason": None,
                "why_note": None, "what_would_make_this_wrong": None, "instrument_note": None,
                "teaching_question": None, "pending_confirmation": True}
        if blackout and c["setup"] != "M2 EP":
            card["entry_permitted"] = False
            card["entry_block_reason"] = "binary macro event within 48h: " + card["event_risk"]
        if not cards_allowed:
            card["entry_permitted"] = False
            card["entry_block_reason"] = "; ".join(brief["refusals"])
        if shares == 0 and card["entry_permitted"]:
            card["entry_permitted"] = False
            budget = (eq["equity"] or 0) * card["risk_pct"] / 100
            card["entry_block_reason"] = (sz.get("reason") if sz.get("blocked_by_heat") else
                f"risk budget ${budget:,.2f} at this step/regime is below one share's risk (${c['risk_per_share']:,.2f}) "
                f"— a single share breaches Progressive Exposure; the only expression is a 45-90 DTE call "
                f"debit spread with premium <= ${budget:,.0f}, or skip")
        cards.append(card)

    cards.sort(key=lambda c: (not c["entry_permitted"], -int(c["confluence"][0]),
                              swing_screener.QUAD_PRIORITY.get(c["sector_quadrant"], 9), c["stop_pct"]))
    # slots: the desk shows what fits, and names what doesn't
    slots = heat["slots_open"]
    for i, c in enumerate(cards):
        if c["entry_permitted"] and i >= slots:
            c["entry_permitted"] = False
            c["entry_block_reason"] = f"over slot cap ({cfg['max_positions']} positions max, {slots} open) — watch, or close something first"
    brief["cards"], brief["watch"], brief["avoid"], brief["errors"] = cards, watch, avoid, errors

    # ── 9. Manage opens ────────────────────────────────────────────────────
    sq = {tk: quad_of_sector.get(sector_of.get(tk, tk)) for tk in opens}
    brief["open_positions"] = swing_exits.manage(opens, ohlcv, regime_key, sq)

    # ── carry-over: what you never answered ────────────────────────────────
    brief["unconfirmed_from_prior"] = _pending_from_prior(journal, today)
    brief["question_of_the_day"] = None
    brief["review"] = None
    return brief


def _pending_from_prior(journal: pd.DataFrame, today: date) -> list[dict]:
    if not LOG_DIR.exists():
        return []
    prior = sorted(p for p in LOG_DIR.glob("*_brief.json") if p.name[:10] < today.isoformat())
    if not prior:
        return []
    try:
        b = json.loads(prior[-1].read_text())
    except Exception:
        return []
    return sj.pending_from_brief(b, journal)


# ── Output ──────────────────────────────────────────────────────────────────

def render_md(b: dict) -> str:
    r, x = b["regime"], b["exposure"]
    L = [f"# Swing Desk brief — {b['date']}", "",
         f"**Regime:** `{r['key']}` — long book {r['long_book']}, short book {r['short_book']}, size ×{r['size_mult']}.",
         f"**You:** PE step {x['step']} ({x['risk_pct']}% risk) — {x['why']}",
         f"**Equity:** ${x['equity']:,.0f} (start ${x['starting_equity']:,.0f}, realized {x['realized_pnl']:+,.0f}) · "
         f"heat {x['heat_used_pct']}% of {x['heat_cap_pct']}% · {x['open_count']} open, {x['slots_open']} slots"
         if x["equity"] is not None else "**Equity:** not set — desk cannot size",
         (f"**Breadth (proxy):** {b['breadth']['pct_above_200']}% above 200-day — {b['breadth']['read']}"
          if b["breadth"]["pct_above_200"] is not None else "**Breadth (proxy):** no price data this run"), ""]
    if r.get("regime_read"):
        L += [r["regime_read"], ""]
    if b["refusals"]:
        L += ["## Refused", *[f"- {s}" for s in b["refusals"]], ""]
    if b["unconfirmed_from_prior"]:
        L += ["## UNCONFIRMED from the last brief — the desk assumed nothing",
              *[f"- {p['ticker']}: {p['kind']} {p.get('recommendation') or p.get('setup') or ''} ({p['date']})"
                for p in b["unconfirmed_from_prior"]], ""]
    if b["open_positions"]:
        L += ["## Open positions"]
        for p in b["open_positions"]:
            if p["recommendation"] == "NO DATA":
                L += [f"- **{p['ticker']}** — NO DATA: {p['why']}"]; continue
            L += [f"### {p['ticker']} — {p['recommendation']}" + (" (pending your confirmation)" if p["pending_confirmation"] else ""),
                  f"{p['setup']} {p['side']} · entry {p['entry']} · stop {p['stop']} · now {p['current']} · **{p['R']}R** · day {p['days_held']}",
                  *[f"- {k}: {v}" for k, v in p["triggers"].items()],
                  f"- → {p['why']}"]
            if p.get("trigger_note"):
                L += [f"- {p['trigger_note']}"]
            if p.get("decline_consequence"):
                L += [f"- If you decline: {p['decline_consequence']}"]
            L += [""]
    hg = b["hunting_grounds"]
    L += ["## Hunting grounds",
          "Long: " + (", ".join(f"{s['ticker']} ({s['quadrant']}, {s['direction']} → {s['feeds']})" for s in hg["long"]) or "none"),
          "Short: " + (", ".join(f"{s['ticker']} ({s['quadrant']})" for s in hg["short"]) or "none"),
          "Watchlist: " + (", ".join(hg["watchlist"]) or "empty"), ""]
    if b["events"]["blackout"]:
        L += ["**Event block:** " + "; ".join(f"{e['event']} in {e['days_away']}d" for e in b["events"]["blackout"]), ""]
    L += [f"## Trade cards ({len(b['cards'])})"]
    dh = b.get("data_health") or {}
    if not b["cards"] and dh.get("failed"):
        L += [f"**No cards because the price data failed** ({dh.get('bad_fraction', 0):.0%} of tickers missing or stale). "
              "This is a data gap, not a market verdict.", ""]
    elif not b["cards"]:
        L += ["No card today. That is a valid answer, not a gap.", ""]
    for c in b["cards"]:
        tag = "ENTRY PERMITTED" if c["entry_permitted"] else f"NOT PERMITTED — {c['entry_block_reason']}"
        L += [f"### {c['ticker']} — {c['setup']} ({c['side']}) · {c['confluence']} · {tag}",
              f"- Sector {c['sector']} [{c['sector_quadrant']}] · close {c['close']} · ADR {c['adr_pct']}%" + (" · from watchlist" if c["from_watchlist"] else ""),
              f"- Entry trigger **{c['entry']}** · stop **{c['stop']}** ({c['stop_pct']}%) — never moved down",
              f"- Risk {c['risk_pct']}% → **{c['shares']} sh**, ${c['notional']:,.0f} ({c['notional_pct']}% of equity) · heat after {c['heat_after']}%",
              f"- Targets 2R {c['targets']['2R']} · 4R {c['targets']['4R']} · 8R {c['targets']['8R']} · trail {c['trail']}",
              f"- Trail read: {c['trail_why']}",
              f"- Instrument: {c['instrument']}" + (f" — {c['instrument_note']}" if c.get("instrument_note") else ""),
              f"- Legs: rotation={c['legs']['rotation']} structure={c['legs']['structure']} volume={c['legs']['volume']}"
              + (f" · missing: {', '.join(c['legs']['missing'])}" if c["legs"]["missing"] else ""),
              f"- Invalidated when: {c['invalidated_when']}",
              f"- Event risk: {c['event_risk']}",
              f"- Why: {c['why']}"]
        for k, lab in (("why_note", "Read"), ("what_would_make_this_wrong", "What would make this wrong"),
                       ("teaching_question", "Question for you")):
            if c.get(k):
                L += [f"- **{lab}:** {c[k]}"]
        L += [""]
    if b["watch"]:
        L += ["## Watch (1-of-3 or regime-refused)", *[f"- {w['ticker']} [{w['sector_quadrant']}]: {w['reason']}" for w in b["watch"]], ""]
    if b["avoid"]:
        L += ["## Not a setup", *[f"- {a['ticker']}: {a['reason']}" for a in b["avoid"][:25]],
              *([f"- … {len(b['avoid'])-25} more"] if len(b["avoid"]) > 25 else []), ""]
    if b["data_gaps"]:
        L += ["## Data gaps (named, not filled)", *[f"- {g}" for g in b["data_gaps"]], ""]
    if b["errors"]:
        L += [f"_{len(b['errors'])} tickers errored: " + ", ".join(e["ticker"] for e in b["errors"][:10]) + "_", ""]
    if b.get("question_of_the_day"):
        L += ["## Question of the day", b["question_of_the_day"], ""]
    L += ["---", "_Desk research, not personalized advice. Nothing here executes; confirm or decline from the tab or chat._"]
    return "\n".join(L)


def _numeric_fingerprint(b: dict) -> str:
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in LLM_FIELDS}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    return json.dumps(strip(b), sort_keys=True, default=str)


def validate(original: dict, annotated: dict) -> bool:
    """True iff annotation touched ONLY the LLM fields. Used by swing_annotate before it writes."""
    return _numeric_fingerprint(original) == _numeric_fingerprint(annotated)


def write_brief(b: dict, log_dir: Optional[Path] = None) -> dict:
    log_dir = log_dir or LOG_DIR      # resolved at call time, not import time
    log_dir.mkdir(parents=True, exist_ok=True)
    jp, mp = log_dir / f"{b['date']}_brief.json", log_dir / f"{b['date']}_brief.md"
    jp.write_text(json.dumps(b, indent=2, default=str))
    mp.write_text(render_md(b))
    # sidecar the workflow gate reads: proves a proper post-close capture,
    # so a midday manual test never blocks the real evening run (auto_log lesson)
    try:
        import market_time as mt
        et_hour = mt.now_et().hour
    except Exception:
        et_hour = datetime.now(timezone.utc).hour - 4
    (log_dir / f"{b['date']}_brief.meta.json").write_text(json.dumps({"et_hour": et_hour, "generated_at": b["generated_at"]}))
    hist = log_dir / "cards_history.csv"
    rows = [{"date": b["date"], "ticker": c["ticker"], "setup": c["setup"], "side": c["side"],
             "confluence": c["confluence"], "entry": c["entry"], "stop": c["stop"], "close": c["close"],
             "regime": b["regime"]["key"], "entry_permitted": c["entry_permitted"],
             "block_reason": c["entry_block_reason"]} for c in b["cards"]]
    if rows:
        df = pd.DataFrame(rows)
        if hist.exists():
            old = pd.read_csv(hist)
            df = pd.concat([old[~((old["date"] == b["date"]))], df], ignore_index=True)
        df.to_csv(hist, index=False)
    return {"json": str(jp), "md": str(mp), "cards": len(rows)}


# ── Selftest: synthetic prices, synthetic bridges, temp storage ────────────

def selftest() -> dict:
    import tempfile
    f = []
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    global LOG_DIR
    LOG_DIR = Path(tmp) / "swing"
    import importlib, storage_backend; importlib.reload(storage_backend); importlib.reload(sj)
    sj.save_config(starting_equity=10_000.0)

    synth = {"XLE": swing_desk._synth("breakout", seed=2), "XOM": swing_desk._synth("breakout"),
             "CVX": swing_desk._synth("chop"), "NVDA": swing_desk._synth("parabolic"),
             "XLK": swing_desk._synth("chop", seed=4), "SPY": swing_desk._synth("chop", seed=5)}
    fetch = lambda tks, period="2y": {t: synth[t] for t in tks if t in synth}
    markets = {"available": True, "age_hours": 2.0, "regime": {"key": "goldilocks", "label": "Goldilocks", "drivers": ["test"]}}
    rotation = {"available": True, "sectors": [
        {"ticker": "XLE", "sector": "Energy", "quadrant": "Improving", "rotation_direction": "Strengthening", "accumulation_score": 60, "stealth_label": "Stealth"},
        {"ticker": "XLK", "sector": "Technology", "quadrant": "Lagging", "rotation_direction": "Weakening", "accumulation_score": -20}],
        "constituents": {"XLE": ["XOM", "CVX"], "XLK": ["NVDA"]}}
    no_earn = lambda tks: {}
    no_macro = lambda d: []

    b = build_brief(fetch, (markets, rotation), date(2026, 9, 14), no_earn, no_macro)
    tick = {c["ticker"]: c for c in b["cards"]}
    if b["exposure"]["step"] != 1 or b["exposure"]["equity"] != 10_000:
        f.append(f"fresh journal: step 1, equity 10k: {b['exposure']}")
    if "XOM" not in tick or tick["XOM"]["confluence"] != "3-of-3":
        f.append(f"XOM in an Improving+stealth sector on a volume breakout should be 3-of-3: {tick.get('XOM')}")
    if "NVDA" not in tick or tick["NVDA"]["side"] != "short":
        f.append("NVDA parabolic in a Lagging sector should surface as a short")
    if not any(a["ticker"] == "CVX" for a in b["avoid"]):
        f.append("CVX chop must be in avoid with a named reason")
    if any(c["shares"] > 0 and c["notional_pct"] and c["notional_pct"] > 30.5 for c in b["cards"]):
        f.append("concentration cap breached")
    # Sept 2026 regression: a trailing bar with NaN OHLC and Volume=0 (the
    # yfinance shape that blinded the desk from 09-14) must be cleaned away
    # and produce the same cards as clean data.
    def _nan_tail(d):
        extra = pd.DataFrame({c: [float("nan")] for c in d.columns}, index=[d.index[-1] + pd.Timedelta(days=1)])
        if "Volume" in extra.columns:
            extra["Volume"] = 0
        return pd.concat([d, extra])
    fetch_nan = lambda tks, period="2y": {t: _nan_tail(synth[t]) for t in tks if t in synth}
    bn = build_brief(fetch_nan, (markets, rotation), date(2026, 9, 14), no_earn, no_macro)
    if sorted((c["ticker"], c["setup"]) for c in bn["cards"]) != sorted((c["ticker"], c["setup"]) for c in b["cards"]):
        f.append(f"NaN-tail bar changed the cards: {[c['ticker'] for c in bn['cards']]} vs {[c['ticker'] for c in b['cards']]}")
    if not bn["data_health"]["nan_last_cleaned"] or bn["data_health"]["failed"]:
        f.append(f"NaN tail must be reported as cleaned, not failed: {bn['data_health']}")
    # half the tickers missing -> DATA FAILURE, never 'valid answer'
    half = {"XOM", "SPY"}
    fetch_half = lambda tks, period="2y": {t: synth[t] for t in tks if t in synth and t in half}
    bh = build_brief(fetch_half, (markets, rotation), date(2026, 9, 14), no_earn, no_macro)
    mdh = render_md(bh)
    if not bh["data_health"]["failed"] or not any("DATA FAILURE" in r for r in bh["refusals"]):
        f.append(f"missing prices must trigger DATA FAILURE: {bh['data_health']}")
    if any(c["entry_permitted"] for c in bh["cards"]) or "valid answer" in mdh:
        f.append("a data failure must block entries and must not render as 'valid answer'")
    # a name whose last bar is a day behind the rest is skipped, not scanned
    fetch_stale = lambda tks, period="2y": {t: (synth[t].iloc[:-1] if t == "CVX" else synth[t]) for t in tks if t in synth}
    bs = build_brief(fetch_stale, (markets, rotation), date(2026, 9, 14), no_earn, no_macro)
    if "CVX" not in bs["data_health"]["stale"] or not any(e["ticker"] == "CVX" and "stale" in e["error"] for e in bs["errors"]):
        f.append("stale-last-bar ticker must be named and skipped")
    # regime gate: growth_scare closes the long book
    b2 = build_brief(fetch, (dict(markets, regime={"key": "growth_scare", "label": "", "drivers": []}), rotation),
                     date(2026, 9, 14), no_earn, no_macro)
    if any(c["side"] == "long" for c in b2["cards"]):
        f.append("long card produced in growth_scare")
    if not any("long" in (w["reason"] or "").lower() and "closed" in (w["reason"] or "").lower() for w in b2["watch"]):
        f.append("refused long must be reported on the watch list with the regime named")
    # macro blackout blocks non-EP entries but keeps the card
    b3 = build_brief(fetch, (markets, rotation), date(2026, 9, 14), no_earn,
                     lambda d: [{"event": "FOMC", "days_away": 1, "blackout": True}])
    if any(c["entry_permitted"] for c in b3["cards"]):
        f.append("FOMC in 1d must block every non-EP entry")
    # slot cap: 4 max, and the 5th card is named as over-cap
    sj.save_config(max_positions=1)
    b4 = build_brief(fetch, (markets, rotation), date(2026, 9, 14), no_earn, no_macro)
    if sum(c["entry_permitted"] for c in b4["cards"]) > 1:
        f.append("slot cap not enforced")
    sj.save_config(max_positions=4)
    # open position management + pending carry-over
    sj.record_take("chat", "XOM", 80.0, 30, 77.0, setup="M2 Breakout", side="long", planned_entry=80,
                   regime="goldilocks", confluence="3-of-3", trail="10 EMA", card_date="2026-09-14")
    out = write_brief(b)
    b5 = build_brief(fetch, (markets, rotation), date(2026, 9, 15), no_earn, no_macro)
    if not b5["open_positions"] or b5["open_positions"][0]["ticker"] != "XOM":
        f.append("open XOM must be managed")
    if b5["exposure"]["open_count"] != 1 or b5["exposure"]["slots_open"] != 3:
        f.append(f"slots must reflect the journal: {b5['exposure']}")
    if not any(p["ticker"] == "NVDA" for p in b5["unconfirmed_from_prior"]):
        f.append("undecided NVDA card from 09-14 must carry over as UNCONFIRMED")
    # validator: annotation may touch only LLM fields
    ann = json.loads(json.dumps(b5)); ann["question_of_the_day"] = "x"; ann["cards"][0]["why_note"] = "y"
    if not validate(b5, ann):
        f.append("validator rejected a legal annotation")
    ann["cards"][0]["stop"] = 1.0
    if validate(b5, ann):
        f.append("validator accepted a changed stop")
    md = render_md(b5)
    if "Regime:" not in md or "XOM" not in md:
        f.append("render missing regime line or open position")
    if not Path(out["json"]).exists() or not (LOG_DIR / "cards_history.csv").exists():
        f.append("brief files not written")
    return {"ok": not f, "failures": f, "cards_day1": [(c["ticker"], c["setup"], c["confluence"], c["shares"]) for c in b["cards"]]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true"); ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        print(json.dumps(selftest(), indent=2, default=str)); sys.exit(0)
    b = build_brief()
    if a.dry:
        print(render_md(b))
    else:
        print(json.dumps(write_brief(b), indent=2))
        print(render_md(b))
