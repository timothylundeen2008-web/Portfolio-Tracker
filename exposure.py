"""
exposure.py  (v1 — August 2026)
───────────────────────────────
What is this portfolio ACTUALLY exposed to, after look-through and leverage?

THE PROBLEM THIS SOLVES
───────────────────────
A ticker is not its label, and a position count is not diversification.

    VOO   ~33% tech
    QQQ   ~50% tech
    SCHG  ~45% tech
    VGT  ~100% tech
    TQQQ  3x a ~50%-tech index = ~150% tech PER DOLLAR HELD

A portfolio holding all five looks like five diversified positions in a pie
chart. Its actual tech exposure can exceed 60% of the book. That gap between
what the position list SAYS and what the portfolio IS is the single most
common way a "diversified" allocation turns out to be one concentrated bet
in a drawdown.

This is the same failure factor_exposure.py measures statistically via
effective bets (N / (1 + (N-1)·rho)). This module measures it structurally
via published fund composition -- the two are complementary, and they should
broadly agree. When they disagree sharply, trust the correlation-based one:
it measures actual co-movement rather than stated holdings.

LEVERAGE IS COUNTED AT FULL NOTIONAL, DELIBERATELY
──────────────────────────────────────────────────
A 5% position in TQQQ is not 5% of risk -- it carries roughly 15% of
notional equity exposure and moves accordingly. Reporting it as 5% would
understate the book's real risk by a factor of three, which is precisely
the error that makes leveraged products dangerous in an otherwise
disciplined portfolio. Both figures are reported: capital deployed AND
effective notional.

⚠ Sector weights are approximate and drift -- see candidate_universe.py.
Good for concentration warnings, not for precise risk modelling.
"""

from __future__ import annotations

from typing import Optional

try:
    from candidate_universe import UNIVERSE, leverage_of, is_leveraged
except Exception:  # module used standalone / in tests
    UNIVERSE, leverage_of, is_leveraged = {}, lambda t: 1.0, lambda t: False

# Concentration thresholds. Deliberately conservative -- these are WARNINGS
# to surface a fact, not blocks. The framework's own valuation guard already
# uses 45% top-20 concentration as an index-level red line; a single SECTOR
# above 40% of a whole portfolio is a comparable degree of single-theme risk.
SECTOR_WARN_PCT = 30.0
SECTOR_CRITICAL_PCT = 40.0
LEVERAGE_NOTIONAL_WARN = 115.0   # gross notional as % of capital


def compute(weights: dict) -> dict:
    """
    Look-through exposure for a {ticker: weight_pct} dict.

    Returns capital-weighted AND leverage-adjusted (notional) sector
    exposure, plus concentration findings. Tickers absent from UNIVERSE are
    named in `unmapped` and excluded rather than silently assumed to be
    anything -- an unmapped ticker's exposure is unknown, not zero.
    """
    out = {"sectors_capital": {}, "sectors_notional": {}, "unmapped": [],
           "total_capital": 0.0, "total_notional": 0.0,
           "leveraged_positions": {}, "findings": [], "available": False}

    cap, notional = {}, {}
    for tk, w in (weights or {}).items():
        if not w:
            continue
        meta = UNIVERSE.get(tk)
        if not meta:
            out["unmapped"].append(tk)
            continue
        lev = meta.get("leverage", 1.0)
        out["total_capital"] += w
        out["total_notional"] += w * lev
        if lev > 1.0:
            out["leveraged_positions"][tk] = {
                "capital_pct": round(w, 2), "leverage": lev,
                "notional_pct": round(w * lev, 2)}
        for sec, frac in meta["sectors"].items():
            cap[sec] = cap.get(sec, 0.0) + w * frac
            notional[sec] = notional.get(sec, 0.0) + w * frac * lev

    if not cap:
        out["findings"].append(
            "No mapped positions — exposure cannot be computed."
            + (f" Unmapped: {', '.join(out['unmapped'])}." if out["unmapped"] else ""))
        return out

    out["available"] = True
    out["sectors_capital"] = {k: round(v, 2) for k, v in
                              sorted(cap.items(), key=lambda kv: -kv[1])}
    out["sectors_notional"] = {k: round(v, 2) for k, v in
                               sorted(notional.items(), key=lambda kv: -kv[1])}
    out["total_capital"] = round(out["total_capital"], 2)
    out["total_notional"] = round(out["total_notional"], 2)

    # ── Findings ────────────────────────────────────────────────────────────
    for sec, pct in out["sectors_notional"].items():
        if pct >= SECTOR_CRITICAL_PCT:
            contributors = sorted(
                [(tk, round(weights[tk] * UNIVERSE[tk]["sectors"].get(sec, 0)
                            * leverage_of(tk), 1))
                 for tk in weights
                 if tk in UNIVERSE and UNIVERSE[tk]["sectors"].get(sec)],
                key=lambda kv: -kv[1])[:4]
            out["findings"].append({
                "severity": "CRITICAL", "sector": sec, "pct": pct,
                "message": (f"{sec.upper()} is {pct:.0f}% of notional exposure "
                           f"— above the {SECTOR_CRITICAL_PCT:.0f}% "
                           f"single-theme line. This book is concentrated "
                           f"regardless of how many tickers it holds."),
                "contributors": contributors})
        elif pct >= SECTOR_WARN_PCT:
            out["findings"].append({
                "severity": "WARNING", "sector": sec, "pct": pct,
                "message": (f"{sec.upper()} is {pct:.0f}% of notional "
                           f"exposure — worth knowing before adding more of "
                           f"the same theme."),
                "contributors": []})

    if out["total_notional"] > LEVERAGE_NOTIONAL_WARN:
        out["findings"].append({
            "severity": "CRITICAL", "sector": "_leverage",
            "pct": out["total_notional"],
            "message": (f"Gross notional is {out['total_notional']:.0f}% of "
                       f"capital ({out['total_capital']:.0f}% deployed) — the "
                       f"book is effectively levered "
                       f"{out['total_notional']/max(out['total_capital'],1):.2f}x "
                       f"via leveraged ETFs. A -20% move in the underlying "
                       f"becomes roughly "
                       f"{-20*out['total_notional']/max(out['total_capital'],1):.0f}% "
                       f"here."),
            "contributors": [(tk, v["notional_pct"]) for tk, v
                            in out["leveraged_positions"].items()]})

    if out["unmapped"]:
        out["findings"].append({
            "severity": "INFO", "sector": "_unmapped", "pct": 0,
            "message": (f"Not in the universe map, excluded from exposure: "
                       f"{', '.join(out['unmapped'])}. Their exposure is "
                       f"UNKNOWN, not zero."),
            "contributors": []})
    return out


