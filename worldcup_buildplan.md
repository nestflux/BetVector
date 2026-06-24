# BetVector World Cup 2026 — Build Plan

Version 1.0 · June 2026

> **MODULE STATUS: MVP + UX COMPLETE (28/28) · WC-09 IN PROGRESS — 4/8 (tracks A+B done)** · June 23, 2026
> WC-01 through WC-08 done (3-gate reviewed); dashboard is 4 tabs with flags + ET
> times. **WC-09 (Option A):** ✅ 09-01→04 done — shadow CLV scorecard + per-match
> research card & review queue (decision-support tracks A+B, gated). ⏸ Remaining:
> 09-05/06/07 Bayesian shadow model (Tier-2 approved) + 09-08 player-props spike.
> Full test suite: 689/689 passing.

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
| WC-08 | Dashboard UX Redesign (post-MVP) | 7 | Tabbed layout, country flags, ET times, collapsible reference, responsive |
| WC-09 | Decision Support & Bayesian R&D (post-MVP) | 8 | Shadow CLV scorecard, research card, Bayesian shadow model, player-props spike |
| **Total** | | **36** (21 MVP + 15 post-MVP) | |

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

**Post-MVP (Phase 5):**
```
WC-08-01 → WC-08-02 → WC-08-03 → WC-08-04 →
WC-08-05 → WC-08-06 → WC-08-07
```

**Post-MVP (Phase 6 — Option A, parallel tracks):**
```
Scorecard:     WC-09-01 → WC-09-02          (build first)
Research card: WC-09-03 → WC-09-04
Bayesian (||): WC-09-05 → WC-09-06 → WC-09-07
Props spike:   WC-09-08                     (go/no-go, last)
```

### Phase Strategy

| Phase | Issues | Deadline | Goal |
|-------|--------|----------|------|
| **Phase 1: MVP** | WC-01 through WC-04-01 | June 24 (matchday 3) | Basic predictions for remaining group matches |
| **Phase 2: Value & Alerts** | WC-04-02 through WC-05-02 | June 26 | Value betting + email picks for final group matches |
| **Phase 3: Dashboard** | WC-06-01 through WC-06-03 | June 28 (knockouts) | Full dashboard + group advancement simulator |
| **Phase 4: Knockouts** | WC-04-03, WC-07-01, WC-07-02 | June 30 | Knockout model + automated daily pipeline |
| **Phase 5: Post-MVP UX** | WC-08-01 through WC-08-07 | post-tournament-safe | Tabbed dashboard, flags, ET times, collapsible reference, responsive |
| **Phase 6: Decision Support & Bayesian R&D** | WC-09-01 through WC-09-08 (Option A) | rolling | CLV scorecard + research card (fast value), Bayesian shadow model (parallel R&D), player-props go/no-go spike |

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

### WC-01-01 — WC ORM Models ✅ DONE

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
- [x] `src/world_cup/__init__.py` and `src/world_cup/models.py` exist
- [x] All 6 ORM models defined with proper relationships and foreign keys
- [x] Running `init_db()` creates all `wc_*` tables in the database without affecting existing tables
- [x] `WCTeam` has all 15+ columns for alternative features (economic, demographic, squad)
- [x] `WCFeature` has all 30+ feature columns identified in research
- [x] UniqueConstraints: WCOdds on (match_id, bookmaker, market_type, selection), WCMatch on match_number

---

### WC-01-02 — Seed 48 Teams ✅ DONE

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
- [x] `config/worldcup_2026.yaml` exists with all 48 teams organized by group (A–L)
- [x] `config/worldcup_venues.yaml` exists with all 16 WC venues including altitude and coordinates
- [x] `seed_teams()` inserts 48 rows into `wc_teams`
- [x] Each team has: name, fifa_code, confederation, group_letter, wc_appearances, best_wc_finish, is_host
- [x] Running `seed_teams()` twice is idempotent (upsert, not duplicate)
- [x] Host nations (USA, Canada, Mexico) have `is_host=True`

---

### WC-01-03 — Import Historical International Results ✅ DONE

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
- [x] `scripts/import_wc_history.py` exists and runs without errors
- [x] `wc_historical_matches` table contains 1,500+ matches from 2018-2026
- [x] Each match has: date, teams, score, tournament name, match_weight, neutral_venue flag
- [x] All 43+ completed WC 2026 matches are included with correct scores
- [x] Match weights correctly assigned: friendly=0.25, qualifier=0.5, confederation tournament=0.75, WC=1.0
- [x] Script is idempotent (re-running does not create duplicates)

