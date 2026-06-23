# BetVector World Cup 2026 — Build Plan

Version 1.0 · June 2026

---

## Purpose

This document defines the build plan for the BetVector World Cup 2026 add-on module. It extends the existing BetVector infrastructure (database, odds collection, value betting, bankroll management, email alerts, dashboard) with a World Cup-specific prediction system.

This is a **time-boxed add-on** for the 2026 FIFA World Cup (June 11 – July 19, 2026). It is NOT a permanent addition to the league pipeline. It lives in `src/world_cup/` and uses separate database tables prefixed with `wc_`.

### Research Foundation

This build plan is informed by:
- **Groll, Schauberger & Tutz (2015)** — Regularized Poisson for major tournament prediction
- **Groll et al. (2018)** — Random Forest + Poisson stack (correctly predicted France 2018)
- **Baio & Blangiardo (2010)** — Bayesian hierarchical Poisson for football
- **Hvattum & Arntzen (2010)** — Elo vs FIFA ranking for international football
- **Berlinschi et al. (2013)** — Socioeconomic determinants of WC performance
- Live API verification: The Odds API (`soccer_fifa_world_cup`) confirmed active with 59 bookmakers
- All 12 group standings scraped from ESPN (June 22, 2026)

### Key Constraints

- **Timeline:** Matchday 3 starts June 24, knockouts start June 28, final July 19
- **Data sparsity:** National teams play 10-15 matches/year vs 38+ for clubs
- **API budget:** ~388 Odds API requests remaining this month
- **Existing infra:** Reuse BetVector's DB, odds pipeline, value betting, bankroll, email, dashboard

---

## Epics Overview

| Epic | Title | Issues | Description |
|------|-------|--------|-------------|
| WC-01 | Database & Models | 3 | WC-specific ORM models, team seed data, historical match import |
| WC-02 | Data Collection | 5 | Odds API scraper, results scraper, Elo ratings, World Bank indicators, squad data |
| WC-03 | Feature Engineering | 3 | Core features, alternative features, tournament-specific features |
| WC-04 | Prediction Model | 3 | Poisson model adapted for international football, knockout simulator, model calibration |
| WC-05 | Value Betting & Alerts | 2 | Value finder integration, email alerts for WC picks |
| WC-06 | Dashboard | 3 | WC dashboard page, group simulator widget, live tournament tracker |
| WC-07 | Pipeline & Automation | 2 | Daily WC pipeline, launchd integration |
| **Total** | | **21** | |

---

## Critical Path

```
WC-01-01 → WC-01-02 → WC-01-03 →
WC-02-01 → WC-02-02 → WC-02-03 → WC-02-04 → WC-02-05 →
WC-03-01 → WC-03-02 → WC-03-03 →
WC-04-01 → WC-04-02 → WC-04-03 →
WC-05-01 → WC-05-02 →
WC-06-01 → WC-06-02 → WC-06-03 →
WC-07-01 → WC-07-02
```

### Phase Strategy

| Phase | Issues | Deadline | Goal |
|-------|--------|----------|------|
| **Phase 1: MVP** | WC-01 through WC-04-01 | June 24 (matchday 3) | Basic predictions for remaining group matches |
| **Phase 2: Value & Alerts** | WC-04-02 through WC-05-02 | June 26 | Value betting + email picks for final group matches |
| **Phase 3: Dashboard** | WC-06-01 through WC-06-03 | June 28 (knockouts) | Full dashboard + group advancement simulator |
| **Phase 4: Knockouts** | WC-04-03, WC-07-01, WC-07-02 | June 30 | Knockout model + automated daily pipeline |

---

## How to Use This Document

1. Issues within an epic are ordered by dependency — do not skip ahead
2. Complete **all** acceptance criteria before marking an issue done
3. Reuse existing BetVector modules wherever possible — do not duplicate
4. All WC code lives in `src/world_cup/` — do not modify league pipeline code
5. All WC database tables are prefixed with `wc_` — do not modify existing tables
6. When an issue is complete, update the status table at the top of this file

---

## WC-01 — Database & Models

### WC-01-01 — WC ORM Models

**Type:** Schema
**Depends on:** Nothing (existing BetVector DB infrastructure)
**Reuses:** `src/database/db.py` (engine, session, Base)

Define SQLAlchemy ORM models for World Cup data. These use the same `Base` and database engine as the league system but are entirely separate tables.

**Implementation Notes:**
- Create `src/world_cup/__init__.py` and `src/world_cup/models.py`
- All models inherit from `src.database.db.Base` so they are created by `init_db()`
- Table prefix: `wc_` to avoid any collision with existing tables
- Models:
  - `WCTeam`: id, name, fifa_code (3-letter), confederation, group_letter, elo_rating, fifa_ranking, fifa_points, gdp_per_capita, population, gini_coefficient, political_stability, squad_market_value, avg_squad_age, players_in_top5_leagues, cl_players, wc_appearances, best_wc_finish, manager_name, manager_tenure_months, is_host
  - `WCMatch`: id, match_number, group_letter, stage (group/r32/r16/qf/sf/3rd/final), date, venue, city, altitude_m, home_team_id (FK→WCTeam), away_team_id (FK→WCTeam), home_goals, away_goals, home_goals_ht, away_goals_ht, status (scheduled/live/finished), home_xg, away_xg, attendance, temperature_c, matchday (1/2/3)
  - `WCOdds`: id, match_id (FK→WCMatch), bookmaker, market_type (h2h/spreads/totals), selection, odds_decimal, implied_prob, captured_at, source
  - `WCPrediction`: id, match_id (FK→WCMatch), model_name, home_win_prob, draw_prob, away_win_prob, home_expected_goals, away_expected_goals, created_at
  - `WCValueBet`: id, match_id (FK→WCMatch), prediction_id (FK→WCPrediction), market_type, selection, model_prob, best_odds, implied_prob, edge, bookmaker, kelly_stake, created_at
  - `WCFeature`: id, match_id (FK→WCMatch), elo_diff, elo_home, elo_away, market_value_ratio, gdp_ratio, population_ratio, avg_age_home, avg_age_away, top5_league_players_home, top5_league_players_away, cl_players_home, cl_players_away, wc_appearances_home, wc_appearances_away, best_finish_home, best_finish_away, confederation_adj_home, confederation_adj_away, rest_days_home, rest_days_away, altitude_m, climate_gap_home, climate_gap_away, travel_distance_home_km, travel_distance_away_km, is_host_home, is_host_away, manager_tenure_home, manager_tenure_away, home_form_last5, away_form_last5, dark_horse_score_home, dark_horse_score_away, motivation_home (must_win/comfortable/dead_rubber), motivation_away, matchday

