"""
BetVector — API-Football Scraper (Real-Time Data Sources)
==========================================================
Downloads real-time fixtures, results, odds, and injuries from API-Football
(api-sports.io).  This is our primary real-time data source, solving the
multi-day delay problem with Football-Data.co.uk's CSV updates.

API-Football provides:
  - **Fixtures:** All matches with status, scores, and half-time scores
  - **Odds:** Pre-match bookmaker odds from major bookmakers
  - **Injuries:** Active player injuries and suspensions

Auth: ``x-apisports-key`` header from ``API_FOOTBALL_KEY`` env var.
Free tier: 100 requests/day.  We budget ~20 requests across 3 daily runs.

Base URL: ``https://v3.football.api-sports.io``

Key endpoints:
  - ``GET /fixtures?league={id}&season={year}`` — all fixtures for a season
  - ``GET /odds?league={id}&season={year}&page={n}`` — odds (paginated)
  - ``GET /odds?fixture={id}`` — odds for a specific fixture
  - ``GET /injuries?league={id}&season={year}`` — active injuries

Master Plan refs: MP §5 Data Sources, MP §7 Scraper Interface
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.config import PROJECT_ROOT, config
from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DOMAIN = "v3.football.api-sports.io"

# Status mapping: API-Football status short codes → our database status values.
# API-Football has many fine-grained statuses; we simplify to 4 categories.
STATUS_MAP: Dict[str, str] = {
    # Finished — match is complete, goals are final
    "FT": "finished",     # Full Time (90 min)
    "AET": "finished",    # After Extra Time
    "PEN": "finished",    # After Penalties
    # Scheduled — match hasn't started yet
    "NS": "scheduled",    # Not Started
    "TBD": "scheduled",   # Time To Be Defined
    # In play — match is currently being played
    "1H": "in_play",      # First Half
    "HT": "in_play",      # Half Time
    "2H": "in_play",      # Second Half
    "ET": "in_play",      # Extra Time
    "BT": "in_play",      # Break Time (before ET)
    "P": "in_play",       # Penalty In Progress
    "SUSP": "in_play",    # Suspended (temporary)
    "INT": "in_play",     # Interrupted
    "LIVE": "in_play",    # In Progress (generic)
    # Postponed/cancelled — match won't happen as scheduled
    "PST": "postponed",   # Postponed
    "CANC": "postponed",  # Cancelled
    "ABD": "postponed",   # Abandoned
    "AWD": "postponed",   # Awarded (technical result)
    "WO": "postponed",    # Walkover
}

# Team name mapping: API-Football names → our canonical DB names.
# API-Football generally uses full official names, but some differ from
# what Football-Data.co.uk uses (which is our canonical source).
# Verified from actual API-Football responses for EPL.
API_FOOTBALL_EPL_TEAM_MAP: Dict[str, str] = {
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "AFC Bournemouth": "Bournemouth",
    "Brentford": "Brentford",
    "Brighton & Hove Albion": "Brighton",
    "Brighton": "Brighton",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Leeds United": "Leeds United",
    "Leeds": "Leeds United",
    "Leicester City": "Leicester",
    "Leicester": "Leicester",
    "Liverpool": "Liverpool",
    "Manchester City": "Manchester City",
    "Manchester United": "Manchester United",
    "Newcastle United": "Newcastle",
    "Newcastle": "Newcastle",
    "Nottingham Forest": "Nottingham Forest",
    "Sheffield United": "Sheffield United",
    "Sheffield Utd": "Sheffield United",
    "Southampton": "Southampton",
    "Sunderland": "Sunderland",
    "Tottenham Hotspur": "Tottenham",
    "Tottenham": "Tottenham",
    "Watford": "Watford",
    "West Bromwich Albion": "West Brom",
    "West Ham United": "West Ham",
    "West Ham": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
    "Wolverhampton": "Wolves",
    "Wolves": "Wolves",
    # Historical teams that might appear in older seasons
    "Norwich City": "Norwich",
    "Norwich": "Norwich",
    "Ipswich Town": "Ipswich",
    "Ipswich": "Ipswich",
    "Luton Town": "Luton",
    "Luton": "Luton",
}


# ============================================================================
# API-Football Scraper
# ============================================================================

class APIFootballScraper(BaseScraper):
    """Real-time data scraper using the API-Football v3 API.

    Provides fixtures/results, odds, and injuries.  Carefully manages the
    100 requests/day free-tier budget by reading the ``x-ratelimit-requests-remaining``
    header from every response.

    Environment variable: ``API_FOOTBALL_KEY`` (required).
    """

    def __init__(self) -> None:
        super().__init__()
        self._api_key: Optional[str] = os.environ.get("API_FOOTBALL_KEY")
        self._base_url: str = getattr(
            config.settings.scraping.api_football, "base_url",
            "https://v3.football.api-sports.io",
        )
        # Rate limit tracking — updated from response headers
        self._requests_remaining: Optional[int] = None
        self._warning_threshold: int = int(getattr(
            config.settings.scraping.api_football, "warning_threshold", 20,
        ))
        self._hard_stop_threshold: int = int(getattr(
            config.settings.scraping.api_football, "hard_stop_threshold", 5,
        ))

    @property
    def source_name(self) -> str:
        return "api_football"

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Fetch all fixtures for a league-season.

        Returns a DataFrame compatible with ``load_matches()``
        (columns: date, home_team, away_team, home_goals, away_goals,
        home_ht_goals, away_ht_goals) plus status column.
        """
        if not self._check_api_key():
            return pd.DataFrame()

        api_league_id = getattr(league_config, "api_football_id", None)
        if api_league_id is None:
            logger.warning("[api_football] No api_football_id configured for league")
            return pd.DataFrame()

        api_season = self._convert_season(season)
        league_name = getattr(league_config, "short_name", "unknown")

        logger.info(
            "[api_football] Fetching fixtures for league %s (API ID %d), season %s",
            league_name, api_league_id, api_season,
        )

        # Fetch fixtures — single request returns all matches for the season
        data = self._api_request(
            "/fixtures",
            params={"league": api_league_id, "season": api_season},
        )
        if data is None:
            return pd.DataFrame()

        fixtures = data.get("response", [])
        if not fixtures:
            logger.warning("[api_football] No fixtures returned for %s %s", league_name, season)
            return pd.DataFrame()

        # Archive raw JSON for reproducibility
        self._save_raw_json(fixtures, league_name, "fixtures", season)

        # Parse into DataFrame
        rows = []
        for fixture in fixtures:
            row = self._parse_fixture(fixture)
            if row:
                rows.append(row)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # Save raw CSV (BaseScraper pattern)
        self.save_raw(df, league_name, season)

        logger.info(
            "[api_football] Parsed %d fixtures (%d finished, %d scheduled) for %s %s",
            len(df),
            len(df[df["status"] == "finished"]),
            len(df[df["status"] == "scheduled"]),
            league_name, season,
        )

        return df

    def scrape_odds(
        self,
        league_config: object,
        season: str,
    ) -> List[Dict[str, Any]]:
        """Fetch pre-match odds for all fixtures in a league-season.

        Returns a list of dicts ready for ``load_odds_api_football()``:
        ``{date, home_team, away_team, bookmaker, market_type, selection, odds_decimal}``

        The odds endpoint is paginated — we fetch up to 5 pages to stay
        within the daily request budget.
        """
        if not self._check_api_key():
            return []

        api_league_id = getattr(league_config, "api_football_id", None)
        if api_league_id is None:
            return []

        api_season = self._convert_season(season)
        league_name = getattr(league_config, "short_name", "unknown")

        logger.info(
            "[api_football] Fetching odds for league %s, season %s",
            league_name, season,
        )

        all_odds: List[Dict[str, Any]] = []
        max_pages = 5  # Budget: ~5 requests for odds

        for page in range(1, max_pages + 1):
            # Check if we should stop to conserve requests
            if not self._check_budget(critical=False):
                logger.warning(
                    "[api_football] Stopping odds fetch at page %d to conserve budget",
                    page,
                )
                break

            data = self._api_request(
                "/odds",
                params={
                    "league": api_league_id,
                    "season": api_season,
                    "page": page,
                },
            )
            if data is None:
                break

            fixtures_odds = data.get("response", [])
            if not fixtures_odds:
                break

            # Parse odds from this page
            for fixture_odds in fixtures_odds:
                parsed = self._parse_fixture_odds(fixture_odds)
                all_odds.extend(parsed)

            # Check pagination — stop if we've reached the last page
            paging = data.get("paging", {})
            total_pages = paging.get("total", 1)
            if page >= total_pages:
                break

        # Archive raw odds
        if all_odds:
            self._save_raw_json(all_odds, league_name, "odds", season)

        logger.info(
            "[api_football] Parsed %d odds records for %s %s",
            len(all_odds), league_name, season,
        )

        return all_odds

    def scrape_odds_for_fixtures(
        self,
        fixture_ids: List[int],
    ) -> List[Dict[str, Any]]:
        """Fetch odds for specific fixtures (midday targeted refresh).

        Each fixture requires one API request, so this is used sparingly
        for upcoming matches that need fresh odds.

        Parameters
        ----------
        fixture_ids : list of int
            API-Football fixture IDs to fetch odds for.

        Returns
        -------
        list of dict
            Odds records ready for ``load_odds_api_football()``.
        """
        if not self._check_api_key():
            return []

        all_odds: List[Dict[str, Any]] = []

        for fid in fixture_ids:
            if not self._check_budget(critical=False):
                logger.warning(
                    "[api_football] Stopping targeted odds fetch to conserve budget"
                )
                break

            data = self._api_request("/odds", params={"fixture": fid})
            if data is None:
                continue

            for fixture_odds in data.get("response", []):
                parsed = self._parse_fixture_odds(fixture_odds)
                all_odds.extend(parsed)

        logger.info(
            "[api_football] Fetched odds for %d/%d targeted fixtures (%d records)",
            len(fixture_ids), len(fixture_ids), len(all_odds),
        )

        return all_odds

    def scrape_injuries(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Fetch active injuries and suspensions for a league-season.

        Returns a DataFrame with columns:
        ``team, player, type (injury/suspension), reason, status``

        This replaces the deprecated Apify Soccer Intelligence API.
        """
        if not self._check_api_key():
            return pd.DataFrame()

        api_league_id = getattr(league_config, "api_football_id", None)
        if api_league_id is None:
            return pd.DataFrame()

        api_season = self._convert_season(season)
        league_name = getattr(league_config, "short_name", "unknown")

        if not self._check_budget(critical=False):
            logger.warning("[api_football] Skipping injuries fetch to conserve budget")
            return pd.DataFrame()

        data = self._api_request(
            "/injuries",
            params={"league": api_league_id, "season": api_season},
        )
        if data is None:
            return pd.DataFrame()

        injuries = data.get("response", [])
        if not injuries:
            logger.info("[api_football] No injuries data for %s %s", league_name, season)
            return pd.DataFrame()

        # Archive raw JSON
        self._save_raw_json(injuries, league_name, "injuries", season)

        rows = []
        for injury in injuries:
            row = self._parse_injury(injury)
            if row:
                rows.append(row)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        logger.info(
            "[api_football] Parsed %d injury/suspension records for %s %s",
            len(df), league_name, season,
        )

        return df

    # -----------------------------------------------------------------------
    # API request layer
    # -----------------------------------------------------------------------

    def _api_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Make an authenticated API-Football request.

        Handles rate limit tracking, budget enforcement, and error handling.
        Returns the parsed JSON response, or None on failure.
        """
        # Budget check — hard stop if we're dangerously low
        if not self._check_budget(critical=True):
            return None

        url = f"{self._base_url}{endpoint}"
        headers = {
            "x-apisports-key": self._api_key,
        }

        try:
            response = self._request_with_retry(
                url, DOMAIN, headers=headers, params=params,
            )

            # Update rate limit tracking from response headers
            remaining = response.headers.get("x-ratelimit-requests-remaining")
            if remaining is not None:
                self._requests_remaining = int(remaining)
                if self._requests_remaining <= self._warning_threshold:
                    logger.warning(
                        "[api_football] Rate limit: %d requests remaining today",
                        self._requests_remaining,
                    )

            data = response.json()

            # Check for API-level errors
            errors = data.get("errors", {})
            if errors:
                # API-Football returns errors as a dict, not a list
                error_msgs = []
                if isinstance(errors, dict):
                    error_msgs = [f"{k}: {v}" for k, v in errors.items()]
                elif isinstance(errors, list):
                    error_msgs = [str(e) for e in errors]
                if error_msgs:
                    logger.error(
                        "[api_football] API errors: %s", "; ".join(error_msgs),
                    )
                    return None

            return data

        except ScraperError as e:
            logger.error("[api_football] Request failed: %s", e)
            return None
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("[api_football] Failed to parse JSON response: %s", e)
            return None
        except Exception as e:
            logger.error("[api_football] Unexpected error: %s", e)
            return None

    def _check_api_key(self) -> bool:
        """Verify API key is available."""
        if not self._api_key:
            logger.warning(
                "[api_football] No API_FOOTBALL_KEY env var set — skipping. "
                "Get a free key at https://www.api-football.com/"
            )
            return False
        return True

    def _check_budget(self, critical: bool = False) -> bool:
        """Check if we have enough API requests remaining.

        Parameters
        ----------
        critical : bool
            If True, only hard-stop at the hard_stop_threshold.
            If False, also stop at the warning threshold for non-critical requests.

        Returns
        -------
        bool
            True if we can proceed, False if we should stop.
        """
        if self._requests_remaining is None:
            return True  # Haven't made any requests yet, don't know the budget

        if self._requests_remaining <= self._hard_stop_threshold:
            logger.error(
                "[api_football] HARD STOP: Only %d requests remaining — "
                "preserving budget for critical operations",
                self._requests_remaining,
            )
            return False

        if not critical and self._requests_remaining <= self._warning_threshold:
            logger.warning(
                "[api_football] Budget warning: %d requests remaining — "
                "skipping non-critical request",
                self._requests_remaining,
            )
            return False

        return True

    # -----------------------------------------------------------------------
    # Parsing helpers
    # -----------------------------------------------------------------------

    def _parse_fixture(self, fixture: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a single fixture from the API response into a row dict.

        API-Football fixture structure::

            {
              "fixture": {"id": 123, "date": "2025-08-16T15:00:00+00:00", ...},
              "league": {...},
              "teams": {"home": {"id": 42, "name": "Arsenal"}, "away": {...}},
              "goals": {"home": 2, "away": 1},
              "score": {"halftime": {"home": 1, "away": 0}, ...}
            }
        """
        try:
            fixture_info = fixture.get("fixture", {})
            teams = fixture.get("teams", {})
            goals = fixture.get("goals", {})
            score = fixture.get("score", {})

            # Extract fixture ID for cross-referencing
            fixture_id = fixture_info.get("id")

            # Parse date — API returns ISO 8601 with timezone
            date_str = fixture_info.get("date", "")
            match_date = self._parse_date(date_str)
            if match_date is None:
                logger.warning(
                    "[api_football] Could not parse date '%s' for fixture %s",
                    date_str, fixture_id,
                )
                return None

            # Map team names to our canonical names
            home_api_name = teams.get("home", {}).get("name", "")
            away_api_name = teams.get("away", {}).get("name", "")
            home_api_id = teams.get("home", {}).get("id")
            away_api_id = teams.get("away", {}).get("id")

            home_name = self._map_team_name(home_api_name)
            away_name = self._map_team_name(away_api_name)

            # Map status
            status_short = fixture_info.get("status", {}).get("short", "NS")
            status = STATUS_MAP.get(status_short, "scheduled")

            # Goals (None if match hasn't been played yet)
            home_goals = goals.get("home")
            away_goals = goals.get("away")

            # Half-time scores
            halftime = score.get("halftime", {})
            home_ht_goals = halftime.get("home")
            away_ht_goals = halftime.get("away")

            return {
                "date": match_date,
                "home_team": home_name,
                "away_team": away_name,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "home_ht_goals": home_ht_goals,
                "away_ht_goals": away_ht_goals,
                "status": status,
                # Extra fields for internal use (not loaded by load_matches)
                "api_football_fixture_id": fixture_id,
                "home_api_football_id": home_api_id,
                "away_api_football_id": away_api_id,
                "home_api_football_name": home_api_name,
                "away_api_football_name": away_api_name,
            }

        except Exception as e:
            logger.warning("[api_football] Error parsing fixture: %s", e)
            return None

    def _parse_fixture_odds(
        self, fixture_odds: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Parse odds for a single fixture into a list of odds records.

        API-Football odds structure::

            {
              "fixture": {"id": 123, "date": "..."},
              "league": {...},
              "bookmakers": [
                {
                  "id": 1, "name": "Bet365",
                  "bets": [
                    {
                      "id": 1, "name": "Match Winner",
                      "values": [
                        {"value": "Home", "odd": "1.85"},
                        {"value": "Draw", "odd": "3.60"},
                        {"value": "Away", "odd": "4.50"}
                      ]
                    }
                  ]
                }
              ]
            }

        We extract 1X2 (Match Winner) and Over/Under 2.5 goals markets.
        """
        records: List[Dict[str, Any]] = []

        try:
            fixture_info = fixture_odds.get("fixture", {})
            date_str = fixture_info.get("date", "")
            match_date = self._parse_date(date_str)

            # We need the team names to match odds to the correct DB match
            # The odds endpoint doesn't always include team names directly,
            # so we store the fixture_id for lookup
            league_info = fixture_odds.get("league", {})

            bookmakers = fixture_odds.get("bookmakers", [])

            # Get bookmaker name mapping from config
            bookie_map = {}
            try:
                cfg_map = config.settings.scraping.api_football.bookmaker_map
                # ConfigNamespace stores the map — iterate its attributes
                if hasattr(cfg_map, '__dict__'):
                    for k, v in cfg_map.__dict__.items():
                        if not k.startswith('_'):
                            bookie_map[int(k)] = v
                elif isinstance(cfg_map, dict):
                    bookie_map = {int(k): v for k, v in cfg_map.items()}
            except (AttributeError, TypeError):
                pass

            for bookmaker in bookmakers:
                bookie_id = bookmaker.get("id", 0)
                bookie_name = bookie_map.get(
                    bookie_id, bookmaker.get("name", f"bookie_{bookie_id}"),
                )

                for bet in bookmaker.get("bets", []):
                    bet_name = bet.get("name", "").lower()

                    # 1X2 (Match Winner)
                    if "match winner" in bet_name or bet.get("id") == 1:
                        for val in bet.get("values", []):
                            selection = self._map_odds_selection(
                                val.get("value", ""), "1X2",
                            )
                            odds_decimal = self._safe_float(val.get("odd"))
                            if selection and odds_decimal and odds_decimal > 1.0:
                                records.append({
                                    "date": match_date,
                                    "fixture_id": fixture_info.get("id"),
                                    "bookmaker": bookie_name,
                                    "market_type": "1X2",
                                    "selection": selection,
                                    "odds_decimal": odds_decimal,
                                })

                    # Over/Under 2.5 Goals
                    elif "over/under" in bet_name or "goals" in bet_name:
                        for val in bet.get("values", []):
                            value_str = str(val.get("value", ""))
                            # Only care about the 2.5 line
                            if "2.5" in value_str:
                                if "over" in value_str.lower():
                                    selection = "over"
                                elif "under" in value_str.lower():
                                    selection = "under"
                                else:
                                    continue
                                odds_decimal = self._safe_float(val.get("odd"))
                                if odds_decimal and odds_decimal > 1.0:
                                    records.append({
                                        "date": match_date,
                                        "fixture_id": fixture_info.get("id"),
                                        "bookmaker": bookie_name,
                                        "market_type": "OU25",
                                        "selection": selection,
                                        "odds_decimal": odds_decimal,
                                    })

        except Exception as e:
            logger.warning("[api_football] Error parsing fixture odds: %s", e)

        return records

    def _parse_injury(self, injury: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a single injury record from the API response.

        API-Football injury structure::

            {
              "player": {"id": 123, "name": "Marcus Rashford", "type": "Missing Fixture"},
              "team": {"id": 33, "name": "Manchester United"},
              "fixture": {"id": 456, "date": "..."},
              "league": {...}
            }
        """
        try:
            player_info = injury.get("player", {})
            team_info = injury.get("team", {})

            team_api_name = team_info.get("name", "")
            team_name = self._map_team_name(team_api_name)

            return {
                "team": team_name,
                "team_api_id": team_info.get("id"),
                "player": player_info.get("name", "Unknown"),
                "player_api_id": player_info.get("id"),
                "type": player_info.get("type", "Unknown"),
                "reason": player_info.get("reason", "Unknown"),
            }

        except Exception as e:
            logger.warning("[api_football] Error parsing injury: %s", e)
            return None

    # -----------------------------------------------------------------------
    # Team name mapping
    # -----------------------------------------------------------------------

    def _map_team_name(self, api_name: str) -> str:
        """Map an API-Football team name to our canonical DB name.

        Uses the static mapping first, then falls back to fuzzy matching
        via difflib.  Logs unmapped names so they can be added to the map.
        """
        if not api_name:
            return api_name

        # Direct lookup
        canonical = API_FOOTBALL_EPL_TEAM_MAP.get(api_name)
        if canonical:
            return canonical

        # Fuzzy fallback — find the closest match from our map values
        all_canonical = list(set(API_FOOTBALL_EPL_TEAM_MAP.values()))
        matches = get_close_matches(api_name, all_canonical, n=1, cutoff=0.6)
        if matches:
            logger.info(
                "[api_football] Fuzzy matched '%s' → '%s' (not in static map)",
                api_name, matches[0],
            )
            return matches[0]

        # No match found — log a warning and return as-is
        logger.warning(
            "[api_football] UNMAPPED team name: '%s' — add to API_FOOTBALL_EPL_TEAM_MAP",
            api_name,
        )
        return api_name

    # -----------------------------------------------------------------------
    # Utility helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _convert_season(season: str) -> int:
        """Convert our season format to API-Football format.

        Our format: ``"2025-26"`` → API-Football uses the start year: ``2025``
        """
        return int(season.split("-")[0])

    @staticmethod
    def _parse_date(date_str: str) -> Optional[str]:
        """Parse ISO 8601 datetime to YYYY-MM-DD date string.

        API-Football returns dates like ``"2025-08-16T15:00:00+00:00"``.
        We only need the date portion for matching to our DB records.
        """
        if not date_str:
            return None
        try:
            # Handle both formats: with and without timezone
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            # Fallback: try just the first 10 characters
            if len(date_str) >= 10:
                return date_str[:10]
            return None

    @staticmethod
    def _map_odds_selection(value: str, market_type: str) -> Optional[str]:
        """Map API-Football odds selection names to our standard names.

        1X2 market: "Home" → "home", "Draw" → "draw", "Away" → "away"
        """
        value_lower = value.lower().strip()
        if market_type == "1X2":
            if value_lower in ("home", "1"):
                return "home"
            elif value_lower in ("draw", "x"):
                return "draw"
            elif value_lower in ("away", "2"):
                return "away"
        return None

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """Safely convert a value to float, returning None on failure."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _save_raw_json(
        self,
        data: Any,
        league_name: str,
        data_type: str,
        season: str,
    ) -> Path:
        """Save raw API response as JSON for reproducibility.

        Unlike BaseScraper.save_raw() which saves CSV, API-Football
        returns JSON so we archive that directly.
        """
        raw_dir = PROJECT_ROOT / "data" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        today = date.today().isoformat()
        filename = f"api_football_{league_name}_{data_type}_{season}_{today}.json"
        filepath = raw_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        logger.info(
            "[api_football] Saved raw JSON → %s (%d items)",
            filepath, len(data) if isinstance(data, list) else 1,
        )
        return filepath
