3# BetVector — Claude Code Session Rules

These rules apply to every session, every issue, without exception.
Do not deviate from them unless explicitly told to in the chat.

## Reference Documents

| Shorthand | Full Name | File |
|-----------|-----------|------|
| MP | Master Plan | `betvector_masterplan.md` |
| BP | Build Plan | `betvector_buildplan.md` |

When an issue says "MP §6" — open `betvector_masterplan.md` and find
Section 6. Never assume you know what the document says. Read it.

---

## Rule 1 — Read Before You Code

Every issue in the build plan lists master plan section refs.
Read those sections BEFORE writing a single line of code.

The documents contain exact field names, enum values, component structures,
and constraints that are NOT repeated in the issue description.
Skipping them causes drift and rework.

---

## Rule 2 — Stack. No Substitutions.

**Language:** Python 3.10+. Not 3.8. Not 3.9.

**Database ORM:** SQLAlchemy 2.0+ (new-style API with `DeclarativeBase`). Not raw SQL. Not Peewee. Not Django ORM.

**Database:** SQLite for MVP. Connection string from `config/settings.yaml`, never hardcoded. WAL mode enabled. When the owner migrates to PostgreSQL, only the connection string changes — no code changes.

**Data manipulation:** pandas 2.0+ and numpy. Not polars. Not raw Python loops over data.

**Stats/ML:** scipy for Poisson distribution, statsmodels for Poisson regression, scikit-learn for calibration and evaluation, xgboost/lightgbm for future models. Not PyTorch. Not TensorFlow.

**Scraping:** requests + BeautifulSoup for custom scraping, soccerdata for FBref. Not Selenium. Not Playwright. Not scrapy.

**Dashboard:** Streamlit 1.28+. Not Flask. Not Django. Not FastAPI. Not React.

**Charts:** Plotly for all interactive charts (dashboard and email). matplotlib only for static exports (backtest PNGs). Not seaborn for dashboard charts.

**Config:** PyYAML. All tuneable values in `config/*.yaml`. Not JSON. Not TOML. Not .ini.

**Email:** Python smtplib + email.mime + Jinja2 templates. Not SendGrid. Not Mailgun.

**Templates:** Jinja2 for email HTML. Not Mako. Not Django templates.

**Environment variables live in `.env`:**
- `GMAIL_APP_PASSWORD` — Gmail App Password for sending emails
- `DASHBOARD_PASSWORD` — Simple password gate for Streamlit dashboard
- `API_FOOTBALL_KEY` — RapidAPI key for API-Football (free tier)

Never hardcode credentials. Never commit `.env`. Never print credentials to logs.

---

## Rule 3 — One Issue at a Time, Sequential Advancement

Work one issue at a time, in critical-path order. Never skip ahead.
When all three gates pass (Rule 4), auto-advance to the next issue
immediately — no waiting for owner approval.

Critical path:
```
E1-01 → E1-02 → E1-03 → E2-01 → E2-02 → E2-03 → E2-04 →
E3-01 → E3-02 → E3-03 → E3-04 → E4-01 → E4-02 → E4-03 →
E5-01 → E5-02 → E5-03 → E6-01 → E6-02 → E6-03 →
E7-01 → E7-02 → E7-03 → E8-01 → E8-02 →
E9-01 → E9-02 → E9-03 → E9-04 → E9-05 →
E10-01 → E10-02 → E10-03 → E10-04 →
E11-01 → E11-02 → E11-03 →
E12-01 → E12-02 → E12-03 → E12-04 → E12-05 →
E13-01 → E13-02 → E13-03 →
E14-01 → E14-02 → E14-03 → E14-04 →
E15-01 → E15-02 → E15-03 →
E16-01 → E16-02 → E16-03 →
E17-01 → E17-02 → E17-03 → E17-04 →
E18-01 → ... → E18-06 →
E19-01 → E19-02 → E19-03 → E19-04 →
E20-01 → E20-02 → E20-03 →
E21-01 → E21-02 → E21-03 →
E22-01 → E22-02 →
E23-01 → E23-02 → E23-03 → E23-04 → E23-05 → E23-06 → E23-07 →
E24-01 → E24-02 → E24-03 → E24-04 → E24-05 →
E25-01 → E25-02 → E25-03 → E25-04 →
E26-01 → E26-02 → E26-03 → E26-04 →
E27-01 → E27-02 → E27-03 → E27-04 →
E28-01 → E28-02 → E28-03 → E28-04 →
E29-01 → E29-02 → E29-03 → E29-04 →
E30-01 → E30-02 → E30-03 →
E31-01 → E31-02 → E31-03 → E31-04 →
E32-01 → E32-02 → E32-03 → E32-04 → E32-05 →
E33-01 → E33-02 → E33-03 → E33-04 → E33-05 → E33-06 →
E34-01 → E34-02 → E34-03 → E34-04 → E34-05 → E34-06 →
E35-01 → E35-02 → E35-03 →
E35-04 → E35-05 → E35-06 → E35-07 →
E36-01 → E36-02 → E36-03 → E36-04 →
E37-01 → E37-02 → E37-03 → E37-04 →
E38-01 → E38-02 → E38-03 → E38-04 → E38-05 → E38-06 →
E40-01 → E40-02 → E40-03 → E40-04 → E40-05 →
E40-06 → E40-07 → E40-08 → E40-09 → E40-10 →
PC-26-01 → PC-26-02 → PC-26-03 → PC-26-04 → PC-26-05 →
PC-26-06 → PC-26-07 → PC-26-08 → PC-26-09 →
PC-26-10 → PC-26-11 → PC-26-12 → PC-26-13 →
PC-26-14 → PC-26-15 → PC-26-16 → PC-26-17
```

The sequence is the law. Auto-advance after gates pass. Only stop for
blockers (Rule 4) or critical path completion.

---

## Rule 4 — Three-Gate Autonomous Review

Before an issue can be marked complete and auto-advanced (Rule 3),
it must pass all three gates sequentially. If any gate fails, fix and
re-run that gate. If the same gate fails twice, stop and report to the owner.

### Gate 1 — Acceptance Criteria Verification (Self)

Go through every acceptance criteria item one by one and confirm it passes.

