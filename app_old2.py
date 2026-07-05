"""
All-Weather Portfolio Dashboard
Tracks ETF performance vs benchmarks, portfolio construction,
category performance, and provides market signal education.
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

# ─── PAGE CONFIG ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="All-Weather Portfolio Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CUSTOM CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Main background */
    .stApp { background-color: #0f1117; color: #e0e0e0; }
    
    /* Metric cards */
    [data-testid="metric-container"] {
        background: #1c1f2e;
        border: 1px solid #2a2d3e;
        border-radius: 10px;
        padding: 12px 16px;
    }
    [data-testid="metric-container"] label { color: #8b8fa8 !important; font-size: 0.75rem !important; }
    [data-testid="metric-container"] [data-testid="stMetricValue"] { color: #ffffff !important; font-size: 1.4rem !important; }
    [data-testid="metric-container"] [data-testid="stMetricDelta"] { font-size: 0.8rem !important; }
    
    /* Sidebar */
    [data-testid="stSidebar"] { background-color: #13151f; border-right: 1px solid #2a2d3e; }
    
    /* Headers */
    h1, h2, h3 { color: #ffffff !important; }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] { background-color: #1c1f2e; border-radius: 10px; padding: 4px; }
    .stTabs [data-baseweb="tab"] { color: #8b8fa8; border-radius: 8px; }
    .stTabs [aria-selected="true"] { background-color: #2d6a4f !important; color: white !important; }
    
    /* Info boxes */
    .signal-box {
        background: #1c1f2e;
        border-left: 4px solid #2d6a4f;
        border-radius: 0 8px 8px 0;
        padding: 12px 16px;
        margin: 8px 0;
        font-size: 0.9rem;
        line-height: 1.6;
    }
    .signal-box.warning { border-left-color: #e6a817; }
    .signal-box.danger  { border-left-color: #e05252; }
    .signal-box.info    { border-left-color: #4a90d9; }
    
    /* Section card */
    .section-card {
        background: #1c1f2e;
        border: 1px solid #2a2d3e;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 16px;
    }
    
    /* Divider */
    hr { border-color: #2a2d3e !important; }
    
    /* Expander */
    [data-testid="stExpander"] { background: #1c1f2e; border: 1px solid #2a2d3e; border-radius: 10px; }
    
    /* Table */
    .dataframe { background: #1c1f2e !important; color: #e0e0e0 !important; }
    
    /* Scrollable container */
    .scroll-x { overflow-x: auto; }
</style>
""", unsafe_allow_html=True)

# ─── PORTFOLIO DEFINITION ────────────────────────────────────────────────────
PORTFOLIO = {
    # ticker: (name, allocation%, category, benchmark_ticker, benchmark_name)
    "VGT":  ("Vanguard Info Tech",         20, "Growth / Tech",    "QQQ",  "Nasdaq-100"),
    "SMH":  ("VanEck Semiconductors",       8, "Growth / Tech",    "SOXX", "SOX Index"),
    "QQQ":  ("Invesco Nasdaq-100",          7, "Growth / Tech",    "SPY",  "S&P 500"),
    "GLD":  ("SPDR Gold Shares",           12, "Precious Metals",  "GLD",  "Gold Spot"),
    "SLV":  ("iShares Silver Trust",        5, "Precious Metals",  "SLV",  "Silver Spot"),
    "RING": ("iShares Gold Miners",         5, "Precious Metals",  "GDX",  "Gold Miners"),
    "XLE":  ("Energy Select SPDR",          5, "Commodities/Energy","XOP", "Oil E&P"),
    "PDBC": ("Invesco Commodity",           3, "Commodities/Energy","DJP",  "Commodity Index"),
    "SCHD": ("Schwab Dividend Equity",     13, "Defensives",       "DVY",  "Dividend ETF"),
    "XLV":  ("Health Care Select SPDR",     4, "Defensives",       "SPY",  "S&P 500"),
    "XLU":  ("Utilities Select SPDR",       3, "Defensives",       "SPY",  "S&P 500"),
    "SGOV": ("iShares 0-3M Treasury",      10, "Short Bonds/Cash", "BIL",  "T-Bills"),
    "USFR": ("WisdomTree Floating Rate",    5, "Short Bonds/Cash", "FLOT", "Float Rate"),
}

CATEGORY_COLORS = {
    "Growth / Tech":      "#4CAF50",
    "Precious Metals":    "#FFA726",
    "Commodities/Energy": "#EF5350",
    "Defensives":         "#42A5F5",
    "Short Bonds/Cash":   "#AB47BC",
}

BENCHMARKS = {
    "S&P 500":   "SPY",
    "Nasdaq-100": "QQQ",
    "Dow Jones":  "DIA",
    "Gold":       "GLD",
    "Bonds (AGG)":"AGG",
}

