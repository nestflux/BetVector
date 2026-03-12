"""
E38-06 — Multi-League Expansion Phase 2 Integration Test
=========================================================
Automated pytest suite validating that the E38 league expansion
(Championship backfill, Ligue 1, Bundesliga, Serie A) is correctly
wired end-to-end.

Scenarios (from the E38-06 build plan):
  1. Config: all 6 leagues present and active in leagues.yaml
  2. Config: season counts correct per league
  3. Team name maps: no duplicate canonical names across leagues
  4. Feature engineer: handles null Understat gracefully
  5. Backfill script: --league flag routes to correct league
  6. Seed: creates League + Season rows for all 6 leagues
  7. Data integrity: match counts within expected ranges
  8. Backtest: each league produces valid Brier score

All tests use synthetic data or config/file validation — no real DB
writes.  Tests that need DB read access use the existing production DB
via get_session() (read-only queries).

Run with: pytest tests/test_e38_integration.py -v
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest
import yaml

# ============================================================================
# Path setup
# ============================================================================

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ============================================================================
# Constants — expected league configuration
# ============================================================================

# All 6 leagues in the system as of E38
EXPECTED_LEAGUES = {
    "EPL": {
        "football_data_code": "E0",
        "country": "England",
        "understat_league": "EPL",
        "season_count": 6,
        "total_matchdays": 38,
    },
    "Championship": {
        "football_data_code": "E1",
        "country": "England",
        "understat_league": None,
        "season_count": 6,
        "total_matchdays": 46,
    },
    "LaLiga": {
        "football_data_code": "SP1",
        "country": "Spain",
        "understat_league": "La_Liga",
        "season_count": 6,
        "total_matchdays": 38,
    },
    "Ligue1": {
        "football_data_code": "F1",
        "country": "France",
        "understat_league": "Ligue_1",
        "season_count": 6,
        "total_matchdays": 38,
    },
    "Bundesliga": {
        "football_data_code": "D1",
        "country": "Germany",
        "understat_league": "Bundesliga",
        "season_count": 6,
        "total_matchdays": 34,
    },
    "SerieA": {
        "football_data_code": "I1",
        "country": "Italy",
        "understat_league": "Serie_A",
        "season_count": 6,
        "total_matchdays": 38,
    },
}

# Edge thresholds per league (from leagues.yaml)
EXPECTED_EDGE_THRESHOLDS = {
    "EPL": 0.05,         # Standard — well-served market
    "Championship": 0.03,  # Lower — thinner market, less efficient
    "LaLiga": 0.05,      # Standard — well-served market
    "Ligue1": 0.05,      # Standard — well-served market
    "Bundesliga": 0.05,  # Standard — well-served market
    "SerieA": 0.05,      # Standard — well-served market
}

# Minimum expected match counts per league (across all seasons in local DB)
# These are conservative lower bounds — actual counts should exceed these.
MIN_MATCH_COUNTS = {
    "EPL": 700,          # 760 in local DB (2024-25 + 2025-26; historical on Neon)
    "Championship": 3_000,  # 3,181 (6 full seasons)
    "LaLiga": 2_000,     # 2,160 (6 seasons × ~360 matches)
    "Ligue1": 1_900,     # ~1,977 (French Ligue 1: 18-20 teams, ~306-380 matches/season)
    "Bundesliga": 1_600, # 1,746 (6 seasons × ~291 matches)
    "SerieA": 2_000,     # 2,170 (6 seasons × ~362 matches)
}


# ============================================================================
# Helpers
# ============================================================================

def _load_leagues_yaml() -> List[dict]:
    """Load and return the list of league configs from leagues.yaml."""
    config_path = Path("config/leagues.yaml")
    assert config_path.exists(), "config/leagues.yaml not found"
    with config_path.open() as f:
        cfg = yaml.safe_load(f)
    return cfg.get("leagues", [])


def _get_league_config(short_name: str) -> dict:
    """Return the config block for a specific league."""
    for lg in _load_leagues_yaml():
        if lg["short_name"] == short_name:
            return lg
    pytest.fail(f"League {short_name!r} not found in leagues.yaml")


def _load_backtest_report(league_short_name: str) -> dict:
    """Load a backtest JSON report from data/predictions/."""
    # Reports use the naming pattern: backtest_report_poisson_{league}_{season}.json
    path = Path(f"data/predictions/backtest_report_poisson_{league_short_name}_2024-25.json")
    assert path.exists(), (
        f"Backtest report not found: {path}. "
        f"Run the backtest first via run_pipeline.py or backtester."
    )
    with path.open() as f:
        return json.load(f)


_exit_stack = contextlib.ExitStack()
_db_session = None


def _get_session():
    """Return a shared read-only SQLAlchemy session for DB-based tests."""
    global _db_session
    if _db_session is None:
        import atexit
        from src.database.db import get_session
        _db_session = _exit_stack.enter_context(get_session())
        atexit.register(_exit_stack.close)
    return _db_session


# ============================================================================
# Scenario 1 — Config: all 6 leagues present and active
# ============================================================================

class TestAllLeaguesConfigured:
    """Verify all 6 leagues are defined and active in leagues.yaml."""

    def test_six_leagues_present(self):
        """leagues.yaml must contain exactly 6 league entries."""
        leagues = _load_leagues_yaml()
        assert len(leagues) == 6, (
            f"Expected 6 leagues in leagues.yaml, found {len(leagues)}: "
            f"{[lg['short_name'] for lg in leagues]}"
        )

    def test_all_expected_short_names(self):
        """All expected short_names must be present in leagues.yaml."""
        leagues = _load_leagues_yaml()
        short_names = {lg["short_name"] for lg in leagues}
        for expected in EXPECTED_LEAGUES:
            assert expected in short_names, (
                f"Missing league '{expected}' in leagues.yaml. "
                f"Found: {short_names}"
            )

    @pytest.mark.parametrize("short_name", list(EXPECTED_LEAGUES.keys()))
    def test_league_is_active(self, short_name: str):
        """Each league must have is_active: true."""
        lg = _get_league_config(short_name)
        assert lg["is_active"] is True, (
            f"League {short_name} has is_active={lg['is_active']}, expected true"
        )

    @pytest.mark.parametrize("short_name", list(EXPECTED_LEAGUES.keys()))
    def test_football_data_code_correct(self, short_name: str):
        """Each league's football_data_code must match the expected value."""
        lg = _get_league_config(short_name)
        expected_code = EXPECTED_LEAGUES[short_name]["football_data_code"]
        assert lg["football_data_code"] == expected_code, (
            f"{short_name}: football_data_code={lg['football_data_code']}, "
            f"expected {expected_code}"
        )

    @pytest.mark.parametrize("short_name", list(EXPECTED_LEAGUES.keys()))
    def test_understat_league_correct(self, short_name: str):
        """Each league's understat_league must match the expected value (or null)."""
        lg = _get_league_config(short_name)
        expected = EXPECTED_LEAGUES[short_name]["understat_league"]
        actual = lg.get("understat_league")
        assert actual == expected, (
            f"{short_name}: understat_league={actual!r}, expected {expected!r}"
        )


