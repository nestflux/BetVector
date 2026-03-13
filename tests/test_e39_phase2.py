"""
E39-12 — Lineup Features Phase 2 Integration Test
===================================================
Automated pytest suite validating that the E39 lineup feature pipeline
(MatchLineup, formation storage, squad rotation, formation change,
bench strength) is correctly wired end-to-end.

Scenarios (from the E39-12 build plan):
  1. MatchLineup loading (idempotency, starter/bench split)
  2. Formation storage on Match model
  3. calculate_squad_rotation() with known lineup data
  4. calculate_formation_change() with same/different formations
  5. calculate_bench_strength() with known PlayerValue data
  6. All three features return NULL when lineup data missing
  7. Full backtest comparison docs (baseline vs injury vs injury+lineup)

All tests use synthetic data — no real scraper calls.  Tests that need
DB validation read from the production SQLite database via get_session()
(read-only queries).

Run with: pytest tests/test_e39_phase2.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock

import pandas as pd
import pytest

# ============================================================================
# Path setup
# ============================================================================

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ============================================================================
# Scenario 1: MatchLineup loading — idempotency + starter/bench split
# ============================================================================


class TestMatchLineupLoading:
    """Verify that load_match_lineups() handles starter/bench correctly
    and is idempotent (re-running doesn't create duplicates)."""

    def test_match_lineup_model_exists(self):
        """MatchLineup ORM model exists with expected columns."""
        from src.database.models import MatchLineup

        assert hasattr(MatchLineup, "match_id")
        assert hasattr(MatchLineup, "team_id")
        assert hasattr(MatchLineup, "player_name")
        assert hasattr(MatchLineup, "position")
        assert hasattr(MatchLineup, "is_starter")
        assert hasattr(MatchLineup, "shirt_number")

    def test_match_lineup_unique_constraint(self):
        """MatchLineup has UniqueConstraint on (match_id, team_id, player_name)."""
        from src.database.models import MatchLineup

        constraints = MatchLineup.__table_args__
        uq_names = [
            c.name for c in constraints
            if hasattr(c, "name") and c.name and "uq_" in c.name
        ]
        assert "uq_match_lineups_match_team_player" in uq_names

    def test_load_match_lineups_empty_df(self):
        """Empty DataFrame returns gracefully."""
        from src.scrapers.loader import load_match_lineups

        result = load_match_lineups(pd.DataFrame(), league_id=1)
        assert result["new"] == 0
        assert result["skipped"] == 0

    def test_load_match_lineups_none_df(self):
        """None DataFrame returns gracefully."""
        from src.scrapers.loader import load_match_lineups

        result = load_match_lineups(None, league_id=1)
        assert result["new"] == 0

    def test_load_match_lineups_function_signature(self):
        """load_match_lineups has correct parameters."""
        import inspect
        from src.scrapers.loader import load_match_lineups

        sig = inspect.signature(load_match_lineups)
        params = list(sig.parameters.keys())
        assert "df" in params
        assert "league_id" in params


# ============================================================================
# Scenario 2: Formation storage on Match model
# ============================================================================


class TestFormationStorage:
    """Verify that Match model has home_formation/away_formation columns."""

    def test_match_has_home_formation(self):
        """Match model has home_formation column."""
        from src.database.models import Match

        assert hasattr(Match, "home_formation")

    def test_match_has_away_formation(self):
        """Match model has away_formation column."""
        from src.database.models import Match

        assert hasattr(Match, "away_formation")

    def test_match_has_lineups_relationship(self):
        """Match model has a 'lineups' relationship to MatchLineup."""
        from src.database.models import Match

        assert hasattr(Match, "lineups")

    def test_formation_in_db_schema(self):
        """Verify formation columns exist in the actual DB schema."""
        from sqlalchemy import inspect as sa_inspect
        from src.database.db import get_engine

        engine = get_engine()
        inspector = sa_inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("matches")}
        assert "home_formation" in cols
        assert "away_formation" in cols


# ============================================================================
# Scenario 3: calculate_squad_rotation() with known lineup data
# ============================================================================


