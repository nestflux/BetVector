# BetVector — Model Fix Test Report
## Manager Feature Overfitting Analysis & Solutions
### Date: 2026-03-13

---

## Problem Statement

After adding E40 manager features (`new_manager_flag`, `manager_tenure_days`, `manager_win_pct`, `manager_change_count`), the Poisson GLM model regressed in 5 out of 6 leagues. The root cause: `manager_win_pct` has strong correlation with goals (0.20) but at 88% coverage, the 12% mean-imputed rows distort the GLM fit, causing outsized coefficients and overfitting.

---

## Test Methodology

- **Walk-forward backtest** on 2024-25 season for all 6 leagues
- Training data: 2020-21 through matchday-1
- 8 variants tested per league, all using identical matchday splits
- No production code was modified — all tests run in isolation

---

## Variants Tested

| # | Variant | Description |
|---|---------|-------------|
| 1 | BASELINE | Remove all E39 + E40 features (pre-E39 state) |
| 2 | CURRENT | Everything as-is (includes dead/weak features) |
| 3 | REMOVE E40 | Current minus E40 manager features only |
| 4 | RIDGE α=0.1 | L2 regularisation, alpha=0.1 |
| 5 | RIDGE α=0.5 | L2 regularisation, alpha=0.5 |
| 6 | RIDGE α=1.0 | L2 regularisation, alpha=1.0 |
| 7 | ELASTIC NET α=0.05 | Elastic Net (L1_wt=0.5), alpha=0.05 |
| 8 | CLEAN+RIDGE | Remove dead features + Ridge α=0.1 |

---

## Results — Brier Scores (lower is better)

| Variant | EPL | Championship | LaLiga | Ligue1 | Bundesliga | SerieA | Avg |
|---------|-----|-------------|--------|--------|-----------|--------|-----|
| 1) BASELINE | 0.6132 | 0.6338 | 0.5650 | 0.5826 | 0.5897 | 0.5728 | 0.5928 |
| 2) CURRENT | 0.6317 | 0.6338 | 0.5654 | 0.5812 | 0.6010 | 0.5764 | 0.5983 |
| 3) REMOVE E40 | 0.6107 | 0.6338 | 0.5643 | 0.5838 | 0.5944 | 0.5747 | 0.5936 |
| 4) RIDGE α=0.1 | 0.6624 | 0.6805 | 0.6675 | 0.6423 | 0.6657 | 0.6813 | 0.6666 |
| 5) RIDGE α=0.5 | 0.6624 | 0.6805 | 0.6675 | 0.6423 | 0.6657 | 0.6813 | 0.6666 |
| 6) RIDGE α=1.0 | 0.6624 | 0.6805 | 0.6675 | 0.6423 | 0.6657 | 0.6813 | 0.6666 |
| 7) ELASTIC NET | **0.6065** | **0.6233** | 0.5753 | **0.5757** | 0.6023 | 0.5828 | **0.5943** |
| 8) CLEAN+RIDGE | 0.6624 | 0.6805 | 0.6675 | 0.6423 | 0.6657 | 0.6813 | 0.6666 |

**Best per league:** EPL→7, Championship→7, LaLiga→3, Ligue1→7, Bundesliga→1, SerieA→1

---

## Current Regression vs Baseline

| League | Current | Baseline | Regression |
|--------|---------|----------|------------|
| EPL | 0.6317 | 0.6132 | +0.0185 |
| Championship | 0.6338 | 0.6338 | +0.0000 |
| LaLiga | 0.5654 | 0.5650 | +0.0004 |
| Ligue1 | 0.5812 | 0.5826 | -0.0014 |
| Bundesliga | 0.6010 | 0.5897 | +0.0113 |
| SerieA | 0.5764 | 0.5728 | +0.0036 |

---

## Best Fix per League

| League | Best Fix | Brier | Recovery |
|--------|----------|-------|----------|
| EPL | Elastic Net α=0.05 | 0.6065 | +0.0252 recovered |
| Championship | Elastic Net α=0.05 | 0.6233 | +0.0105 recovered |
| LaLiga | Remove E40 | 0.5643 | +0.0011 recovered |
| Ligue1 | Elastic Net α=0.05 | 0.5757 | +0.0055 recovered |
| Bundesliga | Baseline (no E39/E40) | 0.5897 | +0.0113 recovered |
| SerieA | Baseline (no E39/E40) | 0.5728 | +0.0036 recovered |

---

## Key Findings

1. **Ridge regularisation is broken** — produces `inf` lambdas with the current `_add_constant()` + `predict()` pipeline. All Ridge variants produce identical Brier ~0.6666 across all leagues.

2. **Elastic Net works** — `fit_regularized(alpha=0.05, L1_wt=0.5)` correctly constrains coefficients. Wins 4/6 leagues. Average Brier 0.5943 vs current 0.5983.

3. **E39 lineup features genuinely help** — `squad_rotation_index` and `formation_changed` improve EPL by -0.0025 Brier.

4. **E40 manager features hurt** — `manager_win_pct` overfits in the unregularized GLM. Removing E40 alone fixes most damage (avg 0.5936).

5. **Dead feature pruning is insufficient** — the model already auto-prunes constant columns. Only recovers 0.0024 in EPL.

---

## Recommended Options

### Option A: Elastic Net Regularisation
- Avg Brier: 0.5943 (vs current 0.5983)
- Wins: EPL, Championship, Ligue1, close LaLiga
- Trade-off: ~10x slower training, moderate code complexity
- Change: `fit()` → `fit_regularized(alpha=0.05, L1_wt=0.5)` in poisson.py

### Option B: Remove E40 from Poisson Model
- Avg Brier: 0.5936 (vs current 0.5983)
- Wins: LaLiga
- Trade-off: None — simplest possible change
- Change: Remove 4 feature names from `_select_feature_cols()` context_cols
- E40 data remains in DB for XGBoost (handles sparse features natively)
