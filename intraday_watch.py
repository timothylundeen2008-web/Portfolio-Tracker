"""
intraday_watch.py  (v1 — October 2026)
──────────────────────────────────────
Three intraday checks on trading days (about 11:00, 1:30 and 2:45 PM ET;
GitHub may start them late). ALERT-ONLY: the model portfolio still changes
only on closes, so the test record stays clean. What this adds is time —
a fast fall is flagged while there is still a session left to act in, and
the 2:45 run is a pre-close verdict on whether a close-based rule is about
to fire.

WHAT IT CHECKS (against the model portfolio you SHOULD hold)
  1. Circuit breaker  — model book value at live prices vs its peak.
                         ALERT if it would close at/below -8% (breaker trips),
                         WARN at -5%.
  2. Fast fall        — a held sleeve down more than max(3%, 2.5x its daily
                         20-day volatility) today.
  3. Trend break      — a held sleeve that closed above its 200-day yesterday
                         and is below it now.
  4. Market stress    — SPY -3% or worse; VIX >= 30 or +25% today; HYG
                         lagging IEF by 1.25%+ (an intraday credit proxy:
                         HY OAS itself only updates once a day, a day late).
  5. Trigger met      — an add the entry gate is holding back whose release
                         level is now exceeded (INFO only: it executes only
                         if it holds to the close).

HOW IT EMAILS
  It opens one GitHub issue per day ("Intraday watch — YYYY-MM-DD") that
  @mentions the repo owner, so GitHub emails you. Later runs that day add a
  comment ONLY for alerts not already reported — no repeat emails for the
  same condition. Yesterday's issue is closed automatically. INFO-only runs
  never open an issue. Every run writes its full table to the Actions run page.

No commits, no secrets beyond the workflow's own token (issues: write).
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

BOOK_FILE = Path("data/model_book.csv")
BRIEF_GLOB = "logs/brief/*_brief.json"
CASH = {"SGOV", "USFR", "BIL", "SHV"}
WATCH_EXTRA = ["SPY", "^VIX", "HYG", "IEF"]

BREAKER_DD = -8.0
WARN_DD = -5.0
FAST_FALL_MIN_PCT = 3.0
FAST_FALL_SIGMA = 2.5
SPY_DROP_PCT = -3.0
VIX_LEVEL = 30.0
VIX_JUMP_PCT = 25.0
CREDIT_PROXY_PCT = -1.25
MIN_WEIGHT = 1.0
PRE_CLOSE_HOUR = 14.5            # runs at/after 2:30 PM ET are "pre-close"
LABEL = "intraday-watch"


# ── inputs ───────────────────────────────────────────────────────────────────

def load_model(book_file: Path = BOOK_FILE, brief_glob: str = BRIEF_GLOB) -> dict:
    """Latest model state: weights, NAV, peak, breaker, as-of date; plus the
    entry-gate states from the newest brief."""
    out = {"available": False, "gates": {}}
    briefs = sorted(glob.glob(brief_glob))
    brief = {}
    if briefs:
        try:
            brief = json.load(open(briefs[-1]))
        except Exception:
            brief = {}
    out["gates"] = ((brief.get("regime") or {}).get("gates_today") or {})
    try:
        if Path(book_file).exists():
            b = pd.read_csv(book_file).sort_values("date")
            t = b.iloc[-1]
            out.update(available=True, source="model book", date=str(t["date"]), regime=t["regime"],
                       weights=json.loads(t["weights"]), nav=float(t["nav"]), peak=float(t["peak"]),
                       breaker=t["breaker"])
            return out
    except Exception as e:
        out["error"] = f"model book unreadable: {e}"
    sm = ((brief.get("model") or {}).get("summary") or {})
    if sm.get("weights"):
        out.update(available=True, source="latest brief", date=sm.get("date"), regime=sm.get("regime"),
                   weights=sm["weights"], nav=sm.get("nav", 100.0), peak=sm.get("peak", 100.0),
                   breaker=sm.get("breaker", "OFF"))
    return out


def fetch_daily(tickers: list) -> dict:
    """1y of daily closes per ticker, including today's live bar."""
    import yfinance as yf
    df = yf.download(tickers, period="1y", interval="1d", auto_adjust=True,
                     progress=False, group_by="column", threads=True)
    out = {}
    if df is None or df.empty:
        return out
    close = df["Close"] if "Close" in df.columns.get_level_values(0) else df
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    for t in tickers:
        if t in close.columns:
            s = close[t].dropna().astype(float)
            if getattr(s.index, "tz", None) is not None:
                s.index = s.index.tz_localize(None)
            out[t] = s
    return out


