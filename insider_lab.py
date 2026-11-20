"""
insider_lab.py  (v1.0 — 2026-11-20)
────────────────────────────────────
Track B: insider cluster buying (swing book). Pre-registration:
claude/insider_lab_2026-11-20.md. Approved by Matt 2026-11-18 ("Let's look at all of
them") and 2026-11-20 ("proceed to the next build"). Data: edgar_data v1.3
(officer/director open-market buys at S&P 500 members, 2006-01 to 2026-03, mapped
to the company that was the member at the time, survivorship-free).

SIGNAL (frozen before any run)
  A buy counts when it is an open-market purchase (code P) by an officer or
  director, worth at least $10,000 (Form 4 shares × price), and is NOT routine: the
  same insider did not buy the same company in the same calendar month in either of
  the two prior years.
  A cluster fires on filing date F when the counting buys of one company filed on or
  before F with trade dates in the 30 days before F come from at least 3 different
  insiders, total at least $100,000, and at least one of them was filed on F.
  One signal per company per 30 days. The company must be an S&P 500 member that
  month (edgar_data already restricts buys to members).
TRADE
  Buy at the open of the first session after F. Exit at the open 60 sessions later,
  or at the next open after a close below entry − 3×ATR(14) (ATR as of the day before
  entry). 1R = 3×ATR. Costs 5bp a side; stop exits 10bp worse. No market filter
  (insider buying is often contrarian; the thesis is tested as stated).
MEASURES
  Trade level: R per trade; 60-session excess return vs SPY (open to open, same days).
  Book: 10% of equity per position, at most 10 positions, idle cash in T-bills (^IRX);
  same-day signals ranked by cluster dollar value. Starts $10,000 on 2006-01-03.
BAR (trade level, both halves 2006–15 and 2016–26):
  100+ trades, 30+ per half; expectancy > 0R and profit factor ≥ 1.3 in each half;
  mean excess return vs SPY > 0 in each half.
  ROBUST: also positive expectancy when every signal with no free price data counts at
  the candidate's own average loss (per-signal stress — the SEC data says exactly which
  signals could not be priced).
  STABLE (reported): the 40- and 90-session holds also meet the bar.
  Book figures (CAGR, max DD, vs SPY and vs the live T-bill M0 book) are reported, not judged.
TRIALS: 1 + 2 neighbours = 3 (swing 84 → 87).

Run:  python insider_lab.py            (Actions, ~15–30 min)
      python insider_lab.py --selftest (offline)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

VERSION = "1.0"
MIN_BUY = 10_000.0
MIN_CLUSTER = 100_000.0
MIN_INSIDERS = 3
WINDOW_DAYS = 30
COOLDOWN_DAYS = 30
ROUTINE_YEARS = 2
HOLD = 60
NEIGHBOURS = (40, 90)
ATR_MULT = 3.0
COST_BPS, STOP_SLIP_BPS = 5.0, 10.0
POS_PCT, MAX_POS = 10.0, 10
START_EQUITY = 10_000.0
EVAL_START = pd.Timestamp("2006-01-03")
HALF_SPLIT = pd.Timestamp("2016-01-01")
HALVES = ("2006-15", "2016-26")
BAR = {"min_trades": 100, "min_per_half": 30, "min_pf": 1.3}
PRIOR_SWING_TRIALS = 84
DATA_START = "2005-01-01"
OUT_DATA, OUT_LOGS = Path("data/insider_lab"), Path("logs/insider_lab")


# ── signals ─────────────────────────────────────────────────────────────────

def counting_buys(buys: pd.DataFrame) -> pd.DataFrame:
    """Buys that count: value ≥ MIN_BUY and not routine. Routine = same owner, same company, a buy in
    the same calendar month of either of the ROUTINE_YEARS prior years (any size)."""
    b = buys.copy()
    b["value"] = b["shares"].astype(float) * b["price"].astype(float)
    b["owner"] = b["owner"].astype(str)
    ym = set(zip(b["cik"], b["owner"], b["trans_date"].dt.year, b["trans_date"].dt.month))
    routine = [any((c, o, y - k, m) in ym for k in range(1, ROUTINE_YEARS + 1))
               for c, o, y, m in zip(b["cik"], b["owner"], b["trans_date"].dt.year, b["trans_date"].dt.month)]
    b["routine"] = routine
    ok = (b["value"] >= MIN_BUY) & (b["value"] < 1e9) & (b["price"] > 0) & ~b["routine"]
    return b[ok].reset_index(drop=True)


def clusters(cb: pd.DataFrame) -> pd.DataFrame:
    """Signals: (ticker, cik, date F, insiders, value). See module docstring."""
    out = []
    for cik, g in cb.sort_values("filed").groupby("cik"):
        last = None
        for F in g["filed"].drop_duplicates():
            if last is not None and (F - last).days < COOLDOWN_DAYS:
                continue
            w = g[(g["filed"] <= F) & (g["trans_date"] >= F - pd.Timedelta(days=WINDOW_DAYS))]
            if w["owner"].nunique() >= MIN_INSIDERS and w["value"].sum() >= MIN_CLUSTER and (w["filed"] == F).any():
                out.append({"ticker": w["ticker"].iloc[-1], "cik": int(cik), "date": F,
                            "insiders": int(w["owner"].nunique()), "value": float(w["value"].sum())})
                last = F
    return pd.DataFrame(out, columns=["ticker", "cik", "date", "insiders", "value"])


# ── trades ──────────────────────────────────────────────────────────────────

def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def trade(sig: dict, df: pd.DataFrame, spy: pd.DataFrame, hold: int) -> dict:
    """One trade or {'status': reason}. df/spy: OHLC indexed by date."""
    idx = df.index
    k = int(idx.searchsorted(sig["date"], side="right"))           # first session strictly after F
    if k >= len(idx) or k < 15 or (idx[k] - sig["date"]).days > 7:
        return {"status": "no price at entry"}
    a = atr(df).iloc[k - 1]
    entry = float(df["Open"].iloc[k])
    if not (np.isfinite(a) and a > 0 and np.isfinite(entry) and entry > 0):
        return {"status": "no price at entry"}
    risk = ATR_MULT * float(a)
    stop = entry - risk
    closes, opens = df["Close"].to_numpy(float), df["Open"].to_numpy(float)
    xk, how = None, "time"
    for j in range(k, min(k + hold, len(idx))):
        if closes[j] < stop:
            xk, how = j + 1, "stop"
            break
    if xk is None:
        xk = k + hold
    if xk >= len(idx):
        return {"status": "still open"}
    px = opens[xk] * (1 - (COST_BPS + (STOP_SLIP_BPS if how == "stop" else 0)) / 1e4)
    cost_in = entry * (1 + COST_BPS / 1e4)
    d0, d1 = idx[k], idx[xk]
    s = spy["Open"]
    try:
        spy_ret = float(s.loc[d1] / s.loc[d0] - 1)
    except KeyError:
        spy_ret = float("nan")
    ret = px / cost_in - 1
    return {"status": "ok", "ticker": sig["ticker"], "signal": sig["date"], "entry_date": d0, "exit_date": d1,
            "entry": entry, "exit": float(opens[xk]), "exit_how": how, "ret": ret,
            "r": (px - cost_in) / risk, "excess": ret - spy_ret if np.isfinite(spy_ret) else float("nan"),
            "insiders": sig["insiders"], "value": sig["value"]}


def stats(rs: list) -> dict:
    r = np.array([x for x in rs if np.isfinite(x)], dtype=float)
    if len(r) == 0:
        return {"n": 0}
    gp, gl = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": int(len(r)), "expectancy_R": round(float(r.mean()), 3), "win_pct": round(float((r > 0).mean() * 100), 1),
            "profit_factor": round(float(gp / gl), 2) if gl > 0 else float("inf")}


def half_of(d) -> str:
    return HALVES[0] if pd.Timestamp(d) < HALF_SPLIT else HALVES[1]


def judge(trs: list) -> dict:
    ok = [t for t in trs if pd.Timestamp(t["entry_date"]) >= EVAL_START]
    full = stats([t["r"] for t in ok])
    out = {"full": full, "halves": {}, "excess": {}}
    why = []
    if full.get("n", 0) < BAR["min_trades"]:
        why.append(f"{full.get('n', 0)} trades < {BAR['min_trades']}")
    for h in HALVES:
        sub = [t for t in ok if half_of(t["entry_date"]) == h]
        st = stats([t["r"] for t in sub])
        ex = [t["excess"] for t in sub if np.isfinite(t["excess"])]
        out["halves"][h] = st
        out["excess"][h] = {"mean_pct": round(float(np.mean(ex)) * 100, 2) if ex else None,
                            "t": round(float(np.mean(ex) / (np.std(ex, ddof=1) / math.sqrt(len(ex)))), 2) if len(ex) > 2 and np.std(ex) > 0 else None}
        if st.get("n", 0) < BAR["min_per_half"]:
            why.append(f"{h}: {st.get('n', 0)} trades < {BAR['min_per_half']}")
            continue
        if st["expectancy_R"] <= 0:
            why.append(f"{h}: expectancy {st['expectancy_R']}R ≤ 0")
        if st["profit_factor"] < BAR["min_pf"]:
            why.append(f"{h}: profit factor {st['profit_factor']} < {BAR['min_pf']}")
        if not ex or np.mean(ex) <= 0:
            why.append(f"{h}: mean excess vs SPY {out['excess'][h]['mean_pct']}% ≤ 0")
    out["why"] = why
    out["meets"] = not why
    return out


def stress(trs: list, n_unpriced: int) -> dict:
    """Per-signal stress: each unpriced signal at 0R (neutral) or at the candidate's own average loss (harsh)."""
    r = np.array([t["r"] for t in trs if pd.Timestamp(t["entry_date"]) >= EVAL_START], dtype=float)
    if len(r) == 0:
        return {"unpriced": n_unpriced}
    loss = r[r < 0]
    al = float(loss.mean()) if len(loss) else 0.0
    n = len(r) + n_unpriced
    gp, gl = r[r > 0].sum(), -loss.sum() + n_unpriced * abs(al)
    return {"unpriced": n_unpriced, "avg_loss_R": round(al, 2), "neutral_exp_R": round(float(r.sum() / n), 3),
            "harsh_exp_R": round(float((r.sum() + n_unpriced * al) / n), 3),
            "harsh_pf": round(float(gp / gl), 2) if gl > 0 else float("inf")}


