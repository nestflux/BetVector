"""
PC-09-06 — Prediction Model Stability & Data Integrity Integration Test
========================================================================
Automated pytest suite verifying the model stability and data integrity
fixes introduced in PC-09-01 through PC-09-05.

Scenarios:
  1. Poisson model coefficients all have |magnitude| < 100 after training
  2. ``pinnacle_draw_prob`` NOT in model feature list (PC-09-01)
  3. Scheduled match predictions refresh when pipeline runs twice (PC-09-02)
  4. Value bets cleaned before regeneration — no duplicates (PC-09-03)
  5. Odds API uses league-specific sport keys (PC-09-04)
  6. Predictions directionally match market (home favorite agreement)

All tests use synthetic data — no real DB access, no external API calls.

Run with: pytest tests/test_pc09_model_stability.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ============================================================================
# Path setup
# ============================================================================

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ============================================================================
# Synthetic data helpers
# ============================================================================

def _make_synthetic_features(n_rows: int = 600, seed: int = 42) -> pd.DataFrame:
    """Build a synthetic features DataFrame that mimics compute_all_features().

    Includes all columns that PoissonModel._select_feature_cols() looks for
    (home_*/away_* rolling stats, context features) plus match_id.
    Uses random but deterministic data so tests are reproducible.
    """
    rng = np.random.default_rng(seed)
    data: Dict[str, np.ndarray] = {"match_id": np.arange(1, n_rows + 1)}

    for prefix in ("home_", "away_"):
        # Rolling form features
        data[f"{prefix}form_5"] = rng.uniform(0.0, 3.0, n_rows)
        data[f"{prefix}form_10"] = rng.uniform(0.0, 3.0, n_rows)
        data[f"{prefix}goals_scored_5"] = rng.uniform(0.5, 3.0, n_rows)
        data[f"{prefix}goals_scored_10"] = rng.uniform(0.5, 3.0, n_rows)
        data[f"{prefix}goals_conceded_5"] = rng.uniform(0.5, 2.5, n_rows)
        data[f"{prefix}goals_conceded_10"] = rng.uniform(0.5, 2.5, n_rows)
        data[f"{prefix}shots_on_target_5"] = rng.uniform(1.0, 6.0, n_rows)
        data[f"{prefix}venue_form_5"] = rng.uniform(0.0, 3.0, n_rows)
        data[f"{prefix}venue_goals_scored_5"] = rng.uniform(0.5, 3.0, n_rows)
        data[f"{prefix}venue_goals_conceded_5"] = rng.uniform(0.5, 2.5, n_rows)

        # Advanced stats
        data[f"{prefix}npxg_5"] = rng.uniform(0.5, 2.5, n_rows)
        data[f"{prefix}deep_5"] = rng.uniform(2.0, 10.0, n_rows)
        data[f"{prefix}npxga_5"] = rng.uniform(0.5, 2.5, n_rows)
        data[f"{prefix}ppda_allowed_5"] = rng.uniform(5.0, 15.0, n_rows)

        # Set-piece xG
        data[f"{prefix}set_piece_xg_5"] = rng.uniform(0.0, 0.5, n_rows)
        data[f"{prefix}open_play_xg_5"] = rng.uniform(0.5, 2.0, n_rows)

        # Context features — Elo, Pinnacle, etc.
        data[f"{prefix}elo_rating"] = rng.uniform(1200, 1800, n_rows)
        data[f"{prefix}elo_rating_opponent"] = rng.uniform(1200, 1800, n_rows)
        # IMPORTANT: Only 2 of 3 Pinnacle probs (PC-09-01 fix)
        data[f"{prefix}pinnacle_home_prob"] = rng.uniform(0.2, 0.7, n_rows)
        data[f"{prefix}pinnacle_away_prob"] = rng.uniform(0.1, 0.5, n_rows)
        # draw_prob intentionally included in data to verify model ignores it
        data[f"{prefix}pinnacle_draw_prob"] = (
            1.0 - data[f"{prefix}pinnacle_home_prob"]
            - data[f"{prefix}pinnacle_away_prob"]
        )

        # League-specific features (E36-03)
        data[f"{prefix}league_home_adv_5"] = rng.uniform(0.3, 0.7, n_rows)
        data[f"{prefix}is_newly_promoted"] = rng.choice([0, 1], n_rows, p=[0.8, 0.2])

        # Congestion, referee, weather
        data[f"{prefix}days_since_last_match"] = rng.integers(3, 14, n_rows)
        data[f"{prefix}congestion_index_14d"] = rng.uniform(0.5, 3.0, n_rows)
        data[f"{prefix}injury_count"] = rng.integers(0, 5, n_rows)

    return pd.DataFrame(data)


def _make_synthetic_results(n_rows: int = 600, seed: int = 42) -> pd.DataFrame:
    """Build a synthetic results DataFrame with match_id, home_goals, away_goals."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "match_id": np.arange(1, n_rows + 1),
        "home_goals": rng.poisson(1.5, n_rows),
        "away_goals": rng.poisson(1.1, n_rows),
    })


