"""
BetVector — Match Deep Dive View (E9-05)
==========================================
Comprehensive analysis for a single match.  Accessible from Today's Picks
cards and League Explorer upcoming fixtures via ``?match_id=<id>`` query
parameter.

Sections:
1. Match header — teams, date, kickoff, league, actual result (if finished)
2. Scoreline matrix — 7×7 Plotly heatmap with most likely scoreline highlighted
3. Market probabilities — 1X2, O/U 2.5, BTTS derived from the matrix
4. Value bets — all flagged bets for this match with edge and confidence
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
    ("OU25", "over"): "Over 2.5",
    ("OU25", "under"): "Under 2.5",
    ("BTTS", "yes"): "Yes",
    ("BTTS", "no"): "No",
}

CONFIDENCE_COLOURS = {
    "high": COLOURS["green"],
    "medium": COLOURS["yellow"],
    "low": COLOURS["border"],
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
        st.markdown(
            '<div class="bv-empty-state">'
            'No model prediction available for this match yet.'
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

# Get match_id from query params
params = st.query_params
match_id_str = params.get("match_id", None)

if not match_id_str:
    # No match selected — show a picker for demo/development
    st.markdown(
        '<div class="bv-page-title">Match Deep Dive</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="text-muted">Select a match to view detailed analysis</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    # Show a match selector for development/navigation
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
        match_options = {
            m.id: f"{m.date}: {hn} vs {an}" for m, hn, an in recent
        }
        selected_id = st.selectbox(
            "Select a match",
            options=list(match_options.keys()),
            format_func=lambda x: match_options[x],
        )
        if st.button("View Analysis", type="primary"):
            st.query_params["match_id"] = str(selected_id)
            st.rerun()
    else:
        st.markdown(
            '<div class="bv-empty-state">'
            "No matches available. Run the pipeline first."
            "</div>",
            unsafe_allow_html=True,
        )

else:
    # Load match data
    try:
        match_id = int(match_id_str)
    except (ValueError, TypeError):
        st.error("Invalid match ID.")
        st.stop()

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

    st.markdown(
        f'<div style="text-align: center; margin-bottom: 24px;">'
        f'<div style="font-family: Inter, sans-serif; font-size: 12px; color: {COLOURS["text_secondary"]}; '
        f'text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">'
        f'{data["league_name"]} &middot; {data["date"]} &middot; {data["kickoff"]}</div>'
        f'<div style="font-family: Inter, sans-serif; font-size: 24px; font-weight: 700; color: {COLOURS["text"]};">'
        f'{data["home_team"]} vs {data["away_team"]}</div>'
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

        # 1X2
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Home Win", f"{pred.prob_home_win:.1%}")
        with col2:
            st.metric("Draw", f"{pred.prob_draw:.1%}")
        with col3:
            st.metric("Away Win", f"{pred.prob_away_win:.1%}")

        # O/U 2.5 and BTTS
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Over 2.5", f"{pred.prob_over_25:.1%}")
        with col2:
            st.metric("Under 2.5", f"{pred.prob_under_25:.1%}")
        with col3:
            st.metric("BTTS Yes", f"{pred.prob_btts_yes:.1%}")
        with col4:
            st.metric("BTTS No", f"{pred.prob_btts_no:.1%}")

        st.divider()

    # --- Section 4: Value Bets ---
    if data["value_bets"]:
        st.markdown(
            '<div class="bv-section-header">Value Bets</div>',
            unsafe_allow_html=True,
        )

        for vb in data["value_bets"]:
            sel_label = SELECTION_LABELS.get(
                (vb["market_type"], vb["selection"]),
                f"{vb['market_type']}/{vb['selection']}",
            )
            conf_colour = CONFIDENCE_COLOURS.get(vb["confidence"], COLOURS["border"])
            edge_pct = vb["edge"] * 100

            st.markdown(
                f'<div class="bv-card" style="display: flex; justify-content: space-between; align-items: center;">'
                f'<div>'
                f'<span style="font-family: Inter, sans-serif; font-size: 14px; color: {COLOURS["text"]};">'
                f'{sel_label}</span>'
                f'<span style="font-family: Inter, sans-serif; font-size: 12px; color: {COLOURS["text_secondary"]}; margin-left: 8px;">'
                f'({vb["bookmaker"]} @ {vb["bookmaker_odds"]:.2f})</span>'
                f'</div>'
                f'<div style="display: flex; align-items: center; gap: 12px;">'
                f'<span style="font-family: JetBrains Mono, monospace; font-size: 14px; font-weight: 700; '
                f'color: {COLOURS["green"]};">+{edge_pct:.1f}%</span>'
                f'<span class="bv-badge" style="background-color: {conf_colour};">'
                f'{vb["confidence"].upper()}</span>'
                f'</div>'
                f'</div>',
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
            st.markdown(
                f'<div class="bv-card" style="display: flex; align-items: center; '
                f'gap: 12px; padding: 10px 16px;">'
                f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                f'color: {COLOURS["text_secondary"]}; min-width: 85px;">{h["date"]}</span>'
                f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                f'color: {COLOURS["text"]}; min-width: 180px; text-align: right;">'
                f'{h["home_team"]}</span>'
                f'<span style="font-family: JetBrains Mono, monospace; font-size: 14px; '
                f'font-weight: 700; color: {COLOURS["text"]}; min-width: 50px; text-align: center;">'
                f'{h["home_goals"]} - {h["away_goals"]}</span>'
                f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                f'color: {COLOURS["text"]};">{h["away_team"]}</span>'
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

        # Header
        st.markdown(
            f'<div style="display: flex; justify-content: space-between; padding: 8px 0; margin-bottom: 8px;">'
            f'<span style="font-family: Inter, sans-serif; font-size: 16px; font-weight: 600; '
            f'color: {COLOURS["text"]};">{data["home_team"]}</span>'
            f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
            f'color: {COLOURS["text_secondary"]};">vs</span>'
            f'<span style="font-family: Inter, sans-serif; font-size: 16px; font-weight: 600; '
            f'color: {COLOURS["text"]};">{data["away_team"]}</span>'
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
