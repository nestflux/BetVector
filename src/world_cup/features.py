"""
BetVector World Cup 2026 — Feature Engineering (WC-03-01, WC-03-02, WC-03-03)
===============================================================================
Compute the full feature vector for each WC match and store in wc_features.

Features are organized in tiers:
  Tier 1 (Core): Elo, squad, historical, host flag
  Tier 2 (Alt):  Economic, climate, travel, dark horse, manager, form, confederation
  Tier 3 (Tournament): Motivation, matchday, group strength, stage, knockout deflation
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from sqlalchemy import select, func

from src.database.db import get_session
from src.world_cup.models import WCFeature, WCMatch, WCTeam, WCHistoricalMatch
from src.world_cup.world_bank import WC_VENUES, haversine_km

logger = logging.getLogger(__name__)

# Confederation strength adjustments (baseline research — UEFA/CONMEBOL = 0)
CONFEDERATION_ADJ = {
    "UEFA": 0.0,
    "CONMEBOL": 0.0,
    "CONCACAF": -0.06,
    "CAF": -0.07,
    "AFC": -0.09,
    "OFC": -0.10,
}

# Best WC finish → numeric score (lower = better; used for comparison features)
FINISH_SCORE = {
    "Winner": 1, "Runner-up": 2, "Third place": 3, "Fourth place": 4,
    "Quarter-final": 5, "Round of 16": 6, "Group stage": 7,
    "Never qualified": 8,
}

# Stage → numeric code for feature (group=0, deeper = higher)
STAGE_CODE = {
    "group": 0,
    "round_of_32": 1,
    "round_of_16": 2,
    "quarter_final": 3,
    "semi_final": 4,
    "final": 5,
    "third_place": 5,
}


def compute_wc_features(match_id: int | None = None) -> int:
    """
    Compute feature vectors for WC matches and store in wc_features.

    If match_id is given, compute for that match only.
    Otherwise, compute for all matches.

    Returns count of features computed.
    """
    try:
        with get_session() as session:
            if match_id:
                matches = [session.get(WCMatch, match_id)]
                if not matches[0]:
                    logger.warning("Match %d not found", match_id)
                    return 0
            else:
                matches = session.execute(
                    select(WCMatch).order_by(WCMatch.date)
                ).scalars().all()

            teams = session.execute(select(WCTeam)).scalars().all()
            team_map = {t.id: t for t in teams}

            # Pre-compute group strengths (avg Elo of all teams in each group)
            group_strengths = _compute_group_strengths(teams)

            # Pre-load all matches for rest day calculation
            all_matches = session.execute(
                select(WCMatch).order_by(WCMatch.date)
            ).scalars().all()

            computed = 0
            for match in matches:
                home = team_map.get(match.home_team_id)
                away = team_map.get(match.away_team_id)
                if not home or not away:
                    logger.warning("Match %d: missing team data", match.id)
                    continue

                feat = session.execute(
                    select(WCFeature).where(WCFeature.match_id == match.id)
                ).scalar_one_or_none()

                if not feat:
                    feat = WCFeature(match_id=match.id)
                    session.add(feat)

                _compute_tier1(feat, match, home, away)
                _compute_tier2(feat, match, home, away, group_strengths, all_matches, session)
                _compute_tier3(feat, match, home, away, group_strengths, all_matches, session)

                computed += 1

            session.commit()
            logger.info("Computed features for %d matches", computed)
            return computed

    except Exception as e:
        logger.error("Failed to compute WC features: %s", e)
        return 0


def _compute_tier1(feat: WCFeature, match: WCMatch, home: WCTeam, away: WCTeam) -> None:
    """Tier 1 — Core strength, squad, historical, and host features."""
    # Strength
    feat.elo_home = home.elo_rating or 1500.0
    feat.elo_away = away.elo_rating or 1500.0
    feat.elo_diff = feat.elo_home - feat.elo_away

    # Market value ratio — log scale because raw MV ranges from €8M to €1,380M.
    # Log-ratio centers around 0 and correlates with bookmaker pricing.
    home_mv = home.squad_market_value or 1.0
    away_mv = away.squad_market_value or 1.0
    feat.market_value_ratio = math.log(home_mv / away_mv) if away_mv > 0 else 0.0

    # Squad
    feat.avg_age_home = home.avg_squad_age or 0.0
    feat.avg_age_away = away.avg_squad_age or 0.0
    feat.top5_league_players_home = home.players_in_top5_leagues or 0
    feat.top5_league_players_away = away.players_in_top5_leagues or 0
    feat.cl_players_home = home.cl_players or 0
    feat.cl_players_away = away.cl_players or 0

    # Historical
    feat.wc_appearances_home = home.wc_appearances or 0
    feat.wc_appearances_away = away.wc_appearances or 0
    feat.best_finish_home = FINISH_SCORE.get(home.best_wc_finish or "Never qualified", 8)
    feat.best_finish_away = FINISH_SCORE.get(away.best_wc_finish or "Never qualified", 8)

    # Host flag (USA, Canada, Mexico are co-hosts)
    feat.is_host_home = 1 if home.is_host else 0
    feat.is_host_away = 1 if away.is_host else 0


def _compute_tier2(
    feat: WCFeature, match: WCMatch, home: WCTeam, away: WCTeam,
    group_strengths: dict, all_matches: list, session,
) -> None:
    """Tier 2 — Economic, climate, travel, dark horse, manager, form, confederation."""
    # Confederation adjustment — corrects for systematic Elo inflation/deflation
    # between confederations (e.g., AFC teams' Elo may overstate true strength)
    feat.confederation_adj_home = CONFEDERATION_ADJ.get(home.confederation or "", 0.0)
    feat.confederation_adj_away = CONFEDERATION_ADJ.get(away.confederation or "", 0.0)

    # Rest days (days since team's last match; first match = 7)
    feat.rest_days_home = _compute_rest_days(home.id, match, all_matches)
    feat.rest_days_away = _compute_rest_days(away.id, match, all_matches)

    # Economic (log ratio — normalizes the enormous GDP/pop range)
    home_gdp = home.gdp_per_capita or 1.0
    away_gdp = away.gdp_per_capita or 1.0
    feat.gdp_ratio = math.log(home_gdp / away_gdp) if away_gdp > 0 else 0.0

    home_pop = home.population or 1.0
    away_pop = away.population or 1.0
    feat.population_ratio = math.log(home_pop / away_pop) if away_pop > 0 else 0.0

    # Manager tenure
    feat.manager_tenure_home = home.manager_tenure_months or 0
    feat.manager_tenure_away = away.manager_tenure_months or 0

    # Dark horse score
    feat.dark_horse_score_home = home.dark_horse_score or 0.0
    feat.dark_horse_score_away = away.dark_horse_score or 0.0

    # Climate gap and travel distance (venue-specific)
    venue_data = _get_venue_data(match.venue or match.city)
    if venue_data:
        v_lat, v_lon, _, v_temp = venue_data
        if home.home_avg_june_temp_c is not None:
            feat.climate_gap_home = abs(home.home_avg_june_temp_c - v_temp)
        if away.home_avg_june_temp_c is not None:
            feat.climate_gap_away = abs(away.home_avg_june_temp_c - v_temp)
        if home.home_capital_lat is not None:
            feat.travel_distance_home_km = haversine_km(
                home.home_capital_lat, home.home_capital_lon, v_lat, v_lon,
            )
        if away.home_capital_lat is not None:
            feat.travel_distance_away_km = haversine_km(
                away.home_capital_lat, away.home_capital_lon, v_lat, v_lon,
            )
    else:
        # Fallback: use average venue values from world_bank.py compute_derived_features
        _set_avg_venue_features(feat, home, away)

    # Form from last 5 competitive international matches
    feat.home_form_last5 = _compute_form(home.name, match.date, session)
    feat.away_form_last5 = _compute_form(away.name, match.date, session)

    # Venue altitude
    feat.altitude_m = match.altitude_m or 0.0


def _compute_tier3(
    feat: WCFeature, match: WCMatch, home: WCTeam, away: WCTeam,
    group_strengths: dict, all_matches: list, session,
) -> None:
    """Tier 3 — Tournament dynamics: motivation, matchday, group strength, stage."""
    # Matchday (for group stage)
    feat.matchday = match.matchday or _infer_matchday(home.id, match, all_matches)

    # Group strength (average Elo of all teams in the group)
    feat.group_strength = group_strengths.get(match.group_letter, 0.0)

    # Stage code
    feat.stage_code = STAGE_CODE.get(match.stage or "group", 0)

    # Knockout deflation: knockout matches produce ~15% fewer goals than group stages
    feat.knockout_deflation = 0.85 if feat.stage_code >= 1 else 1.0

    # Motivation (meaningful only for matchday 3)
    if feat.matchday == 3 and match.stage == "group":
        feat.motivation_home = _classify_motivation(home.id, match.group_letter, match, all_matches)
        feat.motivation_away = _classify_motivation(away.id, match.group_letter, match, all_matches)
    else:
        feat.motivation_home = "standard"
        feat.motivation_away = "standard"


def _compute_group_strengths(teams: list[WCTeam]) -> dict[str, float]:
    """Average Elo of all teams in each group."""
    groups: dict[str, list[float]] = {}
    for team in teams:
        g = team.group_letter
        if g:
            groups.setdefault(g, []).append(team.elo_rating or 1500.0)
    return {g: sum(elos) / len(elos) for g, elos in groups.items()}


def _compute_rest_days(team_id: int, current_match: WCMatch, all_matches: list) -> int:
    """Days since team's last match. First match of tournament = 7 (standard rest)."""
    current_date = datetime.strptime(current_match.date[:10], "%Y-%m-%d")
    prev_dates = []
    for m in all_matches:
        if m.id == current_match.id:
            continue
        if m.home_team_id == team_id or m.away_team_id == team_id:
            m_date = datetime.strptime(m.date[:10], "%Y-%m-%d")
            if m_date < current_date:
                prev_dates.append(m_date)
    if not prev_dates:
        return 7
    last = max(prev_dates)
    return (current_date - last).days


