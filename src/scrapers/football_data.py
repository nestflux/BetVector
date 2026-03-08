"""
BetVector — Football-Data.co.uk Scraper (E3-02)
================================================
Downloads match results and closing odds from Football-Data.co.uk, the
primary data source for historical EPL data.  Each season is a single CSV
file containing every match with full-time/half-time scores and closing
odds from 50+ bookmakers.

URL pattern::

    https://www.football-data.co.uk/mmz4281/{season_code}/{league_code}.csv

Where ``season_code`` is the last two digits of each year joined together
(e.g. "2024-25" → "2425") and ``league_code`` comes from config (e.g. "E0"
for the English Premier League).

Key columns parsed:
  - Results: Date, HomeTeam, AwayTeam, FTHG, FTAG, HTHG, HTAG
  - Odds: B365H/D/A (Bet365), PSH/D/A (Pinnacle), AvgH/D/A (market avg),
    Avg>2.5 / Avg<2.5 (over/under 2.5 goals market average)

Not all seasons have all bookmaker columns — the scraper handles missing
odds columns gracefully by filling them with NaN.

Master Plan refs: MP §5 Data Sources, MP §7 Scraper Interface
"""

from __future__ import annotations

import io
import logging
from typing import Dict, List, Optional

import pandas as pd

from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

# ============================================================================
# Football-Data.co.uk domain (for rate limiting)
# ============================================================================
DOMAIN = "www.football-data.co.uk"
BASE_URL = "https://www.football-data.co.uk/mmz4281"

# ============================================================================
# Team Name Normalisation
# ============================================================================
# Football-Data.co.uk uses abbreviated team names.  We map them to canonical
# full names so every data source (Football-Data, FBref, API-Football) uses
# the same names throughout the database.
#
# This mapping covers all EPL teams from the 2020-21 through 2024-25 seasons.
# When adding a new league, add its team mappings here or in a separate dict.

EPL_TEAM_NAME_MAP: Dict[str, str] = {
    # Teams that need no change (already canonical)
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Brentford": "Brentford",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Liverpool": "Liverpool",
    "Southampton": "Southampton",
    "Sunderland": "Sunderland",
    "Watford": "Watford",

    # Teams whose Football-Data names differ from canonical
    "Bournemouth": "AFC Bournemouth",
    "Brighton": "Brighton & Hove Albion",
    "Ipswich": "Ipswich Town",
    "Leeds": "Leeds United",
    "Leicester": "Leicester City",
    "Luton": "Luton Town",
    "Man City": "Manchester City",
    "Man United": "Manchester United",
    "Newcastle": "Newcastle United",
    "Nott'm Forest": "Nottingham Forest",
    "Norwich": "Norwich City",
    "Sheffield United": "Sheffield United",
    "Tottenham": "Tottenham Hotspur",
    "West Brom": "West Bromwich Albion",
    "West Ham": "West Ham United",
    "Wolves": "Wolverhampton Wanderers",
}

# ============================================================================
# League One Team Name Map (E38-02 — League Expansion Phase 2)
# ============================================================================
# League One (E2) uses short/abbreviated team names on Football-Data.co.uk.
# Unlike EPL, we use these FD names as-is for the canonical DB name (same
# pattern as Championship E1).  The map is identity so no transformation
# occurs, but having it explicit:
#   (a) suppresses the "No team name map" warning,
#   (b) documents all 49 teams across 6 seasons (2020-21 to 2025-26),
#   (c) enables future normalisation if needed.
#
# League One has high turnover — 24 teams per season but 49 unique teams
# across 6 seasons due to promotion/relegation.
# ============================================================================

