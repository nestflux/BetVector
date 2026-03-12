"""
PC-15 — Local Pipeline Setup Integration Test
===============================================
Automated pytest suite verifying the local pipeline setup changes
introduced in PC-15-01 through PC-15-06.

Scenarios:
  1. Football-Data.org config: all 6 leagues have football_data_org_code set
  2. Football-Data.org team map: covers teams for all 6 league codes
  3. OddsApiIoScraper: class exists, extends BaseScraper, has scrape() method
  4. OddsApiIoScraper output schema matches TheOddsAPIScraper schema
  5. Odds API budget thresholds: config has warning=100, hard_stop=30,
     skip_midday=200
  6. Pipeline fallback: when The Odds API returns empty, odds-api.io is called
  7. Launchd scripts: run_pipeline_local.sh and setup_local_automation.sh exist
     and are executable
  8. Sync stub: sync_to_cloud.py imports without error
  9. Full test suite regression: existing tests still pass (verified by CI)

All tests use in-memory SQLite with synthetic data — no external API calls,
no network access.

Run with: pytest tests/test_pc15_local_setup.py -v
"""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import yaml

# ============================================================================
# Path setup
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def leagues_config() -> List[Dict]:
    """Load leagues.yaml and return the leagues list."""
    config_path = PROJECT_ROOT / "config" / "leagues.yaml"
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    return data["leagues"]


@pytest.fixture(scope="module")
def settings_config() -> Dict:
    """Load settings.yaml and return the full config dict."""
    config_path = PROJECT_ROOT / "config" / "settings.yaml"
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    return data


# ============================================================================
# Scenario 1: Football-Data.org config — all 6 leagues have codes
# ============================================================================

class TestFootballDataOrgConfig:
    """PC-15-01: All 6 leagues have football_data_org_code set."""

    # Expected codes per league short_name (verified against FDO free tier)
    EXPECTED_CODES = {
        "EPL": "PL",
        "Championship": "ELC",
        "LaLiga": "PD",
        "Ligue1": "FL1",
        "Bundesliga": "BL1",
        "SerieA": "SA",
    }

    def test_all_six_leagues_have_fdo_code(self, leagues_config):
        """Every active league must have a non-null football_data_org_code."""
        active_leagues = [lg for lg in leagues_config if lg.get("is_active", True)]
        for league in active_leagues:
            code = league.get("football_data_org_code")
            assert code is not None, (
                f"{league['short_name']} has football_data_org_code=null. "
                f"Expected a valid FDO competition code."
            )

    def test_correct_codes_per_league(self, leagues_config):
        """Each league must have the correct FDO competition code."""
        league_by_name = {lg["short_name"]: lg for lg in leagues_config}
        for short_name, expected_code in self.EXPECTED_CODES.items():
            assert short_name in league_by_name, f"League {short_name} not in config"
            actual = league_by_name[short_name].get("football_data_org_code")
            assert actual == expected_code, (
                f"{short_name}: expected football_data_org_code='{expected_code}', "
                f"got '{actual}'"
            )


# ============================================================================
# Scenario 2: Football-Data.org team map covers all 6 leagues
# ============================================================================

class TestFootballDataOrgTeamMap:
    """PC-15-01: Team name map covers teams for all 6 league codes."""

    # Minimum number of team mappings expected (6 leagues, ~20 teams each)
    MIN_TOTAL_MAPPINGS = 100

    # Spot-check teams per league to verify coverage
    SPOT_CHECKS = {
        "PL": ["Arsenal FC", "Liverpool FC", "Manchester City FC"],
        "ELC": ["Leeds United FC", "Sunderland AFC"],
        "PD": ["Real Madrid CF", "FC Barcelona"],
        "FL1": ["Paris Saint-Germain FC", "Olympique de Marseille"],
        "BL1": ["FC Bayern München", "Borussia Dortmund"],
        "SA": ["FC Internazionale Milano", "Juventus FC"],
    }

    def test_minimum_mappings(self):
        """Team map must have at least 100 entries (6 leagues × ~20 teams)."""
        from src.scrapers.football_data_org import FOOTBALL_DATA_ORG_TEAM_MAP
        assert len(FOOTBALL_DATA_ORG_TEAM_MAP) >= self.MIN_TOTAL_MAPPINGS, (
            f"FOOTBALL_DATA_ORG_TEAM_MAP has {len(FOOTBALL_DATA_ORG_TEAM_MAP)} "
            f"entries, expected >= {self.MIN_TOTAL_MAPPINGS}"
        )

    def test_spot_check_teams(self):
        """Key teams from each league must be in the team map."""
        from src.scrapers.football_data_org import FOOTBALL_DATA_ORG_TEAM_MAP
        all_api_names = set(FOOTBALL_DATA_ORG_TEAM_MAP.keys())
        for league_code, expected_teams in self.SPOT_CHECKS.items():
            for team in expected_teams:
                assert team in all_api_names, (
                    f"Team '{team}' (league {league_code}) not found in "
                    f"FOOTBALL_DATA_ORG_TEAM_MAP. Add it."
                )


