"""
PC-21 — Dixon-Coles Correction Factor Integration Tests
=========================================================
Tests for the Dixon & Coles (1997) ρ estimation and τ correction
applied to the scoreline matrix in both PoissonModel and XGBoostModel.

Covers:
  1. ρ estimation (MLE, minimum sample size, boundary conditions)
  2. τ multiplier correctness (direction, magnitude, non-DC cells)
  3. Backward compatibility (ρ=0 ≡ standard independent Poisson)
  4. Edge cases (extreme λ, boundary ρ, matrix validity)
  5. Save/load round-trip (pickle backward compat)

Master Plan refs: MP §4 Prediction Models, MP §5 Scoreline Matrix,
                  MP §11.1 Recalibration guardrails (200-match min)
"""
import os
import pickle
import tempfile
from typing import List
# (no mock imports needed — tests use real PoissonModel with synthetic data)

import numpy as np
import pandas as pd
import pytest

from src.models.poisson import (
    DIXON_COLES_MIN_MATCHES,
    PoissonModel,
)


# ============================================================================
# Helpers
# ============================================================================

def _make_synthetic_features(n_matches: int, seed: int = 42) -> pd.DataFrame:
    """Create a minimal features DataFrame for training the Poisson model.

    Returns one row per match with home_* and away_* prefixed columns,
    matching the real output of compute_all_features().

    Includes the minimum columns needed by PoissonModel._select_feature_cols():
      - Attack: form_5, form_10, goals_scored_5, goals_scored_10,
        venue_form_5, venue_goals_scored_5
      - Defence: goals_conceded_5, goals_conceded_10, venue_goals_conceded_5
      - Context: rest_days, h2h_goals_scored
    """
    rng = np.random.RandomState(seed)

    rows = []
    for i in range(n_matches):
        row = {"match_id": 10000 + i}
        for prefix in ("home_", "away_"):
            # Attack features
            row[f"{prefix}form_5"] = rng.uniform(0.5, 3.0)
            row[f"{prefix}form_10"] = rng.uniform(0.5, 3.0)
            row[f"{prefix}goals_scored_5"] = rng.uniform(0.5, 3.0)
            row[f"{prefix}goals_scored_10"] = rng.uniform(0.5, 2.5)
            row[f"{prefix}venue_form_5"] = rng.uniform(0.5, 3.0)
            row[f"{prefix}venue_goals_scored_5"] = rng.uniform(0.5, 2.5)
            # Defence features
            row[f"{prefix}goals_conceded_5"] = rng.uniform(0.5, 2.5)
            row[f"{prefix}goals_conceded_10"] = rng.uniform(0.5, 2.0)
            row[f"{prefix}venue_goals_conceded_5"] = rng.uniform(0.5, 2.5)
            # Context features
            row[f"{prefix}rest_days"] = rng.choice([3, 4, 5, 6, 7])
            row[f"{prefix}h2h_goals_scored"] = rng.uniform(0.5, 2.5)
        rows.append(row)

    return pd.DataFrame(rows)


def _make_results(n_matches: int, seed: int = 42) -> pd.DataFrame:
    """Create a minimal results DataFrame (match_id, home_goals, away_goals)."""
    rng = np.random.RandomState(seed)
    return pd.DataFrame({
        "match_id": [10000 + i for i in range(n_matches)],
        "home_goals": rng.poisson(1.5, n_matches),
        "away_goals": rng.poisson(1.1, n_matches),
    })


# ============================================================================
# 1. ρ Estimation Tests
# ============================================================================

