# BetVector — Model Evaluation Log

> **Purpose:** Living document tracking model performance across every change.
> Updated after each model modification, backtest, or significant data change.
> All metrics are reproducible from the database and backtest scripts.

---

## Current Production Model

| Parameter | Value |
|-----------|-------|
| **Model** | `poisson_v1` (Poisson GLM) |
| **Status** | Active since E4-01 (initial deployment) |
| **Ensemble** | Disabled (`ensemble_enabled: false`) |
| **Training data** | 5 seasons, ~1,900 matches |
| **Backtest Brier** | 0.5781 |
| **Backtest ROI** | +2.78% |
| **Live ROI** | +1.4% (1,330 resolved bets) |
| **Edge threshold** | 5% (from `settings.yaml`) |
| **Staking** | Flat 2% of bankroll per bet |

---

## Performance Evolution Timeline

Each row marks a significant model or data change. Metrics are from
walk-forward backtests on the stated evaluation season.

| # | Date | Milestone | Eval Season | Training Matches | Brier Score | ROI (%) | Key Change |
|---|------|-----------|-------------|-----------------|-------------|---------|------------|
| 1 | 2026-01-15 | E13-03 Baseline | 2024-25 | 380 (1 season) | ~0.72 | ~-15.0 | Initial Poisson GLM — basic rolling form features |
| 2 | 2026-01-20 | E16-03 Advanced Features | 2024-25 | 380 (1 season) | 0.6903 | -7.2 | +NPxG, PPDA, deep completions, weather, market value |
| 3 | 2026-02-10 | E20-03 Market-Augmented | 2024-25 | 760 (2 seasons) | 0.6105 | -3.50 | +Pinnacle odds, Asian Handicap line as features |
| 4 | 2026-02-25 | E23-06 Full Backfill | 2024-25 | 2,280 (6 seasons) | 0.5781 | +2.78 | 3x training data from historical backfill — **model now profitable** |
| 5 | 2026-03-03 | E25-03 XGBoost Comparison | 2024-25 | 1,900 (5 seasons) | 0.5781 | +2.78 | Poisson wins — XGBoost overfits (Brier 0.5821, ROI -19%), ensemble unprofitable |

### Brier Score Progression
```
0.72 ████████████████████████████████████████████████  E13-03
0.69 ██████████████████████████████████████████████    E16-03  (-4.2%)
0.61 ████████████████████████████████████████          E20-03  (-11.6%)
0.58 ██████████████████████████████████████            E23-06  (-5.3%)
0.58 ██████████████████████████████████████            E25-03  (unchanged)
     ─────────────────────────────────────────────
     0.50          0.60          0.70          0.80
     (perfect=0)                         (random=0.75)
```

### ROI Progression
```
-15.0% ████████████████████████████████  E13-03
 -7.2% ████████████████                  E16-03
 -3.5% ████████                          E20-03
 +2.8% ██████ (profitable)               E23-06  <-- current
 +2.8% ██████ (profitable)               E25-03
       ──────────────────────────────
       -15%    -10%    -5%    0%    +5%
```

---

## Latest Backtest: E25-03 (2026-03-03)

### Setup
- **Evaluation season:** 2024-25 EPL (380 matches, 109 matchdays)
- **Training seasons:** 2020-21, 2021-22, 2022-23, 2023-24, 2024-25
- **Walk-forward:** Retrain on ALL data before each matchday, predict forward
- **Edge threshold:** 5%
- **Staking:** Flat 2% of bankroll
- **Starting bankroll:** 1,000

### Three-Way Comparison

| Metric | Poisson-only | XGBoost-only | Ensemble (50/50) |
|--------|:------------:|:------------:|:----------------:|
| **Brier Score** | 0.5781 | 0.5821 | **0.5778** |
| **ROI (%)** | **+2.78** | -19.02 | -9.39 |
| **Total PnL** | **+356.33** | -861.70 | -607.05 |
| **Final Bankroll** | **1,356.33** | 138.30 | 392.95 |
| Value Bets Found | 634 | 769 | 580 |
| Total Staked | 12,825.09 | 4,529.47 | 6,463.59 |
| Max Drawdown (%) | **69.2** | 95.5 | 82.8 |
| Win Rate 1X2 (%) | **33.2** | 30.4 | 32.7 |
| Win Rate O/U (%) | **42.7** | 41.1 | 34.0 |
| Win Rate BTTS (%) | 0.0 | 0.0 | 0.0 |
| Matches Predicted | 380 | 380 | 380 |
| Compute Time (s) | 128.7 | 973.2 | 443.2 |