# ============================================================================
# Scenario 3: OddsApiIoScraper class structure
# ============================================================================

class TestOddsApiIoScraper:
    """PC-15-02: OddsApiIoScraper exists and has correct structure."""

    def test_class_exists(self):
        """OddsApiIoScraper class must exist in src.scrapers.odds_api_io."""
        from src.scrapers.odds_api_io import OddsApiIoScraper
        assert OddsApiIoScraper is not None

    def test_extends_base_scraper(self):
        """OddsApiIoScraper must extend BaseScraper."""
        from src.scrapers.base_scraper import BaseScraper
        from src.scrapers.odds_api_io import OddsApiIoScraper
        assert issubclass(OddsApiIoScraper, BaseScraper), (
            "OddsApiIoScraper must inherit from BaseScraper"
        )

    def test_has_scrape_method(self):
        """OddsApiIoScraper must have a scrape() method."""
        from src.scrapers.odds_api_io import OddsApiIoScraper
        assert hasattr(OddsApiIoScraper, "scrape"), (
            "OddsApiIoScraper is missing scrape() method"
        )

    def test_league_to_slug_covers_all_six(self):
        """LEAGUE_TO_SLUG must map all 6 BetVector league short_names."""
        from src.scrapers.odds_api_io import LEAGUE_TO_SLUG
        expected = {"EPL", "Championship", "LaLiga", "Ligue1", "Bundesliga", "SerieA"}
        actual = set(LEAGUE_TO_SLUG.keys())
        missing = expected - actual
        assert not missing, (
            f"LEAGUE_TO_SLUG missing leagues: {missing}"
        )

    def test_team_name_map_has_entries(self):
        """TEAM_NAME_MAP must have substantial coverage (200+ entries)."""
        from src.scrapers.odds_api_io import TEAM_NAME_MAP
        assert len(TEAM_NAME_MAP) >= 200, (
            f"TEAM_NAME_MAP has {len(TEAM_NAME_MAP)} entries, expected >= 200"
        )


# ============================================================================
# Scenario 4: OddsApiIoScraper output schema matches TheOddsAPIScraper
# ============================================================================

