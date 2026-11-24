"""
m0t_stock_lab.py  (v1.0 — 2026-11-23)
──────────────────────────────────────
Swing book only. Trial 99, pre-registered in claude/m0t_stock_lab_2026-11-23.md (Matt 2026-11-23:
"Yes to building 1, 2, and 3"). Bars are fixed BEFORE any run on real prices; a FAIL is final.

Question: M0-T's trade edge on ETFs is strong (+0.44R, PF 1.83) but the $10k book is capacity-bound
(36% invested, 382 of 2,101 trades taken). Does adding S&P 500 stocks, judged point-in-time, give
the book enough good trades to beat the market?

C1 (decision) = ONE $10,000 book taking M0-T trades from BOTH universes:
  * ETFs: the live 41-fund universe, exactly as trial 97 (bt.run M0 + m0t.resimulate, no rotation
    exit, no ladder), SPY above its 200-day at the signal;
  * stocks: S&P 500 members ON THE SIGNAL DAY (data/universe/sp500_membership.csv), signals from the
    production detectors via stock_lab.build_signals (M0 only kept), the same M0-T exits (no rotation
    exit, no ladder), stock_lab's forced close when a stock's prices end (acquired / delisted);
  * the portfolio pass is swing_backtest.run_portfolio, live sizing (1% / 0.5%, streak halving),
    4 positions, 2 per sector (stocks share their sector ETF's sector), 8% heat, 30% cap, T-bills idle.
Window: signals from 2017-01-01 (free stock prices); halves 2017–21 and 2022–26 (as stock_lab).

References, not trials: ETF-only M0-T and stock-only M0-T on the same window and pass.

Run:  python m0t_stock_lab.py            (Actions; needs yfinance; ~1–2 hours)
      python m0t_stock_lab.py --selftest (offline)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import m0t_lab as m0t
import stock_lab as sl
import swing_backtest as bt
import universe_probe as up

VERSION = "1.0"
OUT_DATA, OUT_LOGS = Path("data/m0t_stock_lab"), Path("logs/m0t_stock_lab")
TRIALS_BEFORE, TRIALS_HERE = 98, 1
HALVES = sl.HALVES                          # ("2017-21", "2022-26")
BAR = {"min_trades": 100, "min_half": 30, "min_pf": 1.3, "max_dd": -20.0, "max_months_le_10": 0}


def _log(msg: str) -> None:
    print(f"[m0t_stock_lab {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def etf_universe() -> tuple:
    etfs = bt.SECTOR_ETFS + list(bt.OTHER_ETFS)
    sector_of = {s: s for s in bt.SECTOR_ETFS}
    sector_of.update(bt.OTHER_ETFS)
    return etfs, sector_of


def etf_trades(ohlcv: dict) -> tuple:
    """Trial 97's M0-T on the ETF universe, entries from the test window, SPY > 200-day. -> (trades, unfilled, data)."""
    etfs, sector_of = etf_universe()
    sub = {t: ohlcv[t] for t in etfs if t in ohlcv}
    res = bt.run(sub, etfs, [], sector_of, setups=("M0",), variants=("B",), verbose=False)
    trs, unf = m0t.resimulate(res, ladder=(), rotation=False)
    d = res["data"]
    trs = [t for t in trs if t.mkt_ok and d[t.ticker]["index"][t.entry_t] >= sl.TEST_START]
    unf = [g for g in unf if g.mkt_ok and g.t + 1 < len(d[g.ticker]["index"]) and d[g.ticker]["index"][g.t + 1] >= sl.TEST_START]
    return trs, unf, d