def _get_venue_data(venue_or_city: str | None) -> tuple | None:
    """Look up venue coordinates and temperature from WC_VENUES."""
    if not venue_or_city:
        return None
    # Try exact venue name match
    if venue_or_city in WC_VENUES:
        return WC_VENUES[venue_or_city]
    # Try city match
    for name, data in WC_VENUES.items():
        if data[2].lower() in venue_or_city.lower() or venue_or_city.lower() in data[2].lower():
            return data
    return None


def _set_avg_venue_features(feat: WCFeature, home: WCTeam, away: WCTeam) -> None:
    """Fallback: use average across all 15 WC venues."""
    venue_list = list(WC_VENUES.values())
    avg_temp = sum(v[3] for v in venue_list) / len(venue_list)
    avg_lat = sum(v[0] for v in venue_list) / len(venue_list)
    avg_lon = sum(v[1] for v in venue_list) / len(venue_list)

    if home.home_avg_june_temp_c is not None:
        feat.climate_gap_home = abs(home.home_avg_june_temp_c - avg_temp)
    if away.home_avg_june_temp_c is not None:
        feat.climate_gap_away = abs(away.home_avg_june_temp_c - avg_temp)
    if home.home_capital_lat is not None:
        feat.travel_distance_home_km = haversine_km(
            home.home_capital_lat, home.home_capital_lon, avg_lat, avg_lon,
        )
    if away.home_capital_lat is not None:
        feat.travel_distance_away_km = haversine_km(
            away.home_capital_lat, away.home_capital_lon, avg_lat, avg_lon,
        )