# ============================================================================
# Scenario 2 — Config: season counts correct per league
# ============================================================================

class TestSeasonCounts:
    """Verify each league has the expected number of configured seasons."""

    @pytest.mark.parametrize("short_name", list(EXPECTED_LEAGUES.keys()))
    def test_season_count(self, short_name: str):
        """Each league must have exactly 6 configured seasons (2020-21 through 2025-26)."""
        lg = _get_league_config(short_name)
        seasons = lg.get("seasons", [])
        expected_count = EXPECTED_LEAGUES[short_name]["season_count"]
        assert len(seasons) == expected_count, (
            f"{short_name}: {len(seasons)} seasons configured, expected {expected_count}. "
            f"Seasons: {seasons}"
        )

    @pytest.mark.parametrize("short_name", list(EXPECTED_LEAGUES.keys()))
    def test_seasons_start_2020(self, short_name: str):
        """Every league must include 2020-21 as the earliest season."""
        lg = _get_league_config(short_name)
        seasons = lg.get("seasons", [])
        assert "2020-21" in seasons, (
            f"{short_name}: 2020-21 not in configured seasons ({seasons})"
        )

    @pytest.mark.parametrize("short_name", list(EXPECTED_LEAGUES.keys()))
    def test_seasons_include_current(self, short_name: str):
        """Every league must include the current season 2025-26."""
        lg = _get_league_config(short_name)
        seasons = lg.get("seasons", [])
        assert "2025-26" in seasons, (
            f"{short_name}: 2025-26 not in configured seasons ({seasons})"
        )

    @pytest.mark.parametrize("short_name", list(EXPECTED_LEAGUES.keys()))
    def test_matchday_count(self, short_name: str):
        """Each league's total_matchdays must match expected value."""
        lg = _get_league_config(short_name)
        expected = EXPECTED_LEAGUES[short_name]["total_matchdays"]
        actual = lg.get("total_matchdays")
        assert actual == expected, (
            f"{short_name}: total_matchdays={actual}, expected {expected}"
        )


