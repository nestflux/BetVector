"""
BetVector — Data Loader (E3-04)
================================
Takes scraped DataFrames from the Football-Data.co.uk and FBref scrapers
and loads them into the database with full deduplication.

Three loader functions, each independent and idempotent:

  - ``load_matches(df, league_id, season)`` — inserts matches and
    auto-creates team records if they don't already exist.
  - ``load_odds(df, league_id)`` — maps bookmaker column names
    (B365H → Bet365 / home / 1X2) and inserts closing odds.
  - ``load_match_stats(df, league_id)`` — links FBref stats to the
    correct match_id via (date, team) matching.

All loaders use explicit duplicate checks before inserting.  Running
any loader twice with the same data produces zero new records.

Master Plan refs: MP §6 Database Schema, MP §7 Scraper Interface
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.database.db import get_session
from src.database.models import League, Match, MatchStat, Odds, Team

logger = logging.getLogger(__name__)


# ============================================================================
# Bookmaker Column Mapping
# ============================================================================
# Football-Data.co.uk uses short column prefixes for each bookmaker.
# We map them to our canonical bookmaker names and the corresponding
# market type + selection in the odds table.
#
# Each entry: source_prefix → (canonical_name, market_type, {suffix → selection})
#
# For 1X2 markets:
#   H = home win, D = draw, A = away win
# For O/U 2.5 markets:
#   >2.5 = over, <2.5 = under

BOOKMAKER_1X2_MAP: Dict[str, Tuple[str, Dict[str, str]]] = {
    "B365": ("Bet365", {"H": "home", "D": "draw", "A": "away"}),
    "PS": ("Pinnacle", {"H": "home", "D": "draw", "A": "away"}),
    "WH": ("William Hill", {"H": "home", "D": "draw", "A": "away"}),
    "Avg": ("market_avg", {"H": "home", "D": "draw", "A": "away"}),
}

BOOKMAKER_OU25_MAP: Dict[str, Tuple[str, Dict[str, str]]] = {
    "Avg": ("market_avg", {">2.5": "over", "<2.5": "under"}),
}


# ============================================================================
# Match Loader
# ============================================================================

def load_matches(
    df: pd.DataFrame,
    league_id: int,
    season: str,
) -> Dict[str, int]:
    """Load match results into the database.

    Creates team records automatically if they don't already exist.
    Skips matches that are already in the database (matched by
    league_id + date + home_team_id + away_team_id).

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame from FootballDataScraper with columns: date, home_team,
        away_team, home_goals, away_goals, home_ht_goals, away_ht_goals.
    league_id : int
        Database ID of the league.
    season : str
        Season identifier, e.g. "2024-25".

    Returns
    -------
    dict
        Summary with keys: "new", "skipped", "total".
    """
    new_count = 0
    skipped_count = 0

    for _, row in df.iterrows():
        home_team_name = row["home_team"]
        away_team_name = row["away_team"]

        with get_session() as session:
            # Auto-create teams if they don't exist
            home_team = _get_or_create_team(
                session, home_team_name, league_id
            )
            away_team = _get_or_create_team(
                session, away_team_name, league_id
            )

            # Check for existing match (idempotency)
            existing = session.query(Match).filter_by(
                league_id=league_id,
                date=row["date"],
                home_team_id=home_team.id,
                away_team_id=away_team.id,
            ).first()

            if existing:
                skipped_count += 1
                continue

            # Insert new match
            match = Match(
                league_id=league_id,
                season=season,
                date=row["date"],
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                home_goals=_safe_int(row.get("home_goals")),
                away_goals=_safe_int(row.get("away_goals")),
                home_ht_goals=_safe_int(row.get("home_ht_goals")),
                away_ht_goals=_safe_int(row.get("away_ht_goals")),
                status="finished" if pd.notna(row.get("home_goals")) else "scheduled",
            )
            session.add(match)
            new_count += 1

    summary = {"new": new_count, "skipped": skipped_count, "total": len(df)}
    logger.info(
        "load_matches: Loaded %d matches (%d new, %d skipped as duplicates)",
        summary["total"], summary["new"], summary["skipped"],
    )
    return summary


# ============================================================================
# Odds Loader
# ============================================================================

def load_odds(
    df: pd.DataFrame,
    league_id: int,
) -> Dict[str, int]:
    """Load bookmaker odds into the database.

    Maps Football-Data.co.uk column names to our canonical format:
      - B365H → bookmaker="Bet365", market_type="1X2", selection="home"
      - PSA   → bookmaker="Pinnacle", market_type="1X2", selection="away"
      - Avg>2.5 → bookmaker="market_avg", market_type="OU25", selection="over"

    Each odds entry includes the decimal odds and the implied probability
    (1 / odds).  Implied probability includes the bookmaker's margin (vig).

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame from FootballDataScraper with result columns + odds columns.
    league_id : int
        Database ID of the league.

    Returns
    -------
    dict
        Summary with keys: "new", "skipped", "total_odds".
    """
    new_count = 0
    skipped_count = 0

    for _, row in df.iterrows():
        with get_session() as session:
            # Find the match by date + team names
            match = _find_match(
                session, league_id, row["date"],
                row["home_team"], row["away_team"],
            )
            if match is None:
                logger.warning(
                    "load_odds: No match found for %s %s vs %s — skipping odds",
                    row["date"], row["home_team"], row["away_team"],
                )
                continue

            # Load 1X2 odds for each bookmaker
            for prefix, (bookie_name, suffix_map) in BOOKMAKER_1X2_MAP.items():
                for suffix, selection in suffix_map.items():
                    col_name = f"{prefix}{suffix}"
                    if col_name not in row.index:
                        continue
                    odds_val = row[col_name]
                    if pd.isna(odds_val) or odds_val <= 1.0:
                        continue

                    inserted = _insert_odds(
                        session, match.id, bookie_name, "1X2",
                        selection, float(odds_val),
                    )
                    if inserted:
                        new_count += 1
                    else:
                        skipped_count += 1

            # Load O/U 2.5 odds
            for prefix, (bookie_name, suffix_map) in BOOKMAKER_OU25_MAP.items():
                for suffix, selection in suffix_map.items():
                    col_name = f"{prefix}{suffix}"
                    if col_name not in row.index:
                        continue
                    odds_val = row[col_name]
                    if pd.isna(odds_val) or odds_val <= 1.0:
                        continue

                    inserted = _insert_odds(
                        session, match.id, bookie_name, "OU25",
                        selection, float(odds_val),
                    )
                    if inserted:
                        new_count += 1
                    else:
                        skipped_count += 1

    summary = {"new": new_count, "skipped": skipped_count, "total_odds": new_count + skipped_count}
    logger.info(
        "load_odds: Loaded %d odds entries (%d new, %d skipped as duplicates)",
        summary["total_odds"], summary["new"], summary["skipped"],
    )
    return summary


# ============================================================================
# Match Stats Loader
# ============================================================================

def load_match_stats(
    df: pd.DataFrame,
    league_id: int,
) -> Dict[str, int]:
    """Load FBref match statistics into the database.

    Links stats to the correct match_id by matching on (date, team).
    Each match has two rows — one for the home team, one for the away team.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame from FBrefScraper with columns: date, team, opponent,
        is_home, xg, xga, shots, shots_on_target, possession,
        passes_completed, passes_attempted.
    league_id : int
        Database ID of the league.

    Returns
    -------
    dict
        Summary with keys: "new", "skipped", "total".
    """
    if df.empty:
        logger.info("load_match_stats: Empty DataFrame, nothing to load.")
        return {"new": 0, "skipped": 0, "total": 0}

    new_count = 0
    skipped_count = 0

    for _, row in df.iterrows():
        with get_session() as session:
            # Find team record
            team = session.query(Team).filter_by(
                name=row["team"],
                league_id=league_id,
            ).first()
            if team is None:
                logger.warning(
                    "load_match_stats: Team '%s' not found in DB — skipping.",
                    row["team"],
                )
                skipped_count += 1
                continue

            # Find the match by date and team
            # The team might be home or away
            match = session.query(Match).filter(
                Match.league_id == league_id,
                Match.date == row["date"],
                (
                    (Match.home_team_id == team.id) |
                    (Match.away_team_id == team.id)
                ),
            ).first()

            if match is None:
                logger.warning(
                    "load_match_stats: No match for %s on %s — skipping.",
                    row["team"], row["date"],
                )
                skipped_count += 1
                continue

            # Check for existing stats (idempotency)
            existing = session.query(MatchStat).filter_by(
                match_id=match.id,
                team_id=team.id,
            ).first()

            if existing:
                skipped_count += 1
                continue

            # Determine if this team is home or away in the match
            is_home = 1 if match.home_team_id == team.id else 0

            # Calculate pass completion percentage
            pass_pct = None
            if pd.notna(row.get("passes_completed")) and pd.notna(row.get("passes_attempted")):
                attempted = row["passes_attempted"]
                if attempted > 0:
                    pass_pct = row["passes_completed"] / attempted

            stat = MatchStat(
                match_id=match.id,
                team_id=team.id,
                is_home=is_home,
                xg=_safe_float(row.get("xg")),
                xga=_safe_float(row.get("xga")),
                shots=_safe_int(row.get("shots")),
                shots_on_target=_safe_int(row.get("shots_on_target")),
                possession=_safe_float(row.get("possession")),
                passes_completed=_safe_int(row.get("passes_completed")),
                passes_attempted=_safe_int(row.get("passes_attempted")),
                pass_pct=pass_pct,
                source="fbref",
            )
            session.add(stat)
            new_count += 1

    summary = {"new": new_count, "skipped": skipped_count, "total": len(df)}
    logger.info(
        "load_match_stats: Loaded %d stat rows (%d new, %d skipped as duplicates)",
        summary["total"], summary["new"], summary["skipped"],
    )
    return summary


# ============================================================================
# Helpers
# ============================================================================

def _get_or_create_team(
    session,
    team_name: str,
    league_id: int,
) -> Team:
    """Find a team by canonical name, or create it if it doesn't exist.

    Also stores the name as the ``football_data_name`` for future lookups.
    """
    team = session.query(Team).filter_by(
        name=team_name,
        league_id=league_id,
    ).first()

    if team is None:
        team = Team(
            name=team_name,
            league_id=league_id,
            football_data_name=team_name,
        )
        session.add(team)
        session.flush()  # Get the auto-generated id
        logger.info("Created team: %s (id=%d)", team_name, team.id)

    return team


def _find_match(
    session,
    league_id: int,
    date: str,
    home_team_name: str,
    away_team_name: str,
) -> Optional[Match]:
    """Find a match by league, date, and team names."""
    home_team = session.query(Team).filter_by(
        name=home_team_name, league_id=league_id,
    ).first()
    away_team = session.query(Team).filter_by(
        name=away_team_name, league_id=league_id,
    ).first()

    if home_team is None or away_team is None:
        return None

    return session.query(Match).filter_by(
        league_id=league_id,
        date=date,
        home_team_id=home_team.id,
        away_team_id=away_team.id,
    ).first()


def _insert_odds(
    session,
    match_id: int,
    bookmaker: str,
    market_type: str,
    selection: str,
    odds_decimal: float,
) -> bool:
    """Insert a single odds entry if it doesn't already exist.

    Returns True if inserted, False if skipped (duplicate).

    Implied probability is calculated as 1.0 / odds.  This includes the
    bookmaker's margin (also called "overround" or "vig").  For example,
    odds of 2.00 → implied probability of 0.50 (50%).  The sum of implied
    probabilities across all selections in a market will exceed 1.0 —
    the excess is the bookmaker's profit margin.
    """
    existing = session.query(Odds).filter_by(
        match_id=match_id,
        bookmaker=bookmaker,
        market_type=market_type,
        selection=selection,
    ).first()

    if existing:
        return False

    # Calculate implied probability from decimal odds
    # Decimal odds of 2.10 means you get £2.10 back for a £1 bet (£1.10 profit)
    # Implied probability = 1 / 2.10 = 0.4762 (47.62%)
    implied_prob = 1.0 / odds_decimal

    odds = Odds(
        match_id=match_id,
        bookmaker=bookmaker,
        market_type=market_type,
        selection=selection,
        odds_decimal=odds_decimal,
        implied_prob=implied_prob,
        source="football_data",
    )
    session.add(odds)
    return True


def _safe_int(value) -> Optional[int]:
    """Safely convert a value to int, returning None for NaN/None."""
    if value is None or pd.isna(value):
        return None
    return int(value)


def _safe_float(value) -> Optional[float]:
    """Safely convert a value to float, returning None for NaN/None."""
    if value is None or pd.isna(value):
        return None
    return float(value)