def stock_trades(ohlcv: dict, iv: dict, sector_of: dict) -> tuple:
    """M0-T on S&P 500 members by date. -> (trades, unfilled, data, uncovered-by-year, n members, n priced)."""
    spy = ohlcv["SPY"]
    cal = pd.DatetimeIndex(spy.index)
    end = cal[-1]
    bench = spy["Close"]
    mkt = bt.market_ok(bench)
    quads_by_sector = bt.rotation_proxy({k: v["Close"] for k, v in ohlcv.items()})
    have = set(ohlcv)
    members = sl.members_in_window(iv, sl.TEST_START)
    series = {t: ohlcv[sl.symbol_for(t, have)] for t in members if sl.symbol_for(t, have)}
    cov = sl.coverage_by_year(iv, series, cal)
    uncovered = {int(r.year): 1 - r.covered_pct / 100 for r in cov.itertuples()}
    data, signals = {}, []
    for i, (tk, df) in enumerate(sorted(series.items())):
        idx = pd.DatetimeIndex(df.index)
        mk = mkt.reindex(idx).ffill().fillna(False).to_numpy(dtype=bool)
        allowed = sl.allowed_mask(idx, sl.member_mask(idx, iv[tk]), mk)
        q = quads_by_sector.get(sector_of.get(tk)) if sector_of.get(tk) else None
        sig, x = sl.build_signals(tk, df, bench, q, allowed)       # rotation still counts toward confluence
        sig = [s for s in sig if s.setup == "M0"]
        for s in sig:
            s.leader, s.mkt_ok = False, True
        arr = {k: df[k].to_numpy(dtype=float, copy=True) for k in ("Open", "High", "Low", "Close")}
        for col in ("atr14", "sma5", "ema5", "ema10", "sma50", "sma100"):
            arr[col] = x[col].to_numpy(dtype=float, copy=True)
        data[tk] = {"arr": arr, "quads": None,                     # M0-T: no sector-rotation EXIT
                    "index": idx, "asset": "stock", "close_cal": df["Close"].reindex(cal).ffill()}
        signals.extend(sig)
        if (i + 1) % 100 == 0:
            _log(f"{i + 1}/{len(series)} stocks, {len(signals)} M0 signals")
    saved = bt.LADDER
    bt.LADDER = ()                                                  # M0-T: no ladder trims
    try:
        trs, unf = sl.trades_for(signals, data, "M0", False, end)
    finally:
        bt.LADDER = saved
    return trs, unf, data, uncovered, len(members), len(series)


def half_of(d: pd.Timestamp) -> str:
    return HALVES[0] if d < sl.HALF_SPLIT else HALVES[1]


def windows(eq: pd.Series) -> dict:
    eq = eq[eq.index >= sl.TEST_START]
    return {"full": bt.series_stats(eq), HALVES[0]: bt.series_stats(eq[eq.index < sl.HALF_SPLIT]),
            HALVES[1]: bt.series_stats(eq[eq.index >= sl.HALF_SPLIT])}


def trade_block(trs: list, data: dict) -> dict:
    closed = [t for t in trs if not t.still_open]
    dt = lambda t: data[t.ticker]["index"][t.entry_t]
    return {"full": bt.trade_stats([t.r_net for t in closed]),
            **{h: bt.trade_stats([t.r_net for t in closed if half_of(dt(t)) == h]) for h in HALVES}}


def book(trs: list, unf: list, data: dict, cal: pd.DatetimeIndex, sector_of: dict, sw: dict) -> dict:
    p = bt.run_portfolio(trs, unf, data, cal, sector_of, sweep={"mode": "TBILL", **sw})
    taken = [t for t, _s in p["taken"]]
    return {"p": p, "stats": windows(p["equity"]), "taken": taken,
            "taken_stock": sum(1 for t in taken if t.asset == "stock"), "taken_etf": sum(1 for t in taken if t.asset != "stock")}


def verdict(ts: dict, b: dict, spy: dict, months_le_10: int, harsh: float) -> tuple:
    f = []
    if ts["full"].get("n", 0) < BAR["min_trades"]:
        f.append(f"n {ts['full'].get('n', 0)} < {BAR['min_trades']}")
    for h in HALVES:
        s = ts[h]
        if s.get("n", 0) < BAR["min_half"]:
            f.append(f"{h} n {s.get('n', 0)} < {BAR['min_half']}")
        if not s.get("expectancy_R", -1) > 0:
            f.append(f"{h} expectancy {s.get('expectancy_R')}R <= 0")
        if not s.get("profit_factor", 0) >= BAR["min_pf"]:
            f.append(f"{h} PF {s.get('profit_factor')} < {BAR['min_pf']}")
    if not harsh > 0:
        f.append(f"stock trades' harsh missing-stock stress {harsh}R <= 0")
    for h in ("full", *HALVES):
        c, cs = b[h].get("cagr_pct"), spy[h].get("cagr_pct")
        if c is None or cs is None or not c > cs:
            f.append(f"book {h} CAGR {c}% <= SPY {cs}%")
    dd = b["full"].get("max_dd_pct")
    if dd is None or not dd > BAR["max_dd"]:
        f.append(f"book max DD {dd}% deeper than {BAR['max_dd']}%")
    if months_le_10 > BAR["max_months_le_10"]:
        f.append(f"{months_le_10} month(s) at −10% or worse (limit A)")
    return ("PASS" if not f else "FAIL"), f