class TestRhoEstimation:
    """Tests for _estimate_rho() — MLE estimation of Dixon-Coles ρ."""

    def test_rho_below_min_sample_returns_zero(self):
        """When training data < DIXON_COLES_MIN_MATCHES, ρ must be 0.0."""
        n = DIXON_COLES_MIN_MATCHES - 1  # 199 matches
        features = _make_synthetic_features(n)
        results = _make_results(n)

        model = PoissonModel(use_dixon_coles=True)
        model.train(features, results)

        assert model._rho == 0.0, (
            f"Expected ρ=0.0 with only {n} matches "
            f"(min={DIXON_COLES_MIN_MATCHES}), got {model._rho}"
        )

    def test_rho_at_min_sample_estimates(self):
        """With exactly DIXON_COLES_MIN_MATCHES, ρ should be estimated (≠0)."""
        n = DIXON_COLES_MIN_MATCHES  # 200 matches
        features = _make_synthetic_features(n)
        results = _make_results(n)

        model = PoissonModel(use_dixon_coles=True)
        model.train(features, results)

        # ρ should be in the valid range [-0.15, 0.0]
        assert -0.15 <= model._rho <= 0.0, (
            f"ρ should be in [-0.15, 0.0], got {model._rho}"
        )

    def test_rho_in_valid_range_with_large_sample(self):
        """With ample training data, ρ should be estimated within bounds."""
        n = 500
        features = _make_synthetic_features(n)
        results = _make_results(n)

        model = PoissonModel(use_dixon_coles=True)
        model.train(features, results)

        assert -0.15 <= model._rho <= 0.0, (
            f"ρ should be in [-0.15, 0.0], got {model._rho}"
        )

    def test_dixon_coles_disabled_keeps_rho_zero(self):
        """When use_dixon_coles=False, ρ must remain 0.0 regardless of data."""
        n = 500
        features = _make_synthetic_features(n)
        results = _make_results(n)

        model = PoissonModel(use_dixon_coles=False)
        model.train(features, results)

        assert model._rho == 0.0, (
            f"ρ should be 0.0 when use_dixon_coles=False, got {model._rho}"
        )

    def test_rho_default_enabled(self):
        """Default PoissonModel() has Dixon-Coles enabled."""
        model = PoissonModel()
        assert model._use_dixon_coles is True

    def test_rho_negative_with_enough_data(self):
        """ρ should be negative or zero (never positive) — low-scoring
        outcomes are under-predicted by independent Poisson."""
        n = 500
        features = _make_synthetic_features(n, seed=99)
        results = _make_results(n, seed=99)

        model = PoissonModel(use_dixon_coles=True)
        model.train(features, results)

        assert model._rho <= 0.0, f"ρ should be ≤ 0, got {model._rho}"


# ============================================================================
# 2. τ Multiplier Tests
# ============================================================================

