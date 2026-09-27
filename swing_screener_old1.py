"""
swing_screener.py  (v2 — September 2026: flow-signed hunting grounds)
────────────────────────────────────────
Money Flow as the DISCOVERY layer for the Swing Desk.

    Money Flow (Level 2)          this module              Swing Desk (Level 4)
    which sectors is money   ->   expand to ETF +    ->   which of those names
    rotating INTO / OUT OF        constituents             is at a pivot RIGHT NOW

WHY THIS IS THE RIGHT DIVISION OF LABOUR
  Rotation is a slower signal than a swing entry. The RRG says WHERE to hunt
  over weeks; it cannot say WHEN a specific stock is at a pivot today. That
  is exactly why rotation is ONE of three confluence legs in swing_desk, not
  the trigger. This module feeds the desk candidates whose rotation leg is
  already confirmed -- so every card that comes out is at minimum 1-of-3 by
  construction, and the desk's structure/volume detectors decide the rest.

THE CAVEAT THAT MATTERS MOST
  The stocks that MADE a sector hot are often already extended. The best
  swing candidates inside a rotating-in sector are usually the leaders on a
  pullback to the 10/20 EMA, or the laggards catching up -- not the name
  that already ran 40%. swing_desk handles this: the breakout detector
  REQUIRES a consolidation, and the parabolic detector flags the extended
  names as SHORT candidates rather than longs. This module does not need to
  second-guess that; it just has to feed the right sectors.

DIRECTION  (v2: the flow sign is ENFORCED, not just documented)
  Rotating IN  (Improving / Leading, accumulation > 0)  -> long hunting ground
  Rotating OUT (Weakening / Lagging, accumulation < 0)  -> short hunting ground
  Price quadrant and flow sign DISAGREE (e.g. Leading with accumulation -43)
      -> WATCH ground: scanned so you can see the setups, but no card from it
         is entry-eligible until money confirms the price rotation.
  A long card whose parent sector is a SHORT ground (or vice versa) is
  demoted to watch -- trading against your own hunting-ground read is the
  "Level-4 setup in a hostile Level-2" trap. See ground_gate().
  Improving outranks Leading for longs -- it is the earliest, highest-alpha
  quadrant, and Money Flow's own priority ranking gives it base score 10.
"""

from __future__ import annotations

from typing import Callable, Optional

LONG_QUADS = ("Improving", "Leading")
SHORT_QUADS = ("Weakening", "Lagging")
QUAD_PRIORITY = {"Improving": 0, "Leading": 1, "Weakening": 2, "Lagging": 3}


def _acc(r) -> Optional[float]:
    v = r.get("accumulation_score")
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def select_sectors(rotation: dict, max_long: int = 3, max_short: int = 2) -> dict:
    """
    From the rotation_bridge summary, pick the sectors money is rotating
    into (long hunting grounds) and out of (short hunting grounds).

    v2: a ground needs BOTH the price quadrant and the flow sign.
      long        Improving/Leading AND accumulation > 0
      short       Weakening/Lagging AND accumulation < 0
      long_watch  Improving/Leading but accumulation <= 0 or missing
                  ("price rotating in, money not")
      short_watch Weakening/Lagging but accumulation >= 0 or missing
                  ("price rotating out, money not leaving")

    Returns {"long", "short", "long_watch", "short_watch": [sector rows],
             "reasons": [...], "available": bool}. Watch rows carry a
    "watch_reason" string.
    """
    out = {"long": [], "short": [], "long_watch": [], "short_watch": [],
           "reasons": [], "available": False}
    if not rotation or not rotation.get("available"):
        out["reasons"].append("Money Flow bridge unavailable — no discovery possible. "
                              "Open the Money Flow dashboard once to publish.")
        return out
    if rotation.get("very_stale"):
        out["reasons"].append(f"Money Flow summary is very stale ({rotation.get('message','')}). "
                              "Rotation read may not reflect current money movement.")
    rows = [r for r in rotation.get("sectors", []) if isinstance(r, dict) and r.get("ticker")]
    if not rows:
        out["reasons"].append("Bridge published no sector rows.")
        return out
    out["available"] = True

    def _a0(r):
        a = _acc(r)
        return 0.0 if a is None else a

    longs, shorts, lw, sw = [], [], [], []
    for r in rows:
        q, a = r.get("quadrant"), _acc(r)
        if q in LONG_QUADS:
            if a is not None and a > 0:
                longs.append(r)
            else:
                lw.append(dict(r, watch_reason=(
                    "price rotating in, money not (accumulation "
                    + ("missing" if a is None else f"{a:g}") + ")")))
        elif q in SHORT_QUADS:
            if a is not None and a < 0:
                shorts.append(r)
            else:
                sw.append(dict(r, watch_reason=(
                    "price rotating out, money not leaving (accumulation "
                    + ("missing" if a is None else f"{a:g}") + ")")))
    # Improving first, then by accumulation strength; stealth is a tiebreak
    longs.sort(key=lambda r: (QUAD_PRIORITY.get(r.get("quadrant"), 9), -_a0(r),
                              0 if r.get("stealth_label") else 1))
    shorts.sort(key=lambda r: (-QUAD_PRIORITY.get(r.get("quadrant"), 0), _a0(r)))
    lw.sort(key=lambda r: (QUAD_PRIORITY.get(r.get("quadrant"), 9), -_a0(r)))
    sw.sort(key=lambda r: (-QUAD_PRIORITY.get(r.get("quadrant"), 0), _a0(r)))
    out["long"] = longs[:max_long]
    out["short"] = shorts[:max_short]
    out["long_watch"] = lw[:max_long]
    out["short_watch"] = sw[:max_short]
    if all(_acc(r) is None for r in rows):
        out["reasons"].append("Bridge published no accumulation scores — flow cannot confirm any ground, "
                              "so every rotating sector is watch-only until Money Flow republishes.")
    if not out["long"]:
        out["reasons"].append("No sector is Improving/Leading WITH positive accumulation — no long hunting ground"
                              + (f" ({len(lw)} price-only on watch)" if lw else "")
                              + ". That is a valid answer, not a gap.")
    if not out["short"]:
        out["reasons"].append("No sector is Weakening/Lagging with distribution (negative accumulation).")
    return out


