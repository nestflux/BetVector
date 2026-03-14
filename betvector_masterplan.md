# BetVector — Masterplan

Version 1.3 · March 2026

---

## §1 — Product Vision

Saturday morning. You open your phone, scroll through the day's football fixtures, and feel a pull toward Arsenal at home. They've been playing well. You put $20 on them to win at 1.80 odds, mostly because it *feels* right. By Monday, you can't remember exactly how much you've won or lost this month. You have a vague sense it's negative but no real data. You place another bet next weekend using the same process: gut feeling, tribal knowledge, hope.

This is how 95% of football bettors operate. No systematic edge. No data. No staking discipline. No performance tracking. They're essentially donating money to bookmakers who have teams of quantitative analysts, proprietary data, and decades of model refinement on their side.

BetVector exists to put the data on your side.

BetVector is a personal football betting intelligence system. It collects match data, team statistics, and bookmaker odds from free public sources. It engineers predictive features from that data. It trains statistical models that predict the probability of every possible scoreline for upcoming matches. From those scoreline probabilities, it derives the true probability of any betting market — match result, over/under, both teams to score, Asian handicap — and compares those probabilities to what bookmakers are offering. When the bookmaker's price implies a lower probability than what BetVector calculates, it flags a value bet.

The core insight is architectural: a single Poisson-based model that predicts expected goals for each team generates a full scoreline probability matrix, and from that matrix, every betting market can be derived. One model, all markets. This means the system starts simple but can layer on Elo ratings, gradient boosting, and model ensembles without restructuring anything — each new model just produces its own scoreline matrix, and the ensemble combines them.

**What BetVector is:** A quantitative betting tool. A personal edge-finder. A learning system that teaches you betting theory through the act of building and using it.

**What BetVector is not:** A tipster service. A gambling app. A guaranteed money-maker. It is a tool for making informed, disciplined betting decisions backed by data — with full transparency about when the edge is real and when it isn't.

**Words to use:** system, edge, value, probability, data-driven, disciplined, quantitative.
**Words to avoid:** tips, sure bets, guaranteed, picks (prefer "value bets" or "flagged opportunities").

**Success at 6 months:** BetVector runs daily on autopilot. You check the dashboard on your phone each morning, review value bets, and place the ones you choose. You've tracked 500+ paper bets with a clear picture of your model's ROI, calibration, and CLV. You know whether the system has a real edge or not, and you've learned the fundamentals of quantitative sports betting.

**Success at 1 year:** The system covers 8+ leagues including smaller leagues where edges are larger. You've upgraded to model ensembles (Poisson + Elo + XGBoost). You've transitioned from paper trading to real money with proper bankroll management. Your 1–2 friends are also using the dashboard.

**Success at 3 years:** BetVector is a mature, continuously evolving system. Player-level models, live odds monitoring, market-specific models for O/U and BTTS, and a track record spanning thousands of bets with verified positive CLV.

---

## §2 — User Personas

### Persona 1: You (Primary User) — "The Builder-Bettor"

**Name:** The Owner
**Profile:** Intermediate Python/SQL developer. Follows European football closely — primarily the Premier League, but watches Champions League and keeps an eye on La Liga and Serie A. Places bets semi-regularly through FanDuel, mostly on match results and over/under markets. Has a sense that some bets are smarter than others but no quantitative framework to distinguish them.

**Today without BetVector:** Opens FanDuel on Saturday morning, scrolls through the fixtures, places 3–4 bets based on form, intuition, and whatever he read on Twitter. Doesn't track results systematically. Has no idea what his ROI is over the last 6 months. Suspects it's negative but has never calculated it. Doesn't know what "value" means in a mathematical sense. Betting feels like entertainment, not a discipline.

**With BetVector:** Wakes up to a morning email with 2–3 value bets, each with a clear explanation: the model's probability, the bookmaker's implied probability, the edge, and the recommended stake. Opens the dashboard on his phone to see the full picture — all leagues, confidence levels, bankroll status. Places bets on FanDuel based on the system's recommendations. Checks the evening email for results and running P&L. Over time, learns to think about bets in terms of expected value rather than outcomes. Understands why a losing bet at good odds was still a good bet.

### Persona 2: The Friend — "The Follower"

**Name:** The Viewer
**Profile:** Casual football fan who bets occasionally. Not technical — wouldn't build a system themselves. Trusts the Owner's judgment and analytical approach. Wants to see the picks and decide which ones to follow.

**Today without BetVector:** Asks the Owner "got any bets this weekend?" via text. Gets an informal reply. Has no structured way to track whether the advice was any good.

**With BetVector:** Gets a shared dashboard link. Opens it on their phone before the weekend's matches. Sees the same value bets with the same analysis. Can track their own bets and bankroll separately from the Owner. Understands the picks better because the dashboard explains the reasoning.

**The primary user is the Owner.** Every design decision optimises for the Builder-Bettor. The Friend's experience is a nice-to-have that comes nearly for free from the multi-user database design.

---

## §3 — Core User Flows

### Flow 1: Morning Picks Review (Daily Core Loop)

This is the most important flow — it's what happens every match day.

**Trigger:** User wakes up on a match day. Receives the morning picks email at 7:00 AM, or opens the dashboard directly.

1. User opens the morning email on their phone. The email subject reads: "⚽ BetVector — 3 Value Bets Today · EPL + Serie A"
2. The email body shows a clean table: Match, League, Market, BetVector Probability, FanDuel Odds, Implied Probability, Edge, Suggested Stake
3. Below each pick, a one-sentence explanation: "Arsenal vs Fulham O2.5 — Arsenal's 10-game rolling xG at home is 2.1, Fulham conceding 1.8 xGA away. Combined expected goals of 3.9 strongly favours the over."
4. User taps the "Open Dashboard" link in the email
5. Dashboard loads on their phone, defaulting to the "Today's Picks" page
6. User sees the same picks with richer context: a confidence colour indicator (green/yellow/red based on edge size), odds movement chart showing how the odds have shifted, and a "Match Deep Dive" button for each pick
7. User taps "Match Deep Dive" on one of the picks
8. Sees: head-to-head record (last 5 meetings), both teams' rolling form (last 10 matches), xG trend charts, injury report, and the model's full scoreline probability matrix
9. User decides which bets to place. Taps "Mark as Placed" on each one, optionally adjusting the actual odds they got and the actual stake
10. Bets are logged with status "pending" in the user's bet log
11. User places the bets on FanDuel manually

**Key edge case:** No value bets found today. The email says: "No value bets today. The model found no edges above your threshold (5.0%). Next check at 1:00 PM when odds update." The dashboard shows an empty state with the message: "No value bets right now. Your bankroll thanks you for your patience."

**Key edge case:** Odds have moved since the morning run. The dashboard shows the current odds alongside the odds at the time of prediction, with a warning if the edge has disappeared: "⚠️ Edge eroded — odds moved from 2.10 to 1.90 since this morning. Edge now 1.2% (below your 5% threshold)."

### Flow 2: Evening Results Review (Daily)

**Trigger:** User receives the evening review email at 10:00 PM, or opens the dashboard.

1. User opens the evening email. Subject: "BetVector Evening — +$12.40 Today · 2/3 Wins"
2. Email shows: each bet placed today with result (✅ Win / ❌ Loss / ⏳ Pending for late matches), P&L per bet, total daily P&L, running weekly P&L, running monthly ROI
3. Below the results, a brief note on tomorrow's fixtures: "3 matches tomorrow (EPL). Predictions will run at 6:00 AM."
4. User taps "Open Dashboard" to see more detail
5. Dashboard shows the "Performance Tracker" page with: running P&L chart (line graph over time), ROI by league, ROI by market type, current bankroll, a calendar heatmap showing daily P&L (green/red days)
6. User reviews and closes the app

**Key edge case:** All bets lost today. The email tone stays neutral and factual: "0/3 wins today. Daily P&L: -$30.00. Monthly ROI: +2.1%. Variance is normal — your model's edge is measured over hundreds of bets, not individual days."

### Flow 3: Weekly Summary Review

**Trigger:** Sunday evening at 8:00 PM, user receives the weekly summary email.

1. Email shows: total bets this week, win rate, weekly P&L, weekly ROI, cumulative ROI, bankroll change
2. Model health snapshot: Brier score trend (is the model getting more or less accurate?), calibration status (is 60% still winning ~60%?), CLV trend (are we still beating the closing line?)
3. Highlight of the week: best pick (highest edge that won) and worst pick (highest confidence that lost)
4. Preview of next week: number of fixtures, leagues with the most matches

### Flow 4: Dashboard Exploration

**Trigger:** User opens the dashboard outside of the daily email flow, wanting to explore data.

1. User opens BetVector dashboard on laptop or phone
2. Lands on "Today's Picks" by default (if there are upcoming matches) or "Performance Tracker" (if no matches today)
3. Navigation sidebar (desktop) or bottom tabs (mobile) shows six pages:
   - Today's Picks
   - Performance Tracker
   - League Explorer
   - Model Health
   - Bankroll Manager
   - Settings
4. **League Explorer:** User selects a league from a dropdown. Sees current standings, recent results, upcoming fixtures, and which upcoming matches the model sees value in. Can click into any match for the deep dive view.
5. **Model Health:** Shows calibration plot (predicted probability vs actual win rate), Brier score over time, CLV tracking chart, and model comparison if multiple models are active (Poisson vs Elo vs XGBoost vs Ensemble)
6. **Bankroll Manager:** Current bankroll, staking method selector (flat/percentage/Kelly), bet history table with filters (by league, market, date range, result), and safety alerts (drawdown warning, daily loss limit status)

### Flow 5: Bet Placement & Tracking

**Trigger:** User decides to mark a value bet as "placed."

1. From the Today's Picks page, user taps "Place Bet" on a value bet
2. A form slides up: pre-filled with the recommended stake and the odds at time of prediction
3. User can adjust: actual odds (the odds they got on FanDuel, which may differ), actual stake (they may want to bet more or less than recommended)
4. User taps "Confirm"
5. Bet is logged in the bet_log table with status "pending", the user's actual odds, and actual stake
6. The system will automatically resolve the bet when match results come in (status changes to "won", "lost", or "void")
7. If the user doesn't mark any bets as placed, the system still auto-logs all value bets as "system_pick" with the recommended stake — this lets you compare "what the model recommended" vs "what you actually bet on"

### Flow 6: First-Time Setup

**Trigger:** User opens BetVector for the first time.

1. User sees a welcome screen: "Welcome to BetVector. Let's get your system configured."
2. Step 1 — Bankroll: "What's your starting bankroll?" Input field, default $500. Explanation: "This is the total amount you're setting aside for betting. BetVector will calculate stakes as a percentage of this amount."
3. Step 2 — Staking: "How do you want to calculate stakes?" Three options with explanations:
   - Flat Stakes (recommended for beginners): "Bet 2% of your bankroll on every qualifying bet. Simple and safe."
   - Percentage: "Bet a fixed percentage of your current bankroll. Adjusts automatically as your bankroll changes."
   - Kelly Criterion: "Mathematically optimal staking based on your edge. Advanced — only recommended after 500+ bets with good calibration."
4. Step 3 — Edge Threshold: Slider from 1% to 15%, default 5%. Explanation: "BetVector only flags a bet when your model's probability exceeds the bookmaker's implied probability by at least this amount. Higher = fewer but stronger picks."
5. Step 4 — Leagues: Checkboxes for available leagues. EPL pre-selected. Explanation: "You can add more leagues later. We recommend starting with 1–2."
6. Step 5 — Notifications: Email address input. Toggle for morning picks, evening review, weekly summary. Telegram setup link (optional).
7. User taps "Start BetVector"
8. Dashboard loads with the Today's Picks page. If no matches today, shows the League Explorer with a message: "No matches today. Explore league stats while you wait."

### Flow 7: Adding a Friend

**Trigger:** Owner wants to give a friend access.

1. Owner opens Settings → Users
2. Taps "Invite User"
3. Enters friend's name and email
4. System generates a unique access link
5. Friend opens the link, sets their name, starting bankroll, and staking preferences
6. Friend can now access the dashboard with their own bet tracking and bankroll, but sees the same model predictions as the Owner

---

## §4 — Feature Set

### Launch Features (MVP)

**Data Pipeline**
- Automated scraping of match results and betting odds from Football-Data.co.uk for configured leagues and seasons. This is the foundational data source — 20+ years of historical data with odds from 50+ bookmakers including market averages.
- Automated scraping of team-level match statistics (xG, xGA, shots, possession, pass completion) from FBref via the soccerdata Python library. xG data is the most predictive publicly available metric for future football performance.
- Odds fetching from API-Football free tier for upcoming fixtures, lineups, and injury data. Runs 2–3 times per day to capture odds movements.
- All data normalised and loaded into the database with deduplication and error handling.
- Config-driven: adding a new league requires only a YAML config entry, not code changes.

**Feature Engineering**
- Rolling features over configurable windows (default: 5 and 10 matches): points per game, goals scored/conceded per game, xG/xGA per game, xG difference, shots per game, shots on target, possession average.
- Advanced rolling features (E16-01): NPxG/NPxGA per game (non-penalty expected goals — strips out penalty xG for purer open-play signal), NPxG difference, PPDA/PPDA allowed (passes per defensive action — pressing intensity), deep completions/deep completions allowed (passes into the penalty area — attacking penetration quality). All computed over the same 5 and 10-match rolling windows.
- Home/away split features: all rolling stats calculated separately for home and away matches, because teams perform differently at home.
- Head-to-head features: historical record between the two teams over last 5 meetings, including goals scored, xG, and results.
- Rest days: days since each team's last match, capturing fatigue effects.
- Season context: matchday number, normalised to account for early-season instability.
- Market value features (E16-02): squad market value ratio (team ÷ opponent, from Transfermarkt weekly snapshots) captures long-term squad quality advantage — richer squads generally outperform poorer ones beyond what recent form shows. Squad value log provides absolute quality signal.
- Weather features (E16-02): match-day temperature, wind speed, precipitation, and a binary heavy-weather flag (precipitation > 2mm OR wind > 30km/h). Heavy weather reduces scoring rates and affects playing style.
- Strict temporal ordering: no feature ever uses data from after the match it's predicting. Market values use the most recent weekly snapshot on or before the match date.

