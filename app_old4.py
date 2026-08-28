"""
All-Weather Portfolio Dashboard  v2
────────────────────────────────────
Improvements over v1:
  - Hybrid ETF + direct stock/bond portfolio option (sidebar toggle)
  - ETF vs Individual Stock comparison tab (new Tab 7)
  - Sharpe ratio, Sortino ratio, Calmar ratio in stats
  - Real-time dividend yield display for every holding
  - Correlation heatmap across all holdings (Tab 3)
  - Inflation-adjusted real return calculation
  - Recession indicator (yield curve inversion tracker)
  - Portfolio stress-test tab: models 2008, 2020, 2022 crashes
  - Better benchmark: each ETF matched to its closest index
  - Download button for full portfolio CSV
  - Weighted expense ratio updated automatically with allocation sliders
  - P/E fallbacks updated to June 2026 estimates
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

# ── Regime classifier (shared two-real-yield engine) ──────────────────────────
try:
    from regime_classifier import full_assessment, REGIMES, target_weights, BASE_WEIGHTS
    _REGIME_OK = True
except Exception:
    _REGIME_OK = False

# Educational signal guide (static — always renderable, no live data needed)
SIGNAL_GUIDE = [
    ("SHORT real policy rate (EFFR − CPI YoY)",
     "The true repression gauge — front-end real return to savers.",
     "Negative & inflation accelerating → tilt to real assets + trend, minimize "
     "cash. Crosses back positive → repression thesis weakening; trim metals."),
    ("LONG real yield level + momentum (DFII10)",
     "Whether long duration is a friend or a foe right now.",
     "Positive & RISING → hold TLT at 0% (it bleeds). Falling sharply (flight to "
     "quality) → switch TLT on."),
    ("Breakeven inflation (T10YIE)",
     "Splits nominal-yield moves into real vs. inflation-expectation.",
     "Rising via breakevens → inflationary, add real assets. Rising via REAL "
     "yields → tightening, pressure on growth/tech."),
    ("Stock / bond 60-day correlation",
     "Whether 60/40 diversification is working or broken.",
     "Flips POSITIVE → the #1 signal to INCREASE KMLM (trend replaces the "
     "failing bond hedge)."),
    ("HY credit OAS (BAMLH0A0HYM2)",
     "Onset of a liquidity / credit crisis — leads equities.",
     ">500 bps & widening >50 bps/2wk → CRISIS override: trim growth, switch TLT "
     "on, raise cash. Beats the inflation regime."),
    ("2s10s spread (DGS10 − DGS2)",
     "Recession lead — the re-steepening, not the inversion.",
     "Re-steepening from inversion → have defensives + contingent TLT ready "
     "before the downturn confirms."),
    ("VIX term structure",
     "Panic vs. normal volatility.",
     "Front-month > 3-month (backwardation) → late crisis signal; de-risk equity "
     "hard. Tail hedges must already be on."),
]
warnings.filterwarnings("ignore")

# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="All-Weather Portfolio Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .stApp { background-color: #0f1117; color: #e0e0e0; }
  [data-testid="metric-container"] {
      background: #1c1f2e; border: 1px solid #2a2d3e;
      border-radius: 10px; padding: 12px 16px;
  }
  [data-testid="metric-container"] label { color: #8b8fa8 !important; font-size:0.75rem !important; }
  [data-testid="metric-container"] [data-testid="stMetricValue"] { color:#fff !important; font-size:1.4rem !important; }
  [data-testid="metric-container"] [data-testid="stMetricDelta"] { font-size:0.8rem !important; }
  [data-testid="stSidebar"] { background-color:#13151f; border-right:1px solid #2a2d3e; }
  h1,h2,h3 { color:#ffffff !important; }
  .stTabs [data-baseweb="tab-list"] { background-color:#1c1f2e; border-radius:10px; padding:4px; }
  .stTabs [data-baseweb="tab"] { color:#8b8fa8; border-radius:8px; }
  .stTabs [aria-selected="true"] { background-color:#2d6a4f !important; color:white !important; }
  .signal-box {
      background:#1c1f2e; border-left:4px solid #2d6a4f;
      border-radius:0 8px 8px 0; padding:12px 16px;
      margin:8px 0; font-size:0.9rem; line-height:1.6;
  }
  .signal-box.warning { border-left-color:#e6a817; }
  .signal-box.danger  { border-left-color:#e05252; }
  .signal-box.info    { border-left-color:#4a90d9; }
  .signal-box.purple  { border-left-color:#9b59b6; }
  .section-card {
      background:#1c1f2e; border:1px solid #2a2d3e;
      border-radius:12px; padding:16px 20px; margin-bottom:16px;
  }
  hr { border-color:#2a2d3e !important; }
  [data-testid="stExpander"] { background:#1c1f2e; border:1px solid #2a2d3e; border-radius:10px; }
</style>
""", unsafe_allow_html=True)

# ─── PORTFOLIO DEFINITIONS ────────────────────────────────────────────────────

# ETF-based (original all-weather)
ETF_PORTFOLIO = {
    "VGT":  ("Vanguard Info Tech",       20, "Growth / Tech",     "QQQ",   "Nasdaq-100",  0.09),
    "SMH":  ("VanEck Semiconductors",     4, "Growth / Tech",     "SOXX",  "SOX Index",   0.35),
    "QQQ":  ("Invesco Nasdaq-100",        4, "Growth / Tech",     "SPY",   "S&P 500",     0.20),
    "GLD":  ("SPDR Gold Shares",         12, "Precious Metals",   "GLD",   "Gold Spot",   0.40),
    "SLV":  ("iShares Silver Trust",      5, "Precious Metals",   "SLV",   "Silver Spot", 0.50),
    "RING": ("iShares Gold Miners",       5, "Precious Metals",   "GDX",   "Gold Miners", 0.39),
    "XLE":  ("Energy Select SPDR",        5, "Commodities/Energy","XOP",   "Oil E&P",     0.09),
    "PDBC": ("Invesco Commodity",         3, "Commodities/Energy","DJP",   "Commodity",   0.59),
    "SCHD": ("Schwab Dividend Equity",   13, "Defensives",        "DVY",   "Dividend ETF",0.06),
    "XLV":  ("Health Care SPDR",          4, "Defensives",        "SPY",   "S&P 500",     0.09),
    "XLU":  ("Utilities SPDR",            3, "Defensives",        "SPY",   "S&P 500",     0.09),
    "SGOV": ("iShares 0-3M Treasury",     5, "Short Bonds/Cash",  "BIL",   "T-Bills",     0.09),
    "USFR": ("WisdomTree Float Rate",     3, "Short Bonds/Cash",  "FLOT",  "Float Rate",  0.15),
    # ── NEW: duration (contingent) + trend / crisis alpha ──────────────────────
    "TLT":  ("iShares 20+ Yr Treasury",  10, "Duration (contingent)", "IEF", "7-10Y Tsy", 0.15),
    "KMLM": ("KFA Mount Lucas Mgd Fut",   4, "Trend / Crisis Alpha",  "DBMF","Mgd Futures",0.90),
}

# Hybrid: direct stocks replacing ETFs where individual names add alpha
# thesis: avoid ETF dilution on highest-conviction names
HYBRID_PORTFOLIO = {
    # Growth — direct stocks instead of VGT/SMH/QQQ for no dilution
    "NVDA": ("NVIDIA Corporation",       14, "Growth / Tech",     "SMH",   "SOX Index",   0.00),
    "AAPL": ("Apple Inc.",                8, "Growth / Tech",     "QQQ",   "Nasdaq-100",  0.00),
    "MSFT": ("Microsoft Corporation",     8, "Growth / Tech",     "QQQ",   "Nasdaq-100",  0.00),
    "GOOGL":("Alphabet Inc.",             5, "Growth / Tech",     "QQQ",   "Nasdaq-100",  0.00),
    # Precious metals — ETFs still best here (no single-stock alternative)
    "GLD":  ("SPDR Gold Shares",         10, "Precious Metals",   "GLD",   "Gold Spot",   0.40),
    "SLV":  ("iShares Silver Trust",      4, "Precious Metals",   "SLV",   "Silver Spot", 0.50),
    "NEM":  ("Newmont Corporation",       4, "Precious Metals",   "GDX",   "Gold Miners", 0.00),
    # Energy — direct stocks for higher yield & oil price leverage
    "XOM":  ("Exxon Mobil Corp.",         5, "Commodities/Energy","XOP",   "Oil E&P",     0.00),
    "COP":  ("ConocoPhillips",            3, "Commodities/Energy","XOP",   "Oil E&P",     0.00),
    # Defensives — best dividend stocks directly
    "KO":   ("Coca-Cola Company",         4, "Defensives",        "XLP",   "Consumer Staples",0.00),
    "JNJ":  ("Johnson & Johnson",         4, "Defensives",        "XLV",   "Healthcare",  0.00),
    "UNH":  ("UnitedHealth Group",        3, "Defensives",        "XLV",   "Healthcare",  0.00),
    "NEE":  ("NextEra Energy",            3, "Defensives",        "XLU",   "Utilities",   0.00),
    # Financials — payment networks (not in ETF portfolio at all)
    "V":    ("Visa Inc.",                 3, "Defensives",        "XLF",   "Financials",  0.00),
    # Short bonds — still best as ETFs (no individual bond tracking)
    "SGOV": ("iShares 0-3M Treasury",    10, "Short Bonds/Cash",  "BIL",   "T-Bills",     0.09),
    "USFR": ("WisdomTree Float Rate",     5, "Short Bonds/Cash",  "FLOT",  "Float Rate",  0.15),
    # Individual TIPS bond for inflation protection
    "SCHP": ("Schwab TIPS ETF",           4, "Short Bonds/Cash",  "TIP",   "TIPS Index",  0.03),
}

CATEGORY_COLORS = {
    "Growth / Tech":         "#4CAF50",
    "Precious Metals":       "#FFA726",
    "Commodities/Energy":    "#EF5350",
    "Defensives":            "#42A5F5",
    "Short Bonds/Cash":      "#AB47BC",
    "Duration (contingent)": "#7C3AED",
    "Trend / Crisis Alpha":  "#EC4899",
}

BENCHMARKS = {
    "S&P 500":    "SPY",
    "Nasdaq-100": "QQQ",
    "Gold":       "GLD",
    "Bonds (AGG)":"AGG",
    "Dow Jones":  "DIA",
}

# ─── GROWTH SATELLITE UNIVERSE (Level 5.5) ────────────────────────────────────
# Sector/thematic rotation pool for the systematically-selected satellite
# sleeve layered on top of the core All-Weather allocation. Deliberately
# excludes GLD/SLV/RING/XLE/PDBC/SCHD/XLV/XLU/SGOV/USFR/TLT/KMLM — those are
# already governed by the regime classifier (Level 1) and would be double-
# scored under a cross-sectional momentum screen.
SATELLITE_UNIVERSE = {
    "XLK":  "Technology SPDR",
    "XLF":  "Financials SPDR",
    "XLI":  "Industrials SPDR",
    "XLY":  "Consumer Discretionary SPDR",
    "XLC":  "Communication Services SPDR",
    "XLB":  "Materials SPDR",
    "XLRE": "Real Estate SPDR",
    "QQQ":  "Nasdaq-100",
    "VGT":  "Vanguard Info Tech",
    "SMH":  "VanEck Semiconductors",
    "SOXX": "iShares Semiconductor",
    "IWM":  "Russell 2000",
    "IGV":  "iShares Expanded Tech-Software",
    "ARKK": "ARK Innovation",
}
SATELLITE_TOP_N   = 5   # live satellite holdings
SATELLITE_BENCH_N = 5   # ranks 6-10 tracked as promotion bench

# ─── ADDV LIQUIDITY TIERS — ported verbatim from the Institutional Rotation
# Dashboard's top_movers.py (same tier→threshold mapping, so a "vol spike" here
# means the same thing it means on that dashboard). VGT and ARKK aren't in that
# dashboard's own ETF_UNIVERSE, so their tiers are inferred, not copied —
# flagged below in case actual ADDV puts them in a different tier.
SATELLITE_TIER = {
    "XLK": 1, "XLF": 1, "QQQ": 1,                      # >$2B ADDV
    "XLI": 2, "XLY": 2, "XLC": 2, "XLB": 2, "XLRE": 2,  # $200M-$2B
    "IWM": 2,
    "VGT": 2,    # inferred — VGT not in source dashboard's universe
    "SMH": 3, "SOXX": 3, "IGV": 3,                      # $50M-$200M
    "ARKK": 3,   # inferred — ARKK not in source dashboard's universe
}
TIER_THRESHOLDS = {1: 1.25, 2: 1.50, 3: 2.00, 4: 3.00}  # ported verbatim

# Regime-conditional rotation targets for capital freed by a satellite exit
# when no qualifying bench name exists (or the exit was a broad Danger
# Composite trigger, not an idiosyncratic stop). Keys match regime_classifier's
# CURRENT 8 regime keys (verified against the live source, Aug 2026 — this
# module has moved well past the original 4-quadrant table: it now includes
# hard_repression, growth_scare, and a banded transition_ambiguous state)
# plus a "neutral" fallback for when no live key is set.
SATELLITE_ROTATION_TARGETS = {
    "inflationary_repression": ("GLD (momentum-gated) / KMLM / XLE+PDBC",
                                 "Neg short real + rising long real. Real assets WITH momentum + trend win; TLT stays at 0%, rate-sensitive growth compresses."),
    "hard_repression":         ("GLD / RING / SLV / TLT / KMLM",
                                 "Neg short real + long real FALLING/suppressed, credit calm — yield-curve-control signature. Peak debasement: metals+miners lead, duration works again, cash is worst asset."),
    "liquidity_crisis":        ("TLT / GLD / SGOV",
                                 "HY spreads blowing out, long real yields falling (flight to quality). Duration and cash are shock absorbers; metals may sell off first."),
    "stagflation":              ("KMLM / GLD / SGOV",
                                  "Neg short real + growth rolling over (2s10s re-steepening). Gold, trend, and defensives; cut cyclical growth and energy demand risk."),
    "goldilocks":               ("Core VGT/QQQ/SMH (regime is growth-additive) / SGOV",
                                  "Decisively positive real rates + tight credit + leadership intact. This regime ADDS growth — don't park freed capital defensively here, the base sleeve itself is the target."),
    "growth_scare":             ("SCHD / XLV / XLU / SGOV+USFR / KMLM",
                                  "Growth composite CONTRACTING (labour+consumer data deteriorating together), independent of real-rate sign. Cash-flow defensives + front-end carry + trend; duration deliberately NOT added — a growth scare and a fiscal/term-premium scare look identical early."),
    "transition_ambiguous":     ("Hold near base weights / SGOV",
                                  "Primary short-real-rate gauge is inside its own ±0.25% noise band (or a valuation/leadership guard blocked goldilocks) — express NEITHER the repression nor the reflation trade until it clears. Approximate: exact overlay lives in regime_bands.py, which I haven't verified line-by-line."),
    "neutral":                  ("SGOV / USFR",
                                  "No live regime read available — default to cash, no directional bet."),
}

NO_PE_SET = {"GLD","SLV","PDBC","SGOV","USFR","BIL","FLOT","DJP","TIP","SCHP","TLT","KMLM","IEF","DBMF"}