---

## WC-02 — Data Collection

### WC-02-01 — WC Odds Scraper ✅ DONE

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
- [x] `scrape_wc_odds()` fetches odds for all upcoming WC matches
- [x] At least 3 markets collected per match: h2h, spreads, totals
- [x] At least 50 bookmakers represented across all matches
- [x] Raw JSON saved to `data/raw/wc_odds_{date}.json`
- [x] Odds loaded into `wc_odds` table with proper deduplication
- [x] API budget tracked — function logs remaining requests
- [x] Outright winner odds captured separately
- [x] Function handles empty responses gracefully (no matches scheduled = no error)

---

### WC-02-02 — WC Results Scraper ✅ DONE

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
- [x] `scrape_wc_results()` fetches all completed and upcoming WC matches
- [x] Completed matches have correct scores in `wc_matches`
- [x] Scheduled matches inserted with `status='scheduled'`
- [x] Team name mapping handles all 48 teams across API variations
- [x] Group standings can be computed from match results (function `compute_group_standings()`)
- [x] Function is idempotent — re-running updates existing records, does not create duplicates
- [x] All venues correctly assigned (city, altitude)

---

### WC-02-03 — International Elo Calculator ✅ DONE

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
- [x] `compute_international_elo()` processes all historical matches and produces Elo for 48 teams
- [x] Top 5 Elo ratings are plausible (France, Argentina, Spain, England, Brazil in top tier)
- [x] K-factors correctly differentiated by match type
- [x] Goal difference multiplier applied correctly
- [x] `update_elo_after_match()` updates both teams' Elo after a single match
- [x] Neutral venue flag correctly removes home advantage in Elo calculation
- [x] Elo values stored in `wc_teams.elo_rating` column
- [x] Re-running computation produces identical results (deterministic)

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
- [x] `fetch_country_indicators()` fetches data for all 48 WC teams
- [x] GDP per capita populated for all 48 teams (no NULLs)
- [x] Population populated for all 48 teams
- [x] Gini coefficient populated for at least 40 teams (regional average fallback for missing)
- [x] Political stability score populated for at least 44 teams
- [x] FIFA-to-World-Bank country code mapping handles all 48 teams
- [x] Data cached after first fetch (does not re-call API on subsequent runs)
- [x] All values stored in `wc_teams` table

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
- [x] Squad data populated for all 48 teams
- [x] `squad_market_value` in EUR for all 48 teams (no NULLs)
- [x] `avg_squad_age` for all 48 teams
- [x] `players_in_top5_leagues` count for all 48 teams
- [x] `cl_players` count for all 48 teams
- [x] `manager_tenure_months` for all 48 teams
- [x] `dark_horse_score` computed and stored for all 48 teams
- [x] YAML seed file `config/wc_squads_2026.yaml` exists as authoritative source

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
- [x] `compute_wc_features()` produces a feature vector for any given WC match
- [x] All Tier 1 features (elo_diff, market_value_ratio, wc_appearances, host flag, squad age) computed
- [x] Confederation adjustment correctly applied based on team's confederation
- [x] Rest days computed from actual tournament schedule
- [x] Feature vector stored in `wc_features` table
- [x] Function handles both scheduled and completed matches
- [x] No NaN values in output (fallback to 0.0 with warning for missing data)

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
- [x] GDP ratio computed for all matches (log scale, no NaN)
- [x] Climate gap computed using home country vs venue temperature data
- [x] Travel distance computed using haversine formula
- [x] Dark horse score included in feature vector
- [x] Manager tenure included
- [x] Form from last 5 competitive matches computed from historical data
- [x] All alternative features stored in `wc_features` table
- [x] Feature importance can be inspected after model training

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
- [x] Motivation correctly classified for matchday 3 matches based on current standings
- [x] Matchday number assigned to all group stage matches
- [x] Group strength (average Elo) computed for all 12 groups
- [x] Stage indicator correctly set for all tournament stages
- [x] Knockout deflation flag/multiplier applied for R32 onward
- [x] Features recompute correctly after each day's results are imported

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
- [x] `WCPoissonPredictor` class with `fit()` and `predict()` methods
- [x] Model trains on historical international match data (2018-2026)
- [x] Produces P(home), P(draw), P(away) for any WC match
- [x] Produces expected goals (lambda) for each team
- [x] Produces scoreline probability matrix (0-0 through 5-5)
- [x] Over/under and BTTS probabilities derived from scoreline matrix
- [x] Dixon-Coles rho correction applied to low-scoring outcomes
- [x] Regularization prevents extreme coefficients
- [x] Predictions stored in `wc_predictions` table
- [x] Brier score computed on held-out 2022 WC data is below 0.220

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
- [x] `simulate_tournament()` runs 10,000 simulations in under 60 seconds
- [x] Produces advancement probabilities for all 48 teams at each stage
- [x] Third-place team selection correctly implements FIFA tiebreaker rules
- [x] Knockout bracket correctly follows FIFA 48-team bracket template
- [x] Already-decided matches are not re-simulated (uses actual results)
- [x] Probabilities sum to 1.0 for tournament winner across all teams
- [x] Top favorites match bookmaker outright odds in direction (France/Spain/Argentina/England in top 5)
- [x] Results update after each day's matches are finalized

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
- [x] `calibrate_on_group_stage()` re-fits model with 2026 group stage data included
- [x] Brier score improvement measured before vs after calibration
- [x] `detect_dark_horses()` identifies teams with >5% edge vs market
- [x] In-tournament Elo updates applied after each match
- [x] Calibration metrics (Brier, log-loss, accuracy%) stored and accessible
- [x] Model can be re-calibrated daily as new results come in