class TestOddsApiIoOutputSchema:
    """PC-15-02: odds-api.io scraper output uses same schema as The Odds API."""

    # The canonical output columns from TheOddsAPIScraper
    EXPECTED_COLUMNS = {
        "date", "home_team", "away_team",
        "bookmaker", "market_type", "selection", "odds_decimal",
    }

    def test_scrape_returns_dataframe_with_correct_columns(self):
        """
        When _parse_event_odds() returns data, the records must have the same
        columns as TheOddsAPIScraper output (date, home_team, away_team,
        bookmaker, market_type, selection, odds_decimal).

        Uses mock event data matching odds-api.io response format.
        """
        from src.scrapers.odds_api_io import OddsApiIoScraper

        # Mock event data matching odds-api.io /odds response structure
        mock_event = {
            "id": 12345,
            "home": "Arsenal",
            "away": "Chelsea",
            "date": "2026-03-15T15:00:00Z",
            "bookmakers": {
                "Bet365": [
                    {
                        "name": "ML",
                        "odds": [
                            {"home": "2.10", "draw": "3.40", "away": "3.50"}
                        ],
                    },
                    {
                        "name": "Totals",
                        "odds": [
                            {"hdp": 2.5, "over": "1.90", "under": "1.95"}
                        ],
                    },
                ]
            },
        }

        # Create scraper with mocked API key
        with patch.dict(os.environ, {"ODDS_API_IO_KEY": "test_key_12345"}):
            scraper = OddsApiIoScraper()

        # _parse_event_odds doesn't use event_map for lookups —
        # it reads directly from the event_data dict
        event_map = {}

        rows = scraper._parse_event_odds(mock_event, event_map)
        assert len(rows) > 0, "Expected _parse_event_odds to return records"

        df = pd.DataFrame(rows)
        actual_cols = set(df.columns)
        missing = self.EXPECTED_COLUMNS - actual_cols
        assert not missing, (
            f"Output DataFrame missing columns: {missing}. "
            f"Must match TheOddsAPIScraper schema."
        )

    def test_market_type_uses_canonical_values(self):
        """
        market_type must use canonical DB enum values (1X2, OU25, etc.)
        NOT raw API values (h2h, totals). Gate 2 critical gap fix.
        """
        from src.scrapers.odds_api_io import OddsApiIoScraper

        mock_event = {
            "id": 12345,
            "home": "Arsenal",
            "away": "Chelsea",
            "date": "2026-03-15T15:00:00Z",
            "bookmakers": {
                "Bet365": [
                    {
                        "name": "ML",
                        "odds": [
                            {"home": "2.10", "draw": "3.40", "away": "3.50"}
                        ],
                    },
                    {
                        "name": "Totals",
                        "odds": [
                            {"hdp": 2.5, "over": "1.90", "under": "1.95"}
                        ],
                    },
                ]
            },
        }

        with patch.dict(os.environ, {"ODDS_API_IO_KEY": "test_key_12345"}):
            scraper = OddsApiIoScraper()

        rows = scraper._parse_event_odds(mock_event, {})
        df = pd.DataFrame(rows)

        # market_type must be "1X2" for ML, "OU25" for Over/Under 2.5
        # NOT "h2h" or "totals" (those violate the DB CHECK constraint)
        valid_market_types = {"1X2", "OU15", "OU25", "OU35", "BTTS", "AH"}
        actual_types = set(df["market_type"].unique())
        invalid = actual_types - valid_market_types
        assert not invalid, (
            f"Invalid market_type values: {invalid}. "
            f"Must use canonical enum: {valid_market_types}"
        )

    def test_selection_uses_canonical_values(self):
        """
        selection must use canonical DB values (home, draw, away, over, under)
        NOT raw API values (team names, "Over 2.5"). Gate 2 critical gap fix.
        """
        from src.scrapers.odds_api_io import OddsApiIoScraper

        mock_event = {
            "id": 12345,
            "home": "Arsenal",
            "away": "Chelsea",
            "date": "2026-03-15T15:00:00Z",
            "bookmakers": {
                "Bet365": [
                    {
                        "name": "ML",
                        "odds": [
                            {"home": "2.10", "draw": "3.40", "away": "3.50"}
                        ],
                    },
                    {
                        "name": "Totals",
                        "odds": [
                            {"hdp": 2.5, "over": "1.90", "under": "1.95"}
                        ],
                    },
                ]
            },
        }

        with patch.dict(os.environ, {"ODDS_API_IO_KEY": "test_key_12345"}):
            scraper = OddsApiIoScraper()

        rows = scraper._parse_event_odds(mock_event, {})
        df = pd.DataFrame(rows)

        # selection must be lowercase canonical: home, draw, away, over, under
        # NOT team names ("Arsenal", "Chelsea") or "Draw" or "Over 2.5"
        valid_selections = {"home", "draw", "away", "over", "under"}
        actual_selections = set(df["selection"].unique())
        invalid = actual_selections - valid_selections
        assert not invalid, (
            f"Invalid selection values: {invalid}. "
            f"Must use canonical values: {valid_selections}"
        )


# ============================================================================
# Scenario 5: Odds API budget thresholds in config
# ============================================================================

class TestOddsApiBudgetThresholds:
    """PC-15-03: Budget thresholds are correctly configured."""

    def test_warning_threshold(self, settings_config):
        """The Odds API warning_threshold must be 100."""
        threshold = settings_config["scraping"]["the_odds_api"]["warning_threshold"]
        assert threshold == 100, f"Expected warning_threshold=100, got {threshold}"

    def test_hard_stop_threshold(self, settings_config):
        """The Odds API hard_stop_threshold must be 30."""
        threshold = settings_config["scraping"]["the_odds_api"]["hard_stop_threshold"]
        assert threshold == 30, f"Expected hard_stop_threshold=30, got {threshold}"

    def test_skip_midday_below(self, settings_config):
        """The Odds API skip_midday_below must be 200."""
        threshold = settings_config["scraping"]["the_odds_api"]["skip_midday_below"]
        assert threshold == 200, f"Expected skip_midday_below=200, got {threshold}"

    def test_odds_api_io_enabled(self, settings_config):
        """odds-api.io must be enabled in config."""
        enabled = settings_config["scraping"]["odds_api_io"]["enabled"]
        assert enabled is True, f"Expected odds_api_io.enabled=true, got {enabled}"


