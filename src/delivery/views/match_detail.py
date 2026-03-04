"""
BetVector — Match Deep Dive View (E9-05, E26-02, E27-01, E28-02)
==================================================================
Comprehensive analysis for a single match.  Accessible from Today's Picks
cards and Fixtures page via ``st.session_state["deep_dive_match_id"]``
(preferred) or ``?match_id=<id>`` query parameter (URL sharing fallback).

E26-02 changes:
- Navigation uses session_state (not query_params) from Picks/Fixtures pages
  to avoid Streamlit 1.41 param-loss on st.switch_page().
- Match picker split into "Upcoming" and "Recent Results" tabs so users can
  browse future matches for pre-match analysis, not just finished matches.
- session_state is popped after reading (one-time use) and synced to
  query_params so the URL remains shareable.

E27-01 changes:
- Value bets grouped by unique (market_type, selection). One card per bet,
  not one card per bookmaker.
- Default bookmaker: FanDuel. Falls back to highest-edge bookmaker when
  FanDuel has no odds for that selection.
- Bookmaker toggle: selectbox to switch between FanDuel / Best Edge / All.
- OU15 labels added so Over/Under 1.5 value bets render correctly.

E28-02 changes:
- Team badges (crests) displayed beside team names using base64-encoded PNGs.
- Badge helper module ``_badge_helper.py`` provides ``render_team_badge()``
  with memory caching and graceful fallback to plain text.
- Match header uses 28px badges, H2H and form sections use 20px inline badges.

Sections:
1. Match header — teams with badges, date, kickoff, league, actual result (if finished)
2. Scoreline matrix — 7×7 Plotly heatmap with most likely scoreline highlighted
3. Market probabilities — 1X2, O/U 2.5, BTTS derived from the matrix
4. Value bets — grouped by unique bet, FanDuel default, bookmaker toggle
5. Head-to-head — last 5 meetings between the teams
6. Team form — side-by-side rolling stats for home and away teams

Master Plan refs: MP §3 Flow 1 Step 8, MP §8 Design System
"""

import json
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy.orm import aliased

from src.analysis.narrative import generate_match_narrative
from src.database.db import get_session
from src.database.models import (
    Feature,
    League,
    Match,
    Prediction,
    Team,
    TeamMarketValue,
    ValueBet,
    Weather,
)
from src.delivery.views._badge_helper import render_team_badge


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

MARKET_LABELS = {
    "1X2": "Match Result",
    "OU25": "O/U 2.5",
    "OU15": "O/U 1.5",
    "OU35": "O/U 3.5",
    "BTTS": "BTTS",
}

SELECTION_LABELS = {
    ("1X2", "home"): "Home Win",
    ("1X2", "draw"): "Draw",
    ("1X2", "away"): "Away Win",
    ("OU15", "over"): "Over 1.5",
    ("OU15", "under"): "Under 1.5",
    ("OU25", "over"): "Over 2.5",
    ("OU25", "under"): "Under 2.5",
    ("OU35", "over"): "Over 3.5",
    ("OU35", "under"): "Under 3.5",
    ("BTTS", "yes"): "BTTS Yes",
    ("BTTS", "no"): "BTTS No",
}

# E27-01: Preferred bookmaker — shown by default in value bet cards.
# Falls back to highest-edge bookmaker when preferred isn't available.
PREFERRED_BOOKMAKER = "FanDuel"

CONFIDENCE_COLOURS = {
    "high": COLOURS["green"],
    "medium": COLOURS["yellow"],
    "low": "#484F58",  # MP §8: muted text colour for low confidence
}


# ============================================================================
# Data Loading
# ============================================================================

def load_match_data(match_id: int) -> Optional[Dict]:
    """Load all data needed for the match deep dive.

    Returns a dict with match info, prediction, value bets, features,
    and head-to-head history.  Returns None if the match is not found.
    """
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)

    with get_session() as session:
        result = (
            session.query(Match, HomeTeam, AwayTeam, League)
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .join(League, Match.league_id == League.id)
            .filter(Match.id == match_id)
            .first()
        )

        if not result:
            return None

        match, home_team, away_team, league = result

        # Prediction (most recent model)
        prediction = (
            session.query(Prediction)
            .filter_by(match_id=match_id)
            .order_by(Prediction.created_at.desc())
            .first()
        )

        # Value bets for this match
        value_bets = (
            session.query(ValueBet)
            .filter_by(match_id=match_id)
            .order_by(ValueBet.edge.desc())
            .all()
        )

        # Features for both teams in this match
        home_features = (
            session.query(Feature)
            .filter_by(match_id=match_id, team_id=home_team.id)
            .first()
        )
        away_features = (
            session.query(Feature)
            .filter_by(match_id=match_id, team_id=away_team.id)
            .first()
        )

        # Weather data for this match
        weather = (
            session.query(Weather)
            .filter_by(match_id=match_id)
            .first()
        )

        # Market value data for both teams (most recent snapshot)
        home_market_value = (
            session.query(TeamMarketValue)
            .filter(TeamMarketValue.team_id == home_team.id)
            .order_by(TeamMarketValue.evaluated_at.desc())
            .first()
        )
        away_market_value = (
            session.query(TeamMarketValue)
            .filter(TeamMarketValue.team_id == away_team.id)
            .order_by(TeamMarketValue.evaluated_at.desc())
            .first()
        )

        # Head-to-head: last 5 meetings between these teams
        h2h_matches = (
            session.query(Match, HomeTeam.name.label("hn"), AwayTeam.name.label("an"))
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .filter(
                Match.status == "finished",
                Match.date < match.date,
                (
                    ((Match.home_team_id == home_team.id) & (Match.away_team_id == away_team.id))
                    | ((Match.home_team_id == away_team.id) & (Match.away_team_id == home_team.id))
                ),
            )
            .order_by(Match.date.desc())
            .limit(5)
            .all()
        )

    # Parse scoreline matrix
    scoreline_matrix = None
    if prediction and prediction.scoreline_matrix:
        try:
            scoreline_matrix = json.loads(prediction.scoreline_matrix)
        except (json.JSONDecodeError, TypeError):
            scoreline_matrix = None

    return {
        "match_id": match_id,
        "home_team": home_team.name,
        "away_team": away_team.name,
        "home_team_id": home_team.id,
        "away_team_id": away_team.id,
        "league": league.short_name,
        "league_name": league.name,
        "date": match.date,
        "kickoff": match.kickoff_time or "TBD",
        "status": match.status,
        "home_goals": match.home_goals,
        "away_goals": match.away_goals,
        "prediction": prediction,
        "scoreline_matrix": scoreline_matrix,
        "value_bets": [
            {
                "market_type": vb.market_type,
                "selection": vb.selection,
                "model_prob": vb.model_prob,
                "bookmaker": vb.bookmaker,
                "bookmaker_odds": vb.bookmaker_odds,
                "edge": vb.edge,
                "confidence": vb.confidence,
                "explanation": vb.explanation,
            }
            for vb in value_bets
        ],
        "home_features": home_features,
        "away_features": away_features,
        "weather": {
            "temperature_c": weather.temperature_c,
            "wind_speed_kmh": weather.wind_speed_kmh,
            "precipitation_mm": weather.precipitation_mm,
            "weather_category": weather.weather_category,
        } if weather else None,
        "home_market_value": {
            "squad_total_value": home_market_value.squad_total_value,
            "avg_player_value": home_market_value.avg_player_value,
            "squad_size": home_market_value.squad_size,
        } if home_market_value else None,
        "away_market_value": {
            "squad_total_value": away_market_value.squad_total_value,
            "avg_player_value": away_market_value.avg_player_value,
            "squad_size": away_market_value.squad_size,
        } if away_market_value else None,
        "h2h": [
            {
                "date": m.date,
                "home_team": hn,
                "away_team": an,
                "home_team_id": m.home_team_id,
                "away_team_id": m.away_team_id,
                "home_goals": m.home_goals,
                "away_goals": m.away_goals,
            }
            for m, hn, an in h2h_matches
        ],
    }