# ─── DATA HELPERS ────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_price_history(tickers: list, period: str = "1y") -> pd.DataFrame:
    """Fetch adjusted close prices for a list of tickers."""
    try:
        raw = yf.download(tickers, period=period, auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            prices = raw["Close"]
        else:
            prices = raw[["Close"]].rename(columns={"Close": tickers[0]})
        return prices.dropna(how="all")
    except Exception as e:
        st.warning(f"Data fetch error: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_quote(ticker: str) -> dict:
    """Fetch latest quote info for a ticker."""
    try:
        t = yf.Ticker(ticker)
        info = t.info
        hist = t.history(period="2d")
        if len(hist) >= 2:
            prev  = hist["Close"].iloc[-2]
            curr  = hist["Close"].iloc[-1]
            chg   = curr - prev
            pct   = (chg / prev) * 100
        else:
            curr = info.get("regularMarketPrice", 0)
            chg  = info.get("regularMarketChange", 0)
            pct  = info.get("regularMarketChangePercent", 0)
        return {"price": curr, "change": chg, "pct_change": pct, "name": info.get("longName", ticker)}
    except:
        return {"price": 0, "change": 0, "pct_change": 0, "name": ticker}

def calc_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Calculate cumulative returns from price series."""
    return (prices / prices.iloc[0] - 1) * 100

def calc_stats(returns_series: pd.Series) -> dict:
    """Calculate key performance statistics."""
    daily = returns_series.pct_change().dropna()
    total = returns_series.iloc[-1]
    ann_vol = daily.std() * np.sqrt(252) * 100
    sharpe  = (total / ann_vol) if ann_vol > 0 else 0
    rolling_max = (1 + daily).cumprod().cummax()
    drawdown = ((1 + daily).cumprod() / rolling_max - 1).min() * 100
    return {
        "total_return": total,
        "ann_volatility": ann_vol,
        "sharpe_approx": sharpe,
        "max_drawdown": drawdown,
    }

# ─── CHART HELPERS ───────────────────────────────────────────────────────────
CHART_LAYOUT = dict(
    paper_bgcolor="#0f1117",
    plot_bgcolor="#13151f",
    font=dict(color="#c0c4d6", size=12),
    xaxis=dict(gridcolor="#2a2d3e", showgrid=True, zeroline=False),
    yaxis=dict(gridcolor="#2a2d3e", showgrid=True, zeroline=True, zerolinecolor="#3a3d4e"),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
    margin=dict(l=10, r=10, t=40, b=10),
    hovermode="x unified",
)

def styled_fig():
    fig = go.Figure()
    fig.update_layout(**CHART_LAYOUT)
    return fig

# ─── SIDEBAR ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Dashboard Settings")
    st.markdown("---")

    period_map = {
        "1 Month": "1mo", "3 Months": "3mo", "6 Months": "6mo",
        "1 Year": "1y",   "2 Years": "2y",   "5 Years": "5y",
    }
    period_label = st.selectbox("📅 Time Period", list(period_map.keys()), index=3)
    period = period_map[period_label]

    st.markdown("---")
    st.markdown("### 💼 Portfolio Allocation")
    st.markdown("*Adjust weights to model changes:*")

    custom_allocs = {}
    total_custom = 0
    for ticker, (name, alloc, cat, _, _) in PORTFOLIO.items():
        color = CATEGORY_COLORS[cat]
        val = st.slider(f"{ticker}", 0, 30, alloc, 1, key=f"alloc_{ticker}",
                        help=f"{name} — {cat}")
        custom_allocs[ticker] = val
        total_custom += val

    if total_custom != 100:
        delta = total_custom - 100
        color = "🔴" if delta > 0 else "🟡"
        st.warning(f"{color} Total: **{total_custom}%** ({"+" if delta>0 else ""}{delta}% from 100%)")
    else:
        st.success("✅ Total: **100%** — Balanced")

    st.markdown("---")
    st.markdown("### 🔔 Alerts")
    alert_threshold = st.slider("Alert if ETF lags benchmark by:", 2, 20, 5, 1, help="% underperformance trigger")

    st.markdown("---")
    st.markdown("<small style='color:#555'>Data via Yahoo Finance · Refreshes hourly<br>⚠️ Not financial advice</small>", unsafe_allow_html=True)

# ─── MAIN CONTENT ─────────────────────────────────────────────────────────────
st.markdown("# 📊 All-Weather Portfolio Dashboard")
st.markdown(f"<small style='color:#666'>Last updated: {datetime.now().strftime('%B %d, %Y %H:%M')} · Period: {period_label}</small>", unsafe_allow_html=True)
st.markdown("---")

# ─── TABS ─────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🏠 Overview",
    "📈 ETF vs Benchmark",
    "🗂️ Category Performance",
    "🏗️ Portfolio Construction",
    "📡 Market Signals",
    "📚 Education",
])

# ════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### 📌 Portfolio Snapshot")

    # Fetch all tickers + benchmarks
    all_tickers = list(PORTFOLIO.keys()) + list(BENCHMARKS.values())
    all_tickers = list(dict.fromkeys(all_tickers))  # dedupe
    prices = fetch_price_history(all_tickers, period)

    if prices.empty:
        st.error("Unable to fetch market data. Please check your connection.")
    else:
        # ── Top KPI row ──
        col1, col2, col3, col4, col5 = st.columns(5)

        # Weighted portfolio return
        port_return = 0.0
        for ticker, (_, alloc, _, _, _) in PORTFOLIO.items():
            if ticker in prices.columns:
                s = prices[ticker].dropna()
                if len(s) > 1:
                    ret = (s.iloc[-1] / s.iloc[0] - 1) * 100
                    port_return += ret * (custom_allocs.get(ticker, alloc) / 100)

        spy_ret = 0.0
        if "SPY" in prices.columns:
            s = prices["SPY"].dropna()
            if len(s) > 1:
                spy_ret = (s.iloc[-1] / s.iloc[0] - 1) * 100

        col1.metric("Portfolio Return", f"{port_return:+.1f}%",
                    f"vs S&P {port_return-spy_ret:+.1f}%")
        col2.metric("vs S&P 500", f"{spy_ret:+.1f}%")

        if "QQQ" in prices.columns:
            s = prices["QQQ"].dropna()
            qqq_ret = (s.iloc[-1] / s.iloc[0] - 1) * 100 if len(s)>1 else 0
            col3.metric("vs Nasdaq-100", f"{qqq_ret:+.1f}%", f"Port α {port_return-qqq_ret:+.1f}%")

        if "GLD" in prices.columns:
            s = prices["GLD"].dropna()
            gld_ret = (s.iloc[-1] / s.iloc[0] - 1) * 100 if len(s)>1 else 0
            col4.metric("Gold (GLD)", f"{gld_ret:+.1f}%")

        if "AGG" in prices.columns:
            s = prices["AGG"].dropna()
            agg_ret = (s.iloc[-1] / s.iloc[0] - 1) * 100 if len(s)>1 else 0
            col5.metric("Bonds (AGG)", f"{agg_ret:+.1f}%")

        st.markdown("---")

        # ── Portfolio vs Benchmarks chart ──
        st.markdown("### 📈 Portfolio vs Major Benchmarks")
        fig = styled_fig()

        # Weighted portfolio cumulative return
        port_series = None
        for ticker, (_, alloc, _, _, _) in PORTFOLIO.items():
            weight = custom_allocs.get(ticker, alloc) / 100
            if ticker in prices.columns:
                s = prices[ticker].dropna().pct_change().fillna(0)
                if port_series is None:
                    port_series = s * weight
                else:
                    port_series = port_series.add(s * weight, fill_value=0)

        if port_series is not None:
            cum = (1 + port_series).cumprod() - 1
            fig.add_trace(go.Scatter(
                x=cum.index, y=(cum*100).round(2),
                name="📊 This Portfolio", line=dict(color="#00E676", width=3),
                hovertemplate="%{y:.1f}%"
            ))

        bench_colors = {"SPY": "#4a90d9", "QQQ": "#9b59b6", "DIA": "#e67e22", "GLD": "#f1c40f", "AGG": "#1abc9c"}
        bench_names  = {"SPY": "S&P 500", "QQQ": "Nasdaq-100", "DIA": "Dow Jones", "GLD": "Gold", "AGG": "Bonds"}
        for bname, bticker in BENCHMARKS.items():
            if bticker in prices.columns:
                s = prices[bticker].dropna()
                cum = (s / s.iloc[0] - 1) * 100
                fig.add_trace(go.Scatter(
                    x=cum.index, y=cum.round(2),
                    name=bname, line=dict(color=bench_colors.get(bticker, "#888"), width=1.5, dash="dot"),
                    hovertemplate="%{y:.1f}%"
                ))

        fig.update_layout(title="Cumulative Return — Portfolio vs Benchmarks",
                          yaxis_title="Return (%)", height=420, **CHART_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

        # ── All ETF current returns table ──
        st.markdown("### 📋 All Holdings — Quick Returns")
        rows = []
        for ticker, (name, alloc, cat, bench, bench_name) in PORTFOLIO.items():
            w = custom_allocs.get(ticker, alloc)
            if ticker in prices.columns:
                s = prices[ticker].dropna()
                if len(s) > 1:
                    ret = (s.iloc[-1] / s.iloc[0] - 1) * 100
                    b_ret = None
                    if bench in prices.columns and bench != ticker:
                        bs = prices[bench].dropna()
                        b_ret = (bs.iloc[-1] / bs.iloc[0] - 1) * 100 if len(bs) > 1 else None
                    alpha = (ret - b_ret) if b_ret is not None else None
                    rows.append({
                        "Ticker": ticker,
                        "Name": name,
                        "Category": cat,
                        "Weight": f"{w}%",
                        f"Return ({period_label})": f"{ret:+.1f}%",
                        "vs Benchmark": f"{alpha:+.1f}%" if alpha is not None else "—",
                        "Status": "✅ Outperforming" if (alpha or 0) >= 0 else ("⚠️ Watch" if (alpha or 0) > -alert_threshold else "🔴 Lagging"),
                    })

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True,
                         column_config={
                             "Ticker": st.column_config.TextColumn(width="small"),
                             "Weight": st.column_config.TextColumn(width="small"),
                             "Status": st.column_config.TextColumn(width="medium"),
                         })

# ════════════════════════════════════════════════════════════════════════
# TAB 2 — ETF vs BENCHMARK
# ════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### 📈 Individual ETF vs Its Benchmark")
    st.markdown("*Each ETF is compared to its most relevant market benchmark.*")

    selected_ticker = st.selectbox(
        "Select ETF to analyze:",
        list(PORTFOLIO.keys()),
        format_func=lambda t: f"{t} — {PORTFOLIO[t][0]}"
    )

    if selected_ticker:
        name, alloc, cat, bench, bench_name = PORTFOLIO[selected_ticker]
        tickers_to_fetch = list(dict.fromkeys([selected_ticker, bench, "SPY"]))
        prices2 = fetch_price_history(tickers_to_fetch, period)

        if not prices2.empty and selected_ticker in prices2.columns:
            s_etf  = prices2[selected_ticker].dropna()
            s_bench = prices2[bench].dropna() if bench in prices2.columns else None
            s_spy   = prices2["SPY"].dropna()  if "SPY" in prices2.columns else None

            ret_etf   = (s_etf.iloc[-1]   / s_etf.iloc[0]   - 1) * 100 if len(s_etf)   > 1 else 0
            ret_bench = (s_bench.iloc[-1]  / s_bench.iloc[0]  - 1) * 100 if s_bench is not None and len(s_bench) > 1 else 0
            ret_spy   = (s_spy.iloc[-1]    / s_spy.iloc[0]    - 1) * 100 if s_spy   is not None and len(s_spy)   > 1 else 0

            # KPIs
            c1, c2, c3, c4 = st.columns(4)
            c1.metric(f"{selected_ticker} Return", f"{ret_etf:+.1f}%")
            c2.metric(f"vs {bench_name}", f"{ret_bench:+.1f}%", f"Alpha: {ret_etf-ret_bench:+.1f}%")
            c3.metric("vs S&P 500", f"{ret_spy:+.1f}%", f"{ret_etf-ret_spy:+.1f}%")
            stats = calc_stats(s_etf)
            c4.metric("Max Drawdown", f"{stats['max_drawdown']:.1f}%")

            # Cumulative return chart
            fig2 = styled_fig()
            cat_color = CATEGORY_COLORS.get(cat, "#888")

            cum_etf = (s_etf / s_etf.iloc[0] - 1) * 100
            fig2.add_trace(go.Scatter(x=cum_etf.index, y=cum_etf.round(2),
                name=selected_ticker, line=dict(color=cat_color, width=3),
                hovertemplate="%{y:.1f}%"))

            if s_bench is not None and bench != selected_ticker:
                cum_b = (s_bench / s_bench.iloc[0] - 1) * 100
                fig2.add_trace(go.Scatter(x=cum_b.index, y=cum_b.round(2),
                    name=bench_name, line=dict(color="#888", width=1.5, dash="dash"),
                    hovertemplate="%{y:.1f}%"))

            if s_spy is not None:
                cum_spy = (s_spy / s_spy.iloc[0] - 1) * 100
                fig2.add_trace(go.Scatter(x=cum_spy.index, y=cum_spy.round(2),
                    name="S&P 500", line=dict(color="#4a90d9", width=1.5, dash="dot"),
                    hovertemplate="%{y:.1f}%"))

            fig2.update_layout(title=f"{selected_ticker} vs {bench_name} vs S&P 500",
                               yaxis_title="Cumulative Return (%)", height=400, **CHART_LAYOUT)
            st.plotly_chart(fig2, use_container_width=True)

            # Relative strength (rolling 30-day)
            st.markdown("#### 🔁 Rolling 30-Day Relative Strength vs Benchmark")
            if s_bench is not None and bench != selected_ticker:
                etf_ret_daily   = s_etf.pct_change()
                bench_ret_daily = s_bench.pct_change()
                rel_strength    = (etf_ret_daily - bench_ret_daily).rolling(30).sum() * 100

                fig_rs = styled_fig()
                colors = [cat_color if v >= 0 else "#e05252" for v in rel_strength.dropna()]
                fig_rs.add_trace(go.Bar(
                    x=rel_strength.dropna().index,
                    y=rel_strength.dropna().round(2),
                    marker_color=colors,
                    name="Relative Strength",
                    hovertemplate="%{y:.2f}%"
                ))
                fig_rs.add_hline(y=0, line_color="#555", line_width=1)
                fig_rs.update_layout(title="30-Day Rolling Outperformance vs Benchmark (green = outperforming)",
                                     yaxis_title="Relative Return (%)", height=280, **CHART_LAYOUT)
                st.plotly_chart(fig_rs, use_container_width=True)

            # Drawdown chart
            st.markdown("#### 📉 Drawdown Analysis")
            daily_ret = s_etf.pct_change().fillna(0)
            cum_prod  = (1 + daily_ret).cumprod()
            roll_max  = cum_prod.cummax()
            drawdown  = (cum_prod / roll_max - 1) * 100

            fig_dd = styled_fig()
            fig_dd.add_trace(go.Scatter(
                x=drawdown.index, y=drawdown.round(2),
                fill="tozeroy", fillcolor="rgba(224,82,82,0.15)",
                line=dict(color="#e05252", width=1.5),
                name="Drawdown", hovertemplate="%{y:.1f}%"
            ))
            fig_dd.update_layout(title=f"{selected_ticker} Drawdown from Peak",
                                 yaxis_title="Drawdown (%)", height=250, **CHART_LAYOUT)
            st.plotly_chart(fig_dd, use_container_width=True)

            # Stats table
            st.markdown("#### 📊 Performance Statistics")
            vol = stats["ann_volatility"]
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.markdown(f"""
<div class="section-card">
<b>{selected_ticker}</b><br>
📈 Period Return: <b>{ret_etf:+.1f}%</b><br>
📉 Max Drawdown: <b>{stats['max_drawdown']:.1f}%</b><br>
⚡ Ann. Volatility: <b>{vol:.1f}%</b><br>
⚖️ Return/Risk: <b>{stats['sharpe_approx']:.2f}</b>
</div>""", unsafe_allow_html=True)
            with col_s2:
                alpha = ret_etf - ret_bench
                status = "✅ Outperforming" if alpha >= 0 else "🔴 Underperforming"
                st.markdown(f"""
<div class="section-card">
<b>vs {bench_name}</b><br>
{status}<br>
Alpha (period): <b>{alpha:+.1f}%</b><br>
Benchmark Return: <b>{ret_bench:+.1f}%</b><br>
Portfolio weight: <b>{custom_allocs.get(selected_ticker, alloc)}%</b>
</div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════
# TAB 3 — CATEGORY PERFORMANCE
# ════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 🗂️ Performance by Category")

    # Fetch all portfolio tickers
    port_prices = fetch_price_history(list(PORTFOLIO.keys()) + ["SPY"], period)

    if not port_prices.empty:
        # ── Category returns ──
        categories = {}
        for ticker, (name, alloc, cat, bench, bench_name) in PORTFOLIO.items():
            if ticker in port_prices.columns:
                s = port_prices[ticker].dropna()
                if len(s) > 1:
                    ret = (s.iloc[-1] / s.iloc[0] - 1) * 100
                    w   = custom_allocs.get(ticker, alloc)
                    if cat not in categories:
                        categories[cat] = {"tickers": [], "weighted_return": 0, "total_weight": 0}
                    categories[cat]["tickers"].append((ticker, name, ret, w))
                    categories[cat]["weighted_return"] += ret * w
                    categories[cat]["total_weight"]    += w

        # KPI row — one metric per category
        cat_list = list(categories.keys())
        cat_cols = st.columns(len(cat_list))
        for i, (cat, data) in enumerate(categories.items()):
            tw = data["total_weight"]
            wr = data["weighted_return"] / tw if tw > 0 else 0
            cat_cols[i].metric(cat, f"{wr:+.1f}%", f"{tw}% of portfolio")

        st.markdown("---")

        # ── Category cumulative return chart ──
        st.markdown("#### 📈 Category Cumulative Returns")
        fig_cat = styled_fig()

        for cat, data in categories.items():
            cat_series = None
            total_w = data["total_weight"]
            for ticker, name, ret, w in data["tickers"]:
                if ticker in port_prices.columns:
                    daily = port_prices[ticker].dropna().pct_change().fillna(0)
                    share = (w / total_w) if total_w > 0 else 0
                    if cat_series is None:
                        cat_series = daily * share
                    else:
                        cat_series = cat_series.add(daily * share, fill_value=0)

            if cat_series is not None:
                cum = (1 + cat_series).cumprod() - 1
                fig_cat.add_trace(go.Scatter(
                    x=cum.index, y=(cum*100).round(2),
                    name=cat, line=dict(color=CATEGORY_COLORS.get(cat, "#888"), width=2.5),
                    hovertemplate="%{y:.1f}%"
                ))

        # Add S&P 500 as reference
        if "SPY" in port_prices.columns:
            s = port_prices["SPY"].dropna()
            cum_spy = (s / s.iloc[0] - 1) * 100
            fig_cat.add_trace(go.Scatter(
                x=cum_spy.index, y=cum_spy.round(2),
                name="S&P 500 (ref)", line=dict(color="#ffffff", width=1, dash="dot"),
                hovertemplate="%{y:.1f}%"
            ))

        fig_cat.update_layout(title="Category Cumulative Returns vs S&P 500",
                              yaxis_title="Return (%)", height=420, **CHART_LAYOUT)
        st.plotly_chart(fig_cat, use_container_width=True)

        # ── Category breakdown table ──
        st.markdown("#### 📋 Category Breakdown — Holdings Detail")
        for cat, data in categories.items():
            color = CATEGORY_COLORS.get(cat, "#888")
            tw = data["total_weight"]
            wr = data["weighted_return"] / tw if tw > 0 else 0
            with st.expander(f"**{cat}** — {tw}% of portfolio | Weighted return: {wr:+.1f}%"):
                rows_cat = []
                for ticker, name, ret, w in sorted(data["tickers"], key=lambda x: -x[2]):
                    _, _, _, bench, bench_name = PORTFOLIO[ticker]
                    b_ret = None
                    if bench in port_prices.columns and bench != ticker:
                        bs = port_prices[bench].dropna()
                        b_ret = (bs.iloc[-1] / bs.iloc[0] - 1) * 100 if len(bs) > 1 else None
                    rows_cat.append({
                        "Ticker": ticker,
                        "Name": name,
                        "Weight": f"{w}%",
                        "Return": f"{ret:+.1f}%",
                        "Benchmark": bench_name,
                        "vs Benchmark": f"{ret-b_ret:+.1f}%" if b_ret is not None else "—",
                    })
                st.dataframe(pd.DataFrame(rows_cat), use_container_width=True, hide_index=True)

        # ── Heatmap: daily returns ──
        st.markdown("#### 🌡️ Holdings Performance Heatmap (Last 30 Days)")
        tickers_ordered = list(PORTFOLIO.keys())
        avail = [t for t in tickers_ordered if t in port_prices.columns]
        heat_data = port_prices[avail].pct_change().tail(30) * 100

        fig_heat = go.Figure(data=go.Heatmap(
            z=heat_data.values.T,
            x=[d.strftime("%m/%d") for d in heat_data.index],
            y=avail,
            colorscale=[[0, "#b71c1c"], [0.5, "#1c1f2e"], [1, "#1b5e20"]],
            zmid=0,
            text=heat_data.values.T.round(1),
            texttemplate="%{text}%",
            hovertemplate="Date: %{x}<br>Ticker: %{y}<br>Return: %{z:.2f}%<extra></extra>",
            colorbar=dict(title="Return %", tickfont=dict(color="#c0c4d6")),
        ))
        fig_heat.update_layout(
            title="Daily Returns Heatmap — All Holdings",
            height=500,
            paper_bgcolor="#0f1117", plot_bgcolor="#0f1117",
            font=dict(color="#c0c4d6"),
            margin=dict(l=60, r=20, t=40, b=40),
            xaxis=dict(tickfont=dict(size=9)),
            yaxis=dict(tickfont=dict(size=11)),
        )
        st.plotly_chart(fig_heat, use_container_width=True)

# ════════════════════════════════════════════════════════════════════════
# TAB 4 — PORTFOLIO CONSTRUCTION
# ════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 🏗️ Portfolio Construction")

    col_left, col_right = st.columns([1, 1])

    with col_left:
        # Donut — by ticker
        st.markdown("#### Holdings Allocation")
        tickers_ = list(PORTFOLIO.keys())
        weights_ = [custom_allocs.get(t, PORTFOLIO[t][1]) for t in tickers_]
        colors_  = [CATEGORY_COLORS.get(PORTFOLIO[t][2], "#888") for t in tickers_]

        fig_donut = go.Figure(data=[go.Pie(
            labels=tickers_,
            values=weights_,
            hole=0.55,
            marker=dict(colors=colors_, line=dict(color="#0f1117", width=2)),
            textinfo="label+percent",
            textfont=dict(size=11, color="#ffffff"),
            hovertemplate="<b>%{label}</b><br>%{value}% allocation<br>%{percent}<extra></extra>",
        )])
        fig_donut.update_layout(
            annotations=[dict(text=f"<b>{sum(weights_)}%</b>", x=0.5, y=0.5,
                              font_size=18, font_color="#fff", showarrow=False)],
            paper_bgcolor="#0f1117", plot_bgcolor="#0f1117",
            font=dict(color="#c0c4d6"),
            showlegend=False,
            margin=dict(l=10, r=10, t=20, b=10),
            height=380,
        )
        st.plotly_chart(fig_donut, use_container_width=True)

    with col_right:
        # Donut — by category
        st.markdown("#### Category Allocation")
        cat_weights = {}
        for t, (_, alloc, cat, _, _) in PORTFOLIO.items():
            w = custom_allocs.get(t, alloc)
            cat_weights[cat] = cat_weights.get(cat, 0) + w

        fig_cat_donut = go.Figure(data=[go.Pie(
            labels=list(cat_weights.keys()),
            values=list(cat_weights.values()),
            hole=0.55,
            marker=dict(
                colors=[CATEGORY_COLORS.get(c, "#888") for c in cat_weights.keys()],
                line=dict(color="#0f1117", width=2)
            ),
            textinfo="label+percent",
            textfont=dict(size=11, color="#ffffff"),
            hovertemplate="<b>%{label}</b><br>%{value}%<extra></extra>",
        )])
        fig_cat_donut.update_layout(
            paper_bgcolor="#0f1117", plot_bgcolor="#0f1117",
            font=dict(color="#c0c4d6"),
            showlegend=False,
            margin=dict(l=10, r=10, t=20, b=10),
            height=380,
        )
        st.plotly_chart(fig_cat_donut, use_container_width=True)

    # ── Allocation bar chart ──
    st.markdown("#### 📊 Holdings Weight vs Suggested Allocation")
    suggested = {t: PORTFOLIO[t][1] for t in PORTFOLIO}
    current   = {t: custom_allocs.get(t, PORTFOLIO[t][1]) for t in PORTFOLIO}

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        x=list(suggested.keys()), y=list(suggested.values()),
        name="Suggested", marker_color="#2d6a4f", opacity=0.7,
    ))
    fig_bar.add_trace(go.Bar(
        x=list(current.keys()), y=list(current.values()),
        name="Custom (sidebar)", marker_color="#00E676", opacity=0.9,
    ))
    fig_bar.update_layout(
        barmode="group", title="Current vs Suggested Allocation per Holding",
        yaxis_title="Weight (%)", height=350, **CHART_LAYOUT
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # ── Holdings detail table ──
    st.markdown("#### 📋 Full Holdings Table")
    rows_detail = []
    for ticker, (name, alloc, cat, bench, bench_name) in PORTFOLIO.items():
        rows_detail.append({
            "Ticker": ticker,
            "Name": name,
            "Category": cat,
            "Suggested %": alloc,
            "Custom %": custom_allocs.get(ticker, alloc),
            "Δ from Suggested": custom_allocs.get(ticker, alloc) - alloc,
            "Benchmark": bench_name,
            "Expense Ratio": {
                "VGT":"0.09%","SMH":"0.35%","QQQ":"0.18%","GLD":"0.40%",
                "SLV":"0.50%","RING":"0.39%","XLE":"0.09%","PDBC":"0.59%",
                "SCHD":"0.06%","XLV":"0.09%","XLU":"0.09%","SGOV":"0.09%","USFR":"0.15%",
            }.get(ticker, "—"),
        })
    st.dataframe(pd.DataFrame(rows_detail), use_container_width=True, hide_index=True)

    # Weighted avg expense ratio
    er_map = {"VGT":0.09,"SMH":0.35,"QQQ":0.18,"GLD":0.40,"SLV":0.50,"RING":0.39,
              "XLE":0.09,"PDBC":0.59,"SCHD":0.06,"XLV":0.09,"XLU":0.09,"SGOV":0.09,"USFR":0.15}
    weighted_er = sum(er_map.get(t,0) * custom_allocs.get(t,PORTFOLIO[t][1]) / 100 for t in PORTFOLIO)
    st.info(f"💡 Weighted Average Expense Ratio: **{weighted_er:.2f}%** annually")

    # ── Rebalancing alerts ──
    st.markdown("#### 🔔 Rebalancing Alerts")
    alerts_found = False
    for ticker, (name, alloc, cat, _, _) in PORTFOLIO.items():
        custom = custom_allocs.get(ticker, alloc)
        diff   = abs(custom - alloc)
        if diff >= 3:
            alerts_found = True
            direction = "overweight ↑" if custom > alloc else "underweight ↓"
            color = "warning" if diff < 7 else "danger"
            st.markdown(f"""<div class="signal-box {color}">
⚖️ <b>{ticker}</b> ({name}): {direction} by <b>{diff}%</b>
(suggested {alloc}% → current {custom}%)
</div>""", unsafe_allow_html=True)
    if not alerts_found:
        st.success("✅ All holdings are within 3% of their suggested allocation — no rebalancing needed.")

# ════════════════════════════════════════════════════════════════════════
# TAB 5 — MARKET SIGNALS
# ════════════════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### 📡 Live Market Signals & Indicators")
    st.markdown("<small style='color:#666'>Signals updated with live market data where available</small>", unsafe_allow_html=True)

    # Fetch signal data
    signal_tickers = ["^VIX", "GLD", "TLT", "BIL", "SPY", "^TNX", "^TYX"]
    sig_prices = fetch_price_history(signal_tickers + list(PORTFOLIO.keys()), "1y")

    col_s1, col_s2 = st.columns(2)

    with col_s1:
        st.markdown("#### 🔴 Risk / Fear Indicators")

        # VIX
        if "^VIX" in sig_prices.columns:
            vix_val = sig_prices["^VIX"].dropna().iloc[-1]
            vix_color = "danger" if vix_val > 30 else ("warning" if vix_val > 20 else "")
            vix_label = "FEAR (consider defensive tilt)" if vix_val > 30 else ("ELEVATED" if vix_val > 20 else "CALM (watch for complacency)")
            st.markdown(f"""<div class="signal-box {vix_color}">
<b>VIX (Fear Index): {vix_val:.1f}</b> — {vix_label}<br>
<small>Below 15: complacent market. 15–25: normal. Above 30: fear / potential buying opportunity for quality assets.</small>
</div>""", unsafe_allow_html=True)

        # Gold/SPY ratio (risk-off signal)
        if "GLD" in sig_prices.columns and "SPY" in sig_prices.columns:
            gld = sig_prices["GLD"].dropna()
            spy = sig_prices["SPY"].dropna()
            ratio_now   = gld.iloc[-1]  / spy.iloc[-1]
            ratio_start = gld.iloc[0]   / spy.iloc[0]
            ratio_chg   = (ratio_now / ratio_start - 1) * 100
            direction   = "rising ↑ (risk-off sentiment growing)" if ratio_chg > 0 else "falling ↓ (risk-on sentiment)"
            box_class   = "warning" if ratio_chg > 5 else ""
            st.markdown(f"""<div class="signal-box {box_class}">
<b>Gold/S&P Ratio: {direction}</b> ({ratio_chg:+.1f}% over {period_label})<br>
<small>A rising Gold/SPY ratio signals investors rotating to safety. Supports maintaining precious metals allocation.</small>
</div>""", unsafe_allow_html=True)

        # TLT vs BIL (bond stress)
        if "TLT" in sig_prices.columns and "BIL" in sig_prices.columns:
            tlt = sig_prices["TLT"].dropna()
            bil = sig_prices["BIL"].dropna()
            tlt_ret = (tlt.iloc[-1] / tlt.iloc[0] - 1) * 100
            bil_ret = (bil.iloc[-1] / bil.iloc[0] - 1) * 100
            spread  = bil_ret - tlt_ret
            class_  = "danger" if spread > 3 else "warning" if spread > 0 else ""
            msg     = "Long bonds underperforming T-bills — AVOID long bonds" if spread > 0 else "Long bonds recovering — monitor for pivot signal"
            st.markdown(f"""<div class="signal-box {class_}">
<b>T-Bills vs Long Bonds (TLT):</b> {msg}<br>
T-bills: {bil_ret:+.1f}% | TLT: {tlt_ret:+.1f}% | Gap: {spread:+.1f}%<br>
<small>When T-bills outperform long bonds, rising rate environment confirmed. Hold SGOV/USFR, avoid TLT.</small>
</div>""", unsafe_allow_html=True)

    with col_s2:
        st.markdown("#### 🟢 Trend & Momentum Signals")

        # SPY trend
        if "SPY" in sig_prices.columns:
            spy_ = sig_prices["SPY"].dropna()
            ma50 = spy_.rolling(50).mean().iloc[-1]
            ma200= spy_.rolling(200).mean().iloc[-1] if len(spy_) >= 200 else spy_.rolling(min(len(spy_),200)).mean().iloc[-1]
            price_now = spy_.iloc[-1]
            above_50  = price_now > ma50
            above_200 = price_now > ma200
            golden    = ma50 > ma200
            cross_signal = "🟢 Golden Cross (bullish)" if golden else "🔴 Death Cross (bearish)"
            st.markdown(f"""<div class="signal-box {'info' if above_200 else 'warning'}">
<b>S&P 500 Trend:</b> {cross_signal}<br>
Price {'above' if above_50 else 'below'} 50-day MA | {'above' if above_200 else 'below'} 200-day MA<br>
<small>Golden Cross (50MA > 200MA) = long-term uptrend. Death Cross = potential trend reversal. Currently: {'Bullish trend' if above_200 else 'Caution — below long-term trend'}.</small>
</div>""", unsafe_allow_html=True)

        # Momentum: portfolio relative to SPY
        if "SPY" in sig_prices.columns:
            port_mom = None
            for ticker, (_, alloc, _, _, _) in PORTFOLIO.items():
                if ticker in sig_prices.columns:
                    w = custom_allocs.get(ticker, alloc) / 100
                    d = sig_prices[ticker].pct_change().fillna(0)
                    port_mom = d*w if port_mom is None else port_mom + d*w
            if port_mom is not None:
                spy_mom   = sig_prices["SPY"].pct_change().fillna(0)
                rel_30    = ((port_mom.tail(30).sum()) - (spy_mom.tail(30).sum())) * 100
                rel_class = "info" if rel_30 > 0 else "warning"
                st.markdown(f"""<div class="signal-box {rel_class}">
<b>Portfolio 30-Day Momentum vs S&P 500: {rel_30:+.1f}%</b><br>
{'Portfolio is outperforming the S&P 500 this month ✅' if rel_30 > 0 else 'Portfolio is lagging the S&P 500 this month ⚠️'}<br>
<small>Positive = portfolio has stronger recent momentum. Consider trimming lagging categories if persistent.</small>
</div>""", unsafe_allow_html=True)

        # Category momentum
        st.markdown("#### 📊 30-Day Category Momentum")
        if not sig_prices.empty:
            cat_mom_rows = []
            for cat, color in CATEGORY_COLORS.items():
                cat_tickers = [t for t, (_, _, c, _, _) in PORTFOLIO.items() if c == cat and t in sig_prices.columns]
                if cat_tickers:
                    avg_mom = np.mean([(sig_prices[t].pct_change().tail(30).sum()*100) for t in cat_tickers])
                    cat_mom_rows.append({"Category": cat, "30-Day Return": avg_mom})
            if cat_mom_rows:
                mom_df = pd.DataFrame(cat_mom_rows).sort_values("30-Day Return", ascending=True)
                fig_mom = go.Figure(go.Bar(
                    x=mom_df["30-Day Return"].round(2),
                    y=mom_df["Category"],
                    orientation="h",
                    marker_color=[CATEGORY_COLORS.get(c, "#888") for c in mom_df["Category"]],
                    text=[f"{v:+.1f}%" for v in mom_df["30-Day Return"]],
                    textposition="outside",
                ))
                fig_mom.update_layout(
                    title="Category 30-Day Momentum",
                    xaxis_title="Return (%)",
                    height=280, **CHART_LAYOUT
                )
                st.plotly_chart(fig_mom, use_container_width=True)

    # ── Yield curve ──
    st.markdown("---")
    st.markdown("#### 📈 Yield-Based Signals")
    if "^TNX" in sig_prices.columns and "^TYX" in sig_prices.columns:
        tnx = sig_prices["^TNX"].dropna()
        tyx = sig_prices["^TYX"].dropna()
        spread_now   = tyx.iloc[-1]  - tnx.iloc[-1]
        spread_start = tyx.iloc[0]   - tnx.iloc[0]
        spread_chg   = spread_now - spread_start

        fig_yield = styled_fig()
        fig_yield.add_trace(go.Scatter(x=tnx.index, y=tnx, name="10-Yr Yield", line=dict(color="#4a90d9", width=2)))
        fig_yield.add_trace(go.Scatter(x=tyx.index, y=tyx, name="30-Yr Yield", line=dict(color="#e6a817", width=2)))
        spread = tyx - tnx
        fig_yield.add_trace(go.Scatter(x=spread.index, y=spread, name="30/10 Spread", line=dict(color="#00E676", width=1.5, dash="dot"), yaxis="y2"))
        yield_layout = {k: v for k, v in CHART_LAYOUT.items() if k not in ("xaxis", "yaxis")}
        fig_yield.update_layout(
            title="10-Year vs 30-Year Treasury Yields",
            xaxis=dict(gridcolor="#2a2d3e", showgrid=True, zeroline=False),
            yaxis=dict(title="Yield (%)", gridcolor="#2a2d3e", showgrid=True),
            yaxis2=dict(title="Spread (%)", overlaying="y", side="right", gridcolor="#2a2d3e", showgrid=False),
            height=320,
            **yield_layout
        )
        st.plotly_chart(fig_yield, use_container_width=True)

        signal_text = "steepening ↑ (economic growth expectations)" if spread_chg > 0 else "flattening/inverting ↓ (recession risk signal)"
        yield_class = "info" if spread_chg > 0 else "warning"
        st.markdown(f"""<div class="signal-box {yield_class}">
<b>Yield Curve (30yr - 10yr): {signal_text}</b><br>
Current spread: {spread_now:.2f}% | Change over period: {spread_chg:+.2f}%<br>
30-yr yield: {tyx.iloc[-1]:.2f}% | 10-yr yield: {tnx.iloc[-1]:.2f}%<br>
<small>A flattening or inverted curve historically precedes recessions. Steepening = growth confidence returning.</small>
</div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════
# TAB 6 — EDUCATION
# ════════════════════════════════════════════════════════════════════════
with tab6:
    st.markdown("### 📚 Market Signals & Investment Education")
    st.markdown("*Use this as your reference guide for interpreting what you see in the dashboard.*")

    topics = {
        "📉 Understanding Drawdown": """
**What it is:** The peak-to-trough decline in an investment's value. If a fund hits $100, drops to $70, that's a -30% drawdown.

**Why it matters:** Maximum drawdown tells you the worst loss you'd have experienced at the worst possible time. It's more emotionally meaningful than volatility.

**Rules of thumb:**
- **Under 10%:** Very defensive/conservative
- **10–20%:** Moderate risk
- **20–40%:** Growth-oriented
- **Over 40%:** Aggressive/concentrated

**Portfolio application:** VGT's historical max drawdown is ~55% (2000–2002 dot-com bust). That means a $100,000 position could drop to $45,000. The hedge positions (GLD, SGOV) exist to offset this risk.
""",
        "📊 Moving Averages (50-Day & 200-Day)": """
**What they are:** The average closing price over the last 50 or 200 trading days. They smooth out noise to reveal trends.

**Golden Cross 🟢:** 50-day MA crosses *above* 200-day MA. Historically bullish — often signals a sustained uptrend.

**Death Cross 🔴:** 50-day MA crosses *below* 200-day MA. Historically bearish — often precedes continued weakness.

**Key levels:**
- Price **above 200-day MA** → Long-term uptrend intact. Hold or buy dips.
- Price **below 200-day MA** → Caution. Consider reducing risk.
- Price **far above 200-day MA** (>15%) → Potentially overbought. Trim or don't add.

**For this portfolio:** If SPY falls below its 200-day MA and a Death Cross forms, consider increasing SGOV/SCHD and reducing SMH exposure.
""",
        "😱 VIX — The Fear Index": """
**What it is:** The CBOE Volatility Index measures the market's expectation of 30-day volatility based on S&P 500 options pricing. Sometimes called the "fear gauge."

**Reading levels:**
- **Below 15:** Calm, complacent market — often a warning sign that investors are overconfident
- **15–20:** Normal range
- **20–30:** Elevated anxiety; investors hedging more
- **30–40:** Significant fear; often near market bottoms
- **Above 40:** Extreme fear (seen in 2008, March 2020) — historically strong buying opportunities for quality assets

**Contrarian signal:** When VIX spikes above 30–40, it's often a better time to *buy*, not sell. Fear creates opportunity.

**For this portfolio:** A VIX spike is when GLD, SGOV, and SCHD prove their worth. The tech positions (VGT, SMH) will drop hard — that's when to add, not panic.
""",
        "📈 Relative Strength — Is Your ETF Beating Its Benchmark?": """
**What it is:** Compares how your holding performs relative to its specific market benchmark. Positive relative strength = outperforming.

**Why benchmark matching matters:**
- VGT should be compared to the Nasdaq/tech sector — not the S&P 500
- XLE should be compared to oil/energy benchmarks
- SCHD should be compared to dividend indices

**Signals to watch:**
- **Sustained positive relative strength (3+ months):** Holding is genuinely strong. Consider maintaining or adding.
- **Negative relative strength for 2+ months:** Something may be structurally wrong. Review thesis.
- **Relative strength declining while price rises:** Could mean the rally is broad, not specific — not necessarily a problem.

**For this portfolio:** If VGT consistently lags QQQ by more than 5% for a quarter, it may be worth investigating whether a sector rotation is occurring.
""",
        "💹 Yield Curve — What Bonds Tell You About the Economy": """
**What it is:** A chart of interest rates across different Treasury maturities (2yr, 5yr, 10yr, 30yr). Normally, longer = higher yield (upward sloping).

**Normal curve (steep):** Short rates lower than long rates → Economy expected to grow. Pro-risk signal.

**Flat curve:** Short and long rates similar → Economic slowdown concern.

**Inverted curve (2yr > 10yr):** Short rates HIGHER than long rates → Historically the most reliable recession predictor. Has preceded every U.S. recession since 1970.

**Current situation (2026):** The 30-yr is near 5% while the 2-yr is above the Fed Funds Rate — the bond market is signaling the Fed is *behind the curve* on inflation. This is why we hold zero long-duration bonds and own short T-bills (SGOV/USFR) instead.

**Action triggers:**
- Yield curve inverts deeply → Increase SCHD, XLV, XLU; reduce SMH
- Yield curve steepens sharply from inversion → Economy recovering; rotate into cyclicals/growth
""",
        "🏦 PCE & CPI — Reading Inflation Signals": """
**PCE (Personal Consumption Expenditures):** The Fed's *preferred* inflation gauge. Broader than CPI. Tracks what consumers actually spend money on.

**CPI (Consumer Price Index):** More widely reported. Tracks a fixed basket of goods. Tends to run ~0.3% higher than PCE.

**Fed's target:** 2% PCE annually. We are currently at **3.8%** — nearly double the target.

**What inflation means for this portfolio:**
- **High inflation (>3%):** GLD, SLV, XLE, PDBC outperform. Bonds lose real value. Short T-bills protect (SGOV/USFR yields rise with inflation).
- **Falling inflation (<2%):** Bonds recover. Growth/tech re-rates higher. Time to reduce metals, potentially add intermediate bonds.
- **Stagflation (high inflation + slow growth):** Worst scenario for equities. Gold, silver, commodities, and T-bills are your best friends.

**Trigger levels to watch:**
- PCE above 4%: Consider increasing GLD/SLV allocation
- PCE below 2.5% for 3 months: Begin rotating from metals to SCHD/XLV and consider adding IEF (intermediate bonds)
""",
        "⚖️ Portfolio Rebalancing — When and How": """
**What is rebalancing?** Bringing your portfolio back to target weights after market movements cause drift.

**Why it matters:** If VGT surges 40%, it might grow from 20% to 28% of the portfolio — making you more concentrated in tech than intended.

**Rebalancing triggers (use any of these):**
1. **Time-based:** Quarterly or semi-annual automatic rebalance
2. **Threshold-based:** Any holding drifts more than 5% from target → rebalance
3. **Event-based:** Major macro shift (e.g., Iran deal confirmed, Fed pivots, PCE drops below 2.5%)

**Tax-smart rebalancing:**
- In taxable accounts, prefer to rebalance by *directing new contributions* to underweight positions
- Use dividends and income (SCHD, SGOV) to fund rebalancing without selling
- Consider rebalancing in tax-advantaged accounts (IRA, 401k) first

**For this portfolio:**
- If GLD runs up further to 15%+ of portfolio → trim and rebalance to SCHD/SGOV
- If tech sells off >20% → that's a buying opportunity, not a sell signal
- Review allocation quarterly at minimum
""",
    }

    for topic, content in topics.items():
        with st.expander(topic, expanded=False):
            st.markdown(content)

    st.markdown("---")
    st.markdown("### 🗺️ Decision Framework — What to Do When...")

    decisions = [
        ("🔴 Market drops 10–15%", "warning",
         "Hold. Review what's causing the drop. If inflation-driven: gold and SGOV protect you. If recession-driven: add to SCHD, XLV. If tech-specific: do NOT add to tech yet — wait for stabilization around 200-day MA."),
        ("🔴 Market drops >20% (bear market)", "danger",
         "Execute your rebalancing plan. Move 5% from SGOV (dry powder) into VGT/SMH if tech is the cause of the drop. GLD and SCHD should be carrying the portfolio. Do not panic-sell. Review the crash history tab — this portfolio historically limits drawdown to ~17% vs market's ~47%."),
        ("🟡 Inflation rises above 4%", "warning",
         "Increase GLD from 12% to 15%. Consider adding PDBC. Reduce QQQ slightly (high valuations compress faster in inflation). Hold SGOV/USFR — they benefit directly from higher rates."),
        ("🟢 PCE falls below 2.5% for 3 months", "",
         "This is the Fed pivot signal. Begin rotating: reduce GLD/SLV by 5%, initiate a position in IEF (intermediate bonds), consider increasing tech allocation. Long bonds (TLT) become attractive again when inflation sustainably falls."),
        ("🟡 Iran deal confirmed — oil collapses", "warning",
         "Immediately trim XLE from 5% to 2–3%. Rotate proceeds into SCHD. Oil-price relief reduces inflation risk slightly, so gold may pull back 10–15% — that's normal. Hold GLD through it."),
        ("🟢 Fed signals rate cuts", "",
         "Start rotating SGOV/USFR into longer duration. Add XLU and SCHD (bond-proxy sectors benefit from falling rates). Tech rallies hard on rate cuts — your VGT position benefits automatically."),
    ]

    for title, cls, guidance in decisions:
        st.markdown(f"""<div class="signal-box {cls}">
<b>{title}</b><br>{guidance}
</div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("<small style='color:#555'>📌 This dashboard is for informational and educational purposes only. It does not constitute financial advice. Consult a fee-only fiduciary financial advisor before making investment decisions. Data provided by Yahoo Finance.</small>", unsafe_allow_html=True)
