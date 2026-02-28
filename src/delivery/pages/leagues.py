"""
BetVector — League Explorer Page (E9-04)
=========================================
Browse league standings, recent results, upcoming fixtures, and team form.

This page lets the owner explore any active league in depth:

- **Standings table**: Pos, Team, P, W, D, L, GF, GA, GD, Pts — calculated
  on the fly from match results (3 pts for a win, 1 for a draw).  Sorted by
  points → goal difference → goals scored.
- **Recent results**: Last 10 completed matches with scores.
- **Upcoming fixtures**: Next 10 scheduled matches (empty during backtesting
  with historical data only).
- **Form table**: Each team's last 5 results shown as W/D/L badges.

Master Plan refs: MP §3 Flow 4 (Dashboard Exploration), MP §8 Design System
"""

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from sqlalchemy.orm import aliased

from src.config import config
from src.database.db import get_session
from src.database.models import League, Match, Team


# ============================================================================
# Design tokens (MP §8)
# ============================================================================

COLOURS = {
    "green": "#3FB950",
    "red": "#F85149",
    "grey": "#484F58",
    "text": "#E6EDF3",
    "text_secondary": "#8B949E",
    "surface": "#161B22",
    "border": "#30363D",
}


# ============================================================================
# Data Loading
# ============================================================================

def get_active_leagues() -> List[Dict]:
    """Get active leagues from config.

    Reads config/leagues.yaml and returns leagues where is_active is True.
    """
    if not config.leagues:
        return []

    return [
        {"name": lg.name, "short_name": lg.short_name}
        for lg in config.leagues
        if getattr(lg, "is_active", False)
    ]


def get_league_id(short_name: str) -> Optional[int]:
    """Look up the database league ID by short_name."""
    with get_session() as session:
        league = session.query(League).filter_by(short_name=short_name).first()
        return league.id if league else None


def calculate_standings(league_id: int, season: str = "2024-25") -> pd.DataFrame:
    """Calculate league standings from match results.

    Queries all finished matches for the given league/season, then
    aggregates results per team:
    - Win = 3 points, Draw = 1 point, Loss = 0 points
    - Sorted by: Points DESC → Goal Difference DESC → Goals Scored DESC

    Parameters
    ----------
    league_id : int
        Database ID of the league.
    season : str
        Season string (e.g., "2024-25").

    Returns
    -------
    pd.DataFrame
        Columns: Pos, Team, P, W, D, L, GF, GA, GD, Pts
    """
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)

    with get_session() as session:
        matches = (
            session.query(
                Match, HomeTeam.name.label("home_name"),
                AwayTeam.name.label("away_name"),
            )
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .filter(
                Match.league_id == league_id,
                Match.season == season,
                Match.status == "finished",
            )
            .all()
        )

    if not matches:
        return pd.DataFrame()

    # Aggregate stats per team
    # Each team gets entries from both home and away matches
    stats = defaultdict(lambda: {
        "P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0,
    })

    for match, home_name, away_name in matches:
        hg = match.home_goals or 0
        ag = match.away_goals or 0

        # Home team
        stats[home_name]["P"] += 1
        stats[home_name]["GF"] += hg
        stats[home_name]["GA"] += ag
        if hg > ag:
            stats[home_name]["W"] += 1
        elif hg == ag:
            stats[home_name]["D"] += 1
        else:
            stats[home_name]["L"] += 1

        # Away team
        stats[away_name]["P"] += 1
        stats[away_name]["GF"] += ag
        stats[away_name]["GA"] += hg
        if ag > hg:
            stats[away_name]["W"] += 1
        elif ag == hg:
            stats[away_name]["D"] += 1
        else:
            stats[away_name]["L"] += 1

    # Build DataFrame
    rows = []
    for team_name, s in stats.items():
        gd = s["GF"] - s["GA"]
        pts = s["W"] * 3 + s["D"]
        rows.append({
            "Team": team_name,
            "P": s["P"],
            "W": s["W"],
            "D": s["D"],
            "L": s["L"],
            "GF": s["GF"],
            "GA": s["GA"],
            "GD": gd,
            "Pts": pts,
        })

    df = pd.DataFrame(rows)

    # Sort: Points DESC → GD DESC → GF DESC (standard tiebreakers)
    df = df.sort_values(
        ["Pts", "GD", "GF"], ascending=[False, False, False],
    ).reset_index(drop=True)

    # Add position column (1-indexed)
    df.insert(0, "Pos", range(1, len(df) + 1))

    return df