LEAGUE_ONE_TEAM_NAME_MAP: Dict[str, str] = {
    # All teams that appeared in League One 2020-21 through 2025-26.
    # Football-Data.co.uk names → canonical DB names (identity mapping).
    "AFC Wimbledon": "AFC Wimbledon",       # 2020-21, 2021-22, 2025-26
    "Accrington": "Accrington",             # 2020-21, 2021-22, 2022-23
    "Barnsley": "Barnsley",                 # 2022-23, 2023-24, 2024-25, 2025-26
    "Birmingham": "Birmingham",             # 2024-25
    "Blackpool": "Blackpool",               # 2020-21, 2023-24, 2024-25, 2025-26
    "Bolton": "Bolton",                     # 2021-22, 2022-23, 2023-24, 2024-25, 2025-26
    "Bradford": "Bradford",                 # 2025-26
    "Bristol Rvs": "Bristol Rvs",           # 2020-21, 2022-23, 2023-24, 2024-25
    "Burton": "Burton",                     # 2020-21, 2021-22, 2022-23, 2023-24, 2024-25, 2025-26
    "Cambridge": "Cambridge",               # 2021-22, 2022-23, 2023-24, 2024-25
    "Cardiff": "Cardiff",                   # 2025-26
    "Carlisle": "Carlisle",                 # 2023-24
    "Charlton": "Charlton",                 # 2020-21, 2021-22, 2022-23, 2023-24, 2024-25
    "Cheltenham": "Cheltenham",             # 2021-22, 2022-23, 2023-24
    "Crawley Town": "Crawley Town",         # 2024-25
    "Crewe": "Crewe",                       # 2020-21, 2021-22
    "Derby": "Derby",                       # 2022-23, 2023-24
    "Doncaster": "Doncaster",               # 2020-21, 2021-22, 2025-26
    "Exeter": "Exeter",                     # 2022-23, 2023-24, 2024-25, 2025-26
    "Fleetwood Town": "Fleetwood Town",     # 2020-21, 2021-22, 2022-23, 2023-24, 2024-25
    "Forest Green": "Forest Green",         # 2022-23
    "Gillingham": "Gillingham",             # 2020-21, 2021-22
    "Huddersfield": "Huddersfield",         # 2024-25, 2025-26
    "Hull": "Hull",                         # 2020-21
    "Ipswich": "Ipswich",                   # 2020-21, 2021-22, 2022-23
    "Leyton Orient": "Leyton Orient",       # 2023-24, 2024-25, 2025-26
    "Lincoln": "Lincoln",                   # 2020-21, 2021-22, 2022-23, 2023-24, 2024-25, 2025-26
    "Luton": "Luton",                       # 2025-26
    "Mansfield": "Mansfield",               # 2024-25, 2025-26
    "Milton Keynes Dons": "Milton Keynes Dons",  # 2020-21, 2021-22, 2022-23
    "Morecambe": "Morecambe",               # 2021-22, 2022-23
    "Northampton": "Northampton",           # 2020-21, 2023-24, 2024-25, 2025-26
    "Oxford": "Oxford",                     # 2020-21, 2021-22, 2022-23, 2023-24
    "Peterboro": "Peterboro",               # 2020-21, 2022-23, 2023-24, 2024-25, 2025-26
    "Plymouth": "Plymouth",                 # 2020-21, 2021-22, 2022-23, 2025-26
    "Port Vale": "Port Vale",               # 2022-23, 2023-24, 2025-26
    "Portsmouth": "Portsmouth",             # 2020-21, 2021-22, 2022-23, 2023-24
    "Reading": "Reading",                   # 2023-24, 2024-25, 2025-26
    "Rochdale": "Rochdale",                 # 2020-21
    "Rotherham": "Rotherham",               # 2021-22, 2024-25, 2025-26
    "Sheffield Weds": "Sheffield Weds",     # 2021-22, 2022-23
    "Shrewsbury": "Shrewsbury",             # 2020-21, 2021-22, 2022-23, 2023-24, 2024-25
    "Stevenage": "Stevenage",               # 2023-24, 2024-25, 2025-26
    "Stockport": "Stockport",               # 2024-25, 2025-26
    "Sunderland": "Sunderland",             # 2020-21, 2021-22
    "Swindon": "Swindon",                   # 2020-21
    "Wigan": "Wigan",                       # 2020-21, 2021-22, 2023-24, 2024-25, 2025-26
    "Wrexham": "Wrexham",                   # 2024-25
    "Wycombe": "Wycombe",                   # 2021-22, 2022-23, 2023-24, 2024-25, 2025-26
}

# ============================================================================
# Bundesliga Team Name Map (E38-03 — League Expansion Phase 2)
# ============================================================================
# Bundesliga (D1) uses abbreviated team names on Football-Data.co.uk.
# Like Championship and League One, we use these FD names as-is for the
# canonical DB name.  The map is identity so no transformation occurs,
# but having it explicit documents all 25 teams across 6 seasons and
# suppresses the "No team name map" warning.
#
# Bundesliga has 18 teams/season, lower turnover than English leagues.
# 25 unique teams across 2020-21 to 2025-26 (7 promoted/relegated).
# ============================================================================