GROUND_SIDES = ("long", "short", "long_watch", "short_watch")
# merge order for overlapping tickers: later wins (confirmed beats watch, long beats short)
GROUND_MERGE_ORDER = ("short_watch", "long_watch", "short", "long")


def expand_candidates(selected: dict, constituents: dict,
                      include_etf: bool = True, top_n: int = 10) -> dict:
    """
    Sector rows -> concrete tickers. Each candidate carries its parent
    sector's quadrant so the desk's rotation leg is populated automatically,
    and a "ground" tag (long / short / long_watch / short_watch) that
    ground_gate() uses to decide whether a card from it may be traded.

    Returns {"long": {ticker: meta}, "short": {...}, "long_watch": {...}, "short_watch": {...}}
    """
    out = {g: {} for g in GROUND_SIDES}
    for side in GROUND_SIDES:
        for sec in selected.get(side, []):
            etf = sec["ticker"]
            meta = {"sector": etf, "quadrant": sec.get("quadrant"),
                    "accumulation_score": sec.get("accumulation_score"),
                    "stealth": sec.get("stealth_label"), "tier_a": False,
                    "ground": side, "ground_reason": sec.get("watch_reason")}
            if include_etf:
                out[side][etf] = dict(meta, is_etf=True)
            for tk in (constituents.get(etf) or [])[:top_n]:
                out[side].setdefault(tk, dict(meta, is_etf=False))
    return out


def merged_meta(cands: dict) -> dict:
    """All candidates in one dict; confirmed grounds win over watch grounds on overlap."""
    m = {}
    for g in GROUND_MERGE_ORDER:
        m.update(cands.get(g, {}))
    return m


def ground_gate(side: Optional[str], meta: dict) -> tuple:
    """
    May a card on `side` ("long"/"short") be traded given where it came from?
    Returns (ok, reason). Tickers with no ground (watchlist-origin) pass --
    their rotation leg is judged by swing_desk as before.
    """
    g = (meta or {}).get("ground")
    if g is None or side not in ("long", "short"):
        return True, None
    sec, acc = meta.get("sector"), meta.get("accumulation_score")
    acc_s = "missing" if acc is None else f"{acc:g}" if isinstance(acc, (int, float)) else str(acc)
    opposite = "short" if side == "long" else "long"
    if g in (opposite, opposite + "_watch"):
        return False, (f"{side} card from a {opposite} hunting ground ({sec} {meta.get('quadrant')}, "
                       f"accumulation {acc_s}) — the setup fights the sector rotation; watch only")
    if g.endswith("_watch"):
        return False, (f"flow does not confirm the ground: {sec} {meta.get('quadrant')} — "
                       f"{meta.get('ground_reason') or f'price and money disagree (accumulation {acc_s})'}; "
                       f"watch until accumulation turns {'positive' if side == 'long' else 'negative'}")
    return True, None