**Winner: Poisson-only** — the only profitable configuration.

### Why XGBoost Underperformed
- ~1,900 training samples is insufficient for 200-tree gradient boosting with 30+ features
- XGBoost learns non-linear patterns that don't persist out-of-sample (overfitting)
- Poisson GLM's linear-in-log-space constraint acts as strong regularisation
- XGBoost generates more value bets (769 vs 634) but at worse quality (net -19% ROI)
- **Revisit when training data exceeds 5,000 matches** (post-2027 with 7+ EPL seasons)

### Poisson Calibration (Backtest, 2024-25)

How well do predicted probabilities match actual outcomes?

| Predicted Range | Predicted Avg | Actual Rate | Count | Deviation |
|:---------------:|:-------------:|:-----------:|:-----:|:---------:|
| 0.0 - 0.1 | 0.0782 | 0.000 | 11 | -0.078 |
| 0.1 - 0.2 | 0.1651 | 0.144 | 181 | -0.021 |
| 0.2 - 0.3 | 0.2422 | 0.243 | 461 | +0.001 |
| 0.3 - 0.4 | 0.3507 | 0.363 | 146 | +0.012 |
| 0.4 - 0.5 | 0.4484 | 0.430 | 128 | -0.019 |
| 0.5 - 0.6 | 0.5449 | 0.574 | 108 | +0.029 |
| 0.6 - 0.7 | 0.6448 | 0.663 | 83 | +0.018 |
| 0.7 - 0.8 | 0.7338 | 0.765 | 17 | +0.031 |
| 0.8 - 0.9 | 0.8306 | 0.800 | 5 | -0.031 |

**Mean absolute calibration error: ~0.027** (well below the 0.03 recalibration threshold).
The model is well-calibrated across all probability bins. The 0.0-0.1 bin shows the largest
deviation but has only 11 observations (statistically insignificant).

### XGBoost Calibration (Backtest, 2024-25)

| Predicted Range | Predicted Avg | Actual Rate | Count | Deviation |
|:---------------:|:-------------:|:-----------:|:-----:|:---------:|
| 0.0 - 0.1 | 0.0789 | 0.000 | 17 | -0.079 |
| 0.1 - 0.2 | 0.1639 | 0.167 | 216 | +0.003 |
| 0.2 - 0.3 | 0.2420 | 0.260 | 435 | +0.018 |
| 0.3 - 0.4 | 0.3477 | 0.312 | 125 | -0.036 |
| 0.4 - 0.5 | 0.4467 | 0.425 | 113 | -0.022 |
| 0.5 - 0.6 | 0.5500 | 0.541 | 109 | -0.009 |
| 0.6 - 0.7 | 0.6460 | 0.645 | 93 | -0.001 |
| 0.7 - 0.8 | 0.7352 | 0.741 | 27 | +0.006 |
| 0.8 - 0.9 | 0.8364 | 1.000 | 5 | +0.164 |

### Ensemble Calibration (Backtest, 2024-25)

| Predicted Range | Predicted Avg | Actual Rate | Count | Deviation |
|:---------------:|:-------------:|:-----------:|:-----:|:---------:|
| 0.0 - 0.1 | 0.0795 | 0.000 | 10 | -0.080 |
| 0.1 - 0.2 | 0.1665 | 0.138 | 203 | -0.029 |
| 0.2 - 0.3 | 0.2421 | 0.252 | 448 | +0.010 |
| 0.3 - 0.4 | 0.3503 | 0.355 | 138 | +0.005 |
| 0.4 - 0.5 | 0.4514 | 0.429 | 119 | -0.023 |
| 0.5 - 0.6 | 0.5477 | 0.582 | 110 | +0.034 |
| 0.6 - 0.7 | 0.6468 | 0.637 | 91 | -0.010 |
| 0.7 - 0.8 | 0.7385 | 0.778 | 18 | +0.039 |
| 0.8 - 0.9 | 0.8271 | 1.000 | 3 | +0.173 |

---

## Live Betting Performance (as of 2026-03-03)

### Overall
| Metric | Value |
|--------|-------|
| **Total bets placed** | 1,981 (1,980 system_pick + 1 user_placed) |
| **Resolved bets** | 1,330 |
| **Pending bets** | 651 |
| **Won** | 401 (30.2% of resolved) |
| **Lost** | 929 (69.8% of resolved) |
| **Total staked** | 26,606.32 |
| **Total PnL** | **+368.90** |
| **ROI** | **+1.4%** |
| **Date range** | 2024-08-16 to 2026-02-23 |