# P/E fallbacks — June 2026 estimates
PE_FALLBACK = {
    "VGT":  {"trailingPE":34.2,"forwardPE":28.1,"priceToBook":11.8},
    "SMH":  {"trailingPE":29.6,"forwardPE":22.4,"priceToBook":7.4},
    "QQQ":  {"trailingPE":32.5,"forwardPE":26.8,"priceToBook":10.2},
    "RING": {"trailingPE":18.3,"forwardPE":14.9,"priceToBook":2.1},
    "XLE":  {"trailingPE":14.2,"forwardPE":12.8,"priceToBook":2.3},
    "SCHD": {"trailingPE":17.4,"forwardPE":15.9,"priceToBook":3.8},
    "XLV":  {"trailingPE":20.1,"forwardPE":17.6,"priceToBook":4.9},
    "XLU":  {"trailingPE":22.3,"forwardPE":19.8,"priceToBook":2.6},
    "NVDA": {"trailingPE":44.1,"forwardPE":27.8,"priceToBook":38.2},
    "AAPL": {"trailingPE":34.9,"forwardPE":30.2,"priceToBook":51.4},
    "MSFT": {"trailingPE":31.4,"forwardPE":27.6,"priceToBook":12.8},
    "GOOGL":{"trailingPE":22.8,"forwardPE":19.4,"priceToBook":7.1},
    "XOM":  {"trailingPE":14.6,"forwardPE":13.1,"priceToBook":2.1},
    "COP":  {"trailingPE":13.4,"forwardPE":11.8,"priceToBook":2.9},
    "KO":   {"trailingPE":24.2,"forwardPE":21.8,"priceToBook":9.8},
    "JNJ":  {"trailingPE":14.8,"forwardPE":13.2,"priceToBook":4.1},
    "UNH":  {"trailingPE":16.2,"forwardPE":14.8,"priceToBook":5.3},
    "NEE":  {"trailingPE":22.1,"forwardPE":19.4,"priceToBook":3.2},
    "V":    {"trailingPE":33.4,"forwardPE":27.2,"priceToBook":15.6},
    "NEM":  {"trailingPE":18.3,"forwardPE":14.1,"priceToBook":2.4},
    "SCHP": {"trailingPE":None,"forwardPE":None,"priceToBook":None},
    "SPY":  {"trailingPE":27.3,"forwardPE":22.9,"priceToBook":5.0},
}

# Dividend yields (%) — June 2026 estimates
DIV_YIELDS = {
    "VGT":0.6,"SMH":0.5,"QQQ":0.5,"GLD":0.0,"SLV":0.0,"RING":1.5,
    "XLE":3.7,"PDBC":0.0,"SCHD":3.3,"XLV":1.7,"XLU":3.3,"SGOV":5.1,"USFR":5.0,
    "TLT":4.3,"KMLM":0.0,
    "NVDA":0.03,"AAPL":0.52,"MSFT":0.82,"GOOGL":0.45,"XOM":3.4,"COP":3.1,
    "KO":3.1,"JNJ":3.1,"UNH":1.92,"NEE":3.1,"V":0.74,"NEM":1.8,"SCHP":2.1,"NEM":1.8,
}

# ─── CRASH SCENARIO DATA ─────────────────────────────────────────────────────
CRASH_SCENARIOS = {
    "2008 GFC": {
        "period": "Oct 2007 – Mar 2009",
        "spy_drop": -57.0,
        "asset_returns": {
            "SPY":-57,"QQQ":-50,"VGT":-55,"SMH":-55,"GLD":+25,"SLV":-25,
            "RING":-65,"XLE":-55,"PDBC":-50,"SCHD":-45,"XLV":-37,"XLU":-29,
            "SGOV":+3,"USFR":+3,"AGG":+5,"TLT":+34,"KMLM":+20,
            "NVDA":-85,"AAPL":-60,"MSFT":-50,"GOOGL":-65,"XOM":-55,"COP":-70,
            "KO":-20,"JNJ":-25,"UNH":-45,"NEE":-35,"V":-60,"NEM":-20,"SCHP":+10,
        },
    },
    "2020 COVID": {
        "period": "Feb 19 – Mar 23, 2020",
        "spy_drop": -34.0,
        "asset_returns": {
            "SPY":-34,"QQQ":-29,"VGT":-30,"SMH":-28,"GLD":-12,"SLV":-22,
            "RING":-30,"XLE":-57,"PDBC":-45,"SCHD":-33,"XLV":-26,"XLU":-22,
            "SGOV":+1,"USFR":+1,"AGG":+2,"TLT":+14,"KMLM":+3,
            "NVDA":-28,"AAPL":-30,"MSFT":-26,"GOOGL":-30,"XOM":-57,"COP":-60,
            "KO":-22,"JNJ":-18,"UNH":-24,"NEE":-20,"V":-25,"NEM":-15,"SCHP":+3,
        },
    },
    "2022 Rate Hike": {
        "period": "Jan – Oct 2022",
        "spy_drop": -25.0,
        "asset_returns": {
            "SPY":-25,"QQQ":-35,"VGT":-30,"SMH":-34,"GLD":-3,"SLV":-15,
            "RING":-15,"XLE":+65,"PDBC":+20,"SCHD":-16,"XLV":-10,"XLU":-8,
            "SGOV":+2,"USFR":+3,"AGG":-16,"TLT":-33,"KMLM":+28,
            "NVDA":-68,"AAPL":-25,"MSFT":-30,"GOOGL":-40,"XOM":+30,"COP":+45,
            "KO":-1,"JNJ":-5,"UNH":+6,"NEE":-12,"V":-8,"NEM":-10,"SCHP":-12,
        },
    },
    "1973 Stagflation": {
        "period": "Jan 1973 – Oct 1974",
        "spy_drop": -48.0,
        "asset_returns": {
            "SPY":-48,"QQQ":-60,"VGT":-60,"SMH":-60,"GLD":+240,"SLV":+315,
            "RING":+200,"XLE":+40,"PDBC":+50,"SCHD":-25,"XLV":-20,"XLU":-30,
            "SGOV":+8,"USFR":+8,"AGG":-5,"TLT":-40,"KMLM":+45,
            "NVDA":None,"AAPL":None,"MSFT":None,"GOOGL":None,"XOM":+40,"COP":+50,
            "KO":-25,"JNJ":-22,"UNH":None,"NEE":-30,"V":None,"NEM":+200,"SCHP":+15,
        },
    },
}

# ─── DATA HELPERS ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_prices(tickers: list, period: str = "1y") -> pd.DataFrame:
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
def fetch_live_pe(ticker: str) -> dict:
    if ticker in NO_PE_SET:
        return {"trailingPE":None,"forwardPE":None,"priceToBook":None,"dividendYield":None}
    try:
        info = yf.Ticker(ticker).info
        trailing = info.get("trailingPE")
        forward  = info.get("forwardPE")
        ptb      = info.get("priceToBook")
        dy       = info.get("dividendYield")
        return {
            "trailingPE":   round(float(trailing),1) if trailing else None,
            "forwardPE":    round(float(forward), 1) if forward  else None,
            "priceToBook":  round(float(ptb),     2) if ptb      else None,
            "dividendYield":round(float(dy)*100,  2) if dy       else None,
        }
    except:
        return {"trailingPE":None,"forwardPE":None,"priceToBook":None,"dividendYield":None}

def get_pe(ticker: str) -> dict:
    live = fetch_live_pe(ticker)
    if live.get("trailingPE") is not None:
        return live
    return {**live, **PE_FALLBACK.get(ticker, {})}

def pe_badge(pe) -> str:
    if pe is None: return "—"
    if pe < 15:   return f"🟢 {pe:.1f}x"
    if pe < 25:   return f"🟡 {pe:.1f}x"
    if pe < 35:   return f"🟠 {pe:.1f}x"
    return f"🔴 {pe:.1f}x"

def calc_stats(price_series: pd.Series) -> dict:
    daily = price_series.pct_change().dropna()
    if len(daily) < 2:
        return {"total_return":0,"ann_vol":0,"sharpe":0,"sortino":0,"max_drawdown":0,"calmar":0}
    total_ret  = (price_series.iloc[-1] / price_series.iloc[0] - 1) * 100
    ann_vol    = daily.std() * np.sqrt(252) * 100
    # Sharpe (using 5% risk-free rate)
    ann_ret    = ((price_series.iloc[-1] / price_series.iloc[0]) ** (252/len(daily)) - 1) * 100
    sharpe     = (ann_ret - 5.0) / ann_vol if ann_vol > 0 else 0
    # Sortino (downside deviation only)
    downside   = daily[daily < 0].std() * np.sqrt(252) * 100
    sortino    = (ann_ret - 5.0) / downside if downside > 0 else 0
    # Max drawdown
    cum        = (1 + daily).cumprod()
    peak       = cum.cummax()
    drawdown   = ((cum / peak - 1).min()) * 100
    # Calmar
    calmar     = ann_ret / abs(drawdown) if drawdown != 0 else 0
    return {
        "total_return": round(total_ret, 2),
        "ann_vol":      round(ann_vol,   2),
        "sharpe":       round(sharpe,    2),
        "sortino":      round(sortino,   2),
        "max_drawdown": round(drawdown,  2),
        "calmar":       round(calmar,    2),
    }

def fmt(v): return f"{'+' if v>=0 else ''}{v:.1f}%"

def total_return_with_yield(price_ret: float, ticker: str, period: str) -> float:
    """
    Add the income/yield component to the price return so the dashboard
    shows TRUE total return — not just price appreciation.

    For SGOV/USFR this is critical: they show ~0% price return but earn
    5%+ in distributions. Without this, cash positions look like dead weight.

    Income contribution = annual_yield * fraction_of_year elapsed
    """
    years_map = {
        "1mo": 1/12, "3mo": 3/12, "6mo": 6/12,
        "1y": 1.0,   "2y": 2.0,   "5y": 5.0,
    }
    years = years_map.get(period, 1.0)
    ann_yield = DIV_YIELDS.get(ticker, 0.0)
    income_contribution = ann_yield * years        # e.g. 5.1% * 1yr = 5.1%
    return price_ret + income_contribution

def build_total_return_series(price_series: pd.Series, ticker: str, period: str) -> pd.Series:
    """
    Build a daily total-return series by linearly accruing yield on top
    of the price-return series. This gives a more accurate cumulative
    return chart for income-producing holdings (SGOV, SCHD, XLE, etc.).

    Method: compound daily yield accrual onto the price return series.
    daily_yield_rate = (1 + ann_yield/100)^(1/252) - 1
    total_return[t] = price_return[t] * (1 + daily_yield_rate)^t
    """
    ann_yield = DIV_YIELDS.get(ticker, 0.0) / 100
    daily_yield = (1 + ann_yield) ** (1/252) - 1
    n = len(price_series)
    yield_multiplier = pd.Series(
        [(1 + daily_yield) ** i for i in range(n)],
        index=price_series.index
    )
    # Normalise price series to start at 1, apply yield accrual
    norm = price_series / price_series.iloc[0]
    total = norm * yield_multiplier
    return total

# ─── GROWTH SATELLITE HELPERS (Level 5.5 / Level 6.5) ─────────────────────────
@st.cache_data(ttl=3600)
def fetch_ohlcv(tickers: list, period: str = "2y") -> dict:
    """Full OHLCV per ticker — fetch_prices() only keeps Close, but ADX/ATR/
    volume-conviction/Danger-Composite all need High/Low/Volume too."""
    out = {}
    try:
        raw = yf.download(tickers, period=period, auto_adjust=True,
                           progress=False, group_by="ticker")
        for t in tickers:
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = df.dropna(how="all")
                if not df.empty:
                    out[t] = df
            except Exception:
                continue
    except Exception as e:
        st.warning(f"OHLCV fetch error: {e}")
    return out

def ma_slope_gate(close: pd.Series, ma_len: int = 200, slope_lookback: int = 20) -> dict:
    """Trend-health gate (same convention as the Strategas-style 200MA slope
    overlay): price above the MA AND the MA itself rising over slope_lookback
    bars. Both conditions must pass for a name to be selection-eligible."""
    if len(close) < ma_len + slope_lookback:
        return {"pass": False, "price_above_ma": None, "slope_rising": None, "ma": None}
    ma = close.rolling(ma_len).mean()
    price_above  = bool(close.iloc[-1] > ma.iloc[-1])
    slope_rising = bool(ma.iloc[-1] > ma.iloc[-1 - slope_lookback])
    return {
        "pass": price_above and slope_rising,
        "price_above_ma": price_above,
        "slope_rising": slope_rising,
        "ma": float(ma.iloc[-1]),
        "pct_above_ma": float((close.iloc[-1] / ma.iloc[-1] - 1) * 100),
    }