# ── checks ───────────────────────────────────────────────────────────────────

def _ret(s: pd.Series, since: Optional[pd.Timestamp] = None) -> Optional[float]:
    if s is None or len(s) < 2:
        return None
    base = s.iloc[-2]
    if since is not None:
        prior = s[s.index <= since]
        if prior.empty or prior.index[-1] == s.index[-1]:
            return None
        base = prior.iloc[-1]
    return float(s.iloc[-1] / base - 1) * 100 if base else None


def run_checks(model: dict, closes: dict, today: pd.Timestamp, now_hour: float) -> dict:
    alerts = []
    notes = []

    def add(key, level, text):
        alerts.append({"key": key, "level": level, "text": text})

    spy = closes.get("SPY")
    if spy is None or spy.empty or pd.Timestamp(spy.index[-1]).normalize() != today:
        notes.append("No live bar for today (market closed, holiday, or data delayed) — nothing checked.")
        return {"alerts": [], "notes": notes, "live": False, "rows": []}
    pre = now_hour >= PRE_CLOSE_HOUR
    tail = ("If this holds to the 4:00 PM close" if pre else "Intraday; re-checked at the next run")
    rows = []

    # 1) circuit breaker, at live prices
    if model.get("available"):
        w = {k: float(v) for k, v in model["weights"].items()}
        since = pd.Timestamp(model["date"])
        r_book = 0.0
        for t, wt in w.items():
            r = _ret(closes.get(t), since)
            r_book += wt / 100.0 * (r or 0.0) / 100.0
        nav = model["nav"] * (1 + r_book)
        dd = (nav / max(model["peak"], nav) - 1) * 100
        rows.append(("Model book", f"{r_book * 100:+.2f}% since {model['date']}", f"drawdown {dd:+.1f}%"))
        if model.get("breaker") != "ON" and dd <= BREAKER_DD:
            add("breaker_trip", "ALERT",
                f"Model drawdown {dd:.1f}% at live prices. {tail}, the circuit breaker TRIPS "
                f"(risk sleeves halved, freed weight to SGOV; weekday-authorized).")
        elif model.get("breaker") != "ON" and dd <= WARN_DD:
            add("dd_warn", "WARN", f"Model drawdown {dd:.1f}% at live prices — past the {WARN_DD:.0f}% warning; "
                                   f"the breaker trips at {BREAKER_DD:.0f}%.")
        # 2) fast fall and 3) trend break, held sleeves
        for t, wt in sorted(w.items(), key=lambda kv: -kv[1]):
            s = closes.get(t)
            if wt < MIN_WEIGHT or t in CASH or s is None or len(s) < 30:
                continue
            r = _ret(s)
            vol = float(s.pct_change().iloc[-21:-1].std() * 100) if len(s) > 22 else None
            thr = -max(FAST_FALL_MIN_PCT, FAST_FALL_SIGMA * vol) if vol and not math.isnan(vol) else -FAST_FALL_MIN_PCT
            rows.append((t, f"{r:+.2f}%" if r is not None else "—", f"weight {wt:.1f}%"))
            if r is not None and r <= thr:
                add(f"fastfall:{t}", "ALERT",
                    f"{t} ({wt:.1f}% of the model) is {r:+.1f}% today, beyond its {thr:.1f}% fast-fall line.")
            if len(s) >= 201:
                ma_prev = float(s.iloc[-201:-1].mean())
                ma_now = float(s.iloc[-200:].mean())
                if float(s.iloc[-2]) > ma_prev and float(s.iloc[-1]) < ma_now:
                    add(f"trend200:{t}", "WARN",
                        f"{t} ({wt:.1f}% of the model) has dropped below its 200-day ({ma_now:,.2f}) after "
                        f"closing above it yesterday. {tail}, its hold trend turns down.")
    else:
        notes.append("Model portfolio not built yet (run the Consolidated Daily Brief once) — "
                     "only market-stress checks ran.")

    # 4) market stress
    r_spy = _ret(spy)
    rows.append(("SPY", f"{r_spy:+.2f}%" if r_spy is not None else "—", ""))
    if r_spy is not None and r_spy <= SPY_DROP_PCT:
        add("spy_drop", "ALERT", f"SPY {r_spy:+.1f}% today.")
    vix = closes.get("^VIX")
    if vix is not None and len(vix) >= 2:
        lvl, jump = float(vix.iloc[-1]), _ret(vix)
        rows.append(("VIX", f"{lvl:.1f}", f"{jump:+.0f}% today" if jump is not None else ""))
        if lvl >= VIX_LEVEL or (jump is not None and jump >= VIX_JUMP_PCT):
            add("vix", "ALERT", f"VIX {lvl:.1f} ({jump:+.0f}% today) — derivatives are pricing acute stress.")
    r_hyg, r_ief = _ret(closes.get("HYG")), _ret(closes.get("IEF"))
    if r_hyg is not None and r_ief is not None:
        rel = r_hyg - r_ief
        rows.append(("HYG vs IEF", f"{rel:+.2f}%", "intraday credit proxy"))
        if rel <= CREDIT_PROXY_PCT:
            add("credit_proxy", "ALERT",
                f"High yield (HYG) is lagging Treasuries (IEF) by {rel:.2f}% today — credit is widening "
                f"intraday. The HY OAS print that drives credit_stress lands tomorrow.")

    # 5) entry-gate triggers met intraday
    for t, g in (model.get("gates") or {}).items():
        if g.get("state") not in ("BLOCKED", "PULLBACK"):
            continue
        s = closes.get(t)
        if s is None or s.empty:
            continue
        lvl = g.get("ma200") if g.get("state") == "BLOCKED" and not g.get("crisis_exception") else g.get("ma50")
        if lvl and float(s.iloc[-1]) > float(lvl):
            add(f"trigger:{t}", "INFO",
                f"{t} is above its entry-gate level ({float(lvl):,.2f}) — the held-back add releases only "
                f"if it closes there.")
    return {"alerts": alerts, "notes": notes, "live": True, "rows": rows, "pre_close": pre}