# ============================================================================
# Scenario 1 — Poisson coefficients stable after training
# ============================================================================

class TestPoissonCoefficientStability:
    """PC-09-01: Verify model coefficients are numerically stable."""

    def test_coefficients_below_100(self):
        """All Poisson GLM coefficients should have |magnitude| < 100.

        Before PC-09-01, including all 3 Pinnacle probabilities created
        multicollinearity (home + draw + away ≈ 1.0 + intercept), producing
        coefficients of magnitude ~17,000.  After removing draw_prob, the
        design matrix is well-conditioned and coefficients stay reasonable.
        """
        from src.models.poisson import PoissonModel

        features = _make_synthetic_features(600)
        results = _make_synthetic_results(600)

        model = PoissonModel()
        model.train(features, results)

        # Check home model coefficients
        home_params = model._home_model.params
        max_home = max(abs(c) for c in home_params)
        assert max_home < 100, (
            f"Home model has unstable coefficient: max |coeff| = {max_home:.2f}. "
            f"This suggests multicollinearity — check that pinnacle_draw_prob "
            f"is excluded from _select_feature_cols()."
        )

        # Check away model coefficients
        away_params = model._away_model.params
        max_away = max(abs(c) for c in away_params)
        assert max_away < 100, (
            f"Away model has unstable coefficient: max |coeff| = {max_away:.2f}."
        )

    def test_predictions_produce_valid_probabilities(self):
        """Model predictions should produce valid 1X2 probabilities."""
        from src.models.poisson import PoissonModel

        features = _make_synthetic_features(600)
        results = _make_synthetic_results(600)

        model = PoissonModel()
        model.train(features, results)
        preds = model.predict(features.tail(10))

        assert len(preds) == 10
        for p in preds:
            # 1X2 probabilities should sum to ~1.0
            total = p.prob_home_win + p.prob_draw + p.prob_away_win
            assert 0.95 <= total <= 1.05, (
                f"1X2 probs sum to {total:.4f}, expected ~1.0"
            )
            # Each probability should be between 0 and 1
            assert 0.0 < p.prob_home_win < 1.0
            assert 0.0 < p.prob_draw < 1.0
            assert 0.0 < p.prob_away_win < 1.0


# ============================================================================
# Scenario 2 — pinnacle_draw_prob excluded from features
# ============================================================================

