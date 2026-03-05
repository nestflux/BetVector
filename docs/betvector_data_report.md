# BetVector — Data Sources & Pipeline Report

**Version:** 1.0 · March 2026
**Scope:** All data entering the system, how it flows, and its role in the prediction model.

---

## Overview

BetVector ingests data from **8 external sources** through automated daily pipelines. That raw data is cleaned, stored in a structured SQLite database, transformed into **~50 engineered features**, and fed into a Poisson regression model that outputs a 7×7 scoreline probability matrix. All market probabilities (1X2, Over/Under, BTTS) are derived from that matrix. A value bet detector then compares model probabilities against bookmaker odds to identify edges.

The entire flow is:

```
External Sources → Scrapers → Database → Feature Engineering → Model → Predictions → Value Bets
```

---

## 1. Data Sources

### 1.1 Football-Data.co.uk
**Type:** CSV download
**What it provides:** Historical match results and bookmaker opening odds
**Coverage:** EPL 2020-21 through 2025-26
**When it runs:** Morning pipeline, at season start and periodic backfill
**Lag:** Results appear 2–4 days after each match

**Data collected:**
- Full-time and half-time scores
- Referee name
- Opening odds from Bet365, Pinnacle, William Hill, and market average
- Over/Under 2.5 market average odds
- Asian Handicap line

**Writes to:** `matches` table (results), `odds` table (bookmaker odds)

---

### 1.2 Football-Data.org API
**Type:** JSON REST API (authenticated)
**What it provides:** Near real-time match results
**Why it exists:** Solves the 2–4 day lag on the CSV source above
**When it runs:** Evening pipeline (results available minutes to hours after final whistle)

**Data collected:**
- Match date, kickoff time (with timezone)
- Home/away team names
- Full-time and half-time scores
- Match status (scheduled, finished, postponed)

**Writes to:** `matches` table (updates existing records with results)

---

### 1.3 Understat
**Type:** Python library (no API key required)
**What it provides:** Advanced match statistics — the richest data source in the system
**Coverage:** EPL from 2014-15 onward
**When it runs:** Morning pipeline

**Data collected (per match, per team):**
- **xG** — Expected Goals: how many goals a team *should* have scored based on shot quality
- **NPxG** — Non-Penalty xG: removes the random noise of penalty kicks (~76% conversion)
- **xGA** — Expected Goals Against: how many goals the opponent should have scored
- **NPxGA** — Non-Penalty xGA
- **PPDA** — Passes Per Defensive Action: measures pressing intensity (low PPDA = high press)
- **Deep completions** — Passes completed into the opponent's penalty area (attacking threat proxy)
- **Set-piece xG** — xG from set pieces (corners, free kicks) specifically
- **Open-play xG** — xG from open play specifically

**Why NPxG over xG?** Penalties are luck-dependent and distort a team's true attacking quality. NPxG is a cleaner signal.
**Why PPDA?** A team that presses hard creates turnovers in dangerous positions. PPDA < 8.0 signals high-intensity pressing.

**Writes to:** `match_stats` table

---

### 1.4 The Odds API
**Type:** JSON REST API (authenticated, free tier: 500 requests/month)
**What it provides:** Live odds from 50+ bookmakers across UK, US, and EU markets
**When it runs:** Morning and midday pipelines
**Budget:** ~90 requests/month at 3 runs/day — well within the free 500 limit

**Data collected (per bookmaker × market × selection):**
- Bookmaker name (Pinnacle, FanDuel, Bet365, DraftKings, etc.)
- Market type: 1X2 (match result), Over/Under 2.5, Over/Under 1.5, Over/Under 3.5
- Selection: home win / draw / away win / over / under
- Decimal odds

