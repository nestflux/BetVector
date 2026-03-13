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
from src.database.models import (
    ClubElo, InjuryFlag, Match, MatchLineup, Odds, PlayerValue,
    TeamInjury, TeamMarketValue, Weather,
)

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


# ============================================================================
# Market-Implied Features (E20-01, E20-02)
# ============================================================================
# The sharpest bookmaker odds encode vast amounts of information — team news,
# public sentiment, sharp money, and historical patterns — all compressed into
# a single decimal number.  By converting Pinnacle odds to implied probabilities
# (with overround removed) and feeding them as features, the model gets access
# to "what the market thinks" alongside its own statistical analysis.
#
# This is the single highest-impact feature addition available:
#   - Pinnacle 1X2 implied probs: 7-9% Brier score improvement (Constantinou 2022)
#   - Asian Handicap line: 2-4% additional improvement
#
# TEMPORAL INTEGRITY: We use pre-match (opening) odds only.  These are published
# hours/days before kickoff and are available at prediction time.  We never use
# closing odds as features — those are only known at kickoff (after predictions).
# ============================================================================


def calculate_market_odds_features(
    match_id: int,
    is_home: int,
) -> Dict[str, Any]:
    """Calculate market-implied features from Pinnacle odds and AH line.

    For a given match, fetches Pinnacle 1X2 opening odds, removes the
    overround to get true implied probabilities, and fetches the Asian
    Handicap line.

    The features are the same for both home and away teams in the same
    match, BUT which probability the model uses depends on is_home:
    the home team's "pinnacle_home_prob" is the probability of a home win,
    while the away team's "pinnacle_home_prob" is also the probability of
    a home win — but from the away team's row perspective, this tells the
    model "how likely is the home team to beat me?"

    Actually, to keep it simple and let the model learn the relationships,
    we store the same three probabilities on both home and away Feature rows.
    The model already knows which row is home/away via the is_home flag.

    Parameters
    ----------
    match_id : int
        Database ID of the match.
    is_home : int
        1 if computing for the home team, 0 for away.
        (Currently unused — same features for both sides.)

    Returns
    -------
    dict
        Keys: pinnacle_home_prob, pinnacle_draw_prob, pinnacle_away_prob,
        pinnacle_overround, ah_line.
        All values are None if no data is available.
    """
    empty = {
        "pinnacle_home_prob": None,
        "pinnacle_draw_prob": None,
        "pinnacle_away_prob": None,
        "pinnacle_overround": None,
        "ah_line": None,
    }

    with get_session() as session:
        # --- Pinnacle 1X2 odds ---
        # Prefer opening odds (is_opening=1) — these are available before the
        # match and are temporally safe to use as features.
        # Fall back to any available Pinnacle 1X2 odds if no opening odds exist
        # (e.g., older historical data where we only have closing odds from CSV).
        pinnacle_1x2 = (
            session.query(Odds)
            .filter(
                Odds.match_id == match_id,
                Odds.bookmaker == "Pinnacle",
                Odds.market_type == "1X2",
            )
            .order_by(Odds.is_opening.desc())  # Opening (1) first, closing (0) second
            .all()
        )

        # Group by selection to get home/draw/away odds
        odds_by_selection: Dict[str, float] = {}
        is_opening_used = None
        for o in pinnacle_1x2:
            if o.selection not in odds_by_selection:
                odds_by_selection[o.selection] = o.odds_decimal
                is_opening_used = o.is_opening

        home_odds = odds_by_selection.get("home")
        draw_odds = odds_by_selection.get("draw")
        away_odds = odds_by_selection.get("away")

        # --- Compute implied probabilities (overround-removed) ---
        result = dict(empty)  # Start with empty defaults

        if home_odds and draw_odds and away_odds:
            if home_odds > 1.0 and draw_odds > 1.0 and away_odds > 1.0:
                # Raw implied probabilities (include overround)
                raw_home = 1.0 / home_odds
                raw_draw = 1.0 / draw_odds
                raw_away = 1.0 / away_odds
                raw_sum = raw_home + raw_draw + raw_away

                # Overround = how much above 100% the raw probs sum to.
                # Pinnacle typically runs 2-4% (1.02-1.04).
                overround = raw_sum - 1.0

                # Proportional overround removal (multiplicative method):
                # Divide each raw prob by the sum so they add to exactly 1.0.
                # This is the standard approach and preserves relative probabilities.
                true_home = raw_home / raw_sum
                true_draw = raw_draw / raw_sum
                true_away = raw_away / raw_sum

                result["pinnacle_home_prob"] = round(true_home, 6)
                result["pinnacle_draw_prob"] = round(true_draw, 6)
                result["pinnacle_away_prob"] = round(true_away, 6)
                result["pinnacle_overround"] = round(overround, 6)

                logger.debug(
                    "Pinnacle 1X2 for match %d: H=%.3f D=%.3f A=%.3f "
                    "(overround=%.3f, opening=%s)",
                    match_id, true_home, true_draw, true_away,
                    overround, is_opening_used,
                )

        # --- Asian Handicap line (E20-02) ---
        # The AH line is the sharpest market-implied strength difference.
        # Stored as Odds with market_type="AH", selection="home_line".
        # The odds_decimal IS the line value (e.g., -0.5, -1.0, +0.5).
        # Prefer Pinnacle, fall back to market_avg.
        ah_row = (
            session.query(Odds)
            .filter(
                Odds.match_id == match_id,
                Odds.market_type == "AH",
                Odds.selection == "home_line",
                Odds.bookmaker == "Pinnacle",
            )
            .first()
        )
        if ah_row is None:
            # Fall back to Betbrain market average
            ah_row = (
                session.query(Odds)
                .filter(
                    Odds.match_id == match_id,
                    Odds.market_type == "AH",
                    Odds.selection == "home_line",
                    Odds.bookmaker == "market_avg",
                )
                .first()
            )

        if ah_row is not None and ah_row.odds_decimal is not None:
            result["ah_line"] = round(ah_row.odds_decimal, 4)
            logger.debug(
                "AH line for match %d: %.2f (bookmaker=%s)",
                match_id, ah_row.odds_decimal, ah_row.bookmaker,
            )

    return result