**Prediction Models**
- Poisson regression model: predicts expected goals (lambda) for home and away teams. Generates a full scoreline probability matrix (0-0 through 6-6). From the matrix, derives probabilities for 1X2, Over/Under 2.5, BTTS, and Asian Handicap markets. This is the MVP model and the foundation for all market probabilities.
- Model interface: abstract base class that any future model (Elo, XGBoost, neural net) must implement. All models produce the same output: a scoreline probability matrix. This makes ensembling trivial.

**Value Detection**
- Compares model probabilities to bookmaker odds across all available bookmakers.
- Calculates edge (model_prob - implied_prob) for every match × market × bookmaker combination.
- Configurable minimum edge threshold (default 5%, adjustable via dashboard slider from 1% to 15%).
- Ranks value bets by edge size. Highlights the best available odds across bookmakers. Specifically flags FanDuel odds since that's where bets are placed.
- Runs 2–3 times per day to catch odds movements.

**Bankroll Management**
- Tracks bankroll per user. Starting bankroll set during onboarding.
- Three staking methods: flat stakes (default 2%), percentage of current bankroll, fractional Kelly (quarter Kelly).
- Safety rules enforced automatically: max single bet 5% of bankroll, daily loss limit 10%, drawdown alert at 25% from peak, minimum bankroll pause at 50% of starting amount.
- Staking method selectable in dashboard Settings.

**Bet Tracking**
- Dual tracking: system auto-logs all value bets as "system_pick" entries. User can mark bets as "placed" with actual odds and stake.
- Automatic result resolution when match results are scraped.
- Full bet history with filtering by league, market, date range, result, and user.
- P&L calculation: per bet, daily, weekly, monthly, cumulative.

**Evaluation**
- Walk-forward backtesting: trains on data up to match day, predicts next matchday, advances. Never uses future data.
- Metrics: ROI, Brier score, calibration data, CLV, win rate by market type.
- Calibration plots: predicted probability buckets vs actual win rates.
- Model comparison: when multiple models are active, compares their performance head-to-head.

**Dashboard (Streamlit)**
- Six pages: Today's Picks, Performance Tracker, League Explorer, Model Health, Bankroll Manager, Settings.
- Dark theme (trading terminal aesthetic).
- Mobile-responsive: works on phone browsers, designed for iPhone bookmark-to-home-screen usage.
- Match deep dive: click any match for head-to-head, form, xG trends, injury report, scoreline matrix.
- Configurable settings: edge threshold slider, staking method, leagues, notification preferences.
- Multi-user: each user sees the same predictions but tracks their own bets and bankroll.

**Notifications**
- Morning picks email (7:00 AM on match days): today's value bets with explanations.
- Evening review email (10:00 PM daily): results, P&L, model performance snapshot.
- Weekly summary email (Sunday 8:00 PM): comprehensive weekly stats.
- All emails sent via Gmail SMTP, scheduled via GitHub Actions.

**Automation**
- Full pipeline runs automatically via GitHub Actions: 6:00 AM data pull → 6:30 AM predictions → 7:00 AM email. Second run at 1:00 PM for odds updates. Third run at 10:00 PM for results and evening email.
- No manual intervention needed for daily operations.

### Explicit Non-Features (Not in MVP)

- **No automated bet placement.** BetVector finds value and recommends bets. The user places bets manually on FanDuel. Automated bet placement introduces regulatory, API, and risk management complexity that is not justified at this stage.
- **No live in-play betting.** All predictions are pre-match. In-play adds real-time data requirements and sub-second latency needs that are out of scope.
- **No player-level models.** MVP uses team-level statistics only. Player impact modelling is a Phase 5+ enhancement.
- **No mobile app.** The Streamlit dashboard accessed via mobile browser is the mobile experience. No native iOS or Android app.
- **No social features.** No public sharing, leaderboards, or community picks. The Friend access is private, invite-only.
- **No real-money integration.** No connection to FanDuel's API, no wallet management, no deposit/withdrawal tracking. Bankroll tracking is manual.
- **No Telegram alerts.** Email only at launch. Telegram is a post-launch enhancement.
- **No paid data sources.** Everything uses free data at launch.

### Post-Launch Roadmap (Brief)

- **Self-improvement engine (Phase 2–3):** automatic recalibration, adaptive ensemble weights, seasonal re-training triggers, dynamic feature importance tracking, odds market feedback loop — all with conservative guardrails (see §11)
- Telegram alerts for high-value bets (edge > 10%)
- Elo rating model as second prediction model
- XGBoost/LightGBM model as third prediction model
- Model ensemble (weighted average of all active models, with adaptive weights per §11.3)
- **Dixon-Coles correction factor:** Add a ρ (rho) parameter to the Poisson model's scoreline matrix to correct for goal correlation in low-scoring games. Independent Poisson underestimates 0-0 and 1-0 results; Dixon & Coles (1997) fixes this by applying a multiplier τ to the (0,0), (1,0), (0,1), and (1,1) cells. ρ is estimated via MLE on historical data. Implementation: ~50 lines in `poisson.py` — the two GLMs stay untouched, only `_build_scoreline_matrix()` changes. Expected Brier improvement: 0.005–0.015, with biggest gains in draw markets and Under 1.5/2.5.
- Additional leagues: La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League
- Smaller value leagues: Eredivisie, Portuguese Liga, Belgian Pro League, Turkish Süper Lig
- Player-level features (impact of missing key players on team xG)
- Market-specific models (dedicated O/U and BTTS models)
- Live odds monitoring (continuous odds checking, not just 2–3 times per day)
- Migration from SQLite to Neon PostgreSQL ✅ (completed E33, March 2026)
- Telegram bot integration for real-time alerts
- Feature evolution: automated testing of new feature combinations (requires 6+ months of data and a robust evaluation framework — speculative, not committed)

---

## §5 — Architecture

### System Overview

BetVector is a Python-based data pipeline with a Streamlit web frontend and email/Telegram notification layer. It runs locally during development and is deployed to free cloud services (GitHub Actions, Streamlit Cloud) for daily automated operation.

The system is designed as a set of independent, composable modules connected through a shared database. Each module can be run independently, tested independently, and replaced independently. The pipeline orchestrator calls them in sequence, but they have no direct dependencies on each other — only on the database.

### Frontend: Streamlit

**Framework:** Streamlit 1.28+
**Why Streamlit:** Pure Python (no HTML/CSS/JS needed for the owner to maintain), built-in mobile responsiveness, free cloud deployment, rich charting via Plotly integration, and session state for interactive features. The tradeoff is limited customisation compared to React — but for a personal data dashboard, Streamlit's speed of development wins.
**Not React/Next.js:** This is a personal tool, not a SaaS product. The development speed advantage of Streamlit over a full frontend framework is substantial, and the owner's skills are in Python, not JavaScript.
**Styling:** Streamlit's custom theming for dark mode, plus custom CSS injected via `st.markdown` for fine-tuning (component borders, card styling, accent colours).
**Charts:** Plotly for all interactive charts (P&L line charts, calibration plots, odds movement). Plotly integrates natively with Streamlit and supports dark themes.
**State:** Streamlit session state for user selection, filters, and page navigation. No external state management needed.

### Backend: Python Pipeline

**Runtime:** Python 3.10+
**Framework:** No web framework. The "backend" is a Python pipeline that runs as a scheduled script. It reads config, scrapes data, processes features, runs models, identifies value bets, sends notifications, and writes everything to the database.
**Why no web framework:** BetVector is not a request-response application. It's a batch pipeline that runs on a schedule and a dashboard that reads from a database. There's no API to serve. Adding Flask or FastAPI would be unnecessary complexity.
**Key libraries:**
- `pandas` 2.0+ — all data manipulation
- `numpy` 1.24+ — numerical operations
- `scipy` 1.10+ — Poisson distribution calculations
- `scikit-learn` 1.3+ — model training, evaluation, calibration
- `statsmodels` 0.14+ — Poisson regression
- `requests` 2.28+ — HTTP requests for scraping
- `beautifulsoup4` 4.12+ — HTML parsing for scrapers
- `understatapi` 0.3+ — Understat xG/NPxG/PPDA data access (replaced soccerdata/FBref)
- `pyyaml` 6.0+ — config file parsing
- `sqlalchemy` 2.0+ — database ORM
- `plotly` 5.15+ — charts (used by both dashboard and email reports)
- `streamlit` 1.28+ — dashboard
- `xgboost` 2.0+ — future model (post-launch, but install now)
- `lightgbm` 4.0+ — future model (post-launch, but install now)

### Database: SQLite → Neon PostgreSQL

**MVP:** SQLite. Single file (`data/betvector.db`) in the project folder. Zero configuration. Perfect for single-user, single-process pipeline.
**Why SQLite first:** No server to run, no account to create, no connection strings. The owner can inspect the database with DB Browser for SQLite. It's a file — it can be copied, backed up, committed to Git.
**Migration trigger (actual, March 2026):** SQLite caused binary merge conflicts in git when GitHub Actions wrote to the DB and the owner pulled locally. This made multi-device use impractical and polluted the git history with binary diffs. Migrated to Neon PostgreSQL (E33) at this point — not Supabase as originally planned.
**Migration path:** SQLAlchemy is used from day one. Switching from SQLite to PostgreSQL requires only changing the connection string — either via `DATABASE_URL` environment variable (highest priority) or `config/settings.yaml`. No code changes required.
**Why Neon (not Supabase):** Neon's free tier offers 0.5 GB storage, serverless connection pooling, and automatic branching. Crucially it allows pooled connections compatible with Streamlit Cloud's ephemeral compute. The connection string format is standard PostgreSQL — no vendor lock-in.
**Why SQLAlchemy:** Provides database-agnostic ORM. Write code once, run against SQLite or PostgreSQL without modification. Also provides migration support via Alembic if schema changes are needed later.

**Schema Drift Warning (lesson from E33 migration, March 2026):**
SQLite does not enforce schema migrations automatically. Columns added to ORM
models after initial `create_all()` must be applied to existing SQLite databases
manually via `ALTER TABLE ... ADD COLUMN`. If the live DB and a backup diverge
from the ORM model, the migration script (`scripts/migrate_sqlite_to_postgres.py`)
will fail with `no such column` errors. Use `scripts/fix_sqlite_schema.py` to
patch a stale SQLite backup before running migration. All added columns are
nullable so the pipeline backfills them on the next run.

### Authentication: Simple Token

**MVP:** No traditional auth. The Streamlit dashboard uses a simple password gate (`st.text_input` with `type="password"`) stored as an environment variable. This prevents casual access but is not production-grade security.
**Multi-user:** Users are identified by a `user_id` in the database. The owner is user 1. Friends are added via the Settings page and get a shared access link. Each user's bet log and bankroll are scoped to their `user_id`.
**Why not Supabase Auth / OAuth:** Overkill for 1–3 users on a personal tool. A simple password + user selection dropdown is sufficient and avoids auth infrastructure entirely.

### Scheduling: GitHub Actions

**Platform:** GitHub Actions (free tier: 2,000 minutes/month)
**Schedule:** Three daily runs via cron:
- 06:00 UTC — Full pipeline: scrape data, update features, run predictions, send morning email
- 13:00 UTC — Odds update: re-fetch odds, re-calculate edges, update dashboard data
- 22:00 UTC — Results: scrape results, resolve bets, calculate P&L, send evening email
- Sundays 20:00 UTC — Weekly summary email (in addition to the evening run)
**Estimated usage:** ~10 minutes per run × 3 runs/day × 30 days = ~900 minutes/month. Well within the 2,000 free minutes.
**Why GitHub Actions:** Free, runs from the repo, no server to manage, secrets management built in, cron scheduling built in.

### Email: Gmail SMTP

**Provider:** Gmail via Python smtplib
**Authentication:** Gmail App Password stored as a GitHub Actions secret
**Templates:** HTML emails rendered by the pipeline using Jinja2 templates. Styled inline for email client compatibility.
**Rate limit:** 500 emails/day (sending 2–3/day, effectively unlimited)

### Telegram: Future Enhancement

**Not in MVP.** Post-launch: Python `python-telegram-bot` library. Bot sends messages to a private channel. Triggered when a value bet exceeds a configurable high-alert threshold (default: 10% edge).

### Data Sources

| Source | What | How | Frequency |
|--------|------|-----|-----------|
| Football-Data.co.uk | Match results, betting odds (50+ bookmakers) | CSV download via HTTP | Daily (results) |
| FBref.com | Team stats: xG, xGA, shots, possession, passing | `soccerdata` Python library | Daily (after matches) |
| API-Football (RapidAPI) | Upcoming fixtures, lineups, injuries, live odds | REST API (free tier: 100 req/day) | 2–3× daily |

#### Data Sources — Post-Launch Update (March 2026)

The original data source plan above was designed in February 2026. By March 2026, two of the three sources had become unreliable or unusable:

**Football-Data.co.uk** remains the primary source for historical match results and bookmaker odds, but its CSV files only update twice per week (Sunday and Wednesday nights). For a daily-picks workflow, this creates a freshness gap of up to 5 days. The system needs a near-real-time results source to supplement it.