BUNDESLIGA_TEAM_NAME_MAP: Dict[str, str] = {
    # All teams that appeared in Bundesliga 2020-21 through 2025-26.
    # Football-Data.co.uk names → canonical DB names (identity mapping).
    "Augsburg": "Augsburg",                 # all 6 seasons
    "Bayern Munich": "Bayern Munich",       # all 6 seasons
    "Bielefeld": "Bielefeld",              # 2020-21, 2021-22
    "Bochum": "Bochum",                    # 2021-22 through 2024-25
    "Darmstadt": "Darmstadt",              # 2023-24
    "Dortmund": "Dortmund",                # all 6 seasons
    "Ein Frankfurt": "Ein Frankfurt",       # all 6 seasons
    "FC Koln": "FC Koln",                  # 2020-21 through 2023-24, 2025-26
    "Freiburg": "Freiburg",                # all 6 seasons
    "Greuther Furth": "Greuther Furth",     # 2021-22
    "Hamburg": "Hamburg",                   # 2025-26
    "Heidenheim": "Heidenheim",            # 2023-24, 2024-25, 2025-26
    "Hertha": "Hertha",                    # 2020-21 through 2022-23
    "Hoffenheim": "Hoffenheim",            # all 6 seasons
    "Holstein Kiel": "Holstein Kiel",       # 2024-25
    "Leverkusen": "Leverkusen",            # all 6 seasons
    "M'gladbach": "M'gladbach",            # all 6 seasons
    "Mainz": "Mainz",                      # all 6 seasons
    "RB Leipzig": "RB Leipzig",            # all 6 seasons
    "Schalke 04": "Schalke 04",            # 2020-21, 2022-23
    "St Pauli": "St Pauli",                # 2024-25, 2025-26
    "Stuttgart": "Stuttgart",              # all 6 seasons
    "Union Berlin": "Union Berlin",         # all 6 seasons
    "Werder Bremen": "Werder Bremen",       # 2020-21, 2022-23 through 2025-26
    "Wolfsburg": "Wolfsburg",              # all 6 seasons
}

# ============================================================================
# Column definitions
# ============================================================================
# Columns we always expect in the CSV (results)
RESULT_COLUMNS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HTHG", "HTAG"]

# Optional context columns — not present in every season
# Referee is available in most EPL CSVs and useful for referee features (E21-02)
OPTIONAL_CONTEXT_COLUMNS = ["Referee"]

# Odds columns we want — grouped by bookmaker and market.
# Not all are present in every season; missing ones become NaN.
ODDS_COLUMNS: Dict[str, List[str]] = {
    # 1X2 (match result) OPENING odds from key bookmakers
    "bet365_1x2": ["B365H", "B365D", "B365A"],
    "pinnacle_1x2": ["PSH", "PSD", "PSA"],
    "william_hill_1x2": ["WHH", "WHD", "WHA"],
    "market_avg_1x2": ["AvgH", "AvgD", "AvgA"],
    # 1X2 CLOSING odds from Pinnacle (E19-03)
    # Closing odds are the final odds before kickoff — used for CLV (Closing
    # Line Value) calculation.  If our model consistently beats Pinnacle's
    # closing line, we have genuine predictive edge (not just lucky variance).
    "pinnacle_closing_1x2": ["PSCH", "PSCD", "PSCA"],
    # Over/Under 2.5 goals (market average)
    "market_avg_ou25": ["Avg>2.5", "Avg<2.5"],
    # Asian Handicap line (E19-03)
    # The AH market is the sharpest market in football betting — sharper than
    # 1X2.  The handicap line (e.g., -0.5, -1.0) is a direct market-implied
    # assessment of the strength difference between two teams.
    "ah_pinnacle": ["AHh"],
    # Betbrain Asian Handicap market average
    "ah_market_avg": ["BbAHh"],
}

# Flat list of all desired odds columns
ALL_ODDS_COLUMNS = [col for cols in ODDS_COLUMNS.values() for col in cols]

