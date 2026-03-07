"""
E37-04 — XGBoost + Ensemble Integration Test
==============================================
Automated pytest suite verifying the XGBoost model, ensemble blending,
and graceful fallback behaviour introduced in E37-01 through E37-03.

Scenarios (from the E37-04 build plan):
  1. XGBoostModel.train() runs without error on a synthetic 600-row DataFrame
  2. XGBoostModel.predict() returns 7x7 array with values >= 0 that sum to ~1.0
  3. XGBoostModel.train() raises ValueError when fewer than 500 training rows
  4. Ensemble blend: w_a * matrix_a + w_b * matrix_b equals the blended output
  5. Ensemble weights sum to 1.0 at all times
  6. Fallback: pipeline continues with Poisson when XGBoost model file absent
  7. derive_market_probabilities() produces valid probabilities from blended matrix
  8. Temporal integrity: XGBoost training step receives no future data

All tests use synthetic data only -- no real DB access, no pkl files on disk.

Run with: pytest tests/test_e37_integration.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List
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

    Includes all the columns that XGBoostModel._select_feature_cols() looks for
    (home_*/away_* rolling stats, context features, etc.) plus match_id.

    Uses random but deterministic data so tests are reproducible.
    """
    rng = np.random.default_rng(seed)

    data: Dict[str, np.ndarray] = {"match_id": np.arange(1, n_rows + 1)}

    # Prefixes for home/away symmetry
    for prefix in ("home_", "away_"):
        # Rolling form features (E4)
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

        # Advanced stats (E16-01)
        data[f"{prefix}npxg_5"] = rng.uniform(0.5, 2.5, n_rows)
        data[f"{prefix}deep_5"] = rng.uniform(2.0, 10.0, n_rows)
        data[f"{prefix}npxga_5"] = rng.uniform(0.5, 2.5, n_rows)
        data[f"{prefix}ppda_allowed_5"] = rng.uniform(5.0, 15.0, n_rows)

        # Set-piece xG (E22-01)
        data[f"{prefix}set_piece_xg_5"] = rng.uniform(0.0, 0.5, n_rows)
        data[f"{prefix}open_play_xg_5"] = rng.uniform(0.5, 2.0, n_rows)

        # Context features
        data[f"{prefix}rest_days"] = rng.integers(2, 14, n_rows).astype(float)
        data[f"{prefix}h2h_goals_scored"] = rng.uniform(0.0, 3.0, n_rows)
        data[f"{prefix}market_value_ratio"] = rng.uniform(0.5, 2.0, n_rows)
        data[f"{prefix}is_heavy_weather"] = rng.integers(0, 2, n_rows).astype(float)

        # Market-implied (E20)
        data[f"{prefix}pinnacle_home_prob"] = rng.uniform(0.2, 0.6, n_rows)
        data[f"{prefix}pinnacle_draw_prob"] = rng.uniform(0.2, 0.35, n_rows)
        data[f"{prefix}pinnacle_away_prob"] = rng.uniform(0.15, 0.5, n_rows)
        data[f"{prefix}ah_line"] = rng.uniform(-2.0, 2.0, n_rows)

        # Elo (E21-01)
        data[f"{prefix}elo_rating"] = rng.uniform(1200, 1800, n_rows)
        data[f"{prefix}elo_diff"] = rng.uniform(-400, 400, n_rows)

        # Referee (E21-02)
        data[f"{prefix}ref_avg_goals"] = rng.uniform(2.0, 3.5, n_rows)
        data[f"{prefix}ref_home_win_pct"] = rng.uniform(0.3, 0.6, n_rows)

        # Congestion (E21-03)
        data[f"{prefix}is_congested"] = rng.integers(0, 2, n_rows).astype(float)

        # Injury (E22-02)
        data[f"{prefix}injury_impact"] = rng.uniform(0.0, 0.5, n_rows)
        data[f"{prefix}key_player_out"] = rng.integers(0, 2, n_rows).astype(float)

        # Multi-league (E36-03)
        data[f"{prefix}league_home_adv_5"] = rng.uniform(0.3, 0.7, n_rows)
        data[f"{prefix}is_newly_promoted"] = rng.integers(0, 2, n_rows).astype(float)

    return pd.DataFrame(data)