**FBref** is effectively dead for advanced statistics. In January 2026, Opta terminated its data agreement with FBref, permanently removing all xG, xGA, npxG, shots, possession, and passing data. During the build phase (E3-03), Cloudflare was already blocking automated access. Now there is nothing to access even manually. FBref retains only basic results (goals, cards), which Football-Data.co.uk already covers better.

**API-Football free tier** cannot access the current 2025-26 season. The free plan covers seasons 2022–2024 only. The scraper code (E14-03) is complete and tested against historical data, but lies dormant for live predictions until a paid tier is activated or a free alternative is found.

The revised data source landscape:

| Source | Status | What | How | Frequency |
|--------|--------|------|-----|-----------|
| Football-Data.co.uk | **Active** | Match results, odds (50+ bookmakers) | CSV download via HTTP | ~2×/week (Sun, Wed nights) |
| FBref.com | **Dead** | ~~xG, shots, possession~~ | ~~soccerdata library~~ | N/A — Opta data removed Jan 2026 |
| API-Football (RapidAPI) | **Dormant** | Fixtures, lineups, injuries, live odds | REST API | Free tier blocked for 2025-26 |
| Understat | **Active** | xG, xGA, NPxG, PPDA, deep completions, shot-level xG | `understatapi` Python package | Daily (replaces FBref) |
| Open-Meteo | **Active** | Match-day weather (temp, wind, rain) | Free REST API (no key) | Per-match (forecast + archive) |
| Football-Data.org | **Active** | Current-season fixtures and results | Free REST API (`X-Auth-Token`, 10 req/min) | Near real-time (E15-01) |
| Transfermarkt Datasets | **Active** | Squad market values, squad size | CDN CSV dumps (CC0 license) | Weekly (E15-03) |
| The Odds API | **Active** | Live pre-match odds from 50+ bookmakers | REST API (`THE_ODDS_API_KEY`, 500 req/mo free) | 3×/day in pipeline (E19-01) |
| ClubElo | **Active** | Historical and current Elo ratings per team | Free CSV API (`api.clubelo.com`, no key) | Daily in morning pipeline (E21-01) |

### Key Architectural Decisions

**Decision: Scoreline probability matrix as the universal interface.**
Every prediction model must output a matrix of probabilities for every scoreline from 0-0 to 6-6 (a 7×7 matrix = 49 probabilities that sum to 1.0). All market probabilities (1X2, O/U, BTTS, AH) are derived from this matrix. This means any model — Poisson, Elo-based, XGBoost, neural net — can be plugged into the ensemble without any changes to the downstream value detection or market derivation logic.