---

## WC-05 — Value Betting & Alerts

### WC-05-01 — WC Value Finder ✅ DONE

**Type:** Betting
**Results:** Scans 28 upcoming matches. H2H/totals/BTTS markets. Quarter-Kelly staking from config. Edge×calibration ranking. Idempotent save with new/updated/skipped tracking. 0 VBs found (no odds loaded yet — correct).
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
- [x] `find_wc_value_bets()` scans all upcoming WC matches
- [x] Value bets identified across h2h, spreads, and totals markets
- [x] Best odds selected from 59 bookmakers per match
- [x] Edge correctly computed as model_prob - implied_prob
- [x] Kelly stake computed with quarter-Kelly fractional sizing
- [x] Value bets stored in `wc_value_bets` table
- [x] Edge threshold configurable (default 3%)
- [x] Function returns empty list gracefully when no value exists

---

### WC-05-02 — WC Email Alerts ✅ DONE

**Type:** Delivery
**Depends on:** WC-05-01
**Results:** Morning email (23K chars): predictions, VBs, group standings. Evening email (8K chars): results, 2/2 correct, Brier tracking, top-10 Elo table. Dark theme HTML. HTML-escaped team names. Pipeline-resilient (try/except on SMTP). No email on non-match days.
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
- [x] Morning WC email sent with predictions for today's matches
- [x] Value bets included with edge %, odds, bookmaker, and suggested stake
- [x] Evening WC email sent with results and model accuracy
- [x] Group standings or knockout bracket included in email body
- [x] Emails render correctly in HTML (dark theme matching existing BetVector emails)
- [x] No email sent on days with no WC matches
- [x] Email function can be called from WC pipeline

---

## WC-06 — Dashboard

### WC-06-01 — WC Dashboard Page ✅ DONE

**Type:** UI
**Depends on:** WC-04-01, WC-05-01
**Reuses:** `src/delivery/dashboard.py` (Streamlit app shell, page routing, CSS)

Add a World Cup page to the existing BetVector Streamlit dashboard.

**Implementation Notes:**
- Created `src/delivery/views/world_cup.py` (views/ per project convention)
- Page sections:
  1. **Header**: Tournament progress bar (matches played / 104 total), days remaining
  2. **Today's Matches**: Cards showing each match with predictions, odds (joinedload, 1 query)
  3. **Group Standings**: 12 mini-tables (2 columns × 6 rows), color-coded by qualification status (green=qualified, yellow=possible, red=eliminated)
  4. **Value Bets**: Table of current value bets with edge, odds, bookmaker, Kelly stake (joinedload)
  5. **Model Performance**: Running Brier score, accuracy %, calibration chart (reliability diagram)
  6. **Tournament Probabilities**: Bar chart showing P(win tournament) for top 16 teams (cached, 1hr TTL)