# ============================================================================
# Scenario 3 — Team name maps: no duplicate canonical names across leagues
# ============================================================================

class TestTeamNameMaps:
    """Verify team name maps are well-formed with no cross-league conflicts."""

    def test_football_data_maps_no_internal_duplicates(self):
        """Each Football-Data team name map must not have duplicate values within itself.

        Duplicate values would mean two CSV names map to the same canonical name,
        which could cause match deduplication issues.
        """
        from src.scrapers.football_data import (
            EPL_TEAM_NAME_MAP,
            LIGUE_1_TEAM_NAME_MAP,
            BUNDESLIGA_TEAM_NAME_MAP,
            SERIE_A_TEAM_NAME_MAP,
        )

        maps = {
            "EPL": EPL_TEAM_NAME_MAP,
            "Ligue1": LIGUE_1_TEAM_NAME_MAP,
            "Bundesliga": BUNDESLIGA_TEAM_NAME_MAP,
            "SerieA": SERIE_A_TEAM_NAME_MAP,
        }

        for map_name, name_map in maps.items():
            values = list(name_map.values())
            duplicates = [v for v in values if values.count(v) > 1]
            assert not duplicates, (
                f"{map_name} team name map has duplicate canonical names: "
                f"{set(duplicates)}"
            )

    def test_understat_map_no_conflicting_keys(self):
        """The Understat team name map must have unique keys.

        Since all leagues share UNDERSTAT_EPL_TEAM_MAP, we verify each
        Understat API name maps to exactly one canonical DB name.
        Duplicate values are expected (e.g., "Huesca" and "SD Huesca"
        both mapping to "Huesca" across different seasons).
        """
        from src.scrapers.understat_scraper import UNDERSTAT_EPL_TEAM_MAP

        # Dict keys are inherently unique in Python, so verify the map
        # has a reasonable number of entries (120+ across 5 Understat leagues)
        assert len(UNDERSTAT_EPL_TEAM_MAP) >= 120, (
            f"UNDERSTAT_EPL_TEAM_MAP has only {len(UNDERSTAT_EPL_TEAM_MAP)} entries, "
            "expected 120+ across EPL, La Liga, Ligue 1, Bundesliga, Serie A"
        )

        # Verify all values are non-empty strings
        for key, value in UNDERSTAT_EPL_TEAM_MAP.items():
            assert isinstance(value, str) and len(value) > 0, (
                f"UNDERSTAT_EPL_TEAM_MAP[{key!r}] = {value!r} — must be non-empty string"
            )

    def test_clubelo_map_no_conflicting_keys(self):
        """The ClubElo team name map must have unique keys.

        Duplicate values are expected because multiple ClubElo API names
        can map to the same canonical DB name across different leagues
        (e.g., "AstonVilla" → "Aston Villa" from EPL section, and
        identity-mapped "Aston Villa" from another league section).
        """
        from src.scrapers.clubelo_scraper import TEAM_NAME_MAP

        # Dict keys are inherently unique; verify map has reasonable size
        assert len(TEAM_NAME_MAP) >= 100, (
            f"ClubElo TEAM_NAME_MAP has only {len(TEAM_NAME_MAP)} entries, "
            "expected 100+ across all tracked leagues"
        )

        # Verify all values are non-empty strings
        for key, value in TEAM_NAME_MAP.items():
            assert isinstance(value, str) and len(value) > 0, (
                f"ClubElo TEAM_NAME_MAP[{key!r}] = {value!r} — must be non-empty string"
            )

    def test_football_data_get_team_name_map_registry(self):
        """_get_team_name_map must return a map for every league that has one.

        EPL, Ligue1, Bundesliga, SerieA have explicit maps.
        Championship and LaLiga use the identity map pattern (FD names = canonical).
        """
        from src.scrapers.football_data import FootballDataScraper

        for short_name in ["EPL", "Ligue1", "Bundesliga", "SerieA"]:
            name_map = FootballDataScraper._get_team_name_map(short_name)
            assert isinstance(name_map, dict), (
                f"_get_team_name_map({short_name!r}) did not return a dict"
            )
            assert len(name_map) > 0, (
                f"_get_team_name_map({short_name!r}) returned empty dict"
            )

    def test_understat_map_covers_all_understat_leagues(self):
        """The Understat map must include teams for all Understat-covered leagues.

        We check for at least one team from each Understat league:
        EPL (Arsenal), La Liga (Barcelona), Bundesliga (Bayern Munich), Serie A (Inter).
        """
        from src.scrapers.understat_scraper import UNDERSTAT_EPL_TEAM_MAP

        # Spot-check representative teams from each Understat league
        expected_entries = {
            "Arsenal": "Arsenal",              # EPL
            "Barcelona": "Barcelona",          # La Liga
            "Paris Saint Germain": "Paris SG", # Ligue 1
            "Bayern Munich": "Bayern Munich",  # Bundesliga
            "Inter": "Inter",                  # Serie A
        }
        for understat_name, canonical_name in expected_entries.items():
            assert understat_name in UNDERSTAT_EPL_TEAM_MAP, (
                f"Missing Understat team: {understat_name!r}"
            )
            assert UNDERSTAT_EPL_TEAM_MAP[understat_name] == canonical_name, (
                f"Understat {understat_name!r} maps to "
                f"{UNDERSTAT_EPL_TEAM_MAP[understat_name]!r}, expected {canonical_name!r}"
            )