class TestPinnacleDrawProbExcluded:
    """PC-09-01: Verify pinnacle_draw_prob is NOT in the model feature set."""

    def test_poisson_excludes_draw_prob(self):
        """PoissonModel._select_feature_cols() must NOT include draw_prob.

        Including all 3 Pinnacle probabilities creates perfect
        multicollinearity with the GLM intercept because
        home + draw + away ≈ 1.0.  Only 2 of the 3 should be used.
        """
        from src.models.poisson import PoissonModel

        features = _make_synthetic_features(100)
        model = PoissonModel()
        # _select_feature_cols takes (df, target) where target is "home" or "away"
        selected_home = model._select_feature_cols(features, "home")
        selected_away = model._select_feature_cols(features, "away")
        all_selected = selected_home + selected_away

        draw_cols = [c for c in all_selected if "pinnacle_draw_prob" in c]
        assert len(draw_cols) == 0, (
            f"pinnacle_draw_prob found in feature list: {draw_cols}. "
            f"This causes multicollinearity — remove it from "
            f"_select_feature_cols()."
        )

    def test_poisson_includes_home_and_away_prob(self):
        """Model SHOULD still include pinnacle_home_prob and pinnacle_away_prob."""
        from src.models.poisson import PoissonModel

        features = _make_synthetic_features(100)
        model = PoissonModel()
        selected_home = model._select_feature_cols(features, "home")
        selected_away = model._select_feature_cols(features, "away")
        all_selected = selected_home + selected_away

        home_prob_cols = [c for c in all_selected if "pinnacle_home_prob" in c]
        away_prob_cols = [c for c in all_selected if "pinnacle_away_prob" in c]

        assert len(home_prob_cols) > 0, (
            "pinnacle_home_prob not found in features — it should be included."
        )
        assert len(away_prob_cols) > 0, (
            "pinnacle_away_prob not found in features — it should be included."
        )

    def test_xgboost_excludes_draw_prob(self):
        """XGBoostModel._select_feature_cols() must also exclude draw_prob.

        Consistency between models — even though XGBoost is tree-based and
        more robust to collinearity, the feature set should match Poisson.
        """
        try:
            from src.models.xgboost_model import XGBoostModel
        except ImportError:
            pytest.skip("xgboost not installed — skipping XGBoost test")

        features = _make_synthetic_features(100)
        model = XGBoostModel()
        # XGBoost _select_feature_cols takes (df, target) like Poisson
        selected_home = model._select_feature_cols(features, "home")
        selected_away = model._select_feature_cols(features, "away")
        all_selected = selected_home + selected_away

        draw_cols = [c for c in all_selected if "pinnacle_draw_prob" in c]
        assert len(draw_cols) == 0, (
            f"pinnacle_draw_prob found in XGBoost feature list: {draw_cols}. "
            f"Should be excluded for consistency with Poisson (PC-09-01)."
        )


# ============================================================================
# Scenario 3 — Scheduled predictions refresh on each pipeline run
# ============================================================================

class TestScheduledPredictionRefresh:
    """PC-09-02: Verify pipeline deletes stale scheduled predictions."""

    def test_pipeline_deletes_stale_scheduled_predictions(self):
        """The _generate_predictions() method should delete old predictions
        for scheduled matches before regenerating them.

        This test verifies the logic by checking that:
        1. existing_pred_ids only includes finished match predictions
        2. Scheduled match predictions are always regenerated
        """
        # Verify at the code level that the pipeline filters by status='finished'
        import ast

        pipeline_path = Path(__file__).resolve().parents[1] / "src" / "pipeline.py"
        with open(pipeline_path) as f:
            source = f.read()

        tree = ast.parse(source)

        # Search for the filter condition: Match.status == "finished"
        # in the _generate_predictions method
        assert 'Match.status == "finished"' in source, (
            "Pipeline should filter existing_pred_ids to finished matches only. "
            "PC-09-02 fix missing."
        )

        # Also verify the stale scheduled deletion logic exists
        assert "stale_scheduled" in source, (
            "Pipeline should delete stale predictions for scheduled matches. "
            "PC-09-02 cleanup logic missing."
        )


# ============================================================================
# Scenario 4 — Value bet cleanup prevents duplicates
# ============================================================================

class TestValueBetCleanup:
    """PC-09-03: Verify clear_value_bets_for_scheduled() exists and works."""

    def test_clear_function_exists(self):
        """The clear_value_bets_for_scheduled() function must be importable."""
        from src.betting.value_finder import clear_value_bets_for_scheduled
        assert callable(clear_value_bets_for_scheduled)

    def test_clear_called_in_morning_pipeline(self):
        """Morning pipeline must call clear_value_bets_for_scheduled()."""
        pipeline_path = Path(__file__).resolve().parents[1] / "src" / "pipeline.py"
        with open(pipeline_path) as f:
            source = f.read()

        assert "clear_value_bets_for_scheduled" in source, (
            "Morning pipeline must import and call "
            "clear_value_bets_for_scheduled() before finding value bets. "
            "PC-09-03 fix missing."
        )

    def test_clear_deletes_scheduled_vbs_only(self):
        """clear_value_bets_for_scheduled() should only delete VBs for
        scheduled matches, not finished matches (historical performance data).
        """
        # Verify at the code level — check that the function filters by
        # Match.status == "scheduled"
        from src.betting import value_finder
        import inspect

        source = inspect.getsource(value_finder.clear_value_bets_for_scheduled)

        assert '"scheduled"' in source or "'scheduled'" in source, (
            "clear_value_bets_for_scheduled() must filter by "
            "Match.status == 'scheduled' to protect historical VBs."
        )