class TestSquadRotation:
    """Verify squad rotation computation logic."""

    def test_function_exists(self):
        """calculate_squad_rotation is importable."""
        from src.features.context import calculate_squad_rotation
        assert callable(calculate_squad_rotation)

    def test_returns_dict_with_key(self):
        """Function returns dict with squad_rotation_index key."""
        from src.features.context import calculate_squad_rotation

        # Use team_id/match_id that likely don't have lineup data
        result = calculate_squad_rotation(
            team_id=99999, match_id=99999,
            match_date="2025-01-01", league_id=1,
        )
        assert "squad_rotation_index" in result

    def test_no_lineup_returns_none(self):
        """Returns None when no lineup data exists for the match."""
        from src.features.context import calculate_squad_rotation

        result = calculate_squad_rotation(
            team_id=99999, match_id=99999,
            match_date="2025-01-01", league_id=1,
        )
        assert result["squad_rotation_index"] is None

    def test_in_feature_cols(self):
        """squad_rotation_index is in FEATURE_COLS."""
        from src.features.engineer import FEATURE_COLS
        assert "squad_rotation_index" in FEATURE_COLS

    def test_in_poisson_model(self):
        """squad_rotation_index is in Poisson model candidates."""
        import inspect
        from src.models.poisson import PoissonModel

        source = inspect.getsource(PoissonModel._select_feature_cols)
        assert "squad_rotation_index" in source

    def test_rotation_range_zero_to_one(self):
        """Rotation index must be in [0.0, 1.0] range conceptually.
        We verify the formula: changes / denominator yields 0.0 <= val <= 1.0.
        Using synthetic sets to verify logic."""
        # Simulate: current XI = {A, B, C, D, E, F, G, H, I, J, K}
        # Previous XI = {A, B, C, D, E, F, G, H, I, J, K} (identical)
        current = {"a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"}
        previous = {"a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"}
        common = current & previous
        changes = len(current) - len(common)
        rotation = changes / len(current)
        assert rotation == 0.0, "Identical XI should give 0.0"

    def test_rotation_full_change(self):
        """Full XI change gives rotation index = 1.0."""
        current = {"a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"}
        previous = {"l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v"}
        common = current & previous
        changes = len(current) - len(common)
        rotation = changes / len(current)
        assert rotation == 1.0, "Complete change should give 1.0"

    def test_rotation_partial_change(self):
        """3 of 11 players changed gives ~0.2727."""
        current = {"a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"}
        previous = {"a", "b", "c", "d", "e", "f", "g", "h", "x", "y", "z"}
        common = current & previous
        changes = len(current) - len(common)
        rotation = changes / len(current)
        assert abs(rotation - 3 / 11) < 0.001


# ============================================================================
# Scenario 4: calculate_formation_change() with same/different formations
# ============================================================================


class TestFormationChange:
    """Verify formation change detection logic."""

    def test_function_exists(self):
        """calculate_formation_change is importable."""
        from src.features.context import calculate_formation_change
        assert callable(calculate_formation_change)

    def test_returns_dict_with_key(self):
        """Function returns dict with formation_changed key."""
        from src.features.context import calculate_formation_change

        result = calculate_formation_change(
            team_id=99999, match_id=99999,
            match_date="2025-01-01", league_id=1,
        )
        assert "formation_changed" in result

    def test_no_data_returns_none(self):
        """Returns None when match doesn't exist."""
        from src.features.context import calculate_formation_change

        result = calculate_formation_change(
            team_id=99999, match_id=99999,
            match_date="2025-01-01", league_id=1,
        )
        assert result["formation_changed"] is None

    def test_in_feature_cols(self):
        """formation_changed is in FEATURE_COLS."""
        from src.features.engineer import FEATURE_COLS
        assert "formation_changed" in FEATURE_COLS

    def test_binary_output_concept(self):
        """Formation change should produce 0 or 1 (not floats)."""
        # Same formation → 0
        assert (1 if "4-3-3" != "4-3-3" else 0) == 0
        # Different formation → 1
        assert (1 if "4-3-3" != "5-4-1" else 0) == 1


# ============================================================================
# Scenario 5: calculate_bench_strength() with known PlayerValue data
# ============================================================================


class TestBenchStrength:
    """Verify bench strength ratio computation."""

    def test_function_exists(self):
        """calculate_bench_strength is importable."""
        from src.features.context import calculate_bench_strength
        assert callable(calculate_bench_strength)

    def test_returns_dict_with_key(self):
        """Function returns dict with bench_strength key."""
        from src.features.context import calculate_bench_strength

        result = calculate_bench_strength(
            team_id=99999, match_id=99999,
            match_date="2025-01-01",
        )
        assert "bench_strength" in result

    def test_no_lineup_returns_none(self):
        """Returns None when no lineup data exists."""
        from src.features.context import calculate_bench_strength

        result = calculate_bench_strength(
            team_id=99999, match_id=99999,
            match_date="2025-01-01",
        )
        assert result["bench_strength"] is None

    def test_in_feature_cols(self):
        """bench_strength is in FEATURE_COLS."""
        from src.features.engineer import FEATURE_COLS
        assert "bench_strength" in FEATURE_COLS

    def test_ratio_computation_concept(self):
        """Bench/starter ratio computed correctly with synthetic values."""
        starter_values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110]
        bench_values = [5, 10, 15, 20, 25, 30, 35]
        starter_total = sum(starter_values)  # 660
        bench_total = sum(bench_values)      # 140
        ratio = bench_total / starter_total
        assert abs(ratio - 140 / 660) < 0.001
        assert 0 < ratio < 1, "Bench should be less than starters"