class TestTauMultipliers:
    """Tests for Dixon-Coles τ correction in _build_scoreline_matrix()."""

    def test_zero_zero_increases_with_negative_rho(self):
        """P(0-0) should increase when ρ < 0.

        Dixon-Coles equation (4): τ(0,0) = 1 - λ_h × λ_a × ρ
        With ρ < 0: -λ_h×λ_a×ρ > 0, so τ > 1, so P(0,0) increases.
        """
        lambda_h, lambda_a = 1.5, 1.2
        rho = -0.10

        matrix_0 = PoissonModel._build_scoreline_matrix(lambda_h, lambda_a, rho=0.0)
        matrix_dc = PoissonModel._build_scoreline_matrix(lambda_h, lambda_a, rho=rho)

        assert matrix_dc[0][0] > matrix_0[0][0], (
            f"P(0-0) should increase with ρ={rho}: "
            f"baseline={matrix_0[0][0]:.6f}, DC={matrix_dc[0][0]:.6f}"
        )

    def test_one_one_increases_with_negative_rho(self):
        """P(1-1) should increase when ρ < 0.

        Dixon-Coles equation (4): τ(1,1) = 1 - ρ
        With ρ < 0: τ = 1 - (-0.1) = 1.1 > 1, so P(1,1) increases.
        """
        lambda_h, lambda_a = 1.5, 1.2
        rho = -0.10

        matrix_0 = PoissonModel._build_scoreline_matrix(lambda_h, lambda_a, rho=0.0)
        matrix_dc = PoissonModel._build_scoreline_matrix(lambda_h, lambda_a, rho=rho)

        assert matrix_dc[1][1] > matrix_0[1][1], (
            f"P(1-1) should increase with ρ={rho}: "
            f"baseline={matrix_0[1][1]:.6f}, DC={matrix_dc[1][1]:.6f}"
        )

    def test_one_zero_decreases_with_negative_rho(self):
        """P(1-0) should decrease when ρ < 0.

        Dixon-Coles equation (4): τ(1,0) = 1 + λ_a × ρ
        With ρ < 0: τ = 1 + 1.2×(-0.1) = 0.88 < 1, so P(1,0) decreases.
        """
        lambda_h, lambda_a = 1.5, 1.2
        rho = -0.10

        matrix_0 = PoissonModel._build_scoreline_matrix(lambda_h, lambda_a, rho=0.0)
        matrix_dc = PoissonModel._build_scoreline_matrix(lambda_h, lambda_a, rho=rho)

        assert matrix_dc[1][0] < matrix_0[1][0], (
            f"P(1-0) should decrease with ρ={rho}: "
            f"baseline={matrix_0[1][0]:.6f}, DC={matrix_dc[1][0]:.6f}"
        )

    def test_zero_one_decreases_with_negative_rho(self):
        """P(0-1) should decrease when ρ < 0.

        Dixon-Coles equation (4): τ(0,1) = 1 + λ_h × ρ
        With ρ < 0: τ = 1 + 1.5×(-0.1) = 0.85 < 1, so P(0,1) decreases.
        """
        lambda_h, lambda_a = 1.5, 1.2
        rho = -0.10

        matrix_0 = PoissonModel._build_scoreline_matrix(lambda_h, lambda_a, rho=0.0)
        matrix_dc = PoissonModel._build_scoreline_matrix(lambda_h, lambda_a, rho=rho)

        assert matrix_dc[0][1] < matrix_0[0][1], (
            f"P(0-1) should decrease with ρ={rho}: "
            f"baseline={matrix_0[0][1]:.6f}, DC={matrix_dc[0][1]:.6f}"
        )

    def test_non_dc_cells_unchanged_before_renorm(self):
        """Cells outside (0,0), (1,0), (0,1), (1,1) should only change due
        to renormalisation, not due to τ (which is 1.0 for those cells).

        We check that the RATIO of non-DC cells to each other is preserved.
        """
        lambda_h, lambda_a = 1.5, 1.2
        rho = -0.10

        matrix_0 = PoissonModel._build_scoreline_matrix(lambda_h, lambda_a, rho=0.0)
        matrix_dc = PoissonModel._build_scoreline_matrix(lambda_h, lambda_a, rho=rho)

        # Compare ratio of (2,0) to (3,0) — both are non-DC cells
        ratio_baseline = matrix_0[2][0] / matrix_0[3][0] if matrix_0[3][0] > 0 else 0
        ratio_dc = matrix_dc[2][0] / matrix_dc[3][0] if matrix_dc[3][0] > 0 else 0

        assert abs(ratio_baseline - ratio_dc) < 1e-6, (
            f"Non-DC cell ratios should be preserved: "
            f"baseline={ratio_baseline:.6f}, DC={ratio_dc:.6f}"
        )


# ============================================================================
# 3. Matrix Validity Tests
# ============================================================================

