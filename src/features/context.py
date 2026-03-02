"""
BetVector — Head-to-Head and Context Features (E4-02, extended E16-02)
======================================================================
Computes contextual features that go beyond rolling team form:

  - **Head-to-head (H2H):** Historical record between two specific teams
    over their last 5 meetings.  Includes wins, draws, losses, and average
    goals scored/conceded.  H2H data captures rivalry effects and stylistic
    matchup advantages that rolling form alone doesn't reveal.

  - **Rest days:** Days since each team's last match.  Short rest (2-3 days
    between midweek and weekend matches) correlates with lower performance,
    especially for away teams.  Default of 7 days for season openers.

  - **Season progress:** How far through the season the match falls (0.0 to
    1.0).  Early-season matches have more variance (small sample), while
    late-season matches may have motivational effects (relegation battles,
    title races, "dead rubber" matches with nothing to play for).

  - **Market value ratio (E16-02):** Ratio of this team's squad value to
    the opponent's.  Uses the most recent Transfermarkt snapshot before the
    match date.  Richer squads generally outperform poorer ones — a €1B
    squad facing a €200M squad has a 5:1 structural advantage.

  - **Weather conditions (E16-02):** Match-day temperature, wind speed,
    precipitation from Open-Meteo.  Heavy rain and strong wind reduce
    goal-scoring rates and favour direct-play teams.

TEMPORAL INTEGRITY: All features use only data from before the match date.

Master Plan refs: MP §4 Feature Set, MP §6 features table schema
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.database.db import get_session
from src.database.models import Match, TeamMarketValue, Weather

logger = logging.getLogger(__name__)

# Default rest days for a team's first match of the season.
# 7 days is a reasonable assumption — teams typically play a pre-season
# friendly within a week of the season opener.
DEFAULT_REST_DAYS = 7


# ============================================================================
# Head-to-Head Features
# ============================================================================

def calculate_h2h_features(
    team_id: int,
    opponent_id: int,
    match_date: str,
    league_id: int,
    limit: int = 5,
) -> Dict[str, Any]:
    """Calculate head-to-head features from recent meetings between two teams.

    Looks at the last ``limit`` meetings between ``team_id`` and
    ``opponent_id`` (regardless of venue) strictly before ``match_date``.

    Parameters
    ----------
    team_id : int
        The team whose perspective we're computing from.
    opponent_id : int
        The opposing team.
    match_date : str
        ISO date — only H2H matches before this date are included.
    league_id : int
        League scope.
    limit : int
        Maximum number of H2H meetings to look back (default 5).

    Returns
    -------
    dict
        Keys: h2h_wins, h2h_draws, h2h_losses, h2h_goals_scored,
        h2h_goals_conceded.  Returns zeros for all if no prior meetings.
    """
    with get_session() as session:
        # Find matches where these two teams played each other (either venue)
        h2h_matches = session.query(Match).filter(
            Match.league_id == league_id,
            Match.date < match_date,
            Match.status == "finished",
            (
                # team_id at home vs opponent_id
                (
                    (Match.home_team_id == team_id) &
                    (Match.away_team_id == opponent_id)
                ) |
                # team_id away vs opponent_id
                (
                    (Match.home_team_id == opponent_id) &
                    (Match.away_team_id == team_id)
                )
            ),
        ).order_by(Match.date.desc()).limit(limit).all()

    # No prior meetings — return zeros (not None, per AC 4)
    if not h2h_matches:
        return {
            "h2h_wins": 0,
            "h2h_draws": 0,
            "h2h_losses": 0,
            "h2h_goals_scored": 0.0,
            "h2h_goals_conceded": 0.0,
        }

    wins = 0
    draws = 0
    losses = 0
    total_scored = 0
    total_conceded = 0

    for m in h2h_matches:
        # Determine goals from team_id's perspective
        if m.home_team_id == team_id:
            scored = m.home_goals or 0
            conceded = m.away_goals or 0
        else:
            scored = m.away_goals or 0
            conceded = m.home_goals or 0

        total_scored += scored
        total_conceded += conceded

        if scored > conceded:
            wins += 1
        elif scored == conceded:
            draws += 1
        else:
            losses += 1

    n = len(h2h_matches)

    return {
        "h2h_wins": wins,
        "h2h_draws": draws,
        "h2h_losses": losses,
        # Average goals per H2H meeting
        "h2h_goals_scored": round(total_scored / n, 4),
        "h2h_goals_conceded": round(total_conceded / n, 4),
    }


# ============================================================================
# Rest Days
# ============================================================================

def calculate_rest_days(
    team_id: int,
    match_date: str,
    league_id: int,
) -> int:
    """Calculate days since the team's most recent match.

    Parameters
    ----------
    team_id : int
        Team to check.
    match_date : str
        ISO date of the upcoming match.
    league_id : int
        League scope.

    Returns
    -------
    int
        Number of days since last match.  Returns ``DEFAULT_REST_DAYS``
        (7) if the team has no prior matches (e.g. season opener).
    """
    with get_session() as session:
        # Find the team's most recent completed match before this date
        last_match = session.query(Match).filter(
            Match.league_id == league_id,
            Match.date < match_date,
            Match.status == "finished",
            (
                (Match.home_team_id == team_id) |
                (Match.away_team_id == team_id)
            ),
        ).order_by(Match.date.desc()).first()

    if last_match is None:
        logger.info(
            "No prior match for team %d before %s — using default %d days",
            team_id, match_date, DEFAULT_REST_DAYS,
        )
        return DEFAULT_REST_DAYS

    # Calculate days between the two dates
    current_dt = datetime.strptime(match_date, "%Y-%m-%d")
    last_dt = datetime.strptime(last_match.date, "%Y-%m-%d")
    delta = (current_dt - last_dt).days

    return delta


# ============================================================================
# Season Progress
# ============================================================================

def calculate_season_progress(
    matchday: Optional[int],
    total_matchdays: int = 38,
) -> float:
    """Calculate how far through the season a match falls.

    Parameters
    ----------
    matchday : int or None
        The matchday number (1-based).  If None, returns 0.0.
    total_matchdays : int
        Total matchdays in the season (38 for EPL).

    Returns
    -------
    float
        Value between 0.0 (season start) and 1.0 (season end).
        Matchday 1 → ~0.026, matchday 19 → 0.5, matchday 38 → 1.0.
    """
    if matchday is None or matchday < 1:
        return 0.0

    # Clamp to valid range (in case of data issues)
    matchday = min(matchday, total_matchdays)

    return round(matchday / total_matchdays, 4)


# ============================================================================
# Combined context features
# ============================================================================

def calculate_context_features(
    team_id: int,
    opponent_id: int,
    match_date: str,
    league_id: int,
    matchday: Optional[int] = None,
    total_matchdays: int = 38,
) -> Dict[str, Any]:
    """Calculate all context features for a team going into a match.

    Combines H2H, rest days, and season progress into a single dict
    ready for saving to the features table.

    Parameters
    ----------
    team_id : int
        The team whose features we're computing.
    opponent_id : int
        The opposing team.
    match_date : str
        ISO date of the match.
    league_id : int
        League scope.
    matchday : int, optional
        Matchday number in the season.
    total_matchdays : int
        Total matchdays (default 38 for EPL).

    Returns
    -------
    dict
        Combined features: h2h_wins, h2h_draws, h2h_losses,
        h2h_goals_scored, h2h_goals_conceded, rest_days, matchday,
        season_progress.
    """
    # Head-to-head
    h2h = calculate_h2h_features(
        team_id, opponent_id, match_date, league_id,
    )

    # Rest days
    rest = calculate_rest_days(team_id, match_date, league_id)

    # Season progress
    progress = calculate_season_progress(matchday, total_matchdays)

    return {
        **h2h,
        "rest_days": rest,
        "matchday": matchday,
        "season_progress": progress,
    }


# ============================================================================
# Market Value Features (E16-02)
# ============================================================================

# Maximum market value ratio — caps extreme outliers (e.g., Man City vs newly
# promoted team) to prevent a single feature from dominating the model.
MAX_MV_RATIO = 10.0


def calculate_market_value_features(
    team_id: int,
    opponent_id: int,
    match_date: str,
) -> Dict[str, Any]:
    """Calculate market value features from Transfermarkt squad value data.

    Uses the most recent Transfermarkt snapshot **on or before** the match
    date for each team.  Market value snapshots are static weekly snapshots
    of player valuations — they are NOT influenced by match results on the
    same date, so ``<=`` is temporally safe (unlike match stats which use
    ``<`` to avoid including the predicted match).

    The market value ratio captures long-term squad quality.  A team with a
    €1B squad facing a €200M squad has a 5:1 structural advantage that goes
    beyond recent form — it reflects transfer spending, talent retention,
    squad depth, and the overall quality ceiling of the roster.

    Parameters
    ----------
    team_id : int
        The team whose features we're computing.
    opponent_id : int
        The opposing team.
    match_date : str
        ISO date of the match (YYYY-MM-DD).

    Returns
    -------
    dict
        Keys: market_value_ratio, squad_value_log.
        Returns None for both if no market value data exists.
    """
    with get_session() as session:
        # Get most recent snapshot for this team BEFORE match date
        team_mv = session.query(TeamMarketValue).filter(
            TeamMarketValue.team_id == team_id,
            TeamMarketValue.evaluated_at <= match_date,
        ).order_by(TeamMarketValue.evaluated_at.desc()).first()

        # Get most recent snapshot for opponent BEFORE match date
        opp_mv = session.query(TeamMarketValue).filter(
            TeamMarketValue.team_id == opponent_id,
            TeamMarketValue.evaluated_at <= match_date,
        ).order_by(TeamMarketValue.evaluated_at.desc()).first()

    # No data for this team — return None (graceful degradation)
    if team_mv is None or team_mv.squad_total_value is None:
        return {
            "market_value_ratio": None,
            "squad_value_log": None,
        }

    # Compute log of squad value (natural log, normalises the massive range)
    squad_value = team_mv.squad_total_value
    squad_value_log = round(math.log(max(squad_value, 1.0)), 4)

    # Compute ratio: team value / opponent value
    if opp_mv is not None and opp_mv.squad_total_value and opp_mv.squad_total_value > 0:
        ratio = squad_value / opp_mv.squad_total_value
        # Cap at MAX_MV_RATIO to prevent extreme outliers
        ratio = min(ratio, MAX_MV_RATIO)
        ratio = round(ratio, 4)
    else:
        # No opponent data — use 1.0 (neutral assumption)
        ratio = None

    return {
        "market_value_ratio": ratio,
        "squad_value_log": squad_value_log,
    }


# ============================================================================
# Weather Features (E16-02)
# ============================================================================

# Thresholds for "heavy weather" conditions that affect match outcomes.
# These are based on football analytics research:
#   - Precipitation > 2mm: wet pitch reduces passing accuracy, increases
#     turnovers, and slightly reduces overall goals scored.
#   - Wind > 30 km/h: strong wind makes long balls unpredictable, favours
#     direct-play teams over possession-based ones.
HEAVY_RAIN_THRESHOLD_MM = 2.0
STRONG_WIND_THRESHOLD_KMH = 30.0


def calculate_weather_features(
    match_id: int,
) -> Dict[str, Any]:
    """Calculate weather features for a specific match.

    Reads weather data from the ``weather`` table (populated by the
    Open-Meteo scraper in E14-02).  Weather is per-match, not per-team
    — both teams experience the same conditions.

    Parameters
    ----------
    match_id : int
        Database ID of the match.

    Returns
    -------
    dict
        Keys: temperature_c, wind_speed_kmh, precipitation_mm, is_heavy_weather.
        Returns None for all if no weather data exists for this match.
    """
    with get_session() as session:
        weather = session.query(Weather).filter_by(match_id=match_id).first()

    if weather is None:
        return {
            "temperature_c": None,
            "wind_speed_kmh": None,
            "precipitation_mm": None,
            "is_heavy_weather": None,
        }

    # Extract raw values
    temp = weather.temperature_c
    wind = weather.wind_speed_kmh
    precip = weather.precipitation_mm

    # Determine if conditions significantly affect play
    is_heavy = 0
    if precip is not None and precip > HEAVY_RAIN_THRESHOLD_MM:
        is_heavy = 1
    if wind is not None and wind > STRONG_WIND_THRESHOLD_KMH:
        is_heavy = 1

    return {
        "temperature_c": round(temp, 2) if temp is not None else None,
        "wind_speed_kmh": round(wind, 2) if wind is not None else None,
        "precipitation_mm": round(precip, 2) if precip is not None else None,
        "is_heavy_weather": is_heavy,
    }
