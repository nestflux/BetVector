# BetVector

Quantitative edge detection system for football betting. Combines Poisson regression modelling, walk-forward backtesting, and automated bankroll management to identify value bets across bookmaker markets.

**Status:** All 45 issues complete (13 epics)

## Documentation

Full project documentation is hosted on Surge:

**[betvector.surge.sh](https://betvector.surge.sh)**

| Document | Description |
|----------|-------------|
| [Pitch Deck](https://betvector.surge.sh/betvector_pitch.html) | Investor/stakeholder presentation |
| [Prototype](https://betvector.surge.sh/betvector_prototype.html) | Interactive dashboard prototype |
| [Two-Pager](https://betvector.surge.sh/betvector_twopager.html) | Executive summary |
| [Master Plan](https://betvector.surge.sh/betvector_masterplan.html) | Product vision, architecture, database schema |
| [Build Plan](https://betvector.surge.sh/betvector_buildplan.html) | 13 epics, 45 issues - sequenced implementation roadmap |
| [How-To Manual](https://betvector.surge.sh/betvector_howto.html) | Setup, daily usage, dashboard guide, configuration reference |
| [How It Works](https://betvector.surge.sh/betvector_howitworks.html) | Learn the maths, models, and betting concepts behind BetVector |

## Quick Start

```bash
# Install dependencies
make install

# Initialise database and seed reference data
python run_pipeline.py setup

# Run the full morning pipeline
python run_pipeline.py morning

# Run a walk-forward backtest
python run_pipeline.py backtest --league EPL --season 2024-25

# See all commands
python run_pipeline.py --help
```

## Project Structure

```
BetVector/
├── config/                     # YAML configuration files
│   ├── settings.yaml           #   System settings (thresholds, safety limits, scheduling)
│   ├── leagues.yaml            #   League definitions and data source IDs
│   └── email_config.yaml       #   Email delivery settings
├── src/
│   ├── scrapers/               # Data acquisition
│   │   ├── base_scraper.py     #   ABC + rate limiter
│   │   ├── football_data.py    #   Football-Data.co.uk scraper (results + odds)
│   │   ├── fbref_scraper.py    #   FBref scraper (xG, possession, shots)
│   │   └── loader.py           #   Database loader (matches, odds, stats)
│   ├── database/               # SQLAlchemy ORM layer
│   │   ├── db.py               #   Engine, session, init_db
│   │   ├── models.py           #   18 ORM models
│   │   └── seed.py             #   Idempotent seeder (leagues, seasons, owner)
│   ├── features/               # Feature engineering
│   │   ├── rolling.py          #   Rolling averages (form, goals, xG)
│   │   ├── context.py          #   H2H, rest days, matchday, season progress
│   │   └── engineer.py         #   Orchestrator (compute_all_features)
│   ├── models/                 # Prediction models
│   │   ├── base_model.py       #   ABC + MatchPrediction dataclass
│   │   ├── poisson.py          #   Poisson regression (statsmodels GLM)
│   │   └── storage.py          #   Prediction save/load with scoreline matrix
│   ├── betting/                # Value detection and bankroll
│   │   ├── value_finder.py     #   Edge calculation across all markets
│   │   ├── bankroll.py         #   Staking (flat/percentage/Kelly) + safety limits
│   │   └── tracker.py          #   Bet logging and resolution
│   ├── evaluation/             # Performance measurement
│   │   ├── metrics.py          #   ROI, Brier score, calibration, CLV
│   │   ├── backtester.py       #   Walk-forward backtest engine
│   │   └── reporter.py         #   Console, JSON, and PNG report generation
│   ├── delivery/               # Email and notifications (E11)
│   ├── self_improvement/       # Recalibration and retraining (E12)
│   ├── config.py               # Config singleton with dot-notation access
│   └── pipeline.py             # Pipeline orchestrator (morning/midday/evening)
├── data/
│   ├── raw/                    # Scraped CSVs (gitignored)
│   ├── processed/              # Intermediate data
│   ├── predictions/            # Backtest reports and charts
│   └── models/                 # Serialised model files
├── templates/                  # Jinja2 email templates (E11)
├── tests/                      # pytest test suite
├── notebooks/                  # Jupyter analysis notebooks
├── run_pipeline.py             # CLI entry point
├── index.html                  # Surge landing page
├── generate_html_docs.py       # Markdown-to-HTML converter for docs
├── betvector_masterplan.md     # Master plan (source)
├── betvector_buildplan.md      # Build plan (source)
├── betvector_masterplan.html   # Master plan (generated HTML for Surge)
├── betvector_buildplan.html    # Build plan (generated HTML for Surge)
├── betvector_pitch.html        # Pitch deck
├── betvector_prototype.html    # Dashboard prototype
├── betvector_twopager.html     # Executive summary
├── CLAUDE.md                   # Claude Code session rules
├── Makefile                    # make install, make test, make run
├── requirements.txt            # Pinned Python dependencies
└── pyproject.toml              # Editable install config
```

## Tech Stack

- **Language:** Python 3.10+
- **Database:** SQLAlchemy 2.0+ with SQLite (WAL mode)
- **Data:** pandas, numpy
- **Stats/ML:** scipy, statsmodels (Poisson GLM), scikit-learn
- **Scraping:** requests + BeautifulSoup, soccerdata (FBref)
- **Dashboard:** Streamlit 1.28+ (in progress)
- **Charts:** Plotly (dashboard), matplotlib (static exports)
- **Config:** PyYAML, all tuneable values in `config/*.yaml`

## Pipeline

BetVector runs three daily pipelines:

| Run | Time (UTC) | What it does |
|-----|-----------|--------------|
| Morning | 06:00 | Scrape data, compute features, predict, find value bets |
| Midday | 13:00 | Re-fetch odds, recalculate edges |
| Evening | 22:00 | Scrape results, resolve bets, update P&L, compute metrics |

## Dashboard

Launch the dashboard locally:

```bash
streamlit run src/delivery/dashboard.py
```

### Deploy to Streamlit Cloud

1. **Push to GitHub** — ensure your repo is on GitHub (public or private).

2. **Go to [share.streamlit.io](https://share.streamlit.io)** and sign in with your GitHub account.

3. **Create a new app:**
   - Repository: `your-username/BetVector`
   - Branch: `main`
   - Main file path: `src/delivery/dashboard.py`

4. **Configure secrets** — in the Streamlit Cloud app settings, go to
   **Settings → Secrets** and paste your secrets in TOML format:

   ```toml
   DASHBOARD_PASSWORD = "your-password"
   GMAIL_APP_PASSWORD = "your-gmail-app-password"
   API_FOOTBALL_KEY = "your-api-key"

   # Required for cloud — SQLite is not persistent on Streamlit Cloud.
   # Use a Supabase PostgreSQL free tier (500 MB).
   [database]
   connection_string = "postgresql://user:password@host:5432/dbname"
   ```

   See `.streamlit/secrets.toml.example` for the full template.

5. **Deploy** — Streamlit Cloud will install dependencies from
   `requirements.txt` and launch the app.

**Important:** Streamlit Cloud does not persist files between reboots.
The SQLite database is fine for local development, but for cloud
deployment you need a hosted PostgreSQL database (e.g. Supabase free
tier). Configure the connection string in Streamlit secrets as shown
above — BetVector's database layer will use it automatically.

## Security

BetVector takes credential management seriously. Here is what is
stored where and how to keep it safe.

### Sensitive Files

| File | Contains | Gitignored? |
|------|----------|-------------|
| `.env` | `GMAIL_APP_PASSWORD`, `DASHBOARD_PASSWORD`, `API_FOOTBALL_KEY` | Yes |
| `.streamlit/secrets.toml` | Same secrets (Streamlit Cloud format) | Yes |
| `config/email_config.yaml` | SMTP host/port/from-address (may contain credentials) | Yes |
| `data/betvector.db` | SQLite database with all predictions, bets, and user data | Yes |

### Where Secrets Live

- **Local development:** `.env` file in the project root.
  Copy `.env.example` and fill in your values.
- **Streamlit Cloud:** Settings → Secrets in the Streamlit Cloud
  dashboard. See `.streamlit/secrets.toml.example`.
- **GitHub Actions:** Repository Settings → Secrets and variables →
  Actions. Add `GMAIL_APP_PASSWORD`, `DASHBOARD_PASSWORD`, and
  `API_FOOTBALL_KEY`.

### Rotating Credentials

1. **Gmail App Password:** Generate a new one at
   [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords),
   then update `.env`, Streamlit Cloud secrets, and GitHub Actions
   secrets.
2. **Dashboard Password:** Change in `.env` and Streamlit Cloud
   secrets. No database migration needed.
3. **API-Football Key:** Generate a new one at
   [api-football.com](https://www.api-football.com/), update
   everywhere as above.

### Database Backups

A weekly backup runs automatically every Sunday via GitHub Actions
(after the evening pipeline). You can also run it manually:

```bash
./scripts/backup_db.sh                  # Backs up to data/backups/
./scripts/backup_db.sh /custom/path     # Custom backup directory
```

Backups are timestamped (`betvector_YYYY-MM-DD_HHMMSS.db`) and the
script automatically keeps only the last 10.

## License

Private repository. All rights reserved.
