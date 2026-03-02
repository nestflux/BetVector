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
from src.database.models import ClubElo, Match, Odds, TeamMarketValue, Weather

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