**Future enhancement: Dixon-Coles correction factor.**
The current Poisson model assumes home and away goals are independent. In practice, low-scoring outcomes (0-0, 1-0, 0-1) are slightly more frequent than independent Poisson predicts — goals are correlated due to tactical game-state dynamics (a cagey match suppresses both teams' scoring). Dixon & Coles (1997) fix this with a single parameter ρ that adjusts probabilities for these four scoreline cells. The two Poisson GLMs remain unchanged — ρ is applied only when building the 7×7 matrix. Expected improvement: Brier 0.005–0.015, especially for draw and Under markets.

**Decision: Config-driven league and model management.**
Leagues, models, feature windows, thresholds, and schedules are all defined in YAML config files. Adding a league means adding an entry to `config/leagues.yaml` — no code changes. Activating a new model means adding it to `config/models.yaml` with its weight in the ensemble.

**Decision: Dual bet tracking (system picks vs user bets).**
Every value bet the model identifies is logged as a `system_pick` regardless of whether the user places it. User-placed bets are logged separately with actual odds and stake. This allows comparing "what the model recommended" against "what I actually did" — essential for understanding if underperformance is the model's fault or the user's (e.g., skipping good bets, adjusting stakes emotionally).

**Decision: Paper trading as default mode.**
BetVector launches in paper-trading mode. All bets are tracked as simulations. The system must accumulate 500+ system picks with positive ROI, positive CLV, and acceptable calibration before the dashboard unlocks real-money mode. This is a safety feature, not a soft suggestion.

---

## §6 — Database Schema

All tables use SQLite-compatible types. When migrating to PostgreSQL, INTEGER becomes SERIAL or BIGINT, TEXT becomes VARCHAR, and REAL becomes DOUBLE PRECISION. SQLAlchemy handles this transparently.

```sql
-- ============================================================
-- USERS
-- Tracks all users of the system (owner + friends)
-- ============================================================
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,                          -- Display name
    email           TEXT UNIQUE,                            -- For email notifications
    role            TEXT NOT NULL DEFAULT 'viewer'          -- 'owner' or 'viewer'
        CHECK (role IN ('owner', 'viewer')),
    starting_bankroll REAL NOT NULL DEFAULT 500.0,          -- Initial bankroll amount
    current_bankroll  REAL NOT NULL DEFAULT 500.0,          -- Current bankroll (updated after each bet)
    staking_method  TEXT NOT NULL DEFAULT 'flat'            -- 'flat', 'percentage', 'kelly'
        CHECK (staking_method IN ('flat', 'percentage', 'kelly')),
    stake_percentage REAL NOT NULL DEFAULT 0.02,            -- Fraction of bankroll per bet (0.02 = 2%)
    kelly_fraction  REAL NOT NULL DEFAULT 0.25,             -- Kelly multiplier (0.25 = quarter Kelly)
    edge_threshold  REAL NOT NULL DEFAULT 0.05,             -- Minimum edge to flag a value bet (0.05 = 5%)
    is_active       INTEGER NOT NULL DEFAULT 1,             -- 1 = active, 0 = deactivated
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- LEAGUES
-- All configured leagues with their data source settings
-- ============================================================
CREATE TABLE leagues (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,                   -- e.g. 'English Premier League'
    short_name      TEXT NOT NULL UNIQUE,                   -- e.g. 'EPL'
    country         TEXT NOT NULL,                          -- e.g. 'England'
    football_data_code TEXT,                                -- Football-Data.co.uk league code, e.g. 'E0'
    fbref_league_id TEXT,                                   -- FBref/soccerdata league identifier
    api_football_id INTEGER,                                -- API-Football league ID
    is_active       INTEGER NOT NULL DEFAULT 1,             -- 1 = scrape this league, 0 = skip
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- SEASONS
-- Tracks which seasons are loaded for each league
-- ============================================================
CREATE TABLE seasons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    league_id       INTEGER NOT NULL REFERENCES leagues(id),
    season          TEXT NOT NULL,                          -- e.g. '2024-25'
    start_date      TEXT,                                   -- Season start date
    end_date        TEXT,                                   -- Season end date
    is_loaded       INTEGER NOT NULL DEFAULT 0,             -- 1 = data loaded into DB
    UNIQUE(league_id, season)
);

-- ============================================================
-- TEAMS
-- Normalised team names across data sources
-- ============================================================
CREATE TABLE teams (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,                          -- Canonical team name, e.g. 'Arsenal'
    league_id       INTEGER NOT NULL REFERENCES leagues(id),
    football_data_name TEXT,                                -- Name as it appears in Football-Data.co.uk
    fbref_name      TEXT,                                   -- Name as it appears in FBref
    api_football_id INTEGER,                                -- API-Football team ID
    UNIQUE(name, league_id)
);

-- ============================================================
-- MATCHES
-- Every match, past and upcoming
-- ============================================================
CREATE TABLE matches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    league_id       INTEGER NOT NULL REFERENCES leagues(id),
    season          TEXT NOT NULL,                          -- e.g. '2024-25'
    matchday        INTEGER,                                -- Matchday number (1-38 for EPL)
    date            TEXT NOT NULL,                          -- Match date, ISO format YYYY-MM-DD
    kickoff_time    TEXT,                                   -- Kickoff time, HH:MM (24hr)
    home_team_id    INTEGER NOT NULL REFERENCES teams(id),
    away_team_id    INTEGER NOT NULL REFERENCES teams(id),
    home_goals      INTEGER,                                -- NULL if match not yet played
    away_goals      INTEGER,                                -- NULL if match not yet played
    home_ht_goals   INTEGER,                                -- Half-time home goals
    away_ht_goals   INTEGER,                                -- Half-time away goals
    referee         TEXT,                                   -- Match referee name (added E19-03)
    status          TEXT NOT NULL DEFAULT 'scheduled'       -- 'scheduled', 'in_play', 'finished', 'postponed'
        CHECK (status IN ('scheduled', 'in_play', 'finished', 'postponed')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(league_id, date, home_team_id, away_team_id)
);
CREATE INDEX idx_matches_date ON matches(date);
CREATE INDEX idx_matches_league_season ON matches(league_id, season);
CREATE INDEX idx_matches_status ON matches(status);

-- ============================================================
-- MATCH_STATS
-- Team-level statistics for each match (one row per team per match)
-- ============================================================
CREATE TABLE match_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    team_id         INTEGER NOT NULL REFERENCES teams(id),
    is_home         INTEGER NOT NULL,                       -- 1 = home, 0 = away
    xg              REAL,                                   -- Expected goals
    xga             REAL,                                   -- Expected goals against
    shots           INTEGER,
    shots_on_target INTEGER,
    possession      REAL,                                   -- Possession percentage (0.0-1.0)
    passes_completed INTEGER,
    passes_attempted INTEGER,
    pass_pct        REAL,                                   -- Pass completion percentage (0.0-1.0)
    corners         INTEGER,
    fouls           INTEGER,
    yellow_cards    INTEGER,
    red_cards       INTEGER,
    source          TEXT NOT NULL DEFAULT 'understat',       -- Where this data came from ('understat', 'fbref')
    -- Advanced stats (added E15-02, populated by Understat)
    npxg            REAL,                                   -- Non-penalty expected goals (more predictive than raw xG)
    npxga           REAL,                                   -- Non-penalty expected goals against
    ppda_coeff      REAL,                                   -- Passes per defensive action (pressing intensity)
    ppda_allowed_coeff REAL,                                -- PPDA allowed (opponent pressing faced)
    deep            INTEGER,                                -- Deep completions (passes into final third)
    deep_allowed    INTEGER,                                -- Deep completions conceded
    -- Shot-level xG breakdown (added E22-01)
    set_piece_xg    REAL,                                   -- xG from set pieces (corners, free kicks)
    open_play_xg    REAL,                                   -- xG from open play
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(match_id, team_id)
);
CREATE INDEX idx_match_stats_match ON match_stats(match_id);

-- ============================================================
-- ODDS
-- Bookmaker odds for each match × market × selection
-- One row per match per bookmaker per market per selection per timestamp
-- ============================================================
CREATE TABLE odds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    bookmaker       TEXT NOT NULL,                          -- e.g. 'Bet365', 'Pinnacle', 'FanDuel', 'market_avg'
    market_type     TEXT NOT NULL                           -- The betting market
        CHECK (market_type IN ('1X2', 'OU25', 'OU15', 'OU35', 'BTTS', 'AH')),
    selection       TEXT NOT NULL                           -- The specific selection within the market
        CHECK (selection IN ('home', 'draw', 'away', 'over', 'under', 'yes', 'no',
                             'home_-0.5', 'home_-1.0', 'home_-1.5', 'home_+0.5', 'home_+1.0', 'home_+1.5',
                             'away_-0.5', 'away_-1.0', 'away_-1.5', 'away_+0.5', 'away_+1.0', 'away_+1.5')),
    odds_decimal    REAL NOT NULL,                          -- Decimal odds (e.g. 2.10)
    implied_prob    REAL NOT NULL,                          -- 1.0 / odds_decimal (raw, before removing overround)
    is_opening      INTEGER NOT NULL DEFAULT 0,             -- 1 = opening odds, 0 = current/closing
    captured_at     TEXT NOT NULL DEFAULT (datetime('now')), -- When these odds were captured
    source          TEXT NOT NULL DEFAULT 'football_data',  -- 'football_data', 'api_football', 'odds_api'
    UNIQUE(match_id, bookmaker, market_type, selection, captured_at)
);
CREATE INDEX idx_odds_match ON odds(match_id);
CREATE INDEX idx_odds_bookmaker ON odds(bookmaker);
CREATE INDEX idx_odds_market ON odds(market_type);

-- ============================================================
-- FEATURES
-- Pre-computed features for each team going into each match
-- One row per match per team (home and away)
-- ============================================================
CREATE TABLE features (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    team_id         INTEGER NOT NULL REFERENCES teams(id),
    is_home         INTEGER NOT NULL,                       -- 1 = this team is home, 0 = away

    -- Rolling features (5-match window)
    form_5          REAL,    -- Points per game, last 5 matches
    goals_scored_5  REAL,    -- Goals scored per game, last 5
    goals_conceded_5 REAL,   -- Goals conceded per game, last 5
    xg_5            REAL,    -- xG per game, last 5
    xga_5           REAL,    -- xGA per game, last 5
    xg_diff_5       REAL,    -- xG - xGA per game, last 5
    shots_5         REAL,    -- Shots per game, last 5
    shots_on_target_5 REAL,  -- Shots on target per game, last 5
    possession_5    REAL,    -- Average possession, last 5

    -- Rolling features (10-match window)
    form_10         REAL,
    goals_scored_10 REAL,
    goals_conceded_10 REAL,
    xg_10           REAL,
    xga_10          REAL,
    xg_diff_10      REAL,
    shots_10        REAL,
    shots_on_target_10 REAL,
    possession_10   REAL,

    -- Home/away specific rolling features (5-match window, same venue only)
    venue_form_5    REAL,    -- Points per game at this venue (home or away), last 5
    venue_goals_scored_5 REAL,
    venue_goals_conceded_5 REAL,
    venue_xg_5      REAL,
    venue_xga_5     REAL,

    -- Head to head (last 5 meetings between these two teams)
    h2h_wins        INTEGER, -- Times this team won in last 5 H2H
    h2h_draws       INTEGER,
    h2h_losses      INTEGER,
    h2h_goals_scored REAL,   -- Average goals scored in H2H
    h2h_goals_conceded REAL,

    -- Context
    rest_days       INTEGER, -- Days since last match
    matchday        INTEGER, -- Matchday number in the season
    season_progress REAL,    -- 0.0 to 1.0, how far through the season

    -- Advanced rolling stats (added E16-01)
    npxg_5          REAL,    -- Non-penalty xG per game, last 5
    npxga_5         REAL,    -- Non-penalty xGA per game, last 5
    npxg_diff_5     REAL,    -- NPxG - NPxGA per game, last 5
    ppda_5          REAL,    -- PPDA coefficient, last 5
    ppda_allowed_5  REAL,    -- PPDA allowed, last 5
    deep_5          REAL,    -- Deep completions per game, last 5
    deep_allowed_5  REAL,    -- Deep completions conceded per game, last 5
    -- (Same 7 columns repeated for 10-match window: npxg_10, npxga_10, etc.)

    -- Market value and weather features (added E16-02)
    market_value_ratio REAL, -- This team's market value / opponent's (capped at 10.0)
    squad_value_log REAL,    -- log(squad_total_value) for scaling
    temperature     REAL,    -- Match-day temperature from weather table
    wind_speed      REAL,    -- Match-day wind speed
    precipitation   REAL,    -- Match-day precipitation
    is_heavy_weather INTEGER,-- 1 if wind>40 or precip>5mm or temp<2°C

    -- Market odds features (added E20-01, E20-02)
    pinnacle_home_prob REAL, -- Pinnacle implied prob, overround-removed
    pinnacle_draw_prob REAL,
    pinnacle_away_prob REAL,
    pinnacle_overround REAL,
    ah_line         REAL,    -- Asian Handicap home line (added E20-02)

    -- External ratings (added E21-01, E21-02, E21-03)
    elo_rating      REAL,    -- Team's Elo rating on match date
    elo_diff        REAL,    -- This team's Elo minus opponent's Elo
    ref_avg_fouls   REAL,    -- Referee's avg fouls per game (last 20 matches)
    ref_avg_yellows REAL,    -- Referee's avg yellow cards per game
    ref_avg_goals   REAL,    -- Avg goals in referee's matches
    ref_home_win_pct REAL,   -- Home win rate in referee's matches
    days_since_last_match INTEGER, -- Days since team's most recent match
    is_congested    INTEGER, -- 1 if <4 days since last match

    -- Set-piece and injury features (added E22-01, E22-02)
    set_piece_xg_5  REAL,    -- 5-match rolling set-piece xG
    open_play_xg_5  REAL,    -- 5-match rolling open-play xG
    injury_impact   REAL,    -- Sum of impact_ratings for "out" players
    key_player_out  INTEGER, -- 1 if any player with impact_rating >= 0.7 is out

    computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(match_id, team_id)
);
CREATE INDEX idx_features_match ON features(match_id);

-- ============================================================
-- PREDICTIONS
-- Model predictions for each match
-- One row per match per model
-- ============================================================
CREATE TABLE predictions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    model_name      TEXT NOT NULL,                          -- e.g. 'poisson_v1', 'elo_v1', 'ensemble_v1'
    model_version   TEXT NOT NULL,                          -- Semantic version e.g. '1.0.0'

    -- Predicted expected goals
    predicted_home_goals REAL NOT NULL,                     -- Lambda for home team Poisson distribution
    predicted_away_goals REAL NOT NULL,                     -- Lambda for away team Poisson distribution

    -- Scoreline matrix stored as JSON string
    -- 7x7 matrix: scoreline_matrix[home_goals][away_goals] = probability
    scoreline_matrix TEXT NOT NULL,                         -- JSON: [[p_00, p_01, ...], [p_10, ...], ...]

    -- Derived market probabilities
    prob_home_win   REAL NOT NULL,                          -- P(home goals > away goals)
    prob_draw       REAL NOT NULL,                          -- P(home goals == away goals)
    prob_away_win   REAL NOT NULL,                          -- P(home goals < away goals)
    prob_over_25    REAL NOT NULL,                          -- P(total goals > 2.5)
    prob_under_25   REAL NOT NULL,                          -- P(total goals <= 2.5)
    prob_over_15    REAL NOT NULL,                          -- P(total goals > 1.5)
    prob_under_15   REAL NOT NULL,                          -- P(total goals <= 1.5)
    prob_over_35    REAL NOT NULL,                          -- P(total goals > 3.5)
    prob_under_35   REAL NOT NULL,                          -- P(total goals <= 3.5)
    prob_btts_yes   REAL NOT NULL,                          -- P(both teams score >= 1)
    prob_btts_no    REAL NOT NULL,                          -- P(at least one team scores 0)

    is_ensemble     INTEGER NOT NULL DEFAULT 0,             -- 1 if this is the combined ensemble prediction
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(match_id, model_name, model_version)
);
CREATE INDEX idx_predictions_match ON predictions(match_id);
CREATE INDEX idx_predictions_model ON predictions(model_name);

-- ============================================================
-- VALUE_BETS
-- Identified value bets: where model probability exceeds bookmaker implied probability
-- One row per match × market × selection × bookmaker where edge > threshold
-- ============================================================
CREATE TABLE value_bets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    prediction_id   INTEGER NOT NULL REFERENCES predictions(id),
    bookmaker       TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    selection       TEXT NOT NULL,
    model_prob      REAL NOT NULL,                          -- Model's probability for this selection
    bookmaker_odds  REAL NOT NULL,                          -- Best available decimal odds
    implied_prob    REAL NOT NULL,                          -- 1.0 / bookmaker_odds
    edge            REAL NOT NULL,                          -- model_prob - implied_prob
    expected_value  REAL NOT NULL,                          -- (model_prob * bookmaker_odds) - 1.0
    confidence      TEXT NOT NULL                           -- 'high' (edge >= 10%), 'medium' (5-10%), 'low' (< 5%)
        CHECK (confidence IN ('high', 'medium', 'low')),
    explanation     TEXT,                                   -- Human-readable reason for the pick
    detected_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(match_id, market_type, selection, bookmaker, detected_at)
);
CREATE INDEX idx_value_bets_match ON value_bets(match_id);
CREATE INDEX idx_value_bets_edge ON value_bets(edge DESC);

-- ============================================================
-- BET_LOG
-- Every bet — system picks and user-placed bets
-- ============================================================
CREATE TABLE bet_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    value_bet_id    INTEGER REFERENCES value_bets(id),      -- NULL if manual bet not from system pick
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    date            TEXT NOT NULL,                          -- Match date
    league          TEXT NOT NULL,
    home_team       TEXT NOT NULL,
    away_team       TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    selection       TEXT NOT NULL,
    model_prob      REAL NOT NULL,                          -- Model probability at time of bet
    bookmaker       TEXT NOT NULL,                          -- Which bookmaker
    odds_at_detection REAL NOT NULL,                        -- Odds when system detected the value
    odds_at_placement REAL,                                 -- Actual odds when user placed bet (NULL for system_pick)
    implied_prob    REAL NOT NULL,
    edge            REAL NOT NULL,
    stake           REAL NOT NULL,                          -- Stake amount in currency
    stake_method    TEXT NOT NULL,                          -- 'flat', 'percentage', 'kelly', 'manual' (E35-01: sentinel for user-entered manual bets)
    bet_type        TEXT NOT NULL DEFAULT 'system_pick'     -- 'system_pick' (auto-logged) or 'user_placed'
        CHECK (bet_type IN ('system_pick', 'user_placed')),
    status          TEXT NOT NULL DEFAULT 'pending'         -- Bet resolution status
        CHECK (status IN ('pending', 'won', 'lost', 'void', 'half_won', 'half_lost')),
    pnl             REAL DEFAULT 0.0,                       -- Profit/loss (positive = profit, negative = loss)
    bankroll_before REAL,                                   -- Bankroll before this bet
    bankroll_after  REAL,                                   -- Bankroll after this bet resolved
    closing_odds    REAL,                                   -- Closing odds (captured just before kickoff)
    clv             REAL,                                   -- Closing line value: implied_prob(closing) - implied_prob(placement)
    resolved_at     TEXT,                                   -- When the bet was resolved
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_bet_log_user ON bet_log(user_id);
CREATE INDEX idx_bet_log_match ON bet_log(match_id);
CREATE INDEX idx_bet_log_status ON bet_log(status);
CREATE INDEX idx_bet_log_date ON bet_log(date);
CREATE INDEX idx_bet_log_type ON bet_log(bet_type);

-- ============================================================
-- MODEL_PERFORMANCE
-- Aggregated model performance metrics, calculated periodically
-- ============================================================
CREATE TABLE model_performance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name      TEXT NOT NULL,
    period_type     TEXT NOT NULL                           -- 'daily', 'weekly', 'monthly', 'season', 'all_time', 'backtest'
        CHECK (period_type IN ('daily', 'weekly', 'monthly', 'season', 'all_time', 'backtest')),
    period_start    TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    total_predictions INTEGER NOT NULL,
    brier_score     REAL,                                   -- Mean squared error of probability predictions
    roi             REAL,                                   -- Return on investment for this period
    avg_clv         REAL,                                   -- Average closing line value
    calibration_json TEXT,                                  -- JSON: {"0.5-0.55": {"predicted": 0.525, "actual": 0.51, "count": 40}, ...}
    win_rate_1x2    REAL,                                   -- Win rate on 1X2 value bets
    win_rate_ou     REAL,                                   -- Win rate on O/U value bets
    win_rate_btts   REAL,                                   -- Win rate on BTTS value bets
    computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(model_name, period_type, period_start)
);

-- ============================================================
-- PIPELINE_RUNS
-- Tracks every pipeline execution for debugging and monitoring
-- ============================================================
CREATE TABLE pipeline_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type        TEXT NOT NULL                           -- 'morning', 'midday', 'evening', 'manual', 'backtest'
        CHECK (run_type IN ('morning', 'midday', 'evening', 'manual', 'backtest')),
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT,
    status          TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed')),
    matches_scraped INTEGER DEFAULT 0,
    predictions_made INTEGER DEFAULT 0,
    value_bets_found INTEGER DEFAULT 0,
    emails_sent     INTEGER DEFAULT 0,
    error_message   TEXT,                                   -- NULL if successful
    duration_seconds REAL
);

-- ============================================================
-- WEATHER (added E14-02)
-- Match-day weather conditions from Open-Meteo API
-- ============================================================
CREATE TABLE weather (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    temperature     REAL,                                   -- Celsius
    wind_speed      REAL,                                   -- km/h
    humidity        REAL,                                   -- Percentage
    precipitation   REAL,                                   -- mm
    weather_code    INTEGER,                                -- WMO weather code
    source          TEXT NOT NULL DEFAULT 'open_meteo',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(match_id)
);

-- ============================================================
-- CLUB_ELO (added E21-01)
-- Historical Elo ratings per team per date from ClubElo API
-- ============================================================
CREATE TABLE club_elo (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id         INTEGER NOT NULL REFERENCES teams(id),
    elo_rating      REAL NOT NULL,
    rank            INTEGER,
    rating_date     TEXT NOT NULL,                          -- ISO date YYYY-MM-DD
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(team_id, rating_date)
);

-- ============================================================
-- TEAM_MARKET_VALUES (added E15-03)
-- Squad market value snapshots from Transfermarkt Datasets
-- ============================================================
CREATE TABLE team_market_values (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id         INTEGER NOT NULL REFERENCES teams(id),
    squad_total_value REAL,                                 -- Total squad value in EUR
    avg_player_value REAL,                                  -- Average player value in EUR
    squad_size      INTEGER,
    contract_expiring_count INTEGER,                        -- Players with contracts expiring within 6 months
    evaluated_at    TEXT NOT NULL,                          -- Snapshot date
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(team_id, evaluated_at)
);

-- ============================================================
-- INJURY_FLAGS (added E22-02)
-- Manual absence tracking for key player injuries/suspensions
-- ============================================================
CREATE TABLE injury_flags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id         INTEGER NOT NULL REFERENCES teams(id),
    player_name     TEXT NOT NULL,
    status          TEXT NOT NULL                           -- 'out', 'doubt', 'suspended'
        CHECK (status IN ('out', 'doubt', 'suspended')),
    estimated_return TEXT,
    impact_rating   REAL NOT NULL DEFAULT 0.5,             -- 0.0 to 1.0 (0.3=rotation, 0.5=starter, 0.7=key, 1.0=star)
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### Enum Values Reference

**market_type:** `1X2` (match result), `OU25` (over/under 2.5 goals), `OU15` (over/under 1.5), `OU35` (over/under 3.5), `BTTS` (both teams to score), `AH` (Asian handicap)

**selection for 1X2:** `home`, `draw`, `away`
**selection for OU:** `over`, `under`
**selection for BTTS:** `yes`, `no`
**selection for AH:** `home_-0.5`, `home_-1.0`, `home_-1.5`, `home_+0.5`, `home_+1.0`, `home_+1.5`, `away_-0.5`, `away_-1.0`, `away_-1.5`, `away_+0.5`, `away_+1.0`, `away_+1.5`

**bet status:** `pending` (match not yet played), `won`, `lost`, `void` (match cancelled), `half_won` / `half_lost` (for Asian handicap pushes)

**confidence:** `high` (edge >= 10%), `medium` (edge 5–10%), `low` (edge < 5%)

---

## §7 — Internal Pipeline API

BetVector does not have a REST API — it's a pipeline, not a web service. However, each module exposes a Python interface. These are the contracts between modules.

### Scraper Interface

All scrapers inherit from `BaseScraper` and implement:

```python
class BaseScraper(ABC):
    def scrape(self, league_config: dict, season: str) -> pd.DataFrame:
        """Download and parse data for one league-season. Returns a clean DataFrame."""

    def save_raw(self, data: pd.DataFrame, filename: str) -> Path:
        """Save raw data to data/raw/ for reproducibility."""
```

**FootballDataScraper.scrape()** returns a DataFrame with columns:
`date, home_team, away_team, home_goals, away_goals, home_ht_goals, away_ht_goals, B365H, B365D, B365A, PSH, PSD, PSA, AvgH, AvgD, AvgA, Avg>2.5, Avg<2.5, ...`

**FBrefScraper.scrape()** returns a DataFrame with columns:
`date, team, opponent, is_home, xg, xga, shots, shots_on_target, possession, passes_completed, passes_attempted`

### Feature Engineer Interface

```python
class FeatureEngineer:
    def compute_features(self, match_id: int) -> dict:
        """Compute all features for a specific match. Returns dict with home and away feature sets."""

    def compute_all_features(self, league_id: int, season: str) -> pd.DataFrame:
        """Compute features for all matches in a league-season. Returns DataFrame ready for model training."""
```

Returns a DataFrame where each row is a match with columns:
`match_id, home_form_5, home_form_10, home_goals_scored_5, ..., away_form_5, away_form_10, ..., h2h_home_wins, ..., home_rest_days, away_rest_days, matchday`

### Model Interface

All models inherit from `BaseModel` and implement:

```python
class BaseModel(ABC):
    @property
    def name(self) -> str: ...
    @property
    def version(self) -> str: ...

    def train(self, features: pd.DataFrame, results: pd.DataFrame) -> None:
        """Train the model on historical data."""

    def predict(self, features: pd.DataFrame) -> list[MatchPrediction]:
        """Generate predictions for matches. Each prediction includes the scoreline matrix."""

    def save(self, path: Path) -> None: ...
    def load(self, path: Path) -> None: ...
```

**MatchPrediction** dataclass:
```python
@dataclass
class MatchPrediction:
    match_id: int
    model_name: str
    model_version: str
    predicted_home_goals: float      # Lambda for home Poisson
    predicted_away_goals: float      # Lambda for away Poisson
    scoreline_matrix: list[list[float]]  # 7x7 matrix of probabilities
    prob_home_win: float
    prob_draw: float
    prob_away_win: float
    prob_over_25: float
    prob_under_25: float
    prob_over_15: float
    prob_under_15: float
    prob_over_35: float
    prob_under_35: float
    prob_btts_yes: float
    prob_btts_no: float
```

### Value Finder Interface

```python
class ValueFinder:
    def find_value_bets(self, match_id: int, edge_threshold: float = 0.05) -> list[ValueBet]:
        """Compare model predictions to bookmaker odds. Return value bets above threshold."""
```

**ValueBet** dataclass:
```python
@dataclass
class ValueBet:
    match_id: int
    bookmaker: str
    market_type: str
    selection: str
    model_prob: float
    bookmaker_odds: float
    implied_prob: float
    edge: float
    expected_value: float
    confidence: str          # 'high', 'medium', 'low'
    explanation: str         # Human-readable reason
```

### Bankroll Manager Interface

```python
class BankrollManager:
    def calculate_stake(self, user_id: int, model_prob: float, odds: float) -> float:
        """Calculate stake based on user's staking method and current bankroll."""

    def check_safety_limits(self, user_id: int) -> dict:
        """Check if any safety limits are triggered. Returns dict of limit statuses."""

    def log_bet(self, user_id: int, value_bet: ValueBet, stake: float, bet_type: str) -> int:
        """Log a bet. Returns bet_log id."""

    def resolve_bet(self, bet_log_id: int, result: str) -> None:
        """Resolve a bet and update bankroll."""
```

### Pipeline Orchestrator

```python
class Pipeline:
    def run_morning(self) -> PipelineResult:
        """Full pipeline: scrape → features → predict → find value → email."""

    def run_midday(self) -> PipelineResult:
        """Odds update: re-fetch odds → re-calculate edges → update dashboard."""

    def run_evening(self) -> PipelineResult:
        """Results: scrape results → resolve bets → P&L → evening email."""

    def run_backtest(self, league: str, season: str) -> BacktestResult:
        """Walk-forward backtest on historical data."""
```

---

## §8 — Design System

BetVector uses a dark trading terminal aesthetic — inspired by Bloomberg Terminal, TradingView, and Betfair Exchange. Information-dense, data-first, minimal decoration. The design communicates precision and discipline.

### Colour Palette

| Name | Hex | Usage |
|------|-----|-------|
| Background | `#0D1117` | Main background (near-black with blue undertone) |
| Surface | `#161B22` | Cards, panels, elevated surfaces |
| Surface Hover | `#1C2333` | Hovered cards and rows |
| Border | `#30363D` | Borders between sections and cards |
| Text Primary | `#E6EDF3` | Main body text (high contrast on dark bg) |
| Text Secondary | `#8B949E` | Labels, captions, secondary info |
| Text Muted | `#484F58` | Disabled text, subtle separators |
| Accent Green | `#3FB950` | Positive values: profit, wins, edges, "value bet" badges |
| Accent Red | `#F85149` | Negative values: losses, drawdowns, warnings |
| Accent Yellow | `#D29922` | Caution: medium confidence, approaching limits |
| Accent Blue | `#58A6FF` | Links, interactive elements, model indicators |
| Accent Purple | `#BC8CFF` | Ensemble/combined metrics, special highlights |
| Row Even | `#0D1117` | Alternating table row (same as bg) |
| Row Odd | `#161B22` | Alternating table row (same as surface) |

### Typography

**Primary font:** `JetBrains Mono` — monospace font that reinforces the terminal/quant aesthetic. Used for data tables, numbers, odds, probabilities, and code-like elements. Load from Google Fonts.

**Secondary font:** `Inter` — clean sans-serif for body text, labels, and explanatory copy. Load from Google Fonts.

| Element | Font | Size | Weight | Colour |
|---------|------|------|--------|--------|
| Page title | Inter | 24px | 700 | `#E6EDF3` |
| Section heading | Inter | 18px | 600 | `#E6EDF3` |
| Card heading | Inter | 15px | 600 | `#E6EDF3` |
| Body text | Inter | 14px | 400 | `#E6EDF3` |
| Label / caption | Inter | 12px | 400 | `#8B949E` |
| Data value (large) | JetBrains Mono | 28px | 700 | `#E6EDF3` |
| Data value (table) | JetBrains Mono | 14px | 400 | `#E6EDF3` |
| Positive number | JetBrains Mono | inherit | inherit | `#3FB950` |
| Negative number | JetBrains Mono | inherit | inherit | `#F85149` |
| Badge text | Inter | 11px | 600 | `#0D1117` (on coloured bg) |

### Spacing System

Base unit: 4px

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | 4px | Tight internal spacing |
| `--space-sm` | 8px | Between related elements |
| `--space-md` | 16px | Between sections within a card |
| `--space-lg` | 24px | Between cards |
| `--space-xl` | 32px | Between major page sections |
| `--space-xxl` | 48px | Page top margin |

### Component Patterns

**Cards:** Background `#161B22`, border `1px solid #30363D`, border-radius 8px, padding 16px. Cards are the primary container for all dashboard content — each metric, each match, each chart lives in a card.

**Tables:** No outer border. Row borders using `1px solid #30363D` between rows only (not columns). Alternating row colours: `#0D1117` and `#161B22`. Column headers: text `#8B949E`, uppercase, 11px, weight 600, letter-spacing 0.5px. Sticky header on scroll.

**Badges:** Small coloured pills for status indicators. Green badge for "Value Bet", red for "No Edge", yellow for "Borderline". Border-radius 4px, padding 2px 8px.

**Confidence indicators:** Three-tier system based on edge size:
- 🟢 High confidence (edge >= 10%): Green accent `#3FB950`
- 🟡 Medium confidence (edge 5–10%): Yellow accent `#D29922`
- 🔴 Low confidence / no value (edge < 5%): Red accent or muted `#484F58`

**Charts (Plotly):** Dark theme with transparent background. Grid lines in `#30363D`. Line colours: green for P&L, blue for model metrics, red for losses. Font: JetBrains Mono for axis labels and values.

**Loading states:** Skeleton screens using `#161B22` rectangles that pulse with a subtle opacity animation (0.3 → 0.7 → 0.3 over 1.5s). Not spinners — skeleton screens feel faster and communicate layout before data arrives.

**Empty states:** Centred message in `#8B949E` with a subtle icon. Always include a call to action or explanation: "No matches today. Check back tomorrow, or explore league stats in the League Explorer."

**Error states:** Red border on the card that errored. Error message in `#F85149`. Suggestion for what to do: "Failed to fetch odds. This usually means the API rate limit was hit. The system will retry at the next scheduled run."

### Mobile Responsiveness

The dashboard is designed mobile-first for iPhone (375px width) and scales up to desktop.

**Mobile (< 768px):**
- Single-column layout
- Bottom tab navigation (5 tabs: Picks, Performance, Leagues, Health, Settings)
- Cards stack vertically
- Tables scroll horizontally
- Charts resize to full-width

**Desktop (>= 768px):**
- Sidebar navigation on the left (collapsible)
- Multi-column layouts where appropriate (2 metric cards side by side)
- Tables display all columns without scrolling
- Charts at comfortable reading width

---

## §9 — Revenue Model

BetVector is not a revenue-generating product. It is a personal tool. There are no pricing tiers, no billing, no subscriptions, and no paywall.

The "revenue model" is the return on the owner's betting bankroll — if the system generates consistent positive ROI, that is the financial return.

**Cost to operate:** $0/month (all free services)
**Potential future costs if scaling:** $30–50/month for paid odds API, $25/month for Supabase Pro, $5–10/month for VPS. Total worst case: ~$85/month, justified only if the system is generating significantly more than that in betting profit.

**If the system is ever offered to others:** A simple subscription model (e.g., $20/month for dashboard access with own bankroll tracking) could be considered, but this is speculative and not in scope.

---

## §10 — GTM Strategy

There is no GTM strategy. BetVector is a personal tool built for one user. It is not launched publicly. There is no landing page, no marketing, no user acquisition.

**If sharing with friends:** Direct invite via a shared dashboard link. No public discovery, no SEO, no social presence.

**If ever considering a public offering:** The track record (months of verified positive CLV, transparent bet history) would be the marketing. The category would be "quantitative betting tools" (not "tipster service", not "prediction app"). But this is a distant future consideration and not in the current scope.

---

## §11 — Self-Improvement Engine

BetVector is designed to get smarter over time — not just because it accumulates more training data, but because it actively monitors its own performance and adjusts. This section specifies five self-improvement capabilities, each with explicit guardrails to prevent overreaction to small samples or noise.

**The core philosophy: be cautious.** Every automatic adjustment requires a minimum sample size, changes gradually rather than abruptly, and is fully transparent in the dashboard. The system never makes a dramatic change silently. If it recalibrates, adjusts weights, or changes its assessment of a league, the Model Health page shows exactly what changed and why.

### 11.1 — Automatic Recalibration

**What it does:** Monitors whether predicted probabilities match actual outcomes. If the model's "70% predictions" are only winning 60% of the time, it applies a statistical correction (Platt scaling or isotonic regression via scikit-learn) to bring probabilities back in line with reality.

**When it runs:** After every 200 resolved predictions (not on a time schedule — on a prediction count schedule). This ensures there's always enough data for a meaningful recalibration.

**Guardrails:**
- **Minimum sample size:** 200 resolved predictions before any recalibration is applied. Below this, the raw model probabilities are used uncorrected.
- **Significance threshold:** Recalibration only applies if the mean absolute calibration error exceeds 3 percentage points. Small deviations are expected and don't warrant correction.
- **Rollback protection:** The system always stores both the raw model probability and the calibrated probability. If a recalibration makes things worse (measured over the next 100 predictions), it automatically reverts to the previous calibration.
- **Transparency:** The Model Health dashboard page shows a before/after calibration plot whenever a recalibration is applied, with a timestamp and the sample size it was based on.

**Database impact:** The `predictions` table already stores model probabilities. A new `calibration_history` table (see §6 addendum below) stores each calibration event with its parameters and performance impact.

### 11.2 — Dynamic Feature Importance Tracking

**What it does:** After each model training cycle, logs which features contributed most to predictions (using XGBoost/LightGBM's built-in feature importance via "gain" method). Over time, builds a history of how feature importance shifts — revealing whether certain signals are becoming more or less useful.

**When it runs:** Every time a gradient boosting model (XGBoost or LightGBM) is trained. Poisson model doesn't have native feature importance in the same way, so this applies only to tree-based models.

**Guardrails:**
- **No automatic feature removal.** The system never drops a feature on its own. It reports importance trends in the Model Health dashboard and flags features whose importance has dropped below 1% for 3+ consecutive training cycles, with a suggestion: "Consider removing [feature] — it has contributed less than 1% importance for the last 3 months."
- **Human decision required.** Feature changes are manual. The system informs, the owner decides.
- **Baseline comparison.** Feature importance is always shown relative to a baseline (the importance at the time the feature was first added), so you can see trends rather than just snapshots.

**Dashboard display:** A "Feature Importance" card on the Model Health page showing a horizontal bar chart of the top 15 features, with trend arrows (↑ rising, ↓ falling, → stable) based on the last 5 training cycles.

### 11.3 — Adaptive Ensemble Weights

**What it does:** When multiple models are active (Poisson + Elo + XGBoost), the system adjusts how much weight each model gets in the ensemble prediction based on recent performance. A model that's been more accurate recently gets more weight.

**When it runs:** Weights are recalculated every 100 resolved ensemble predictions. Between recalculations, weights remain fixed.

**Guardrails:**
- **Minimum sample size:** 300 resolved predictions per model before adaptive weighting activates. Before this threshold, all models get equal weight (1/N where N = number of active models).
- **Evaluation window:** Performance is measured over the last 300 predictions, not all-time. This allows the system to adapt to changing conditions while being long enough to avoid noise.
- **Gradual adjustment:** Weights never change by more than 10 percentage points per recalculation. If the system thinks XGBoost should go from 33% to 55%, it moves it to 43% this cycle, then potentially 53% next cycle. This prevents whiplash.
- **Minimum weight floor:** No active model can drop below 10% weight. This prevents the ensemble from effectively becoming a single model, which would lose the diversification benefit.
- **Maximum weight ceiling:** No single model can exceed 60% weight. Same reason — preserve ensemble diversity.
- **Transparency:** The dashboard shows current weights, historical weight changes as a line chart, and the performance metrics that drove each change.

**Weight calculation method:** Inverse Brier score weighting. Each model's weight is proportional to (1 / Brier_score) normalised so all weights sum to 1.0, then clamped to the floor/ceiling and smoothed by the 10pp max change rule.

### 11.4 — Odds Market Feedback Loop

**What it does:** Tracks the system's performance broken down by league × market type combination. Over time, learns where BetVector has a genuine edge and where it doesn't. Surfaces these insights in the dashboard so you can focus your betting on the most profitable combinations.

**When it runs:** Recalculated weekly (Sunday evening, as part of the weekly summary pipeline).

**Guardrails:**
- **Minimum sample size:** 50 resolved value bets in a specific league × market combination before any assessment is made. Below 50, the status is "Insufficient data — no assessment yet."
- **Confidence intervals:** Every ROI figure is shown with a 95% confidence interval. "EPL Over/Under 2.5: ROI +7.2% (95% CI: -1.1% to +15.5%)" tells you the edge might be real, but you can't be sure yet. "Serie A 1X2: ROI +4.8% (95% CI: +1.2% to +8.4%)" is more convincing because the entire confidence interval is positive.
- **Three-tier assessment:**
  - 🟢 **Profitable** — ROI positive AND lower bound of 95% CI is positive AND sample size >= 100. The system is confident there's a real edge here.
  - 🟡 **Promising** — ROI positive but CI includes zero, OR sample size is 50–99. More data needed before drawing conclusions.
  - ⚪ **Insufficient data** — Fewer than 50 bets. No assessment possible.
  - 🔴 **Unprofitable** — ROI negative AND upper bound of 95% CI is negative AND sample size >= 100. The system is confident there's no edge here. Consider reducing or stopping bets in this combination.
- **No automatic filtering.** The system never automatically excludes a league × market combination from value bet detection. It recommends, you decide. An unprofitable combination is flagged with a warning in the Today's Picks page: "⚠️ BetVector has historically underperformed in [EPL BTTS] (ROI: -3.2% over 120 bets). Proceed with caution."

**Dashboard display:** A "Market Edge Map" card on the Model Health page — a heatmap grid with leagues on the y-axis and market types on the x-axis, colour-coded by the three-tier assessment. Click any cell to see the detailed stats and confidence interval.

### 11.5 — Seasonal Re-training Triggers

**What it does:** Monitors model accuracy over a rolling window. If performance degrades beyond a threshold, triggers an automatic full retrain rather than waiting for the next scheduled training cycle.

**When it runs:** Checked daily as part of the evening pipeline run.

**Guardrails:**
- **Rolling window:** Brier score is monitored over the last 100 predictions. This is long enough to be meaningful but short enough to detect degradation within a few weeks.
- **Degradation threshold:** A retrain is triggered if the rolling Brier score is more than 15% worse than the model's all-time average Brier score. Example: if the all-time Brier score is 0.200 and the rolling score hits 0.230 (15% worse), a retrain fires.
- **Cooldown period:** After a retrain, no further automatic retrains for 30 days. This prevents a failing model from retraining repeatedly when the issue might be data quality or a fundamental model limitation rather than staleness.
- **Retrain on full history:** Automatic retrains use all available training data (not just recent data). This prevents overfitting to recent trends.
- **Notification:** When an automatic retrain fires, the owner receives an email alert: "🔄 BetVector auto-retrain triggered. Model [poisson_v1] Brier score degraded to 0.231 (all-time average: 0.200). Retraining on full dataset. New model will be active for tomorrow's predictions."
- **Performance comparison:** After retrain, the system runs a 50-prediction evaluation comparing old vs new model. If the new model is worse, it rolls back and alerts the owner.

### Database Addendum — Self-Improvement Tables

```sql
-- ============================================================
-- CALIBRATION_HISTORY
-- Tracks every automatic recalibration event
-- ============================================================
CREATE TABLE calibration_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name      TEXT NOT NULL,
    calibration_method TEXT NOT NULL                        -- 'platt' or 'isotonic'
        CHECK (calibration_method IN ('platt', 'isotonic')),
    sample_size     INTEGER NOT NULL,                       -- Number of predictions used
    mean_abs_error_before REAL NOT NULL,                    -- Calibration error before
    mean_abs_error_after REAL NOT NULL,                     -- Calibration error after
    parameters_json TEXT NOT NULL,                          -- JSON: calibration model parameters
    is_active       INTEGER NOT NULL DEFAULT 1,             -- 1 = currently applied, 0 = superseded or rolled back
    rolled_back     INTEGER NOT NULL DEFAULT 0,             -- 1 = this calibration was rolled back
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- FEATURE_IMPORTANCE_LOG
-- Tracks feature importance over time for tree-based models
-- ============================================================
CREATE TABLE feature_importance_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name      TEXT NOT NULL,
    training_date   TEXT NOT NULL,
    feature_name    TEXT NOT NULL,
    importance_gain REAL NOT NULL,                           -- Feature importance by gain
    importance_rank INTEGER NOT NULL,                        -- Rank (1 = most important)
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_feature_importance_model ON feature_importance_log(model_name, training_date);

-- ============================================================
-- ENSEMBLE_WEIGHT_HISTORY
-- Tracks ensemble weight changes over time
-- ============================================================
CREATE TABLE ensemble_weight_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name      TEXT NOT NULL,
    weight          REAL NOT NULL,                           -- Weight assigned (0.0 to 1.0)
    brier_score     REAL NOT NULL,                           -- Brier score over evaluation window
    evaluation_window INTEGER NOT NULL,                      -- Number of predictions evaluated
    previous_weight REAL,                                    -- Weight before this change
    reason          TEXT NOT NULL,                            -- Human-readable reason for change
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- MARKET_PERFORMANCE
-- League × market performance tracking for feedback loop
-- ============================================================
CREATE TABLE market_performance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    league          TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    period_end      TEXT NOT NULL,                           -- End of evaluation period
    total_bets      INTEGER NOT NULL,
    wins            INTEGER NOT NULL,
    losses          INTEGER NOT NULL,
    total_staked    REAL NOT NULL,
    total_pnl       REAL NOT NULL,
    roi             REAL NOT NULL,
    roi_ci_lower    REAL,                                    -- 95% CI lower bound
    roi_ci_upper    REAL,                                    -- 95% CI upper bound
    assessment      TEXT NOT NULL                            -- 'profitable', 'promising', 'insufficient', 'unprofitable'
        CHECK (assessment IN ('profitable', 'promising', 'insufficient', 'unprofitable')),
    computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(league, market_type, period_end)
);
CREATE INDEX idx_market_perf_league ON market_performance(league, market_type);

-- ============================================================
-- RETRAIN_HISTORY
-- Tracks automatic and manual model retrains
-- ============================================================
CREATE TABLE retrain_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name      TEXT NOT NULL,
    trigger_type    TEXT NOT NULL                            -- 'automatic', 'manual', 'scheduled'
        CHECK (trigger_type IN ('automatic', 'manual', 'scheduled')),
    trigger_reason  TEXT NOT NULL,                            -- e.g. 'Brier score degraded to 0.231 (threshold: 0.230)'
    brier_before    REAL NOT NULL,                            -- Rolling Brier score before retrain
    brier_after     REAL,                                    -- Brier score after retrain (measured over 50 preds)
    training_samples INTEGER NOT NULL,                       -- Number of matches used for training
    was_rolled_back INTEGER NOT NULL DEFAULT 0,              -- 1 = new model was worse, rolled back
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### Architectural Decision Addendum

**Decision: Conservative self-improvement with human oversight.**
Every self-improvement capability follows the same pattern: measure performance over a statistically meaningful sample, change gradually, and never remove human control. The system recommends, surfaces data, and automates calibration — but never silently removes a feature, drops a league, or radically shifts model weights. The owner always sees what changed and can override any automatic decision. This philosophy — "intelligent but cautious" — is the guardrail that prevents the system from outsmarting itself.

---

## §12 — Glossary of Betting Concepts

This section exists because the owner is learning betting concepts as they build. Every term used in the system is defined here for reference.

**Value bet:** A bet where your estimated probability of the outcome is higher than the bookmaker's implied probability. You don't need to think the team will win — you need to think the price is wrong.

**Implied probability:** The probability a bookmaker's odds suggest. Calculated as 1 / decimal_odds. Odds of 2.00 imply a 50% chance. Odds of 1.50 imply 66.7%.

**Overround (vig/margin):** The bookmaker's profit margin. In a fair market, probabilities sum to 100%. Bookmakers set odds so implied probabilities sum to 105–110%. The extra 5–10% is their guaranteed profit. Example: a coin flip should be 50/50 (total 100%). A bookmaker might offer 1.90 for heads and 1.90 for tails. Implied probs: 52.6% + 52.6% = 105.2%. That extra 5.2% is the overround.

**Edge:** The difference between your model's probability and the bookmaker's implied probability. Edge = model_prob - implied_prob. A positive edge means you think the bet is underpriced.

**Expected Value (EV):** The average profit per bet over many repetitions. EV = (model_prob × odds) - 1. Positive EV means the bet is profitable long-term.

**Closing Line Value (CLV):** Whether you got better odds than the closing line (the final odds before kickoff). If you bet at 2.10 and the odds closed at 1.95, you got positive CLV. CLV is the single best predictor of long-term profitability — even more reliable than short-term results, which are dominated by variance.

**Bankroll:** The total amount of money set aside for betting. It is ring-fenced money you can afford to lose entirely.

**Flat staking:** Betting the same amount on every bet, typically 1–3% of bankroll. Simple, low variance, easy to track.

**Kelly Criterion:** A formula that calculates the optimal bet size based on your edge and the odds. Formula: stake_fraction = (model_prob × odds - 1) / (odds - 1). Full Kelly is aggressive; fractional Kelly (quarter or half) reduces variance at the cost of slower growth.

**Drawdown:** The decline from your bankroll's peak to its current value. A 25% drawdown means your bankroll has dropped 25% from its highest point. This is normal even with a winning edge — variance causes temporary losing streaks.

**Brier score:** A measure of prediction accuracy. Calculated as the mean squared difference between predicted probabilities and actual outcomes (0 or 1). Lower is better. 0 is perfect. A Brier score of 0.25 is no better than random for binary outcomes. Professional sports bettors typically achieve 0.19–0.22.

**Calibration:** Whether your probabilities match reality. If you predict "60% chance" for 100 events, about 60 should happen. A calibration plot shows predicted probability on the x-axis and actual frequency on the y-axis. A well-calibrated model follows the diagonal line.

**xG (Expected Goals):** A metric that measures the quality of goal-scoring chances. Each shot is assigned a probability based on location, angle, body part, and match situation. A team's xG for a match is the sum of all their shot probabilities. xG is more predictive of future performance than actual goals because it's less affected by luck.

**Poisson distribution:** A probability distribution that models how many times a rare event occurs in a fixed interval. In football, it models how many goals a team scores in a match. If a team's expected goals (lambda) is 1.5, the Poisson distribution tells you: P(0 goals) = 22.3%, P(1 goal) = 33.5%, P(2 goals) = 25.1%, P(3 goals) = 12.6%, etc.

**Asian Handicap:** A market that applies a goal handicap to one team. Example: Arsenal -1.5 means Arsenal must win by 2+ goals for the bet to win. Half-goal handicaps eliminate the possibility of a draw. Whole-goal handicaps can result in a "push" (bet returned).

**Walk-forward validation:** A backtesting method for time-series data. Train the model on data up to date T, predict date T+1, then advance T forward. This simulates real-world usage where you only have historical data when making predictions. It's the only valid backtesting approach for sports prediction — random train/test splits would leak future information.

---

## §13 — Post-Launch Pivots and Data Source Evolution

This section documents what happened after the initial 45-issue build was completed in March 2026. The original 12 sections above remain untouched — they describe the system as it was designed and built. This section describes how the system evolved once it met reality.

### 13.1 — What We Planned vs What Happened

The original data architecture (§5) relied on three sources:

1. **Football-Data.co.uk** for historical match results and betting odds
2. **FBref** (via `soccerdata`) for advanced team statistics (xG, shots, possession)
3. **API-Football** (free tier) for upcoming fixtures, live odds, and injuries

Within weeks of launch, two of these three sources failed:

- **FBref lost all advanced statistics permanently** when Opta terminated its data agreement in January 2026. Cloudflare had already been blocking automated access during the build phase (E3-03 handled this gracefully), but the Opta departure meant there was nothing to scrape even if access were restored. FBref now only has basic results — goals, cards — which Football-Data.co.uk already provides.

- **API-Football's free tier only covers seasons 2022–2024.** The current 2025-26 season returns an explicit error: *"plan: Free plans do not have access to this season, try from 2022 to 2024."* The Pro tier at $19/month would unlock current data, but the project philosophy (§9) prioritises free sources first.

- **Football-Data.co.uk remained reliable** for historical data but revealed a freshness limitation: its CSV files only update twice per week (Sunday and Wednesday nights). On a Monday or Thursday, match results could be up to 5 days stale — unacceptable for a system that promises daily picks.

### 13.2 — Pivots Taken (E14 — Completed)

**E14 — Real-Time Data Sources** was executed as the first post-launch epic. Four issues, all completed:

**E14-01: Understat xG Scraper.** Replaced FBref as the primary xG source. Built `src/scrapers/understat_scraper.py` using the `understatapi` Python package. Understat provides match-level xG and xGA for the top 6 European leagues since 2014/15. No Cloudflare blocking, no API key needed, no Selenium required. Team name mapping with fuzzy fallback handles naming differences. 262 xG stat rows loaded for EPL 2025-26 on first run.

**E14-02: Open-Meteo Weather Scraper.** Added weather as a new feature dimension — heavy rain, strong wind, and extreme temperatures can materially affect match outcomes, particularly goals markets. Built `src/scrapers/weather_scraper.py` using the Open-Meteo free API (no key required). Fetches match-day temperature, wind speed, humidity, precipitation, and WMO weather code for each fixture based on stadium coordinates stored in a new `config/stadiums.yaml` file. Weather data is stored in a new `weather` database table. 35 weather records loaded on first run.

**E14-03: API-Football Scraper.** Code-complete but dormant. Built `src/scrapers/api_football.py` with full support for fixtures, odds (with bookmaker ID mapping), and injuries endpoints. Rate budget tracking reads `x-ratelimit-requests-remaining` from response headers. The scraper works correctly against historical data (2022–2024 seasons) but returns empty DataFrames gracefully for the current season due to the free tier restriction. Ready to activate when budget allows or if the free tier expands.

**E14-04: Pipeline and Loader Integration.** Wired all three new scrapers into the pipeline. Added 6 new loader functions to `src/scrapers/loader.py`. Parameterised `_insert_odds()` to accept a configurable source string (was hardcoded to `"football_data"`). Integrated all 3 scrapers into morning/midday/evening pipeline steps — each wrapped in try/except so failure of any individual scraper never blocks the pipeline. Updated all 3 GitHub Actions workflows with inline DB migrations for the new `weather` table and `teams.api_football_name` column.

### 13.3 — Bug Fixes Applied Post-Launch

Two bugs were discovered and fixed during E14 work:

- **`db.py` `st.secrets` crash.** When the pipeline ran outside Streamlit (CLI, GitHub Actions), accessing `st.secrets` crashed with a `FileNotFoundError`. Fixed with a guard that checks for the existence of `.streamlit/secrets.toml` before attempting to read Streamlit secrets. Root cause: the database connection code tried to read Streamlit secrets unconditionally, but secrets are only available inside a running Streamlit app.

- **ConfigNamespace integer key TypeError.** YAML config with integer keys (e.g., `1: "Bet365"` in the API-Football bookmaker map) caused a `TypeError` because Python's `setattr()` requires string attribute names. BetVector's `ConfigNamespace` class uses `setattr()` to convert YAML dicts into attribute-accessible objects. Fixed by quoting all numeric keys as strings in `config/settings.yaml` (e.g., `"1": "Bet365"`).

### 13.4 — E15 — Data Freshness and Feature Expansion (Completed)

**E15-01: Football-Data.org API Scraper.** Built `src/scrapers/football_data_org.py` using the free REST API (separate from Football-Data.co.uk). Provides current-season EPL fixtures and results in near real-time. 10 requests/minute on the free tier, authentication via `X-Auth-Token` header. Closes the freshness gap left by Football-Data.co.uk's twice-weekly CSV updates.

**E15-02: Understat Scraper Expansion.** Extended the existing Understat scraper to parse the richer data already available in the API response — NPxG (non-penalty expected goals), NPxGA, PPDA (pressing intensity), PPDA allowed, shots, key passes, deep completions, and deep completions allowed. Added corresponding columns to the `UnderstatTeamStats` model. All stored per-match per-team in `match_stats`.

**E15-03: Transfermarkt Datasets Integration.** Built `src/scrapers/transfermarkt.py` using public CSV dumps from `dcaribou/transfermarkt-datasets` on Cloudflare R2 CDN (CC0 license). Downloads `players.csv.gz`, filters to EPL, aggregates player-level data to team-level snapshots: squad total value, average player value, squad size, contract expiring count. Stored in the `team_market_values` table. Team name mapping with fuzzy fallback handles Transfermarkt → canonical name differences.

### 13.5 — Lessons Learned

1. **Free data sources are fragile.** FBref's Opta data vanishing overnight proved that any external dependency can disappear without warning. The modular scraper architecture (§5) paid for itself immediately — swapping FBref for Understat required no changes to the feature engine, model, or dashboard.

2. **Freshness matters more than volume.** Football-Data.co.uk has 20+ years of historical odds data — invaluable for backtesting — but its twice-weekly update schedule makes it unreliable as a sole source for daily operations. A near-real-time source for fixtures and results is essential even if it provides less data per record.

3. **Free tier APIs are marketing funnels, not infrastructure.** API-Football's free tier is deliberately limited to historical seasons to drive upgrades. Building the scraper was still worthwhile (the code is ready when the budget allows), but free tiers should never be the sole source for critical pipeline functionality.

4. **Pipeline resilience was the right bet.** The standing constraint in CLAUDE.md Rule 6 — *"If one step in the pipeline fails, log the error and continue to the next step"* — meant that FBref dying, API-Football returning empty, and even Understat having occasional timeouts never prevented predictions from being generated with whatever data was available. Defensive programming at the scraper level prevented cascading failures.

### 13.6 — E16 — Advanced Feature Engineering (Completed)

E14 and E15 added four new data sources — Understat advanced stats (NPxG, PPDA, deep completions), Open-Meteo weather, Football-Data.org API, and Transfermarkt squad market values. All were scraped and stored in the database, but none reached the prediction model. The feature engineering layer only computed rolling averages for basic stats (goals, xG, shots, possession). This was the largest untapped improvement available.

**E16-01: Rolling Advanced Stats Features.** Extended `src/features/rolling.py` to read NPxG, NPxGA, PPDA coefficient, PPDA allowed coefficient, deep completions, and deep completions allowed from `match_stats`. Added 14 new columns to the `Feature` model (7 per rolling window): `npxg_5/10`, `npxga_5/10`, `npxg_diff_5/10`, `ppda_5/10`, `ppda_allowed_5/10`, `deep_5/10`, `deep_allowed_5/10`. Updated the Poisson model to include `npxg_5` (attack) and `npxga_5` (defence) — NPxG is strictly more predictive than raw xG because it strips out penalty xG which converts at ~76% regardless of team quality.

**E16-02: Market Value and Weather Features.** Added two new functions to `src/features/context.py`: `calculate_market_value_features()` queries the most recent Transfermarkt snapshot on or before the match date (temporal integrity) and returns market value ratio (capped at 10.0) and squad value log; `calculate_weather_features()` queries the weather table and returns temperature, wind speed, precipitation, and a binary heavy-weather flag. Added 6 new columns to the Feature model. Updated the Poisson model to include `market_value_ratio` and `is_heavy_weather` as context features.

**E16-03: Feature Recomputation and Validation.** Added `force_recompute` parameter to `compute_all_features()` to re-run feature computation for all matches even when feature rows already exist. Recomputed all 281 EPL 2025-26 matches: 271/281 have NPxG/PPDA/deep data (from Understat), 35/281 have weather data, 4/281 have market value data. Walk-forward backtest on 2025-26: ROI -7.2%, Brier score 0.6903, 705 value bets from $10,704 staked. The model now has access to up to 17 candidate features per GLM (up from 12). Feature coverage will improve as more weather and market value data accumulates.

**Key design decisions:**
- NPxG over raw xG in the model — strips out penalty xG for purer open-play signal
- Market value ratio (not raw value) — the relative advantage matters more than absolute wealth
- Weather as binary flag — complex non-linear weather effects simplified to a clean signal
- `evaluated_at <= match_date` for market values — weekly snapshots are static and independent of match results, making same-day comparisons temporally safe
- Graceful degradation everywhere — all 20 new features default to None, model handles via `fillna(mean).fillna(0.0)` and constant-column dropping

### 13.7 — E17 — Dashboard Feature Surfacing (Completed)

E16 added 20 new features to the prediction model (NPxG, PPDA, deep completions, market value, weather) but none were visible on the dashboard. Users could see predictions but had no insight into *why* the model favoured one team. This epic surfaced the new data across every relevant dashboard page.

**E17-01: Match Deep Dive Enhancements.** Expanded the Match Deep Dive page with three new sections: advanced stats comparison (NPxG, PPDA, deep completions as bar charts), market value comparison (squad total values with ratio indicator), and weather conditions (temperature, wind, precipitation with a heavy-weather warning badge). All data pulled from Feature records via the match's team IDs.

**E17-02: Today's Picks Weather & Market Value Indicators.** Added compact badges to Today's Picks cards — a weather icon with temperature when heavy weather is flagged, and a squad value ratio indicator when the difference exceeds 2×. These give at-a-glance context without cluttering the pick card layout.

**E17-03: League Explorer NPxG Rankings.** Added an NPxG-based team rankings section to the League Explorer page — parallel to the existing xG rankings but using non-penalty expected goals, which strips out the noise of penalty kicks. Fixed hardcoded season defaults across the page so it always loads the current season.

**E17-04: Fixtures Page.** New standalone page showing all upcoming scheduled matches with date, time, and venue. Value picks are highlighted with the model's edge percentage. Each fixture links to its Match Deep Dive page for full analysis. This replaced the old pattern of embedding upcoming matches in the Today's Picks page.

### 13.8 — E18 — Match Narrative & Data Quality (Completed)

The dashboard could display numbers but couldn't explain them. A user seeing "Model: 62% Home Win" had no way to understand *what drove that prediction* — form, xG trends, venue advantage, squad value gap, or pressing intensity. Meanwhile, critical data quality issues (missing kickoff times, features not computed for scheduled matches) undermined the production pipeline.

**E18-01: Match Analysis Narrative.** Created `src/delivery/narrative.py` — an algorithmic narrative engine that synthesises raw model output into plain-English paragraphs. Eight factor generators examine form trends, xG quality gaps, venue strength, H2H records, squad market value differences, pressing intensity (PPDA), weather conditions, and rest day advantages. Each factor contributes a sentence only when the signal is meaningful (e.g., PPDA only mentioned when a team's pressing intensity is >2σ from league average). The output reads like a human analyst's pre-match briefing.

**E18-02: Kickoff Time Fix.** The Football-Data.org API returned full datetime strings but the loader was discarding the time component, causing all fixtures to display "TBD" on the dashboard. Fixed `load_api_football_fixtures()` to parse and store the full ISO 8601 timestamp including time zone offset.

**E18-03: Scheduled Match Feature Computation.** The feature engineering pipeline only processed matches with `status='FT'` (finished). Upcoming matches had no Feature rows, so predictions couldn't run. Extended `compute_all_features()` to include `status='scheduled'` matches, using opponent-specific lookback queries that respect temporal integrity (only completed matches before the scheduled date).

**E18-04: Match Deep Dive Glossary.** Added a collapsible glossary panel to the Match Deep Dive page with 28 definitions organised into 7 categories: Form, xG, Pressing, Model, Market Probabilities, Value, and Squad metrics. Definitions are written for a betting novice learning quantitative concepts (per MP §12 philosophy).

**E18-05: Deep Dive from Today's Picks.** Added a "Deep Dive →" button on each pick card that navigates directly to the full Match Deep Dive page for that fixture. Previously, users had to navigate through League Explorer to find individual matches.

**E18-06: Today's Picks Glossary + TBD Cleanup.** Added a context-specific glossary to the Picks page explaining value bet concepts (edge, EV, Kelly fraction). Cleaned up the "TBD" display — when kickoff time is unknown, the card now shows just the date without a misleading time placeholder.

### 13.9 — E19 — Live Odds Pipeline (Completed)

BetVector's sole odds source — Football-Data.co.uk CSV files — updated only twice per week, creating a 2–7 day freshness gap. Matches beyond the CSV's last update had zero odds data, meaning zero value bets could be identified. This epic integrated a live odds API, extracted additional data from existing CSV columns, and completed the CLV tracking infrastructure.

**E19-01: The Odds API Scraper.** Built `src/scrapers/odds_api.py` (TheOddsAPIScraper) using the free tier of The Odds API — 500 requests/month, with EPL 3×/day pipeline needing only ~90 requests/month. A single API call returns odds from 50+ bookmakers (Pinnacle, Bet365, FanDuel, DraftKings, William Hill, etc.) for all upcoming EPL matches. Includes team name normalisation map (Odds API uses display names like "Arsenal" → canonical "Arsenal"), bookmaker name mapping, and API budget tracking via `x-requests-remaining` response header. Config: `settings.yaml` section for API key env var, regions, and markets.

**E19-02: Odds Loader + Pipeline Integration.** New loader function `load_odds_the_odds_api()` with idempotent upsert (dedup on match_id + bookmaker + market_type + selection). Sets `is_opening=1` for first capture, `is_opening=0` for subsequent updates. Integrated into morning and midday pipeline steps — if The Odds API fails, pipeline falls back to existing CSV odds silently.

**E19-03: Extract Closing Odds + AH + Referee from CSV.** Football-Data.co.uk CSVs contain columns that BetVector was ignoring: `PSCH/PSCD/PSCA` (Pinnacle closing odds), `AHh` (Asian Handicap home line), `BbAHh` (Betbrain AH market average), and `Referee`. Extended `football_data.py` to extract all of these. Closing odds stored with `is_opening=0` and `bookmaker='Pinnacle'`. AH records stored with `market_type='AH'`. Referee name stored on the Match model (`referee TEXT` column added).

**E19-04: CLV Tracking Pipeline.** The CLV infrastructure was 90% built — `BetLog` had `closing_odds` and `clv` columns (always NULL), `metrics.py` had `calculate_clv()` fully implemented, Model Health dashboard had CLV visualisation (showing empty state). The missing piece was a function to populate closing odds after matches finish. Added `backfill_closing_odds()` to the evening pipeline: for each pending BetLog entry, looks up Pinnacle closing odds and computes CLV = (bet_odds − closing_odds) / closing_odds. The existing dashboard auto-populates with real CLV data.

### 13.10 — E20 — Market-Augmented Poisson (Completed)

Academic research (Constantinou 2012, Štrumbelj 2014) shows that incorporating bookmaker odds as features yields 7–9% Brier score improvement — the single highest-impact enhancement available. This is because Pinnacle's odds embed crowd wisdom, injury information, and market sentiment that statistical models can't capture from match data alone.

**E20-01: Pinnacle Opening Odds as Features.** Added 4 new Feature columns: `pinnacle_home_prob`, `pinnacle_draw_prob`, `pinnacle_away_prob`, `pinnacle_overround`. Uses proportional overround removal: `true_prob = (1/odds) / Σ(1/all_odds)` to convert raw odds to fair probabilities. Queries Odds table for Pinnacle 1×2 records, preferring `is_opening=1`. For historical matches, uses PSH/PSD/PSA from CSV. For upcoming matches, uses latest Odds API fetch. 1,180 of 1,520 Feature rows backfilled from CSV data.

**E20-02: Asian Handicap Line as Feature.** Added `ah_line` Feature column — the Asian Handicap home line (e.g., -0.5, -1.0) is the sharpest market-implied strength difference available. The line itself IS the feature — no conversion needed. Queried from Odds table with market_type='AH', preferring Pinnacle, falling back to market average.

**E20-03: Backtest Market-Augmented vs Base Poisson.** Walk-forward backtest on EPL 2024-25 (380 matches): Brier score 0.6105 (unchanged — Poisson GLM is limited in exploiting non-linear odds features), but ROI improved from -4.15% to -3.50% (+0.65pp). The odds features helped value detection more than probability calibration. The Brier-unchanged result confirmed the Poisson GLM architecture is near its ceiling — further improvement requires more training data (E23) or non-linear models (future XGBoost ensemble).

### 13.11 — E21 — External Ratings & Context (Completed)

Three context signals that don't exist in match statistics: long-term team quality (Elo ratings — especially valuable for promoted teams with no top-flight history), referee tendencies (some referees consistently produce higher-scoring matches), and fixture congestion (teams playing every 3 days underperform).

**E21-01: ClubElo Scraper + Elo Features.** Built `src/scrapers/clubelo_scraper.py` using the free ClubElo API (`http://api.clubelo.com/{YYYY-MM-DD}` — no auth, no rate limit). Returns Elo ratings for all clubs on any given date. New `ClubElo` ORM model with UniqueConstraint on `(team_id, rating_date)`. Two new Feature columns: `elo_rating` (team's absolute Elo) and `elo_diff` (team Elo minus opponent Elo). Elo is particularly valuable early in the season for promoted teams — they have zero top-flight form data but Elo captures their Championship strength. Integrated into morning pipeline. 4,738 records backfilled for 2024-25 and 2025-26.

**E21-02: Referee Features.** Four new Feature columns computed from referee history: `ref_avg_fouls`, `ref_avg_yellows`, `ref_avg_goals`, `ref_home_win_pct`. Uses a lookback of the referee's last 20 EPL matches (minimum 5 required, otherwise NULL). Only `ref_avg_goals` and `ref_home_win_pct` were added to the Poisson model — fouls and yellows don't directly predict goals. The referee features are most impactful for Over/Under and BTTS markets where the officiating environment affects goal-scoring.

**E21-03: Fixture Congestion Flag.** Two new Feature columns: `days_since_last_match` (integer, any competition) and `is_congested` (binary: 1 if <4 days since last match). The 4-day threshold comes from sports science research (Carling et al. 2015) showing significant performance drops in European football when rest is under 4 days. 155 of 1,520 historical Feature rows flagged as congested (~10% — aligns with expected rate for teams in European competitions).

### 13.12 — E22 — Advanced Features (Completed)

Two specialised features: decomposing expected goals by situation type (set pieces vs open play — different predictive profiles), and a manual injury input system for when key players are absent.

**E22-01: Set-Piece xG Breakdown.** Extended the Understat scraper to fetch shot-level data with `situation` field (OpenPlay, SetPiece, FromCorner, Counter). New MatchStat columns: `set_piece_xg` and `open_play_xg`. New Feature columns: `set_piece_xg_5` and `open_play_xg_5` (5-match rolling averages). Set-piece xG is distinctly predictive because set-piece proficiency is more repeatable than open-play quality (lower variance season-to-season). A team strong at set pieces but weak in open play has a different risk profile than the reverse.

**E22-02: Injury Impact Flags (Manual Input).** New `InjuryFlag` ORM model with fields: `team_id`, `player_name`, `status` (out/doubt/suspended), `estimated_return`, and `impact_rating` (0.0–1.0 scale: 0.3 rotation player, 0.5 regular starter, 0.7 key player, 1.0 star player). New Feature columns: `injury_impact` (sum of impact_ratings for "out" players) and `key_player_out` (binary: 1 if any player with rating ≥0.7 is out). Settings page UI allows manual entry until API-Football Pro ($20/month) auto-populates from their injuries endpoint.

### 13.13 — E23 — Historical Data Backfill & Model Revalidation (Completed)

The model trained on just 2 seasons (760 matches) — a dangerously small sample for a Poisson GLM with 17+ features. Overfitting risk was high, and the model had never seen promoted teams that aren't in the current EPL. This epic tripled the training data to 6 seasons (~2,280 matches) and revalidated model performance.

**E23-01: Load Historical Match Data + Odds.** Downloaded Football-Data.co.uk CSV files for 4 additional seasons (2020-21 through 2023-24). Loaded 1,520 new Match records with full result data, plus 22,800 Odds records (Pinnacle opening/closing, Asian Handicap, and referee data). Uses the same loader functions as the live pipeline — just pointed at historical CSV files.

**E23-02: Backfill Understat xG + Advanced Stats.** Fetched 5 seasons of Understat data (2020-21 through 2024-25) via the `understatapi` library. Created 3,800 MatchStat records with xG, xGA, NPxG, NPxGA, PPDA coefficient, PPDA allowed coefficient, deep completions, and deep allowed. Rate-limited to 2 seconds per API call.

**E23-03: Backfill Shot-Level xG Breakdown.** The slowest step (~100 minutes) — fetched individual shot data for each of 3,800 matches from Understat to decompose xG into set-piece and open-play components. Updated all MatchStat records with `set_piece_xg` and `open_play_xg`.

**E23-04: Backfill ClubElo for Historical Seasons.** Fetched Elo ratings for 495 unique match dates across 4 historical seasons from the ClubElo API. Created 13,227 new ClubElo records (17,965 total). Fixed team name mapping bug: "West Brom"/"WestBrom" → "West Bromwich Albion". 28 unique teams across all 6 seasons with 100% match-date coverage.

**E23-05: Recompute All Features.** Recomputed the entire Feature table for all 6 seasons with complete data. 4,560 Feature rows (6 seasons × 380 matches × 2 teams). Coverage: xG 97–100%, Elo 100%, Pinnacle odds 78% (historical), referee 85%. All rolling windows now have sufficient lookback depth.

**E23-06: Full Backtest & Revalidation.** Walk-forward backtest across 5 seasons (2020-21 through 2024-25) as out-of-sample test data: **Brier score improved from 0.6105 to 0.5781 (−5.3%)**, **ROI improved from −3.50% to +2.78% (+6.28 percentage points)**. The model crossed from losing to profitable. Total P&L: +$356 from $12,825 staked across 634 value bets. The improvement came primarily from more stable coefficient estimates in the Poisson GLM (3× more training data reduced overfitting).

**E23-07: Verify Odds API Pipeline.** End-to-end production verification: ran The Odds API scraper → 3,130 odds fetched from 50+ bookmakers → loader matched and stored 3,070 new records (60 duplicates correctly skipped) → all 20 EPL teams mapped → final DB state: 34,076 total Odds records. Confirmed the live pipeline works end-to-end.

---

### Model Performance Evolution

| Milestone | Brier Score | ROI | Training Data | Key Change |
|-----------|-------------|-----|---------------|------------|
| E13-03 (Baseline) | ~0.72 | ~−15% | 1 season (380) | Initial Poisson GLM |
| E16-03 (Advanced Features) | 0.6903 | −7.2% | 1 season (380) | +NPxG, PPDA, weather, market value |
| E20-03 (Market-Augmented) | 0.6105 | −3.50% | 2 seasons (760) | +Pinnacle odds, AH line |
| **E23-06 (Full Backfill)** | **0.5781** | **+2.78%** | **6 seasons (2,280)** | **3× training data — model now profitable** |
| E25-03 (XGBoost Backtest) | 0.5781 | +2.78% | 5 seasons (1,900) | Poisson wins — XGBoost overfits (Brier 0.5821, ROI −19%), ensemble unprofitable (ROI −9.4%) |

### 13.14 — E24 — Dashboard Fixes & Fixtures Value Grid (Planned)

Three dashboard issues preventing effective forward-looking use: Today's Picks shows stale 2024 data due to an unbounded fallback cascade, the Match Deep Dive page is empty for future matches even when predictions exist, and the Fixtures page gives no analytical insight without clicking into each match.

**E24-01: Fix Today's Picks Date Logic.** The triple fallback in `get_todays_value_bets()` eventually queries all-time value bets sorted by edge with no date or status filter — surfacing completed matches from 2024. Fix: filter to `Match.status IN ('scheduled')` for actionable picks, sort by date ascending then edge descending, cap fallback to 14 days, and separate "Upcoming Picks" from "Recent Results" sections.

**E24-02: Fix Deep Dive for Future Matches.** The Deep Dive page hides the scoreline matrix, market probabilities, and narrative sections when no ValueBet records exist — but Prediction records DO exist for scheduled matches. Fix: render prediction data (scoreline heatmap, 1X2/BTTS/O-U probabilities, expected goals, narrative) regardless of whether value bets have been identified. Also debug any Odds API team name mapping gaps that prevent odds from loading.

**E24-03: Fixtures Value Grid — Model Indicators.** Add inline color-coded market indicators to each fixture row on the Fixtures page. For every scheduled match, display compact badges for 7 selections: Home/Draw/Away (1X2), BTTS Yes/No, Over 2.5/Under 2.5. Color coding: green = strong edge (above value threshold), yellow = marginal edge, red = no edge or negative. Driven by Prediction + Odds data joined at render time. This makes the Fixtures page a standalone decision-making tool without requiring Deep Dive clicks.

**E24-04: Fixtures Value Grid — Data Pipeline.** Ensure the prediction→odds→value chain is complete for all scheduled fixtures. Add diagnostic indicators when data is missing (e.g., "No odds yet" badge, "Awaiting prediction" badge). Verify Odds API team name coverage and fix any gaps.

**E24-05: Fixtures + Picks Integration Test.** End-to-end verification: run the morning pipeline → confirm fixtures show color-coded grid with live data → confirm Today's Picks shows only upcoming matches → confirm Deep Dive works for every scheduled match with full prediction content.

### 13.15 — E25 — XGBoost Ensemble Model (Planned)

The Poisson GLM is at its ceiling — it cannot exploit non-linear interactions between features (e.g., Pinnacle odds × Elo × congestion). XGBoost (gradient-boosted decision trees) is the natural next model, and the architecture was designed for this from day one: `BaseModel` defines the abstract interface, every model produces a 7×7 scoreline matrix, and `ensemble_weights.py` already handles weighted combination.

**E25-01: XGBoost Scoreline Model.** New file `src/models/xgboost_model.py` implementing `BaseModel`. Trains XGBoost regressors on the same feature set as Poisson, predicting home and away expected goals. Generates the 7×7 scoreline probability matrix via Poisson distribution from the XGBoost-predicted λ values. Key advantages: captures non-linear feature interactions, handles missing values natively, automatic feature importance ranking.

**E25-02: Ensemble Combiner.** Weighted average of Poisson and XGBoost scoreline matrices using the existing `src/self_improvement/ensemble_weights.py` infrastructure. Initial weights: 50/50. The self-improvement module will adjust weights over time based on per-model Brier scores (guardrails from MP §11 apply — minimum sample size, maximum weight change rate, rollback on degradation).

**E25-03: Walk-Forward Backtest.** Compare three configurations across 5 historical seasons: Poisson-only, XGBoost-only, and weighted ensemble. Metrics: Brier score, ROI, calibration, log-loss. Store results in ModelPerformance table. This determines which configuration becomes the production default.

**E25-04: Promote Best Model.** Based on E25-03 results, update `config/settings.yaml` to set the winning model/ensemble as the production default. Update pipeline to use the promoted configuration. If XGBoost underperforms, Poisson remains the sole production model — no forced adoption.