# ============================================================================
# Elo Rating Features (E21-01)
# ============================================================================
# Elo ratings from ClubElo capture LONG-TERM team quality — unlike rolling form
# which only looks at the last 5-10 matches.  The key insight is that a team
# losing 3 in a row doesn't suddenly become weak — their Elo barely changes.
# Conversely, a newly promoted team may have a winning run early on, but their
# Elo correctly reflects they're still weaker than established EPL teams.
#
# The Elo DIFFERENCE between teams is especially predictive:
#   - Elo diff > 200: heavy favourite (e.g., Man City vs newly promoted)
#   - Elo diff ~0: evenly matched teams
#   - Elo diff < -200: heavy underdog
#
# Expected Brier improvement: 1-8% (larger for promoted teams, early season).
#
# TEMPORAL INTEGRITY: Uses the most recent Elo rating BEFORE the match date.
# ClubElo updates ratings after each round, so using ratings "on or before"
# the match date is safe — those ratings were known before kickoff.
# ============================================================================


def calculate_elo_features(
    team_id: int,
    opponent_id: int,
    match_date: str,
) -> Dict[str, Any]:
    """Calculate Elo rating features for a team in a specific match.

    Looks up the most recent ClubElo rating for both the team and its
    opponent on or before the match date, then computes the Elo difference.

    Parameters
    ----------
    team_id : int
        Database ID of the team whose features we're computing.
    opponent_id : int
        Database ID of the opposing team.
    match_date : str
        ISO date of the match (YYYY-MM-DD).  Only ratings on or before
        this date are considered (temporal integrity).

    Returns
    -------
    dict
        Keys: elo_rating, elo_diff.
        - elo_rating: this team's Elo rating on match date
        - elo_diff: this team's Elo minus opponent's Elo
          (positive = this team is stronger)
        Returns None for both if no Elo data exists.
    """
    with get_session() as session:
        # Get the most recent Elo rating for THIS team on or before match date.
        # ClubElo publishes daily snapshots; the most recent one reflects all
        # results up to that date and is temporally safe to use.
        team_elo = (
            session.query(ClubElo)
            .filter(
                ClubElo.team_id == team_id,
                ClubElo.rating_date <= match_date,
            )
            .order_by(ClubElo.rating_date.desc())
            .first()
        )

        # Get the most recent Elo rating for the OPPONENT on or before match date
        opp_elo = (
            session.query(ClubElo)
            .filter(
                ClubElo.team_id == opponent_id,
                ClubElo.rating_date <= match_date,
            )
            .order_by(ClubElo.rating_date.desc())
            .first()
        )

    # No Elo data for this team — return None (graceful degradation)
    if team_elo is None:
        return {
            "elo_rating": None,
            "elo_diff": None,
        }

    team_rating = round(team_elo.elo_rating, 1)

    # Compute Elo difference if opponent data exists
    if opp_elo is not None:
        elo_diff = round(team_elo.elo_rating - opp_elo.elo_rating, 1)
    else:
        # No opponent Elo — can't compute difference
        elo_diff = None

    logger.debug(
        "Elo features for team %d vs %d on %s: rating=%.1f, diff=%s",
        team_id, opponent_id, match_date,
        team_rating, elo_diff,
    )

    return {
        "elo_rating": team_rating,
        "elo_diff": elo_diff,
    }


