"""
BetVector — Understat Scraper (E14-01 + E15-02 Expansion)
==========================================================
Downloads match-level xG and advanced statistics from Understat via the
``understatapi`` Python package.  This replaces FBref as our primary xG
data source — FBref lost all Opta data in January 2026, while Understat
works reliably with no authentication.

Understat provides (all extracted since E15-02 expansion):
  - **xG / xGA:** Expected goals for and against each team per match
  - **NPxG / NPxGA:** Non-penalty expected goals — strips out penalty xG
    which is essentially random (~76% conversion regardless of team).
    NPxG is more predictive of future performance than raw xG.
  - **PPDA:** Passes Per Defensive Action (pressing intensity metric).
    Lower PPDA = team presses more aggressively (e.g. Liverpool ~8,
    Burnley ~18).  Stored as a coefficient (att / def ratio).
  - **Deep completions:** Passes that reach the area near the opponent's
    box.  Measures attacking penetration quality.
  - **Shots:** Goals scored + conceded (actual, not expected).

Data is fetched via two API calls per league-season:
  1. ``get_match_data()`` → fixture structure (date, home/away teams)
  2. ``get_team_data()`` → rich per-team per-match statistics

The match fixtures provide the pairing (who played whom), and the team
data provides the detailed stats.  They are merged by (team_name, date).

No API key needed — ``understatapi`` scrapes understat.com directly.
Coverage: EPL from 2014/15 onward (covers all our historical seasons).

Install: ``pip install understatapi``

Master Plan refs: MP §5 Data Sources, MP §7 Scraper Interface, MP §13.4
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.config import config
from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


# ============================================================================
# Team Name Mapping: Understat → Canonical DB Names
# ============================================================================
# Understat uses slightly different team names than our canonical names
# (which come from Football-Data.co.uk).  The canonical DB names are the
# FULL official names stored in the teams table.
#
# Verified against actual DB content — these map Understat's display names
# to our canonical team names as they exist in the database.

UNDERSTAT_EPL_TEAM_MAP: Dict[str, str] = {
    # --- Teams in the 2025-26 EPL season ---
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Bournemouth": "AFC Bournemouth",
    "Brentford": "Brentford",
    "Brighton": "Brighton & Hove Albion",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Leeds": "Leeds United",
    "Liverpool": "Liverpool",
    "Manchester City": "Manchester City",
    "Manchester United": "Manchester United",
    "Newcastle United": "Newcastle United",
    "Nottingham Forest": "Nottingham Forest",
    "Sunderland": "Sunderland",
    "Tottenham": "Tottenham Hotspur",
    "West Ham": "West Ham United",
    "Wolverhampton Wanderers": "Wolverhampton Wanderers",

    # --- Recent/historical teams ---
    "Leicester": "Leicester City",
    "Southampton": "Southampton",
    "Sheffield United": "Sheffield United",
    "Ipswich": "Ipswich Town",
    "Luton": "Luton Town",
    "Norwich": "Norwich City",
    "Watford": "Watford",
    "West Bromwich Albion": "West Bromwich Albion",
    "Huddersfield": "Huddersfield Town",
    "Cardiff": "Cardiff City",
}


# ============================================================================
# Understat Scraper
# ============================================================================

class UnderstatScraper(BaseScraper):
    """Advanced stats scraper using the understatapi Python package.

    Fetches match-level xG, NPxG, PPDA, deep completions, and shots from
    Understat.  Each match produces two MatchStat rows (home + away) with
    all available statistics.

    This data replaces FBref (lost all Opta data January 2026) and provides
    the richest free xG feature set available for the Poisson model.

    E15-02 expansion: switched from ``get_match_data()`` (basic xG only) to
    ``get_team_data()`` (full stats including NPxG, PPDA, deep completions).
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
        """Fetch match-level xG + advanced stats for a league-season.

        Uses two API calls:
          1. ``get_match_data()`` → fixture list (date, home/away teams, isResult)
          2. ``get_team_data()`` → per-team per-match stats (xG, NPxG, PPDA, deep)

        Returns a DataFrame with columns suitable for ``load_understat_stats()``:
          - date, home_team, away_team, is_result
          - home_xg, away_xg, home_xga, away_xga (expected goals)
          - home_npxg, away_npxg, home_npxga, away_npxga (non-penalty xG)
          - home_ppda, away_ppda (PPDA coefficient — pressing intensity)
          - home_ppda_allowed, away_ppda_allowed (opponent pressing faced)
          - home_deep, away_deep (deep completions)
          - home_deep_allowed, away_deep_allowed (deep completions conceded)
          - home_shots, away_shots (total shots — goals scored in Understat terms)

        Parameters
        ----------
        league_config : ConfigNamespace
            League config from ``config.get_active_leagues()``.
        season : str
            Season string, e.g. ``"2025-26"``.

        Returns
        -------
        pd.DataFrame
            Match-level stats, or empty DataFrame on failure.
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
            "[understat] Fetching xG + advanced stats for %s season %s "
            "(understat year: %d)",
            league_name, season, api_season,
        )

        try:
            from understatapi import UnderstatClient

            client = UnderstatClient()
            league_obj = client.league(league=understat_league)

            # --- API call 1: Match fixtures (who played whom) ---
            self.rate_limiter.wait("understat.com")
            match_data = league_obj.get_match_data(season=str(api_season))

            if not match_data:
                logger.warning(
                    "[understat] No match data returned for %s %s",
                    league_name, season,
                )
                return pd.DataFrame()

            # --- API call 2: Team-level per-match stats (rich data) ---
            self.rate_limiter.wait("understat.com")
            team_data = league_obj.get_team_data(season=str(api_season))

            if not team_data:
                logger.warning(
                    "[understat] No team data returned for %s %s — "
                    "falling back to basic xG only",
                    league_name, season,
                )
                # Fall back to basic xG parsing (E14-01 behavior)
                return self._parse_basic_matches(match_data, league_name, season)

        except ImportError:
            logger.warning(
                "[understat] understatapi not installed — "
                "run: pip install understatapi"
            )
            return pd.DataFrame()
        except Exception as e:
            logger.error("[understat] Failed to fetch data: %s", e)
            return pd.DataFrame()

        # --- Build team stats index for fast lookup ---
        # Key: (understat_team_name, date_str) → stats dict
        team_stats_index = self._build_team_stats_index(team_data)

        # --- Merge match fixtures with team stats ---
        rows: List[Dict[str, Any]] = []
        stats_found = 0
        stats_missing = 0

        for match in match_data:
            row = self._parse_match_with_stats(match, team_stats_index)
            if row is not None:
                rows.append(row)
                # Count whether we got rich stats or just basic xG
                if row.get("home_npxg") is not None:
                    stats_found += 1
                else:
                    stats_missing += 1

        if not rows:
            logger.warning(
                "[understat] No parseable matches for %s %s",
                league_name, season,
            )
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # Save raw data (CSV via BaseScraper pattern)
        self.save_raw(df, league_name, season)

        # Count finished matches
        finished = df[df["home_xg"].notna()]

        logger.info(
            "[understat] Parsed %d matches (%d with xG, %d with full stats) "
            "for %s %s",
            len(df), len(finished), stats_found, league_name, season,
        )

        return df

    # -----------------------------------------------------------------------
    # Team Stats Index
    # -----------------------------------------------------------------------

    def _build_team_stats_index(
        self, team_data: Dict[Any, Dict[str, Any]],
    ) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """Build a lookup index from team_data for fast match-stats merging.

        Maps ``(understat_team_name, date_string)`` → per-match stats dict.

        The ``get_team_data()`` API returns::

            {
              71: {
                "title": "Aston Villa",
                "id": 71,
                "history": [
                  {
                    "h_a": "h",
                    "xG": 0.32, "xGA": 1.40,
                    "npxG": 0.32, "npxGA": 1.40,
                    "ppda": {"att": 227, "def": 12},
                    "ppda_allowed": {"att": 146, "def": 24},
                    "deep": 2, "deep_allowed": 6,
                    "scored": 0, "missed": 0,
                    "date": "2025-08-16 11:30:00",
                    ...
                  },
                  ...
                ]
              },
              ...
            }
        """
        index: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for team_id, team_info in team_data.items():
            team_name = team_info.get("title", "")
            history = team_info.get("history", [])

            for entry in history:
                date_str = self._parse_date(str(entry.get("date", "")))
                if date_str and team_name:
                    index[(team_name, date_str)] = entry

        logger.debug(
            "[understat] Built team stats index: %d entries across %d teams",
            len(index), len(team_data),
        )
        return index

    # -----------------------------------------------------------------------
    # Match Parsing (with rich stats)
    # -----------------------------------------------------------------------

    def _parse_match_with_stats(
        self,
        match: Dict[str, Any],
        team_stats_index: Dict[Tuple[str, str], Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Parse a match fixture and merge with rich team stats.

        Parameters
        ----------
        match : dict
            A match from ``get_match_data()`` with basic structure:
            ``{id, isResult, datetime, h, a, xG, goals, forecast}``
        team_stats_index : dict
            Lookup table from ``_build_team_stats_index()``.

        Returns
        -------
        dict or None
            Combined match row with all available stats.
        """
        try:
            is_result = match.get("isResult", False)

            # Parse date
            date_str = match.get("datetime", "")
            match_date = self._parse_date(str(date_str))
            if match_date is None:
                return None

            # Get team names (Understat's display names)
            home_info = match.get("h", {})
            away_info = match.get("a", {})
            home_api_name = home_info.get("title", "")
            away_api_name = away_info.get("title", "")

            # Map to canonical DB names
            home_name = self._map_team_name(home_api_name)
            away_name = self._map_team_name(away_api_name)

            # --- Basic xG from match_data (always available for finished) ---
            xg_data = match.get("xG", {})
            home_xg = self._safe_float(xg_data.get("h")) if is_result else None
            away_xg = self._safe_float(xg_data.get("a")) if is_result else None

            # Start building the row with basic data
            row: Dict[str, Any] = {
                "date": match_date,
                "home_team": home_name,
                "away_team": away_name,
                "is_result": is_result,
                # xG from match_data (baseline, always available)
                "home_xg": home_xg,
                "away_xg": away_xg,
                "home_xga": away_xg,   # xGA = opponent's xG
                "away_xga": home_xg,
                # Advanced stats — filled from team_data if available
                "home_npxg": None,
                "away_npxg": None,
                "home_npxga": None,
                "away_npxga": None,
                "home_ppda": None,
                "away_ppda": None,
                "home_ppda_allowed": None,
                "away_ppda_allowed": None,
                "home_deep": None,
                "away_deep": None,
                "home_deep_allowed": None,
                "away_deep_allowed": None,
                "home_shots": None,
                "away_shots": None,
            }

            # --- Merge rich stats from team_data (E15-02) ---
            if is_result:
                home_stats = team_stats_index.get(
                    (home_api_name, match_date),
                )
                away_stats = team_stats_index.get(
                    (away_api_name, match_date),
                )

                if home_stats:
                    self._extract_team_stats(row, home_stats, "home")
                if away_stats:
                    self._extract_team_stats(row, away_stats, "away")

            return row

        except Exception as e:
            logger.warning("[understat] Error parsing match: %s", e)
            return None

    def _extract_team_stats(
        self,
        row: Dict[str, Any],
        stats: Dict[str, Any],
        prefix: str,
    ) -> None:
        """Extract rich stats from a team_data history entry into a match row.

        Parameters
        ----------
        row : dict
            The match row dict being built (modified in place).
        stats : dict
            One entry from a team's ``history`` array in ``get_team_data()``.
        prefix : str
            Either ``"home"`` or ``"away"`` — determines which columns to fill.
        """
        # NPxG — non-penalty expected goals (more predictive than raw xG)
        row[f"{prefix}_npxg"] = self._safe_float(stats.get("npxG"))
        row[f"{prefix}_npxga"] = self._safe_float(stats.get("npxGA"))

        # PPDA — Passes Per Defensive Action (pressing intensity)
        # Raw data: {"att": 227, "def": 12} → coefficient = att / def = 18.9
        # Lower coefficient = more pressing (fewer passes allowed per action)
        ppda_raw = stats.get("ppda", {})
        if isinstance(ppda_raw, dict):
            ppda_att = self._safe_float(ppda_raw.get("att"))
            ppda_def = self._safe_float(ppda_raw.get("def"))
            if ppda_att is not None and ppda_def is not None and ppda_def > 0:
                row[f"{prefix}_ppda"] = round(ppda_att / ppda_def, 2)

        ppda_allowed_raw = stats.get("ppda_allowed", {})
        if isinstance(ppda_allowed_raw, dict):
            pa_att = self._safe_float(ppda_allowed_raw.get("att"))
            pa_def = self._safe_float(ppda_allowed_raw.get("def"))
            if pa_att is not None and pa_def is not None and pa_def > 0:
                row[f"{prefix}_ppda_allowed"] = round(pa_att / pa_def, 2)

        # Deep completions — attacks into the area near the opponent's box
        row[f"{prefix}_deep"] = self._safe_int(stats.get("deep"))
        row[f"{prefix}_deep_allowed"] = self._safe_int(stats.get("deep_allowed"))

        # Shots — Understat's "scored" field is goals scored, not shots.
        # We extract goals scored/conceded as extra match-level validation.
        row[f"{prefix}_shots"] = self._safe_int(stats.get("scored"))

    # -----------------------------------------------------------------------
    # Fallback: Basic xG Parsing (E14-01 behavior)
    # -----------------------------------------------------------------------

    def _parse_basic_matches(
        self,
        match_data: List[Dict[str, Any]],
        league_name: str,
        season: str,
    ) -> pd.DataFrame:
        """Parse matches using only basic xG data (no team stats).

        This is the E14-01 fallback used when ``get_team_data()`` fails.
        Returns the same DataFrame structure but with advanced stat columns
        set to None.
        """
        rows = []
        for match in match_data:
            try:
                is_result = match.get("isResult", False)
                date_str = match.get("datetime", "")
                match_date = self._parse_date(str(date_str))
                if match_date is None:
                    continue

                home_info = match.get("h", {})
                away_info = match.get("a", {})

                xg_data = match.get("xG", {})
                home_xg = self._safe_float(xg_data.get("h")) if is_result else None
                away_xg = self._safe_float(xg_data.get("a")) if is_result else None

                rows.append({
                    "date": match_date,
                    "home_team": self._map_team_name(home_info.get("title", "")),
                    "away_team": self._map_team_name(away_info.get("title", "")),
                    "is_result": is_result,
                    "home_xg": home_xg,
                    "away_xg": away_xg,
                    "home_xga": away_xg,
                    "away_xga": home_xg,
                    # All advanced stats None in fallback mode
                    "home_npxg": None, "away_npxg": None,
                    "home_npxga": None, "away_npxga": None,
                    "home_ppda": None, "away_ppda": None,
                    "home_ppda_allowed": None, "away_ppda_allowed": None,
                    "home_deep": None, "away_deep": None,
                    "home_deep_allowed": None, "away_deep_allowed": None,
                    "home_shots": None, "away_shots": None,
                })
            except Exception as e:
                logger.warning("[understat] Error in basic parse: %s", e)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        self.save_raw(df, league_name, season)

        finished = df[df["home_xg"].notna()]
        logger.info(
            "[understat] Parsed %d matches (%d with xG, basic mode) for %s %s",
            len(df), len(finished), league_name, season,
        )
        return df

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

    @staticmethod
    def _safe_int(value) -> Optional[int]:
        """Safely convert a value to int."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
