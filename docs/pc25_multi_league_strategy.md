# PC-25: Multi-League Strategy System
## BetVector — Per-League Optimization Plan

Version 1.0 · March 2026

---

## Executive Summary

PC-24 proved that the same optimization lever can be poison for one league and gold for another — Pinnacle-only filtering improved LaLiga by +21.49pp and Ligue1 by +22.14pp, yet destroyed EPL and Championship performance. This plan introduces **per-league strategy profiles**: each league gets its own optimized combination of edge threshold, sharp filtering, stake weighting, and exposure limits — operating as independent units within one unified system.

The plan is grounded in four streams of research: master plan alignment, architecture feasibility, academic betting literature, and deep backtest data analysis.

---

## Current State Assessment

### Portfolio Performance (PC-24-05 Final Report)

| League | ROI | 95% CI | Tier | Value Bets | PnL |
|--------|-----|--------|------|-----------|-----|
| Championship | +10.52% | [+3.5%, +23.0%] | 🟢 Profitable | 731 | +$4,270 |
| LaLiga | +18.05% | [-9.2%, +50.3%] | 🟡 Promising | 110 | +$460 |
| EPL | -12.94% | [-17.4%, +1.5%] | 🟡 Promising | 1,229 | -$930 |
| Ligue1 | -21.76% | [-28.9%, -1.1%] | 🔴 Unprofitable | 257 | -$572 |
| Bundesliga | -21.15% | [-35.2%, -7.4%] | 🔴 Unprofitable | 245 | -$671 |
| SerieA | -18.65% | [-32.4%, -4.2%] | 🔴 Unprofitable | 240 | -$617 |
| **Aggregate** | **+3.26%** | | | **2,812** | **+$1,940** |

### The Concentration Risk Problem

Championship's +$4,270 carries the entire system. Without it, the aggregate PnL would be **-$2,330**. The portfolio is concentration risk masquerading as diversification — one league's market inefficiency subsidizes five leagues of losses.

### The Untapped Opportunity

PC-24-02 (Pinnacle-only filtering) was rolled back globally because it failed in aggregate. But per-league analysis revealed:

| League | Standard ROI | With Pinnacle-Only | Delta |
|--------|-------------|-------------------|-------|
| LaLiga | +18.05% | ~+39.5% | **+21.49pp** |
| Ligue1 | -21.76% | ~+0.4% | **+22.14pp** |
| EPL | -12.94% | -25.1% | -12.2pp |
| Championship | +10.52% | +4.8% | -5.7pp |

**The single biggest insight: per-league sharp filtering could turn Ligue1 from confirmed unprofitable to break-even, and double LaLiga's already-strong ROI.**

---

## Research Foundations

### 1. Market Efficiency Is Not Uniform

Academic research (University of Reading, 16,000+ matches) quantifies the liquidity gap:

- **EPL**: £23,262 average bet volume per match — highest sharp bettor density, fastest price discovery
- **Championship**: £3,044 (13% of EPL) — fewer sharp bettors, larger pricing errors persist longer
- **League One**: £1,030 (4.5% of EPL) — edges can persist 1-3 seasons

This explains why Championship is profitable: less efficient markets = larger, more persistent edges.

### 2. CLV > ROI for Edge Measurement

| Metric | Bets Needed for 95% Significance | Time at BetVector's Volume |
|--------|----------------------------------|---------------------------|
| ROI | ~2,000 bets | 4-5 years |
| CLV (Closing Line Value) | ~50 bets | 2-3 months |

CLV measures whether your bet beat the closing line — the final odds before kickoff. Professional operations use CLV as their primary edge metric because it converges 40x faster than ROI. BetVector generates ~400-600 value bets per year; at that rate, ROI confidence intervals remain too wide for decision-making for years. CLV gives actionable signal within months.

### 3. Unified Model Beats Per-League Models

At fewer than 5,000 matches per league, a single unified model with league features outperforms separate per-league models. BetVector's architecture (one Poisson model with league-aware features + one XGBoost model) is correct for current data volumes. The cross-league information transfer (how home advantage works, how form decays) benefits all leagues.

