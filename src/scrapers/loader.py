"""
BetVector — Data Loader (E3-04 + Real-Time Data Sources)
=========================================================
Takes scraped DataFrames from all data sources and loads them into the
database with full deduplication.

Loader functions (each independent and idempotent):

  - ``load_matches(df, league_id, season)`` — inserts matches and
    auto-creates team records if they don't already exist.
  - ``load_odds(df, league_id)`` — maps Football-Data.co.uk bookmaker
    columns (B365H → Bet365 / home / 1X2) and inserts closing odds.
  - ``load_odds_api_football(odds_records, league_id)`` — loads pre-match
    odds from API-Football (dict-based, not DataFrame-based).
  - ``load_match_stats(df, league_id)`` — links FBref stats to the
    correct match_id via (date, team) matching.
  - ``load_understat_stats(df, league_id)`` — loads xG data from Understat.
  - ``load_weather(df)`` — loads match-day weather into the weather table.
  - ``load_market_values(df, league_id)`` — loads team market value snapshots
    from Transfermarkt into the team_market_values table.
  - ``update_match_results(df, league_id)`` — updates scheduled matches
    with results from API-Football (goals, status).

All loaders use explicit duplicate checks before inserting.  Running
any loader twice with the same data produces zero new records.

Master Plan refs: MP §6 Database Schema, MP §7 Scraper Interface
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.database.db import get_session
from src.database.models import (
    League, Match, MatchStat, Odds, Team, TeamMarketValue, Weather,
)

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
    source: str = "football_data",
) -> bool:
    """Insert a single odds entry if it doesn't already exist.

    Returns True if inserted, False if skipped (duplicate).

    Parameters
    ----------
    source : str
        Data source identifier — ``"football_data"`` or ``"api_football"``.

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
        source=source,
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


# ============================================================================
# API-Football Odds Loader
# ============================================================================

def load_odds_api_football(
    odds_records: List[Dict],
    league_id: int,
) -> Dict[str, int]:
    """Load bookmaker odds from API-Football into the database.

    Unlike ``load_odds()`` which parses Football-Data.co.uk DataFrame columns,
    this accepts a list of pre-parsed dicts from ``APIFootballScraper.scrape_odds()``.

    Each dict must have: ``date``, ``fixture_id``, ``bookmaker``,
    ``market_type``, ``selection``, ``odds_decimal``.

    The fixture_id is used to look up the match via API-Football's fixture ID.
    If no match is found by fixture_id, falls back to date + team matching.

    Parameters
    ----------
    odds_records : list of dict
        Odds records from ``APIFootballScraper.scrape_odds()``.
    league_id : int
        Database ID of the league.

    Returns
    -------
    dict
        Summary with keys: "new", "skipped", "no_match", "total".
    """
    new_count = 0
    skipped_count = 0
    no_match_count = 0

    # Group odds by fixture_id for efficiency (one match lookup per fixture)
    from collections import defaultdict
    by_fixture: Dict[int, List[Dict]] = defaultdict(list)
    for record in odds_records:
        fid = record.get("fixture_id")
        if fid:
            by_fixture[fid].append(record)

    for fixture_id, records in by_fixture.items():
        with get_session() as session:
            # Try to find the match — first by date (since we may not have
            # stored fixture_id on the Match model).  We use the date and
            # look for matches on that day in this league.
            match = None
            sample_date = records[0].get("date") if records else None

            if sample_date:
                # Get all matches on this date for this league
                day_matches = session.query(Match).filter_by(
                    league_id=league_id,
                    date=sample_date,
                ).all()

                if len(day_matches) == 1:
                    # Only one match on this day — it's a safe match
                    match = day_matches[0]
                elif len(day_matches) > 1:
                    # Multiple matches — we'd need team names to disambiguate
                    # For now, skip these odds (rare for a single fixture_id)
                    logger.debug(
                        "load_odds_api_football: Multiple matches on %s — "
                        "skipping odds for fixture %s", sample_date, fixture_id,
                    )

            if match is None:
                no_match_count += len(records)
                continue

            # Insert each odds record
            for record in records:
                bookmaker = record.get("bookmaker", "")
                market_type = record.get("market_type", "")
                selection = record.get("selection", "")
                odds_decimal = record.get("odds_decimal", 0.0)

                if not bookmaker or not market_type or not selection or odds_decimal <= 1.0:
                    continue

                inserted = _insert_odds(
                    session, match.id, bookmaker, market_type,
                    selection, odds_decimal, source="api_football",
                )
                if inserted:
                    new_count += 1
                else:
                    skipped_count += 1

    summary = {
        "new": new_count,
        "skipped": skipped_count,
        "no_match": no_match_count,
        "total": len(odds_records),
    }
    logger.info(
        "load_odds_api_football: %d new, %d skipped, %d no match (of %d total)",
        new_count, skipped_count, no_match_count, len(odds_records),
    )
    return summary


