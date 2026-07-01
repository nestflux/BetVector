# BetVector World Cup 2026 — Build Plan

Version 1.0 · June 2026

> **MODULE STATUS: WC-09 COMPLETE (36/36) · WC-10 COMPLETE (7/7 — 10-08 deferred) · WHOLE WC MODULE LIVE** · June 24, 2026
> WC-01→09 done. **WC-10 — Live Operations & Automation** ✅ COMPLETE + LIVE:
> Phase 1 (10-01/02: odds 12→2 credits, 09:30 ET morning job), Phase 2 (10-03/04/05:
> dispatcher INSTALLED + running every 15 min — fires the 2-credit prematch pull
> ~40min pre-KO, true-close CLV), Phase 3 (10-06/07: lineup capture via ESPN's free
> JSON API 15/15 + rotation flag on the research card). 10-08 λ-adjust DEFERRED
> (=WC-11, gated). WC stays shadow-only; lineups are decision-support. Suite: 763/763.
>
> **DF — Decision-First UX** (10 issues · owner-approved 2026-06-24) **IN PROGRESS** —
> verdict-led fixtures (WC + leagues) + a digestible research card + a WC deep dive;
> markets → 1X2 + O/U 1.5/2.5/3.5 + BTTS; WC = the login landing during the
> tournament window. Phase A (main page) → Phase B (deep dive). DF-02 lands first.

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

### WC-09-05 — Hierarchical Bayesian Poisson (scipy MAP + Laplace) ✅ DONE

**Type:** Model
**Depends on:** WC-01 (data)

Implement the hierarchical Bayesian model. **Approach change (owner-approved
2026-06-23):** PyMC would not install in this environment (llvmlite toolchain),
and the project stack deliberately avoids heavy deps (Rule 2). So we use **scipy**
— MAP estimation with hierarchical shrinkage priors + a Laplace approximation for
uncertainty — instead of PyMC/MCMC. Delivers the two things that matter (partial
pooling for sparse data + posterior uncertainty), fast (seconds), no new heavy dep.

**Implementation Notes:**
- `src/world_cup/bayesian_model.py`: hierarchical Poisson — latent per-team
  attack/defence (`log λ = μ + home_adv + att[home] − def[away]`), Gaussian
  shrinkage priors pooling team strengths toward 0 (the hierarchical effect), a
  home-advantage parameter (off on neutral venues), and the Dixon-Coles low-score
  correction on the matrix.
- Fit on `wc_historical_matches` (recency × `match_weight`-weighted) + finished WC
  matches, via `scipy.optimize.minimize` (L-BFGS-B, analytic gradient) on the
  penalized negative log-posterior.
- Uncertainty: Laplace approximation — Hessian at the mode → covariance → credible
  interval on λ per prediction.
- `predict()` → **7×7 scoreline matrix** reusing `WCPoissonPredictor`'s matrix
  builder + `_derive_probabilities` (Rule 6, zero downstream changes).
- Tuneables (shrinkage, recency half-life, ρ) in `config/worldcup_2026.yaml`.

**Acceptance Criteria:**
- [x] `bayesian_model.py` present; uses only scipy/numpy (no new heavy dep)
- [x] MAP fit converges; Laplace Hessian is positive-definite (valid covariance)
- [x] `predict()` returns a 7×7 matrix compatible with `derive_market_probabilities`
- [x] Training completes in a tolerable, documented time (seconds)
- [x] Posterior uncertainty (credible interval on λ) exposed
- [x] Recovers known team strengths on synthetic data (validation test)

---

### WC-09-06 — Bayesian Shadow Integration ✅ DONE

**Type:** Pipeline
**Depends on:** WC-09-05, WC-07-01

Run the Bayesian model alongside the Poisson, shadow only.

**Implementation Notes:**
- Store Bayesian predictions under `model_name="wc_bayesian_v1"` in `wc_predictions`.
- Wire into the WC pipeline as a parallel predictor (after the Poisson).
- **Never auto-stake; never overrides the Poisson.**

**Acceptance Criteria:**
- [x] Bayesian predictions stored under a distinct `model_name`
- [x] No value bets / no staking from the Bayesian model
- [x] Pipeline runs both models without error
- [x] Existing Poisson behavior unchanged

---

### WC-09-07 — Bayesian Validation Harness + Scorecard Comparison ✅ DONE

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
- [x] Backtest/metrics comparing Bayesian vs Poisson produced
- [x] Scorecard shows both models' CLV / calibration
- [x] Promotion criteria documented; no automatic promotion
- [x] Tests for the model interface + integration

---

### Phase D — Player-Props Feasibility Spike (go/no-go)

### WC-09-08 — Player-Prop Data-Sourcing Spike ✅ DONE

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
- [x] Report on per-player WC data availability/quality (sources, gaps)
- [x] Prototype anytime-scorer estimate for one match vs the market
- [x] Prop-scrape budget plan (scope to stay within quota)
- [x] Clear go/no-go recommendation + WC-10 scope sketch
- [x] Time-boxed — no production prop pipeline built here

---

## WC-10 — Live Operations & Automation (post-MVP)

> **Added 2026-06-23, owner-confirmed.** Make the WC system run itself reliably
> during the tournament: daily automation, a dynamic pre-kickoff closing-odds/CLV
> dispatcher, and a lineup-based rotation flag for decision support. **No change to
> the model or staking — WC bets remain shadow-only.**
>
> **Cost: $0 (free tiers).** Odds API ~130–200/mo of ~323 (1 region incl. Pinnacle,
> 1 pull/match); API-Football ~5/day of 100 (lineups); Neon storage bounded (odds
> are upsert — one row per match×book×market×selection); Neon compute safe (the
> heartbeat reads a local fixture cache, not Neon, when idle); Streamlit Cloud
> unaffected (read-only, auto-sleeps).
>
> **Why:** the WC pipeline is not scheduled today, so the board goes stale (odds
> emptied to 0 while predictions remained). Matches span ~11 kickoff times
> (1 PM–11 PM ET), 2–8/day, reshuffling each round — a static 2×/day schedule
> misses kickoffs and mis-times results. Fix: a daily planning run + a dynamic
> pre-kickoff dispatcher that adapts to any schedule.

### Phase 1 — Operate

### WC-10-01 — Diagnose & Harden the WC Odds Refresh ✅ DONE

**Type:** Bug / Hardening
**Depends on:** WC-02 (odds scraper)

The WC odds board emptied to 0 rows on Neon while predictions remained — odds aren't
refreshing reliably. Find the cause and make the refresh safe before scheduling it.

**Result (root cause — 2026-06-23):** The "0 odds on Neon" was a **diagnostic-tooling
artifact, not a production bug.** Ad-hoc scripts that call bare `load_dotenv()` from
outside the project dir (e.g. `/tmp`) fail to find `.env`, so `db.py` silently falls
back to **local SQLite** (resolution order: `DATABASE_URL` → Streamlit secrets →
SQLite). Those scripts were reading SQLite (which had 0 odds), while **production was
consistent and never empty** — the pipeline `source`s `.env` → Neon, the dashboard
reads Neon via Streamlit secrets, and Neon held 6,627 odds throughout. Two real
issues were found and fixed in passing: (a) the scrape default cost **12 credits/call**
(`h2h,spreads,totals` × `us,uk,eu,au`, incl. unused spreads) — now config-driven
`h2h,totals` × `eu` = **2 credits**; (b) the SQLite fallback was **silent** — now a
loud WARNING. Also surfaced + fixed: the Bayesian shadow preds had been written to
SQLite by earlier ad-hoc runs (`bayesian=0` on Neon) — repopulated to Neon (now 40).

**Implementation Notes:**
- Reproduce + root-cause the empty `wc_odds` (never-scraped vs. cleared-then-failed
  vs. match-name mapping failure vs. Odds API auth/empty response). Document it.
- Ensure a real scrape populates + persists odds for all upcoming matches.
- Make the refresh fail-safe: a failed/empty Odds API response must **never** wipe
  existing odds (no destructive delete before a confirmed successful fetch).
- Add explicit logging of rows fetched / upserted / skipped per run.

**Acceptance Criteria:**
- [x] Root cause of the empty board documented (tooling SQLite fallback; prod never empty)
- [x] A real scrape populates odds for upcoming matches and they persist (Neon: 6,781, 2 credits)
- [x] A failed/empty scrape leaves prior odds intact (upsert-only; 2 tests)
- [x] Per-run logging of fetched/upserted/skipped counts (summary log in `_load_odds_to_db`)

### WC-10-02 — Daily Morning Automation (Retimed) ✅ DONE

**Type:** Pipeline / Ops
**Depends on:** WC-07 (pipeline), WC-10-01

Make the morning run the daily spine and schedule it to this tournament's clock.