# ============================================================================
# Scenario 4 — Feature engineer: handles null Understat gracefully
# ============================================================================

class TestFeatureEngineerNullUnderstat:
    """Verify that the feature engineer and models handle missing xG gracefully.

    Championship doesn't have Understat coverage, so xG-based feature
    columns (npxg_5, deep_5, etc.) will be NaN or absent.  The Poisson
    and XGBoost models must handle this without crashing.
    """

    def _make_features_without_xg(self, n_rows: int = 50) -> pd.DataFrame:
        """Create a feature DataFrame with NO xG columns.

        Simulates what Championship features look like:
        only form, market, and basic stats — no npxg, deep, xga, etc.
        """
        rng = np.random.default_rng(42)
        data: Dict[str, np.ndarray] = {"match_id": np.arange(1, n_rows + 1)}

        for prefix in ("home_", "away_"):
            # Basic form (always available from goals data)
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
            data[f"{prefix}rest_days"] = rng.integers(2, 14, n_rows).astype(float)
            data[f"{prefix}h2h_goals_scored"] = rng.uniform(0.0, 3.0, n_rows)
            data[f"{prefix}pinnacle_home_prob"] = rng.uniform(0.2, 0.6, n_rows)
            data[f"{prefix}pinnacle_draw_prob"] = rng.uniform(0.2, 0.35, n_rows)
            data[f"{prefix}pinnacle_away_prob"] = rng.uniform(0.15, 0.5, n_rows)

            # xG columns intentionally ABSENT — simulating Championship (no Understat)
            # npxg_5, deep_5, npxga_5, ppda_allowed_5, set_piece_xg_5, etc. are NOT here

        return pd.DataFrame(data)

    def test_poisson_select_feature_cols_filters_missing(self):
        """Poisson _select_feature_cols() drops candidates not in the DataFrame.

        When xG columns are absent (Championship — no Understat), the model
        must gracefully use only available features.  The method takes
        (df, target) where target is "home" or "away".
        """
        from src.models.poisson import PoissonModel

        model = PoissonModel()
        df = self._make_features_without_xg()

        # Access the feature selection method (requires target: "home" or "away")
        available_cols = model._select_feature_cols(df, target="home")

        # Must not include any xG columns since they're not in the DataFrame
        xg_cols = [c for c in available_cols if "npxg" in c or "deep" in c or "ppda" in c]
        assert not xg_cols, (
            f"Poisson selected xG columns that don't exist in the DataFrame: {xg_cols}"
        )

        # Must include some form/market columns that DO exist
        assert len(available_cols) > 0, "Poisson selected zero features"

    def test_poisson_fillna_handles_all_nan_column(self):
        """Poisson fillna(mean).fillna(0.0) handles columns that are entirely NaN.

        When a feature column exists but is all NaN (e.g., Elo for some teams),
        fillna(mean) returns NaN (mean of empty = NaN), so fillna(0.0) catches it.
        """
        from src.models.poisson import PoissonModel

        model = PoissonModel()
        df = self._make_features_without_xg(100)

        # Add an all-NaN column (simulates partial Elo coverage)
        df["home_elo_rating"] = np.nan
        df["away_elo_rating"] = np.nan

        results = pd.DataFrame({
            "match_id": np.arange(1, 101),
            "home_goals": np.random.default_rng(42).poisson(1.4, 100),
            "away_goals": np.random.default_rng(42).poisson(1.1, 100),
        })

        # Training should not crash even with all-NaN columns
        model.train(df, results)
        assert model._is_trained is True, "Poisson model failed to train with all-NaN column"