### By Market Type (Resolved Bets Only)

| Market | Bets | Won | Lost | Win % | Staked | PnL | ROI |
|--------|:----:|:---:|:----:|:-----:|-------:|----:|:---:|
| **1X2** | 1,139 | 308 | 831 | 27.0% | 22,780.00 | -71.80 | **-0.3%** |
| **OU25** | 191 | 93 | 98 | 48.7% | 3,826.32 | +440.70 | **+11.5%** |
| **Total** | **1,330** | **401** | **929** | **30.2%** | **26,606.32** | **+368.90** | **+1.4%** |

**Key insight:** The Over/Under 2.5 goals market is highly profitable at +11.5% ROI.
The 1X2 (match result) market is approximately breakeven at -0.3%. The model's edge
is concentrated in the totals market.

### Value Bets by Market (Including Pending)

| Market | Total VBs |
|--------|:---------:|
| 1X2 | 1,733 |
| OU25 | 247 |
| OU35 | 0 |
| BTTS | 0 |

### Average Model Probabilities (All 760 Predictions)

| Outcome | Avg Probability |
|---------|:---------------:|
| Home Win | 39.9% |
| Draw | 24.8% |
| Away Win | 35.4% |
| Over 2.5 | 52.2% |
| Under 2.5 | 47.8% |

---

## Database Inventory (as of 2026-03-03)

### Matches by Season

| Season | Total | Finished | Scheduled | Teams |
|--------|:-----:|:--------:|:---------:|:-----:|
| 2020-21 | 380 | 380 | 0 | 20 |
| 2021-22 | 380 | 380 | 0 | 20 |
| 2022-23 | 380 | 380 | 0 | 20 |
| 2023-24 | 380 | 380 | 0 | 20 |
| 2024-25 | 380 | 380 | 0 | 20 |
| 2025-26 | 380 | 281 | 99 | 20 |
| **Total** | **2,280** | **2,181** | **99** | **28 unique** |

### Data Assets

| Asset | Records | Coverage |
|-------|--------:|----------|
| Odds | 34,076 | 6 seasons (Football-Data.co.uk + The Odds API) |
| Features | 4,560 | 6 seasons (760 per season = 380 matches x 2 teams) |
| MatchStats (xG/NPxG/PPDA) | 4,362 | 5.5 seasons (2020-21 through mid-2025-26) |
| ClubElo ratings | 17,965 | 6 seasons |
| Predictions | 760 | 2024-25 + 2025-26 |
| Value Bets | 1,981 | 2024-25 + 2025-26 |
| BetLog entries | 1,981 | 2024-25 + 2025-26 |

### Odds by Market Type

| Market | Records | % of Total |
|--------|--------:|:----------:|
| 1X2 | 27,273 | 80.0% |
| OU25 | 4,902 | 14.4% |
| AH | 1,801 | 5.3% |
| OU35 | 100 | 0.3% |

### Odds Sources

| Source | Records |
|--------|--------:|
| Football-Data.co.uk (CSV) | ~31,006 |
| The Odds API (live) | ~3,070 |

---

## Feature Set (Current Production)

The Poisson model uses the following features per team (home/away prefix):

### Rolling Form (5 and 10 match windows)
- `form_5`, `form_10` — points per game
- `goals_scored_5`, `goals_scored_10` — goals scored rolling avg
- `goals_conceded_5`, `goals_conceded_10` — goals conceded rolling avg
- `shots_on_target_5` — shots on target rolling avg
- `venue_form_5` — home/away specific form
- `venue_goals_scored_5`, `venue_goals_conceded_5` — venue-specific goals

### Advanced Stats (from Understat)
- `npxg_5` — non-penalty expected goals (5-match rolling)
- `npxga_5` — non-penalty xG against
- `ppda_allowed_5` — passes per defensive action allowed
- `deep_5` — deep completions (passes into final third)

### Set-Piece Breakdown (E22-01)
- `set_piece_xg_5` — set-piece expected goals (5-match rolling)
- `open_play_xg_5` — open-play expected goals

### Market-Implied Features (E20-01, E20-02)
- `pinnacle_home_prob`, `pinnacle_draw_prob`, `pinnacle_away_prob` — overround-removed
- `ah_line` — Asian Handicap line

### External Ratings (E21-01)
- `elo_rating` — ClubElo rating on match date
- `elo_diff` — team Elo minus opponent Elo

