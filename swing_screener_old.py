"""
swing_screener.py  (v1 — September 2026)
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

DIRECTION
  Rotating IN  (Improving / Leading, accumulation > 0)  -> long candidates
  Rotating OUT (Weakening / Lagging, accumulation < 0)  -> short candidates
  Improving outranks Leading for longs -- it is the earliest, highest-alpha
  quadrant, and Money Flow's own priority ranking gives it base score 10.
"""

from __future__ import annotations

from typing import Callable, Optional

LONG_QUADS = ("Improving", "Leading")
SHORT_QUADS = ("Weakening", "Lagging")
QUAD_PRIORITY = {"Improving": 0, "Leading": 1, "Weakening": 2, "Lagging": 3}


def select_sectors(rotation: dict, max_long: int = 3, max_short: int = 2) -> dict:
    """
    From the rotation_bridge summary, pick the sectors money is rotating
    into (long hunting grounds) and out of (short hunting grounds).

    Returns {"long": [sector rows], "short": [sector rows], "reasons": [...]}
    with each row carrying its quadrant, accumulation score and stealth flag
    so the desk can populate the rotation confluence leg directly.
    """
    out = {"long": [], "short": [], "reasons": [], "available": False}
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

    def _acc(r):
        v = r.get("accumulation_score")
        return float(v) if v is not None else 0.0

    longs = [r for r in rows if r.get("quadrant") in LONG_QUADS]
    shorts = [r for r in rows if r.get("quadrant") in SHORT_QUADS]
    # Improving first, then by accumulation strength; stealth is a tiebreak
    longs.sort(key=lambda r: (QUAD_PRIORITY.get(r.get("quadrant"), 9), -_acc(r),
                              0 if r.get("stealth_label") else 1))
    shorts.sort(key=lambda r: (-QUAD_PRIORITY.get(r.get("quadrant"), 0), _acc(r)))
    out["long"] = longs[:max_long]
    out["short"] = shorts[:max_short]
    if not out["long"]:
        out["reasons"].append("No sector is Improving or Leading — no long hunting ground. "
                              "That is a valid answer, not a gap.")
    if not out["short"]:
        out["reasons"].append("No sector is Weakening or Lagging with distribution.")
    return out


def expand_candidates(selected: dict, constituents: dict,
                      include_etf: bool = True, top_n: int = 10) -> dict:
    """
    Sector rows -> concrete tickers. Each candidate carries its parent
    sector's quadrant so the desk's rotation leg is populated automatically.

    Returns {"long": {ticker: meta}, "short": {ticker: meta}}
    """
    out = {"long": {}, "short": {}}
    for side in ("long", "short"):
        for sec in selected.get(side, []):
            etf = sec["ticker"]
            meta = {"sector": etf, "quadrant": sec.get("quadrant"),
                    "accumulation_score": sec.get("accumulation_score"),
                    "stealth": sec.get("stealth_label"), "tier_a": False}
            if include_etf:
                out[side][etf] = dict(meta, is_etf=True)
            for tk in (constituents.get(etf) or [])[:top_n]:
                out[side].setdefault(tk, dict(meta, is_etf=False))
    return out


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

    all_meta = {**cands["short"], **cands["long"]}   # long wins on overlap
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
    results = {"cards": [], "avoid": [], "errors": [], "regime": regime_key}
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
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🟢 Rotating IN — long hunting grounds**")
        for s in sel["long"]:
            n = sum(1 for m in cands["long"].values() if m["sector"] == s["ticker"] and not m["is_etf"])
            st.caption(f"{s['ticker']} · {s.get('quadrant')} · acc {s.get('accumulation_score','?')}"
                       f"{' · 🔍 stealth' if s.get('stealth_label') else ''} · {n} constituents")
    with c2:
        st.markdown("**🔴 Rotating OUT — short hunting grounds**")
        for s in sel["short"]:
            n = sum(1 for m in cands["short"].values() if m["sector"] == s["ticker"] and not m["is_etf"])
            st.caption(f"{s['ticker']} · {s.get('quadrant')} · acc {s.get('accumulation_score','?')} · {n} constituents")
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
    empty = select_sectors({"available": False})
    if empty["available"] or not empty["reasons"]:
        f.append("unavailable bridge must fail loudly")
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2))