def analyse(ohlcv: dict, iv: dict, stock_sector: dict, rates: dict) -> dict:
    _log("ETF M0-T ...")
    e_tr, e_uf, e_data = etf_trades(ohlcv)
    _log("stock M0-T (point-in-time members) ...")
    s_tr, s_uf, s_data, uncovered, n_mem, n_priced = stock_trades(ohlcv, iv, stock_sector)
    _e, e_sec = etf_universe()
    sector_of = {**e_sec, **{t: stock_sector.get(t) for t in s_data}}
    data = {**e_data, **s_data}
    cal_all = pd.DatetimeIndex(ohlcv["SPY"].index)
    cal = cal_all[cal_all >= sl.TEST_START]
    sw, gaps = bt.sweep_inputs(ohlcv, rates, cal)
    _log("portfolio passes ...")
    c1 = book(e_tr + s_tr, e_uf + s_uf, data, cal, sector_of, sw)
    eo = book(e_tr, e_uf, data, cal, sector_of, sw)
    so = book(s_tr, s_uf, data, cal, sector_of, sw)
    spy = windows(ohlcv["SPY"]["Close"].reindex(cal).ffill())
    ts = trade_block(e_tr + s_tr, data)
    by_year: dict = {}
    for t in s_tr:
        if not t.still_open:
            by_year.setdefault(int(data[t.ticker]["index"][t.entry_t].year), []).append(t.r_net)
    st = sl.stress(by_year, uncovered)
    ver, fails = verdict(ts, c1["stats"], spy, c1["p"]["months_le_-10pct"], st.get("harsh_exp_R", -1))

    def pack(b, trs):
        p = b["p"]
        mret = p["equity"].resample("ME").last().pct_change().dropna()
        return {"book": b["stats"], "exposure_avg_pct": p["exposure_avg_pct"], "heat_max_pct": p["heat_max_pct"],
                "trades_taken": p["trades_taken"], "taken_stock": b["taken_stock"], "taken_etf": b["taken_etf"],
                "months_le_-10pct": p["months_le_-10pct"], "hwm_-20pct_breached": p["hwm_-20pct_breached"],
                "worst_month_pct": round(float(mret.min()) * 100, 2) if len(mret) else None,
                "trades": trade_block(trs, data), "taken_trades": trade_block(b["taken"], data)["full"]}

    exits: dict = {}
    for t in e_tr + s_tr:
        exits.setdefault(t.exit_reason, []).append(t.r_net)
    return {"version": VERSION, "verdict": ver, "fails": fails, "gaps": gaps, "stress_stocks": st,
            "members": n_mem, "priced": n_priced, "uncovered": uncovered, "spy": spy,
            "c1": pack(c1, e_tr + s_tr), "etf_only": pack(eo, e_tr), "stock_only": pack(so, s_tr),
            "exit_mix": {k: {"n": len(v), "mean_R": round(float(np.nanmean(v)), 3)}
                         for k, v in sorted(exits.items(), key=lambda kv: -len(kv[1]))},
            "ladder_restored": bt.LADDER == (2.0, 4.0, 8.0),
            "equity": {"c1": c1["p"]["equity"], "etf_only": eo["p"]["equity"], "stock_only": so["p"]["equity"]}}


def _c(x):
    return "—" if x is None else f"{x:.2f}%"