def screen(rotation: dict, regime_key: str, fetch_ohlcv: Callable, scan_fn: Callable,
           bench=None, max_long: int = 3, max_short: int = 2, top_n: int = 10,
           tier_a_confirmed: Optional[set] = None, **desk_kw) -> dict:
    """
    End-to-end: rotation summary -> sectors -> candidates -> swing_desk.scan.

    The desk's regime gate still governs direction. If the regime says the
    long book is closed, long candidates from rotating-in sectors are STILL
    evaluated -- and refused with the regime named -- so you can see what
    you would be trading if the regime unlocked. Nothing is hidden.
    """
    sel = select_sectors(rotation, max_long, max_short)
    cands = expand_candidates(sel, rotation.get("constituents", {}), top_n=top_n)
    tier_a = tier_a_confirmed or set()

    all_meta = merged_meta(cands)   # confirmed beats watch, long beats short
    tickers = list(all_meta)
    if not tickers:
        return {"selected": sel, "candidates": cands, "scan": None,
                "message": " ".join(sel["reasons"]) or "No candidates."}

    ohlcv = fetch_ohlcv(tickers + (["SPY"] if bench is None else []))
    if bench is None:
        b = ohlcv.get("SPY")
        bench = b["Close"] if b is not None and not b.empty else None

    # Per-ticker quadrant + Tier A into the desk -- the rotation leg is now
    # sourced from Money Flow, not typed in.
    results = {"cards": [], "watch": [], "avoid": [], "errors": [], "regime": regime_key}
    for tk in tickers:
        df = ohlcv.get(tk)
        if df is None or len(df) < 60:
            results["errors"].append((tk, "insufficient history")); continue
        m = all_meta[tk]
        try:
            r = scan_fn(tk, df, regime_key, bench=bench, sector_quadrant=m["quadrant"],
                        tier_a_confirmed=(tk in tier_a) or bool(m.get("stealth")), **desk_kw)
            r["sector"] = m["sector"]; r["sector_quadrant"] = m["quadrant"]
            r["is_etf"] = m["is_etf"]; r["accumulation_score"] = m["accumulation_score"]
            r["ground"] = m.get("ground")
            if r["card"]:
                ok, why = ground_gate(r["card"].get("side") or r.get("side"), m)
                if not ok:
                    r["ground_block"] = why
                    results["watch"].append(r); continue
            (results["cards"] if r["card"] else results["avoid"]).append(r)
        except Exception as e:
            results["errors"].append((tk, f"{type(e).__name__}: {e}"))
    results["cards"].sort(key=lambda r: (-r["confluence"]["score"],
                                          QUAD_PRIORITY.get(r["sector_quadrant"], 9),
                                          r["card"]["stop_pct"]))
    from swing_desk import REGIME_DIRECTION
    results["direction"] = REGIME_DIRECTION.get(regime_key, ("both", 0.5))[0]
    return {"selected": sel, "candidates": cands, "scan": results,
            "message": " ".join(sel["reasons"])}


def render_selection(st, sel: dict, cands: dict):
    """The 'where money is moving' header above the desk's cards."""
    if not sel.get("available"):
        st.warning(" ".join(sel.get("reasons", [])) or "Money Flow unavailable.")
        return

    def _n(side, etf):
        return sum(1 for m in cands.get(side, {}).values() if m["sector"] == etf and not m["is_etf"])

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🟢 Rotating IN — long hunting grounds** (price + money)")
        for s in sel["long"]:
            st.caption(f"{s['ticker']} · {s.get('quadrant')} · acc {s.get('accumulation_score','?')}"
                       f"{' · 🔍 stealth' if s.get('stealth_label') else ''} · {_n('long', s['ticker'])} constituents")
        for s in sel.get("long_watch", []):
            st.caption(f"👁 {s['ticker']} · {s.get('quadrant')} · watch — {s.get('watch_reason')}")
    with c2:
        st.markdown("**🔴 Rotating OUT — short hunting grounds** (price + money)")
        for s in sel["short"]:
            st.caption(f"{s['ticker']} · {s.get('quadrant')} · acc {s.get('accumulation_score','?')} · "
                       f"{_n('short', s['ticker'])} constituents")
        for s in sel.get("short_watch", []):
            st.caption(f"👁 {s['ticker']} · {s.get('quadrant')} · watch — {s.get('watch_reason')}")
    for r in sel.get("reasons", []):
        st.caption(f"ℹ {r}")


