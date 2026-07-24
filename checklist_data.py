"""
checklist_data.py  (v5 — July 2026)
──────────────────────────────────────────────────────────────────────────────
THE CANONICAL SOURCE OF THE DASHBOARD ANALYSIS CHECKLIST.

Why this file exists in this form:
  v5 Part 5 ("When the code changes") establishes that duplicated documentation
  is a liability — the same methodology explained in two places gets fixed in
  one and rots in the other. That has now happened three times in this codebase.

  So the checklist content lives HERE, once, as data. The human-readable
  markdown is GENERATED from it (render_markdown() below), and the app renders
  the same structure as interactive widgets. One source, two renderings, no
  drift possible.

  If you edit the checklist, edit THIS FILE, then regenerate the markdown:
      python -c "import checklist_data as c; print(c.render_markdown())" > checklist_v5.md

ITEM KINDS — this is also the machine-readable gap analysis:
  auto        value is fetched automatically; user confirms/observes
  manual_num  user must type a number no data source provides
  manual_bool user must answer yes/no from an external source
  manual_text free text (judgment, notes)
  action      a thing you DO, not a thing you record (e.g. "exit the position")

  Every manual_* item is, by definition, a data gap. Count them with
  gap_report() to see exactly where the automation stops.

TIERS (v5 evidence-tier rule):
  A = money (creations/redemptions, COT)   B = directional volume/pressure
  C = price/outcome                        — = not a flow claim
"""

from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
#  DAILY
# ─────────────────────────────────────────────────────────────────────────────

