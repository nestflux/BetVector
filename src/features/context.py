"""
BetVector — Head-to-Head and Context Features (E4-02)
======================================================
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

TEMPORAL INTEGRITY: All features use only data from before the match date.

Master Plan refs: MP §4 Feature Set, MP §6 features table schema
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.database.db import get_session
from src.database.models import Match

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