# ── book ────────────────────────────────────────────────────────────────────

def book(trs: list, prices: dict, cal: pd.DatetimeIndex, rate: pd.Series) -> pd.Series:
    """Daily equity. Positions of POS_PCT% of equity (prior close) at their entry open, at most MAX_POS;
    same-day entries by cluster value. Exits at their exit open. Idle cash earns rate (per day, prior day's)."""
    by_entry = {}
    for t in trs:
        by_entry.setdefault(pd.Timestamp(t["entry_date"]), []).append(t)
    cash, pos, eq_prev, out, most = START_EQUITY, [], START_EQUITY, [], 0
    rate = rate.reindex(cal).ffill().fillna(0.0).to_numpy()
    for k, d in enumerate(cal):
        if k > 0 and cash > 0:
            cash *= 1 + rate[k - 1]
        for p in [p for p in pos if p["t"]["exit_date"] == d]:
            px = p["t"]["exit"] * (1 - (COST_BPS + (STOP_SLIP_BPS if p["t"]["exit_how"] == "stop" else 0)) / 1e4)
            cash += p["sh"] * px
            pos.remove(p)
        for t in sorted(by_entry.get(d, []), key=lambda x: (-x["value"], x["ticker"])):
            if len(pos) >= MAX_POS:
                break
            amt = min(eq_prev * POS_PCT / 100, cash)
            if amt <= 1:
                continue
            sh = amt / (t["entry"] * (1 + COST_BPS / 1e4))
            cash -= amt
            pos.append({"t": t, "sh": sh})
        most = max(most, len(pos))
        mv = 0.0
        for p in pos:
            s = prices[p["t"]["ticker"]]["Close"]
            v = s.asof(d) if len(s) else np.nan
            mv += p["sh"] * (v if np.isfinite(v) else p["t"]["entry"])
        eq_prev = cash + mv
        out.append(eq_prev)
    eq = pd.Series(out, index=cal)
    eq.attrs["max_positions"] = most
    return eq


