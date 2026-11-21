"""
market_radar.py  (v1.1 — 2026-11-21)
─────────────────────────────────────
Opportunity Radar (track C, widened at Matt's request 2026-11-20: "I want to keep a
wide eye on the markets to take advantage of any opportunities there are"; cadence:
"every Monday, Wednesday, and Friday along with notifications for sharp increases
and decreases"). Design: claude/opportunity_radar.md.

Runs every weekday evening after the close (workflow "Market Radar").
  PULSE (every run)   engine closes (SPY/QQQ vs 200-day, the O11 rule), SPY/QQQ/IWM
                      moves over 1, 5 and 10 sessions, and the biggest movers across
                      the universe measured against each fund's own volatility.
                      Notifies (GitHub issue that @mentions the owner) only for the
                      engine's 2nd close, a first cross, or a 5/10-session move.
  SCAN (Mon/Wed/Fri)  ~95 ETFs across US sectors and industries, size and style,
                      countries, commodities, rates, credit, currencies, themes and
                      crypto. Trend (close above a rising 200-day), strength vs SPY
                      (average of 3/6/12-month excess return), rank, distance from
                      the 52-week high. LEADER = in trend and top fifth by strength.
                      Flags what changed since the previous scan: NEW LEADER,
                      BREAKDOWN (a leader that lost its trend or fell below the top
                      40%). Every flag is logged and scored against SPY at 3, 6 and
                      12 months, so the radar's own edge is measured forward.
v1.1 (2026-11-21): brief_summary() — one reader of the radar's saved files for the
  daily brief (section 7A) and the app, so the two can never disagree. A missing or
  stale radar is reported as such, never as "no signal".

ALERT-ONLY. Nothing here changes the model book or the swing book.

Run:  python market_radar.py [--scan]     (Actions)
      python market_radar.py --selftest   (offline)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

VERSION = "1.1"
UNIVERSE = {
    # US broad, size and style
    "SPY": ("US broad", "S&P 500"), "QQQ": ("US broad", "Nasdaq-100"), "IWM": ("US broad", "Small caps"),
    "MDY": ("US broad", "Mid caps"), "RSP": ("US broad", "S&P 500 equal weight"),
    "IWD": ("US broad", "Large value"), "IWF": ("US broad", "Large growth"), "MTUM": ("US broad", "Momentum factor"),
    "USMV": ("US broad", "Min volatility"),
    # sectors
    "XLK": ("US sectors", "Technology"), "XLF": ("US sectors", "Financials"), "XLE": ("US sectors", "Energy"),
    "XLV": ("US sectors", "Health care"), "XLI": ("US sectors", "Industrials"), "XLY": ("US sectors", "Consumer discretionary"),
    "XLP": ("US sectors", "Consumer staples"), "XLU": ("US sectors", "Utilities"), "XLB": ("US sectors", "Materials"),
    "XLRE": ("US sectors", "Real estate"), "XLC": ("US sectors", "Communication"),
    # industries
    "SMH": ("US industries", "Semiconductors"), "IGV": ("US industries", "Software"), "KRE": ("US industries", "Regional banks"),
    "KBE": ("US industries", "Banks"), "XBI": ("US industries", "Biotech (equal weight)"), "IBB": ("US industries", "Biotech"),
    "ITB": ("US industries", "Homebuilders"), "XHB": ("US industries", "Home & building"), "ITA": ("US industries", "Aerospace & defense"),
    "XOP": ("US industries", "Oil & gas producers"), "OIH": ("US industries", "Oil services"), "XME": ("US industries", "Metals & mining"),
    "IYT": ("US industries", "Transports"), "XRT": ("US industries", "Retail"), "JETS": ("US industries", "Airlines"),
    "FDN": ("US industries", "Internet"), "IHI": ("US industries", "Medical devices"), "KIE": ("US industries", "Insurance"),
    # themes
    "GRID": ("Themes", "Grid infrastructure"), "PAVE": ("Themes", "US infrastructure"), "CIBR": ("Themes", "Cybersecurity"),
    "SKYY": ("Themes", "Cloud computing"), "BOTZ": ("Themes", "Robotics & AI"), "NLR": ("Themes", "Nuclear"),
    "URA": ("Themes", "Uranium"), "TAN": ("Themes", "Solar"), "ICLN": ("Themes", "Clean energy"),
    "ARKK": ("Themes", "Disruptive innovation"), "DTCR": ("Themes", "Data centers"), "UFO": ("Themes", "Space"),
    "LIT": ("Themes", "Lithium & batteries"),
    # international
    "EFA": ("International", "Developed ex-US"), "EEM": ("International", "Emerging markets"), "VGK": ("International", "Europe"),
    "EWJ": ("International", "Japan"), "EWG": ("International", "Germany"), "EWU": ("International", "United Kingdom"),
    "EWC": ("International", "Canada"), "EWA": ("International", "Australia"), "EWZ": ("International", "Brazil"),
    "EWW": ("International", "Mexico"), "INDA": ("International", "India"), "EWY": ("International", "South Korea"),
    "EWT": ("International", "Taiwan"), "FXI": ("International", "China large caps"), "KWEB": ("International", "China internet"),
    "ARGT": ("International", "Argentina"), "EZA": ("International", "South Africa"),
    # commodities
    "GLD": ("Commodities", "Gold"), "SLV": ("Commodities", "Silver"), "PPLT": ("Commodities", "Platinum"),
    "CPER": ("Commodities", "Copper"), "USO": ("Commodities", "Crude oil"), "UNG": ("Commodities", "Natural gas"),
    "DBA": ("Commodities", "Agriculture"), "DBC": ("Commodities", "Broad commodities"), "GDX": ("Commodities", "Gold miners"),
    "SIL": ("Commodities", "Silver miners"), "COPX": ("Commodities", "Copper miners"),
    # rates and credit
    "SHY": ("Rates & credit", "1–3y Treasuries"), "IEF": ("Rates & credit", "7–10y Treasuries"), "TLT": ("Rates & credit", "20y+ Treasuries"),
    "TIP": ("Rates & credit", "TIPS"), "LQD": ("Rates & credit", "Investment-grade credit"), "HYG": ("Rates & credit", "High yield"),
    "EMB": ("Rates & credit", "EM bonds"), "BKLN": ("Rates & credit", "Senior loans"),
    # currencies, alternatives, crypto
    "UUP": ("Currencies & alts", "US dollar"), "FXY": ("Currencies & alts", "Japanese yen"), "FXE": ("Currencies & alts", "Euro"),
    "DBMF": ("Currencies & alts", "Managed futures"), "KMLM": ("Currencies & alts", "Managed futures (KFA)"),
    "IBIT": ("Currencies & alts", "Bitcoin"), "ETHA": ("Currencies & alts", "Ether"),
}
INDEXES = ("SPY", "QQQ", "IWM")
LOOKBACK = (63, 126, 252)
LEADER_PCT, BREAKDOWN_PCT = 80.0, 60.0
HORIZONS = (63, 126, 252)
SCAN_DAYS = (0, 2, 4)                       # Monday, Wednesday, Friday
MULTI = ((5, 5.0), (10, 8.0))
TOP_MOVERS = 5
LABEL = "market-pulse"
OUT_DATA, OUT_LOGS = Path("data/radar"), Path("logs/radar")


# ── metrics ─────────────────────────────────────────────────────────────────

def metrics(closes: pd.DataFrame) -> pd.DataFrame:
    """One row per ticker, from closes up to the last row only."""
    spy = closes["SPY"]
    rows = {}
    for t in closes.columns:
        s = closes[t].dropna()
        if len(s) < 25:
            continue
        r = s.pct_change()
        vol = float(r.iloc[-21:-1].std()) if len(s) > 22 else float("nan")
        row = {"close": float(s.iloc[-1]), "ret_1d": float(s.iloc[-1] / s.iloc[-2] - 1) * 100,
               "ret_5d": float(s.iloc[-1] / s.iloc[-6] - 1) * 100 if len(s) > 6 else float("nan")}
        row["z_1d"] = row["ret_1d"] / (vol * 100) if vol and vol > 0 else float("nan")
        row["z_5d"] = row["ret_5d"] / (vol * 100 * math.sqrt(5)) if vol and vol > 0 else float("nan")
        if len(s) >= 221:
            ma = s.rolling(200).mean()
            row["trend"] = bool(s.iloc[-1] > ma.iloc[-1] and ma.iloc[-1] > ma.iloc[-21])
            row["vs_200d"] = float(s.iloc[-1] / ma.iloc[-1] - 1) * 100
        else:
            row["trend"], row["vs_200d"] = None, float("nan")
        ex = []
        for n in LOOKBACK:
            if len(s) > n and len(spy.dropna()) > n:
                sp = spy.reindex(s.index).ffill()
                ex.append((s.iloc[-1] / s.iloc[-1 - n] - 1) - (sp.iloc[-1] / sp.iloc[-1 - n] - 1))
        row["rs"] = float(np.mean(ex)) * 100 if len(ex) == len(LOOKBACK) else float("nan")
        row["from_high"] = float(s.iloc[-1] / s.iloc[-252:].max() - 1) * 100
        rows[t] = row
    m = pd.DataFrame.from_dict(rows, orient="index")
    m["rs_pct"] = m["rs"].rank(pct=True) * 100
    m.loc[m["rs"].isna(), "rs_pct"] = np.nan
    m["leader"] = (m["trend"] == True) & (m["rs_pct"] >= LEADER_PCT)  # noqa: E712
    return m


def flags(now: pd.DataFrame, prev_leaders: set) -> list:
    """NEW LEADER: a leader now that was not one at the previous scan. BREAKDOWN: a previous leader that
    lost its trend or fell below the 60th percentile."""
    out = []
    for t, r in now.iterrows():
        if r["leader"] and t not in prev_leaders:
            out.append((t, "new_leader"))
    for t in sorted(prev_leaders):
        if t not in now.index:
            continue
        r = now.loc[t]
        if r["trend"] is False or (np.isfinite(r["rs_pct"]) and r["rs_pct"] < BREAKDOWN_PCT):
            out.append((t, "breakdown"))
    return sorted(out)


def score_flags(fl: pd.DataFrame, closes: pd.DataFrame) -> pd.DataFrame:
    """Excess return over SPY since each flag, at each horizon that has passed (sessions)."""
    rows = []
    idx = closes.index
    for r in fl.itertuples():
        d = pd.Timestamp(r.date)
        if r.ticker not in closes or d not in idx:
            continue
        k0 = idx.get_loc(d)
        for h in HORIZONS:
            if k0 + h >= len(idx):
                continue
            a, s = closes[r.ticker], closes["SPY"]
            p0, p1, s0, s1 = a.iloc[k0], a.iloc[k0 + h], s.iloc[k0], s.iloc[k0 + h]
            if not all(np.isfinite([p0, p1, s0, s1])):
                continue
            rows.append({"date": d.date(), "ticker": r.ticker, "kind": r.kind, "horizon": h,
                         "excess_pct": round(((p1 / p0) - (s1 / s0)) * 100, 2)})
    return pd.DataFrame(rows, columns=["date", "ticker", "kind", "horizon", "excess_pct"])


def scoreboard(sc: pd.DataFrame) -> pd.DataFrame:
    if sc.empty:
        return pd.DataFrame(columns=["kind", "horizon", "n", "mean_excess_pct", "right_pct"])
    g = sc.groupby(["kind", "horizon"])
    out = g["excess_pct"].agg(n="size", mean_excess_pct="mean").reset_index()
    right = sc.assign(right=np.where(sc["kind"] == "breakdown", sc["excess_pct"] < 0, sc["excess_pct"] > 0))
    out["right_pct"] = right.groupby(["kind", "horizon"])["right"].mean().mul(100).round(0).to_numpy()
    out["mean_excess_pct"] = out["mean_excess_pct"].round(2)
    return out


# ── pulse ───────────────────────────────────────────────────────────────────

def pulse(closes: pd.DataFrame, m: pd.DataFrame) -> dict:
    """Close-of-day checks. Findings: (key, level, text)."""
    import intraday_watch as iw
    found, rows = [], []
    for t in INDEXES:
        s = closes[t].dropna() if t in closes else None
        if s is None or len(s) < 12:
            continue
        parts = [f"1 day {m.loc[t, 'ret_1d']:+.1f}%"] if t in m.index else []
        for n, lim in MULTI:
            mv = float(s.iloc[-1] / s.iloc[-1 - n] - 1) * 100
            parts.append(f"{n} sessions {mv:+.1f}%")
            if abs(mv) >= lim:
                found.append((f"multi:{t}:{n}:{'down' if mv < 0 else 'up'}", "ALERT",
                              f"{t} closed {mv:+.1f}% over {n} sessions{' — a sharp rally' if mv > 0 else ''}."))
        rows.append((t, ", ".join(parts)))
    for t, role in (("SPY", "Defense"), ("QQQ", "Offense vs Balanced")):
        e = iw.engine_cross(closes[t].dropna()) if t in closes else None
        if e is None:
            continue
        rows.append((f"{t} vs 200-day", f"{e['pct']:+.2f}% ({e['today_side']}; {e['prior_run']} close(s) "
                                         f"{e['prior_side']} before today)"))
        if e["today_side"] != e["prior_side"]:
            found.append((f"engine1:{t}:{e['today_side']}", "WARN",
                          f"{t} closed {e['today_side']} its 200-day ({e['pct']:+.1f}%): close #1 of 2 ({role} rule)."))
        elif e["prior_run"] == 1:
            found.append((f"engine2:{t}:{e['today_side']}", "ALERT",
                          f"{t} closed {e['today_side']} its 200-day for the 2nd day ({e['pct']:+.1f}%): the O11 "
                          f"{role} rule fires; the model trades next session."))
    mv = m.dropna(subset=["z_1d"])
    up = mv.sort_values("z_1d", ascending=False).head(TOP_MOVERS)
    dn = mv.sort_values("z_1d").head(TOP_MOVERS)
    return {"found": found, "rows": rows, "up": up, "down": dn}


# ── notification ────────────────────────────────────────────────────────────

class Issues:
    def __init__(self, repo: str, token: str, http=None):
        import requests
        self.http = http or requests
        self.h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        self.base = f"https://api.github.com/repos/{repo}"

    def open_issues(self) -> list:
        r = self.http.get(f"{self.base}/issues", headers=self.h,
                          params={"labels": LABEL, "state": "open", "per_page": 20}, timeout=30)
        return r.json() if r.status_code == 200 else []

    def create(self, title, body):
        self.http.post(f"{self.base}/labels", headers=self.h, timeout=30,
                       json={"name": LABEL, "color": "fbca04", "description": "Market Radar pulse"})
        return self.http.post(f"{self.base}/issues", headers=self.h, timeout=30,
                              json={"title": title, "body": body, "labels": [LABEL]}).json()

    def close(self, number):
        self.http.patch(f"{self.base}/issues/{number}", headers=self.h, timeout=30, json={"state": "closed"})


def notify(found: list, today: str, issues, owner: str) -> dict:
    """One issue per day with ALERT/WARN findings; earlier days' pulse issues are closed."""
    for i in issues.open_issues():
        if i.get("title", "").startswith("Market pulse — ") and not i["title"].endswith(today):
            issues.close(i["number"])
    loud = [f for f in found if f[1] in ("ALERT", "WARN")]
    if not loud:
        return {"action": "none"}
    if any(i.get("title") == f"Market pulse — {today}" for i in issues.open_issues()):
        return {"action": "none", "reason": "already sent today"}
    body = f"@{owner}\n\n**After the close** (alert-only; the engine and the books act only on their rules)\n\n" + \
        "\n".join(f"- **{lvl}** — {txt}" for _, lvl, txt in loud) + "\n\nFull report: logs/radar/latest.md"
    issues.create(f"Market pulse — {today}", body)
    return {"action": "create", "keys": [k for k, _, _ in loud]}


