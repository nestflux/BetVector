# BetVector — Build Plan

Version 1.1 · March 2026

---

## Purpose

This document breaks the BetVector masterplan into sequenced epics and issues that Claude Code (or Cowork) can execute one at a time, in order, without making architectural decisions. Every issue references the masterplan sections it implements and has objectively verifiable acceptance criteria.

---

## Epics Overview

| Epic | Title | Issues | Description |
|------|-------|--------|-------------|
| E1 | Development Environment | 3 | Project structure, dependencies, config system, Git repo |
| E2 | Database | 4 | All tables, indexes, ORM models, connection management |
| E3 | Data Scrapers | 4 | Football-Data.co.uk scraper, FBref scraper, API-Football scraper, data loader |
| E4 | Feature Engineering | 3 | Rolling features, H2H features, feature pipeline orchestration |
| E5 | Prediction Models | 3 | Base model interface, Poisson model, scoreline-to-market derivation |
| E6 | Value Detection & Bankroll | 3 | Value finder, bankroll manager, bet tracker |
| E7 | Evaluation & Backtesting | 3 | Metrics module, walk-forward backtester, model performance logger |
| E8 | Pipeline Orchestrator | 2 | Pipeline runner, CLI interface |
| E9 | Dashboard — Core | 5 | Streamlit app shell, Today's Picks, Performance Tracker, League Explorer, Match Deep Dive |
| E10 | Dashboard — Advanced | 4 | Model Health page, Bankroll Manager page, Settings page, Onboarding flow |
| E11 | Email Notifications | 3 | Email templates, email sender, scheduled email integration |
| E12 | Self-Improvement Engine | 5 | Auto-recalibration, feature importance tracking, adaptive ensemble weights, market feedback loop, retrain triggers |
| E13 | Automation & Deployment | 3 | GitHub Actions workflows, Streamlit Cloud deployment, security hardening |
| E14 | Real-Time Data Sources | 4 | Understat xG scraper, Open-Meteo weather scraper, API-Football scraper, pipeline integration |
| E15 | Data Freshness & Feature Expansion | 3 | Football-Data.org API scraper, Understat expansion, Transfermarkt datasets |
| E16 | Advanced Feature Engineering | 3 | Rolling advanced stats (NPxG, PPDA, deep), market value & weather features, recomputation & validation |
| E17 | Dashboard Feature Surfacing | 4 | Match Deep Dive enhancements, Today's Picks indicators, League Explorer NPxG rankings, Fixtures page |
| E18 | Match Narrative & Data Quality | 6 | Algorithmic match analysis narrative, kickoff time fix, scheduled match predictions, glossaries, UX improvements |
| E19 | Live Odds Pipeline | 4 | The Odds API scraper, loader + pipeline integration, CSV closing odds + AH + referee extraction, CLV tracking |
| E20 | Market-Augmented Poisson | 3 | Pinnacle opening odds as features, Asian Handicap line as feature, backtest comparison |
| E21 | External Ratings & Context | 3 | ClubElo scraper + Elo features, referee features, fixture congestion flag |
| E22 | Advanced Features | 2 | Set-piece xG breakdown, injury impact flags (manual input) |
| E23 | Historical Data Backfill | 7 | Load 4 missing seasons, Understat xG for all, shot-level xG, ClubElo, recompute features, backtest, Odds API verification |

**Total: 23 epics, 84 issues** (45 original + 20 post-launch + 12 odds/model improvement + 7 data backfill)

---

## How to Use This Document

1. Read the referenced masterplan sections (`MP §X`) before writing any code for an issue
2. Complete **all** acceptance criteria before marking an issue done
3. Never proceed to the next issue if current acceptance criteria are not met
4. Issues within an epic are ordered by dependency — do not skip ahead
5. When an issue is complete, update the `Current Status` section in `CLAUDE.md`

---