# ── notification (GitHub issue -> email) ─────────────────────────────────────

class Issues:
    def __init__(self, repo: str, token: str, http=None):
        import requests
        self.repo, self.http = repo, http or requests
        self.h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        self.base = f"https://api.github.com/repos/{repo}"

    def open_watch_issues(self) -> list:
        r = self.http.get(f"{self.base}/issues", headers=self.h,
                          params={"labels": LABEL, "state": "open", "per_page": 20}, timeout=30)
        return r.json() if r.status_code == 200 else []

    def ensure_label(self):
        self.http.post(f"{self.base}/labels", headers=self.h, timeout=30,
                       json={"name": LABEL, "color": "d73a4a", "description": "Intraday watch alerts"})

    def create(self, title, body):
        return self.http.post(f"{self.base}/issues", headers=self.h, timeout=30,
                              json={"title": title, "body": body, "labels": [LABEL]}).json()

    def comment(self, number, body):
        self.http.post(f"{self.base}/issues/{number}/comments", headers=self.h, timeout=30, json={"body": body})

    def edit(self, number, **fields):
        self.http.patch(f"{self.base}/issues/{number}", headers=self.h, timeout=30, json=fields)


KEYS_RE = re.compile(r"<!-- watch-keys: (.*?) -->")


def notify(result: dict, today: str, when: str, issues, owner: str) -> dict:
    """Open/extend today's issue for NEW alert/warn keys only."""
    loud = [a for a in result["alerts"] if a["level"] in ("ALERT", "WARN")]
    title = f"Intraday watch — {today}"
    existing = issues.open_watch_issues()
    today_issue = next((i for i in existing if i.get("title") == title), None)
    for i in existing:                                   # close earlier days' issues
        if i is not today_issue and i.get("title", "").startswith("Intraday watch — "):
            issues.edit(i["number"], state="closed")
    if not loud:
        return {"action": "none", "reason": "no ALERT/WARN"}
    seen = set()
    if today_issue:
        m = KEYS_RE.search(today_issue.get("body") or "")
        seen = set(filter(None, (m.group(1).split(",") if m else [])))
    new = [a for a in loud if a["key"] not in seen]
    if not new:
        return {"action": "none", "reason": "already reported today"}
    lines = [f"- **{a['level']}** — {a['text']}" for a in new]
    info = [f"- {a['text']}" for a in result["alerts"] if a["level"] == "INFO"]
    block = (f"**{when}** (alert-only — the model changes only on closes)\n\n" + "\n".join(lines)
             + (("\n\nAlso:\n" + "\n".join(info)) if info else ""))
    keys = sorted(seen | {a["key"] for a in new})
    marker = f"<!-- watch-keys: {','.join(keys)} -->"
    if today_issue:
        issues.comment(today_issue["number"], f"@{owner}\n\n{block}")
        body = KEYS_RE.sub(marker, today_issue.get("body") or "") if KEYS_RE.search(today_issue.get("body") or "") \
            else (today_issue.get("body") or "") + "\n" + marker
        issues.edit(today_issue["number"], body=body)
        return {"action": "comment", "new": [a["key"] for a in new]}
    issues.ensure_label()
    issues.create(title, f"@{owner}\n\n{block}\n\nFull table: the Intraday Watch run page in Actions.\n\n{marker}")
    return {"action": "create", "new": [a["key"] for a in new]}


