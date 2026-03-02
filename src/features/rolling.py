"""
BetVector — Rolling Feature Calculator (E4-01, extended E16-01)
================================================================
Computes rolling team performance features over configurable match windows.

For each team entering a match, we look back at their most recent N
completed matches (where N comes from ``config/settings.yaml``, default
[5, 10]) and compute averages for:

  - **Form:** Points per game (Win=3, Draw=1, Loss=0)
  - **Attack:** Goals scored per game, xG per game, shots, shots on target
  - **Defence:** Goals conceded per game, xGA per game
  - **Style:** Possession average
  - **xG difference:** xG minus xGA — measures overall performance quality
  - **NPxG / NPxGA:** Non-penalty expected goals (more predictive than raw xG)
  - **PPDA:** Passes Per Defensive Action (pressing intensity metric)
  - **Deep completions:** Passes reaching the opponent's penalty area

Additionally, **venue-specific** features use only matches at the same
venue (home or away) over a 5-match window, capturing the well-documented
home advantage effect in football.

TEMPORAL INTEGRITY (CRITICAL):
  Every feature calculation uses ONLY matches with ``date < match_date``.
  The match being predicted is NEVER included.  This is the #1 constraint
  in the entire system — violating it invalidates all predictions.

Master Plan refs: MP §4 Feature Set, MP §6 features table schema
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import and_
from sqlalchemy.orm import Session

from src.config import config
from src.database.db import get_session
from src.database.models import Feature, Match, MatchStat, Team

logger = logging.getLogger(__name__)

# Points awarded per match result (standard football scoring)
POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0


# ============================================================================
# Public API
# ============================================================================

def calculate_rolling_features(
    team_id: int,
    match_date: str,
    window: int,
    league_id: int,
    is_home: int,
) -> Dict[str, Any]:
    """Calculate rolling features for a team going into a match.

    Looks back at the team's most recent ``window`` completed matches
    (strictly before ``match_date``) and computes per-game averages.

    Parameters
    ----------
    team_id : int
        Database ID of the team.
    match_date : str
        ISO date of the match being predicted (YYYY-MM-DD).
        Features use ONLY matches before this date.
    window : int
        Number of recent matches to include (e.g. 5 or 10).
    league_id : int
        Database ID of the league (for scoping queries).
    is_home : int
        1 if the team is playing at home, 0 if away.
        Used for venue-specific features.

    Returns
    -------
    dict
        Feature name → value.  Keys follow the pattern ``{stat}_{window}``
        (e.g. ``form_5``, ``xg_10``).  Returns None values for teams
        with zero prior matches.
    """
    with get_session() as session:
        # Get the team's recent matches (before match_date)
        recent = _get_recent_matches(
            session, team_id, match_date, league_id, limit=window,
        )

        # Compute overall rolling features
        features = _compute_rolling_stats(recent, team_id, window)

        # Compute venue-specific features (5-match window at same venue)
        if window == 5:
            venue_recent = _get_recent_matches(
                session, team_id, match_date, league_id,
                limit=5, venue_filter=is_home,
            )
            venue_features = _compute_venue_stats(venue_recent, team_id)
            features.update(venue_features)

    return features


def compute_all_rolling_features(
    match_id: int,
    league_id: int,
) -> Dict[str, Dict[str, Any]]:
    """Compute rolling features for both teams in a match.

    Returns a dict with keys ``"home"`` and ``"away"``, each containing
    the full feature dict for that team.

    Parameters
    ----------
    match_id : int
        Database ID of the match.
    league_id : int
        Database ID of the league.

    Returns
    -------
    dict
        ``{"home": {features...}, "away": {features...}}``
    """
    windows = config.settings.features.rolling_windows  # [5, 10]

    with get_session() as session:
        match = session.query(Match).filter_by(id=match_id).first()
        if match is None:
            raise ValueError(f"Match {match_id} not found")

        match_date = match.date
        home_team_id = match.home_team_id
        away_team_id = match.away_team_id

    # Calculate features for each window and merge
    home_features: Dict[str, Any] = {}
    away_features: Dict[str, Any] = {}

    for w in windows:
        home_w = calculate_rolling_features(
            home_team_id, match_date, w, league_id, is_home=1,
        )
        away_w = calculate_rolling_features(
            away_team_id, match_date, w, league_id, is_home=0,
        )
        home_features.update(home_w)
        away_features.update(away_w)

    return {"home": home_features, "away": away_features}


def save_features(
    match_id: int,
    team_id: int,
    is_home: int,
    features: Dict[str, Any],
) -> None:
    """Save computed features to the database (idempotent).

    If a feature row already exists for this match/team combination,
    it is updated.  Otherwise a new row is inserted.
    """
    with get_session() as session:
        existing = session.query(Feature).filter_by(
            match_id=match_id, team_id=team_id,
        ).first()

        if existing:
            # Update existing record
            for key, val in features.items():
                if hasattr(existing, key):
                    setattr(existing, key, val)
            logger.info(
                "Updated features for match=%d, team=%d", match_id, team_id,
            )
        else:
            # Insert new record
            feature = Feature(
                match_id=match_id,
                team_id=team_id,
                is_home=is_home,
                **{k: v for k, v in features.items() if hasattr(Feature, k)},
            )
            session.add(feature)
            logger.info(
                "Saved features for match=%d, team=%d", match_id, team_id,
            )


# ============================================================================
# Internal helpers
# ============================================================================

def _get_recent_matches(
    session: Session,
    team_id: int,
    before_date: str,
    league_id: int,
    limit: int,
    venue_filter: Optional[int] = None,
) -> pd.DataFrame:
    """Fetch a team's most recent completed matches before a date.

    Returns a DataFrame with one row per match, sorted by date descending
    (most recent first), limited to ``limit`` rows.

    Parameters
    ----------
    session : Session
        Active SQLAlchemy session.
    team_id : int
        Team to look up.
    before_date : str
        Only include matches strictly before this date.
    league_id : int
        League scope.
    limit : int
        Maximum number of matches to return.
    venue_filter : int, optional
        If 1, only home matches.  If 0, only away matches.
        If None, all matches regardless of venue.
    """
    # Query matches where this team played (home or away), before the date,
    # and the match is finished (has a result)
    query = session.query(Match).filter(
        Match.league_id == league_id,
        Match.date < before_date,
        Match.status == "finished",
        (
            (Match.home_team_id == team_id) |
            (Match.away_team_id == team_id)
        ),
    )

    # Apply venue filter if requested
    if venue_filter == 1:
        query = query.filter(Match.home_team_id == team_id)
    elif venue_filter == 0:
        query = query.filter(Match.away_team_id == team_id)

    # Order by date descending (most recent first) and limit
    matches = query.order_by(Match.date.desc()).limit(limit).all()

    if not matches:
        return pd.DataFrame()

    # Build a flat DataFrame with the stats we need
    rows = []
    for m in matches:
        is_home = 1 if m.home_team_id == team_id else 0

        # Goals scored and conceded from the team's perspective
        if is_home:
            goals_scored = m.home_goals
            goals_conceded = m.away_goals
        else:
            goals_scored = m.away_goals
            goals_conceded = m.home_goals

        # Points earned
        if goals_scored is not None and goals_conceded is not None:
            if goals_scored > goals_conceded:
                points = POINTS_WIN
            elif goals_scored == goals_conceded:
                points = POINTS_DRAW
            else:
                points = POINTS_LOSS
        else:
            points = None

        # Try to get match stats (xG, shots, possession) from match_stats
        stat = session.query(MatchStat).filter_by(
            match_id=m.id, team_id=team_id,
        ).first()

        rows.append({
            "match_id": m.id,
            "date": m.date,
            "is_home": is_home,
            "goals_scored": goals_scored,
            "goals_conceded": goals_conceded,
            "points": points,
            "xg": stat.xg if stat else None,
            "xga": stat.xga if stat else None,
            "shots": stat.shots if stat else None,
            "shots_on_target": stat.shots_on_target if stat else None,
            "possession": stat.possession if stat else None,
            # --- Advanced stats from Understat (E16-01) ---
            # NPxG strips penalty xG (penalties convert at ~76% regardless of
            # team) making it more predictive of future open-play performance.
            "npxg": stat.npxg if stat else None,
            "npxga": stat.npxga if stat else None,
            # PPDA = opponent passes / team defensive actions.  Lower values
            # mean more aggressive pressing (Liverpool ~8, Burnley ~18).
            "ppda": stat.ppda_coeff if stat else None,
            "ppda_allowed": stat.ppda_allowed_coeff if stat else None,
            # Deep completions = passes reaching near the opponent's box.
            # Measures attacking penetration quality beyond just shots/xG.
            "deep": stat.deep if stat else None,
            "deep_allowed": stat.deep_allowed if stat else None,
        })

    return pd.DataFrame(rows)


def _compute_rolling_stats(
    df: pd.DataFrame,
    team_id: int,
    window: int,
) -> Dict[str, Any]:
    """Compute rolling average features from recent match data.

    If the DataFrame has fewer rows than ``window``, uses all available
    matches.  If empty, returns None for all features.

    Feature naming: ``{stat}_{window}`` (e.g. ``form_5``, ``xg_10``).
    """
    suffix = f"_{window}"

    # No prior matches — return all None
    if df.empty:
        return {
            f"form{suffix}": None,
            f"goals_scored{suffix}": None,
            f"goals_conceded{suffix}": None,
            f"xg{suffix}": None,
            f"xga{suffix}": None,
            f"xg_diff{suffix}": None,
            f"shots{suffix}": None,
            f"shots_on_target{suffix}": None,
            f"possession{suffix}": None,
            # Advanced stats (E16-01)
            f"npxg{suffix}": None,
            f"npxga{suffix}": None,
            f"npxg_diff{suffix}": None,
            f"ppda{suffix}": None,
            f"ppda_allowed{suffix}": None,
            f"deep{suffix}": None,
            f"deep_allowed{suffix}": None,
        }

    n = len(df)  # Actual matches available (may be < window)

    # Points per game (form)
    # Win=3, Draw=1, Loss=0 — higher is better
    form = _safe_mean(df["points"])

    # Goals per game
    goals_scored = _safe_mean(df["goals_scored"])
    goals_conceded = _safe_mean(df["goals_conceded"])

    # xG per game (expected goals — may be None if FBref data unavailable)
    xg = _safe_mean(df["xg"])
    xga = _safe_mean(df["xga"])

    # xG difference: positive = outperforming opponents, negative = underperforming
    if xg is not None and xga is not None:
        xg_diff = xg - xga
    else:
        xg_diff = None

    # Shots
    shots = _safe_mean(df["shots"])
    shots_on_target = _safe_mean(df["shots_on_target"])

    # Possession (already stored as 0.0–1.0 proportion)
    possession = _safe_mean(df["possession"])

    # --- Advanced stats from Understat (E16-01) ---
    # NPxG = non-penalty expected goals.  Strips penalty xG which converts
    # at ~76% regardless of team, making NPxG a purer measure of open-play
    # chance creation.  NPxGA is the defensive counterpart.
    npxg = _safe_mean(df["npxg"])
    npxga = _safe_mean(df["npxga"])
    if npxg is not None and npxga is not None:
        npxg_diff = round(npxg - npxga, 4)
    else:
        npxg_diff = None

    # PPDA = Passes Per Defensive Action.  A pressing intensity metric:
    # how many passes does the opponent complete before the team wins the
    # ball?  Lower = more aggressive pressing.  Teams with low PPDA tend
    # to create more turnovers in dangerous areas.
    ppda = _safe_mean(df["ppda"])
    ppda_allowed = _safe_mean(df["ppda_allowed"])

    # Deep completions = passes that reach the opponent's penalty area.
    # Measures quality of attacking buildup — a team can have high
    # possession but low deep completions if they just pass sideways.
    deep = _safe_mean(df["deep"])
    deep_allowed = _safe_mean(df["deep_allowed"])

    return {
        f"form{suffix}": form,
        f"goals_scored{suffix}": goals_scored,
        f"goals_conceded{suffix}": goals_conceded,
        f"xg{suffix}": xg,
        f"xga{suffix}": xga,
        f"xg_diff{suffix}": xg_diff,
        f"shots{suffix}": shots,
        f"shots_on_target{suffix}": shots_on_target,
        f"possession{suffix}": possession,
        # Advanced stats (E16-01)
        f"npxg{suffix}": npxg,
        f"npxga{suffix}": npxga,
        f"npxg_diff{suffix}": npxg_diff,
        f"ppda{suffix}": ppda,
        f"ppda_allowed{suffix}": ppda_allowed,
        f"deep{suffix}": deep,
        f"deep_allowed{suffix}": deep_allowed,
    }


def _compute_venue_stats(
    df: pd.DataFrame,
    team_id: int,
) -> Dict[str, Any]:
    """Compute venue-specific rolling features (5-match window).

    These capture the home advantage effect — teams typically score more,
    concede less, and have better xG at home than away.

    Feature naming: ``venue_{stat}_5``
    """
    if df.empty:
        return {
            "venue_form_5": None,
            "venue_goals_scored_5": None,
            "venue_goals_conceded_5": None,
            "venue_xg_5": None,
            "venue_xga_5": None,
        }

    return {
        "venue_form_5": _safe_mean(df["points"]),
        "venue_goals_scored_5": _safe_mean(df["goals_scored"]),
        "venue_goals_conceded_5": _safe_mean(df["goals_conceded"]),
        "venue_xg_5": _safe_mean(df["xg"]),
        "venue_xga_5": _safe_mean(df["xga"]),
    }


def _safe_mean(series: pd.Series) -> Optional[float]:
    """Calculate mean of a series, ignoring NaN.  Returns None if all NaN."""
    valid = series.dropna()
    if valid.empty:
        return None
    return round(float(valid.mean()), 4)
