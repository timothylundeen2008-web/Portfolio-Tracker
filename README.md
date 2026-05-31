# 📊 All-Weather Portfolio Dashboard

A Streamlit dashboard for tracking your portfolio of ETFs against their respective benchmarks, analyzing category performance, and getting educated on market signals.

---

## 🚀 Setup & Launch

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the dashboard
```bash
streamlit run app.py
```

The dashboard opens in your browser at `http://localhost:8501`

---

## 📋 Dashboard Tabs

| Tab | What it does |
|-----|-------------|
| 🏠 **Overview** | Portfolio return vs S&P 500, Nasdaq, Gold, Bonds. Full holdings table with status. |
| 📈 **ETF vs Benchmark** | Deep dive on any single ETF — cumulative return, relative strength, drawdown, stats. |
| 🗂️ **Category Performance** | Growth/Tech, Precious Metals, Defensives etc. vs S&P 500. Heatmap of daily returns. |
| 🏗️ **Portfolio Construction** | Donut charts (by holding and category), allocation bars, expense ratio calculator, rebalancing alerts. |
| 📡 **Market Signals** | Live VIX, gold/SPY ratio, yield curve, golden/death cross, 30-day momentum. |
| 📚 **Education** | Guides on drawdown, moving averages, VIX, yield curve, inflation signals, rebalancing, decision framework. |

---

## ⚙️ Sidebar Controls

- **Time Period:** 1 month to 5 years
- **Custom Allocation Sliders:** Adjust any holding's weight and see portfolio impact in real time
- **Alert Threshold:** Set how many % an ETF must lag its benchmark before flagging

---

## 💼 Portfolio Holdings

| Ticker | Name | Category | Allocation |
|--------|------|----------|-----------|
| VGT | Vanguard Info Tech | Growth/Tech | 20% |
| SMH | VanEck Semiconductors | Growth/Tech | 8% |
| QQQ | Invesco Nasdaq-100 | Growth/Tech | 7% |
| GLD | SPDR Gold Shares | Precious Metals | 12% |
| SLV | iShares Silver Trust | Precious Metals | 5% |
| RING | iShares Gold Miners | Precious Metals | 5% |
| XLE | Energy Select SPDR | Commodities/Energy | 5% |
| PDBC | Invesco Commodity | Commodities/Energy | 3% |
| SCHD | Schwab Dividend Equity | Defensives | 13% |
| XLV | Health Care Select SPDR | Defensives | 4% |
| XLU | Utilities Select SPDR | Defensives | 3% |
| SGOV | iShares 0-3M Treasury | Short Bonds/Cash | 10% |
| USFR | WisdomTree Floating Rate | Short Bonds/Cash | 5% |

---

## 🔄 Deploying to Streamlit Cloud (Free)

1. Push this folder to a GitHub repo
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo
4. Set main file: `app.py`
5. Deploy — no server needed

---

⚠️ *Not financial advice. Data via Yahoo Finance. For informational purposes only.*