# ============================================================================
# Referee Features (E21-02)
# ============================================================================
# Referees have measurable tendencies that affect match outcomes:
#
# 1. **Goal-permissive referees:** Some refs allow physical play and fewer
#    stoppages, leading to more fluid attacking play and more goals.  Others
#    are strict card-givers who break up play frequently, lowering goal totals.
#    This is captured by ref_avg_goals — average total goals in their matches.
#
# 2. **Home bias signal:** Research consistently shows referees make more
#    favourable decisions for the home team (Sutter & Kocher 2004, Dohmen 2008).
#    ref_home_win_pct captures the intensity of this bias for each referee.
#    A ref with 55% home win rate is roughly neutral; 65%+ signals strong
#    home advantage amplification.
#
# 3. **Disciplinary tendencies:** ref_avg_fouls and ref_avg_yellows capture
#    how strictly a referee enforces the laws.  High-discipline refs may
#    disrupt the rhythm of technical teams (affecting O/U predictions).
#
# Expected Brier improvement: 1-2% for BTTS/O/U markets.
#
# TEMPORAL INTEGRITY: Only uses matches BEFORE the match date.
# MINIMUM SAMPLE: Requires at least 5 matches for statistical reliability.
# ============================================================================

# Minimum number of historical matches a referee must have for features to
# be computed.  With fewer than this, the averages are unreliable noise.
MIN_REFEREE_MATCHES = 5

# Maximum number of recent matches to include in referee averages.
# Using a rolling window (like 20 matches) prevents ancient results from
# diluting current tendencies, since refs' styles do evolve over time.
MAX_REFEREE_LOOKBACK = 20


def calculate_referee_features(
    match_id: int,
) -> Dict[str, Any]:
    """Calculate referee tendency features for a specific match.

    Looks up the referee assigned to this match, then queries the last
    ``MAX_REFEREE_LOOKBACK`` matches officiated by the same referee
    (strictly before this match date) to compute disciplinary and scoring
    averages.

    Parameters
    ----------
    match_id : int
        Database ID of the match.

    Returns
    -------
    dict
        Keys: ref_avg_fouls, ref_avg_yellows, ref_avg_goals, ref_home_win_pct.
        All values are None if referee is unknown or sample size is too small.
    """
    empty = {
        "ref_avg_fouls": None,
        "ref_avg_yellows": None,
        "ref_avg_goals": None,
        "ref_home_win_pct": None,
    }

    with get_session() as session:
        # Get this match's referee
        match = session.query(Match).filter_by(id=match_id).first()
        if match is None or not match.referee:
            return empty

        referee_name = match.referee.strip()
        match_date = match.date

        # Query the referee's recent matches BEFORE this match date.
        # Temporal integrity: we only know about matches that happened before
        # the prediction date.  The referee's future performance is unknown.
        ref_matches = (
            session.query(Match)
            .filter(
                Match.referee == referee_name,
                Match.date < match_date,
                Match.home_goals.isnot(None),  # Only finished matches
            )
            .order_by(Match.date.desc())
            .limit(MAX_REFEREE_LOOKBACK)
            .all()
        )

        # Minimum sample size check — with fewer than 5 matches, averages
        # are unreliable and could introduce noise rather than signal.
        if len(ref_matches) < MIN_REFEREE_MATCHES:
            logger.debug(
                "Referee '%s': only %d matches (need %d) — skipping features",
                referee_name, len(ref_matches), MIN_REFEREE_MATCHES,
            )
            return empty

        # Compute averages from the referee's match history
        total_goals = 0
        home_wins = 0
        total_fouls = 0
        total_yellows = 0
        fouls_count = 0  # Track how many matches have fouls data
        yellows_count = 0  # Track how many matches have yellow card data

        for rm in ref_matches:
            # Goals (always available for finished matches)
            total_goals += (rm.home_goals or 0) + (rm.away_goals or 0)

            # Home win detection
            if rm.home_goals is not None and rm.away_goals is not None:
                if rm.home_goals > rm.away_goals:
                    home_wins += 1

            # Fouls and yellow cards — may not be available for all matches.
            # The match_stats table has fouls/yellow_cards per team.
            # Sum home + away for total per match.
            from src.database.models import MatchStat
            stats = session.query(MatchStat).filter_by(match_id=rm.id).all()
            match_fouls = 0
            match_yellows = 0
            has_fouls = False
            has_yellows = False

            for stat in stats:
                if stat.fouls is not None:
                    match_fouls += stat.fouls
                    has_fouls = True
                if stat.yellow_cards is not None:
                    match_yellows += stat.yellow_cards
                    has_yellows = True

            if has_fouls:
                total_fouls += match_fouls
                fouls_count += 1
            if has_yellows:
                total_yellows += match_yellows
                yellows_count += 1

        n = len(ref_matches)

        result = {
            "ref_avg_goals": round(total_goals / n, 3),
            "ref_home_win_pct": round(home_wins / n, 3),
            # Fouls/yellows: only compute if we have data for at least
            # MIN_REFEREE_MATCHES matches.  Otherwise return None.
            "ref_avg_fouls": (
                round(total_fouls / fouls_count, 3)
                if fouls_count >= MIN_REFEREE_MATCHES
                else None
            ),
            "ref_avg_yellows": (
                round(total_yellows / yellows_count, 3)
                if yellows_count >= MIN_REFEREE_MATCHES
                else None
            ),
        }

        logger.debug(
            "Referee '%s': %d matches → goals=%.2f, home_win=%.1f%%, "
            "fouls=%s, yellows=%s",
            referee_name, n,
            result["ref_avg_goals"],
            result["ref_home_win_pct"] * 100,
            result["ref_avg_fouls"],
            result["ref_avg_yellows"],
        )

    return result