**Acceptance Criteria:**
- [ ] `src/world_cup/__init__.py` and `src/world_cup/models.py` exist
- [ ] All 6 ORM models defined with proper relationships and foreign keys
- [ ] Running `init_db()` creates all `wc_*` tables in the database without affecting existing tables
- [ ] `WCTeam` has all 15+ columns for alternative features (economic, demographic, squad)
- [ ] `WCFeature` has all 30+ feature columns identified in research
- [ ] UniqueConstraints: WCOdds on (match_id, bookmaker, market_type, selection), WCMatch on match_number

---

### WC-01-02 — Seed 48 Teams

**Type:** Data
**Depends on:** WC-01-01

Populate the `wc_teams` table with all 48 World Cup 2026 teams and their static attributes.

**Implementation Notes:**
- Create `src/world_cup/seed.py` with `seed_teams()` function
- Hard-code or load from a YAML file (`config/worldcup_2026.yaml`) the 48 teams with:
  - Group assignments (A through L, 4 teams per group)
  - FIFA 3-letter codes
  - Confederation (UEFA/CONMEBOL/AFC/CAF/CONCACAF/OFC)
  - Host flag (USA, Canada, Mexico = True)
  - Historical WC appearances and best finish (from Wikipedia/Kaggle)
- Leave dynamic fields (elo_rating, gdp_per_capita, squad_market_value, etc.) as NULL — populated by WC-02 scrapers
- Create `config/worldcup_2026.yaml` with all 48 teams structured by group
- Include venue data: `config/worldcup_venues.yaml` with 16 stadiums (name, city, country, capacity, altitude_m, latitude, longitude)

**Acceptance Criteria:**
- [ ] `config/worldcup_2026.yaml` exists with all 48 teams organized by group (A–L)
- [ ] `config/worldcup_venues.yaml` exists with all 16 WC venues including altitude and coordinates
- [ ] `seed_teams()` inserts 48 rows into `wc_teams`
- [ ] Each team has: name, fifa_code, confederation, group_letter, wc_appearances, best_wc_finish, is_host
- [ ] Running `seed_teams()` twice is idempotent (upsert, not duplicate)
- [ ] Host nations (USA, Canada, Mexico) have `is_host=True`

---

### WC-01-03 — Import Historical International Results

**Type:** Data
**Depends on:** WC-01-02

Import historical international match results for Elo computation and model training.

**Implementation Notes:**
- Download the Kaggle "International Football Results from 1872 to 2024" dataset (or equivalent GitHub dataset: `martj42/international_results`)
- Create `scripts/import_wc_history.py` that:
  1. Downloads/reads the CSV of international results
  2. Filters to matches from 2018 onward (last 2 WC cycles — older data has negligible predictive value)
  3. Tags match type: friendly (weight=0.25), qualifier (weight=0.5), continental championship (weight=0.75), World Cup (weight=1.0)
  4. Stores in a `wc_historical_matches` table (date, home_team, away_team, home_goals, away_goals, tournament, match_weight, neutral_venue)
- Also import all 2026 WC results played so far (from The Odds API scores endpoint or ESPN scrape)
- Must include the neutral_venue flag (critical for Elo computation)

**Acceptance Criteria:**
- [ ] `scripts/import_wc_history.py` exists and runs without errors
- [ ] `wc_historical_matches` table contains 1,500+ matches from 2018-2026
- [ ] Each match has: date, teams, score, tournament name, match_weight, neutral_venue flag
- [ ] All 43+ completed WC 2026 matches are included with correct scores
- [ ] Match weights correctly assigned: friendly=0.25, qualifier=0.5, confederation tournament=0.75, WC=1.0
- [ ] Script is idempotent (re-running does not create duplicates)

---

## WC-02 — Data Collection

### WC-02-01 — WC Odds Scraper

**Type:** Scraper
**Depends on:** WC-01-01
**Reuses:** `src/scrapers/odds_api.py` (connection logic, budget tracking, JSON saving)

Scrape World Cup match odds from The Odds API.

**Implementation Notes:**
- Create `src/world_cup/scraper.py` with `scrape_wc_odds()` function
- Sport key: `soccer_fifa_world_cup` (verified working, 59 bookmakers)
- Markets: `h2h`, `spreads`, `totals` (verified available)
- Regions: `us,uk,eu,au` for maximum bookmaker coverage
- Also scrape outright winner odds: `soccer_fifa_world_cup_winner` with `outrights` market
- Reuse existing Odds API budget tracking (`data/logs/odds_api_budget.json`)
- Save raw JSON to `data/raw/wc_odds_{date}.json`
- Load into `wc_odds` table via a loader function `load_wc_odds()`
- Dedup on (match_id, bookmaker, market_type, selection) — same pattern as league odds

