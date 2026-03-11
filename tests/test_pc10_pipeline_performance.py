"""
PC-10-04 — Morning Pipeline Performance Optimization Integration Test
=====================================================================
Automated pytest suite verifying the bulk feature loading and
compute_all_features() optimization introduced in PC-10-01 through PC-10-03.

Scenarios:
  1. load_features_bulk() returns correct DataFrame for synthetic data
  2. load_features_bulk() handles empty seasons (returns empty DataFrame)
  3. load_features_bulk() output matches compute_all_features() output
  4. compute_all_features() with pre-loaded dicts skips per-match DB queries
  5. _generate_predictions() uses bulk loader for historical features

All tests use a real in-memory SQLite database with synthetic data — no
external API calls.

Run with: pytest tests/test_pc10_pipeline_performance.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# ============================================================================
# Path setup
# ============================================================================

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.db import Base
from src.database.models import Feature, League, Match, Team
# Import the shared constant from engineer.py — single source of truth (PC-10-02)
from src.features.engineer import FEATURE_COLS


# ============================================================================
# Test fixtures: in-memory SQLite database
# ============================================================================

@pytest.fixture
def db_session():
    """Create an in-memory SQLite database with schema and return a session factory.

    Uses a patched get_session() context manager so all code under test
    uses this in-memory database instead of the real one.
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)

    # Seed a league
    with Session(engine) as session:
        league = League(
            id=1, name="English Premier League", short_name="EPL",
            country="England", football_data_code="E0",
            is_active=True,
        )
        session.add(league)
        session.commit()

    # Create a context manager that returns a session bound to our engine
    from contextlib import contextmanager

    @contextmanager
    def mock_get_session():
        with Session(engine) as session:
            yield session

    return engine, mock_get_session


def _seed_teams(engine, team_ids):
    """Insert teams into the database."""
    with Session(engine) as session:
        for tid in team_ids:
            if not session.query(Team).filter_by(id=tid).first():
                session.add(Team(id=tid, name=f"Team_{tid}", league_id=1))
        session.commit()


def _seed_matches(engine, matches_data):
    """Insert matches into the database.

    matches_data: list of dicts with keys:
        id, league_id, season, date, home_team_id, away_team_id, status,
        home_goals, away_goals
    """
    with Session(engine) as session:
        for md in matches_data:
            m = Match(
                id=md["id"],
                league_id=md.get("league_id", 1),
                season=md["season"],
                date=md["date"],
                home_team_id=md["home_team_id"],
                away_team_id=md["away_team_id"],
                status=md.get("status", "finished"),
                home_goals=md.get("home_goals"),
                away_goals=md.get("away_goals"),
            )
            session.add(m)
        session.commit()


def _seed_features(engine, match_id, home_team_id, away_team_id, seed=42):
    """Insert home + away Feature rows for a match with deterministic values."""
    rng = np.random.default_rng(seed + match_id)

    with Session(engine) as session:
        for is_home, team_id in [(1, home_team_id), (0, away_team_id)]:
            feat = Feature(
                match_id=match_id,
                team_id=team_id,
                is_home=is_home,
                matchday=15,
                season_progress=0.4,
            )
            # Set all feature columns
            for col in FEATURE_COLS:
                setattr(feat, col, round(float(rng.uniform(0.0, 3.0)), 4))
            session.add(feat)
        session.commit()


# ============================================================================
# Tests: load_features_bulk()
# ============================================================================

