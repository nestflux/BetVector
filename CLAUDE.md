# BetVector — Claude Code Session Rules

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
E25-01 → E25-02 → E25-03 → E25-04
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

## Current Status

Last completed: E25-01 (XGBoost Scoreline Model)
Currently working: E25-02 (Ensemble Combiner)
Next up: E25-03 (Walk-Forward Backtest)

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
E23 complete: 7 issues ✅ (Historical backfill + validation)
E24 complete: All 5 issues done ✅ (Dashboard fixes + fixtures value grid)
E25 in progress: 1/4 (XGBoost ensemble model)
Total issues: 93 (90 complete + 3 E25 remaining)

---

## Handoff Notes (Cowork → Claude Code)

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