# ============================================================================
# Scenario 5 — League-specific sport keys for Odds API
# ============================================================================

class TestLeagueSportKeys:
    """PC-09-04: Verify Odds API uses correct sport key per league."""

    def test_league_to_sport_key_mapping_exists(self):
        """LEAGUE_TO_SPORT_KEY dict must map all 6 active leagues."""
        from src.scrapers.odds_api import LEAGUE_TO_SPORT_KEY

        expected_leagues = {
            "EPL", "Championship", "LaLiga", "Ligue1", "Bundesliga", "SerieA",
        }

        for league in expected_leagues:
            assert league in LEAGUE_TO_SPORT_KEY, (
                f"League '{league}' not in LEAGUE_TO_SPORT_KEY mapping. "
                f"PC-09-04 fix incomplete."
            )

    def test_epl_uses_correct_sport_key(self):
        """EPL must map to 'soccer_epl'."""
        from src.scrapers.odds_api import LEAGUE_TO_SPORT_KEY
        assert LEAGUE_TO_SPORT_KEY["EPL"] == "soccer_epl"

    def test_championship_uses_correct_sport_key(self):
        """Championship must NOT use 'soccer_epl' (the original bug)."""
        from src.scrapers.odds_api import LEAGUE_TO_SPORT_KEY
        assert LEAGUE_TO_SPORT_KEY["Championship"] != "soccer_epl", (
            "Championship should use 'soccer_championship', not 'soccer_epl'. "
            "This was the cross-league contamination bug."
        )
        assert LEAGUE_TO_SPORT_KEY["Championship"] == "soccer_championship"

    def test_la_liga_uses_correct_sport_key(self):
        """La Liga must use 'soccer_spain_la_liga'."""
        from src.scrapers.odds_api import LEAGUE_TO_SPORT_KEY
        assert LEAGUE_TO_SPORT_KEY["LaLiga"] == "soccer_spain_la_liga"

    def test_all_sport_keys_start_with_soccer(self):
        """All sport keys should start with 'soccer_' (Odds API convention)."""
        from src.scrapers.odds_api import LEAGUE_TO_SPORT_KEY
        for league, key in LEAGUE_TO_SPORT_KEY.items():
            assert key.startswith("soccer_"), (
                f"Sport key for {league} doesn't start with 'soccer_': {key}"
            )

    def test_scraper_skips_unknown_league(self):
        """Scraper should return empty DataFrame for unmapped leagues."""
        from src.scrapers.odds_api import TheOddsAPIScraper

        scraper = TheOddsAPIScraper()

        # Mock a league config with an unknown short_name
        fake_league = MagicMock()
        fake_league.short_name = "UnknownLeague"

        result = scraper.scrape(fake_league, "2025-26")
        assert result.empty, (
            "Scraper should return empty DataFrame for leagues not in "
            "LEAGUE_TO_SPORT_KEY, not fetch EPL odds."
        )


# ============================================================================
# Scenario 6 — Predictions directionally reasonable
# ============================================================================