# ============================================================================
# Fixture Congestion Features (E21-03)
# ============================================================================
# Teams playing multiple matches in quick succession (midweek + weekend)
# suffer measurable performance drops:
#   - Reduced pressing intensity (less energy for high-press systems)
#   - Higher injury risk (fatigue-related muscle injuries spike)
#   - More squad rotation (weaker lineups, less cohesion)
#
# The <4-day threshold is the widely accepted congestion boundary in
# European football (Carling et al. 2015, Bengtsson et al. 2013):
#   - 3 days rest (e.g., Wednesday → Saturday): congested
#   - 4+ days rest: normal recovery window
#
# This is especially impactful for teams competing in European competitions
# alongside the EPL — they play midweek Champions League/Europa League
# followed by a weekend EPL match with only 3 days between them.
#
# days_since_last_match: integer days (same as rest_days but stored as
# a separate feature column for explicit model access)
# is_congested: binary flag (1 if <4 days, 0 otherwise)
#
# Expected Brier improvement: 2-3% for European competitors.
# ============================================================================

# Congestion threshold — fewer than this many days between matches
# signals significant fatigue effects.
CONGESTION_THRESHOLD_DAYS = 4


def calculate_congestion_features(
    team_id: int,
    match_date: str,
    league_id: int,
) -> Dict[str, Any]:
    """Calculate fixture congestion features for a team.

    Determines how many days since the team's last match and whether
    they're in a congested fixture period (<4 days between matches).

    This function reuses the same logic as ``calculate_rest_days()`` but
    returns both the raw days value and a binary congestion flag.

    Parameters
    ----------
    team_id : int
        Database ID of the team.
    match_date : str
        ISO date of the match (YYYY-MM-DD).
    league_id : int
        Database ID of the league.

    Returns
    -------
    dict
        Keys: days_since_last_match, is_congested.
        Returns None for days_since_last_match if this is the team's first
        match (no prior match).  is_congested defaults to 0 in that case.
    """
    # Reuse the existing rest_days calculation which handles all edge cases
    # (first match of season → DEFAULT_REST_DAYS).
    rest = calculate_rest_days(team_id, match_date, league_id)

    # rest_days returns DEFAULT_REST_DAYS (7) for first match of season.
    # In that case, days_since_last_match should be None (we genuinely
    # don't know when they last played) and is_congested should be 0
    # (7 days is definitely not congested).
    if rest == DEFAULT_REST_DAYS:
        # Check if this is genuinely 7 days rest or the default
        with get_session() as session:
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
            # First match of season — no prior data
            return {
                "days_since_last_match": None,
                "is_congested": 0,  # Not congested (no prior match)
            }

    # Normal case: we have a real rest days value
    is_congested = 1 if rest < CONGESTION_THRESHOLD_DAYS else 0

    return {
        "days_since_last_match": rest,
        "is_congested": is_congested,
    }


# ============================================================================
# Injury Impact Features (E22-02)
# ============================================================================

# Threshold for "key player" status.  Players with impact_rating >= this
# value trigger the key_player_out binary flag.  0.7 corresponds to the
# "key player" tier in the impact rating scale.
KEY_PLAYER_THRESHOLD = 0.7