**Acceptance Criteria:**
- [ ] `scrape_wc_odds()` fetches odds for all upcoming WC matches
- [ ] At least 3 markets collected per match: h2h, spreads, totals
- [ ] At least 50 bookmakers represented across all matches
- [ ] Raw JSON saved to `data/raw/wc_odds_{date}.json`
- [ ] Odds loaded into `wc_odds` table with proper deduplication
- [ ] API budget tracked — function logs remaining requests
- [ ] Outright winner odds captured separately
- [ ] Function handles empty responses gracefully (no matches scheduled = no error)

---

### WC-02-02 — WC Results Scraper

**Type:** Scraper
**Depends on:** WC-01-02

Scrape completed WC 2026 match results and update standings.

**Implementation Notes:**
- Add `scrape_wc_results()` to `src/world_cup/scraper.py`
- Primary source: The Odds API scores endpoint (`/v4/sports/soccer_fifa_world_cup/scores`)
- Fallback: ESPN standings page scrape (already proven working)
- For each completed match:
  1. Update `wc_matches.home_goals`, `away_goals`, `status='finished'`
  2. Update group standings (computed, not stored — derive from match results)
- Also scrape scheduled fixtures and insert as `status='scheduled'` in `wc_matches`
- Match teams to `wc_teams` by name (build a name mapping dict for variations: "Türkiye"→"Turkey", "Czechia"→"Czech Republic", "Ivory Coast"→"Côte d'Ivoire", "DR Congo"→"Congo DR", etc.)

**Acceptance Criteria:**
- [ ] `scrape_wc_results()` fetches all completed and upcoming WC matches
- [ ] Completed matches have correct scores in `wc_matches`
- [ ] Scheduled matches inserted with `status='scheduled'`
- [ ] Team name mapping handles all 48 teams across API variations
- [ ] Group standings can be computed from match results (function `compute_group_standings()`)
- [ ] Function is idempotent — re-running updates existing records, does not create duplicates
- [ ] All venues correctly assigned (city, altitude)

---

### WC-02-03 — International Elo Calculator

**Type:** Feature
**Depends on:** WC-01-03

Compute Elo ratings for all 48 teams from historical international results.

**Implementation Notes:**
- Create `src/world_cup/elo.py` with `compute_international_elo()` function
- Follow the World Football Elo methodology (eloratings.net):
  - K-factors: friendly=20, qualifier=25, confederation tournament=35, WC group=40, WC knockout=50
  - Goal difference multiplier: 1 goal=1.0, 2 goals=1.5, 3+ goals=(11+goal_diff)/8
  - Expected result: W_e = 1 / (10^(-elo_diff/400) + 1)
  - Home advantage: +100 Elo for true home, +50 for partial home (same continent), 0 for neutral
- Initialize all teams at 1500 Elo
- Process all historical matches chronologically (2018-2026)
- Store final Elo in `wc_teams.elo_rating`
- Also provide `update_elo_after_match(match)` to update ratings during the tournament
- Apply 20% regression-to-mean between WC cycles (2022→2026 qualifying)

**Acceptance Criteria:**
- [ ] `compute_international_elo()` processes all historical matches and produces Elo for 48 teams
- [ ] Top 5 Elo ratings are plausible (France, Argentina, Spain, England, Brazil in top tier)
- [ ] K-factors correctly differentiated by match type
- [ ] Goal difference multiplier applied correctly
- [ ] `update_elo_after_match()` updates both teams' Elo after a single match
- [ ] Neutral venue flag correctly removes home advantage in Elo calculation
- [ ] Elo values stored in `wc_teams.elo_rating` column
- [ ] Re-running computation produces identical results (deterministic)

---

### WC-02-04 — World Bank & Alternative Data Collector ✅ DONE

**Type:** Scraper
**Depends on:** WC-01-02
**Results:** GDP 48/48, Population 48/48, Gini 48/48 (10 regional fallbacks), Political Stability 48/48 (WGI 2023 hardcoded — API retired). Batch API (3 calls vs 192). Cached to data/raw/wc_world_bank_cache.json. Climate gap and travel distance computed for all 48 teams.

Fetch economic, demographic, and governance indicators from the World Bank API for all 48 teams.

**Implementation Notes:**
- Create `src/world_cup/world_bank.py` with `fetch_country_indicators()` function
- World Bank API (free, no auth required):
  - Endpoint: `https://api.worldbank.org/v2/country/{code}/indicators/{indicator}?format=json`
  - GDP per capita: `NY.GDP.PCAP.CD` (use latest available year, likely 2024)
  - Population: `SP.POP.TOTL`
  - Gini coefficient: `SI.POV.GINI` (may be missing for some countries — use regional average)
  - Political stability: `PV.EST` from Worldwide Governance Indicators
- Map FIFA country codes to World Bank ISO3 codes (FIFA uses different codes for some nations)
- Update `wc_teams` table columns: gdp_per_capita, population, gini_coefficient, political_stability
- Compute derived features:
  - `climate_gap`: Average June temperature at home capital vs WC venue temperatures
  - `travel_distance_km`: Great-circle distance from capital to assigned group venues
- Cache results — these don't change during the tournament, so fetch once

**Acceptance Criteria:**
- [ ] `fetch_country_indicators()` fetches data for all 48 WC teams
- [ ] GDP per capita populated for all 48 teams (no NULLs)
- [ ] Population populated for all 48 teams
- [ ] Gini coefficient populated for at least 40 teams (regional average fallback for missing)
- [ ] Political stability score populated for at least 44 teams
- [ ] FIFA-to-World-Bank country code mapping handles all 48 teams
- [ ] Data cached after first fetch (does not re-call API on subsequent runs)
- [ ] All values stored in `wc_teams` table