def render(result: dict, model: dict, when: str) -> str:
    L = [f"## Intraday watch — {when}", ""]
    if model.get("available"):
        L.append(f"Model: `{model.get('regime')}` as of {model.get('date')} ({model.get('source')}), "
                 f"breaker {model.get('breaker')}.")
    L += [f"- {n}" for n in result["notes"]]
    if result.get("rows"):
        L += ["", "| Item | Today | Note |", "|---|---|---|", *[f"| {a} | {b} | {c} |" for a, b, c in result["rows"]]]
    L += ["", "**Alerts:**"] + ([f"- **{a['level']}** — {a['text']}" for a in result["alerts"]] or ["- none"])
    return "\n".join(L)


def main() -> int:
    import market_time as mt
    now = mt.now_et()
    today = pd.Timestamp(now.date())
    when = f"{now:%a %b %d, %I:%M %p} ET"
    model = load_model()
    tickers = sorted({t for t, w in (model.get("weights") or {}).items() if float(w) >= MIN_WEIGHT and t not in CASH}
                     | set(WATCH_EXTRA) | set((model.get("gates") or {}).keys()))
    try:
        closes = fetch_daily(tickers)
    except Exception as e:
        closes = {}
        print(f"price fetch failed: {e}")
    result = run_checks(model, closes, today, now.hour + now.minute / 60)
    md = render(result, model, when)
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(md + "\n")
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or (repo or "/").split("/")[0]
    if token and repo and result.get("live"):
        try:
            print(notify(result, today.date().isoformat(), when, Issues(repo, token), owner))
        except Exception as e:
            print(f"notify failed (alerts still on the run page): {e}")
    return 0


# ── selftest (offline) ───────────────────────────────────────────────────────