### 4. Daily Exposure Caps Are Non-Negotiable

Professional operations never risk more than 15-20% of bankroll per day across all bets combined. BetVector's current per-bet cap (5%) provides no aggregate protection — 10 value bets in a day means 50% of bankroll deployed simultaneously.

### 5. Calibration-Based Triggers, Not ROI-Based

A 2024 paper (Wilkens, Machine Learning with Applications) found that model selection by calibration (Brier score) produced **+34.69% ROI** out-of-sample, while model selection by raw accuracy produced **-35.17% ROI**. Never adjust strategy based on short-term ROI — use calibration metrics.

---

## The Three-Phase Plan

### Phase 1 — Foundation (Now → 2 weeks)
*Stop the bleeding, protect what works, instrument everything*

#### PC-25-01: League Strategy Profiles in Config

Add a `strategy` block to each league in `leagues.yaml`:

```yaml
- name: "Championship"
  short_name: "Championship"
  edge_threshold_override: 0.10
  strategy:
    sharp_only: false          # All bookmakers (market inefficient enough)
    staking: "flat"
    stake_multiplier: 1.0      # Standard allocation
    auto_bet: true             # 🟢 tier — system recommends
    clv_tracking: true
    max_daily_bets: 10

- name: "La Liga"
  short_name: "LaLiga"
  edge_threshold_override: 0.08
  strategy:
    sharp_only: true           # +21.49pp with Pinnacle-only
    staking: "flat"
    stake_multiplier: 1.0
    auto_bet: false            # 🟡 tier — analysis only
    clv_tracking: true
    max_daily_bets: 8
```

Pipeline reads these per-league. No architectural change — extends the existing `edge_threshold_override` config pattern.

#### PC-25-02: Per-League Sharp-Only Filtering

The highest-impact single change available. Make `sharp_only` per-league instead of global:

| League | sharp_only | Rationale |
|--------|-----------|-----------|
| LaLiga | `true` | +21.49pp ROI improvement in backtest |
| Ligue1 | `true` | +22.14pp ROI improvement in backtest |
| EPL | `false` | Pinnacle filtering hurt EPL by -12.2pp |
| Championship | `false` | Market is inefficient enough without filtering |
| Bundesliga | `false` | Insufficient data to justify change |
| SerieA | `false` | Insufficient data to justify change |

Requires modifying `ValueFinder.find_value_bets()` to read the league's strategy config instead of the function-level parameter.

#### PC-25-03: Aggregate Daily Exposure Cap

Add to `config/settings.yaml`:

```yaml
safety:
  max_daily_exposure: 0.15     # Never stake >15% of bankroll in one day
  max_league_exposure: 0.08    # Never stake >8% on a single league per day
```

Enforced in `BankrollManager.calculate_stake()` — checks cumulative daily stakes before approving new bets.

#### PC-25-04: CLV Tracking Infrastructure

Add a `clv` column to the `value_bets` table. During the evening pipeline (when results and closing odds come in), compute:

```
CLV = (closing_implied_prob / prediction_time_implied_prob) - 1
```

Positive CLV = your bet got better odds than the market settled at = real edge signal. Track per-league CLV trend on the dashboard.

#### PC-25-05: Backtest Validation

Before deploying PC-25-02 live, run a proper validation backtest:
- 6-league backtest with LaLiga + Ligue1 set to `sharp_only: true`, all others `false`
- Compute CI on the per-league and aggregate improvement
- Verify no league regresses more than 5pp

#### PC-25-06: Raise profitable_min_bets to 250

At 100 bets with a true +5% ROI, there's a 37% chance of showing negative ROI through pure variance. Raise the threshold in `settings.yaml`:

```yaml
self_improvement:
  market_feedback:
    profitable_min_bets: 250   # Was 100 — statistically insufficient
```

#### PC-25-07: Integration Tests