### Context Features
- `rest_days` — days since last match
- `h2h_goals_scored` — head-to-head historical goals
- `market_value_ratio` — Transfermarkt squad value ratio
- `is_heavy_weather` — rain/snow flag from Open-Meteo
- `ref_avg_goals` — referee's average goals per match (E21-02)
- `ref_home_win_pct` — referee home bias signal (E21-02)
- `is_congested` — fixture congestion flag (<4 days rest, E21-03)
- `injury_impact` — sum of injury impact ratings (E22-02)
- `key_player_out` — binary flag for high-impact absence (E22-02)

**Total: ~30 features per team (60 features per match)**

Features are selected dynamically — only columns present in the DataFrame
are used (`available = [c for c in all_candidates if c in df.columns]`).

---

## Self-Improvement Module Status (as of 2026-03-03)

| Module | Status | Trigger Threshold | Current Count |
|--------|--------|-------------------|:-------------:|
| Recalibration (Platt/Isotonic) | Inactive | 200 resolved predictions | 380 (backtest only) |
| Feature Importance Tracking | Inactive | XGBoost/LightGBM required | Poisson-only (N/A) |
| Adaptive Ensemble Weights | Inactive | 300 per model | Single model |
| Market Feedback Loop | Inactive | 50 per league/market | Accumulating |
| Retrain Trigger | Inactive | 15% Brier degradation | Monitoring |

### History Tables (all empty)
- CalibrationHistory: 0 records
- RetrainHistory: 0 records
- EnsembleWeightHistory: 0 records
- FeatureImportanceLog: 0 records
- MarketPerformance: 0 records

---

## CLV (Closing Line Value) Status

CLV infrastructure is built but not yet populated:
- `BetLog.closing_odds` column exists — always NULL
- `BetLog.clv` column exists — always NULL
- `metrics.calculate_clv()` is implemented
- Model Health CLV chart renders empty state

**Blocker:** Closing odds require a second odds scrape after match start (Football-Data CSV
provides Pinnacle closing odds for historical matches, but the pipeline doesn't yet run a
post-kickoff scrape from The Odds API to capture closing odds for live matches).

---

## Methodology Notes

### Brier Score
Three-outcome Brier score for 1X2 markets:
```
Brier = (1/N) * sum[(p_home - y_home)^2 + (p_draw - y_draw)^2 + (p_away - y_away)^2]
```
where y is 1 for the actual outcome and 0 otherwise.
- **0.0** = perfect predictions
- **0.75** = random guessing (uniform 1/3 probabilities)
- **< 0.25** = better than random, meaningful skill

### ROI
```
ROI = (Total PnL / Total Staked) x 100
```
Positive ROI = profitable. The industry standard for a successful model is sustained
ROI > 0% over 1,000+ bets.

### Walk-Forward Backtest
The ONLY valid backtesting method for time-series prediction:
1. Start at matchday 1 of the evaluation season
2. Train on ALL data before matchday 1 (all prior seasons)
3. Predict matchday 1, find value bets, simulate staking
4. Advance to matchday 2, retrain on all data before matchday 2
5. Continue through all 109 matchdays

This prevents look-ahead bias — the model never sees future data.

### Value Bet Detection
A fixture is a value bet when:
```
edge = model_probability - implied_odds_probability >= threshold (5%)
```
The model must believe the outcome is at least 5 percentage points more likely than
the bookmaker's odds imply.

### Calibration
Predictions are binned by probability range (0.0-0.1, 0.1-0.2, ..., 0.8-0.9).
For each bin, we compare:
- **Predicted average:** mean of model probabilities in this bin
- **Actual rate:** fraction of outcomes that actually occurred

A perfectly calibrated model has predicted_avg == actual_rate in every bin.

---

## How to Reproduce

### Run backtest
```bash
source venv/bin/activate
python scripts/e25_03_backtest.py
```

### Check live performance
```bash
source venv/bin/activate
python -c "
from src.database.db import get_session
from src.database.models import BetLog
with get_session() as s:
    won = s.query(BetLog).filter_by(status='won').count()
    lost = s.query(BetLog).filter_by(status='lost').count()
    print(f'Won: {won}, Lost: {lost}, Win rate: {won/(won+lost)*100:.1f}%')
"
```

### Check model performance records
```bash
source venv/bin/activate
python -c "
from src.database.db import get_session
from src.database.models import ModelPerformance
with get_session() as s:
    for r in s.query(ModelPerformance).all():
        print(f'{r.model_name:20s} | {r.period_type:10s} | brier={r.brier_score} | roi={r.roi}')
"
```

---

*Last updated: 2026-03-03 by Claude Code (E25-04 completion)*
*Next update: after any model change, feature addition, or significant data update*