def eq_stats(eq: pd.Series, a=None, b=None) -> dict:
    s = eq[(eq.index >= (a or eq.index[0])) & (eq.index < (b or eq.index[-1] + pd.Timedelta(days=1)))]
    if len(s) < 2:
        return {}
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1 if yrs > 0.5 else float("nan")
    return {"cagr_pct": round(cagr * 100, 2), "max_dd_pct": round(float((s / s.cummax() - 1).min()) * 100, 1)}


# ── run ─────────────────────────────────────────────────────────────────────

def run(sigs: pd.DataFrame, prices: dict, spy: pd.DataFrame, holds=(HOLD, *NEIGHBOURS)) -> dict:
    res = {}
    for h in holds:
        trs, status, unpriced = [], {}, 0
        for s in sigs.to_dict("records"):
            df = prices.get(s["ticker"])
            r = trade(s, df, spy, h) if df is not None else {"status": "no price data"}
            status[r["status"]] = status.get(r["status"], 0) + 1
            if r["status"] == "ok":
                trs.append(r)
            elif r["status"] in ("no price data", "no price at entry") and pd.Timestamp(s["date"]) >= EVAL_START:
                unpriced += 1
        # one position per company at a time: drop a signal whose entry falls inside an earlier trade
        trs.sort(key=lambda t: (t["ticker"], t["entry_date"]))
        kept, busy = [], {}
        for t in trs:
            if t["ticker"] in busy and t["entry_date"] < busy[t["ticker"]]:
                status["overlap"] = status.get("overlap", 0) + 1
                continue
            kept.append(t)
            busy[t["ticker"]] = t["exit_date"]
        res[h] = {"trades": kept, "status": status, "judge": judge(kept), "stress": stress(kept, unpriced)}
    return res