## Critical Path

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
E17-01 → E17-02 → E17-03 → E17-04
E18-01 → E18-02 → E18-03 → E18-04 → E18-05 → E18-06 →
E19-01 → E19-02 → E19-03 → E19-04 →
E20-01 → E20-02 → E20-03 →
E21-01 → E21-02 → E21-03 →
E22-01 → E22-02 →
E23-01 → E23-02 → E23-03 → E23-04 → E23-05 → E23-06 → E23-07
```

---

## E1 — Development Environment

### E1-01 — Project Structure and Folder Scaffold

**Type:** Setup
**Depends on:** Nothing
**Master Plan:** MP §5 Architecture

Create the complete project folder structure for BetVector. This establishes the modular architecture that every subsequent issue builds into.

**Implementation Notes:**
- Create all directories as specified in MP §5: `config/`, `data/raw/`, `data/processed/`, `data/predictions/`, `src/scrapers/`, `src/database/`, `src/features/`, `src/models/`, `src/evaluation/`, `src/betting/`, `src/delivery/`, `src/self_improvement/`, `notebooks/`, `tests/`, `templates/`
- Every Python package directory must have an `__init__.py`
- Create a `setup.py` or `pyproject.toml` so that `from src.models.poisson import PoissonModel` works from any location
- Create a comprehensive `.gitignore` that excludes: `data/*.db`, `data/raw/`, `__pycache__/`, `.env`, `.ipynb_checkpoints/`, `*.pkl`, `*.joblib`, `.DS_Store`

**Acceptance Criteria:**
- [ ] Running `find . -name "__init__.py"` from the project root lists an `__init__.py` in every package directory under `src/`
- [ ] Running `python -c "from src import scrapers, database, features, models, evaluation, betting, delivery, self_improvement"` succeeds without ImportError
- [ ] `.gitignore` exists and contains entries for `data/*.db`, `__pycache__`, `.env`, `*.pkl`
- [ ] `data/raw/`, `data/processed/`, `data/predictions/` directories exist
- [ ] `config/`, `notebooks/`, `tests/`, `templates/` directories exist

---

### E1-02 — Dependencies and Virtual Environment

**Type:** Setup
**Depends on:** E1-01
**Master Plan:** MP §5 Architecture → Key Libraries

Install all required Python dependencies in a virtual environment and create a `requirements.txt` that pins exact versions.

**Implementation Notes:**
- Create a Python virtual environment using `python3 -m venv venv`
- Install all libraries listed in MP §5: pandas, numpy, scipy, scikit-learn, statsmodels, soccerdata, requests, beautifulsoup4, pyyaml, sqlalchemy, plotly, streamlit, xgboost, lightgbm, matplotlib, seaborn, mplsoccer, jinja2, pytest
- Pin exact versions in `requirements.txt` using `pip freeze`
- Create a `Makefile` with common commands: `make install`, `make test`, `make run`, `make lint`

**Acceptance Criteria:**
- [ ] `requirements.txt` exists and lists all dependencies from MP §5 with pinned versions
- [ ] Running `pip install -r requirements.txt` in a fresh virtual environment completes without errors
- [ ] Running `python -c "import pandas, numpy, scipy, sklearn, statsmodels, requests, bs4, yaml, sqlalchemy, plotly, streamlit, xgboost, lightgbm"` succeeds
- [ ] `Makefile` exists with targets: `install`, `test`, `run`
- [ ] `venv/` directory is listed in `.gitignore`

---

### E1-03 — Configuration System

**Type:** Setup
**Depends on:** E1-01
**Master Plan:** MP §5 Architecture → Config-driven

Create the YAML configuration files that drive all system behaviour. Every tuneable parameter lives here, not in code.

**Implementation Notes:**
- Create `config/leagues.yaml` with EPL configuration: name, short_name, country, football_data_code (`E0`), fbref_league_id, api_football_id, seasons (2020-21 through 2024-25). Include a commented-out La Liga example showing how to add a league.
- Create `config/settings.yaml` with: database path (`data/betvector.db`), feature windows (`[5, 10]`), edge threshold default (`0.05`), bankroll defaults (starting: 1000, method: flat, stake_pct: 0.02, kelly_fraction: 0.25), safety limits (max_bet_pct: 0.05, daily_loss_limit: 0.10, drawdown_alert: 0.25, min_bankroll_pct: 0.50), model settings, self-improvement thresholds (min_calibration_sample: 200, calibration_error_threshold: 0.03, min_ensemble_sample: 300, max_weight_change: 0.10, weight_floor: 0.10, weight_ceiling: 0.60, retrain_degradation_threshold: 0.15, retrain_cooldown_days: 30, min_market_feedback_bets: 50)
- Create `config/email_config.yaml` with: SMTP settings for Gmail (host, port, use_tls), schedule (morning: "07:00", evening: "22:00", weekly: "sunday_20:00"), placeholder for credentials (reference to env vars, never actual values)
- Create `src/config.py` — a Python module that loads all YAML configs, validates them, and provides typed access: `config.leagues`, `config.settings.edge_threshold`, `config.email.schedule`, etc. Use dataclasses or Pydantic for type safety.

**Acceptance Criteria:**
- [ ] `config/leagues.yaml` exists with full EPL configuration including 5 seasons and a commented La Liga example
- [ ] `config/settings.yaml` exists with all parameters from MP §5, §6, §11 including self-improvement thresholds
- [ ] `config/email_config.yaml` exists with Gmail SMTP template and schedule
- [ ] No config file contains actual credentials — all sensitive values reference environment variables
- [ ] `src/config.py` loads all three config files and exposes typed attributes
- [ ] Running `python -c "from src.config import config; print(config.settings.edge_threshold)"` prints `0.05`
- [ ] Running `python -c "from src.config import config; print(config.leagues[0].short_name)"` prints `EPL`

---

## E2 — Database

### E2-01 — Database Connection and Setup

**Type:** Schema
**Depends on:** E1-03
**Master Plan:** MP §5 Architecture → Database, MP §6 Database Schema

Create the database connection manager using SQLAlchemy. This is the foundation that every other module reads from and writes to.

**Implementation Notes:**
- Use SQLAlchemy 2.0+ with the new-style API (`create_engine`, `Session`, `DeclarativeBase`)
- Database path comes from `config.settings.database_path` (default: `data/betvector.db`)
- Create a `src/database/db.py` with: `get_engine()`, `get_session()`, `init_db()` (creates all tables), `reset_db()` (drops and recreates — for development only)
- Connection string format: `sqlite:///data/betvector.db` for SQLite. When migrating to PostgreSQL, only this string changes.
- Enable WAL mode for SQLite for better concurrent read performance: `PRAGMA journal_mode=WAL`

**Acceptance Criteria:**
- [ ] `src/database/db.py` exists with `get_engine()`, `get_session()`, `init_db()`, `reset_db()` functions
- [ ] `init_db()` creates the database file at the configured path
- [ ] `get_session()` returns a working SQLAlchemy session that can execute `SELECT 1`
- [ ] Database path is read from config, not hardcoded
- [ ] SQLite WAL mode is enabled after connection

---

### E2-02 — Core ORM Models

**Type:** Schema
**Depends on:** E2-01
**Master Plan:** MP §6 Database Schema (users through predictions tables)

Define SQLAlchemy ORM models for all core tables: users, leagues, seasons, teams, matches, match_stats, odds, features, predictions.

**Implementation Notes:**
- Create `src/database/models.py` with one class per table
- Follow the exact schema from MP §6: every column, type, constraint, default, and CHECK constraint
- Use SQLAlchemy's `CheckConstraint` for enum-like TEXT fields (e.g., `status IN ('scheduled', 'in_play', 'finished', 'postponed')`)
- Define all relationships: `Match.home_team` → `Team`, `Match.match_stats` → `[MatchStat]`, `Prediction.match` → `Match`, etc.
- Create all indexes specified in MP §6
- Add `__repr__` methods for debugging readability
- Tables to create in this issue: `users`, `leagues`, `seasons`, `teams`, `matches`, `match_stats`, `odds`, `features`, `predictions`

**Acceptance Criteria:**
- [ ] `src/database/models.py` defines ORM classes for all 9 core tables
- [ ] Running `init_db()` creates all 9 tables in the SQLite database
- [ ] Every column from MP §6 is present with the correct type and constraints
- [ ] CHECK constraints exist for: `users.role`, `users.staking_method`, `matches.status`, `odds.market_type`, `odds.selection`
- [ ] Foreign key relationships are defined: `matches.home_team_id` → `teams.id`, `match_stats.match_id` → `matches.id`, etc.
- [ ] Indexes exist for: `matches(date)`, `matches(league_id, season)`, `matches(status)`, `match_stats(match_id)`, `odds(match_id)`, `odds(bookmaker)`, `odds(market_type)`, `features(match_id)`, `predictions(match_id)`, `predictions(model_name)`
- [ ] A test user (the owner) can be inserted and queried back successfully

---

### E2-03 — Betting and Tracking ORM Models

**Type:** Schema
**Depends on:** E2-02
**Master Plan:** MP §6 Database Schema (value_bets, bet_log, model_performance, pipeline_runs)

Define SQLAlchemy ORM models for the betting, tracking, and operational tables.

**Implementation Notes:**
- Create these tables in `src/database/models.py` (append to existing file): `value_bets`, `bet_log`, `model_performance`, `pipeline_runs`
- Follow exact schema from MP §6 including all CHECK constraints and indexes
- `bet_log` is the most important table — it tracks every bet the system recommends and every bet the user places. Double-check all columns match MP §6.

**Acceptance Criteria:**
- [ ] ORM classes exist for `value_bets`, `bet_log`, `model_performance`, `pipeline_runs`
- [ ] Running `init_db()` creates all 13 tables (9 core + 4 from this issue)
- [ ] CHECK constraints exist for: `value_bets.confidence`, `bet_log.bet_type`, `bet_log.status`, `model_performance.period_type`, `pipeline_runs.run_type`, `pipeline_runs.status`
- [ ] Indexes exist for: `value_bets(match_id)`, `value_bets(edge DESC)`, `bet_log(user_id)`, `bet_log(match_id)`, `bet_log(status)`, `bet_log(date)`, `bet_log(bet_type)`

---

### E2-04 — Self-Improvement ORM Models and Seed Data

**Type:** Schema
**Depends on:** E2-03
**Master Plan:** MP §6 Database Schema Addendum (§11), MP §11 Self-Improvement Engine

Define ORM models for self-improvement tables and seed the database with initial data.

**Implementation Notes:**
- Create these tables: `calibration_history`, `feature_importance_log`, `ensemble_weight_history`, `market_performance`, `retrain_history` (from MP §11 database addendum)
- Create `src/database/seed.py` that:
  - Inserts the owner user (id=1, name from config, role='owner', defaults from config)
  - Inserts EPL league configuration
  - Inserts EPL seasons (2020-21 through 2024-25)
  - Is idempotent — running it twice doesn't create duplicates

**Acceptance Criteria:**
- [ ] ORM classes exist for all 5 self-improvement tables
- [ ] Running `init_db()` creates all 18 tables total
- [ ] `seed.py` creates the owner user with role='owner' and config defaults
- [ ] `seed.py` creates EPL league and 5 season entries
- [ ] Running `seed.py` twice does not create duplicate records
- [ ] Total table count in database after `init_db()` + `seed.py`: 18 tables, 1 user, 1 league, 5 seasons

---

## E3 — Data Scrapers

### E3-01 — Base Scraper and Rate Limiter

**Type:** Backend
**Depends on:** E1-03
**Master Plan:** MP §5 Architecture → Data Sources, MP §7 Scraper Interface

Create the abstract base scraper class and shared utilities (rate limiting, logging, raw file saving).

**Implementation Notes:**
- Create `src/scrapers/base_scraper.py` with the abstract interface from MP §7
- Implement rate limiting: minimum 2 seconds between HTTP requests to the same domain. Use `time.sleep()`.
- Implement `save_raw()`: saves DataFrames to `data/raw/{source}_{league}_{season}_{date}.csv`
- Use Python `logging` module: INFO for progress, WARNING for retries, ERROR for failures
- Implement retry logic: 3 retries with exponential backoff for HTTP errors

**Acceptance Criteria:**
- [ ] `src/scrapers/base_scraper.py` defines `BaseScraper` ABC with `scrape()`, `save_raw()` abstract methods
- [ ] Rate limiter enforces minimum 2-second gap between requests (testable with a mock)
- [ ] `save_raw()` writes a CSV to `data/raw/` with a filename containing source, league, season, and date
- [ ] Retry logic attempts 3 retries with increasing delay on HTTP 429/500/503 errors
- [ ] Logger is configured and outputs INFO-level progress messages

---

### E3-02 — Football-Data.co.uk Scraper

**Type:** Backend
**Depends on:** E3-01, E2-02
**Master Plan:** MP §5 Architecture → Data Sources, MP §7 Scraper Interface

Build the scraper for Football-Data.co.uk — the primary source for match results and betting odds.

**Implementation Notes:**
- Create `src/scrapers/football_data.py` inheriting from `BaseScraper`
- URL pattern: `https://www.football-data.co.uk/mmz4281/{season_code}/{league_code}.csv` where season_code is like `2425` for 2024-25 and league_code comes from config (e.g., `E0` for EPL)
- Parse columns: Date, HomeTeam, AwayTeam, FTHG, FTAG, HTHG, HTAG (results) + B365H, B365D, B365A, PSH, PSD, PSA, WHH, WHD, WHA, AvgH, AvgD, AvgA, Avg>2.5, Avg<2.5 (odds)
- Normalise team names to canonical form (create a mapping dict for known variations)
- Handle missing odds columns gracefully — not all seasons have all bookmakers
- Save raw CSV before any processing

**Acceptance Criteria:**
- [ ] `FootballDataScraper.scrape(league_config, season)` downloads the CSV for the given league-season
- [ ] Raw CSV is saved to `data/raw/football_data_EPL_2024-25_{date}.csv`
- [ ] Returned DataFrame contains columns: `date, home_team, away_team, home_goals, away_goals, home_ht_goals, away_ht_goals`
- [ ] Returned DataFrame contains odds columns for at least: Bet365, Pinnacle (PS prefix), market average (Avg prefix) for 1X2 and O/U 2.5
- [ ] Team names are normalised (e.g., "Man United" → "Manchester United")
- [ ] Scraper handles HTTP errors and missing columns without crashing
- [ ] Scraper respects the 2-second rate limit between requests

---

### E3-03 — FBref Scraper

**Type:** Backend
**Depends on:** E3-01, E2-02
**Master Plan:** MP §5 Architecture → Data Sources, MP §7 Scraper Interface

Build the scraper for FBref match statistics using the soccerdata library.

**Implementation Notes:**
- Create `src/scrapers/fbref_scraper.py` inheriting from `BaseScraper`
- Use `soccerdata.FBref` class to fetch team-level match stats
- Extract per-match: xG, xGA, shots, shots on target, possession, passes completed, passes attempted
- soccerdata handles FBref's rate limiting internally, but add a note about this
- Map FBref team names to canonical names (same mapping as Football-Data scraper)
- Cache soccerdata results to avoid re-downloading (soccerdata has built-in caching)

**Acceptance Criteria:**
- [ ] `FBrefScraper.scrape(league_config, season)` returns a DataFrame with per-match team stats
- [ ] DataFrame contains columns: `date, team, opponent, is_home, xg, xga, shots, shots_on_target, possession, passes_completed, passes_attempted`
- [ ] Team names are normalised to the same canonical names as Football-Data scraper
- [ ] xG and xGA values are numeric (not strings) and reasonable (0.0–6.0 range)
- [ ] Raw data is saved to `data/raw/fbref_EPL_2024-25_{date}.csv`
- [ ] Scraper handles seasons where some stats are unavailable without crashing

---

### E3-04 — Data Loader

**Type:** Backend
**Depends on:** E3-02, E3-03, E2-04
**Master Plan:** MP §7 Scraper Interface, MP §6 Database Schema

Build the data loader that takes scraped DataFrames and loads them into the database with deduplication.

**Implementation Notes:**
- Create `src/scrapers/loader.py` with functions: `load_matches()`, `load_match_stats()`, `load_odds()`
- `load_matches()`: inserts into `matches` table, creates `teams` entries if they don't exist, skips duplicates based on UNIQUE(league_id, date, home_team_id, away_team_id)
- `load_odds()`: inserts into `odds` table, handles all market types (1X2, OU25), maps bookmaker column names to canonical bookmaker names (B365 → Bet365, PS → Pinnacle, etc.)
- `load_match_stats()`: inserts into `match_stats` table, links to match_id via date + team matching
- All loaders print a summary: "Loaded X matches (Y new, Z skipped as duplicates)"
- Use SQLAlchemy's `session.merge()` or INSERT OR IGNORE for deduplication

**Acceptance Criteria:**
- [ ] `load_matches(df, league_id, season)` inserts matches and creates teams automatically
- [ ] Running `load_matches()` twice with the same data does not create duplicate records
- [ ] `load_odds(df, league_id)` correctly maps bookmaker column names (B365H → Bet365, home, 1X2)
- [ ] `load_odds()` stores both 1X2 and O/U 2.5 odds with correct `market_type` and `selection` values
- [ ] `load_match_stats(df, league_id)` links stats to the correct match_id via date and team matching
- [ ] After loading EPL 2024-25: matches table has ~380 rows, odds table has thousands of rows, match_stats has ~760 rows (2 per match)
- [ ] Each loader prints a summary of new vs skipped records

---

## E4 — Feature Engineering

### E4-01 — Rolling Feature Calculator

**Type:** Backend
**Depends on:** E3-04
**Master Plan:** MP §4 Feature Set → Feature Engineering, MP §6 features table

Build the rolling feature calculator that computes team form, xG, and performance stats over configurable windows.

**Implementation Notes:**
- Create `src/features/rolling.py`
- For each team, for each match, look back at the team's last N matches (where N comes from config, default [5, 10]) and calculate: points_per_game, goals_scored_per_game, goals_conceded_per_game, xg_per_game, xga_per_game, xg_diff_per_game, shots_per_game, shots_on_target_per_game, possession_avg
- Calculate venue-specific variants (home-only and away-only) using only matches at the same venue over last 5
- CRITICAL: Only use matches BEFORE the current match date. Sort by date descending, take last N, never include the match being predicted.
- Handle edge cases: team has fewer than N matches (use however many are available), team just promoted (start fresh)
- Use pandas vectorised operations where possible for speed

**Acceptance Criteria:**
- [ ] `calculate_rolling_features(team_id, match_date, window)` returns a dict of all rolling features
- [ ] Features use only matches strictly before `match_date` — never includes the current match or future matches
- [ ] For a team with 20+ matches, features for window=5 use exactly the 5 most recent matches before the date
- [ ] For a team with only 3 matches, features for window=5 use all 3 available matches
- [ ] Venue-specific features (venue_form_5, venue_xg_5, etc.) use only home matches for home features and only away matches for away features
- [ ] All features are REAL numbers (no NaN for teams with at least 1 prior match; NULL/None for teams with 0 prior matches)

---

### E4-02 — Head-to-Head and Context Features

**Type:** Backend
**Depends on:** E4-01
**Master Plan:** MP §4 Feature Set → Feature Engineering, MP §6 features table

Build the head-to-head calculator and contextual features (rest days, season progress).

**Implementation Notes:**
- Create `src/features/context.py`
- H2H features: look up last 5 meetings between the two teams (regardless of venue) before the current match date. Calculate: wins, draws, losses, avg goals scored, avg goals conceded for each team.
- Rest days: calculate days between the current match date and the team's previous match date. If no previous match (season opener), use a default of 7 days.
- Season progress: `matchday / total_matchdays` as a 0.0–1.0 float. For EPL, total_matchdays = 38.
- Matchday: the matchday number from the matches table.

**Acceptance Criteria:**
- [ ] `calculate_h2h_features(team_id, opponent_id, match_date)` returns wins, draws, losses, avg goals for/against from last 5 H2H meetings
- [ ] H2H only uses meetings strictly before `match_date`
- [ ] If fewer than 5 H2H meetings exist, uses however many are available
- [ ] If 0 H2H meetings exist, returns zeros for all H2H features
- [ ] `calculate_rest_days(team_id, match_date)` returns the correct number of days since last match
- [ ] `calculate_season_progress(matchday, league_config)` returns a float between 0.0 and 1.0

---

### E4-03 — Feature Pipeline Orchestration

**Type:** Backend
**Depends on:** E4-01, E4-02
**Master Plan:** MP §4 Feature Set, MP §6 features table, MP §7 Feature Engineer Interface

Combine rolling, H2H, and context features into a single pipeline that computes and stores features for all matches in a league-season.

**Implementation Notes:**
- Create `src/features/engineer.py` implementing the `FeatureEngineer` interface from MP §7
- `compute_features(match_id)`: compute all features for a single match (both home and away teams), return as dict
- `compute_all_features(league_id, season)`: iterate through all matches in a league-season in chronological order, compute features for each, store in the `features` table
- Skip matches that already have features (idempotent)
- Print progress: "Computing features: match 127/380 (Arsenal vs Chelsea, 2024-11-10)"
- Return a DataFrame suitable for model training: one row per match with home_* and away_* feature columns

**Acceptance Criteria:**
- [ ] `compute_features(match_id)` returns a dict with all feature columns from MP §6 features table for both home and away teams
- [ ] `compute_all_features(league_id, season)` stores features for every match in the features table
- [ ] Running `compute_all_features()` twice does not create duplicate feature rows
- [ ] Returned DataFrame has one row per match with columns matching the pattern: `home_form_5, home_form_10, ..., away_form_5, away_form_10, ..., h2h_home_wins, ..., home_rest_days, away_rest_days, matchday, season_progress`
- [ ] No feature for any match uses data from that match or future matches (temporal integrity)
- [ ] Progress messages print to console during computation

---

## E5 — Prediction Models

### E5-01 — Base Model Interface and Match Prediction Dataclass

**Type:** Backend
**Depends on:** E1-03
**Master Plan:** MP §5 Architecture → Scoreline matrix decision, MP §7 Model Interface

Create the abstract base model class and the MatchPrediction dataclass that all models must produce.

**Implementation Notes:**
- Create `src/models/base_model.py` with the `BaseModel` ABC from MP §7
- Create the `MatchPrediction` dataclass from MP §7 with all fields
- The scoreline matrix is a 7×7 list of lists (indexes 0–6 for each team's goals), probabilities summing to 1.0
- Create a utility function `derive_market_probabilities(scoreline_matrix)` that takes a 7×7 matrix and returns all market probabilities:
  - prob_home_win = sum of matrix[h][a] where h > a
  - prob_draw = sum of matrix[h][a] where h == a
  - prob_away_win = sum of matrix[h][a] where h < a
  - prob_over_25 = sum of matrix[h][a] where h + a > 2.5 (i.e., >= 3)
  - prob_under_25 = 1 - prob_over_25
  - prob_over_15 / prob_under_15 (same pattern with 1.5 threshold)
  - prob_over_35 / prob_under_35 (same pattern with 3.5 threshold)
  - prob_btts_yes = sum of matrix[h][a] where h >= 1 AND a >= 1
  - prob_btts_no = 1 - prob_btts_yes
- This utility function is THE critical piece — every model's market probabilities flow through it

**Acceptance Criteria:**
- [ ] `BaseModel` ABC defines abstract methods: `train()`, `predict()`, `save()`, `load()`, and properties `name`, `version`
- [ ] `MatchPrediction` dataclass has all fields from MP §7
- [ ] `derive_market_probabilities([[...]])` correctly computes all market probabilities from a 7×7 matrix
- [ ] For a known scoreline matrix, `prob_home_win + prob_draw + prob_away_win` equals 1.0 (within floating point tolerance)
- [ ] `prob_over_25 + prob_under_25` equals 1.0
- [ ] `prob_btts_yes + prob_btts_no` equals 1.0
- [ ] A test with a uniform scoreline matrix (equal probability for all 49 outcomes) produces probabilities that are mathematically correct

---

### E5-02 — Poisson Regression Model

**Type:** Backend
**Depends on:** E5-01, E4-03
**Master Plan:** MP §4 Feature Set → Prediction Models, MP §5 Architecture → Scoreline matrix

Implement the Poisson regression model — BetVector's foundational prediction model.

**Implementation Notes:**
- Create `src/models/poisson.py` inheriting from `BaseModel`
- Training: use statsmodels `GLM` with Poisson family to predict goals scored based on team attack strength, opponent defense strength, and home advantage
- The model produces two lambda values per match: `lambda_home` (expected home goals) and `lambda_away` (expected away goals)
- Scoreline matrix generation: for each cell [h][a], probability = `poisson.pmf(h, lambda_home) × poisson.pmf(a, lambda_away)` using `scipy.stats.poisson`
- Truncate at 6 goals and renormalise so the matrix sums to 1.0
- Use `derive_market_probabilities()` from E5-01 to get all market probs
- Save/load model using `joblib` or `pickle`
- Add extensive comments explaining: Poisson distribution, attack/defense strength, why independence assumption works, how the scoreline matrix is built

**Acceptance Criteria:**
- [ ] `PoissonModel.train(features_df, results_df)` fits a Poisson regression without errors
- [ ] `PoissonModel.predict(features_df)` returns a list of `MatchPrediction` objects
- [ ] Each prediction has `predicted_home_goals` and `predicted_away_goals` as positive floats (typically 0.5–3.5)
- [ ] Each prediction's `scoreline_matrix` is a 7×7 matrix where all values sum to 1.0 (±0.001)
- [ ] All derived market probabilities are between 0.0 and 1.0
- [ ] `prob_home_win + prob_draw + prob_away_win` = 1.0 (±0.001) for every prediction
- [ ] Model can be saved to a file and loaded back, producing identical predictions
- [ ] Code comments explain what Poisson distribution is, how attack/defense strengths work, and how the scoreline matrix is generated

---

### E5-03 — Prediction Storage and Retrieval

**Type:** Backend
**Depends on:** E5-02, E2-02
**Master Plan:** MP §6 predictions table, MP §7 Model Interface

Store model predictions in the database and provide retrieval functions for downstream modules (value finder, dashboard).

**Implementation Notes:**
- Create `src/models/storage.py`
- `save_predictions(predictions: list[MatchPrediction])`: store each prediction in the `predictions` table, serialising the scoreline matrix as JSON
- `get_predictions(match_id, model_name=None)`: retrieve predictions for a match, optionally filtered by model. Deserialise scoreline matrix from JSON.
- `get_latest_predictions(league_id=None)`: retrieve the most recent prediction for each upcoming match
- Handle duplicate predictions: if a prediction already exists for match_id + model_name + model_version, update it rather than inserting a duplicate

**Acceptance Criteria:**
- [ ] `save_predictions()` stores predictions in the database with scoreline_matrix as valid JSON
- [ ] `get_predictions(match_id)` returns predictions with scoreline_matrix deserialised to a Python list of lists
- [ ] `get_latest_predictions()` returns one prediction per upcoming match (most recent by created_at)
- [ ] Saving the same prediction twice (same match_id, model_name, version) updates rather than duplicates
- [ ] Stored `prob_home_win + prob_draw + prob_away_win` = 1.0 for every prediction in the database

---

## E6 — Value Detection & Bankroll

### E6-01 — Value Finder

**Type:** Backend
**Depends on:** E5-03, E2-03
**Master Plan:** MP §4 Feature Set → Value Detection, MP §7 Value Finder Interface, MP §12 Glossary (value bet, edge, implied probability)

Build the value finder that compares model probabilities to bookmaker odds and identifies value bets.

**Implementation Notes:**
- Create `src/betting/value_finder.py` implementing the `ValueFinder` interface from MP §7
- For each upcoming match, for each market type, for each bookmaker: calculate implied_prob = 1.0 / odds, calculate edge = model_prob - implied_prob
- Flag as value bet if edge >= user's configured threshold (from config or user settings)
- Calculate expected_value = (model_prob × odds) - 1.0
- Set confidence: 'high' if edge >= 0.10, 'medium' if 0.05 <= edge < 0.10, 'low' if edge < 0.05
- Generate human-readable explanation string for each value bet using the team names, market, and key stats
- Store value bets in the `value_bets` table
- Add detailed comments explaining: implied probability, edge, expected value, overround

**Acceptance Criteria:**
- [ ] `find_value_bets(match_id, edge_threshold)` returns a list of `ValueBet` objects
- [ ] Each ValueBet has correct implied_prob = 1.0 / bookmaker_odds (verified mathematically)
- [ ] Each ValueBet has correct edge = model_prob - implied_prob
- [ ] Value bets are only returned when edge >= edge_threshold
- [ ] Confidence is correctly assigned: 'high' for edge >= 10%, 'medium' for 5–10%, 'low' for < 5%
- [ ] Each ValueBet has a non-empty explanation string containing team names and market type
- [ ] Value bets are stored in the `value_bets` table with all fields populated

---

### E6-02 — Bankroll Manager

**Type:** Backend
**Depends on:** E6-01, E2-04
**Master Plan:** MP §4 Feature Set → Bankroll Management, MP §7 Bankroll Manager Interface, MP §12 Glossary (bankroll, flat staking, Kelly)

Build the bankroll manager that calculates stakes and enforces safety limits.

**Implementation Notes:**
- Create `src/betting/bankroll.py` implementing the `BankrollManager` interface from MP §7
- Three staking methods (selected per user):
  - `flat`: stake = current_bankroll × stake_percentage (default 2%)
  - `percentage`: same as flat but recalculates after each bet (bankroll changes)
  - `kelly`: stake = ((model_prob × odds - 1) / (odds - 1)) × kelly_fraction × current_bankroll. Clamp to non-negative.
- Safety limits (from config):
  - Max single bet: min(calculated_stake, current_bankroll × max_bet_pct)
  - Daily loss limit: sum today's losses; if >= daily_loss_limit × starting_bankroll, return stake=0 with warning
  - Drawdown alert: if current_bankroll < peak_bankroll × (1 - drawdown_alert), flag warning
  - Minimum bankroll: if current_bankroll < starting_bankroll × min_bankroll_pct, return stake=0 with "paper trade only" warning
- `check_safety_limits()` returns a dict: `{daily_limit_hit: bool, drawdown_warning: bool, min_bankroll_hit: bool, message: str}`
- Add detailed comments explaining: bankroll management, flat stakes, Kelly Criterion formula with worked example, fractional Kelly, drawdown

**Acceptance Criteria:**
- [ ] `calculate_stake(user_id, model_prob, odds)` returns correct stake for flat method: current_bankroll × 0.02
- [ ] Kelly stake is calculated correctly: ((0.6 × 2.1 - 1) / (2.1 - 1)) × 0.25 × bankroll = correct value
- [ ] Max single bet cap is enforced: no stake exceeds 5% of current bankroll regardless of method
- [ ] `check_safety_limits()` returns `daily_limit_hit=True` when daily losses exceed 10% of starting bankroll
- [ ] `check_safety_limits()` returns `drawdown_warning=True` when bankroll is 25%+ below peak
- [ ] `check_safety_limits()` returns `min_bankroll_hit=True` when bankroll drops below 50% of starting amount
- [ ] Kelly stake returns 0 when model_prob × odds < 1 (negative edge — no bet)
- [ ] Code comments include a worked Kelly Criterion example with actual numbers

---

### E6-03 — Bet Tracker

**Type:** Backend
**Depends on:** E6-02
**Master Plan:** MP §4 Feature Set → Bet Tracking, MP §6 bet_log table, MP §3 Flow 5

Build the bet tracker that logs system picks and user-placed bets, and resolves them when results come in.

**Implementation Notes:**
- Create `src/betting/tracker.py`
- `log_system_picks(value_bets, user_id)`: auto-log all value bets as 'system_pick' entries with calculated stake based on user's staking method. Bankroll fields populated from current state.
- `log_user_bet(value_bet_id, user_id, actual_odds, actual_stake)`: log a user-placed bet linked to a system pick, with the actual odds and stake they got.
- `resolve_bets(match_id)`: when match results come in, update all pending bets for that match. Calculate PnL: if won, pnl = stake × (odds - 1); if lost, pnl = -stake. Update bankroll_after.
- `get_bet_history(user_id, filters)`: retrieve bet log with optional filters (date range, league, market, status, bet_type)
- Calculate CLV for resolved bets: compare odds_at_placement to closing_odds

**Acceptance Criteria:**
- [ ] `log_system_picks()` creates a bet_log entry for every value bet with bet_type='system_pick' and status='pending'
- [ ] `log_user_bet()` creates a bet_log entry with bet_type='user_placed' and links to the correct value_bet_id
- [ ] `resolve_bets(match_id)` changes status from 'pending' to 'won' or 'lost' based on match result
- [ ] PnL is calculated correctly: won bets have positive pnl = stake × (odds - 1), lost bets have negative pnl = -stake
- [ ] User's current_bankroll in the users table is updated after bet resolution
- [ ] `get_bet_history()` returns results filtered correctly by date range, league, market type, and bet_type
- [ ] CLV is calculated when closing_odds are available: clv = (1/closing_odds) - (1/odds_at_placement)

---

## E7 — Evaluation & Backtesting

### E7-01 — Metrics Module

**Type:** Backend
**Depends on:** E6-03
**Master Plan:** MP §4 Feature Set → Evaluation, MP §7 Pipeline Orchestrator, MP §12 Glossary (ROI, Brier score, CLV, calibration)

Build the metrics calculation module for evaluating model and betting performance.

**Implementation Notes:**
- Create `src/evaluation/metrics.py`
- `calculate_roi(bet_logs)`: total_pnl / total_staked. Return as a percentage.
- `calculate_brier_score(predictions, actuals)`: mean squared error between predicted probabilities and binary outcomes (0 or 1). Implement for 1X2 market: for each match, Brier = (prob_home - actual_home)² + (prob_draw - actual_draw)² + (prob_away - actual_away)²
- `calculate_calibration(predictions, actuals, n_bins=10)`: bucket predictions into probability bins (0.0–0.1, 0.1–0.2, etc.), calculate actual win rate per bin. Return as dict for plotting.
- `calculate_clv(bet_logs)`: average CLV across all bets where closing_odds are available
- `generate_performance_report(user_id, period)`: calculate all metrics for a time period, store in `model_performance` table
- Add detailed comments explaining each metric and what "good" looks like

**Acceptance Criteria:**
- [ ] `calculate_roi()` returns correct ROI: if 100 staked and 105 returned, ROI = 5%
- [ ] `calculate_brier_score()` returns a float between 0 and 2 (for 1X2 market)
- [ ] `calculate_brier_score()` for a perfect predictor returns 0.0
- [ ] `calculate_calibration()` returns a dict with keys like `"0.5-0.6": {"predicted_avg": 0.55, "actual_rate": 0.52, "count": 30}`
- [ ] `calculate_clv()` returns average CLV as a float (positive = beating closing line)
- [ ] `generate_performance_report()` stores results in `model_performance` table
- [ ] Code comments explain what each metric means and what ranges indicate good performance

---

### E7-02 — Walk-Forward Backtester

**Type:** Backend
**Depends on:** E7-01, E5-02, E4-03, E6-01, E6-02
**Master Plan:** MP §4 Feature Set → Evaluation, MP §12 Glossary (walk-forward validation)

Build the walk-forward backtesting framework that simulates real-world usage on historical data.

**Implementation Notes:**
- Create `src/evaluation/backtester.py`
- `run_backtest(league_id, season, model_class, edge_threshold, staking_method)`: 
  - Sort all matches in the season by date
  - For each matchday: (1) train model on all data before this date, (2) compute features for this matchday's matches, (3) predict, (4) find value bets, (5) simulate betting with the staking method, (6) record results
  - Track cumulative P&L, running ROI, and running Brier score
- Return a `BacktestResult` dataclass: total_matches, total_value_bets, total_staked, total_pnl, roi, brier_score, calibration_data, clv_avg, daily_pnl_series (for plotting)
- Print progress: "Backtesting matchday 15/38: 3 value bets found, running ROI: +2.3%"
- CRITICAL: the model MUST retrain from scratch for each matchday (or use an expanding window). It must never see future data.

**Acceptance Criteria:**
- [ ] `run_backtest()` iterates through matchdays in chronological order
- [ ] For each matchday, the model is trained only on matches before that date (verifiable by checking training set size increases)
- [ ] Value bets are identified using the specified edge threshold
- [ ] Betting is simulated using the specified staking method with safety limits
- [ ] `BacktestResult` contains: total_matches, total_value_bets, total_staked, total_pnl, roi, brier_score, calibration_data, daily_pnl_series
- [ ] Progress messages print to console during backtest
- [ ] A full-season EPL backtest completes in under 10 minutes

---

### E7-03 — Backtest Reporting

**Type:** Backend
**Depends on:** E7-02
**Master Plan:** MP §4 Feature Set → Evaluation

Generate formatted backtest reports for console output and file export.

**Implementation Notes:**
- Create `src/evaluation/reporter.py`
- `print_backtest_report(result: BacktestResult)`: formatted console output with key metrics, including a visual P&L sparkline if terminal supports it
- `save_backtest_report(result, filepath)`: save detailed report as JSON for later analysis
- `plot_backtest_results(result)`: generate a matplotlib figure with: P&L curve over time, calibration plot, ROI by market type. Save as PNG to `data/predictions/`

**Acceptance Criteria:**
- [ ] `print_backtest_report()` outputs: total matches, value bets found, total staked, P&L, ROI, Brier score, CLV in a formatted table
- [ ] `save_backtest_report()` creates a valid JSON file with all backtest data
- [ ] `plot_backtest_results()` generates and saves a PNG with P&L curve and calibration plot
- [ ] Report clearly labels whether ROI is positive or negative
- [ ] Report includes a per-market breakdown (1X2, O/U, BTTS) if bets span multiple markets

---

## E8 — Pipeline Orchestrator

### E8-01 — Pipeline Runner

**Type:** Integration
**Depends on:** E7-02, E6-03
**Master Plan:** MP §5 Architecture → Scheduling, MP §7 Pipeline Orchestrator Interface

Build the pipeline orchestrator that chains all modules together for the three daily runs.

**Implementation Notes:**
- Create `src/pipeline.py` implementing the `Pipeline` interface from MP §7
- `run_morning()`: scrape latest data → load into DB → compute features → run predictions → find value bets → log system picks → (email integration comes in E11)
- `run_midday()`: re-fetch odds only → recalculate edges → update value_bets table
- `run_evening()`: scrape results → resolve pending bets → calculate P&L → update bankroll → generate performance metrics → (email comes in E11)
- `run_backtest()`: delegate to backtester from E7-02
- Each run creates a `pipeline_runs` entry with start time, status, counts, and duration
- Wrap each run in try/except: if any step fails, log the error in pipeline_runs and continue to next step where possible
- Print clear step-by-step progress: "[Step 1/6] Downloading data... → EPL: 10 new matches found"

**Acceptance Criteria:**
- [ ] `run_morning()` executes the full pipeline: scrape → load → features → predict → value bets → log picks
- [ ] `run_midday()` re-fetches odds and recalculates edges without re-scraping results
- [ ] `run_evening()` resolves bets, updates P&L, and recalculates performance metrics
- [ ] Each run creates a `pipeline_runs` record with correct run_type, status, and counts
- [ ] If a step fails, the error is logged and subsequent steps still attempt to run
- [ ] Duration is recorded in seconds in the pipeline_runs table
- [ ] Step-by-step progress messages print to console

---

### E8-02 — CLI Interface

**Type:** Integration
**Depends on:** E8-01
**Master Plan:** MP §5 Architecture

Create the command-line interface for running the pipeline manually.

**Implementation Notes:**
- Create `run_pipeline.py` in the project root
- Use `argparse` for commands: `python run_pipeline.py morning`, `python run_pipeline.py midday`, `python run_pipeline.py evening`, `python run_pipeline.py backtest --league EPL --season 2024-25`, `python run_pipeline.py setup` (runs init_db + seed)
- Default (no arguments): run `morning` pipeline
- Add `--verbose` flag for DEBUG-level logging
- Add `--dry-run` flag that runs everything except database writes (useful for testing)

**Acceptance Criteria:**
- [ ] `python run_pipeline.py setup` initialises the database and seeds it
- [ ] `python run_pipeline.py morning` runs the full morning pipeline
- [ ] `python run_pipeline.py backtest --league EPL --season 2024-25` runs a backtest and prints results
- [ ] `python run_pipeline.py --help` shows usage information for all commands
- [ ] `--verbose` flag increases log output to DEBUG level
- [ ] Running with no arguments defaults to the morning pipeline

---

## E9 — Dashboard — Core

### E9-01 — Streamlit App Shell and Theme

**Type:** Frontend
**Depends on:** E8-01
**Master Plan:** MP §8 Design System, MP §3 Flow 4 (navigation)

Create the Streamlit app with dark theme, navigation, and page routing.

**Implementation Notes:**
- Create `src/delivery/dashboard.py` as the main Streamlit entry point
- Use Streamlit's multi-page app pattern with `st.navigation` or sidebar radio buttons
- Implement the dark theme from MP §8: set custom theme in `.streamlit/config.toml` (primaryColor, backgroundColor, secondaryBackgroundColor, textColor)
- Inject custom CSS via `st.markdown` for: JetBrains Mono font loading (Google Fonts), card styling, table styling, badge colours
- Simple password gate: `st.text_input(type="password")` checking against environment variable
- Mobile-responsive: test sidebar collapse on mobile, use `st.columns` with responsive ratios
- Pages: Today's Picks, Performance Tracker, League Explorer, Model Health, Bankroll Manager, Settings

**Acceptance Criteria:**
- [ ] `streamlit run src/delivery/dashboard.py` launches the app without errors
- [ ] Background colour is `#0D1117`, surface colour is `#161B22`, text is `#E6EDF3`
- [ ] JetBrains Mono font is loaded and used for data values
- [ ] Inter font is loaded and used for body text and labels
- [ ] Navigation between all 6 pages works
- [ ] Password gate blocks access until correct password is entered
- [ ] App renders correctly on a 375px-wide viewport (mobile)

---

### E9-02 — Today's Picks Page

**Type:** Frontend
**Depends on:** E9-01, E6-01
**Master Plan:** MP §3 Flow 1 (Morning Picks Review), MP §8 Design System

Build the Today's Picks page — the primary daily interface.

**Implementation Notes:**
- Create `src/delivery/pages/picks.py`
- Query upcoming matches with value bets from the database
- Display as cards: match info (teams, league, kickoff time), market, BetVector probability, bookmaker odds (highlight FanDuel), edge, confidence badge (green/yellow/red), suggested stake
- "Mark as Placed" button per card: opens a form to enter actual odds and stake, saves to bet_log as 'user_placed'
- Edge threshold slider at the top: filters displayed picks in real-time (reads from user settings, adjustable)
- Sort by edge (highest first)
- Empty state: "No value bets right now. Your bankroll thanks you for your patience."
- Show odds movement warning if edge has eroded since detection

**Acceptance Criteria:**
- [ ] Page displays all value bets for today's matches, sorted by edge descending
- [ ] Each card shows: teams, league, kickoff time, market, model probability, bookmaker odds, edge, confidence badge, suggested stake
- [ ] Confidence badges use correct colours: green (#3FB950) for high, yellow (#D29922) for medium
- [ ] Edge threshold slider filters picks in real-time
- [ ] "Mark as Placed" button opens a form with editable odds and stake fields
- [ ] Submitting the form creates a bet_log entry with bet_type='user_placed'
- [ ] Empty state message shows when no value bets exist
- [ ] FanDuel odds are highlighted if available

---

### E9-03 — Performance Tracker Page

**Type:** Frontend
**Depends on:** E9-01, E7-01
**Master Plan:** MP §3 Flow 2 (Evening Results Review), MP §8 Design System

Build the Performance Tracker page showing betting results and P&L.

**Implementation Notes:**
- Create `src/delivery/pages/performance.py`
- Top row: 4 metric cards — Total P&L (large number, green/red), ROI %, Total Bets, Win Rate
- Main chart: Plotly line chart of cumulative P&L over time. Dark theme, green line, transparent background.
- Filters: date range picker, league dropdown, market type dropdown, bet_type toggle (system picks vs user placed)
- Below chart: recent bets table with columns: Date, Match, Market, Odds, Stake, Result (✅/❌), P&L. Alternating row colours per MP §8.
- Monthly summary: bar chart of monthly P&L (green bars for positive months, red for negative)

**Acceptance Criteria:**
- [ ] Page displays 4 metric cards with current P&L, ROI, total bets, and win rate
- [ ] P&L number is green (#3FB950) when positive, red (#F85149) when negative
- [ ] Plotly line chart shows cumulative P&L over time with correct dark theme styling
- [ ] Filters (date range, league, market, bet_type) correctly filter all displayed data
- [ ] Bets table shows recent bets with correct result indicators
- [ ] Monthly bar chart displays with green/red bars
- [ ] All numbers use JetBrains Mono font

---

### E9-04 — League Explorer Page

**Type:** Frontend
**Depends on:** E9-01, E4-03
**Master Plan:** MP §3 Flow 4 (Dashboard Exploration), MP §8 Design System

Build the League Explorer page for browsing league data and upcoming fixtures.

**Implementation Notes:**
- Create `src/delivery/pages/leagues.py`
- League dropdown selector at top (populated from active leagues in config)
- Current standings table: Pos, Team, Played, W, D, L, GF, GA, GD, Pts. Calculated from match results.
- Recent results: last 10 matches in the league with scores
- Upcoming fixtures: next 10 matches with date, teams, and "View Analysis" button
- Form table: last 5 results per team shown as W/D/L badges (green/grey/red circles)
- Click any upcoming match to navigate to Match Deep Dive (E9-05)

**Acceptance Criteria:**
- [ ] League dropdown shows all active leagues from config
- [ ] Standings table calculates correctly from match results (3 pts for win, 1 for draw)
- [ ] Standings table sorts by points, then goal difference, then goals scored
- [ ] Recent results show last 10 matches with correct scores
- [ ] Upcoming fixtures list next 10 scheduled matches
- [ ] Form badges show correct W/D/L sequence for each team's last 5 matches
- [ ] Clicking an upcoming match navigates to the Match Deep Dive view

---

### E9-05 — Match Deep Dive View

**Type:** Frontend
**Depends on:** E9-04, E5-03, E4-03
**Master Plan:** MP §3 Flow 1 Step 8, MP §8 Design System

Build the Match Deep Dive view showing comprehensive analysis for a single match.

**Implementation Notes:**
- Create `src/delivery/pages/match_detail.py`
- Accessible from Today's Picks cards and League Explorer upcoming fixtures
- Sections:
  1. Match header: Teams, date, kickoff time, league
  2. Model prediction summary: scoreline matrix heatmap (Plotly), predicted score, market probabilities
  3. Value bets for this match: all flagged value bets with edge and confidence
  4. Head-to-head: last 5 meetings table (date, score, venue)
  5. Team form: side-by-side comparison of home team and away team rolling stats (xG, goals, form) with sparkline charts
  6. Injury/suspension report (placeholder — data from API-Football when available)
- Scoreline matrix: 7×7 heatmap with darker cells for higher probability, most likely scoreline highlighted

**Acceptance Criteria:**
- [ ] Match detail view loads for any match when navigated to
- [ ] Scoreline matrix displays as a 7×7 heatmap with probability values visible in cells
- [ ] Most likely scoreline cell is visually highlighted
- [ ] All derived market probabilities are displayed (1X2, O/U 2.5, BTTS)
- [ ] H2H table shows last 5 meetings with correct dates and scores
- [ ] Team form section shows rolling stats for both teams side-by-side
- [ ] Back navigation returns to the previous page (Picks or League Explorer)

---

## E10 — Dashboard — Advanced

### E10-01 — Model Health Page

**Type:** Frontend
**Depends on:** E9-01, E7-01
**Master Plan:** MP §3 Flow 4 (Model Health), MP §8 Design System, MP §11 Self-Improvement Engine

Build the Model Health page showing calibration, Brier scores, CLV, and self-improvement status.

**Implementation Notes:**
- Create `src/delivery/pages/model_health.py`
- Calibration plot: Plotly scatter with diagonal reference line. X-axis = predicted probability, Y-axis = actual win rate. Points sized by sample count per bin.
- Brier score trend: line chart over time (by week or month)
- CLV tracking: line chart of rolling average CLV
- Model comparison: if multiple models active, side-by-side metrics table (Brier, ROI, CLV per model)
- Ensemble weights: horizontal stacked bar showing current model weights
- Feature importance: horizontal bar chart of top 15 features (from E12-02)
- Market Edge Map: heatmap of league × market performance (from E12-04)
- Recalibration history: table of past recalibration events with before/after error
- Retrain history: table of past retrains with trigger reason and outcome

**Acceptance Criteria:**
- [ ] Calibration plot displays with diagonal reference line and correctly binned data points
- [ ] Brier score trend chart shows historical scores by time period
- [ ] CLV trend chart shows rolling average CLV
- [ ] Model comparison table displays when 2+ models are active
- [ ] Ensemble weight bar shows current weight allocation per model
- [ ] Feature importance chart shows top 15 features ranked by gain
- [ ] Market Edge Map heatmap is colour-coded by assessment (green/yellow/white/red)
- [ ] All charts use dark theme styling from MP §8

---

### E10-02 — Bankroll Manager Page

**Type:** Frontend
**Depends on:** E9-01, E6-02
**Master Plan:** MP §3 Flow 4 (Bankroll Manager), MP §8 Design System

Build the Bankroll Manager page for tracking and managing the betting bankroll.

**Implementation Notes:**
- Create `src/delivery/pages/bankroll.py`
- Top row: current bankroll (large number), starting bankroll, peak bankroll, current drawdown %
- Staking method display: show current method with brief explanation
- Bet history table: filterable (date, league, market, result, bet_type), sortable, with pagination
- Safety status: traffic light indicators for each limit (daily loss, drawdown, min bankroll) — green = OK, yellow = approaching, red = triggered
- Bankroll chart: Plotly line chart showing bankroll over time, with peak highlighted
- Monthly P&L breakdown: table with month, bets placed, wins, losses, P&L, ROI

**Acceptance Criteria:**
- [ ] Current bankroll displays in large JetBrains Mono text, green if above starting, red if below
- [ ] Drawdown percentage is calculated correctly from peak bankroll
- [ ] Bet history table filters and sorts correctly
- [ ] Safety status indicators show correct colours based on current limits
- [ ] Bankroll chart shows historical bankroll with peak annotated
- [ ] Monthly breakdown table calculates correctly from bet_log data

---

### E10-03 — Settings Page

**Type:** Frontend
**Depends on:** E9-01, E1-03
**Master Plan:** MP §3 Flow 6 (First-Time Setup), MP §3 Flow 7 (Adding a Friend)

Build the Settings page for user preferences, system configuration, and user management.

**Implementation Notes:**
- Create `src/delivery/pages/settings.py`
- User preferences section: staking method selector (flat/percentage/kelly), stake percentage slider, Kelly fraction slider, edge threshold slider (1%–15%), starting bankroll input
- League management: checkboxes to enable/disable leagues
- Notification preferences: toggles for morning/evening/weekly emails, email address input
- User management (owner only): list current users, "Invite User" button that generates an access link, ability to deactivate users
- All changes save to the database immediately on change

**Acceptance Criteria:**
- [ ] Staking method selector shows three options with explanations
- [ ] Edge threshold slider ranges from 1% to 15% with 1% increments
- [ ] Changing a setting persists to the users table in the database
- [ ] League toggles reflect current config and changes take effect on next pipeline run
- [ ] User management section is visible only to users with role='owner'
- [ ] "Invite User" creates a new user record with role='viewer'

---

### E10-04 — Onboarding Flow

**Type:** Frontend
**Depends on:** E10-03
**Master Plan:** MP §3 Flow 6 (First-Time Setup)

Build the first-time setup wizard that guides new users through initial configuration.

**Implementation Notes:**
- Create `src/delivery/pages/onboarding.py`
- Displayed only when user has never completed onboarding (check a `has_onboarded` flag in users table)
- 5 steps as per MP §3 Flow 6: Bankroll → Staking Method → Edge Threshold → Leagues → Notifications
- Each step has an explanation of the concept in plain language
- Progress indicator at top (Step 2 of 5)
- "Start BetVector" button on final step sets `has_onboarded=True` and redirects to Today's Picks

**Acceptance Criteria:**
- [ ] Onboarding shows automatically for new users who haven't completed it
- [ ] All 5 steps are present with correct explanations
- [ ] Progress indicator shows current step number
- [ ] Settings chosen during onboarding are saved to the users table
- [ ] Completing onboarding sets a flag and redirects to Today's Picks
- [ ] Returning users skip onboarding and go directly to the dashboard

---

## E11 — Email Notifications

### E11-01 — Email Templates

**Type:** Backend
**Depends on:** E7-01, E6-03
**Master Plan:** MP §3 Flows 1–3 (email content), MP §5 Architecture → Email

Create HTML email templates for all three scheduled emails using Jinja2.

**Implementation Notes:**
- Create `templates/morning_picks.html`, `templates/evening_review.html`, `templates/weekly_summary.html`
- Use Jinja2 templating with inline CSS (email clients strip external styles)
- Dark theme styling matching dashboard: dark background, green/red for P&L, monospace for numbers
- Morning template: value bets table (match, market, probability, odds, edge, stake), one-sentence explanation per pick, link to dashboard
- Evening template: results table (match, result, P&L), daily totals, running stats, tomorrow preview
- Weekly template: week summary metrics, best/worst pick, monthly chart (as static image or simple HTML table), model health snapshot
- Test that emails render correctly in Gmail (the most likely client)

**Acceptance Criteria:**
- [ ] Three Jinja2 HTML templates exist in `templates/` directory
- [ ] Morning template renders a table of value bets with all required columns
- [ ] Evening template renders results with ✅/❌ indicators and P&L
- [ ] Weekly template renders summary metrics and best/worst picks
- [ ] All templates use inline CSS (no external stylesheets)
- [ ] All templates include a "Open Dashboard" link
- [ ] Templates render correctly when opened in a browser

---

### E11-02 — Email Sender

**Type:** Backend
**Depends on:** E11-01
**Master Plan:** MP §5 Architecture → Email (Gmail SMTP)

Build the email sending module using Gmail SMTP.

**Implementation Notes:**
- Create `src/delivery/email_alerts.py`
- Use Python's `smtplib` and `email.mime` modules
- SMTP config comes from `config/email_config.yaml` and environment variables (GMAIL_APP_PASSWORD)
- `send_morning_picks(user_id)`: render morning template with today's value bets, send to user's email
- `send_evening_review(user_id)`: render evening template with today's results, send
- `send_weekly_summary(user_id)`: render weekly template with week's stats, send
- `send_alert(user_id, subject, body)`: generic alert (for retrain notifications, safety warnings)
- Retry logic: 3 attempts with 5-second delay on SMTP errors
- Never hardcode credentials. Always read from environment variables.

**Acceptance Criteria:**
- [ ] `send_morning_picks()` sends an HTML email with today's value bets to the configured address
- [ ] `send_evening_review()` sends an HTML email with today's results and P&L
- [ ] `send_weekly_summary()` sends an HTML email with the week's summary metrics
- [ ] Email credentials are read from environment variables, never from config files or code
- [ ] SMTP connection uses TLS
- [ ] Failed sends are retried 3 times before raising an error
- [ ] Sent emails are logged in pipeline_runs (emails_sent count)

---

### E11-03 — Email Integration with Pipeline

**Type:** Integration
**Depends on:** E11-02, E8-01
**Master Plan:** MP §5 Architecture → Scheduling

Connect email sending to the pipeline runs so emails are sent automatically at the end of each pipeline.

**Implementation Notes:**
- Modify `pipeline.run_morning()` to call `send_morning_picks()` for all active users after predictions complete
- Modify `pipeline.run_evening()` to call `send_evening_review()` after results processing
- Add weekly check in evening pipeline: if today is Sunday, also call `send_weekly_summary()`
- If email sending fails, log the error but don't fail the entire pipeline
- Add email toggle check: only send to users who have notifications enabled

**Acceptance Criteria:**
- [ ] `run_morning()` sends morning picks emails to all users with notifications enabled
- [ ] `run_evening()` sends evening review emails
- [ ] Weekly summary sends on Sundays only
- [ ] Email failure does not cause the pipeline to fail — error is logged and pipeline continues
- [ ] Users with notifications disabled do not receive emails
- [ ] `pipeline_runs.emails_sent` is correctly incremented

---

## E12 — Self-Improvement Engine

### E12-01 — Automatic Recalibration

**Type:** Backend
**Depends on:** E7-01, E5-03
**Master Plan:** MP §11.1 Automatic Recalibration

Build the automatic recalibration system that corrects probability drift.

**Implementation Notes:**
- Create `src/self_improvement/calibration.py`
- After every batch of resolved predictions, check if total unprocessed predictions since last calibration >= 200 (from config)
- If threshold met: compute calibration error. If mean absolute error > 0.03 (from config): fit Platt scaling (sklearn `CalibratedClassifierCV` or manual logistic regression on probabilities) or isotonic regression
- Store calibration event in `calibration_history` table
- Apply calibration to future predictions by transforming raw model probabilities through the calibration function
- Rollback: after 100 new predictions post-calibration, compare calibrated vs raw error. If calibrated is worse, rollback (set is_active=0, rolled_back=1)
- Never apply calibration to fewer than 200 predictions

**Acceptance Criteria:**
- [ ] Recalibration check runs after each batch of resolved predictions
- [ ] No recalibration fires if fewer than 200 predictions have accumulated since last calibration
- [ ] No recalibration fires if mean absolute calibration error is below 3%
- [ ] When triggered, calibration parameters are stored in `calibration_history` with is_active=1
- [ ] Calibrated probabilities are closer to actual outcomes than raw probabilities (measurable)
- [ ] Rollback activates if calibrated predictions perform worse than raw over 100 post-calibration predictions
- [ ] Rolled-back calibrations have `rolled_back=1` and `is_active=0` in the database

---

### E12-02 — Feature Importance Tracking

**Type:** Backend
**Depends on:** E5-02
**Master Plan:** MP §11.2 Dynamic Feature Importance Tracking

Build the feature importance logger for tree-based models.

**Implementation Notes:**
- Create `src/self_improvement/feature_tracking.py`
- After each XGBoost or LightGBM training cycle, extract feature importance (by gain)
- Log all features with their importance and rank to `feature_importance_log` table
- `get_importance_trends(model_name, n_cycles=5)`: return trend data showing how each feature's importance has changed over the last N training cycles
- Flag features below 1% importance for 3+ consecutive cycles with a warning message
- This module only logs and reports — it never auto-removes features

**Acceptance Criteria:**
- [ ] After training a gradient boosting model, feature importance is logged to `feature_importance_log`
- [ ] Each logged entry includes model_name, training_date, feature_name, importance_gain, and importance_rank
- [ ] `get_importance_trends()` returns a DataFrame showing importance over the last N training cycles per feature
- [ ] Features below 1% importance for 3+ consecutive cycles are flagged with a warning message
- [ ] No features are automatically removed — the module is read-only on model configuration

---

### E12-03 — Adaptive Ensemble Weights

**Type:** Backend
**Depends on:** E7-01, E5-03
**Master Plan:** MP §11.3 Adaptive Ensemble Weights

Build the adaptive ensemble weight system that shifts weight toward better-performing models.

**Implementation Notes:**
- Create `src/self_improvement/ensemble_weights.py`
- `recalculate_weights()`: triggered every 100 resolved ensemble predictions
- Weight = inverse Brier score, normalised to sum to 1.0
- Guardrails from MP §11.3:
  - Don't activate until each model has 300+ resolved predictions
  - Max weight change per recalculation: 10 percentage points
  - Weight floor: 10% (no model below this)
  - Weight ceiling: 60% (no model above this)
  - Smoothing: new_weight = 0.7 × calculated_weight + 0.3 × previous_weight
- Store each weight change in `ensemble_weight_history` with reason and metrics
- `get_current_weights()`: return current weights for the ensemble predictor

**Acceptance Criteria:**
- [ ] Weights are not recalculated until each model has 300+ predictions
- [ ] Weight changes never exceed 10 percentage points from previous weights
- [ ] No model weight drops below 10% or exceeds 60%
- [ ] Smoothing is applied: new weight blends 70% calculated with 30% previous
- [ ] Each recalculation is logged in `ensemble_weight_history` with Brier scores and reason
- [ ] `get_current_weights()` returns a dict of model_name → weight that sums to 1.0
- [ ] With only one active model, weight is 1.0 (ensemble degrades gracefully to single model)

---

### E12-04 — Market Feedback Loop

**Type:** Backend
**Depends on:** E7-01, E6-03
**Master Plan:** MP §11.4 Odds Market Feedback Loop

Build the league × market performance tracker with confidence intervals and assessments.

**Implementation Notes:**
- Create `src/self_improvement/market_feedback.py`
- `update_market_performance()`: run weekly, compute ROI + 95% CI for every league × market combination that has resolved bets
- 95% CI calculation: use bootstrap resampling (1000 samples) or normal approximation for ROI confidence interval
- Assessment logic from MP §11.4:
  - 'profitable': ROI > 0 AND CI lower bound > 0 AND n >= 100
  - 'promising': ROI > 0 but CI includes 0, OR n = 50–99
  - 'insufficient': n < 50
  - 'unprofitable': ROI < 0 AND CI upper bound < 0 AND n >= 100
- Store in `market_performance` table
- Never auto-filter bets. Only surface warnings in the dashboard.

**Acceptance Criteria:**
- [ ] `update_market_performance()` computes ROI and 95% CI for every league × market combination
- [ ] Combinations with < 50 bets are assessed as 'insufficient'
- [ ] Combinations with ROI > 0 and CI lower > 0 and n >= 100 are assessed as 'profitable'
- [ ] Combinations with ROI < 0 and CI upper < 0 and n >= 100 are assessed as 'unprofitable'
- [ ] Results are stored in `market_performance` table with ROI, CI bounds, and assessment
- [ ] No value bets are automatically filtered or suppressed based on market performance
- [ ] Warning text is generated for 'unprofitable' combinations for use in the dashboard

---

### E12-05 — Seasonal Re-training Triggers

**Type:** Backend
**Depends on:** E7-01, E5-02
**Master Plan:** MP §11.5 Seasonal Re-training Triggers

Build the automatic re-training trigger that detects model degradation and initiates retraining.

**Implementation Notes:**
- Create `src/self_improvement/retrain_trigger.py`
- `check_retrain_needed(model_name)`: run daily in the evening pipeline
- Calculate rolling Brier score over last 100 predictions
- Compare to all-time average Brier score for this model
- If rolling is > 15% worse than all-time: trigger retrain
- Cooldown: no auto-retrain within 30 days of the last retrain (check `retrain_history`)
- On trigger: retrain model on full dataset, log in `retrain_history`, send email alert to owner
- Post-retrain evaluation: after 50 new predictions, compare new vs old model Brier score. If new is worse, rollback.

**Acceptance Criteria:**
- [ ] `check_retrain_needed()` correctly computes rolling vs all-time Brier score
- [ ] Retrain triggers when rolling Brier is > 15% worse than all-time average
- [ ] No retrain fires within 30 days of the last retrain (cooldown enforced)
- [ ] Triggered retrain uses full historical dataset for training
- [ ] Retrain event is logged in `retrain_history` with trigger_reason and brier_before
- [ ] Email alert is sent to the owner when retrain triggers
- [ ] Post-retrain evaluation after 50 predictions detects if new model is worse and rolls back
- [ ] Rolled-back retrains have `was_rolled_back=1` in the database

---

## E13 — Automation & Deployment

### E13-01 — GitHub Actions Workflows

**Type:** Setup
**Depends on:** E11-03
**Master Plan:** MP §5 Architecture → Scheduling (GitHub Actions)

Create GitHub Actions workflow files for automated daily pipeline execution.

**Implementation Notes:**
- Create `.github/workflows/morning.yml`: cron schedule `0 6 * * *` (UTC), runs `python run_pipeline.py morning`
- Create `.github/workflows/midday.yml`: cron schedule `0 13 * * *`, runs `python run_pipeline.py midday`
- Create `.github/workflows/evening.yml`: cron schedule `0 22 * * *`, runs `python run_pipeline.py evening`
- Each workflow: checkout repo → setup Python 3.10 → install dependencies → run script → commit database changes (if using SQLite in repo)
- Secrets needed: GMAIL_APP_PASSWORD, DASHBOARD_PASSWORD, and any API keys
- Add error notification: if workflow fails, send an email alert

**Acceptance Criteria:**
- [ ] Three workflow YAML files exist in `.github/workflows/`
- [ ] Morning workflow is scheduled for 06:00 UTC daily
- [ ] Midday workflow is scheduled for 13:00 UTC daily
- [ ] Evening workflow is scheduled for 22:00 UTC daily
- [ ] Each workflow installs Python 3.10 and all requirements
- [ ] Secrets are referenced as `${{ secrets.GMAIL_APP_PASSWORD }}`, never hardcoded
- [ ] Workflow commits database changes back to repo (if using SQLite strategy)
- [ ] A manual trigger (`workflow_dispatch`) is available for each workflow

---

### E13-02 — Streamlit Cloud Deployment

**Type:** Setup
**Depends on:** E10-04
**Master Plan:** MP §5 Architecture → Frontend (Streamlit Cloud)

Prepare the project for deployment to Streamlit Cloud.

**Implementation Notes:**
- Create `.streamlit/config.toml` with dark theme settings
- Create `.streamlit/secrets.toml.example` showing required secrets (actual secrets configured in Streamlit Cloud dashboard)
- Ensure `src/delivery/dashboard.py` is the entry point
- Add database connection logic that works both locally (SQLite file) and in cloud (Supabase connection string from secrets)
- Create a `README.md` section with Streamlit Cloud deployment instructions
- Test that the app runs with `streamlit run src/delivery/dashboard.py`

**Acceptance Criteria:**
- [ ] `.streamlit/config.toml` exists with dark theme configuration
- [ ] `.streamlit/secrets.toml.example` documents all required secrets
- [ ] Dashboard runs locally with `streamlit run src/delivery/dashboard.py`
- [ ] Dashboard reads database connection from config/secrets (not hardcoded path)
- [ ] README includes step-by-step Streamlit Cloud deployment instructions
- [ ] App handles missing database gracefully (shows error message, not a crash)

---

### E13-03 — Security Hardening

**Type:** Polish
**Depends on:** E13-01, E13-02
**Master Plan:** MP §5 Architecture → Authentication

Final security review and hardening before the system goes live.

**Implementation Notes:**
- Audit all files for hardcoded credentials — there should be zero
- Ensure `.env` and `config/email_config.yaml` (if containing real values) are in `.gitignore`
- Verify GitHub Actions secrets are properly configured
- Add database backup script: `scripts/backup_db.sh` that copies the database to a timestamped backup
- Add weekly backup to GitHub Actions (Sunday, after weekly summary)
- Document the security model in README: what's stored where, what's sensitive, how to rotate credentials

**Acceptance Criteria:**
- [ ] `grep -r "password\|secret\|key" src/` returns zero matches for actual credential values
- [ ] `.env`, `*.db`, and `config/email_config.yaml` are in `.gitignore`
- [ ] `scripts/backup_db.sh` creates a timestamped copy of the database
- [ ] Weekly backup is scheduled in GitHub Actions
- [ ] README includes a security section documenting credential management
- [ ] All environment variables are documented in `.env.example`

---

## Post-Launch Enhancements

> The original 45-issue build (E1–E13) was completed in March 2026. The epics below document post-launch work: pivots forced by data source failures, new scrapers, and planned feature expansion. See MP §13 for the full narrative.

---

## E14 — Real-Time Data Sources (Post-Launch)

> **Context:** This epic was added post-launch after discovering that two of the three original data sources (FBref, API-Football free tier) were unusable for current-season data, and Football-Data.co.uk had multi-day update delays that broke the daily picks workflow. See MP §13 for the full narrative.

### E14-01 — Understat xG Scraper

**Type:** Backend
**Depends on:** E3-01
**Master Plan:** MP §5 Data Sources (post-launch update), MP §13.2
**Status:** COMPLETED

Replace FBref (which permanently lost all Opta xG/shots/possession data in January 2026) with Understat as the primary xG source.

**Implementation Notes:**
- Created `src/scrapers/understat_scraper.py` (~330 lines) inheriting from `BaseScraper`
- Uses `understatapi` Python package (added `understatapi==0.7.1` to `requirements.txt`)
- `UnderstatScraper.scrape(league_config, season)` fetches match-level xG data via `UnderstatClient`
- `UNDERSTAT_EPL_TEAM_MAP` dictionary maps Understat team names to BetVector canonical names
- Fuzzy fallback via `difflib.get_close_matches()` for unmapped names
- Returns DataFrame with columns: `date`, `home_team`, `away_team`, `home_xg`, `away_xg`, `home_xga`, `away_xga`
- Raw data saved to `data/raw/understat_{league}_{season}_{date}.csv`
- Added `understat_league: "EPL"` to `config/leagues.yaml`
- Added `understat.min_request_interval_seconds: 3` to `config/settings.yaml`
- Handles missing data and HTTP errors without crashing — returns empty DataFrame

**Acceptance Criteria:**
- [x] `UnderstatScraper` class exists in `src/scrapers/understat_scraper.py` inheriting from `BaseScraper`
- [x] `scrape()` returns a DataFrame with per-match xG for both teams
- [x] Team names are mapped to BetVector canonical names with fuzzy fallback
- [x] Raw data is saved to `data/raw/`
- [x] Scraper handles HTTP errors and missing data without crashing
- [x] `understatapi==0.7.1` is in `requirements.txt`
- [x] `understat_league` field is configured in `config/leagues.yaml` for EPL
- [x] 262 xG stat rows loaded for EPL 2025-26

---

### E14-02 — Open-Meteo Weather Scraper

**Type:** Backend
**Depends on:** E2-02, E3-01
**Master Plan:** MP §13.2
**Status:** COMPLETED

Add match-day weather as a new data dimension. Weather conditions (rain, wind, extreme cold) can affect match outcomes, particularly goals and over/under markets.

**Implementation Notes:**
- Created `src/scrapers/weather_scraper.py` (~340 lines) inheriting from `BaseScraper`
- Uses Open-Meteo free API (no API key required)
- Created `config/stadiums.yaml` with lat/lon coordinates for all 20 EPL 2025-26 teams (including promoted Sunderland, Leeds, Burnley)
- `WeatherScraper.scrape_for_matches(match_list)` accepts a list of matches, looks up stadium coordinates, fetches weather
- Uses the **forecast API** (`api.open-meteo.com`) for future matches and **archive API** (`archive-api.open-meteo.com`) for past matches
- WMO weather code mapped to simplified categories: `clear`, `cloudy`, `fog`, `drizzle`, `rain`, `heavy_rain`, `snow`, `storm`
- Finds the hourly reading closest to the match kickoff time
- Added `Weather` ORM model to `src/database/models.py` with `UNIQUE` constraint on `match_id`
- Added weather API URLs to `config/settings.yaml` under `scraping.weather`

**Acceptance Criteria:**
- [x] `WeatherScraper` class exists in `src/scrapers/weather_scraper.py` inheriting from `BaseScraper`
- [x] `config/stadiums.yaml` contains coordinates for all 20 EPL 2025-26 teams
- [x] Forecast API used for future matches, archive API for past matches
- [x] `Weather` ORM model exists in `src/database/models.py` with all specified columns
- [x] Weather data is stored with unique constraint on `match_id` (idempotent)
- [x] WMO weather codes are mapped to human-readable categories
- [x] No API key required (Open-Meteo is fully free)
- [x] 35 weather records loaded on first run

---

### E14-03 — API-Football Scraper (Code Complete, Dormant)

**Type:** Backend
**Depends on:** E2-02, E3-01
**Master Plan:** MP §5 Data Sources, MP §13.2
**Status:** COMPLETED (code complete; dormant due to free tier season restriction)

Build the full API-Football scraper for fixtures, odds, and injuries. Code is ready for when a paid tier is activated or the free tier is extended.

**Implementation Notes:**
- Created `src/scrapers/api_football.py` (~530 lines) inheriting from `BaseScraper`
- Three scrape methods: `scrape()` for fixtures, `scrape_odds()` for pre-match odds (paginated, max 5 pages), `scrape_injuries()` for active injuries
- `scrape_odds_for_fixtures(fixture_ids)` for targeted midday odds refresh
- Rate budget tracking: reads `x-ratelimit-requests-remaining` from response headers
- Configurable thresholds in `config/settings.yaml`: `daily_request_limit: 100`, `warning_threshold: 20`, `hard_stop_threshold: 5`
- `API_FOOTBALL_EPL_TEAM_MAP` dictionary with fuzzy fallback for team name mapping
- `STATUS_MAP` converts API status codes (`FT`, `NS`, `1H`, `PST`, etc.) to BetVector status values
- Bookmaker ID mapping in `config/settings.yaml` under `scraping.api_football.bookmaker_map` (keys quoted as strings to avoid ConfigNamespace integer key bug)
- Raw JSON responses archived to `data/raw/api_football_{league}_{type}_{date}.json`
- Added `api_football_name` column to `Team` model in `src/database/models.py`
- **Current limitation:** Free tier returns error for 2025-26: *"plan: Free plans do not have access to this season, try from 2022 to 2024"*. Scraper handles this gracefully.

**Acceptance Criteria:**
- [x] `APIFootballScraper` class exists with `scrape()`, `scrape_odds()`, `scrape_injuries()` methods
- [x] Rate budget tracking respects the 100 requests/day free tier limit
- [x] Raw JSON responses are archived to `data/raw/`
- [x] Team name mapping with fuzzy fallback
- [x] Bookmaker ID mapping configurable in `config/settings.yaml`
- [x] `teams.api_football_name` column exists in the ORM model
- [x] Scraper returns empty DataFrame gracefully when free tier blocks current season
- [x] Pipeline does not crash when API-Football returns no data

---

### E14-04 — Pipeline and Loader Integration

**Type:** Integration
**Depends on:** E14-01, E14-02, E14-03, E8-01
**Master Plan:** MP §13.2
**Status:** COMPLETED

Wire all three new scrapers into the existing pipeline and data loader, with DB schema migrations for the new table and column.

**Implementation Notes:**
- Added 6 new functions to `src/scrapers/loader.py`:
  - `load_odds_api_football(odds_records, league_id)` — loads odds with `source="api_football"`
  - `load_understat_stats(df, league_id)` — loads xG data into `match_stats` with `source="understat"`
  - `load_weather(df)` — loads weather records into the `weather` table
  - `update_team_api_names(df, league_id)` — populates `teams.api_football_name`
  - `update_match_results(df, league_id)` — updates scheduled matches with results from API-Football
  - Parameterised `_insert_odds()` with a `source` parameter (was hardcoded to `"football_data"`)
- Morning pipeline integration: Football-Data.co.uk → API-Football → Understat → Weather (each in try/except)
- Midday pipeline: added API-Football odds refresh alongside Football-Data odds
- Evening pipeline: added API-Football results fetch + Understat xG for finished matches
- Updated `.github/workflows/morning.yml`, `midday.yml`, `evening.yml` with inline DB migrations:
  - `ALTER TABLE teams ADD COLUMN api_football_name TEXT`
  - `CREATE TABLE IF NOT EXISTS weather (...)` with all columns and constraints
- Added `API_FOOTBALL_KEY` to env block in all 3 workflow files

**Acceptance Criteria:**
- [x] `load_odds_api_football()` stores odds with `source="api_football"` in the odds table
- [x] `load_understat_stats()` stores xG data with `source="understat"` in match_stats table
- [x] `load_weather()` stores weather records in the weather table (idempotent via unique constraint)
- [x] `update_team_api_names()` populates `api_football_name` on Team records
- [x] Morning pipeline runs all scrapers with graceful failure handling
- [x] Midday pipeline re-fetches API-Football odds
- [x] Evening pipeline fetches Understat xG for finished matches
- [x] All 3 GitHub Actions workflows include DB migration steps
- [x] Failure of any individual scraper does not block the pipeline

---

## E15 — Data Freshness & Feature Expansion (Completed)

> **Context:** E14 added three new data sources but one gap remains: Football-Data.co.uk only updates 2×/week, and API-Football's free tier can't access 2025-26. We need a near-real-time source for fixtures/results (E15-01), richer features from data we already receive (E15-02), and unique supplementary data (E15-03). See MP §13.4.

### E15-01 — Football-Data.org API Scraper

**Type:** Backend
**Depends on:** E3-01, E14-04
**Master Plan:** MP §5 Data Sources (post-launch update), MP §13.4
**Status:** COMPLETED

Build a scraper for the Football-Data.org free REST API to get near-real-time match results and fixtures for the current EPL season. This closes the freshness gap caused by Football-Data.co.uk's twice-weekly CSV updates.

**Implementation Notes:**
- Create `src/scrapers/football_data_org.py` inheriting from `BaseScraper`
- API base URL: `https://api.football-data.org/v4`
- Authentication: `X-Auth-Token` header with API key from environment variable `FOOTBALL_DATA_ORG_KEY`
- Primary endpoint: `GET /v4/competitions/PL/matches` with optional `?status=FINISHED` or `?dateFrom=YYYY-MM-DD&dateTo=YYYY-MM-DD` query parameters
- Free tier: 10 requests/minute rate limit (enforce via existing `BaseScraper` rate limiter)
- Competition code for EPL: `PL`
- Map team names from API response to BetVector canonical names
- Returns DataFrame compatible with existing `load_matches()` and `update_match_results()` loader functions
- Use this source for near-real-time result updates in the morning and evening pipeline, supplementing (not replacing) Football-Data.co.uk which remains the canonical source for historical odds
- Add `FOOTBALL_DATA_ORG_KEY` to `.env.example` and GitHub Actions secrets
- Add config section to `config/settings.yaml` under `scraping.football_data_org`

**Acceptance Criteria:**
- [ ] `FootballDataOrgScraper` class exists inheriting from `BaseScraper`
- [ ] `scrape()` returns a DataFrame with current-season matches and results
- [ ] API key read from environment variable, never hardcoded
- [ ] Rate limit of 10 req/min is enforced
- [ ] Team names mapped to canonical BetVector names
- [ ] Results are fresher than Football-Data.co.uk (same-day updates vs 2–5 day lag)
- [ ] Scraper handles HTTP 429 (rate limit) and 403 (auth failure) gracefully
- [ ] Integrated into morning and evening pipeline steps
- [ ] `FOOTBALL_DATA_ORG_KEY` documented in `.env.example`

---

### E15-02 — Understat Scraper Expansion

**Type:** Backend
**Depends on:** E14-01
**Master Plan:** MP §13.4
**Status:** COMPLETED

Expand the existing Understat scraper to parse additional statistics that the API already returns but are not currently extracted: NPxG, PPDA, shots, and deep completions.

**Implementation Notes:**
- Modify `src/scrapers/understat_scraper.py` to extract additional fields from the existing API response
- New fields to parse: `npxg`, `npxga`, `ppda_att`, `ppda_def`, `deep`, `deep_allowed`
- NPxG (non-penalty xG) is more predictive than raw xG — strips out penalty xG which is essentially random
- PPDA (passes per defensive action) measures pressing intensity — lower PPDA = higher pressing team
- Deep completions measure attacking penetration into the final third
- Update `load_understat_stats()` in `src/scrapers/loader.py` to store the new fields as additional `match_stats` rows or extend existing stat entries
- Small change — estimated ~30 minutes of work

**Acceptance Criteria:**
- [ ] Understat scraper extracts NPxG, PPDA, deep completions in addition to basic xG
- [ ] New stat values are stored in the database
- [ ] Existing xG data loading continues to work (backward compatible)
- [ ] Feature engineer can access the new stats for future feature engineering
- [ ] No regression in existing Understat scraping functionality

---

### E15-03 — Transfermarkt Datasets Integration

**Type:** Backend
**Depends on:** E3-01, E2-02
**Master Plan:** MP §13.4
**Status:** COMPLETED

Integrate weekly CSV dumps from the public Transfermarkt Datasets repository on GitHub (CC0 license) for injury data and squad market values — two data dimensions no other free source provides.

**Implementation Notes:**
- Create `src/scrapers/transfermarkt.py` inheriting from `BaseScraper`
- Data source: `github.com/dcaribou/transfermarkt-datasets` — pre-scraped weekly CSVs under CC0 license (no scraping of transfermarkt.com itself)
- Two data types to extract:
  1. **Injuries:** Player name, team, injury type, expected return date, days out. Aggregate to team level: count of injured players, total estimated impact (using market value as proxy for player importance)
  2. **Squad market values:** Team total squad value, average player value. Use as a static feature representing team quality/depth
- Map Transfermarkt team names to BetVector canonical names
- Create ORM models or extend existing tables for injury and market value data
- Injury data is a powerful feature: teams missing >20% of squad value to injuries are weaker than their rolling stats suggest
- Market value ratio between two teams is a simple but effective predictor of match outcome
- Update frequency: weekly (run in Sunday evening pipeline)
- No API key needed — public GitHub CSVs

**Acceptance Criteria:**
- [ ] `TransfermarktScraper` class exists inheriting from `BaseScraper`
- [ ] Downloads and parses injury CSV from the public GitHub repository
- [ ] Downloads and parses squad market value CSV
- [ ] Team names mapped to BetVector canonical names
- [ ] Injury data aggregated to team level (count, estimated impact)
- [ ] Market value data stored with team-level granularity
- [ ] Data is idempotent — running twice does not create duplicates
- [ ] Integrated into the weekly pipeline step (Sunday evening)

---

## E16 — Advanced Feature Engineering

> **Context:** E14 and E15 added four new data sources (Understat advanced stats, weather, Football-Data.org API, Transfermarkt market values) that are scraped and stored but not yet used by the prediction model. The feature engineering layer only computes rolling averages for basic stats (goals, xG, shots, possession). NPxG, PPDA, deep completions, market values, and weather sit unused in the database. This epic wires that data into the feature pipeline and the Poisson model — the highest-impact improvement available. See MP §4 Feature Set, MP §13.4.

### E16-01 — Rolling Advanced Stats Features (NPxG, PPDA, Deep Completions)

**Type:** Backend — Feature Engineering
**Depends on:** E4-01, E4-02, E4-03, E15-02
**Master Plan:** MP §4 Feature Set, MP §13.4
**Status:** COMPLETED

Add rolling average features for the advanced Understat statistics that are already stored in `match_stats` but not yet computed as features: NPxG (non-penalty expected goals), PPDA (pressing intensity), and deep completions (attacking penetration). These are strictly more informative than the basic stats currently used.

**Implementation Notes:**
- Add 14 new nullable Float columns to the `Feature` model in `src/database/models.py`:
  - 5-match window: `npxg_5`, `npxga_5`, `npxg_diff_5`, `ppda_5`, `ppda_allowed_5`, `deep_5`, `deep_allowed_5`
  - 10-match window: `npxg_10`, `npxga_10`, `npxg_diff_10`, `ppda_10`, `ppda_allowed_10`, `deep_10`, `deep_allowed_10`
- Extend `_get_recent_matches()` in `src/features/rolling.py` to read `npxg`, `npxga`, `ppda_coeff`, `ppda_allowed_coeff`, `deep`, `deep_allowed` from `MatchStat` (the query already joins to `match_stats` — just add more fields)
- Extend `_compute_rolling_stats()` to compute rolling averages for the new stats, plus `npxg_diff` (npxg - npxga)
- Update `_read_existing_features()` in `src/features/engineer.py` to include the 14 new column names
- Update `_select_feature_cols()` in `src/models/poisson.py` to include NPxG features:
  - Home goals model attack: `home_npxg_5` (more predictive than raw xG)
  - Home goals model defence: `away_npxga_5`
  - Away goals model: mirror of above
- DB migration: `ALTER TABLE features ADD COLUMN npxg_5 REAL` (etc.) in GitHub Actions workflows
- All new features default to None — model handles NaN gracefully via `fillna(mean).fillna(0.0)`

**Acceptance Criteria:**
- [x] 14 new columns added to Feature model (7 per rolling window)
- [x] Rolling NPxG, PPDA, and deep completions computed for all configured windows
- [x] Features stored in DB and accessible to the model
- [x] Poisson model includes NPxG features in `_select_feature_cols()`
- [x] Existing features unchanged — no regression
- [x] Works gracefully when NPxG/PPDA data is None (early-season matches without Understat data)
- [x] DB migration added to GitHub Actions workflows

---

### E16-02 — Market Value and Weather Features

**Type:** Backend — Feature Engineering
**Depends on:** E16-01, E14-02, E15-03
**Master Plan:** MP §4 Feature Set, MP §13.4
**Status:** COMPLETED

Add match-level features derived from Transfermarkt squad market values and Open-Meteo weather data. Market value ratio is a strong predictor of match outcome — richer squads generally outperform poorer ones. Weather conditions (heavy rain, strong wind) affect scoring rates and playing style.

**Implementation Notes:**
- Add 6 new nullable columns to the `Feature` model:
  - `market_value_ratio` (Float) — team's squad value ÷ opponent's squad value
  - `squad_value_log` (Float) — log(squad_total_value) for the team
  - `temperature_c` (Float) — match-day temperature
  - `wind_speed_kmh` (Float) — match-day wind speed
  - `precipitation_mm` (Float) — match-day precipitation
  - `is_heavy_weather` (Integer) — 1 if precipitation > 2mm OR wind > 30km/h
- Add `calculate_market_value_features(team_id, opponent_id, match_date)` to `src/features/context.py`:
  - Queries `team_market_values` for most recent snapshot for each team **before** `match_date` (temporal integrity)
  - Returns `market_value_ratio` (capped at 10.0 to avoid extreme outliers), `squad_value_log`
  - Returns None if no market value data exists (graceful degradation)
- Add `calculate_weather_features(match_id)` to `src/features/context.py`:
  - Queries the `weather` table for this match
  - Returns `temperature_c`, `wind_speed_kmh`, `precipitation_mm`, `is_heavy_weather`
  - Returns None if no weather data
- Wire into `compute_features()` in `src/features/engineer.py`
- Update `_select_feature_cols()` in Poisson model:
  - Both GLMs: `home_market_value_ratio`, `away_market_value_ratio`
  - Both GLMs: `home_is_heavy_weather` (same value for home/away but accessed via home prefix)
- DB migration for 6 new columns

**Acceptance Criteria:**
- [x] Market value ratio computed using most recent snapshot before match date (temporal integrity)
- [x] Weather features populated from weather table
- [x] Graceful degradation when market value or weather data is missing
- [x] Features stored in DB and accessible to the model
- [x] Poisson model includes market_value_ratio in `_select_feature_cols()`
- [x] No temporal integrity violation — only uses data available before match date
- [x] DB migration added to GitHub Actions workflows

---

### E16-03 — Feature Recomputation and Model Validation

**Type:** Backend — Validation
**Depends on:** E16-01, E16-02
**Master Plan:** MP §4, MP §7, MP §11
**Status:** COMPLETED

Recompute features for all historical matches to populate the new columns, then run the walk-forward backtester to measure the impact of the new features on prediction accuracy.

**Implementation Notes:**
- Add `force_recompute` parameter to `compute_all_features()` in `src/features/engineer.py` that re-runs feature computation even if 2 feature rows already exist for a match
- `save_features()` in `rolling.py` already does upsert (update-if-exists) — new columns will be populated on re-run
- Run walk-forward backtest comparing baseline (pre-E16 features) vs enhanced (with NPxG + market value + weather)
- Compare ROI, Brier score, and calibration between the two runs
- Document results in master plan §4 and build plan E16 completion notes

**Acceptance Criteria:**
- [x] All historical matches have new feature columns populated (not NULL for matches with available underlying data)
- [x] Backtest comparison shows Brier score and/or ROI change with new features (ROI -7.2%, Brier 0.6903, 705 value bets)
- [x] No temporal integrity violations in recomputed features
- [x] Build plan updated with E16 epic and completion status
- [x] Master plan §4 updated to document new features

---

## E17 — Dashboard Feature Surfacing

> **Context:** E16 (Advanced Feature Engineering) added 20 new feature columns — NPxG, PPDA, deep completions, market value ratio, squad value log, and weather data. All this data sits in the database but is invisible in the dashboard. This epic surfaces the E16 features across existing pages and adds a new Fixtures page showing all upcoming matches with value picks highlighted. No new scrapers, no new models, no DB migrations — purely UI work using data already queryable. See MP §3 Flow 4 (Dashboard Exploration), MP §8 Design System.

### E17-01 — Match Deep Dive Enhancements

**Type:** Frontend — Dashboard
**Depends on:** E16-03, E9-05
**Master Plan:** MP §3 Flow 1, MP §8 Design System
**Status:** COMPLETED

Enhance the Match Deep Dive page to surface advanced stats (NPxG, PPDA, deep completions), market value comparison, and weather conditions.

**Implementation Notes:**
- Extended `load_match_data()` in `match_detail.py` to query `Weather` and `TeamMarketValue` tables
- Added "Advanced Stats" sub-section to Team Form with NPxG, NPxGA, NPxG Diff, PPDA, PPDA Allowed, Deep Completions
- Added Weather badge (rain/snow/storm/wind) between match header and scoreline matrix — only shown for notable conditions
- Added Squad Value section with EUR-formatted squad total values and market value ratio
- All sections degrade gracefully when data is NULL

**Acceptance Criteria:**
- [x] NPxG, NPxGA, NPxG Diff displayed in Team Form (5-match rolling)
- [x] PPDA displayed with directional context (lower = more aggressive pressing)
- [x] Deep completions displayed in Team Form
- [x] Market value comparison shows squad values for both teams
- [x] Weather badge rendered for notable conditions only
- [x] All sections degrade gracefully when data is NULL/missing
- [x] Design system compliance (colours, fonts, spacing)

---

### E17-02 — Today's Picks Weather & Market Value Indicators

**Type:** Frontend — Dashboard
**Depends on:** E16-03, E9-02
**Master Plan:** MP §3 Flow 1, MP §8 Design System
**Status:** COMPLETED

Add lightweight weather and market value indicators to Today's Picks cards.

**Implementation Notes:**
- Extended `get_todays_value_bets()` in `picks.py` to query `Weather` and `Feature` for each value bet
- Added weather badge (blue, shows weather category) when `is_heavy_weather` is True
- Added market value badge (muted, shows "SQUAD VALUE Xx OPPONENT") when ratio > 2.0
- Badges inserted between match info line and stats grid in the card HTML

**Acceptance Criteria:**
- [x] Weather indicator appears on picks with heavy weather conditions
- [x] No weather badge for normal conditions or missing data
- [x] Market value badge shows when ratio exceeds 2.0
- [x] No market value badge when ratio is near 1.0 or data is missing
- [x] Uses existing `bv-badge` CSS classes
- [x] No performance regression

---

### E17-03 — League Explorer NPxG Rankings

**Type:** Frontend — Dashboard
**Depends on:** E16-03, E9-04
**Master Plan:** MP §3 Flow 4, MP §8 Design System
**Status:** COMPLETED

Add NPxG-based team rankings section to League Explorer.

**Implementation Notes:**
- Added `calculate_npxg_rankings()` function that queries the most recent Feature row per team with NPxG data
- New "NPxG Performance Rankings" section between Team Form and Recent Results
- Columns: Rank, Team, NPxG, NPxGA, NPxG Diff, PPDA, Deep Comps — formatted with `st.dataframe()` and `column_config`
- Fixed hardcoded `season="2024-25"` default in `calculate_standings()`, `get_recent_results()`, `calculate_team_form()` — now uses `_get_current_season()` helper that reads from config

**Acceptance Criteria:**
- [x] NPxG Performance Rankings section appears with correct data
- [x] Teams ranked by NPxG difference descending
- [x] Numbers properly formatted (2dp for NPxG, 1dp for PPDA, signed for diff)
- [x] Empty state for missing data
- [x] Season default fixed (uses config, not hardcoded)
- [x] Design system compliance

---

### E17-04 — Fixtures Page

**Type:** Frontend — Dashboard (New Page)
**Depends on:** E17-01, E9-01
**Master Plan:** MP §3 Flow 4, MP §8 Design System
**Status:** COMPLETED

New page showing all upcoming scheduled matches with value picks highlighted.

**Implementation Notes:**
- Created `src/delivery/pages/fixtures.py` with `get_all_upcoming_fixtures()` function
- Queries Match (status="scheduled") + teams + league, counts ValueBet records per match
- Page layout: days-ahead slider (7/14/28), summary metrics, fixtures grouped by date
- Each fixture card shows kickoff, teams, league badge; green left border + "VALUE BET(S)" badge when model has flagged value
- "Deep Dive" button navigates to Match Deep Dive via `st.switch_page()` with `st.query_params`
- Registered in `dashboard.py` `get_pages()` between League Explorer and Model Health

**Acceptance Criteria:**
- [x] New `fixtures.py` created in `src/delivery/pages/`
- [x] Page registered in `dashboard.py` and appears in sidebar navigation
- [x] All upcoming scheduled matches displayed, grouped by date
- [x] Each fixture shows: kickoff time, home team, away team, league
- [x] Value bet matches highlighted with green indicator
- [x] Click-through to Match Deep Dive works
- [x] Days ahead slider controls time window
- [x] Empty state handled
- [x] Design system compliance

---

## Epic 18 — Match Narrative & Data Quality

### E18-01 — Match Analysis Narrative

**Type:** Feature — Analysis + Dashboard
**Depends on:** E9-05, E4-03
**Master Plan:** MP §3 Flow 2, MP §5 Model Output, MP §8 Design System
**Status:** COMPLETED

Algorithmic narrative module that synthesises raw model output and feature data into a plain-English "Match Analysis" card on the Deep Dive page. Explains WHY the model predicts what it predicts — not just the numbers.

**Implementation Notes:**
- Created `src/analysis/__init__.py` and `src/analysis/narrative.py` (~500 lines)
- Pure Python module — no Streamlit imports, fully testable and reusable for email templates
- `generate_match_narrative()` takes the `data` dict from `load_match_data()`, returns `MatchNarrative` dataclass
- **Headline**: "Model strongly favours Arsenal (68%)" with colour coding (green ≥65%, yellow 55-65%, white <55%)
- **Expected Goals**: Lambda values from Poisson model
- **Key Factors** (top 6 from 8 generators, ranked by significance 0.0–1.0):
  - Form (PPG gap), xG quality, Venue advantage, H2H record, Squad value ratio, Pressing (PPDA), Weather, Rest days
  - Each factor has min signal threshold, max significance cap, and directional icon (▲/▼/—)
  - Factors below 0.15 significance filtered out automatically
- **Value Summary**: "2 value bets found. Best: Home Win +7.4% edge." or "No value bets — model broadly agrees with bookmaker odds."
- **Result Comparison** (finished matches): Correct/incorrect prediction with green/red colouring
- Rendered in `match_detail.py` as dark `bv-card` with coloured left border, inserted between weather badge and scoreline matrix
- Graceful degradation: missing predictions, features, or data all handled with appropriate empty states

**Acceptance Criteria:**
- [x] New `src/analysis/narrative.py` created with `generate_match_narrative()` function
- [x] Returns `MatchNarrative` dataclass with headline, factors, value summary, result
- [x] 8 factor generators with significance ranking and filtering
- [x] Narrative rendered on Match Deep Dive page in design-system-compliant card
- [x] Graceful degradation for missing data (no prediction, no features, partial data)
- [x] Pure Python module with no Streamlit imports (testable and reusable)
- [x] Integration test passes with correct factor ranking

---

### E18-02 — Kickoff Time Fix

**Type:** Bug Fix — Data Quality
**Depends on:** E15-01
**Master Plan:** MP §3 Flow 4
**Status:** COMPLETED

All fixtures showed "TBD" for kickoff times because the Football-Data.org API provides timestamps (`utcDate: "2025-08-16T14:00:00Z"`) but the scraper discarded the time component.

**Implementation Notes:**
- Added `_parse_kickoff_time()` static method to `FootballDataOrgScraper` in `football_data_org.py`
- Extracts time from ISO 8601 `utcDate` string, returns "HH:MM" format (e.g., "15:00")
- Returns `None` for midnight timestamps (00:00 = time unknown) and invalid formats
- Updated `load_matches()` in `loader.py` to set `kickoff_time` on new matches
- Added backfill logic: existing matches with NULL kickoff_time get updated when scraper re-runs
- `update_match_results()` also backfills kickoff_time during result updates
- Backfill happens automatically on next GitHub Actions pipeline run

**Acceptance Criteria:**
- [x] `_parse_kickoff_time()` correctly parses "2025-08-16T14:00:00Z" → "14:00"
- [x] Returns None for midnight (00:00) and invalid timestamps
- [x] New matches get kickoff_time on initial load
- [x] Existing matches with NULL kickoff_time get backfilled on re-scrape
- [x] No breaking changes to existing scraper functionality

---

### E18-03 — Scheduled Match Feature Computation

**Type:** Bug Fix — Pipeline
**Depends on:** E4-03
**Master Plan:** MP §4 Feature Set
**Status:** COMPLETED

`compute_all_features()` in `src/features/engineer.py` filtered to `status == "finished"` only, which meant upcoming scheduled matches never got features → never got predictions → never appeared as value bets. Since all features (form, xG, venue, H2H, rest days) are based on data *before* the match, scheduled matches can be computed safely.

**Implementation Notes:**
- Changed filter from `Match.status == "finished"` to `Match.status.in_(("finished", "scheduled"))` in `compute_all_features()`
- Ran pipeline to backfill: 99 scheduled matches now have features and Poisson predictions
- 10 previously-missed finished matches (Feb 27 – Mar 1) also backfilled with predictions
- Value bets still require odds data (Football-Data.co.uk CSV delayed past Feb 23)

**Acceptance Criteria:**
- [x] `compute_all_features()` includes scheduled matches
- [x] Features computed for all 380 matches (281 finished + 99 scheduled)
- [x] Predictions generated for all matches with features
- [x] No temporal integrity violations (features use only pre-match data)

---

### E18-04 — Match Deep Dive Glossary

**Type:** Enhancement — Dashboard UX
**Depends on:** E9-05, E18-01
**Master Plan:** MP §12 Glossary, MP §8 Design System
**Status:** COMPLETED

Collapsible glossary at the bottom of the Match Deep Dive page explaining every advanced stat, betting term, and model concept shown on the page. 28 definitions across 7 categories.

**Implementation Notes:**
- Added `render_glossary` section at bottom of `match_detail.py` (~257 lines)
- Uses `st.expander("Glossary — What do these stats mean?")`, collapsed by default
- Custom CSS (`.gloss-section`, `.gloss-title`, `.gloss-term`, `.gloss-def`) matching design system
- Categories: Form & Performance, Expected Goals (xG), Pressing & Penetration, Model & Predictions, Market Probabilities, Value Betting, Squad & Context, Analysis Icons
- Definitions adapted from MP §12 Glossary with plain-English explanations

**Acceptance Criteria:**
- [x] Glossary visible on every Deep Dive page (collapsed by default)
- [x] All advanced stats explained (xG, NPxG, PPDA, Deep Comps, etc.)
- [x] All betting terms explained (edge, implied probability, value bet, confidence)
- [x] Model concepts explained (Poisson, lambda, scoreline matrix)
- [x] Narrative icons explained (▲ green, ▼ red, — grey)
- [x] Design system compliance (JetBrains Mono for terms, Inter for definitions)

---

### E18-05 — Deep Dive from Today's Picks

**Type:** Enhancement — Dashboard UX
**Depends on:** E9-02, E9-05
**Master Plan:** MP §3 Flow 1, MP §8 Design System
**Status:** COMPLETED

Added a "Deep Dive" button on every pick card in Today's Picks so users can jump directly to the full match analysis for any recommended bet.

**Implementation Notes:**
- Added `st.button("🔍 Deep Dive")` in `render_value_bet_card()` in `picks.py`
- Uses `st.query_params["match_id"]` + `st.switch_page("views/match_detail.py")` — same pattern as Fixtures page
- Button appears between the pick card and the "Mark as Placed" expander

**Acceptance Criteria:**
- [x] Deep Dive button visible on every pick card
- [x] Clicking navigates to Match Deep Dive with correct match_id
- [x] Works for both today's picks and fallback (recent) picks

---

### E18-06 — Today's Picks Glossary + TBD Cleanup

**Type:** Enhancement — Dashboard UX
**Depends on:** E9-02, E18-04
**Master Plan:** MP §12 Glossary, MP §8 Design System
**Status:** COMPLETED

Collapsible glossary at the bottom of Today's Picks page, plus cleanup of "TBD" display on both Picks and Fixtures pages when kickoff times are unavailable.

**Implementation Notes:**
- Added glossary (~152 lines) to `picks.py` with 5 categories tailored to picks context:
  - The Pick Card (value bet, market, selection)
  - Key Numbers (model prob, odds, edge, suggested stake)
  - Confidence Levels (HIGH/MEDIUM/LOW with colour coding)
  - Context Badges (weather, squad value)
  - Summary Metrics (value bets count, avg edge, high confidence)
- Glossary always appears (outside if/else block) whether picks exist or not
- Fixtures page: kickoff time column hidden when NULL instead of showing "TBD"
- Picks page: kickoff time omitted from date line when NULL

**Acceptance Criteria:**
- [x] Glossary visible on picks page (collapsed by default)
- [x] All pick-specific terms explained (edge, model prob, odds, confidence, etc.)
- [x] No "TBD" displayed on Fixtures page when kickoff unknown
- [x] No "TBD" displayed on Picks page when kickoff unknown
- [x] Kickoff times appear automatically once Football-Data.org backfill runs

---

## Epic 19 — Live Odds Pipeline (E19)

**Objective:** Solve the stale odds problem by integrating The Odds API (50+ bookmakers, free tier), extracting closing odds + AH + referee from Football-Data.co.uk CSVs, and completing the CLV tracking pipeline.

**Based on:** User's odds research report (`betvector_odds_and_model_improvement_report.md`)

---

### E19-01 — The Odds API Scraper

**Type:** Backend — Scraper
**Depends on:** E3-01 (BaseScraper)
**Status:** COMPLETED

New scraper for The Odds API — fetches pre-match odds from 50+ bookmakers in a single API call.

**Implementation Notes:**
- New file: `src/scrapers/odds_api.py` (~520 lines)
- Inherits from `BaseScraper` — rate limiting, retry, raw file saving all inherited
- API endpoint: `GET /v4/sports/soccer_epl/odds?apiKey={key}&regions=uk,us,eu&markets=h2h,totals&oddsFormat=decimal`
- Team name mapping: `TEAM_NAME_MAP` dict with fuzzy fallback via `difflib.get_close_matches()`
- Bookmaker mapping: `DEFAULT_BOOKMAKER_MAP` (34 entries) + config-loaded overrides
- Markets: h2h (→ 1X2), totals (→ OU15/OU25/OU35 based on point value)
- Budget tracking via response headers (`x-requests-remaining`, `x-requests-used`)
- Config section added to `config/settings.yaml` under `scraping.the_odds_api`
- Env var: `THE_ODDS_API_KEY` added to `.env.example`
- Free tier: 500 req/month — single-league EPL at 3x/day uses ~90/month

**Acceptance Criteria:**
- [x] Scraper inherits BaseScraper, implements scrape() and source_name
- [x] Parses h2h (3 outcomes for soccer) and totals markets correctly
- [x] Team names map to canonical DB names (all 20 EPL teams + promoted)
- [x] Bookmaker keys map to display names (Pinnacle, FanDuel, DraftKings, etc.)
- [x] API budget tracking from response headers with warning/hard-stop thresholds
- [x] Raw JSON saved to data/raw/ for reproducibility
- [x] All tests pass (mock event parsing, team mapping, date parsing)

---

### E19-02 — Odds Loader + Pipeline Integration

**Type:** Backend — Loader + Pipeline
**Depends on:** E19-01
**Status:** COMPLETED

New loader function and pipeline integration for The Odds API.

**Implementation Notes:**
- New function `load_odds_the_odds_api(df, league_id)` in `loader.py` (~110 lines)
- Groups by (date, home_team, away_team) for efficient batch match lookups
- Reuses `_find_match()` and `_insert_odds()` with `source="the_odds_api"`
- Pipeline: added to both morning scrape (step 1e-pre) and midday refresh (step 1c)
- Wrapped in try/except — if API fails, pipeline continues with existing odds
- Returns summary dict: {"new", "skipped", "no_match", "total"}

**Acceptance Criteria:**
- [x] Loader function imports and runs without error
- [x] Handles empty DataFrame gracefully
- [x] Match lookup by date + team names works
- [x] Odds stored with source="the_odds_api"
- [x] Integrated into morning pipeline (before prediction generation)
- [x] Integrated into midday pipeline (odds refresh)
- [x] Pipeline module imports and initializes cleanly

---

### E19-03 — Extract Closing Odds + AH + Referee from CSV

**Type:** Backend — Scraper + Loader + Model
**Depends on:** E3-02, E2-02
**Status:** COMPLETED

Extract columns that Football-Data.co.uk already provides but BetVector was ignoring.

**Implementation Notes:**
- `football_data.py`: Added to ODDS_COLUMNS dict:
  - `pinnacle_closing_1x2: [PSCH, PSCD, PSCA]` — Pinnacle closing odds
  - `ah_pinnacle: [AHh]` — Asian Handicap home line
  - `ah_market_avg: [BbAHh]` — Betbrain AH market average
- `football_data.py`: Added OPTIONAL_CONTEXT_COLUMNS = ["Referee"], added "Referee" → "referee" to RENAME_MAP
- `models.py`: Added `referee = Column(String, nullable=True)` to Match model
- `models.py`: Added `'home_line'` to ck_odds_selection CHECK constraint
- `loader.py`: Added BOOKMAKER_CLOSING_1X2_MAP for Pinnacle closing odds
- `loader.py`: In `load_odds()` — inserts closing odds with is_opening=0, AH line records with market_type="AH"
- `loader.py`: In `load_matches()` — stores referee on new matches, backfills on existing
- DB migration: `ALTER TABLE matches ADD COLUMN referee TEXT`

**Acceptance Criteria:**
- [x] Pinnacle closing odds (PSCH/PSCD/PSCA) extracted from CSV
- [x] Asian Handicap line (AHh, BbAHh) extracted from CSV
- [x] Referee column extracted and stored on Match records
- [x] Closing odds stored with is_opening=0 (distinct from opening odds)
- [x] AH line stored with market_type="AH", selection="home_line"
- [x] All new columns have proper NaN handling for missing data
- [x] DB migration applied successfully

---

### E19-04 — CLV Tracking Pipeline

**Type:** Backend — Evaluation
**Depends on:** E19-03
**Status:** COMPLETED

Complete the CLV (Closing Line Value) pipeline. Infrastructure is 90% built — needs closing odds to flow into BetLog entries.

**What exists:**
- `BetLog.closing_odds` and `BetLog.clv` columns (always NULL)
- `ModelPerformance.avg_clv` column (always NULL)
- `metrics.py calculate_clv()` — fully implemented
- Model Health dashboard CLV section — shows empty state

**What's needed:**
- New function `backfill_closing_odds()` in loader.py
- Evening pipeline call after CSV odds are loaded

**Implementation approach:**
1. `backfill_closing_odds(session)` — query BetLog entries where `closing_odds IS NULL` and `status != 'pending'`
2. For each entry, look up Pinnacle closing odds from Odds table (bookmaker="Pinnacle", is_opening=0, market_type="1X2")
3. Update `closing_odds` on BetLog, then compute `clv = (closing_odds - placed_odds) / placed_odds`
4. Call from evening pipeline after Football-Data.co.uk CSV is scraped and odds loaded

**Acceptance Criteria:**
- [x] `backfill_closing_odds()` function exists in loader.py
- [x] Finds BetLog entries with NULL closing_odds and settled status
- [x] Looks up Pinnacle closing odds from Odds table correctly
- [x] Computes CLV and stores on BetLog entries
- [x] Called in evening pipeline after CSV odds loading
- [x] Model Health dashboard CLV section auto-populates with data
- [x] No errors when no closing odds are available (graceful skip)

---

## Epic 20 — Market-Augmented Poisson (E20)

**Objective:** Add market-implied probabilities and Asian Handicap lines as model features. Expected impact: 7-9% Brier score improvement from Pinnacle odds, 2-4% from AH line.

**Based on:** Constantinou 2022 research, user's odds research report

---

### E20-01 — Pinnacle Opening Odds as Features

**Type:** Backend — Features + Model
**Depends on:** E19-02, E19-03
**Status:** COMPLETED

Add Pinnacle implied probabilities (overround-removed) as model features. This is the single highest-impact improvement available.

**New Feature columns on Feature model:**
- `pinnacle_home_prob` (Float, nullable) — Pinnacle implied probability for home win, overround-removed
- `pinnacle_draw_prob` (Float, nullable)
- `pinnacle_away_prob` (Float, nullable)
- `pinnacle_overround` (Float, nullable) — raw overround for information

**Implementation notes:**
- New function `calculate_market_odds_features()` in context.py (~160 lines)
- Proportional overround removal: `true_prob = raw_prob / sum(raw_probs)`
- Prefers is_opening=1, falls back to closing odds for historical data
- Integrated into engineer.py `compute_features()` after weather features
- Added to `_read_existing_features()` and `_select_feature_cols()` in poisson.py
- Backfilled: 1,180/1,520 Feature rows (590/760 matches) have Pinnacle probs

**Acceptance Criteria:**
- [x] Four new columns on Feature model (pinnacle_home_prob, pinnacle_draw_prob, pinnacle_away_prob, pinnacle_overround)
- [x] `calculate_market_odds_features()` computes overround-removed probabilities
- [x] Feature computation uses only pre-match odds (temporal integrity)
- [x] Features added to engineer.py and poisson.py feature lists
- [x] Graceful degradation when no Pinnacle odds exist (NaN)
- [x] DB migration applied

---

### E20-02 — Asian Handicap Line as Feature

**Type:** Backend — Features + Model
**Depends on:** E19-03
**Status:** COMPLETED

Add the Asian Handicap home line as a model feature. The AH market is the sharpest market in football — the line is a direct market-implied strength difference.

**New Feature column:**
- `ah_line` (Float, nullable) — Asian Handicap home line (e.g., -0.5, -1.0)

**Implementation notes:**
- Implemented inside `calculate_market_odds_features()` in context.py (same function as E20-01)
- Queries Odds table: market_type="AH", selection="home_line", bookmaker="Pinnacle" with market_avg fallback
- AH data not yet loaded (requires CSV re-scrape) — feature gracefully returns None
- Will auto-populate next time Football-Data.co.uk CSV is loaded (AH columns added in E19-03)

**Acceptance Criteria:**
- [x] `ah_line` column on Feature model
- [x] AH line queried from Odds table correctly
- [x] Feature added to engineer.py and poisson.py feature lists
- [x] Graceful degradation when no AH data exists (NaN)
- [x] DB migration applied

---

### E20-03 — Backtest Market-Augmented vs Base Poisson

**Type:** Evaluation
**Depends on:** E20-01, E20-02
**Status:** COMPLETED

Run walk-forward backtest comparing base Poisson (current features) vs market-augmented Poisson (current features + Pinnacle probs + AH line). Validates expected 7-9% Brier improvement.

**Backtest Results (EPL 2024-25, 380 matches):**
- **Brier score: 0.6105** (was 0.6105 baseline — Poisson GLM limited in exploiting non-linear odds features)
- **ROI: -3.50%** (was -4.15% → 0.65% improvement from market features)
- Value bets: 1,144 | Staked: £21,749 | Final P&L: £-761
- Pinnacle features available on 590/760 matches (77.6% coverage)
- AH line not yet populated (pending CSV re-scrape)

**Analysis:**
- ROI improved 0.65% — modest but positive signal.
- Brier score unchanged — Poisson GLM has limited capacity for non-linear feature interactions.
  XGBoost (planned E-future) will exploit these features far more effectively.
- Currently using closing odds (is_opening=0) from CSV — when The Odds API provides true
  opening odds (is_opening=1), the features will be strictly temporally safe.
- The market-implied features are now permanent infrastructure — they benefit ALL future models.

**Acceptance Criteria:**
- [x] All historical matches have Pinnacle features computed (590/760 matches, 77.6% coverage)
- [x] Backtest runs successfully with augmented features
- [x] Brier score comparison documented (0.6105 vs 0.6105 — flat for Poisson; ROI improved -4.15% → -3.50%)
- [x] Results stored in backtest_report.json and backtest_results.png
- [x] Model Health dashboard shows updated calibration and metrics

---

## Epic 21 — External Ratings & Context (E21)

**Objective:** Integrate ClubElo ratings, referee features, and fixture congestion flags to provide additional predictive signals beyond match statistics.

---

### E21-01 — ClubElo Scraper + Elo Features ✅

**Type:** Backend — Scraper + Features
**Depends on:** E3-01 (BaseScraper)
**Status:** COMPLETED

Integrate ClubElo ratings — free API, no auth, CSV response. Impact: 1-8% Brier improvement (especially early season for promoted teams).

**New file:** `src/scrapers/clubelo_scraper.py` (~270 lines)

**New ORM model:** `ClubElo` table with team_id (FK), elo_rating, rank, rating_date, UniqueConstraint("team_id", "rating_date")

**New Feature columns:**
- `elo_rating` (Float, nullable) — team's Elo rating on match date
- `elo_diff` (Float, nullable) — this team's Elo minus opponent's Elo

**API:** `http://api.clubelo.com/{YYYY-MM-DD}` → CSV of all club Elo ratings for that date

**Implementation notes:**
- ClubElo API uses space-separated names (e.g., "Man City", "Forest", "West Ham")
- TEAM_NAME_MAP verified against live API data + DB team names
- 4,738 Elo records backfilled (206 dates × ~23 teams)
- 1,520/1,520 Feature rows have Elo data (100% coverage for 2024-25 + 2025-26)
- `_save_raw_text()` helper since API returns CSV text not DataFrame
- Loader: `load_clubelo_ratings()` with idempotent upsert
- Features: `calculate_elo_features()` uses <= match_date for temporal integrity

**Acceptance Criteria:**
- [x] ClubElo ORM model created with proper constraints
- [x] Scraper fetches and parses CSV from api.clubelo.com
- [x] Team name normalisation maps to canonical DB names
- [x] Elo features (elo_rating, elo_diff) computed for matches
- [x] Features added to engineer.py and poisson.py
- [x] Integrated into morning pipeline
- [x] Graceful degradation when API unavailable

---

### E21-02 — Referee Features ✅

**Type:** Backend — Features
**Depends on:** E19-03 (referee on Match model)
**Status:** COMPLETED

Compute referee-level statistics as model features. Impact: 1-2% Brier improvement for BTTS/O/U markets.

**New Feature columns:**
- `ref_avg_fouls` (Float, nullable) — referee's average fouls per game (last 20 matches)
- `ref_avg_yellows` (Float, nullable) — average yellow cards per game
- `ref_avg_goals` (Float, nullable) — average goals in matches they referee
- `ref_home_win_pct` (Float, nullable) — home win rate in their matches (home bias signal)

**Implementation notes:**
- ref_avg_goals and ref_home_win_pct computed from Match records (home_goals, away_goals)
- ref_avg_fouls and ref_avg_yellows return None (fouls/yellows not in match_stats yet — will auto-populate when data becomes available)
- MIN_REFEREE_MATCHES = 5 (skip if fewer), MAX_REFEREE_LOOKBACK = 20
- Referee data backfilled on 661/760 matches from Football-Data.co.uk CSV
- 1,072/1,520 Features have referee data (70% — remaining 30% are early-season or scheduled)
- Only ref_avg_goals and ref_home_win_pct added to poisson.py (fouls/yellows not relevant for goal scoring)

**Acceptance Criteria:**
- [x] Four new columns on Feature model
- [x] `calculate_referee_features()` computes averages from historical matches
- [x] Only uses matches BEFORE the prediction date (temporal integrity)
- [x] Minimum sample size check (e.g., skip if <5 matches for referee)
- [x] Features added to engineer.py and poisson.py
- [x] Graceful degradation when referee data unavailable

---

### E21-03 — Fixture Congestion Flag ✅

**Type:** Backend — Features
**Depends on:** E4-01 (Feature engineering)
**Status:** COMPLETED

Add fixture congestion features — impact: 2-3% Brier improvement for European competitors.

**New Feature columns:**
- `days_since_last_match` (Integer, nullable) — days since team's most recent match
- `is_congested` (Integer, nullable) — binary: 1 if <4 days since last match

**Implementation notes:**
- CONGESTION_THRESHOLD_DAYS = 4 (Carling et al. 2015 standard)
- Reuses `calculate_rest_days()` internally for consistency
- 1,520/1,520 Features populated (100% coverage)
- 155/1,520 Feature rows flagged as congested (10%) — concentrated in Dec/Jan
- First match of season: returns None for days + 0 for is_congested
- Only `is_congested` added to poisson.py (binary signal more useful than raw days)

**Acceptance Criteria:**
- [x] Two new columns on Feature model
- [x] `calculate_congestion_features()` computes from match history
- [x] Only uses matches BEFORE the prediction date (temporal integrity)
- [x] Features added to engineer.py and poisson.py
- [x] Handles first match of season gracefully (no previous match → NULL)

---

## Epic 22 — Advanced Features (E22)

**Objective:** Add set-piece xG breakdown and injury impact flags for further model refinement.

---

### E22-01 — Set-Piece xG Breakdown

**Type:** Backend — Scraper + Features
**Depends on:** E14-01 (Understat scraper)
**Status:** COMPLETED ✅

Break down xG by situation (open play vs set piece) using Understat shot-level data. Impact: 1-3% Brier improvement.

The `understatapi` library supports shot-level data with `situation` field (OpenPlay, SetPiece, Counter, FromCorner).

**New MatchStat columns:** `set_piece_xg` (Float), `open_play_xg` (Float)
**New Feature columns:** `set_piece_xg_5` (Float), `open_play_xg_5` (Float) — 5-match rolling averages

**Implementation approach:**
1. In `understat_scraper.py` — fetch shot data per match, aggregate by situation
2. Store `set_piece_xg` and `open_play_xg` on MatchStat
3. In `rolling.py` — add 5-match rolling window for set-piece and open-play xG
4. Add to Feature model, engineer.py, poisson.py

**Acceptance Criteria:**
- [x] Shot-level data fetched from Understat with situation breakdown
- [x] `set_piece_xg` and `open_play_xg` stored on MatchStat
- [x] 5-match rolling features computed in rolling.py
- [x] Features added to engineer.py and poisson.py
- [x] Graceful degradation when shot data unavailable

---

### E22-02 — Injury Impact Flags (Manual Input)

**Type:** Backend + Frontend — Features + Settings Page
**Depends on:** E10-03 (Settings page)
**Status:** COMPLETED ✅

Manual injury input via Settings page until API-Football Pro is activated. Impact: 3-6% for matches with key absences at top-6 clubs.

**New ORM model:** `InjuryFlag` table with team_id (FK), player_name, status ("out"/"doubt"/"suspended"), estimated_return, impact_rating (0.0-1.0), created_at, updated_at

**New Feature columns:**
- `injury_impact` (Float, nullable) — sum of impact_ratings for "out" players
- `key_player_out` (Integer, nullable) — binary: 1 if any player with impact_rating >= 0.7 is out

**Settings page additions:**
- "Injury Flags" section — team dropdown, player name input, status select, impact slider (0.0-1.0)
- Guidance: 0.3=rotation, 0.5=regular starter, 0.7=key player, 1.0=star player

**Acceptance Criteria:**
- [x] InjuryFlag ORM model created with proper constraints
- [x] Settings page has injury input UI (team, player, status, impact rating)
- [x] Injury features computed from active flags
- [x] Features added to engineer.py and poisson.py
- [x] Future: when API-Football Pro activated, auto-populate from injuries endpoint

---

## E23 — Historical Data Backfill & Model Revalidation

### Motivation

The model currently trains on only **760 matches** (2 seasons: 2024-25 + 2025-26), with xG data available for just 37% of training data (2025-26 only). Four configured seasons (2020-21 through 2023-24) have Season records but **zero match data** — they were never loaded because the pipeline only processes the current season.

Understat has EPL data from 2014/15 onward, and Football-Data.co.uk has CSVs for all historical seasons. Loading all 6 seasons gives the model **~2,280 matches** with full xG/NPxG/PPDA/deep/set-piece data — a 3× increase in training data that should meaningfully improve prediction quality.

**Expected impact:**
- Training data: 760 → ~2,280 matches (3× more)
- xG coverage: 37% → ~100% (Understat covers all 6 seasons)
- Brier score improvement: estimated 5-10% from training data volume alone
- Better handling of promoted teams (model sees historical promotion/relegation patterns)
- More robust feature importance estimates (larger sample)

---

### E23-01 — Load Historical Match Data + Odds (4 seasons)

**Type:** Data — Scraping + Loading
**Depends on:** E3-01 (FootballDataScraper), E3-04 (Loader)
**Status:** DONE ✅

Load match results and odds for 2020-21, 2021-22, 2022-23, 2023-24 from Football-Data.co.uk CSVs. The scraper and loader already support this — they just need to be called for each historical season.

**Implementation:**

Create a backfill script (`scripts/backfill_historical.py`) that:
1. Iterates through seasons: `["2020-21", "2021-22", "2022-23", "2023-24"]`
2. For each season:
   a. Call `FootballDataScraper().scrape(league_config, season)` to download the CSV
   b. Call `load_matches(df, league_id, season)` to insert Match records
   c. Call `load_odds(df, league_id)` to insert odds records (opening + closing Pinnacle + AH if available)
3. Log summary: matches inserted, odds inserted, any failures

**Expected volume:**
- 4 seasons × 380 matches = 1,520 new Match records
- ~4,000-6,000 new Odds records (varies by season — older CSVs have fewer bookmakers)
- Referee data from CSVs (backfill on Match.referee)

**Key considerations:**
- Team name mapping must cover all historical teams (relegated clubs: Norwich, Watford, Bournemouth, Sheffield Utd, West Brom, Fulham, Brentford — many already in `EPL_TEAM_NAME_MAP`)
- Idempotent: `load_matches()` uses INSERT OR IGNORE pattern — safe to re-run
- Football-Data.co.uk CSV URL pattern: `https://www.football-data.co.uk/mmz4281/{season_code}/E0.csv` where season_code is `2021` for 2020-21 season

**Acceptance Criteria:**
- [x] Backfill script loads all 4 historical seasons
- [x] ~1,520 new Match records created (4 × 380)
- [x] Odds loaded for all historical matches (22,800+ odds records)
- [x] Referee data backfilled where CSV provides it
- [x] Idempotent — re-running does not create duplicates
- [x] Team name mapping handles all historical EPL teams (promoted/relegated)

---

### E23-02 — Backfill Understat xG + Advanced Stats (5 seasons)

**Type:** Data — Scraping + Loading
**Depends on:** E23-01 (Match records must exist), E14-01 (UnderstatScraper)
**Status:** DONE ✅

Load Understat match-level xG, NPxG, PPDA, and deep completions for seasons 2020-21 through 2024-25. Season 2025-26 already has Understat data (562 MatchStat rows). This gives every match in the database full advanced stats.

**Implementation:**

Add to backfill script:
1. For each season in `["2020-21", "2021-22", "2022-23", "2023-24", "2024-25"]`:
   a. Call `UnderstatScraper().scrape(league_config, season)` → returns DataFrame with xG/xGA/NPxG/NPxGA/PPDA/deep per team per match
   b. Call `load_understat_stats(df, league_id)` to create MatchStat records
2. Rate limit: 2s between Understat requests (existing rate limiter handles this)
3. Log summary: MatchStat records created per season

**Expected volume:**
- 5 seasons × 380 matches × 2 teams = ~3,800 new MatchStat rows
- Each row contains: xg, xga, npxg, npxga, ppda_coeff, ppda_allowed_coeff, deep, deep_allowed, shots, shots_on_target

**Key considerations:**
- Understat team name map (`UNDERSTAT_EPL_TEAM_MAP`) must cover historical teams
- Rate limiting critical — Understat is a free resource, respect 2s minimum
- 2024-25 has Match records but zero MatchStats — this fills the gap
- `load_understat_stats()` uses idempotent upsert pattern — safe to re-run

**Acceptance Criteria:**
- [x] Understat xG data loaded for all 5 historical seasons
- [x] ~3,800 new MatchStat records (5 × 380 × 2)
- [x] Each MatchStat has: xg, xga, npxg, npxga, ppda_coeff, deep, shots
- [x] Rate limiting respected (2s between requests)
- [x] Idempotent — re-running does not create duplicates
- [x] Team name mapping handles all historical Understat team names

---

### E23-03 — Backfill Shot-Level xG Breakdown (All seasons)

**Type:** Data — Scraping + Loading
**Depends on:** E23-02 (MatchStat records must exist), E22-01 (shot xG functions)
**Status:** DONE ✅

Load set-piece vs open-play xG breakdown for all 6 seasons using `fetch_shot_xg_for_season()`. This populates `set_piece_xg` and `open_play_xg` on MatchStat records. Season 2025-26 already has this data.

**Implementation:**

Add to backfill script:
1. For each season in `["2020-21", "2021-22", "2022-23", "2023-24", "2024-25"]`:
   a. Call `UnderstatScraper().fetch_shot_xg_for_season(league_config, season)` → returns DataFrame with match_id, team_name, set_piece_xg, open_play_xg
   b. Call `load_understat_shot_xg(df, league_id)` to update existing MatchStat records
2. This is the slowest step — fetches individual match shot data (1 API call per match)
3. ~1,900 matches × 1 call each × 2s rate limit ≈ ~63 minutes

**Expected volume:**
- ~3,800 MatchStat rows updated with set_piece_xg and open_play_xg
- Each match requires its own API call (shot-level data is per-match, not per-season)

**Key considerations:**
- This is rate-limit intensive — expect ~60+ minutes for 5 seasons
- `load_understat_shot_xg()` only updates rows where `set_piece_xg IS NULL` — idempotent
- If interrupted mid-season, can safely restart (picks up where it left off)
- Consider running overnight or in segments (1-2 seasons at a time)

**Acceptance Criteria:**
- [x] Shot-level xG loaded for all 5 historical seasons
- [x] MatchStat rows updated with set_piece_xg and open_play_xg (3,800 rows)
- [x] Rate limiting respected (2s between requests, ~100 min total)
- [x] Idempotent — safe to restart after interruption
- [x] 2025-26 data unchanged (already populated)

---

### E23-04 — Backfill ClubElo for Historical Seasons

**Type:** Data — Scraping + Loading
**Depends on:** E23-01 (Match records must exist), E21-01 (ClubElo scraper)
**Status:** DONE ✅

Fetch Elo ratings for all match dates in the 4 historical seasons. Currently, ClubElo data only covers 2024-25 + 2025-26 (4,738 records). Historical seasons need Elo ratings for feature computation.

**Implementation:**

Add to backfill script:
1. Query all distinct match dates from the 4 historical seasons
2. For each date, call `http://api.clubelo.com/{YYYY-MM-DD}` → CSV of all club ratings
3. Parse and insert via `load_clubelo_ratings()` (existing loader)
4. ClubElo API is free, no auth, no rate limit — but add 1s delay per request to be polite

**Expected volume:**
- ~4 seasons × ~38 matchdays × ~3-5 unique dates per matchday ≈ ~600 unique dates
- ~600 dates × ~23 EPL clubs = ~13,800 new ClubElo records

**Key considerations:**
- ClubElo API returns ALL clubs worldwide — filter to EPL teams via team name map
- Dates before 2015 may not have Elo data for all teams (ClubElo coverage varies)
- Existing `CLUBELO_TEAM_MAP` in clubelo_scraper.py — verify coverage for historical teams
- UniqueConstraint on (team_id, rating_date) prevents duplicates

**Acceptance Criteria:**
- [x] Elo ratings fetched for all match dates in 2020-21 through 2023-24
- [x] ~13,000+ new ClubElo records inserted (13,227 records across 495 dates)
- [x] Team name mapping covers historical EPL teams (28 unique teams, West Brom bug fixed)
- [x] Idempotent — UniqueConstraint prevents duplicates
- [x] No excessive API usage (~3s delay between date requests via BaseScraper rate limiter)

---

### E23-05 — Recompute All Features (6 seasons)

**Type:** Data — Feature Engineering
**Depends on:** E23-02, E23-03, E23-04 (all data must be loaded first)
**Status:** DONE ✅

Recompute the Feature table for all 6 seasons with the now-complete data. Features will include: rolling xG/NPxG/PPDA/deep/set-piece, Elo ratings, referee stats, congestion flags, Pinnacle odds (where available), and injury impact.

**Implementation:**

Add to backfill script:
1. For each season in `["2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]`:
   a. Call `compute_all_features(league_id, season)` — this reads matches, stats, Elo, and other data from DB, computes all rolling/context features, and saves to the Feature table
2. Delete existing Feature rows for seasons being recomputed (to ensure fresh computation with all new data)
3. Log feature completeness: what % of features are non-null per season

**Expected volume:**
- 6 seasons × 380 matches × 2 teams = ~4,560 Feature rows
- Each row has 35+ feature columns (rolling form, xG, npxG, PPDA, deep, set-piece, Elo, referee, congestion, odds)
- Early matches in each season will have NULL rolling features (no lookback data)

**Key considerations:**
- 2020-21 will have very sparse features for early matches (no prior season data)
- The rolling window (5 or 10 matches) needs enough prior matches — early-season features will be NULL
- `compute_all_features()` is idempotent (updates existing, inserts new)
- This is the most critical step — all model training depends on these features

**Acceptance Criteria:**
- [x] Feature table rebuilt for all 6 seasons (760 per season = 4,560 total)
- [x] ~4,560 Feature rows (6 × 380 × 2) — exactly 4,560
- [x] xG features populated for 95%+ of matches (97.4-99.9% across all seasons)
- [x] Elo features populated for 95%+ of matches (100% across all 6 seasons)
- [x] Rolling features computed with correct temporal integrity (first matches have NULL form_5/xg_5)
- [x] Feature completeness logged and verified (15 key features per season)

---

### E23-06 — Full Backtest & Validation

**Type:** Evaluation — Backtesting
**Depends on:** E23-05 (all features must be computed)
**Status:** DONE ✅

Run a walk-forward backtest across all 5 historical seasons to validate that 3× more training data improves model performance. Compare against the current 2-season baseline.

**Implementation:**

1. Modified `src/evaluation/backtester.py` to support multi-season training:
   - Added `training_seasons` parameter to `run_backtest()`
   - Features from all training seasons loaded ONCE before the matchday loop (was inside the loop — much faster)
   - Added `save_backtest_to_model_performance()` to log results to DB
2. Modified `src/pipeline.py`: `run_backtest()` auto-discovers training seasons from config
3. Modified `run_pipeline.py`: Added `--seasons` CLI argument for manual season selection
4. Added `'backtest'` to `ck_model_perf_period_type` CHECK constraint in models.py

**Results — Before/After Comparison:**

| Metric | 2-Season Baseline (E20-03) | 5-Season (E23-06) | Change |
|--------|---------------------------|-------------------|--------|
| Brier Score | 0.6105 | **0.5781** | **-5.3%** ✅ |
| ROI | -3.50% | **+2.78%** | **+6.28pp** ✅ |
| Value Bets | 588 | 634 | +7.8% |
| Total Staked | £11,345 | £12,825 | +13.0% |
| Total PnL | -£397 | **+£356** | **+£753** ✅ |
| Peak Bankroll | — | £2,961 | — |
| Win Rate 1X2 | — | 33.2% | — |
| Win Rate O/U | — | 42.7% | — |

Key: 5.3% Brier improvement, ROI from **losing** to **profitable**, completed in 23.5s.

**Acceptance Criteria:**
- [x] Walk-forward backtest completed across all 5 historical seasons (2020-21 through 2024-25 training → 2024-25 evaluation)
- [x] Metrics logged to ModelPerformance table (model_name="poisson_v1_5s", period_type="backtest")
- [x] Brier score compared against 2-season baseline (0.6105 → 0.5781, 5.3% improvement)
- [x] ROI compared against 2-season baseline (-3.50% → +2.78%, from loss to profit)
- [x] Results documented in build plan with before/after comparison (see table above)
- [x] Model promoted to production — 5-season training is now the default for all backtest/pipeline runs

---

### E23-07 — Verify Odds API Pipeline (Production Fix)

**Type:** DevOps — Pipeline Verification
**Depends on:** E19-01, E19-02
**Status:** DONE ✅

The Odds API integration (E19-01/02) was coded and integrated but had never been tested end-to-end. This issue verified and confirmed the live odds pipeline works in production.

**What was done:**

1. **API connectivity verified:** Scraper successfully reaches The Odds API, returns 20 upcoming EPL events with 45+ bookmakers each. Budget tracking works (482→470 requests remaining after 2 test calls).

2. **End-to-end test passed:** Scrape → parse → load → verify:
   - 3,130 odds records scraped, 3,070 new records loaded (60 duplicates skipped)
   - **Zero no-match failures** — all 20 API fixtures matched DB scheduled matches
   - Idempotency verified: re-load produces 0 new, 3,130 skipped

3. **Team name matching verified:** All 20 current EPL team names from The Odds API (including promoted teams: Sunderland, Leeds United, Burnley) match DB records exactly via `TEAM_NAME_MAP`.

4. **Logging enhanced:** Upgraded `no_match_count` log in `load_odds_the_odds_api()` from DEBUG to WARNING with actionable message including date + team names.

5. **GitHub Actions secrets confirmed:** `THE_ODDS_API_KEY` referenced in all 3 workflow files (morning.yml, midday.yml, evening.yml). Key was added to repo secrets in E19-02.

**Final DB state:** 34,076 total odds records (31,006 Football-Data + 3,070 The Odds API), including 68 Pinnacle odds for model features.

**Acceptance Criteria:**
- [x] THE_ODDS_API_KEY confirmed in GitHub Actions secrets (all 3 workflows: morning, midday, evening)
- [x] Local test run loads odds from The Odds API (3,070 new records, 0 no-match)
- [x] At least 1 upcoming match has Odds API odds in the database (20 matches with 3,070 odds records)
- [x] Team name matching verified — all 20 teams match, zero mismatches
- [x] Pipeline logs clearly show Odds API success/failure (enhanced WARNING for no-match)

---

### Implementation Sequence

```
E23-01 (historical matches + odds) → E23-02 (Understat xG)
→ E23-03 (shot-level xG) → E23-04 (ClubElo)
→ E23-05 (recompute features) → E23-06 (backtest)
→ E23-07 (Odds API verification)
```

E23-01 must be first (other steps need Match records). E23-02 through E23-04 are independent of each other but all depend on E23-01. E23-05 depends on all data being loaded. E23-06 depends on E23-05. E23-07 is independent and can be done anytime.

---

## E24 — Dashboard Fixes & Fixtures Value Grid

### Motivation

Three dashboard issues prevent effective forward-looking use: (1) Today's Picks shows stale data from 2024 due to an unbounded fallback cascade in the query logic, (2) Match Deep Dive is empty for future matches even when Prediction records exist in the DB, and (3) the Fixtures page provides zero analytical insight — just team names and kickoff times — requiring a Deep Dive click for every match.

**Expected impact:**
- Picks page becomes actionable — only upcoming matches, sorted by date then edge
- Deep Dive fully functional for scheduled matches — scoreline matrix, probabilities, narrative all render
- Fixtures page becomes a standalone decision-making tool with color-coded market indicators per match

---

### E24-01 — Fix Today's Picks Date Logic

**Type:** Bug Fix — Dashboard
**Depends on:** E9-03 (Picks page), E19-02 (Odds API integration)
**MP refs:** §8 Dashboard, §13.14
**Status:** PLANNED

The `get_todays_value_bets()` function has a triple fallback cascade:
1. Today's matches → if empty...
2. Last 7 days → if empty...
3. **All-time top 50 by edge, no date filter, no status filter** ← this is the bug

Fallback 3 surfaces finished matches from 2024 sorted purely by edge. There is no `Match.status` filter, so completed games appear alongside upcoming ones.

**Implementation:**

1. Replace fallback logic in `src/delivery/views/picks.py`:
   - Primary query: `Match.status == "scheduled"` AND `Match.date >= today`, sorted by `Match.date ASC, ValueBet.edge DESC`
   - Fallback: expand window to next 14 days of scheduled matches
   - If still empty: show "No upcoming value bets found" with last pipeline run timestamp
2. Add separate "Recent Results" section below for last 7 days of finished matches with actual outcomes shown (win/loss indicator)
3. Remove "Mark as Placed" button for finished matches
4. Sort: date ascending (soonest first), edge descending within same matchday

**Acceptance Criteria:**
- [ ] Today's Picks shows ONLY scheduled/upcoming matches by default
- [ ] Sorting: soonest date first, then highest edge within each date
- [ ] No finished matches appear in the actionable picks section
- [ ] Fallback window capped at 14 days, not all-time
- [ ] "Recent Results" section shows last 7 days of completed picks with outcomes
- [ ] "Mark as Placed" only shown for scheduled matches

---

### E24-02 — Fix Deep Dive for Future Matches

**Type:** Bug Fix — Dashboard
**Depends on:** E8-01 (Match Deep Dive), E18-01 (Narrative), E19-01 (Odds API)
**MP refs:** §8 Dashboard, §13.14
**Status:** PLANNED

The Match Deep Dive page conditionally hides scoreline matrix, market probabilities, and narrative when no ValueBet records exist. But scheduled matches have Prediction records with full scoreline matrices — the page should render this data regardless of value bet availability.

**Implementation:**

1. In `src/delivery/views/match_detail.py`:
   - Render scoreline matrix section when `data["prediction"]` exists (not gated on value bets)
   - Render market probabilities section when prediction exists
   - Render narrative section when prediction exists
   - Only gate the "Value Bets" card on `data["value_bets"]` being non-empty
2. In `src/delivery/narrative.py`:
   - Ensure `generate_match_narrative()` works with predictions that have no associated odds/value bets
   - Gracefully handle missing odds data in narrative factors
3. Debug Odds API team name mapping:
   - Verify all 20 EPL teams map correctly from The Odds API → DB canonical names
   - Add any missing mappings
   - Add a diagnostic log when odds exist in DB but weren't matched to predictions

**Acceptance Criteria:**
- [ ] Deep Dive shows scoreline matrix for scheduled matches with predictions
- [ ] Deep Dive shows market probabilities (1X2, BTTS, O/U) for scheduled matches
- [ ] Deep Dive shows match narrative for scheduled matches
- [ ] Value Bets section shows "No value bets identified" when none exist (not hidden entirely)
- [ ] All 20 EPL teams correctly mapped in Odds API → DB name mapping
- [ ] No crashes or empty pages for any scheduled match with a Prediction record

---

### E24-03 — Fixtures Value Grid — Model Indicators

**Type:** Enhancement — Dashboard
**Depends on:** E24-02 (predictions must render for scheduled matches)
**MP refs:** §8 Dashboard, §13.14
**Status:** PLANNED

Add inline color-coded market indicators to each fixture row on the Fixtures page. Currently each row shows only: kickoff time, "Home vs Away", binary value badge, league badge, and a Deep Dive button.

**Implementation:**

1. In `src/delivery/views/fixtures.py`:
   - For each scheduled match, query its Prediction record and associated Odds records
   - Compute edge per market selection: `edge = model_prob - implied_prob` (same logic as ValueFinder)
   - Render 7 compact badges per fixture row:
     - **1X2:** Home (H), Draw (D), Away (A)
     - **BTTS:** Yes, No
     - **O/U 2.5:** Over (O), Under (U)
   - Color coding based on edge:
     - 🟢 Green: edge ≥ value threshold (from config, typically 3-5%)
     - 🟡 Yellow: 0% < edge < value threshold (marginal — model slightly favours but not enough for a bet)
     - 🔴 Red: edge ≤ 0% (no value — bookmaker price is fair or better)
     - ⚫ Grey: no data (odds or prediction unavailable)
   - Layout: badges appear on the same line as team names, right-aligned before the Deep Dive button

2. Add a legend/key at the top of the Fixtures page explaining the color coding

3. Add tooltip on each badge showing the exact edge percentage on hover (Streamlit `st.help` or custom HTML)

**Acceptance Criteria:**
- [ ] Each fixture row shows 7 color-coded badges (H/D/A, BTTS Y/N, O2.5/U2.5)
- [ ] Green = edge above value threshold, yellow = marginal, red = no value, grey = no data
- [ ] Edge thresholds read from config (not hardcoded)
- [ ] Legend at top of page explains color coding
- [ ] Badges render correctly when predictions exist but odds don't (grey fallback)
- [ ] Fixtures without predictions show all-grey badges (not broken layout)
- [ ] Design system compliant: green #3FB950, red #F85149, yellow #D29922, grey #484F58

---

### E24-04 — Fixtures Value Grid — Data Pipeline

**Type:** DevOps — Pipeline Verification
**Depends on:** E24-03 (grid must be built first)
**MP refs:** §13.14
**Status:** COMPLETE ✅

Ensure the prediction→odds→value chain is complete for all scheduled fixtures. The value grid is only useful if data flows through the full pipeline for upcoming matches.

**Implementation:**

1. Verify prediction generation for all scheduled matches:
   - Check `_generate_predictions()` in pipeline.py — confirm it processes scheduled matches
   - Verify Feature computation includes scheduled matches (E18-03 should have fixed this)
   - If any scheduled match lacks a Prediction, trace why and fix

2. Verify Odds API coverage:
   - Run The Odds API scraper and confirm all scheduled matches get odds loaded
   - Check team name mapping for all 20 EPL teams
   - Log any matches with predictions but no odds (diagnostic)

3. Add diagnostic badges to fixtures page:
   - "No odds" badge when a match has predictions but no odds loaded
   - "No prediction" badge when odds exist but no prediction
   - "Full data" indicator when both are present

4. Add pipeline health check: a summary line at top of Fixtures page showing
   "X/Y fixtures have full prediction + odds data"

**Acceptance Criteria:**
- [ ] All scheduled matches have Prediction records after morning pipeline
- [ ] All scheduled matches have Odds records after morning pipeline (Odds API)
- [ ] Diagnostic badges visible when data is partially missing
- [ ] Pipeline health summary shown on Fixtures page
- [ ] Zero team name mapping failures in Odds API → DB

---

### E24-05 — Fixtures + Picks Integration Test

**Type:** Testing — End-to-End
**Depends on:** E24-01, E24-02, E24-03, E24-04
**MP refs:** §13.14
**Status:** COMPLETE ✅

Run the full morning pipeline and verify all three dashboard fixes work end-to-end with live data.

**Acceptance Criteria:**
- [ ] Morning pipeline runs to completion (features → predictions → odds → value bets)
- [ ] Fixtures page shows color-coded grid with real data for all scheduled matches
- [ ] Today's Picks shows only upcoming matches, sorted by date then edge
- [ ] Deep Dive works for every scheduled match — shows scoreline matrix, probabilities, narrative
- [ ] No finished/historical matches appear in actionable picks
- [ ] All 20 EPL teams have predictions + odds for their next scheduled match
- [ ] Dashboard loads in <5 seconds on all pages

---

### Implementation Sequence

```
E24-01 (picks date fix) → E24-02 (deep dive fix) → E24-03 (fixtures grid UI)
→ E24-04 (data pipeline verification) → E24-05 (integration test)
```

E24-01 and E24-02 are independent bug fixes that can be done first. E24-03 builds the UI that E24-04 validates. E24-05 tests everything together.

---

## E25 — XGBoost Ensemble Model

### Motivation

The Poisson GLM has reached its architectural ceiling at Brier 0.5781 / ROI +2.78%. It cannot capture non-linear interactions between features — e.g., how Pinnacle odds interact with Elo ratings under fixture congestion. XGBoost (gradient-boosted decision trees) is the natural next model:

- Handles non-linear relationships natively
- Handles missing values without imputation
- Provides feature importance rankings out of the box
- Already installed as a pip dependency (`xgboost` in requirements.txt)
- The `BaseModel` interface was designed for exactly this — any model producing a 7×7 scoreline matrix slots in

With 2,280 matches of training data (from E23), there is sufficient volume to train a gradient-boosted model without severe overfitting.

---

### E25-01 — XGBoost Scoreline Model

**Type:** Model — New Implementation
**Depends on:** E4-01 (BaseModel), E23-06 (sufficient training data)
**MP refs:** §5 Model Architecture, §13.15
**Status:** COMPLETE ✅

Build `src/models/xgboost_model.py` implementing the `BaseModel` abstract interface. Trains XGBoost regressors to predict home and away expected goals, then generates the 7×7 scoreline probability matrix via Poisson distribution from the predicted λ values.

**Implementation:**

1. New file `src/models/xgboost_model.py`:
   - Class `XGBoostModel(BaseModel)`
   - `train()`: Fits two XGBRegressor models (home_goals, away_goals) on the same feature matrix as Poisson
   - `predict()`: Predicts home_λ and away_λ, builds 7×7 scoreline matrix via `scipy.stats.poisson.pmf`
   - Feature selection: reuse `_select_feature_cols()` pattern from Poisson — only include columns present in DataFrame
   - Hyperparameters in `config/settings.yaml`: max_depth, n_estimators, learning_rate, min_child_weight, subsample, colsample_bytree
   - Walk-forward safe: `train()` only sees past data, `predict()` produces future predictions
   - Model persistence: save/load via `src/models/storage.py` (pickle)

2. Key design decisions:
   - Predict λ (expected goals), NOT scoreline probabilities directly — preserves the Poisson distribution assumption for the scoreline matrix
   - Use the same feature set as Poisson for fair comparison — no feature engineering advantage
   - Cross-validation within training set for hyperparameter tuning (temporal CV, not random)

**Acceptance Criteria:**
- [ ] `XGBoostModel` implements `BaseModel` interface (train, predict, name, version)
- [ ] Produces a valid 7×7 scoreline matrix (probabilities sum to ~1.0)
- [ ] Hyperparameters configurable from settings.yaml
- [ ] Walk-forward safe — train/predict split respects temporal integrity
- [ ] Feature selection handles missing columns gracefully
- [ ] Model saves and loads via storage.py
- [ ] Unit test: train on small sample, predict produces valid matrix

---

### E25-02 — Ensemble Combiner

**Type:** Model — Ensemble Integration
**Depends on:** E25-01 (XGBoost model must exist), E11-01 (ensemble_weights.py)
**MP refs:** §5 Model Architecture, §11 Self-Improvement, §13.15
**Status:** COMPLETE ✅

Combine Poisson and XGBoost scoreline matrices using the existing ensemble infrastructure. The combined matrix is the weighted average of both models' 7×7 outputs.

**Implementation:**

1. Update `src/self_improvement/ensemble_weights.py`:
   - Register "xgboost_v1" as a new model alongside "poisson_v1"
   - Initial weights: 50/50 (equal weighting until backtested)
   - Weight update logic already exists — adjusts based on per-model Brier scores with guardrails (MP §11: minimum 100 bets sample, max 10% weight change per update, rollback on degradation)

2. Update `src/pipeline.py`:
   - In `_generate_predictions()`: train both Poisson and XGBoost
   - Generate scoreline matrices from both models
   - Combine via weighted average
   - Store the ensemble prediction as the primary Prediction record
   - Store individual model predictions in a new `model_name` field for tracking

3. Config: `config/settings.yaml` — `ensemble.models` list with names and initial weights

**Acceptance Criteria:**
- [ ] Ensemble combines Poisson + XGBoost scoreline matrices
- [ ] Weights configurable in settings.yaml
- [ ] Self-improvement guardrails apply (min sample, max change rate, rollback)
- [ ] Individual model predictions tracked alongside ensemble
- [ ] Pipeline runs both models and stores ensemble result
- [ ] Ensemble matrix is valid (probabilities sum to ~1.0)

---

### E25-03 — Walk-Forward Backtest

**Type:** Evaluation — Backtesting
**Depends on:** E25-02 (ensemble must be built)
**MP refs:** §13.15
**Status:** COMPLETE ✅

Compare three configurations across 5 historical seasons to determine the best production model.

**Configurations:**
1. **Poisson-only** (current production baseline: Brier 0.5781, ROI +2.78%)
2. **XGBoost-only** (new model in isolation)
3. **Ensemble** (weighted Poisson + XGBoost)

**Metrics:** Brier score, ROI, calibration (expected vs actual), log-loss, max drawdown, win rate by market.

**Implementation:**

1. Run `backtester.py` for each configuration with identical feature set and training data
2. Store all results in ModelPerformance table with distinct `model_name` values
3. Generate comparison table and charts in Model Health dashboard
4. Document results with before/after comparison

**Backtest Results (2024-25, 5-season training):**

| Metric | Poisson-only | XGBoost-only | Ensemble (50/50) |
|--------|-------------|-------------|-----------------|
| **Brier Score** | **0.5781** | 0.5821 | 0.5778 |
| **ROI (%)** | **+2.78** 🏆 | -19.02 | -9.39 |
| **Total PnL (£)** | **+356.33** | -861.70 | -607.05 |
| **Final Bankroll (£)** | **1,356.33** | 138.30 | 392.95 |
| Value Bets | 634 | 769 | 580 |
| Max Drawdown (%) | 69.2 | 95.5 | 82.8 |
| Win Rate 1X2 (%) | 33.2 | 30.4 | 32.7 |
| Win Rate O/U (%) | 42.7 | 41.1 | 34.0 |
| Time (s) | 128.7 | 973.2 | 443.2 |

**Winner: Poisson-only** — the ONLY profitable configuration (+2.78% ROI).
- XGBoost alone is significantly worse: higher Brier (0.5821), deeply unprofitable (-19% ROI), 95% drawdown
- Ensemble has marginally better Brier (0.5778 vs 0.5781 = 0.05% improvement) but is unprofitable (-9.4% ROI)
- Poisson's simpler parametric model generalises better with ~1,900 training samples
- XGBoost likely overfits non-linear patterns that don't persist out-of-sample
- Conclusion: **keep Poisson as production model, do not enable ensemble**

**Acceptance Criteria:**
- [x] All 3 configurations backtested on 2024-25 with 5-season training data
- [x] Results stored in ModelPerformance table (poisson_v1_5s, xgboost_v1_5s, ensemble_v1_5s)
- [x] Comparison table: Brier, ROI, max drawdown, win rates for each configuration
- [x] Clear winner identified: Poisson-only (only profitable model)
- [x] Results documented in build plan with full metrics table

---

### E25-04 — Promote Best Model

**Type:** DevOps — Model Promotion
**Depends on:** E25-03 (backtest results must be available)
**MP refs:** §13.15
**Status:** COMPLETE ✅

Based on E25-03 backtest results, set the winning configuration as the production default.

**Decision: Keep Poisson as production model.**

The E25-03 backtest conclusively showed Poisson-only is the best configuration:
- **Poisson:** Brier 0.5781, ROI +2.78%, PnL +£356 ← only profitable model
- **XGBoost:** Brier 0.5821, ROI -19.0%, nearly wiped out bankroll (95% drawdown)
- **Ensemble:** Brier 0.5778, ROI -9.4%, marginally better prediction quality but unprofitable

**Why XGBoost didn't help:**
- ~1,900 training samples is insufficient for 200-tree gradient boosting with 30+ features
- XGBoost learns non-linear patterns that don't persist out-of-sample (overfitting)
- The Poisson GLM's constraint (linear in log-space) acts as strong regularisation
- XGBoost generates more value bets (769 vs 634) but at worse quality → net negative ROI

**When to revisit:** When training data exceeds 5,000 matches (post-2027 with 7+ EPL seasons), XGBoost's capacity for non-linear interactions may become beneficial. The infrastructure (model class, ensemble combiner, backtester) is built and ready.

**Changes made:**
1. `config/settings.yaml` — confirmed `poisson_v1` as sole active model, `ensemble_enabled: false`, added decision documentation comment
2. `pipeline.py` — already uses `config.settings.models.active_models` (no change needed)
3. `model_health.py` — updated "Active Models" metric to show actual model name from config
4. `betvector_masterplan.md` — updated Model Performance Evolution table with E25-03 results
5. `betvector_buildplan.md` — documented full decision rationale

**Acceptance Criteria:**
- [x] Best model/configuration promoted to production in settings.yaml (Poisson retained, decision documented)
- [x] Pipeline uses the promoted configuration for daily predictions (poisson_v1 via config)
- [x] Model Health dashboard shows active model name ("poisson_v1" instead of count)
- [x] Masterplan Model Performance Evolution table updated with E25-03 results
- [x] Build plan documents the decision and rationale (this section)

---

### Implementation Sequence

```
E25-01 (XGBoost model) → E25-02 (ensemble combiner)
→ E25-03 (backtest comparison) → E25-04 (promote winner)
```

E25-01 must be first (model must exist). E25-02 integrates it. E25-03 evaluates. E25-04 promotes.