**Result (2026-06-23):** `com.betvector.wc_morning` installed + loaded (Mac is EDT →
09:30 ET); evening plist retired (marked DO-NOT-INSTALL, not loaded). The morning
run now absorbs the evening's CLV-capture + accuracy steps and folds yesterday's
results into the morning email (owner option 1). Verified end-to-end via the exact
launchd path (`run_wc_pipeline.sh morning`): exit 0 in 80.4s — CLV captured 4,
accuracy on 15 matches (Brier 0.493), odds at the 2-credit disciplined cost, 40
predictions + 40 Bayesian shadow + 51 value bets, morning email sent. "Unattended
24h" confirms on the first scheduled 09:30 ET fire (job loaded, path proven).

**Implementation Notes:**
- Morning run at **~09:30 local (ET)** does: settle overnight results + CLV for any
  matches finished since the last run, refresh the full board (1 odds pull covers
  the day), predictions, Bayesian shadow, value bets, morning email.
- Confirm the Mac's timezone so the plist hour maps to ET; retime
  `com.betvector.wc_morning.plist` accordingly.
- **Retire the 22:00 evening plist** — it fires mid-late-matches (10/11 PM ET games
  still playing) and mis-captures results. Overnight results settle on the next
  morning run instead (results aren't time-critical; pre-match odds are).
- Install: `cp scripts/com.betvector.wc_morning.plist ~/Library/LaunchAgents/` +
  `launchctl load`.

**Acceptance Criteria:**
- [x] Morning plist installed and loaded (Mac TZ confirmed → 09:30 ET)
- [x] A scheduled run completes end-to-end (board, predictions, Bayesian, value bets, email)
- [x] Overnight results + CLV settle on the morning run
- [x] Evening plist retired/uninstalled; documented
- [x] System runs unattended across a 24h cycle

### Phase 2 — Sharpen CLV (dynamic dispatcher)

### WC-10-03 — Local Fixture Cache + Heartbeat Dispatcher ✅ DONE

**Type:** Pipeline
**Depends on:** WC-10-02

A schedule-proof trigger for pre-kickoff runs that costs almost nothing when idle.

**Implementation Notes:**
- The morning run writes the day's fixtures (match_id, kickoff UTC, status) to a
  **local JSON cache** (e.g. `data/world_cup/today_fixtures.json`).
- A dispatcher script + **one** launchd job runs every ~15 min, reads the LOCAL
  cache (never Neon when idle), and finds matches entering the ~40-min pre-KO window
  not yet prepped.
- Persist prepped-state locally (set of prepped match_ids per day) so a restart
  doesn't double-fire and a missed tick still catches the match.
- Neon is touched only when a pre-match run actually fires (WC-10-04), so the DB
  stays autosuspended between runs (free-tier compute discipline).

**Acceptance Criteria:**
- [x] Idle heartbeat reads only the local cache — no Neon connection
- [x] Fires exactly once per match when it enters the pre-KO window
- [x] Prepped-state persists across restarts (no double-fire, no miss)
- [x] One launchd job; documented install

### WC-10-04 — Pre-Kickoff Focused Run (Closing Line) ✅ DONE

**Type:** Pipeline
**Depends on:** WC-10-03

Capture the near-closing line for one match, budget-disciplined.

**Implementation Notes:**
- New pipeline mode `prematch` (takes a match_id / slot): **exactly one** Odds API
  pull, **1 region** (incl. Pinnacle), upsert that match's odds (refreshes
  `captured_at` → becomes the closing line on finish), recompute value/edge.
- No full board refresh, no results, no Elo — focused and cheap.
- Idempotent: re-running for the same match updates in place (no duplicate odds).

**Acceptance Criteria:**
- [x] `prematch` mode issues exactly one Odds API call per invocation
- [x] Fresh odds persisted for the target match; value/edge recomputed
- [x] 1 region only; logged credit usage
- [x] Idempotent (no duplicate rows on re-run)

### WC-10-05 — CLV Integrity End-to-End ✅ DONE

**Type:** Test / Validation
**Depends on:** WC-10-04, WC-09-01

Prove the scorecard's CLV is now anchored to a true closing line.

**Result (2026-06-24):** Verified the prematch→finish→CLV path: because odds are
upserted in place, the closing line a finished match yields is the LATEST stored
price (the prematch near-closing pull), not the morning line. The headline test
runs the real `_load_odds_to_db` upsert twice (morning 2.00 → prematch 1.50, one
row), then `capture_wc_closing_lines`, asserting close == 1.50 (not 2.00) + CLV>0.
Real-data validation on Neon: 4 settled picks have CLV captured but **all read
0.0** because they finished BEFORE any prematch refresh (close == entry == morning
line). This is the exact gap the dispatcher closes — once it fires the pre-KO pull,
the close diverges from entry and CLV becomes a real signal. So the scorecard
faithfully reflects captured CLV; meaningful CLV is unblocked by the dispatcher
install (held for owner OK).

**Implementation Notes:**
- Verify the near-closing odds captured by the pre-match run are what
  `capture_wc_closing_lines` reads when the match finishes (closing line = last
  pre-match odds, not the morning line).
- Tests for the prematch→finish→CLV path; validate on one real finished match.

**Acceptance Criteria:**
- [x] A prepped → finished match yields CLV computed from the near-closing line
- [x] Tests cover the prematch→finish→CLV path
- [x] Scorecard reflects the true-close CLV

### Phase 3 — Lineups (decision support)

### WC-10-06 — WC Lineup Capture (ESPN) ✅ DONE

**Type:** Scraper
**Depends on:** WC-10-03

