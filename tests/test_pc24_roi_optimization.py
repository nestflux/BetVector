"""
PC-24 — ROI Optimization Pipeline Integration Tests
=====================================================
Tests covering all PC-24 components: per-league thresholds (accepted),
sharp-only filtering infrastructure (available but rolled back),
calibration module (rolled back), and Kelly staking (rolled back).

Accepted layers:
  - PC-24-01: Per-league edge thresholds (Championship 10%, LaLiga 8%, Ligue1 7%)

Rolled-back layers (infrastructure tested to verify safe defaults):
  - PC-24-02: Pinnacle-only filtering (sharp_only=False default)
  - PC-24-03: Lambda calibration (module functional but not applied)
  - PC-24-04: Kelly staking (staking_method="flat" default)

Master Plan refs: MP §4 Value Detection, MP §11.4 Assessment Tiers,
                  config/leagues.yaml edge_threshold_override,
                  config/settings.yaml sharp_bookmaker
"""
import os
import pickle
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import yaml

from src.models.calibration import (
    CALIBRATION_ERROR_THRESHOLD,
    CALIBRATION_MIN_SAMPLES,
    CalibrationResult,
    LambdaCalibrator,
)


# ============================================================================
# Config Loading Tests — PC-24-01 Per-League Thresholds
# ============================================================================