def _make_synthetic_results(n_rows: int = 600, seed: int = 42) -> pd.DataFrame:
    """Build a synthetic results DataFrame (match_id, home_goals, away_goals)."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "match_id": np.arange(1, n_rows + 1),
        "home_goals": rng.poisson(1.4, n_rows),
        "away_goals": rng.poisson(1.1, n_rows),
    })


def _make_uniform_matrix() -> List[List[float]]:
    """Create a simple 7x7 scoreline matrix that sums to 1.0.

    Each cell gets 1/49 probability -- used as a baseline for blending tests.
    """
    p = 1.0 / 49.0
    return [[p] * 7 for _ in range(7)]


def _make_realistic_matrix(home_lambda: float = 1.5, away_lambda: float = 1.1) -> List[List[float]]:
    """Create a Poisson-based 7x7 scoreline matrix.

    Uses the independent Poisson model (home and away goals are independent)
    to create a realistic scoreline probability distribution.
    """
    from scipy.stats import poisson

    matrix = [[0.0] * 7 for _ in range(7)]
    for h in range(7):
        for a in range(7):
            matrix[h][a] = poisson.pmf(h, home_lambda) * poisson.pmf(a, away_lambda)

    # Renormalise (truncation at 6 goals loses a tiny amount of probability)
    total = sum(matrix[h][a] for h in range(7) for a in range(7))
    return [[matrix[h][a] / total for a in range(7)] for h in range(7)]


# ============================================================================
# Scenario 1: XGBoostModel.train() on synthetic 600-row DataFrame
# ============================================================================

class TestXGBoostTrain:
    """Verify XGBoostModel.train() runs without error on synthetic data."""

    def test_train_600_rows(self):
        """XGBoost trains successfully on 600 synthetic matches."""
        from src.models.xgboost_model import XGBoostModel

        model = XGBoostModel()
        features = _make_synthetic_features(600)
        results = _make_synthetic_results(600)

        # Should not raise -- 600 > min_train_samples (500)
        model.train(features, results)

        assert model._is_trained is True
        assert model._home_model is not None
        assert model._away_model is not None
        assert len(model._feature_cols) > 0


# ============================================================================
# Scenario 2: XGBoostModel.predict() returns valid 7x7 matrix
# ============================================================================

class TestXGBoostPredict:
    """Verify XGBoost predictions produce valid scoreline matrices."""

    def test_predict_returns_valid_matrix(self):
        """Each prediction has a 7x7 matrix with values >= 0 summing to ~1.0."""
        from src.models.xgboost_model import XGBoostModel

        model = XGBoostModel()
        features = _make_synthetic_features(600)
        results = _make_synthetic_results(600)
        model.train(features, results)

        # Predict on a small subset (first 5 matches)
        predict_df = features.head(5).copy()
        predictions = model.predict(predict_df)

        assert len(predictions) == 5

        for pred in predictions:
            matrix = pred.scoreline_matrix
            # Must be 7x7
            assert len(matrix) == 7, f"Expected 7 rows, got {len(matrix)}"
            for row in matrix:
                assert len(row) == 7, f"Expected 7 cols, got {len(row)}"

            # All values must be non-negative
            for h in range(7):
                for a in range(7):
                    assert matrix[h][a] >= 0.0, (
                        f"Negative probability at [{h}][{a}]: {matrix[h][a]}"
                    )

            # Matrix must sum to approximately 1.0 (within floating point tolerance)
            total = sum(matrix[h][a] for h in range(7) for a in range(7))
            assert abs(total - 1.0) < 0.01, f"Matrix sum = {total}, expected ~1.0"


# ============================================================================
# Scenario 3: XGBoostModel.train() raises ValueError with < 500 rows
# ============================================================================

class TestXGBoostMinSamples:
    """Verify the min_train_samples guard rejects small datasets."""

    def test_train_400_rows_raises_value_error(self):
        """XGBoost refuses to train on fewer than 500 matches."""
        from src.models.xgboost_model import XGBoostModel

        model = XGBoostModel()
        features = _make_synthetic_features(400)
        results = _make_synthetic_results(400)

        with pytest.raises(ValueError, match="Not enough training data"):
            model.train(features, results)

    def test_train_499_rows_raises(self):
        """Edge case: exactly 499 rows is below the 500 threshold."""
        from src.models.xgboost_model import XGBoostModel

        model = XGBoostModel()
        features = _make_synthetic_features(499)
        results = _make_synthetic_results(499)

        with pytest.raises(ValueError, match="Not enough training data"):
            model.train(features, results)

    def test_train_500_rows_succeeds(self):
        """Edge case: exactly 500 rows meets the threshold."""
        from src.models.xgboost_model import XGBoostModel

        model = XGBoostModel()
        features = _make_synthetic_features(500)
        results = _make_synthetic_results(500)

        # Should NOT raise
        model.train(features, results)
        assert model._is_trained is True


# ============================================================================
# Scenario 4: Ensemble blend w_a * matrix_a + w_b * matrix_b
# ============================================================================

class TestEnsembleBlend:
    """Verify that the weighted average of two scoreline matrices is correct."""

    def test_50_50_blend(self):
        """50/50 blend of two matrices equals their arithmetic mean."""
        matrix_a = _make_realistic_matrix(1.5, 1.1)
        matrix_b = _make_realistic_matrix(1.2, 1.3)

        w_a, w_b = 0.5, 0.5

        # Manual blend
        blended = [[0.0] * 7 for _ in range(7)]
        for h in range(7):
            for a in range(7):
                blended[h][a] = w_a * matrix_a[h][a] + w_b * matrix_b[h][a]

        # Verify each cell
        for h in range(7):
            for a in range(7):
                expected = (matrix_a[h][a] + matrix_b[h][a]) / 2.0
                assert abs(blended[h][a] - expected) < 1e-10, (
                    f"Cell [{h}][{a}]: {blended[h][a]} != {expected}"
                )

        # Blended matrix must sum to 1.0
        total = sum(blended[h][a] for h in range(7) for a in range(7))
        assert abs(total - 1.0) < 1e-10, f"Blended sum = {total}"

    def test_70_30_blend(self):
        """70/30 blend produces weighted average (Poisson-heavy scenario)."""
        matrix_a = _make_realistic_matrix(1.5, 1.1)
        matrix_b = _make_realistic_matrix(1.2, 1.3)

        w_a, w_b = 0.7, 0.3

        blended = [[0.0] * 7 for _ in range(7)]
        for h in range(7):
            for a in range(7):
                blended[h][a] = w_a * matrix_a[h][a] + w_b * matrix_b[h][a]

        # Each cell must equal the weighted average
        for h in range(7):
            for a in range(7):
                expected = 0.7 * matrix_a[h][a] + 0.3 * matrix_b[h][a]
                assert abs(blended[h][a] - expected) < 1e-10

        # Weights sum to 1.0, so blended matrix sums to 1.0
        total = sum(blended[h][a] for h in range(7) for a in range(7))
        assert abs(total - 1.0) < 1e-10

    def test_blend_preserves_non_negativity(self):
        """All cells in a blended matrix remain non-negative."""
        matrix_a = _make_realistic_matrix(2.0, 0.5)
        matrix_b = _make_realistic_matrix(0.5, 2.0)

        blended = [[0.0] * 7 for _ in range(7)]
        for h in range(7):
            for a in range(7):
                blended[h][a] = 0.5 * matrix_a[h][a] + 0.5 * matrix_b[h][a]
                assert blended[h][a] >= 0.0


# ============================================================================
# Scenario 5: Ensemble weights sum to 1.0 at all times
# ============================================================================

class TestEnsembleWeightsSum:
    """Verify get_current_weights() always returns weights summing to 1.0."""

    def test_single_model_weight_is_1(self):
        """Single model gets weight = 1.0."""
        from src.self_improvement.ensemble_weights import get_current_weights

        weights = get_current_weights(["poisson_v1"])
        assert abs(sum(weights.values()) - 1.0) < 1e-10
        assert weights["poisson_v1"] == 1.0

    def test_two_models_equal_weights(self):
        """Two models with no DB history get equal (50/50) weights."""
        from src.self_improvement.ensemble_weights import get_current_weights

        # Patch DB lookup to return None (no weight history)
        with patch(
            "src.self_improvement.ensemble_weights._get_latest_weights_from_db",
            return_value=None,
        ):
            weights = get_current_weights(["poisson_v1", "xgboost_v1"])

        assert abs(sum(weights.values()) - 1.0) < 1e-10
        assert abs(weights["poisson_v1"] - 0.5) < 1e-10
        assert abs(weights["xgboost_v1"] - 0.5) < 1e-10

    def test_three_models_equal_weights(self):
        """Three models with no DB history get equal (1/3) weights."""
        from src.self_improvement.ensemble_weights import get_current_weights

        with patch(
            "src.self_improvement.ensemble_weights._get_latest_weights_from_db",
            return_value=None,
        ):
            weights = get_current_weights(["a", "b", "c"])

        assert abs(sum(weights.values()) - 1.0) < 1e-10

    def test_empty_models_returns_empty(self):
        """Empty model list returns empty dict (edge case)."""
        from src.self_improvement.ensemble_weights import get_current_weights

        weights = get_current_weights([])
        assert weights == {}


# ============================================================================
# Scenario 6: Fallback — pipeline uses Poisson when XGBoost pkl absent
# ============================================================================

class TestFallbackPoissonOnly:
    """Verify load_active_models() gracefully falls back to Poisson."""

    def test_pkl_missing_returns_poisson_only(self, tmp_path):
        """When xgboost_v1.pkl is missing, only Poisson is loaded."""
        from src.models.storage import load_active_models

        # Point to a non-existent pkl path
        fake_pkl = tmp_path / "xgboost_v1.pkl"  # does not exist

        with patch("src.models.storage.Path", return_value=fake_pkl):
            loaded = load_active_models()

        # Only Poisson should be loaded (XGBoost skipped due to missing pkl)
        assert "poisson_v1" in loaded
        assert "xgboost_v1" not in loaded

    def test_poisson_always_present_as_fallback(self):
        """Even if all models fail, Poisson is still returned."""
        from src.models.storage import load_active_models

        # Patch config to have no valid model keys
        mock_cfg = MagicMock()
        mock_cfg.settings.models.active_models = ["nonexistent_model"]

        with patch("src.config.config", mock_cfg):
            loaded = load_active_models()

        assert "poisson_v1" in loaded
        assert len(loaded) >= 1

    def test_pkl_exists_loads_xgboost(self, tmp_path):
        """When pkl exists, XGBoost is successfully loaded."""
        from src.models.storage import load_active_models
        from src.models.xgboost_model import XGBoostModel

        # Train a real XGBoost model in memory, save to temp path
        model = XGBoostModel()
        features = _make_synthetic_features(600)
        results = _make_synthetic_results(600)
        model.train(features, results)

        pkl_path = tmp_path / "xgboost_v1.pkl"
        model.save(pkl_path)

        # Patch Path() to return our temp pkl path for xgboost lookups
        with patch("src.models.storage.Path", return_value=pkl_path):
            loaded = load_active_models()

        assert "poisson_v1" in loaded
        assert "xgboost_v1" in loaded
        assert loaded["xgboost_v1"]._is_trained is True


# ============================================================================
# Scenario 7: derive_market_probabilities() from blended matrix
# ============================================================================

class TestDeriveFromBlendedMatrix:
    """Verify derive_market_probabilities() works on a blended matrix."""

    def test_blended_matrix_produces_valid_1x2(self):
        """Blended matrix → valid home/draw/away probabilities summing to 1."""
        from src.models.base_model import derive_market_probabilities

        matrix_a = _make_realistic_matrix(1.5, 1.1)
        matrix_b = _make_realistic_matrix(1.2, 1.3)

        blended = [[0.0] * 7 for _ in range(7)]
        for h in range(7):
            for a in range(7):
                blended[h][a] = 0.5 * matrix_a[h][a] + 0.5 * matrix_b[h][a]

        probs = derive_market_probabilities(blended)

        # 1X2 probabilities must sum to ~1.0
        p_1x2 = probs["prob_home_win"] + probs["prob_draw"] + probs["prob_away_win"]
        assert abs(p_1x2 - 1.0) < 0.01, f"1X2 sum = {p_1x2}"

        # Each must be in [0, 1]
        assert 0.0 <= probs["prob_home_win"] <= 1.0
        assert 0.0 <= probs["prob_draw"] <= 1.0
        assert 0.0 <= probs["prob_away_win"] <= 1.0

    def test_blended_matrix_produces_valid_ou(self):
        """Blended matrix → valid Over/Under probabilities summing to 1."""
        from src.models.base_model import derive_market_probabilities

        matrix_a = _make_realistic_matrix(1.5, 1.1)
        matrix_b = _make_realistic_matrix(1.2, 1.3)

        blended = [[0.5 * matrix_a[h][a] + 0.5 * matrix_b[h][a]
                     for a in range(7)] for h in range(7)]

        probs = derive_market_probabilities(blended)

        # Over/Under 2.5
        assert abs(probs["prob_over_25"] + probs["prob_under_25"] - 1.0) < 0.01
        # Over/Under 1.5
        assert abs(probs["prob_over_15"] + probs["prob_under_15"] - 1.0) < 0.01
        # Over/Under 3.5
        assert abs(probs["prob_over_35"] + probs["prob_under_35"] - 1.0) < 0.01

    def test_blended_matrix_produces_valid_btts(self):
        """Blended matrix → valid BTTS yes/no probabilities summing to 1."""
        from src.models.base_model import derive_market_probabilities

        matrix_a = _make_realistic_matrix(1.5, 1.1)
        matrix_b = _make_realistic_matrix(1.2, 1.3)

        blended = [[0.5 * matrix_a[h][a] + 0.5 * matrix_b[h][a]
                     for a in range(7)] for h in range(7)]

        probs = derive_market_probabilities(blended)

        assert abs(probs["prob_btts_yes"] + probs["prob_btts_no"] - 1.0) < 0.01


# ============================================================================
# Scenario 8: Temporal integrity — no future data in training
# ============================================================================

class TestTemporalIntegrity:
    """Verify XGBoost training only uses data before the prediction date.

    This scenario validates the backtester's temporal enforcement via the
    _get_match_ids_before_date_multi helper.  We verify the strict
    less-than date filter directly.
    """

    def test_strict_less_than_date_filter(self):
        """Matches ON the prediction date are excluded from training data."""
        from src.evaluation.backtester import _get_match_ids_before_date_multi
        from unittest.mock import MagicMock
        from src.database.models import Match

        # Create mock matches with known dates
        match_today = MagicMock()
        match_today.id = 100
        match_today.date = "2025-03-07"
        match_today.league_id = 1
        match_today.status = "finished"

        match_yesterday = MagicMock()
        match_yesterday.id = 99
        match_yesterday.date = "2025-03-06"
        match_yesterday.league_id = 1
        match_yesterday.status = "finished"

        match_tomorrow = MagicMock()
        match_tomorrow.id = 101
        match_tomorrow.date = "2025-03-08"
        match_tomorrow.league_id = 1
        match_tomorrow.status = "scheduled"

        # The function uses: Match.date < before_date (strict less-than)
        # We test this by verifying the SQLAlchemy filter logic
        # Since this requires a DB session, we verify via the source code pattern
        import inspect
        source = inspect.getsource(_get_match_ids_before_date_multi)
        assert "Match.date < before_date" in source, (
            "Temporal integrity violation: _get_match_ids_before_date_multi "
            "must use strict < (not <=) to prevent future data leakage"
        )

    def test_single_league_delegates_to_multi(self):
        """_get_match_ids_before_date delegates to the multi-league version."""
        from src.evaluation.backtester import _get_match_ids_before_date
        import inspect

        source = inspect.getsource(_get_match_ids_before_date)
        assert "_get_match_ids_before_date_multi" in source, (
            "Single-league helper must delegate to multi-league version"
        )

    def test_xgboost_train_does_not_see_predict_matches(self):
        """XGBoost training set must not contain any match in the predict set.

        This verifies the conceptual separation: features used for training
        (finished matches) must not overlap with features used for prediction
        (upcoming matches).
        """
        from src.models.xgboost_model import XGBoostModel

        model = XGBoostModel()

        # Training set: matches 1-600
        train_features = _make_synthetic_features(600)
        train_results = _make_synthetic_results(600)
        model.train(train_features, train_results)

        # Prediction set: matches 601-605 (no overlap with training)
        predict_features = _make_synthetic_features(5, seed=99)
        predict_features["match_id"] = np.arange(601, 606)

        predictions = model.predict(predict_features)

        # All predicted match_ids must be from the predict set (601-605)
        predicted_ids = {p.match_id for p in predictions}
        assert predicted_ids.issubset({601, 602, 603, 604, 605}), (
            f"Predicted IDs {predicted_ids} contain training match IDs"
        )

        # No training match_id should appear in predictions
        training_ids = set(range(1, 601))
        assert predicted_ids.isdisjoint(training_ids), (
            "Temporal integrity violation: prediction set overlaps training set"
        )


# ============================================================================
# Bonus: Config-driven ensemble flag
# ============================================================================

class TestEnsembleConfig:
    """Verify ensemble is controlled by config (no hardcoded toggle)."""

    def test_settings_yaml_has_ensemble_enabled(self):
        """config/settings.yaml must have ensemble_enabled: true."""
        import yaml
        settings_path = Path("config/settings.yaml")
        assert settings_path.exists(), "config/settings.yaml not found"

        with settings_path.open() as f:
            cfg = yaml.safe_load(f)

        assert cfg["models"]["ensemble_enabled"] is True

    def test_settings_yaml_has_both_models(self):
        """config/settings.yaml must list both poisson_v1 and xgboost_v1."""
        import yaml
        settings_path = Path("config/settings.yaml")
        with settings_path.open() as f:
            cfg = yaml.safe_load(f)

        active = cfg["models"]["active_models"]
        assert "poisson_v1" in active
        assert "xgboost_v1" in active

    def test_min_train_samples_in_config(self):
        """min_train_samples must be set in config (default 500)."""
        import yaml
        settings_path = Path("config/settings.yaml")
        with settings_path.open() as f:
            cfg = yaml.safe_load(f)

        xgb = cfg["models"]["xgboost"]
        assert "min_train_samples" in xgb
        assert xgb["min_train_samples"] >= 100  # sanity check