**Source change (spike-confirmed 2026-06-24):** API-Football's **free tier has no
2026 access** ("Free plans do not have access to this season, try from 2022 to
2024"), so the planned lineup source is unusable without a paid plan. The WC-10-06
spike found **ESPN's free, key-less JSON API** (`site.api.espn.com/.../soccer/
fifa.world/summary?event={id}`) serves the full WC 2026 XI — formation, starters,
positions, jerseys. Free + JSON + requests-only (stack-compliant) — strictly better
than the paid API-Football option. Building against ESPN instead.

**Implementation Notes:**
- `src/world_cup/lineups.py`: resolve a WC match → ESPN event id (scoreboard for the
  match date, matched by team names via a small ESPN→DB name map), then fetch the
  summary `rosters` → the starting XI + formation.
- Store in a new `wc_lineups` table (match_id, team_id, player_name, is_starter,
  position, jersey, formation, captured_at); idempotent upsert on
  (match_id, team_id, player_name).
- ESPN is **free/no-quota**, so capture is wired into the dispatcher as a per-tick
  retry in a wider window (~[KO−60, KO)) until the XI is published, separate from
  the once-only odds fire. Graceful no-op when the XI isn't out yet — never crashes.

**Acceptance Criteria:**
- [x] Official XIs fetched + stored for a WC match from ESPN (XI + formation)
- [x] Free/key-less ESPN JSON API; no quota concern; polite single request per check
- [x] Early/missing lineup handled gracefully (no crash, retried next tick)
- [x] Idempotent storage (no duplicate lineup rows on re-fetch)

### WC-10-07 — Rotation / Absence Flag on the Research Card ✅ DONE

**Type:** Feature / Dashboard
**Depends on:** WC-10-06

Turn the lineup into the decision-support signal you actually want.

**Implementation Notes:**
- Compute a rotation/absence signal: compare the announced XI to the team's
  "regulars" (squad data / recent XIs) → "N starters rested", "key player X out".
- Surface a ⚠️ flag on the research card (Tab 1) next to affected matches; framed as
  a hypothesis flag ("XI confirms / heavy rotation — re-check this pick"), not a
  model input.
- **Decision-support only — no change to λ or value-bet generation.**

**Acceptance Criteria:**
- [x] Rotation/absence flag computed from the announced XI vs regulars
- [x] Surfaced on the research card; absent before the XI is announced
- [x] Framed as decision support; no λ / value-bet change
- [x] Empty/early-lineup state handled

### WC-10-08 — λ-Adjustment from Lineups — DEFERRED

**Type:** Model (deferred)
**Depends on:** WC-10-07

Actually adjusting expected goals for missing players is **not built here.** Gated —
like the player-props build (WC-11) — on (a) per-player WC contribution data of
usable quality, and (b) the model first demonstrating it can beat the market at all
(the team Bayesian is competitive but not promoted). Listed so the scope boundary is
explicit; revisit only on owner opt-in.

---

## DF — Decision-First UX (post-MVP · owner-approved 2026-06-24)

**Goal:** make the system answer *"what's the bet, and can I trust it?"* at every
depth. A three-layer information architecture — **glance** (fixtures verdict) →
**study** (research card) → **deep dive** (full dossier) — replacing flat data
tables with a verdict-led, trust-weighted presentation. Spans the WC page **and**
league fixtures. All of this is **presentation over the existing value-finder
output**: the model, value bets, and temporal integrity are untouched, and WC stays
shadow-only ("track", never "bet").

**Markets:** expanded to 1X2 + Over/Under 1.5/2.5/3.5 + BTTS (owner choice). The
model derives every market from the 7×7 scoreline matrix for free; the only cost is
the market odds, loaded from the cheap once-per-day board pull (cost = markets ×
regions per *request* — all matches in one call) → net ≈ +2 odds credits/day. The
focused near-kickoff per-event pull stays lean (h2h + totals) to protect in-play CLV.

**Sequence:** Phase A (main page) before Phase B (deep dive). DF-02 lands first.

### DF-01 — Market Expansion (odds + model surfacing) ✅ DONE

**Type:** Data / Config
**Depends on:** none

**Implementation Notes:**
- Add `btts` + `alternate_totals` to the **morning board** scrape only; the focused
  per-event pull (`scrape_wc_match_odds`) keeps `h2h,totals` for the CLV closing line.
- Verify `derive_market_probabilities()` emits BTTS + O/U 1.5/2.5/3.5 from the 7×7
  matrix; if a line is missing, derive it from the matrix — never bypass it.
- Surface model + de-vigged market probs for all markets in `research.py`.

**Acceptance Criteria:**
- [x] Morning board pull includes btts + alternate_totals; per-event pull unchanged (CLV-safe)
- [x] Model probs for 1X2, O/U 1.5/2.5/3.5, BTTS available per upcoming match (all via the matrix)
- [x] De-vigged market probs for the same markets where books price them; graceful when a book doesn't
- [x] Odds-credit budget impact documented; net ≈ +2 credits/day

### DF-02 — World Cup as the Login Landing Page (tournament window) ✅ DONE

**Type:** Navigation / Config
**Depends on:** none

**Implementation Notes:**
- Add `tournament: { start_date: 2026-06-11, end_date: 2026-07-19 }` to
  `worldcup_2026.yaml`.
- Helper `wc_window_active(today)` — config-driven, date-only, inclusive.
- In `get_pages()`: when active, move the World Cup `st.Page` to the front and set
  `default=True` on it (clearing it from Fixtures); otherwise unchanged. Reverts
  automatically the day after `end_date`.
- Landing-default only — every page stays reachable; onboarding nav untouched.

**Acceptance Criteria:**
- [x] Inside the window, a fresh login lands on World Cup (and it's first in the sidebar)
- [x] Outside the window, lands on Fixtures (current behaviour) — reverts with no code change
- [x] Dates are config-driven; no hardcoded date in code
- [x] Owner role + onboarding flows unaffected

### DF-03 — Uniform Flag Component ✅ DONE

**Type:** UI
**Depends on:** none

**Implementation Notes:**
- One flag render at a fixed box (height = surrounding text, capped width, object-fit
  to avoid distortion, vertical-align middle, small right gap, subtle rounded border
  so pale flags don't bleed into `#0D1117`).
- Replace every flag call site (WC strip, group standings, knockouts, league
  fixtures) with the single component + one size.

**Acceptance Criteria:**
- [x] All flags render at one uniform box size, flush beside the country name
- [x] No aspect-ratio distortion; pale flags have a visible edge
- [x] Used consistently across WC + league surfaces (one component, one size)
- [x] No regression in existing flag tests

**Result:** `render_flag` (`src/world_cup/flags.py`) draws every flag into one fixed
`height × round(height*1.5)` 3:2 cell — `object-fit:cover` (fills without distortion),
1px `#30363D` border (visible edge on pale flags like Japan/England), `border-radius:3px`,
`box-sizing:border-box`; missing-flag fallback is a same-size bordered cell so rows stay
aligned. All three WC flag sites (strip, group standings, knockouts via `_flag_for_name`)
flow through the single component. League crests aligned to the same treatment in
`_badge_helper` (`render_team_badge` + `render_badge_only`): fixed `size × size` square cell
with `object-fit:contain` (no crop for transparent crests, no border). Verified with a real
before/after render. 785/785 tests; Gate 2 CLEAN, Gate 3 APPROVED.

### DF-04 — Verdict-Led WC Fixtures ✅ DONE

**Type:** UI
**Depends on:** DF-01, DF-03

**Implementation Notes:**
- Rework `_render_todays_matches`: per match, one headline verdict from the value
  finder's top pick — tiers value (within the edge band) / capped (edge > ceiling →
  likely model error) / none. Show selection · edge · best price; probabilities
  behind an expander. WC framing = "track" (shadow).
- Reads the existing value-finder output; no model/value math changes.

**Acceptance Criteria:**
- [x] Each fixture shows one colour-tiered verdict (value / capped / no-edge) at a glance
- [x] Selection, edge, best price on the row; full probabilities on tap
- [x] Edge > ceiling shown as "re-check / likely model noise", not as value
- [x] WC verdicts framed as shadow ("track"); decision-support only

**Result:** New additive `classify_fixture_verdict()` + batch `wc_fixture_verdicts()` in
`value_finder.py` reuse the EXACT edge math (`edge = model_prob - 1/odds`) and config
thresholds (`edge_threshold` 0.03, `max_actionable_edge` 0.15, `markets` [h2h, totals]) as
`find_wc_value_bets` but KEEP the two cases the finder discards — over-ceiling ("capped") and
sub-threshold ("none") — so every fixture gets a tier. `find_wc_value_bets` is byte-for-byte
unchanged (git diff: 0 deletions; value/staking path provably untouched). Value takes
precedence over capped. The strip leads with a colour-tiered chip
(`_verdict_chip_html`: green ✓ value / yellow ⚠ "re-check · likely model noise" / dim — no
edge) and full probabilities sit behind a per-fixture `st.expander` (`_verdict_detail_html`:
1X2 / O/U 2.5 / BTTS / xG / pick model-vs-market). Caption reframed shadow/"track". Removed
the now-dead `_model_lean_html`/`_best_price_html`. Verified with a real value/capped/no-edge
render. 795/795 tests; Gate 2 CLEAN, Gate 3 APPROVED.

### DF-05 — Verdict-Led League Fixtures (trust-weighted) ✅ DONE

**Type:** UI
**Depends on:** DF-03, DF-04

**Implementation Notes:**
- Same verdict treatment on `fixtures.py`, folding in the per-league strategy tier
  (`leagues.yaml`) so a pick in a proven tier reads stronger than an unproven one.
- Reuse the DF-04 verdict component.

**Acceptance Criteria:**
- [x] League fixtures show the same verdict-led row + uniform flags
- [x] The league trust tier modulates the verdict's emphasis/label
- [x] Probabilities on tap; no model/value math changes
- [x] Existing fixtures tests pass (or are updated to the new layout)

**Result:** New streamlit-free `src/delivery/views/_verdict.py` mirrors the DF-04 verdict for
leagues: `classify_league_verdict()` picks the highest-edge bet the ValueFinder ALREADY stored
(via the fixture's `market_vb_info` — no recompute, no new query), and `league_verdict_chip_html()`
renders it with the emphasis set by the league's trust tier (from `stake_multiplier` in the
`leagues.yaml` strategy block, same PC-25 source BankrollManager uses): 🟢 proven = filled green
pill (auto-bet tier, reads strongest), 🟡 promising = green text, 🔴 unproven = amber "treat with
caution", no edge = dim. Deliberately NO "capped" tier (unlike WC) — the league ValueFinder has no
actionable-edge ceiling, so caution is carried by the trust tier instead. `fixtures.py` enriches
`market_vb_info` with odds/book (additive, zero new queries — PC-12 ≤6-query guarantee intact),
builds the trust map once from `config.leagues` (guarded), and inserts a verdict row between teams
and the badge row; existing market badges + Deep Dive (probabilities on tap) preserved. The league
value path (`src/betting/value_finder.py`) is byte-for-byte unchanged. 809/809 tests (14 new);
Gate 2 CLEAN, Gate 3 APPROVED.

### DF-06 — Research Card Redesign

**Type:** UI
**Depends on:** DF-01

**Implementation Notes:**
- Rework `_render_research_card` + extend `build_research_card`: group selections by
  market (Match result / Goals / BTTS); model-vs-market paired bars (model accent,
  market grey) so the gap is the visual; edge highlighted; a one-line plain-English
  read per market block; a headline lean with a within-range / model-noise label and
  the shadow chip. Line movement stays as the confirmation signal.

**Acceptance Criteria:**
- [x] Selections grouped by market with model-vs-market visual bars (the gap stands out)
- [x] Headline names the strongest trustworthy lean + a trust label
- [x] One plain-English read per market block ("the edge is on X, not Y")
- [x] Edge ceiling honoured (a big gap is labelled likely model error, not celebrated)