def calculate_injury_features(
    team_id: int,
    match_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Calculate injury impact features for a team.

    Two modes of operation (E39-04):

    **Live mode (match_date=None):**
      Reads active injury flags (status='out' or 'suspended') from the
      ``injury_flags`` table.  Used for upcoming match predictions where
      we have current sidelined data from the Soccerdata API.

    **Historical mode (match_date='2024-01-15'):**
      Reads from the ``team_injuries`` table, filtering for injuries that
      were active on the given date:
        - ``reported_at <= match_date``
        - ``expected_return IS NULL OR expected_return > match_date``
      Cross-references ``PlayerValue`` to compute impact ratings from
      market value percentile within the squad.  This allows backtesting
      to reconstruct who was injured on any past matchday.

    Features computed:

    - **injury_impact**: sum of impact_ratings for all absent players.
      Higher value = more players missing = weaker squad.  A team
      missing Haaland (1.0) + De Bruyne (0.9) has injury_impact = 1.9;
      full-strength = 0.0.

    - **key_player_out**: binary flag, 1 if ANY absent player has
      impact_rating >= 0.7.  Captures the "star player missing" signal.

    Parameters
    ----------
    team_id : int
        Database ID of the team.
    match_date : str, optional
        If provided (YYYY-MM-DD), use historical ``team_injuries`` table
        instead of live ``injury_flags``.

    Returns
    -------
    dict
        ``{"injury_impact": float, "key_player_out": int}``
    """
    default = {"injury_impact": 0.0, "key_player_out": 0}

    if match_date is None:
        # --- Live mode: read from injury_flags (current state) ---
        with get_session() as session:
            active_flags = session.query(InjuryFlag).filter(
                InjuryFlag.team_id == team_id,
                InjuryFlag.status.in_(("out", "suspended")),
            ).all()

        if not active_flags:
            return default

        total_impact = sum(f.impact_rating for f in active_flags)
        has_key = any(
            f.impact_rating >= KEY_PLAYER_THRESHOLD
            for f in active_flags
        )
        return {
            "injury_impact": round(total_impact, 2),
            "key_player_out": 1 if has_key else 0,
        }

    # --- Historical mode: read from team_injuries for a specific date ---
    # TEMPORAL INTEGRITY: only injuries reported on or before match_date,
    # and where the player had NOT returned by match_date.
    with get_session() as session:
        injuries = session.query(TeamInjury).filter(
            TeamInjury.team_id == team_id,
            TeamInjury.reported_at <= match_date,
            # Player still out on match_date: no return date, or
            # return date is AFTER the match date
            (
                (TeamInjury.expected_return.is_(None))
                | (TeamInjury.expected_return > match_date)
            ),
        ).all()

        if not injuries:
            return default

        # Build PlayerValue percentile lookup for this team to compute
        # impact_rating.  Uses the latest PlayerValue snapshot (the same
        # percentile is used for all historical dates — acceptable since
        # market value rank within a squad is relatively stable).
        pvs = session.query(PlayerValue).filter_by(
            team_id=team_id,
        ).all()
        pv_percentile: Dict[str, float] = {
            pv.player_name.lower().strip(): pv.value_percentile
            for pv in pvs
        }

    # Compute features from historical injuries
    total_impact = 0.0
    has_key = False
    for inj in injuries:
        # Use PlayerValue percentile as impact_rating
        impact = pv_percentile.get(
            inj.player_name.lower().strip(),
            0.5,  # Default if player not in PlayerValue table
        )
        total_impact += impact
        if impact >= KEY_PLAYER_THRESHOLD:
            has_key = True

    return {
        "injury_impact": round(total_impact, 2),
        "key_player_out": 1 if has_key else 0,
    }


# ============================================================================
# League Home Advantage Feature (E36-03)
# ============================================================================
# Home advantage varies significantly by league:
#   EPL:         ~0.3 goals/match (moderate — large away fan sections,
#                 continental travel not an issue within England)
#   Championship:~0.4 goals/match (stronger — larger home crowds relative
#                 to away allocations, more physical long-distance away trips)
#   La Liga:     ~0.25 goals/match (lower — more technical play,
#                 shorter travel distances across Spain)
#
# Rather than hard-coding these constants, we compute the rolling actual
# home advantage from recent league matches.  This automatically captures
# seasonal variation and adapts as the league's style evolves over time.
#
# league_home_adv_5 = mean(home_goals - away_goals) over the last 5
# COMPLETED matches in this league before the match date.
# Same value stored on both home and away Feature rows for a match.
# ============================================================================

# Minimum matches needed to compute a reliable league home advantage.
# With fewer than this, the average is too noisy.
MIN_LEAGUE_HOME_ADV_MATCHES = 3


def calculate_league_home_advantage(
    league_id: int,
    match_date: str,
    window: int = 5,
) -> Dict[str, Any]:
    """Calculate rolling league-level home advantage.

    Looks at the last ``window`` completed matches in this league before
    ``match_date`` and returns the average home goal advantage (home goals
    minus away goals per match).

    A positive value means home teams score more (the normal case).
    Values close to 0 indicate weak or no home advantage in this league
    for recent matches.

    Parameters
    ----------
    league_id : int
        Database ID of the league.
    match_date : str
        ISO date — only matches BEFORE this date are included.
    window : int
        Number of recent league matches to average over (default 5).

    Returns
    -------
    dict
        Keys: league_home_adv_5.
        Returns None if fewer than MIN_LEAGUE_HOME_ADV_MATCHES exist.
    """
    with get_session() as session:
        # Get the most recent ``window`` FINISHED league matches before this date.
        # TEMPORAL INTEGRITY: strictly before match_date — we cannot know the
        # result of the match being predicted, so we exclude it.
        recent = (
            session.query(Match)
            .filter(
                Match.league_id == league_id,
                Match.date < match_date,
                Match.status == "finished",
                Match.home_goals.isnot(None),
                Match.away_goals.isnot(None),
            )
            .order_by(Match.date.desc())
            .limit(window)
            .all()
        )

    if len(recent) < MIN_LEAGUE_HOME_ADV_MATCHES:
        # Not enough data yet (early season or first season in this league)
        return {"league_home_adv_5": None}

    # Average home-minus-away goal differential across recent matches.
    # Positive means home teams are scoring more than away teams.
    diffs = [
        (m.home_goals or 0) - (m.away_goals or 0)
        for m in recent
    ]
    avg_adv = round(sum(diffs) / len(diffs), 4)

    logger.debug(
        "League home advantage (league_id=%d, before %s, window=%d): %.3f",
        league_id, match_date, window, avg_adv,
    )

    return {"league_home_adv_5": avg_adv}


# ============================================================================
# Newly Promoted Team Feature (E36-03)
# ============================================================================
# Teams promoted from a lower division face a significant quality jump.
# For example, a Championship team promoted to the EPL typically struggles
# because opponents are substantially stronger.  The Elo system captures
# this (promoted teams start with lower Elo), but an explicit binary flag
# helps the model identify this pattern directly.
#
# A team is "newly promoted" if it did NOT appear in the same league
# during the immediately preceding season.  We determine the prior season
# by looking at which season_id in the same league has a start date just
# before the current match date.
#
# TEMPORAL INTEGRITY:
#   - We only check completed matches from the prior season.
#   - We never use data from future seasons.
#   - "is False when no prior season in DB" — this treats the earliest
#     season in our DB as "established" (safe default: no false promotion flags).
# ============================================================================


def calculate_is_newly_promoted(
    team_id: int,
    league_id: int,
    match_date: str,
) -> Dict[str, Any]:
    """Check whether this team is playing in this league for the first time.

    Determines the current season from match records in the database, then
    checks whether this team appeared in the prior season of the same league.
    If not, the team is newly promoted.

    Strategy: instead of relying on Season.start_date (which may be NULL for
    some records), we determine the current season string by finding the most
    recent season in the matches table for this league with match dates <=
    the prediction date.  Then we find the lexicographically prior season
    (e.g., "2023-24" is before "2024-25") and check team appearances.

    Parameters
    ----------
    team_id : int
        Database ID of the team.
    league_id : int
        Database ID of the league.
    match_date : str
        ISO date of the match being predicted.

    Returns
    -------
    dict
        Keys: is_newly_promoted.
        - 1 if the team did not appear in this league last season
        - 0 if the team played in this league last season
        - 0 (not None) if no prior-season data exists in the DB
    """
    with get_session() as session:
        from sqlalchemy import distinct

        # Determine the current season: find the most recent season in the
        # matches table for this league whose match dates are <= match_date.
        # Season strings sort lexicographically (e.g., "2022-23" < "2023-24").
        # We find all distinct seasons for this league, then take the most
        # recent one whose matches include dates <= match_date.
        season_rows = (
            session.query(distinct(Match.season))
            .filter(
                Match.league_id == league_id,
                Match.date <= match_date,
            )
            .all()
        )

        if not season_rows:
            # No data for this league before this date — default to established
            logger.debug(
                "No matches found for league_id=%d on or before %s — "
                "defaulting is_newly_promoted=0",
                league_id, match_date,
            )
            return {"is_newly_promoted": 0}

        # Sort seasons lexicographically and take the most recent one.
        # "2024-25" > "2023-24" > "2022-23" in string comparison.
        all_seasons = sorted([row[0] for row in season_rows])
        current_season_str = all_seasons[-1]

        # Find all known seasons for this league, sorted.
        all_league_season_rows = (
            session.query(distinct(Match.season))
            .filter(Match.league_id == league_id)
            .all()
        )
        all_league_seasons = sorted([row[0] for row in all_league_season_rows])

        # Find the index of the current season to identify the prior one
        try:
            idx = all_league_seasons.index(current_season_str)
        except ValueError:
            return {"is_newly_promoted": 0}

        if idx == 0:
            # Current season is the earliest in our DB — no prior data
            # Default to 0 (established): no evidence of promotion
            logger.debug(
                "Season %s is earliest in DB for league_id=%d — "
                "defaulting is_newly_promoted=0",
                current_season_str, league_id,
            )
            return {"is_newly_promoted": 0}

        prior_season_str = all_league_seasons[idx - 1]

        # Check if this team appeared in ANY match in the prior season.
        # Both home and away appearances count.
        appeared_in_prior = (
            session.query(Match)
            .filter(
                Match.league_id == league_id,
                Match.season == prior_season_str,
                (
                    (Match.home_team_id == team_id) |
                    (Match.away_team_id == team_id)
                ),
            )
            .first()
        )

    # If the team appeared in the prior season → established (0)
    # If not → newly promoted (1)
    is_promoted = 0 if appeared_in_prior is not None else 1

    logger.debug(
        "is_newly_promoted for team_id=%d in league_id=%d on %s: %d "
        "(current season: %s, prior season: %s)",
        team_id, league_id, match_date, is_promoted,
        current_season_str, prior_season_str,
    )

    return {"is_newly_promoted": is_promoted}


# ============================================================================
# Squad Rotation Index (E39-09)
# ============================================================================
# Measures how many starting XI players changed compared to the team's
# previous match.  squad_rotation_index = num_changed / 11.
#
# High rotation (>0.5) typically happens during fixture congestion or when
# managers deliberately rest players ahead of a bigger match.  Low rotation
# (0.0-0.1) indicates a settled XI — often correlates with better results
# because the manager trusts these 11 players the most.
#
# TEMPORAL INTEGRITY:
#   Only considers matches BEFORE match_date, so we never leak future info.
#   Returns None when no prior lineup data exists (e.g., first match of
#   season or before lineup scraping began).  Models handle None via
#   fillna(mean).fillna(0.0).
# ============================================================================


def calculate_squad_rotation(
    team_id: int,
    match_id: int,
    match_date: str,
    league_id: int,
) -> Dict[str, Any]:
    """Calculate squad rotation index for a team in a specific match.

    Compares the starting XI of the current match with the starting XI
    from the team's most recent previous match (in the same league,
    before match_date).

    squad_rotation_index = number_of_changes / 11

    Parameters
    ----------
    team_id : int
        Database ID of the team.
    match_id : int
        Database ID of the current match (to get its lineup).
    match_date : str
        ISO date (YYYY-MM-DD) of the match being predicted.
    league_id : int
        Database ID of the league (limits search to same league).

    Returns
    -------
    dict
        ``{"squad_rotation_index": float | None}``
        None if either current or previous lineup is unavailable.
    """
    default = {"squad_rotation_index": None}

    with get_session() as session:
        # Get current match starters
        current_starters = (
            session.query(MatchLineup.player_name)
            .filter(
                MatchLineup.match_id == match_id,
                MatchLineup.team_id == team_id,
                MatchLineup.is_starter == 1,
            )
            .all()
        )

        if not current_starters:
            # No lineup data for this match — return None
            return default

        current_names = {
            row[0].lower().strip() for row in current_starters
        }

        if len(current_names) < 1:
            return default

        # Find the team's most recent previous match (same league, before date)
        prev_match = (
            session.query(Match)
            .filter(
                Match.league_id == league_id,
                Match.date < match_date,
                Match.status == "finished",
                (
                    (Match.home_team_id == team_id)
                    | (Match.away_team_id == team_id)
                ),
            )
            .order_by(Match.date.desc())
            .first()
        )

        if prev_match is None:
            return default

        # Get previous match starters
        prev_starters = (
            session.query(MatchLineup.player_name)
            .filter(
                MatchLineup.match_id == prev_match.id,
                MatchLineup.team_id == team_id,
                MatchLineup.is_starter == 1,
            )
            .all()
        )

        if not prev_starters:
            # No lineup data for previous match
            return default

        prev_names = {
            row[0].lower().strip() for row in prev_starters
        }

    # Count players NOT in common between current and previous starting XIs.
    # A player appearing in current but not previous = a "change".
    # Use min(11, len(current)) as denominator for safety.
    common = current_names & prev_names
    denominator = max(len(current_names), 1)
    changes = denominator - len(common)
    rotation_index = round(changes / denominator, 4)

    logger.debug(
        "Squad rotation for team_id=%d, match_id=%d: "
        "%d/%d players changed (index=%.3f)",
        team_id, match_id, changes, denominator, rotation_index,
    )

    return {"squad_rotation_index": rotation_index}


# ============================================================================
# Formation Change Feature (E39-10)
# ============================================================================
# Binary flag: 1 if the team's formation in this match differs from their
# formation in their most recent previous match, 0 if the same.
#
# Formation changes signal tactical adaptation — a manager switching from
# 4-3-3 to 5-4-1 against a strong opponent, or from 4-4-2 to 4-2-3-1
# for extra midfield control.  Frequent changes may indicate instability
# (struggling to find a winning formula) or flexibility (adapting to
# opponents).
#
# Returns None when either the current or previous match formation is
# unknown (NULL).  Models handle None via fillna(mean).fillna(0.0).
#
# TEMPORAL INTEGRITY: Only compares with matches BEFORE match_date.
# ============================================================================


def calculate_formation_change(
    team_id: int,
    match_id: int,
    match_date: str,
    league_id: int,
) -> Dict[str, Any]:
    """Check whether team's formation changed from previous match.

    Compares the formation used in the current match against the formation
    in the team's most recent previous match in the same league.

    Parameters
    ----------
    team_id : int
        Database ID of the team.
    match_id : int
        Database ID of the current match.
    match_date : str
        ISO date (YYYY-MM-DD) of the match being predicted.
    league_id : int
        Database ID of the league.

    Returns
    -------
    dict
        ``{"formation_changed": 0 | 1 | None}``
        None if either match has no formation data.
    """
    default = {"formation_changed": None}

    with get_session() as session:
        # Get current match to determine this team's formation
        current_match = session.query(Match).filter_by(id=match_id).first()
        if current_match is None:
            return default

        # Determine which side (home/away) this team is on
        if current_match.home_team_id == team_id:
            current_formation = current_match.home_formation
        elif current_match.away_team_id == team_id:
            current_formation = current_match.away_formation
        else:
            return default

        if not current_formation:
            return default

        # Find the team's most recent previous match (same league, before date)
        prev_match = (
            session.query(Match)
            .filter(
                Match.league_id == league_id,
                Match.date < match_date,
                Match.status == "finished",
                (
                    (Match.home_team_id == team_id)
                    | (Match.away_team_id == team_id)
                ),
            )
            .order_by(Match.date.desc())
            .first()
        )

        if prev_match is None:
            return default

        # Determine previous formation
        if prev_match.home_team_id == team_id:
            prev_formation = prev_match.home_formation
        else:
            prev_formation = prev_match.away_formation

        if not prev_formation:
            return default

    # Normalise formations before comparing (strip whitespace)
    changed = 1 if current_formation.strip() != prev_formation.strip() else 0

    logger.debug(
        "Formation change for team_id=%d, match_id=%d: "
        "%s → %s (changed=%d)",
        team_id, match_id, prev_formation, current_formation, changed,
    )

    return {"formation_changed": changed}


# ============================================================================
# Bench Strength Feature (E39-11)
# ============================================================================
# Ratio of bench total market value to starter total market value.
#
# bench_strength = sum(bench player values) / sum(starter player values)
#
# Typically 0.3–0.8.  Elite clubs (Man City ~0.7) have benches worth nearly
# as much as most other teams' starting XIs, giving them a massive advantage
# in congested fixture periods — they can rotate freely without dropping
# quality.  Mid-table teams (~0.4) see noticeable performance drops when
# forced to rotate due to thin bench quality.
#
# Returns None when no lineup or PlayerValue data is available.
# Models handle None via fillna(mean).fillna(0.0).
#
# TEMPORAL INTEGRITY: Uses the PlayerValue snapshot closest to (but not
# after) the match date.  Since PlayerValue snapshots are updated infrequently
# (typically once per season), we use the latest available snapshot for the
# team — this is acceptable because market value rank within a squad is
# relatively stable across a season.
# ============================================================================


def calculate_bench_strength(
    team_id: int,
    match_id: int,
    match_date: str,
) -> Dict[str, Any]:
    """Calculate bench-to-starter market value ratio.

    Uses MatchLineup to identify starters vs bench, then PlayerValue
    to assign market values.  Returns the ratio bench_value / starter_value.

    Parameters
    ----------
    team_id : int
        Database ID of the team.
    match_id : int
        Database ID of the match.
    match_date : str
        ISO date (YYYY-MM-DD) — used for temporal integrity on
        PlayerValue snapshot selection.

    Returns
    -------
    dict
        ``{"bench_strength": float | None}``
        None if lineup or market value data is unavailable.
    """
    default = {"bench_strength": None}

    with get_session() as session:
        # Get all lineup entries for this team in this match
        lineup = (
            session.query(MatchLineup)
            .filter(
                MatchLineup.match_id == match_id,
                MatchLineup.team_id == team_id,
            )
            .all()
        )

        if not lineup:
            return default

        starters = [p for p in lineup if p.is_starter == 1]
        bench = [p for p in lineup if p.is_starter == 0]

        if not starters:
            return default

        # Get PlayerValue data for this team.
        # Use the latest snapshot before or on match_date for temporal integrity.
        pvs = (
            session.query(PlayerValue)
            .filter(
                PlayerValue.team_id == team_id,
                PlayerValue.snapshot_date <= match_date,
            )
            .all()
        )

        if not pvs:
            return default

        # Build a lookup: player_name (lowered, stripped) → market_value_eur
        # If multiple snapshots exist, take the most recent per player.
        pv_lookup: Dict[str, float] = {}
        for pv in pvs:
            key = pv.player_name.lower().strip()
            # Keep the most recent snapshot (pvs are unordered, so
            # only replace if this snapshot is newer).
            if key not in pv_lookup or pv.snapshot_date > pv_lookup.get(
                f"_date_{key}", ""
            ):
                pv_lookup[key] = pv.market_value_eur or 0.0
                pv_lookup[f"_date_{key}"] = pv.snapshot_date or ""

    # Sum market values for starters and bench
    starter_value = sum(
        pv_lookup.get(p.player_name.lower().strip(), 0.0)
        for p in starters
    )
    bench_value = sum(
        pv_lookup.get(p.player_name.lower().strip(), 0.0)
        for p in bench
    )

    if starter_value <= 0:
        # Can't compute ratio with zero starter value
        return default

    ratio = round(bench_value / starter_value, 4)

    logger.debug(
        "Bench strength for team_id=%d, match_id=%d: "
        "bench=%.0f / starters=%.0f = %.3f",
        team_id, match_id, bench_value, starter_value, ratio,
    )

    return {"bench_strength": ratio}