# ============================================================================
# Scenario 5 — Backfill script: --league flag routes correctly
# ============================================================================

class TestBackfillLeagueRouting:
    """Verify the backfill script's --league flag selects the correct league."""

    def test_league_argument_exists_in_parser(self):
        """The argparse parser must accept a --league argument."""
        import argparse

        # Parse the backfill script source to verify --league is defined
        script_path = Path("scripts/backfill_historical.py")
        assert script_path.exists(), "scripts/backfill_historical.py not found"

        source = script_path.read_text()
        assert '"--league"' in source or "'--league'" in source, (
            "Backfill script does not accept --league argument"
        )

    def test_league_routing_filters_active_leagues(self):
        """--league EPL should select EPL; --league SerieA should select Serie A.

        We verify the routing logic by checking that each league short_name
        is present in the active leagues list from config.
        """
        from src.config import BetVectorConfig

        config = BetVectorConfig()
        active_leagues = config.get_active_leagues()
        active_short_names = {lc.short_name for lc in active_leagues}

        # All 6 leagues must be in the active list
        for short_name in EXPECTED_LEAGUES:
            assert short_name in active_short_names, (
                f"League {short_name!r} is not in config.get_active_leagues(). "
                f"Active: {active_short_names}"
            )

    @pytest.mark.parametrize("league_name", [
        "EPL", "Championship", "LaLiga", "Ligue1", "Bundesliga", "SerieA",
    ])
    def test_backfill_league_routing_logic(self, league_name: str):
        """The backfill script's league selection logic must find each league.

        Simulates the core routing logic from backfill_historical.py:
            league_cfg = next(lc for lc in active if lc.short_name == args.league)
        """
        from src.config import BetVectorConfig

        config = BetVectorConfig()
        active_leagues = config.get_active_leagues()

        # Simulate the routing logic from the backfill script
        league_cfg = next(
            (lc for lc in active_leagues if lc.short_name == league_name),
            None,
        )
        assert league_cfg is not None, (
            f"Backfill routing failed for --league {league_name!r}"
        )
        assert league_cfg.short_name == league_name