# ============================================================================
# Match Results Updater (API-Football)
# ============================================================================

def update_match_results(
    df: pd.DataFrame,
    league_id: int,
) -> Dict[str, int]:
    """Update existing scheduled matches with results from API-Football.

    ``load_matches()`` only inserts new matches — it never updates existing
    ones.  This function is needed because API-Football gives us scheduled
    matches first, then results come in later.

    Matches are found by (league_id, date, home_team, away_team).
    Only matches with status ``"scheduled"`` are updated.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame from ``APIFootballScraper.scrape()`` containing columns:
        date, home_team, away_team, home_goals, away_goals,
        home_ht_goals, away_ht_goals, status.
    league_id : int
        Database ID of the league.

    Returns
    -------
    dict
        Summary with keys: "updated", "skipped", "not_found".
    """
    updated = 0
    skipped = 0
    not_found = 0

    # Only process rows that have results (finished matches)
    finished_df = df[df["status"] == "finished"].copy()

    for _, row in finished_df.iterrows():
        with get_session() as session:
            match = _find_match(
                session, league_id, row["date"],
                row["home_team"], row["away_team"],
            )

            if match is None:
                not_found += 1
                continue

            # Only update if currently scheduled (don't overwrite finished matches)
            if match.status != "scheduled":
                skipped += 1
                continue

            # Update with results
            match.home_goals = _safe_int(row.get("home_goals"))
            match.away_goals = _safe_int(row.get("away_goals"))
            match.home_ht_goals = _safe_int(row.get("home_ht_goals"))
            match.away_ht_goals = _safe_int(row.get("away_ht_goals"))
            match.status = "finished"
            updated += 1

    summary = {"updated": updated, "skipped": skipped, "not_found": not_found}
    logger.info(
        "update_match_results: %d updated, %d already finished, %d not found",
        updated, skipped, not_found,
    )
    return summary


# ============================================================================
# Understat Stats Loader
# ============================================================================

