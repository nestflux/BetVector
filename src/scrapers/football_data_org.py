"""
BetVector — Football-Data.org API Scraper (E15-01)
====================================================
Downloads match fixtures and results from the Football-Data.org v4 REST API.
This supplements our primary source (Football-Data.co.uk CSV files) by
providing **near-real-time** data — typically updated within minutes of
match completion, versus the 2–4 day lag on CSV updates.

This scraper does NOT replace Football-Data.co.uk.  It fills the freshness
gap between CSV updates so that the evening pipeline can resolve bets on
the same day matches are played.

API Details (v4):
  - Base URL: ``https://api.football-data.org/v4``
  - Auth: ``X-Auth-Token`` header with key from ``FOOTBALL_DATA_ORG_KEY`` env var
  - Endpoint: ``GET /v4/competitions/{code}/matches?season={year}``
  - Rate limit: 10 requests/minute (free tier) → 6-second minimum between calls
  - Returns all fixtures for a competition-season in a single response (~380 rows)

Coverage: Premier League (competition code "PL") is available on the free tier.
No daily request cap — only a per-minute rate limit.

Install: No extra packages needed — uses ``requests`` (already in requirements).

Master Plan refs: MP §5 Data Sources, MP §7 Scraper Interface, MP §13.4
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from difflib import get_close_matches
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import config
from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


# ============================================================================
# Team Name Mapping: Football-Data.org API → Canonical DB Names
# ============================================================================
# The Football-Data.org API uses official club names (often with "FC" suffix).
# Our canonical DB names come from Football-Data.co.uk (set during initial
# data load in E3-02).  This mapping bridges the two naming conventions.
#
# Canonical names verified against the actual ``teams`` table in the DB.
# If a new team appears (e.g., promoted side), a fuzzy fallback tries to
# match it, and a warning is logged so we can add the explicit mapping.

FOOTBALL_DATA_ORG_TEAM_MAP: Dict[str, str] = {
    # --- Current 2025-26 EPL squads ---
    "Arsenal FC": "Arsenal",
    "Aston Villa FC": "Aston Villa",
    "AFC Bournemouth": "AFC Bournemouth",
    "Brentford FC": "Brentford",
    "Brighton & Hove Albion FC": "Brighton & Hove Albion",
    "Burnley FC": "Burnley",
    "Chelsea FC": "Chelsea",
    "Crystal Palace FC": "Crystal Palace",
    "Everton FC": "Everton",
    "Fulham FC": "Fulham",
    "Liverpool FC": "Liverpool",
    "Manchester City FC": "Manchester City",
    "Manchester United FC": "Manchester United",
    "Newcastle United FC": "Newcastle United",
    "Nottingham Forest FC": "Nottingham Forest",
    "Southampton FC": "Southampton",
    "Sunderland AFC": "Sunderland",
    "Tottenham Hotspur FC": "Tottenham Hotspur",
    "West Ham United FC": "West Ham United",
    "Wolverhampton Wanderers FC": "Wolverhampton Wanderers",

    # --- Recently promoted/relegated (historical coverage) ---
    "Ipswich Town FC": "Ipswich Town",
    "Leeds United FC": "Leeds United",
    "Leicester City FC": "Leicester City",
    "Luton Town FC": "Luton Town",
    "Sheffield United FC": "Sheffield United",
    "Norwich City FC": "Norwich City",
    "Watford FC": "Watford",
    "West Bromwich Albion FC": "West Bromwich Albion",
    "Huddersfield Town AFC": "Huddersfield Town",
    "Cardiff City FC": "Cardiff City",
}


# ============================================================================
# API Status → DB Status Mapping
# ============================================================================
# Football-Data.org returns fine-grained match statuses.  We map them to
# the simpler set our database uses (see config/settings.yaml → enums →
# match_statuses).
#
# FINISHED   → "finished"  — match is complete with a final score
# SCHEDULED  → "scheduled" — fixture announced but no kick-off time
# TIMED      → "scheduled" — kick-off time confirmed, not yet started
# POSTPONED  → "postponed" — match delayed to a future date
# IN_PLAY    → skipped     — mid-match; our batch pipeline ignores these
# PAUSED     → skipped     — half-time; same reasoning as IN_PLAY
# CANCELLED  → skipped     — match won't be played
# SUSPENDED  → skipped     — match interrupted, may resume later
# AWARDED    → skipped     — result decided by governing body (rare)

STATUS_MAP: Dict[str, Optional[str]] = {
    "FINISHED": "finished",
    "SCHEDULED": "scheduled",
    "TIMED": "scheduled",
    "POSTPONED": "postponed",
    # Statuses below are skipped — return None
    "IN_PLAY": None,
    "PAUSED": None,
    "CANCELLED": None,
    "SUSPENDED": None,
    "AWARDED": None,
}


# ============================================================================
# Football-Data.org Scraper
# ============================================================================

class FootballDataOrgScraper(BaseScraper):
    """Near-real-time fixtures and results scraper via Football-Data.org API.

    Fetches all matches for a competition-season in a single API call.
    Returns a DataFrame compatible with:
      - ``load_matches()`` — for inserting new scheduled fixtures
      - ``update_match_results()`` — for updating scheduled → finished

    Output columns: ``date, home_team, away_team, home_goals, away_goals,
    home_ht_goals, away_ht_goals, status``

    This scraper requires the ``FOOTBALL_DATA_ORG_KEY`` environment variable
    to be set.  If the key is missing, the scraper logs a warning and returns
    an empty DataFrame — it never blocks the pipeline.
    """

    # Domain for rate limiting (per-domain, shared across instances)
    DOMAIN = "api.football-data.org"

    def __init__(self) -> None:
        super().__init__()

        # Override rate limit for Football-Data.org API
        # Free tier: 10 req/min → 6 second minimum between requests
        try:
            interval = float(
                getattr(config.settings.scraping.football_data_org,
                        "min_request_interval_seconds", 6)
            )
            self.rate_limiter._min_interval = interval
        except (AttributeError, TypeError):
            self.rate_limiter._min_interval = 6.0

        # API key from environment variable
        self._api_key: Optional[str] = os.environ.get("FOOTBALL_DATA_ORG_KEY")

        # Base URL and competition code from config
        try:
            self._base_url = str(
                getattr(config.settings.scraping.football_data_org,
                        "base_url", "https://api.football-data.org/v4")
            )
            self._competition_code = str(
                getattr(config.settings.scraping.football_data_org,
                        "competition_code", "PL")
            )
        except (AttributeError, TypeError):
            self._base_url = "https://api.football-data.org/v4"
            self._competition_code = "PL"

    @property
    def source_name(self) -> str:
        return "football_data_org"

    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Fetch all fixtures and results for a league-season.

        Makes a single API call to get every match in the competition-season.
        Returns both finished matches (with scores) and scheduled fixtures
        (with null scores).  The pipeline uses ``load_matches()`` for new
        fixtures and ``update_match_results()`` for freshly completed games.

        Parameters
        ----------
        league_config : ConfigNamespace
            League configuration from ``config.get_active_leagues()``.
        season : str
            Season string, e.g. ``"2025-26"``.

        Returns
        -------
        pd.DataFrame
            All parseable matches, or empty DataFrame on failure.
            Columns: date, home_team, away_team, home_goals, away_goals,
            home_ht_goals, away_ht_goals, status.
        """
        league_name = getattr(league_config, "short_name", "unknown")

        # --- Guard: API key required ---
        if not self._api_key:
            logger.warning(
                "[%s] FOOTBALL_DATA_ORG_KEY not set — skipping. "
                "Sign up at https://www.football-data.org/client/register",
                self.source_name,
            )
            return pd.DataFrame()

        # Convert season string to API year (e.g. "2025-26" → 2025)
        api_season = self._convert_season(season)

        # Build the API URL
        url = (
            f"{self._base_url}/competitions/{self._competition_code}"
            f"/matches?season={api_season}"
        )

        logger.info(
            "[%s] Fetching fixtures/results for %s season %s (API year: %d)",
            self.source_name, league_name, season, api_season,
        )

        try:
            # Make the authenticated API request
            # _request_with_retry handles rate limiting and retries
            response = self._request_with_retry(
                url=url,
                domain=self.DOMAIN,
                headers={
                    "X-Auth-Token": self._api_key,
                    "Accept": "application/json",
                },
            )

            data = response.json()

            # Log remaining rate limit quota if present in headers
            remaining = response.headers.get("X-Requests-Available-Minute")
            if remaining is not None:
                logger.info(
                    "[%s] API rate limit: %s requests remaining this minute",
                    self.source_name, remaining,
                )

        except ScraperError as e:
            logger.error("[%s] API request failed: %s", self.source_name, e)
            return pd.DataFrame()
        except Exception as e:
            logger.error(
                "[%s] Unexpected error fetching data: %s",
                self.source_name, e,
            )
            return pd.DataFrame()

        # --- Parse response ---
        matches_raw = data.get("matches", [])
        if not matches_raw:
            logger.warning(
                "[%s] No matches in API response for %s %s",
                self.source_name, league_name, season,
            )
            return pd.DataFrame()

        # Parse each match into a row dict
        rows: List[Dict[str, Any]] = []
        skipped = 0
        for match in matches_raw:
            row = self._parse_match(match)
            if row is not None:
                rows.append(row)
            else:
                skipped += 1

        if not rows:
            logger.warning(
                "[%s] No parseable matches for %s %s (skipped %d)",
                self.source_name, league_name, season, skipped,
            )
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # Save raw data for reproducibility (BaseScraper pattern)
        self.save_raw(df, league_name, season)

        # Log summary
        finished = len(df[df["status"] == "finished"])
        scheduled = len(df[df["status"] == "scheduled"])
        postponed = len(df[df["status"] == "postponed"])

        logger.info(
            "[%s] Parsed %d matches for %s %s: "
            "%d finished, %d scheduled, %d postponed (skipped %d in-play/other)",
            self.source_name, len(df), league_name, season,
            finished, scheduled, postponed, skipped,
        )

        return df

    # -----------------------------------------------------------------------
    # Match Parsing
    # -----------------------------------------------------------------------

    def _parse_match(self, match: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a single match from the Football-Data.org API response.

        API match structure (v4)::

            {
              "id": 416044,
              "utcDate": "2025-08-16T14:00:00Z",
              "status": "FINISHED",
              "matchday": 1,
              "homeTeam": {
                "id": 57,
                "name": "Arsenal FC",
                "shortName": "Arsenal",
                "tla": "ARS"
              },
              "awayTeam": {
                "id": 354,
                "name": "Crystal Palace FC",
                "shortName": "Crystal Palace",
                "tla": "CRY"
              },
              "score": {
                "winner": "HOME_TEAM",
                "fullTime": {"home": 2, "away": 0},
                "halfTime": {"home": 1, "away": 0}
              }
            }

        Returns None for matches with statuses we skip (IN_PLAY, etc.).
        """
        try:
            # Map API status to our DB status
            api_status = match.get("status", "")
            db_status = STATUS_MAP.get(api_status)

            if db_status is None:
                # Skip in-play, cancelled, suspended, awarded matches
                return None

            # Parse date and kickoff time from ISO 8601 UTC datetime
            # e.g. "2025-08-16T14:00:00Z" → date="2025-08-16", kickoff="14:00"
            utc_date = match.get("utcDate", "")
            match_date = self._parse_date(utc_date)
            kickoff_time = self._parse_kickoff_time(utc_date)
            if match_date is None:
                logger.warning(
                    "[%s] Could not parse date '%s' — skipping match",
                    self.source_name, utc_date,
                )
                return None

            # Map team names to canonical DB names
            home_info = match.get("homeTeam", {})
            away_info = match.get("awayTeam", {})
            home_api_name = home_info.get("name", "")
            away_api_name = away_info.get("name", "")

            home_name = self._map_team_name(home_api_name)
            away_name = self._map_team_name(away_api_name)

            # Extract scores (None for scheduled matches)
            score = match.get("score", {})
            full_time = score.get("fullTime", {}) or {}
            half_time = score.get("halfTime", {}) or {}

            # For finished matches, goals are integers; for scheduled, they're None
            home_goals = full_time.get("home")
            away_goals = full_time.get("away")
            home_ht_goals = half_time.get("home")
            away_ht_goals = half_time.get("away")

            return {
                "date": match_date,
                "kickoff_time": kickoff_time,
                "home_team": home_name,
                "away_team": away_name,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "home_ht_goals": home_ht_goals,
                "away_ht_goals": away_ht_goals,
                "status": db_status,
            }

        except Exception as e:
            logger.warning(
                "[%s] Error parsing match: %s", self.source_name, e,
            )
            return None

    # -----------------------------------------------------------------------
    # Team Name Mapping
    # -----------------------------------------------------------------------

    def _map_team_name(self, api_name: str) -> str:
        """Map a Football-Data.org team name to our canonical DB name.

        First tries the explicit mapping dict.  If no match, falls back to
        fuzzy matching against all known canonical names.  If even fuzzy
        matching fails, returns the raw API name and logs a warning so the
        mapping can be added manually.
        """
        if not api_name:
            return api_name

        # Direct lookup in the mapping dict
        canonical = FOOTBALL_DATA_ORG_TEAM_MAP.get(api_name)
        if canonical:
            return canonical

        # Fuzzy fallback — try to match against known canonical names
        all_canonical = list(set(FOOTBALL_DATA_ORG_TEAM_MAP.values()))
        matches = get_close_matches(api_name, all_canonical, n=1, cutoff=0.6)
        if matches:
            logger.info(
                "[%s] Fuzzy matched '%s' → '%s'",
                self.source_name, api_name, matches[0],
            )
            return matches[0]

        # No match found — log a warning for manual intervention
        logger.warning(
            "[%s] UNMAPPED team name: '%s' — add to FOOTBALL_DATA_ORG_TEAM_MAP",
            self.source_name, api_name,
        )
        return api_name

    # -----------------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------------

    @staticmethod
    def _convert_season(season: str) -> int:
        """Convert a BetVector season string to an API season year.

        Football-Data.org uses the start year of the season as the season
        identifier.  For example, the 2025-26 EPL season is ``season=2025``.

        ``"2025-26"`` → ``2025``
        ``"2024-25"`` → ``2024``
        """
        return int(season.split("-")[0])

    @staticmethod
    def _parse_date(utc_date: str) -> Optional[str]:
        """Parse an ISO 8601 UTC date string to ``YYYY-MM-DD``.

        The API returns dates like ``"2025-08-16T14:00:00Z"``.
        We store only the date portion for match-day matching.
        """
        if not utc_date:
            return None
        try:
            # Handle both "2025-08-16T14:00:00Z" and "2025-08-16" formats
            dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            # Fallback: try to extract the first 10 characters as YYYY-MM-DD
            if len(utc_date) >= 10:
                return utc_date[:10]
            return None

    @staticmethod
    def _parse_kickoff_time(utc_date: str) -> Optional[str]:
        """Extract kickoff time (``HH:MM``) from an ISO 8601 UTC datetime.

        The API returns timestamps like ``"2025-08-16T14:00:00Z"``
        from which we extract ``"14:00"`` as the kickoff time (UTC).
        Returns None if the timestamp doesn't contain a time component
        or if the time is midnight (which usually means "time not set").
        """
        if not utc_date or "T" not in utc_date:
            return None
        try:
            dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
            # Midnight usually means the API hasn't set the actual kickoff
            # time yet — the match isn't really at 00:00 UTC
            if dt.hour == 0 and dt.minute == 0:
                return None
            return dt.strftime("%H:%M")
        except (ValueError, AttributeError):
            return None