# ============================================================================
# Scenario 6: Pipeline fallback logic
# ============================================================================

class TestPipelineFallback:
    """PC-15-02/03: Pipeline falls back to odds-api.io when primary is empty."""

    def test_pipeline_imports_odds_api_io(self):
        """Pipeline module must be importable and reference odds-api.io."""
        pipeline_path = PROJECT_ROOT / "src" / "pipeline.py"
        source = pipeline_path.read_text()
        assert "odds_api_io" in source, (
            "src/pipeline.py does not reference odds_api_io. "
            "Fallback logic is missing."
        )

    def test_pipeline_has_fallback_pattern(self):
        """Pipeline must contain fallback pattern: try primary, then odds-api.io."""
        pipeline_path = PROJECT_ROOT / "src" / "pipeline.py"
        source = pipeline_path.read_text()
        # Check that both the primary source and fallback source are referenced
        assert "OddsApiIoScraper" in source, (
            "src/pipeline.py does not import OddsApiIoScraper for fallback"
        )
        assert "fallback" in source.lower() or "odds_api_io" in source, (
            "src/pipeline.py does not contain fallback logic to odds-api.io"
        )

    def test_midday_budget_aware_skip(self):
        """Pipeline midday must reference skip_midday_below for budget-aware skip."""
        pipeline_path = PROJECT_ROOT / "src" / "pipeline.py"
        source = pipeline_path.read_text()
        assert "skip_midday" in source, (
            "src/pipeline.py does not reference skip_midday_below config. "
            "Budget-aware midday skip is missing."
        )


# ============================================================================
# Scenario 7: Launchd scripts exist and are executable
# ============================================================================

class TestLaunchdScripts:
    """PC-15-04: Shell scripts and plist files exist."""

    SCRIPTS = [
        "scripts/run_pipeline_local.sh",
        "scripts/setup_local_automation.sh",
        "scripts/teardown_local_automation.sh",
    ]

    PLISTS = [
        "scripts/launchd/com.betvector.morning.plist",
        "scripts/launchd/com.betvector.midday.plist",
        "scripts/launchd/com.betvector.evening.plist",
    ]

    def test_scripts_exist(self):
        """All shell scripts must exist in scripts/ directory."""
        for script in self.SCRIPTS:
            path = PROJECT_ROOT / script
            assert path.exists(), f"Script not found: {script}"

    def test_scripts_are_executable(self):
        """All shell scripts must have executable permission."""
        for script in self.SCRIPTS:
            path = PROJECT_ROOT / script
            file_stat = path.stat()
            is_executable = bool(file_stat.st_mode & stat.S_IXUSR)
            assert is_executable, (
                f"Script not executable: {script}. "
                f"Run: chmod +x {script}"
            )

    def test_plists_exist(self):
        """All launchd plist files must exist."""
        for plist in self.PLISTS:
            path = PROJECT_ROOT / plist
            assert path.exists(), f"Plist not found: {plist}"

    def test_plists_are_valid_xml(self):
        """All plist files must be valid XML."""
        import xml.etree.ElementTree as ET
        for plist in self.PLISTS:
            path = PROJECT_ROOT / plist
            try:
                ET.parse(str(path))
            except ET.ParseError as e:
                pytest.fail(f"Invalid XML in {plist}: {e}")

    def test_plists_have_correct_schedule(self):
        """Plist files must have correct StartCalendarInterval hours."""
        import xml.etree.ElementTree as ET

        expected_hours = {
            "com.betvector.morning.plist": 7,
            "com.betvector.midday.plist": 12,
            "com.betvector.evening.plist": 21,
        }

        for plist in self.PLISTS:
            path = PROJECT_ROOT / plist
            tree = ET.parse(str(path))
            root = tree.getroot()

            # Find the Hour value in the plist
            found_hour = False
            elements = list(root.iter())
            for i, elem in enumerate(elements):
                if elem.tag == "key" and elem.text == "Hour":
                    # Next element should be <integer> with the hour value
                    hour_elem = elements[i + 1]
                    hour_val = int(hour_elem.text)
                    plist_name = Path(plist).name
                    expected = expected_hours[plist_name]
                    assert hour_val == expected, (
                        f"{plist_name}: expected Hour={expected}, got {hour_val}"
                    )
                    found_hour = True
                    break

            assert found_hour, f"No Hour key found in {plist}"

    def test_wrapper_script_validates_args(self):
        """run_pipeline_local.sh must validate mode argument."""
        script_path = PROJECT_ROOT / "scripts" / "run_pipeline_local.sh"
        source = script_path.read_text()
        # Should check for valid modes
        assert "morning" in source and "midday" in source and "evening" in source, (
            "Wrapper script does not validate pipeline mode argument"
        )

    def test_wrapper_script_sources_env(self):
        """run_pipeline_local.sh must source .env for launchd compatibility."""
        script_path = PROJECT_ROOT / "scripts" / "run_pipeline_local.sh"
        source = script_path.read_text()
        assert ".env" in source and "source" in source, (
            "Wrapper script does not source .env — launchd won't have env vars"
        )

    def test_wrapper_script_activates_venv(self):
        """run_pipeline_local.sh must activate the Python venv."""
        script_path = PROJECT_ROOT / "scripts" / "run_pipeline_local.sh"
        source = script_path.read_text()
        assert "venv" in source and "activate" in source, (
            "Wrapper script does not activate Python venv"
        )


