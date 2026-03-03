"""
BetVector — Fixtures Page (E17-04, E24-03)
============================================
All upcoming matches across active leagues, grouped by date.

Different from Today's Picks:
- **Today's Picks** = "here are the value bets the model likes"
- **Fixtures** = "here are ALL matches happening, with color-coded model
  indicators for every market"

E24-03: Added inline color-coded market indicators per fixture row.
For each scheduled match, 7 compact badges show the model's view:
Home/Draw/Away (1X2), BTTS Yes/No, Over/Under 2.5.
Colour coding:  green = strong edge, yellow = marginal, red = no edge,
grey = no data.

Master Plan refs: MP §3 Flow 4 (Dashboard Exploration), MP §8 Design System
"""

from datetime import date, timedelta
from itertools import groupby
from typing import Dict, List, Optional, Tuple

import streamlit as st
from sqlalchemy import func
from sqlalchemy.orm import aliased

from src.config import config
from src.database.db import get_session
from src.database.models import League, Match, Odds, Prediction, Team, ValueBet


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
    "grey": "#484F58",
}


# ============================================================================
# Edge thresholds — driven from config for consistency with ValueFinder.
# Green = edge at or above the value threshold (worth betting on).
# Yellow = positive edge but below threshold (marginal — model slightly
#   favours the selection but not enough to recommend a bet).
# Red = no edge or negative edge (bookmaker price is fair or better).
# Grey = no data available (odds or prediction missing).
# ============================================================================

try:
    _edge_threshold = float(config.settings.value_betting.edge_threshold)
except (AttributeError, TypeError, ValueError):
    _edge_threshold = 0.05  # 5% default


def _edge_colour(edge: Optional[float]) -> str:
    """Return a hex colour based on the edge value.

    Parameters
    ----------
    edge : float or None
        Model probability minus bookmaker implied probability.
        None means data is unavailable.

    Returns
    -------
    str
        Hex colour code for the badge background.
    """
    if edge is None:
        return COLOURS["grey"]
    if edge >= _edge_threshold:
        return COLOURS["green"]
    if edge > 0:
        return COLOURS["yellow"]
    return COLOURS["red"]


# ============================================================================
# Market badge definitions — the 7 selections shown per fixture.
# Each tuple: (market_type_db, selection_db, badge_label)
# These correspond to ValueBet.market_type and ValueBet.selection values.
# ============================================================================

MARKET_BADGES = [
    ("1X2", "home", "H"),
    ("1X2", "draw", "D"),
    ("1X2", "away", "A"),
    ("BTTS", "yes", "BTTS Y"),
    ("BTTS", "no", "BTTS N"),
    ("OU25", "over", "O2.5"),
    ("OU25", "under", "U2.5"),
]

# Map Prediction attributes to (market_type, selection) for probability lookups.
# The Prediction model stores derived probabilities from the scoreline matrix.
PRED_PROB_MAP = {
    ("1X2", "home"): "prob_home_win",
    ("1X2", "draw"): "prob_draw",
    ("1X2", "away"): "prob_away_win",
    ("BTTS", "yes"): "prob_btts_yes",
    ("BTTS", "no"): "prob_btts_no",
    ("OU25", "over"): "prob_over_25",
    ("OU25", "under"): "prob_under_25",
}


# ============================================================================
# Data Loading
# ============================================================================