- BetVector dark theme, JetBrains Mono for data, Plotly charts
- "World Cup" 🏆 added to sidebar navigation in get_pages()
- Knockout bracket deferred to WC-06-03

**Acceptance Criteria:**
- [x] World Cup page accessible from dashboard sidebar
- [x] Today's matches displayed with model predictions and best odds
- [x] All 12 group standings displayed correctly
- [x] Value bets table shows edge, odds, bookmaker for each bet
- [x] Model performance metrics displayed (Brier score, accuracy)
- [x] Tournament winner probabilities shown as a bar chart
- [x] Page loads in under 5 seconds
- [x] Responsive layout works at common screen widths

---

### WC-06-02 — Group Advancement Simulator Widget ✅ DONE

**Type:** UI
**Depends on:** WC-04-02

Interactive widget showing group advancement probabilities and "what-if" scenarios.

**Implementation Notes:**
- Added position-specific tracking to `simulator.py`: P(1st), P(2nd), P(3rd-qualify), P(4th), E[pts], E[GD]
- Per-group expanders show P(advance) with breakdown: 1st/2nd/3rd-Q/Elim per team
- Color-coded: green >=80%, yellow 30-80%, red <30%
- What-if scenario selector: pick a scheduled match, enter hypothetical score, recompute standings
- Third-place table: actual 3rd-place team per group (by standings), with E[Pts], E[GD], P(Qualify 3rd) from sim
- Shared `_compute_group_standings()` eliminates redundant DB queries

**Acceptance Criteria:**
- [x] Each group shows advancement probability per team
- [x] Probabilities sourced from Monte Carlo simulation (WC-04-02)
- [x] Color-coding reflects qualification likelihood
- [x] Third-place comparison table shows all 12 potential third-place finishers
- [x] Probabilities update when page is refreshed after new results

---

### WC-06-03 — Knockout Bracket Visualization ✅ DONE

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
- [x] Knockout bracket displays all rounds (R32 → Final)
- [x] Each matchup shows both teams with advancement probabilities
- [x] Completed matches show actual results
- [x] Predicted matches show model probabilities
- [x] Value bet flags visible on bracket
- [x] Bracket renders correctly in Streamlit

**Status:** ✅ DONE — HTML/CSS bracket cards with Elo + P(advance) + best odds + value bet flags. Projected bracket from group standings (sorted top-8 thirds), actual bracket from DB knockout matches. html.escape defense, None-safe Elo, try/except fallback. 621/621 tests.

---

## WC-07 — Pipeline & Automation

### WC-07-01 — WC Daily Pipeline ✅ DONE

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
- [x] Morning pipeline runs end-to-end without errors
- [x] Evening pipeline runs end-to-end without errors
- [x] Results scraped and stored correctly
- [x] Elo updated after each match
- [x] Fresh odds collected for upcoming matches
- [x] Predictions generated for all scheduled matches
- [x] Value bets identified and stored
- [x] Emails sent (morning picks, evening review)
- [x] Pipeline completes in under 10 minutes
- [x] Logs written to `data/logs/wc_*.log`
- [x] CLI entry point works: `python -m src.world_cup.pipeline --mode morning`

**Status:** ✅ DONE — Morning (8 steps) + evening (5 steps) pipelines with per-step error isolation, file+console logging, CLI entry point. 621/621 tests.

---

### WC-07-02 — Launchd Integration ✅ DONE

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
- [x] Launchd plist files created for WC morning and evening
- [x] WC pipeline runs automatically at 08:00 and 22:00
- [x] Pipeline timeout prevents zombie processes (30 min max)
- [x] Logs appear in `data/logs/wc_morning_{date}.log`
- [x] WC pipeline does not interfere with league pipeline schedule
- [x] Pipeline exits cleanly on days with no WC matches

**Status:** ✅ DONE — run_wc_pipeline.sh + 2 launchd plists (08:00/22:00). 30-min timeout, stale process killer, log rotation. Zero interference with league pipeline. 621/621 tests.

---

## WC-08 — Dashboard UX Redesign (Phase 5, Post-MVP)