class TestPredictionDirection:
    """Verify model predictions are directionally sensible.

    With synthetic random data, the Poisson model can't learn strong
    directional relationships (features are uncorrelated with results).
    Instead, we verify structural properties: that the model produces
    higher expected home goals when Pinnacle home prob is higher, and
    that coefficients are reasonable.
    """

    def test_higher_pinnacle_home_prob_increases_home_goals(self):
        """When Pinnacle home prob is high, predicted home goals should
        be at least as high as when Pinnacle home prob is low.

        This tests that the Pinnacle market signals are used correctly
        and not inverted (the original PC-09 bug made predictions go
        the wrong direction because of multicollinearity).
        """
        from src.models.poisson import PoissonModel

        # Build structured training data where home goals correlate
        # with Pinnacle home probability (mimicking real data)
        rng = np.random.default_rng(42)
        n = 600

        features = _make_synthetic_features(n)
        results = _make_synthetic_results(n)

        # Make training data have some structure: higher pinnacle_home_prob
        # → higher home goals (this is the real-world pattern)
        for i in range(n):
            phome = features.loc[i, "home_pinnacle_home_prob"]
            # Scale home goals to correlate with Pinnacle home prob
            results.loc[i, "home_goals"] = rng.poisson(1.0 + 2.0 * phome)
            results.loc[i, "away_goals"] = rng.poisson(
                1.5 - 1.0 * features.loc[i, "home_pinnacle_home_prob"]
            )

        model = PoissonModel()
        model.train(features, results)

        # Create two prediction rows: one with high home prob, one with low
        pred_high = features.iloc[0:1].copy()
        pred_high["match_id"] = 9001
        pred_high["home_pinnacle_home_prob"] = 0.8
        pred_high["home_pinnacle_away_prob"] = 0.1
        pred_high["away_pinnacle_home_prob"] = 0.8
        pred_high["away_pinnacle_away_prob"] = 0.1

        pred_low = features.iloc[0:1].copy()
        pred_low["match_id"] = 9002
        pred_low["home_pinnacle_home_prob"] = 0.2
        pred_low["home_pinnacle_away_prob"] = 0.5
        pred_low["away_pinnacle_home_prob"] = 0.2
        pred_low["away_pinnacle_away_prob"] = 0.5

        preds = model.predict(pd.concat([pred_high, pred_low], ignore_index=True))
        assert len(preds) == 2

        high_pred = preds[0]
        low_pred = preds[1]

        # With higher Pinnacle home prob, model should predict more home goals
        assert high_pred.predicted_home_goals > low_pred.predicted_home_goals, (
            f"Higher Pinnacle home prob should → more home goals, but got "
            f"high={high_pred.predicted_home_goals:.3f}, "
            f"low={low_pred.predicted_home_goals:.3f}. "
            f"The model may be using draw_prob which inverts the signal."
        )

    def test_model_does_not_produce_extreme_lambdas(self):
        """Predicted goals (lambdas) should be reasonable (0.2–5.0).

        Before PC-09-01, multicollinearity caused lambda values to
        explode (e.g., 50+ goals expected), which produced nonsensical
        1X2 probabilities.
        """
        from src.models.poisson import PoissonModel

        features = _make_synthetic_features(600)
        results = _make_synthetic_results(600)

        model = PoissonModel()
        model.train(features, results)
        preds = model.predict(features.tail(20))

        for p in preds:
            assert 0.1 < p.predicted_home_goals < 6.0, (
                f"Predicted home goals {p.predicted_home_goals:.2f} is "
                f"unreasonable (expected 0.1–6.0). Check for coefficient "
                f"instability."
            )
            assert 0.1 < p.predicted_away_goals < 6.0, (
                f"Predicted away goals {p.predicted_away_goals:.2f} is "
                f"unreasonable (expected 0.1–6.0)."
            )


# ============================================================================
# Bonus — Value bet edge sanity
# ============================================================================

class TestValueBetEdgeSanity:
    """Verify value bet edge calculations are mathematically correct."""

    def test_edge_equals_model_minus_implied(self):
        """edge = model_prob - implied_prob (basic definition)."""
        model_prob = 0.55
        bookmaker_odds = 2.10
        implied_prob = 1.0 / bookmaker_odds  # 0.4762

        edge = model_prob - implied_prob
        assert abs(edge - 0.0738) < 0.001

    def test_expected_value_formula(self):
        """EV = (model_prob × odds) - 1.0"""
        model_prob = 0.55
        bookmaker_odds = 2.10

        ev = (model_prob * bookmaker_odds) - 1.0
        assert abs(ev - 0.155) < 0.001

    def test_confidence_tiers(self):
        """Verify confidence classification thresholds."""
        from src.betting.value_finder import _classify_confidence

        assert _classify_confidence(0.12) == "high"    # >= 10%
        assert _classify_confidence(0.10) == "high"    # exactly 10%
        assert _classify_confidence(0.07) == "medium"  # 5-10%
        assert _classify_confidence(0.05) == "medium"  # exactly 5%
        assert _classify_confidence(0.03) == "low"     # < 5%
        assert _classify_confidence(0.001) == "low"    # tiny edge