def get_recent_results(
    league_id: int, season: str = "2024-25", limit: int = 10,
) -> List[Dict]:
    """Get the most recent completed matches in a league.

    Returns matches in reverse chronological order (newest first).
    """
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)

    with get_session() as session:
        matches = (
            session.query(
                Match, HomeTeam.name.label("home_name"),
                AwayTeam.name.label("away_name"),
            )
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .filter(
                Match.league_id == league_id,
                Match.season == season,
                Match.status == "finished",
            )
            .order_by(Match.date.desc())
            .limit(limit)
            .all()
        )

    return [
        {
            "date": m.date,
            "home_team": hn,
            "away_team": an,
            "home_goals": m.home_goals,
            "away_goals": m.away_goals,
            "match_id": m.id,
        }
        for m, hn, an in matches
    ]


def get_upcoming_fixtures(
    league_id: int, limit: int = 10,
) -> List[Dict]:
    """Get the next scheduled matches in a league.

    Returns matches in chronological order (soonest first).
    During backtesting with historical data, this may return an empty list.
    """
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)

    with get_session() as session:
        matches = (
            session.query(
                Match, HomeTeam.name.label("home_name"),
                AwayTeam.name.label("away_name"),
            )
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .filter(
                Match.league_id == league_id,
                Match.status == "scheduled",
            )
            .order_by(Match.date.asc())
            .limit(limit)
            .all()
        )

    return [
        {
            "date": m.date,
            "kickoff": m.kickoff_time or "TBD",
            "home_team": hn,
            "away_team": an,
            "match_id": m.id,
        }
        for m, hn, an in matches
    ]


