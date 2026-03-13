"""
BetVector — Feature Pipeline Orchestrator (E4-03)
===================================================
Combines rolling averages, head-to-head, and context features into a single
pipeline that computes and stores features for all matches in a league-season.

Three main entry points:

  - ``compute_features(match_id)`` — compute all features for a single match
    (both home and away teams), save to the ``features`` table, return as dict.

  - ``compute_all_features(league_id, season)`` — iterate through all matches
    in chronological order, compute and store features for each.  Idempotent —
    skips matches that already have features.  Returns a training-ready
    DataFrame with one row per match and home_*/away_* columns.

  - ``load_features_bulk(league_id, seasons)`` — bulk-load pre-computed
    features for multiple seasons in 2 DB queries (PC-10-01).  Use this
    for loading historical training data instead of calling
    ``compute_all_features()`` in a loop.

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
    calculate_bench_strength,
    calculate_congestion_features,
    calculate_context_features,
    calculate_elo_features,
    calculate_formation_change,
    calculate_injury_features,
    calculate_is_newly_promoted,
    calculate_league_home_advantage,
    calculate_manager_features,
    calculate_market_odds_features,
    calculate_market_value_features,
    calculate_referee_features,
    calculate_squad_rotation,
    calculate_weather_features,
)
from src.features.rolling import (
    calculate_rolling_features,
    save_features,
)

logger = logging.getLogger(__name__)

# ============================================================================
# Shared feature column list (PC-10-02)
# ============================================================================
# Single source of truth for all feature columns read from the Feature model.
# Used by load_features_bulk(), compute_all_features(), and
# _read_existing_features() to ensure identical DataFrame output.
# When adding new feature columns, update THIS list only.
# ============================================================================

FEATURE_COLS = [
    # --- Rolling form (5-match) — Source: Match table (all leagues) ---
    "form_5", "goals_scored_5", "goals_conceded_5",
    # --- xG rolling (5-match) — Source: Understat (all except Championship) ---
    "xg_5", "xga_5", "xg_diff_5",
    # --- FBref columns — PERMANENTLY NULL (Cloudflare blocked since Jan 2026) ---
    "shots_5", "shots_on_target_5", "possession_5",
    # --- Advanced stats 5-match (E16-01) — Source: Understat (not Championship) ---
    "npxg_5", "npxga_5", "npxg_diff_5",
    "ppda_5", "ppda_allowed_5", "deep_5", "deep_allowed_5",
    # --- Rolling form (10-match) — Source: Match table (all leagues) ---
    "form_10", "goals_scored_10", "goals_conceded_10",
    # --- xG rolling (10-match) — Source: Understat (all except Championship) ---
    "xg_10", "xga_10", "xg_diff_10",
    # --- FBref columns — PERMANENTLY NULL (see DATA_GAPS.md §2) ---
    "shots_10", "shots_on_target_10", "possession_10",
    # --- Advanced stats 10-match (E16-01) — Source: Understat (not Championship) ---
    "npxg_10", "npxga_10", "npxg_diff_10",
    "ppda_10", "ppda_allowed_10", "deep_10", "deep_allowed_10",
    # --- Venue-specific (5-match, home/away only) — Source: Match + Understat ---
    "venue_form_5", "venue_goals_scored_5", "venue_goals_conceded_5",
    "venue_xg_5", "venue_xga_5",
    # --- Head-to-head (last 5 meetings) — Source: Match table (all leagues) ---
    "h2h_wins", "h2h_draws", "h2h_losses",
    "h2h_goals_scored", "h2h_goals_conceded",
    # --- Context — Source: Match table (all leagues) ---
    "rest_days",
    # --- Market value (E16-02) — Source: Transfermarkt CDN (current snapshot only) ---
    "market_value_ratio", "squad_value_log",
    # --- Weather (E16-02) — Source: Open-Meteo API (all leagues, needs backfill) ---
    "temperature_c", "wind_speed_kmh", "precipitation_mm",
    "is_heavy_weather",
    # --- Market-implied (E20-01, E20-02) — Source: The Odds API / Pinnacle ---
    "pinnacle_home_prob", "pinnacle_draw_prob", "pinnacle_away_prob",
    "pinnacle_overround", "ah_line",
    # --- Elo ratings (E21-01) — Source: ClubElo API + internal Elo (all leagues) ---
    "elo_rating", "elo_diff",
    # --- Referee (E21-02) — Source: Football-Data CSVs (EPL + Championship ONLY) ---
    "ref_avg_fouls", "ref_avg_yellows", "ref_avg_goals", "ref_home_win_pct",
    # --- Fixture congestion (E21-03) — Source: Match table (all leagues) ---
    "days_since_last_match", "is_congested",
    # --- Set-piece xG (E22-01) — Source: Understat shot data (not Championship) ---
    "set_piece_xg_5", "open_play_xg_5",
    # --- Injury impact (E22-02) — Source: API-Football + manual flags ---
    "injury_impact", "key_player_out",
    # --- Multi-league context (E36-03) — Source: Match table (all leagues) ---
    "league_home_adv_5", "is_newly_promoted",
    # --- Lineup features (E39-09, E39-10, E39-11) — Source: Soccerdata lineups ---
    "squad_rotation_index", "formation_changed", "bench_strength",
    # --- Manager features (E40-05) — Source: Transfermarkt games table ---
    "new_manager_flag", "manager_tenure_days",
    "manager_win_pct", "manager_change_count",
]


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

        # PC-14-04: Compute matchday when NULL — count distinct match dates
        # in the same (league_id, season) on or before this match's date.
        # This gives a sequential matchday number (1, 2, 3, ...).
        if matchday is None and match_date and match.season:
            from sqlalchemy import func as sa_func
            distinct_dates = (
                session.query(sa_func.count(sa_func.distinct(Match.date)))
                .filter(
                    Match.league_id == league_id,
                    Match.season == match.season,
                    Match.date <= match_date,
                )
                .scalar()
            ) or 0
            matchday = distinct_dates
            # Persist computed matchday back to the Match row
            match.matchday = matchday
            session.commit()

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

    # --- Injury impact features (E22-02, E39-04) ---
    # For upcoming matches (no match_date or future date): reads live InjuryFlag
    # table populated by Soccerdata API (E39-02).
    # For historical matches (match_date in the past): reads team_injuries table
    # with temporal filtering (only injuries active on that date) and uses
    # PlayerValue percentile as the impact_rating (E39-04).
    home_injury = calculate_injury_features(home_team_id, match_date=match_date)
    away_injury = calculate_injury_features(away_team_id, match_date=match_date)
    home_features.update(home_injury)
    away_features.update(away_injury)

    # --- Squad rotation index (E39-09) ---
    # Fraction of starting XI changed vs the team's previous match.
    # 0.0 = identical XI, 1.0 = completely different lineup.
    # NULL when no lineup data available (models handle via fillna).
    home_rotation = calculate_squad_rotation(
        home_team_id, match_id, match_date, league_id,
    )
    away_rotation = calculate_squad_rotation(
        away_team_id, match_id, match_date, league_id,
    )
    home_features.update(home_rotation)
    away_features.update(away_rotation)

    # --- Formation change (E39-10) ---
    # Binary flag: 1 if the team's formation differs from their previous
    # match, 0 if same.  NULL when formation data is unavailable.
    home_formation = calculate_formation_change(
        home_team_id, match_id, match_date, league_id,
    )
    away_formation = calculate_formation_change(
        away_team_id, match_id, match_date, league_id,
    )
    home_features.update(home_formation)
    away_features.update(away_formation)

    # --- Bench strength (E39-11) ---
    # Ratio of bench total market value to starter total market value.
    # Higher ratio = deeper squad = better ability to handle rotation.
    # NULL when no lineup or PlayerValue data available.
    home_bench = calculate_bench_strength(
        home_team_id, match_id, match_date,
    )
    away_bench = calculate_bench_strength(
        away_team_id, match_id, match_date,
    )
    home_features.update(home_bench)
    away_features.update(away_bench)

    # --- Multi-league context features (E36-03) ---

    # League home advantage (rolling 5-match window).
    # Captures the actual observed home-field advantage in this specific league,
    # which differs across EPL (~0.3 goals), Championship (~0.4), La Liga (~0.25).
    # Same value for both home and away teams — it's a match/league-level stat.
    league_ha = calculate_league_home_advantage(league_id, match_date, window=5)
    home_features.update(league_ha)
    away_features.update(league_ha)

    # Newly promoted team flag.
    # 1 if the team did not appear in this league last season (first season
    # after promotion).  Promoted teams face a substantial quality step-up
    # and systematically underperform pre-match form expectations.
    # Computed per-team — different for home vs away.
    home_promoted = calculate_is_newly_promoted(
        home_team_id, league_id, match_date,
    )
    away_promoted = calculate_is_newly_promoted(
        away_team_id, league_id, match_date,
    )
    home_features.update(home_promoted)
    away_features.update(away_promoted)

    # --- Manager features (E40-05) ---
    # Manager changes create a measurable short-term "bounce" effect.
    # 4 features: new_manager_flag, manager_tenure_days, manager_win_pct,
    # and manager_change_count.  Each team has its own manager, so these
    # are computed per-team.  NULL when no manager data available.
    home_manager = calculate_manager_features(
        home_team_id, match_id, match_date, league_id,
    )
    away_manager = calculate_manager_features(
        away_team_id, match_id, match_date, league_id,
    )
    home_features.update(home_manager)
    away_features.update(away_manager)

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
    league_name_str = _league_name(league_id)
    logger.info(
        "Computing features for %d matches in %s season %s",
        total, league_name_str, season,
    )

    # --- PC-10-02: Bulk pre-load to avoid per-match DB queries ---
    # Instead of 5 queries per match (existence check, 2 team lookups,
    # 2 feature reads), we pre-load everything in 3 bulk queries and
    # use dict lookups in the loop.  For a 380-match season this
    # reduces DB hits from ~1,900 to 3.

    all_match_ids = [m["id"] for m in match_info]

    # Bulk query 1: Which matches already have features?
    # Build a set of match_ids that have ≥2 feature rows (home + away).
    existing_feature_counts: Dict[int, int] = {}
    with get_session() as session:
        from sqlalchemy import func
        count_rows = (
            session.query(Feature.match_id, func.count(Feature.id))
            .filter(Feature.match_id.in_(all_match_ids))
            .group_by(Feature.match_id)
            .all()
        )
        for mid, cnt in count_rows:
            existing_feature_counts[mid] = cnt

    # Bulk query 2: Pre-load team names for progress logging.
    # Collect all unique team IDs from match_info, load in one query.
    all_team_ids = set()
    for m in match_info:
        all_team_ids.add(m["home_team_id"])
        all_team_ids.add(m["away_team_id"])

    team_names: Dict[int, str] = {}
    with get_session() as session:
        teams = session.query(Team).filter(Team.id.in_(list(all_team_ids))).all()
        for t in teams:
            team_names[t.id] = t.name

    # Bulk query 3: Pre-load all existing Feature rows for matches
    # that already have features, so we can build the DataFrame without
    # per-match _read_existing_features() calls.
    # Only load for matches we'll skip (existing_count >= 2).
    skip_ids = [
        mid for mid in all_match_ids
        if existing_feature_counts.get(mid, 0) >= 2
    ]
    pre_loaded_features: Dict[int, Dict[int, Feature]] = {}
    if skip_ids and not force_recompute:
        CHUNK_SIZE = 5000
        with get_session() as session:
            for ci in range(0, len(skip_ids), CHUNK_SIZE):
                chunk = skip_ids[ci : ci + CHUNK_SIZE]
                feats = (
                    session.query(Feature)
                    .filter(Feature.match_id.in_(chunk))
                    .all()
                )
                for f in feats:
                    # Force attribute load while session is open
                    _ = f.match_id, f.is_home, f.matchday, f.season_progress
                    if f.match_id not in pre_loaded_features:
                        pre_loaded_features[f.match_id] = {}
                    pre_loaded_features[f.match_id][f.is_home] = f

    computed = 0
    skipped = 0
    rows: List[Dict[str, Any]] = []

    for i, m in enumerate(match_info):
        match_id = m["id"]

        # Use pre-loaded counts instead of per-match DB query
        existing_count = existing_feature_counts.get(match_id, 0)

        # Use pre-loaded team names instead of per-match DB query
        home_name = team_names.get(m["home_team_id"], "?")
        away_name = team_names.get(m["away_team_id"], "?")

        if existing_count >= 2 and not force_recompute:
            # Both home and away features exist — skip (unless force_recompute)
            skipped += 1

            # Use pre-loaded features instead of per-match _read_existing_features()
            feat_pair = pre_loaded_features.get(match_id, {})
            home_feat = feat_pair.get(1)
            away_feat = feat_pair.get(0)

            if home_feat is not None and away_feat is not None:
                row: Dict[str, Any] = {
                    "match_id": match_id,
                    "date": m["date"],
                    "home_team_id": m["home_team_id"],
                    "away_team_id": m["away_team_id"],
                }
                for col in FEATURE_COLS:
                    row[f"home_{col}"] = getattr(home_feat, col, None)
                    row[f"away_{col}"] = getattr(away_feat, col, None)
                row["matchday"] = home_feat.matchday
                row["season_progress"] = home_feat.season_progress
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


def load_features_bulk(
    league_id: int,
    seasons: List[str],
) -> pd.DataFrame:
    """Bulk-load pre-computed features for multiple seasons (PC-10-01).

    This is a read-only, high-performance alternative to calling
    ``compute_all_features()`` in a loop for historical seasons.
    Instead of 5 DB queries per match (existence check, 2 team lookups,
    2 feature reads), this function uses **exactly 2 ORM queries** total:

    1. Fetch all matches for the given league + seasons.
    2. Fetch all Feature rows for those match IDs in bulk.

    For 13,000 historical matches this reduces DB hits from ~65,000 to 2,
    cutting historical feature loading from ~20 minutes to ~5 seconds.

    Parameters
    ----------
    league_id : int
        Database ID of the league.
    seasons : list[str]
        Season identifiers to load, e.g. ``["2020-21", "2021-22", ...]``.

    Returns
    -------
    pd.DataFrame
        Training-ready DataFrame with one row per match.  Same column
        format as ``compute_all_features()`` output — ``match_id``,
        ``date``, ``home_team_id``, ``away_team_id``, ``matchday``,
        ``season_progress``, plus ``home_*`` / ``away_*`` feature columns.
        Matches that lack both home and away features are silently skipped.
    """
    if not seasons:
        return pd.DataFrame()

    # --- Query 1: All matches for this league across requested seasons ---
    with get_session() as session:
        matches = (
            session.query(Match)
            .filter(
                Match.league_id == league_id,
                Match.season.in_(seasons),
                Match.status.in_(("finished", "scheduled")),
            )
            .order_by(Match.date)
            .all()
        )

        # Detach match info from session
        match_lookup = {}
        match_ids = []
        for m in matches:
            match_lookup[m.id] = {
                "id": m.id,
                "date": m.date,
                "home_team_id": m.home_team_id,
                "away_team_id": m.away_team_id,
            }
            match_ids.append(m.id)

    if not match_ids:
        logger.info(
            "Bulk load: no matches found for %s seasons %s",
            _league_name(league_id), ", ".join(seasons),
        )
        return pd.DataFrame()

    # --- Query 2: All Feature rows for those matches in one shot ---
    # SQLAlchemy's IN clause handles large lists; for very large sets
    # (>10K), we chunk to avoid parameter limits on some DB backends.
    CHUNK_SIZE = 5000
    all_features_raw: List[Feature] = []

    with get_session() as session:
        for i in range(0, len(match_ids), CHUNK_SIZE):
            chunk = match_ids[i : i + CHUNK_SIZE]
            features_chunk = (
                session.query(Feature)
                .filter(Feature.match_id.in_(chunk))
                .all()
            )
            # Detach from session by accessing attributes while session is open
            for f in features_chunk:
                # Force attribute load before session closes
                _ = f.match_id, f.is_home, f.matchday, f.season_progress
            all_features_raw.extend(features_chunk)

    # Build a nested dict: {match_id: {is_home(1/0): Feature}}
    feature_map: Dict[int, Dict[int, Feature]] = {}
    for feat in all_features_raw:
        if feat.match_id not in feature_map:
            feature_map[feat.match_id] = {}
        feature_map[feat.match_id][feat.is_home] = feat

    # --- Flatten into rows (same format as _read_existing_features) ---
    # Uses module-level FEATURE_COLS constant for column list consistency.
    rows: List[Dict[str, Any]] = []
    skipped = 0

    for mid in match_ids:
        feats = feature_map.get(mid, {})
        home_feat = feats.get(1)
        away_feat = feats.get(0)

        # Skip matches that don't have both home and away features
        if home_feat is None or away_feat is None:
            skipped += 1
            continue

        m_info = match_lookup[mid]
        row: Dict[str, Any] = {
            "match_id": mid,
            "date": m_info["date"],
            "home_team_id": m_info["home_team_id"],
            "away_team_id": m_info["away_team_id"],
        }

        for col in FEATURE_COLS:
            row[f"home_{col}"] = getattr(home_feat, col, None)
            row[f"away_{col}"] = getattr(away_feat, col, None)

        row["matchday"] = home_feat.matchday
        row["season_progress"] = home_feat.season_progress

        rows.append(row)

    logger.info(
        "Bulk-loaded %d features for %d matches across %d seasons "
        "(skipped %d without features) for %s",
        len(rows), len(match_ids), len(seasons), skipped,
        _league_name(league_id),
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

    # Uses module-level FEATURE_COLS constant (PC-10-02 DRY fix)
    for col in FEATURE_COLS:
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