# ============================================================================
# Charts
# ============================================================================

def create_scoreline_heatmap(matrix: List[List[float]], home_team: str, away_team: str) -> go.Figure:
    """Create a 7×7 Plotly heatmap of the scoreline probability matrix.

    The matrix is indexed as matrix[home_goals][away_goals].
    The most likely scoreline cell is highlighted with a border.
    """
    arr = np.array(matrix)

    # Find the most likely scoreline
    max_idx = np.unravel_index(arr.argmax(), arr.shape)
    max_home, max_away = max_idx

    # Create text annotations showing probability as percentage
    text = [[f"{arr[h][a]:.1%}" for a in range(7)] for h in range(7)]

    # Highlight the most likely scoreline in the text
    text[max_home][max_away] = f"<b>{arr[max_home][max_away]:.1%}</b>"

    fig = go.Figure(data=go.Heatmap(
        z=arr,
        x=[str(i) for i in range(7)],
        y=[str(i) for i in range(7)],
        text=text,
        texttemplate="%{text}",
        textfont=dict(size=11, family="JetBrains Mono, monospace"),
        colorscale=[
            [0, "#0D1117"],
            [0.25, "#161B22"],
            [0.5, "#1C4532"],
            [0.75, "#2D6A4F"],
            [1.0, "#3FB950"],
        ],
        showscale=False,
        hovertemplate=(
            f"{home_team} %{{y}} - %{{x}} {away_team}<br>"
            "Probability: %{z:.1%}<extra></extra>"
        ),
    ))

    # Highlight the most likely scoreline with a border shape
    fig.add_shape(
        type="rect",
        x0=max_away - 0.5, x1=max_away + 0.5,
        y0=max_home - 0.5, y1=max_home + 0.5,
        line=dict(color=COLOURS["green"], width=3),
    )

    fig.update_layout(
        title="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="JetBrains Mono, monospace",
            color=COLOURS["text_secondary"],
            size=12,
        ),
        xaxis=dict(
            title=f"{away_team} Goals",
            side="top",
            dtick=1,
        ),
        yaxis=dict(
            title=f"{home_team} Goals",
            autorange="reversed",
            dtick=1,
        ),
        margin=dict(l=60, r=20, t=60, b=20),
        height=400,
        width=500,
    )

    return fig


# ============================================================================
# Match Analysis Narrative Rendering (E18-01)
# ============================================================================

# Direction indicators — simple text arrows to keep the design clean
_DIRECTION_ICONS = {
    "positive": "▲",
    "negative": "▼",
    "neutral": "—",
}