def calculate_team_form(
    league_id: int, season: str = "2024-25", last_n: int = 5,
) -> pd.DataFrame:
    """Calculate each team's form over their last N matches.

    Returns a DataFrame with the team name and a list of W/D/L results
    for their most recent matches (chronological order, most recent last).

    Parameters
    ----------
    league_id : int
        Database ID of the league.
    season : str
        Season string.
    last_n : int
        Number of recent matches to show (default 5).

    Returns
    -------
    pd.DataFrame
        Columns: Team, Form (list of 'W'/'D'/'L' strings), Pts (form points)
    """
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)

    with get_session() as session:
        # Get all finished matches
        matches = (
            session.query(
                Match, HomeTeam.name.label("home_name"),
                AwayTeam.name.label("away_name"),
            )
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .filter(
                Match.league_id == league_id,
                Match.season == season,
                Match.status == "finished",
            )
            .order_by(Match.date.asc())
            .all()
        )

    # Build form sequences per team
    team_results = defaultdict(list)

    for match, home_name, away_name in matches:
        hg = match.home_goals or 0
        ag = match.away_goals or 0

        if hg > ag:
            team_results[home_name].append("W")
            team_results[away_name].append("L")
        elif hg == ag:
            team_results[home_name].append("D")
            team_results[away_name].append("D")
        else:
            team_results[home_name].append("L")
            team_results[away_name].append("W")

    # Take last N results per team
    rows = []
    for team_name, results in team_results.items():
        recent = results[-last_n:]
        form_pts = sum(3 if r == "W" else 1 if r == "D" else 0 for r in recent)
        rows.append({
            "Team": team_name,
            "Form": recent,
            "Pts": form_pts,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Pts", ascending=False).reset_index(drop=True)

    return df


# ============================================================================
# Rendering Helpers
# ============================================================================

def render_form_badges(form_list: List[str]) -> str:
    """Render W/D/L form as coloured HTML badges.

    W = green circle, D = grey circle, L = red circle.
    """
    badges = []
    for result in form_list:
        if result == "W":
            colour = COLOURS["green"]
        elif result == "D":
            colour = COLOURS["grey"]
        else:
            colour = COLOURS["red"]

        badges.append(
            f'<span style="display: inline-block; width: 24px; height: 24px; '
            f'border-radius: 50%; background-color: {colour}; color: #0D1117; '
            f'text-align: center; line-height: 24px; font-family: Inter, sans-serif; '
            f'font-size: 11px; font-weight: 600; margin-right: 4px;">{result}</span>'
        )

    return "".join(badges)


def render_score(home_goals: int, away_goals: int) -> str:
    """Render a match score with styled formatting."""
    return (
        f'<span style="font-family: JetBrains Mono, monospace; '
        f'font-weight: 700; color: {COLOURS["text"]};">'
        f'{home_goals} - {away_goals}</span>'
    )


# ============================================================================
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">League Explorer</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Standings, results, and upcoming fixtures</p>',
    unsafe_allow_html=True,
)
st.divider()

# --- League Selector ---
active_leagues = get_active_leagues()

if not active_leagues:
    st.markdown(
        '<div class="bv-empty-state">'
        "No active leagues configured. Check config/leagues.yaml."
        "</div>",
        unsafe_allow_html=True,
    )
else:
    league_names = {lg["short_name"]: lg["name"] for lg in active_leagues}
    selected_short = st.selectbox(
        "League",
        options=list(league_names.keys()),
        format_func=lambda x: league_names[x],
        key="league_selector",
    )

    league_id = get_league_id(selected_short)
    if league_id is None:
        st.error(f"League '{selected_short}' not found in database. Run the pipeline first.")
    else:
        # --- Standings ---
        st.markdown(
            '<div class="bv-section-header">Standings</div>',
            unsafe_allow_html=True,
        )

        standings = calculate_standings(league_id)
        if standings.empty:
            st.info("No match results available to calculate standings.")
        else:
            st.dataframe(
                standings,
                use_container_width=True,
                hide_index=True,
                height=min(38 * len(standings) + 40, 800),
            )

        st.divider()

        # --- Team Form ---
        st.markdown(
            '<div class="bv-section-header">Team Form (Last 5 Matches)</div>',
            unsafe_allow_html=True,
        )

        form_df = calculate_team_form(league_id)
        if form_df.empty:
            st.info("No match data available for form calculation.")
        else:
            # Render form badges as HTML
            for _, row in form_df.iterrows():
                badges_html = render_form_badges(row["Form"])
                st.markdown(
                    f'<div class="bv-card" style="display: flex; justify-content: '
                    f'space-between; align-items: center; padding: 10px 16px;">'
                    f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'color: {COLOURS["text"]}; min-width: 200px;">{row["Team"]}</span>'
                    f'<div>{badges_html}</div>'
                    f'<span style="font-family: JetBrains Mono, monospace; font-size: 14px; '
                    f'color: {COLOURS["text_secondary"]};">{row["Pts"]} pts</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        st.divider()

        # --- Recent Results ---
        st.markdown(
            '<div class="bv-section-header">Recent Results</div>',
            unsafe_allow_html=True,
        )

        results = get_recent_results(league_id)
        if not results:
            st.info("No completed matches found.")
        else:
            for r in results:
                score_html = render_score(r["home_goals"], r["away_goals"])
                st.markdown(
                    f'<div class="bv-card" style="display: flex; align-items: center; '
                    f'gap: 12px; padding: 10px 16px;">'
                    f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                    f'color: {COLOURS["text_secondary"]}; min-width: 85px;">{r["date"]}</span>'
                    f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'color: {COLOURS["text"]}; min-width: 180px; text-align: right;">'
                    f'{r["home_team"]}</span>'
                    f'<span style="min-width: 50px; text-align: center;">{score_html}</span>'
                    f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'color: {COLOURS["text"]};">{r["away_team"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        st.divider()

        # --- Upcoming Fixtures ---
        st.markdown(
            '<div class="bv-section-header">Upcoming Fixtures</div>',
            unsafe_allow_html=True,
        )

        fixtures = get_upcoming_fixtures(league_id)
        if not fixtures:
            st.markdown(
                '<div class="bv-empty-state">'
                "No upcoming fixtures scheduled. All matches for this season "
                "have been played."
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            for f in fixtures:
                st.markdown(
                    f'<div class="bv-card" style="display: flex; align-items: center; '
                    f'gap: 12px; padding: 10px 16px;">'
                    f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                    f'color: {COLOURS["text_secondary"]}; min-width: 85px;">{f["date"]}</span>'
                    f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                    f'color: {COLOURS["text_secondary"]}; min-width: 45px;">{f["kickoff"]}</span>'
                    f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'color: {COLOURS["text"]}; min-width: 180px; text-align: right;">'
                    f'{f["home_team"]}</span>'
                    f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'color: {COLOURS["text_secondary"]};">vs</span>'
                    f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'color: {COLOURS["text"]};">{f["away_team"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