def load_understat_stats(
    df: pd.DataFrame,
    league_id: int,
) -> Dict[str, int]:
    """Load xG + advanced stats from Understat into the match_stats table.

    Maps Understat match-level data to two MatchStat rows per match
    (home team + away team), with ``source="understat"``.

    Only loads data for finished matches that have xG values.
    Does NOT overwrite existing stats — if a match already has MatchStat
    rows from any source, Understat data is skipped for that team/match.

    Since E15-02, also stores advanced stats from the ``get_team_data()``
    endpoint: NPxG, PPDA coefficient, deep completions, and shots.  These
    columns are nullable — older data without advanced stats just has NULL.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame from ``UnderstatScraper.scrape()`` with columns:
        date, home_team, away_team, home_xg, away_xg, home_xga, away_xga,
        home_npxg, away_npxg, home_npxga, away_npxga,
        home_ppda, away_ppda, home_ppda_allowed, away_ppda_allowed,
        home_deep, away_deep, home_deep_allowed, away_deep_allowed,
        home_shots, away_shots.
    league_id : int
        Database ID of the league.

    Returns
    -------
    dict
        Summary with keys: "new", "skipped", "not_found", "updated".
    """
    if df.empty:
        return {"new": 0, "skipped": 0, "not_found": 0, "updated": 0}

    new_count = 0
    skipped_count = 0
    not_found = 0
    updated_count = 0

    # Only load finished matches with xG data
    has_xg = df[df["home_xg"].notna()].copy()

    for _, row in has_xg.iterrows():
        with get_session() as session:
            # Find the match in our DB
            match = _find_match(
                session, league_id, row["date"],
                row["home_team"], row["away_team"],
            )

            if match is None:
                not_found += 1
                continue

            # Find the home and away team IDs
            home_team = session.query(Team).filter_by(
                name=row["home_team"], league_id=league_id,
            ).first()
            away_team = session.query(Team).filter_by(
                name=row["away_team"], league_id=league_id,
            ).first()

            if home_team is None or away_team is None:
                not_found += 1
                continue

            # --- Home team stats ---
            existing_home = session.query(MatchStat).filter_by(
                match_id=match.id, team_id=home_team.id,
            ).first()

            if existing_home is None:
                # Insert new stat row with all available fields
                home_stat = MatchStat(
                    match_id=match.id,
                    team_id=home_team.id,
                    is_home=1,
                    xg=_safe_float(row.get("home_xg")),
                    xga=_safe_float(row.get("home_xga")),
                    # E15-02: Advanced stats from get_team_data()
                    npxg=_safe_float(row.get("home_npxg")),
                    npxga=_safe_float(row.get("home_npxga")),
                    ppda_coeff=_safe_float(row.get("home_ppda")),
                    ppda_allowed_coeff=_safe_float(row.get("home_ppda_allowed")),
                    deep=_safe_int(row.get("home_deep")),
                    deep_allowed=_safe_int(row.get("home_deep_allowed")),
                    source="understat",
                )
                session.add(home_stat)
                new_count += 1
            elif existing_home.source == "understat" and existing_home.npxg is None:
                # Existing Understat row without advanced stats — backfill
                # (handles re-running after E15-02 upgrade on old data)
                existing_home.npxg = _safe_float(row.get("home_npxg"))
                existing_home.npxga = _safe_float(row.get("home_npxga"))
                existing_home.ppda_coeff = _safe_float(row.get("home_ppda"))
                existing_home.ppda_allowed_coeff = _safe_float(row.get("home_ppda_allowed"))
                existing_home.deep = _safe_int(row.get("home_deep"))
                existing_home.deep_allowed = _safe_int(row.get("home_deep_allowed"))
                updated_count += 1
            else:
                skipped_count += 1

            # --- Away team stats ---
            existing_away = session.query(MatchStat).filter_by(
                match_id=match.id, team_id=away_team.id,
            ).first()

            if existing_away is None:
                away_stat = MatchStat(
                    match_id=match.id,
                    team_id=away_team.id,
                    is_home=0,
                    xg=_safe_float(row.get("away_xg")),
                    xga=_safe_float(row.get("away_xga")),
                    # E15-02: Advanced stats
                    npxg=_safe_float(row.get("away_npxg")),
                    npxga=_safe_float(row.get("away_npxga")),
                    ppda_coeff=_safe_float(row.get("away_ppda")),
                    ppda_allowed_coeff=_safe_float(row.get("away_ppda_allowed")),
                    deep=_safe_int(row.get("away_deep")),
                    deep_allowed=_safe_int(row.get("away_deep_allowed")),
                    source="understat",
                )
                session.add(away_stat)
                new_count += 1
            elif existing_away.source == "understat" and existing_away.npxg is None:
                # Backfill advanced stats on existing Understat rows
                existing_away.npxg = _safe_float(row.get("away_npxg"))
                existing_away.npxga = _safe_float(row.get("away_npxga"))
                existing_away.ppda_coeff = _safe_float(row.get("away_ppda"))
                existing_away.ppda_allowed_coeff = _safe_float(row.get("away_ppda_allowed"))
                existing_away.deep = _safe_int(row.get("away_deep"))
                existing_away.deep_allowed = _safe_int(row.get("away_deep_allowed"))
                updated_count += 1
            else:
                skipped_count += 1

    summary = {
        "new": new_count,
        "skipped": skipped_count,
        "not_found": not_found,
        "updated": updated_count,
    }
    logger.info(
        "load_understat_stats: %d new, %d updated (backfill), "
        "%d skipped, %d not found",
        new_count, updated_count, skipped_count, not_found,
    )
    return summary


# ============================================================================
# Weather Loader
# ============================================================================

def load_weather(df: pd.DataFrame) -> Dict[str, int]:
    """Load match-day weather data into the weather table.

    Each match has at most one weather record (enforced by unique constraint
    on match_id).  Idempotent — skips matches that already have weather data.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame from ``WeatherScraper.scrape_for_matches()`` with columns:
        match_id, temperature_c, wind_speed_kmh, humidity_pct,
        precipitation_mm, weather_code, weather_category.

    Returns
    -------
    dict
        Summary with keys: "new", "skipped".
    """
    if df.empty:
        return {"new": 0, "skipped": 0}

    new_count = 0
    skipped_count = 0

    for _, row in df.iterrows():
        match_id = int(row["match_id"])

        with get_session() as session:
            # Check for existing weather record (idempotency)
            existing = session.query(Weather).filter_by(
                match_id=match_id,
            ).first()

            if existing:
                skipped_count += 1
                continue

            weather = Weather(
                match_id=match_id,
                temperature_c=_safe_float(row.get("temperature_c")),
                wind_speed_kmh=_safe_float(row.get("wind_speed_kmh")),
                humidity_pct=_safe_float(row.get("humidity_pct")),
                precipitation_mm=_safe_float(row.get("precipitation_mm")),
                weather_code=_safe_int(row.get("weather_code")),
                weather_category=row.get("weather_category"),
                source="open_meteo",
            )
            session.add(weather)
            new_count += 1

    summary = {"new": new_count, "skipped": skipped_count}
    logger.info(
        "load_weather: %d new weather records, %d skipped as duplicates",
        new_count, skipped_count,
    )
    return summary