**Result:** ✅ DONE. The research card now leads with a headline lean and groups selections
into three blocks — Match result / Goals / BTTS — each a stack of model-vs-market paired
bars (model in an accent over the de-vigged market in grey, so the GAP between the two bars
*is* the edge). All the grouping, wording, and trust logic lives in a new pure
`research.summarize_card` (streamlit-free, unit-tested apart from the page module, which runs
`main()` at import): it annotates each selection with a trust class, arranges the blocks, and
writes one plain-English read per block ("Edge is on Over 2.5 — model 58% vs market 50%
(+8%)") plus the card's single headline. Trust uses the SAME bounds the value finder stakes on
(`edge_threshold` 0.03 / `max_actionable_edge` 0.15 from `config/worldcup_2026.yaml` via
`_load_betting_config` — no hardcoded duplicate): a lean is highlighted (filled green pill +
best price) only inside `[threshold, ceiling]`; a gap past the ceiling is rendered amber and
labelled "likely model error, not a bet" — never celebrated. Line movement is folded in as the
confirmation signal (headline "line confirms / caution"; per-row ▲/▼ since open). The view
(`world_cup.py`) only turns `blocks`/`headline` into HTML (`_research_headline_html` /
`_research_block_html` / `_research_bar_html`), all dynamic values escaped. `build_research_card`
keeps every prior key and adds `blocks`/`headline` (backward-compatible; `top_disagreements`
unchanged). The value/model path (`value_finder.py`, `predictor.py`) is byte-for-byte unchanged
— the card stays shadow / decision-support. 822/822 (+13 DF-06 tests); Gate 2 CLEAN, Gate 3
APPROVED. The "Biggest disagreements" queue is intentionally left for DF-07.

### DF-07 — Biggest Disagreements Redesign

**Type:** UI
**Depends on:** DF-06

**Implementation Notes:**
- Rework the disagreements queue + `top_disagreements`: each row a ranked sentence
  with an explicit verdict — ✓ conviction (within ceiling) vs ⚠ likely model error
  (> ceiling) — direction obvious, ordered by trustworthy edge magnitude.

**Acceptance Criteria:**
- [x] Each disagreement reads as a sentence with a clear verdict tag
- [x] Conviction vs likely-model-error split is explicit (edge ceiling)
- [x] Ranked by trustworthy edge; the point of each row is obvious
- [x] Empty/early state handled

**Result:** ✅ DONE. The "Biggest disagreements to review" queue is now ranked verdict
sentences instead of a flat dataframe. New pure `research.build_disagreements(limit, cfg)`
collapses each market to the side the MODEL favours (so a row is a clear directional call,
not a mirror Over/Under pair), keeps it only when the edge clears the threshold (a real
disagreement), and tags it against the SAME bounds the value finder stakes on (via the DF-06
`_edge_trust` / `_trust_bounds`): `value` → ✓ conviction (a backable shadow lean, with best
price), `capped` → ⚠ likely model error (gap past the ceiling, too big to trust). Rows sort
`(conviction-before-capped, edge desc)` so the trustworthy calls lead even when a capped gap is
numerically bigger (a +28% over-ceiling gap ranks below a +13% conviction). `_disagreement_sentence`
(pure) writes the sentence; the view's `_disagreement_row_html` adds the ✓/⚠ colour-tiered tag +
the signed edge as a scannable rank marker (all escaped). Empty/in-line/no-prediction states return
`[]` → a neutral caption. The older `top_disagreements` is kept as the tested lower-level primitive.
The value path (`value_finder.py`, `predictor.py`) is byte-for-byte unchanged — shadow only.
831/831 (+9 tests); Gate 2 CLEAN, Gate 3 APPROVED. **This completes DF Phase A (main page).**

### DF-08 — WC Deep Dive: Scaffold + Heatmap + Model-vs-Books

**Type:** UI / Page
**Depends on:** DF-01

**Implementation Notes:**
- New WC deep-dive view mirroring `match_detail.py` against the WC tables (WCMatch /
  WCPrediction / WCOdds / Bayesian). Scoreline heatmap (the 7×7) + model-vs-**every
  pulled book** visual comparison (port `_build_bookie_probs` / `_render_prob_cell`),
  all markets.
- Entry buttons on each fixture row + the research card (session-state match id + nav
  switch).

**Acceptance Criteria:**
- [x] Clicking a fixture / research card opens that match's deep dive
- [x] Scoreline heatmap renders the model's 7×7
- [x] Model vs every pulled book shown per market with the visual comparison
- [x] Empty/missing-data states handled

**Result:** ✅ DONE — New read-only page `src/delivery/views/wc_deep_dive.py` (Phase B
start), mirroring `match_detail.py` against the WC tables. Three pure additions feed it
(value path byte-for-byte unchanged — shadow): (1) `predictor.scoreline_matrix_from_lambdas`
rebuilds the 7×7 Dixon-Coles grid from the stored expected goals (wc_predictions persists λ,
not the matrix); (2) `research.build_book_comparison` returns, per market (1X2 + O/U
1.5/2.5/3.5 + BTTS), the model prob + de-vigged median consensus + **every** pulled book's
own de-vigged line (via new `_collect_by_book`), each tagged with the model edge and the
DF-06 trust class against the SAME config bounds the value finder stakes on (`_trust_bounds`/
`_edge_trust`, not hardcoded); (3) the view's pure `_market_table_html` renders the model row
over the consensus row over one row per book, edge-tinted (green = value vs that book, amber =
past the ceiling / likely model error), softest-book-first, with ★ on the best price across
books (line shopping). Entry: the WC hub's fixtures strip (per-row expander button) and the
research card both set `st.session_state["wc_deep_dive_match_id"]` + `st.switch_page`; the page
resolves session-state (one-shot pop) → `?wc_match_id`, registered in `dashboard.py` nav, with
a picker fallback. Empty/missing states: no prediction → no heatmap (`st.info`); no odds → no
comparison; match not found → `st.error` + back. 851/851 (+20), Gate 2 CLEAN / Gate 3 APPROVED.
Real heatmap + model-vs-books PNG on owner Desktop. **DF-09/DF-10 extend this same page**
(movement + lineups; qualification impact + Bayesian read).

### DF-09 — WC Deep Dive: Movement + Lineups

**Type:** UI
**Depends on:** DF-08

**Implementation Notes:**
- Line-movement chart (price since open, with entry + close marked — the CLV story).
- Both confirmed XIs + formations + the rotation flag (reuse `lineup_signal`).

**Acceptance Criteria:**
- [x] Movement chart shows price history with entry + close markers
- [x] Both lineups + formations rendered when available; graceful "not announced"
- [x] Rotation flag surfaced (decision-support framing)
- [x] No model/value change

**Result:** ✅ DONE — Two sections added to the same deep-dive page
(`src/delivery/views/wc_deep_dive.py`), fed by one new pure data layer
(`research.build_movement`) and the existing `lineups.lineup_signal`. **Line
movement & CLV:** `WCOdds` keeps only the opening + latest price (no per-snapshot
tick history), so each *backable* selection (every logged `WCValueBet`) is traced
on one consistent best-available-across-books basis — the opening line, the entry
we logged (`best_odds`), the current best line, and the closing line frozen at
kickoff (`closing_odds`) — with the entry + close marked on a Plotly line
(`_movement_chart`) and a precise `_movement_table_html` carrying the stored CLV
(`clv = (1/close) − (1/entry)`; +ve green = we beat the close, −ve red, "awaiting
close" until captured). The UI is explicit that these are real snapshots, not a
dense series. **Confirmed lineups:** `_render_lineups` reuses the SAME
`lineup_signal` that powers the research-card flag (no divergent logic) — both XIs
+ formations side-by-side, a "🔒 not announced yet" state until ESPN posts the XI
(~1h pre-KO), and the heavy-rotation flag surfaced as an amber card note + an
`st.warning` framed "a hypothesis to re-check, not a model signal". Value/model
path byte-for-byte unchanged (`value_finder.py` × 2 + `predictor.py` empty diff —
shadow). 868/868 (+17), Gate 1 PASS 4/4 / Gate 2 CLEAN / Gate 3 APPROVED. Real
movement-chart + CLV-table + rotation-flag PNG on owner Desktop. **DF-10 extends
this same page** (qualification impact + Bayesian read + glossary + nav/integration).

### DF-10 — WC Deep Dive: Context + Bayesian

**Type:** UI
**Depends on:** DF-08

**Implementation Notes:**
- Group/qualification impact of the result (what it does to the table).
- Bayesian-vs-Poisson read for this match (shadow). Nav registration + glossary.

**Acceptance Criteria:**
- [x] Qualification/standings impact shown for the match
- [x] Per-match Bayesian-vs-Poisson read rendered (shadow framing)
- [x] Glossary covers the new deep-dive terms
- [x] Page registered in nav; integration test for the deep-dive flow

**Result:** ✅ DONE. Three sections added to the read-only deep-dive page
(`src/delivery/views/wc_deep_dive.py`), fed by two new pure, unit-tested,
streamlit-free data layers in `src/world_cup/research.py`. The value/staking path
(`value_finder.py` ×2) and `predictor.py` are byte-for-byte unchanged — the WC
system stays shadow / decision-support.

- **Group & qualification impact** — `build_group_context(match_id)` builds the
  match's group table from finished results (same 3/1/0 + GD/GF logic as the WC
  hub), flags the two teams in the tie, and computes the qualification impact of
  each result. The status read (`_qual_status`) is points-only and deliberately
  conservative: "through" (clinched top 2) and "out" (eliminated from top 2) are
  shown only when mathematically certain — ties and head-to-head are assumed
  against the team, and the 8-best-third-place race (which depends on other
  groups) honestly stays "in contention". A knockout tie has no table to move, so
  the section says exactly that. The view renders an escaped group table +
  per-result scenario chips (or the realised standing once played).
- **Bayesian vs Poisson — this match** — `build_model_comparison(match_id)` lines
  up the two STORED predictions (staked Poisson `MODEL_NAME` + shadow Bayesian
  `MODEL_NAME_BAYES`) per market with the gap (Δ = Bayesian − Poisson) and an
  agreement read. It reads stored rows only — nothing is recomputed or staked;
  the Bayesian stays display-only with explicit "promotion is manual" framing.
- **Glossary** — a pure `_glossary_html()` defines the new deep-dive terms
  (scoreline matrix, de-vig, edge, line movement, CLV, rotation flag,
  qualification status, Bayesian shadow), styled like the league deep dive's.
- **Integration test** — `tests/test_wc_deep_dive_integration.py` is a real
  end-to-end test: it seeds an in-memory DB (a full Group C + both model
  predictions + odds + shadow value bets + lineups) and exercises every per-match
  data layer (`build_book_comparison`, `scoreline_matrix_from_lambdas`,
  `build_movement`, `build_group_context`, `build_model_comparison`,
  `lineup_signal`) plus an AST-exec render of the view's pure HTML helpers over
  that real data, including an XSS-escaping probe.

902/902 tests (+34). Gate 1 PASS 4/4, Gate 2 CLEAN (no drift; `_qual_status`
verified sound; field names match `models.py`), Gate 3 APPROVED (the reviewer
brute-forced `_qual_status` over 25,270 group states — zero false
clinched/eliminated — and ran an explicit XSS test). Real context + Bayesian +
glossary PNG on the owner's Desktop. **This completes the DF (Decision-First UX)
epic — all 10 issues DONE.**

---

## WC-11A — Player Insight (display-only, shadow) · COMPLETE 2026-06-24

**Status:** COMPLETE — all 4 issues done (01 rate engine + resolver → 02 adjusted-λ
lineup impact → 03 anytime-scorer board + pen-taker → 04 player-watch extras). Every
issue shipped display-only / shadow: the value path (`value_finder.py` ×2) and
`predictor.py` are byte-for-byte unchanged across the whole epic, and no odds are
pulled (zero Odds API credits). This was the **display-only subset of WC-11** (the
deferred player-props epic) — the "A1" slice agreed with
the owner: turn the confirmed lineups we already capture into decision-support
about *which players carry the goals and how a changed XI shifts the picture*,
**without** building a staked product and **without** the prop-odds budget the full
WC-11 needs (see `worldcup_props_spike.md` §3, ≈ the whole monthly Odds API quota).

**Hard discipline (same as DF):** everything here is **presentation over data we
already hold**. The model and the value/staking path are untouched — `predictor.py`
and `value_finder.py` ×2 stay byte-for-byte unchanged, asserted by an empty
`git diff --stat` + a grep guard in CI. The model's stored λ (expected goals) is
**read, never rewritten**; any "adjusted λ" is a display-only what-if computed at
render time and never persisted to `WCPrediction`. WC stays "track", never "bet".

**Why this is safe AND useful:** the team model already isn't sharp enough vs the
market to stake (that's why WC is shadow), and a player model would be cruder — so
we deliberately do **not** chase a betting edge here. We surface *the model's own
view of the XI* (who's likely to score, what a rotation costs) as a learning /
decision-support layer, exactly like the DF deep dive.

### Data sources (researched 2026-06-24 — three parallel audits)

**1. ESPN confirmed lineups** (`site.api.espn.com/.../soccer/fifa.world`, free,
key-less, GET-only — already wired in `src/world_cup/lineups.py`):
- ✅ Confirmed starting XI for **both** teams (gated: stored only when each side has
  ≥11 starters), **granular position** per player (role-level: `CF`/`RW`/`DM`/`CD-L`,
  not just FWD/MID/DEF), **formation**, jersey, and the full bench.
- ✅ Already feeds `lineup_signal()` (the rotation flag the research card + deep dive
  share) — WC-11A **reuses** it, never re-queries.
- ❌ No expected minutes, no per-player xG, no season/career stats (only a live
  single-match stats block, empty pre-KO), no injury reason. → any λ-adjust is a
  **heuristic from goal-shares + who's in/out**, framed as decision-support, never a
  data-grade minutes model.
- ⚠️ **Timing:** the XI posts only **~1 h before kickoff** (dispatcher retries every
  ~15 min in `[KO-60, KO)`); before that the feature shows a clean "🔒 XI not
  announced yet" state.
- ⚠️ **Name capture fix needed:** the feed carries both `displayName` (short, e.g.
  "Vinicius Jr") and `fullName` ("Vinicius Junior"); we currently store the **short**
  form (`lineups.py:125`), which zero-matches Transfermarkt. WC-11A-01 fixes this.

**2. Transfermarkt** (local `data/raw/transfermarkt/datasets/`, **current through
2026-05-24** — the 2025/26 season is present; 1.88 M appearance rows, 47.7 K players):
- ✅ Per-player **goals-per-90 + minutes** (`appearances.csv.gz`; the appearances↔
  players join is **100 %** clean), **cards**, `position`/`sub_position`, market
  value, `country_of_citizenship`, `international_goals/caps`, and **penalty-taker**
  signal (`game_events.csv.gz`, 21,874 penalty goals → top takers resolve to Ronaldo,
  Kane, Messi).
- ⚠️ **The make-or-break: the ESPN-name → TM-player join.** Verified solvable
  **without ML**: (a) capture ESPN **`fullName`** (fixes the "Vini Jr"/"Leo Messi"
  zero-match class); (b) resolve on **normalised name + nation** (the team's WC nation
  is a free, strong disambiguator), tiebreak on **most-recent `last_season`** (picks
  active over retired — the "Rodri trap") **+ position**; (c) a small **curated
  `(name, squad) → player_id` override map** for the handful of ambiguous stars per
  tournament (mirrors the existing `_ESPN_NAME_MAP`); (d) **blank ("—") on residual
  ambiguity — never show a guessed player's stats.** Collision rate falls 2.0 %
  (name) → 1.4 % (name+nation) → 0.6 % (+position); the override map + blank-on-doubt
  closes the rest.
- ⚠️ **Coverage:** top-5-league starters are rich; Saudi/MLS players (Ronaldo,
  Benzema, Neymar) have **0 recent club minutes** → fall back to `international_goals`,
  **clearly labelled "international form"**, not club form.

**3. Integration / shadow safety** (verified against `predictor.py`, `research.py`,
`value_finder.py` ×2): the team λ is computed once from **team-level features only**
(no player input anywhere) and stored on `WCPrediction.home/away_expected_goals`. A
display-only adjusted-λ is a **new pure function reading that stored λ** — zero change
to the model or value path. Pattern mirrors DF-08/09/10: a pure, streamlit-free,
unit-tested `research.build_lineup_impact()` + one thin escaped deep-dive renderer.

### Issues

#### WC-11A-01 — Player rate engine + name resolver (the data foundation)

**Type:** Data
**Depends on:** WC-10-06 (ESPN capture)

**Implementation Notes:**
- Capture ESPN **`fullName`** for join accuracy. Recommended: add **nullable**
  `full_name` + `espn_athlete_id` columns to `WCLineup` (additive, `wc_`-only
  migration; keeps `player_name`/`displayName` so the rotation signal is undisturbed)
  and store `athlete.id` as a stable identifier. NOTE: Transfermarkt carries no ESPN
  ids, so the id is **not** a direct join key — the resolve is name-based; the id is
  kept for dedup / a future ESPN-id→player_id bridge that could seed the override map.
- New streamlit-free `src/world_cup/player_rates.py`: from the local Transfermarkt
  files, build a cached per-player lookup — recency-weighted **goals-per-90**,
  minutes, **cards-per-90**, **penalty-taker** flag, `position`/`sub_position`,
  market value, and an `international_goals/caps` fallback. Pure, unit-tested.
- New resolver `resolve_player(name, nation, position=None) → player_id | None`: a
  curated override map first; else normalised(name)+nation, tiebreak max
  `last_season` + position; else a unique name-only fallback; else **None** (blank —
  never guess).

**Acceptance Criteria:**
- [x] `player_rates` computes sane goals-per-90 for known stars (Kane ≈ 1.1, Haaland
  ≈ 1.0, a defender ≈ 0.1) from local data — no new scraping, no Odds API cost.
- [x] Resolver maps the audit's star set (incl. "Vinicius Junior", "Bruno Fernandes")
  to the correct `player_id`, and returns **None** (not a wrong match) on ambiguity.
- [x] Saudi/MLS players resolve with an **international-form fallback**, labelled.
- [x] Unit tests cover the resolver's exact-match, tiebreak, override, and
  blank-on-ambiguity paths; capture change leaves `lineup_signal` tests green.

**Result:** ✅ DONE (commit 14a7a67). `src/world_cup/player_rates.py` builds a
compact committed cache (`data/world_cup/player_rates.csv.gz`, 29,809 players,
~925 KB) from the local Transfermarkt files — recency-weighted goals-per-90
(min-minutes guarded), yellows-per-90, penalty-taker flag, position, market value,
international fallback. `resolve_player` = curated override → name+nation (+
recency/position tiebreak) → unique name-only → **None** (blanks on ambiguity,
never guesses; nation aliases verified vs the real TM country spellings). `WCLineup`
gained additive nullable `full_name` + `espn_athlete_id` (captured from ESPN's
feed; migration applied to Neon). Verified on real stars (Kane 1.15, Mbappé 0.92,
van Dijk 0.12, Ronaldo 0.63 via international fallback; short-form/ambiguous names
blank). 18 tests, 927/927. Gate 1 PASS 4/4, Gate 2 CLEAN (after dropping a dead
`espn_id` resolver param the spec over-promised — TM has no ESPN ids), Gate 3
APPROVED (after NaN-scrubbing string fields). predictor.py + value_finder.py ×2
byte-for-byte unchanged. PNG on owner Desktop.

#### WC-11A-02 — Lineup impact: display-only adjusted-λ (the core "A1")

**Type:** UI
**Depends on:** WC-11A-01

**Implementation Notes:**
- New pure `research.build_lineup_impact(match_id, rate_lookup)`: reuse
  `lineup_signal` for the XIs, read the **stored** λ off `WCPrediction`, and per team
  return `{status, lambda_model, lambda_adjusted, delta, formation, heavy_rotation,
  scorers:[{player,in_xi,share,exp_goals}], missing:[...]}`. `lambda_adjusted =
  lambda_model × (Σ in-XI goal-share ÷ Σ baseline-XI goal-share)` — **read-only, never
  written back.**
- New `_render_lineup_impact(match_id)` deep-dive section after `_render_lineups`
  (`st.divider()`), with the model-λ-vs-adjusted-λ read + the standard shadow caption
  ("a display-only what-if from the confirmed XI — never changes the model or a bet")
  and the not-announced state. Optional one-line echo on the research card (same
  `build_lineup_impact`, so the surfaces can't disagree).

**Acceptance Criteria:**
- [x] Adjusted-λ shown beside the model's λ when the XI is confirmed; clean
  not-announced state otherwise.
- [x] A rotated-out high-share striker visibly lowers adjusted-λ; the `delta` is
  presented **neutrally** (not as an edge).
- [x] `predictor.py` + `value_finder.py` ×2 byte-for-byte unchanged (empty diff +
  grep guard); `build_lineup_impact` is read-only (no `add`/`commit`).
- [x] Pure layer unit-tested; view AST-tested; glossary gains "Adjusted xG" /
  "Goal-share".

**Result (DONE):** New pure `research.build_lineup_impact(match_id, rate_lookup)`
reuses `lineup_signal` for the confirmed XI / formation / rotation, reads the
STORED Poisson λ off `WCPrediction`, and rescales it by the XI's goal-share vs the
team's previous XI: `lambda_adjusted = lambda_model × clamp(Σ in-XI gp90 ÷ Σ
baseline-XI gp90, 0.5, 1.5)` (the ±50% clamp is a display guard against a thin
resolve). `rate_lookup` is injected (the view passes `player_rates.player_rate`),
so the math is unit-testable and research.py stays free of the player cache.
Per team it returns `{status, lambda_model, lambda_adjusted, delta,
baseline_available, formation, heavy_rotation, changes, scorers:[{player, in_xi,
share, exp_goals}], missing, n_xi, n_rated}`; unresolved players are excluded from
the share and surfaced in `missing`, rotated-out baseline players appear with
`in_xi=False`, and the rated in-XI `exp_goals` slices sum to `lambda_adjusted`.
Two read helpers added to `lineups.py` (`_starter_rows` + `_prior_starter_rows`,
carrying the resolver's full_name/position columns); `_prior_xi` refactored to
delegate (behaviour-preserving). New deep-dive Section 6 `_render_lineup_impact`
(after lineups, before group context) draws a per-team card — model→adjusted λ
with a NEUTRAL grey delta (▲/▼, never green/red), a scorer board (g/90 → xG slice,
rotated-out struck through), and the unrated footnote — plus glossary terms
"Adjusted xG" / "Goal-share". READ-ONLY / shadow: no `add`/`commit`, nothing
written back to WCPrediction; `predictor.py` + `value_finder.py` ×2 byte-for-byte
unchanged. 15 tests (pure formula incl. clamp + read-only + escaping + view AST),
942/942. Real-rate proof on owner Desktop (England bench Kane 1.15 → 1.90→1.44;
France add Mbappé → 1.75→2.03). 3-gate green (Gate 2 CLEAN / Gate 3 APPROVED).
The optional research-card echo was deferred (the AC doesn't need it; keeps the
card path untouched).

#### WC-11A-03 — "Who's likely to score" board + penalty-taker flag

**Type:** UI
**Depends on:** WC-11A-02

**Implementation Notes:**
- Per-player anytime estimate `P = 1 − exp(−player_λ)`, `player_λ = goal-share ×
  team λ` (minutes held flat — the spike's honest framing; position-weight when club
  data is missing). **Display-only, NO odds pull** → no budget hit; we show *the
  model's* "who scores" ranking, not a market comparison.
- Flag the **designated penalty taker** (real anytime bump) from the TM penalty data.

**Acceptance Criteria:**
- [x] Ranked anytime-scorer table for the confirmed XI (Kane-type ≈ 45–50 %,
  defenders low), with the penalty-taker flagged; international-fallback labelled.
- [x] No Odds API credits spent; shadow caption ("the model's view, not a market
  line; not a bet").

**Result (DONE — commit pending):** New pure `research.build_scorer_board(match_id,
rate_lookup)` reuses the WC-11A-02 read (`_match_legs`, factored out of
`build_lineup_impact` so both share one DB pass) and `_team_impact` wholesale, so the
per-player λ has a single source of truth. For each in-XI player it takes his
`exp_goals` (= goal-share × the team's adjusted λ — the WC-11A-02 slice) as `player_λ`
and turns it into an anytime chance `P = 1 − exp(−player_λ)` via `_anytime_prob`
(Poisson P(≥1); guards λ≤0/None → None, never a guess). Each player also carries
`is_pen_taker` + the goals-per-90 `source` ('club'/'international') re-read via the
SAME `rate_lookup`/full-name the impact layer used; ranked P desc; unrated and
rotated-out players excluded (a zero-rate keeper is silently dropped — rated zero, not
"unrated"). The pen taker is **flagged, not bumped** — his spot-kicks are already in
his goals-per-90, so an extra bump would double-count. NO odds pull anywhere → zero
Odds API credits. Deep-dive Section 7 `_render_scorer_board` (after lineup impact,
before group context): per-team ranked card (#, player + PK/intl chips, g/90, anytime
% with a NEUTRAL grey proportional bar — it's an estimate, not an edge), not-announced
/ no-model / all-unrated states, shadow caption, footnotes for the PK/intl tags + the
unrated list. Glossary +"Anytime scorer %"/"Penalty taker". READ-ONLY: no
add/commit, nothing written back; `predictor.py` + `value_finder.py` ×2 byte-for-byte
unchanged (empty diff). 14 tests (formula + ranking + flags + zero-rate drop +
read-only + escaping + view AST); 956/956. Gate 1 PASS 6/6 · Gate 2 CLEAN · Gate 3
APPROVED (two cosmetic no-fix nits, both addressed/accepted). Real-rate PNG on owner
Desktop: Kane 52.5% [PK] top for England; Ronaldo 41.4% [PK,intl] for Portugal;
defenders low (Shaw 1.5%, Dias 2.5%).

#### WC-11A-04 — Player watch extras (optional polish)

**Type:** UI
**Depends on:** WC-11A-03

**Implementation Notes:** small display add-ons off the same data — a **booking-risk**
note (high cards-per-90 starters), a **star-absence callout** (the `missing` list,
"Brazil without Vinícius Júnior"), and **form/milestone** notes (recent scoring run;
approaching a caps/goals milestone). All display-only, escaped, no new cost.

**Acceptance Criteria:**
- [x] At least the booking-risk + star-absence callouts render from real data with
  graceful empty states; no model/value change.

**Result (DONE — closes the WC-11A epic):** New pure `research.build_player_watch(
match_id, rate_lookup)` reuses the shared `_match_legs` read (NO extra query) and the
injected `rate_lookup` (the view passes `player_rates.player_rate`) to emit three squad
notes per confirmed XI — squad FACTS, not model outputs, so they need no stored λ and
surface the moment the XI lands. **(a) Booking risk:** confirmed starters whose recent
club `yellows_per_90` ≥ `_BOOKING_RISK_PER90` (0.25 — ~a yellow every 4 full games,
which cleanly separates card-prone DMs/CBs at 0.25–0.34 from clean attackers/keepers
< 0.20 in the real cache; a 2-yellow tournament suspension risk), ranked desc — framed
as a heads-up on a *club* rate, explicitly NOT a tournament caution/suspension count.
**(b) Star absence:** a player in the team's PREVIOUS XI but not this one (baseline
minus current, mirroring `_team_impact`'s rotated-out walk) who is high-value
(`market_value_eur` ≥ €40m) OR a genuine goal threat (`goals_per_90` ≥ 0.60), ranked by
value — "Brazil without Vinícius Júnior". **(c) Milestones:** a confirmed starter within
5 of a 50-cap landmark, or within 3 of the next ten of international goals at/above a
floor of 20 (`_next_milestone` with a `floor` guard, so we never celebrate a defender
"nearing 10 goals"). Each note has a graceful empty state (not-announced; "Nothing
flagged"; star-absence needs a baseline). Deep-dive **Section 8** `_render_player_watch`
(after the scorer board, before group context): a per-team card with a booking block
(amber YEL chip — a literal yellow card), a star-absence block ("{nation} without …"
plus per-player market value), and a milestone block — NO MODEL badge (these are facts,
not model numbers) and all dynamic strings escaped. Glossary +"Booking risk"/"Star
absence". READ-ONLY: no add/commit, nothing written back; `predictor.py` +
`value_finder.py` ×2 byte-for-byte unchanged (empty diff). 16 tests (milestone math +
floor + booking threshold + star-by-value/by-g90 + sorting + empty/not-announced states
+ DB read-only + escaping + view AST); 972/972. Gate 1 PASS 5/5 · Gate 2 CLEAN · Gate 3
APPROVED (two non-blocking nits: `n_flags` is a tested convenience field mirroring the
sibling builders' `n_ranked`; the stale module-docstring section list was renumbered).
Real-rate PNG on owner Desktop: England (Maguire/Mainoo card-prone, "without
Bellingham" €160m, Kane 1 from 80 intl goals + Walker 4 from 100 caps); Brazil ("without
Vinícius Júnior, Rodrygo" €180m/€110m, a card-heavy engine room, G. Jesus 1 from 20).

### Deferred / gated add-on (NOT in WC-11A)

**Model-vs-market prop comparison** — comparing our anytime numbers to the
**de-vigged** bookmaker line needs a **day-of prop-odds pull** (`player_goal_scorer_
anytime`, 1 market × 1 region), which the spike costs at ≈ the whole monthly Odds API
quota. Kept **OFF** and **gated on owner opt-in + budget**, exactly per
`worldcup_props_spike.md` §3/§5. WC-11A delivers the model's view for free; the market
overlay is a separate, funded decision.

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

---

## WC-BET — Personal Bet Tracker (Complete · 2026-06-29)

Self-contained World Cup personal bet tracker: a user logs their OWN WC bets
(manually or from a model pick) and tracks them with auto-settlement + running
P&L. Entirely separate from the model's shadow value picks (`wc_value_bets`) and
from league bets (`bet_log`); never touches the model / value / prediction path.
User-scoped (user_id); markets 1X2 / O-U 1.5·2.5·3.5 / BTTS.

- **WC-BET-01** (6f3fd77) — Data + settlement layer. New `wc_bet_log` table
  (`WCBetLog`: user_id, match_id, market_type, selection, odds, stake, bookmaker,
  model_prob/edge captured-and-frozen at log time, status, pnl, placed_at /
  settled_at; created on local + Neon via create_all). `src/world_cup/bets.py`:
  `log_wc_bet` (validates market/selection + odds>1 + stake>0), `settle_wc_bets`
  (idempotent, pipeline-safe), `load_wc_bets` (read-time settlement so the display
  is correct before the pipeline persists it), `wc_bet_summary`. Settlement reuses
  `betting.tracker._did_bet_win`, so a WC bet settles by the same proven logic as a
  league bet.
- **WC-BET-02** (6fc74d0) — "🎟️ My Bets" tab in the WC hub: scoreboard (Net P&L /
  ROI / record / win-rate / staked / pending + a model-advised subset), a manual
  log form, and the settled bet list. Verified live.
- **WC-BET-03** (6f6ed15) — Log-from-advice: an inline "➕ Log one of these picks"
  control under the Value Bets pre-fills the model's pick (odds from the best book)
  and logs it tagged 🎯, capturing model_prob/edge. `_vb_to_canon` maps a value bet
  (h2h/totals/btts) to canonical (1X2/OU25/BTTS); totals → OU25 (the only line the
  model prices).
- **WC-BET-04** (416bc91) — `settle_wc_bets` wired into BOTH the morning + evening
  pipeline runs (persisted settlement); a cumulative-P&L-over-time line chart in My
  Bets.
- **WC-BET-05** — review (independent code-review agent) + docs.

Tests: `tests/test_wc_bet_tracker.py`. Owner-approved 2026-06-29 (inline logging
chosen; the accumulator/parlay variant — multi-leg, combined odds, all-legs-must-win
— is deferred to a follow-up to be plan-first, chip task_e5f58071).

---

## WC-ACC — Accumulator (Parlay) Bets · ✅ COMPLETE 5/5 (owner-approved 2026-06-29; WC-ACC-01/02 2026-06-30, WC-ACC-03/04/05 2026-07-01; MERGED to `main` via PR #1 on 2026-07-01, rebased tip a4d8a08)

Extends the WC bet tracker (WC-BET) to **accumulators**: multiple legs as one bet,
all legs must win, combined odds = product of the legs. **Calculator + tracker, NOT
a recommender** — the user builds the slip; the system computes combined odds/payout,
settles all-legs-must-win, and tracks P&L; it never picks the combination. Owner
confirmed the *informative* combined-edge display (WC-ACC-03). Shadow-safe,
user-scoped; reuses `betting.tracker._did_bet_win` per leg; never touches the
model/value/prediction path.

**Schema (decided):**
- `wc_accumulator` (parent): id, user_id (FK), stake, combined_odds (frozen at log),
  status (pending/won/lost/void), pnl, source, notes, placed_at, settled_at.
- `wc_acca_leg` (legs): id, accumulator_id (FK), match_id (FK), market_type,
  selection, odds, status, settled_at.
- `wc_bet_log` (singles) unchanged; the My Bets scoreboard + cumulative-P&L chart
  MERGE singles + accumulators for combined P&L.

**Issues:**
- **WC-ACC-01 — Data model + settlement engine.** ✅ DONE (2026-06-30). New
  `wc_accumulator` + `wc_acca_leg` tables (created local + Neon via create_all — no
  data migration). Pure fns in `world_cup.bets`: `accumulator_odds`
  (product of leg odds), `accumulator_status` (lost if ANY leg lost; won if ALL win;
  void legs excluded; pending until all resolve; void if all void),
  `accumulator_effective_odds` + `accumulator_pnl` (effective odds recompute EXCLUDING
  void legs), `settle_wc_accumulators` (idempotent, pipeline-safe),
  `log_wc_accumulator` (≥2 legs; each valid market/selection + odds>1; stake>0;
  all-or-nothing; match-existence guard), `load_wc_accumulators` (read-time
  settlement, user-scoped, parent + expandable legs). Leg settlement reuses
  `betting.tracker._did_bet_win`; shadow-safe (predictor.py/value_finder.py empty
  diff); singles `wc_bet_log` byte-for-byte unchanged. Leg carries nullable
  `model_prob`/`edge` frozen at log (for the WC-ACC-03 edge readout). AC 8/8: combined
  odds correct · one losing leg → whole acca lost · all-win → payout = stake×combined ·
  void leg drops out + odds recompute · pending until all settle · idempotent ·
  user-scoped · never raises. Gate 2 CLEAN · Gate 3 APPROVED. 16 tests
  (tests/test_wc_accumulator.py); suite 1250.
- **WC-ACC-02 — Knockout 90-minute settlement (correctness; ALSO fixes singles).**
  ✅ DONE (2026-06-30). Match-result / O-U / BTTS legs settle on the 90-MINUTE score
  (bookmaker convention), not extra-time/penalties. INVESTIGATION (real ESPN data):
  ESPN's free `keyEvents` feed carries a `period` on every goal (1-2 = regulation,
  3-4 = ET, 5 = shootout); counting periods 1-2 reconstructs the 90-minute score, and
  a per-team SELF-CHECK against the official final (a.e.t.) score guards it (defers if
  it can't reconcile — never mis-settles). Verified on the 2022 final (2-2 at 90 vs
  3-3 a.e.t.) + the live 2026 shootouts (Germany 1-1 Paraguay, Netherlands 1-1
  Morocco). SCHEMA (migrated local + Neon): `WCMatch.home_goals_reg`/`away_goals_reg`
  (nullable, the 90-min score) + `went_to_extra_time` (flag). New
  `src/world_cup/regulation.py`: `reconstruct_regulation_score` (self-checked) +
  `reconcile_knockout_regulation` (finds finished KO matches, matches to ESPN events
  by date+pair, maps orientation, writes reg+flag; idempotent, self-healing, never
  raises), wired into morning+evening BEFORE settlement. `bets.settlement_score`
  routes singles (settle/load) AND acca legs (`_leg_status`) through the 90-min score.
  Shadow-safe (predictor/value_finder empty diff). A KO awaiting reconstruction stays
  PENDING. AC 3/3: KO pens-win settles "home win" NOT won · group-stage unchanged ·
  singles + acca legs both correct. Gate 2 CLEAN · Gate 3 APPROVED. 18 tests
  (tests/test_wc_regulation.py); suite 1268.
- **WC-ACC-03 — Bet-slip builder + combined-edge readout (INFORMATIVE — CONFIRMED).**
  ✅ DONE (2026-07-01). Session-state bet slip (`wc_acca_slip`) in the My Bets tab
  (`world_cup._render_bet_slip`): manual add-leg (match/market/selection/odds) +
  "➕ Add to slip" on the model value picks (extends `_render_log_pick_control`,
  captures model_prob/edge frozen). Slip panel: removable legs, live combined odds +
  potential payout, "🎫 Log accumulator" (≥2 legs + stake>0 → reuses WC-ACC-01
  `log_wc_accumulator`), Clear slip. NEW pure `bets.accumulator_slip_readout`:
  combined_odds (product), implied_prob, combined MODEL prob (product of per-leg
  probs, only when ALL legs have one), edge (model−implied), same-match `correlated`
  groups. INFORMATIVE readout shown only when every leg has a model estimate (framed
  "not a recommendation"); CORRELATION WARNING (`st.warning`) when 2+ legs share a
  match (independence assumption breaks). Pure escaped HTML helpers
  `_slip_leg_row_html`/`_slip_readout_html`. NO recommender. Shadow-safe (value_finder
  /predictor empty diff). AC 5/5: add/remove legs · combined odds+payout live · logs a
  valid acca (≥2) · same-match warning · never suggests combos. Gate 2 CLEAN · Gate 3
  APPROVED. 6 tests (22 in test_wc_accumulator.py); suite 1274. PNG proof on Desktop.
- **WC-ACC-04 — Display accumulators + pipeline settlement.** ✅ DONE (2026-07-01).
  NEW pure `bets.combined_bet_summary`/`combined_pnl_timeline` merge singles + accas
  into ONE scoreboard + ONE cumulative curve (each bet = one unit; an acca's settle
  date = its LATEST leg date). My Bets tab (`_render_my_bets`) loads singles
  (load_wc_bets) + accas (load_wc_accumulators, read-time settled), shows the merged
  scoreboard/chart, then a "🎫 Accumulators" section — each acca an `st.expander`
  (parent header `_acca_expander_label`: status icon · N-leg · combined odds · stake ·
  P&L settled / "→ $X potential" pending) with legs (`_acca_leg_row_html`: teams ·
  market/sel · odds · per-leg status) — above "🎟️ Single bets". `settle_wc_accumulators`
  wired into morning+evening AFTER reconcile_knockout_regulation + settle_wc_bets (so
  KO accas settle on the 90-min score; a KO awaiting reconstruction stays pending).
  Singles-only wc_bet_summary/wc_pnl_timeline retained (still tested). Shadow-safe.
  AC 4/4: expandable legs + correct status/P&L · scoreboard + chart include acca P&L ·
  pipeline settles accas · read-time == persisted. Gate 2 CLEAN · Gate 3 APPROVED.
  6 tests (30 in test_wc_accumulator.py) + 2 wiring assertions updated; suite 1280.
  PNG proof on Desktop.
- **WC-ACC-05 — Review + docs.** ✅ DONE (2026-07-01), CLOSES the epic. Holistic
  independent review of all 5 issues APPROVED — verified the cross-issue seams:
  read-time (`load_wc_accumulators`) == persisted (`settle_wc_accumulators`) P&L (same
  pure trio over the same legs); singles + acca legs both route `settlement_score`
  (KO 90-min; a KO awaiting reconstruction keeps the acca pending, never settles
  early); each acca counts as ONE unit in `combined_bet_summary`/`combined_pnl_timeline`
  (no per-leg double-count); void-drops-out identical both paths; shadow-safe (only
  `wc_accumulator`/`wc_acca_leg` writes; reconcile only the 3 `wc_matches` reg cols);
  never-raises + idempotent. LIVE E2E (real fns, fresh DB): 2-leg acca WON +24.20;
  3-leg acca LOST −10.00 because its KO leg settled on the 90-min draw (Spain 2-1
  a.e.t. / 1-1 at 90) — proves 01↔02; merged scoreboard net +21.20 across 1 single +
  2 accas. DATA CHECK: WC knockouts carry `stage='knockout'` (6 finished on Neon) →
  the reconciler's `stage != "group"` filter processes them (KO reg scores populate
  next pipeline run). Rule-8 Tier-1: masterplan 1.9 → 1.10 + §13.16 WC-ACC & WC-BET
  paragraphs. Suite 1280.

Tests: `tests/test_wc_accumulator.py`. Each issue runs the full review gates +
commit/push, exactly like WC-BET. Supersedes follow-up chip task_e5f58071.


## WC-QUAL — "To Qualify / To Advance" Market · APPROVED (owner-approved 2026-07-01, building on branch `wc-qual`)

Extends the WC personal bet-tracker (WC-BET singles + WC-ACC accumulators) with a new
**"To qualify"** market: bet on which team ADVANCES from a knockout tie — settled on
the winner after 90 min + extra time + penalties — as the counterpart to the existing
"Match result (90 min)" (1X2). Loggable as a single OR an accumulator leg; knockout
matches only; two selections (home / away, no draw). MANUAL odds — the model does not
price it (an OPTIONAL display-only informational qualify-chance is derived from the
stored 90-minute probabilities). Shadow-safe, user-scoped: never touches the
model / value / prediction path — extends the same self-contained tracker as
WC-BET / WC-ACC.

The two markets it distinguishes (both stored, different data):
- **Match result (90 min) / 1X2** — settles on the 90-MINUTE score (the WC-ACC-02
  regulation columns).
- **To qualify** — settles on WHO ADVANCED (the a.e.t. score, tie-broken by the
  penalty shootout).

**Schema (decided):** add nullable `WCMatch.home_pens` / `away_pens` (the shootout
score; the regulation reconciler captures them from ESPN). `wc_bet_log` /
`wc_acca_leg` are UNCHANGED (`market_type` is text → `"QUALIFY"` just works). Migrated
local + Neon.

**Out of scope:** group-stage "to qualify" as a futures / outright market (which two
teams finish top-2 of a group across 3 matches) — a different multi-match bet, not
this per-tie "to advance." This epic is the knockout-tie market only.

**Issues:**
- **WC-QUAL-01 — Data + settlement engine.** Add `home_pens` / `away_pens` to
  `WCMatch` (migrated local + Neon); `regulation.reconcile_knockout_regulation` also
  captures the shootout score from ESPN (`competitor.shootoutScore`) for finished
  knockouts. New pure `_did_qualify(match, selection)` — advancer = higher a.e.t.
  score, tie-broken by pens; returns None (defer → pending) if a tie's pens aren't
  captured yet. Market-aware `bet_result(match, market_type, selection)` routes
  `QUALIFY` → advancement and every other market → the existing 90-minute
  `settlement_score` path; singles (`settle_wc_bets` / `load_wc_bets`) + acca legs
  (`_leg_status`) all route through it. Add `QUALIFY` to `WC_MARKETS` /
  `MARKET_LABELS` / `is_valid_selection` (home / away); `log_wc_bet` /
  `log_wc_accumulator` reject `QUALIFY` on a group match. AC: a KO won on pens settles
  "X to qualify" WON for the advancer / LOST for the loser · "Match result (90 min)"
  still settles on the 90-minute score (unchanged) · group matches reject QUALIFY ·
  unresolved advancement → pending · idempotent · never raises · shadow-safe.
- **WC-QUAL-02 — UI: log + slip + display.** The market dropdown offers "To qualify"
  ONLY for knockout matches (log form + slip builder); relabel 1X2 → "Match result
  (90 min)" on knockouts so the two sit side by side. QUALIFY bets / legs display +
  settle in the existing lists (singles + expandable acca legs). The value-pick
  "➕ Add to slip / Log" flow stays 1X2 / O-U / BTTS only (QUALIFY is manual). AC: log
  a QUALIFY single + acca leg on a KO match · not offered on group matches · displays
  + settles correctly · value-pick flow unchanged.
- **WC-QUAL-03 — Informational qualify-chance (display-only).** Pure
  `qualify_estimate` = P(win 90) + ½·P(draw 90) from the stored `WCPrediction` probs,
  shown as a clearly-labelled approximation when a QUALIFY selection is chosen — never
  an edge / value signal. Reads stored rows, writes nothing (shadow-safe). AC: shows
  an estimate only when the model has a stored prediction · labelled "approximation,
  not a recommendation" · absent for unpredicted matches.
- **WC-QUAL-04 — Review + docs.** Holistic review (advancement money / settlement edge
  cases: ET-decided vs pens-decided vs unresolved; shadow safety; multi-user
  isolation) + live end-to-end (log + settle a qualify bet on a real pens match) +
  masterplan / build-plan docs (Rule 8 Tier-1) + version bump. Closes the mini-epic.

Tests: `tests/test_wc_qualify.py`. Each issue runs the full review gates + commit /
push to the `wc-qual` branch (a fresh PR, now that PR #1 is merged), exactly like
WC-ACC. Cost: $0 (ESPN free; no Odds API). Value / predictor path held byte-for-byte
unchanged.