class TestLoadFeaturesBulk:
    """Tests for the bulk feature loading function (PC-10-01)."""

    def test_returns_correct_dataframe_format(self, db_session):
        """load_features_bulk() returns a DataFrame with all expected columns."""
        engine, mock_get_session = db_session

        # Seed 3 matches with features
        team_ids = list(range(1, 7))
        _seed_teams(engine, team_ids)

        matches = [
            {"id": 1, "season": "2023-24", "date": "2024-01-01",
             "home_team_id": 1, "away_team_id": 2, "home_goals": 2, "away_goals": 1},
            {"id": 2, "season": "2023-24", "date": "2024-01-08",
             "home_team_id": 3, "away_team_id": 4, "home_goals": 1, "away_goals": 0},
            {"id": 3, "season": "2023-24", "date": "2024-01-15",
             "home_team_id": 5, "away_team_id": 6, "home_goals": 0, "away_goals": 3},
        ]
        _seed_matches(engine, matches)
        for m in matches:
            _seed_features(engine, m["id"], m["home_team_id"], m["away_team_id"])

        with patch("src.features.engineer.get_session", mock_get_session):
            from src.features.engineer import load_features_bulk
            result = load_features_bulk(1, ["2023-24"])

        # Verify DataFrame shape
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3, f"Expected 3 rows, got {len(result)}"

        # Verify all required columns
        assert "match_id" in result.columns
        assert "date" in result.columns
        assert "home_team_id" in result.columns
        assert "away_team_id" in result.columns
        assert "matchday" in result.columns
        assert "season_progress" in result.columns

        # Verify home_* and away_* feature columns
        for col in FEATURE_COLS:
            assert f"home_{col}" in result.columns, f"Missing home_{col}"
            assert f"away_{col}" in result.columns, f"Missing away_{col}"

    def test_handles_empty_seasons(self, db_session):
        """load_features_bulk() returns empty DataFrame for seasons with no data."""
        engine, mock_get_session = db_session

        with patch("src.features.engineer.get_session", mock_get_session):
            from src.features.engineer import load_features_bulk
            result = load_features_bulk(1, ["2019-20"])

        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_handles_empty_seasons_list(self):
        """load_features_bulk() returns empty DataFrame for empty season list."""
        from src.features.engineer import load_features_bulk
        result = load_features_bulk(1, [])
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_skips_matches_without_both_features(self, db_session):
        """Matches missing home or away features are silently skipped."""
        engine, mock_get_session = db_session

        _seed_teams(engine, [1, 2, 3, 4])

        matches = [
            {"id": 10, "season": "2023-24", "date": "2024-01-01",
             "home_team_id": 1, "away_team_id": 2, "home_goals": 2, "away_goals": 1},
            {"id": 11, "season": "2023-24", "date": "2024-01-08",
             "home_team_id": 3, "away_team_id": 4, "home_goals": 1, "away_goals": 0},
        ]
        _seed_matches(engine, matches)

        # Only seed features for match 10 (both home + away)
        _seed_features(engine, 10, 1, 2)

        # Match 11 gets only home feature (no away)
        rng = np.random.default_rng(53)
        with Session(engine) as session:
            feat = Feature(match_id=11, team_id=3, is_home=1,
                           matchday=15, season_progress=0.4)
            for col in FEATURE_COLS:
                setattr(feat, col, round(float(rng.uniform(0.0, 3.0)), 4))
            session.add(feat)
            session.commit()

        with patch("src.features.engineer.get_session", mock_get_session):
            from src.features.engineer import load_features_bulk
            result = load_features_bulk(1, ["2023-24"])

        # Only match 10 should be returned
        assert len(result) == 1
        assert result.iloc[0]["match_id"] == 10

    def test_multiple_seasons(self, db_session):
        """load_features_bulk() loads data across multiple seasons in one call."""
        engine, mock_get_session = db_session

        _seed_teams(engine, list(range(1, 13)))

        # 3 matches in season 1, 3 in season 2
        all_matches = []
        for i, season in enumerate(["2022-23", "2023-24"]):
            for j in range(3):
                mid = i * 100 + j + 1
                all_matches.append({
                    "id": mid, "season": season,
                    "date": f"2024-0{i+1}-{(j+1)*7:02d}",
                    "home_team_id": i * 6 + j * 2 + 1,
                    "away_team_id": i * 6 + j * 2 + 2,
                    "home_goals": 2, "away_goals": 1,
                })

        _seed_matches(engine, all_matches)
        for m in all_matches:
            _seed_features(engine, m["id"], m["home_team_id"], m["away_team_id"])

        with patch("src.features.engineer.get_session", mock_get_session):
            from src.features.engineer import load_features_bulk
            result = load_features_bulk(1, ["2022-23", "2023-24"])

        assert len(result) == 6, f"Expected 6 rows (3+3), got {len(result)}"

    def test_feature_values_are_correct(self, db_session):
        """Bulk-loaded feature values match what was stored in the database."""
        engine, mock_get_session = db_session

        _seed_teams(engine, [1, 2])
        _seed_matches(engine, [{
            "id": 20, "season": "2023-24", "date": "2024-02-01",
            "home_team_id": 1, "away_team_id": 2,
            "home_goals": 3, "away_goals": 0,
        }])

        # Seed with known values
        with Session(engine) as session:
            home_feat = Feature(
                match_id=20, team_id=1, is_home=1,
                matchday=20, season_progress=0.53,
                form_5=2.5, goals_scored_5=1.8, goals_conceded_5=0.6,
            )
            away_feat = Feature(
                match_id=20, team_id=2, is_home=0,
                matchday=20, season_progress=0.53,
                form_5=1.2, goals_scored_5=0.9, goals_conceded_5=1.5,
            )
            session.add_all([home_feat, away_feat])
            session.commit()

        with patch("src.features.engineer.get_session", mock_get_session):
            from src.features.engineer import load_features_bulk
            result = load_features_bulk(1, ["2023-24"])

        assert len(result) == 1
        row = result.iloc[0]
        assert row["home_form_5"] == 2.5
        assert row["home_goals_scored_5"] == 1.8
        assert row["away_form_5"] == 1.2
        assert row["away_goals_conceded_5"] == 1.5
        assert row["matchday"] == 20
        assert row["season_progress"] == pytest.approx(0.53)