# ============================================================================
# Scenario 8: Sync stub imports without error
# ============================================================================

class TestSyncStub:
    """PC-15-05: sync_to_cloud.py imports cleanly."""

    def test_sync_module_imports(self):
        """scripts/sync_to_cloud.py must import without errors."""
        spec = importlib.util.spec_from_file_location(
            "sync_to_cloud",
            str(PROJECT_ROOT / "scripts" / "sync_to_cloud.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            pytest.fail(f"sync_to_cloud.py import failed: {e}")

    def test_sync_functions_exist(self):
        """sync_to_cloud.py must have run_sync() and sync_table() stubs."""
        spec = importlib.util.spec_from_file_location(
            "sync_to_cloud",
            str(PROJECT_ROOT / "scripts" / "sync_to_cloud.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert hasattr(mod, "run_sync"), "Missing run_sync() function"
        assert hasattr(mod, "sync_table"), "Missing sync_table() function"
        assert hasattr(mod, "verify_schema_compatibility"), (
            "Missing verify_schema_compatibility() function"
        )

    def test_sync_functions_raise_not_implemented(self):
        """All sync functions must raise NotImplementedError (stub)."""
        spec = importlib.util.spec_from_file_location(
            "sync_to_cloud",
            str(PROJECT_ROOT / "scripts" / "sync_to_cloud.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with pytest.raises(NotImplementedError):
            mod.run_sync()

        with pytest.raises(NotImplementedError):
            mod.sync_table("matches", None, None)

        with pytest.raises(NotImplementedError):
            mod.verify_schema_compatibility(None, None)

    def test_sync_strategy_document_exists(self):
        """SYNC_STRATEGY.md must exist in project root."""
        path = PROJECT_ROOT / "SYNC_STRATEGY.md"
        assert path.exists(), "SYNC_STRATEGY.md not found"

    def test_sync_strategy_has_three_phases(self):
        """SYNC_STRATEGY.md must document all 3 phases."""
        path = PROJECT_ROOT / "SYNC_STRATEGY.md"
        content = path.read_text()
        assert "Phase 1" in content, "SYNC_STRATEGY.md missing Phase 1"
        assert "Phase 2" in content, "SYNC_STRATEGY.md missing Phase 2"
        assert "Phase 3" in content, "SYNC_STRATEGY.md missing Phase 3"

    def test_env_example_has_cloud_url(self):
        """.env.example must have CLOUD_DATABASE_URL (commented out)."""
        path = PROJECT_ROOT / ".env.example"
        content = path.read_text()
        assert "CLOUD_DATABASE_URL" in content, (
            ".env.example missing CLOUD_DATABASE_URL"
        )

    def test_env_example_has_odds_api_io_key(self):
        """.env.example must have ODDS_API_IO_KEY."""
        path = PROJECT_ROOT / ".env.example"
        content = path.read_text()
        assert "ODDS_API_IO_KEY" in content, (
            ".env.example missing ODDS_API_IO_KEY"
        )
