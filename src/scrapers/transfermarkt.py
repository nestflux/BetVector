"""
BetVector — Transfermarkt Datasets Scraper (E15-03)
=====================================================
Downloads squad market value data from the public ``dcaribou/transfermarkt-datasets``
GitHub repository, hosted on Cloudflare R2 CDN.  No API key or authentication required.

This data supplements our prediction models by providing:
  - **Squad market value ratio** — richer squads generally outperform poorer ones.
    A €1 billion squad facing a €200 million squad has a structural advantage that
    goes beyond recent form.  Market value captures long-term squad quality.
  - **Average player value** — proxy for depth of talent.
  - **Contract expiring count** — players with contracts ending within 6 months
    are a proxy for squad instability (potential distraction, transfer speculation).

Data Source:
  - Repo: https://github.com/dcaribou/transfermarkt-datasets (CC0 1.0 license)
  - CDN:  https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/{table}.csv.gz
  - Tables used: ``players.csv.gz`` (individual player data + valuations)
  - Filters: ``current_club_domestic_competition_id == "GB1"`` (EPL)
  - Updated weekly by the repository maintainer

The scraper downloads the full players CSV, filters to EPL clubs, and aggregates
player-level data to team-level snapshots.  Individual player values are not
stored — only the team aggregate (our prediction model operates at match level).

Master Plan refs: MP §5 Data Sources, MP §7 Scraper Interface
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta
from difflib import get_close_matches
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import config
from src.scrapers.base_scraper import BaseScraper, ScraperError

logger = logging.getLogger(__name__)


# ============================================================================
# Team Name Mapping: Transfermarkt → Canonical DB Names
# ============================================================================
# Transfermarkt uses full official club names (often with "Football Club"
# suffix).  Our canonical DB names come from Football-Data.co.uk (set during
# initial data load in E3-02).  This mapping bridges the two conventions.
#
# Names verified against actual CDN data and the ``teams`` table in the DB.
# If a new team appears (e.g., promoted side), a fuzzy fallback tries to
# match it, and a warning is logged so we can add the explicit mapping.

TRANSFERMARKT_TEAM_MAP: Dict[str, str] = {
    # --- Current 2025-26 EPL squads ---
    "Arsenal Football Club": "Arsenal",
    "Association Football Club Bournemouth": "AFC Bournemouth",
    "Aston Villa Football Club": "Aston Villa",
    "Brentford Football Club": "Brentford",
    "Brighton and Hove Albion Football Club": "Brighton & Hove Albion",
    "Burnley Football Club": "Burnley",
    "Chelsea Football Club": "Chelsea",
    "Crystal Palace Football Club": "Crystal Palace",
    "Everton Football Club": "Everton",
    "Fulham Football Club": "Fulham",
    "Liverpool Football Club": "Liverpool",
    "Manchester City Football Club": "Manchester City",
    "Manchester United Football Club": "Manchester United",
    "Newcastle United Football Club": "Newcastle United",
    "Nottingham Forest Football Club": "Nottingham Forest",
    "Southampton FC": "Southampton",
    "Sunderland Association Football Club": "Sunderland",
    "Tottenham Hotspur Football Club": "Tottenham Hotspur",
    "West Ham United Football Club": "West Ham United",
    "Wolverhampton Wanderers Football Club": "Wolverhampton Wanderers",

    # --- Recently promoted/relegated (historical coverage) ---
    "Ipswich Town": "Ipswich Town",
    "Leeds United Association Football Club": "Leeds United",
    "Leicester City": "Leicester City",
    "Luton Town": "Luton Town",
    "Sheffield United": "Sheffield United",
    "Norwich City": "Norwich City",
    "Watford FC": "Watford",
    "West Bromwich Albion": "West Bromwich Albion",
    "Huddersfield Town": "Huddersfield Town",
    "Cardiff City": "Cardiff City",
}


# ============================================================================
# Transfermarkt Datasets Scraper
# ============================================================================

class TransfermarktScraper(BaseScraper):
    """Squad market value scraper via Transfermarkt Datasets CDN.

    Downloads the full ``players.csv.gz`` file from the CDN, filters to EPL
    clubs, and aggregates player-level data to team-level market value
    snapshots.  Returns a DataFrame ready for ``load_market_values()``.

    Output columns: ``team_name, squad_total_value, avg_player_value,
    squad_size, contract_expiring_count, evaluated_at``

    This scraper does NOT require an API key — the CDN is public and free.
    The data is licensed under CC0 1.0 (public domain).
    """

    # Domain for rate limiting
    DOMAIN = "pub-e682421888d945d684bcae8890b0ec20.r2.dev"

    def __init__(self) -> None:
        super().__init__()

        # Override rate limit for the CDN (polite, not aggressive)
        try:
            interval = float(
                getattr(config.settings.scraping.transfermarkt,
                        "min_request_interval_seconds", 2)
            )
            self.rate_limiter._min_interval = interval
        except (AttributeError, TypeError):
            self.rate_limiter._min_interval = 2.0

        # CDN base URL and competition ID from config
        try:
            self._cdn_base = str(
                getattr(config.settings.scraping.transfermarkt,
                        "cdn_base_url",
                        "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data")
            )
            self._competition_id = str(
                getattr(config.settings.scraping.transfermarkt,
                        "competition_id", "GB1")
            )
        except (AttributeError, TypeError):
            self._cdn_base = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data"
            self._competition_id = "GB1"

    @property
    def source_name(self) -> str:
        return "transfermarkt"

    def scrape(
        self,
        league_config: object,
        season: str,
    ) -> pd.DataFrame:
        """Fetch squad market values for all EPL teams.

        Downloads ``players.csv.gz`` from the CDN, filters to the configured
        competition (EPL / GB1), and aggregates to team-level metrics.

        The ``season`` parameter is used for file naming (``save_raw()``) but
        does not filter the data — the CDN always serves the latest snapshot.

        Parameters
        ----------
        league_config : ConfigNamespace
            League configuration from ``config.get_active_leagues()``.
        season : str
            Season string, e.g. ``"2025-26"`` — used for raw file naming.

        Returns
        -------
        pd.DataFrame
            One row per EPL team with: team_name, squad_total_value,
            avg_player_value, squad_size, contract_expiring_count, evaluated_at.
            Empty DataFrame on any failure.
        """
        league_name = getattr(league_config, "short_name", "unknown")

        logger.info(
            "[%s] Fetching squad market values for %s %s",
            self.source_name, league_name, season,
        )

        # --- Download players.csv.gz ---
        players_url = f"{self._cdn_base}/players.csv.gz"

        try:
            response = self._request_with_retry(
                url=players_url,
                domain=self.DOMAIN,
                headers={"Accept": "application/gzip"},
            )
        except ScraperError as e:
            logger.error("[%s] Failed to download players.csv.gz: %s",
                         self.source_name, e)
            return pd.DataFrame()
        except Exception as e:
            logger.error("[%s] Unexpected error downloading players: %s",
                         self.source_name, e)
            return pd.DataFrame()

        # --- Parse the gzip-compressed CSV ---
        try:
            players_df = pd.read_csv(
                io.BytesIO(response.content),
                compression="gzip",
            )
        except Exception as e:
            logger.error("[%s] Failed to parse players CSV: %s",
                         self.source_name, e)
            return pd.DataFrame()

        logger.info(
            "[%s] Downloaded %d total players from CDN",
            self.source_name, len(players_df),
        )

        if players_df.empty:
            logger.warning("[%s] Empty players CSV from CDN", self.source_name)
            return pd.DataFrame()

        # --- Filter to EPL clubs ---
        # Use the competition ID column on the players table directly
        epl_players = players_df[
            players_df["current_club_domestic_competition_id"] == self._competition_id
        ].copy()

        if epl_players.empty:
            logger.warning(
                "[%s] No EPL players found (competition_id=%s)",
                self.source_name, self._competition_id,
            )
            return pd.DataFrame()

        # Filter to recent players only — the dataset includes historical players
        # who may no longer be at the club.  last_season >= (current year - 1)
        # ensures we only count active squad members.
        current_year = datetime.utcnow().year
        min_last_season = current_year - 1  # e.g., 2024 for 2025-26 season
        epl_players = epl_players[
            epl_players["last_season"] >= min_last_season
        ].copy()

        # Only keep players with market values for aggregation
        valued_players = epl_players[
            epl_players["market_value_in_eur"].notna()
        ].copy()

        logger.info(
            "[%s] EPL players: %d total, %d with market values (last_season >= %d)",
            self.source_name, len(epl_players), len(valued_players), min_last_season,
        )

        if valued_players.empty:
            logger.warning("[%s] No EPL players with market values", self.source_name)
            return pd.DataFrame()

        # --- Calculate contract expiring count ---
        # A player's contract is "expiring" if it ends within 6 months from today.
        # This is a proxy for squad instability — players may be distracted by
        # transfer speculation, and the team risks losing key assets for free.
        today = datetime.utcnow()
        cutoff = today + timedelta(days=180)

        epl_players["contract_exp"] = pd.to_datetime(
            epl_players["contract_expiration_date"], errors="coerce"
        )
        expiring_counts = (
            epl_players[epl_players["contract_exp"] <= cutoff]
            .groupby("current_club_name")
            .size()
            .reset_index(name="contract_expiring_count")
        )

        # --- Aggregate to team level ---
        team_agg = (
            valued_players
            .groupby("current_club_name")
            .agg(
                squad_total_value=("market_value_in_eur", "sum"),
                avg_player_value=("market_value_in_eur", "mean"),
                squad_size=("player_id", "count"),
            )
            .reset_index()
            .rename(columns={"current_club_name": "tm_name"})
        )

        # Merge contract expiring counts
        team_agg = team_agg.merge(
            expiring_counts.rename(columns={"current_club_name": "tm_name"}),
            on="tm_name",
            how="left",
        )
        team_agg["contract_expiring_count"] = (
            team_agg["contract_expiring_count"].fillna(0).astype(int)
        )

        # --- Map team names to canonical DB names ---
        team_agg["team_name"] = team_agg["tm_name"].apply(self._map_team_name)

        # Add evaluation date (today's date — this is a snapshot)
        team_agg["evaluated_at"] = date.today().isoformat()

        # Select output columns
        result = team_agg[[
            "team_name", "squad_total_value", "avg_player_value",
            "squad_size", "contract_expiring_count", "evaluated_at",
        ]].copy()

        # Save raw data for reproducibility
        self.save_raw(result, league_name, season)

        # Log summary
        top = result.sort_values("squad_total_value", ascending=False).head(3)
        top_str = ", ".join(
            f"{r['team_name']} (€{r['squad_total_value']/1e6:.0f}M)"
            for _, r in top.iterrows()
        )
        logger.info(
            "[%s] Aggregated market values for %d EPL teams. "
            "Top 3: %s",
            self.source_name, len(result), top_str,
        )

        return result

    # -----------------------------------------------------------------------
    # Team Name Mapping
    # -----------------------------------------------------------------------

    def _map_team_name(self, tm_name: str) -> str:
        """Map a Transfermarkt club name to our canonical DB name.

        First tries the explicit mapping dict.  If no match, falls back to
        fuzzy matching against all known canonical names.  If even fuzzy
        matching fails, returns the raw Transfermarkt name and logs a warning
        so the mapping can be added manually.
        """
        if not tm_name:
            return tm_name

        # Direct lookup
        canonical = TRANSFERMARKT_TEAM_MAP.get(tm_name)
        if canonical:
            return canonical

        # Fuzzy fallback — try to match against known canonical names
        all_canonical = list(set(TRANSFERMARKT_TEAM_MAP.values()))
        matches = get_close_matches(tm_name, all_canonical, n=1, cutoff=0.6)
        if matches:
            logger.info(
                "[%s] Fuzzy matched '%s' → '%s'",
                self.source_name, tm_name, matches[0],
            )
            return matches[0]

        # No match — log warning for manual intervention
        logger.warning(
            "[%s] UNMAPPED team name: '%s' — add to TRANSFERMARKT_TEAM_MAP",
            self.source_name, tm_name,
        )
        return tm_name