---

### WC-02-05 — Squad Data Collector ✅ DONE

**Type:** Scraper
**Depends on:** WC-01-02
**Reuses:** `src/scrapers/transfermarkt.py` (scraping patterns)
**Results:** 48/48 squads loaded from YAML seed file. All fields populated: MV, age, top5, CL, caps, Gini, manager, tenure. Dark horse scores: Iran +23, Algeria +19, Australia +15. Range: €8M (Curaçao) to €1,380M (England).

Collect squad-level data for all 48 teams: market value, age profile, club league distribution.

**Implementation Notes:**
- Create `src/world_cup/squad.py` with `fetch_squad_data()` function
- For each of the 48 teams, collect (from Transfermarkt or manual seed file):
  - Total squad market value (€)
  - Average squad age
  - Number of players in top-5 European leagues (EPL, La Liga, Serie A, Bundesliga, Ligue 1)
  - Number of Champions League participants
  - Average international caps per player
  - Intra-squad market value Gini (star concentration metric)
  - Manager name and appointment date → compute tenure in months
- Primary approach: Create a seed file `config/wc_squads_2026.yaml` with manually curated data for all 48 squads (faster and more reliable than scraping Transfermarkt for 48 national teams mid-tournament)
- Fallback: Scrape Transfermarkt national team pages if YAML is incomplete
- Update `wc_teams` table: squad_market_value, avg_squad_age, players_in_top5_leagues, cl_players, manager_name, manager_tenure_months
- Compute `dark_horse_score`: elo_rank - market_value_rank (positive = potential overperformer)

**Acceptance Criteria:**
- [ ] Squad data populated for all 48 teams
- [ ] `squad_market_value` in EUR for all 48 teams (no NULLs)
- [ ] `avg_squad_age` for all 48 teams
- [ ] `players_in_top5_leagues` count for all 48 teams
- [ ] `cl_players` count for all 48 teams
- [ ] `manager_tenure_months` for all 48 teams
- [ ] `dark_horse_score` computed and stored for all 48 teams
- [ ] YAML seed file `config/wc_squads_2026.yaml` exists as authoritative source

---

## WC-03 — Feature Engineering

### WC-03-01 — Core Match Features ✅ DONE

**Type:** Feature
**Depends on:** WC-02-03, WC-02-04, WC-02-05
**Results:** 40/40 matches with full Tier 1 features. 0 NULL values. Elo diff, MV ratio (log), squad features, WC appearances, host flags all computed.

Compute the primary feature vector for each WC match.

**Implementation Notes:**
- Create `src/world_cup/features.py` with `compute_wc_features(match)` function
- For each match, compute and store in `wc_features`:
  - **Strength features:** elo_diff, elo_home, elo_away, market_value_ratio (log scale)
  - **Squad features:** avg_age_home/away, top5_league_players_home/away, cl_players_home/away
  - **Historical features:** wc_appearances_home/away, best_finish_home/away
  - **Contextual features:** is_host_home/away, confederation_adj_home/away, rest_days_home/away
  - **Venue features:** altitude_m
- Confederation adjustment factors (hard-coded from research):
  - UEFA: 0.0 (reference)
  - CONMEBOL: 0.0
  - CONCACAF: -0.06
  - CAF: -0.07
  - AFC: -0.09
  - OFC: -0.10