def render(r: dict, stamp: str) -> str:
    cols = (("c1", "C1 ETFs + stocks (decision)"), ("etf_only", "ETF only"), ("stock_only", "Stocks only"))
    L = [f"# M0-T on ETFs + S&P 500 stocks (trial 99) — m0t_stock_lab {VERSION} — {stamp}", "",
         f"Pre-registered in `claude/m0t_stock_lab_2026-11-23.md`. Trials {TRIALS_BEFORE} → {TRIALS_BEFORE + TRIALS_HERE}. "
         "Research, not personalized advice.", "",
         f"## Verdict: **{r['verdict']}**", "", f"- Fails: {'; '.join(r['fails']) or 'none'}",
         f"- {r['members']} S&P 500 members since 2017, {r['priced']} with prices; stock trades' missing-stock stress: "
         f"neutral {r['stress_stocks'].get('neutral_exp_R')}R, harsh {r['stress_stocks'].get('harsh_exp_R')}R", "",
         "| | " + " | ".join(n for _k, n in cols) + " | SPY |", "|---" * (len(cols) + 2) + "|"]
    for h in ("full", *HALVES):
        L.append(f"| Book CAGR {h} | " + " | ".join(_c(r[k]["book"][h].get("cagr_pct")) for k, _n in cols) +
                 f" | {_c(r['spy'][h].get('cagr_pct'))} |")
    L.append("| Max DD | " + " | ".join(_c(r[k]["book"]["full"].get("max_dd_pct")) for k, _n in cols) +
             f" | {_c(r['spy']['full'].get('max_dd_pct'))} |")
    for key, lab in (("worst_month_pct", "Worst month %"), ("months_le_-10pct", "Months ≤ −10%"),
                     ("hwm_-20pct_breached", "−20% from high breached"), ("exposure_avg_pct", "Average invested %"),
                     ("trades_taken", "Trades taken"), ("taken_stock", "… of which stocks")):
        L.append(f"| {lab} | " + " | ".join(str(r[k][key]) for k, _n in cols) + " | — |")
    L += ["", "| Trades (closed) | n | Win % | Avg win R | Avg loss R | Expectancy R | PF |", "|---|---|---|---|---|---|---|"]
    for k, n in cols:
        for h in ("full", *HALVES):
            s = r[k]["trades"][h]
            L.append(f"| {n} {h} | {s.get('n')} | {s.get('win_rate')} | {s.get('avg_win_R')} | {s.get('avg_loss_R')} | "
                     f"{s.get('expectancy_R')} | {s.get('profit_factor')} |")
    L += ["", "**How trades ended (both universes):** " +
          "; ".join(f"{k} {v['n']} ({v['mean_R']:+.2f}R)" for k, v in list(r["exit_mix"].items())[:8]),
          "", f"Ladder restored after the run: {'yes' if r['ladder_restored'] else '**NO**'}"]
    if r.get("gaps"):
        L += ["", "Data gaps: " + "; ".join(r["gaps"])]
    L += ["", f"*m0t_stock_lab.py {VERSION}*"]
    return "\n".join(L) + "\n"


def write_outputs(r: dict, stamp: str, out_data: Path = OUT_DATA, out_logs: Path = OUT_LOGS) -> str:
    from lever_lab import _jsonable
    md = render(r, stamp)
    eq = r.pop("equity", None)
    js = json.dumps(_jsonable({**r, "trials": TRIALS_BEFORE + TRIALS_HERE, "asof": stamp}), indent=1, default=str)
    out_data.mkdir(parents=True, exist_ok=True)
    out_logs.mkdir(parents=True, exist_ok=True)
    if eq:
        pd.DataFrame(eq).round(2).to_csv(out_data / "equity.csv")
    (out_data / "summary.json").write_text(js)
    (out_logs / "latest.md").write_text(md)
    (out_logs / f"{stamp}.md").write_text(md)
    return md


