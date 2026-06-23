"""Regression tests for WC model calibration (2026-06-23).

Two calibration changes are locked here:
1. The ad-hoc +0.03 group-stage "draw_boost" was removed — it over-predicted
   draws by ~4.5pp vs the de-vigged 59-book market and manufactured phantom
   h2h/draw value bets. Draw probability must now equal the scoreline-matrix
   diagonal with no group-stage inflation.
2. The value finder gained a config-driven edge ceiling (max_actionable_edge)
   so miscalibration can't produce huge phantom edges.
"""

import yaml
from pathlib import Path

from src.world_cup.predictor import WCPoissonPredictor

CONFIG = Path(__file__).resolve().parents[1] / "config" / "worldcup_2026.yaml"


class TestNoDrawBoost:
    def _matrix(self):
        # Representative low-scoring international fixture
        return WCPoissonPredictor._build_scoreline_matrix(1.4, 1.1, -0.06)

    def test_group_and_knockout_give_identical_draw(self):
        m = self._matrix()
        group = WCPoissonPredictor._derive_probabilities(m, is_group=True)
        knockout = WCPoissonPredictor._derive_probabilities(m, is_group=False)
        # No group-stage inflation: draw must be the same either way.
        assert abs(group["draw"] - knockout["draw"]) < 1e-9

    def test_draw_equals_matrix_diagonal(self):
        m = self._matrix()
        diagonal = sum(m[h][h] for h in range(len(m)))
        probs = WCPoissonPredictor._derive_probabilities(m, is_group=True)
        # The diagonal IS the draw mass. Tolerance 1e-3 absorbs the 4-decimal
        # rounding in the return value while still being far below the old 0.03
        # boost — so any reintroduced boost would fail this test loudly.
        assert abs(probs["draw"] - diagonal) < 1e-3

    def test_1x2_normalized(self):
        probs = WCPoissonPredictor._derive_probabilities(self._matrix(), is_group=True)
        assert abs(probs["home_win"] + probs["draw"] + probs["away_win"] - 1.0) < 1e-6


class TestEdgeCeilingConfig:
    def test_max_actionable_edge_present_and_sane(self):
        cfg = yaml.safe_load(CONFIG.read_text())
        ceiling = cfg["betting"].get("max_actionable_edge")
        assert ceiling is not None, "max_actionable_edge missing from WC betting config"
        # A ceiling must sit above the entry threshold and below an absurd edge.
        assert cfg["betting"]["edge_threshold"] < ceiling < 0.5