def compare(before: dict, after: dict) -> dict:
    """Exposure delta between two weight sets — for previewing a suggested change."""
    b, a = compute(before), compute(after)
    if not (b["available"] and a["available"]):
        return {"available": False,
                "detail": "Need both weight sets mapped to compare."}
    secs = set(b["sectors_notional"]) | set(a["sectors_notional"])
    deltas = {s: round(a["sectors_notional"].get(s, 0)
                       - b["sectors_notional"].get(s, 0), 2) for s in secs}
    return {"available": True,
            "deltas": {k: v for k, v in
                      sorted(deltas.items(), key=lambda kv: -abs(kv[1])) if v},
            "notional_before": b["total_notional"],
            "notional_after": a["total_notional"],
            "before": b, "after": a}


def render(st, exp: dict, title: str = "Look-through exposure"):
    """Render the exposure panel."""
    st.markdown(f"##### {title}")
    if not exp.get("available"):
        st.caption(exp["findings"][0] if exp.get("findings")
                   else "Exposure unavailable.")
        return

    c1, c2 = st.columns(2)
    c1.metric("Capital deployed", f"{exp['total_capital']:.0f}%")
    c2.metric("Gross notional", f"{exp['total_notional']:.0f}%",
              delta=(f"{exp['total_notional'] - exp['total_capital']:+.0f}% "
                     f"from leverage")
              if exp["total_notional"] > exp["total_capital"] + 0.5 else None,
              help="Leveraged positions counted at FULL notional. A 5% TQQQ "
                   "position carries ~15% of equity exposure and moves "
                   "accordingly — reporting it as 5% would understate real "
                   "risk threefold.")

    for f in exp.get("findings", []):
        if isinstance(f, str):
            st.caption(f)
            continue
        box = (st.error if f["severity"] == "CRITICAL"
               else st.warning if f["severity"] == "WARNING" else st.info)
        box(f["message"])
        if f.get("contributors"):
            st.caption("Driven by: " + " · ".join(
                f"{tk} ({pct:.1f}%)" for tk, pct in f["contributors"]))

    st.markdown("**Notional sector exposure**")
    rows = [{"Sector": s.replace("_", " ").title(),
             "Capital %": exp["sectors_capital"].get(s, 0),
             "Notional %": v}
            for s, v in exp["sectors_notional"].items() if v >= 0.5]
    if rows:
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                    hide_index=True)
    st.caption(
        "⚠ Sector splits are APPROXIMATE published fund compositions and "
        "drift as indices rebalance — good for concentration warnings, not "
        "precise risk modelling. Cross-check against the Markets Dashboard's "
        "Factor Exposure tab, which measures actual co-movement rather than "
        "stated holdings; when the two disagree sharply, trust that one."
    )


def selftest() -> dict:
    failures = []
    global UNIVERSE
    if not UNIVERSE:
        return {"ok": False, "failures": ["candidate_universe not importable"]}

    # The exact scenario this module exists for: five "diversified" tickers,
    # one enormous tech bet.
    hidden = {"VOO": 20, "QQQ": 15, "SCHG": 15, "VGT": 10, "SCHD": 10,
              "SGOV": 30}
    e = compute(hidden)
    tech = e["sectors_notional"].get("tech", 0)
    if tech < 25:
        failures.append(f"expected material hidden tech exposure, got {tech}%")
    if not any(isinstance(f, dict) and f.get("sector") == "tech"
               for f in e["findings"]):
        failures.append("no tech concentration finding raised")

    # Leverage must be counted at full notional
    lev = {"TQQQ": 10, "SGOV": 90}
    el = compute(lev)
    if abs(el["total_notional"] - 120.0) > 0.5:
        failures.append(f"notional {el['total_notional']}, expected 120 "
                        f"(10% x 3 + 90%)")
    if "TQQQ" not in el["leveraged_positions"]:
        failures.append("leveraged position not tracked")

    # Unmapped must not be silently zeroed
    u = compute({"VOO": 50, "FAKE": 50})
    if "FAKE" not in u["unmapped"]:
        failures.append("unmapped ticker not reported")

    # Comparison
    cmp = compare({"VGT": 20, "SGOV": 80}, {"VOO": 20, "SGOV": 80})
    if not cmp["available"] or cmp["deltas"].get("tech", 0) >= 0:
        failures.append("swapping VGT->VOO should REDUCE tech exposure")

    return {"ok": not failures, "failures": failures,
            "hidden_tech_pct": tech,
            "levered_notional": el["total_notional"]}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2, default=str))