def name(t: str) -> str:
    return UNIVERSE.get(t, ("", t))[1]


def area(t: str) -> str:
    return UNIVERSE.get(t, ("Other", ""))[0]


# ── report ──────────────────────────────────────────────────────────────────

def _p(x, nd=1, pct=True):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:+.{nd}f}{'%' if pct else ''}"


def render(stamp: str, pl: dict, m: pd.DataFrame, scan: bool, fl: list, board: pd.DataFrame, notes: list) -> str:
    L = [f"# Market Radar {VERSION} — {stamp}", "",
         "Alert-only. The O11 engine and the swing desk act only on their own rules. Research, not personalized advice.", "",
         "## Pulse (after the close)", ""]
    L += [f"- **{lvl}** — {txt}" for _, lvl, txt in pl["found"]] or ["- Nothing loud today."]
    L += ["", "| Item | Reading |", "|---|---|"] + [f"| {a} | {b} |" for a, b in pl["rows"]]
    L += ["", "**Biggest moves today, against each fund's normal volatility**", "",
          "| Up | Move | σ | Down | Move | σ |", "|---|---|---|---|---|---|"]
    for (tu, ru), (td, rd) in zip(pl["up"].iterrows(), pl["down"].iterrows()):
        L.append(f"| {tu} {name(tu)} | {_p(ru['ret_1d'])} | {ru['z_1d']:+.1f} | "
                 f"{td} {name(td)} | {_p(rd['ret_1d'])} | {rd['z_1d']:+.1f} |")
    if scan:
        lead = m[m["leader"]].sort_values("rs", ascending=False)
        L += ["", "## Scan (Mon/Wed/Fri)", "",
              f"Leaders (in an uptrend and top fifth by strength vs SPY): **{len(lead)}** of {int(m['rs'].notna().sum())} ranked.", ""]
        nl = [t for t, k in fl if k == "new_leader"]
        bd = [t for t, k in fl if k == "breakdown"]
        L += [f"- **New leaders:** {', '.join(f'{t} ({name(t)})' for t in nl) or 'none'}",
              f"- **Breakdowns:** {', '.join(f'{t} ({name(t)})' for t in bd) or 'none'}", "",
              "| Fund | Area | Strength vs SPY | Rank | vs 200-day | From 52w high | 5 days |", "|---|---|---|---|---|---|---|"]
        for t, r in lead.iterrows():
            L.append(f"| {t} {name(t)} | {area(t)} | {_p(r['rs'])} | {r['rs_pct']:.0f} | "
                     f"{_p(r['vs_200d'])} | {_p(r['from_high'])} | {_p(r['ret_5d'])} |")
        L += ["", "### By area (median strength vs SPY; funds in an uptrend)", "", "| Area | Funds | In uptrend | Median strength |", "|---|---|---|---|"]
        m2 = m.assign(area=[area(t) for t in m.index])
        for a, g in m2.groupby("area"):
            L.append(f"| {a} | {len(g)} | {int((g['trend'] == True).sum())} | {_p(g['rs'].median())} |")  # noqa: E712
        L += ["", "### Radar scoreboard (flags scored vs SPY after 3, 6, 12 months)", ""]
        if board.empty:
            L.append("No flag is old enough to score yet (first scores after 63 sessions).")
        else:
            L += ["| Flag | Horizon (sessions) | Scored | Mean excess vs SPY | Right % |", "|---|---|---|---|---|"]
            L += [f"| {r.kind} | {r.horizon} | {r.n} | {r.mean_excess_pct:+.2f}% | {r.right_pct:.0f} |" for r in board.itertuples()]
    if notes:
        L += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    L += ["", f"*market_radar.py {VERSION}*"]
    return "\n".join(L) + "\n"


