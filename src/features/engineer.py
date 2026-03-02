"""
BetVector — Feature Pipeline Orchestrator (E4-03)
===================================================
Combines rolling averages, head-to-head, and context features into a single
pipeline that computes and stores features for all matches in a league-season.

Two main entry points:

  - ``compute_features(match_id)`` — compute all features for a single match
    (both home and away teams), save to the ``features`` table, return as dict.

  - ``compute_all_features(league_id, season)`` — iterate through all matches
    in chronological order, compute and store features for each.  Idempotent —
    skips matches that already have features.  Returns a training-ready
    DataFrame with one row per match and home_*/away_* columns.

The returned DataFrame is the direct input to the prediction models.
Each row represents a match with features for both teams, suitable for
training a Poisson regression or feeding into an XGBoost model.

Master Plan refs: MP §4 Feature Set, MP §6 features table, MP §7 Feature Engineer Interface
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import and_

from src.config import config
from src.database.db import get_session
from src.database.models import Feature, Match, Team
from src.features.context import (
    calculate_congestion_features,
    calculate_context_features,
    calculate_elo_features,
    calculate_market_odds_features,
    calculate_market_value_features,
    calculate_referee_features,
    calculate_weather_features,
)
from src.features.rolling import (
    calculate_rolling_features,
    save_features,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Public API
# ============================================================================

def compute_features(match_id: int, league_id: int) -> Dict[str, Dict[str, Any]]:
    """Compute and save all features for a single match.

    Calculates rolling averages, venue-specific stats, head-to-head,
    rest days, and season progress for both home and away teams.

    Parameters
    ----------
    match_id : int
        Database ID of the match.
    league_id : int
        Database ID of the league.

    Returns
    -------
    dict
        ``{"home": {features...}, "away": {features...}}`` with all
        feature columns from the features table schema.
    """
    windows = config.settings.features.rolling_windows  # [5, 10]

    with get_session() as session:
        match = session.query(Match).filter_by(id=match_id).first()
        if match is None:
            raise ValueError(f"Match {match_id} not found")

        match_date = match.date
        home_team_id = match.home_team_id
        away_team_id = match.away_team_id
        matchday = match.matchday

        # Get team names for logging
        home_team = session.query(Team).filter_by(id=home_team_id).first()
        away_team = session.query(Team).filter_by(id=away_team_id).first()
        home_name = home_team.name if home_team else f"team_{home_team_id}"
        away_name = away_team.name if away_team else f"team_{away_team_id}"

    # Get total matchdays from league config
    league_cfg = _get_league_config(league_id)
    total_matchdays = league_cfg.total_matchdays if league_cfg else 38

    # --- Rolling features for each window ---
    home_features: Dict[str, Any] = {}
    away_features: Dict[str, Any] = {}

    for w in windows:
        home_rolling = calculate_rolling_features(
            home_team_id, match_date, w, league_id, is_home=1,
        )
        away_rolling = calculate_rolling_features(
            away_team_id, match_date, w, league_id, is_home=0,
        )
        home_features.update(home_rolling)
        away_features.update(away_rolling)

    # --- Context features (H2H, rest days, season progress) ---
    home_context = calculate_context_features(
        home_team_id, away_team_id, match_date, league_id,
        matchday=matchday, total_matchdays=total_matchdays,
    )
    away_context = calculate_context_features(
        away_team_id, home_team_id, match_date, league_id,
        matchday=matchday, total_matchdays=total_matchdays,
    )

    home_features.update(home_context)
    away_features.update(away_context)

    # --- Market value features (E16-02) ---
    # Market value ratio captures long-term squad quality — richer squads
    # generally outperform poorer ones.  Uses most recent Transfermarkt
    # snapshot before the match date (temporal integrity).
    home_mv = calculate_market_value_features(
        home_team_id, away_team_id, match_date,
    )
    away_mv = calculate_market_value_features(
        away_team_id, home_team_id, match_date,
    )
    home_features.update(home_mv)
    away_features.update(away_mv)

    # --- Weather features (E16-02) ---
    # Match-day conditions affect scoring rates — heavy rain reduces passing
    # accuracy, strong wind makes long balls unpredictable.  Same weather
    # for both teams (it's the same match).
    weather = calculate_weather_features(match_id)
    home_features.update(weather)
    away_features.update(weather)

    # --- Market-implied features (E20-01, E20-02) ---
    # Pinnacle implied probabilities (overround-removed) and Asian Handicap line.
    # Same market data for both teams — the model learns from the probabilities
    # themselves (e.g., high home_prob → fewer away goals).
    # TEMPORAL INTEGRITY: uses only pre-match (opening) odds.
    home_market = calculate_market_odds_features(match_id, is_home=1)
    away_market = calculate_market_odds_features(match_id, is_home=0)
    home_features.update(home_market)
    away_features.update(away_market)

    # --- Elo rating features (E21-01) ---
    # ClubElo ratings capture long-term team quality beyond rolling form.
    # Especially valuable early in the season when rolling stats are sparse,
    # and for promoted teams whose lower Elo encodes "newly promoted" signal.
    # Each team gets its own elo_rating and elo_diff (team Elo minus opponent Elo).
    home_elo = calculate_elo_features(
        home_team_id, away_team_id, match_date,
    )
    away_elo = calculate_elo_features(
        away_team_id, home_team_id, match_date,
    )
    home_features.update(home_elo)
    away_features.update(away_elo)

    # --- Referee features (E21-02) ---
    # Referee tendencies affect match outcomes — some refs are goal-permissive
    # (high ref_avg_goals), others are strict card-givers.  Same referee for
    # both teams in the same match, so we store identical features on both rows.
    ref_features = calculate_referee_features(match_id)
    home_features.update(ref_features)
    away_features.update(ref_features)

    # --- Fixture congestion features (E21-03) ---
    # Binary signal for <4-day rest periods.  Teams in European competitions
    # (Champions League, Europa League) often play midweek + weekend with
    # only 3 days between matches, causing measurable performance drops.
    home_congestion = calculate_congestion_features(
        home_team_id, match_date, league_id,
    )
    away_congestion = calculate_congestion_features(
        away_team_id, match_date, league_id,
    )
    home_features.update(home_congestion)
    away_features.update(away_congestion)

    # --- Save to database ---
    save_features(match_id, home_team_id, is_home=1, features=home_features)
    save_features(match_id, away_team_id, is_home=0, features=away_features)

    return {"home": home_features, "away": away_features}


def compute_all_features(
    league_id: int,
    season: str,
    force_recompute: bool = False,
) -> pd.DataFrame:
    """Compute and store features for every match in a league-season.

    Iterates through matches in chronological order, computes features
    for each, and stores them in the ``features`` table.  Matches that
    already have features are skipped (idempotent) unless
    ``force_recompute=True``.

    Parameters
    ----------
    league_id : int
        Database ID of the league.
    season : str
        Season identifier, e.g. ``"2024-25"``.
    force_recompute : bool
        If True, recompute features for ALL matches even if they already
        have feature rows.  The existing rows are updated (upsert) with
        the new values.  Use this after adding new feature columns
        (E16-01/E16-02) to populate them for historical matches.

    Returns
    -------
    pd.DataFrame
        Training-ready DataFrame with one row per match.  Columns follow
        the pattern ``home_form_5, home_form_10, ..., away_form_5, ...``.
    """
    # Get all matches in chronological order.
    # Include both finished and scheduled matches — scheduled matches
    # can have features computed because all features are based on data
    # BEFORE the match date (rolling form, xG, H2H, rest days, etc.).
    # This allows the model to generate predictions for upcoming fixtures.
    with get_session() as session:
        matches = session.query(Match).filter(
            Match.league_id == league_id,
            Match.season == season,
            Match.status.in_(("finished", "scheduled")),
        ).order_by(Match.date).all()

        # Collect match info (detach from session)
        match_info = [
            {
                "id": m.id,
                "date": m.date,
                "home_team_id": m.home_team_id,
                "away_team_id": m.away_team_id,
            }
            for m in matches
        ]

    total = len(match_info)
    logger.info(
        "Computing features for %d matches in %s season %s",
        total, _league_name(league_id), season,
    )

    computed = 0
    skipped = 0
    rows: List[Dict[str, Any]] = []

    for i, m in enumerate(match_info):
        match_id = m["id"]

        # Check if features already exist (idempotent)
        with get_session() as session:
            existing_count = session.query(Feature).filter_by(
                match_id=match_id,
            ).count()

        # Get team names for progress message
        with get_session() as session:
            home_team = session.query(Team).filter_by(id=m["home_team_id"]).first()
            away_team = session.query(Team).filter_by(id=m["away_team_id"]).first()
            home_name = home_team.name if home_team else "?"
            away_name = away_team.name if away_team else "?"

        if existing_count >= 2 and not force_recompute:
            # Both home and away features exist — skip (unless force_recompute)
            skipped += 1
            # Still read existing features for the DataFrame
            row = _read_existing_features(match_id, m)
            if row:
                rows.append(row)

            if (i + 1) % 50 == 0 or (i + 1) == total:
                logger.info(
                    "Computing features: match %d/%d (%s vs %s, %s) — skipped",
                    i + 1, total, home_name, away_name, m["date"],
                )
            continue

        # Compute features for this match
        logger.info(
            "Computing features: match %d/%d (%s vs %s, %s)",
            i + 1, total, home_name, away_name, m["date"],
        )
        features = compute_features(match_id, league_id)
        computed += 1

        # Build a flat row for the training DataFrame
        row = _flatten_features(match_id, m, features)
        rows.append(row)

    logger.info(
        "Feature computation complete: %d computed, %d skipped, %d total",
        computed, skipped, total,
    )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


# ============================================================================
# Internal helpers
# ============================================================================

def _flatten_features(
    match_id: int,
    match_info: Dict[str, Any],
    features: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Flatten home/away feature dicts into a single row for the DataFrame.

    Prefixes home features with ``home_`` and away features with ``away_``.
    Shared features (matchday, season_progress) are not duplicated.
    """
    row: Dict[str, Any] = {
        "match_id": match_id,
        "date": match_info["date"],
        "home_team_id": match_info["home_team_id"],
        "away_team_id": match_info["away_team_id"],
    }

    home = features.get("home", {})
    away = features.get("away", {})

    # Rolling and venue features get prefixed
    for key, val in home.items():
        if key in ("matchday", "season_progress"):
            row[key] = val  # Shared — same for both teams
        else:
            row[f"home_{key}"] = val

    for key, val in away.items():
        if key in ("matchday", "season_progress"):
            continue  # Already added from home
        row[f"away_{key}"] = val

    return row


