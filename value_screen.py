"""
value_screen.py  (v1 — October 2026)
────────────────────────────────────
Quality-value screen for the Construction & P/E tab.

WHY NOT "P/E < 15"
──────────────────
An absolute P/E cut-off is the classic value-trap generator in a credit
cycle: cyclicals (banks, homebuilders, energy, materials) look cheapest at
PEAK earnings, right before the E falls. The checklist's own Level-3 rule is
"cheap or rich vs its OWN history, not vs the market". So this screen asks
five questions, and the absolute P/E cap is only an optional extra filter:

  1. P/E below its own history   trailing P/E vs the median of its annual
                                  P/Es (fiscal-year EPS / avg price that
                                  year). Yahoo gives ~4-5 fiscal years, so
                                  this is a ~5-year history, NOT 10 — the
                                  table says exactly how many years were used.
  2. Net debt / EBITDA < 2.0x    balance sheet. High real rates make
                                  refinancing the binding constraint.
  3. Interest coverage > 8x      EBIT / interest expense (latest fiscal yr).
  4. FCF yield > 5%              free cash flow / market cap.
  5. Estimates stable or rising  next-FY EPS consensus now vs 90 days ago,
                                  >= -2%. Falling estimates are THE value-
                                  trap tell: the P/E looks low because the
                                  market already expects E to drop.

SECTOR HANDLING (stated, not hidden)
  • Financial Services / Real Estate: debt/EBITDA and interest coverage are
    not meaningful for banks, insurers and REITs -> N/A, not failed. They
    are judged on the remaining tests only.
  • Utilities: regulated balance sheets run ~5x net debt/EBITDA by design;
    the leverage threshold is 5.5x for that sector.

VERDICTS
  QUALITY VALUE    every evaluated test passes, >= 4 tests evaluated
  VALUE TRAP RISK  cheap vs own history BUT estimates falling or leverage
                   failing — the low P/E is probably the market being right
  PARTIAL k/n      some tests pass
  NOT VALUE        P/E at or above its own history
  INSUFFICIENT     fewer than 3 tests could be evaluated (data gap)

REGIME LINK
  Deep-cyclical sectors get a WAIT flag while the HY credit cycle
  (regime_classifier.credit_cycle_state) is WIDENING / PEAK_FORMING /
  RE_ENTRY_PENDING, or while the regime is credit_stress / liquidity_crisis
  without a confirmed RE_ENTRY. RE_ENTRY flips the flag to ELIGIBLE.

Pure functions; network access only in fetch_fundamentals(), which takes the
yfinance module as an argument so selftest() runs offline.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Optional

PE_DISCOUNT_MAX = 0.0          # trailing P/E must be BELOW own median (ratio - 1 < 0)
NET_DEBT_EBITDA_MAX = 2.0
NET_DEBT_EBITDA_MAX_UTIL = 5.5
INT_COVER_MIN = 8.0
FCF_YIELD_MIN = 5.0            # percent
EST_REVISION_MIN = -2.0        # percent change, next-FY EPS, 90 days
MIN_HISTORY_YEARS = 3
MIN_TESTS = 3

LEVERAGE_NA_SECTORS = {"Financial Services", "Real Estate"}
UTILITY_SECTORS = {"Utilities"}
DEEP_CYCLICAL_SECTORS = {"Energy", "Basic Materials", "Industrials",
                         "Consumer Cyclical", "Financial Services"}
CREDIT_WAIT_REGIMES = {"credit_stress", "liquidity_crisis"}
CREDIT_WAIT_STATES = {"WIDENING", "PEAK_FORMING", "RE_ENTRY_PENDING"}


# ── data ─────────────────────────────────────────────────────────────────────

def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


def _row(df, *names):
    """First matching row of a yfinance statement DataFrame, as {date: value}."""
    if df is None or getattr(df, "empty", True):
        return {}
    for n in names:
        if n in df.index:
            s = df.loc[n]
            return {c: _f(v) for c, v in s.items() if _f(v) is not None}
    return {}


def fetch_fundamentals(ticker: str, yf) -> dict:
    """Pull everything the screen needs for one ticker. Never raises."""
    out = {"ticker": ticker, "error": None}
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        out.update({
            "name": info.get("shortName") or info.get("longName") or ticker,
            "sector": info.get("sector"),
            "trailing_pe": _f(info.get("trailingPE")),
            "forward_pe": _f(info.get("forwardPE")),
            "market_cap": _f(info.get("marketCap")),
            "fcf": _f(info.get("freeCashflow")),
            "total_debt": _f(info.get("totalDebt")),
            "total_cash": _f(info.get("totalCash")),
            "ebitda": _f(info.get("ebitda")),
            "quote_type": info.get("quoteType"),
        })
        inc = getattr(t, "income_stmt", None)
        eps = _row(inc, "Diluted EPS", "Basic EPS")
        ebit = _row(inc, "EBIT", "Operating Income")
        intx = _row(inc, "Interest Expense", "Interest Expense Non Operating")
        latest = max(ebit) if ebit else None
        out["ebit"] = ebit.get(latest) if latest is not None else None
        out["interest_expense"] = intx.get(latest) if latest is not None and intx else None
        # annual P/E history: FY EPS vs average monthly close over that FY
        hist = t.history(period="6y", interval="1mo", auto_adjust=False)
        closes = hist["Close"] if hist is not None and not hist.empty else None
        pe_hist = []
        if closes is not None:
            if getattr(closes.index, "tz", None) is not None:
                closes.index = closes.index.tz_localize(None)
            for fy_end, e in sorted(eps.items()):
                if not e or e <= 0:
                    continue
                end = _naive(fy_end)
                window = closes[(closes.index > end - _year()) & (closes.index <= end)]
                if len(window) >= 6:
                    pe_hist.append(round(float(window.mean()) / e, 2))
        out["pe_history"] = pe_hist
        # estimate revisions
        trend = getattr(t, "eps_trend", None)
        out["eps_now"], out["eps_90d"] = None, None
        if trend is not None and not getattr(trend, "empty", True):
            for period in ("+1y", "0y"):
                if period in trend.index:
                    r = trend.loc[period]
                    now, ago = _f(r.get("current")), _f(r.get("90daysAgo"))
                    if now is not None and ago:
                        out["eps_now"], out["eps_90d"], out["eps_period"] = now, ago, period
                        break
    except Exception as e:                       # one bad ticker never breaks the screen
        out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return out


def _naive(ts):
    import pandas as pd
    ts = pd.Timestamp(ts)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def _year():
    import pandas as pd
    return pd.DateOffset(years=1)


# ── evaluation ───────────────────────────────────────────────────────────────

def _test(value, ok, detail):
    return {"value": value, "pass": ok, "detail": detail}


def evaluate(raw: dict, regime_key: Optional[str] = None,
             max_forward_pe: Optional[float] = None,
             credit_state: Optional[str] = None) -> dict:
    sector = raw.get("sector") or "—"
    tests = {}

    # 1) P/E vs own history
    pe, hist = raw.get("trailing_pe"), raw.get("pe_history") or []
    if pe and pe > 0 and len(hist) >= MIN_HISTORY_YEARS:
        med = median(hist)
        disc = pe / med - 1
        tests["pe_vs_history"] = _test(round(disc * 100, 1), disc < PE_DISCOUNT_MAX,
                                       f"{pe:.1f}x vs {med:.1f}x median of {len(hist)} FYs")
    else:
        why = "no positive trailing P/E" if not pe or pe <= 0 else f"only {len(hist)} FY of P/E history"
        tests["pe_vs_history"] = _test(None, None, why)

    # 2) net debt / EBITDA
    if sector in LEVERAGE_NA_SECTORS:
        tests["net_debt_ebitda"] = _test(None, None, f"N/A for {sector}")
    else:
        debt, cash, ebitda = raw.get("total_debt"), raw.get("total_cash"), raw.get("ebitda")
        cap = NET_DEBT_EBITDA_MAX_UTIL if sector in UTILITY_SECTORS else NET_DEBT_EBITDA_MAX
        if debt is not None and cash is not None and debt - cash <= 0:
            tests["net_debt_ebitda"] = _test(round((debt - cash) / ebitda, 2) if ebitda else None,
                                             True, "net cash")
        elif debt is not None and ebitda:
            if ebitda <= 0:
                tests["net_debt_ebitda"] = _test(None, False, "EBITDA negative")
            else:
                nd = (debt - (cash or 0)) / ebitda
                tests["net_debt_ebitda"] = _test(round(nd, 2), nd < cap, f"< {cap:.1f}x required")
        else:
            tests["net_debt_ebitda"] = _test(None, None, "debt/EBITDA data missing")

    # 3) interest coverage
    if sector in LEVERAGE_NA_SECTORS:
        tests["interest_cover"] = _test(None, None, f"N/A for {sector}")
    else:
        ebit, ix = raw.get("ebit"), raw.get("interest_expense")
        if ebit is not None and ix not in (None, 0):
            cov = ebit / abs(ix)
            tests["interest_cover"] = _test(round(cov, 1), cov > INT_COVER_MIN, f"> {INT_COVER_MIN:.0f}x required")
        elif ebit is not None and ebit > 0 and tests["net_debt_ebitda"]["detail"] == "net cash":
            tests["interest_cover"] = _test(None, True, "net cash — no meaningful interest burden")
        else:
            tests["interest_cover"] = _test(None, None, "interest data missing")

    # 4) FCF yield
    fcf, mc = raw.get("fcf"), raw.get("market_cap")
    if fcf is not None and mc:
        y = fcf / mc * 100
        tests["fcf_yield"] = _test(round(y, 1), y > FCF_YIELD_MIN, f"> {FCF_YIELD_MIN:.0f}% required")
    else:
        tests["fcf_yield"] = _test(None, None, "FCF or market cap missing")

    # 5) estimate revisions
    now, ago = raw.get("eps_now"), raw.get("eps_90d")
    if now is not None and ago:
        chg = (now / ago - 1) * 100 if ago > 0 else (100.0 if now > ago else -100.0)
        tests["estimates"] = _test(round(chg, 1), chg >= EST_REVISION_MIN,
                                   f"{raw.get('eps_period', '+1y')} EPS {ago:.2f} -> {now:.2f} (90d)")
    else:
        tests["estimates"] = _test(None, None, "no consensus trend")

    evaluated = [k for k, v in tests.items() if v["pass"] is not None]
    passed = [k for k in evaluated if tests[k]["pass"]]
    cheap = tests["pe_vs_history"]["pass"] is True
    trap = cheap and (tests["estimates"]["pass"] is False or tests["net_debt_ebitda"]["pass"] is False
                      or tests["interest_cover"]["pass"] is False)

    if raw.get("error"):
        verdict = "INSUFFICIENT"
    elif len(evaluated) < MIN_TESTS:
        verdict = "INSUFFICIENT"
    elif tests["pe_vs_history"]["pass"] is False:
        verdict = "NOT VALUE"
    elif trap:
        verdict = "VALUE TRAP RISK"
    elif len(passed) == len(evaluated) and (len(evaluated) >= 4 or
                                            (sector in LEVERAGE_NA_SECTORS and len(evaluated) >= 3)):
        verdict = "QUALITY VALUE"
    else:
        verdict = f"PARTIAL {len(passed)}/{len(evaluated)}"

    fpe = raw.get("forward_pe")
    pe_cap_ok = None if max_forward_pe is None else (fpe is not None and 0 < fpe <= max_forward_pe)

    flags = []
    if sector in DEEP_CYCLICAL_SECTORS:
        if credit_state == "RE_ENTRY":
            flags.append("ELIGIBLE — HY spread peak confirmed; cyclical value back on the menu")
        elif (credit_state in CREDIT_WAIT_STATES
              or (regime_key in CREDIT_WAIT_REGIMES and credit_state != "RE_ENTRY")):
            flags.append(f"WAIT — deep cyclical, credit cycle {credit_state or regime_key}; "
                         "buy after the HY spread-peak signal")
    if verdict == "VALUE TRAP RISK":
        bad = [k for k in ("estimates", "net_debt_ebitda", "interest_cover") if tests[k]["pass"] is False]
        flags.append("cheap for a reason: " + ", ".join(bad))

    return {"ticker": raw.get("ticker"), "name": raw.get("name"), "sector": sector,
            "trailing_pe": pe, "forward_pe": fpe, "tests": tests, "passed": len(passed),
            "evaluated": len(evaluated), "verdict": verdict, "pe_cap_ok": pe_cap_ok,
            "flags": flags, "error": raw.get("error")}


VERDICT_ORDER = {"QUALITY VALUE": 0, "PARTIAL": 1, "VALUE TRAP RISK": 2,
                 "NOT VALUE": 3, "INSUFFICIENT": 4}


def sort_key(r: dict):
    v = r["verdict"].split(" ")[0] if r["verdict"].startswith("PARTIAL") else r["verdict"]
    disc = r["tests"]["pe_vs_history"]["value"]
    return (VERDICT_ORDER.get(v, 9), -r["passed"], disc if disc is not None else 999)


def to_rows(results: list) -> list:
    """Flatten for st.dataframe."""
    def cell(t, fmt):
        if t["pass"] is None:
            return f"— ({t['detail']})" if t["value"] is None else fmt(t["value"])
        mark = "✅" if t["pass"] else "❌"
        return f"{mark} {fmt(t['value'])}" if t["value"] is not None else f"{mark} {t['detail']}"
    rows = []
    for r in sorted(results, key=sort_key):
        t = r["tests"]
        rows.append({
            "Ticker": r["ticker"], "Name": (r["name"] or "")[:28], "Sector": r["sector"],
            "Verdict": r["verdict"],
            "P/E vs own hist": cell(t["pe_vs_history"], lambda v: f"{v:+.0f}%"),
            "Fwd P/E": f"{r['forward_pe']:.1f}x" if r["forward_pe"] else "—",
            "Net debt/EBITDA": cell(t["net_debt_ebitda"], lambda v: f"{v:.1f}x"),
            "Int. cover": cell(t["interest_cover"], lambda v: f"{v:.0f}x"),
            "FCF yield": cell(t["fcf_yield"], lambda v: f"{v:.1f}%"),
            "EPS est. 90d": cell(t["estimates"], lambda v: f"{v:+.1f}%"),
            "Flags": " · ".join(r["flags"]) or (r["error"] or ""),
        })
    return rows


# ── selftest ─────────────────────────────────────────────────────────────────

def selftest() -> dict:
    f = []
    base = dict(ticker="AAA", name="Quality Co", sector="Healthcare", trailing_pe=14.0,
                forward_pe=13.0, market_cap=100e9, fcf=7e9, total_debt=20e9, total_cash=10e9,
                ebitda=12e9, ebit=10e9, interest_expense=-0.8e9, pe_history=[18, 19, 17, 20, 18],
                eps_now=5.2, eps_90d=5.1, eps_period="+1y")
    r = evaluate(base)
    if r["verdict"] != "QUALITY VALUE":
        f.append(f"clean quality value misread: {r['verdict']} {r['tests']}")
    r = evaluate({**base, "eps_now": 4.5, "eps_90d": 5.1})
    if r["verdict"] != "VALUE TRAP RISK":
        f.append(f"falling estimates must be a trap: {r['verdict']}")
    r = evaluate({**base, "total_debt": 60e9})
    if r["verdict"] != "VALUE TRAP RISK" or r["tests"]["net_debt_ebitda"]["pass"] is not False:
        f.append(f"4.2x leverage must fail and trap: {r['verdict']}")
    r = evaluate({**base, "trailing_pe": 22.0})
    if r["verdict"] != "NOT VALUE":
        f.append(f"P/E above own median must be NOT VALUE: {r['verdict']}")
    r = evaluate({**base, "sector": "Financial Services", "total_debt": 500e9, "ebit": None})
    if r["tests"]["net_debt_ebitda"]["pass"] is not None or r["verdict"] != "QUALITY VALUE":
        f.append(f"bank leverage must be N/A, judged on the rest: {r['verdict']} {r['tests']['net_debt_ebitda']}")
    r = evaluate({**base, "sector": "Utilities", "total_debt": 60e9})      # 4.2x < 5.5x
    if r["tests"]["net_debt_ebitda"]["pass"] is not True:
        f.append("utility at 4.2x must pass the 5.5x sector threshold")
    r = evaluate({**base, "total_cash": 30e9, "interest_expense": None})
    if r["tests"]["net_debt_ebitda"]["detail"] != "net cash" or r["tests"]["interest_cover"]["pass"] is not True:
        f.append(f"net-cash company must pass leverage and coverage: {r['tests']}")
    r = evaluate({**base, "pe_history": [18, 19]})
    if r["tests"]["pe_vs_history"]["pass"] is not None:
        f.append("2 years of history must be N/A, not a verdict")
    r = evaluate({"ticker": "ZZZ", "error": "HTTPError"})
    if r["verdict"] != "INSUFFICIENT":
        f.append("fetch error must be INSUFFICIENT")
    r = evaluate({**base, "sector": "Energy"}, regime_key="credit_stress")
    if not any(x.startswith("WAIT") for x in r["flags"]):
        f.append("cyclical in credit_stress must carry the WAIT flag")
    r = evaluate({**base, "sector": "Energy"}, regime_key="credit_stress", credit_state="RE_ENTRY")
    if not any(x.startswith("ELIGIBLE") for x in r["flags"]):
        f.append("confirmed spread peak must lift the WAIT flag")
    r = evaluate({**base, "sector": "Energy"}, regime_key="restrictive_tightening", credit_state="WIDENING")
    if not any(x.startswith("WAIT") for x in r["flags"]):
        f.append("a widening credit episode must WAIT cyclicals even before the regime flips")
    r = evaluate({**base, "sector": "Energy"}, regime_key="restrictive_tightening", credit_state="NO_EPISODE")
    if r["flags"]:
        f.append("no episode, no credit regime -> no cyclical flag")
    r = evaluate(base, max_forward_pe=12)
    if r["pe_cap_ok"] is not False:
        f.append("forward P/E 13 must fail a 12x cap")
    rows = to_rows([evaluate(base), evaluate({**base, "ticker": "BBB", "trailing_pe": 25})])
    if rows[0]["Ticker"] != "AAA":
        f.append("quality value must sort first")
    # fetch path against a fake yfinance (no network)
    import pandas as pd

    class _T:
        info = {"shortName": "Fake", "sector": "Healthcare", "trailingPE": 15.0,
                "forwardPE": 14.0, "marketCap": 50e9, "freeCashflow": 3e9,
                "totalDebt": 5e9, "totalCash": 2e9, "ebitda": 4e9}
        income_stmt = pd.DataFrame(
            {pd.Timestamp("2022-12-31"): [4.0, 3.0e9, -0.2e9],
             pd.Timestamp("2023-12-31"): [4.5, 3.2e9, -0.2e9],
             pd.Timestamp("2024-12-31"): [5.0, 3.5e9, -0.2e9],
             pd.Timestamp("2025-12-31"): [5.5, 3.8e9, -0.2e9]},
            index=["Diluted EPS", "EBIT", "Interest Expense"])
        eps_trend = pd.DataFrame({"current": [6.0], "90daysAgo": [5.9]}, index=["+1y"])

        def history(self, **k):
            idx = pd.date_range("2021-01-31", "2026-09-30", freq="ME", tz="America/New_York")
            return pd.DataFrame({"Close": [90.0] * len(idx)}, index=idx)

    class _YF:
        @staticmethod
        def Ticker(t):
            return _T()

    raw = fetch_fundamentals("FAKE", _YF)
    if raw.get("error"):
        f.append(f"fake fetch errored: {raw['error']}")
    elif len(raw["pe_history"]) != 4 or abs(raw["pe_history"][0] - 22.5) > 0.01:
        f.append(f"P/E history wrong: {raw['pe_history']}")
    elif abs(raw["interest_expense"] + 0.2e9) > 1 or raw["eps_now"] != 6.0:
        f.append(f"coverage/estimate fields wrong: {raw}")
    else:
        ev = evaluate(raw)
        if ev["verdict"] != "QUALITY VALUE":
            f.append(f"fake quality co should pass end to end: {ev['verdict']} {ev['tests']}")
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2))