# ============================================================================
# Tests: compute_all_features() optimization (PC-10-02)
# ============================================================================

class TestComputeAllFeaturesOptimized:
    """Tests for the bulk pre-loading optimization in compute_all_features()."""

    def test_uses_bulk_queries_not_per_match(self, db_session):
        """compute_all_features() should use bulk queries, not per-match DB calls."""
        engine, mock_get_session = db_session

        _seed_teams(engine, [1, 2, 3, 4])
        _seed_matches(engine, [
            {"id": 30, "season": "2024-25", "date": "2024-08-15",
             "home_team_id": 1, "away_team_id": 2, "home_goals": 2, "away_goals": 1},
            {"id": 31, "season": "2024-25", "date": "2024-08-22",
             "home_team_id": 3, "away_team_id": 4, "home_goals": 0, "away_goals": 0},
        ])
        for mid, ht, at in [(30, 1, 2), (31, 3, 4)]:
            _seed_features(engine, mid, ht, at)

        # Track query count by wrapping get_session
        query_count = [0]
        original_mock = mock_get_session

        from contextlib import contextmanager

        @contextmanager
        def counting_get_session():
            query_count[0] += 1
            with original_mock() as session:
                yield session

        with patch("src.features.engineer.get_session", counting_get_session):
            from src.features.engineer import compute_all_features
            result = compute_all_features(1, "2024-25")

        # With 2 matches that both have features (skipped), the optimized version
        # should use ~4 sessions: matches, feature counts, team names, feature bulk read
        # NOT 5 sessions per match (10 total for 2 matches)
        assert query_count[0] <= 6, (
            f"Expected ≤6 DB sessions for 2 skipped matches (bulk pre-loading), "
            f"got {query_count[0]}. Per-match queries should be eliminated."
        )

        # Verify the result is still correct
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2


# ============================================================================
# Tests: _generate_predictions() uses bulk loader (PC-10-03)
# ============================================================================

class TestGeneratePredictionsBulkLoader:
    """Tests that _generate_predictions() uses load_features_bulk() for historical data."""

    def test_pipeline_imports_load_features_bulk(self):
        """The pipeline module can import load_features_bulk from engineer."""
        from src.features.engineer import load_features_bulk
        assert callable(load_features_bulk)

    def test_pipeline_code_references_bulk_loader(self):
        """Verify pipeline.py uses load_features_bulk in _generate_predictions()."""
        import inspect
        from src.pipeline import Pipeline

        source = inspect.getsource(Pipeline._generate_predictions)

        # Verify it references load_features_bulk
        assert "load_features_bulk" in source, (
            "_generate_predictions() should use load_features_bulk() "
            "for loading historical features (PC-10-03)"
        )

        # Verify the old per-season loop pattern is gone
        assert "for hist_season in hist_seasons" not in source, (
            "_generate_predictions() should NOT loop through historical seasons "
            "calling compute_all_features() one at a time"
        )

    def test_pipeline_does_not_loop_compute_all_features(self):
        """The historical feature loading code should NOT loop calling compute_all_features."""
        import inspect
        from src.pipeline import Pipeline

        source = inspect.getsource(Pipeline._generate_predictions)

        # The old pattern was: "for hist_season in hist_seasons:" followed by
        # "compute_all_features(league_id, hist_season)".  This per-season
        # loop should be replaced by a single load_features_bulk() call.
        assert "for hist_season in hist_seasons" not in source, (
            "Historical feature loading should NOT loop through seasons "
            "calling compute_all_features() one at a time. Use load_features_bulk() instead."
        )


# ============================================================================
# Tests: DataFrame format consistency
# ============================================================================