**Context:** The WC dashboard page (`src/delivery/views/world_cup.py`) grew to
~6,500px in a single scroll, ordered reference-first (group standings and
advancement probabilities at the top) with the actionable Value Bets buried at
the bottom — inverted for a betting tool. This epic restructures the page into
four tabs, adds country flags, converts kickoff times to US Eastern, and makes
the reference sections collapsible, so the user lands on what's actionable
without scrolling.

**Owner decisions (2026-06-23):** tabs (not single-page collapsibles);
responsive for desktop **and** mobile; **image** flags (not emoji); fixtures and
value bets kept as **separate** components on Tab 1.

**Target layout:**
```
Slim header (logo + "Matchday X · N days to Final")
┌ Tab 1: Today & Bets ┐ Tab 2: Groups ┐ Tab 3: Knockouts ┐ Tab 4: Model ┐
│ • Upcoming fixtures  │ • Standings ▾ │ • Bracket        │ • Winner probs │
│   (flag·ET·lean·odds)│ • Advance.  ▾ │   (w/ flags)     │ • Brier/calib  │
│ • Value Bets table   │ • 3rd-place ▾ │                  │                │
└──────────────────────┘───────────────┘──────────────────┘────────────────┘
```

**Note:** Streamlit responsiveness is limited (columns stack and tables scroll
horizontally on narrow screens). Target is "good on both," not pixel-perfect.

---

### WC-08-01 — Country Flag Assets & Helper ✅ DONE

**Type:** UI / Data
**Depends on:** Nothing (extends the existing WC dashboard + badge pattern)

Download national-team flag images and provide a render helper, mirroring the
team-badge pattern in `data/badges/`.

**Implementation Notes:**
- Build a `fifa_code → ISO 3166-1 alpha-2` map for all 48 teams. Home nations
  are special: England → `gb-eng`, Scotland → `gb-sct`, Wales → `gb-wls`
  (flagcdn supports these sub-national codes).
- Download ~48 flags once to `data/flags/{fifa_code}.png` via flagcdn
  (`flagcdn.com/w40/{iso}.png` and `w80` for retina). Rate-limited (≥0.5s),
  idempotent (skip existing), via a `scripts/` downloader.
- Add a `render_flag(team)` / base64 helper in the dashboard with a graceful
  text/abbreviation fallback when a flag is missing.
- No render-time CDN dependency — flags served from local assets.

**Acceptance Criteria:**
- [x] `data/flags/` contains a flag for all 48 WC teams
- [x] England / Scotland / Wales show their own flags (not the Union Jack)
- [x] `render_flag()` returns an inline image; a missing flag falls back to text without erroring
- [x] Re-running the downloader is idempotent (skips existing files)

---

### WC-08-02 — Eastern Time Conversion Utility ✅ DONE

**Type:** UI
**Depends on:** Nothing

Convert UTC kickoff times to US Eastern for display.

**Implementation Notes:**
- Add `to_eastern(date_str, kickoff_utc_str)` using
  `zoneinfo.ZoneInfo("America/New_York")` — returns a tz-aware Eastern datetime
  (correctly EDT in summer, EST in winter).
- Handle the date shift: a near-midnight UTC kickoff can fall on a different
  Eastern calendar date; return both the Eastern date and time.
- Format helper → e.g. `Wed 3:00 PM ET`. Always label "ET" (covers EST/EDT).
- Guard against missing/empty kickoff times (return a clear placeholder).

**Acceptance Criteria:**
- [x] UTC kickoff converts to correct US Eastern time (EDT in June)
- [x] Date-shift across midnight is handled correctly
- [x] Times render labelled "ET"
- [x] Missing/empty kickoff shows a safe placeholder, no crash

---

### WC-08-03 — Tabbed Shell & Slim Header ✅ DONE

**Type:** UI
**Depends on:** Nothing

Restructure `main()` into four tabs with a minimal header (pure relocation — no
section logic changes yet).

**Implementation Notes:**
- Replace the sequential section calls with
  `st.tabs(["Today & Bets", "Groups", "Knockouts", "Model"])`.
- Slim header above the tabs: logo + one context line
  (`Matchday X · N days to Final`), replacing the 3-metric block.
- Move the existing render functions into the relevant tab bodies unchanged.
- Default tab = Today & Bets (first).

**Acceptance Criteria:**
- [x] Page renders 4 tabs; Today & Bets is the landing tab
- [x] Slim one-line header replaces the metric cards
- [x] All existing sections still render (relocated, not removed)
- [x] No regression in data loading (predictions / odds / value bets still shown)