# ── reader for the brief and the app (v1.1) ────────────────────────────────

def _read_csv(p: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(p) if p.exists() else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def brief_summary(data_dir="data", session=None, max_leaders: int = 12, movers: int = 3) -> dict:
    """What the daily brief and the app show from the radar's last run. Pure file reads.
    `session` (date or ISO string): the session the reader is about; the radar is STALE
    when its last bar is older (a missing radar is a data gap, not a quiet market)."""
    d = Path(data_dir) / "radar"
    out = {"available": False, "version": VERSION, "asof": None, "stale": None, "scan_date": None,
           "pulse": [], "leaders": [], "flags": [], "movers_up": [], "movers_down": [], "areas": [],
           "scoreboard": [], "notes": [], "conclusion": ""}
    try:
        lj = json.loads((d / "latest.json").read_text())
    except Exception as e:
        out["conclusion"] = (f"Radar has not published ({type(e).__name__}) — no market-wide read today. "
                             "This is a data gap, not a quiet market.")
        return out
    m = _read_csv(d / "latest_metrics.csv")
    if m.empty:
        out["conclusion"] = "Radar metrics file missing — no market-wide read today (data gap)."
        return out
    m = m.rename(columns={m.columns[0]: "ticker"}).set_index("ticker")
    asof = lj.get("asof")
    out.update(available=True, asof=asof, pulse=list(lj.get("pulse") or []), notes=list(lj.get("notes") or []))
    sess = str(session)[:10] if session is not None else None
    out["stale"] = bool(sess and asof and asof < sess)
    # leaders now (every run recomputes them), strongest first
    if "leader" in m:
        lead = m[m["leader"].astype(str).str.lower() == "true"].sort_values("rs", ascending=False)
        out["leaders"] = [{"ticker": t, "name": name(t), "area": area(t), "rs": _r(r.get("rs")),
                           "vs_200d": _r(r.get("vs_200d")), "from_high": _r(r.get("from_high")),
                           "ret_5d": _r(r.get("ret_5d"))} for t, r in lead.head(max_leaders).iterrows()]
        out["n_leaders"], out["n_ranked"] = int(len(lead)), int(m["rs"].notna().sum())
    # biggest moves vs each fund's own volatility
    if "z_1d" in m:
        z = m.dropna(subset=["z_1d"]).sort_values("z_1d")
        pick = lambda df: [{"ticker": t, "name": name(t), "ret_1d": _r(r["ret_1d"]), "z_1d": _r(r["z_1d"])}
                           for t, r in df.iterrows()]
        out["movers_up"] = pick(z[z["z_1d"] > 0].iloc[::-1].head(movers))
        out["movers_down"] = pick(z[z["z_1d"] < 0].head(movers))
    # areas: funds in an uptrend
    if "trend" in m:
        tr = m["trend"].astype(str).str.lower() == "true"
        g = pd.DataFrame({"area": [area(t) for t in m.index], "up": tr.to_numpy(), "rs": m["rs"].to_numpy()})
        out["areas"] = [{"area": a, "funds": int(len(x)), "uptrend": int(x["up"].sum()),
                         "median_rs": _r(x["rs"].median())} for a, x in g.groupby("area")]
    # last scan and its flags
    hist = _read_csv(d / "scan_history.csv")
    if not hist.empty and "date" in hist:
        out["scan_date"] = str(hist["date"].max())
        fl = _read_csv(d / "flags.csv")
        if not fl.empty:
            fl = fl[fl["date"].astype(str) == out["scan_date"]]
            out["flags"] = [{"ticker": r.ticker, "name": name(r.ticker), "kind": r.kind} for r in fl.itertuples()]
    sc = _read_csv(d / "scores.csv")
    if not sc.empty:
        out["scoreboard"] = scoreboard(sc).to_dict("records")
    # one-paragraph conclusion
    loud = [x for x in out["pulse"] if x.get("level") in ("ALERT", "WARN")]
    nl = [x["ticker"] for x in out["flags"] if x["kind"] == "new_leader"]
    bd = [x["ticker"] for x in out["flags"] if x["kind"] == "breakdown"]
    c = (f"Radar (as of the {asof} close): {out.get('n_leaders', 0)} of {out.get('n_ranked', 0)} funds lead "
         "(uptrend and top fifth vs SPY)")
    if out["leaders"]:
        c += " — strongest " + ", ".join(x["ticker"] for x in out["leaders"][:5])
    c += ". "
    if out["scan_date"]:
        first = any(str(n).startswith("First scan") for n in out["notes"]) and out["scan_date"] == asof
        c += (f"Last scan {out['scan_date']}: "
              + ("first scan, nothing to compare yet" if first and not out["flags"] else "")
              + ("" if first and not out["flags"] else ("new leaders " + ", ".join(nl) if nl else "no new leaders"))
              + ("" if first and not out["flags"] else ("; breakdowns " + ", ".join(bd) if bd else "; no breakdowns"))
              + ". ")
    if loud:
        c += f"{len(loud)} close alert(s): " + " ".join(x["text"] for x in loud) + " "
    if out["stale"]:
        c = f"⚠ STALE — the radar's last bar is {asof}, older than the {sess} session. " + c
    out["conclusion"] = c.strip() + " Alert-only: no book acts on it."
    return out


def _r(v, dp: int = 2):
    try:
        v = float(v)
        return None if math.isnan(v) else round(v, dp)
    except (TypeError, ValueError):
        return None


# ── run ─────────────────────────────────────────────────────────────────────

def fetch(tickers: list, period: str = "3y") -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(tickers, period=period, interval="1d", auto_adjust=True, progress=False,
                     group_by="column", threads=True)
    c = df["Close"] if "Close" in df.columns.get_level_values(0) else df
    if getattr(c.index, "tz", None) is not None:
        c.index = c.index.tz_localize(None)
    return c.dropna(how="all")


def main() -> int:
    import market_time as mt
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    a, _ = ap.parse_known_args()
    now = mt.now_et()
    stamp = now.date().isoformat()
    scan = a.scan or now.weekday() in SCAN_DAYS
    notes = []
    closes = fetch(sorted(UNIVERSE))
    missing = sorted(set(UNIVERSE) - set(closes.columns[closes.notna().any()]))
    if "SPY" not in closes or closes["SPY"].dropna().empty:
        print("[radar] DATA FAILURE: no SPY; nothing written.")
        return 1
    last = pd.Timestamp(closes["SPY"].dropna().index[-1]).date()
    if last != now.date():
        notes.append(f"Latest SPY bar is {last}, not today ({now.date()}): data delayed or not a session.")
    if missing:
        notes.append(f"No data for {len(missing)} fund(s): {', '.join(missing)}.")
    m = metrics(closes)
    pl = pulse(closes, m)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_LOGS.mkdir(parents=True, exist_ok=True)
    fl, board = [], pd.DataFrame()
    hist_p, flags_p = OUT_DATA / "scan_history.csv", OUT_DATA / "flags.csv"
    if scan:
        hist = pd.read_csv(hist_p) if hist_p.exists() else pd.DataFrame(columns=["date", "ticker", "leader", "rs", "rs_pct", "trend"])
        prev = hist[hist["date"] < str(last)]
        prev_leaders = set(prev[prev["date"] == prev["date"].max()].query("leader == True")["ticker"]) if len(prev) else None
        if prev_leaders is None:
            notes.append("First scan: no earlier scan to compare, so no flags today.")
        else:
            fl = flags(m, prev_leaders)
        snap = m.reset_index().rename(columns={"index": "ticker"})[["ticker", "leader", "rs", "rs_pct", "trend"]].assign(date=str(last))
        hist = pd.concat([hist[hist["date"] != str(last)], snap[["date", "ticker", "leader", "rs", "rs_pct", "trend"]]])
        hist.round(3).to_csv(hist_p, index=False)
        fdf = pd.read_csv(flags_p) if flags_p.exists() else pd.DataFrame(columns=["date", "ticker", "kind", "close"])
        fdf = fdf[fdf["date"] != str(last)]
        new = pd.DataFrame([{"date": str(last), "ticker": t, "kind": k, "close": round(m.loc[t, "close"], 4)} for t, k in fl],
                           columns=["date", "ticker", "kind", "close"])
        fdf = pd.concat([fdf, new])
        fdf.to_csv(flags_p, index=False)
        sc = score_flags(fdf, closes)
        sc.to_csv(OUT_DATA / "scores.csv", index=False)
        board = scoreboard(sc)
    m.round(3).to_csv(OUT_DATA / "latest_metrics.csv")
    (OUT_DATA / "latest.json").write_text(json.dumps({
        "asof": str(last), "scan": scan, "pulse": [{"key": k, "level": lv, "text": tx} for k, lv, tx in pl["found"]],
        "leaders": sorted(m.index[m["leader"]].tolist()), "flags": [{"ticker": t, "kind": k} for t, k in fl],
        "notes": notes}, indent=1))
    md = render(stamp, pl, m, scan, fl, board, notes)
    (OUT_LOGS / "latest.md").write_text(md)
    (OUT_LOGS / f"{stamp}.md").write_text(md)
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(md)
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or (repo or "/").split("/")[0]
    if token and repo and last == now.date():
        try:
            print(notify(pl["found"], stamp, Issues(repo, token), owner))
        except Exception as e:
            print(f"[radar] notify failed (report still written): {e}")
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    f = []
    idx = pd.bdate_range(end="2026-11-20", periods=400)
    n = len(idx)

    def walk(drift, vol=0.01, seed=0):
        r = np.random.default_rng(seed).normal(drift, vol, n)
        return pd.Series(100 * np.exp(np.cumsum(r)), index=idx)
    closes = pd.DataFrame({"SPY": walk(0.0004, 0.008, 1), "QQQ": walk(0.0005, 0.01, 2), "IWM": walk(0.0002, 0.012, 3),
                           "STRONG": walk(0.0025, 0.01, 4), "WEAK": walk(-0.0015, 0.01, 5), "FLAT": walk(0.0, 0.01, 6)})
    for k in range(10):
        closes[f"F{k}"] = walk(0.0003 * (k - 4), 0.01, 10 + k)
    m = metrics(closes)
    if not m.loc["STRONG", "leader"] or m.loc["WEAK", "leader"] or m.loc["WEAK", "trend"]:
        f.append(f"leader = uptrend and top fifth: {m.loc[['STRONG', 'WEAK'], ['trend', 'rs_pct', 'leader']].to_dict()}")
    s, sp = closes["STRONG"], closes["SPY"]
    exp = np.mean([(s.iloc[-1] / s.iloc[-1 - k] - 1) - (sp.iloc[-1] / sp.iloc[-1 - k] - 1) for k in LOOKBACK]) * 100
    if abs(m.loc["STRONG", "rs"] - exp) > 1e-9:
        f.append("strength = mean 3/6/12-month excess over SPY")
    if abs(m.loc["SPY", "rs"]) > 1e-9:
        f.append("SPY's strength vs itself is zero")
    short = closes.copy()
    short.loc[short.index[:300], "FLAT"] = np.nan
    ms = metrics(short)
    if np.isfinite(ms.loc["FLAT", "rs"]) or ms.loc["FLAT", "trend"] is not None or ms.loc["FLAT", "leader"]:
        f.append("a fund with under a year of history is not ranked or trended")
    # a leader must be in an uptrend; an uptrend needs a RISING 200-day
    t2 = pd.DataFrame({"SPY": closes["SPY"]}, index=idx)
    for k in range(10):
        t2[f"G{k}"] = walk(0.0002 - 0.0001 * k, 0.01, 30 + k)          # all lag SPY
    up = np.r_[100 * np.exp(np.cumsum(np.full(n - 10, 0.006))), np.zeros(10)]
    up[-10:] = up[-11] * np.linspace(0.97, 0.5, 10)                  # big 12-month gain, then a crash
    t2["SPIKE"] = up
    rb = np.r_[np.full(n - 170, 100.0), np.linspace(100, 40, 150), np.linspace(40, 120, 20)]
    t2["REBOUND"] = rb
    m2 = metrics(t2)
    if m2.loc["SPIKE", "rs_pct"] < LEADER_PCT or m2.loc["SPIKE", "trend"] or m2.loc["SPIKE", "leader"]:
        f.append(f"top strength but below the 200-day is not a leader: {m2.loc['SPIKE', ['rs_pct', 'trend', 'leader']].to_dict()}")
    if m2.loc["REBOUND", "vs_200d"] <= 0 or m2.loc["REBOUND", "trend"]:
        f.append("above a FALLING 200-day is not an uptrend")
    # no look-ahead: metrics on data to day k equal metrics computed with later rows dropped
    m_cut = metrics(closes.iloc[:300])
    m_full_then = metrics(closes.loc[:closes.index[299]])
    if not np.allclose(m_cut["rs"].dropna(), m_full_then["rs"].dropna()):
        f.append("metrics use only rows up to the scan date")
    # z-score
    jump = closes.copy()
    jump.iloc[-1, jump.columns.get_loc("FLAT")] = jump["FLAT"].iloc[-2] * 1.05
    mj = metrics(jump)
    vol = jump["FLAT"].pct_change().iloc[-21:-1].std() * 100
    if abs(mj.loc["FLAT", "z_1d"] - mj.loc["FLAT", "ret_1d"] / vol) > 1e-9 or mj.loc["FLAT", "z_1d"] < 3:
        f.append("1-day move in units of the fund's own 20-day volatility")
    # flags
    fl = flags(m, prev_leaders={"WEAK", "STRONG"})
    if ("WEAK", "breakdown") not in fl or ("STRONG", "new_leader") in fl or ("STRONG", "breakdown") in fl:
        f.append(f"flags vs previous scan: {fl}")
    fl2 = flags(m, prev_leaders=set())
    if ("STRONG", "new_leader") not in fl2:
        f.append("a leader not on the previous list is new")
    # scoring
    fdf = pd.DataFrame([{"date": str(idx[100].date()), "ticker": "STRONG", "kind": "new_leader", "close": 1.0},
                        {"date": str(idx[100].date()), "ticker": "WEAK", "kind": "breakdown", "close": 1.0},
                        {"date": str(idx[-10].date()), "ticker": "STRONG", "kind": "new_leader", "close": 1.0}])
    sc = score_flags(fdf, closes)
    h63 = sc[(sc["ticker"] == "STRONG") & (sc["horizon"] == 63)]
    e63 = ((closes["STRONG"].iloc[163] / closes["STRONG"].iloc[100]) - (closes["SPY"].iloc[163] / closes["SPY"].iloc[100])) * 100
    if len(h63) != 1 or abs(h63["excess_pct"].iloc[0] - round(e63, 2)) > 1e-9:
        f.append("excess vs SPY over the horizon")
    if len(sc[sc["date"] == idx[-10].date()]):
        f.append("a flag younger than the horizon is not scored")
    b = scoreboard(sc)
    bd = b[(b["kind"] == "breakdown") & (b["horizon"] == 63)]
    wk = sc[(sc["kind"] == "breakdown") & (sc["horizon"] == 63)]["excess_pct"].iloc[0]
    if len(bd) != 1 or bd["right_pct"].iloc[0] != (100.0 if wk < 0 else 0.0):
        f.append("a breakdown is right when the fund then lags SPY")
    # pulse
    slide = closes.copy()
    v = slide["SPY"].to_numpy().copy()
    ma = pd.Series(v).rolling(200).mean().to_numpy()
    v[-1] = ma[-1] * 0.97
    v[-2] = ma[-2] * 0.97
    v[-3] = ma[-3] * 1.02
    slide["SPY"] = v
    p = pulse(slide, metrics(slide))
    keys = {k for k, _, _ in p["found"]}
    if "engine2:SPY:below" not in keys:
        f.append(f"2nd close below SPY's 200-day must alert: {keys}")
    drop = closes.copy()
    w = drop["IWM"].to_numpy().copy()
    w[-5:] = w[-6] * np.linspace(0.98, 0.93, 5)
    drop["IWM"] = w
    if "multi:IWM:5:down" not in {k for k, _, _ in pulse(drop, metrics(drop))["found"]}:
        f.append("a 7% five-session slide must alert")
    if any(k.startswith("multi") for k, _, _ in pulse(closes, m)["found"]):
        f.append("quiet tape: no multi-session alert")
    # notify
    class FI:
        def __init__(self):
            self.items, self.closed, self.created = [{"number": 1, "title": "Market pulse — 2026-11-19"}], [], []
        def open_issues(self):
            return [i for i in self.items if i["number"] not in self.closed]
        def create(self, t, b):
            self.items.append({"number": 9, "title": t}); self.created.append(t)
        def close(self, n):
            self.closed.append(n)
    fi = FI()
    if notify([("x", "INFO", "y")], "2026-11-20", fi, "me")["action"] != "none" or fi.closed != [1]:
        f.append("INFO only: no issue; yesterday's closed")
    fi = FI()
    notify([("engine2:SPY:below", "ALERT", "t")], "2026-11-20", fi, "me")
    if fi.created != ["Market pulse — 2026-11-20"] or notify([("a", "ALERT", "t")], "2026-11-20", fi, "me")["action"] != "none":
        f.append("one issue per day")
    md = render("T", p, metrics(slide), True, fl, b, ["n"])
    if "Pulse" not in md or "Radar scoreboard" not in md:
        f.append("report sections")
    # v1.1: brief_summary reads the saved files; missing / stale are said, never read as quiet
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    if brief_summary(tmp, "2026-11-20")["available"] or "data gap" not in brief_summary(tmp)["conclusion"]:
        f.append("brief_summary: a missing radar must be unavailable and called a data gap")
    rd = tmp / "radar"
    rd.mkdir()
    mm = pd.DataFrame({"close": [1.0, 1, 1, 1], "ret_1d": [2.0, -3, 0.5, -0.1], "z_1d": [3.0, -2.5, 0.4, float("nan")],
                       "ret_5d": [1.0, 1, 1, 1], "trend": [True, False, True, True], "vs_200d": [5.0, -4, 2, 1],
                       "rs": [20.0, -10, 5, 1], "from_high": [-1.0, -9, -2, -3], "rs_pct": [100.0, 25, 75, 50],
                       "leader": [True, False, False, False]}, index=["XLV", "SMH", "XLE", "SPY"])
    mm.to_csv(rd / "latest_metrics.csv")
    (rd / "latest.json").write_text(json.dumps({"asof": "2026-11-23", "scan": True, "notes": [],
                                                "pulse": [{"key": "k", "level": "ALERT", "text": "SPY closed -8.6%."},
                                                          {"key": "i", "level": "INFO", "text": "quiet"}]}))
    pd.DataFrame({"date": ["2026-11-20", "2026-11-23"], "ticker": ["XLE", "XLV"], "leader": [True, True],
                  "rs": [1.0, 2], "rs_pct": [90.0, 95], "trend": [True, True]}).to_csv(rd / "scan_history.csv", index=False)
    pd.DataFrame({"date": ["2026-11-20", "2026-11-23", "2026-11-23"], "ticker": ["SMH", "XLV", "XLE"],
                  "kind": ["new_leader", "new_leader", "breakdown"], "close": [1.0, 1, 1]}).to_csv(rd / "flags.csv", index=False)
    bs = brief_summary(tmp, "2026-11-23")
    if not bs["available"] or bs["stale"] or bs["scan_date"] != "2026-11-23":
        f.append(f"brief_summary: fresh read {bs['stale']} {bs['scan_date']}")
    if [x["ticker"] for x in bs["leaders"]] != ["XLV"] or bs.get("n_leaders") != 1 or bs.get("n_ranked") != 4:
        f.append("brief_summary: leaders come from the leader column, strongest first")
    if sorted((x["ticker"], x["kind"]) for x in bs["flags"]) != [("XLE", "breakdown"), ("XLV", "new_leader")]:
        f.append("brief_summary: only the last scan's flags")
    if [x["ticker"] for x in bs["movers_up"]] != ["XLV", "XLE"] or [x["ticker"] for x in bs["movers_down"]] != ["SMH"]:
        f.append("brief_summary: movers by z, NaN skipped")
    if "new leaders XLV" not in bs["conclusion"] or "breakdowns XLE" not in bs["conclusion"] \
            or "SPY closed -8.6%" not in bs["conclusion"] or "quiet" in bs["conclusion"]:
        f.append("brief_summary: conclusion names flags and only ALERT/WARN pulse lines")
    if not brief_summary(tmp, "2026-11-24")["stale"] or "STALE" not in brief_summary(tmp, "2026-11-24")["conclusion"]:
        f.append("brief_summary: an older bar than the session must be STALE")
    if {a["area"]: a["uptrend"] for a in bs["areas"]}.get("US sectors") != 2:
        f.append("brief_summary: uptrend count by area")
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest()
        print(json.dumps(r, indent=2, default=str))
        sys.exit(0 if r["ok"] else 1)
    sys.exit(main())