Test all new config loading, exposure cap enforcement, CLV computation, and strategy profile application.

---

### Phase 2 — Intelligence (Weeks 3-6)
*Let the system learn which levers work for which leagues*

#### PC-25-08: Per-League Market Assessment (MP §11.4)

Break down the existing league-level assessment to **league × market** granularity:

- Championship × 1X2: tier assessment with CI
- Championship × OU25: separate tier
- LaLiga × 1X2 with Pinnacle-only: how does it perform?

Runs weekly (Sunday evening per MP §11.4). Each cell gets its own assessment tier. Surfaces in the dashboard as a heatmap.

#### PC-25-09: Stake Multiplier Calibration

Weight flat stakes by tier:

| Tier | Multiplier | Effect |
|------|-----------|--------|
| 🟢 Profitable | 1.5x | Lean into verified edge |
| 🟡 Promising | 1.0x | Standard stake |
| 🔴 Unprofitable | 0.5x | Reduce exposure, keep learning |
| ⚪ Insufficient | 0.5x | Small stakes to gather data |

This is NOT Kelly staking (which we rolled back). It's simple multipliers on the flat stake — Championship at 1.5x, Bundesliga at 0.5x.

#### PC-25-10: Dashboard — League Strategy View

Add a "League Strategy" section to the Model Health page:
- Per-league strategy profile (threshold, sharp_only, multiplier, tier)
- Per-league CLV trend chart
- League × market assessment heatmap (MP §11.4)
- Suggested strategy changes (displayed, never auto-applied)

#### PC-25-11: Automated Weekly Strategy Review

Extend the Sunday evening pipeline to:
1. Recompute all league tiers with updated CI
2. Recompute per-league CLV trends
3. Flag tier transitions in the weekly email (e.g., "LaLiga moved from 🟡 to 🟢")
4. Suggest strategy changes — but never auto-apply (MP: "recommend, don't force")

---

### Phase 3 — Experimentation (Months 2-4)
*Systematic testing of new levers*

#### PC-25-12: Shadow Mode for Strategy Changes

Before applying any strategy change live, run it in "shadow mode" for 4 weeks:
- System computes what WOULD have happened with the proposed change
- Tracks shadow PnL alongside real PnL
- Only promotes to live if shadow outperforms by >3pp ROI

#### PC-25-13: Per-League Model Variants

With the unified model as the foundation, add league-specific tuning:
- Per-league Dixon-Coles ρ estimation (currently computed globally from training data, which is already league-filtered)
- League-specific lambda clamps (Bundesliga averages more goals than Serie A)
- Training data weighting by league when predicting for that league

#### PC-25-14: Expand to Value Leagues

Once the framework is proven, add leagues with larger market inefficiency:
- Eredivisie (Netherlands)
- Portuguese Liga
- Belgian Pro League
- Turkish Süper Lig

These leagues have less bookmaker attention → larger edges → but also less data → higher variance. The tier system handles this naturally.

#### PC-25-15: Probabilistic Kelly with Per-League Guardrails

Re-attempt Kelly staking, but ONLY on 🟢 profitable leagues with:
- Max 3% per bet (not 5%)
- Only Championship initially (our only 🟢 league with n=731)
- Shadow mode first (PC-25-12)
- Quarter-Kelly fraction (0.25)
- Automatic rollback if drawdown exceeds 15%

---

## Config Architecture

The complete per-league strategy profile in `leagues.yaml`:

```yaml
- name: "Championship"
  short_name: "Championship"
  country: "England"
  football_data_code: "E1"
  # ... existing data source fields ...
  edge_threshold_override: 0.10     # PC-24-01: validated
  strategy:                          # PC-25-01: new
    sharp_only: false                # PC-25-02: all bookmakers
    stake_multiplier: 1.5            # PC-25-09: 🟢 profitable tier
    max_daily_bets: 10               # PC-25-03: per-league cap
    auto_bet: true                   # 🟢 tier — system recommends
    clv_tracking: true               # PC-25-04: enabled
    shadow_mode: false               # PC-25-12: not in shadow
```