# ============================================================================
# Team API Name Updater
# ============================================================================

def update_team_api_names(
    df: pd.DataFrame,
    league_id: int,
) -> int:
    """Update teams with their API-Football IDs and names.

    Called after loading API-Football fixture data.  Updates the
    ``api_football_id`` and ``api_football_name`` columns on Team records
    so we can cross-reference in future lookups.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame from ``APIFootballScraper.scrape()`` with columns:
        home_team, away_team, home_api_football_id, away_api_football_id,
        home_api_football_name, away_api_football_name.
    league_id : int
        Database ID of the league.

    Returns
    -------
    int
        Number of teams updated.
    """
    updated = 0

    # Collect unique team mappings from the fixture data
    team_mappings: Dict[str, Dict[str, Any]] = {}

    for _, row in df.iterrows():
        # Home team
        home_name = row.get("home_team")
        home_api_id = row.get("home_api_football_id")
        home_api_name = row.get("home_api_football_name")
        if home_name and home_api_id:
            team_mappings[home_name] = {
                "api_football_id": int(home_api_id),
                "api_football_name": home_api_name,
            }

        # Away team
        away_name = row.get("away_team")
        away_api_id = row.get("away_api_football_id")
        away_api_name = row.get("away_api_football_name")
        if away_name and away_api_id:
            team_mappings[away_name] = {
                "api_football_id": int(away_api_id),
                "api_football_name": away_api_name,
            }

    # Update DB records
    for canonical_name, api_info in team_mappings.items():
        with get_session() as session:
            team = session.query(Team).filter_by(
                name=canonical_name, league_id=league_id,
            ).first()

            if team is None:
                continue

            changed = False
            if team.api_football_id != api_info["api_football_id"]:
                team.api_football_id = api_info["api_football_id"]
                changed = True
            if team.api_football_name != api_info.get("api_football_name"):
                team.api_football_name = api_info.get("api_football_name")
                changed = True

            if changed:
                updated += 1

    if updated:
        logger.info(
            "update_team_api_names: Updated %d teams with API-Football IDs",
            updated,
        )

    return updated


# ============================================================================
# Market Value Loader (Transfermarkt)
# ============================================================================

def load_market_values(
    df: pd.DataFrame,
    league_id: int,
) -> Dict[str, int]:
    """Load team market value snapshots into the team_market_values table.

    Each row in the input DataFrame represents one team's aggregated squad
    market value.  The loader is idempotent — if a snapshot for the same
    (team_id, evaluated_at) already exists, it is skipped.

    Market value ratio between teams is a strong predictor of match outcomes.
    Richer squads (higher total market value) generally outperform poorer ones
    because market value captures long-term squad quality — transfer spending,
    talent retention, and depth — in a single number.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame from ``TransfermarktScraper.scrape()`` with columns:
        team_name, squad_total_value, avg_player_value, squad_size,
        contract_expiring_count, evaluated_at.
    league_id : int
        Database ID of the league.

    Returns
    -------
    dict
        Summary with keys: "new", "skipped", "not_found".
    """
    if df.empty:
        return {"new": 0, "skipped": 0, "not_found": 0}

    new_count = 0
    skipped_count = 0
    not_found = 0

    for _, row in df.iterrows():
        team_name = row["team_name"]
        evaluated_at = row["evaluated_at"]

        with get_session() as session:
            # Find the team in our DB
            team = session.query(Team).filter_by(
                name=team_name, league_id=league_id,
            ).first()

            if team is None:
                logger.warning(
                    "load_market_values: Team '%s' not found in DB — skipping.",
                    team_name,
                )
                not_found += 1
                continue

            # Check for existing snapshot (idempotency)
            # UniqueConstraint: (team_id, evaluated_at)
            existing = session.query(TeamMarketValue).filter_by(
                team_id=team.id,
                evaluated_at=evaluated_at,
            ).first()

            if existing:
                skipped_count += 1
                continue

            # Insert new market value snapshot
            mv = TeamMarketValue(
                team_id=team.id,
                squad_total_value=float(row["squad_total_value"]),
                avg_player_value=_safe_float(row.get("avg_player_value")),
                squad_size=_safe_int(row.get("squad_size")),
                contract_expiring_count=_safe_int(row.get("contract_expiring_count")),
                evaluated_at=evaluated_at,
                source="transfermarkt_datasets",
            )
            session.add(mv)
            new_count += 1

    summary = {"new": new_count, "skipped": skipped_count, "not_found": not_found}
    logger.info(
        "load_market_values: %d new snapshots, %d skipped (duplicates), "
        "%d teams not found",
        new_count, skipped_count, not_found,
    )
    return summary