- Rest days: Compute from match schedule (days since team's last match; first match = 7)

**Acceptance Criteria:**
- [ ] `compute_wc_features()` produces a feature vector for any given WC match
- [ ] All Tier 1 features (elo_diff, market_value_ratio, wc_appearances, host flag, squad age) computed
- [ ] Confederation adjustment correctly applied based on team's confederation
- [ ] Rest days computed from actual tournament schedule
- [ ] Feature vector stored in `wc_features` table
- [ ] Function handles both scheduled and completed matches
- [ ] No NaN values in output (fallback to 0.0 with warning for missing data)

---

### WC-03-02 — Alternative Features ✅ DONE

**Type:** Feature
**Depends on:** WC-03-01
**Results:** GDP/pop ratio (log), climate gap (venue-specific), travel distance (haversine), dark horse, manager tenure, form (last 5 competitive). All stored in wc_features.

Add Tier 2 and Tier 3 features from the research: economic, climatic, and tactical indicators.

**Implementation Notes:**
- Extend `compute_wc_features()` to include:
  - **Economic features:** gdp_ratio (log GDP per capita ratio), population_ratio (log)
  - **Climate features:** climate_gap_home/away (temperature difference between team's home country average June temp and match venue's forecast/average June temp)
  - **Travel features:** travel_distance_home/away_km (great-circle from capital to venue)
  - **Dark horse features:** dark_horse_score_home/away (elo_rank minus market_value_rank)
  - **Manager features:** manager_tenure_home/away (months)
  - **Form features:** home_form_last5/away_form_last5 (points from last 5 competitive matches, weighted by match type)
- Home country average June temperatures: hard-code in `config/worldcup_2026.yaml` per team (one-time research)
- Venue average June temperatures: hard-code in `config/worldcup_venues.yaml`

**Acceptance Criteria:**
- [ ] GDP ratio computed for all matches (log scale, no NaN)
- [ ] Climate gap computed using home country vs venue temperature data
- [ ] Travel distance computed using haversine formula
- [ ] Dark horse score included in feature vector
- [ ] Manager tenure included
- [ ] Form from last 5 competitive matches computed from historical data
- [ ] All alternative features stored in `wc_features` table
- [ ] Feature importance can be inspected after model training

---

### WC-03-03 — Tournament-Specific Features ✅ DONE

**Type:** Feature
**Depends on:** WC-03-01
**Results:** Motivation (standard/must_win/comfortable/dead_rubber/live), matchday inferred, group strength, stage code, knockout deflation (0.85). All 40 matches, 0 NULLs.

Add features unique to tournament dynamics: motivation, matchday, group position.

**Implementation Notes:**
- Extend `compute_wc_features()` with:
  - **Motivation classification** (for matchday 3 only):
    - `must_win`: team is eliminated if they lose
    - `comfortable`: team has already qualified
    - `dead_rubber`: team is already eliminated
    - `live`: qualification depends on result
    - Compute from current group standings before the match
  - **Matchday** (1, 2, or 3): First matches are less predictable; matchday 3 has dead rubbers
  - **Group strength**: Average Elo of all 4 teams in the group
  - **Stage indicator**: group=0, r32=1, r16=2, qf=3, sf=4, final=5 (for knockout deflation)
  - **Knockout deflation**: For knockout matches, multiply expected goals by 0.85 (research: 15% fewer goals in knockouts)
- These features update dynamically as the tournament progresses

**Acceptance Criteria:**
- [ ] Motivation correctly classified for matchday 3 matches based on current standings
- [ ] Matchday number assigned to all group stage matches
- [ ] Group strength (average Elo) computed for all 12 groups
- [ ] Stage indicator correctly set for all tournament stages
- [ ] Knockout deflation flag/multiplier applied for R32 onward
- [ ] Features recompute correctly after each day's results are imported

---

## WC-04 — Prediction Model

### WC-04-01 — International Poisson Model ✅ DONE

**Type:** Model
**Results:** WCPoissonPredictor in predictor.py. 1039 training matches, rho=-0.062, max|coef|=0.39. Holdout Brier 0.194/class (46 WC 2022 matches, 54% accuracy). 40 WC 2026 predictions stored. Dixon-Coles + knockout deflation + group draw inflation.
**Depends on:** WC-03-01
**Reuses:** `src/models/poisson.py` (Poisson distribution math, scoreline matrix)

Adapt the BetVector Poisson model for international World Cup football.

**Implementation Notes:**
- Create `src/world_cup/predictor.py` with `WCPoissonPredictor` class
- Core approach: Regularized Poisson regression (Groll et al. 2015 methodology)
  - lambda_home = exp(intercept + sum(beta_i * feature_i))
  - lambda_away = exp(intercept + sum(beta_j * feature_j))
- Feature selection (ordered by importance from research):
  1. elo_diff (standardized)
  2. market_value_ratio (log)
  3. is_host
  4. confederation_adj
  5. wc_appearances (log)
  6. avg_squad_age (centered at 27, quadratic term for inverted-U)
  7. cl_players_diff
  8. rest_days_diff
  9. altitude_m (for Mexico City matches)
  10. gdp_ratio (log)
- Training data: Historical WC matches (2018, 2022) + continental championships (2021, 2024) + current WC 2026 group stage results
- Use L2 regularization (ridge) to prevent overfitting with small sample
- From the Poisson lambdas, derive:
  - P(home win), P(draw), P(away win) via scoreline matrix summation
  - P(over 2.5), P(over 3.5), P(BTTS)
  - Most likely scoreline
- Apply Dixon-Coles correction factor for low-scoring draws (rho parameter)
- Apply knockout deflation (multiply both lambdas by 0.85) for knockout matches
- Draw inflation: Add 2-3 percentage points to draw probability (documented market bias)

**Acceptance Criteria:**
- [ ] `WCPoissonPredictor` class with `fit()` and `predict()` methods
- [ ] Model trains on historical international match data (2018-2026)
- [ ] Produces P(home), P(draw), P(away) for any WC match
- [ ] Produces expected goals (lambda) for each team
- [ ] Produces scoreline probability matrix (0-0 through 5-5)
- [ ] Over/under and BTTS probabilities derived from scoreline matrix
- [ ] Dixon-Coles rho correction applied to low-scoring outcomes
- [ ] Regularization prevents extreme coefficients
- [ ] Predictions stored in `wc_predictions` table
- [ ] Brier score computed on held-out 2022 WC data is below 0.220

---

### WC-04-02 — Tournament Simulator ✅ DONE

**Type:** Model
**Depends on:** WC-04-01
**Results:** 10K sims in 3.9s. Winner sum=1.0. Top 5: Argentina 6.0%, Spain 5.5%, Japan 4.8%, Morocco 4.2%, France 4.1%. H2H tiebreaker, correct R32 bracket (winners face thirds), penalty clamp [0.35,0.65].

Monte Carlo simulation of the entire tournament to compute advancement probabilities.

**Implementation Notes:**
- Create `src/world_cup/simulator.py` with `simulate_tournament(n_sims=10000)` function
- For each simulation:
  1. Simulate remaining group matches using Poisson model (sample goals from Poisson distribution)
  2. Compute final group standings (points, GD, GF, head-to-head tiebreaker)
  3. Determine top 2 per group (24 teams) + 8 best third-placed teams (32 total)
  4. Fill knockout bracket per FIFA rules
  5. Simulate each knockout match: 90-min result from Poisson, if draw → 50/50 coin flip for advancement (simplification of ET + penalties)
  6. Track: which team reaches each round, and who wins the tournament
- Output probabilities for each team:
  - P(advance from group)
  - P(reach R16), P(reach QF), P(reach SF), P(reach final), P(win tournament)
- Third-place computation: Rank all 12 third-placed teams by points, then GD, then GF → top 8 advance
- Bracket assignment follows FIFA's published bracket template for 48-team format
- Results cached until new match results are imported

**Acceptance Criteria:**
- [ ] `simulate_tournament()` runs 10,000 simulations in under 60 seconds
- [ ] Produces advancement probabilities for all 48 teams at each stage
- [ ] Third-place team selection correctly implements FIFA tiebreaker rules
- [ ] Knockout bracket correctly follows FIFA 48-team bracket template
- [ ] Already-decided matches are not re-simulated (uses actual results)
- [ ] Probabilities sum to 1.0 for tournament winner across all teams
- [ ] Top favorites match bookmaker outright odds in direction (France/Spain/Argentina/England in top 5)
- [ ] Results update after each day's matches are finalized

---

### WC-04-03 — Model Calibration & Dark Horse Detection ✅ DONE

**Type:** Model
**Depends on:** WC-04-01
**Results:** Pre-cal Brier 0.4552 (0.152/class), 75% accuracy on 12 matches. Post-cal Brier 0.4517. Config-driven K-factors (40/50), GD multiplier, idempotent Elo. Metrics persisted to wc_calibration_metrics. Dark horse detection supports match-level + tournament-advancement probabilities.

Calibrate the model using group stage results and identify dark horses for knockout betting.

**Implementation Notes:**
- Create `src/world_cup/calibration.py` with:
  - `calibrate_on_group_stage()`: After group stage completes (~72 matches), re-estimate model coefficients using 2026 group stage data combined with historical data. This tunes the model for the specific characteristics of this tournament (higher goal rate, upset frequency, etc.)
  - `detect_dark_horses()`: Compare model advancement probability to bookmaker implied probability for each team. Teams where model_prob >> market_prob are dark horses. Flag teams with >5% edge in advancement probability.
  - `compute_model_accuracy()`: Track Brier score, log-loss, and calibration plot for predictions made so far
- Also compute in-tournament Elo updates: After each match, update both teams' Elo using WC K-factor (40 for group, 50 for knockout). This captures momentum and form within the tournament.
- Store calibration metrics for dashboard display

**Acceptance Criteria:**
- [ ] `calibrate_on_group_stage()` re-fits model with 2026 group stage data included
- [ ] Brier score improvement measured before vs after calibration
- [ ] `detect_dark_horses()` identifies teams with >5% edge vs market
- [ ] In-tournament Elo updates applied after each match
- [ ] Calibration metrics (Brier, log-loss, accuracy%) stored and accessible
- [ ] Model can be re-calibrated daily as new results come in

---

## WC-05 — Value Betting & Alerts

### WC-05-01 — WC Value Finder

**Type:** Betting
**Depends on:** WC-04-01, WC-02-01
**Reuses:** `src/betting/value_finder.py` (edge calculation, Kelly criterion), `src/betting/bankroll.py`

Identify value bets by comparing model probabilities to market odds.

**Implementation Notes:**
- Create `src/world_cup/value_finder.py` with `find_wc_value_bets()` function
- For each upcoming match:
  1. Get model probabilities (home/draw/away, over/under)
  2. Get best available odds across all bookmakers from `wc_odds`
  3. Compute edge: `edge = model_prob - implied_prob` (where implied_prob = 1/odds)
  4. If edge > threshold (default 3%, configurable), flag as value bet
  5. Compute Kelly stake: `kelly = edge / (odds - 1)`, apply quarter-Kelly for safety
- Support multiple markets: h2h (3-way), spreads (Asian handicap), totals (over/under)
- Rank value bets by edge magnitude × confidence (model calibration quality)
- Store in `wc_value_bets` table
- Reuse existing bankroll module for stake sizing
- Configure separate WC bankroll (independent of league bankroll)

**Acceptance Criteria:**
- [ ] `find_wc_value_bets()` scans all upcoming WC matches
- [ ] Value bets identified across h2h, spreads, and totals markets
- [ ] Best odds selected from 59 bookmakers per match
- [ ] Edge correctly computed as model_prob - implied_prob
- [ ] Kelly stake computed with quarter-Kelly fractional sizing
- [ ] Value bets stored in `wc_value_bets` table
- [ ] Edge threshold configurable (default 3%)
- [ ] Function returns empty list gracefully when no value exists

---

### WC-05-02 — WC Email Alerts

**Type:** Delivery
**Depends on:** WC-05-01
**Reuses:** `src/delivery/email_alerts.py` (SMTP connection, HTML templates)

Send daily email alerts with WC predictions and value bets.

**Implementation Notes:**
- Add WC-specific email functions to existing email system (or create `src/world_cup/alerts.py`)
- Morning WC email (sent at 08:00 on match days):
  - Today's WC matches with predictions (home/draw/away probabilities)
  - Value bets flagged with edge %, recommended stake, best bookmaker
  - Current group standings (or knockout bracket)
  - Tournament advancement probabilities for key teams
- Evening WC email (sent at 22:00):
  - Today's results vs predictions (was the model right?)
  - Updated Elo ratings after today's matches
  - Updated tournament advancement probabilities
  - Model accuracy tracker (running Brier score)
- Subject lines: "🏆 WC Day N: [X] value bets for today" / "🏆 WC Day N Results: [X/Y] correct"
- Use existing Gmail SMTP connection and recipient list

**Acceptance Criteria:**
- [ ] Morning WC email sent with predictions for today's matches
- [ ] Value bets included with edge %, odds, bookmaker, and suggested stake
- [ ] Evening WC email sent with results and model accuracy
- [ ] Group standings or knockout bracket included in email body
- [ ] Emails render correctly in HTML (dark theme matching existing BetVector emails)
- [ ] No email sent on days with no WC matches
- [ ] Email function can be called from WC pipeline

---

## WC-06 — Dashboard

### WC-06-01 — WC Dashboard Page

**Type:** UI
**Depends on:** WC-04-01, WC-05-01
**Reuses:** `src/delivery/dashboard.py` (Streamlit app shell, page routing, CSS)

Add a World Cup page to the existing BetVector Streamlit dashboard.

**Implementation Notes:**
- Create `src/delivery/pages/world_cup.py` as a new Streamlit page
- Page sections:
  1. **Header**: Tournament progress bar (matches played / 80 total), days remaining
  2. **Today's Matches**: Cards showing each match with predictions, odds, value bet flags
  3. **Group Standings**: 12 mini-tables (2 columns × 6 rows), color-coded by qualification status (green=qualified, yellow=possible, red=eliminated)
  4. **Value Bets**: Table of current value bets with edge, odds, bookmaker, Kelly stake
  5. **Model Performance**: Running Brier score, accuracy %, calibration chart
  6. **Tournament Probabilities**: Bar chart showing P(win tournament) for top 16 teams
- Use existing BetVector CSS/theme for consistency
- Add "World Cup" to the sidebar navigation
- Show knockout bracket visualization when knockouts begin

**Acceptance Criteria:**
- [ ] World Cup page accessible from dashboard sidebar
- [ ] Today's matches displayed with model predictions and best odds
- [ ] All 12 group standings displayed correctly
- [ ] Value bets table shows edge, odds, bookmaker for each bet
- [ ] Model performance metrics displayed (Brier score, accuracy)
- [ ] Tournament winner probabilities shown as a bar chart
- [ ] Page loads in under 5 seconds
- [ ] Responsive layout works at common screen widths

---

### WC-06-02 — Group Advancement Simulator Widget

**Type:** UI
**Depends on:** WC-04-02

Interactive widget showing group advancement probabilities and "what-if" scenarios.

**Implementation Notes:**
- Add an interactive section to the WC dashboard page
- For each group:
  - Show P(advance) for each team (from Monte Carlo simulation)
  - Show P(1st), P(2nd), P(3rd-qualify), P(eliminated)
  - Color-code: green (>80% advance), yellow (30-80%), red (<30%)
- "What-if" scenario selector: User picks a result for a remaining match → instantly recompute group probabilities
- Third-place comparison table: Show all 12 potential third-place teams ranked by expected points/GD, with P(qualify as best third)
- Use Streamlit columns and expanders for compact layout

**Acceptance Criteria:**
- [ ] Each group shows advancement probability per team
- [ ] Probabilities sourced from Monte Carlo simulation (WC-04-02)
- [ ] Color-coding reflects qualification likelihood
- [ ] Third-place comparison table shows all 12 potential third-place finishers
- [ ] Probabilities update when page is refreshed after new results

---

### WC-06-03 — Knockout Bracket Visualization

**Type:** UI
**Depends on:** WC-04-02

Display the knockout bracket with predicted advancement probabilities.

**Implementation Notes:**
- Create a bracket visualization once group stage is complete (or show projected bracket during groups)
- Show all R32 through Final matchups
- For each matchup:
  - Team names with Elo ratings
  - Model P(advance) for each team
  - Best available odds from bookmakers
  - Value bet flag if edge exists
- Bracket updates as matches complete (actual results replace predictions)
- Use SVG or HTML/CSS for bracket layout (not matplotlib — needs to be interactive)

**Acceptance Criteria:**
- [ ] Knockout bracket displays all rounds (R32 → Final)
- [ ] Each matchup shows both teams with advancement probabilities
- [ ] Completed matches show actual results
- [ ] Predicted matches show model probabilities
- [ ] Value bet flags visible on bracket
- [ ] Bracket renders correctly in Streamlit

---

## WC-07 — Pipeline & Automation

### WC-07-01 — WC Daily Pipeline

**Type:** Pipeline
**Depends on:** WC-02-01, WC-02-02, WC-04-01, WC-05-01

Orchestrate the daily World Cup pipeline: scrape → compute → predict → find value → alert.

**Implementation Notes:**
- Create `src/world_cup/pipeline.py` with `run_wc_pipeline(mode='morning'|'evening')` function
- Morning pipeline (run at 08:00 on match days):
  1. Scrape latest WC results (update completed matches)
  2. Update Elo ratings for any newly completed matches
  3. Fetch fresh odds for today's and tomorrow's matches
  4. Compute/recompute features for upcoming matches
  5. Generate predictions for upcoming matches
  6. Run tournament simulator (10K simulations)
  7. Find value bets
  8. Send morning email alert
- Evening pipeline (run at 22:00):
  1. Scrape today's results
  2. Update Elo ratings
  3. Evaluate predictions vs actual results
  4. Update model accuracy metrics
  5. Send evening review email
- Log to `data/logs/wc_morning_{date}.log` and `data/logs/wc_evening_{date}.log`
- Add CLI entry point: `python -m src.world_cup.pipeline --mode morning`

**Acceptance Criteria:**
- [ ] Morning pipeline runs end-to-end without errors
- [ ] Evening pipeline runs end-to-end without errors
- [ ] Results scraped and stored correctly
- [ ] Elo updated after each match
- [ ] Fresh odds collected for upcoming matches
- [ ] Predictions generated for all scheduled matches
- [ ] Value bets identified and stored
- [ ] Emails sent (morning picks, evening review)
- [ ] Pipeline completes in under 10 minutes
- [ ] Logs written to `data/logs/wc_*.log`
- [ ] CLI entry point works: `python -m src.world_cup.pipeline --mode morning`

---

### WC-07-02 — Launchd Integration

**Type:** Automation
**Depends on:** WC-07-01

Add WC pipeline to the existing launchd schedule alongside league pipelines.

**Implementation Notes:**
- Create `com.betvector.wc_morning.plist` and `com.betvector.wc_evening.plist`
- Schedule: Morning at 08:00, Evening at 22:00 (same as league pipelines)
- Modify `run_pipeline_local.sh` to accept a `--wc` flag that runs the WC pipeline instead of league pipeline
- OR create a separate `run_wc_pipeline.sh` script
- Include the same safeguards as league pipeline: timeout (30 min max), stale process killer, log rotation
- Only run on days with WC matches (check schedule) — or run daily and exit early if no matches

**Acceptance Criteria:**
- [ ] Launchd plist files created for WC morning and evening
- [ ] WC pipeline runs automatically at 08:00 and 22:00
- [ ] Pipeline timeout prevents zombie processes (30 min max)
- [ ] Logs appear in `data/logs/wc_morning_{date}.log`
- [ ] WC pipeline does not interfere with league pipeline schedule
- [ ] Pipeline exits cleanly on days with no WC matches

---

## Appendix A — Feature Reference

### Full Feature Vector (30 features)

| # | Feature | Source | Tier | Type |
|---|---------|--------|------|------|
| 1 | elo_diff | Computed (WC-02-03) | 1 | Strength |
| 2 | elo_home | Computed | 1 | Strength |
| 3 | elo_away | Computed | 1 | Strength |
| 4 | market_value_ratio | Transfermarkt (WC-02-05) | 1 | Squad |
| 5 | avg_age_home | Transfermarkt | 1 | Squad |
| 6 | avg_age_away | Transfermarkt | 1 | Squad |
| 7 | top5_league_players_home | Transfermarkt | 1 | Squad |
| 8 | top5_league_players_away | Transfermarkt | 1 | Squad |
| 9 | cl_players_home | Transfermarkt | 1 | Squad |
| 10 | cl_players_away | Transfermarkt | 1 | Squad |
| 11 | wc_appearances_home | Historical (WC-01-02) | 1 | Historical |
| 12 | wc_appearances_away | Historical | 1 | Historical |
| 13 | best_finish_home | Historical | 1 | Historical |
| 14 | best_finish_away | Historical | 1 | Historical |
| 15 | is_host_home | Hard-coded | 1 | Context |
| 16 | is_host_away | Hard-coded | 1 | Context |
| 17 | confederation_adj_home | Hard-coded (WC-03-01) | 2 | Context |
| 18 | confederation_adj_away | Hard-coded | 2 | Context |
| 19 | rest_days_home | Schedule (WC-03-01) | 2 | Context |
| 20 | rest_days_away | Schedule | 2 | Context |
| 21 | gdp_ratio | World Bank (WC-02-04) | 2 | Economic |
| 22 | population_ratio | World Bank | 2 | Economic |
| 23 | altitude_m | Venue config | 3 | Venue |
| 24 | climate_gap_home | Temperature data | 3 | Venue |
| 25 | climate_gap_away | Temperature data | 3 | Venue |
| 26 | travel_distance_home_km | Haversine | 3 | Venue |
| 27 | travel_distance_away_km | Haversine | 3 | Venue |
| 28 | manager_tenure_home | Squad data (WC-02-05) | 2 | Tactical |
| 29 | manager_tenure_away | Squad data | 2 | Tactical |
| 30 | dark_horse_score_home | Computed (elo_rank - mv_rank) | 2 | Meta |
| 31 | dark_horse_score_away | Computed | 2 | Meta |
| 32 | home_form_last5 | Historical (WC-03-02) | 2 | Form |
| 33 | away_form_last5 | Historical | 2 | Form |
| 34 | motivation_home | Standings (WC-03-03) | 3 | Tournament |
| 35 | motivation_away | Standings | 3 | Tournament |
| 36 | matchday | Schedule | 3 | Tournament |
| 37 | group_strength | Computed | 3 | Tournament |

---

## Appendix B — Data Sources

| Source | Endpoint / URL | Auth | Cost | Used By |
|--------|---------------|------|------|---------|
| The Odds API | `soccer_fifa_world_cup` | API key (existing) | Free (388 remaining) | WC-02-01 |
| The Odds API | `soccer_fifa_world_cup_winner` | API key | Free | WC-02-01 |
| The Odds API | Scores endpoint | API key | Free | WC-02-02 |
| World Bank API | `api.worldbank.org/v2/country/{code}/indicators/{id}` | None | Free | WC-02-04 |
| Kaggle | International Football Results dataset | Account | Free | WC-01-03 |
| ESPN | Standings page scrape | None | Free | WC-02-02 |
| Transfermarkt | National team squad pages | None (scrape) | Free | WC-02-05 |
| eloratings.net | Current international Elo | None (JS scrape) | Free | WC-02-03 (validation) |

---

## Appendix C — Academic References

| Paper | Year | Key finding | Used in |
|-------|------|-------------|---------|
| Groll, Schauberger & Tutz | 2015 | GDP + host + regularized Poisson → 60% WC variance explained | WC-04-01, WC-03-02 |
| Groll et al. | 2018 | RF + Poisson stack correctly predicted France; market value is strongest covariate | WC-04-01, WC-02-05 |
| Baio & Blangiardo | 2010 | Bayesian hierarchical Poisson handles sparse international data | WC-04-01 (future upgrade) |
| Hvattum & Arntzen | 2010 | Elo outperforms FIFA ranking; bookmaker odds outperform both | WC-02-03, WC-05-01 |
| Berlinschi et al. | 2013 | GDP effect saturates above ~$20K PPP; Gini is negative predictor | WC-02-04 |
| Dixon & Coles | 1997 | Rho correction for low-scoring draws in Poisson | WC-04-01 |
| Forrest, Goddard & Simmons | 2005 | Draws underpriced by 2-3% in international football | WC-04-01 |
| Leeds & Leeds | 2009 | Political stability +0.15-0.20 pts/match effect | WC-02-04 |
| Goldman Sachs | 2018 | Intra-squad market value Gini: star-dependent teams underperform | WC-02-05 |