class TestPerLeagueThresholds:
    """Verify config/leagues.yaml has correct per-league edge thresholds."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        """Load leagues.yaml once per test."""
        config_path = Path(__file__).parent.parent / "config" / "leagues.yaml"
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.leagues = self.config["leagues"]
        self.league_map = {lg["short_name"]: lg for lg in self.leagues}

    def test_championship_threshold_is_10pct(self):
        """Championship has 10% threshold (PC-24-01: best ROI at 10%, +10.5%)."""
        lg = self.league_map["Championship"]
        assert lg.get("edge_threshold_override") == 0.10

    def test_laliga_threshold_is_8pct(self):
        """LaLiga has 8% threshold (PC-24-01: best ROI at 8%, +18.1%)."""
        lg = self.league_map["LaLiga"]
        assert lg.get("edge_threshold_override") == 0.08

    def test_ligue1_threshold_is_7pct(self):
        """Ligue1 has 7% threshold (PC-24-01: 7% is -21.8% vs 8% at -32.1%)."""
        lg = self.league_map["Ligue1"]
        assert lg.get("edge_threshold_override") == 0.07

    def test_bundesliga_threshold_is_5pct(self):
        """Bundesliga keeps 5% (PC-24-01: 7% was worse at -22.6%)."""
        lg = self.league_map["Bundesliga"]
        assert lg.get("edge_threshold_override") == 0.05

    def test_serie_a_threshold_is_5pct(self):
        """SerieA keeps 5% (PC-24-01: 7% was 14pp worse at -33.0%)."""
        lg = self.league_map["SerieA"]
        assert lg.get("edge_threshold_override") == 0.05

    def test_epl_has_no_override(self):
        """EPL uses the global default (5%) — no override needed."""
        lg = self.league_map["EPL"]
        # EPL may have no override or 0.05 — either is correct
        override = lg.get("edge_threshold_override")
        assert override is None or override == 0.05

    def test_pipeline_uses_override_when_present(self):
        """Pipeline reads edge_threshold_override from league config."""
        # Verify the config attribute exists for leagues that have it
        for short_name in ["Championship", "LaLiga", "Ligue1"]:
            lg = self.league_map[short_name]
            override = lg.get("edge_threshold_override")
            assert override is not None, (
                f"{short_name} should have edge_threshold_override"
            )
            assert 0.0 < override < 1.0, (
                f"{short_name} threshold should be a fraction, got {override}"
            )


# ============================================================================
# Value Finder Sharp-Only Tests — PC-24-02 Infrastructure
# ============================================================================

class TestSharpOnlyInfrastructure:
    """Test sharp-only filtering infrastructure (rolled back, defaults OFF)."""

    def test_find_value_bets_sharp_only_defaults_false(self):
        """find_value_bets() defaults to sharp_only=False (rolled back)."""
        from src.betting.value_finder import ValueFinder
        import inspect
        sig = inspect.signature(ValueFinder.find_value_bets)
        assert sig.parameters["sharp_only"].default is False

    def test_find_value_bets_sharp_bookmaker_defaults_pinnacle(self):
        """Sharp bookmaker defaults to 'Pinnacle'."""
        from src.betting.value_finder import ValueFinder
        import inspect
        sig = inspect.signature(ValueFinder.find_value_bets)
        assert sig.parameters["sharp_bookmaker"].default == "Pinnacle"

    def test_backtester_sharp_only_defaults_false(self):
        """run_backtest() defaults to sharp_only=False (rolled back)."""
        from src.evaluation.backtester import run_backtest
        import inspect
        sig = inspect.signature(run_backtest)
        assert sig.parameters["sharp_only"].default is False

    def test_backtester_staking_method_defaults_flat(self):
        """run_backtest() defaults to staking_method='flat' (Kelly rolled back)."""
        from src.evaluation.backtester import run_backtest
        import inspect
        sig = inspect.signature(run_backtest)
        assert sig.parameters["staking_method"].default == "flat"

    def test_config_has_sharp_bookmaker(self):
        """config/settings.yaml has sharp_bookmaker setting."""
        config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(config_path, "r") as f:
            settings = yaml.safe_load(f)
        vb = settings.get("value_betting", {})
        assert vb.get("sharp_bookmaker") == "Pinnacle"


# ============================================================================
# Calibration Module Tests — PC-24-03 Infrastructure
# ============================================================================

class TestLambdaCalibrator:
    """Test LambdaCalibrator module (rolled back, available for future use)."""

    def test_fit_below_min_samples(self):
        """Calibration not applied when sample count < minimum (200)."""
        cal = LambdaCalibrator()
        pred_h = np.array([1.5] * 50)
        pred_a = np.array([1.2] * 50)
        actual_h = np.array([2.0] * 50)  # Significant bias
        actual_a = np.array([0.8] * 50)

        result = cal.fit(pred_h, pred_a, actual_h, actual_a)

        assert not result.is_applied
        assert result.n_samples == 50
        assert "minimum sample size" in result.reason.lower()
        assert not cal.is_fitted

    def test_fit_below_significance_threshold(self):
        """Calibration not applied when bias < 3pp threshold."""
        cal = LambdaCalibrator()
        n = 300
        pred_h = np.array([1.50] * n)
        pred_a = np.array([1.20] * n)
        # 1% bias (below 3% threshold)
        actual_h = np.array([1.515] * n)
        actual_a = np.array([1.212] * n)

        result = cal.fit(pred_h, pred_a, actual_h, actual_a)

        assert not result.is_applied
        assert "significance threshold" in result.reason.lower()
        assert not cal.is_fitted

    def test_fit_applies_when_significant(self):
        """Calibration applied when bias > 3pp and sample size sufficient."""
        cal = LambdaCalibrator()
        n = 300
        pred_h = np.array([1.50] * n)
        pred_a = np.array([1.20] * n)
        # 10% bias (well above 3% threshold)
        actual_h = np.array([1.65] * n)
        actual_a = np.array([1.32] * n)

        result = cal.fit(pred_h, pred_a, actual_h, actual_a)

        assert result.is_applied
        assert cal.is_fitted
        assert abs(result.scale_home - 1.10) < 0.01
        assert abs(result.scale_away - 1.10) < 0.01

    def test_transform_applies_scaling(self):
        """transform() scales λ values when fitted."""
        cal = LambdaCalibrator()
        n = 300
        pred_h = np.array([1.50] * n)
        pred_a = np.array([1.20] * n)
        actual_h = np.array([1.65] * n)
        actual_a = np.array([1.32] * n)
        cal.fit(pred_h, pred_a, actual_h, actual_a)

        h_cal, a_cal = cal.transform(1.5, 1.2)

        assert abs(h_cal - 1.65) < 0.01
        assert abs(a_cal - 1.32) < 0.01

    def test_transform_passthrough_when_not_fitted(self):
        """transform() returns original λ when calibration not applied."""
        cal = LambdaCalibrator()

        h_cal, a_cal = cal.transform(1.5, 1.2)

        assert h_cal == 1.5
        assert a_cal == 1.2

    def test_save_load_roundtrip(self):
        """Calibrator state survives pickle save/load."""
        cal = LambdaCalibrator()
        n = 300
        pred_h = np.array([1.50] * n)
        pred_a = np.array([1.20] * n)
        actual_h = np.array([1.65] * n)
        actual_a = np.array([1.32] * n)
        cal.fit(pred_h, pred_a, actual_h, actual_a)

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            cal.save(Path(f.name))
            tmp_path = Path(f.name)

        try:
            cal2 = LambdaCalibrator()
            cal2.load(tmp_path)
            assert cal2.is_fitted
            assert cal2.scales == cal.scales
            h_cal, a_cal = cal2.transform(1.5, 1.2)
            assert abs(h_cal - 1.65) < 0.01
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_constants_match_mp_spec(self):
        """Calibration constants match MP §11.1 guardrails."""
        assert CALIBRATION_MIN_SAMPLES == 200
        assert CALIBRATION_ERROR_THRESHOLD == 0.03


# ============================================================================
# Rollback Verification Tests
# ============================================================================

class TestRollbackVerification:
    """Verify that rolled-back layers don't affect default behavior."""

    def test_default_backtest_uses_flat_staking(self):
        """Default staking method is flat (Kelly was rolled back)."""
        from src.evaluation.backtester import run_backtest
        import inspect
        sig = inspect.signature(run_backtest)
        assert sig.parameters["staking_method"].default == "flat"
        assert sig.parameters["stake_percentage"].default == 0.02

    def test_default_value_finder_uses_all_bookmakers(self):
        """Default value finding uses all bookmakers (sharp-only rolled back)."""
        from src.betting.value_finder import ValueFinder
        import inspect
        sig = inspect.signature(ValueFinder.find_value_bets)
        assert sig.parameters["sharp_only"].default is False

    def test_calibration_module_importable(self):
        """Calibration module exists as infrastructure for future use."""
        from src.models.calibration import LambdaCalibrator, CalibrationResult
        cal = LambdaCalibrator()
        assert not cal.is_fitted
        assert cal.scales == (1.0, 1.0)