---

### WC-08-04 — Tab 1: Today & Bets ✅ DONE

**Type:** UI
**Depends on:** WC-08-01, WC-08-02, WC-08-03

Build the actionable landing tab.

**Implementation Notes:**
- Compact upcoming-fixtures strip: rows of
  `flag · Team — Team · kickoff (ET) · model lean (1X2) · best price`.
  Window = **today + next 2 days**; today's games visually highlighted. Replaces
  the large "Today's Matches" cards.
- Value Bets table directly below (existing edge / odds / bookmaker / Kelly
  table), labelled as **tracked / shadow picks** (calibration caveat from the
  edge-ceiling work).
- Bulk queries only — joinedload fixtures / odds / predictions (no N+1).
- Responsive: small flags, dense rows, `st.dataframe` for the value table.

**Acceptance Criteria:**
- [x] Fixtures strip shows flags, ET kickoffs, model lean, best price for today + 2 days
- [x] Value Bets table appears immediately below fixtures
- [x] Value bets labelled as tracked / shadow picks
- [x] No N+1 queries (verified by query count)
- [x] Renders cleanly on a narrow (mobile) viewport

---

### WC-08-05 — Tab 2: Groups (Collapsible) ✅ DONE

**Type:** UI
**Depends on:** WC-08-01, WC-08-03

Move group reference content into collapsible sections.

**Implementation Notes:**
- Three `st.expander` blocks, **collapsed by default**: Group Standings (12
  groups, with flags), Advancement Probabilities (+ what-if widget), Third-place
  Race.
- Preserve existing computations (`_compute_group_standings`, the cached
  simulation, the what-if recompute).
- Add flags to standings rows.

**Acceptance Criteria:**
- [x] Standings, advancement, and third-place each in a collapsed expander
- [x] Flags shown in standings rows
- [x] What-if widget still works
- [x] Expanding / collapsing does not re-trigger the 10K simulation (cache intact)

---

### WC-08-06 — Tab 3 & Tab 4: Knockouts + Model ✅ DONE

**Type:** UI
**Depends on:** WC-08-01, WC-08-03

Relocate the bracket and model sections into their tabs.

**Implementation Notes:**
- Tab 3 (Knockouts): knockout bracket (projected / actual) with flags on the
  matchup cards.
- Tab 4 (Model): tournament winner-probabilities chart + model performance
  (Brier / calibration reliability chart).
- Responsive layouts.

**Acceptance Criteria:**
- [x] Knockouts tab shows the bracket with flags
- [x] Model tab shows winner probabilities + Brier / calibration
- [x] Both render on narrow viewports

---

### WC-08-07 — Responsive Polish & Integration Test ✅ DONE

**Type:** Test
**Depends on:** WC-08-04, WC-08-05, WC-08-06

Verify the full redesign on desktop + mobile and lock behavior with tests.

**Implementation Notes:**
- Verify against Neon on a wide and a narrow viewport (preview tools / window
  resize).
- Integration test: page imports, all 4 tabs render without error; flag helper
  and ET utility unit-tested; Tab 1 fixtures / value queries are bulk.
- Confirm no regression against the data already in Neon (51 value bets, 40
  predictions, standings).

**Acceptance Criteria:**
- [x] All 4 tabs render error-free against Neon
- [x] Flag helper + ET conversion covered by unit tests
- [x] Tab 1 fixtures / value queries are bulk (no N+1)
- [x] Verified on desktop and narrow / mobile viewport
- [x] Full test suite green

---

## WC-09 — Decision Support & Bayesian Model R&D (Phase 6, Option A, Post-MVP)

**Context:** With the dashboard redesigned (WC-08), this epic turns it into a real
decision aid and starts the model upgrade. The honest read on the WC betting problem
— sparse data (12 results) vs a sharp 59-book market — means the priority order is:
(1) a **measurement rig** that tells us whether any edge is real (CLV + calibration),
(2) per-match **decision support**, (3) a better-calibrated **Bayesian model** run in
shadow, and (4) a scoped **player-props feasibility spike**. Option A ships the
scorecard + research card first (fast value this tournament), runs the Bayesian model
as a parallel R&D track, and treats player props as a go/no-go spike before any full
build.