def main(fetch=None, membership=sl.MEMBERSHIP, sector_lookup=sl.yahoo_sector) -> int:
    stamp = datetime.now(timezone.utc).date().isoformat()
    fetch = fetch or bt.fetch_ohlcv
    try:
        _mem, iv = sl.load_membership(membership)
    except Exception as e:
        print(f"[m0t_stock_lab] DATA FAILURE: membership file unreadable ({type(e).__name__}); nothing written.")
        return 1
    members = sl.members_in_window(iv, sl.TEST_START)
    etfs, _s = etf_universe()
    syms = sorted({up.yahoo_symbol(t) for t in members} | {v for k, v in up.RENAMES.items() if k in members})
    _log(f"{len(members)} members since {sl.TEST_START.date()}; fetching {len(syms)} stock symbols and {len(etfs)} ETFs")
    ohlcv = {}
    for i in range(0, len(syms), 150):
        ohlcv.update(fetch(syms[i:i + 150], sl.DATA_START))
    e_px = fetch(sorted(set(etfs)), sl.DATA_START)
    for attempt in range(3):
        miss = sorted(set(etfs) - set(e_px))
        if not miss:
            break
        _log(f"ETF retry {attempt + 1}: {', '.join(miss)}")
        for t in miss:
            e_px.update(fetch([t], sl.DATA_START))
    miss = sorted(set(etfs) - set(e_px))
    if miss or "SPY" not in e_px:
        print(f"[m0t_stock_lab] DATA FAILURE: no prices for ETFs {', '.join(miss) or 'SPY'}; nothing written.")
        return 1
    ohlcv.update(e_px)
    have = set(ohlcv)
    priced = [t for t in members if sl.symbol_for(t, have)]
    if len(priced) < 0.6 * len(members):
        print(f"[m0t_stock_lab] DATA FAILURE: prices for only {len(priced)} of {len(members)} members; nothing written.")
        return 1
    stock_sector, note = sl.sector_map(priced, lookup=sector_lookup)
    _log(note)
    rates = fetch(["^IRX"], sl.DATA_START)
    r = analyse(ohlcv, iv, stock_sector, rates)
    if not r["ladder_restored"]:
        print("[m0t_stock_lab] GUARD FAILED: bt.LADDER not restored; nothing written.")
        return 1
    print(write_outputs(r, stamp))
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _fixture():
    etfs, _s = etf_universe()
    idx = pd.bdate_range(sl.DATA_START, periods=2900)
    ohl = {}
    for i, t in enumerate(["SPY", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLU", "XLRE", "XLB", "XLC", "XLP", "QQQ"]):
        d = bt._walk(i + 3, n=len(idx), drift=0.0005 + 0.0001 * (i % 4)); d.index = idx; ohl[t] = d
    stocks = {}
    for i in range(12):
        d = bt._walk(50 + i, n=len(idx), drift=0.0006 + 0.0001 * (i % 3), vol=0.018); d.index = idx
        stocks[f"S{i:02d}"] = d
    # membership: S00-S07 members throughout; S08-S09 join 2020; S10 leaves 2019 (prices end there); S11 never a member
    iv = {f"S{i:02d}": [(pd.Timestamp("2010-01-04"), None)] for i in range(8)}
    iv["S08"] = iv["S09"] = [(pd.Timestamp("2020-01-02"), None)]
    iv["S10"] = [(pd.Timestamp("2010-01-04"), pd.Timestamp("2019-06-03"))]
    stocks["S10"] = stocks["S10"][stocks["S10"].index < "2019-06-03"]
    iv["OLD"] = [(pd.Timestamp("2010-01-04"), pd.Timestamp("2016-01-04"))]
    ohl.update(stocks)
    sec = {f"S{i:02d}": ("XLK" if i < 6 else "XLF") for i in range(12)}
    irx = pd.DataFrame({"Open": 4.0, "High": 4.0, "Low": 4.0, "Close": 4.0, "Volume": 0}, index=idx)
    return ohl, iv, sec, {"^IRX": irx}


def selftest() -> dict:
    import contextlib, io, os, tempfile
    f = []
    ohl, iv, sec, rates = _fixture()
    saved = (bt.SECTOR_ETFS, bt.OTHER_ETFS)
    bt.SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLU", "XLRE", "XLB", "XLC", "XLP"]
    bt.OTHER_ETFS = {"SPY": None, "QQQ": "XLK"}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            r = analyse(ohl, iv, sec, rates)
            s_tr, s_uf, s_data, _u, _nm, _np = stock_trades(ohl, iv, sec)
            e_tr, e_uf, e_data = etf_trades(ohl)
        if not r["ladder_restored"] or bt.LADDER != (2.0, 4.0, 8.0):
            f.append("bt.LADDER must be restored")
        allt = s_tr + e_tr
        if not s_tr or not e_tr:
            f.append(f"fixture: need trades in both universes ({len(s_tr)} stock, {len(e_tr)} ETF)")
        if any(t.exit_reason.startswith("thesis") for t in allt):
            f.append("M0-T never exits on sector rotation")
        if any(k == "trim" for t in allt for (_t, k, *_x) in t.events):
            f.append("M0-T never trims")
        # point-in-time membership: no stock signal on a non-member day or before the window
        for t in s_tr + [g for g in s_uf]:
            tk, sig_t = t.ticker, (t.signal_t if hasattr(t, "signal_t") else t.t)
            d = s_data[tk]["index"][sig_t]
            if not sl.member_mask(pd.DatetimeIndex([d]), iv[tk])[0] or d < sl.TEST_START:
                f.append(f"stock signal on a non-member / pre-window day: {tk} {d.date()}")
                break
        if "S11" in {t.ticker for t in s_tr} or "OLD" in s_data:
            f.append("never-members and pre-window leavers must have no trades")
        if not any(t.ticker in ("S08", "S09") for t in s_tr):
            f.append("fixture: joiners should trade after joining")
        # S10's prices end on leaving: an open trade is closed at its last close
        s10 = [t for t in s_tr if t.ticker == "S10" and t.exit_t == len(s_data["S10"]["index"]) - 1]
        if s10 and s10[0].still_open:
            f.append("a stock whose prices end must be closed, not left open")
        if any(s_data[t.ticker]["index"][t.entry_t] < sl.TEST_START for t in s_tr) or \
                any(e_data[t.ticker]["index"][t.entry_t] < sl.TEST_START for t in e_tr):
            f.append("no entry before the test window")
        # the decision book is the backtest's own pass over the union
        if r["c1"]["trades_taken"] < max(r["etf_only"]["trades_taken"], 1) or r["c1"]["taken_stock"] == 0:
            f.append(f"C1 must take stock trades too ({r['c1']})")
        if r["c1"]["taken_stock"] + r["c1"]["taken_etf"] != r["c1"]["trades_taken"]:
            f.append("C1 trade split must add up")
        # verdict logic
        ok_ts = {"full": {"n": 300}, HALVES[0]: {"n": 100, "expectancy_R": 0.3, "profit_factor": 1.6},
                 HALVES[1]: {"n": 100, "expectancy_R": 0.2, "profit_factor": 1.5}}
        bk = {h: {"cagr_pct": 16.0, "max_dd_pct": -15.0} for h in ("full", *HALVES)}
        sp = {h: {"cagr_pct": 14.0} for h in ("full", *HALVES)}
        if verdict(ok_ts, bk, sp, 0, 0.1)[0] != "PASS":
            f.append("verdict: clean pass")
        for args, why in (((ok_ts, bk, sp, 1, 0.1), "month"), ((ok_ts, bk, sp, 0, -0.01), "harsh stress"),
                          ((ok_ts, dict(bk, full={"cagr_pct": 16, "max_dd_pct": -20.5}), sp, 0, 0.1), "DD"),
                          ((ok_ts, dict(bk, **{HALVES[1]: {"cagr_pct": 13.9}}), sp, 0, 0.1), "half vs SPY"),
                          ((dict(ok_ts, **{HALVES[0]: {"n": 100, "expectancy_R": 0.3, "profit_factor": 1.29}}), bk, sp, 0, 0.1), "PF")):
            if verdict(*args)[0] != "FAIL":
                f.append(f"verdict must fail: {why}")
        tmp = Path(tempfile.mkdtemp())
        md = write_outputs(dict(r), "2026-11-23", tmp / "d", tmp / "l")
        js = json.loads((tmp / "d" / "summary.json").read_text())
        if js["verdict"] not in ("PASS", "FAIL") or "trial 99" not in md or not (tmp / "d" / "equity.csv").exists():
            f.append("writer: outputs incomplete")
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            mem_csv = tmp / "mem.csv"
            mem_csv.write_text("nope")
            with contextlib.redirect_stdout(io.StringIO()):
                rc1 = main(fetch=lambda tks, start=None: {}, membership=tmp / "missing.csv")
            if rc1 != 1 or (tmp / "data" / "m0t_stock_lab").exists():
                f.append("main: unreadable membership must stop with nothing written")
        finally:
            os.chdir(cwd)
    except Exception as e:
        import traceback
        f.append(f"crashed: {type(e).__name__}: {e} {traceback.format_exc()[-400:]}")
    finally:
        bt.SECTOR_ETFS, bt.OTHER_ETFS = saved
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r_ = selftest()
        print(json.dumps(r_, indent=2))
        sys.exit(0 if r_["ok"] else 1)
    sys.exit(main())
