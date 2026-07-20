"""
repression_regime_section.py
===========================
Drop-in Streamlit section for the Repression Dashboard.

INTEGRATION (3 lines in your existing app.py):

    from repression_regime_section import render_regime_section
    # ... inside the tab where you want it (e.g. a new "Regime" tab):
    with tab_regime:
        render_regime_section(FRED_API_KEY, fetch_fred=_fetch_fred_inline)

If you pass your own `fetch_fred` (your app's `_fetch_fred_inline`) and
`fetch_prices`, the section uses them; otherwise it falls back to the inline
fetchers in regime_classifier.py.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import regime_classifier as rc

try:
    from historical_episodes import render_historical_panel
    _HIST_OK = True
except Exception:
    _HIST_OK = False

_REGIME_COLOR = {
    "inflationary_repression": "#c026d3",
    "liquidity_crisis": "#dc2626",
    "stagflation": "#d97706",
    "goldilocks": "#16a34a",
    "neutral": "#6b7280",
}


def _arrow(x):
    if x is None:
        return "—"
    if x > 0.02:
        return "▲ rising"
    if x < -0.02:
        return "▼ falling"
    return "► flat"


def _fmt(x, suffix="%"):
    return "n/a" if x is None else f"{x:+.2f}{suffix}"


def render_regime_section(fred_api_key: str = "",
                          fetch_fred=None, fetch_prices=None,
                          start: str = "2015-01-01"):
    st.subheader("🌡️ Regime Classifier — the two real yields")
    st.caption(
        "Repression is a *front-end* phenomenon. This panel separates the two "
        "real yields that most dashboards wrongly merge into one."
    )

    kw = {"start": start}
    if fetch_fred is not None:
        kw["fetch_fred"] = fetch_fred
    if fetch_prices is not None:
        kw["fetch_prices"] = fetch_prices

    with st.spinner("Computing regime signals…"):
        out = rc.full_assessment(fred_api_key, **kw)

    sig, regime, fed = out["signals"], out["regime"], out["fed"]

    # ---- Headline regime banner ----
    color = _REGIME_COLOR.get(regime["key"], "#6b7280")
    st.markdown(
        f"<div style='padding:14px 18px;border-radius:10px;"
        f"background:{color}22;border-left:6px solid {color};'>"
        f"<span style='font-size:1.35rem;font-weight:700;color:{color};'>"
        f"{regime['label']}</span><br>"
        f"<span style='color:#374151;'>{regime['blurb']}</span></div>",
        unsafe_allow_html=True,
    )
    if regime["drivers"]:
        st.markdown("**Why:** " + " · ".join(regime["drivers"]))

    # ---- The two real yields, side by side ----
    st.markdown("#### The two real yields (never conflate these)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "SHORT real policy rate", _fmt(sig.short_real_rate),
        help="EFFR − CPI YoY. THE repression gauge. Negative = savers "
             "penalized at the front end.",
    )
    c1.caption("EFFR − CPI YoY")
    c2.metric(
        "LONG real yield (10y)", _fmt(sig.long_real_yield),
        delta=_arrow(sig.long_real_mom_3m),
        help="DFII10 (10y TIPS). Duration friend/foe. Positive & RISING = "
             "long duration bleeds; do NOT add TLT.",
    )
    c2.caption("DFII10 · 3-month momentum")
    c3.metric("HY credit OAS", _fmt(sig.hy_oas), delta=_arrow(sig.hy_oas_mom_2w))
    c3.caption(">500 bps & rising ⇒ crisis override")
    c4.metric(
        "Stock/bond 60d corr",
        "n/a" if sig.stock_bond_corr_60d is None
        else f"{sig.stock_bond_corr_60d:+.2f}",
        help="Positive ⇒ 60/40 breaking ⇒ increase KMLM.",
    )
    c4.caption("KMLM sizing signal")

    # ---- Fed reaction function flag ----
    st.markdown(
        f"**Fed reaction function:** `{fed['state']}` — {fed['detail']}"
    )

    # ---- Two-real-yield history chart ----
    _real_yield_chart(fred_api_key, kw)

    # ---- Quadrant map ----
    with st.expander("📐 The 4-regime quadrant map & target tilts"):
        _quadrant_table(regime["key"])

    # ---- KMLM signal ----
    kml = out["kmlm"]
    st.markdown(f"#### Trend / KMLM signal: **{kml['stance']}** "
                f"(score {kml['score']})")
    for r in kml["reasons"]:
        st.markdown(f"- {r}")
    st.info("**Funding:** " + kml["funding"])

    # ---- Historical episode context ----
    if _HIST_OK:
        st.markdown("---")
        render_historical_panel(st)

    st.caption(
        "Data hygiene: if a CPI release is missing (e.g. a government-services "
        "suspension), substitute the Cleveland Fed inflation nowcast so the "
        "short-real-rate signal never goes stale."
    )
    return out


def _real_yield_chart(fred_api_key, kw):
    fetch = kw.get("fetch_fred", rc._inline_fetch_fred)
    start = kw.get("start", "2015-01-01")
    r10 = fetch(rc.FRED_SERIES["real_10y"], fred_api_key, start)
    be = fetch(rc.FRED_SERIES["breakeven_10y"], fred_api_key, start)
    if (r10 is None or r10.empty):
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=r10.index, y=r10.values,
                             name="10y real yield (DFII10)",
                             line=dict(color="#2563eb", width=2)))
    if be is not None and not be.empty:
        fig.add_trace(go.Scatter(x=be.index, y=be.values,
                                 name="10y breakeven (T10YIE)",
                                 line=dict(color="#f59e0b", width=1.5,
                                           dash="dot")))
    fig.add_hline(y=0, line_dash="dash", line_color="#9ca3af")
    fig.update_layout(
        height=320, margin=dict(l=10, r=10, t=30, b=10),
        title="Long real yield vs. breakeven inflation",
        legend=dict(orientation="h", y=1.12), yaxis_title="%",
    )
    st.plotly_chart(fig, use_container_width=True)


def _quadrant_table(active_key):
    rows = []
    order = ["inflationary_repression", "liquidity_crisis",
             "stagflation", "goldilocks"]
    disc = {
        "inflationary_repression": "short real −  ·  long real ↑",
        "liquidity_crisis": "HY blowout  ·  long real ↓",
        "stagflation": "short real −  ·  2s10s re-steepening",
        "goldilocks": "short real +  ·  credit tight",
    }
    for k in order:
        w = rc.target_weights(k)
        star = " ⬅ **ACTIVE**" if k == active_key else ""
        rows.append({
            "Regime": rc.REGIMES[k]["label"] + star,
            "Discriminator": disc[k],
            "TLT": f"{w['TLT']}%", "KMLM": f"{w['KMLM']}%",
            "Metals": f"{w['GLD']+w['SLV']+w['RING']}%",
            "Cash": f"{w['SGOV']+w['USFR']}%",
            "Growth": f"{w['VGT']+w['SMH']+w['QQQ']}%",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