Report format:
`[PASS]` [criteria text] — [how you verified it]
`[FAIL]` [criteria text] — [what's failing and why]

All items must be `[PASS]` to advance to Gate 2. If any `[FAIL]`, fix
the issue and re-run Gate 1.

### Gate 2 — Masterplan Cross-Reference Audit (Dispatched Agent)

Launch a separate agent to audit the completed work against the Master Plan
sections referenced by the issue. The agent reads the MP sections, reads the
code that was written, and checks for:
- Wrong field names, missing enum values, architectural violations
- Constraint mismatches, component structure drift
- Any deviation from what the MP specifies

Report format:
`[CLEAN]` — No drift detected between code and Master Plan.
`[GAP]` — [specific drift found, with MP section reference and code location]

Must be `[CLEAN]` to advance to Gate 3. If `[GAP]`, fix the gaps and re-run.

### Gate 3 — Code Review (Dispatched Agent)

Launch a separate agent to review all code changes for production quality.
The agent checks for:
- Error handling and edge cases
- Idempotency and temporal integrity
- No hardcoded values, no TODOs left in code
- Proper comments explaining betting concepts
- Design system compliance (Rule 5)
- All standing technical constraints (Rule 6)

Report format:
`[APPROVED]` — Code meets production quality standards.
`[ISSUE]` — [specific problem, file, and line reference]

Must be `[APPROVED]` to pass. If `[ISSUE]`, fix and re-run Gate 3.

### Blocker Detection

The following require stopping and asking the owner because they cannot
be resolved autonomously:
- API keys, tokens, or credentials not yet provisioned
- Account creation or third-party service registration
- DNS configuration or domain setup
- OAuth or external authentication setup
- Anything requiring payment or subscription changes
- External service configuration outside the codebase

When a blocker is detected: stop, report the blocker clearly, and wait
for the owner to resolve it before continuing.

---

## Rule 5 — Production Quality. No Exceptions.

This is a launch-grade product, not a prototype. Every issue is built to
production standard — full stop.

- Handle all edge cases and errors gracefully — scrapers that fail mid-run must not crash the pipeline
- Every function that touches the database must handle connection errors and retry once
- Add generous code comments explaining betting concepts as they appear (the owner is learning — see MP §12 Glossary for definitions)
- Empty states, loading skeletons, and error states on every dashboard page
- Zero hackathon shortcuts, zero TODOs left in code, zero hardcoded values
- Dashboard matches the design system exactly: background `#0D1117`, surface `#161B22`, text `#E6EDF3`, green `#3FB950`, red `#F85149`, JetBrains Mono for data, Inter for text
- Temporal integrity is sacred: no feature, no prediction, no training step ever uses data from the future

You are the technical co-founder on this project. Own it.

---

## Rule 6 — Standing Technical Constraints

These apply to every issue without needing to be restated:

- **Temporal integrity:** This is the #1 constraint. Every feature calculation, every model training step, every backtest iteration must use ONLY data from before the prediction date. Leaking future data invalidates the entire system. If unsure whether a data access is temporally safe, it isn't. Add explicit date filters.

- **Config-driven everything:** Leagues, seasons, feature windows, edge thresholds, staking parameters, safety limits, self-improvement thresholds, email schedules — all come from `config/*.yaml` or the `users` table. Never hardcode these values. If a value might change, it belongs in config.

- **Database is the single source of truth:** All modules read from and write to the database. No passing DataFrames between modules via function arguments across pipeline steps. Scraper writes to DB → Feature engineer reads from DB → Model reads from DB. This keeps modules independent and replaceable.

- **Scoreline matrix is the universal model interface:** Every prediction model outputs a 7×7 scoreline probability matrix (MP §5). All market probabilities are derived from this matrix via `derive_market_probabilities()`. Never derive market probabilities any other way. Never bypass the matrix.

- **Dual bet tracking:** Every value bet is auto-logged as a `system_pick` in `bet_log`. User-placed bets are separate entries with `bet_type='user_placed'`. Never skip the system_pick logging — it's how we measure model performance independently of human decisions.

- **user_id on everything personal:** bet_log, bankroll data, and notification preferences are always scoped to a `user_id`. Even when there's only one user. This is a 5-minute decision now that prevents a multi-day refactor later.

- **Self-improvement guardrails:** Every automatic adjustment (recalibration, weight changes, retrain triggers) has a minimum sample size, maximum change rate, and rollback mechanism defined in MP §11. Never skip these guardrails. An overconfident self-improvement system is worse than no self-improvement at all.

- **Rate limiting on all HTTP requests:** Minimum 2 seconds between requests to the same domain. API-Football has a 100 requests/day limit on the free tier — track and respect it. Football-Data.co.uk and FBref are free public resources — don't abuse them.

- **Idempotent operations:** Running any scraper, loader, or feature calculator twice with the same inputs must not create duplicate records. Use INSERT OR IGNORE, session.merge(), or explicit duplicate checks.

- **Pipeline resilience:** If one step in the pipeline fails (e.g., FBref is down), log the error and continue to the next step. Never let a single scraper failure prevent predictions from being made with available data. Never let an email failure prevent results from being recorded.

---

## Rule 7 — Advance and Report

When all three gates pass (Rule 4), execute this sequence immediately:

1. **Update `CLAUDE.md` status:**
   - Move the completed issue to "Last completed"
   - Set "Currently working" to the next issue
   - Set "Next up" to the issue after that

2. **Update `betvector_buildplan.md`:**
   - Mark the issue as DONE with results/metrics

3. **Deploy tracker:**
   - Commit and push changes so the owner can see progress remotely

4. **Post completion report** in this format:
   ```
   ══════════════════════════════════════
   ✅ ISSUE [ID] — [Title] — COMPLETE
   ══════════════════════════════════════
   Gate 1 (AC):        [PASS] — [count] / [count] items verified
   Gate 2 (Masterplan): [CLEAN] or [GAP] — [summary]
   Gate 3 (Code Review): [APPROVED] or [ISSUE] — [summary]
   Key Metrics:        [relevant stats]
   Next:               [next issue ID] — [title]
   ══════════════════════════════════════
   ```

5. **Advance immediately** — begin the next issue without waiting.

### When to stop

Only stop advancing for:
- **Unfixable gate failure** — same gate failed twice after fix attempts
- **Blocker needing owner action** — from the Blocker Detection list (Rule 4)
- **Critical path complete** — no more issues in the sequence

---

## Rule 8 — Masterplan Update Protocol

The Master Plan (`betvector_masterplan.md`) is the single source of
architectural truth. It must stay in sync with the codebase. Updates are
handled in two tiers based on scope:

### Tier 1 — Auto-Update (No Approval Needed)

After closing an epic (all issues in an E-series marked DONE), automatically:
1. Add or update the §13.x subsection for that epic
2. Update the §5 data source table if new sources were added
3. Update the §6 schema if new tables or columns were added
4. Bump the version patch number (e.g., 1.2 → 1.3)
5. Update the Model Performance Evolution table if Brier/ROI changed

These are factual updates documenting what was already built and approved
through the three-gate process. They don't change the plan — they record
what happened.

### Tier 2 — Proposal Required (Owner Must Approve)

Any change that alters the *future direction* of the project requires
explicit owner approval before writing to the Master Plan:

- Adding new epics or issues to the critical path
- Changing the tech stack (Rule 2)
- Modifying architectural constraints (§3, §4, §5 core sections)
- Adding new data sources not yet discussed
- Changing model architecture (e.g., adding XGBoost ensemble)
- Revising success criteria (§1) or the product vision
- Adding new external service dependencies or costs

**Proposal format:**

```
══════════════════════════════════════
📋 MASTERPLAN UPDATE PROPOSAL
══════════════════════════════════════
Section(s):     [which MP sections would change]
Type:           [new epic / architecture change / stack change / etc.]
Summary:        [1-2 sentence description]
Rationale:      [why this change is needed]
Impact:         [what existing code/plans it affects]
Cost:           [$0 / $X per month / one-time $X]
══════════════════════════════════════
```

Wait for owner to respond with approval before making the change.

---

## Rule 9 — No Inline Multi-Line Python

Never use `python -c "..."` with multi-line code, and never use
`cat > file << 'HEREDOC'` in Bash either. The permission allow-list
wildcard `*` does not match across newlines, so both patterns always
trigger a manual permission prompt — blocking autonomous advancement.

Instead, use the **Write tool** to create the script, then run it
with a single-line Bash command:

```
# ✅ Do this — zero permission prompts
Step 1: Write tool → creates /tmp/bv_check.py
Step 2: Bash → python /tmp/bv_check.py   (matches "Bash(python *)")

# ❌ Never this — cat heredoc triggers prompt (newlines break glob)
cat > /tmp/bv_check.py << 'PYEOF'
import os
print("hello")
PYEOF
python /tmp/bv_check.py

# ❌ Never this — python -c triggers prompt (same newline issue)
python -c "
import os
print('hello')
"
```

This applies to all ad-hoc Python: DB checks, data queries, one-off
scripts, migration commands — anything that would be more than a
single-line expression.

---

## Current Status

Last completed: WC-10-02 ✅ — Daily morning automation INSTALLED + LIVE. com.betvector.wc_morning loaded, fires 09:30 ET (Mac is EDT); evening plist RETIRED. Morning run absorbed the evening's CLV-capture + accuracy steps and folds yesterday's results into the morning email (owner option 1). Verified end-to-end via run_wc_pipeline.sh morning: exit 0, 80.4s, CLV captured 4, accuracy 15 matches, 2-credit odds, 40 preds + 40 Bayesian + 51 value bets, email sent. 6 tests, 725/725. → WC-10 PHASE 1 COMPLETE (the system now runs itself).
Also done: WC-10-03 ✅ — pre-kickoff heartbeat dispatcher. src/world_cup/dispatcher.py: morning run writes data/world_cup/today_fixtures.json (gitignored); a 15-min launchd job (com.betvector.wc_dispatcher.plist + run_wc_dispatcher.sh, NOT installed yet) reads the LOCAL cache (idle = NO Neon connection), fires run_prematch once per match in [KO-40min, KO), persists prepped-state (auto daily reset). run_prematch is a PLACEHOLDER until 10-04. Verified on 25 real fixtures. 8 tests, 733/733. WC-10-01 prior: split-brain footgun fix + odds 12→2 credits.
Phase 2 (10-03/04/05) ✅ + dispatcher INSTALLED + LIVE: com.betvector.wc_dispatcher loaded (every 15 min). 10-04 focused per-event prematch pull (scrape_wc_match_odds: FREE /events → 1 paid /events/{id}/odds = 2 credits, ONLY target match — protects in-play CLV). 10-05 CLV integrity (close=latest upsert=near-closing; CLV was 0 until the dispatcher went live).
Also done: WC-10-06 ✅ — WC lineup capture via ESPN (API-Football free tier has NO 2026 — spike found ESPN's free key-less JSON API site.api.espn.com/.../soccer/fifa.world serves WC XIs). src/world_cup/lineups.py fetch_wc_lineup: scoreboard→event (name map _ESPN_NAME_MAP{Congo DR→DR Congo, United States→USA}) → summary rosters → wc_lineups table (NEW; created on Neon). Requires BOTH XIs (11 each) before storing. Wired into dispatcher as a SEPARATE lineup pass [KO-60,KO) retried each tick (ESPN free) until out. Verified live (Germany 52 players/22 starters). 9+3 tests, 754/754.
Also done: WC-10-07 ✅ — rotation/absence flag (research card, Tab 1). lineups.lineup_signal: compares the captured XI to the team's PREVIOUS captured XI (_prior_xi), flags heavy_rotation (≥ config rotation_threshold=5 changes). _render_lineup_flag shows confirmed XI + ⚠️ st.warning ("hypothesis to re-check"). DECISION-SUPPORT ONLY (grep-verified: zero refs in model/value-bet path). Date-range fix to fetch_wc_lineup (±1 day window — ESPN indexes late kickoffs a day off) → capture 11/15→15/15. Rotation reads 0 until a team has 2 captured XIs (early tournament). 8 tests, 763/763.
NEW EPIC — DF (Decision-First UX), owner-approved 2026-06-24, spec in worldcup_buildplan.md. 10 issues: verdict-led fixtures (WC+leagues) + digestible research card + WC deep dive; markets → 1X2+O/U 1.5/2.5/3.5+BTTS; WC = login landing during the tournament. Phase A (main page) → Phase B (deep dive).
Currently working: **NONE — awaiting owner direction.** Just done: **STAKING RECONCILE (owner task_5a7fe3ba, CLOSED)** — flat staking was identical to percentage (both % of current); HC-04 had "fixed" the copy to match that degenerate code, but the masterplan's own onboarding design (§3 Flow 6) said stakes = % of the STARTING amount, so the CODE was the drift. Owner chose (b): flat is now **level staking** = a fixed % of the STARTING bankroll (bankroll.py `base = user.get("starting_bankroll") or bankroll`), genuinely distinct from percentage (% of current). Reconciled EVERY source to "starting/level": bankroll.py docstring+calc, views/bankroll.py label, settings.py + onboarding.py help, help_content.py (flat glossary + bankroll concept + flat_stake docstring), help.py demo label; masterplan §3 Flow 6/197 + the HC-epic note annotated, buildplan HC-04 entry annotated. Drawdown (issue 2) was ALREADY 25% everywhere (HC-04/06) — no change. 5 new tests (tests/test_flat_level_staking.py: flat=starting, pct=current, they differ on drawdown, equal when fresh, safe fallback). 1116/1116. **Backtester ALSO aligned to level staking (owner approved "Choice B done safely"):** new `_level_or_pct_stake` helper (flat=starting/level, pct=current; 5% cap on current balance), 5 tests (tests/test_backtester_level_staking.py). Verified read-only via a 6-league replay (one Poisson backtest/league at a uniform 5% edge, then replay each realised bet sequence under compounding vs level — same bets/results, only stake sizes differ): delta (level−compound) ranged +2.5pp (LaLiga/Championship) to −9.5pp (Ligue1); **NO league sign-flipped** (winners stay +, losers −; Championship +9.4% level). KEY FINDING: compounding-"flat" FLATTERED losing leagues — as the bankroll death-spirals toward $0, stakes shrink so losses stop accumulating; level is the honest per-unit ROI, so losers look WORSE under level (EPL −12.7%→−17.8%, Ligue1 −27.4%→−37.0%) and winners better. CAVEAT: that check used a UNIFORM 5% threshold, NOT the tuned per-league configs behind the documented tier CIs, so the documented ROI baselines are NOT yet regenerated (Brier is staking-INDEPENDENT — unaffected). leagues.yaml UNTOUCHED (no re-tier). DEFERRED (owner, 2026-06-25): tuned per-league ROI-baseline regen under level is PARKED — tiers safe + not urgent; revisit when next touching the strategy tiers. (Backlog item; not awaiting an answer.) Prior: **WC Results tab** — new ✅ Results tab in the WC hub (5th tab) = completed matches newest-first (flags + score, winner emboldened) + per-game Model ✓/✗ with the favoured outcome + its confidence %, a mini hit-rate scorecard (17/22 = 77% where the model had a pre-match call; backfilled 11-19 Jun games correctly show "no model call"), a group filter, and a picker into the deep dive. Pure helpers (_result_outcome/_model_pick/_pick_conf/_short_date/_result_row_html) AST-tested; 13 tests; verified live via preview (port 8507, .env-sourced → Neon). NOTE: showed the favoured-OUTCOME probability NOT the modal scoreline (Poisson's most-likely score is often a draw even when a win is likeliest → reads as contradictory). 1111/1111. Prior: **WC results ESPN backfill + pipeline self-heal** — the standings showed 1 game/team because the Odds API /scores daysFrom=3 cap + late capture start (~23 Jun) meant 11-19 Jun was NEVER ingested; new src/world_cup/results_espn.py backfilled 32 missing matches from ESPN's free scoreboard → finished 22→54, every team now 2-3 games, all 12 groups correct; self_heal_wc_results wired into morning+evening so it can't recur. Also fixed the 2 board_markets tests left failing by the prior 422 commit. Prior: WC standings fix + evening results refresh re-enabled (23:30 ET); WC odds 422 fix; dashboard error/aesthetic scan ✅ (14 pages, zero errors); RBAC ✅ (owner-vs-tester access differentiation). Prior: EMAIL-OPTIN ✅ (all email types opt-in/default-off) + WC-EMAIL ✅ (multi-user WC emails). PRIOR: DH epic COMPLETE (4/4, masterplan v1.8) — read-only data-quality monitoring (CLI `make health` + 🩺 Data Health page + morning-pipeline email-on-issue); HC (6/6, v1.7); WC-11A (4/4, v1.6); DF (10/10, v1.5). Backlog (owner-directed, none auto-advancing): GATED WC-11 player-props overlay; PC-27 soak; owner task task_5a7fe3ba. **MULTI-USER TESTING:** add testers via Admin (create_user_with_password); NEW users now default OFF for EVERY email type (morning/evening/weekly/wc) — they opt in via Settings (all 4 toggles now functional) or onboarding (toggles default off). **The owner (user 1) keeps their PRE-EXISTING prefs (league morning/evening/weekly=1, wc=0)** — only NEW users are flipped to off; owner can self-toggle in Settings, or ask to flip to a clean opt-in slate. The 2 Ligue 1 stale stubs auto-clear on the 26/29 Jun morning runs (owner: leave them).
Last done: WC standings fix + evening results refresh. (a) Owner reported stale WC group standings: 4 matches dated 24-Jun (Bosnia 3-1 Qatar, Switzerland 2-1 Canada, Scotland 0-3 Brazil, Morocco 4-2 Haiti) finished AFTER the 09:30 ET morning scrape, so weren't ingested (WC pipeline is once-daily morning; evening run was retired). Ran scrape_wc_results() (owner-approved prod write) → 32 updated/2 created, stale stubs 4→0, finished 16→22, Groups B/C current. CONFIRMED records: WCMatch stores all results; WCPrediction stores model's full pre-match call (H/D/A probs, xG, most-likely score) for BOTH wc_poisson_v1 + wc_bayesian_v1 — all 16 finished have predictions (model 5/6 on recent sample). (b) Re-enabled + retimed scripts/com.betvector.wc_evening.plist 22:00→23:30 ET (old 22:00 fired mid-match → mis-captured; un-retired, installed to ~/Library/LaunchAgents, launchctl loaded, plutil OK). Evening mode = lighter (results→CLV→Elo→accuracy→email; NO odds re-pull/re-predict/value-scan). LESSON (logged): WCMatch.updated_at has NO onupdate= → it never reflects UPDATEs (only insert time); don't use it as a "last pipeline run" freshness signal (I misread it as "pipeline hasn't run since 23-Jun" — wrong; the log showed it ran + updated 36). Verify pipeline activity from LOGS / a run record, not a model's updated_at unless it has onupdate.
Prior: RBAC ✅ — owner-vs-tester (role='owner'/'viewer') access differentiation. (1) Data Health is now OWNER-ONLY: removed from the always-on nav, registered only inside the `if get_session_user_role()=="owner":` block in dashboard.get_pages (inserted next to Model Health), PLUS an in-page guard (`!= "owner" → st.error+st.stop`) before any load (defence in depth). Model Health stays visible to testers (owner's choice). (2) settings.py: the two GLOBAL sections — Section 2 League Management (toggles League.is_active globally) + Section 4 Injury Flags (global CRUD) — are now wrapped in `if user_data["role"]=="owner":` (script-driven re-indent of ~250 lines; py_compile + suite green); personal sections (User Preferences, Notifications incl. the 4 functional email toggles, Danger Zone per-user reset) stay open to all. Caption "...and users" → "...your staking, thresholds, and notifications". (3) onboarding.py: render_step_4_leagues early-returns an info note for non-owners (no editable checkboxes); save_league_selections guarded to owner — a tester can NEITHER stage NOR write global League.is_active. Per-user data still scoped to get_session_user_id() (unchanged); unauth default 'owner' only on local-dev/emergency paths, real viewers resolve to 'viewer'. 5 new tests (nav gating + in-page guard + section enclosure via nearest-guard walk + personal-sections-open + onboarding gating), 1084/1084. Gate 3 APPROVED (gating complete, re-indent intact, no leaks). LESSON (logged): multi-user audit must gate EVERY global-state write (league activation, injury flags) in EVERY entry point + gate ops pages in nav AND in-page. NEXT: live dashboard error/aesthetic scan (owner logs in / run via preview).
Prior: EMAIL-OPTIN ✅ — ALL email types are now opt-in (default OFF), user-controllable. models.py: notify_morning/evening/weekly/wc all get `default=0, server_default="0"` — the Python-side `default=0` makes NEW users off even on the already-deployed DBs (whose league columns carry a DB-level DEFAULT 1; server_default only affects fresh create_all). NO schema migration needed (columns exist); verified via a rolled-back probe user on the existing-schema local DB → notify_*=0. onboarding.py: the 3 wizard toggles + their session_state fallbacks default to False (was True). settings.py: the 3 league toggles are now FUNCTIONAL (read user_data + persist via save_user_setting, like the WC toggle); load_current_user exposes all 4 flags; the "E11 informational" note replaced. EXISTING owner (user 1) prefs UNCHANGED (still league=1,1,1, wc=0) — only the default for new users flipped; owner can self-toggle or ask to flip. 3 new tests (all-flags-default-off + functional toggles + onboarding-off), 1079/1079. value/predictor untouched. LESSON (logged): to flip a new-user default on a live DB use Python-side `default=`, not just `server_default=` (+ flip UI creation-path defaults like the onboarding toggles).
Prior: WC-EMAIL ✅ — Opt-in multi-user World Cup emails. NEW User.notify_wc column (Integer, server_default 0 = OFF; opt-IN, unlike notify_morning/evening/weekly which default 1) + migration in db._apply_schema_migrations ("users","notify_wc","INTEGER NOT NULL DEFAULT 0") APPLIED to BOTH local SQLite + Neon (owner=0). src/world_cup/alerts.py: _wc_notifiable_user_ids(session=None) (active + email set + notify_wc=1) + send_wc_morning_email_to_all()/send_wc_evening_email_to_all() (loop, per-user try/except, count real sends); single-user send_wc_morning_email(user_id=1)/evening unchanged. WC pipeline (world_cup/pipeline.py) now calls the _to_all dispatchers (was owner-only user_id=1). settings.py: a REAL toggle "🏆 World Cup Digest" (reads/persists notify_wc via save_user_setting; the existing morning/evening/weekly toggles are pre-existing display-only placeholders — left as-is). 8 new tests, 1076/1076. Gate 3 APPROVED (opt-in default verified, per-user isolation + _step double-guard, migration idempotent both backends, value_finder/predictor empty diff). LESSON (logged): adding a model column needs the migration applied to the LOCAL data/betvector.db backup too (admin.py queries users at import → a stale local file fails the suite) — run init_db with all models imported, per DB.
Prior: DH-04 ✅ — Morning-pipeline data-health alert (CLOSES the DH epic). New src/monitoring/health_alert.py: run_and_alert() runs the read-only engine + emails the owner via the existing email_alerts.send_alert when overall ≥ health.alert.min_status (DEFAULT "warn" — the live standings issue is WARN not FAIL, so fail-only would miss it; tunable). build_alert_body_html lists fail/warn checks, every field escaped. run_and_alert NEVER raises (Rule 6). A tiny GUARDED hook at the end of run_morning() (after _complete_run, before return result) calls it in try/except → can't touch the run. 9 tests incl. an integration scenario (seed stale stubs + missing odds + finished-NULL-goals → engine catches each, overall=FAIL) + alert wrapper + owner fallback + hook wiring. 1067/1067. Gate 3 APPROVED (pipeline-safe: double-guarded, post-finalise; read-only; escaped; value_finder.py ×2 + predictor.py untouched). Rule-8 Tier-1: masterplan DH paragraph (§13.16 area) + version 1.7→1.8. DH EPIC COMPLETE (4/4): 01 engine (src/monitoring/health_check.py, 5 groups, season-gated, config in settings.yaml health:) + 02 CLI (health_cli.py, `make health`, --json/--strict) + 03 page (views/data_health.py, 🩺 nav after Model Health) + 04 alert. Read-only/$0 throughout. LESSON: a data-freshness check must be activity-aware — gate "stale source" on whether the thing should be flowing (leagues in-season) or it cries wolf in the off-season; the live smoke (4 spurious FAILs) is what exposed this, so always smoke a monitoring check against real data before trusting its verdicts.
Prior: HC-04 ✅ — Help Center "Betting 101" concept cards. New CONCEPTS in help_content.py — 10 plain-English lessons, each {title, body, example} with a WORKED numeric example (odds↔implied prob, value/edge, overround/de-vig, CLV, "why a +edge bet can still lose"=variance, bankroll/staking, drawdown, reading the scoreline matrix, calibration/Brier, ROI vs win rate). Rendered as a "🎓 Betting 101" tab (5th) via pure escaped _concepts_html (title + body + green-accented "Example." box). **Gate 2 re-computed every example (all 10 correct) + cross-checked claims vs code → caught 2 real errors latent in the consolidated glossary too: (1) drawdown safety alert is 25% (settings.yaml drawdown_alert_threshold:0.25), NOT the "~30%" the page glossaries said; (2) flat staking uses CURRENT bankroll (bankroll.py: flat & percentage share current_bankroll×stake_percentage), NOT "% of starting bankroll".** Fixed concept + glossary to match code; spawned an OWNER TASK to reconcile the app's own Settings/onboarding copy (still says 30%/starting). Edge lesson uses raw 1/odds (consistent w/ HC-03). 3 new tests (concept integrity + edge-example arithmetic + AST/escaping), 1002/1002. Gate 1 PASS / Gate 2 CLEAN (after drawdown+flat fixes) / Gate 3 APPROVED. Real PNG on owner Desktop. LESSON: a teaching page needs its WORKED EXAMPLES re-computed AND its thresholds checked against config/code (not the app's own UI copy, which can itself be wrong).
Prior: HC-03 ✅ — Help Center FAQ + on-page "How to read this page" deep-links. New FAQ (8 Q&A) + tour_for_page() in help_content.py; a "❓ FAQ" tab + a deep-link FOCUS PANEL in views/help.py (pops help_focus_page from session-state → surfaces that page's tour card on top). Per-page link wired CENTRALLY in dashboard.py: render_help_link(nav.title) after st.navigation() shows a "❓ Page guide" button on any page with a tour card (sets help_focus_page + st.switch_page("views/help.py")) → all 11 pages get the link WITHOUT editing a single view. **Gate 2 caught a REAL factual error**: the help system (FAQ #4 AND the HC-01 glossary "Edge" entry) claimed picks flag against a DE-VIGGED price, but value_finder.py flags on the RAW implied prob (implied=1/odds "INCLUDES the margin (vig)", edge=model−implied); de-vig is a deep-dive DISPLAY refinement only. Corrected the FAQ + the Edge glossary entry + the authoring docstring. 5 new tests (FAQ integrity + tour_for_page map + FAQ AST/escaping + source-level deep-link wiring), 999/999. Gate 1 PASS / Gate 2 CLEAN (after the de-vig fixes) / Gate 3 APPROVED (hot-path dashboard edit: additive, guarded, title↔TOUR map exact). Real PNG on owner Desktop. LESSON: cross-check help content against the ACTUAL value path (value_finder.py), not just internal glossary consistency — the staked edge uses raw 1/odds, NOT de-vig.
Prior: HC-02 ✅ — Help Center screen tour (one card per page: what it's for · 3 things to look at first · colours/badges decoded). New TOUR in help_content.py (11 cards — every primary nav page + both deep dives), rendered as a "🗺️ Screen tour" tab via pure escaped helpers (_tour_card_html/_tour_html; .tour-* CSS; Settings has empty decode → no badge block). Gate 2 caught SIX faithfulness errors (a manual that misdescribes the UI is worse than none) — all fixed after reading the real views: WC "🟢🟡🔴 trust mark"→group-qualification dots (WC strip uses ✓/⚠/— verdicts, NOT a trust mark); Match Deep Dive "★ best price"→FanDuel/Best-Edge/All toggle (no ★ there); Today's Picks "✅/❌ + P&L"→"FT score" badge (no per-pick P&L); Fixtures chip→"league trust chip"; League Explorer form "most recent on the right"; Bankroll "green/red months"→real monthly-breakdown columns. 5 new tests, 994/994. Gate 1 PASS / Gate 2 CLEAN (after the 6 fixes) / Gate 3 APPROVED. Real PNG on owner Desktop. Only help_content.py + views/help.py + test changed. LESSON: for a UI manual, always cross-check every described badge/colour against the real view file — Gate 2 faithfulness is the load-bearing gate.
Prior: HC-01 ✅ — Help Center spine + consolidated searchable master glossary (NEW dashboard-wide feature; read-only, $0 cost, zero change to model/value/predictions/bet logic). New src/delivery/help_content.py = SINGLE SOURCE OF TRUTH: GLOSSARY_GROUPS (69 terms in 5 groups — Betting basics / Markets / The model / Performance & bankroll / World Cup) consolidating the FIVE scattered page glossaries (picks/performance/bankroll/match_detail/wc_deep_dive) with drift resolved (Edge→de-vigged-probability precision; BTTS→one verb; Confidence→all 3 HIGH/MEDIUM/LOW tiers; Squad value→1.5× "meaningful" + ~2× badge), PLUS terms the app shows but no page defined (calibration, Brier, ensemble, MODEL badge, trust tiers, verdict states, line shopping, O/U 3.5, capped edge); START_HERE_INTRO/DAILY_LOOP/GOOD_TO_KNOW orientation + pure filter_glossary (term OR definition, case-insensitive; blank→all; no-match→graceful empty). New views/help.py (📖 Start here · 🔤 searchable Glossary tabs) registered as ❓ Help in nav after Settings; pure HTML helpers AST-tested, all dynamic HTML escaped; READ-ONLY (only help_content.py + views/help.py + dashboard.py nav + test changed — nothing in model/value/predictor). 17 tests (integrity + uniqueness + 4 drift resolutions + definition-body search + view AST + escaping + nav), 989/989. Gate 1 PASS / Gate 2 CLEAN (after adding the "Squad value" term the docstring had promised) / Gate 3 APPROVED (3 cosmetic nits; nav-coverage one closed with a test). Real PNG on owner Desktop (Start-here + a live "drawdown" glossary search). PATTERN for HC-02..06: author content ONCE in help_content.py (single source) + thin escaped render in views/help.py (AST-tested) + 3-gate + qlmanage PNG to /tmp then Desktop; HC-06 closes the epic → masterplan Tier-1.
Prior: WC-11A-04 ✅ — player-watch extras (display-only, zero Odds API credits; CLOSES the WC-11A epic). New pure research.build_player_watch(match_id, rate_lookup) reuses the shared _match_legs read (NO extra query) + the injected rate_lookup to emit three squad notes per confirmed XI — squad FACTS, not model outputs, so they need no stored λ and surface the moment the XI lands. (a) Booking risk: starters with recent club yellows_per_90 ≥ _BOOKING_RISK_PER90 (0.25 — cleanly separates card-prone DMs/CBs at 0.25–0.34 from clean attackers/keepers <0.20 in the real cache; a 2-yellow tournament suspension risk), ranked desc, framed as a CLUB rate NOT a tournament caution count. (b) Star absence: a player in the team's PREVIOUS XI but not this one (baseline minus current, mirroring _team_impact's rotated-out walk) who is high-value (market_value_eur ≥ €40m) OR a goal threat (goals_per_90 ≥ 0.60), ranked by value — "Brazil without Vinícius Júnior". (c) Milestones: within 5 of a 50-cap landmark, or within 3 of the next ten of intl goals at/above a floor of 20 (_next_milestone gained a floor guard so a defender "nearing 10 goals" never flags). Each note has a graceful empty state. Deep-dive Section 8 _render_player_watch (after scorer board, before group context): per-team card — booking block (amber YEL chip = a literal yellow card), star-absence block ("{nation} without …" + per-player market value), milestone block; NO MODEL badge (facts, not model numbers), all dynamic strings escaped. Glossary +"Booking risk"/"Star absence". READ-ONLY: no add/commit, nothing written back; predictor.py + value_finder.py ×2 EMPTY diff. 16 tests (milestone math + floor + booking threshold + star-by-value/by-g90 + sorting + empty/not-announced + DB read-only + escaping + view AST), 972/972. Gate 1 PASS 5/5 / Gate 2 CLEAN / Gate 3 APPROVED (two non-blocking nits: n_flags is a tested convenience field mirroring sibling n_ranked; the stale module-docstring section list was renumbered). Real-rate PNG on owner Desktop: England (Maguire/Mainoo card-prone, "without Bellingham" €160m, Kane 1 from 80 intl goals + Walker 4 from 100 caps); Brazil ("without Vinícius Júnior, Rodrygo" €180m/€110m, card-heavy engine room, G. Jesus 1 from 20). Rule-8 Tier-1 masterplan update: §13.16 WC-11A paragraph + version bump 1.5→1.6.
Prior: WC-11A-03 ✅ — "who's likely to score" board + penalty-taker flag (commit 2c6b3d8): research.build_scorer_board, anytime chance P = 1 − exp(−player_λ) from each starter's goal-share, pen taker FLAGGED NOT BUMPED (his spot-kicks already in his goals-per-90), zero odds, deep-dive §7; 14 tests, 956/956, 3-gate green.
Prior: WC-11A-02 ✅ — lineup impact: display-only adjusted-λ (commit 5a3b89c). New pure research.build_lineup_impact(match_id, rate_lookup) reuses lineups.lineup_signal for the confirmed XI/formation/rotation, reads the STORED Poisson λ off WCPrediction, and rescales it by the XI's goal-share vs the team's previous XI: lambda_adjusted = lambda_model × clamp(Σ in-XI gp90 ÷ Σ baseline-XI gp90, 0.5, 1.5) — the ±50% clamp is a display guard against a thin resolve. rate_lookup is INJECTED (the view passes player_rates.player_rate) so the math is unit-testable and research.py stays free of the cache. Per team returns {status, lambda_model, lambda_adjusted, delta, baseline_available, formation, heavy_rotation, changes, scorers:[{player,in_xi,share,exp_goals}], missing, n_xi, n_rated}; unresolved players excluded from the share + surfaced in missing, rotated-out baseline players appear in_xi=False, rated in-XI exp_goals slices SUM to lambda_adjusted. lineups.py gained _starter_rows + _prior_starter_rows (carry full_name/position the resolver needs); _prior_xi refactored to delegate (behaviour-preserving). New deep-dive Section 6 _render_lineup_impact (after lineups, before group context): per-team card with model→adjusted λ (NEUTRAL grey ▲/▼ delta, never green/red — it is NOT an edge), scorer board (g/90→xG slice, rotated-out struck through), unrated footnote; glossary +"Adjusted xG"/"Goal-share". READ-ONLY: no add/commit, nothing written back to WCPrediction; predictor.py + value_finder.py ×2 EMPTY diff. 15 tests (formula incl. clamp + read-only + escaping + view AST), 942/942. Gate 2 CLEAN / Gate 3 APPROVED (one cosmetic no-fix nit: gp90==0.0 player shows "—" xG slice). Real-rate PNG on Desktop (England bench Kane 1.15 → 1.90→1.44; France add Mbappé → 1.75→2.03). Optional research-card echo DEFERRED (AC doesn't need it; keeps card path untouched).
Prior: WC-11A-01 ✅ — player rate engine + name resolver (display-only foundation; commit 14a7a67). New src/world_cup/player_rates.py builds a compact COMMITTED cache (data/world_cup/player_rates.csv.gz, 29,809 players, ~925KB) from the local Transfermarkt files (recency-weighted goals-per-90 min-minutes-guarded, yellows-per-90, penalty-taker flag, position, market value, international goals-per-cap fallback for Saudi/MLS players w/ no club minutes). resolve_player(name,nation,position)= curated _OVERRIDE → name+nation (+max-last_season/position tiebreak) → unique name-only → None (BLANKS on ambiguity, never guesses; _NATION_ALIASES verified vs real TM spellings — TM has NO ESPN ids so the resolve is name-based, espn_athlete_id captured only as a stable key). WCLineup gained additive nullable full_name + espn_athlete_id (captured from ESPN displayName-stays-player_name + fullName + athlete.id; migration via db._apply_schema_migrations applied to Neon). Verified real: Kane 1.15/Mbappé 0.92/van Dijk 0.12/Ronaldo 0.63-international; short-form "Vinicius Jr" + ambiguous "Bruno" → blank. 18 tests, 927/927. Gate 2 CLEAN (after dropping the dead espn_id param the spec over-promised), Gate 3 APPROVED (after NaN-scrubbing string fields). PNG on owner Desktop. CACHE NOTE: cloud needs the committed csv.gz (data/raw/ is gitignored); rebuild via player_rates.build_player_rates().
Prior: DF-10 ✅ — WC Deep Dive: Context + Bayesian (FINAL DF issue, completes the epic). Three sections added to src/delivery/views/wc_deep_dive.py, fed by two new pure/unit-tested/streamlit-free data layers in research.py. (1) Group & qualification impact: research.build_group_context(id) builds the match's group table from finished results (same 3/1/0 + GD/GF logic as the WC hub), flags the two teams, reads the qualification impact of each result via _qual_status — points-only and CONSERVATIVE: "through" (clinched top 2) / "out" (eliminated) only when mathematically certain (ties + head-to-head assumed against the team), the 8-best-third-place race honestly stays "in contention"; knockout tie = no table ("win or out"). View renders escaped group table + scenario chips (or realised standing once played). (2) Bayesian vs Poisson — this match: research.build_model_comparison(id) lines up the two STORED predictions (Poisson MODEL_NAME + shadow Bayesian MODEL_NAME_BAYES) per market + Δ (Bayesian−Poisson) + agreement read; reads stored rows only (no recompute, no stake), explicit "promotion is manual". (3) Glossary: pure _glossary_html() defines the new deep-dive terms (scoreline matrix, de-vig, edge, line movement, CLV, rotation flag, qualification status, Bayesian shadow). (4) NEW real integration test tests/test_wc_deep_dive_integration.py — seeds a full Group C + both preds + odds + VBs + lineups, exercises EVERY per-match data layer end-to-end + AST-exec render of the view's pure helpers + an XSS-escaping probe. value_finder.py ×2 + predictor.py empty diff (shadow). 902/902 (+34). Gate 1 PASS 4/4 / Gate 2 CLEAN / Gate 3 APPROVED (reviewer brute-forced _qual_status over 25,270 group states → zero false clinched/eliminated + ran an XSS test). Real context+Bayesian+glossary PNG on owner Desktop.
Prior: DF-09 ✅ — WC Deep Dive: Movement + Lineups (Phase B). Two sections added to src/delivery/views/wc_deep_dive.py, fed by one new pure data layer (research.build_movement) + the existing lineups.lineup_signal. Line movement & CLV: WCOdds stores only opening_odds + odds_decimal (no per-snapshot history), so each backable selection (every logged WCValueBet) is traced on a consistent best-available-across-books basis — open → entry (best_odds) → current → close (closing_odds) — entry+close marked on a Plotly line (_movement_chart) + a precise _movement_table_html carrying the stored CLV ((1/close−1/entry); +ve green=beat the close, −ve red, "awaiting close" until captured). Confirmed lineups: _render_lineups reuses the SAME lineup_signal that powers the research-card flag (no divergent logic) — both XIs+formations side-by-side, heavy-rotation surfaced as amber card note + st.warning. value_finder.py ×2 + predictor.py empty diff (shadow). 868/868 (+17), 3-gate green. Pushed 16a3ac7.
Prior: DF-08 ✅ — WC Deep Dive: Scaffold + Heatmap + Model-vs-Books (Phase B start). New read-only page wc_deep_dive.py mirroring match_detail.py against the WC tables. 3 pure additions (shadow): predictor.scoreline_matrix_from_lambdas (7×7 from stored λ); research.build_book_comparison (per market: model prob + de-vigged consensus + EVERY pulled book's de-vigged line, edge-tagged via DF-06 config bounds); view _market_table_html (model/consensus/per-book rows, edge-tinted, softest-first, ★ best price). Entry: fixtures strip + research card → session-state + switch_page; page resolves session-state→?wc_match_id, registered in dashboard.py nav, picker fallback. 851/851 (+20), 3-gate green. Pushed 238ef5f.
Prior: DF-07 ✅ — Biggest Disagreements Redesign (completes Phase A). Reworked the research card's "Biggest disagreements" queue from a flat dataframe into ranked verdict sentences. New pure research.build_disagreements(limit,cfg) collapses each market to the side the MODEL favours (one directional call, not a mirror pair), keeps it only if edge ≥ threshold (a real disagreement), tags via DF-06 _edge_trust against the value-finder bounds: value→✓ conviction (backable shadow lean + best price), capped→⚠ likely model error (past ceiling). Sort (conviction-before-capped, edge desc) → trustworthy calls lead even when a capped gap is bigger (+28% capped ranks below +13% conviction). _disagreement_sentence (pure) writes the sentence; view _disagreement_row_html adds the ✓/⚠ tag + signed-edge rank marker (escaped). Empty/in-line/no-pred → [] + neutral caption. top_disagreements kept as the tested primitive. value_finder.py/predictor.py byte-for-byte unchanged (shadow). 831/831 (+9), Gate 2 CLEAN / Gate 3 APPROVED. PNG on owner Desktop. Pushed 1829469.
Prior: DF-06 ✅ — Research Card Redesign. Reworked the WC research card from a flat dataframe into a headline lean + three market blocks (Match result / Goals / BTTS), each a stack of model-vs-market paired bars (model accent over de-vigged market grey, so the GAP is the edge). New pure research.summarize_card (streamlit-free, unit-tested apart from world_cup.py which runs main() at import) annotates each selection with a trust class, arranges blocks, writes one plain-English read per block + the card headline. Trust uses the SAME bounds the value finder stakes on (edge_threshold 0.03 / max_actionable_edge 0.15 via _load_betting_config, no hardcoded dup): in-range lean = filled green pill + best price; gap past the ceiling = amber "likely model error", never celebrated. Line movement folded in as confirmation (headline + per-row ▲/▼). View only renders blocks/headline → HTML (all escaped). build_research_card keeps all prior keys + adds blocks/headline (backward-compat; top_disagreements untouched). value_finder.py/predictor.py byte-for-byte unchanged (card stays shadow). 822/822 (+13), Gate 2 CLEAN / Gate 3 APPROVED. Real 3-state PNGs on owner Desktop. Pushed c9b40dd.
Prior: DF-05 ✅ — Verdict-Led League Fixtures (trust-weighted). New streamlit-free src/delivery/views/_verdict.py mirrors the DF-04 verdict for leagues: classify_league_verdict() picks the highest-edge bet the ValueFinder ALREADY stored (via the fixture's market_vb_info — no recompute, zero new queries), league_verdict_chip_html() renders it with emphasis set by the league trust tier (stake_multiplier in leagues.yaml strategy): 🟢 proven=filled green pill / 🟡 promising=green text / 🔴 unproven=amber caution / none=dim. NO capped tier (league finder has no ceiling, unlike WC). fixtures.py enriches market_vb_info with odds/book (additive), builds trust map once from config.leagues (guarded), inserts a verdict row between teams + badges; existing badges + Deep Dive preserved. src/betting/value_finder.py byte-for-byte unchanged. 809/809, 3-gate green. Real 4-tier PNG sent + on owner Desktop.
Also done: DF-04 ✅ — Verdict-Led WC Fixtures. Additive classify_fixture_verdict() + wc_fixture_verdicts() in value_finder.py reuse the EXACT edge math + config thresholds of find_wc_value_bets but KEEP the over-ceiling ("capped") + sub-threshold ("none") cases the finder drops, so every fixture gets a tier (value takes precedence over capped). find_wc_value_bets byte-for-byte unchanged (0 deletions; value path provably untouched). Strip leads with a colour-tiered chip (green ✓ value / yellow ⚠ re-check·likely model noise / dim — no edge); full probabilities behind a per-fixture st.expander; caption reframed shadow/"track". Removed dead _model_lean_html/_best_price_html; fixed a duplicate _pct. Real value/capped/none PNG sent to owner. 795/795, 3-gate green.
Also done: DF-03 ✅ — Uniform flag component. render_flag now draws every flag into one fixed height×round(height*1.5) 3:2 box (object-fit:cover, 1px #30363D border so pale flags get a visible edge, box-sizing:border-box); missing-flag fallback is a same-size bordered cell so rows stay aligned. _badge_helper (render_team_badge + render_badge_only) aligned to a fixed size×size square cell with object-fit:contain (no crop for transparent crests, no border). All WC flag sites flow through render_flag (strip/standings/knockouts); verified with a real before/after render (qlmanage PNG sent to owner). 785/785, 3-gate green (Gate2 CLEAN, Gate3 APPROVED).
Also done: DF-01 ✅ — Market expansion (1X2 + O/U 1.5/2.5/3.5 + BTTS on the research card). NO migration (decided against it): the loader BAKES the line into alternate_totals selections ("Over 1.5") so multiple O/U lines persist under the existing (match,book,market,selection) unique key; research rebuilds O/U 1.5/3.5 from stored λ's via predictor.derive_markets_from_lambdas (rho -0.05, ≤0.46pp off fitted — verified). research.py refactored to point-encoded canon keys → each O/U line de-vigs independently. odds_scrape.board_markets (h2h,totals,btts,alternate_totals) for board pull; per-event stays lean. VALUE PATH UNTOUCHED (value_finder byte-for-byte unchanged; bets stay 1X2+O/U2.5). 780/780, 3-gate green.
Also done: DF-02 ✅ + HARDENED (lazy/guarded landing import) + VERIFIED LIVE — WC = login landing during the tournament window (config tournament.start/end_date 2026-06-11→07-19; auto-reverts day after the final).
Owner (still pending, non-blocking): log in to verify Bayes-vs-Poisson panel + lineup flag; PC-27 7-day soak; watch the CLV scorecard fill. DEFERRED: 10-08 λ-adjust + props = WC-11 (gated). KEY: ad-hoc scripts must load_dotenv("/Users/kyng/Projects/BetVector/.env") or hit SQLite. Odds API ~313 (lineups free via ESPN).
Next up: Phase 3 lineup flag (10-06/07 via api_football); 10-08 DEFERRED. Owner: OK the dispatcher install?; log in to verify Bayes-vs-Poisson panel; PC-27 soak. Props=WC-11. KEY: ad-hoc scripts must load_dotenv("/Users/kyng/Projects/BetVector/.env") or hit SQLite. Odds API remaining ~313.
Hybrid cloud: DB is Neon Postgres (DATABASE_URL in .env / Streamlit Cloud secrets [database] connection_string); local SQLite kept as backup.

E40 complete: All 10 issues done ✅ (TM datasets download, lineup/formation/manager backfill, manager features, injury club fix, minutes impact, recomputation, weekly refresh, integration test — 14,187 matches, 9,829 TM-mapped, 393K lineups, 42 tests)

E39 complete: All 12 issues done ✅ (Injury pipeline fix + lineup features — PlayerValue, Soccerdata scraper, pipeline integration, historical backfill, recompute, dashboard display, Phase 1 tests, MatchLineup, squad rotation, formation change, bench strength, Phase 2 tests)

E1-E13 complete: 45 original issues ✅
E14 complete: 4 issues ✅ (Understat xG, weather, API-Football dormant, pipeline integration)
E15 complete: 3 issues ✅ (Football-Data.org API, Understat expansion, Transfermarkt)
E16 complete: 3 issues ✅ (Rolling advanced stats, market/weather features, recomputation)
E17 complete: 4 issues ✅ (Dashboard feature surfacing)
E18 complete: 6 issues ✅ (Match narratives, kickoff fix, glossaries)
E19 complete: 4 issues ✅ (Live Odds Pipeline + CLV)
E20 complete: 3 issues ✅ (Market-Augmented Poisson, Brier 0.6105 → 0.5781)
E21 complete: 3 issues ✅ (Elo, referee, congestion features)
E22 complete: 2 issues ✅ (Set-piece xG, injury flags)
E23 complete: All 7 issues done ✅ (Historical backfill + validation + Odds API verified)
E24 complete: All 5 issues done ✅ (Dashboard fixes + fixtures value grid)
E25 complete: All 4 issues done ✅ (XGBoost ensemble model — Poisson wins backtest, +2.78% ROI)
E26 complete: All 4 issues done ✅ (Dashboard UX Overhaul — picks dedup, deep dive nav, fixtures landing, integration test)
E27 complete: All 4 issues done ✅ (Deep Dive FanDuel default, O/U 1.5 markets, glossary completeness, integration test)
E28 complete: All 4 issues done ✅ (Team Badges — logo fetch, badge helper, page rollout, integration test)
E29 complete: All 4 issues done ✅ (Dashboard UX Polish — model top pick, badge ring, perf/bankroll badges, bankroll reset)
E30 complete: All 3 issues done ✅ (Fixtures Enhancements + Logo — threshold/ring, historical view, logo integration)
E31 complete: All 4 issues done ✅ (Badge Ring Redesign + League Explorer Badges — blue/green rings, card borders, team badges in all tables)
E32 complete: All 5 issues done ✅ (Dashboard Clarity & Tooltips — MODEL badge, CSS tooltips, picks crash fix, glossary updates)
E33 complete: All 6 issues done ✅ (Cloud Migration — Neon PostgreSQL + Streamlit Community Cloud, pipeline running)
Total original critical path: 127 issues — ALL COMPLETE ✅

Post-critical-path (March 2026):
- PC-01: Logo transparency fix ✅ — all 4 logo PNGs de-haloed (flood-fill BFS from corners)
- PC-02: Logo centering ✅ — wordmark centred at top of every authenticated page + login gate redesigned
- PC-03: Demo app ✅ — `demo_app.py` (port 8502) self-contained with mock data, no DB/pipeline needed
- PC-04: Demo GIF ✅ — `demo_walkthrough.gif` (36 frames, 40s, 0.4 MB) via `scripts/capture_demo_gif.py`
- PC-05: Login ENTER button ✅ — styled green-bordered `st.form_submit_button`, JetBrains Mono, glow on hover
- PC-06: Fixture stub auto-creation ✅ — `load_odds_the_odds_api` creates scheduled stubs; fixes Today's Picks
- PC-07: Dashboard & Value Bet Logic Fixes ✅ — lambda clamp [0.2, 3.5], prob cap [0.02, 0.98], edge alignment, Top Picks dates, error handling, display cap ±30%
- PC-08: Data Gap Fix ✅ — League Correction + Missing Data + Pipeline Timeout (6 issues)
- PC-09: Prediction Model Stability & Data Integrity Fix ✅ — Pinnacle multicollinearity (max coeff 1.98, was 17K), stale prediction refresh, VB dedup, cross-league odds (6 sport keys), data regen (659 VBs, 0 >30% edge, 78% Pinnacle agreement), 20 tests
- PC-10: Morning Pipeline Performance Optimization ✅ — Bulk feature loading (330K→30 queries), load_features_bulk() (2 ORM queries), compute_all_features() bulk pre-loading (3 queries), FEATURE_COLS DRY constant, 16 tests
- PC-11: Pipeline Data Integrity & Email Fix ✅ — FK constraint fix (VBs deleted before predictions), email encoding (UTF-8, as_bytes, Header, sanitize \xa0), BetLog.value_bet_id actual VB ID lookup, Ligue 1 migration verified, 12 integration tests
- PC-12: Dashboard UX Clarity & Performance ✅ — Value tag on Today's Picks sidebar, Top Value Picks terminology, league filter multiselect, picks N+1 fix (12K→7 queries via bulk Team/Weather/Feature + precomputed stakes), fixtures N+1 fix (500+→5 queries via bulk VB/Prediction/Odds/BestOdds), 26 integration tests
- PC-13: Local SQLite Rebuild & Neon Recovery ✅ — Switched from Neon PostgreSQL to local SQLite (quota exceeded), EPL backfill, pipeline running locally
- PC-14: Full Data Gap Closure & 6-League Predictions ✅ — Transfermarkt multi-league (5 leagues, CDN lacks GB2), Odds API team maps (250 entries, 6 leagues), load_injuries() pipeline hookup, matchday NULL computation, weather+transfermarkt backfill CLI, season flag fix, DATA_GAPS.md (7 gaps), 13,569 matches, 27,110 features, predictions for all 6 leagues (EPL 671, Championship 421, LaLiga 260, Ligue1 675, Bundesliga 675, SerieA 840), 28 integration tests, 309/309 full suite
- PC-15: Local Pipeline Setup ✅ — Fixtures, Odds Resilience, Automation
- PC-16: Badge Audit & Fixtures Layout Redesign ✅ — Force re-downloaded 122 badges from API-Football, fixed Paris FC/Bielefeld swap, fixed Leeds United ID, downloaded 27 missing badges, 183/183 full coverage, zero cross-team mismatches. Fixtures card layout redesigned: date left, teams centered, kickoff right, model+markets row below. Added ~35 multi-league name mappings to API_FOOTBALL_EPL_TEAM_MAP.
- PC-17: Badge Full Coverage + Allow-List Sync ✅ — Fixed Paris FC/Bielefeld badge swap (API-Football IDs set), downloaded all 27 remaining missing badges (Darmstadt, Hertha, Barnsley, Norwich, WBA, Almeria, Granada, Levante, Bordeaux, Clermont, Dijon, Nimes, Troyes, Benevento, Crotone, Frosinone, Salernitana, Sampdoria, Spezia, etc.), 183/183 full badge coverage, zero mismatches. Synced project allow-list with global (added pgrep, nohup, kill, pkill, lsof + 11 more).
- PC-18: Feature Pruning for Model Accuracy ✅ — Removed 21 features from Poisson + XGBoost `_select_feature_cols()`: manager_win_pct (overfitting, +0.0185 EPL regression), manager_tenure_days (re-appointment bug), ref_avg_goals/ref_home_win_pct (76% EPL, dead elsewhere), all weather (13% EPL, dead elsewhere), set_piece/open_play_xg (59% LaLiga, dead elsewhere), 11 dead features (0% all leagues). Kept new_manager_flag + manager_change_count (clean signals). Backtest: avg Brier 0.5983→0.5921 (-1.0%), EPL 0.6317→0.6029 (-4.6%), zero regressions across 6 leagues. Data retained in DB.
- PC-19: Deep Dive Bookmaker Probability Comparison ✅ — Model (white) vs bookmaker (grey #A0ADB8) side-by-side on Deep Dive page. Overround removed for fair comparison. Green highlight + edge badge when edge ≥ 5%. FanDuel preferred, auto-fallback. Today's Picks default filter: today + 14 days.
- PC-20: Email Notifications Setup ✅ — Set betvector.co@gmail.com on user 1, GMAIL_APP_PASSWORD verified (19 chars), morning + evening notifications enabled. Awaiting next pipeline run for delivery confirmation.
- PC-21: Dixon-Coles Correction Factor ✅ — Dixon & Coles (1997) ρ correction for low-scoring matches. `_estimate_rho()` MLE via `minimize_scalar` [-0.15, 0.0], 200-match min, vectorized numpy (15x speedup). τ multipliers on (0,0), (1,0), (0,1), (1,1) cells. `use_dixon_coles` flag + `model_kwargs` in backtester. 6-league A/B backtest: DC wins Brier 3/6 (LaLiga -0.0003, Bundesliga -0.0018, SerieA -0.0021), ROI mixed. Adopted permanently. 33 tests, 473/473 suite passing.
- PC-22: Test Suite Hygiene ✅ — E35 MagicMock import error was already resolved (mock setup in test_e35_v2_integration.py handles module-level Streamlit code correctly). Full suite verified: 464/464 tests passing, 0 failures, 1 warning (SQLAlchemy legacy API).
- PC-23: Log Housekeeping ✅ — Added `data/logs/` to `.gitignore` (no longer clutters git status). Added Python-level `_rotate_logs()` to `run_pipeline.py` (belt-and-suspenders with shell-level rotation in `run_pipeline_local.sh` line 108). 30-day retention, catches all exceptions silently, never blocks pipeline.
- PC-24: ROI Optimization Pipeline ✅ — 4-layer stacked optimisation (thresholds, Pinnacle filtering, λ calibration, Kelly staking). PC-24-01 KEEP: per-league thresholds (Championship 10%, LaLiga 8%, Ligue1 7%) — aggregate ROI 1.34%→3.26% (+1.92%). PC-24-02 ROLLBACK: Pinnacle-only collapsed sample sizes (-5.65%). PC-24-03 ROLLBACK: calibration unnecessary (GLM MLE self-calibrates). PC-24-04 ROLLBACK: Kelly staking catastrophic drawdown (99.8%). Final tiers: 🟢 Championship (CI [3.5%, 23.0%]), 🟡 EPL+LaLiga (CI crosses zero), 🔴 Ligue1+Bundesliga+SerieA. 30 integration tests, 517/517 suite.
- PC-25: Multi-League Strategy System ✅ — ALL 15 ISSUES across 3 phases:
  Phase 1 (PC-25-01 to PC-25-07): Per-league strategy profiles (sharp_only, stake_multiplier, max_daily_bets, auto_bet, clv_tracking) in leagues.yaml. LaLiga+Ligue1 sharp_only=True (+21/+22pp). Championship auto_bet=True (only 🟢 league). Aggregate daily exposure caps (15% total, 8% per-league). CLV backfill extended to ValueBet. profitable_min_bets raised 100→250.
  Phase 2 (PC-25-08 to PC-25-10): Stake multiplier enforcement in BankrollManager (🟢=1.5×, 🟡=1.0×, 🔴=0.5×). Dashboard League Strategy Profiles section on Model Health page with CLV summary.
  PC-25-11: Automated weekly strategy review — Sunday pipeline detects tier transitions, generates strategy suggestions (never auto-applied), includes them in weekly email.
  PC-25-12: Shadow mode infrastructure — ShadowValueBet table, compute_shadow_pnl(), generate_shadow_comparison() (4-week minimum, >3pp ROI to promote). All leagues start shadow_mode=False.
  PC-25-13: Per-league model variants — lambda clamps per league in leagues.yaml (Bundesliga [0.3, 4.0], SerieA [0.2, 3.0]), training_weight per league (Championship 2.0×, LaLiga 1.5×). PoissonModel.predict() accepts league param.
  PC-25-14: Expand to value leagues — DEFERRED (framework ready, awaiting 3+ months live data on current 6 leagues before adding noise).
  PC-25-15: Probabilistic Kelly with per-league guardrails — Championship uses Kelly (staking_method: kelly, kelly_max_bet_pct: 0.03, drawdown_rollback_pct: 0.15). All other leagues remain flat. BankrollManager reads per-league staking method.
  94 integration tests, 569/569 full suite passing.

E34 — Multi-User Authentication: ALL 6 issues done ✅
- E34-01: Password storage + session overhaul ✅
- E34-02: Per-user login page ✅
- E34-03: Scope all dashboard queries to logged-in user ✅
- E34-04: Per-user reset controls ✅
- E34-05: Owner admin page ✅
- E34-06: Integration test ✅ (19/19 pytest tests passing)

E35 — Bet Tracker UX: ALL 7 issues done ✅
- E35-01: Manual bet entry form (My Bets page) ✅
- E35-02: Bet slip with edit/void ✅
- E35-03: Integration test ✅ (15 tests)
- E35-04: Fixture browser on My Bets page ✅ (load_fixtures_with_odds, date tabs, 7-market buttons, toggle add/remove, pending_slip session state)
- E35-05: Bet slip builder panel ✅ (global stake + per-row override, log_multiple_bets, Clear Slip, totals row)
- E35-06: Quick-log from Fixtures page ✅ (Add-to-Slip button + inline expander, sidebar slip badge, shared session state)
- E35-07: Integration test v2 ✅ (10 scenarios, 44/44 tests passing across full suite)

E36 — League Expansion: ALL 4 issues done ✅
- E36-01: Championship data pipeline ✅ (2,077 matches, 29,133 odds)
- E36-02: La Liga data pipeline ✅ (1,400 matches, 19,704 odds, 26,750 ClubElo records, 2,800 features)
- E36-03: Multi-league feature adjustments ✅ (league_home_adv_5, is_newly_promoted, per-league edge threshold, backfill bug fix)
- E36-04: Integration test + backtest ✅ (28/28 tests, La Liga Brier 0.5741 ±0.04 of EPL, ROI +4.71%, 72/72 full suite)

E37 complete: All 4 issues done ✅ (XGBoost model, walk-forward backtest, ensemble blend, integration test — Poisson remains best, ensemble at 50/50 initial weights, 96/96 tests)
- E37-01: XGBoost model on multi-league dataset ✅ (4,148 matches, 66 features, early stopping, saved to data/models/xgboost_v1.pkl)
- E37-02: Walk-forward backtest XGBoost vs Poisson ✅ (EPL: XGB Brier 0.5872 ROI -26.05% vs Poisson Brier 0.5781 ROI +2.78%; Poisson wins all 3 leagues)
- E37-03: Ensemble Poisson + XGBoost adaptive blend ✅ (50/50 initial weights, pkl fallback, Model Health blend ratio)
- E37-04: Integration test ✅ (24 new tests, 96/96 total, all 8 build plan scenarios, synthetic data only)

E38 complete: All 6 issues done ✅ (League Backfill & Expansion Phase 2 — 6 leagues, 13,183 matches, 26,366 features, Brier: LaLiga 0.5660, SerieA 0.5713, Bundesliga 0.5914, LeagueOne 0.6114, Championship 0.6672)
- E38-01: Backfill Championship & La Liga to 2020-21 ✅ (2,077 + 720 matches backfilled)
- E38-02: League One data pipeline ✅ (3,166 matches, 44,396 odds, 6,332 features, 37 teams across 6 seasons)
- E38-03: Bundesliga data pipeline ✅ (1,746 matches, 24,434 odds, 3,492 features, 28 teams across 6 seasons)
- E38-04: Serie A data pipeline ✅ (2,170 matches, 31,236 odds, 4,340 features, 29 teams across 6 seasons)
- E38-05: Multi-league validation & backtest ✅ (5 league backtests, XGBoost retrained on 13,094 matches, zero temporal violations)
- E38-06: Integration test ✅ (110 tests, 8 scenarios, 182/182 non-XGBoost tests passing)

---

## Handoff Notes (Cowork → Claude Code)

### Post-critical-path assets (March 2026)

**Logo transparency fix ✅**
- All four `docs/logo/` PNGs had background colours (`#181d24`, `#252d2f`, `#1e2227`) inconsistent with the app bg (`#0D1117`), producing a visible halo.
- Fixed with a BFS flood-fill from image corners (PIL + NumPy). Bvlogo2 required inner seeds due to a 1-px edge artefact.
- Files modified: `Bvlogo1.png`, `Bvlogo1.5.png`, `Bvlogo2.png`, `Bvlogo3.png`

**Logo centering (`src/delivery/dashboard.py`) ✅**
- Added `import base64`, `_LOGO_B64` pre-encoded constant, `render_page_logo()` helper.
- `render_page_logo()` injects a centred base64 `<img>` via `st.markdown(unsafe_allow_html=True)` — works without a static file server.
- Called in `main()` before `nav.run()` → appears on every authenticated page.
- `st.logo()` updated with `size="large"` for a more prominent sidebar logo.
- Login gate: replaced `st.image(_LOGO_WORDMARK, width=280)` with `st.columns([1,2,1])` layout → logo, subtitle, and password field all centred.

**Demo app (`demo_app.py`) ✅**
- Self-contained single-file Streamlit app (port 8502). No `src/` imports, no DB.
- Mock data: EPL GW29 2025-26, 7 pages matching production layout.
- Real team badge PNGs from `data/badges/{team_id}.png` with text fallback.
- Launch config added to `.claude/launch.json` under key `"demo"`.

**Demo GIF (`demo_walkthrough.gif`) ✅**
- 36-frame animated GIF, 960×600 px, ~40 s, ~0.4 MB.
- Script: `scripts/capture_demo_gif.py` (Playwright headless Chromium + PIL).
- Per-frame green progress bar added to defeat Pillow's GIF frame-collapse optimiser.
- Individual page PNGs in `demo_walkthrough_frames/`.

---

### What's done

**E1-01 — Project Structure and Folder Scaffold ✅**
- All directories created: `config/`, `data/raw/`, `data/processed/`, `data/predictions/`, `src/scrapers/`, `src/database/`, `src/features/`, `src/models/`, `src/evaluation/`, `src/betting/`, `src/delivery/`, `src/self_improvement/`, `notebooks/`, `tests/`, `templates/`
- `__init__.py` in every package directory under `src/` (9 files total), each with a descriptive docstring
- `.gitignore` covers `data/*.db`, `__pycache__/`, `.env`, `*.pkl`, `venv/`, `.DS_Store`, IDE files
- `pyproject.toml` for editable install (`pip install -e .`) so `from src.x import y` works anywhere

**E1-02 — Dependencies and Virtual Environment ✅**
- `requirements.txt` with 20 pinned packages matching MP §5 Key Libraries
- `Makefile` with targets: `install`, `test`, `run`, `lint`, `clean`
- `venv/` directory exists but was not fully set up (sandbox limitation)

### What to do first in Claude Code

1. Run `make install` — this creates the venv, installs all 20 packages, and does `pip install -e .`
2. Verify with: `source venv/bin/activate && python -c "import pandas, numpy, scipy, sklearn, statsmodels, requests, bs4, yaml, sqlalchemy, plotly, streamlit, xgboost, lightgbm"`
3. If both pass, E1-02 is fully verified. Proceed to E1-03.

### Files created (not part of original repo)

- `index.html` — landing page for surge.sh deployment (links to pitch/prototype/twopager). Not part of the build plan, can be ignored.

### What has NOT been started

- E1-03 (Configuration System) — not a single line written yet. Start fresh from the build plan.