def render_match_narrative(data: dict) -> None:
    """Render the Match Analysis narrative card.

    Calls the narrative generator to synthesise feature data into a
    human-readable explanation, then renders it as a styled card.
    Shows headline, expected goals, ranked factors, value summary,
    and result comparison (for finished matches).
    """
    narrative = generate_match_narrative(data)

    if narrative is None:
        # E24-02: More helpful empty state when prediction doesn't exist yet.
        # This happens when the pipeline hasn't run for this match's matchday,
        # or when the match was added after the last feature computation.
        st.markdown(
            '<div class="bv-empty-state">'
            'No model prediction available for this match yet. '
            'Predictions are generated during the morning pipeline run — '
            'check back after the next scheduled run.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # Map colour names to hex design tokens
    colour_map = {
        "green": COLOURS["green"],
        "yellow": COLOURS["yellow"],
        "text": COLOURS["text"],
    }
    headline_hex = colour_map.get(narrative.headline_colour, COLOURS["text"])

    # --- Build the card HTML ---

    # Headline + expected goals
    header_html = (
        f'<div style="font-family: Inter, sans-serif; font-size: 18px; '
        f'font-weight: 700; color: {headline_hex}; margin-bottom: 4px;">'
        f'{narrative.headline}</div>'
        f'<div style="font-family: Inter, sans-serif; font-size: 13px; '
        f'color: {COLOURS["text_secondary"]}; margin-bottom: 16px;">'
        f'Expected goals: '
        f'<span style="font-family: JetBrains Mono, monospace; '
        f'color: {COLOURS["text"]};">{narrative.predicted_home_goals:.2f}</span>'
        f' - '
        f'<span style="font-family: JetBrains Mono, monospace; '
        f'color: {COLOURS["text"]};">{narrative.predicted_away_goals:.2f}</span>'
        f'</div>'
    )

    # Factors section
    factors_html = ""
    if narrative.factors:
        factors_html = (
            f'<div style="font-family: Inter, sans-serif; font-size: 12px; '
            f'color: {COLOURS["text_secondary"]}; text-transform: uppercase; '
            f'letter-spacing: 0.5px; margin-bottom: 8px;">KEY FACTORS</div>'
        )
        for factor in narrative.factors:
            icon = _DIRECTION_ICONS.get(factor.direction, "—")
            if factor.direction == "positive":
                icon_colour = COLOURS["green"]
            elif factor.direction == "negative":
                icon_colour = COLOURS["red"]
            else:
                icon_colour = COLOURS["text_secondary"]

            factors_html += (
                f'<div style="display: flex; align-items: flex-start; gap: 10px; '
                f'padding: 6px 0; border-bottom: 1px solid {COLOURS["border"]};">'
                f'<span style="color: {icon_colour}; font-size: 14px; '
                f'min-width: 18px; font-family: JetBrains Mono, monospace;">'
                f'{icon}</span>'
                f'<div>'
                f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                f'color: {COLOURS["text"]};">{factor.headline}</span><br>'
                f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text_secondary"]};">{factor.detail}</span>'
                f'</div>'
                f'</div>'
            )

    # Value summary
    value_html = ""
    if narrative.value_summary:
        vs = narrative.value_summary
        value_border = COLOURS["green"] if vs.has_value_bets else COLOURS["border"]
        value_html = (
            f'<div style="margin-top: 16px; padding: 10px 12px; border-radius: 6px; '
            f'background-color: {COLOURS["bg"]}; border: 1px solid {value_border};">'
            f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
            f'color: {COLOURS["text_secondary"]}; text-transform: uppercase; '
            f'letter-spacing: 0.5px;">VALUE</span><br>'
            f'<span style="font-family: Inter, sans-serif; font-size: 13px; '
            f'color: {COLOURS["text"]};">{vs.summary_text}</span>'
            f'</div>'
        )

    # Result comparison (finished matches only)
    result_html = ""
    if narrative.result:
        r = narrative.result
        if r.predicted_correct_1x2:
            result_colour = COLOURS["green"]
            result_bg = "#0d2818"
        else:
            result_colour = COLOURS["red"]
            result_bg = "#2d0f0f"

        result_html = (
            f'<div style="margin-top: 12px; padding: 10px 12px; border-radius: 6px; '
            f'background-color: {result_bg}; border: 1px solid {result_colour};">'
            f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
            f'font-weight: 600; color: {result_colour};">'
            f'{r.result_text}</span>'
            f'</div>'
        )

    # Assemble the full card
    st.markdown(
        '<div class="bv-section-header">Match Analysis</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="bv-card" style="border-left: 3px solid {headline_hex};">'
        f'{header_html}'
        f'{factors_html}'
        f'{value_html}'
        f'{result_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


# ============================================================================
# Page Layout
# ============================================================================

# --- E26-02: Resolve match_id from multiple sources ---
# Priority:
#   1. st.session_state["deep_dive_match_id"]  (set by Picks/Fixtures pages)
#   2. st.query_params["match_id"]             (URL sharing / direct link)
#
# Pop from session_state after reading so it doesn't persist across
# unrelated page visits.  Sync to query_params so the URL is shareable.
from datetime import date as _date_type

_match_id_resolved: int | None = None

# Source 1: session_state (cross-page navigation from Picks/Fixtures)
if "deep_dive_match_id" in st.session_state:
    _match_id_resolved = int(st.session_state.pop("deep_dive_match_id"))
    # Sync to query_params so the URL stays shareable
    st.query_params["match_id"] = str(_match_id_resolved)

# Source 2: query_params (direct URL / refresh)
if _match_id_resolved is None:
    _qp = st.query_params.get("match_id", None)
    if _qp:
        try:
            _match_id_resolved = int(_qp)
        except (ValueError, TypeError):
            _match_id_resolved = None

if _match_id_resolved is None:
    # -----------------------------------------------------------------
    # No match selected — show a tabbed picker (E26-02)
    # "Upcoming" = scheduled matches for pre-match analysis
    # "Recent Results" = finished matches for post-match review
    # -----------------------------------------------------------------
    st.markdown(
        '<div class="bv-page-title">Match Deep Dive</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="text-muted">Select a match to view detailed analysis</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    tab_upcoming, tab_recent = st.tabs(["Upcoming", "Recent Results"])

    with tab_upcoming:
        with get_session() as session:
            HomeTeam = aliased(Team)
            AwayTeam = aliased(Team)
            today_str = _date_type.today().isoformat()
            upcoming = (
                session.query(Match, HomeTeam.name, AwayTeam.name)
                .join(HomeTeam, Match.home_team_id == HomeTeam.id)
                .join(AwayTeam, Match.away_team_id == AwayTeam.id)
                .filter(Match.status == "scheduled")
                .filter(Match.date >= today_str)
                .order_by(Match.date.asc())
                .limit(20)
                .all()
            )

        if upcoming:
            upcoming_options = {
                m.id: f"{m.date}: {hn} vs {an}" for m, hn, an in upcoming
            }
            selected_upcoming = st.selectbox(
                "Select an upcoming match",
                options=list(upcoming_options.keys()),
                format_func=lambda x: upcoming_options[x],
                key="upcoming_picker",
            )
            if st.button("View Analysis", type="primary", key="view_upcoming"):
                st.query_params["match_id"] = str(selected_upcoming)
                st.rerun()
        else:
            st.markdown(
                '<div class="bv-empty-state">'
                "No upcoming matches found. The season may be between matchdays."
                "</div>",
                unsafe_allow_html=True,
            )

    with tab_recent:
        with get_session() as session:
            HomeTeam = aliased(Team)
            AwayTeam = aliased(Team)
            recent = (
                session.query(Match, HomeTeam.name, AwayTeam.name)
                .join(HomeTeam, Match.home_team_id == HomeTeam.id)
                .join(AwayTeam, Match.away_team_id == AwayTeam.id)
                .filter(Match.status == "finished")
                .order_by(Match.date.desc())
                .limit(20)
                .all()
            )

        if recent:
            recent_options = {
                m.id: f"{m.date}: {hn} vs {an}" for m, hn, an in recent
            }
            selected_recent = st.selectbox(
                "Select a recent match",
                options=list(recent_options.keys()),
                format_func=lambda x: recent_options[x],
                key="recent_picker",
            )
            if st.button("View Analysis", type="primary", key="view_recent"):
                st.query_params["match_id"] = str(selected_recent)
                st.rerun()
        else:
            st.markdown(
                '<div class="bv-empty-state">'
                "No finished matches available. Run the pipeline first."
                "</div>",
                unsafe_allow_html=True,
            )

else:
    # Load match data
    match_id = _match_id_resolved

    data = load_match_data(match_id)

    if not data:
        st.error(f"Match {match_id} not found.")
        st.stop()

    # --- Back Navigation ---
    if st.button("< Back"):
        st.query_params.clear()
        st.rerun()

    # --- Section 1: Match Header ---
    result_html = ""
    if data["status"] == "finished" and data["home_goals"] is not None:
        result_html = (
            f'<span style="font-family: JetBrains Mono, monospace; font-size: 28px; '
            f'font-weight: 700; color: {COLOURS["text"]};">'
            f'{data["home_goals"]} - {data["away_goals"]}</span>'
        )

    # Build badge + name HTML for the match header (28px badges for header)
    home_badge_html = render_team_badge(
        data["home_team_id"], data["home_team"], size=28,
        name_style=f"font-family: Inter, sans-serif; font-size: 24px; font-weight: 700; color: {COLOURS['text']};",
    )
    away_badge_html = render_team_badge(
        data["away_team_id"], data["away_team"], size=28,
        name_style=f"font-family: Inter, sans-serif; font-size: 24px; font-weight: 700; color: {COLOURS['text']};",
    )

    st.markdown(
        f'<div style="text-align: center; margin-bottom: 24px;">'
        f'<div style="font-family: Inter, sans-serif; font-size: 12px; color: {COLOURS["text_secondary"]}; '
        f'text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">'
        f'{data["league_name"]} &middot; {data["date"]} &middot; {data["kickoff"]}</div>'
        f'<div style="display: flex; align-items: center; justify-content: center; gap: 12px;">'
        f'{home_badge_html}'
        f'<span style="font-family: Inter, sans-serif; font-size: 18px; color: {COLOURS["text_secondary"]};">vs</span>'
        f'{away_badge_html}'
        f'</div>'
        f'<div style="margin-top: 8px;">{result_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # --- Weather Badge (shown only for notable conditions) ---
    weather = data.get("weather")
    if weather:
        category = (weather.get("weather_category") or "").lower()
        precip = weather.get("precipitation_mm") or 0
        wind = weather.get("wind_speed_kmh") or 0
        temp = weather.get("temperature_c")

        # Only show badge for notable weather: rain, heavy rain, snow, storm, or strong wind
        notable = category in ("rain", "heavy_rain", "snow", "storm") or wind > 30

        if notable:
            badges = []
            if category in ("rain", "heavy_rain"):
                badges.append(
                    f'<span class="bv-badge" style="background-color: {COLOURS["blue"]}; '
                    f'color: #fff; margin-right: 6px;">'
                    f'\U0001F327\uFE0F Rain {precip:.1f}mm</span>'
                )
            elif category == "snow":
                badges.append(
                    f'<span class="bv-badge" style="background-color: #A5D6FF; '
                    f'color: #0D1117; margin-right: 6px;">'
                    f'\u2744\uFE0F Snow</span>'
                )
            elif category == "storm":
                badges.append(
                    f'<span class="bv-badge" style="background-color: {COLOURS["yellow"]}; '
                    f'color: #0D1117; margin-right: 6px;">'
                    f'\u26A1 Storm</span>'
                )
            if wind > 30:
                badges.append(
                    f'<span class="bv-badge" style="background-color: {COLOURS["border"]}; '
                    f'color: {COLOURS["text"]}; margin-right: 6px;">'
                    f'\U0001F4A8 Wind {wind:.0f} km/h</span>'
                )
            if temp is not None:
                badges.append(
                    f'<span class="bv-badge" style="background-color: {COLOURS["border"]}; '
                    f'color: {COLOURS["text_secondary"]};">'
                    f'\U0001F321\uFE0F {temp:.0f}\u00B0C</span>'
                )
            st.markdown(
                f'<div style="text-align: center; margin-bottom: 16px;">{"".join(badges)}</div>',
                unsafe_allow_html=True,
            )

    st.divider()

    # --- Section 1b: Match Analysis Narrative (E18-01) ---
    # Synthesises model predictions and feature data into a plain-English
    # explanation of why the model predicts what it predicts.
    render_match_narrative(data)

    st.divider()

    # --- Section 2: Scoreline Matrix ---
    if data["scoreline_matrix"]:
        st.markdown(
            '<div class="bv-section-header">Scoreline Probability Matrix</div>',
            unsafe_allow_html=True,
        )

        # Most likely scoreline
        arr = np.array(data["scoreline_matrix"])
        max_idx = np.unravel_index(arr.argmax(), arr.shape)
        max_prob = arr[max_idx]

        st.markdown(
            f'<p style="font-family: Inter, sans-serif; color: {COLOURS["text_secondary"]}; font-size: 14px;">'
            f'Most likely scoreline: '
            f'<span style="font-family: JetBrains Mono, monospace; color: {COLOURS["green"]}; font-weight: 700;">'
            f'{max_idx[0]}-{max_idx[1]}</span> ({max_prob:.1%})</p>',
            unsafe_allow_html=True,
        )

        fig = create_scoreline_heatmap(
            data["scoreline_matrix"], data["home_team"], data["away_team"],
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        st.divider()

    # --- Section 3: Market Probabilities ---
    pred = data["prediction"]
    if pred:
        st.markdown(
            '<div class="bv-section-header">Market Probabilities</div>',
            unsafe_allow_html=True,
        )

        # 1X2 — the three possible match outcomes
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Home Win", f"{pred.prob_home_win:.1%}")
        with col2:
            st.metric("Draw", f"{pred.prob_draw:.1%}")
        with col3:
            st.metric("Away Win", f"{pred.prob_away_win:.1%}")

        # Over/Under goals — 1.5 and 2.5 thresholds side by side.
        # O/U 1.5 = will there be 2+ goals? O/U 2.5 = will there be 3+ goals?
        # Both are derived from the scoreline matrix via derive_market_probabilities().
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Over 1.5", f"{pred.prob_over_15:.1%}")
        with col2:
            st.metric("Under 1.5", f"{pred.prob_under_15:.1%}")
        with col3:
            st.metric("Over 2.5", f"{pred.prob_over_25:.1%}")
        with col4:
            st.metric("Under 2.5", f"{pred.prob_under_25:.1%}")

        # BTTS — both teams to score at least one goal each
        col1, col2 = st.columns(2)
        with col1:
            st.metric("BTTS Yes", f"{pred.prob_btts_yes:.1%}")
        with col2:
            st.metric("BTTS No", f"{pred.prob_btts_no:.1%}")

        st.divider()

    # --- Section 4: Value Bets ---
    # E24-02: Always show the section header. If no value bets exist
    # (common for scheduled matches before odds arrive), show a clear
    # empty state instead of hiding the section entirely.
    # E27-01: Group by unique (market_type, selection). Show one card per
    # unique bet with FanDuel as the default bookmaker. Falls back to
    # highest-edge bookmaker when FanDuel isn't available. Toggle lets
    # the user switch to Best Edge view or expand All Bookmakers.
    st.markdown(
        '<div class="bv-section-header">Value Bets</div>',
        unsafe_allow_html=True,
    )

    if data["value_bets"]:
        # ----------------------------------------------------------
        # Group value bets by unique (market_type, selection).
        # Each group collects all bookmaker rows for that selection.
        # ----------------------------------------------------------
        grouped_vbs: Dict[Tuple[str, str], List[Dict]] = {}
        for vb in data["value_bets"]:
            key = (vb["market_type"], vb["selection"])
            grouped_vbs.setdefault(key, []).append(vb)

        # Sort each group by edge descending (best bookmaker first)
        for key in grouped_vbs:
            grouped_vbs[key].sort(key=lambda x: -x["edge"])

        # Sort the groups themselves by highest edge (best bet first)
        sorted_groups = sorted(
            grouped_vbs.items(),
            key=lambda item: -item[1][0]["edge"],
        )

        # ----------------------------------------------------------
        # Bookmaker view toggle — lets the user control display mode
        # ----------------------------------------------------------
        view_mode = st.selectbox(
            "Show odds from",
            [
                f"{PREFERRED_BOOKMAKER} (Default)",
                "Best Edge",
                "All Bookmakers",
            ],
            index=0,
            key="vb_view_mode",
            help=(
                f"'{PREFERRED_BOOKMAKER} (Default)' shows {PREFERRED_BOOKMAKER} odds "
                f"per bet (falls back to best edge if unavailable). "
                f"'Best Edge' shows the single best-value bookmaker. "
                f"'All Bookmakers' expands every bookmaker for each bet."
            ),
        )

        # Pre-compute the preferred bookmaker name in lowercase for matching
        _pref_lower = PREFERRED_BOOKMAKER.lower()

        for (mkt, sel), vb_list in sorted_groups:
            sel_label = SELECTION_LABELS.get(
                (mkt, sel), f"{mkt}/{sel}",
            )
            total_bookmakers = len(vb_list)
            # Best edge is always the first item (sorted above)
            best_edge_vb = vb_list[0]

            # Find the preferred bookmaker row (case-insensitive match)
            preferred_vb = None
            for vb in vb_list:
                if vb["bookmaker"].lower().startswith(_pref_lower):
                    preferred_vb = vb
                    break

            # ----------------------------------------------------------
            # Determine which bookmaker(s) to display based on view mode
            # ----------------------------------------------------------
            if view_mode == "All Bookmakers":
                # Show every bookmaker in this group
                display_vbs = vb_list
            elif view_mode == "Best Edge":
                # Show only the single highest-edge bookmaker
                display_vbs = [best_edge_vb]
            else:
                # Preferred bookmaker (Default): show preferred if available, else best edge
                display_vbs = [preferred_vb if preferred_vb else best_edge_vb]

            # Count of alternative bookmakers (excluding the displayed one)
            alt_count = total_bookmakers - len(display_vbs)
            if alt_count < 0:
                alt_count = 0

            # ----------------------------------------------------------
            # Render a selection header when showing All Bookmakers
            # ----------------------------------------------------------
            if view_mode == "All Bookmakers" and len(display_vbs) > 1:
                st.markdown(
                    f'<div style="font-family: Inter, sans-serif; font-size: 13px; '
                    f'font-weight: 600; color: {COLOURS["text"]}; '
                    f'margin-top: 12px; margin-bottom: 4px;">'
                    f'{sel_label} — {total_bookmakers} bookmaker{"s" if total_bookmakers != 1 else ""}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            for vb in display_vbs:
                conf_colour = CONFIDENCE_COLOURS.get(
                    vb["confidence"], COLOURS["border"],
                )
                edge_pct = vb["edge"] * 100

                # Model probability vs implied probability for context
                model_prob_pct = vb["model_prob"] * 100 if vb.get("model_prob") else None
                implied_prob = (1.0 / vb["bookmaker_odds"]) * 100 if vb["bookmaker_odds"] > 0 else None

                # Probability comparison text (model vs implied)
                prob_text = ""
                if model_prob_pct is not None and implied_prob is not None:
                    prob_text = (
                        f'<span style="font-family: JetBrains Mono, monospace; '
                        f'font-size: 11px; color: {COLOURS["text_secondary"]}; '
                        f'margin-left: 8px;">'
                        f'Model {model_prob_pct:.0f}% vs Implied {implied_prob:.0f}%'
                        f'</span>'
                    )

                # Alt bookmakers count (only in single-card views)
                alt_text = ""
                if view_mode != "All Bookmakers" and alt_count > 0:
                    # Grammar: "1 other bookmaker also offers value"
                    #          "44 other bookmakers also offer value"
                    bk_plural = "bookmaker" if alt_count == 1 else "bookmakers"
                    verb = "offers" if alt_count == 1 else "offer"
                    alt_text = (
                        f'<div style="font-family: Inter, sans-serif; font-size: 11px; '
                        f'color: {COLOURS["text_secondary"]}; margin-top: 2px;">'
                        f'{alt_count} other {bk_plural} also {verb} value'
                        f'</div>'
                    )

                # Is this the preferred bookmaker? Show a fallback indicator if not
                is_preferred = vb["bookmaker"].lower().startswith(_pref_lower)
                bk_indicator = ""
                if not is_preferred and view_mode.startswith(PREFERRED_BOOKMAKER):
                    # Fallback indicator — preferred bookmaker wasn't available
                    bk_indicator = (
                        f'<span style="font-family: Inter, sans-serif; font-size: 10px; '
                        f'color: {COLOURS["yellow"]}; margin-left: 4px;">'
                        f'({PREFERRED_BOOKMAKER} N/A)</span>'
                    )

                st.markdown(
                    f'<div class="bv-card" style="padding: 10px 14px; margin-bottom: 6px;">'
                    f'<div style="display: flex; justify-content: space-between; align-items: center;">'
                    f'<div>'
                    f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'font-weight: 600; color: {COLOURS["text"]};">'
                    f'{sel_label}</span>'
                    f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
                    f'color: {COLOURS["text_secondary"]}; margin-left: 8px;">'
                    f'{vb["bookmaker"]} @ {vb["bookmaker_odds"]:.2f}</span>'
                    f'{bk_indicator}'
                    f'{prob_text}'
                    f'</div>'
                    f'<div style="display: flex; align-items: center; gap: 12px;">'
                    f'<span style="font-family: JetBrains Mono, monospace; font-size: 14px; '
                    f'font-weight: 700; color: {COLOURS["green"]};">+{edge_pct:.1f}%</span>'
                    f'<span class="bv-badge" style="background-color: {conf_colour};">'
                    f'{(vb["confidence"] or "low").upper()}</span>'
                    f'</div>'
                    f'</div>'
                    f'{alt_text}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
    else:
        st.markdown(
            f'<div style="font-family: Inter, sans-serif; font-size: 13px; '
            f'color: {COLOURS["text_secondary"]}; padding: 12px 0;">'
            f'No value bets identified for this match. The model found no selections '
            f'where the edge exceeds the minimum threshold, or odds data has not been '
            f'loaded yet.</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Section 5: Head-to-Head ---
    st.markdown(
        '<div class="bv-section-header">Head-to-Head</div>',
        unsafe_allow_html=True,
    )

    if data["h2h"]:
        for h in data["h2h"]:
            # Render badges inline beside team names (20px for H2H rows)
            h2h_home = render_team_badge(h["home_team_id"], h["home_team"], size=20)
            h2h_away = render_team_badge(h["away_team_id"], h["away_team"], size=20)
            st.markdown(
                f'<div class="bv-card" style="display: flex; align-items: center; '
                f'gap: 12px; padding: 10px 16px;">'
                f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                f'color: {COLOURS["text_secondary"]}; min-width: 85px;">{h["date"]}</span>'
                f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                f'color: {COLOURS["text"]}; min-width: 200px; text-align: right;">'
                f'{h2h_home}</span>'
                f'<span style="font-family: JetBrains Mono, monospace; font-size: 14px; '
                f'font-weight: 700; color: {COLOURS["text"]}; min-width: 50px; text-align: center;">'
                f'{h["home_goals"]} - {h["away_goals"]}</span>'
                f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                f'color: {COLOURS["text"]};">{h2h_away}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div class="bv-empty-state">'
            "No previous meetings found between these teams in the database."
            "</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Section 6: Team Form (Side-by-Side) ---
    hf = data["home_features"]
    af = data["away_features"]

    if hf or af:
        st.markdown(
            '<div class="bv-section-header">Team Form</div>',
            unsafe_allow_html=True,
        )

        col_home, col_away = st.columns(2)

        def render_stat_row(label: str, home_val, away_val, fmt: str = ".2f") -> None:
            """Render a side-by-side stat comparison row."""
            hv = f"{home_val:{fmt}}" if home_val is not None else "—"
            av = f"{away_val:{fmt}}" if away_val is not None else "—"

            st.markdown(
                f'<div style="display: flex; justify-content: space-between; padding: 6px 0; '
                f'border-bottom: 1px solid {COLOURS["border"]};">'
                f'<span style="font-family: JetBrains Mono, monospace; font-size: 14px; '
                f'color: {COLOURS["text"]}; width: 80px; text-align: right;">{hv}</span>'
                f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text_secondary"]}; text-transform: uppercase; '
                f'letter-spacing: 0.5px;">{label}</span>'
                f'<span style="font-family: JetBrains Mono, monospace; font-size: 14px; '
                f'color: {COLOURS["text"]}; width: 80px;">{av}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # Header with team badges (20px inline badges)
        form_home = render_team_badge(
            data["home_team_id"], data["home_team"], size=20,
            name_style=f"font-family: Inter, sans-serif; font-size: 16px; font-weight: 600; color: {COLOURS['text']};",
        )
        form_away = render_team_badge(
            data["away_team_id"], data["away_team"], size=20,
            name_style=f"font-family: Inter, sans-serif; font-size: 16px; font-weight: 600; color: {COLOURS['text']};",
        )
        st.markdown(
            f'<div style="display: flex; justify-content: space-between; align-items: center; '
            f'padding: 8px 0; margin-bottom: 8px;">'
            f'<span>{form_home}</span>'
            f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
            f'color: {COLOURS["text_secondary"]};">vs</span>'
            f'<span>{form_away}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Stats rows — basic form metrics
        basic_stats = [
            ("Form (5)", getattr(hf, "form_5", None), getattr(af, "form_5", None)),
            ("Form (10)", getattr(hf, "form_10", None), getattr(af, "form_10", None)),
            ("Goals Scored", getattr(hf, "goals_scored_5", None), getattr(af, "goals_scored_5", None)),
            ("Goals Conceded", getattr(hf, "goals_conceded_5", None), getattr(af, "goals_conceded_5", None)),
            ("xG", getattr(hf, "xg_5", None), getattr(af, "xg_5", None)),
            ("xGA", getattr(hf, "xga_5", None), getattr(af, "xga_5", None)),
            ("Venue Form", getattr(hf, "venue_form_5", None), getattr(af, "venue_form_5", None)),
            ("Venue xG", getattr(hf, "venue_xg_5", None), getattr(af, "venue_xg_5", None)),
            ("Rest Days", getattr(hf, "rest_days", None), getattr(af, "rest_days", None), ".0f"),
        ]

        for item in basic_stats:
            label, hv, av = item[0], item[1], item[2]
            fmt = item[3] if len(item) > 3 else ".2f"
            render_stat_row(label, hv, av, fmt)

        # --- Advanced Stats sub-header (NPxG, PPDA, Deep Completions from E16) ---
        # Check if any advanced stat data exists for either team
        has_advanced = any([
            getattr(hf, "npxg_5", None), getattr(af, "npxg_5", None),
            getattr(hf, "ppda_5", None), getattr(af, "ppda_5", None),
            getattr(hf, "deep_5", None), getattr(af, "deep_5", None),
        ])

        if has_advanced:
            st.markdown(
                f'<div style="font-family: Inter, sans-serif; font-size: 13px; '
                f'font-weight: 600; color: {COLOURS["text_secondary"]}; '
                f'text-transform: uppercase; letter-spacing: 0.5px; '
                f'margin-top: 16px; margin-bottom: 8px;">Advanced Stats</div>',
                unsafe_allow_html=True,
            )

            advanced_stats = [
                # NPxG: Non-penalty expected goals — strips out penalty xG for a
                # truer measure of open-play attacking quality
                ("NPxG (5)", getattr(hf, "npxg_5", None), getattr(af, "npxg_5", None)),
                ("NPxGA (5)", getattr(hf, "npxga_5", None), getattr(af, "npxga_5", None)),
                ("NPxG Diff", getattr(hf, "npxg_diff_5", None), getattr(af, "npxg_diff_5", None)),
                # PPDA: Passes Per Defensive Action — lower means more aggressive
                # pressing (e.g., Liverpool ~8, Burnley ~18)
                ("PPDA (5)", getattr(hf, "ppda_5", None), getattr(af, "ppda_5", None), ".1f"),
                ("PPDA Allowed", getattr(hf, "ppda_allowed_5", None), getattr(af, "ppda_allowed_5", None), ".1f"),
                # Deep completions: passes reaching the opponent penalty area —
                # measures attacking penetration quality
                ("Deep Comps (5)", getattr(hf, "deep_5", None), getattr(af, "deep_5", None)),
                ("Deep Allowed", getattr(hf, "deep_allowed_5", None), getattr(af, "deep_allowed_5", None)),
            ]

            for item in advanced_stats:
                label, hv, av = item[0], item[1], item[2]
                fmt = item[3] if len(item) > 3 else ".2f"
                render_stat_row(label, hv, av, fmt)

    else:
        st.markdown(
            '<div class="bv-empty-state">'
            "Feature data not available for this match."
            "</div>",
            unsafe_allow_html=True,
        )

    # --- Section 7: Market Value Comparison ---
    # Shows squad values from Transfermarkt when available — richer squads
    # generally outperform poorer ones beyond what recent form shows
    home_mv = data.get("home_market_value")
    away_mv = data.get("away_market_value")

    if home_mv or away_mv:
        st.divider()
        st.markdown(
            '<div class="bv-section-header">Squad Value</div>',
            unsafe_allow_html=True,
        )

        def _fmt_eur(value: float) -> str:
            """Format a euro value into a readable string (e.g. €253.4m)."""
            if value is None:
                return "—"
            if value >= 1_000_000_000:
                return f"\u20AC{value / 1_000_000_000:.1f}b"
            if value >= 1_000_000:
                return f"\u20AC{value / 1_000_000:.0f}m"
            return f"\u20AC{value:,.0f}"

        col_h, col_a = st.columns(2)
        with col_h:
            if home_mv:
                st.markdown(
                    f'<div class="bv-card" style="text-align: center;">'
                    f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'font-weight: 600; color: {COLOURS["text"]}; margin-bottom: 8px;">'
                    f'{data["home_team"]}</div>'
                    f'<div style="font-family: JetBrains Mono, monospace; font-size: 22px; '
                    f'font-weight: 700; color: {COLOURS["text"]};">'
                    f'{_fmt_eur(home_mv["squad_total_value"])}</div>'
                    f'<div style="font-family: Inter, sans-serif; font-size: 12px; '
                    f'color: {COLOURS["text_secondary"]}; margin-top: 4px;">'
                    f'{home_mv["squad_size"]} players</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="bv-card" style="text-align: center;">'
                    f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'font-weight: 600; color: {COLOURS["text"]};">{data["home_team"]}</div>'
                    f'<div style="color: {COLOURS["text_secondary"]}; margin-top: 8px;">—</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        with col_a:
            if away_mv:
                st.markdown(
                    f'<div class="bv-card" style="text-align: center;">'
                    f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'font-weight: 600; color: {COLOURS["text"]}; margin-bottom: 8px;">'
                    f'{data["away_team"]}</div>'
                    f'<div style="font-family: JetBrains Mono, monospace; font-size: 22px; '
                    f'font-weight: 700; color: {COLOURS["text"]};">'
                    f'{_fmt_eur(away_mv["squad_total_value"])}</div>'
                    f'<div style="font-family: Inter, sans-serif; font-size: 12px; '
                    f'color: {COLOURS["text_secondary"]}; margin-top: 4px;">'
                    f'{away_mv["squad_size"]} players</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="bv-card" style="text-align: center;">'
                    f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'font-weight: 600; color: {COLOURS["text"]};">{data["away_team"]}</div>'
                    f'<div style="color: {COLOURS["text_secondary"]}; margin-top: 8px;">—</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # Show market value ratio if available from the feature model
        if hf and getattr(hf, "market_value_ratio", None):
            ratio = hf.market_value_ratio
            ratio_text = f"{ratio:.2f}x" if ratio >= 1 else f"{1/ratio:.2f}x"
            favoured = data["home_team"] if ratio >= 1 else data["away_team"]
            st.markdown(
                f'<p style="text-align: center; font-family: Inter, sans-serif; '
                f'font-size: 13px; color: {COLOURS["text_secondary"]}; margin-top: 8px;">'
                f'Value ratio: <span style="font-family: JetBrains Mono, monospace; '
                f'color: {COLOURS["text"]};">{ratio_text}</span> '
                f'in favour of {favoured}</p>',
                unsafe_allow_html=True,
            )

    # ========================================================================
    # Glossary / Key — explains every stat and betting term on this page
    # ========================================================================
    # The owner is learning (MP §12).  This section gives short, plain-English
    # definitions so anyone can understand the deep dive without prior knowledge.

    st.divider()
    with st.expander("Glossary — What do these stats mean?", expanded=False):
        # CSS for the glossary — consistent with the design system
        st.markdown(
            '<style>'
            '.gloss-section { margin-bottom: 18px; }'
            '.gloss-title {'
            '  font-family: Inter, sans-serif; font-size: 14px; font-weight: 700;'
            '  color: #3FB950; text-transform: uppercase; letter-spacing: 0.5px;'
            '  margin-bottom: 8px; border-bottom: 1px solid #21262D; padding-bottom: 4px;'
            '}'
            '.gloss-row {'
            '  display: flex; gap: 8px; margin-bottom: 6px; line-height: 1.45;'
            '}'
            '.gloss-term {'
            '  font-family: "JetBrains Mono", monospace; font-size: 12px;'
            '  font-weight: 600; color: #E6EDF3; min-width: 140px; flex-shrink: 0;'
            '}'
            '.gloss-def {'
            '  font-family: Inter, sans-serif; font-size: 12px; color: #8B949E;'
            '}'
            '</style>',
            unsafe_allow_html=True,
        )

        # --- Form & Performance ---
        st.markdown(
            '<div class="gloss-section">'
            '<div class="gloss-title">Form &amp; Performance</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Form (5 / 10)</span>'
            '  <span class="gloss-def">Points per game (PPG) over the last 5 or 10 matches. '
            '3.0 = won every game, 0.0 = lost every game. A gap of 0.5+ PPG is significant.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Goals Scored</span>'
            '  <span class="gloss-def">Average goals scored per match in the rolling window. '
            'Higher = more attacking output.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Goals Conceded</span>'
            '  <span class="gloss-def">Average goals allowed per match. '
            'Lower = better defensive record.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Rest Days</span>'
            '  <span class="gloss-def">Days since the team\'s last competitive match. '
            'A gap of 2+ days between teams gives the rested side an edge.</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # --- Expected Goals (xG) ---
        st.markdown(
            '<div class="gloss-section">'
            '<div class="gloss-title">Expected Goals (xG)</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">xG</span>'
            '  <span class="gloss-def">Expected Goals \u2014 the sum of the probability of each shot '
            'going in, based on shot position, angle, and type. '
            'Measures chance quality, not luck. If a team has xG 2.1 but scored 0, '
            'they were unlucky.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">xGA</span>'
            '  <span class="gloss-def">Expected Goals Against \u2014 how many quality chances '
            'opponents created against this team. Lower = harder to break down.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">NPxG</span>'
            '  <span class="gloss-def">Non-Penalty Expected Goals \u2014 same as xG but excludes penalty kicks. '
            'A cleaner measure of open-play attacking quality.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">NPxGA</span>'
            '  <span class="gloss-def">Non-Penalty xG Against \u2014 defensive quality excluding penalties conceded.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">NPxG Diff</span>'
            '  <span class="gloss-def">NPxG minus NPxGA. Positive = team creates better chances than they allow. '
            'The single best measure of overall open-play quality.</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # --- Pressing & Penetration ---
        st.markdown(
            '<div class="gloss-section">'
            '<div class="gloss-title">Pressing &amp; Penetration</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">PPDA</span>'
            '  <span class="gloss-def">Passes Per Defensive Action \u2014 how many passes the '
            'opponent completes before the team wins the ball. '
            'Lower = aggressive pressing (e.g. Liverpool \u2248 8). '
            'Higher = deep block / counter-attack style (e.g. Burnley \u2248 18).</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">PPDA Allowed</span>'
            '  <span class="gloss-def">The reverse: how many passes this team makes before '
            'the opponent wins it back. Reflects how much pressing this team faces.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Deep Comps</span>'
            '  <span class="gloss-def">Deep Completions \u2014 passes that reach the opponent\'s '
            'penalty area. Measures how often a team creates danger in the final third.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Deep Allowed</span>'
            '  <span class="gloss-def">How many deep completions the opponent achieves against this team. '
            'Lower = better at keeping opponents away from the box.</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # --- Model & Predictions ---
        st.markdown(
            '<div class="gloss-section">'
            '<div class="gloss-title">Model &amp; Predictions</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Poisson Model</span>'
            '  <span class="gloss-def">A statistical model that predicts how many goals each team '
            'will score using historical performance data. Outputs a lambda (\u03BB) value '
            'for each team \u2014 the expected goals in this match.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Lambda (\u03BB)</span>'
            '  <span class="gloss-def">The model\'s expected goals for a team in this specific match. '
            'E.g. \u03BB = 1.8 means the model expects roughly 1\u20132 goals, '
            'with 3+ possible but less likely.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Scoreline Matrix</span>'
            '  <span class="gloss-def">A 7\u00D77 grid showing the probability of every possible scoreline '
            '(0\u20130 through 6\u20136). Darker green = higher probability. The model derives '
            'all market probabilities (1X2, O/U, BTTS) from this matrix.</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # --- Market Probabilities ---
        st.markdown(
            '<div class="gloss-section">'
            '<div class="gloss-title">Market Probabilities</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">1X2</span>'
            '  <span class="gloss-def">The three possible match outcomes: '
            'Home Win (1), Draw (X), Away Win (2). The most common betting market.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Over / Under 1.5</span>'
            '  <span class="gloss-def">Whether total goals will be 2 or more (Over) or '
            '0\u20131 (Under). Under 1.5 is rare in top leagues (~15\u201320% of EPL matches).</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Over / Under 2.5</span>'
            '  <span class="gloss-def">Whether total goals will be 3 or more (Over) or 2 or fewer (Under). '
            'The 2.5 threshold is the most popular goals line in betting (~50/50 split).</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">BTTS</span>'
            '  <span class="gloss-def">Both Teams to Score \u2014 will each team get at least one goal? '
            'Derived from the scoreline matrix by summing all cells where both scores &gt; 0.</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # --- Value Betting ---
        st.markdown(
            '<div class="gloss-section">'
            '<div class="gloss-title">Value Betting</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Value Bet</span>'
            '  <span class="gloss-def">A bet where the model thinks the outcome is more likely than '
            'the bookmaker does. Over time, consistently finding value bets is how '
            'the model aims to be profitable.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Edge</span>'
            '  <span class="gloss-def">The difference between the model\'s probability and the bookmaker\'s '
            'implied probability. <span style="color: #3FB950;">Positive edge = the bet is '
            'underpriced</span> (model thinks it\'s more likely than the odds suggest). '
            'This is the core concept behind profitable betting.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Implied Probability</span>'
            '  <span class="gloss-def">What the bookmaker\'s odds suggest the true probability is: '
            '1 \u00F7 decimal odds. E.g. odds of 2.50 imply a 40% probability.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Model vs Implied</span>'
            '  <span class="gloss-def">Shows the model\'s probability alongside the bookmaker\'s '
            'implied probability. The gap between them is the edge.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Confidence</span>'
            '  <span class="gloss-def">How strong the edge is. '
            'HIGH = large edge with high model certainty, '
            'LOW = marginal edge. Higher confidence bets are more reliable.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Bookmaker Toggle</span>'
            '  <span class="gloss-def">Switch between FanDuel odds (default), the highest-edge '
            'bookmaker, or expand all bookmakers. Different bookmakers price the same outcome '
            'differently \u2014 the toggle lets you compare.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Other Bookmakers</span>'
            '  <span class="gloss-def">How many additional bookmakers also offer value for this '
            'selection. More bookmakers = more confidence the value is real.</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # --- Squad & Context ---
        st.markdown(
            '<div class="gloss-section">'
            '<div class="gloss-title">Squad &amp; Context</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Squad Value</span>'
            '  <span class="gloss-def">Total market value of all squad players (from Transfermarkt). '
            'A proxy for long-term quality \u2014 a \u20AC800m squad is generally deeper '
            'and more talented than a \u20AC200m squad. A ratio above 1.5x is significant.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">H2H Record</span>'
            '  <span class="gloss-def">Head-to-Head \u2014 historical results between these two teams. '
            'Some teams consistently struggle against specific opponents regardless of form.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Venue Form</span>'
            '  <span class="gloss-def">A team\'s record specifically at home or away, which can differ '
            'significantly from their overall form. Some teams are '
            '"fortress" at home but weak on the road.</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term">Weather Impact</span>'
            '  <span class="gloss-def">Heavy rain, strong wind, or snow can reduce passing accuracy '
            'and goal-scoring. The model flags these as contextual factors when conditions are extreme.</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # --- Narrative Icons ---
        st.markdown(
            '<div class="gloss-section">'
            '<div class="gloss-title">Analysis Icons</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term" style="color: #3FB950;">\u25B2 Green</span>'
            '  <span class="gloss-def">Factor supports the model\'s prediction '
            '(e.g. strong form for the favoured team).</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term" style="color: #F85149;">\u25BC Red</span>'
            '  <span class="gloss-def">Factor works against the prediction '
            '(e.g. poor away form for the team expected to win).</span>'
            '</div>'
            '<div class="gloss-row">'
            '  <span class="gloss-term" style="color: #8B949E;">\u2014 Grey</span>'
            '  <span class="gloss-def">Neutral context \u2014 worth knowing but doesn\'t clearly '
            'favour either side (e.g. even H2H record).</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