def render(res: dict, sigs: pd.DataFrame, cb_n: int, books: dict, spy_st: dict, stamp: str, notes: list) -> str:
    j, st = res[HOLD]["judge"], res[HOLD]["stress"]
    verdict = "FAIL" if not j["meets"] else ("ROBUST PASS" if st.get("harsh_exp_R", -1) > 0 else "PASS")
    stable = j["meets"] and all(res[h]["judge"]["meets"] for h in NEIGHBOURS)
    L = [f"# Insider lab {VERSION} — {stamp}", "",
         "Track B: insider cluster buying. Rules and bar fixed before the run (claude/insider_lab_2026-11-20.md). "
         "Research, not personalized advice.", "",
         f"## Verdict: **{verdict}**" + (f" — {'; '.join(j['why'])}" if j["why"] else "") + f" · **{'STABLE' if stable else 'NOT STABLE'}**", "",
         f"Counting buys: {cb_n}; cluster signals: {len(sigs)} ({int((sigs['date'] >= EVAL_START).sum())} from 2006).", "",
         "| Hold | Trades | 2006–15 exp R / PF | 2016–26 exp R / PF | Excess vs SPY 06–15 / 16–26 | Win % | Harsh stress exp R |",
         "|---|---|---|---|---|---|---|"]
    for h in (HOLD, *NEIGHBOURS):
        jj, ss = res[h]["judge"], res[h]["stress"]
        a, b = jj["halves"][HALVES[0]], jj["halves"][HALVES[1]]
        ea, eb = jj["excess"][HALVES[0]], jj["excess"][HALVES[1]]
        L.append(f"| {h} sessions{' (decision)' if h == HOLD else ''} | {jj['full'].get('n', 0)} | "
                 f"{a.get('expectancy_R')} / {a.get('profit_factor')} (n {a.get('n', 0)}) | "
                 f"{b.get('expectancy_R')} / {b.get('profit_factor')} (n {b.get('n', 0)}) | "
                 f"{ea['mean_pct']}% (t {ea['t']}) / {eb['mean_pct']}% (t {eb['t']}) | {jj['full'].get('win_pct')} | "
                 f"{ss.get('harsh_exp_R')} |")
    L += ["", f"Signal outcomes ({HOLD}-session hold): {res[HOLD]['status']}. Unpriced signals from 2006 (stressed): "
              f"{st.get('unpriced')}; neutral expectancy {st.get('neutral_exp_R')}R, harsh {st.get('harsh_exp_R')}R "
              f"(PF {st.get('harsh_pf')}).", "",
          "## Book (reported, not judged): 10% positions, up to 10, idle cash in T-bills", "",
          "| Book | CAGR 2006–26 | 2006–15 | 2016–26 | Max DD |", "|---|---|---|---|---|"]
    for k, v in books.items():
        L.append(f"| {k} | {v['full'].get('cagr_pct')}% | {v['h1'].get('cagr_pct')}% | {v['h2'].get('cagr_pct')}% | {v['full'].get('max_dd_pct')}% |")
    L.append(f"| SPY | {spy_st['full'].get('cagr_pct')}% | {spy_st['h1'].get('cagr_pct')}% | {spy_st['h2'].get('cagr_pct')}% | {spy_st['full'].get('max_dd_pct')}% |")
    L += ["", "Live swing reference: M0 on ETFs with T-bill idle cash backtests at 2.94% a year (ROT3 lab, 2005–26).", "",
          "## Notes", ""] + [f"- {n}" for n in notes] + ["", f"*insider_lab.py {VERSION}*"]
    return "\n".join(L) + "\n", verdict, stable


