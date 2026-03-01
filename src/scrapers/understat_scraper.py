"""
BetVector — Understat Scraper (Real-Time Data Sources)
=======================================================
Downloads match-level xG (expected goals) data from Understat via the
``understatapi`` Python package.  This replaces FBref as our primary xG
data source — FBref is blocked by Cloudflare, while Understat works
reliably with no authentication.

Understat provides:
  - **Match-level xG/xGA:** Expected goals for each team per match
  - **npxG:** Non-penalty expected goals (more predictive than raw xG)
  - **Shots & deep completions:** Shot counts and deep (within box) completions
  - **PPDA:** Passes allowed Per Defensive Action (pressing intensity metric)

No API key needed — ``understatapi`` scrapes understat.com directly.
Coverage: EPL from 2014/15 onward (covers all our historical seasons).

Install: ``pip install understatapi``

Master Plan refs: MP §5 Data Sources, MP §7 Scraper Interface
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from difflib import get_close_matches
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import config
from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


# ============================================================================
# Team Name Mapping: Understat → Canonical DB Names
# ============================================================================
# Understat uses slightly different team names than our canonical names
# (which come from Football-Data.co.uk).  Map them here.

UNDERSTAT_EPL_TEAM_MAP: Dict[str, str] = {
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Bournemouth": "Bournemouth",
    "Brentford": "Brentford",
    "Brighton": "Brighton",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Leeds": "Leeds United",
    "Leicester": "Leicester",
    "Liverpool": "Liverpool",
    "Manchester City": "Manchester City",
    "Manchester United": "Manchester United",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nottingham Forest",
    "Sheffield United": "Sheffield United",
    "Southampton": "Southampton",
    "Sunderland": "Sunderland",
    "Tottenham": "Tottenham",
    "Watford": "Watford",
    "West Bromwich Albion": "West Brom",
    "West Ham": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
    # Historical teams from older seasons
    "Norwich": "Norwich",
    "Huddersfield": "Huddersfield",
    "Cardiff": "Cardiff",
    "Ipswich": "Ipswich",
    "Luton": "Luton",
}


# ============================================================================
# Understat Scraper
# ============================================================================

class UnderstatScraper(BaseScraper):
    """xG data scraper using the understatapi Python package.

    Fetches match-level expected goals data from Understat.  Each match
    produces two MatchStat rows (home + away) with xG, xGA, and shots.

    This data replaces FBref (blocked by Cloudflare) and gives us real
    xG features for the Poisson model's feature matrix.
    """

    def __init__(self) -> None:
        super().__init__()
        # Override rate limit interval for Understat (be extra polite)
        try:
            interval = float(
                getattr(config.settings.scraping.understat,
                        "min_request_interval_seconds", 3)
            )
            self.rate_limiter._min_interval = interval
        except (AttributeError, TypeError):
            self.rate_limiter._min_interval = 3.0

    @property
    def source_name(self) -> str:
        return "understat"

    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Fetch match-level xG data for a league-season from Understat.

        Returns a DataFrame with columns suitable for ``load_understat_stats()``:
          - date, home_team, away_team
          - home_xg, away_xg (expected goals)
          - home_xga, away_xga (xG against — same data, opposite perspective)
          - home_shots, away_shots
          - home_deep, away_deep (completions inside the box)
          - home_ppda, away_ppda (PPDA pressing metric)

        Parameters
        ----------
        league_config : ConfigNamespace
            League config from ``config.get_active_leagues()``.
        season : str
            Season string, e.g. ``"2025-26"``.

        Returns
        -------
        pd.DataFrame
            Match-level xG data, or empty DataFrame on failure.
        """
        league_name = getattr(league_config, "short_name", "unknown")
        understat_league = getattr(league_config, "understat_league", None)

        if understat_league is None:
            logger.warning(
                "[understat] No understat_league configured for %s — skipping",
                league_name,
            )
            return pd.DataFrame()

        # understatapi uses start year (e.g. "2025-26" → 2025)
        api_season = self._convert_season(season)

        logger.info(
            "[understat] Fetching xG data for %s season %s (understat year: %d)",
            league_name, season, api_season,
        )

        try:
            from understatapi import UnderstatClient

            client = UnderstatClient()

            # Rate limit before making the request
            self.rate_limiter.wait("understat.com")

            # Get all match results with xG data for the league-season
            # understatapi returns a list of match dicts
            matches_data = client.league(league=understat_league).get_match_data(
                season=str(api_season),
            )

            if not matches_data:
                logger.warning(
                    "[understat] No data returned for %s %s", league_name, season,
                )
                return pd.DataFrame()

        except ImportError:
            logger.warning(
                "[understat] understatapi not installed — run: pip install understatapi"
            )
            return pd.DataFrame()
        except Exception as e:
            logger.error("[understat] Failed to fetch data: %s", e)
            return pd.DataFrame()

        # Parse match data into rows
        rows = []
        for match in matches_data:
            row = self._parse_match(match)
            if row:
                rows.append(row)

        if not rows:
            logger.warning("[understat] No parseable matches for %s %s", league_name, season)
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # Save raw data (CSV via BaseScraper pattern)
        self.save_raw(df, league_name, season)

        # Count only finished matches (those with xG data)
        finished = df[df["home_xg"].notna()]

        logger.info(
            "[understat] Parsed %d matches (%d with xG data) for %s %s",
            len(df), len(finished), league_name, season,
        )

        return df

    # -----------------------------------------------------------------------
    # Parsing
    # -----------------------------------------------------------------------

    def _parse_match(self, match: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a single match from understatapi response.

        understatapi match structure::

            {
              "id": "12345",
              "isResult": True,
              "datetime": "2025-08-16 15:00:00",
              "h": {"title": "Arsenal", "short_title": "ARS", "id": "1"},
              "a": {"title": "Crystal Palace", "short_title": "CRY", "id": "2"},
              "xG": {"h": "1.45", "a": "0.82"},
              "goals": {"h": "2", "a": "1"},
              "forecast": {"w": "0.55", "d": "0.25", "l": "0.20"}
            }
        """
        try:
            # Only process finished matches (those with results and xG)
            is_result = match.get("isResult", False)

            # Parse date
            date_str = match.get("datetime", "")
            match_date = self._parse_date(date_str)
            if match_date is None:
                return None

            # Map team names
            home_info = match.get("h", {})
            away_info = match.get("a", {})
            home_api_name = home_info.get("title", "")
            away_api_name = away_info.get("title", "")

            home_name = self._map_team_name(home_api_name)
            away_name = self._map_team_name(away_api_name)

            # xG data — only available for finished matches
            xg_data = match.get("xG", {})
            home_xg = self._safe_float(xg_data.get("h")) if is_result else None
            away_xg = self._safe_float(xg_data.get("a")) if is_result else None

            return {
                "date": match_date,
                "home_team": home_name,
                "away_team": away_name,
                "is_result": is_result,
                # xG: expected goals for each team
                "home_xg": home_xg,
                "away_xg": away_xg,
                # xGA: expected goals against = the opponent's xG
                "home_xga": away_xg,
                "away_xga": home_xg,
            }

        except Exception as e:
            logger.warning("[understat] Error parsing match: %s", e)
            return None

    # -----------------------------------------------------------------------
    # Team name mapping
    # -----------------------------------------------------------------------

    def _map_team_name(self, api_name: str) -> str:
        """Map an Understat team name to our canonical DB name."""
        if not api_name:
            return api_name

        # Direct lookup
        canonical = UNDERSTAT_EPL_TEAM_MAP.get(api_name)
        if canonical:
            return canonical

        # Fuzzy fallback
        all_canonical = list(set(UNDERSTAT_EPL_TEAM_MAP.values()))
        matches = get_close_matches(api_name, all_canonical, n=1, cutoff=0.6)
        if matches:
            logger.info(
                "[understat] Fuzzy matched '%s' → '%s'", api_name, matches[0],
            )
            return matches[0]

        logger.warning(
            "[understat] UNMAPPED team name: '%s' — add to UNDERSTAT_EPL_TEAM_MAP",
            api_name,
        )
        return api_name

    # -----------------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------------

    @staticmethod
    def _convert_season(season: str) -> int:
        """Convert ``"2025-26"`` → ``2025``."""
        return int(season.split("-")[0])

    @staticmethod
    def _parse_date(date_str: str) -> Optional[str]:
        """Parse Understat datetime to ``YYYY-MM-DD``."""
        if not date_str:
            return None
        try:
            dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            if len(date_str) >= 10:
                return date_str[:10]
            return None

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """Safely convert a value to float."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