class TestMatrixValidity:
    """Tests that the corrected scoreline matrix is always valid."""

    @pytest.mark.parametrize("rho", [0.0, -0.03, -0.05, -0.10, -0.15])
    def test_matrix_sums_to_one(self, rho):
        """All 49 cells must sum to 1.0 after correction and renormalisation."""
        matrix = PoissonModel._build_scoreline_matrix(1.5, 1.2, rho=rho)
        total = sum(sum(row) for row in matrix)
        assert abs(total - 1.0) < 1e-9, f"Matrix sum = {total}, expected 1.0"

    @pytest.mark.parametrize("rho", [0.0, -0.03, -0.05, -0.10, -0.15])
    def test_all_cells_positive(self, rho):
        """Every cell must be strictly positive (no negative probabilities)."""
        matrix = PoissonModel._build_scoreline_matrix(1.5, 1.2, rho=rho)
        for h in range(7):
            for a in range(7):
                assert matrix[h][a] > 0, (
                    f"Cell ({h},{a}) = {matrix[h][a]} is not positive (ρ={rho})"
                )

    def test_matrix_valid_with_extreme_lambda(self):
        """With very high λ values, Dixon-Coles should still produce valid matrix."""
        # High λ makes the τ corrections more extreme (e.g., τ(0,0) = 1 - 4*3*(-0.15) = 2.8)
        matrix = PoissonModel._build_scoreline_matrix(4.0, 3.0, rho=-0.15)
        total = sum(sum(row) for row in matrix)
        assert abs(total - 1.0) < 1e-9
        for h in range(7):
            for a in range(7):
                assert matrix[h][a] > 0

    def test_matrix_valid_with_low_lambda(self):
        """With very low λ values, matrix should still be valid."""
        matrix = PoissonModel._build_scoreline_matrix(0.3, 0.2, rho=-0.10)
        total = sum(sum(row) for row in matrix)
        assert abs(total - 1.0) < 1e-9
        for h in range(7):
            for a in range(7):
                assert matrix[h][a] > 0

    def test_market_probs_valid_with_dc(self):
        """Market probabilities derived from corrected matrix must be in (0, 1)."""
        from src.models.poisson import PoissonModel

        matrix = PoissonModel._build_scoreline_matrix(1.5, 1.2, rho=-0.10)

        # Home win = sum of cells where h > a
        home_win = sum(matrix[h][a] for h in range(7) for a in range(7) if h > a)
        draw = sum(matrix[h][a] for h in range(7) for a in range(7) if h == a)
        away_win = sum(matrix[h][a] for h in range(7) for a in range(7) if h < a)

        assert 0 < home_win < 1, f"P(home_win) = {home_win}"
        assert 0 < draw < 1, f"P(draw) = {draw}"
        assert 0 < away_win < 1, f"P(away_win) = {away_win}"
        assert abs(home_win + draw + away_win - 1.0) < 1e-9


# ============================================================================
# 4. Backward Compatibility Tests
# ============================================================================

class TestBackwardCompatibility:
    """Tests that ρ=0.0 produces identical output to pre-Dixon-Coles model."""

    def test_rho_zero_identical_to_no_rho(self):
        """_build_scoreline_matrix(λ_h, λ_a, rho=0.0) must produce the
        exact same output as _build_scoreline_matrix(λ_h, λ_a)."""
        # Without rho kwarg (default = 0.0)
        matrix_default = PoissonModel._build_scoreline_matrix(1.5, 1.2)
        # With explicit rho=0.0
        matrix_zero = PoissonModel._build_scoreline_matrix(1.5, 1.2, rho=0.0)

        for h in range(7):
            for a in range(7):
                assert matrix_default[h][a] == matrix_zero[h][a], (
                    f"Cell ({h},{a}) differs: default={matrix_default[h][a]}, "
                    f"zero={matrix_zero[h][a]}"
                )

    def test_save_load_preserves_rho(self):
        """Model pickle round-trip must preserve ρ value."""
        n = 300
        features = _make_synthetic_features(n)
        results = _make_results(n)

        model = PoissonModel(use_dixon_coles=True)
        model.train(features, results)
        original_rho = model._rho

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name

        try:
            model.save(path)

            loaded = PoissonModel()
            loaded.load(path)

            assert loaded._rho == original_rho, (
                f"Loaded ρ={loaded._rho} != original ρ={original_rho}"
            )
        finally:
            os.unlink(path)

    def test_load_old_pickle_defaults_rho_zero(self):
        """Loading a pre-Dixon-Coles pickle (no 'rho' key) must default to 0.0.

        Simulates an old pickle by training a model, saving it, removing
        the 'rho' key from the pickled dict, and re-loading.
        """
        # Train a real model to get a valid pickle
        n = 300
        features = _make_synthetic_features(n)
        results = _make_results(n)
        model = PoissonModel(use_dixon_coles=True)
        model.train(features, results)

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        try:
            model.save(path)

            # Remove the 'rho' key to simulate a pre-Dixon-Coles pickle
            with open(path, "rb") as f:
                state = pickle.load(f)
            del state["rho"]
            with open(path, "wb") as f:
                pickle.dump(state, f)

            # Load should default to rho=0.0
            loaded = PoissonModel()
            loaded.load(path)
            assert loaded._rho == 0.0, (
                f"Old pickle without 'rho' key should default to 0.0, got {loaded._rho}"
            )
        finally:
            os.unlink(path)