**Writes to:** `odds` table
**Key use:** Pinnacle odds (the market's sharpest bookmaker) are used as model features — the market's own probability estimate is valuable input data.

---

### 1.5 API-Football
**Type:** JSON REST API (authenticated, free tier: 100 requests/day)
**What it provides:** Real-time fixtures, odds, injury reports, and team logos
**When it runs:** Morning pipeline
**Budget:** ~20 requests/day across 3 pipeline runs

**Data collected:**
- Scheduled fixtures (dates, kickoff times)
- Live and final match scores
- Bookmaker odds (backup to The Odds API)
- Player injury and suspension reports
- Team logo images (cached locally as PNG files)

**Writes to:** `matches`, `odds`, `injury_flags` tables; badge images to `data/badges/`

---

### 1.6 ClubElo
**Type:** CSV via HTTP (free, no authentication)
**What it provides:** Elo ratings for every European club, updated daily
**When it runs:** Morning pipeline
**Why Elo?** Elo ratings encode long-term team strength in a single number, updated after every result. Particularly useful early in a season (small rolling sample) and for newly promoted teams.

**Data collected (per team per date):**
- Elo rating (typically 1300–2000 for EPL clubs)
- World rank
- League tier level

**Writes to:** `club_elo` table
**Coverage:** 17,965 rating records across all match dates in the database

---

### 1.7 Transfermarkt (via Public Dataset)
**Type:** Compressed CSV download (public CDN, CC0 licensed)
**What it provides:** Squad market values for every EPL team
**When it runs:** Morning pipeline (weekly dataset updates)
**Why squad value?** A team's total market value is a reliable long-term quality proxy — squads worth more generally outperform squads worth less over a season.

**Data collected (aggregated per team):**
- Total squad market value (EUR)
- Average player market value (EUR)
- Squad size (number of valued players)
- Number of players with contracts expiring within 6 months (instability signal)

**Writes to:** `team_market_values` table

---

### 1.8 Open-Meteo
**Type:** JSON REST API (free, no authentication)
**What it provides:** Weather conditions at each stadium at kickoff time
**Coverage:** Forecasts up to 16 days; historical archive back to 1940
**When it runs:** Morning pipeline; stadium coordinates from `config/stadiums.yaml`

**Data collected:**
- Temperature (°C)
- Wind speed (km/h)
- Humidity (%)
- Precipitation (mm)
- Weather category: clear / cloudy / drizzle / rain / heavy rain / snow / fog / storm

**Writes to:** `weather` table
**Impact on model:** Heavy rain and strong wind (>30 km/h) correlate with fewer goals and reduced passing quality. Both factors feed into the model as numeric features.

---

### 1.9 Manual Injury Flags
**Type:** Dashboard form entry (owner-entered)
**What it provides:** Key player absences for upcoming matches
**When entered:** As needed, before prediction runs
**Fields:** Player name, team, impact rating (0.0–1.0 scale)

**Writes to:** `injury_flags` table
**Impact on model:** Aggregated into an `injury_impact` feature and a binary `key_player_out` flag

---

## 2. Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        EXTERNAL SOURCES                         │
│                                                                 │
│  Football-Data.co.uk   Football-Data.org   Understat           │
│  The Odds API          API-Football        ClubElo             │
│  Transfermarkt         Open-Meteo          Manual Flags        │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Scrapers (requests + BeautifulSoup)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         DATABASE (SQLite)                       │
│                                                                 │
│  matches      match_stats    odds          weather              │
│  club_elo     team_market_values           injury_flags         │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Feature Engineering
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         FEATURES TABLE                          │
│                                                                 │
│  ~50 engineered columns per team per match                      │
│  Rolling form, xG, NPxG, PPDA, H2H, Elo, market odds, etc.     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Poisson Regression Model
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       PREDICTIONS TABLE                         │
│                                                                 │
│  7×7 scoreline matrix → market probabilities                    │
│  (1X2, OU 1.5/2.5/3.5, BTTS, Asian Handicap)                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Value Bet Detection
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       VALUE BETS TABLE                          │
│                                                                 │
│  Model probability vs bookmaker implied probability             │
│  Edge ≥ 5% flagged; confidence: low / medium / high            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Feature Engineering

Features are computed for each team in each match. Two windows are used for rolling statistics: **last 5 matches** and **last 10 matches**. The 5-match window captures recent form; the 10-match window captures medium-term consistency.

**Temporal integrity is the #1 constraint:** Every feature uses only data from before the match date. No future data ever leaks into training or prediction.

### Form & Goals (Rolling)
| Feature | What it measures | Source |
|---------|-----------------|--------|
| `form_5`, `form_10` | Points per game (W=3, D=1, L=0) over last 5/10 | match results |
| `goals_scored_5`, `goals_scored_10` | Goals scored per game | match results |
| `goals_conceded_5`, `goals_conceded_10` | Goals conceded per game | match results |
| `form_home_5`, `form_away_5` | Form specifically at home / away | match results |
| `goals_scored_home_5` | Goals scored in last 5 home games specifically | match results |

### Advanced Stats (Rolling)
| Feature | What it measures | Source |
|---------|-----------------|--------|
| `xg_5`, `xg_10` | Expected goals per game | Understat |
| `xga_5`, `xga_10` | Expected goals against per game | Understat |
| `xg_diff_5`, `xg_diff_10` | xG − xGA (net expected goal difference) | Understat |
| `npxg_5`, `npxg_10` | Non-penalty expected goals per game | Understat |
| `npxga_5`, `npxga_10` | Non-penalty expected goals against | Understat |
| `ppda_5`, `ppda_10` | Passes per defensive action (pressing) | Understat |
| `deep_5`, `deep_10` | Deep completions per game (attacking threat) | Understat |
| `shots_5`, `shots_10` | Shots per game | Understat |

### Head-to-Head History
| Feature | What it measures | Source |
|---------|-----------------|--------|
| `h2h_wins` | Wins in last 5 head-to-head meetings | match results |
| `h2h_draws` | Draws in last 5 head-to-head | match results |
| `h2h_losses` | Losses in last 5 head-to-head | match results |
| `h2h_goals_scored` | Avg goals scored in last 5 H2H | match results |
| `h2h_goals_conceded` | Avg goals conceded in last 5 H2H | match results |

### Context & Scheduling
| Feature | What it measures | Source |
|---------|-----------------|--------|
| `rest_days` | Days since team's last match | match results |
| `season_progress` | How far through the season (0.0–1.0) | match results |
| `short_rest` | Binary flag: 1 if fewer than 4 days rest | match results |

### Team Strength
| Feature | What it measures | Source |
|---------|-----------------|--------|
| `elo_rating` | ClubElo rating on match date | ClubElo |
| `elo_diff` | Team Elo minus opponent Elo | ClubElo |
| `squad_value_ratio` | Team squad value ÷ opponent squad value | Transfermarkt |
| `avg_player_value_ratio` | Avg player value ratio vs opponent | Transfermarkt |

### Market Intelligence
| Feature | What it measures | Source |
|---------|-----------------|--------|
| `home_prob` | Pinnacle implied probability for home win | The Odds API |
| `draw_prob` | Pinnacle implied probability for draw | The Odds API |
| `away_prob` | Pinnacle implied probability for away win | The Odds API |
| `ah_line` | Asian Handicap line (e.g. −0.5, −1.0) | Football-Data.co.uk |

> **Why use market odds as features?** Pinnacle is the world's sharpest bookmaker — their lines reflect a massive aggregation of information. Treating Pinnacle's odds as a feature lets the model incorporate market wisdom without fully deferring to it.

### Match Conditions
| Feature | What it measures | Source |
|---------|-----------------|--------|
| `temperature_c` | Temperature at kickoff (°C) | Open-Meteo |
| `wind_speed_kmh` | Wind speed at kickoff | Open-Meteo |
| `humidity_pct` | Humidity at kickoff (%) | Open-Meteo |
| `precipitation_mm` | Precipitation at kickoff | Open-Meteo |
| `weather_code` | WMO numeric weather code | Open-Meteo |
| `weather_category` | Human-readable category (rain, snow, etc.) | Open-Meteo |

### Referee
| Feature | What it measures | Source |
|---------|-----------------|--------|
| `ref_avg_goals` | Avg total goals in this referee's matches | match results |
| `ref_avg_fouls` | Avg fouls per match | match results |
| `ref_avg_yellows` | Avg yellow cards per match | match results |

### Injury
| Feature | What it measures | Source |
|---------|-----------------|--------|
| `injury_impact` | Sum of impact ratings for absent players | Manual flags |
| `key_player_out` | Binary: 1 if any absence rated ≥ 0.7 | Manual flags |

---

## 4. Model Architecture

### 4.1 Two Poisson Regression Models

The prediction engine uses **two separate Poisson Generalized Linear Models** — one for home goals, one for away goals. Poisson regression is the standard statistical approach for modelling goal counts, because goals are rare, discrete, and count-based (exactly the properties Poisson distributions describe).

**Why two separate models?** Home and away goals are influenced by different factors. A home team's attack is matched against an away team's defence — these relationships are best modelled separately.

**Home goals model** — trained on:
- Home team's attack features (form, xG, NPxG, shots)
- Away team's defensive features (xGA, NPxGA, PPDA)
- Context (rest days, Elo, market odds, weather)

**Away goals model** — trained on:
- Away team's attack features
- Home team's defensive features
- Same context features

### 4.2 Feature Columns Passed to the Model

From the ~50 engineered features, the model selects only those available in the training DataFrame:

```
form_5             form_10
goals_scored_5     goals_scored_10
xg_5               xg_10
npxg_5             npxg_10
ppda_5             ppda_10
deep_5             deep_10
h2h_goals_scored   h2h_goals_conceded
rest_days          season_progress
squad_value_ratio
home_prob          away_prob          ah_line
elo_rating         elo_diff
ref_avg_goals
short_rest         injury_impact
```

**Total: ~25 features per model** (exact number depends on data availability for a given match)

Features not in this list (e.g. `weather_category`, `humidity_pct`) are stored in the features table but currently not passed to the Poisson model — they are available for future model iterations.

### 4.3 Training

- **Training data:** All completed EPL matches from 2020-21 through the most recent completed season (~2,280 matches)
- **Minimum training set:** 20 matches required before the model will produce a prediction
- **Missing values:** Filled with column mean, then 0.0 for any remaining NaN
- **No data leakage:** Only matches completed before the target match date are included

### 4.4 The 7×7 Scoreline Matrix

The two models output **lambda_home** and **lambda_away** — the expected number of goals for each team. From these, the probability of every exact scoreline (0–0 through 6–6) is computed using the Poisson probability formula:

```
P(home scores H goals) × P(away scores A goals) = matrix[H][A]
```

This gives a 49-cell matrix where each cell is the probability of that exact scoreline. The matrix is renormalised to sum to 1.0.

```
Example matrix (Arsenal vs Brighton, model output):
         Away: 0    1    2    3    4    5    6
Home: 0  [0.04  0.07  0.06  0.03  0.01  ...  ]
      1  [0.09  0.14  0.11  0.06  0.02  ...  ]
      2  [0.09  0.14  0.11  0.06  0.02  ...  ]
      3  [0.06  0.09  0.07  0.04  0.01  ...  ]
      4  [0.03  0.05  0.04  0.02  ...        ]
      5  [0.01  0.02  ...                    ]
      6  [0.00  ...                          ]
```

### 4.5 Market Probability Derivation

All betting market probabilities come from summing cells of the scoreline matrix:

| Market | Probability | Cells summed |
|--------|------------|-------------|
| Home win | prob_home_win | All cells where H > A |
| Draw | prob_draw | All cells where H = A |
| Away win | prob_away_win | All cells where H < A |
| Over 1.5 | prob_over_15 | All cells where H + A ≥ 2 |
| Under 1.5 | prob_under_15 | All cells where H + A ≤ 1 |
| Over 2.5 | prob_over_25 | All cells where H + A ≥ 3 |
| Under 2.5 | prob_under_25 | All cells where H + A ≤ 2 |
| Over 3.5 | prob_over_35 | All cells where H + A ≥ 4 |
| Under 3.5 | prob_under_35 | All cells where H + A ≤ 3 |
| BTTS Yes | prob_btts_yes | All cells where H ≥ 1 AND A ≥ 1 |
| BTTS No | prob_btts_no | All cells where H = 0 OR A = 0 |

---

## 5. Value Bet Detection

Once the model produces probabilities, they are compared against bookmaker odds for the same markets.

**The edge formula:**
```
Edge = Model probability − Bookmaker implied probability
     = Model probability − (1 ÷ Decimal odds)
```

**A positive edge means the model believes the true probability is higher than what the bookmaker's odds imply** — the bookmaker is underpricing this outcome, making it a value bet.

**Confidence tiers:**
| Tier | Edge threshold |
|------|---------------|
| High | ≥ 10% |
| Medium | 5–10% |
| Low | < 5% (flagged but not recommended) |

All value bets are automatically logged as `system_pick` entries in the bet log, independently of whether the user places the bet. This allows model performance to be tracked without human decision bias.

---

## 6. Pipeline Schedule

| Run | Time (UTC) | Key operations |
|-----|-----------|---------------|
| **Morning** | 06:00 | Scrape all sources → compute features → generate predictions → detect value bets → send email picks |
| **Midday** | 13:00 | Re-fetch odds → recalculate edges for today's matches |
| **Evening** | 22:00 | Fetch results → resolve bets → update bankroll → send results email |

---

## 7. Current Performance

| Metric | Value | Benchmark |
|--------|-------|-----------|
| Model | Market-Augmented Poisson | — |
| Brier Score | 0.5781 | Random = 0.667, Perfect = 0 |
| Backtest ROI | +2.78% | Breakeven = 0% |
| Training seasons | 5 (2020-25) | — |
| Test season | 2024-25 | — |
| Total matches in DB | 2,280+ | — |
| Total odds records | 34,076+ | — |
| Feature rows | 4,560 | — |

The model is profitable in backtest. The Brier score of 0.5781 indicates meaningful predictive accuracy above the baseline of a model that simply predicts uniform 33/33/33 probabilities for all matches (Brier ≈ 0.667).

---

## 8. Data Quality & Reliability

**Deduplication:** Every loader is idempotent — running a scraper twice produces zero duplicate records. Each table has a unique constraint on its natural key (e.g. match date + teams).

**Team name mapping:** All 8 sources use different team name conventions. Each scraper has an explicit name mapping dictionary (e.g. "Man City" → "Manchester City", "Brighton & Hove Albion" → "Brighton") to ensure consistent identity across sources.

**Rate limiting:** All scrapers enforce minimum delays between requests to the same domain (2–6 seconds). API-Football and The Odds API have daily/monthly budget limits tracked and enforced by the scraper.

**Pipeline resilience:** If any single scraper fails (e.g. Understat is temporarily unavailable), the error is logged and the pipeline continues with the remaining sources. Predictions are still generated using whatever data is available.

**Temporal integrity:** Every database query that reads features or results for model training explicitly filters on `date < match_date`. Future data physically cannot enter the training set.

---

## 9. Data Source Summary

| Source | Auth | Update lag | Primary use | DB table |
|--------|------|-----------|-------------|---------|
| Football-Data.co.uk | None | 2–4 days | Historical results + opening odds | matches, odds |
| Football-Data.org API | API key | Minutes | Real-time results | matches |
| Understat | None | Daily | xG, NPxG, PPDA, deep completions | match_stats |
| The Odds API | API key | Real-time | Live odds, 50+ bookmakers | odds |
| API-Football | API key | Real-time | Fixtures, injuries, logos | matches, odds, injury_flags |
| ClubElo | None | Daily | Long-term team strength (Elo) | club_elo |
| Transfermarkt | None | Weekly | Squad market value | team_market_values |
| Open-Meteo | None | Real-time | Weather at kickoff | weather |
| Manual flags | Dashboard | As needed | Key player absences | injury_flags |

---

*Report generated from live codebase · BetVector v1.3 · March 2026*