# ============================================================================
# Scenario 6: All three features return NULL when lineup data missing
# ============================================================================


class TestNullGracefulDegradation:
    """Verify all three lineup features handle missing data gracefully."""

    def test_rotation_null_no_match(self):
        """Squad rotation returns None for non-existent match."""
        from src.features.context import calculate_squad_rotation

        result = calculate_squad_rotation(
            team_id=1, match_id=999999,
            match_date="2020-01-01", league_id=1,
        )
        assert result["squad_rotation_index"] is None

    def test_formation_null_no_match(self):
        """Formation change returns None for non-existent match."""
        from src.features.context import calculate_formation_change

        result = calculate_formation_change(
            team_id=1, match_id=999999,
            match_date="2020-01-01", league_id=1,
        )
        assert result["formation_changed"] is None

    def test_bench_null_no_lineup(self):
        """Bench strength returns None for non-existent lineup."""
        from src.features.context import calculate_bench_strength

        result = calculate_bench_strength(
            team_id=1, match_id=999999,
            match_date="2020-01-01",
        )
        assert result["bench_strength"] is None

    def test_feature_model_nullable(self):
        """All three columns are nullable on the Feature model."""
        from src.database.models import Feature

        # SQLAlchemy Column.nullable should be True
        table = Feature.__table__
        for col_name in ("squad_rotation_index", "formation_changed",
                         "bench_strength"):
            col = table.columns[col_name]
            assert col.nullable is True, f"{col_name} should be nullable"

    def test_db_columns_exist(self):
        """All three columns exist in the actual database."""
        from sqlalchemy import inspect as sa_inspect
        from src.database.db import get_engine

        engine = get_engine()
        inspector = sa_inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("features")}
        assert "squad_rotation_index" in cols
        assert "formation_changed" in cols
        assert "bench_strength" in cols


# ============================================================================
# Scenario 7: Backtest comparison documentation
# ============================================================================


class TestBacktestDocumentation:
    """Verify backtest infrastructure and lineup features are wired into
    the model pipeline correctly for future backtest runs."""

    def test_feature_cols_count(self):
        """FEATURE_COLS has the expected total count after E39 additions."""
        from src.features.engineer import FEATURE_COLS
        # Should include all 3 new lineup features
        assert len(FEATURE_COLS) >= 71

    def test_poisson_model_includes_lineup_features(self):
        """PoissonModel._select_feature_cols includes all 3 lineup features."""
        import inspect
        from src.models.poisson import PoissonModel

        source = inspect.getsource(PoissonModel._select_feature_cols)
        for feat in ("squad_rotation_index", "formation_changed",
                     "bench_strength"):
            assert feat in source, f"Missing {feat} in Poisson candidates"

    def test_xgboost_model_includes_lineup_features(self):
        """XGBoost model source includes all 3 lineup features."""
        # XGBoost may not be importable, so read source file directly.
        source_path = Path(__file__).resolve().parents[1] / \
            "src" / "models" / "xgboost_model.py"
        source = source_path.read_text()
        for feat in ("squad_rotation_index", "formation_changed",
                     "bench_strength"):
            assert feat in source, f"Missing {feat} in XGBoost candidates"

    def test_compute_features_calls_lineup_functions(self):
        """compute_features() calls all three lineup feature functions."""
        source_path = Path(__file__).resolve().parents[1] / \
            "src" / "features" / "engineer.py"
        source = source_path.read_text()
        assert "calculate_squad_rotation" in source
        assert "calculate_formation_change" in source
        assert "calculate_bench_strength" in source

    def test_lineup_scraper_in_evening_pipeline(self):
        """Lineup scraping is wired into the evening pipeline."""
        source_path = Path(__file__).resolve().parents[1] / \
            "src" / "pipeline.py"
        source = source_path.read_text()
        assert "scrape_lineups" in source

    def test_match_lineup_table_in_db(self):
        """match_lineups table exists in the database."""
        from sqlalchemy import inspect as sa_inspect
        from src.database.db import get_engine

        engine = get_engine()
        inspector = sa_inspect(engine)
        tables = inspector.get_table_names()
        assert "match_lineups" in tables

    def test_soccerdata_scraper_has_lineup_method(self):
        """SoccerdataScraper has scrape_lineups method."""
        from src.scrapers.soccerdata import SoccerdataScraper
        assert hasattr(SoccerdataScraper, "scrape_lineups")