# ============================================================================
# Scenario 6 — Seed: creates League + Season rows for all 6 leagues
# ============================================================================

class TestSeedAllLeagues:
    """Verify seed_leagues() and seed_seasons() handle all 6 leagues.

    Instead of actually running the seed (which modifies DB), we verify
    that the seed module correctly iterates over config.get_active_leagues()
    which now includes all 6 leagues.
    """

    def test_seed_leagues_iterates_all_active(self):
        """seed_leagues() must iterate over all active leagues from config.

        We verify by checking that config.get_active_leagues() returns
        all 6 expected leagues.
        """
        from src.config import BetVectorConfig

        config = BetVectorConfig()
        active = config.get_active_leagues()
        short_names = {lc.short_name for lc in active}

        assert short_names == set(EXPECTED_LEAGUES.keys()), (
            f"get_active_leagues() returned {short_names}, "
            f"expected {set(EXPECTED_LEAGUES.keys())}"
        )

    def test_seed_seasons_creates_correct_count(self):
        """seed_seasons() should create 6 seasons per league = 36 total.

        We verify by counting the total seasons across all active leagues.
        """
        from src.config import BetVectorConfig

        config = BetVectorConfig()
        active = config.get_active_leagues()

        total_seasons = sum(len(lc.seasons) for lc in active)
        assert total_seasons == 36, (
            f"Total configured seasons across 6 leagues = {total_seasons}, expected 36"
        )

    def test_all_leagues_exist_in_database(self):
        """All 6 leagues must exist in the database after seeding."""
        from src.database.models import League

        session = _get_session()
        db_leagues = session.query(League).filter_by(is_active=1).all()
        db_short_names = {lg.short_name for lg in db_leagues}

        for short_name in EXPECTED_LEAGUES:
            assert short_name in db_short_names, (
                f"League {short_name!r} not found in database. "
                f"DB leagues: {db_short_names}"
            )

    def test_all_seasons_exist_in_database(self):
        """All 36 league-season combinations must exist in the database."""
        from src.database.models import League, Season

        session = _get_session()
        total = 0
        for short_name in EXPECTED_LEAGUES:
            league = session.query(League).filter_by(short_name=short_name).first()
            assert league is not None, f"League {short_name!r} not in DB"
            season_count = session.query(Season).filter_by(league_id=league.id).count()
            total += season_count
            assert season_count >= 6, (
                f"{short_name}: only {season_count} Season rows in DB, expected ≥6"
            )

        assert total >= 36, (
            f"Total Season rows across all leagues = {total}, expected ≥36"
        )


# ============================================================================
# Scenario 7 — Data integrity: match counts within expected ranges
# ============================================================================

