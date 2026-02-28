# BetVector

Quantitative edge detection system for football betting. Combines Poisson regression modelling, walk-forward backtesting, and automated bankroll management to identify value bets across bookmaker markets.

**Status:** Active development (Epic 8 of 13 complete)

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

## License

Private repository. All rights reserved.