DAILY_STEPS = [
    {
        "id": "d1", "title": "Credit: HY OAS (FRED: BAMLH0A0HYM2)", "tier": "—",
        "items": [
            {"id": "d1_level", "kind": "auto", "field": "hy_oas", "unit": "%",
             "text": "Record today's HY OAS. Flag if above 3.50% and rising; "
                     "ALARM if above 5.00% AND widening more than 0.50% in 2 weeks.",
             "why": "Credit leads equities into every genuine crisis. This is the "
                    "classifier's liquidity-crisis override — the ONE signal allowed to "
                    "beat the inflation regime, re-arm TLT (+6), and cut growth intraweek. "
                    "It is also the asymmetry you accepted: running TLT at 0% costs about "
                    "3 points of hedge in a 2008-style bust, and this daily check is the "
                    "tripwire that restores it in time. Baseline: 2.75% (Jul 2026) = calm.",
             "alert": {"warn": ("gt", 3.50), "alarm": ("gt", 5.00)}},
            {"id": "d1_mom", "kind": "auto", "field": "hy_oas_mom_2w", "unit": "pp",
             "text": "Note the 30-day change. Widening more than 1.00% in 30 days = "
                     "broad de-risk signal even below the 5% line.",
             "why": "Spread velocity matters as much as level — the 2008 and 2020 "
                    "blowouts were visible in the rate of change weeks before the level "
                    "looked scary.",
             "alert": {"warn": ("gt", 0.50)}},
        ],
    },
    {
        "id": "d2", "title": "Volatility: VIX level and term structure", "tier": "—",
        "items": [
            {"id": "d2_vix", "kind": "auto", "field": "vix", "unit": "",
             "text": "Record VIX. Above 30 sustained = de-risk equities. Above 35 = "
                     "trend-whipsaw zone: pause any KMLM ADDS (do not sell).",
             "why": "KMLM is trend-following; it earns in sustained moves and bleeds in "
                    "V-shaped panic reversals. VIX above 35 marks the tape where trend "
                    "systems get whipsawed — you stop adding, but you do not dump the "
                    "hedge mid-crisis.",
             "alert": {"warn": ("gt", 30), "alarm": ("gt", 35)}},
            {"id": "d2_term", "kind": "auto", "field": "vix_term_spread", "unit": "",
             "text": "Check term structure: spot VIX above 3-month VIX (backwardation) "
                     "= late-crisis signature.",
             "why": "Contango is normal. Backwardation means the market is paying up for "
                    "protection NOW — historically a late-stage crisis marker and the "
                    "tell to shift from de-risking to preparing the rebalance-at-lows list.",
             "alert": {"warn": ("gt", 0.0)}},
        ],
    },
    {
        "id": "d3", "title": "The discount rate: DFII10 (10y TIPS real yield)", "tier": "—",
        "items": [
            {"id": "d3_level", "kind": "auto", "field": "long_real_yield", "unit": "%",
             "text": "Record DFII10 close and direction vs yesterday. Note if it crosses "
                     "2.50% (up) or shows 5+ consecutive down days.",
             "why": "DFII10 is the discount rate for every risk asset and the single input "
                    "that governs the TLT sleeve (0% while rising), the growth trim "
                    "(VGT/SMH/QQQ compress as it rises), and the soft-vs-hard repression "
                    "split. Above ~2.50%, long-duration equity multiples historically "
                    "cannot ignore it — that is your trigger to trim growth further. Five "
                    "straight down days is the earliest hint the regime may be rotating "
                    "toward hard repression.",
             "alert": {"warn": ("gt", 2.50)}},
        ],
    },
    {
        "id": "d4", "title": "Dollar & auction demand: DXY divergence and Treasury bid-to-cover",
        "tier": "—",
        "items": [
            {"id": "d4_dxy", "kind": "auto", "field": "dxy_chg_20d", "unit": "%",
             "text": "Record DXY's 20-trading-day % change alongside DFII10/10-yr "
                     "nominal's 20-day change. Flag DIVERGENCE if the 10-yr yield is up "
                     "more than 0.10pp over 20 days while DXY is down more than 1.0%.",
             "why": "Normally a rising US real yield pulls in foreign capital and supports "
                    "the dollar. When yields rise while DXY falls, bond buyers are pricing "
                    "debt-confidence risk into the term premium rather than growth or "
                    "Fed-policy expectations — a leading, not lagging, tell. This does NOT "
                    "add a fourth authorized daily trade; it is context that sharpens the "
                    "weekly regime read."},
            {"id": "d4_btc", "kind": "auto", "field": "auction_btc", "unit": "",
             "text": "On Treasury 10-yr auction days only (roughly monthly): record the "
                     "bid-to-cover ratio. Note if below 2.30 (softening) or below 2.00 "
                     "(stressed).",
             "why": "Auction demand is a leading indicator of debt-sustainability stress, "
                    "the same category as HY spread velocity but for the Treasury market "
                    "itself. A weakening trend across 2–3 consecutive auctions — not one "
                    "print — is what would eventually warrant a weekly-review discussion, "
                    "never a same-day reaction.",
             "source": "treasury_data.auction_demand() — TreasuryDirect TA_WS API. "
                       "Reports the TREND across the last 4 auctions, not a single "
                       "print, per this step's own rule that one auction is noise."},
        ],
    },
    {
        "id": "d5", "title": "The curve: 2s10s (T10Y2Y)", "tier": "—",
        "items": [
            {"id": "d5_level", "kind": "auto", "field": "spread_2s10s", "unit": "pp",
             "text": "Record the spread. Apply the noise filter: moves that revert within "
                     "1–2 weeks are noise (Fed speak, CPI prints, auctions). Only sustained "
                     "moves are signal.",
             "why": "The curve is the most information-dense macro series but also the "
                    "noisiest day to day. Acting on transient spikes is how systematic "
                    "frameworks get chopped up."},
            {"id": "d5_bull", "kind": "auto", "field": "curve_regime", "unit": "",
             "text": "Specifically watch for rapid BULL steepening: 2-year yield falling "
                     "hard while the spread widens.",
             "why": "Steepening FROM inversion driven by the 2-year collapsing means the "
                    "market is pricing the Fed cutting into deterioration — historically "
                    "the most violent regime-shift signal there is (recession arriving). "
                    "It demands immediate reallocation review, not a note for the weekend.",
             "source": "treasury_data.curve_signal() — classifies BULL/BEAR × "
                       "STEEPENING/FLATTENING from DGS2 + DGS10 velocity, which is the "
                       "distinction this step actually asks for."},
        ],
    },
    {
        "id": "d6", "title": "Positions: stops, heat, and options mechanics", "tier": "—",
        "items": [
            {"id": "d6_stops", "kind": "auto", "field": "stop_status", "unit": "",
             "text": "Verify no stop was hit or is within 1 ATR. If a stop was hit: exit. "
                     "Full stop. Never move a stop DOWN.",
             "why": "The stop was set before entry, based on structure, when you were "
                    "objective. Moving it down converts a controlled 1% loss into an "
                    "uncontrolled one — the single most account-destructive habit in trading.",
             "source": "position_ledger.evaluate_positions() — live price vs stop in "
                       "ATR units. Stop-lowering is REFUSED by update_stop(), because a "
                       "rule enforced only by willpower is enforced exactly when you "
                       "least want it to be."},
            {"id": "d6_options", "kind": "auto", "field": "options_status", "unit": "",
             "text": "Options book: close anything at 50% of max profit. Close/roll any "
                     "short premium at 21 DTE. Close anything that has lost 2x the credit "
                     "received.",
             "why": "These three mechanical rules are what separates consistent premium "
                    "sellers from people who get gamma-crushed. Past 21 DTE, gamma risk "
                    "escalates and you lose control of the position; the last pennies are "
                    "never worth it. They execute on trigger — no thesis review, no 'one "
                    "more day.'",
             "source": "position_ledger.check_options_rules() — DTE computed "
                       "automatically. The 50%-profit and 2×-credit rules need a current "
                       "mark, which no free API provides reliably for option chains; "
                       "supply marks or check those two manually."},
            {"id": "d6_heat", "kind": "auto", "field": "heat_pct", "unit": "%",
             "text": "Confirm total portfolio heat (sum of entry-to-stop risk across open "
                     "trades) is at or under 15%.",
             "why": "Heat is the portfolio's maximum plausible drawdown from stops alone. "
                    "Above 15%, one bad correlated week does structural damage to the "
                    "compounding base.",
             "alert": {"alarm": ("gt", 15.0)},
             "source": "position_ledger — heat = Σ(entry−stop)×shares ÷ equity, this "
                       "step's own definition. Was literally not computable before."},
        ],
    },
    {
        "id": "d7", "title": "Rotation dashboard: 2-minute scan", "tier": "B",
        "items": [
            {"id": "d7_accum", "kind": "auto", "field": "rot_top_accum", "unit": "",
             "text": "Scan the top-8 rows sorted by Accumulation Score (Tier B — quiet, "
                     "sustained, directional; replaces the retired Flow Score). Separately "
                     "note anything flagged Event Score / 🔊 — that is 'something happened, "
                     "go find out what,' never 'accumulation,' regardless of magnitude.",
             "why": "Institutions cannot build size loudly. A high Accumulation Score with "
                    "a low Event Score is the closest this dashboard can get, on its own, "
                    "to real quiet accumulation. A high Event Score is the opposite "
                    "pattern — it says a session was loud, not who was on which side of it.",
             "source": "rotation_bridge.read_summary() — the Rotation app publishes a "
                       "signal summary to the shared repo; staleness is reported on every "
                       "read and a stale snapshot is never presented as current."},
            {"id": "d7_stealth", "kind": "auto", "field": "rot_stealth", "unit": "",
             "text": "Check the Stealth label. 'Strong Stealth' / 'Stealth' now requires "
                     "quiet volume (below tier threshold) as a PRECONDITION, not a point — "
                     "a loud session can never score as stealth however strong its buying "
                     "pressure. Tiers unchanged: T1 1.25x / T2 1.5x / T3 2x / T4 3x, "
                     "computed as last 5-session avg volume vs prior 20-session baseline.",
             "why": "The pre-v5 stealth signal checked four price conditions and no volume "
                    "at all, so it fired on any ordinary uptrend. Tiered thresholds exist "
                    "because a 1.5x volume day means everything in QQQ ($500M+ of extra "
                    "flow) and nothing in XBI (retail noise does that weekly). Daily you "
                    "only NOTE these; entries wait for the weekly confluence test.",
             "source": "rotation_bridge.read_summary()."},
        ],
    },
    {
        "id": "d8", "title": "Tomorrow's calendar", "tier": "—",
        "items": [
            {"id": "d8_events", "kind": "auto", "field": "event_clear", "unit": "",
             "text": "Check for CPI, FOMC, PCE, jobs, or earnings for any holding in the "
                     "next 24–48h. No NEW entries the day before a binary event for the "
                     "affected sleeve; no short premium entered into earnings with "
                     "elevated IVR.",
             "why": "Event days gap through stops and crush IV. Entering the day before "
                    "surrenders your risk control (the stop) and your edge (IV rank) "
                    "simultaneously. Existing positions with proper stops are fine — the "
                    "rule is about NEW risk.",
             "source": "event_calendar.event_check() — FOMC/CPI/PCE/NFP dates are "
                       "scheduled and hardcoded (re-verify each January); per-holding "
                       "earnings come from yfinance and are ADVISORY, not authoritative."},
        ],
    },
]

