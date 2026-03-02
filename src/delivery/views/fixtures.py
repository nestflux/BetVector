"""
BetVector — Fixtures Page (E17-04)
===================================
All upcoming matches across active leagues, grouped by date.

Different from Today's Picks:
- **Today's Picks** = "here are the value bets the model likes"
- **Fixtures** = "here are ALL matches happening, and these ones have value"

Matches with value bets are highlighted with a green left border and a
"VALUE" badge so the user can quickly see where the model has found edge.
Click any fixture to open the Match Deep Dive for full analysis.

Master Plan refs: MP §3 Flow 4 (Dashboard Exploration), MP §8 Design System
"""

from datetime import date, timedelta
from itertools import groupby
from typing import Dict, List

import streamlit as st
from sqlalchemy.orm import aliased

from src.database.db import get_session
from src.database.models import League, Match, Team, ValueBet


# ============================================================================
# Design tokens (MP §8)
# ============================================================================

COLOURS = {
    "bg": "#0D1117",
    "surface": "#161B22",
    "border": "#30363D",
    "text": "#E6EDF3",
    "text_secondary": "#8B949E",
    "green": "#3FB950",
    "red": "#F85149",
    "yellow": "#D29922",
    "blue": "#58A6FF",
}


# ============================================================================
# Data Loading
# ============================================================================

def get_all_upcoming_fixtures(days_ahead: int = 14) -> List[Dict]:
    """Fetch all upcoming scheduled matches across active leagues.

    Groups matches by date.  For each match, checks whether any ValueBet
    records exist — this indicates the model has flagged value on the match.

    Parameters
    ----------
    days_ahead : int
        How many days into the future to look (default 14).

    Returns
    -------
    list[dict]
        Fixture data enriched with team names, league, and value bet count.
    """
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)

    today_str = date.today().isoformat()
    cutoff_str = (date.today() + timedelta(days=days_ahead)).isoformat()

    with get_session() as session:
        matches = (
            session.query(Match, HomeTeam, AwayTeam, League)
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .join(League, Match.league_id == League.id)
            .filter(
                Match.status == "scheduled",
                Match.date >= today_str,
                Match.date <= cutoff_str,
            )
            .order_by(Match.date.asc(), Match.kickoff_time.asc())
            .all()
        )

        results = []
        for match, home_team, away_team, league in matches:
            # Count value bets flagged for this match
            vb_count = (
                session.query(ValueBet)
                .filter_by(match_id=match.id)
                .count()
            )

            results.append({
                "match_id": match.id,
                "date": match.date,
                "kickoff": match.kickoff_time or "TBD",
                "home_team": home_team.name,
                "away_team": away_team.name,
                "league": league.short_name,
                "league_name": league.name,
                "has_value_bets": vb_count > 0,
                "value_bet_count": vb_count,
            })

    return results


# ============================================================================
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">Fixtures</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">'
    "All upcoming matches. Value picks highlighted with a green border."
    "</p>",
    unsafe_allow_html=True,
)
st.divider()

# Days-ahead slider — controls how far forward we look
days_ahead = st.slider(
    "Days ahead",
    min_value=7,
    max_value=28,
    value=14,
    step=7,
    help="How far ahead to show fixtures.",
)

# Load fixtures
with st.spinner("Loading fixtures..."):
    fixtures = get_all_upcoming_fixtures(days_ahead=days_ahead)

if not fixtures:
    st.markdown(
        '<div class="bv-empty-state">'
        "No upcoming fixtures found. The season may be between matchdays, "
        "or the pipeline hasn't scraped fixture data yet."
        "</div>",
        unsafe_allow_html=True,
    )
else:
    # Summary
    total = len(fixtures)
    with_value = sum(1 for f in fixtures if f["has_value_bets"])

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Upcoming Matches", total)
    with col2:
        st.metric("With Value Bets", with_value)

    st.divider()

    # Group fixtures by date and render
    for match_date, group in groupby(fixtures, key=lambda x: x["date"]):
        # Date header
        st.markdown(
            f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
            f'font-weight: 600; color: {COLOURS["text"]}; '
            f'margin: 20px 0 10px; text-transform: uppercase; '
            f'letter-spacing: 0.5px;">{match_date}</div>',
            unsafe_allow_html=True,
        )

        for fix in group:
            # Green left border for matches with value bets
            border_style = (
                f"border-left: 3px solid {COLOURS['green']};"
                if fix["has_value_bets"]
                else ""
            )

            # Value badge HTML (only for matches the model flagged)
            value_badge = ""
            if fix["has_value_bets"]:
                count = fix["value_bet_count"]
                value_badge = (
                    f'<span class="bv-badge" style="background-color: {COLOURS["green"]}; '
                    f'margin-left: 8px;">'
                    f'{count} VALUE BET{"S" if count > 1 else ""}</span>'
                )

            # League badge
            league_badge = (
                f'<span class="bv-badge" style="background-color: {COLOURS["border"]}; '
                f'color: {COLOURS["text_secondary"]};">{fix["league"]}</span>'
            )

            # Kickoff time — only show the time slot if we actually have one.
            # When the Football-Data.org scraper hasn't backfilled yet,
            # kickoff_time is NULL and we just skip the column rather
            # than displaying "TBD" which looks broken.
            kickoff_html = ""
            if fix["kickoff"] and fix["kickoff"] != "TBD":
                kickoff_html = (
                    f'<span style="font-family: JetBrains Mono, monospace; font-size: 13px; '
                    f'color: {COLOURS["text_secondary"]}; min-width: 50px;">'
                    f'{fix["kickoff"]}</span>'
                )

            # Fixture card
            st.markdown(
                f'<div class="bv-card" style="display: flex; justify-content: space-between; '
                f'align-items: center; padding: 12px 16px; {border_style}">'
                f'<div style="display: flex; align-items: center; gap: 12px;">'
                f'{kickoff_html}'
                # Teams
                f'<span style="font-family: Inter, sans-serif; font-size: 15px; '
                f'font-weight: 600; color: {COLOURS["text"]};">'
                f'{fix["home_team"]} vs {fix["away_team"]}</span>'
                # Value badge
                f'{value_badge}'
                f'</div>'
                # League badge (right side)
                f'<div>{league_badge}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # "Deep Dive" button — navigates to Match Deep Dive with match_id
            if st.button(
                "\U0001F50D Deep Dive",
                key=f"fixture_dive_{fix['match_id']}",
                type="secondary",
            ):
                st.query_params["match_id"] = str(fix["match_id"])
                st.switch_page("views/match_detail.py")