def _read_existing_features(
    match_id: int,
    match_info: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Read existing features from the database and flatten into a row."""
    with get_session() as session:
        home_feat = session.query(Feature).filter_by(
            match_id=match_id, is_home=1,
        ).first()
        away_feat = session.query(Feature).filter_by(
            match_id=match_id, is_home=0,
        ).first()

    if home_feat is None or away_feat is None:
        return None

    row: Dict[str, Any] = {
        "match_id": match_id,
        "date": match_info["date"],
        "home_team_id": match_info["home_team_id"],
        "away_team_id": match_info["away_team_id"],
    }

    # Feature columns from the Feature model (excluding metadata)
    feature_cols = [
        "form_5", "goals_scored_5", "goals_conceded_5",
        "xg_5", "xga_5", "xg_diff_5", "shots_5", "shots_on_target_5",
        "possession_5",
        # Advanced stats — 5-match window (E16-01)
        "npxg_5", "npxga_5", "npxg_diff_5",
        "ppda_5", "ppda_allowed_5", "deep_5", "deep_allowed_5",
        "form_10", "goals_scored_10", "goals_conceded_10",
        "xg_10", "xga_10", "xg_diff_10", "shots_10", "shots_on_target_10",
        "possession_10",
        # Advanced stats — 10-match window (E16-01)
        "npxg_10", "npxga_10", "npxg_diff_10",
        "ppda_10", "ppda_allowed_10", "deep_10", "deep_allowed_10",
        "venue_form_5", "venue_goals_scored_5", "venue_goals_conceded_5",
        "venue_xg_5", "venue_xga_5",
        "h2h_wins", "h2h_draws", "h2h_losses",
        "h2h_goals_scored", "h2h_goals_conceded",
        "rest_days",
        # Market value + weather features (E16-02)
        "market_value_ratio", "squad_value_log",
        "temperature_c", "wind_speed_kmh", "precipitation_mm",
        "is_heavy_weather",
        # Market-implied features (E20-01, E20-02)
        "pinnacle_home_prob", "pinnacle_draw_prob", "pinnacle_away_prob",
        "pinnacle_overround", "ah_line",
        # Elo rating features (E21-01)
        "elo_rating", "elo_diff",
        # Referee features (E21-02)
        "ref_avg_fouls", "ref_avg_yellows", "ref_avg_goals", "ref_home_win_pct",
        # Fixture congestion features (E21-03)
        "days_since_last_match", "is_congested",
        # Set-piece xG breakdown (E22-01)
        "set_piece_xg_5", "open_play_xg_5",
    ]

    for col in feature_cols:
        row[f"home_{col}"] = getattr(home_feat, col, None)
        row[f"away_{col}"] = getattr(away_feat, col, None)

    row["matchday"] = home_feat.matchday
    row["season_progress"] = home_feat.season_progress

    return row


def _get_league_config(league_id: int):
    """Look up league config by database ID."""
    with get_session() as session:
        from src.database.models import League
        league = session.query(League).filter_by(id=league_id).first()
        if league is None:
            return None
        short_name = league.short_name

    for lg in config.leagues:
        if lg.short_name == short_name:
            return lg
    return None


def _league_name(league_id: int) -> str:
    """Get league short name for logging."""
    with get_session() as session:
        from src.database.models import League
        league = session.query(League).filter_by(id=league_id).first()
        return league.short_name if league else f"league_{league_id}"