def selftest() -> dict:
    f = []
    rot = {"available": True, "very_stale": False, "sectors": [
        {"ticker": "XLE", "quadrant": "Improving", "accumulation_score": 0.6, "stealth_label": "STEALTH"},
        {"ticker": "XLF", "quadrant": "Leading", "accumulation_score": 0.4},
        {"ticker": "XLK", "quadrant": "Weakening", "accumulation_score": -0.3},
        {"ticker": "XLU", "quadrant": "Lagging", "accumulation_score": -0.5},
        {"ticker": "XLV", "quadrant": "Leading", "accumulation_score": 0.9},
    ], "constituents": {"XLE": ["XOM", "CVX"], "XLF": ["JPM"], "XLK": ["NVDA"], "XLU": ["NEE"], "XLV": ["LLY"]}}
    sel = select_sectors(rot)
    if [s["ticker"] for s in sel["long"]] != ["XLE", "XLV", "XLF"]:
        f.append(f"Improving must outrank Leading, then by accumulation: got {[s['ticker'] for s in sel['long']]}")
    if [s["ticker"] for s in sel["short"]] != ["XLU", "XLK"]:
        f.append(f"Lagging+most-negative first for shorts: got {[s['ticker'] for s in sel['short']]}")
    c = expand_candidates(sel, rot["constituents"])
    if "XOM" not in c["long"] or c["long"]["XOM"]["quadrant"] != "Improving":
        f.append("constituent must inherit parent sector quadrant")
    if "XLE" not in c["long"] or not c["long"]["XLE"]["is_etf"]:
        f.append("sector ETF itself must be a candidate")
    if "NEE" not in c["short"]:
        f.append("rotating-out constituents must be short candidates")
    # v2: flow sign enforced
    rot2 = {"available": True, "sectors": [
        {"ticker": "XLK", "quadrant": "Leading", "accumulation_score": 50},
        {"ticker": "XLF", "quadrant": "Leading", "accumulation_score": -43},
        {"ticker": "XLC", "quadrant": "Improving", "accumulation_score": -40},
        {"ticker": "XLB", "quadrant": "Weakening", "accumulation_score": -12},
        {"ticker": "XLP", "quadrant": "Lagging", "accumulation_score": 15},
        {"ticker": "XLRE", "quadrant": "Improving"},
    ], "constituents": {"XLK": ["NVDA"], "XLF": ["JPM"], "XLC": ["META"], "XLB": ["NUE"], "XLP": ["PG"]}}
    s2 = select_sectors(rot2, max_long=5, max_short=3)
    if [x["ticker"] for x in s2["long"]] != ["XLK"]:
        f.append(f"only positive-accumulation long quadrants are long grounds: {[x['ticker'] for x in s2['long']]}")
    if sorted(x["ticker"] for x in s2["long_watch"]) != ["XLC", "XLF", "XLRE"]:
        f.append(f"Leading/Improving with acc<=0 or missing must be long_watch: {[x['ticker'] for x in s2['long_watch']]}")
    if [x["ticker"] for x in s2["short"]] != ["XLB"] or [x["ticker"] for x in s2["short_watch"]] != ["XLP"]:
        f.append(f"short grounds need negative acc: short={[x['ticker'] for x in s2['short']]} "
                 f"watch={[x['ticker'] for x in s2['short_watch']]}")
    c2 = expand_candidates(s2, rot2["constituents"])
    mm = merged_meta(c2)
    if not ground_gate("long", mm["NVDA"])[0]:
        f.append("NVDA long from XLK (Leading, +50) must be allowed")
    ok, why = ground_gate("long", mm["NUE"])
    if ok or "short hunting ground" not in why:
        f.append(f"NUE long from XLB short ground must be blocked: {why}")
    ok, why = ground_gate("long", mm["JPM"])
    if ok or "flow does not confirm" not in why or "-43" not in why:
        f.append(f"JPM long from XLF (Leading, acc -43) must be watch with the acc named: {why}")
    if ground_gate("short", mm["NVDA"])[0]:
        f.append("short card from a long ground must be blocked")
    if not ground_gate("short", mm["NUE"])[0]:
        f.append("short card from a short ground must be allowed")
    if not ground_gate("long", {"sector": "XLK", "quadrant": "Leading"})[0]:
        f.append("watchlist-origin ticker (no ground) must pass the gate")
    empty = select_sectors({"available": False})
    if empty["available"] or not empty["reasons"]:
        f.append("unavailable bridge must fail loudly")
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2))
