"""
investors_tab.py  (v1.1 — 2026-11-24; shows the units note)
─────────────────────────────────────
The "🧭 Investor 13F" tab: latest 13F holdings of Duquesne Family Office (Stanley Druckenmiller) and
Bridgewater Associates (Ray Dalio's firm). REFERENCE ONLY. Reads data/investors_13f/summary.json,
written by investors_13f.py (weekly workflow "Investor 13F"); computes nothing.
"""
from __future__ import annotations

import json
import os
from datetime import date

import pandas as pd

PATH = os.path.join("data", "investors_13f", "summary.json")


def _age_days(iso: str | None) -> int | None:
    try:
        return (date.today() - date.fromisoformat(iso)).days
    except Exception:
        return None


def render(st) -> None:
    st.markdown("## 🧭 What Druckenmiller and Dalio's firm hold — latest 13F filings")
    st.info("**Reference only — not a signal and not tested.** A 13F shows US-listed long stocks, ETFs and listed "
            "options at the quarter end. It is filed up to **45 days later**, so it is 6–20 weeks old when you read it. "
            "It shows **no** shorts, bonds, futures, currencies or non-US holdings. For a macro firm like Bridgewater "
            "that is a small and possibly misleading slice of the book. Dalio founded Bridgewater but no longer runs "
            "it day to day. Nothing here feeds the model portfolio or the swing book.")
    try:
        r = json.load(open(PATH))
    except Exception:
        st.warning("No 13F data yet. Run **Actions → Investor 13F → Run workflow** (it also runs weekly).")
        return
    st.caption(f"Fetched from SEC EDGAR on {r.get('asof')} · investors_13f.py {r.get('version')}")
    filers = r.get("filers") or {}
    tabs = st.tabs([f"{v['person']}" for v in filers.values()]) if filers else []
    for tab, (k, v) in zip(tabs, filers.items()):
        with tab:
            age = _age_days(v.get("period"))
            c = st.columns(4)
            c[0].metric("Quarter end", v.get("period"), f"{age} days old" if age is not None else None, delta_color="off")
            c[1].metric("Filed", v.get("filed"))
            c[2].metric("Reported value", f"${v.get('total_value', 0) / 1e9:,.2f}bn")
            c[3].metric("Positions", v.get("positions"), f"top 10 = {v.get('top10_weight_pct')}%", delta_color="off")
            st.caption(f"{v.get('name')} · SEC CIK {v.get('cik')} · [filings on EDGAR]({v.get('source_url')})"
                       + (f" · {v['options_lines']} option lines (puts/calls are listed at the value of the "
                          "underlying shares, not the premium)" if v.get("options_lines") else ""))
            for n in v.get("unit_notes") or []:
                st.caption(f"Units: {n}")
            if v.get("amendments_after"):
                st.warning("An amendment was filed after this report (not merged): " + "; ".join(v["amendments_after"]))
            st.markdown("**Top holdings**")
            df = pd.DataFrame(v.get("top") or [])
            if len(df):
                df["Holding"] = df["issuer"] + df["put_call"].map(lambda x: f" ({x})" if x else "")
                st.dataframe(df[["Holding", "class", "weight_pct", "value", "shares"]].rename(columns={
                    "class": "Class", "weight_pct": "Weight %", "value": "Value $", "shares": "Shares"}),
                    use_container_width=True, hide_index=True)
            ch = v.get("changes") or {}
            st.markdown(f"**Changes since the previous quarter ({v.get('previous_period') or '—'})** — by share count; "
                        "a buy or sale could have happened any time in the quarter, at any price.")
            cols = st.columns(4)
            for col, key, title, fmt in ((cols[0], "new", "New", lambda z: f"{z['issuer']} ({z['weight_pct']:.1f}%)"),
                                         (cols[1], "added", "Added ≥10%", lambda z: f"{z['issuer']} ({z['shares_chg_pct']:+.0f}%)"),
                                         (cols[2], "trimmed", "Trimmed ≥10%", lambda z: f"{z['issuer']} ({z['shares_chg_pct']:+.0f}%)"),
                                         (cols[3], "exited", "Exited", lambda z: f"{z['issuer']} (was {z['prior_weight_pct']:.1f}%)")):
                with col:
                    st.markdown(f"*{title}*")
                    xs = ch.get(key) or []
                    st.markdown("\n".join(f"- {fmt(z)}" for z in xs[:10]) if xs else "—")
    st.caption("Research, not personalized advice. Copying 13Fs has not been tested here; the filing delay is the "
               "main reason such copies lag the original.")
