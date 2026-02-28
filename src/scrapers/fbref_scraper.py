"""
BetVector — FBref Scraper (E3-03)
==================================
Downloads per-match team statistics from FBref.com using the ``soccerdata``
Python library.  FBref is the primary source for advanced stats like
xG (expected goals), shots, possession, and passing data.

soccerdata handles FBref's internal rate limiting and caching automatically.
Results are cached to ``~/soccerdata/data/FBref/`` by default, so repeated
scrapes of the same season won't re-download.

**Important:** FBref uses Cloudflare protection that may block programmatic
access.  If FBref is unreachable (403/connection error), the scraper logs
a warning and returns an empty DataFrame instead of crashing.  The pipeline
continues without FBref data — predictions can still be made using
Football-Data.co.uk results and odds alone (just without xG features).

Columns returned (per-match, per-team):
  ``date, team, opponent, is_home, xg, xga, shots, shots_on_target,
  possession, passes_completed, passes_attempted``

Master Plan refs: MP §5 Data Sources, MP §7 Scraper Interface
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd

from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


# ============================================================================
# FBref Team Name Normalisation
# ============================================================================
# FBref uses its own team naming convention (usually full official names).
# We map them to the same canonical names used by the Football-Data scraper
# so all sources share a single namespace in the database.
#
# This mapping covers EPL teams from 2020-21 through 2024-25 seasons.

FBREF_EPL_TEAM_MAP: Dict[str, str] = {
    # FBref name → Canonical name
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Bournemouth": "AFC Bournemouth",
    "AFC Bournemouth": "AFC Bournemouth",
    "Brentford": "Brentford",
    "Brighton": "Brighton & Hove Albion",
    "Brighton and Hove Albion": "Brighton & Hove Albion",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Ipswich Town": "Ipswich Town",
    "Leeds United": "Leeds United",
    "Leicester City": "Leicester City",
    "Liverpool": "Liverpool",
    "Luton Town": "Luton Town",
    "Manchester City": "Manchester City",
    "Manchester Utd": "Manchester United",
    "Manchester United": "Manchester United",
    "Newcastle Utd": "Newcastle United",
    "Newcastle United": "Newcastle United",
    "Nott'ham Forest": "Nottingham Forest",
    "Nottingham Forest": "Nottingham Forest",
    "Norwich City": "Norwich City",
    "Sheffield Utd": "Sheffield United",
    "Sheffield United": "Sheffield United",
    "Southampton": "Southampton",
    "Tottenham": "Tottenham Hotspur",
    "Tottenham Hotspur": "Tottenham Hotspur",
    "Watford": "Watford",
    "West Brom": "West Bromwich Albion",
    "West Bromwich Albion": "West Bromwich Albion",
    "West Ham": "West Ham United",
    "West Ham United": "West Ham United",
    "Wolves": "Wolverhampton Wanderers",
    "Wolverhampton Wanderers": "Wolverhampton Wanderers",
}


class FBrefScraper(BaseScraper):
    """Scraper for FBref.com match-level team statistics.

    Uses the ``soccerdata`` library which handles:
      - FBref page scraping and HTML parsing
      - Built-in rate limiting (respects FBref's crawl delays)
      - Automatic caching to avoid re-downloading

    If FBref is unreachable (Cloudflare 403, timeout, etc.), returns
    an empty DataFrame — the pipeline can still run without xG data.
    """

    @property
    def source_name(self) -> str:
        return "fbref"

    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Download per-match team stats for one league-season from FBref.

        Parameters
        ----------
        league_config : ConfigNamespace
            League config with ``fbref_league_id`` (e.g. "ENG-Premier League")
            and ``short_name`` (e.g. "EPL").
        season : str
            Season in BetVector format, e.g. ``"2024-25"``.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: date, team, opponent, is_home, xg, xga,
            shots, shots_on_target, possession, passes_completed,
            passes_attempted.  Empty DataFrame (with correct columns) if
            FBref is unreachable.
        """
        fbref_league = league_config.fbref_league_id  # type: ignore[attr-defined]
        short_name = league_config.short_name  # type: ignore[attr-defined]
        fbref_season = self._to_fbref_season(season)

        logger.info(
            "Scraping FBref: %s %s (soccerdata league=%s, season=%s)",
            short_name, season, fbref_league, fbref_season,
        )

        # Fetch data via soccerdata — handles rate limiting and caching
        try:
            raw_df = self._fetch_via_soccerdata(fbref_league, fbref_season)
        except Exception as exc:
            logger.warning(
                "FBref scrape failed for %s %s: %s. "
                "Returning empty DataFrame — pipeline will continue "
                "without FBref data for this season.",
                short_name, season, exc,
            )
            return self._empty_dataframe()

        if raw_df.empty:
            logger.warning(
                "FBref returned no data for %s %s.",
                short_name, season,
            )
            return self._empty_dataframe()

        # Save raw data before processing
        self.save_raw(raw_df, short_name, season)

        # Clean and normalise
        clean_df = self._clean(raw_df, short_name)

        logger.info(
            "FBref %s %s: %d match-team rows parsed",
            short_name, season, len(clean_df),
        )
        return clean_df

    # --- internal helpers -----------------------------------------------------

    @staticmethod
    def _to_fbref_season(season: str) -> str:
        """Convert BetVector season format to soccerdata format.

        Examples::

            "2024-25" → "2024-2025"
            "2020-21" → "2020-2021"

        soccerdata uses full four-digit years separated by hyphen.
        """
        parts = season.split("-")
        if len(parts) != 2:
            raise ScraperError(
                f"Invalid season format '{season}' — expected 'YYYY-YY'"
            )
        start_year = parts[0]
        end_suffix = parts[1]

        # Derive full end year from the 2-digit suffix
        century = start_year[:2]
        end_year = f"{century}{end_suffix}"

        return f"{start_year}-{end_year}"

    def _fetch_via_soccerdata(
        self,
        fbref_league: str,
        fbref_season: str,
    ) -> pd.DataFrame:
        """Use soccerdata to fetch and combine schedule + shooting + passing stats.

        We need data from multiple stat types:
          - ``schedule``: match dates, teams, scores
          - ``shooting``: xG, shots, shots on target
          - ``possession``: possession percentage
          - ``passing``: passes completed, passes attempted

        These are fetched separately and merged on match/team keys.
        """
        import soccerdata

        fb = soccerdata.FBref(
            leagues=fbref_league,
            seasons=fbref_season,
        )

        # Fetch schedule (match list with basic info)
        logger.info("FBref: fetching schedule...")
        schedule = fb.read_team_match_stats(stat_type="schedule")

        # Fetch shooting stats (xG, shots)
        logger.info("FBref: fetching shooting stats...")
        shooting = fb.read_team_match_stats(stat_type="shooting")

        # Fetch passing stats
        logger.info("FBref: fetching passing stats...")
        passing = fb.read_team_match_stats(stat_type="passing")

        # Fetch possession stats
        logger.info("FBref: fetching possession stats...")
        possession = fb.read_team_match_stats(stat_type="possession")

        # Combine all stat types into a single DataFrame
        combined = self._merge_stat_types(schedule, shooting, passing, possession)
        return combined

    def _merge_stat_types(
        self,
        schedule: pd.DataFrame,
        shooting: pd.DataFrame,
        passing: pd.DataFrame,
        possession: pd.DataFrame,
    ) -> pd.DataFrame:
        """Merge multiple FBref stat type DataFrames into one.

        soccerdata returns MultiIndex DataFrames. We extract the columns
        we need from each and merge them on the shared index.
        """
        # soccerdata DataFrames have a MultiIndex: (league, season, team, date, ...)
        # We'll reset the index and merge on common keys

        # Extract what we need from schedule
        result = self._extract_schedule_cols(schedule)

        # Extract shooting cols (xG, shots)
        shooting_cols = self._extract_shooting_cols(shooting)
        if shooting_cols is not None:
            result = result.merge(
                shooting_cols,
                on=["date", "team"],
                how="left",
            )

        # Extract passing cols
        passing_cols = self._extract_passing_cols(passing)
        if passing_cols is not None:
            result = result.merge(
                passing_cols,
                on=["date", "team"],
                how="left",
            )

        # Extract possession cols
        possession_cols = self._extract_possession_cols(possession)
        if possession_cols is not None:
            result = result.merge(
                possession_cols,
                on=["date", "team"],
                how="left",
            )

        return result

    def _extract_schedule_cols(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract date, team, opponent, venue from the schedule DataFrame."""
        flat = df.reset_index()

        # soccerdata column names vary by version — look for common patterns
        cols = flat.columns.tolist()
        logger.info("FBref schedule columns: %s", cols)

        result = pd.DataFrame()
        result["date"] = self._find_column(flat, ["date", "Date"])
        result["team"] = self._find_column(flat, ["team", "Team", "squad"])
        result["opponent"] = self._find_column(
            flat, ["opponent", "Opponent", "opp"]
        )
        # Venue: 'Home' or 'Away'
        venue = self._find_column(flat, ["venue", "Venue"])
        if venue is not None:
            result["is_home"] = venue.map(
                lambda v: 1 if str(v).lower() == "home" else 0
            )
        else:
            result["is_home"] = None

        return result

    def _extract_shooting_cols(
        self, df: pd.DataFrame
    ) -> Optional[pd.DataFrame]:
        """Extract xG, shots, shots on target from shooting stats."""
        try:
            flat = df.reset_index()
            result = pd.DataFrame()
            result["date"] = self._find_column(flat, ["date", "Date"])
            result["team"] = self._find_column(flat, ["team", "Team", "squad"])
            result["xg"] = self._find_numeric_column(flat, ["xg", "xG"])
            result["shots"] = self._find_numeric_column(
                flat, ["sh", "Sh", "shots", "Shots"]
            )
            result["shots_on_target"] = self._find_numeric_column(
                flat, ["sot", "SoT", "shots_on_target"]
            )
            return result
        except Exception as exc:
            logger.warning("Could not extract shooting stats: %s", exc)
            return None

    def _extract_passing_cols(
        self, df: pd.DataFrame
    ) -> Optional[pd.DataFrame]:
        """Extract passes completed and attempted from passing stats."""
        try:
            flat = df.reset_index()
            result = pd.DataFrame()
            result["date"] = self._find_column(flat, ["date", "Date"])
            result["team"] = self._find_column(flat, ["team", "Team", "squad"])
            result["passes_completed"] = self._find_numeric_column(
                flat, ["cmp", "Cmp", "passes_completed"]
            )
            result["passes_attempted"] = self._find_numeric_column(
                flat, ["att", "Att", "passes_attempted"]
            )
            return result
        except Exception as exc:
            logger.warning("Could not extract passing stats: %s", exc)
            return None

    def _extract_possession_cols(
        self, df: pd.DataFrame
    ) -> Optional[pd.DataFrame]:
        """Extract possession percentage from possession stats."""
        try:
            flat = df.reset_index()
            result = pd.DataFrame()
            result["date"] = self._find_column(flat, ["date", "Date"])
            result["team"] = self._find_column(flat, ["team", "Team", "squad"])
            poss = self._find_numeric_column(
                flat, ["poss", "Poss", "possession"]
            )
            # Convert percentage (e.g. 65.0) to proportion (0.65)
            if poss is not None:
                result["possession"] = poss / 100.0
            else:
                result["possession"] = None
            return result
        except Exception as exc:
            logger.warning("Could not extract possession stats: %s", exc)
            return None

    @staticmethod
    def _find_column(
        df: pd.DataFrame, candidates: list
    ) -> Optional[pd.Series]:
        """Find a column by trying multiple possible names.

        soccerdata column names can be MultiIndex tuples or flat strings,
        and they vary between versions. This handles both cases.
        """
        # Handle MultiIndex columns
        if hasattr(df.columns, 'levels'):
            # Flatten multi-index column names
            flat_cols = [
                str(c[-1]) if isinstance(c, tuple) else str(c)
                for c in df.columns
            ]
            for candidate in candidates:
                for i, col_name in enumerate(flat_cols):
                    if col_name.lower() == candidate.lower():
                        return df.iloc[:, i]

        # Handle flat columns
        for candidate in candidates:
            for col in df.columns:
                col_str = str(col[-1]) if isinstance(col, tuple) else str(col)
                if col_str.lower() == candidate.lower():
                    return df[col]

        return None

    @staticmethod
    def _find_numeric_column(
        df: pd.DataFrame, candidates: list
    ) -> Optional[pd.Series]:
        """Find a numeric column, coercing to float."""
        # Handle MultiIndex columns
        if hasattr(df.columns, 'levels'):
            flat_cols = [
                str(c[-1]) if isinstance(c, tuple) else str(c)
                for c in df.columns
            ]
            for candidate in candidates:
                for i, col_name in enumerate(flat_cols):
                    if col_name.lower() == candidate.lower():
                        return pd.to_numeric(df.iloc[:, i], errors="coerce")

        for candidate in candidates:
            for col in df.columns:
                col_str = str(col[-1]) if isinstance(col, tuple) else str(col)
                if col_str.lower() == candidate.lower():
                    return pd.to_numeric(df[col], errors="coerce")

        return None

    def _clean(self, df: pd.DataFrame, league_short_name: str) -> pd.DataFrame:
        """Clean and normalise the merged FBref DataFrame.

        Steps:
          1. Normalise team and opponent names
          2. Parse dates to ISO format
          3. Derive xGA from opponent's xG data
          4. Ensure all expected columns are present
          5. Validate value ranges
        """
        clean = df.copy()

        # Normalise team names
        name_map = self._get_team_name_map(league_short_name)
        if name_map:
            clean["team"] = clean["team"].map(lambda x: name_map.get(x, x))
            clean["opponent"] = clean["opponent"].map(
                lambda x: name_map.get(x, x)
            )

        # Parse dates to ISO format
        if "date" in clean.columns:
            clean["date"] = pd.to_datetime(
                clean["date"], errors="coerce"
            ).dt.strftime("%Y-%m-%d")

        # Derive xGA: for each team's row, xGA is the opponent's xG in the
        # same match.  We merge on (date, team=opponent) to get this.
        if "xg" in clean.columns:
            xga_lookup = clean[["date", "team", "xg"]].rename(
                columns={"team": "opponent", "xg": "xga"}
            )
            clean = clean.merge(
                xga_lookup, on=["date", "opponent"], how="left"
            )

        # Ensure all expected output columns exist
        expected_cols = [
            "date", "team", "opponent", "is_home", "xg", "xga",
            "shots", "shots_on_target", "possession",
            "passes_completed", "passes_attempted",
        ]
        for col in expected_cols:
            if col not in clean.columns:
                clean[col] = None

        # Select only the expected columns
        clean = clean[expected_cols].copy()

        # Validate xG range (should be 0.0–6.0 for realistic values)
        for col in ["xg", "xga"]:
            if col in clean.columns and clean[col].notna().any():
                clean[col] = pd.to_numeric(clean[col], errors="coerce")
                # Flag but don't remove outliers
                outliers = clean[col] > 6.0
                if outliers.any():
                    logger.warning(
                        "FBref %s: %d rows with %s > 6.0 (unusual but kept)",
                        league_short_name, outliers.sum(), col,
                    )

        return clean.reset_index(drop=True)

    @staticmethod
    def _get_team_name_map(league_short_name: str) -> Dict[str, str]:
        """Return the FBref team name normalisation map for a league."""
        maps: Dict[str, Dict[str, str]] = {
            "EPL": FBREF_EPL_TEAM_MAP,
        }
        if league_short_name not in maps:
            logger.warning(
                "No FBref team name map for '%s' — names pass through "
                "un-normalised.",
                league_short_name,
            )
            return {}
        return maps[league_short_name]

    @staticmethod
    def _empty_dataframe() -> pd.DataFrame:
        """Return an empty DataFrame with the expected output columns.

        This is returned when FBref is unreachable — downstream code can
        check ``df.empty`` and skip FBref-dependent features.
        """
        return pd.DataFrame(columns=[
            "date", "team", "opponent", "is_home", "xg", "xga",
            "shots", "shots_on_target", "possession",
            "passes_completed", "passes_attempted",
        ])