DAILY_ACTION_RULE = (
    "The only trades authorized from the daily checklist are (1) the HY crisis "
    "override, (2) a stop-loss execution, (3) the three mechanical options rules. "
    "Everything else — including the Step 4 dollar/auction read — however tempting, "
    "is written down and waits for the weekly review. If you feel urgency and none of "
    "the three triggers has fired, the urgency is the emotion, not the signal."
)


# ─────────────────────────────────────────────────────────────────────────────
#  WEEKLY
# ─────────────────────────────────────────────────────────────────────────────

WEEKLY_STEPS = [
    {
        "id": "w1", "title": "Run the classifier (Level 1)", "tier": "—",
        "items": [
            {"id": "w1_regime", "kind": "auto", "field": "regime_key", "unit": "",
             "text": "Record the regime key exactly as classify_regime() names it — "
                     "inflationary_repression, hard_repression, liquidity_crisis, "
                     "stagflation, goldilocks, or neutral — with its drivers list.",
             "why": "The regime is the root of every allocation decision; everything "
                    "downstream inherits its errors."},
            {"id": "w1_fedflag", "kind": "auto", "field": "fed_flag", "unit": "",
             "text": "Record the fed_reaction_flag() state SEPARATELY (SOFT repression / "
                     "HARD repression / Not repressive). Soft/hard is the Fed's reaction "
                     "function, not a suffix on the regime key; there is no key that "
                     "combines them.",
             "why": "The two outputs answer different questions — what regime the data "
                    "describes vs how the Fed is likely to respond — and can point in "
                    "different directions at once (as they did on July 20, 2026: key = "
                    "goldilocks, flag = still SOFT repression). Merging them into one "
                    "label loses exactly the contradiction most worth seeing."},
            {"id": "w1_score", "kind": "auto", "field": "repression_score", "unit": "/10",
             "text": "Record the repression score with its missing[] list — an incomplete "
                     "5 and a true 5 are different states; say which you have.",
             "why": "The two manual flags (fed_bs_expanding, deficit_gt_5pct_gdp) exist "
                    "because the classifier cannot self-fetch them."},
            {"id": "w1_degraded", "kind": "auto", "field": "degraded", "unit": "",
             "text": "Check the drivers list for the degraded-data warning "
                     "('DFII10 momentum unavailable').",
             "why": "v2 surfaces missing data instead of silently classifying around it. "
                    "A regime read on missing duration momentum is a coin flip on the TLT "
                    "sleeve — fix the data before trusting the output."},
            {"id": "w1_transition", "kind": "auto", "field": "regime_changed", "unit": "",
             "text": "Compare regime vs LAST week's log. If changed: this is a rebalance "
                     "event — the new regime must hold TWO consecutive daily closes before "
                     "executing the overlay shift, and execution is cuts first, hedges "
                     "second, adds last, over 2–5 sessions on limits.",
             "why": "Regime transitions are the highest-value moments the system produces "
                    "(overlays move 10–24 points). But a regime can also stay nominally "
                    "the same while its drivers rotate underneath — same label, weakening "
                    "conviction — which is your early warning."},
        ],
    },
    {
        "id": "w2", "title": "The two real yields (never conflate them)", "tier": "—",
        "items": [
            {"id": "w2_short", "kind": "auto", "field": "short_real_rate", "unit": "%",
             "text": "Recompute the SHORT real policy rate = EFFR minus CPI YoY. Note "
                     "distance from zero.",
             "why": "This is the repression gauge — the Fed's real stance. Negative means "
                    "inflation is eroding debt (and cash). Its ZERO CROSSING is the single "
                    "trigger for trimming the core metals sleeve (GLD 12%). It only moves "
                    "on CPI prints and Fed action, so weekly is the right cadence."},
            {"id": "w2_cpi_check", "kind": "auto", "field": "cpi_crosscheck", "unit": "",
             "text": "CROSS-CHECK the computed CPI YoY against BLS's own published "
                     "headline figure (the number in the BLS press release) before trusting "
                     "it — especially in any month where a prior month's data was delayed, "
                     "revised, or cancelled.",
             "why": "A calendar-misalignment bug went undetected from November 2025 to "
                    "July 2026 — eight months — because nothing cross-checked the computed "
                    "figure against what BLS actually published. BLS cancelled the October "
                    "2025 release (shutdown); combined with a positional pct_change(12), "
                    "every month silently compared against a base one month too early. "
                    "Fixed at source, but a different future gap could reintroduce the same "
                    "class of error somewhere the fix doesn't cover. Five seconds against a "
                    "headline would have caught it in month one.",
             "source": "bls_client.cross_check() — pulls CUUR0000SA0 (the headline NSA "
                       "series) with BLS's OWN 12-month calculation, so nothing is "
                       "recomputed locally and the check cannot reproduce the class of "
                       "bug it exists to catch. Fires on any gap beyond 0.15pp."},
            {"id": "w2_dfii_mom", "kind": "auto", "field": "long_real_mom_3m", "unit": "pp",
             "text": "Record DFII10 3-month momentum SIGN from the classifier output.",
             "why": "This one sign is the TLT gate (positive = TLT 0%, it bleeds), the "
                    "growth-trim justification, and the soft-vs-hard repression "
                    "discriminator. If it has flipped negative while credit stays calm, "
                    "the classifier will name it hard_repression — metals max, TLT re-arms "
                    "at 12% — instead of going silent like v1 did."},
        ],
    },
    {
        "id": "w3", "title": "The gold momentum gate (Level 4)", "tier": "C",
        "items": [
            {"id": "w3_gate", "kind": "auto", "field": "gold_gate", "unit": "",
             "text": "Check the gate: is GLD above a RISING 200-day MA? Record PASS/FAIL "
                     "and compare to last week.",
             "why": "The regime says own real assets; the gate decides WHICH ones get the "
                    "tactical add. Rising long real yields — the regime's own defining "
                    "signal — are gold's primary headwind, so the +3 tilt must never fire "
                    "into a confirmed downtrend. Gate FAIL: the 3 points sit in SGOV. Gate "
                    "flips PASS: GLD 12 to 15, funded from SGOV — that flip IS the "
                    "Lagging-to-Improving hook, mechanically detected.\n\n"
                    "NAMING NOTE: this gate (GLD above a rising 200d MA, in "
                    "regime_classifier.py) governs position sizing. It is DISTINCT from "
                    "the Repression Dashboard's gold repression-confirmation gate "
                    "(indicators.py), which requires a fundamental condition (real yield "
                    "<1.5% + rising breakevens) plus a 50d/200d crossover. They can "
                    "disagree by design — if they do, THIS gate governs the model "
                    "portfolio; the other is scorecard context only."},
            {"id": "w3_rrg", "kind": "auto", "field": "rot_gold_rrg", "unit": "",
             "text": "Cross-check with the weekly RRG: is gold/miners showing the hook "
                     "(RS-momentum crossing up from Lagging)?",
             "why": "Two independent confirmations (trend gate + RRG hook) turn a "
                    "mechanical signal into a high-conviction one. If they disagree, the "
                    "gate governs the model portfolio; the RRG governs any discretionary "
                    "add beyond it.",
             "source": "rotation_bridge.read_summary()."},
        ],
    },
    {
        "id": "w4", "title": "KMLM sizing signal", "tier": "—",
        "items": [
            {"id": "w4_signal", "kind": "auto", "field": "kmlm_stance", "unit": "",
             "text": "Record the kmlm_signal() output: 60-day stock/bond correlation, "
                     "score, and stance. INCREASE requires score 3+ (correlation above "
                     "+0.20 is worth 2 of it).",
             "why": "KMLM exists because the bond hedge fails exactly when inflation "
                    "drives the crash — stocks and bonds fall together (2022). Positive "
                    "stock/bond correlation is the direct measurement that 60/40 "
                    "diversification is broken and trend must carry the hedge role. "
                    "Funding order matters: SGOV first (it bleeds in real terms), then "
                    "SMH/QQQ — NEVER metals or energy in a repression regime, because you "
                    "would be selling the assets the regime favors to buy the hedge."},
            {"id": "w4_conflict", "kind": "auto", "field": "kmlm_conflict", "unit": "",
             "text": "If kmlm_signal()'s live stance DISAGREES with the regime overlay's "
                     "target weight for KMLM, the SLOWER-MOVING of the two governs until "
                     "they converge. Log the disagreement explicitly rather than silently "
                     "picking one.",
             "why": "The overlay is a mechanical consequence of the regime label; "
                    "kmlm_signal() is a live measurement of the thing the overlay assumes. "
                    "On a fresh or border-case transition these can genuinely conflict (as "
                    "on July 20, 2026: goldilocks overlay said cut KMLM to 2%, live signal "
                    "still read HOLD on a positive long-real tailwind). Executing the "
                    "faster instruction risks cutting a hedge the data hasn't stopped "
                    "confirming."},
        ],
    },
    {
        "id": "w5", "title": "Weekly RRG review (Level 2, Tier C)", "tier": "C",
        "items": [
            {"id": "w5_quadrants", "kind": "auto", "field": "rot_quadrants", "unit": "",
             "text": "For every sector ETF: record quadrant, rotation direction, and "
                     "momentum acceleration vs the ±0.8% threshold — the metric labeled "
                     "'spread' in the dashboard. It is momentum acceleration (1M vs the 3M "
                     "run-rate), NOT accumulation: it contains no volume and no money, and "
                     "is Tier C regardless of its name in the UI.",
             "why": "Weekly is the PRIMARY RRG timeframe — daily is entry timing only, "
                    "monthly is context. The Improving quadrant is the entry zone because "
                    "RS is still below market while momentum inflects: you are early, "
                    "before the crowd. Leading is hold-only (easy money made); Weakening "
                    "is distribution — trim.",
             "source": "rotation_bridge.read_summary()."},
            {"id": "w5_counterclock", "kind": "manual_bool",
             "text": "Flag any COUNTER-CLOCKWISE movement (e.g., Improving falling "
                     "straight back to Lagging).",
             "why": "Normal rotation is clockwise. Counter-clockwise is a failed rotation "
                    "/ trend reversal — the earliest structural warning the RRG produces, "
                    "and it voids any pending entry in that sector.",
             "source": "rotation_bridge. NOTE: the RRG's rotation-direction arrows are "
                       "synthesized from the same snapshot's shorter timeframes, not an "
                       "observed multi-week trajectory — treat as proxy, not track record."},
            {"id": "w5_confluence", "kind": "manual_text",
             "text": "CONFLUENCE TEST — now requires a Tier-A leg. (1) Tier C: Improving "
                     "quadrant or Lagging hook on weekly. (2) Tier B: CMF positive and "
                     "rising 4+ weeks, or A/D making higher lows while price consolidates. "
                     "(3) Tier A: net positive ETF creations over 4 weeks, OR supportive "
                     "COT Asset Manager positioning. FULL SIZE requires 3 of 3 INCLUDING "
                     "Tier A. Two of three including Tier B = half size. Tier C alone — "
                     "however clean — is watchlist only.",
             "why": "Each tier fails differently: price can be a one-week squeeze, "
                    "pressure can be a single strong session in a name that goes nowhere, "
                    "and money is the one the other two cannot fake — creations require an "
                    "Authorized Participant transacting real size with the issuer. "
                    "Requiring all three is what turns a chart pattern into a position.\n\n"
                    "PROVENANCE: a leg with no supplied evidence scores NOT MET, full "
                    "stop — never 'probably fine.' Tier-C-only caps at watchlist; C+B "
                    "without A caps at half size."},
        ],
    },
    {
        "id": "w5b", "title": "Flow review (Level 2, Tier A)", "tier": "A",
        "items": [
            {"id": "w5b_creations", "kind": "auto", "field": "rot_flow_div", "unit": "",
             "text": "Record 1-week and 4-week net ETF creations/redemptions for each "
                     "sleeve holding and each candidate. FLAG every case where price "
                     "direction and flow direction disagree — a sector rising on net "
                     "redemptions is distribution into strength, invisible to every other "
                     "signal in this checklist.",
             "why": "Shares are created only when an Authorized Participant transacts "
                    "directly with the issuer in blocks (typically 25,000+ shares) — "
                    "ordinary secondary-market trading moves price and prints volume but "
                    "creates nothing. A change in shares outstanding is, by construction, "
                    "evidence of real net demand at institutional scale.",
             "source": "rotation_bridge flow divergences, fed by the daily "
                       "shares-outstanding poll (now a scheduled GitHub Action writing to "
                       "the repo, so history survives redeploys). Needs ~20 sessions "
                       "before readings are usable; coverage is reported."},
            {"id": "w5b_cot", "kind": "auto", "field": "rot_cot", "unit": "",
             "text": "Record CFTC COT positioning — Asset Manager and Leveraged Fund net, "
                     "as PERCENTILE RANK vs 3-year history — for gold, WTI, 10Y/30Y "
                     "Treasuries, E-mini S&P, DXY. Flag beyond the 90th or below the 10th "
                     "percentile, and any wide cohort divergence.",
             "why": "Positioning extremes are where regime calls get their asymmetry — "
                    "Asset Managers at a 3-year low in gold with the repression thesis "
                    "intact is a very different setup from the same chart at a 3-year "
                    "positioning high. The cohorts move differently on purpose: Leveraged "
                    "Funds are fast and mean-reverting, Asset Managers slow and "
                    "trend-persistent; the faster side is usually the one that has to "
                    "unwind. COT is Tuesday-dated, published Friday — a 3-day-stale "
                    "snapshot, NEVER an entry trigger.",
             "source": "rotation_bridge COT table. rotation_bridge.cot_status() reports "
                       "whether the producer verified the CFTC schema — unverified "
                       "positioning data is flagged rather than silently trusted."},
        ],
    },
    {
        "id": "w5c", "title": "Constituent breadth check (Level 2/3, Tier B/C)", "tier": "B",
        "items": [
            {"id": "w5c_breadth", "kind": "auto", "field": "rot_breadth", "unit": "",
             "text": "For any sector showing a strong Accumulation Score or a Step 5 "
                     "confluence pass, check the breadth verdict: BROAD (widespread "
                     "participation — signal is real), CONCENTRATED (a handful of "
                     "mega-caps driving the whole reading), or NARROW (few names, high "
                     "dispersion — a stock-picker's tape).",
             "why": "A cap-weighted sector ETF can be one stock wearing a sector's "
                    "clothes. XLK's top 10 run roughly 61% of the fund, with the top 3 "
                    "commonly a third of it — 'technology is accumulating' can mean "
                    "nothing more than one chip name is. Acting on a CONCENTRATED reading "
                    "as a diversified sector position takes single-stock risk while "
                    "believing you hold something broader.",
             "source": "rotation_bridge.read_summary()."},
            {"id": "w5c_action", "kind": "manual_bool",
             "text": "If CONCENTRATED: either express the view in the specific names, or "
                     "size the sector position as if it carries single-stock concentration "
                     "risk — do not size it as a diversified sleeve.",
             "why": "This is the difference between a sector bet and a disguised "
                    "single-stock bet at sector size."},
        ],
    },
    {
        "id": "w6", "title": "Valuation filter (Level 3)", "tier": "—",
        "items": [
            {"id": "w6_route", "kind": "auto", "field": "valuation_summary", "unit": "",
             "text": "ROUTE BY TICKER FIRST. Portfolio-sleeve tickers use the Portfolio "
                     "app's get_pe(). Rotation-universe sector candidates use "
                     "rot_valuation.py. For either: verify the stale flag — if "
                     "source='fallback'/'snapshot' and stale=True (>45 days), the multiple "
                     "is fiction after a fast move; use it qualitatively, never for sizing. "
                     "Where a ticker exists in both (XLE, XLV, XLU), the Portfolio app's "
                     "live number governs.",
             "why": "Absolute P/E across sectors is meaningless (tech at 35x vs utilities "
                    "at 17x is structural). Only deviation from a sector's own history "
                    "carries signal. The stale flag exists because after a move like the "
                    "H1-2026 semi run, a 45-day-old multiple is fiction — and a Level-3 "
                    "verdict on fiction propagates to sizing."},
            {"id": "w6_matrix", "kind": "manual_text",
             "text": "Locate each position on the matrix: cheap + Improving = highest "
                     "conviction; expensive + Weakening = avoid/exit; cheap + Lagging with "
                     "no hook = value trap, do nothing.",
             "why": "Value without momentum stays cheap longer than you can stay patient; "
                    "momentum without value is late-cycle chasing. The sweet spot needs both."},
        ],
    },
    {
        "id": "w7", "title": "Position-level review (Levels 6–7)", "tier": "—",
        "items": [
            {"id": "w7_stops", "kind": "auto", "field": "stop_status", "unit": "",
             "text": "For every open position: re-derive stop validity (structure "
                     "unchanged?), trail stops UP where the trade has worked, recount "
                     "shares-at-risk, re-sum portfolio heat.",
             "why": "Stops trail up, never down. Weekly is when trailing happens — moving "
                    "a stop up under a new higher swing low locks progress without choking "
                    "the trend.",
             "source": "position_ledger.evaluate_positions()."},
            {"id": "w7_invalidation", "kind": "manual_text",
             "text": "For every position, write one sentence: 'This position is "
                     "invalidated when ______.' If you cannot fill the blank, the position "
                     "has no thesis — exit it.",
             "why": "A position without a pre-stated invalidation condition can never be "
                    "wrong, which means it can never be managed. This sentence is the "
                    "difference between a system and a collection of opinions."},
        ],
    },
    {
        "id": "w8", "title": "Drift bands and rebalancing", "tier": "—",
        "items": [
            {"id": "w8_drift", "kind": "auto", "field": "drift_summary", "unit": "",
             "text": "Compare live weights vs the regime targets (target_weights output). "
                     "Flag any sleeve more than 20% RELATIVE drift from target (e.g., a 10% "
                     "target is out of band below 8% or above 12%).",
             "why": "Band-based rebalancing beats calendar rebalancing: it trades only "
                    "when positions have actually moved (harvesting the divergence) and "
                    "stays quiet otherwise, cutting costs and whipsaw.",
             "source": "position_ledger.drift_vs_targets() — computed from ACTUAL "
                       "market value when the ledger has positions. Falls back to slider "
                       "weights only if it is empty, which answers the weaker question "
                       "'does my intended allocation match' (drift zero by construction)."},
            {"id": "w8_trigger", "kind": "manual_bool",
             "text": "Rebalance ONLY on: (a) a regime transition, (b) a band breach, "
                     "(c) a gate flip (gold gate, KMLM stance, TLT re-arm). Never on a "
                     "calendar date, never on a feeling.",
             "why": "Three named triggers make every rebalance auditable. If none fired "
                    "and you still want to trade, that is the emotion talking — log it and "
                    "revisit next week."},
        ],
    },
    {
        "id": "w9", "title": "Stress test and journal", "tier": "—",
        "items": [
            {"id": "w9_stress", "kind": "manual_bool",
             "text": "Run the stress tab on CURRENT weights for at least 2022 Rate Hike "
                     "and 2008 GFC. Where the regime's closest analogue calls for it, also "
                     "run 2000 Dot-Com and/or 1973 Stagflation (1973 = directional context "
                     "only; its pre-1997 real-yield inputs are ex-post constructs and most "
                     "single-stock returns are approximated). A 60/40 benchmark row is now "
                     "available alongside raw S&P 500.",
             "why": "The TLT=0 posture is a conscious asymmetry, not an oversight — it "
                    "must be re-confirmed weekly against the crisis-override tripwire (HY "
                    "OAS) that re-arms duration. If drift has silently changed the stress "
                    "profile, Step 8 missed something."},
            {"id": "w9_mind", "kind": "manual_text",
             "text": "Log what would change your mind by next week — the single data "
                     "point that, if it moved, would flip the current call.",
             "why": "The journal is the system's memory and its audit trail. Six months of "
                    "logs is the only honest way to evaluate whether the framework — or "
                    "your adherence to it — is the weak link. Naming the falsifier in "
                    "advance is what makes the next review an evaluation rather than a "
                    "rationalization."},
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def all_steps(cadence: str) -> list:
    return DAILY_STEPS if cadence == "daily" else WEEKLY_STEPS


def all_items(cadence: str) -> list:
    return [it for st in all_steps(cadence) for it in st["items"]]


def gap_report() -> dict:
    """
    Machine-readable gap analysis: which checklist items have no data source.

    This is the answer to 'where does the automation stop' — computed from the
    checklist itself rather than maintained separately, so it cannot drift.
    """
    out = {}
    for cadence in ("daily", "weekly"):
        items = all_items(cadence)
        auto = [i for i in items if i["kind"] == "auto"]
        manual = [i for i in items if i["kind"].startswith("manual")]
        gapped = [i for i in items if i.get("gap")]
        out[cadence] = {
            "total": len(items),
            "auto": len(auto),
            "manual": len(manual),
            "auto_pct": round(100 * len(auto) / len(items), 1) if items else 0,
            "documented_gaps": [{"id": i["id"], "gap": i["gap"]} for i in gapped],
        }
    return out


def render_markdown() -> str:
    """
    Regenerate the human-readable checklist FROM this data structure.

    This is why the content lives here as data: the markdown document and the
    app's interactive widgets are two renderings of ONE source, so they cannot
    disagree. Per v5 Part 5, duplicated documentation is a liability.
    """
    L = ["# Dashboard Analysis Checklist — v5", ""]
    for cadence, steps, title in (("daily", DAILY_STEPS, "PART 1 — DAILY CHECKLIST"),
                                  ("weekly", WEEKLY_STEPS, "PART 2 — WEEKLY CHECKLIST")):
        L += [f"## {title}", ""]
        for st in steps:
            tier = f"  `Tier {st['tier']}`" if st["tier"] != "—" else ""
            L += [f"**{st['id'].upper()} — {st['title']}**{tier}", ""]
            for it in st["items"]:
                L.append(f"- [ ] {it['text']}")
                L.append(f"  *Why:* {it['why']}")
                if it.get("gap"):
                    L.append(f"  *⚠ Data gap:* {it['gap']}")
            L.append("")
        if cadence == "daily":
            L += [f"**DAILY ACTION RULE:** {DAILY_ACTION_RULE}", ""]
    return "\n".join(L)