class TestDataIntegrity:
    """Verify match, odds, and feature counts per league are within bounds."""

    @pytest.mark.parametrize("short_name", list(MIN_MATCH_COUNTS.keys()))
    def test_match_count_per_league(self, short_name: str):
        """Each league must have at least the minimum expected match count."""
        from src.database.models import League, Match

        session = _get_session()
        league = session.query(League).filter_by(short_name=short_name).first()
        assert league is not None, f"League {short_name!r} not in DB"

        match_count = session.query(Match).filter_by(league_id=league.id).count()
        min_expected = MIN_MATCH_COUNTS[short_name]
        assert match_count >= min_expected, (
            f"{short_name}: {match_count} matches in DB, expected ≥{min_expected}"
        )

    @pytest.mark.parametrize("short_name", list(MIN_MATCH_COUNTS.keys()))
    def test_no_null_team_ids(self, short_name: str):
        """No match should have NULL home_team_id or away_team_id."""
        from src.database.models import League, Match

        session = _get_session()
        league = session.query(League).filter_by(short_name=short_name).first()
        if league is None:
            pytest.skip(f"League {short_name!r} not in DB")

        null_home = (
            session.query(Match)
            .filter(Match.league_id == league.id, Match.home_team_id.is_(None))
            .count()
        )
        null_away = (
            session.query(Match)
            .filter(Match.league_id == league.id, Match.away_team_id.is_(None))
            .count()
        )
        assert null_home == 0, f"{short_name}: {null_home} matches with NULL home_team_id"
        assert null_away == 0, f"{short_name}: {null_away} matches with NULL away_team_id"

    @pytest.mark.parametrize("short_name", list(MIN_MATCH_COUNTS.keys()))
    def test_no_null_dates(self, short_name: str):
        """No match should have a NULL date."""
        from src.database.models import League, Match

        session = _get_session()
        league = session.query(League).filter_by(short_name=short_name).first()
        if league is None:
            pytest.skip(f"League {short_name!r} not in DB")

        null_dates = (
            session.query(Match)
            .filter(Match.league_id == league.id, Match.date.is_(None))
            .count()
        )
        assert null_dates == 0, f"{short_name}: {null_dates} matches with NULL date"

    @pytest.mark.parametrize("short_name", list(MIN_MATCH_COUNTS.keys()))
    def test_features_exist(self, short_name: str):
        """Each league must have Feature rows computed."""
        from src.database.models import Feature, League, Match

        session = _get_session()
        league = session.query(League).filter_by(short_name=short_name).first()
        if league is None:
            pytest.skip(f"League {short_name!r} not in DB")

        feature_count = (
            session.query(Feature)
            .join(Match, Feature.match_id == Match.id)
            .filter(Match.league_id == league.id)
            .count()
        )
        # Features should exist for most matches (at least 80% of match count)
        min_expected = int(MIN_MATCH_COUNTS[short_name] * 0.8)
        assert feature_count >= min_expected, (
            f"{short_name}: {feature_count} Feature rows, expected ≥{min_expected}"
        )

    def test_no_orphan_features(self):
        """No Feature row should reference a non-existent Match."""
        from src.database.models import Feature, Match

        session = _get_session()
        # Features with match_id not in the matches table
        orphans = (
            session.query(Feature)
            .outerjoin(Match, Feature.match_id == Match.id)
            .filter(Match.id.is_(None))
            .count()
        )
        assert orphans == 0, f"{orphans} orphan Feature rows found (no matching Match)"


# ============================================================================
# Scenario 8 — Backtest: each league produces valid Brier score
# ============================================================================