# Renamed columns for the clean DataFrame output
RENAME_MAP = {
    "Date": "date",
    "HomeTeam": "home_team",
    "AwayTeam": "away_team",
    "FTHG": "home_goals",
    "FTAG": "away_goals",
    "HTHG": "home_ht_goals",
    "HTAG": "away_ht_goals",
    "Referee": "referee",
}


# ============================================================================
# Scraper
# ============================================================================

class FootballDataScraper(BaseScraper):
    """Scraper for Football-Data.co.uk CSV match data.

    Downloads one CSV per league-season containing match results and
    closing bookmaker odds.  Saves raw CSV to ``data/raw/`` before
    parsing and normalising.
    """

    @property
    def source_name(self) -> str:
        return "football_data"

    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Download and parse match data for one league-season.

        Parameters
        ----------
        league_config : ConfigNamespace
            League config from ``config.get_active_leagues()``.
            Must have ``football_data_code`` (e.g. "E0") and
            ``short_name`` (e.g. "EPL").
        season : str
            Season identifier, e.g. ``"2024-25"``.

        Returns
        -------
        pd.DataFrame
            Clean DataFrame with normalised team names, result columns,
            and available odds columns.

        Raises
        ------
        ScraperError
            If the CSV cannot be downloaded after retries.
        """
        league_code = league_config.football_data_code  # type: ignore[attr-defined]
        short_name = league_config.short_name  # type: ignore[attr-defined]
        season_code = self._season_to_code(season)

        url = f"{BASE_URL}/{season_code}/{league_code}.csv"
        logger.info(
            "Scraping Football-Data.co.uk: %s %s → %s",
            short_name, season, url,
        )

        # Download the CSV (with rate limiting and retries)
        response = self._request_with_retry(url, DOMAIN)

        # Parse the CSV from the response content
        raw_df = self._parse_csv(response.text, season)

        # Save raw data before any processing (reproducibility)
        self.save_raw(raw_df, short_name, season)

        # Clean and normalise
        clean_df = self._clean(raw_df, short_name)

        logger.info(
            "Football-Data.co.uk %s %s: %d matches parsed",
            short_name, season, len(clean_df),
        )
        return clean_df

    # --- internal helpers -----------------------------------------------------

    @staticmethod
    def _season_to_code(season: str) -> str:
        """Convert a season string to Football-Data.co.uk's URL code.

        Examples::

            "2024-25" → "2425"
            "2020-21" → "2021"
            "2023-24" → "2324"

        The code is the last two digits of each year concatenated.
        """
        parts = season.split("-")
        if len(parts) != 2:
            raise ScraperError(
                f"Invalid season format '{season}' — expected 'YYYY-YY' "
                f"(e.g. '2024-25')"
            )
        # First year: last 2 digits of the full year
        start = parts[0][-2:]
        # Second year: already 2 digits
        end = parts[1][-2:]
        return f"{start}{end}"

    def _parse_csv(self, csv_text: str, season: str) -> pd.DataFrame:
        """Parse raw CSV text into a DataFrame.

        Handles encoding quirks and trailing empty rows that
        Football-Data.co.uk CSVs sometimes contain.
        """
        try:
            df = pd.read_csv(
                io.StringIO(csv_text),
                encoding="utf-8",
                on_bad_lines="warn",
            )
        except Exception as exc:
            raise ScraperError(
                f"Failed to parse Football-Data.co.uk CSV for {season}: {exc}"
            ) from exc

        # Drop rows that are entirely empty (trailing garbage rows)
        df = df.dropna(how="all")

        # Drop rows where essential columns are missing
        # (sometimes the CSV has extra rows at the bottom with no data)
        essential = ["Date", "HomeTeam", "AwayTeam"]
        for col in essential:
            if col not in df.columns:
                raise ScraperError(
                    f"Football-Data.co.uk CSV missing essential column "
                    f"'{col}' — available columns: {list(df.columns)}"
                )
        df = df.dropna(subset=essential)

        logger.info("Parsed %d rows from Football-Data.co.uk CSV", len(df))
        return df

    def _clean(self, df: pd.DataFrame, league_short_name: str) -> pd.DataFrame:
        """Clean and normalise the raw DataFrame.

        Steps:
          1. Select result columns and available odds columns
          2. Rename columns to our standard names
          3. Parse and normalise the date column
          4. Normalise team names
          5. Convert numeric columns to proper types
        """
        # --- 1. Select columns ------------------------------------------------
        # Start with result columns (always required)
        keep_cols = list(RESULT_COLUMNS)

        # Add optional context columns (Referee, etc.) if present
        available_context = [c for c in OPTIONAL_CONTEXT_COLUMNS if c in df.columns]
        keep_cols.extend(available_context)

        # Add odds columns that exist in this season's CSV
        available_odds = [c for c in ALL_ODDS_COLUMNS if c in df.columns]
        missing_odds = [c for c in ALL_ODDS_COLUMNS if c not in df.columns]
        keep_cols.extend(available_odds)

        if missing_odds:
            logger.warning(
                "Football-Data.co.uk %s: missing odds columns (will be NaN): %s",
                league_short_name, missing_odds,
            )

        clean = df[keep_cols].copy()

        # Add missing odds columns as NaN so downstream code always sees them
        for col in missing_odds:
            clean[col] = float("nan")

        # Add missing optional context columns as NaN
        for col in OPTIONAL_CONTEXT_COLUMNS:
            if col not in clean.columns:
                clean[col] = None

        # --- 2. Rename result columns -----------------------------------------
        clean = clean.rename(columns=RENAME_MAP)

        # --- 3. Parse date column ---------------------------------------------
        clean["date"] = self._parse_dates(clean["date"])

        # --- 4. Normalise team names ------------------------------------------
        name_map = self._get_team_name_map(league_short_name)
        clean["home_team"] = clean["home_team"].map(
            lambda x: name_map.get(x, x)
        )
        clean["away_team"] = clean["away_team"].map(
            lambda x: name_map.get(x, x)
        )

        # Log any team names that weren't in our mapping (so we can add them)
        all_teams = set(clean["home_team"]) | set(clean["away_team"])
        unknown = [t for t in all_teams if t not in name_map.values()]
        if unknown:
            logger.warning(
                "Football-Data.co.uk %s: unmapped team names (passed through "
                "as-is): %s",
                league_short_name, sorted(unknown),
            )

        # --- 5. Convert numeric types -----------------------------------------
        int_cols = ["home_goals", "away_goals", "home_ht_goals", "away_ht_goals"]
        for col in int_cols:
            clean[col] = pd.to_numeric(clean[col], errors="coerce").astype(
                "Int64"  # Nullable integer — supports NaN for unplayed matches
            )

        float_cols = available_odds + missing_odds
        for col in float_cols:
            clean[col] = pd.to_numeric(clean[col], errors="coerce")

        return clean.reset_index(drop=True)

    @staticmethod
    def _parse_dates(date_series: pd.Series) -> pd.Series:
        """Parse the Date column into ISO format (YYYY-MM-DD).

        Football-Data.co.uk uses DD/MM/YYYY format (and sometimes
        DD/MM/YY for older seasons).  We normalise to ISO.
        """
        # Try DD/MM/YYYY first, then DD/MM/YY as fallback
        parsed = pd.to_datetime(date_series, format="%d/%m/%Y", errors="coerce")
        # Fill any failures with the 2-digit year format
        mask = parsed.isna()
        if mask.any():
            fallback = pd.to_datetime(
                date_series[mask], format="%d/%m/%y", errors="coerce"
            )
            parsed[mask] = fallback

        # Convert to ISO string format
        return parsed.dt.strftime("%Y-%m-%d")

    @staticmethod
    def _get_team_name_map(league_short_name: str) -> Dict[str, str]:
        """Return the team name normalisation map for a given league.

        Currently only EPL is supported.  When adding new leagues,
        create a new mapping dict and add a branch here.
        """
        maps: Dict[str, Dict[str, str]] = {
            "EPL": EPL_TEAM_NAME_MAP,
            "LeagueOne": LEAGUE_ONE_TEAM_NAME_MAP,  # E38-02: identity map (FD names are canonical)
            "Bundesliga": BUNDESLIGA_TEAM_NAME_MAP,  # E38-03: identity map (FD names are canonical)
        }
        if league_short_name not in maps:
            logger.warning(
                "No team name map for league '%s' — names will pass through "
                "un-normalised. Add a mapping to football_data.py.",
                league_short_name,
            )
            return {}
        return maps[league_short_name]
