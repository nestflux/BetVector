# BetVector -- How-To Manual

A practical guide to installing, running, and operating the BetVector football
betting system.

**Version:** 1.1
**Last updated:** February 2026

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Running the Pipeline](#running-the-pipeline)
3. [Using the Dashboard](#using-the-dashboard)
4. [Automated Operation (GitHub Actions)](#automated-operation-github-actions)
5. [Walk-Forward Backtesting](#walk-forward-backtesting)
6. [Adding New Leagues](#adding-new-leagues)
7. [Configuration Reference](#configuration-reference)
8. [Database Backup and Maintenance](#database-backup-and-maintenance)
9. [Deploying to Streamlit Cloud](#deploying-to-streamlit-cloud)
10. [Troubleshooting](#troubleshooting)
11. [Daily Workflow (Recommended)](#daily-workflow-recommended)
12. [Key Concepts Glossary](#key-concepts-glossary)

---

## Getting Started

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10 or higher | 3.11 works fine. Do not use 3.8 or 3.9. |
| Git | Any recent version | For cloning the repo and version control. |
| Make | Any version | Comes preinstalled on macOS/Linux. On Windows use WSL. |
| sqlite3 | Any version | Used by the backup script. Comes preinstalled on most systems. |

**Required accounts:**

| Account | Purpose | Where to sign up |
|---------|---------|------------------|
| Gmail | Sending email alerts (morning picks, evening results, weekly summary) | gmail.com |
| API-Football | Live odds and fixtures (free tier: 100 requests/day) | api-football.com |

The Gmail account requires two-factor authentication enabled so you can
generate an App Password (your regular Gmail password will not work).

### Installation

Clone the repository and install all dependencies:

```bash
git clone https://github.com/nestflux/BetVector.git
cd BetVector
make install
```

The `make install` command does three things:

1. Creates a Python virtual environment in `venv/`
2. Installs all 20 pinned dependencies from `requirements.txt`
3. Installs the project in editable mode (`pip install -e .`) so that
   `from src.x import y` works from anywhere

Activate the virtual environment:

```bash
source venv/bin/activate
```

You need to activate the virtual environment every time you open a new
terminal session. All commands in this manual assume it is active.

Verify the installation:

```bash
python -c "import pandas, numpy, scipy, sklearn, statsmodels, requests, bs4, yaml, sqlalchemy, plotly, streamlit, xgboost, lightgbm"
```

If that runs without errors, all dependencies are installed correctly.

### Setting Up the `.env` File

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

Open `.env` in your editor and set these three variables:

```
# Password to protect the Streamlit dashboard.
# Leave empty to disable the password gate during local development.
DASHBOARD_PASSWORD=your-secure-password

# Gmail App Password for sending morning/evening/weekly email alerts.
# Generate one at: https://myaccount.google.com/apppasswords
# Requires 2-factor authentication enabled on your Google account.
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

# RapidAPI key for API-Football (free tier: 100 requests/day).
# Sign up at: https://www.api-football.com/
API_FOOTBALL_KEY=your-api-football-key
```

**Important:** Never commit the `.env` file. It is already listed in `.gitignore`.

### First-Time Setup

Initialize the database and seed reference data (leagues, seasons, default user):

```bash
python run_pipeline.py setup
```

This creates the SQLite database at `data/betvector.db` with all 18 tables and
populates leagues, seasons, and the owner user record. You will see:

```
BetVector Setup
========================================
[1/2] Initialising database...
  -> Database tables created
[2/2] Seeding reference data...
  -> Leagues, seasons, and owner seeded

Setup complete.
```

### Running Your First Backtest

Before going live, validate the model against historical data:

```bash
python run_pipeline.py backtest --league EPL --season 2024-25
```

This runs a full walk-forward backtest on the 2024-25 English Premier League
season. It will:

1. Scrape historical match data from Football-Data.co.uk
2. Walk through each matchday chronologically
3. Train the Poisson model only on past data at each step
4. Generate predictions and find value bets
5. Simulate bankroll changes
6. Output a report with ROI, bet count, and Brier score

Results are saved to `data/predictions/backtest_report.json` and a chart is
written to `data/predictions/backtest_results.png`.

---

## Running the Pipeline

BetVector operates on a three-run-per-day cycle. Each run serves a different
purpose and can be triggered manually from the command line.

### Morning Pipeline (06:00 UTC)

**What it does:** Scrape fixtures and odds, compute features, run the Poisson
model, detect value bets, log system picks, and send the morning email alert.

```bash
python run_pipeline.py morning
```

This is the core run -- it answers the question "what should we bet on today?"

Steps executed in order:

1. Scrape today's fixtures from Football-Data.co.uk and API-Football
2. Scrape current bookmaker odds
3. Compute rolling features (goals scored/conceded, form, xG if available)
4. Run Poisson regression to produce 7x7 scoreline probability matrices
5. Derive market probabilities (1X2, Over/Under 2.5, BTTS) from each matrix
6. Compare model probabilities against bookmaker implied probabilities
7. Flag fixtures where the model edge exceeds the configured threshold
8. Log every value bet as a `system_pick` in the bet log
9. Send the morning email with today's picks

If no command is specified, the morning pipeline runs by default:

```bash
python run_pipeline.py
```

### Midday Pipeline (13:00 UTC)

**What it does:** Re-fetch odds (which move throughout the day as money comes
in), recalculate edges, and update the value bets table.

```bash
python run_pipeline.py midday
```

Odds change between morning and kickoff. The midday run captures those
movements -- a bet that had 8% edge at 06:00 might now have 12% or 3%.

### Evening Pipeline (22:00 UTC)

**What it does:** Scrape match results, resolve pending bets (won/lost/void),
update P&L, recalculate the bankroll, generate performance metrics, and send
the evening email.

```bash
python run_pipeline.py evening
```

This is the "how did we do today?" run. It also checks self-improvement
triggers (recalibration, retrain) and runs the weekly summary on Sundays.

### Verbose Mode

Add `--verbose` (or `-v`) to any command for DEBUG-level logging:

```bash
python run_pipeline.py morning --verbose
python run_pipeline.py backtest --league EPL --season 2024-25 --verbose
```

This shows every HTTP request, database query, feature calculation, and model
output. Useful for diagnosing issues.

### Pipeline Resilience

Each pipeline run is wrapped in step-level error handling. If one step fails
(for example, FBref returns a 403 or the odds API times out):

- The error is logged
- Subsequent steps still attempt to run
- The pipeline run record in the database records which steps succeeded and
  which failed
- A `PipelineResult` object is returned with the list of errors

A single scraper failure will never prevent predictions from being made with
the data that is available. A single email failure will never prevent results
from being recorded.

Each run also creates a `pipeline_runs` record in the database tracking:
- Run type (morning/midday/evening/manual/backtest)
- Status (running, completed, failed)
- Counts (matches scraped, predictions made, value bets found)
- Duration in seconds
- Error messages (if any step failed)

---

## Using the Dashboard

### Launching the Dashboard

```bash
streamlit run src/delivery/dashboard.py
```

Or using the Makefile shortcut:

```bash
make run
```

The dashboard opens at `http://localhost:8501` by default.

### Password Protection

If you set `DASHBOARD_PASSWORD` in your `.env` file, the dashboard shows a
login screen. Enter the password to access the pages.

If the variable is empty or unset, the dashboard is open without a password
(convenient for local development).

### Onboarding

First-time users see a welcome wizard before the main dashboard. The
onboarding flow walks you through initial configuration (staking method,
bankroll, edge threshold). Once completed, you go straight to the dashboard
on subsequent visits.

### Today's Picks

The default landing page. Shows every value bet the model has found for today.

**Reading a pick card:**

| Field | Meaning |
|-------|---------|
| Match | Home vs Away team names and kickoff time |
| Market | The bet type -- 1X2 (match result), OU25 (over/under 2.5 goals), BTTS |
| Model Prob | The model's estimated probability for this outcome |
| Implied Prob | The bookmaker's implied probability (derived from the odds) |
| Edge | Model probability minus implied probability. Higher is better. |
| Confidence | High (edge >= 10%), Medium (5-10%), Low (< 5%) |
| Best Odds | The highest odds found across bookmakers |
| Suggested Stake | Based on your chosen staking method and current bankroll |

**Placing bets:** After you place a bet with a real bookmaker, click the "Log
Bet" button on the pick card to record it. This creates a `user_placed` entry
in the bet log, separate from the `system_pick` that was auto-logged. This
dual tracking lets you compare the model's theoretical performance against
your actual betting results.

### Performance Tracker

Tracks the system's overall performance over time.

- **ROI** -- Return on investment across all resolved bets. System picks and
  user-placed bets are shown separately so you can compare the model's full
  recommendations against only the bets you actually placed.
- **Brier Score** -- Measures prediction accuracy. Lower is better. A Brier
  score of 0.25 is random chance for binary outcomes; anything below that
  indicates predictive skill.
- **P&L Chart** -- Cumulative profit and loss over time, plotted as an
  interactive Plotly line chart. Hover over any point to see the exact value.
- **Win Rate** -- Percentage of bets that won.
- **Bet Count** -- Total resolved bets.

### League Explorer

Breaks down performance by league. Shows ROI, bet count, win rate, and Brier
score for each tracked league. Useful for identifying which leagues the model
performs best in and which might need higher edge thresholds.

### Match Deep Dive

Detailed analysis of any specific match. Select a match to see:

- **Scoreline Probability Matrix** -- The 7x7 heatmap showing the probability
  of every possible score from 0-0 to 6-6. This is the core model output from
  which all market probabilities are derived.
- **Market Probabilities** -- Home/Draw/Away, Over/Under 2.5, BTTS
  probabilities compared against bookmaker odds.
- **Team Form** -- Recent results, goals scored/conceded rolling averages.
- **Feature Values** -- The exact feature inputs the model used for this
  prediction.

### Model Health

Monitors whether the model is well-calibrated and performing within expected
bounds.

- **Calibration Curve** -- Plots predicted probabilities against actual
  outcome frequencies. A well-calibrated model hugs the diagonal line. If the
  curve bows above the diagonal, the model is underconfident; below means
  overconfident.
- **Brier Score Over Time** -- Rolling Brier score to detect performance
  degradation. If it trends upward, the model may need retraining.
- **Prediction Distribution** -- Histogram of predicted probabilities. A good
  model produces a spread of probabilities, not just 50/50 for everything.

### Bankroll Manager

Tracks your bankroll and staking history.

- **Current Bankroll** -- Your current balance, starting amount, and
  all-time P&L.
- **Drawdown Monitor** -- Current drawdown from peak (calculated from settled
  bets only), with alerts if it exceeds the configured threshold (default: 25%).
- **Staking History** -- Table of every bet placed, with stake size, odds,
  outcome, and P&L.
- **Safety Alerts** -- Warnings if daily losses exceed 10% of bankroll, if
  bankroll drops below 50% of starting, or if any single bet exceeds the
  max bet percentage (5%).

### Settings

Configure the system through the dashboard without editing YAML files directly.

- **Staking Method** -- Switch between flat (fixed amount per bet), percentage
  (fixed percentage of current bankroll), or Kelly (stake proportional to edge,
  scaled by the Kelly fraction).
- **Edge Threshold** -- Minimum edge required to flag a value bet. Default is
  5% (0.05). Lower it to see more bets, raise it for fewer but higher-quality
  picks.
- **Paper Trading Mode** -- When enabled, the system logs bets and tracks P&L
  but marks them as simulated. Recommended for the first few weeks until you
  trust the model.
- **Kelly Fraction** -- Scaling factor for Kelly staking. Default is 0.25
  (quarter-Kelly). Full Kelly is mathematically optimal but has high variance;
  fractional Kelly is more practical.
- **Stake Percentage** -- For percentage staking, what fraction of the bankroll
  to bet per pick. Default is 2%.

---

## Automated Operation (GitHub Actions)

### The Three Cron Workflows

BetVector includes three GitHub Actions workflows that automate the daily
pipeline:

| Workflow | Schedule | File |
|----------|----------|------|
| Morning Pipeline | 06:00 UTC daily | `.github/workflows/morning.yml` |
| Midday Pipeline | 13:00 UTC daily | `.github/workflows/midday.yml` |
| Evening Pipeline | 22:00 UTC daily | `.github/workflows/evening.yml` |

Each workflow:

1. Checks out the repository (including the SQLite database)
2. Sets up Python 3.10 and installs dependencies
3. Runs the corresponding pipeline command
4. Commits any database changes back to the repo
5. Sends an email notification if the run fails

Concurrency groups ensure that overlapping runs of the same pipeline are
prevented (e.g., a manual trigger during a scheduled run).

### How to Enable Automated Operation

**Step 1: Push your repository to GitHub** (if not already done):

```bash
git push origin main
```

**Step 2: Set repository secrets** in GitHub:

Go to your repo on GitHub, then Settings > Secrets and variables > Actions,
and add these three secrets:

| Secret Name | Value |
|-------------|-------|
| `GMAIL_APP_PASSWORD` | Your Gmail App Password |
| `DASHBOARD_PASSWORD` | Your dashboard password |
| `API_FOOTBALL_KEY` | Your API-Football RapidAPI key |

**Step 3: Workflows activate automatically.** The cron schedules start running
at the specified UTC times once the workflow files are on the `main` branch.

### Running Workflows Manually

Each workflow supports `workflow_dispatch`, which means you can trigger it
from the GitHub UI at any time:

1. Go to your repo on GitHub
2. Click the **Actions** tab
3. Select the workflow (e.g., "Morning Pipeline") from the left sidebar
4. Click **Run workflow**
5. Optionally set "verbose" to "true" for debug logging
6. Click the green **Run workflow** button

### Checking Workflow Run History

1. Go to the **Actions** tab on your GitHub repo
2. Each workflow run shows its status (success, failure, in-progress)
3. Click a run to see the full log output for each step
4. Failed runs send an email notification if `GMAIL_APP_PASSWORD` is
   configured

### What Gets Committed Automatically

After each pipeline run, the workflow commits the updated SQLite database
(`data/betvector.db`) back to the repository. The commit message indicates
which pipeline ran and the date:

```
Morning pipeline: 2025-03-15
Midday pipeline: 2025-03-15
Evening pipeline: 2025-03-15
```

On Sunday evenings, the weekly database backup is also committed (see
[Database Backup and Maintenance](#database-backup-and-maintenance)).

---

## Walk-Forward Backtesting

### What Is Walk-Forward Backtesting?

Walk-forward validation is the only valid backtesting approach for time-series
prediction like sports betting. It simulates exactly what happens in live
operation:

1. Start at the first matchday of the season
2. Train the model on all data available before that matchday
3. Predict that matchday's matches
4. Record predictions and find value bets
5. Advance to the next matchday
6. Retrain on all data up to (but not including) the current matchday
7. Repeat through the entire season

**Why this matters:** A random train/test split would leak future data into
training -- a match from April might train the model that then predicts a
March match. Walk-forward validation prevents this by ensuring the model only
ever sees data from before the prediction date.

**Training set grows over time:** Early-season predictions (matchdays 1-5)
have very little training data and will be noisy. The Poisson model requires
at least 20 matches to fit, so the first 2-3 matchdays are typically skipped.
This is realistic -- in live operation, you also have less data at the start
of a new season.

### Running a Backtest

```bash
python run_pipeline.py backtest --league EPL --season 2024-25
```

Available flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--league` | `EPL` | League short name from `config/leagues.yaml` |
| `--season` | `2024-25` | Season to backtest |
| `--verbose` | off | Enable DEBUG-level logging |

For verbose output showing every matchday:

```bash
python run_pipeline.py backtest --league EPL --season 2024-25 --verbose
```

### Reading the Backtest Report

The report is saved to `data/predictions/backtest_report.json` and contains:

| Field | Meaning |
|-------|---------|
| `total_bets` | Number of value bets the model would have placed |
| `won` | Number of winning bets |
| `lost` | Number of losing bets |
| `roi` | Return on investment as a percentage |
| `brier_score` | Overall prediction accuracy (lower is better) |
| `total_staked` | Sum of all stakes placed |
| `total_return` | Sum of all returns from winning bets |
| `profit_loss` | Net profit or loss |

### Interpreting the Backtest Chart

The chart (`data/predictions/backtest_results.png`) shows cumulative P&L over
the season. Key things to look for:

- **Upward trend** -- The model is generating profit over time
- **Flat or downward** -- The model is not finding consistent value
- **Sharp drops** -- Extended losing runs (normal variance, but watch for
  sustained declines)
- **Recovery after drops** -- The model bounces back, which is a good sign

A negative ROI on the first backtest is normal. The baseline Poisson model
without xG features typically produces ROI in the -5% to +5% range. Adding
more features and leagues improves this over time.

---

## Adding New Leagues

### Step 1: Edit `config/leagues.yaml`

Add a new league block following the existing EPL template:

```yaml
  - name: "La Liga"
    short_name: "LaLiga"
    country: "Spain"
    football_data_code: "SP1"
    fbref_league_id: "ESP-La Liga"
    api_football_id: 140
    is_active: true
    seasons:
      - "2024-25"
    total_matchdays: 38
```

### Step 2: Find the Required Identifiers

You need three identifiers per league, one for each data source:

| Identifier | Where to Find It |
|------------|------------------|
| `football_data_code` | URL path on football-data.co.uk -- look at the CSV download links (e.g., `E0` for EPL, `SP1` for La Liga, `D1` for Bundesliga, `I1` for Serie A, `F1` for Ligue 1) |
| `fbref_league_id` | The soccerdata package league identifier (e.g., `ENG-Premier League`, `ESP-La Liga`, `GER-Bundesliga`, `ITA-Serie A`, `FRA-Ligue 1`) |
| `api_football_id` | The numeric league ID from the API-Football documentation |

### Step 3: Set `is_active: true`

Only leagues with `is_active: true` are included in pipeline runs. You can
add league configurations with `is_active: false` and enable them later.

### Step 4: Run Setup to Seed the New League

```bash
python run_pipeline.py setup
```

This seeds the new league and its seasons into the database. Existing data
is not affected (the seed operations are idempotent).

### Step 5: Run the Morning Pipeline

```bash
python run_pipeline.py morning
```

The pipeline will scrape data for the new league, compute features, and
generate predictions. The first run may take longer as it downloads historical
match data.

### Step 6: Verify

Check the dashboard's League Explorer page to confirm the new league appears
with matches and predictions.

### Common League Codes

| League | `football_data_code` | `fbref_league_id` | `api_football_id` |
|--------|---------------------|-------------------|-------------------|
| Premier League (England) | `E0` | `ENG-Premier League` | 39 |
| La Liga (Spain) | `SP1` | `ESP-La Liga` | 140 |
| Bundesliga (Germany) | `D1` | `GER-Bundesliga` | 78 |
| Serie A (Italy) | `I1` | `ITA-Serie A` | 135 |
| Ligue 1 (France) | `F1` | `FRA-Ligue 1` | 61 |
| Eredivisie (Netherlands) | `N1` | `NED-Eredivisie` | 88 |
| Primeira Liga (Portugal) | `P1` | `POR-Primeira Liga` | 94 |
| Championship (England) | `E1` | `ENG-Championship` | 40 |

---

## Configuration Reference

All tuneable parameters live in YAML files under `config/`. The system reads
them through `src/config.py` -- never hardcode values in application code.

### `config/settings.yaml`

#### Database

```yaml
database:
  path: "data/betvector.db"      # SQLite file location
  enable_wal: true               # Write-Ahead Logging for concurrent access
```

When migrating to PostgreSQL, change `path` to a connection string and set
`enable_wal: false`. PostgreSQL handles concurrency differently and does not
use WAL.

#### Feature Engineering

```yaml
features:
  rolling_windows:
    - 5                          # Last 5 matches
    - 10                         # Last 10 matches
```

Rolling windows for computing averages (goals, shots, xG). Expressed in number
of matches, not calendar days.

#### Value Betting

```yaml
value_betting:
  edge_threshold: 0.05           # Minimum 5% edge to flag a value bet
  confidence_thresholds:
    high: 0.10                   # Edge >= 10%
    medium: 0.05                 # 5% <= edge < 10%
```

Lower the `edge_threshold` to see more bets (but with less edge). Raise it
for fewer, higher-quality picks.

#### Bankroll Management

```yaml
bankroll:
  starting_amount: 1000.0        # Initial bankroll in your currency
  staking_method: "flat"         # flat | percentage | kelly
  stake_percentage: 0.02         # 2% of bankroll per bet (for percentage staking)
  kelly_fraction: 0.25           # Quarter-Kelly (for kelly staking)
  paper_trading_mode: true       # Simulated mode -- no real money at risk
```

**Staking methods explained:**

| Method | How It Works |
|--------|--------------|
| `flat` | Same fixed stake on every bet, regardless of bankroll or edge size. Simplest approach. |
| `percentage` | Stake = `stake_percentage` x current bankroll. Bets grow when you're winning and shrink when you're losing. |
| `kelly` | Stake = `kelly_fraction` x Kelly criterion (edge / (odds - 1)). Mathematically optimal for long-term bankroll growth but volatile in practice. Quarter-Kelly (0.25) is recommended. |

#### Safety Limits

```yaml
safety:
  max_bet_percentage: 0.05       # Never stake > 5% of bankroll on one bet
  daily_loss_limit: 0.10         # Alert if daily losses > 10% of bankroll
  drawdown_alert_threshold: 0.25 # Alert if drawdown from peak > 25%
  minimum_bankroll_percentage: 0.50  # Alert if bankroll < 50% of starting
```

These limits apply regardless of staking method. Breaching any limit pauses
automated staking and triggers an alert on the dashboard and via email.

#### Model Settings

```yaml
models:
  active_models:
    - "poisson_v1"               # Currently active model(s)
  ensemble_enabled: false        # Enable after each model has 300+ resolved predictions
```

Additional models (XGBoost, LightGBM) can be added to `active_models` once
they are trained. The ensemble averages their predictions using adaptive
weights (see Self-Improvement below).

#### Scoreline Matrix

```yaml
scoreline_matrix:
  max_goals: 7                   # 0-6 goals per side = 7x7 matrix
```

Every prediction model outputs a 7x7 matrix of scoreline probabilities. All
market probabilities (1X2, Over/Under, BTTS) are derived from this matrix.
This is the universal model interface -- every model must produce this output.

#### Self-Improvement Engine

The self-improvement engine automatically tunes the model over time, with
guardrails to prevent overcorrection. Every automatic adjustment has a minimum
sample size, a maximum change rate, and a rollback mechanism.

**Recalibration** (adjusts predicted probabilities to match actual outcomes):

```yaml
self_improvement:
  recalibration:
    min_sample_size: 200         # Need 200+ resolved predictions before recalibrating
    calibration_error_threshold: 0.03  # Trigger if mean-abs cal error > 3 pp
    rollback_window: 100         # Evaluate rollback after 100 post-cal predictions
    calibration_methods:
      - "platt"                  # Platt scaling (logistic regression on probabilities)
      - "isotonic"               # Isotonic regression (non-parametric)
```

**Feature importance tracking** (for tree-based models only):

```yaml
  feature_importance:
    enabled_for_models:
      - "xgboost"
      - "lightgbm"
    importance_threshold: 0.01   # Flag features contributing < 1%
    flagging_window: 3           # Must be low for 3 consecutive cycles
    auto_removal: false          # Never auto-drop features; human review required
```

**Adaptive ensemble weights:**

```yaml
  adaptive_weights:
    min_sample_size: 300         # Per-model minimum before adjusting weights
    evaluation_window: 300       # Look-back window in resolved predictions
    max_weight_change: 0.10      # Max +/-10 pp per recalculation cycle
    weight_floor: 0.10           # No model drops below 10% weight
    weight_ceiling: 0.60         # No model exceeds 60% weight
    weight_method: "inverse_brier"  # Weight proportional to 1 / Brier score
```

**Retrain triggers** (detects when the model needs retraining):

```yaml
  retrain:
    rolling_window: 100          # Monitor last 100 predictions
    degradation_threshold: 0.15  # Retrain if Brier score degrades 15% vs all-time
    cooldown_period_days: 30     # No auto-retrain within 30 days of last retrain
    auto_rollback: true          # Roll back if new model is worse
```

**Market feedback** (tracks which league x market combinations are profitable):

```yaml
  market_feedback:
    min_sample_size: 50          # Need 50+ resolved bets before assessing
    profitable_min_bets: 100     # Need 100+ bets for "profitable" classification
    confidence_interval: 0.95    # 95% CI for ROI estimates
    assessment_frequency: "weekly"
    assessment_day: "sunday"
    assessment_time: "20:00"     # UTC
```

#### Scraping / Rate Limiting

```yaml
scraping:
  min_request_interval_seconds: 2    # Min 2 seconds between requests to same domain
  api_football:
    daily_request_limit: 100         # Free-tier RapidAPI cap
  request_timeout_seconds: 30
  max_retries: 3
```

Football-Data.co.uk and FBref are free public resources. The 2-second interval
prevents overloading them. API-Football's free tier allows 100 requests per day
-- the system tracks and respects this limit.

#### Pipeline Scheduling

```yaml
scheduling:
  morning:
    time: "06:00"
    operations:
      - "scrape_fixtures"
      - "scrape_odds"
      - "compute_features"
      - "generate_predictions"
      - "detect_value"
      - "send_morning_email"
  evening:
    time: "22:00"
    operations:
      - "scrape_results"
      - "resolve_bets"
      - "update_bankroll"
      - "send_evening_email"
  weekly:
    day: "sunday"
    time: "20:00"
    operations:
      - "market_feedback"
      - "recalibrate"
      - "send_weekly_email"
```

### `config/leagues.yaml`

Defines which leagues are tracked, their data-source identifiers, and which
seasons to ingest. See [Adding New Leagues](#adding-new-leagues) for details.

Set `is_active: false` to disable a league without removing its configuration.

---

## Database Backup and Maintenance

### Automatic Weekly Backups

The evening GitHub Actions workflow runs a database backup every Sunday. The
backup script (`scripts/backup_db.sh`):

1. Uses SQLite's `.backup` command for a safe, WAL-aware copy (falls back to
   `cp` if `sqlite3` is not available)
2. Saves to `data/backups/betvector_YYYY-MM-DD_HHMMSS.db`
3. Keeps the last 10 backups and removes older ones automatically
4. Commits the backup to the repository

### Manual Backup

Run the backup script at any time:

```bash
./scripts/backup_db.sh
```

The backup is saved to `data/backups/` by default.

To use a custom backup directory:

```bash
./scripts/backup_db.sh /path/to/custom/backup/directory
```

### Restoring from Backup

To restore a backup, copy it over the current database:

```bash
cp data/backups/betvector_2025-03-15_220000.db data/betvector.db
```

Make sure no other process is accessing the database when you replace it
(stop any running pipeline or dashboard first).

### Database Location

The SQLite database lives at `data/betvector.db` by default (configured in
`config/settings.yaml`). It is excluded from version control via `.gitignore`
during development, but the GitHub Actions workflows commit it after each
pipeline run so the next run has the latest state.

---

## Deploying to Streamlit Cloud

### Step 1: Create Secrets Configuration

The project includes an example secrets file at
`.streamlit/secrets.toml.example`. On Streamlit Cloud, you configure secrets
through the web dashboard rather than a local file.

### Step 2: Set Up a PostgreSQL Database

Streamlit Cloud's filesystem is ephemeral -- SQLite files are deleted on each
deployment. You need a persistent PostgreSQL database:

1. Create a free project at https://supabase.com (or any PostgreSQL provider)
2. Copy the PostgreSQL connection string from your provider's dashboard
3. The format is: `postgresql://user:password@host:5432/dbname`

### Step 3: Deploy

1. Go to https://share.streamlit.io
2. Click "New app"
3. Select your GitHub repo, branch `main`, and set the main file path to
   `src/delivery/dashboard.py`
4. Click "Deploy"

### Step 4: Configure Secrets in Streamlit Cloud

1. Once deployed, go to your app's Settings in the Streamlit Cloud dashboard
2. Click "Secrets"
3. Enter your secrets in TOML format:

```toml
DASHBOARD_PASSWORD = "your-dashboard-password"
GMAIL_APP_PASSWORD = "xxxx-xxxx-xxxx-xxxx"
API_FOOTBALL_KEY = "your-api-football-key"

[database]
connection_string = "postgresql://user:password@host:5432/dbname"
```

4. Save and reboot the app

The dashboard code automatically checks `st.secrets` when environment variables
are not set, so no code changes are needed for cloud deployment.

---

## Troubleshooting

### FBref Blocked (403 Forbidden)

**Symptom:** The FBref scraper logs a 403 error.

**Cause:** Cloudflare protection blocks automated requests to FBref.

**Impact:** xG, shots, and possession features will be `None`. The model
continues to work using goals-based and form-based features. Predictions are
still generated, just without xG data.

**Fix:** No action needed. The system handles this gracefully and logs a
warning. FBref blocks are often temporary and may resolve on their own.

### No Value Bets Found

**Symptom:** The morning pipeline runs successfully but finds zero value bets.

**Possible causes and fixes:**

| Cause | Fix |
|-------|-----|
| Edge threshold too high | Lower `value_betting.edge_threshold` in `config/settings.yaml` from 0.05 to 0.03 |
| No matches today | Check if there are actually fixtures scheduled for today |
| Odds data missing | Run with `--verbose` to check if odds scraping succeeded |
| Model and bookmakers agree | No action needed -- sometimes there is genuinely no value |

### Pipeline Fails

**Symptom:** `python run_pipeline.py morning` exits with a non-zero code.

**Debugging steps:**

1. Run with `--verbose` to get full debug output
2. Check for network issues (internet connectivity)
3. Check for rate limiting (API-Football: 100 requests/day on free tier)
4. Check that the database exists (`python run_pipeline.py setup`)
5. Check `data/betvector.db` is not locked by another process

Remember that pipeline steps are independent -- a failure in one step (e.g.,
odds scraping) does not prevent other steps from running.

### Database Locked

**Symptom:** `sqlite3.OperationalError: database is locked`

**Cause:** Multiple processes trying to write to the database simultaneously.

**Fix:** WAL mode is enabled by default and handles most concurrent access
scenarios. If you still see this error:

1. Make sure only one pipeline process is running at a time
2. Close any SQLite browser tools (DB Browser for SQLite, etc.) that might
   have a write lock
3. The GitHub Actions workflows use concurrency groups to prevent overlapping
   runs

### Email Not Sending

**Symptom:** Pipeline completes but no email arrives.

**Checklist:**

1. Verify `GMAIL_APP_PASSWORD` is set in `.env` -- this must be a Gmail App
   Password, not your regular Gmail password
2. Ensure 2-factor authentication is enabled on your Google account
3. Generate a new App Password at https://myaccount.google.com/apppasswords
4. Check your spam/junk folder
5. Run with `--verbose` to see SMTP connection details in the logs

### Backtest Shows Poor ROI

**Symptom:** Walk-forward backtest returns negative ROI.

**Context:** This is expected for the baseline Poisson model, especially
without xG features. The EPL 2024-25 baseline is approximately -4% ROI.

**What to expect going forward:**

- The Poisson v1 model is a starting point, not the final product
- Adding xG features (when FBref data is available) improves accuracy
- Adding more seasons of historical training data improves the model
- The self-improvement engine (recalibration, retrain triggers) tunes the
  model over time as it accumulates resolved predictions
- Adding more leagues provides more training data across football in general
- Positive ROI comes from the combination of model improvements, feature
  additions, and disciplined bankroll management

### Dashboard Shows "Database connection failed"

**Symptom:** The dashboard displays an error about database connection.

**Fix for local development:** Run `python run_pipeline.py setup` to create
the database.

**Fix for Streamlit Cloud:** Configure a PostgreSQL connection string in
Settings > Secrets under `[database]`.

---

## Daily Workflow (Recommended)

### Morning (After 06:00 UTC)

1. Open the dashboard and go to **Today's Picks**
2. Review the pick cards -- focus on high-confidence picks with edges above 8%
3. Cross-reference with your own knowledge (injuries, team news, motivation)
4. Place bets with your bookmaker for the picks you agree with
5. Log each bet on the dashboard so the system tracks your actual performance

### Midday (After 13:00 UTC)

1. Check the dashboard for updated edges -- odds may have moved since morning
2. Look for new value bets that appeared after line movement
3. Check if any of your morning picks now have significantly different edges
4. Place additional bets if new value has appeared

### Evening (After 22:00 UTC)

1. Open **Performance Tracker** to review today's results
2. Check the P&L chart for your cumulative trajectory
3. Open **Bankroll Manager** to monitor drawdown and safety limits
4. Review any safety alerts (daily loss limit, drawdown threshold)

### Weekly (Sundays)

1. Open **Model Health** and check the calibration curve:
   - Hugging the diagonal? The model is well-calibrated.
   - Bowing above the diagonal? The model is underconfident (could stake more).
   - Bowing below the diagonal? The model is overconfident (edges may be
     overstated).
2. Check the rolling Brier score -- is it stable or trending upward?
3. Open **Performance Tracker** and review ROI by market type:
   - Which markets are profitable? (1X2? Over/Under? BTTS?)
   - Consider raising the edge threshold for unprofitable markets.
4. Review the weekly email summary for a consolidated view.
5. Open **League Explorer** and compare performance across leagues.
6. The database backup runs automatically on Sunday evening -- no action
   needed.

---

## Key Concepts Glossary

| Term | Definition |
|------|------------|
| **Edge** | The difference between the model's probability and the bookmaker's implied probability. A 7% edge means the model thinks the outcome is 7 percentage points more likely than the odds suggest. |
| **Implied Probability** | The probability of an outcome as implied by the bookmaker's odds. Calculated as 1 / decimal odds. |
| **Value Bet** | A bet where the model's estimated probability exceeds the bookmaker's implied probability by more than the configured edge threshold. |
| **Brier Score** | A scoring rule that measures prediction accuracy. Ranges from 0 (perfect) to 1 (worst). For binary outcomes, 0.25 is random chance. |
| **Scoreline Matrix** | A 7x7 grid of probabilities for every possible match score (0-0 through 6-6). All market probabilities are derived from this matrix. |
| **Walk-Forward Validation** | A backtesting method where the model is trained only on data available before each prediction date, simulating live operation. |
| **Temporal Integrity** | The principle that no feature, prediction, or training step ever uses data from the future. This is the system's most important constraint. |
| **Poisson Regression** | A statistical model that predicts the number of goals each team will score, assuming goals follow a Poisson distribution (a probability distribution for count data). |
| **Kelly Criterion** | A staking formula that sizes bets proportional to the edge. Mathematically optimal for long-term bankroll growth, but volatile in practice. |
| **Quarter-Kelly** | Staking 25% of what full Kelly suggests. Reduces variance significantly while retaining most of the growth benefit. |
| **Paper Trading** | Running the system with simulated bets -- no real money at risk. Useful for validating the model before going live. |
| **Drawdown** | The decline from a peak bankroll value to a subsequent trough. A 25% drawdown means the bankroll dropped 25% from its highest point. |
| **Recalibration** | Adjusting model probabilities (via Platt scaling or isotonic regression) so they better match actual outcome frequencies. |
| **1X2** | The match result market: 1 = home win, X = draw, 2 = away win. |
| **OU25** | Over/Under 2.5 goals. "Over" means 3 or more total goals in the match. |
| **BTTS** | Both Teams To Score. "Yes" means both teams score at least one goal. |
| **ROI** | Return on Investment. Calculated as (total returns - total staked) / total staked, expressed as a percentage. |
| **System Pick** | A value bet that the model automatically logged. Every value bet is logged as a system pick regardless of whether you actually place the bet. |
| **User-Placed Bet** | A bet you manually recorded after placing it with a bookmaker. Tracked separately so you can compare your actual results against the model's full recommendations. |
| **WAL Mode** | Write-Ahead Logging -- an SQLite journaling mode that allows concurrent reads while writing, preventing most database lock issues. |
| **xG (Expected Goals)** | A metric that measures the quality of chances created, based on historical shot data. An xG of 1.5 means the chances created were equivalent to scoring 1.5 goals on average. |