Pipeline reads strategy with fallback to global defaults:
```python
sharp_only = getattr(league_cfg, 'strategy', {}).get('sharp_only', False)
stake_mult = getattr(league_cfg, 'strategy', {}).get('stake_multiplier', 1.0)
```

---

## Risk Management

### What This Plan Does NOT Do

- **No separate bankroll pools per league** — too complex, stake multipliers achieve 90% of the value
- **No per-league XGBoost models** — insufficient data (<5K matches/league), unified model performs better
- **No automatic bet suppression** — MP says "recommend, don't force." Unprofitable leagues get warnings, not exclusion
- **No ROI-based strategy changes** — all triggers are calibration-based (Brier score, CLV). ROI is too noisy for decision-making at current sample sizes

### Guardrails

| Guardrail | Value | Source |
|-----------|-------|--------|
| Min bets for "profitable" | 250 | Research: 37% false negative at n=100 |
| Max daily exposure | 15% | Professional operations standard |
| Max per-league daily exposure | 8% | Prevents Championship concentration |
| Strategy change validation | 4-week shadow mode | PC-25-12 |
| Retrain cooldown | 30 days | MP §11.5 |
| Ensemble weight max change | ±10pp per cycle | MP §11.3 |
| Edge metric for decisions | CLV (primary), Brier (secondary) | 50 bets for significance |
| ROI metric for decisions | Display only until n > 2,000 | 4-5 years at current volume |

---

## Expected Impact

### Phase 1 (Immediate)

| Change | League | Expected Impact |
|--------|--------|----------------|
| Per-league sharp_only | LaLiga | ROI +18% → ~+39% (Pinnacle filter) |
| Per-league sharp_only | Ligue1 | ROI -22% → ~0% (break-even) |
| Daily exposure cap | All | Prevents >15% single-day risk |
| CLV tracking | All | Edge validation in 2-3 months vs 4-5 years |

### Phase 2 (Medium-term)

| Change | Impact |
|--------|--------|
| Stake multipliers | Capital tilts toward proven leagues |
| Market × league assessment | Know WHERE the edge is (not just IF) |
| Weekly strategy review | Tier transitions flagged automatically |

### Phase 3 (Long-term)

| Change | Impact |
|--------|--------|
| Shadow mode | Every strategy change validated before deployment |
| Value leagues | More markets with larger inefficiency |
| Per-league Kelly | Higher returns on verified edges only |

---

## Master Plan Alignment

This plan is a **Tier 2 change** per CLAUDE.md Rule 8 — it adds new issues to the critical path and introduces per-league strategy as an architectural concept.

### What Already Exists in MP

- MP §11.4: Per-league × market assessment tiers (envisioned, not yet granular)
- MP §4: Edge thresholds adjustable 1-15%
- MP §11.4: "No automatic filtering" — recommend, don't force
- `edge_threshold_override` config pattern (PC-24-01)

### What's New

- Per-league strategy profiles (sharp_only, stake_multiplier, exposure caps)
- CLV as primary edge metric (currently secondary)
- Daily exposure caps (currently no aggregate cap)
- Shadow mode for strategy changes
- `profitable_min_bets` raised from 100 to 250

### Implementation Difficulty

| Component | Difficulty | Reason |
|-----------|-----------|--------|
| Config (leagues.yaml) | Easy | Extends existing pattern |
| Per-league sharp_only | Easy | ValueFinder already accepts param |
| Stake multipliers | Easy | One multiplication in calculate_stake() |
| Daily exposure cap | Easy | New safety check in bankroll manager |
| CLV tracking | Medium | Closing odds capture + new column |
| Market × league heatmap | Medium | Extends market_feedback module |
| Shadow mode | Medium | Parallel tracking infrastructure |
| Self-improvement DB columns | Easy | Nullable league column (NULL = global) |

---

*Document prepared March 2026. Based on research across master plan analysis, architecture review, academic betting literature, and 6-league backtest data analysis.*