def selftest() -> dict:
    import numpy as np
    f = []
    idx = pd.bdate_range(end="2026-10-05", periods=260)
    today = idx[-1]

    def series(last_move=0.0, base=100.0, drift=0.0004):
        v = base * np.exp(np.cumsum(np.r_[np.full(259, drift), [0.0]]))
        s = pd.Series(v, index=idx)
        s.iloc[-1] = s.iloc[-2] * (1 + last_move)
        return s

    model = {"available": True, "date": str(idx[-2].date()), "regime": "restrictive_tightening",
             "weights": {"VGT": 60.0, "XLV": 20.0, "SGOV": 20.0}, "nav": 100.0, "peak": 104.0,
             "breaker": "OFF", "gates": {"KMLM": {"state": "BLOCKED", "ma200": 99.0, "ma50": 98.0}}}
    calm = {"SPY": series(0.002), "VGT": series(0.003), "XLV": series(-0.001), "SGOV": series(0.0001),
            "^VIX": series(0.01, base=15, drift=0), "HYG": series(0.0), "IEF": series(0.001),
            "KMLM": series(0.0, base=95, drift=0)}
    r = run_checks(model, calm, today, 11.0)
    if [a for a in r["alerts"] if a["level"] in ("ALERT", "WARN")]:
        f.append(f"calm day must raise nothing loud: {r['alerts']}")
    crash = dict(calm, SPY=series(-0.045), VGT=series(-0.08), **{"^VIX": series(0.40, base=15, drift=0)},
                 HYG=series(-0.025), IEF=series(0.006))
    r = run_checks(model, crash, today, 14.75)
    keys = {a["key"] for a in r["alerts"]}
    for k in ("breaker_trip", "fastfall:VGT", "spy_drop", "vix", "credit_proxy"):
        if k not in keys:
            f.append(f"crash day must raise {k}: {keys}")
    _bt = next((a["text"] for a in r["alerts"] if a["key"] == "breaker_trip"), "")
    if not r["pre_close"] or "4:00 PM close" not in _bt:
        f.append("2:45 PM run must read as a pre-close verdict")
    # trigger met (INFO only)
    up = dict(calm, KMLM=series(0.0, base=101, drift=0))
    r = run_checks(model, up, today, 11.0)
    if not any(a["key"] == "trigger:KMLM" and a["level"] == "INFO" for a in r["alerts"]):
        f.append("a blocked add trading above its level must raise an INFO trigger")
    # no live bar -> nothing
    stale = {k: v.iloc[:-1] for k, v in calm.items()}
    if run_checks(model, stale, today, 11.0)["live"]:
        f.append("no live bar for today must check nothing")

    # notification: create, dedupe, extend, close yesterday
    class FakeIssues:
        def __init__(self):
            self.issues, self.calls, self.n = [{"number": 1, "title": "Intraday watch — 2026-10-02", "body": ""}], [], 1
        def open_watch_issues(self):
            return [dict(i) for i in self.issues if i.get("state") != "closed"]
        def ensure_label(self):
            self.calls.append("label")
        def create(self, title, body):
            self.n += 1
            self.issues.append({"number": self.n, "title": title, "body": body}); self.calls.append("create")
        def comment(self, number, body):
            self.calls.append(f"comment:{number}")
        def edit(self, number, **kw):
            for i in self.issues:
                if i["number"] == number:
                    i.update(kw)
            self.calls.append(f"edit:{number}:{','.join(kw)}")
    fi = FakeIssues()
    r1 = run_checks(model, crash, today, 11.0)
    a1 = notify(r1, "2026-10-05", "11:00", fi, "me")
    if a1["action"] != "create" or "edit:1:state" not in fi.calls:
        f.append(f"first loud run must create today's issue and close yesterday's: {a1} {fi.calls}")
    a2 = notify(r1, "2026-10-05", "13:30", fi, "me")
    if a2["action"] != "none":
        f.append(f"same alerts again must not email again: {a2}")
    r3 = dict(r1, alerts=r1["alerts"] + [{"key": "fastfall:XLV", "level": "ALERT", "text": "XLV down"}])
    a3 = notify(r3, "2026-10-05", "14:45", fi, "me")
    if a3["action"] != "comment" or a3["new"] != ["fastfall:XLV"]:
        f.append(f"a NEW alert must comment once: {a3}")
    if notify(run_checks(model, calm, today, 11.0), "2026-10-06", "11:00", FakeIssues(), "me")["action"] != "none":
        f.append("a calm day must never open an issue")
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
    else:
        raise SystemExit(main())