def main() -> int:
    import edgar_data as ed
    import stock_lab as sl
    import swing_backtest as bt
    D = ed.load()
    notes = []
    cb = counting_buys(D.buys)
    sigs = clusters(cb)
    print(f"[insider_lab] v{VERSION}: {len(D.buys)} buys, {len(cb)} counting, {len(sigs)} cluster signals")
    tick = sorted(set(sigs["ticker"]))
    yahoo = {}
    import universe_probe as up
    want = sorted({up.yahoo_symbol(t) for t in tick} | {up.RENAMES[t] for t in tick if t in up.RENAMES} | {"SPY"})
    for i in range(0, len(want), 150):
        yahoo.update(bt.fetch_ohlcv(want[i:i + 150], start=DATA_START))
    rates = bt.fetch_ohlcv(["^IRX"], start=DATA_START)
    if "SPY" not in yahoo:
        print("[insider_lab] DATA FAILURE: no SPY; nothing written.")
        return 1
    have = set(yahoo)
    prices = {t: yahoo[sl.symbol_for(t, have)] for t in tick if sl.symbol_for(t, have)}
    notes.append(f"{len(prices)} of {len(tick)} signal companies have free (Yahoo) prices; the rest are stressed per signal.")
    spy = yahoo["SPY"]
    res = run(sigs, prices, spy)
    cal = spy.index[spy.index >= EVAL_START]
    irx = rates.get("^IRX")
    rate = (irx["Close"] / 100 / 252).clip(lower=0) if irx is not None else pd.Series(0.0, index=cal)
    if irx is None:
        notes.append("^IRX missing: idle cash earns 0% in the book.")
    books = {}
    for h in (HOLD, *NEIGHBOURS):
        eq = book(res[h]["trades"], prices, cal, rate)
        books[f"Insider {h}-session"] = {"eq": eq, "full": eq_stats(eq), "h1": eq_stats(eq, None, HALF_SPLIT),
                                         "h2": eq_stats(eq, HALF_SPLIT)}
    spyc = spy["Close"][spy.index >= EVAL_START]
    spy_st = {"full": eq_stats(spyc), "h1": eq_stats(spyc, None, HALF_SPLIT), "h2": eq_stats(spyc, HALF_SPLIT)}
    stamp = date.today().isoformat()
    md, verdict, stable = render(res, sigs, len(cb), books, spy_st, stamp, notes)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_LOGS.mkdir(parents=True, exist_ok=True)
    sigs.to_csv(OUT_DATA / "signals.csv", index=False)
    pd.DataFrame(res[HOLD]["trades"]).to_csv(OUT_DATA / "trades.csv", index=False)
    pd.DataFrame({k: v["eq"] for k, v in books.items()}).round(2).to_csv(OUT_DATA / "equity.csv")
    (OUT_DATA / "summary.json").write_text(json.dumps(
        {"verdict": verdict, "stable": stable, **{str(h): {"judge": res[h]["judge"], "stress": res[h]["stress"],
                                                           "status": res[h]["status"]} for h in res},
         "books": {k: {"full": v["full"], "h1": v["h1"], "h2": v["h2"]} for k, v in books.items()}},
        indent=1, default=str))
    tl = OUT_DATA / "trial_log.csv"
    first = not tl.exists()
    row = pd.DataFrame([{"date": stamp, "version": VERSION, "trials": 3 if first else 0,
                         "note": "insider clusters, 60-session hold + 40/90 neighbours" if first else "re-run"}])
    (pd.concat([pd.read_csv(tl), row]) if tl.exists() else row).to_csv(tl, index=False)
    md = md.replace("*insider_lab.py", f"Trials: {'3 new (swing 84 → 87)' if first else 'none new (re-run)'}.\n\n*insider_lab.py")
    (OUT_LOGS / f"{stamp}_report.md").write_text(md)
    (OUT_LOGS / "latest.md").write_text(md)
    print(md)
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _px(n=400, start="2009-01-02", drift=0.0, vol=0.01, seed=1, jump=None):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    c = 50 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    if jump:
        k, f = jump
        c[k:] *= f
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.002, n))
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.005, "Low": np.minimum(o, c) * 0.995,
                         "Close": c, "Volume": 1e6}, index=idx)