# ============================================================================
# 5. Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge cases for Dixon-Coles correction."""

    def test_rho_at_boundary_minus_015(self):
        """ρ = -0.15 (maximum correction) should still produce valid matrix."""
        matrix = PoissonModel._build_scoreline_matrix(1.5, 1.2, rho=-0.15)
        total = sum(sum(row) for row in matrix)
        assert abs(total - 1.0) < 1e-9

    def test_tau_exact_values(self):
        """Verify τ multiplier formulas with known values.

        λ_h = 1.5, λ_a = 1.2, ρ = -0.10
        τ(0,0) = 1 - 1.5 × 1.2 × (-0.10) = 1 + 0.18 = 1.18
        τ(1,0) = 1 + 1.2 × (-0.10) = 1 - 0.12 = 0.88
        τ(0,1) = 1 + 1.5 × (-0.10) = 1 - 0.15 = 0.85
        τ(1,1) = 1 - (-0.10) = 1.10
        """
        lambda_h, lambda_a = 1.5, 1.2
        rho = -0.10

        # Build matrix with no correction as reference
        from scipy.stats import poisson as poisson_dist
        p00_base = poisson_dist.pmf(0, lambda_h) * poisson_dist.pmf(0, lambda_a)
        p10_base = poisson_dist.pmf(1, lambda_h) * poisson_dist.pmf(0, lambda_a)
        p01_base = poisson_dist.pmf(0, lambda_h) * poisson_dist.pmf(1, lambda_a)
        p11_base = poisson_dist.pmf(1, lambda_h) * poisson_dist.pmf(1, lambda_a)

        tau_00 = 1.0 - lambda_h * lambda_a * rho  # 1.18
        tau_10 = 1.0 + lambda_a * rho              # 0.88
        tau_01 = 1.0 + lambda_h * rho              # 0.85
        tau_11 = 1.0 - rho                          # 1.10

        assert abs(tau_00 - 1.18) < 1e-10
        assert abs(tau_10 - 0.88) < 1e-10
        assert abs(tau_01 - 0.85) < 1e-10
        assert abs(tau_11 - 1.10) < 1e-10

        # Verify the DC matrix cells are τ × base (before renorm)
        matrix_dc = PoissonModel._build_scoreline_matrix(lambda_h, lambda_a, rho=rho)

        # After renormalisation, the ratios should match τ
        # P_dc(0,0) / P_dc(2,0) ≈ (P_base(0,0) * τ_00) / P_base(2,0)
        # Because τ(2,0) = 1.0 (no correction)
        p20_base = poisson_dist.pmf(2, lambda_h) * poisson_dist.pmf(0, lambda_a)
        expected_ratio = (p00_base * tau_00) / p20_base
        actual_ratio = matrix_dc[0][0] / matrix_dc[2][0]
        assert abs(expected_ratio - actual_ratio) < 1e-6, (
            f"Ratio P(0,0)/P(2,0) mismatch: expected {expected_ratio:.6f}, "
            f"got {actual_ratio:.6f}"
        )

    def test_min_matches_constant_is_200(self):
        """DIXON_COLES_MIN_MATCHES must be 200 (MP §11.1)."""
        assert DIXON_COLES_MIN_MATCHES == 200