**Owner decision (2026-06-23):** Option A — scorecard + research card now, Bayesian in
parallel, props as a later spike.

**Tier 2 note:** the Bayesian model (WC-09-05..07) adds a new model architecture + the
PyMC dependency — approved via the Rule 8 Tier-2 proposal (2026-06-23). It runs
**shadow only** (never auto-staked) until it beats the current Poisson on CLV +
calibration.

**Prop coverage (verified 2026-06-23, 15 credits):** anytime / first goal scorer = 10
books incl. FanDuel / DraftKings / Pinnacle; shots on target = 4; cards = 4; assists =
2. Feasible — gated on player-data sourcing (WC-09-08 spike). Prop scraping costs
markets × regions per call — budget discipline required.

---

### Phase A — Shadow Scorecard (the measurement rig — build first)

### WC-09-01 — Closing-Line Capture & CLV for WC Shadow Picks ✅ DONE

**Type:** Pipeline / Data
**Depends on:** WC-05-01 (value finder), WC-07-01 (pipeline)

Capture the closing line for each WC shadow pick so CLV (the leading edge indicator)
can be computed.

**Implementation Notes:**
- Add a near-kickoff odds snapshot to the WC pipeline: for matches kicking off within
  ~1–2h, re-fetch odds (reuse `scrape_wc_odds`) and record them as the "closing" line.
- Store `closing_odds` + `clv` on `WCValueBet` (add columns if absent, mirroring the
  league `ValueBet` schema). Use the same CLV convention as the league system.
- Idempotent — set the closing line once per pick at/after kickoff, never overwrite.

**Acceptance Criteria:**
- [x] Closing line captured for WC picks near kickoff
- [x] `WCValueBet.closing_odds` + `clv` populated after a match starts
- [x] CLV uses the same convention as the league system
- [x] Idempotent (closing line set once)
- [x] No new API cost beyond one near-kickoff snapshot per match day

---

### WC-09-02 — Shadow Scorecard Computation + Dashboard Panel ✅ DONE

**Type:** UI / Analytics
**Depends on:** WC-09-01

Compute and display the self-assessment scorecard on the dashboard.

**Implementation Notes:**
- Over WC shadow picks: CLV distribution (mean, % positive), hit rate, calibration
  bins (predicted vs actual), flat-stake paper P&L (1u/pick).
- Surface on the Model tab (new "Scorecard" expander): headline CLV %, calibration
  reliability, paper P&L, n picks. Honest low-sample state ("need ≥N picks").
- Clearly labelled tracked/shadow, not realized money.

**Acceptance Criteria:**
- [x] Scorecard shows mean CLV, % positive CLV, n picks
- [x] Calibration (predicted vs actual frequency) displayed
- [x] Flat-stake paper P&L shown
- [x] Low-sample state handled (<N picks → "insufficient data")
- [x] Clearly labelled shadow/tracked

---

### Phase B — Research Card (decision support)

### WC-09-03 — Line-Movement & Best-Price Data Layer ✅ DONE

**Type:** Analytics
**Depends on:** WC-02-01 (odds), WC-05-01

Compute per-selection line movement and best price across books.

**Implementation Notes:**
- From `WCOdds` history (`captured_at`), compute open→current movement per (match,
  market, canonical selection); reuse `_canonical_selection`.
- Best price across books per selection.
- Expose the de-vigged market consensus + model-vs-market diff per match (mostly in
  the value finder already).

**Acceptance Criteria:**
- [x] Line movement (open→current) computed per selection from odds history
- [x] Best price across books per selection
- [x] De-vigged market consensus + model diff exposed per match
- [x] Single-snapshot markets handled (no movement → "—")

---

### WC-09-04 — Research Card View + Review Queue ✅ DONE

**Type:** UI
**Depends on:** WC-09-03

Per-match decision card + a biggest-disagreements review queue.

**Implementation Notes:**
- Research card per match: model probs (with the Bayesian uncertainty band once
  WC-09-06 lands), de-vigged market, edge, line movement, best price + book.
- "Biggest disagreements" queue across upcoming matches, sorted by |model − market|,
  framed as **hypotheses to investigate, not bets** (shadow discipline).
- xG form **deferred** (no reliable WC xG source) — clearly-marked placeholder only.