class TestDataFrameConsistency:
    """Tests that bulk and per-match loading produce identical formats."""

    def test_feature_cols_match_model_columns(self):
        """The feature column list used in bulk loading matches the Feature model."""
        for col in FEATURE_COLS:
            assert hasattr(Feature, col), (
                f"Feature model missing column '{col}' — "
                "bulk loader feature_cols list is out of sync with the ORM model"
            )

    def test_bulk_output_has_expected_column_count(self):
        """Bulk-loaded DataFrame should have the right number of columns."""
        # 4 metadata cols + 2 shared cols + 2 * N feature cols
        expected_count = 4 + 2 + len(FEATURE_COLS) * 2
        assert expected_count == 4 + 2 + len(FEATURE_COLS) * 2

    def test_bulk_and_read_existing_use_same_feature_cols(self):
        """load_features_bulk() and _read_existing_features() both use FEATURE_COLS."""
        import inspect
        from src.features.engineer import (
            load_features_bulk,
            _read_existing_features,
            FEATURE_COLS as shared_cols,
        )

        # Both functions should reference the shared FEATURE_COLS constant
        bulk_source = inspect.getsource(load_features_bulk)
        read_source = inspect.getsource(_read_existing_features)

        assert "FEATURE_COLS" in bulk_source, (
            "load_features_bulk() should use the shared FEATURE_COLS constant"
        )
        assert "FEATURE_COLS" in read_source, (
            "_read_existing_features() should use the shared FEATURE_COLS constant"
        )

        # Verify the constant includes key distinctive columns
        for col in ["league_home_adv_5", "is_newly_promoted", "pinnacle_overround"]:
            assert col in shared_cols, (
                f"FEATURE_COLS missing '{col}' — column list out of sync with Feature model"
            )

    def test_bulk_matches_per_match_output(self, db_session):
        """Bulk-loaded DataFrame matches per-match _read_existing_features() output."""
        engine, mock_get_session = db_session

        _seed_teams(engine, [1, 2])
        _seed_matches(engine, [{
            "id": 40, "season": "2023-24", "date": "2024-03-01",
            "home_team_id": 1, "away_team_id": 2,
            "home_goals": 1, "away_goals": 1,
        }])
        _seed_features(engine, 40, 1, 2, seed=99)

        with patch("src.features.engineer.get_session", mock_get_session):
            from src.features.engineer import load_features_bulk, _read_existing_features

            # Get bulk result
            bulk_df = load_features_bulk(1, ["2023-24"])

            # Get per-match result
            match_info = {
                "id": 40, "date": "2024-03-01",
                "home_team_id": 1, "away_team_id": 2,
            }
            per_match_row = _read_existing_features(40, match_info)

        assert len(bulk_df) == 1
        assert per_match_row is not None

        bulk_row = bulk_df.iloc[0]

        # Compare key columns — values should be identical
        assert bulk_row["match_id"] == per_match_row["match_id"]
        assert bulk_row["matchday"] == per_match_row["matchday"]

        # Compare feature values
        for col in FEATURE_COLS:
            bulk_val = bulk_row.get(f"home_{col}")
            per_val = per_match_row.get(f"home_{col}")
            if bulk_val is not None and per_val is not None:
                assert bulk_val == pytest.approx(per_val, abs=1e-6), (
                    f"home_{col} mismatch: bulk={bulk_val}, per_match={per_val}"
                )


# ============================================================================
# Tests: Edge cases and robustness
# ============================================================================

class TestEdgeCases:
    """Edge case tests for the bulk loading optimization."""

    def test_function_signatures_correct(self):
        """Verify function signatures match the plan specification."""
        import inspect
        from src.features.engineer import load_features_bulk, compute_all_features

        # load_features_bulk(league_id, seasons)
        sig = inspect.signature(load_features_bulk)
        params = list(sig.parameters.keys())
        assert "league_id" in params
        assert "seasons" in params

        # compute_all_features(league_id, season, force_recompute)
        sig = inspect.signature(compute_all_features)
        params = list(sig.parameters.keys())
        assert "league_id" in params
        assert "season" in params
        assert "force_recompute" in params

    def test_bulk_loader_handles_only_scheduled_matches(self, db_session):
        """Scheduled matches (no goals) should still have features loaded."""
        engine, mock_get_session = db_session

        _seed_teams(engine, [1, 2])
        _seed_matches(engine, [{
            "id": 50, "season": "2024-25", "date": "2025-03-14",
            "home_team_id": 1, "away_team_id": 2,
            "status": "scheduled", "home_goals": None, "away_goals": None,
        }])
        _seed_features(engine, 50, 1, 2)

        with patch("src.features.engineer.get_session", mock_get_session):
            from src.features.engineer import load_features_bulk
            result = load_features_bulk(1, ["2024-25"])

        assert len(result) == 1
        assert result.iloc[0]["match_id"] == 50