def calc_adx(df: pd.DataFrame, period: int = 14) -> float | None:
    """Standard Wilder ADX — the trend-strength component of the composite
    score, and the same ADX>25 test used in the KMLM sizing signal."""
    if df is None or len(df) < period * 2 or not {"High","Low","Close"}.issubset(df.columns):
        return None
    high, low, close = df["High"], df["Low"], df["Close"]
    up_move, down_move = high.diff(), -low.diff()
    plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = pd.concat([(high - low), (high - close.shift()).abs(),
                     (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    plus_di  = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, min_periods=period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, min_periods=period).mean() / atr
    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1/period, min_periods=period).mean().dropna()
    return float(adx.iloc[-1]) if len(adx) else None

def calc_atr(df: pd.DataFrame, period: int = 14) -> float | None:
    """Wilder ATR — feeds both the Level 6 stop and the R-multiple unit used
    in the Level 6.5 trim schedule below."""
    if df is None or len(df) < period + 1 or not {"High","Low","Close"}.issubset(df.columns):
        return None
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([(high - low), (high - close.shift()).abs(),
                     (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period).mean().dropna()
    return float(atr.iloc[-1]) if len(atr) else None

def _pct(series: pd.Series, days_back: int) -> float:
    """% change from days_back trading days ago to latest close — ported from
    the Institutional Rotation Dashboard's data_fetcher.py (_pct_change)."""
    recent = series.dropna()
    if len(recent) < 2:
        return 0.0
    start_idx = max(0, len(recent) - days_back - 1)
    start_price = recent.iloc[start_idx]
    if start_price == 0:
        return 0.0
    return float((recent.iloc[-1] / start_price - 1) * 100)

def _to_rs(perf_pct: float, benchmark_pct: float) -> float:
    """Relative Strength ratio normalized to 100 — ported verbatim from the
    Institutional Rotation Dashboard's rotation_math.py."""
    s = 1 + perf_pct / 100
    b = 1 + benchmark_pct / 100
    return (s / b) * 100 if b != 0 else 100.0

def compute_universe_rrg(perf_df: pd.DataFrame) -> pd.DataFrame:
    """RRG quadrant classification — ported from the Institutional Rotation
    Dashboard's rotation_math.py, same default (3M-toggle) timeframe pair:
    RS-Ratio = RS at 1Y, RS-Momentum = RS at 6M / RS at 1Y. Benchmark is the
    EQUAL-WEIGHTED MEAN of the universe being scored (not SPY) — this is the
    one thing a naive "vs S&P 500" RRG gets wrong, and matches exactly how
    the money-flow dashboard computes it. perf_df needs columns perf_1w,
    perf_1m, perf_3m, perf_6m, perf_1y."""
    df = perf_df.copy()
    for tf in ["1w", "1m", "3m", "6m", "1y"]:
        col = f"perf_{tf}"
        bm = df[col].mean()
        df[f"rs_{tf}"] = df[col].apply(lambda v: _to_rs(v, bm))
    df["rs_ratio"]    = df["rs_1y"]
    df["rs_momentum"] = 100 * df["rs_6m"] / df["rs_1y"]

    def _quad(row):
        r, m = row["rs_ratio"], row["rs_momentum"]
        if r >= 100 and m >= 100: return "Leading"
        if r >= 100 and m <  100: return "Weakening"
        if r <  100 and m <  100: return "Lagging"
        return "Improving"
    df["quadrant"] = df.apply(_quad, axis=1)
    return df

def _vol_ratio(volume: pd.Series) -> float:
    """5-day recent avg vs prior 20-day baseline — ported from the CURRENT
    (v4) Institutional Rotation Dashboard top_movers.py. Verified against
    live source: this is explicitly UNCHANGED from v3 per that file's own
    changelog, despite an earlier app.py docstring implying a today-vs-20-day
    version — that docstring was describing a different badge computation,
    not this function. Confirmed directly against the current file."""
    v = volume.dropna()
    if len(v) < 25:
        return 1.0
    recent = v.iloc[-5:].mean()
    baseline = v.iloc[-25:-5].mean()
    return round(float(recent / baseline), 2) if baseline != 0 else 1.0

# ─── DIRECTIONAL FLOW (CMF-based) — ported from flow_metrics.py ──────────────
# The Institutional Rotation Dashboard's v3 _flow_score() (momentum/accel/
# vol-conviction/consistency weighted sum) is GONE as of top_movers.py v4.
# Its own changelog: "The old composite awarded a FLAT +8 for crossing the
# volume-spike threshold while its entire momentum term spanned roughly ±2,
# so a single loud session outweighed any realistic momentum difference ~4x
# ... the exact INVERSION of this framework's stated thesis that loud volume
# is retail and institutions accumulate quietly." It's been replaced by two
# scores computed from actual High/Low/Close/Volume (not Close alone) via
# the Chaikin Money Flow multiplier, reported side by side and NEVER summed:
#   accumulation_score — quiet, sustained, directional buying (Tier B)
#   event_score        — loud activity + which side it closed on
_TREND_CAP = 5.0
DIVERGENCE_SCALE = 2.0
MIN_BARS_FLOW = 63   # matches flow_metrics.py's MIN_BARS_STEALTH

def money_flow_multiplier(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Per-session directional weight in [-1, +1]. High==Low sessions (limit
    moves, halts) get 0.0 rather than NaN/inf, per the source's own rule."""
    rng = (high - low)
    mfm = ((close - low) - (high - close)) / rng.replace(0, np.nan)
    return mfm.fillna(0.0)

def money_flow_volume(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    return money_flow_multiplier(high, low, close) * volume

def ad_line(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Cumulative signed volume — the real A/D line, replacing the old
    price-only "spread" that had no volume term at all."""
    return money_flow_volume(high, low, close, volume).cumsum()

def chaikin_money_flow(high: pd.Series, low: pd.Series, close: pd.Series,
                        volume: pd.Series, period: int = 21) -> pd.Series:
    """CMF = sum(money-flow volume, period) / sum(volume, period) ∈ [-1, +1].
    >+0.10 strong buying · >+0.05 buying · -0.05..+0.05 neutral ·
    <-0.05 selling · <-0.10 strong selling."""
    if len(close.dropna()) < period:
        return pd.Series(np.nan, index=close.index)
    mfv = money_flow_volume(high, low, close, volume)
    vol_sum = volume.rolling(period).sum()
    return mfv.rolling(period).sum() / vol_sum.replace(0, np.nan)

def _trend_strength(s: pd.Series, window: int) -> float:
    """Least-squares slope over `window` bars, normalized by the series' own
    daily-change volatility — dimensionless, comparable across the A/D
    line (signed shares) and price (dollars)."""
    s = s.dropna()
    if len(s) < window:
        return float("nan")
    y = s.iloc[-window:].to_numpy(dtype=float)
    x = np.arange(window, dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    noise = float(np.std(np.diff(y)))
    if noise == 0.0:
        tol = 1e-9 * max(1.0, float(np.abs(y).mean()))
        return 0.0 if abs(slope) <= tol else float(np.sign(slope) * _TREND_CAP)
    return float(np.clip(slope / noise, -_TREND_CAP, _TREND_CAP))

def cmf_persistence(cmf: pd.Series, window: int = 21) -> float:
    """Fraction of the last `window` sessions with positive CMF, in [0,1]."""
    c = cmf.dropna()
    if len(c) < window:
        return float("nan")
    return float((c.iloc[-window:] > 0).mean())

def ad_price_divergence(high, low, close, volume, window: int = 21) -> float:
    """(normalized A/D slope) - (normalized price slope). >0 = A/D trending
    up harder than price = absorption/accumulation. A sector making new
    highs on a FALLING A/D line is distribution-into-strength — invisible
    to any price-only or undirected-volume signal."""
    ad = ad_line(high, low, close, volume)
    return _trend_strength(ad, window) - _trend_strength(close, window)

def accumulation_score(high, low, close, volume, vol_ratio: float,
                        tier_threshold: float, window: int = 21) -> float:
    """QUIET accumulation, roughly -100..+100. CMF level (±35) + persistence
    (±25) + A/D-vs-price divergence (±25) + quietness (±15, PENALIZES loud
    names rather than just failing to reward them). Ported from
    flow_metrics.py's accumulation_score()."""
    if len(close.dropna()) < MIN_BARS_FLOW:
        return float("nan")
    cmf = chaikin_money_flow(high, low, close, volume, period=window)
    if not cmf.notna().any():
        return float("nan")
    cmf_now = float(cmf.dropna().iloc[-1])
    persist = cmf_persistence(cmf, window)
    diverg = ad_price_divergence(high, low, close, volume, window)
    if any(pd.isna(v) for v in (persist, diverg)):
        return float("nan")
    cmf_pts = float(np.clip(cmf_now / 0.20, -1, 1) * 35)
    persist_pts = float(np.clip((persist - 0.5) / 0.5, -1, 1) * 25)
    diverg_pts = float(np.clip(diverg / DIVERGENCE_SCALE, -1, 1) * 25)
    if vol_ratio < tier_threshold:
        quiet_pts = 15.0
    else:
        excess = (vol_ratio - tier_threshold) / max(tier_threshold, 1e-9)
        quiet_pts = float(-15.0 * np.clip(excess, 0, 1))
    return round(cmf_pts + persist_pts + diverg_pts + quiet_pts, 2)

def event_score(high, low, close, volume, vol_ratio: float, tier_threshold: float) -> dict:
    """LOUD activity, 0-100 — "something happened, go find out what." NOT an
    accumulation signal; reported alongside accumulation_score, never summed
    with it. Direction comes from the money-flow multiplier, not trailing
    price sign — a spike closing on the low is a selling event even in a
    green month."""
    out = {"event_score": 0.0, "event_direction": "None", "spike": False}
    if len(close.dropna()) < 2 or vol_ratio is None or pd.isna(vol_ratio):
        return out
    spike = bool(vol_ratio >= tier_threshold)
    out["spike"] = spike
    mfm = money_flow_multiplier(high, low, close)
    mfm_now = float(mfm.iloc[-1]) if len(mfm) else float("nan")
    magnitude = float(np.clip((vol_ratio / tier_threshold - 1) / 1.0, 0, 1) * 60)
    base = 40.0 if spike else 0.0
    out["event_score"] = round(base + magnitude, 2)
    if not spike:
        out["event_direction"] = "None"
    elif mfm_now > 0.3:
        out["event_direction"] = "Buying event"
    elif mfm_now < -0.3:
        out["event_direction"] = "Selling event"
    else:
        out["event_direction"] = "Two-sided / unresolved"
    return out

def signal_label(cmf: float, vol_spike: bool) -> str:
    """Signal label driven by CMF direction — ported from the current
    top_movers.py _signal_label(). Quiet + strong CMF = Accumulation tier;
    loud + strong CMF = Event tier (same pressure, different loudness)."""
    quiet = not vol_spike
    if cmf is None or pd.isna(cmf):
        return "Neutral (px only)"
    if cmf >= 0.10:
        return "Strong Accumulation" if quiet else "Buying Event"
    if cmf >= 0.05:
        return "Accumulation" if quiet else "Inflow"
    if cmf <= -0.10:
        return "Strong Distribution" if quiet else "Selling Event"
    if cmf <= -0.05:
        return "Distribution" if quiet else "Outflow"
    return "Neutral"

def calc_danger_composite(close: pd.Series, volume: pd.Series, basket_closes: dict,
                           ma_len: int = 200, basket_lookback: int = 10) -> dict:
    """Level 6.5 Danger Signal Composite (0-10). basket_closes = the OTHER
    current satellite holdings' close series, used for the correlated-basket
    simultaneous-peak component (two or more thesis-linked names topping in
    the same short window = sector-wide euphoria, not single-name strength)."""
    pts, detail = 0, {}
    roc21 = (close.iloc[-1]/close.iloc[-22]-1)*100 if len(close) > 22 else 0
    roc63 = (close.iloc[-1]/close.iloc[-64]-1)*100 if len(close) > 64 else 0
    p1 = 3 if roc21 > 100 else 0
    p2 = 2 if roc63 > 150 else 0
    pts += p1 + p2; detail["Parabolic ROC"] = p1 + p2
    if len(close) >= ma_len + 252:
        ma  = close.rolling(ma_len).mean()
        ext = (close/ma - 1) * 100
        pct = ext.tail(252).rank(pct=True).iloc[-1] * 100
        p3  = 2 if pct >= 90 else 0
    else:
        p3 = 0
    pts += p3; detail["MA Extension %ile"] = p3
    if volume is not None and len(volume) >= 20:
        vavg, vstd = volume.tail(20).mean(), volume.tail(20).std()
        vz = (volume.iloc[-1]-vavg)/vstd if vstd else 0
        p4 = 1 if vz >= 2 else 0
    else:
        p4 = 0
    pts += p4; detail["Volume Climax"] = p4
    self_high = close.iloc[-1] >= close.tail(basket_lookback).max()
    peak_ct = int(self_high)
    for bc in basket_closes.values():
        if len(bc) >= basket_lookback and bc.iloc[-1] >= bc.tail(basket_lookback).max():
            peak_ct += 1
    p5 = 2 if peak_ct >= 2 else 0
    pts += p5; detail["Basket Confirm"] = p5
    zone = "Euphoria" if pts >= 6 else ("Elevated" if pts >= 3 else "Normal")
    return {"score": pts, "zone": zone, "detail": detail}

CHART_BG = dict(
    paper_bgcolor="#0f1117", plot_bgcolor="#13151f",
    font=dict(color="#c0c4d6",size=12),
    xaxis=dict(gridcolor="#2a2d3e",showgrid=True,zeroline=False),
    yaxis=dict(gridcolor="#2a2d3e",showgrid=True,zeroline=True,zerolinecolor="#3a3d4e"),
    legend=dict(bgcolor="rgba(0,0,0,0)",font=dict(size=11)),
    margin=dict(l=10,r=10,t=40,b=10),
    hovermode="x unified",
)

# ─── LIVE CPI HELPER ──────────────────────────────────────────────────────────
@st.cache_data(ttl=6 * 3600)
def get_live_cpi_yoy(fred_key: str = "") -> float | None:
    """Latest CPI YoY (%) from FRED CPIAUCNS — NOT seasonally adjusted.

    CPI series discipline (non-negotiable, per framework): always compute CPI
    YoY from CPIAUCNS, never CPIAUCSL. CPIAUCNS is what BLS's officially-quoted
    headline inflation figure is actually calculated from. CPIAUCSL's seasonal
    factors are re-revised every February, reshuffling trailing SA values in a
    way that can diverge from the quoted headline by several tenths of a
    point — enough to flip a real-rate sign call (short real rate = EFFR minus
    this CPI YoY). If you need to show SA alongside, fine — but never feed it
    into the short-real-rate math.

    Returns None if unavailable (e.g. no API key or network issue), so the
    caller can fall back."""
    if not fred_key:
        return None
    try:
        import requests
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": "CPIAUCNS", "api_key": fred_key,
                    "file_type": "json", "observation_start": "2022-01-01"},
            timeout=15,
        )
        r.raise_for_status()
        obs = [o for o in r.json().get("observations", [])
               if o["value"] not in (".", "", None)]
        if len(obs) < 13:
            return None
        latest = float(obs[-1]["value"])
        year_ago = float(obs[-13]["value"])
        return round((latest / year_ago - 1) * 100, 1)
    except Exception:
        return None


# ─── SIDEBAR ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Dashboard Settings")
    st.markdown("---")

    # Portfolio mode toggle
    portfolio_mode = st.radio(
        "Portfolio Mode",
        ["ETF All-Weather", "Hybrid (Stocks + ETFs)"],
        index=0,
        help="ETF: broad diversification via funds. Hybrid: direct stocks for highest-conviction names + ETFs for everything else.",
    )
    PORTFOLIO = ETF_PORTFOLIO if portfolio_mode == "ETF All-Weather" else HYBRID_PORTFOLIO

    period_map = {
        "1 Month":"1mo","3 Months":"3mo","6 Months":"6mo",
        "1 Year":"1y","2 Years":"2y","5 Years":"5y",
    }
    period_label = st.selectbox("Time Period", list(period_map.keys()), index=3)
    period = period_map[period_label]

    st.markdown("---")
    fred_key_input = st.text_input(
        "FRED API key (optional)", type="password",
        help="Enables the LIVE regime banner in the Education tab. Free key at "
             "fredaccount.stlouisfed.org. Without it, the static signal guide "
             "and quadrant map still render.",
    )

    st.markdown("---")
    st.markdown("### Allocation Weights")
    st.markdown("*Drag to model changes:*")

    custom_allocs = {}
    total_w = 0
    for ticker, (name, alloc, cat, *_) in PORTFOLIO.items():
        val = st.slider(ticker, 0, 35, alloc, 1, key=f"w_{ticker}",
                        help=f"{name} — {cat}")
        custom_allocs[ticker] = val
        total_w += val

    diff_from_100 = total_w - 100
    if diff_from_100 == 0:
        st.success(f"✅ Total: 100% — Balanced")
    else:
        col = "🔴" if diff_from_100 > 0 else "🟡"
        st.warning(f"{col} Total: {total_w}% ({'+' if diff_from_100>0 else ''}{diff_from_100}% from 100%)")

    st.markdown("---")
    alert_thresh = st.slider("Lag alert threshold (%)", 2, 20, 5, 1)

    # Inflation rate for real-return calc — defaults to LIVE CPI YoY from FRED
    _live_cpi = get_live_cpi_yoy(fred_key_input)
    _cpi_default = _live_cpi if _live_cpi is not None else 4.2
    cpi_rate = st.slider("CPI inflation rate (%)", 1.0, 8.0, _cpi_default, 0.1,
                         help="Defaults to live CPI YoY from FRED when a key is "
                              "set (sidebar); otherwise a recent fallback. Drag "
                              "to model scenarios.")
    if _live_cpi is not None:
        st.caption(f"↑ Live CPI YoY (FRED): {_live_cpi}%")
    else:
        st.caption("↑ Fallback CPI — add a FRED key above for the live value")

    st.markdown("---")
    st.markdown("<small style='color:#555'>Data via Yahoo Finance · Refreshes hourly<br>⚠️ Not financial advice</small>",
                unsafe_allow_html=True)

# ─── HEADER ──────────────────────────────────────────────────────────────────
mode_badge = "🧩 Hybrid Mode" if portfolio_mode == "Hybrid (Stocks + ETFs)" else "📦 ETF Mode"
st.markdown(f"# 📊 All-Weather Portfolio Dashboard  <small style='font-size:0.5em;color:#888'>{mode_badge}</small>",
            unsafe_allow_html=True)
st.markdown(f"<small style='color:#666'>Updated: {datetime.now().strftime('%B %d, %Y %H:%M')} · Period: {period_label} · CPI: {cpi_rate}%</small>",
            unsafe_allow_html=True)
st.markdown("---")

# ─── TABS ─────────────────────────────────────────────────────────────────────
tab1,tab2,tab3,tab4,tab5,tab6,tab7,tab8,tab9 = st.tabs([
    "🏠 Overview",
    "📈 Holding vs Benchmark",
    "🗂️ Category Performance",
    "🏗️ Construction & P/E",
    "📡 Market Signals",
    "💥 Stress Test",
    "⚖️ ETF vs Stocks",
    "📚 Education",
    "🛰️ Growth Satellite",
])

# ════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### Portfolio Snapshot")

    all_tix = list(dict.fromkeys(list(PORTFOLIO.keys()) + list(BENCHMARKS.values()) + ["AGG","^TNX","^VIX"]))
    prices  = fetch_prices(all_tix, period)

    if prices.empty:
        st.error("Unable to fetch market data.")
    else:
        # ── Weighted portfolio TOTAL return (price + yield accrual) ──────────
        port_series_price = None   # price-only (for ratio chart)
        port_series_total = None   # total return incl. yield
        port_return_price = 0.0
        port_return_total = 0.0

        for ticker, (_, alloc, *_) in PORTFOLIO.items():
            w = custom_allocs.get(ticker, alloc) / 100
            if ticker in prices.columns:
                s = prices[ticker].dropna()
                # Price return series
                price_daily = s.pct_change().fillna(0)
                port_series_price = (
                    price_daily * w if port_series_price is None
                    else port_series_price.add(price_daily * w, fill_value=0)
                )
                price_ret = (s.iloc[-1] / s.iloc[0] - 1) * 100
                port_return_price += price_ret * w

                # Total return = price + yield
                tr = build_total_return_series(s, ticker, period)
                tr_daily = tr.pct_change().fillna(0)
                port_series_total = (
                    tr_daily * w if port_series_total is None
                    else port_series_total.add(tr_daily * w, fill_value=0)
                )
                tot_ret = total_return_with_yield(price_ret, ticker, period)
                port_return_total += tot_ret * w

        def _ret(tkr):
            if tkr in prices.columns:
                s = prices[tkr].dropna()
                return (s.iloc[-1] / s.iloc[0] - 1) * 100 if len(s) > 1 else 0.0
            return 0.0

        spy_ret = _ret("SPY")
        qqq_ret = _ret("QQQ")
        gld_ret = _ret("GLD")
        agg_ret = _ret("AGG")

        # SPY total return (incl. ~1% yield)
        spy_total = total_return_with_yield(spy_ret, "SPY", period)
        qqq_total = total_return_with_yield(qqq_ret, "QQQ", period)

        # Real return (inflation-adjusted) — use TOTAL return as base
        years = {"1mo":1/12,"3mo":3/12,"6mo":6/12,"1y":1,"2y":2,"5y":5}.get(period,1)
        inflation_drag = ((1+cpi_rate/100)**years - 1)*100
        real_return = port_return_total - inflation_drag

        # Income contribution (yield-only portion)
        income_contrib = port_return_total - port_return_price

        # ── KPI metrics ──────────────────────────────────────────────────────
        st.markdown(
            '<div style="background:rgba(0,230,118,0.06);border:1px solid rgba(0,230,118,0.2);'
            'border-radius:8px;padding:8px 14px;margin-bottom:12px;font-size:12px;color:#9ca3af">'
            '&#9432; <b style="color:#00E676">Total Return</b> = price appreciation + '
            'dividend/yield income. Income from SGOV/USFR (~5%), SCHD (~3.3%), XLE (~3.7%) '
            'is added to price return so holdings are not understated.'
            '</div>',
            unsafe_allow_html=True,
        )

        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric(
            "Total Return (price+yield)",
            fmt(port_return_total),
            f"vs S&P {fmt(port_return_total - spy_total)}",
            help="Price return + dividend/income yield contribution over the period",
        )
        c2.metric(
            "Price Return only",
            fmt(port_return_price),
            f"Income adds {fmt(income_contrib)}",
            help="Pure price appreciation — excludes dividends and distributions",
        )
        c3.metric(
            "Real Return (CPI-adj)",
            fmt(real_return),
            f"inflation drag: {fmt(-inflation_drag)}",
        )
        c4.metric("S&P 500 Total Return", fmt(spy_total))
        c5.metric("Nasdaq-100 Total Return", fmt(qqq_total), fmt(port_return_total-qqq_total))
        c6.metric("Bonds (AGG)", fmt(agg_ret))

        st.markdown("---")

        # ── Chart 1: Total Return vs Benchmarks ──────────────────────────────
        st.markdown("### Total Return vs Benchmarks")
        st.caption(
            "Portfolio line includes yield accrual daily. "
            "Benchmark lines are price-only — switch to 'auto_adjust=True' data which includes dividends."
        )

        fig = go.Figure()
        fig.update_layout(**CHART_BG)

        if port_series_total is not None:
            cum_total = (1 + port_series_total).cumprod() - 1
            fig.add_trace(go.Scatter(
                x=cum_total.index, y=(cum_total*100).round(2),
                name="Portfolio (Total Return incl. yield)",
                line=dict(color="#00E676", width=3),
                hovertemplate="%{y:.1f}%",
            ))

        if port_series_price is not None:
            cum_price = (1 + port_series_price).cumprod() - 1
            fig.add_trace(go.Scatter(
                x=cum_price.index, y=(cum_price*100).round(2),
                name="Portfolio (Price Only)",
                line=dict(color="#00E676", width=1.5, dash="dot"),
                hovertemplate="%{y:.1f}%",
            ))

        bench_colors = {
            "SPY":"#4a90d9","QQQ":"#9b59b6","DIA":"#e67e22",
            "GLD":"#f1c40f","AGG":"#1abc9c",
        }
        for bname, btk in BENCHMARKS.items():
            if btk in prices.columns:
                s = prices[btk].dropna()
                cum = (s / s.iloc[0] - 1) * 100
                fig.add_trace(go.Scatter(
                    x=cum.index, y=cum.round(2),
                    name=bname,
                    line=dict(color=bench_colors.get(btk, "#888"), width=1.5, dash="dash"),
                    hovertemplate="%{y:.1f}%",
                ))

        fig.update_layout(
            title="Cumulative Return — Portfolio (Total Return) vs Benchmarks",
            yaxis_title="Return (%)", height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

        # ── Chart 2: Portfolio / S&P 500 Ratio ───────────────────────────────
        st.markdown("### Portfolio ÷ S&P 500 — Relative Performance Ratio")
        st.caption(
            "Rising line = portfolio outperforming S&P 500. "
            "Falling line = S&P 500 outperforming. "
            "Flat = tracking in lockstep. "
            "Value of 1.0 = equal performance since start of period."
        )

        if port_series_total is not None and "SPY" in prices.columns:
            spy_s   = prices["SPY"].dropna().pct_change().fillna(0)
            port_cum = (1 + port_series_total).cumprod()
            spy_cum  = (1 + spy_s).cumprod()

            # Align on common dates
            common_idx = port_cum.index.intersection(spy_cum.index)
            ratio = (port_cum.loc[common_idx] / spy_cum.loc[common_idx])
            ratio = ratio / ratio.iloc[0]   # normalise to 1.0 at start

            # Color: green when above 1 (outperforming), red when below
            ratio_vals   = ratio.values
            above        = ratio_vals >= 1.0
            ratio_colors = ["rgba(0,230,118,0.15)" if a else "rgba(224,82,82,0.15)"
                            for a in above]

            fig_ratio = go.Figure()
            fig_ratio.update_layout(**CHART_BG)

            # Filled area chart — green above 1, red below
            fig_ratio.add_trace(go.Scatter(
                x=ratio.index, y=ratio.round(4),
                name="Portfolio / S&P 500",
                line=dict(color="#00E676", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(0,230,118,0.08)",
                hovertemplate="Ratio: %{y:.3f}<br>%{x}<extra></extra>",
            ))

            # Reference line at 1.0
            fig_ratio.add_hline(
                y=1.0,
                line_color="rgba(255,255,255,0.35)",
                line_width=1.5,
                line_dash="dot",
                annotation_text="Equal performance (1.0)",
                annotation_position="top right",
                annotation_font_color="rgba(255,255,255,0.5)",
            )

            # Annotation for current ratio
            current_ratio = float(ratio.iloc[-1])
            outperforming = current_ratio >= 1.0
            ratio_pct     = (current_ratio - 1) * 100
            ann_color     = "#00E676" if outperforming else "#e05252"
            ann_text      = (
                f"Currently {fmt(ratio_pct)} vs S&P 500<br>"
                + ("Portfolio OUTPERFORMING" if outperforming else "Portfolio TRAILING")
            )
            fig_ratio.add_annotation(
                x=ratio.index[-1], y=current_ratio,
                text=ann_text,
                showarrow=True, arrowhead=2,
                arrowcolor=ann_color, font=dict(color=ann_color, size=11),
                bgcolor="rgba(20,20,35,0.8)",
                bordercolor=ann_color, borderwidth=1,
                xshift=-20,
            )

            fig_ratio.update_layout(
                title="Portfolio Total Return ÷ S&P 500 (normalised to 1.0 at period start)",
                yaxis_title="Relative Value (1.0 = equal)",
                yaxis=dict(
                    gridcolor="#2a2d3e", showgrid=True,
                    zeroline=False, tickformat=".3f",
                ),
                height=320,
            )
            st.plotly_chart(fig_ratio, use_container_width=True)

            # Plain-English interpretation
            if outperforming:
                st.markdown(
                    f'<div class="signal-box">'
                    f'<b>Portfolio is outperforming the S&P 500 by {fmt(ratio_pct)} '
                    f'over the {period_label} period</b> on a total return basis. '
                    f'The all-weather structure is adding value vs. simply buying and holding SPY.'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                pct_behind = abs(ratio_pct)
                st.markdown(
                    f'<div class="signal-box warning">'
                    f'<b>Portfolio is trailing the S&P 500 by {pct_behind:.1f}% '
                    f'over the {period_label} period</b> on a total return basis. '
                    f'This is expected in strong equity bull markets — the portfolio trades '
                    f'some upside for crash protection and income. '
                    f'Check the Stress Test tab to see how much drawdown was avoided '
                    f'vs. a pure S&P 500 position.'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # ── Holdings table with TOTAL return column ───────────────────────────
        st.markdown("### All Holdings — Total Return")
        rows = []
        for ticker, (name, alloc, cat, bench, bench_name, er) in PORTFOLIO.items():
            w = custom_allocs.get(ticker, alloc)
            if ticker in prices.columns:
                s = prices[ticker].dropna()
                if len(s) > 1:
                    price_ret = (s.iloc[-1] / s.iloc[0] - 1) * 100
                    tot_ret   = total_return_with_yield(price_ret, ticker, period)
                    dy        = DIV_YIELDS.get(ticker, 0)
                    yield_add = dy * years

                    b_ret = None
                    if bench in prices.columns and bench != ticker:
                        bs = prices[bench].dropna()
                        b_ret = (bs.iloc[-1] / bs.iloc[0] - 1) * 100 if len(bs) > 1 else None
                    alpha = (tot_ret - b_ret) if b_ret is not None else None
                    pe_d  = get_pe(ticker)

                    rows.append({
                        "Ticker":   ticker,
                        "Name":     name,
                        "Category": cat,
                        "Weight":   f"{w}%",
                        f"Price Ret":       fmt(price_ret),
                        f"Yield Add":       f"+{yield_add:.1f}%" if yield_add > 0 else "—",
                        f"Total Ret ({period_label})": fmt(tot_ret),
                        "vs Benchmark":    fmt(alpha) if alpha is not None else "—",
                        "Div Yield (ann)": f"{dy:.1f}%" if dy else "—",
                        "Trail P/E":       pe_badge(pe_d.get("trailingPE")),
                        "Exp Ratio":       f"{er:.2f}%" if er else "0%",
                        "Status":          "✅" if (alpha or 0) >= 0 else (
                                           "⚠️" if (alpha or 0) > -alert_thresh else "🔴"),
                    })

        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Ticker":              st.column_config.TextColumn(width="small"),
                    "Weight":              st.column_config.TextColumn(width="small"),
                    "Price Ret":           st.column_config.TextColumn(width="small"),
                    "Yield Add":           st.column_config.TextColumn(width="small"),
                    f"Total Ret ({period_label})": st.column_config.TextColumn(width="small"),
                    "vs Benchmark":        st.column_config.TextColumn(width="small"),
                    "Div Yield (ann)":     st.column_config.TextColumn(width="small"),
                    "Trail P/E":           st.column_config.TextColumn(width="small"),
                    "Exp Ratio":           st.column_config.TextColumn(width="small"),
                    "Status":              st.column_config.TextColumn(width="small"),
                },
            )
            st.caption(
                "Price Ret = price appreciation only | "
                "Yield Add = income contribution (yield × time) | "
                "Total Ret = price + yield | "
                "Status vs per-holding benchmark using total return"
            )

        # Download CSV
        if rows:
            csv_df = pd.DataFrame(rows)
            st.download_button(
                "⬇ Download Holdings CSV",
                csv_df.to_csv(index=False),
                f"portfolio_{datetime.now().strftime('%Y%m%d')}.csv",
                "text/csv",
            )

# ════════════════════════════════════════════════════════════
# TAB 2 — HOLDING vs BENCHMARK
# ════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### Individual Holding vs Benchmark")
    sel = st.selectbox("Select holding:", list(PORTFOLIO.keys()),
                       format_func=lambda t: f"{t} — {PORTFOLIO[t][0]}")
    if sel:
        _,_,cat,bench,bench_name,_ = PORTFOLIO[sel]
        tix_fetch = list(dict.fromkeys([sel,bench,"SPY"]))
        p2 = fetch_prices(tix_fetch,period)
        if not p2.empty and sel in p2.columns:
            se = p2[sel].dropna()
            sb = p2[bench].dropna() if bench in p2.columns and bench!=sel else None
            ss = p2["SPY"].dropna() if "SPY" in p2.columns else None

            ret_e  = (se.iloc[-1]/se.iloc[0]-1)*100 if len(se)>1 else 0
            ret_b  = (sb.iloc[-1]/sb.iloc[0]-1)*100 if sb is not None and len(sb)>1 else 0
            ret_s  = (ss.iloc[-1]/ss.iloc[0]-1)*100 if ss is not None and len(ss)>1 else 0
            stats  = calc_stats(se)
            pe_d   = get_pe(sel)
            dy     = DIV_YIELDS.get(sel,0)

            c1,c2,c3,c4,c5,c6 = st.columns(6)
            c1.metric(f"{sel} Return",  fmt(ret_e))
            c2.metric(f"vs {bench_name}", fmt(ret_b), f"Alpha {fmt(ret_e-ret_b)}")
            c3.metric("vs S&P 500",  fmt(ret_s), fmt(ret_e-ret_s))
            c4.metric("Max Drawdown", f"{stats['max_drawdown']:.1f}%")
            c5.metric("Sharpe Ratio", f"{stats['sharpe']:.2f}",
                      help="Risk-adjusted return vs 5% risk-free rate. >1.0 = good")
            c6.metric("Sortino",      f"{stats['sortino']:.2f}",
                      help="Like Sharpe but penalizes downside volatility only. Higher = better")

            # Cumulative return chart
            fig2 = go.Figure(); fig2.update_layout(**CHART_BG)
            c_e = (se/se.iloc[0]-1)*100
            fig2.add_trace(go.Scatter(x=c_e.index,y=c_e.round(2),name=sel,
                line=dict(color=CATEGORY_COLORS.get(cat,"#888"),width=3),
                hovertemplate="%{y:.1f}%"))
            if sb is not None and bench!=sel:
                c_b=(sb/sb.iloc[0]-1)*100
                fig2.add_trace(go.Scatter(x=c_b.index,y=c_b.round(2),
                    name=bench_name,line=dict(color="#888",width=1.5,dash="dash"),
                    hovertemplate="%{y:.1f}%"))
            if ss is not None:
                c_s=(ss/ss.iloc[0]-1)*100
                fig2.add_trace(go.Scatter(x=c_s.index,y=c_s.round(2),
                    name="S&P 500",line=dict(color="#4a90d9",width=1.5,dash="dot"),
                    hovertemplate="%{y:.1f}%"))
            fig2.update_layout(title=f"{sel} vs {bench_name} vs S&P 500",
                               yaxis_title="Return (%)",height=380)
            st.plotly_chart(fig2,use_container_width=True)

            # Rolling 30-day relative strength
            st.markdown("#### Rolling 30-Day Relative Strength vs Benchmark")
            if sb is not None and bench!=sel:
                rel = (se.pct_change()-sb.pct_change()).rolling(30).sum()*100
                colors_rs = ["#4CAF50" if v>=0 else "#e05252" for v in rel.dropna()]
                fig_rs=go.Figure()
                fig_rs.update_layout(**CHART_BG)
                fig_rs.add_trace(go.Bar(x=rel.dropna().index,y=rel.dropna().round(2),
                    marker_color=colors_rs,name="Relative Strength",hovertemplate="%{y:.2f}%"))
                fig_rs.add_hline(y=0,line_color="#555",line_width=1)
                fig_rs.update_layout(title="30-Day Rolling Outperformance (green=outperforming)",
                                     yaxis_title="(%)",height=250)
                st.plotly_chart(fig_rs,use_container_width=True)

            # Drawdown chart
            st.markdown("#### Drawdown from Peak")
            daily_r = se.pct_change().fillna(0)
            cum_p   = (1+daily_r).cumprod()
            dd      = (cum_p/cum_p.cummax()-1)*100
            fig_dd=go.Figure(); fig_dd.update_layout(**CHART_BG)
            fig_dd.add_trace(go.Scatter(x=dd.index,y=dd.round(2),fill="tozeroy",
                fillcolor="rgba(224,82,82,0.15)",line=dict(color="#e05252",width=1.5),
                name="Drawdown",hovertemplate="%{y:.1f}%"))
            fig_dd.update_layout(yaxis_title="Drawdown (%)",height=220)
            st.plotly_chart(fig_dd,use_container_width=True)

            # Stats card
            st.markdown("#### Performance Statistics")
            sc1,sc2 = st.columns(2)
            with sc1:
                st.markdown(f"""<div class="section-card">
<b>{sel}</b><br>
Return: <b>{fmt(ret_e)}</b><br>
Ann. Volatility: <b>{stats['ann_vol']:.1f}%</b><br>
Max Drawdown: <b>{stats['max_drawdown']:.1f}%</b><br>
Sharpe: <b>{stats['sharpe']:.2f}</b>  Sortino: <b>{stats['sortino']:.2f}</b><br>
Calmar: <b>{stats['calmar']:.2f}</b><br>
Trailing P/E: <b>{pe_badge(pe_d.get('trailingPE'))}</b>  Fwd P/E: <b>{pe_badge(pe_d.get('forwardPE'))}</b><br>
Dividend Yield: <b>{dy:.1f}%</b>
</div>""",unsafe_allow_html=True)
            with sc2:
                alpha_val = ret_e-ret_b
                st.markdown(f"""<div class="section-card">
<b>vs {bench_name}</b><br>
{"✅ Outperforming" if alpha_val>=0 else "🔴 Underperforming"}<br>
Alpha (period): <b>{fmt(alpha_val)}</b><br>
Benchmark: <b>{fmt(ret_b)}</b><br>
Portfolio weight: <b>{custom_allocs.get(sel,PORTFOLIO[sel][1])}%</b><br>
Category: <b>{cat}</b>
</div>""",unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
# TAB 3 — CATEGORY PERFORMANCE
# ════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### Performance by Category")
    port_prices = fetch_prices(list(PORTFOLIO.keys())+["SPY"],period)

    if not port_prices.empty:
        categories={}
        for ticker,(name,alloc,cat,bench,bench_name,er) in PORTFOLIO.items():
            if ticker in port_prices.columns:
                s=port_prices[ticker].dropna()
                if len(s)>1:
                    ret=(s.iloc[-1]/s.iloc[0]-1)*100
                    w=custom_allocs.get(ticker,alloc)
                    if cat not in categories:
                        categories[cat]={"tickers":[],"weighted_return":0,"total_weight":0}
                    categories[cat]["tickers"].append((ticker,name,ret,w))
                    categories[cat]["weighted_return"]+=ret*w
                    categories[cat]["total_weight"]+=w

        # KPIs per category
        cat_cols=st.columns(len(categories))
        for i,(cat,data) in enumerate(categories.items()):
            tw=data["total_weight"]
            wr=data["weighted_return"]/tw if tw>0 else 0
            cat_cols[i].metric(cat,fmt(wr),f"{tw}% of portfolio")

        st.markdown("---")
        st.markdown("#### Category Cumulative Returns vs S&P 500")
        fig_cat=go.Figure(); fig_cat.update_layout(**CHART_BG)
        for cat,data in categories.items():
            cat_s=None; tw=data["total_weight"]
            for ticker,name,ret,w in data["tickers"]:
                if ticker in port_prices.columns:
                    daily=port_prices[ticker].dropna().pct_change().fillna(0)
                    share=(w/tw) if tw>0 else 0
                    cat_s=daily*share if cat_s is None else cat_s.add(daily*share,fill_value=0)
            if cat_s is not None:
                cum=(1+cat_s).cumprod()-1
                fig_cat.add_trace(go.Scatter(x=cum.index,y=(cum*100).round(2),
                    name=cat,line=dict(color=CATEGORY_COLORS.get(cat,"#888"),width=2.5),
                    hovertemplate="%{y:.1f}%"))
        if "SPY" in port_prices.columns:
            s=port_prices["SPY"].dropna(); c=(s/s.iloc[0]-1)*100
            fig_cat.add_trace(go.Scatter(x=c.index,y=c.round(2),name="S&P 500",
                line=dict(color="#fff",width=1,dash="dot"),hovertemplate="%{y:.1f}%"))
        fig_cat.update_layout(yaxis_title="Return (%)",height=400)
        st.plotly_chart(fig_cat,use_container_width=True)

        # Correlation heatmap — NEW in v2
        st.markdown("#### Correlation Heatmap — All Holdings")
        st.caption("Correlation of daily returns. Low/negative = better diversification. Red = highly correlated (move together).")
        avail=[t for t in PORTFOLIO if t in port_prices.columns]
        corr_df=port_prices[avail].pct_change().dropna().corr().round(2)
        fig_corr=go.Figure(go.Heatmap(
            z=corr_df.values, x=avail, y=avail,
            colorscale=[[0,"#1D3461"],[0.5,"#2a2d3e"],[1,"#8B1A1A"]],
            zmid=0, zmin=-1, zmax=1,
            text=corr_df.values.round(2),
            texttemplate="%{text}",
            colorbar=dict(title="Corr",tickfont=dict(color="#c0c4d6")),
        ))
        fig_corr.update_layout(
            height=max(350,len(avail)*32+80),
            paper_bgcolor="#0f1117",plot_bgcolor="#0f1117",
            font=dict(color="#c0c4d6"),
            margin=dict(l=60,r=20,t=20,b=60),
        )
        st.plotly_chart(fig_corr,use_container_width=True)

        # Heatmap 30-day daily returns
        st.markdown("#### 30-Day Returns Heatmap")
        heat=port_prices[avail].pct_change().tail(30)*100
        fig_heat=go.Figure(go.Heatmap(
            z=heat.values.T,
            x=[d.strftime("%m/%d") for d in heat.index],
            y=avail,
            colorscale=[[0,"#b71c1c"],[0.5,"#1c1f2e"],[1,"#1b5e20"]],
            zmid=0,
            text=heat.values.T.round(1),texttemplate="%{text}%",
            colorbar=dict(title="Ret%",tickfont=dict(color="#c0c4d6")),
        ))
        fig_heat.update_layout(
            height=max(300,len(avail)*28+80),
            paper_bgcolor="#0f1117",plot_bgcolor="#0f1117",
            font=dict(color="#c0c4d6"),
            margin=dict(l=60,r=20,t=20,b=40),
            xaxis=dict(tickfont=dict(size=9)),
        )
        st.plotly_chart(fig_heat,use_container_width=True)

# ════════════════════════════════════════════════════════════
# TAB 4 — CONSTRUCTION & P/E
# ════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### Portfolio Construction")
    cl, cr = st.columns(2)
    with cl:
        st.markdown("#### Allocation by Holding")
        tickers_=list(PORTFOLIO.keys())
        weights_=[custom_allocs.get(t,PORTFOLIO[t][1]) for t in tickers_]
        colors_=[CATEGORY_COLORS.get(PORTFOLIO[t][2],"#888") for t in tickers_]
        fig_d=go.Figure(go.Pie(labels=tickers_,values=weights_,hole=0.55,
            marker=dict(colors=colors_,line=dict(color="#0f1117",width=2)),
            textinfo="label+percent",textfont=dict(size=11,color="#fff"),
            hovertemplate="<b>%{label}</b><br>%{value}%<extra></extra>"))
        fig_d.update_layout(
            annotations=[dict(text=f"<b>{sum(weights_)}%</b>",x=0.5,y=0.5,
                font_size=18,font_color="#fff",showarrow=False)],
            paper_bgcolor="#0f1117",font=dict(color="#c0c4d6"),
            showlegend=False,margin=dict(l=10,r=10,t=20,b=10),height=360)
        st.plotly_chart(fig_d,use_container_width=True)
    with cr:
        st.markdown("#### Allocation by Category")
        cat_w={}
        for t,(n,a,cat,*_) in PORTFOLIO.items():
            cat_w[cat]=cat_w.get(cat,0)+custom_allocs.get(t,a)
        fig_dc=go.Figure(go.Pie(labels=list(cat_w.keys()),values=list(cat_w.values()),hole=0.55,
            marker=dict(colors=[CATEGORY_COLORS.get(c,"#888") for c in cat_w],
                        line=dict(color="#0f1117",width=2)),
            textinfo="label+percent",textfont=dict(size=11,color="#fff"),
            hovertemplate="<b>%{label}</b><br>%{value}%<extra></extra>"))
        fig_dc.update_layout(paper_bgcolor="#0f1117",font=dict(color="#c0c4d6"),
            showlegend=False,margin=dict(l=10,r=10,t=20,b=10),height=360)
        st.plotly_chart(fig_dc,use_container_width=True)

    # Holdings detail table
    st.markdown("#### Full Holdings Detail")
    detail_rows=[]
    for ticker,(name,alloc,cat,bench,bench_name,er) in PORTFOLIO.items():
        pe_d=get_pe(ticker)
        dy=DIV_YIELDS.get(ticker,0)
        detail_rows.append({
            "Ticker":ticker,"Name":name,"Category":cat,
            "Suggested%":alloc,"Custom%":custom_allocs.get(ticker,alloc),
            "Delta":custom_allocs.get(ticker,alloc)-alloc,
            "Benchmark":bench_name,"Exp Ratio":f"{er:.2f}%" if er else "0%",
            "Div Yield":f"{dy:.1f}%","Trail P/E":pe_badge(pe_d.get("trailingPE")),
            "Fwd P/E":pe_badge(pe_d.get("forwardPE")),
            "P/B":f"{pe_d['priceToBook']:.1f}x" if pe_d.get("priceToBook") else "—",
        })
    st.dataframe(pd.DataFrame(detail_rows),use_container_width=True,hide_index=True)
    st.caption("🟢 P/E<15  🟡 15-25  🟠 25-35  🔴>35")

    # Weighted avg expense ratio + dividend yield
    er_vals=sum(PORTFOLIO[t][5]*custom_allocs.get(t,PORTFOLIO[t][1])/100 for t in PORTFOLIO)
    dy_vals=sum(DIV_YIELDS.get(t,0)*custom_allocs.get(t,PORTFOLIO[t][1])/100 for t in PORTFOLIO)
    i1,i2=st.columns(2)
    i1.info(f"💡 Weighted Average Expense Ratio: **{er_vals:.2f}%** annually")
    i2.info(f"💰 Weighted Average Dividend Yield: **{dy_vals:.2f}%** annually")

    # P/E chart
    st.markdown("---")
    st.markdown("#### Trailing vs Forward P/E — Equity Holdings")
    eq_tix=[t for t in PORTFOLIO if PE_FALLBACK.get(t,{}).get("trailingPE") is not None]
    pe_rows2=[]
    for t in eq_tix:
        d=get_pe(t)
        if d.get("trailingPE"):
            pe_rows2.append({"t":t,"trail":d["trailingPE"],
                "fwd":d.get("forwardPE") or d["trailingPE"],
                "c":CATEGORY_COLORS.get(PORTFOLIO[t][2],"#888")})
    if pe_rows2:
        fig_pe=go.Figure()
        fig_pe.add_trace(go.Bar(x=[r["t"] for r in pe_rows2],y=[r["trail"] for r in pe_rows2],
            name="Trailing P/E",marker_color=[r["c"] for r in pe_rows2],opacity=0.9,
            text=[f"{v['trail']:.1f}x" for v in pe_rows2],textposition="outside"))
        fig_pe.add_trace(go.Bar(x=[r["t"] for r in pe_rows2],y=[r["fwd"] for r in pe_rows2],
            name="Forward P/E",marker_color=[r["c"] for r in pe_rows2],opacity=0.45,
            text=[f"{v['fwd']:.1f}x" for v in pe_rows2],textposition="outside"))
        for y,color,label,pos in [
            (18,"#4CAF50","Historical median 18x","top right"),
            (27.3,"#E24B4A","S&P 500 current 27.3x","top right"),
        ]:
            fig_pe.add_hline(y=y,line_dash="dot",line_color=color,line_width=1.5,
                annotation_text=label,annotation_position=pos,annotation_font_color=color)
        pe_layout={k:v for k,v in CHART_BG.items() if k not in ("xaxis","yaxis")}
        fig_pe.update_layout(barmode="group",yaxis_title="P/E (x)",height=380,**pe_layout,
            xaxis=dict(gridcolor="#2a2d3e"),
            yaxis=dict(gridcolor="#2a2d3e",range=[0,max([r["trail"] for r in pe_rows2]+[35])+8]))
        st.plotly_chart(fig_pe,use_container_width=True)

    # Rebalancing alerts
    st.markdown("#### Rebalancing Alerts")
    any_alert=False
    for ticker,(name,alloc,cat,*_) in PORTFOLIO.items():
        diff=abs(custom_allocs.get(ticker,alloc)-alloc)
        if diff>=3:
            any_alert=True
            direction="overweight" if custom_allocs.get(ticker,alloc)>alloc else "underweight"
            cls="warning" if diff<7 else "danger"
            st.markdown(f'<div class="signal-box {cls}">&#9878; <b>{ticker}</b>: {direction} by <b>{diff}%</b></div>',
                        unsafe_allow_html=True)
    if not any_alert:
        st.success("All holdings within 3% of target — no rebalancing needed.")

# ════════════════════════════════════════════════════════════
# TAB 5 — MARKET SIGNALS
# ════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### Live Market Signals")
    sig_tix=["^VIX","GLD","TLT","BIL","SPY","^TNX","^TYX"]+list(PORTFOLIO.keys())
    sig_prices=fetch_prices(sig_tix,"1y")

    cs1,cs2=st.columns(2)
    with cs1:
        st.markdown("#### Risk / Fear Indicators")
        # VIX
        if "^VIX" in sig_prices.columns:
            vix=float(sig_prices["^VIX"].dropna().iloc[-1])
            cls="danger" if vix>30 else ("warning" if vix>20 else "")
            lbl="FEAR — potential buy signal for quality assets" if vix>30 else ("ELEVATED" if vix>20 else "CALM — watch for complacency")
            st.markdown(f'<div class="signal-box {cls}"><b>VIX: {vix:.1f}</b> — {lbl}<br><small>Below 15: complacent. 15-25: normal. Above 30: fear/opportunity.</small></div>',
                        unsafe_allow_html=True)
        # Gold/SPY
        if "GLD" in sig_prices.columns and "SPY" in sig_prices.columns:
            g=sig_prices["GLD"].dropna(); s=sig_prices["SPY"].dropna()
            chg=((g.iloc[-1]/s.iloc[-1])/(g.iloc[0]/s.iloc[0])-1)*100
            d="rising (risk-off)" if chg>0 else "falling (risk-on)"
            cls="warning" if chg>5 else ""
            st.markdown(f'<div class="signal-box {cls}"><b>Gold/S&P Ratio: {d}</b> ({chg:+.1f}%)<br><small>Rising ratio = flight to safety = supports metals allocation.</small></div>',
                        unsafe_allow_html=True)
        # Yield curve / recession indicator
        if "^TNX" in sig_prices.columns and "^TYX" in sig_prices.columns:
            tnx=float(sig_prices["^TNX"].dropna().iloc[-1])
            tyx=float(sig_prices["^TYX"].dropna().iloc[-1])
            spread=tyx-tnx
            # 2yr proxy via BIL
            inv="INVERTED — recession historically follows within 12-18 months" if spread<0 else ("Flat — caution" if spread<0.5 else "Normal — economy expanding")
            cls="danger" if spread<0 else ("warning" if spread<0.5 else "")
            st.markdown(f'<div class="signal-box {cls}"><b>Yield Curve (30yr-10yr): {spread:.2f}%</b><br>{inv}<br><small>10yr: {tnx:.2f}% | 30yr: {tyx:.2f}% | Spread: {spread:+.2f}%</small></div>',
                        unsafe_allow_html=True)
        # TLT vs BIL
        if "TLT" in sig_prices.columns and "BIL" in sig_prices.columns:
            tlt=sig_prices["TLT"].dropna(); bil=sig_prices["BIL"].dropna()
            tlt_r=(tlt.iloc[-1]/tlt.iloc[0]-1)*100; bil_r=(bil.iloc[-1]/bil.iloc[0]-1)*100
            sp=bil_r-tlt_r
            cls="danger" if sp>3 else ("warning" if sp>0 else "")
            msg="T-bills outperforming bonds — hold SGOV/USFR, avoid TLT" if sp>0 else "Long bonds recovering — watch for rate pivot"
            st.markdown(f'<div class="signal-box {cls}"><b>T-Bills vs Long Bonds:</b> {msg}<br><small>T-bills: {bil_r:+.1f}% | TLT: {tlt_r:+.1f}% | Gap: {sp:+.1f}%</small></div>',
                        unsafe_allow_html=True)

    with cs2:
        st.markdown("#### Trend & Momentum Signals")
        if "SPY" in sig_prices.columns:
            spy_=sig_prices["SPY"].dropna()
            ma50=spy_.rolling(50).mean().iloc[-1]
            ma200=spy_.rolling(min(200,len(spy_))).mean().iloc[-1]
            pnow=spy_.iloc[-1]
            golden=ma50>ma200
            cross="Golden Cross (bullish — 50MA above 200MA)" if golden else "Death Cross (bearish — 50MA below 200MA)"
            cls="info" if golden else "warning"
            st.markdown(f'<div class="signal-box {cls}"><b>S&P 500: {cross}</b><br>Price {"above" if pnow>ma200 else "below"} 200-day MA<br><small>Golden Cross = sustained uptrend. Death Cross = trend reversal risk.</small></div>',
                        unsafe_allow_html=True)
        # Portfolio momentum
        port_m=None
        for ticker,(n,a,*_) in PORTFOLIO.items():
            if ticker in sig_prices.columns:
                w=custom_allocs.get(ticker,a)/100
                d=sig_prices[ticker].pct_change().fillna(0)
                port_m=d*w if port_m is None else port_m+d*w
        if port_m is not None and "SPY" in sig_prices.columns:
            spy_m=sig_prices["SPY"].pct_change().fillna(0)
            rel30=((port_m.tail(30).sum())-(spy_m.tail(30).sum()))*100
            cls="info" if rel30>0 else "warning"
            st.markdown(f'<div class="signal-box {cls}"><b>30-Day Portfolio vs S&P 500: {rel30:+.1f}%</b><br>{"Outperforming" if rel30>0 else "Lagging"} the market this month.</div>',
                        unsafe_allow_html=True)

        # Yield curve chart
        if "^TNX" in sig_prices.columns and "^TYX" in sig_prices.columns:
            tnx_s=sig_prices["^TNX"].dropna(); tyx_s=sig_prices["^TYX"].dropna()
            yl_layout={k:v for k,v in CHART_BG.items() if k not in ("xaxis","yaxis")}
            fig_y=go.Figure()
            fig_y.add_trace(go.Scatter(x=tnx_s.index,y=tnx_s,name="10-Yr",line=dict(color="#4a90d9",width=2)))
            fig_y.add_trace(go.Scatter(x=tyx_s.index,y=tyx_s,name="30-Yr",line=dict(color="#e6a817",width=2)))
            sp_s=tyx_s-tnx_s
            fig_y.add_trace(go.Scatter(x=sp_s.index,y=sp_s,name="Spread",
                line=dict(color="#00E676",width=1.5,dash="dot"),yaxis="y2"))
            fig_y.update_layout(title="Treasury Yields",height=280,**yl_layout,
                xaxis=dict(gridcolor="#2a2d3e"),
                yaxis=dict(title="Yield (%)",gridcolor="#2a2d3e"),
                yaxis2=dict(title="Spread",overlaying="y",side="right",gridcolor="rgba(0,0,0,0)"))
            st.plotly_chart(fig_y,use_container_width=True)

# ════════════════════════════════════════════════════════════
# TAB 6 — STRESS TEST (NEW)
# ════════════════════════════════════════════════════════════
with tab6:
    st.markdown("### Portfolio Stress Test — Historical Crashes")
    st.markdown("*Estimated portfolio drawdown in each historical crash scenario based on asset class behavior.*")

    sel_crash = st.selectbox("Select crash scenario:",list(CRASH_SCENARIOS.keys()))
    scenario  = CRASH_SCENARIOS[sel_crash]

    port_crash_ret = 0.0
    crash_rows     = []
    for ticker,(name,alloc,cat,*_) in PORTFOLIO.items():
        w   = custom_allocs.get(ticker,alloc)/100
        ret = scenario["asset_returns"].get(ticker)
        if ret is not None:
            port_crash_ret += ret * w
            crash_rows.append({
                "Ticker":ticker,"Name":name,"Category":cat,
                "Weight":f"{w*100:.0f}%",
                "Est. Return":fmt(ret),
                "Contribution":fmt(ret*w),
                "Signal":"🟢 Hedge" if ret>0 else ("🟡 Hold" if ret>-15 else "🔴 Pain")
            })

    spy_crash = scenario["spy_drop"]
    improvement = spy_crash - port_crash_ret

    c1,c2,c3 = st.columns(3)
    c1.metric("Est. Portfolio Drawdown",  fmt(port_crash_ret))
    c2.metric("S&P 500 Actual Drop",      fmt(spy_crash))
    c3.metric("Portfolio Protection",     fmt(improvement),
              help="Positive = portfolio fell less than S&P 500")

    st.caption(f"Scenario: {sel_crash} ({scenario['period']}). Estimates based on historical asset class behavior. Not actual returns.")

    # Waterfall chart
    crash_df=pd.DataFrame(crash_rows).sort_values("Contribution")
    colors_c=[("rgba(29,158,117,0.8)" if float(r.replace("+","").replace("%",""))>0
               else "rgba(224,82,82,0.8)") for r in crash_df["Contribution"]]
    fig_c=go.Figure(go.Bar(
        x=crash_df["Ticker"],y=[float(r.replace("+","").replace("%","")) for r in crash_df["Contribution"]],
        marker_color=colors_c,text=crash_df["Contribution"],textposition="outside",
    ))
    fig_c.add_hline(y=0,line_color="#555",line_width=1)
    layout_c={k:v for k,v in CHART_BG.items() if k not in ("xaxis","yaxis")}
    fig_c.update_layout(title=f"Contribution to Portfolio Return — {sel_crash}",
        yaxis_title="Contribution (%)",height=340,**layout_c,
        xaxis=dict(gridcolor="#2a2d3e"),yaxis=dict(gridcolor="#2a2d3e",zeroline=True,zerolinecolor="#555"))
    st.plotly_chart(fig_c,use_container_width=True)

    st.dataframe(pd.DataFrame(crash_rows),use_container_width=True,hide_index=True,
        column_config={"Signal":st.column_config.TextColumn(width="small"),
                       "Weight":st.column_config.TextColumn(width="small")})

    # Cross-scenario comparison
    st.markdown("---")
    st.markdown("#### Cross-Scenario Comparison")
    scenario_names=list(CRASH_SCENARIOS.keys())
    port_returns_all=[]
    spy_returns_all=[]
    for sname,sdata in CRASH_SCENARIOS.items():
        pr=sum(
            sdata["asset_returns"].get(t,0)*(custom_allocs.get(t,PORTFOLIO[t][1])/100)
            for t in PORTFOLIO if sdata["asset_returns"].get(t) is not None
        )
        port_returns_all.append(round(pr,1))
        spy_returns_all.append(sdata["spy_drop"])

    fig_cross=go.Figure()
    fig_cross.add_trace(go.Bar(name="S&P 500",x=scenario_names,y=spy_returns_all,
        marker_color="rgba(224,82,82,0.8)"))
    fig_cross.add_trace(go.Bar(name="This Portfolio (est.)",x=scenario_names,y=port_returns_all,
        marker_color="rgba(55,138,221,0.8)"))
    layout_x={k:v for k,v in CHART_BG.items() if k not in ("xaxis","yaxis")}
    fig_cross.update_layout(barmode="group",yaxis_title="Return (%)",height=320,**layout_x,
        xaxis=dict(gridcolor="#2a2d3e"),yaxis=dict(gridcolor="#2a2d3e",zeroline=True,zerolinecolor="#555"))
    st.plotly_chart(fig_cross,use_container_width=True)

# ════════════════════════════════════════════════════════════
# TAB 7 — ETF vs DIRECT STOCKS (NEW)
# ════════════════════════════════════════════════════════════
with tab7:
    st.markdown("### ETF vs Direct Stock Holdings — When Does It Matter?")

    st.markdown("""
<div class="signal-box info">
<b>The core question:</b> ETFs give you diversification at low cost — but they also dilute your
exposure to the best names. When NVDA was the decade's top performer, VGT held it at
just 1-3% for most of that run. Owning NVDA directly at 5% would have generated more wealth
from that single position than the entire VGT allocation.
</div>""",unsafe_allow_html=True)

    # Compare ETF basket vs equivalent direct stocks
    comparison_pairs = [
        {"etf":"VGT","stocks":["NVDA","AAPL","MSFT"],"label":"Tech: VGT vs Top 3 Stocks"},
        {"etf":"XLE","stocks":["XOM","COP"],"label":"Energy: XLE vs XOM+COP"},
        {"etf":"XLV","stocks":["JNJ","UNH"],"label":"Healthcare: XLV vs JNJ+UNH"},
        {"etf":"XLU","stocks":["NEE"],"label":"Utilities: XLU vs NEE"},
    ]

    sel_comp=st.selectbox("Select comparison:",
        [c["label"] for c in comparison_pairs])
    pair=[c for c in comparison_pairs if c["label"]==sel_comp][0]

    comp_tix=list(dict.fromkeys([pair["etf"]]+pair["stocks"]+["SPY"]))
    cp=fetch_prices(comp_tix,period)

    if not cp.empty:
        fig_comp=go.Figure(); fig_comp.update_layout(**CHART_BG)
        etf_s=cp[pair["etf"]].dropna() if pair["etf"] in cp.columns else None
        if etf_s is not None:
            c_etf=(etf_s/etf_s.iloc[0]-1)*100
            fig_comp.add_trace(go.Scatter(x=c_etf.index,y=c_etf.round(2),
                name=f"{pair['etf']} (ETF)",
                line=dict(color="#888",width=2.5,dash="dash"),hovertemplate="%{y:.1f}%"))

        stock_colors=["#4CAF50","#FFA726","#42A5F5","#AB47BC"]
        # Equal-weight stock basket
        basket_s=None
        for i,stk in enumerate(pair["stocks"]):
            if stk in cp.columns:
                s=cp[stk].dropna()
                daily=s.pct_change().fillna(0)/len(pair["stocks"])
                basket_s=daily if basket_s is None else basket_s+daily
                cum=(s/s.iloc[0]-1)*100
                fig_comp.add_trace(go.Scatter(x=cum.index,y=cum.round(2),
                    name=stk,line=dict(color=stock_colors[i%4],width=1.5),
                    hovertemplate="%{y:.1f}%"))
        if basket_s is not None:
            cum_b=(1+basket_s).cumprod()-1
            fig_comp.add_trace(go.Scatter(x=cum_b.index,y=(cum_b*100).round(2),
                name="Equal-weight basket",
                line=dict(color="#00E676",width=3),hovertemplate="%{y:.1f}%"))

        fig_comp.update_layout(title=pair["label"],yaxis_title="Return (%)",height=380)
        st.plotly_chart(fig_comp,use_container_width=True)

        # Stats comparison table
        comp_rows=[]
        if etf_s is not None:
            st_=calc_stats(etf_s)
            dy=DIV_YIELDS.get(pair["etf"],0)
            er=PORTFOLIO.get(pair["etf"],(None,None,None,None,None,0.09))[5]
            comp_rows.append({"Holding":pair["etf"],"Type":"ETF",
                "Return":fmt((etf_s.iloc[-1]/etf_s.iloc[0]-1)*100),
                "Ann Vol":f"{st_['ann_vol']:.1f}%","Sharpe":st_["sharpe"],
                "Max DD":f"{st_['max_drawdown']:.1f}%",
                "Div Yield":f"{dy:.1f}%","Exp Ratio":f"{er:.2f}%"})
        for stk in pair["stocks"]:
            if stk in cp.columns:
                s=cp[stk].dropna(); st_=calc_stats(s)
                dy=DIV_YIELDS.get(stk,0)
                comp_rows.append({"Holding":stk,"Type":"Direct Stock",
                    "Return":fmt((s.iloc[-1]/s.iloc[0]-1)*100),
                    "Ann Vol":f"{st_['ann_vol']:.1f}%","Sharpe":st_["sharpe"],
                    "Max DD":f"{st_['max_drawdown']:.1f}%",
                    "Div Yield":f"{dy:.1f}%","Exp Ratio":"0%"})
        st.dataframe(pd.DataFrame(comp_rows),use_container_width=True,hide_index=True)

    st.markdown("---")
    # ETF vs stocks decision framework
    st.markdown("#### When to Use ETFs vs Direct Stocks")

    col_e,col_s=st.columns(2)
    with col_e:
        st.markdown("""<div class="signal-box info">
<b>Use ETFs when:</b><br>
&#10003; You want automatic sector diversification<br>
&#10003; You can't pick the single best stock in a sector<br>
&#10003; The sector has many winners (e.g. SCHD — 100 dividend stocks)<br>
&#10003; The commodity has no single-stock equivalent (GLD, SLV, PDBC)<br>
&#10003; The asset is a bond/T-bill (SGOV, USFR — no individual bond practical)<br>
&#10003; You want rebalancing done for you (equal-weight ETFs)<br>
&#10003; Tax efficiency matters (ETFs distribute fewer capital gains)
</div>""",unsafe_allow_html=True)
    with col_s:
        st.markdown("""<div class="signal-box purple">
<b>Use direct stocks when:</b><br>
&#10003; You have high conviction in a specific name (NVDA, AAPL, MSFT)<br>
&#10003; A major IPO enters the market (ETFs dilute new entries slowly)<br>
&#10003; The ETF's top holding IS the whole thesis (NVDA = 25%+ of SMH)<br>
&#10003; You want the full dividend from a specific company (KO, JNJ, XOM)<br>
&#10003; The ETF contains losers dragging down winners (XLV holds ~50 stocks)<br>
&#10003; You can monitor and rebalance yourself<br>
&#10003; You want to do tax-loss harvesting on individual positions
</div>""",unsafe_allow_html=True)

    # IPO dilution illustration
    st.markdown("---")
    st.markdown("#### The IPO Dilution Problem — Why Direct Ownership Matters at Launch")
    st.markdown("""<div class="signal-box warning">
<b>Example: NVIDIA in VGT</b><br>
NVDA entered VGT at roughly 1-2% weight in 2015. It stayed under 5% until 2022.
By the time it became the largest holding at 18-20%, most of the gain had already occurred.
An investor who bought NVDA directly at 5% allocation in 2015 captured nearly the full
216,000% twenty-year return. An investor in VGT captured a fraction of it, diluted
by 300+ other holdings. The same dynamic applies to every future AI/quantum/biotech winner
that enters an index slowly after it has already appreciated significantly.
<br><br>
<b>Upcoming major IPOs to watch (2026-2027 expected):</b>
Anthropic, OpenAI, SpaceX, Stripe — all expected to enter indices at small weights
long after their private valuations have already compounded. Consider buying directly at IPO.
</div>""",unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
# TAB 8 — EDUCATION
# ════════════════════════════════════════════════════════════
with tab8:
    st.markdown("### Market Signals & Investment Education")

    # ══════════════════════════════════════════════════════════════════════════
    # REGIME CLASSIFIER — signals to watch & when to change construction
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("#### 🧭 Which signals to watch — and when to change the portfolio")
    st.caption(
        "Rebalance on regime *transitions*, not on a calendar. The quadrant is "
        "the SIGN of the short real rate × the DIRECTION of the long real yield, "
        "with credit spreads able to override everything."
    )

    _assessment = None
    if _REGIME_OK and fred_key_input:
        try:
            _assessment = full_assessment(fred_key_input)
        except Exception as _e:
            st.warning(f"Live regime unavailable ({_e}). Showing static guide.")

    if _assessment is not None:
        _r = _assessment["regime"]; _s = _assessment["signals"]
        # Verified against the live regime_classifier.py (Aug 2026): 8 keys,
        # not the original 4 — this dict previously fell back to gray for
        # hard_repression / growth_scare / transition_ambiguous.
        _color = {"inflationary_repression":"#c026d3","hard_repression":"#9333ea",
                  "liquidity_crisis":"#dc2626","stagflation":"#d97706",
                  "goldilocks":"#16a34a","growth_scare":"#ea580c",
                  "transition_ambiguous":"#0891b2",
                  "neutral":"#6b7280"}.get(_r["key"], "#6b7280")
        st.markdown(
            f"<div style='padding:12px 16px;border-radius:8px;background:{_color}22;"
            f"border-left:5px solid {_color};'><b style='color:{_color};font-size:1.15rem;'>"
            f"Current regime: {_r['label']}</b><br><span style='color:#cbd5e1;'>"
            f"{_r['blurb']}</span></div>", unsafe_allow_html=True)
        _cA,_cB,_cC,_cD = st.columns(4)
        _cA.metric("SHORT real rate",
                   "n/a" if _s.short_real_rate is None else f"{_s.short_real_rate:+.2f}%")
        _cB.metric("LONG real yield",
                   "n/a" if _s.long_real_yield is None else f"{_s.long_real_yield:+.2f}%")
        _cC.metric("HY OAS",
                   "n/a" if _s.hy_oas is None else f"{_s.hy_oas:.2f}%")
        _cD.metric("Stock/bond 60d corr",
                   "n/a" if _s.stock_bond_corr_60d is None else f"{_s.stock_bond_corr_60d:+.2f}")
        _k = _assessment["kmlm"]
        st.markdown(f"**Trend / KMLM signal: {_k['stance']}** — {_k['funding']}")
    elif _REGIME_OK:
        st.info("💡 Add a FRED API key in the sidebar to see the LIVE regime "
                "banner. The static guide and quadrant map below always render.")

    st.markdown("##### Signal → what it tells you → when to change construction")
    st.dataframe(
        pd.DataFrame(SIGNAL_GUIDE, columns=[
            "Signal", "What it tells you", "When to change construction"]),
        hide_index=True, use_container_width=True,
    )

    if _REGIME_OK:
        st.markdown("##### The regime map & target tilts")
        st.caption("8 regimes as of the current classifier — grown from the original "
                   "4-quadrant table (added hard_repression, growth_scare, and a "
                   "banded transition_ambiguous state for when the short-real-rate "
                   "gauge is inside its own noise).")
        _active = _assessment["regime"]["key"] if _assessment else None
        _disc = {"inflationary_repression":"short real −  ·  long real ↑",
                 "hard_repression":"short real −  ·  long real ↓  ·  credit calm",
                 "liquidity_crisis":"HY blowout  ·  long real ↓",
                 "stagflation":"short real −  ·  2s10s re-steepening",
                 "goldilocks":"short real +  ·  credit tight  ·  leadership intact",
                 "growth_scare":"growth composite CONTRACTING (≥3 of 4 series)",
                 "transition_ambiguous":"short real inside ±0.25% band, or valuation/leadership guard"}
        _rows=[]
        for _kk in ["inflationary_repression","hard_repression","liquidity_crisis",
                    "stagflation","goldilocks","growth_scare","transition_ambiguous"]:
            _w = target_weights(_kk)
            _rows.append({
                "Regime": REGIMES[_kk]["label"] + (" ⬅ ACTIVE" if _kk==_active else ""),
                "Trigger": _disc[_kk],
                "TLT": f"{_w['TLT']}%", "KMLM": f"{_w['KMLM']}%",
                "Real assets": f"{_w['GLD']+_w['SLV']+_w['RING']+_w['XLE']+_w['PDBC']}%",
                "Cash": f"{_w['SGOV']+_w['USFR']}%",
                "Growth": f"{_w['VGT']+_w['SMH']+_w['QQQ']}%",
            })
        st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)
        st.caption("TLT is a *contingent* sleeve: 0% in inflationary repression "
                   "(rising long real yields), armed in a liquidity crisis. "
                   "GLD tilts shown here are pre-momentum-gate — the live "
                   "app can redirect a GLD add to SGOV if GLD isn't above a "
                   "rising 200-day MA; this table shows the regime's raw "
                   "intent, not the gated outcome.")

    st.markdown("---")

    topics={
        "📉 Max Drawdown & Why It Matters More Than Volatility": """
**Max Drawdown** is the peak-to-trough decline — the worst loss you would have experienced at the worst possible time.

- **Under 10%:** Highly defensive
- **10-20%:** Moderate
- **20-40%:** Growth-oriented
- **Over 40%:** Aggressive/concentrated

Volatility (standard deviation) measures how much returns fluctuate *on average*. Drawdown measures the worst single streak. Emotionally, drawdown is what actually makes investors panic-sell — not volatility.

**The Sortino ratio** is better than Sharpe in most cases because it only penalizes *downside* volatility. An asset that swings up wildly has high Sharpe-penalizing volatility but the upswings aren't harmful. Sortino ignores them.

**Calmar ratio** = annualized return / max drawdown. Higher = better risk-adjusted performance specifically on crash risk. A Calmar > 1.0 is very good.
""",
        "📊 Moving Averages — 50-Day & 200-Day": """
**Golden Cross:** 50-day MA crosses ABOVE 200-day MA → sustained uptrend signal.
**Death Cross:** 50-day MA crosses BELOW 200-day MA → potential downtrend.

- Price **above 200-day MA** → long-term uptrend intact. Hold or buy dips.
- Price **below 200-day MA** → caution. Consider reducing risk.
- Price **far above 200-day MA (>15%)** → potentially overbought. Don't add here.

For this portfolio: if SPY falls below its 200-day MA and a Death Cross forms, increase SGOV/SCHD and reduce SMH exposure.
""",
        "😱 VIX — The Market's Fear Gauge": """
The VIX measures the market's expectation of 30-day S&P 500 volatility from options pricing.

- **Below 15:** Calm/complacent — often a contrarian warning sign
- **15-20:** Normal
- **20-30:** Elevated anxiety
- **30-40:** Significant fear — historically near bottoms
- **Above 40:** Extreme fear (2008, March 2020) — historically the best buying opportunity

When VIX spikes above 30-40, SGOV and GLD protect while VGT/SMH fall hard — that's when to ADD, not sell. VIX spikes are buying opportunities for quality assets.
""",
        "💹 Yield Curve — The Recession Predictor": """
Normally, longer bonds yield more than shorter bonds (upward sloping curve).

**Inversion** (2yr > 10yr): the most reliable recession predictor in 60+ years. Has preceded every U.S. recession since 1970, usually by 12-18 months.

**Steepening from inversion**: economy recovering. Time to add cyclicals.

**Current situation (2026):** 30-yr at ~5%, headline CPI running above 4% — no long bonds. SGOV earns 5%+ with zero duration risk. When the curve re-steepens and inflation falls below 2.5%, that's when to rotate SGOV proceeds into IEF (intermediate bonds).
""",
        "🔄 Sharpe, Sortino & Calmar Ratios Explained": """
These three ratios measure different dimensions of risk-adjusted performance:

| Ratio | Formula | Best used for |
|---|---|---|
| **Sharpe** | (Return - Risk-Free) / Std Dev | General comparison |
| **Sortino** | (Return - Risk-Free) / Downside Std Dev | Penalizes bad volatility only |
| **Calmar** | Annualized Return / Max Drawdown | Crash-specific risk |

**Interpreting values:**
- Sharpe/Sortino above 1.0: excellent risk-adjusted return
- Calmar above 1.0: very good crash resilience
- Calmar below 0.5: too much drawdown for the return generated

For crash protection, prioritize Calmar. For smooth compounding, prioritize Sortino.
""",
        "🏦 ETF vs Direct Stocks — Decision Framework": """
**ETFs are better when:**
- The sector has many winners you can't pick between (SCHD's 100 dividend stocks)
- You want automatic rebalancing and diversification
- The asset has no single-stock equivalent (gold, T-bills, commodities)
- Tax efficiency matters (ETFs have fewer capital gains distributions)

**Direct stocks are better when:**
- You have high conviction in a specific name
- A major IPO launches — ETFs enter it slowly, you can buy at listing
- The ETF's top holding IS the whole thesis (NVDA = 25%+ of SMH)
- You want tax-loss harvesting flexibility

**The hybrid approach** (used in Hybrid Mode): Direct stocks for highest-conviction growth names (NVDA, AAPL, MSFT, GOOGL), ETFs for everything else where diversification reduces risk more than it reduces return.
""",
        "🔁 When & How to Rebalance": """
**Time-based:** Quarterly or semi-annual automatic rebalance.
**Threshold-based:** Any holding drifts more than 5% from target → rebalance.
**Event-based:** Major macro shift (Iran deal, Fed pivot, CPI drops below 2.5%).

**Tax-smart rebalancing:**
- In taxable accounts: direct new contributions to underweight positions
- Use dividends (SCHD, SGOV) to fund rebalancing without selling
- Rebalance in tax-advantaged accounts (Roth IRA, 401k) first

**Triggers specific to this portfolio:**
- Gold runs to 15%+ → trim, rotate to SCHD
- Tech drops 20%+ → buying opportunity, add VGT/NVDA
- PCE drops below 2.5% for 3 months → reduce metals, add IEF
- Fed cuts rates → rotate SGOV into XLU/SCHD (bond-proxy sectors rally)
""",
    }

    for topic,content in topics.items():
        with st.expander(topic,expanded=False):
            st.markdown(content)

    st.markdown("---")
    st.markdown("### Decision Framework — What to Do When...")
    decisions=[
        ("Market drops 10-15%","","Hold. Review cause. Gold/SGOV protect. If tech-specific: wait for 200-day MA support before adding."),
        ("Market drops >20% (bear)","danger","Deploy SGOV dry powder into VGT/SMH/NVDA. GLD/SCHD carry portfolio. Review crash history tab for guidance."),
        ("Inflation rises above 4%","warning","Increase GLD to 15-17%. Add PDBC. Trim QQQ slightly. Hold SGOV — yields rise with inflation."),
        ("PCE falls below 2.5% for 3 months","","Fed pivot signal. Trim GLD/SLV 5%. Start IEF position. Increase SCHD/XLU. Long bonds become attractive."),
        ("Fed cuts rates","","XLU surges. SCHD/DGRO re-rate. Rotate SGOV into XLU/SCHD. Tech rallies — VGT benefits automatically."),
        ("Major IPO launches (Anthropic, OpenAI, SpaceX)","purple","Consider direct purchase at listing — don't wait for ETF index inclusion which takes months and comes after early gains."),
        ("Iran deal confirmed","warning","Trim XLE from 5% to 2-3%. Rotate into SCHD. Gold may pull back 10-15% on peace — hold through it."),
    ]
    for title,cls,guidance in decisions:
        st.markdown(f'<div class="signal-box {cls}"><b>{title}</b><br>{guidance}</div>',
                    unsafe_allow_html=True)

    st.markdown("---")
    st.caption("📌 Not financial advice. Consult a fee-only fiduciary financial advisor before making investment decisions. Data via Yahoo Finance.")

# ════════════════════════════════════════════════════════════
# TAB 9 — GROWTH SATELLITE  (Level 5.5, layered on the core All-Weather sleeve)
# ════════════════════════════════════════════════════════════
with tab9:
    st.markdown("### 🛰️ Growth Satellite — Selection, Exits & Rotation")
    st.caption(
        "A systematically-selected top-5 sleeve layered on top of the core "
        "All-Weather allocation. Screens the rotation universe below "
        "(deliberately excludes GLD/SLV/RING/XLE/PDBC/SCHD/XLV/XLU/SGOV/USFR/"
        "TLT/KMLM — those are already governed by the regime classifier at "
        "Level 1) for gate-passing names, ranks them, and tracks Level 6.5 "
        "exit discipline on whichever 5 names are currently held. This is "
        "tactical conviction capital, not the strategic core — see the "
        "Education tab's regime map for how the core sleeves rebalance."
    )

    sat_tickers = list(SATELLITE_UNIVERSE.keys())
    sat_ohlcv   = fetch_ohlcv(sat_tickers, "2y")

    if not sat_ohlcv:
        st.error("Universe data unavailable — try refreshing.")
    else:
        sat_perf_rows, sat_close_cache = [], {}
        for tkr, name in SATELLITE_UNIVERSE.items():
            if tkr not in sat_ohlcv:
                continue
            df = sat_ohlcv[tkr]
            close, volume = df["Close"], df.get("Volume")
            if len(close.dropna()) < 260:   # need ~1y for perf_1y + gate history
                continue
            sat_close_cache[tkr] = close

            tier      = SATELLITE_TIER.get(tkr, 2)
            threshold = TIER_THRESHOLDS[tier]
            vol_r     = _vol_ratio(volume) if volume is not None else 1.0
            vol_spike = vol_r >= threshold

            perf_1w, perf_1m, perf_3m = _pct(close, 5), _pct(close, 21), _pct(close, 63)
            perf_6m, perf_1y          = _pct(close, 126), _pct(close, 252)
            spread = round(perf_1m - (perf_3m / 3), 2)  # momentum_accel — context only, not a scoring input

            high, low = df.get("High"), df.get("Low")
            if high is not None and low is not None and volume is not None and len(close.dropna()) >= MIN_BARS_FLOW:
                cmf_series = chaikin_money_flow(high, low, close, volume)
                cmf_now = float(cmf_series.dropna().iloc[-1]) if cmf_series.notna().any() else None
                acc_score = accumulation_score(high, low, close, volume, vol_r, threshold)
                ev = event_score(high, low, close, volume, vol_r, threshold)
            else:
                cmf_now, acc_score = None, np.nan
                ev = {"event_score": 0.0, "event_direction": "None", "spike": vol_spike}
            sig = signal_label(cmf_now, vol_spike)

            sat_perf_rows.append({
                "Ticker": tkr, "Name": name,
                "perf_1w": perf_1w, "perf_1m": perf_1m, "perf_3m": perf_3m,
                "perf_6m": perf_6m, "perf_1y": perf_1y, "Spread": spread,
                "Tier": tier, "Vol Ratio": round(vol_r, 2), "Vol Spike": vol_spike,
                "CMF": cmf_now, "Accumulation Score": acc_score,
                "Event Score": ev["event_score"], "Event Direction": ev["event_direction"],
                "Signal": sig,
            })

        if not sat_perf_rows:
            st.warning("No universe data returned — try refreshing.")
        else:
            sat_perf_df = pd.DataFrame(sat_perf_rows).set_index("Ticker")
            # RRG on the FULL universe, unconditional — benchmark is the
            # equal-weighted mean of this universe, matching the money-flow
            # dashboard's actual methodology (never SPY).
            sat_perf_df = compute_universe_rrg(sat_perf_df)

            # Gate + ADX/ATR (this dashboard's own Level 5.5 addition — the
            # source dashboard has no trend gate, this layers one on top)
            sat_gate_rows = []
            for tkr in sat_perf_df.index:
                close = sat_close_cache[tkr]
                df = sat_ohlcv[tkr]
                gate = ma_slope_gate(close)
                sat_gate_rows.append({
                    "Ticker": tkr, "Gate": gate["pass"],
                    "ADX": calc_adx(df), "ATR": calc_atr(df),
                    "Close": float(close.iloc[-1]),
                    "Blended Ret": np.nanmean([sat_perf_df.loc[tkr,"perf_1m"],
                                                sat_perf_df.loc[tkr,"perf_3m"],
                                                sat_perf_df.loc[tkr,"perf_6m"]]),
                })
            sat_gate_df = pd.DataFrame(sat_gate_rows).set_index("Ticker")
            sat_df = sat_perf_df.join(sat_gate_df).reset_index()

            sat_gated = sat_df[sat_df["Gate"] == True].copy()

            if sat_gated.empty:
                st.markdown(
                    '<div class="signal-box danger"><b>No names clear the 200MA/slope gate.</b><br>'
                    "Zero eligible names is itself a breadth-deterioration signal, not just an "
                    "empty bench — see the Rotation Targets panel below for where uncommitted "
                    "capital should sit under the current regime rather than forcing a pick.</div>",
                    unsafe_allow_html=True)
            else:
                sat_gated["Ret %ile"] = sat_gated["Blended Ret"].rank(pct=True) * 100
                _rrg_pts_map = {"Leading":100, "Improving":70, "Weakening":35, "Lagging":0}
                sat_gated["RRG Pts"] = sat_gated["quadrant"].map(lambda q: _rrg_pts_map.get(q, 0))
                _adx_max = sat_gated["ADX"].max() if sat_gated["ADX"].notna().any() else 1
                sat_gated["Trend Pts"] = (sat_gated["ADX"].fillna(0) / (_adx_max or 1)) * 100
                # Accumulation Score (quiet, CMF-based — see accumulation_score())
                # is a raw ranking score (roughly -100..+100), not 0-100, so it
                # enters the composite the same way Blended Ret does: cross-
                # sectional percentile rank within the gated set. Names with
                # insufficient history (NaN) get a neutral 50, not a penalty —
                # missing data isn't the same as a bad signal.
                sat_gated["Flow Pts"] = sat_gated["Accumulation Score"].rank(pct=True).fillna(0.5) * 100
                sat_gated["Composite"] = (
                    0.35*sat_gated["Ret %ile"] + 0.25*sat_gated["RRG Pts"] +
                    0.25*sat_gated["Trend Pts"] + 0.15*sat_gated["Flow Pts"]
                ).round(1)

                sat_ranked = sat_gated.sort_values("Composite", ascending=False).reset_index(drop=True)
                sat_ranked.index = sat_ranked.index + 1
                sat_top5  = sat_ranked.head(SATELLITE_TOP_N)
                sat_bench = sat_ranked.iloc[SATELLITE_TOP_N:SATELLITE_TOP_N + SATELLITE_BENCH_N]

                st.markdown("#### Growth Satellite Score — Ranked")
                st.caption(
                    "Signal/Accum/Event columns use the CURRENT Institutional Rotation "
                    "Dashboard methodology (CMF-based, from High/Low/Close/Volume) — not "
                    "the older momentum+volume weighted score, which that dashboard's own "
                    "changelog flagged as inverted (loud volume outranking quiet, sustained "
                    "accumulation) and replaced. Accumulation Score and Event Score measure "
                    "opposite things (quiet absorption vs. loud activity) and are never summed."
                )
                sat_disp = sat_ranked[["Ticker","Name","Composite","quadrant","perf_1m","perf_3m","perf_6m",
                                        "ADX","Accumulation Score","Signal","Event Direction","Vol Spike"]].copy()
                sat_disp.columns = ["Ticker","Name","Composite","Quadrant","1M","3M","6M",
                                     "ADX","Accum Score","Signal","Event","🔊"]
                for c in ["1M","3M","6M"]:
                    sat_disp[c] = sat_disp[c].apply(lambda v: fmt(v) if pd.notna(v) else "—")
                sat_disp["ADX"] = sat_disp["ADX"].apply(lambda v: f"{v:.1f}" if pd.notna(v) else "—")
                sat_disp["Accum Score"] = sat_disp["Accum Score"].apply(lambda v: f"{v:+.0f}" if pd.notna(v) else "—")
                sat_disp["🔊"] = sat_disp["🔊"].map({True:"🔊", False:""})
                st.dataframe(sat_disp, use_container_width=True,
                    column_config={"Composite": st.column_config.ProgressColumn(
                        "Composite", min_value=0, max_value=100, format="%.1f")})
                st.caption(f"Rank 1–{SATELLITE_TOP_N}: live satellite holdings (index = rank). "
                           f"Rank {SATELLITE_TOP_N+1}–{SATELLITE_TOP_N+SATELLITE_BENCH_N}: bench, "
                           "promoted on a vacancy per the rotation rules below. Signal and 🔊 use "
                           "the same tiered volume-spike thresholds (1.25×/1.50×/2.00×/3.00× by "
                           "ADDV tier) as the Institutional Rotation Dashboard.")

                st.markdown("---")
                st.markdown("#### Exit Discipline — Level 6.5, per current holding")
                st.caption(
                    "Enter your actual entry price and initial stop for each holding to see "
                    "live R-multiples against the 2R/4R/8R default trim schedule. Defaults are "
                    "starting points — backtest before trusting them."
                )

                sat_basket_closes = {t: sat_close_cache[t] for t in sat_top5["Ticker"] if t in sat_close_cache}

                for _, row in sat_top5.iterrows():
                    tkr, close, atr, cur_price = row["Ticker"], sat_close_cache[row["Ticker"]], row["ATR"], row["Close"]
                    with st.expander(f"{tkr} — {row['Name']}  ·  Composite {row['Composite']}  ·  {row['quadrant']}"):
                        ec1, ec2, ec3 = st.columns(3)
                        entry_price = ec1.number_input(f"Your entry price ({tkr})", value=float(cur_price), key=f"sat_entry_{tkr}")
                        default_stop = entry_price - 2*atr if atr else entry_price*0.92
                        stop_price = ec2.number_input(f"Your stop price ({tkr})", value=float(round(default_stop,2)), key=f"sat_stop_{tkr}")
                        ec3.metric("Current Price", f"${cur_price:,.2f}")

                        r_unit = entry_price - stop_price
                        if r_unit > 0:
                            r_multiple = (cur_price - entry_price) / r_unit
                            tcols = st.columns(3)
                            for (thresh, label), col in zip(
                                [(2,"First trim (33%)"), (4,"Second trim (33%)"), (8,"Final exit (remainder)")], tcols):
                                hit = r_multiple >= thresh
                                col.metric(label, f"{thresh}R", "✅ Triggered" if hit else f"{r_multiple:.1f}R now")
                        else:
                            st.warning("Stop must be below entry to compute R-multiples.")

                        others = {k:v for k,v in sat_basket_closes.items() if k != tkr}
                        dc = calc_danger_composite(close, sat_ohlcv[tkr].get("Volume"), others)
                        cls = "danger" if dc["zone"]=="Euphoria" else ("warning" if dc["zone"]=="Elevated" else "info")
                        detail_str = " · ".join(f"{k}: +{v}" for k,v in dc["detail"].items() if v>0) or "none firing"
                        st.markdown(
                            f'<div class="signal-box {cls}"><b>Danger Composite: {dc["score"]}/10 — {dc["zone"]}</b><br>'
                            f"<small>{detail_str}</small></div>", unsafe_allow_html=True)
                        if dc["zone"] == "Euphoria":
                            st.caption("⚠️ Per the Level 6.5 iron rule: execute the next scheduled trim "
                                       "regardless of R-multiple tier, or exit outright if none has triggered yet.")

                st.markdown("---")
                st.markdown("#### Bench (ranks 6–10) — promotion candidates on a vacancy")
                if not sat_bench.empty:
                    sat_bdisp = sat_bench[["Ticker","Name","Composite","quadrant"]].copy()
                    sat_bdisp.columns = ["Ticker","Name","Composite","Quadrant"]
                    st.dataframe(sat_bdisp, use_container_width=True)
                else:
                    st.caption("Fewer than 10 names clear the gate — bench is thin. Treat as a "
                               "breadth warning alongside the empty-gate case above.")

            st.markdown("---")
            st.markdown("#### Rotation-on-Exit — where freed capital goes")
            st.caption(
                "The regime dashboard has veto power over the rotation dashboard. If a satellite "
                "position exits and no qualifying bench name exists — or the exit was a Danger "
                "Composite trigger rather than an idiosyncratic stop — route capital per the "
                "current regime row below instead of mechanically refilling the next-ranked name."
            )

            _sat_assessment = None
            if _REGIME_OK and fred_key_input:
                try:
                    _sat_assessment = full_assessment(fred_key_input)
                except Exception:
                    _sat_assessment = None

            if _sat_assessment is not None:
                _sat_reg_key = _sat_assessment["regime"]["key"]
                _sat_target, _sat_why = SATELLITE_ROTATION_TARGETS.get(
                    _sat_reg_key, SATELLITE_ROTATION_TARGETS["neutral"])
                st.markdown(
                    f'<div class="signal-box purple"><b>Live regime: {_sat_assessment["regime"]["label"]}</b><br>'
                    f"Route freed capital → <b>{_sat_target}</b><br><small>{_sat_why}</small></div>",
                    unsafe_allow_html=True)
                _sat_k = _sat_assessment["kmlm"]
                st.caption(f"KMLM sizing signal: {_sat_k['stance']} — {_sat_k['funding']}")
            else:
                st.info("Add a FRED key in the sidebar for a live regime-conditional target. "
                        "Static rotation table below covers all four regime rows in the meantime.")
                _sat_rt_rows = [{"Regime": k.replace('_',' ').title(), "Route To": v[0], "Why": v[1]}
                                for k, v in SATELLITE_ROTATION_TARGETS.items() if k != "neutral"]
                st.dataframe(pd.DataFrame(_sat_rt_rows), hide_index=True, use_container_width=True)

            st.markdown("---")
            st.caption(
                "Exit-reason bias (apply manually — not yet automated here): a plain ATR stop "
                "hit with no Danger Composite signal firing → refill from bench immediately. A "
                "Danger Composite / euphoria exit → skip refill for one weekly cycle before "
                "considering the next bench name, per the Level 6.5 cooling-off rule."
            )

    st.markdown("---")
    st.caption("📌 Not financial advice. Growth Satellite scoring is a decision-support tool, "
               "not a signal to act on automatically. Composite weights and gate thresholds are "
               "backtestable starting points, not fixed rules. Data via Yahoo Finance.")