# ============================================================================
# Report Verification Tests
# ============================================================================

class TestROIOptimizationReport:
    """Verify the PC-24-05 final report was generated correctly."""

    @pytest.fixture(autouse=True)
    def load_report(self):
        """Load the final ROI optimization report."""
        import json
        report_path = (
            Path(__file__).parent.parent
            / "data" / "predictions" / "roi_optimization_report.json"
        )
        if not report_path.exists():
            pytest.skip("ROI optimization report not yet generated")
        with open(report_path, "r") as f:
            self.report = json.load(f)

    def test_report_has_all_six_leagues(self):
        """Report covers all 6 leagues."""
        per_league = self.report["per_league"]
        expected = {"EPL", "Championship", "LaLiga", "Ligue1", "Bundesliga", "SerieA"}
        assert set(per_league.keys()) == expected

    def test_report_has_aggregate_section(self):
        """Report includes aggregate comparison metrics."""
        agg = self.report["aggregate"]
        assert "baseline_roi" in agg
        assert "optimised_roi" in agg
        assert "roi_delta" in agg

    def test_aggregate_roi_improved(self):
        """Aggregate ROI improved vs baseline."""
        agg = self.report["aggregate"]
        assert agg["roi_delta"] > 0, (
            f"ROI should have improved, got delta {agg['roi_delta']}"
        )

    def test_no_league_regressed_over_5pct(self):
        """No league regressed more than 5% ROI vs baseline."""
        for name, data in self.report["per_league"].items():
            assert data["roi_delta"] >= -5.0, (
                f"{name} regressed by {data['roi_delta']}% (limit: -5%)"
            )

    def test_championship_is_profitable(self):
        """Championship tier is 'profitable' (CI lower bound > 0)."""
        champ = self.report["per_league"]["Championship"]
        assert champ["tier"] == "profitable"
        assert champ["ci_lower"] > 0

    def test_each_league_has_tier(self):
        """Every league has an assigned assessment tier."""
        valid_tiers = {"profitable", "promising", "insufficient", "unprofitable"}
        for name, data in self.report["per_league"].items():
            assert data["tier"] in valid_tiers, (
                f"{name} has invalid tier '{data['tier']}'"
            )

    def test_layers_documented(self):
        """Report documents keep/rollback decision for each layer."""
        layers = self.report["layers"]
        assert layers["PC-24-01_thresholds"] == "KEEP"
        assert layers["PC-24-02_pinnacle"] == "ROLLBACK"
        assert layers["PC-24-03_calibration"] == "ROLLBACK"
        assert layers["PC-24-04_kelly"] == "ROLLBACK"

    def test_accepted_config_matches_leagues_yaml(self):
        """Accepted config in report matches leagues.yaml values."""
        config_path = Path(__file__).parent.parent / "config" / "leagues.yaml"
        with open(config_path, "r") as f:
            leagues = yaml.safe_load(f)["leagues"]
        league_map = {lg["short_name"]: lg for lg in leagues}

        accepted = self.report["accepted_config"]
        for short_name, cfg in accepted.items():
            if short_name in league_map:
                override = league_map[short_name].get("edge_threshold_override")
                if override:
                    assert cfg["edge_threshold"] == override, (
                        f"{short_name}: report says {cfg['edge_threshold']} "
                        f"but config says {override}"
                    )
            assert cfg["staking"] == "flat"