def selftest() -> dict:
    f = []
    T = pd.Timestamp
    rows = []

    def buy(cik, owner, td, fd, sh=1000, px=50.0, tk="AAA"):
        rows.append({"accession": f"{cik}-{owner}-{td}", "filed": T(fd), "cik": cik, "trans_date": T(td),
                     "shares": sh, "price": px, "owner": owner, "role": "Director", "ticker": tk})
    # cluster: 3 insiders, $50k each, completes on the third filing
    buy(1, "a", "2012-03-01", "2012-03-02"); buy(1, "b", "2012-03-05", "2012-03-06"); buy(1, "c", "2012-03-08", "2012-03-09")
    # too small: 3 insiders but $3k each
    buy(2, "a", "2012-03-01", "2012-03-02", sh=60, tk="BBB"); buy(2, "b", "2012-03-05", "2012-03-06", sh=60, tk="BBB")
    buy(2, "c", "2012-03-08", "2012-03-09", sh=60, tk="BBB")
    # routine: same three insiders bought in March of the prior year
    for o in "abc":
        buy(3, o, "2011-03-10", "2011-03-11", tk="CCC")
        buy(3, o, "2012-03-10", "2012-03-12", tk="CCC")
    # spread out: third buy 40 days later
    buy(4, "a", "2012-03-01", "2012-03-02", tk="DDD"); buy(4, "b", "2012-03-05", "2012-03-06", tk="DDD")
    buy(4, "c", "2012-04-20", "2012-04-21", tk="DDD")
    # one insider three times
    for d in ("2012-03-01", "2012-03-05", "2012-03-08"):
        buy(5, "a", d, d, tk="EEE")
    B = pd.DataFrame(rows)
    cb = counting_buys(B)
    if set(cb["ticker"]) - {"AAA", "DDD", "EEE", "CCC"} or (cb["ticker"] == "BBB").any():
        f.append("buys under $10,000 must not count")
    ccc = cb[cb["ticker"] == "CCC"]
    if len(ccc) != 3 or (ccc["trans_date"].dt.year == 2012).any():
        f.append(f"routine buys (same insider, same month, prior year) must not count: {ccc[['owner', 'trans_date']].values.tolist()}")
    s = clusters(cb)
    if list(s["ticker"]) != ["AAA", "CCC"] or s.iloc[0]["date"] != T("2012-03-09") or s.iloc[0]["insiders"] != 3 \
            or s.iloc[1]["date"] != T("2011-03-11"):
        f.append(f"AAA fires on the third filing; CCC only in its first (non-routine) year: {s.to_dict('records')}")
    if s.iloc[0]["value"] != 150_000:
        f.append("cluster value = sum of counting buys")
    # cooldown: a fourth insider 10 days later does not fire again; one 40 days later does
    buy(1, "d", "2012-03-15", "2012-03-19"); buy(1, "e", "2012-04-25", "2012-04-26"); buy(1, "f", "2012-04-26", "2012-04-27")
    buy(1, "g", "2012-04-27", "2012-04-30")
    s2 = clusters(counting_buys(pd.DataFrame(rows)))
    a2 = s2[s2["ticker"] == "AAA"]["date"].tolist()
    if a2 != [T("2012-03-09"), T("2012-04-30")]:
        f.append(f"one signal per company per 30 days: {a2}")
    # trades: entry the session AFTER the filing, time exit after the hold, stop on a close below 3×ATR
    df = _px(400, drift=0.001)
    spy = _px(400, drift=0.0003, seed=9)
    sig = {"ticker": "AAA", "date": df.index[100], "insiders": 3, "value": 2e5}
    t = trade(sig, df, spy, 60)
    if t["entry_date"] != df.index[101] or t["exit_date"] != df.index[161] or t["exit_how"] != "time":
        f.append(f"entry next session, exit 60 sessions later: {t.get('entry_date')} {t.get('exit_date')} {t.get('exit_how')}")
    if abs(t["entry"] - df["Open"].iloc[101]) > 1e-9:
        f.append("entry at the next open")
    exp_sp = spy["Open"].iloc[161] / spy["Open"].iloc[101] - 1
    if abs(t["excess"] - (t["ret"] - exp_sp)) > 1e-12:
        f.append("excess vs SPY over the same open-to-open window")
    sig_f = {**sig, "date": df.index[100] - pd.Timedelta(hours=1)}            # filed before the session: same rule
    if trade(sig_f, df, spy, 60)["entry_date"] != df.index[100]:
        f.append("a filing dated the day before enters that session")
    crash = _px(400, drift=0.0, seed=3, jump=(130, 0.6))
    tc = trade({**sig, "date": crash.index[100]}, crash, spy, 60)
    if tc["exit_how"] != "stop" or tc["exit_date"] != crash.index[131] or tc["r"] > -1.0:
        f.append(f"a 40% gap down stops out at the next open, worse than −1R: {tc.get('exit_how')} {tc.get('exit_date')} {tc.get('r')}")
    if trade({**sig, "date": df.index[-5]}, df, spy, 60)["status"] != "still open":
        f.append("a trade without an exit inside the data is still open, not counted")
    if trade({**sig, "date": df.index[0] - pd.Timedelta(days=30)}, df, spy, 60)["status"] != "no price at entry":
        f.append("a signal before the price history is unpriced")
    # judge and stress
    mk = lambda r, d, ex=0.01: {"r": r, "entry_date": T(d), "excess": ex}
    good = [mk(1.0, "2008-01-02") for _ in range(30)] + [mk(-0.5, "2009-01-02") for _ in range(20)] + \
           [mk(1.0, "2018-01-02") for _ in range(30)] + [mk(-0.5, "2019-01-02") for _ in range(20)]
    if not judge(good)["meets"]:
        f.append(f"a clean candidate meets the bar: {judge(good)['why']}")
    bad_ex = [{**x, "excess": -0.01} if x["entry_date"].year > 2016 else x for x in good]
    if judge(bad_ex)["meets"]:
        f.append("negative excess vs SPY in a half must fail")
    thin = [x for x in good if x["entry_date"].year < 2016] + [mk(1.0, "2018-01-02") for _ in range(10)]
    if judge(thin)["meets"]:
        f.append("fewer than 30 trades in a half must fail")
    st = stress(good, 50)
    if st["avg_loss_R"] != -0.5 or abs(st["harsh_exp_R"] - (60 - 20 - 25) / 150) > 1e-3:
        f.append(f"per-signal stress: {st}")
    # book: one trade, 10% of equity
    cal = df.index[100:200]
    eq = book([t], {"AAA": df}, cal, pd.Series(0.0, index=cal))
    sh = (START_EQUITY * 0.10) / (t["entry"] * (1 + COST_BPS / 1e4))
    exp_end = START_EQUITY * 0.9 + sh * t["exit"] * (1 - COST_BPS / 1e4)
    if abs(eq.iloc[-1] - exp_end) > 1e-6:
        f.append(f"book accounting: {eq.iloc[-1]:.4f} vs {exp_end:.4f}")
    many = [{**t, "ticker": f"T{i}", "value": float(i)} for i in range(12)]
    pr = {f"T{i}": df for i in range(12)}
    eq2 = book(many, pr, cal, pd.Series(0.0, index=cal))
    if not (abs(eq2.loc[t["entry_date"]] - START_EQUITY) < START_EQUITY * 0.02):
        f.append("at most 10 positions at 10% each, never more than the cash")
    # cap: 10 positions open, one exits with a gain, two new signals the next day -> only one enters
    up_df = _px(400, drift=0.004, seed=4)
    t0 = trade({**sig, "date": up_df.index[100]}, up_df, spy, 60)
    first = [{**t0, "ticker": f"T{i}", "value": 10.0 + i} for i in range(10)]
    early = {**t0, "ticker": "T0", "exit_date": up_df.index[110], "exit": float(up_df["Open"].iloc[110]), "exit_how": "time"}
    first[0] = early
    later = [{**t0, "ticker": f"N{i}", "entry_date": up_df.index[111], "entry": float(up_df["Open"].iloc[111]),
              "value": 1.0 + i} for i in range(2)]
    flat = up_df.copy()
    flat[["Open", "High", "Low", "Close"]] = float(up_df["Open"].iloc[101])            # the other nine go nowhere
    pr2 = {**{f"T{i}": flat for i in range(1, 10)}, "T0": up_df, "N0": up_df, "N1": up_df}
    eq3 = book(first + later, pr2, up_df.index[100:200], pd.Series(0.0, index=up_df.index[100:200]))
    if eq3.attrs["max_positions"] > MAX_POS:
        f.append(f"never more than {MAX_POS} positions: {eq3.attrs['max_positions']}")
    # risk unit uses ATR as of the day before entry
    a_prev = float(atr(df).iloc[100])
    cost_in = t["entry"] * (1 + COST_BPS / 1e4)
    px_out = t["exit"] * (1 - COST_BPS / 1e4)
    if abs(t["r"] - (px_out - cost_in) / (ATR_MULT * a_prev)) > 1e-9:
        f.append("1R = 3×ATR(14) as of the day before entry")
    # a cluster of three $12k buys ($36k) is under the $100k cluster minimum
    small = pd.DataFrame([{"accession": o, "filed": T("2013-05-0" + str(i + 2)), "cik": 9, "trans_date": T("2013-05-01"),
                           "shares": 240, "price": 50.0, "owner": o, "role": "Officer", "ticker": "SML"}
                          for i, o in enumerate("xyz")])
    if len(clusters(counting_buys(small))):
        f.append("a cluster under $100,000 in total must not fire")
    # run(): overlap with an open trade is dropped
    s3 = pd.DataFrame([{**sig, "date": df.index[100]}, {**sig, "date": df.index[120]}, {**sig, "date": df.index[200]}])
    r3 = run(s3, {"AAA": df}, spy, holds=(60,))
    if len(r3[60]["trades"]) != 2 or r3[60]["status"].get("overlap") != 1:
        f.append(f"one position per company at a time: {r3[60]['status']}")
    r4 = run(pd.DataFrame([{**sig, "ticker": "ZZZ", "date": T("2010-06-01")}]), {}, spy, holds=(60,))
    if r4[60]["stress"]["unpriced"] != 1:
        f.append("an unpriced signal is counted in the stress")
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        r = selftest()
        print(json.dumps(r, indent=2, default=str))
        sys.exit(0 if r["ok"] else 1)
    sys.exit(main())
