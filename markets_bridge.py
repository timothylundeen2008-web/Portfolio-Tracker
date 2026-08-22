"""
markets_bridge.py  (v1 — August 2026)
─────────────────────────────────────
Markets Dashboard → All-Weather. The second half of the data spine.

WHY THIS MIRRORS rotation_bridge.py DELIBERATELY
────────────────────────────────────────────────
rotation_bridge already carries Money Flow → All-Weather using
storage_backend's GitHub-backed durable store, with staleness thresholds and
an explicit "not evidence beyond this age" rule. That pattern works and has
been in production.

This is the same pattern for the Markets Dashboard's outputs, using the same
storage backend, the same staleness discipline, and the same
never-fabricate rules. Inventing a second, parallel mechanism would mean two
things to keep in sync, two failure modes, and two places to check when
something goes dark.

WHAT IS PUBLISHED
─────────────────
Only what All-Weather cannot compute for itself:

    regime          key, label, WHY it was routed there (transition_reason)
    guards          which of the four guards are blocking, and why
    growth axis     state + composite score
    tripwires       distance to every pre-committed threshold
    relative strength   quartile per sleeve
    trend state     scalar per sleeve
    conviction      3-of-3 score per sleeve

STALENESS IS A FIRST-CLASS FIELD
────────────────────────────────
A regime read from four days ago is not evidence about today. Every consumer
gets `age_hours`, `stale` and `very_stale`, and the All-Weather suggestion
engine is written to DOWNGRADE its confidence rather than silently use old
data — the same discipline as the flow layer's coverage gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from storage_backend import read_json, write_json

MARKETS_FILE = "markets_summary.json"
STALE_HOURS = 36
VERY_STALE_HOURS = 168


# ── Producer side (runs in the Markets Dashboard) ───────────────────────────
def publish(regime: dict, repression: Optional[dict] = None,
            growth: Optional[dict] = None,
            tripwires: Optional[list] = None,
            rs: Optional[dict] = None,
            trends: Optional[dict] = None,
            conviction: Optional[dict] = None,
            targets: Optional[dict] = None,
            kmlm: Optional[dict] = None,
            notes: str = "") -> dict:
    """
    Publish the Markets Dashboard's outputs for All-Weather to consume.

    Everything optional — a partial publish with named gaps beats no publish
    at all, and consumers check per-field rather than assuming completeness.
    """
    payload = {
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notes": notes,
        "regime": {
            "key": (regime or {}).get("key"),
            "label": (regime or {}).get("label"),
            "transition_reason": (regime or {}).get("transition_reason"),
            "drivers": (regime or {}).get("drivers", [])[:12],
        },
        "repression": {
            "score": (repression or {}).get("score"),
            "band": (repression or {}).get("band"),
            "hollow": (repression or {}).get("hollow"),
            "top_weight": (repression or {}).get("top_weight_display"),
            "missing": (repression or {}).get("missing", []),
        },
        "growth": {
            "state": (growth or {}).get("state"),
            "score": (growth or {}).get("score"),
            "confirmed": (growth or {}).get("confirmed"),
        },
        "kmlm_stance": (kmlm or {}).get("stance"),
        "tripwires": [
            {"name": t.get("name"), "value": t.get("value"),
             "threshold": t.get("threshold"), "distance": t.get("distance"),
             "direction": t.get("direction"), "severity": t.get("severity")}
            for t in (tripwires or []) if t.get("available")
        ][:12],
        "rs_quartiles": (rs or {}).get("quartiles", {}),
        "trend_scalars": {
            tk: s.get("scalar")
            for tk, s in (trends or {}).get("states", {}).items()
        },
        "trend_states": {
            tk: s.get("state")
            for tk, s in (trends or {}).get("states", {}).items()
        },
        "conviction": {
            tk: {"score": c.get("score"), "multiplier": c.get("multiplier")}
            for tk, c in (conviction or {}).items()
        },
        "regime_targets": targets or {},
    }

    res = write_json(MARKETS_FILE, payload,
                     message=f"markets: publish summary "
                             f"{payload['published_at']}")
    return {"ok": bool(res.get("github") or res.get("local")),
            "durable": res.get("durable", False),
            "storage": res,
            "regime": payload["regime"]["key"]}


# ── Consumer side (runs in All-Weather) ─────────────────────────────────────
def read() -> dict:
    """
    Read the published Markets summary, with staleness front and centre.

    Returns available=False rather than an empty-but-plausible dict when
    nothing has been published — the consumer must be able to distinguish
    "no data" from "neutral data".
    """
    data = read_json(MARKETS_FILE)
    if not data:
        return {"available": False, "stale": True, "very_stale": True,
                "message": ("No Markets summary published yet. Open the "
                           "Markets Dashboard and let it publish, or run "
                           "markets_bridge.publish() from its scheduled job.")}

    try:
        published = datetime.fromisoformat(data["published_at"])
        age_h = (datetime.now(timezone.utc) - published).total_seconds() / 3600
    except Exception:
        return {"available": False, "stale": True, "very_stale": True,
                "message": "Markets summary has an unreadable timestamp."}

    stale = age_h > STALE_HOURS
    very_stale = age_h > VERY_STALE_HOURS

    out = dict(data)
    out.update({
        "available": True,
        "age_hours": round(age_h, 1),
        "stale": stale,
        "very_stale": very_stale,
    })
    if very_stale:
        out["message"] = (f"⚠ VERY STALE ({age_h/24:.1f} days). Do NOT treat "
                         f"as evidence about today's market — republish "
                         f"before acting on any of it.")
    elif stale:
        out["message"] = (f"⚠ Stale ({age_h:.0f}h). Usable for context, but "
                         f"confidence in every downstream suggestion should "
                         f"be downgraded.")
    else:
        out["message"] = f"Fresh ({age_h:.0f}h old)."
    return out


def selftest() -> dict:
    """Round-trip through the real storage backend."""
    failures = []
    demo_regime = {"key": "transition_ambiguous",
                   "label": "Transition — Growth Guard Active",
                   "transition_reason": "growth_guard",
                   "drivers": ["test driver"]}
    res = publish(regime=demo_regime,
                  growth={"state": "DETERIORATING", "score": -3,
                          "confirmed": True},
                  rs={"quartiles": {"VGT": 1, "TLT": 4}},
                  trends={"states": {"VGT": {"scalar": 1.0,
                                             "state": "CONFIRMED UPTREND"}}},
                  notes="selftest")
    if not res["ok"]:
        failures.append(f"publish failed: {res}")

    back = read()
    if not back.get("available"):
        failures.append(f"read failed: {back.get('message')}")
    else:
        if back["regime"]["key"] != "transition_ambiguous":
            failures.append("regime did not round-trip")
        if back["regime"]["transition_reason"] != "growth_guard":
            failures.append("transition_reason did not round-trip")
        if back["rs_quartiles"].get("VGT") != 1:
            failures.append("rs quartiles did not round-trip")
        if back["stale"]:
            failures.append("freshly published summary reported as stale")

    return {"ok": not failures, "failures": failures,
            "durable": res.get("durable"),
            "age_hours": back.get("age_hours")}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2, default=str))