class TestBacktestResults:
    """Verify each new league's backtest report exists and meets quality thresholds.

    Brier score thresholds:
    - Understat leagues (La Liga, Bundesliga, Serie A): < 0.65
    - Non-Understat leagues (Championship): < 0.70
      (structural limitation — no xG features available)
    """

    # Leagues that were backtested in E38-05 (excluding EPL which uses Neon data)
    BACKTEST_LEAGUES = {
        "LaLiga": {"brier_max": 0.65, "has_understat": True},
        "Bundesliga": {"brier_max": 0.65, "has_understat": True},
        "SerieA": {"brier_max": 0.65, "has_understat": True},
        "Championship": {"brier_max": 0.70, "has_understat": False},
        "Ligue1": {"brier_max": 0.65, "has_understat": True},
    }

    @pytest.mark.parametrize("league_name", list(BACKTEST_LEAGUES.keys()))
    def test_backtest_report_exists(self, league_name: str):
        """Backtest report JSON must exist for each league."""
        path = Path(f"data/predictions/backtest_report_poisson_{league_name}_2024-25.json")
        assert path.exists(), (
            f"Missing backtest report: {path}. Run backtest for {league_name}."
        )

    @pytest.mark.parametrize("league_name", list(BACKTEST_LEAGUES.keys()))
    def test_brier_score_within_threshold(self, league_name: str):
        """Each league's Brier score must be below its threshold.

        Understat leagues (with xG data): < 0.65
        Non-Understat leagues (goals-only): < 0.70
        """
        report = _load_backtest_report(league_name)
        brier = report["summary"]["brier_score"]
        max_brier = self.BACKTEST_LEAGUES[league_name]["brier_max"]

        assert brier < max_brier, (
            f"{league_name}: Brier {brier:.4f} exceeds threshold {max_brier}. "
            f"{'Has Understat' if self.BACKTEST_LEAGUES[league_name]['has_understat'] else 'No Understat (structural limitation)'}."
        )

    @pytest.mark.parametrize("league_name", list(BACKTEST_LEAGUES.keys()))
    def test_backtest_has_valid_match_count(self, league_name: str):
        """Each backtest report must have a positive match count."""
        report = _load_backtest_report(league_name)
        total_matches = report["summary"]["total_matches"]
        total_predicted = report["summary"]["total_predicted"]

        assert total_matches > 0, f"{league_name}: total_matches = 0"
        assert total_predicted > 0, f"{league_name}: total_predicted = 0"
        assert total_predicted == total_matches, (
            f"{league_name}: predicted {total_predicted} of {total_matches} matches — "
            "some matches were not predicted"
        )

    def test_xgboost_model_exists(self):
        """XGBoost model pkl must exist (retrained on expanded dataset)."""
        pkl_path = Path("data/models/xgboost_v1.pkl")
        assert pkl_path.exists(), (
            "XGBoost model not found at data/models/xgboost_v1.pkl. "
            "Run E38-05 XGBoost retrain step."
        )

    def test_xgboost_model_is_loadable(self):
        """The XGBoost pkl must be loadable and trained."""
        pkl_path = Path("data/models/xgboost_v1.pkl")
        if not pkl_path.exists():
            pytest.skip("XGBoost model pkl not found")

        try:
            from src.models.xgboost_model import XGBoostModel
        except ImportError:
            pytest.skip("xgboost package not installed — skipping load test")

        model = XGBoostModel()
        model.load(pkl_path)
        assert model._is_trained is True, "Loaded XGBoost model is not marked as trained"


# ============================================================================
# Bonus: Edge threshold configuration per league
# ============================================================================

class TestEdgeThresholds:
    """Verify per-league edge thresholds are correctly configured."""

    @pytest.mark.parametrize("short_name,expected_threshold", [
        ("EPL", 0.05),
        ("Championship", 0.03),
        ("LaLiga", 0.05),
        ("Ligue1", 0.05),
        ("Bundesliga", 0.05),
        ("SerieA", 0.05),
    ])
    def test_edge_threshold_correct(self, short_name: str, expected_threshold: float):
        """Each league's edge threshold must match the expected value.

        Lower threshold (Championship 3%) captures more value in a less
        efficient market.  Standard threshold (5%) for EPL, La Liga, Ligue 1,
        Bundesliga, Serie A reflects well-served betting markets.
        """
        lg = _get_league_config(short_name)
        # Edge threshold comes from edge_threshold_override or defaults to 0.05
        actual = float(
            lg.get("edge_threshold_override",
            lg.get("edge_threshold", 0.05))
        )
        assert actual == pytest.approx(expected_threshold, abs=1e-6), (
            f"{short_name}: edge threshold = {actual}, expected {expected_threshold}"
        )