def get_all_upcoming_fixtures(days_ahead: int = 14) -> List[Dict]:
    """Fetch all upcoming scheduled matches with prediction + odds data.

    For each match, loads the Prediction record and the best available odds
    per market selection to compute edge.  Returns a list ready for rendering
    with color-coded market indicators.

    Parameters
    ----------
    days_ahead : int
        How many days into the future to look (default 14).

    Returns
    -------
    list[dict]
        Fixture data enriched with team names, league, value bet count,
        and per-market edge values.
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

            # Load prediction for this match (most recent model)
            prediction = (
                session.query(Prediction)
                .filter_by(match_id=match.id)
                .order_by(Prediction.created_at.desc())
                .first()
            )

            # Compute per-market edges by comparing model probs to best odds.
            # For each of the 7 market selections, we need:
            #   1. model_prob from Prediction attributes
            #   2. best available odds from the Odds table
            #   3. edge = model_prob - (1.0 / odds)
            market_edges = {}
            for market_type, selection, _label in MARKET_BADGES:
                edge = _compute_edge(
                    session, match.id, prediction, market_type, selection,
                )
                market_edges[(market_type, selection)] = edge

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
                "has_prediction": prediction is not None,
                "market_edges": market_edges,
            })

    return results


def _compute_edge(
    session,
    match_id: int,
    prediction: Optional[Prediction],
    market_type: str,
    selection: str,
) -> Optional[float]:
    """Compute the edge for a specific market selection.

    Edge = model_prob - implied_prob, where implied_prob = 1/odds.
    Returns None if either the prediction or odds are unavailable.

    Parameters
    ----------
    session : Session
        Active DB session.
    match_id : int
        Match ID.
    prediction : Prediction or None
        The Prediction record.
    market_type : str
        Market type (e.g., "1X2", "BTTS", "OU25").
    selection : str
        Selection (e.g., "home", "draw", "over").

    Returns
    -------
    float or None
        Edge as a decimal (e.g., 0.08 for 8%), or None if data missing.
    """
    if prediction is None:
        return None

    # Get model probability from the Prediction attributes
    prob_attr = PRED_PROB_MAP.get((market_type, selection))
    if not prob_attr:
        return None
    model_prob = getattr(prediction, prob_attr, None)
    if model_prob is None:
        return None

    # Get the best available odds for this market + selection.
    # "Best" = highest odds (most generous to the bettor) because
    # higher odds mean lower implied probability, so the edge is larger.
    best_odds_row = (
        session.query(func.max(Odds.odds_decimal))
        .filter(
            Odds.match_id == match_id,
            Odds.market_type == market_type,
            Odds.selection == selection,
        )
        .scalar()
    )

    if not best_odds_row or best_odds_row <= 1.0:
        return None

    implied_prob = 1.0 / best_odds_row
    return model_prob - implied_prob


# ============================================================================
# Badge Rendering
# ============================================================================

def _render_market_badges(market_edges: Dict[Tuple[str, str], Optional[float]]) -> str:
    """Build HTML for the 7 color-coded market indicator badges.

    Each badge is a compact pill showing the selection label (H, D, A,
    BTTS Y, BTTS N, O2.5, U2.5) with a background colour indicating
    the model's edge.

    Parameters
    ----------
    market_edges : dict
        Keys are (market_type, selection) tuples, values are edge floats
        or None.

    Returns
    -------
    str
        HTML string of badge spans.
    """
    badges = []
    for market_type, selection, label in MARKET_BADGES:
        edge = market_edges.get((market_type, selection))
        bg = _edge_colour(edge)

        # Tooltip text — shows edge percentage on hover
        if edge is not None:
            edge_pct = edge * 100
            title = f"{label}: {edge_pct:+.1f}% edge"
        else:
            title = f"{label}: no data"

        badges.append(
            f'<span title="{title}" style="'
            f"display: inline-block; padding: 2px 6px; margin: 0 2px; "
            f"border-radius: 4px; font-family: 'JetBrains Mono', monospace; "
            f"font-size: 10px; font-weight: 600; color: #fff; "
            f'background-color: {bg}; cursor: help;">'
            f"{label}</span>"
        )
    return "".join(badges)


# ============================================================================
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">Fixtures</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">'
    "All upcoming matches with color-coded model indicators per market"
    "</p>",
    unsafe_allow_html=True,
)
st.divider()

# Legend — explains the badge colour coding
st.markdown(
    '<div style="font-family: Inter, sans-serif; font-size: 12px; '
    f'color: {COLOURS["text_secondary"]}; margin-bottom: 16px; '
    'display: flex; gap: 16px; flex-wrap: wrap; align-items: center;">'
    '<span style="font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; '
    'margin-right: 4px;">Legend:</span>'
    f'<span><span style="display: inline-block; width: 10px; height: 10px; '
    f'border-radius: 2px; background-color: {COLOURS["green"]}; margin-right: 4px; '
    f'vertical-align: middle;"></span>Value (edge ≥ {_edge_threshold*100:.0f}%)</span>'
    f'<span><span style="display: inline-block; width: 10px; height: 10px; '
    f'border-radius: 2px; background-color: {COLOURS["yellow"]}; margin-right: 4px; '
    f'vertical-align: middle;"></span>Marginal (0–{_edge_threshold*100:.0f}%)</span>'
    f'<span><span style="display: inline-block; width: 10px; height: 10px; '
    f'border-radius: 2px; background-color: {COLOURS["red"]}; margin-right: 4px; '
    f'vertical-align: middle;"></span>No Value (≤ 0%)</span>'
    f'<span><span style="display: inline-block; width: 10px; height: 10px; '
    f'border-radius: 2px; background-color: {COLOURS["grey"]}; margin-right: 4px; '
    f'vertical-align: middle;"></span>No Data</span>'
    '</div>',
    unsafe_allow_html=True,
)

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
    with_prediction = sum(1 for f in fixtures if f["has_prediction"])

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Upcoming Matches", total)
    with col2:
        st.metric("With Predictions", with_prediction)
    with col3:
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

            # Kickoff time — only show the time slot if we actually have one
            kickoff_html = ""
            if fix["kickoff"] and fix["kickoff"] != "TBD":
                kickoff_html = (
                    f'<span style="font-family: JetBrains Mono, monospace; font-size: 13px; '
                    f'color: {COLOURS["text_secondary"]}; min-width: 50px;">'
                    f'{fix["kickoff"]}</span>'
                )

            # League badge
            league_badge = (
                f'<span class="bv-badge" style="background-color: {COLOURS["border"]}; '
                f'color: {COLOURS["text_secondary"]};">{fix["league"]}</span>'
            )

            # Market indicator badges — the 7 color-coded pills (E24-03)
            market_html = _render_market_badges(fix["market_edges"])

            # Fixture card — two rows:
            # Row 1: Kickoff + Teams + League badge
            # Row 2: Market indicator badges (below the team names)
            st.markdown(
                f'<div class="bv-card" style="padding: 12px 16px; {border_style}">'
                # Row 1: match header
                f'<div style="display: flex; justify-content: space-between; '
                f'align-items: center; margin-bottom: 6px;">'
                f'<div style="display: flex; align-items: center; gap: 12px;">'
                f'{kickoff_html}'
                f'<span style="font-family: Inter, sans-serif; font-size: 15px; '
                f'font-weight: 600; color: {COLOURS["text"]};">'
                f'{fix["home_team"]} vs {fix["away_team"]}</span>'
                f'</div>'
                f'<div>{league_badge}</div>'
                f'</div>'
                # Row 2: market badges
                f'<div style="display: flex; align-items: center; gap: 4px; '
                f'padding-left: 62px;">'
                f'{market_html}'
                f'</div>'
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