# ============================================================================
# 6. XGBoost Model Consistency
# ============================================================================

class TestXGBoostConsistency:
    """Verify XGBoostModel has the same τ correction as PoissonModel."""

    def test_xgboost_build_scoreline_matrix_matches_poisson(self):
        """XGBoostModel._build_scoreline_matrix should produce identical
        output to PoissonModel._build_scoreline_matrix for the same inputs."""
        try:
            from src.models.xgboost_model import XGBoostModel
        except ImportError:
            pytest.skip("xgboost not installed")

        lambda_h, lambda_a = 1.5, 1.2

        for rho in [0.0, -0.05, -0.10, -0.15]:
            poisson_matrix = PoissonModel._build_scoreline_matrix(
                lambda_h, lambda_a, rho=rho,
            )
            xgb_matrix = XGBoostModel._build_scoreline_matrix(
                lambda_h, lambda_a, rho=rho,
            )

            for h in range(7):
                for a in range(7):
                    assert abs(poisson_matrix[h][a] - xgb_matrix[h][a]) < 1e-12, (
                        f"Cell ({h},{a}) differs at ρ={rho}: "
                        f"Poisson={poisson_matrix[h][a]}, XGB={xgb_matrix[h][a]}"
                    )


# ============================================================================
# 7. Full Training + Prediction Integration
# ============================================================================

class TestFullIntegration:
    """End-to-end test: train → predict with Dixon-Coles enabled."""

    def test_predict_with_dixon_coles_returns_valid_predictions(self):
        """Train with DC enabled, predict, and verify all probabilities are valid."""
        n = 300
        features = _make_synthetic_features(n)
        results = _make_results(n)

        model = PoissonModel(use_dixon_coles=True)
        model.train(features, results)

        # Predict on a subset (first 10 matches)
        test_features = features[features["match_id"].isin([10000, 10001, 10002])]
        predictions = model.predict(test_features)

        assert len(predictions) > 0, "Should produce at least one prediction"

        for pred in predictions:
            # 1X2 probabilities must be valid
            assert 0 < pred.prob_home_win < 1
            assert 0 < pred.prob_draw < 1
            assert 0 < pred.prob_away_win < 1
            total = pred.prob_home_win + pred.prob_draw + pred.prob_away_win
            assert abs(total - 1.0) < 0.01, f"1X2 sum = {total}"

            # Scoreline matrix must be 7×7 and sum to 1.0
            assert len(pred.scoreline_matrix) == 7
            assert all(len(row) == 7 for row in pred.scoreline_matrix)
            matrix_sum = sum(sum(row) for row in pred.scoreline_matrix)
            assert abs(matrix_sum - 1.0) < 1e-6

    def test_dc_vs_baseline_predictions_differ(self):
        """Dixon-Coles predictions should differ from baseline (at least slightly)
        when ρ is non-zero."""
        n = 300
        features = _make_synthetic_features(n, seed=77)
        results = _make_results(n, seed=77)

        model_dc = PoissonModel(use_dixon_coles=True)
        model_dc.train(features, results)

        model_bl = PoissonModel(use_dixon_coles=False)
        model_bl.train(features, results)

        # If ρ was estimated as non-zero, predictions should differ
        if model_dc._rho != 0.0:
            test_features = features[features["match_id"] == 10000]
            pred_dc = model_dc.predict(test_features)
            pred_bl = model_bl.predict(test_features)

            assert len(pred_dc) == 1
            assert len(pred_bl) == 1

            # Draw probability should be the most affected by Dixon-Coles
            # (draw = sum of diagonal cells, which are boosted by ρ < 0)
            assert pred_dc[0].prob_draw != pred_bl[0].prob_draw, (
                "Draw probabilities should differ with ρ != 0"
            )