def _compute_form(team_name: str, before_date: str, session) -> float:
    """
    Weighted form from last 5 competitive matches before the given date.
    Points: win=3, draw=1, loss=0, weighted by match importance.
    Returns 0-15 scale (5 matches * max 3 points).
    """
    # Map WC team name to historical match name if needed
    from src.world_cup.elo import WC_TO_HIST_NAME
    hist_name = WC_TO_HIST_NAME.get(team_name, team_name)

    matches = session.execute(
        select(WCHistoricalMatch)
        .where(
            WCHistoricalMatch.date < before_date,
            (WCHistoricalMatch.home_team == hist_name) | (WCHistoricalMatch.away_team == hist_name),
            WCHistoricalMatch.match_weight >= 0.5,
        )
        .order_by(WCHistoricalMatch.date.desc())
        .limit(5)
    ).scalars().all()

    if not matches:
        return 7.5  # Neutral form (midpoint)

    total = 0.0
    for m in matches:
        if m.home_team == hist_name:
            if m.home_goals > m.away_goals:
                total += 3.0 * m.match_weight
            elif m.home_goals == m.away_goals:
                total += 1.0 * m.match_weight
        else:
            if m.away_goals > m.home_goals:
                total += 3.0 * m.match_weight
            elif m.away_goals == m.home_goals:
                total += 1.0 * m.match_weight

    return round(total, 2)