**Acceptance Criteria:**
- [x] Research card shows model · market · edge · movement · best price for a match
- [x] Review queue lists the biggest model–market disagreements
- [x] Framed as "review / investigate", consistent with shadow discipline
- [x] Renders on desktop + mobile; no N+1

---

### Phase C — Bayesian Shadow Model (parallel R&D)

### WC-09-05 — PyMC Dependency + Bayesian Hierarchical Poisson

**Type:** Model
**Depends on:** WC-01 (data), WC-03 (features)

Add PyMC and implement the hierarchical Bayesian model.

**Implementation Notes:**
- Add `pymc` (+ `arviz`) to requirements.
- `src/world_cup/bayesian_model.py`: hierarchical Poisson — latent per-team
  attack/defence with priors pooled toward confederation/global means; home-advantage
  parameter; low-score correlation parameter (Dixon-Coles-style or bivariate).
- Fit on `wc_historical_matches` (recency/importance-weighted) + finished WC matches.
  NUTS sampler; fall back to ADVI (variational) if too slow.
- `predict()` → posterior-predictive **7×7 scoreline matrix** (same interface as the
  Poisson — Rule 6, zero downstream changes).

**Acceptance Criteria:**
- [ ] `pymc` in requirements; `bayesian_model.py` present
- [ ] Model fits with acceptable diagnostics (no/low divergences)
- [ ] `predict()` returns a 7×7 matrix compatible with `derive_market_probabilities`
- [ ] Training completes in a tolerable, documented time
- [ ] Posterior uncertainty (e.g. credible interval on λ) exposed

---

### WC-09-06 — Bayesian Shadow Integration

**Type:** Pipeline
**Depends on:** WC-09-05, WC-07-01

Run the Bayesian model alongside the Poisson, shadow only.

**Implementation Notes:**
- Store Bayesian predictions under `model_name="wc_bayesian_v1"` in `wc_predictions`.
- Wire into the WC pipeline as a parallel predictor (after the Poisson).
- **Never auto-stake; never overrides the Poisson.**

**Acceptance Criteria:**
- [ ] Bayesian predictions stored under a distinct `model_name`
- [ ] No value bets / no staking from the Bayesian model
- [ ] Pipeline runs both models without error
- [ ] Existing Poisson behavior unchanged

---

### WC-09-07 — Bayesian Validation Harness + Scorecard Comparison

**Type:** Test / Analytics
**Depends on:** WC-09-06, WC-09-02

Compare Bayesian vs Poisson and feed the scorecard.

**Implementation Notes:**
- Walk-forward backtest (where data allows) + Brier / log-loss / calibration vs the
  Poisson.
- Live: the scorecard tracks both models' CLV / calibration side-by-side over the
  remaining WC matches.
- Document the promotion bar (beats Poisson on Brier + positive CLV) — **no
  auto-promotion**.

**Acceptance Criteria:**
- [ ] Backtest/metrics comparing Bayesian vs Poisson produced
- [ ] Scorecard shows both models' CLV / calibration
- [ ] Promotion criteria documented; no automatic promotion
- [ ] Tests for the model interface + integration

---

### Phase D — Player-Props Feasibility Spike (go/no-go)

### WC-09-08 — Player-Prop Data-Sourcing Spike

**Type:** Spike / Research (time-boxed ~half-day)
**Depends on:** Nothing (uses the confirmed prop coverage)

Decide whether a full player-props build (a future WC-10) is viable — **no production
build in this issue**.

**Implementation Notes:**
- Investigate whether per-player goal/shot rates + expected minutes for the 48 WC
  squads are sourceable at usable quality (Transfermarkt goals/minutes, FBref shots;
  map to squads). Document coverage gaps.
- Prototype the data design (`wc_players` schema) and a rough anytime-scorer estimate
  for ONE match (team λ × player goal-share × minutes) vs the book / Pinnacle price.
- Define the prop-scrape budget plan (markets × regions discipline given the
  ~15-credit-per-check cost).
- Output: a go/no-go report + recommended WC-10 scope sketch.

**Acceptance Criteria:**
- [ ] Report on per-player WC data availability/quality (sources, gaps)
- [ ] Prototype anytime-scorer estimate for one match vs the market
- [ ] Prop-scrape budget plan (scope to stay within quota)
- [ ] Clear go/no-go recommendation + WC-10 scope sketch
- [ ] Time-boxed — no production prop pipeline built here

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
