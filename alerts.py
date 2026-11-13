"""
alerts.py — phone alerts for the books (risk_policy.md §9). Build #3, 2026-11-12.

WHAT IT DOES
  Reads the three nightly outputs, decides which alert conditions are live,
  and keeps one GitHub issue open per live condition. The GitHub mobile app
  pushes a new issue (and an @mention) to Matt's phone. No new service, no
  new keys: the workflow's own GITHUB_TOKEN opens and closes the issues.

    data/model_book.csv                 long-term model book (drawdown, breaker)
    logs/brief/YYYY-MM-DD_brief.json    consolidated daily brief (regime, data health)
    logs/swing/YYYY-MM-DD_brief.json    swing desk brief (loss limits, open positions)

RULES                                           severity   clears when
  LT_DD_10     model book <= -10% from peak     alert      above -8%  (2-pt hysteresis)
  LT_DD_15     model book <= -15% from peak     ALARM      above -13%
  LT_BREAKER   breaker WARN (-5%)               alert      warn off
  LT_BREAKER_ON  breaker ON (-8%)               ALARM      breaker off
  HY_OVERRIDE  regime = liquidity_crisis        ALARM      regime changes
  SWING_MONTH  swing monthly stand-down         alert      new month
  SWING_HWM    swing high-water stand-down      ALARM      journaled RESTART
  SWING_EXIT_<TK>  disaster stop traded         ALARM      position closed in the journal
                   other EXIT due at the open   alert
  DATA_FAIL    an input that feeds a decision   alert      inputs healthy again
               is STALE/MISSING/FAILED/DOWN, the
               swing price feed failed, or a
               source file is missing or stale
  ALERTS_SELFTEST  this script's own test fails ALARM     tests pass again

ISSUE CONTRACT
  title  "[KEY] one-line summary"; labels auto-alert + alert|alarm
  - live and no open issue for KEY  -> open one (push)
  - live and open, material change  -> comment with @mention (push)
  - not live, its source was read   -> comment "cleared" and close
  - its source could not be read    -> leave it alone (DATA_FAIL says why)

RUN
  python alerts.py              evaluate + sync (needs GITHUB_TOKEN, GITHUB_REPOSITORY)
  python alerts.py --dry        evaluate only, print what it would do
  python alerts.py --test       also open a [TEST] issue to prove the phone push;
                                the next normal run closes it
  python alerts.py --selftest   offline tests with a fake GitHub
Stdlib only, so the workflow needs no pip install.
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

VERSION = "alerts v1 (build #3, 2026-11-12)"
ROOT = Path(os.environ.get("ALERTS_ROOT", "."))
OUT_DIR = Path("logs/alerts")

LT_ALERT, LT_ALERT_CLEAR = -10.0, -8.0
LT_ALARM, LT_ALARM_CLEAR = -15.0, -13.0
BAD_STATUS = {"STALE", "MISSING", "FAILED", "FAIL", "DOWN"}
IGNORED_INPUTS = {"Position ledger"}          # UNUSED by design: the model book is the reference
MAX_SOURCE_AGE_DAYS = 4                        # covers a weekend plus a holiday
LABEL_ROOT = "auto-alert"
LABELS = {LABEL_ROOT: "5319e7", "alert": "fbca04", "alarm": "d73a4a"}
FAMILIES = ("LT", "HY", "SWING", "DATA", "TEST", "ALERTS")


def _family(key: str) -> str:
    return key.split("_", 1)[0]


def _fp(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def finding(key, severity, title, body, fp=None, state="active") -> dict:
    return {"key": key, "severity": severity, "title": title, "body": body,
            "fp": fp or _fp(key, severity), "state": state}


# ── Sources ─────────────────────────────────────────────────────────────────

def _latest_json(pattern: str):
    files = sorted(f for f in glob.glob(str(ROOT / pattern)) if re.search(r"\d{4}-\d{2}-\d{2}_brief\.json$", f))
    if not files:
        return None, None
    p = files[-1]
    try:
        return json.loads(Path(p).read_text()), Path(p).name[:10]
    except Exception:
        return None, Path(p).name[:10]


def load_sources() -> dict:
    mb, mb_err = None, None
    p = ROOT / "data" / "model_book.csv"
    try:
        with open(p, newline="") as fh:
            rows = list(csv.DictReader(fh))
        mb = rows[-1] if rows else None
        if mb is None:
            mb_err = "model_book.csv has no rows"
    except Exception as e:
        mb_err = f"model_book.csv unreadable: {type(e).__name__}"
    daily, daily_date = _latest_json("logs/brief/*_brief.json")
    swing, swing_date = _latest_json("logs/swing/*_brief.json")
    return {"model_book": mb, "model_book_error": mb_err, "daily": daily, "daily_date": daily_date,
            "swing": swing, "swing_date": swing_date}


def _age(d: Optional[str], today: date) -> Optional[int]:
    try:
        return (today - date.fromisoformat(str(d)[:10])).days
    except Exception:
        return None


def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return None if v != v else v
    except Exception:
        return None


# ── Rules ───────────────────────────────────────────────────────────────────

def evaluate(src: dict, today: date) -> tuple[list[dict], set]:
    """(findings, families whose sources were read). A family not read is never auto-closed."""
    out, fams, data = [], {"DATA", "TEST", "ALERTS"}, []

    # long-term model book
    mb = src.get("model_book")
    if mb is None:
        data.append(f"model book: {src.get('model_book_error') or 'missing'} — blocks the LT drawdown alarms")
    else:
        age = _age(mb.get("date"), today)
        if age is None or age > MAX_SOURCE_AGE_DAYS:
            data.append(f"model book last row {mb.get('date')} ({age} days old) — LT drawdown alarms are blind")
        else:
            fams.add("LT")
            dd = _num(mb.get("drawdown_pct"))
            nav, peak = mb.get("nav"), mb.get("peak")
            line = f"Model book {dd:+.2f}% from peak (NAV {nav}, peak {peak}) on {mb.get('date')}; breaker {mb.get('breaker')}." if dd is not None else ""
            if dd is None:
                data.append("model book drawdown_pct unreadable — LT drawdown alarms are blind"); fams.discard("LT")
            else:
                if dd <= LT_ALARM or LT_ALARM < dd <= LT_ALARM_CLEAR:
                    out.append(finding("LT_DD_15", "alarm", f"Model book {dd:+.1f}% from peak — ALARM",
                        line + "\n\n**ALARM (risk_policy §3).** Mandatory written review within 2 sessions: is the "
                        "regime call, the posture or a rule wrong? **No new adds until the review is done.** "
                        "The breaker rules are unchanged.",
                        state="active" if dd <= LT_ALARM else "hold"))
                if dd <= LT_ALERT or LT_ALERT < dd <= LT_ALERT_CLEAR:
                    out.append(finding("LT_DD_10", "alert", f"Model book {dd:+.1f}% from peak — alert",
                        line + "\n\n**Alert (risk_policy §3).** Nothing to trade from this alone. It leads the weekend "
                        "review; the −15% alarm triggers a mandatory written review.",
                        state="active" if dd <= LT_ALERT else "hold"))
            brk = str(mb.get("breaker") or "").upper()
            warn = str(mb.get("warn") or "").strip().lower() in ("true", "1", "yes", "warn")
            if brk == "ON":
                out.append(finding("LT_BREAKER_ON", "alarm", "Model-book breaker ON — risk sleeves halved into SGOV",
                    line + "\n\nThe −8% breaker tripped (risk_policy §3, `model_book.py`): risk sleeves halved into "
                    "SGOV. Release above −5% with SPY > 50-day on 2 closes. Daily authority item 3."))
            elif warn:
                out.append(finding("LT_BREAKER", "alert", "Model-book breaker WARN (−5%)",
                    line + "\n\nWarn line crossed: the breaker trips at −8% (risk sleeves halved into SGOV)."))

    # consolidated daily brief
    daily = src.get("daily")
    dage = _age(src.get("daily_date"), today)
    if daily is None:
        data.append("daily brief missing or unreadable — regime/HY override and input health unknown")
    elif dage is None or dage > MAX_SOURCE_AGE_DAYS:
        data.append(f"daily brief {src.get('daily_date')} is {dage} days old — regime/HY override unknown")
    else:
        fams.add("HY")
        rk = (daily.get("regime") or {}).get("key")
        if rk == "liquidity_crisis":
            out.append(finding("HY_OVERRIDE", "alarm", "HY crisis override: regime liquidity_crisis",
                f"The daily brief for {src.get('daily_date')} reads `liquidity_crisis` (HY crisis override). "
                "Daily authority item 1: apply the override per `regime_playbook.md`. The swing desk stands "
                "aside (long-only)."))
        for d in daily.get("data_health") or []:
            if d.get("status") in BAD_STATUS and d.get("input") not in IGNORED_INPUTS:
                data.append(f"{d.get('input')}: {d.get('status')} (as of {d.get('asof')}) {d.get('note') or ''}".strip())

    # swing brief
    sw = src.get("swing")
    sage = _age(src.get("swing_date"), today)
    if sw is None:
        data.append("swing brief missing or unreadable — swing stand-downs and exits unknown")
    elif sage is None or sage > MAX_SOURCE_AGE_DAYS:
        data.append(f"swing brief {src.get('swing_date')} is {sage} days old — swing stand-downs and exits unknown")
    else:
        fams.add("SWING")
        rs = sw.get("risk_state") or {}
        m, h = rs.get("monthly") or {}, rs.get("high_water") or {}
        if m.get("active"):
            out.append(finding("SWING_MONTH", "alert", f"Swing monthly stand-down ({m.get('month')})",
                (m.get("refusal") or "") + f"\n\nEquity marked to market ${rs.get('equity_mtm')}. Lifts on the 1st.",
                fp=_fp("SWING_MONTH", m.get("month"))))
        if h.get("active"):
            out.append(finding("SWING_HWM", "alarm", "Swing high-water stand-down (−20%) — ALARM",
                (h.get("refusal") or "") + "\n\nRestart: write the incident review, then **Approve restart** in "
                "the Swing tab (journals a RESTART).", fp=_fp("SWING_HWM", h.get("tripped_on"))))
        if sw.get("risk_state") is None:
            data.append("swing brief has no risk_state (pre-build #3 desk?) — swing stand-downs unknown")
        for p in sw.get("open_positions") or []:
            tk = p.get("ticker")
            if p.get("recommendation") == "NO DATA":
                data.append(f"swing open position {tk}: no price data — check it manually")
                continue
            if p.get("recommendation") != "EXIT":
                continue
            hit = "HIT" in str((p.get("triggers") or {}).get("disaster") or "")
            detail = (f"{tk} {p.get('setup')} · entry {p.get('entry')} · stop {p.get('stop')} · disaster "
                      f"{p.get('disaster_stop')} · close {p.get('current')} · {p.get('R')}R\n\n→ {p.get('why')}")
            if hit:
                out.append(finding(f"SWING_EXIT_{tk}", "alarm", f"{tk}: disaster stop traded — confirm the fill",
                    detail + "\n\nThe resting stop likely filled. Confirm in thinkorswim/Schwab and journal the EXIT "
                    "in the Swing tab.", fp=_fp(tk, "disaster")))
            else:
                out.append(finding(f"SWING_EXIT_{tk}", "alert", f"{tk}: EXIT due at the next open",
                    detail + "\n\nSell at the next open (closing-basis rule), then journal the EXIT.",
                    fp=_fp(tk, "exit")))
        dh = sw.get("data_health") or {}
        if dh.get("failed"):
            data.append(f"swing price feed FAILED: {len(dh.get('missing') or [])} missing + "
                        f"{len(dh.get('stale') or [])} stale of {dh.get('requested')} — no cards tonight")

    if data:
        out.append(finding("DATA_FAIL", "alert", f"Data failure: {len(data)} input(s) block decisions",
            "Inputs that feed a decision are missing or stale. A data gap is not a signal: the decisions that "
            "use these inputs are blocked until they refresh.\n\n" + "\n".join(f"- {x}" for x in data),
            fp=_fp(*sorted(re.sub(r"\(.*?\)|\d+ days old|\d+", "", x) for x in data))))
    return out, fams


# ── GitHub ──────────────────────────────────────────────────────────────────

class GitHub:
    def __init__(self, repo: str, token: str):
        self.repo, self.token = repo, token

    def _req(self, method: str, path: str, body: Optional[dict] = None):
        url = f"https://api.github.com/repos/{self.repo}{path}"
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "portfolio-tracker-alerts"})
        with urllib.request.urlopen(r, timeout=30) as resp:
            txt = resp.read().decode()
            return json.loads(txt) if txt else None

    def ensure_labels(self):
        for name, color in LABELS.items():
            try:
                self._req("POST", "/labels", {"name": name, "color": color})
            except urllib.error.HTTPError as e:
                if e.code != 422:          # 422 = already exists
                    raise

    def open_issues(self) -> list[dict]:
        out = self._req("GET", f"/issues?state=open&labels={LABEL_ROOT}&per_page=100") or []
        return [i for i in out if "pull_request" not in i]

    def create(self, title, body, labels):
        return self._req("POST", "/issues", {"title": title, "body": body, "labels": labels})

    def comment(self, number, body):
        return self._req("POST", f"/issues/{number}/comments", {"body": body})

    def close(self, number):
        return self._req("PATCH", f"/issues/{number}", {"state": "closed", "state_reason": "completed"})

    def edit_body(self, number, body):
        return self._req("PATCH", f"/issues/{number}", {"body": body})


def _key_of(title: str) -> Optional[str]:
    m = re.match(r"^\[([A-Z0-9_\-]+)\]", title or "")
    return m.group(1) if m else None


def _fp_of(body: str) -> Optional[str]:
    m = re.findall(r"<!-- fp:([0-9a-f]+) -->", body or "")
    return m[-1] if m else None


def sync(findings: list[dict], fams: set, gh, mention: str, today: date) -> list[dict]:
    """Bring the open auto-alert issues in line with the findings. Returns the actions taken."""
    acts = []
    gh.ensure_labels()
    issues = {}
    for i in gh.open_issues():
        k = _key_of(i.get("title"))
        if k:
            issues.setdefault(k, i)
    live = {f["key"]: f for f in findings}
    for k, f in live.items():
        i = issues.get(k)
        tag = f"<!-- fp:{f['fp']} -->"
        if f["state"] == "hold":
            continue                                              # inside the hysteresis band: no new issue, no close
        if i is None:
            body = (f"@{mention} **{f['severity'].upper()}** — {today.isoformat()}\n\n{f['body']}\n\n"
                    f"_Opened by `alerts.py` ({VERSION}). It closes itself when the condition clears._\n{tag}")
            n = gh.create(f"[{k}] {f['title']}", body, [LABEL_ROOT, f["severity"]])
            acts.append({"action": "open", "key": k, "number": (n or {}).get("number")})
        else:
            # the body always ends with the latest fingerprint, so one material change = one push
            if _fp_of(i.get("body")) != f["fp"]:
                gh.comment(i["number"], f"@{mention} update {today.isoformat()}:\n\n{f['body']}")
                gh.edit_body(i["number"], re.sub(r"<!-- fp:[0-9a-f]+ -->", tag, i.get("body") or "") if _fp_of(i.get("body"))
                             else (i.get("body") or "") + "\n" + tag)
                acts.append({"action": "update", "key": k, "number": i["number"]})
            else:
                acts.append({"action": "still open", "key": k, "number": i["number"]})
    for k, i in issues.items():
        if k in live or _family(k) not in fams:
            continue
        gh.comment(i["number"], f"Cleared {today.isoformat()}: the condition is no longer live. Closing.")
        gh.close(i["number"])
        acts.append({"action": "close", "key": k, "number": i["number"]})
    return acts


# ── Selftest (offline: fake GitHub, synthetic sources) ──────────────────────

class FakeGitHub:
    def __init__(self):
        self.issues, self.n, self.calls = {}, 0, []

    def ensure_labels(self):
        self.calls.append("labels")

    def open_issues(self):
        return [dict(i) for i in self.issues.values() if i["state"] == "open"]

    def create(self, title, body, labels):
        self.n += 1
        self.issues[self.n] = {"number": self.n, "title": title, "body": body, "labels": labels, "state": "open"}
        self.calls.append(("create", title)); return {"number": self.n}

    def comment(self, number, body):
        self.calls.append(("comment", number, body))

    def edit_body(self, number, body):
        self.issues[number]["body"] = body; self.calls.append(("edit", number))

    def close(self, number):
        self.issues[number]["state"] = "closed"; self.calls.append(("close", number))

    def open_keys(self):
        return sorted(_key_of(i["title"]) for i in self.issues.values() if i["state"] == "open")


def _src(dd=-3.7, breaker="OFF", warn="False", regime="transition_ambiguous", health=None, rs=None,
         opens=None, swing_failed=False, d="2026-11-12"):
    return {"model_book": {"date": d, "nav": "98.2", "peak": "101.9", "drawdown_pct": str(dd), "breaker": breaker,
                           "warn": warn},
            "model_book_error": None, "daily_date": d,
            "daily": {"regime": {"key": regime}, "data_health": health or [{"input": "FRED DGS10", "status": "OK"},
                      {"input": "Position ledger", "status": "STALE"}]},
            "swing_date": d,
            "swing": {"risk_state": rs if rs is not None else {"equity_mtm": 10000, "monthly": {"active": False},
                                                               "high_water": {"active": False}},
                      "open_positions": opens or [], "data_health": {"failed": swing_failed}}}


def selftest() -> dict:
    f = []
    T = date(2026, 11, 12)
    keys = lambda src: sorted(x["key"] for x in evaluate(src, T)[0] if x["state"] == "active")

    if keys(_src()) != []:
        f.append(f"a calm night must raise nothing (Position ledger STALE is ignored): {keys(_src())}")
    if keys(_src(dd=-10.0)) != ["LT_DD_10"]:
        f.append("exactly -10% must raise the LT alert")
    if keys(_src(dd=-15.2)) != ["LT_DD_10", "LT_DD_15"]:
        f.append(f"-15.2% must raise both the alert and the alarm: {keys(_src(dd=-15.2))}")
    held = [x for x in evaluate(_src(dd=-9.0), T)[0] if x["key"] == "LT_DD_10"]
    if not held or held[0]["state"] != "hold":
        f.append("-9% must hold an open -10% alert (hysteresis), not clear it")
    held15 = [x for x in evaluate(_src(dd=-14.0), T)[0] if x["key"] == "LT_DD_15"]
    if not held15 or held15[0]["state"] != "hold":
        f.append("-14% must hold an open -15% alarm (hysteresis), not clear it")
    g0 = FakeGitHub(); sync(*evaluate(_src(dd=-9.0), T), g0, "owner", T)
    if g0.open_keys():
        f.append("inside the hysteresis band with no open issue, nothing may be opened")
    if keys(_src(warn="True")) != ["LT_BREAKER"] or keys(_src(breaker="ON", warn="True")) != ["LT_BREAKER_ON"]:
        f.append("breaker WARN -> alert; ON -> alarm only")
    if keys(_src(regime="liquidity_crisis")) != ["HY_OVERRIDE"]:
        f.append("liquidity_crisis must raise the HY override alarm")
    bad = _src(health=[{"input": "FRED DGS10", "status": "MISSING", "asof": None}])
    if keys(bad) != ["DATA_FAIL"] or "FRED DGS10" not in evaluate(bad, T)[0][0]["body"]:
        f.append("a MISSING input must raise DATA_FAIL naming it")
    if keys(_src(health=[{"input": "macro_flags", "status": "WARN"}])) != []:
        f.append("WARN is context, not a data failure")
    if keys(_src(swing_failed=True)) != ["DATA_FAIL"]:
        f.append("a failed swing price feed must raise DATA_FAIL")
    rs_m = {"equity_mtm": 8900, "monthly": {"active": True, "month": "2026-11", "refusal": "MONTHLY STAND-DOWN"},
            "high_water": {"active": False}}
    rs_h = {"equity_mtm": 7900, "monthly": {"active": True, "month": "2026-11", "refusal": "x"},
            "high_water": {"active": True, "tripped_on": "2026-11-10", "refusal": "HIGH-WATER STAND-DOWN"}}
    if keys(_src(rs=rs_m)) != ["SWING_MONTH"] or keys(_src(rs=rs_h)) != ["SWING_HWM", "SWING_MONTH"]:
        f.append("swing stand-downs must map to SWING_MONTH (alert) and SWING_HWM (alarm)")
    ex = {"ticker": "XLU", "recommendation": "EXIT", "triggers": {"disaster": "resting at 70"}, "why": "closing-basis stop"}
    dx = {"ticker": "XEL", "recommendation": "EXIT", "triggers": {"disaster": "HIT — low 60 reached 61"}, "why": "disaster"}
    ev = {x["key"]: x for x in evaluate(_src(opens=[ex, dx, {"ticker": "SPG", "recommendation": "HOLD"}]), T)[0]}
    if set(ev) != {"SWING_EXIT_XLU", "SWING_EXIT_XEL"} or ev["SWING_EXIT_XEL"]["severity"] != "alarm" \
            or ev["SWING_EXIT_XLU"]["severity"] != "alert":
        f.append(f"exit due -> alert, disaster hit -> alarm, HOLD -> nothing: {sorted(ev)}")
    old = _src(d="2026-11-01")
    o_keys, o_fams = evaluate(old, T)
    if [x["key"] for x in o_keys] != ["DATA_FAIL"] or o_fams & {"LT", "HY", "SWING"}:
        f.append("11-day-old sources must raise DATA_FAIL and mark their families unread (no auto-close)")
    nosw = _src(); nosw["swing"]["risk_state"] = None
    nosw["swing"].pop("risk_state")
    if keys(nosw) != ["DATA_FAIL"]:
        f.append("a swing brief without risk_state must be flagged (stand-downs unknown)")

    # sync lifecycle with a fake GitHub
    gh = FakeGitHub()
    run = lambda src: sync(*evaluate(src, T), gh, "owner", T)
    run(_src(dd=-10.5))
    if gh.open_keys() != ["LT_DD_10"] or "@owner" not in gh.issues[1]["body"] or gh.issues[1]["labels"] != [LABEL_ROOT, "alert"]:
        f.append(f"open with @mention and labels: {gh.open_keys()} {gh.issues.get(1)}")
    run(_src(dd=-11.0))
    if gh.n != 1 or any(c[0] == "comment" for c in gh.calls if isinstance(c, tuple)):
        f.append("a live condition must not re-open or spam comments when nothing material changed")
    run(_src(dd=-9.0))
    if gh.open_keys() != ["LT_DD_10"]:
        f.append("inside the hysteresis band the issue stays open")
    run(_src(d="2026-11-01", dd=-3.0))
    if gh.open_keys() != ["DATA_FAIL", "LT_DD_10"]:
        f.append(f"unread source must not close its issues: {gh.open_keys()}")
    run(_src(dd=-3.0))
    if gh.open_keys() != []:
        f.append(f"healthy, recovered night must close everything: {gh.open_keys()}")
    run(_src(health=[{"input": "FRED DGS10", "status": "MISSING"}]))
    n_comments = sum(1 for c in gh.calls if isinstance(c, tuple) and c[0] == "comment")
    run(_src(health=[{"input": "FRED DGS10", "status": "MISSING"}, {"input": "Markets bridge", "status": "STALE"}]))
    n2 = sum(1 for c in gh.calls if isinstance(c, tuple) and c[0] == "comment")
    last_c = [c for c in gh.calls if isinstance(c, tuple) and c[0] == "comment"][-1]
    if n2 != n_comments + 1 or "@owner" not in last_c[2] or "Markets bridge" not in last_c[2]:
        f.append("a new failed input on an open DATA_FAIL must post one @mention update")
    run(_src(health=[{"input": "FRED DGS10", "status": "MISSING"}, {"input": "Markets bridge", "status": "STALE"}]))
    if sum(1 for c in gh.calls if isinstance(c, tuple) and c[0] == "comment") != n2:
        f.append("the same failed inputs on the next night must not post again")
    # TEST issue: opened on demand, closed by the next normal run
    tsrc = _src(); fs, fm = evaluate(tsrc, T)
    sync(fs + [finding("TEST", "alert", "Alert pipeline test", "test")], fm, gh, "owner", T)
    if "TEST" not in gh.open_keys():
        f.append("--test must open a TEST issue")
    run(_src())
    if "TEST" in gh.open_keys():
        f.append("the next normal run must close the TEST issue")
    if _key_of("[SWING_EXIT_XLU] x") != "SWING_EXIT_XLU" or _key_of("no key") is not None:
        f.append("title key parse")
    return {"ok": not f, "failures": f, "version": VERSION}


# ── Main ────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    st = selftest()
    if a.selftest:
        print(json.dumps(st, indent=2)); return 0 if st["ok"] else 1
    today = datetime.now(timezone.utc).date()
    try:
        import market_time as mt
        today = mt.et_date()
    except Exception:
        pass
    findings, fams = evaluate(load_sources(), today)
    if not st["ok"]:
        findings.append(finding("ALERTS_SELFTEST", "alarm", "alerts.py selftest failing — alerts may be wrong",
                                "\n".join(f"- {x}" for x in st["failures"])))
    if a.test:
        findings.append(finding("TEST", "alert", "Alert pipeline test — did this reach your phone?",
            "If this arrived as a push notification, the alert pipeline works. Nothing to do: the next nightly "
            "run closes this issue.", fp=_fp("TEST", today)))
    repo = os.environ.get("GITHUB_REPOSITORY")
    mention = os.environ.get("ALERT_MENTION") or (repo.split("/")[0] if repo else "owner")
    actions, err = [], None
    if a.dry:
        actions = [{"action": "would-" + ("hold" if x["state"] == "hold" else "raise"), "key": x["key"],
                    "severity": x["severity"]} for x in findings]
    elif not (repo and os.environ.get("GITHUB_TOKEN")):
        err = "GITHUB_TOKEN / GITHUB_REPOSITORY not set — evaluated only, no issues touched"
    else:
        try:
            actions = sync(findings, fams, GitHub(repo, os.environ["GITHUB_TOKEN"]), mention, today)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "date": today.isoformat(),
               "version": VERSION, "selftest_ok": st["ok"], "families_read": sorted(fams),
               "findings": [{k: x[k] for k in ("key", "severity", "state", "title")} for x in findings],
               "actions": actions, "error": err}
    if not a.dry:
        (ROOT / OUT_DIR).mkdir(parents=True, exist_ok=True)
        (ROOT / OUT_DIR / "latest.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 1 if err and not a.dry and "not set" not in err else 0


if __name__ == "__main__":
    sys.exit(main())