def _infer_matchday(team_id: int, match: WCMatch, all_matches: list) -> int:
    """Infer matchday from the team's match sequence in their group."""
    group_matches = sorted(
        [m for m in all_matches if m.group_letter == match.group_letter
         and (m.home_team_id == team_id or m.away_team_id == team_id)],
        key=lambda m: m.date,
    )
    for i, m in enumerate(group_matches):
        if m.id == match.id:
            return i + 1
    return 1


def _classify_motivation(
    team_id: int, group_letter: str, current_match: WCMatch, all_matches: list,
) -> str:
    """
    Classify team's motivation for matchday 3 based on current group standings.
    States: comfortable (already through), must_win, dead_rubber (eliminated), live.

    In the 2026 format (4 teams per group, top 2 + best 3rd advance), a team
    on 0 points after 2 matches is dead_rubber if other teams have enough
    points to make qualification mathematically impossible.

    Matchday 3 dead rubbers historically have the highest upset rate in WC
    group stages — the team with nothing to play for often underperforms
    their Elo, creating value betting opportunities on the opponent.
    """
    # Temporal integrity: only use results from before this match
    group_matches = [
        m for m in all_matches
        if m.group_letter == group_letter
        and m.status == "finished"
        and m.home_goals is not None
        and m.id != current_match.id
        and m.date <= current_match.date
    ]

    # Build points table for all teams in this group
    points: dict[int, int] = {}
    for m in group_matches:
        points.setdefault(m.home_team_id, 0)
        points.setdefault(m.away_team_id, 0)
        if m.home_goals > m.away_goals:
            points[m.home_team_id] += 3
        elif m.home_goals == m.away_goals:
            points[m.home_team_id] += 1
            points[m.away_team_id] += 1
        else:
            points[m.away_team_id] += 3

    team_pts = points.get(team_id, 0)

    # Sorted points of other teams in group
    other_pts = sorted(
        [p for tid, p in points.items() if tid != team_id],
        reverse=True,
    )

    # If team wins matchday 3, max possible points
    max_pts = team_pts + 3

    if team_pts >= 6:
        return "comfortable"

    # Dead rubber: even with a win, team can't catch 2nd place
    if len(other_pts) >= 2 and max_pts < other_pts[1]:
        return "dead_rubber"

    # 0 points after 2 matches — eliminated if other teams have 4+ each
    if team_pts == 0 and len(other_pts) >= 2 and other_pts[1] >= 4:
        return "dead_rubber"

    if team_pts >= 4:
        return "comfortable"
    elif team_pts <= 1:
        return "must_win"
    else:
        return "live"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from src.database.db import init_db

    init_db()

    print("=== Computing WC Match Features ===")
    count = compute_wc_features()
    print(f"\nComputed features for {count} matches")

    print("\n=== Feature Summary ===")
    with get_session() as session:
        feats = session.execute(
            select(WCFeature).order_by(WCFeature.match_id)
        ).scalars().all()

        null_counts: dict[str, int] = {}
        for col in WCFeature.__table__.columns:
            if col.name in ("id", "match_id", "created_at"):
                continue
            null_counts[col.name] = sum(1 for f in feats if getattr(f, col.name) is None)

        total = len(feats)
        print(f"Total features: {total}")
        nan_fields = {k: v for k, v in null_counts.items() if v > 0}
        if nan_fields:
            print("Fields with NULLs:")
            for field, count in sorted(nan_fields.items()):
                print(f"  {field}: {count}/{total} NULL")
        else:
            print("No NULL values in any feature field")

        # Sample feature
        if feats:
            f = feats[0]
            match = session.get(WCMatch, f.match_id)
            ht = session.get(WCTeam, match.home_team_id)
            at = session.get(WCTeam, match.away_team_id)
            print(f"\nSample: {ht.name} vs {at.name}")
            print(f"  Elo: {f.elo_home:.0f} vs {f.elo_away:.0f} (diff={f.elo_diff:.0f})")
            print(f"  MV ratio: {f.market_value_ratio:.2f}")
            print(f"  Rest: {f.rest_days_home}d vs {f.rest_days_away}d")
            print(f"  Form: {f.home_form_last5} vs {f.away_form_last5}")
            print(f"  Climate gap: {f.climate_gap_home} vs {f.climate_gap_away}")
            print(f"  Stage: {f.stage_code}, Matchday: {f.matchday}")
