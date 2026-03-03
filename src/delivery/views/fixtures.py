"""
BetVector — Fixtures Page (E17-04, E24-03, E24-04, E26-03)
============================================================
All upcoming matches across active leagues, grouped by date.
**E26-03: Now the dashboard landing page.**

Different from Today's Picks:
- **Today's Picks** = "here are the value bets the model likes"
- **Fixtures** = "here are ALL matches happening, with color-coded model
  indicators for every market"

E24-03: Added inline color-coded market indicators per fixture row.
E27-02: Expanded to 9 badges by adding Over/Under 1.5 goals.
For each scheduled match, 9 compact badges show the model's view:
Home/Draw/Away (1X2), Over/Under 1.5, Over/Under 2.5, BTTS Yes/No.
Colour coding:  green = strong edge, yellow = marginal, red = no edge,
grey = no data.

E24-04: Added pipeline health summary and diagnostic badges.
- Pipeline coverage bar at top: "X/Y fixtures have full prediction + odds data"
- Per-fixture diagnostic badges: "No pred", "No odds", "Full data", or "X VB"
- Blue left border for full-data fixtures, green for value bet fixtures
- Info tip when odds coverage is below 70% (explains bookmaker pricing window)

E26-03: Landing page enhancements:
- Top Picks banner: 3-5 highest-edge value bets (grouped by unique pick)
  shown prominently at the top of the page.
- Predicted score per fixture: "Model: X.X - X.X" inline below market badges.
- Fixtures page is now default=True in dashboard.py.

Master Plan refs: MP §3 Flow 4 (Dashboard Exploration), MP §8 Design System
"""

from datetime import date, timedelta
from html import escape as html_escape
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
# Market badge definitions — the 9 selections shown per fixture.
# Each tuple: (market_type_db, selection_db, badge_label)
# These correspond to ValueBet.market_type and ValueBet.selection values.
# Order: 1X2 → O/U 1.5 → O/U 2.5 → BTTS (natural threshold progression)
# ============================================================================

MARKET_BADGES = [
    ("1X2", "home", "H"),
    ("1X2", "draw", "D"),
    ("1X2", "away", "A"),
    ("OU15", "over", "O1.5"),
    ("OU15", "under", "U1.5"),
    ("OU25", "over", "O2.5"),
    ("OU25", "under", "U2.5"),
    ("BTTS", "yes", "BTTS Y"),
    ("BTTS", "no", "BTTS N"),
]

# Map Prediction attributes to (market_type, selection) for probability lookups.
# The Prediction model stores derived probabilities from the scoreline matrix.
PRED_PROB_MAP = {
    ("1X2", "home"): "prob_home_win",
    ("1X2", "draw"): "prob_draw",
    ("1X2", "away"): "prob_away_win",
    ("OU15", "over"): "prob_over_15",
    ("OU15", "under"): "prob_under_15",
    ("OU25", "over"): "prob_over_25",
    ("OU25", "under"): "prob_under_25",
    ("BTTS", "yes"): "prob_btts_yes",
    ("BTTS", "no"): "prob_btts_no",
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

            # Check if this match has ANY odds loaded (any source)
            odds_count = (
                session.query(Odds)
                .filter_by(match_id=match.id)
                .count()
            )

            # Compute per-market edges by comparing model probs to best odds.
            # For each of the 9 market selections, we need:
            #   1. model_prob from Prediction attributes
            #   2. best available odds from the Odds table
            #   3. edge = model_prob - (1.0 / odds)
            market_edges = {}
            for market_type, selection, _label in MARKET_BADGES:
                edge = _compute_edge(
                    session, match.id, prediction, market_type, selection,
                )
                market_edges[(market_type, selection)] = edge

            # E26-03: Extract predicted goals for inline display.
            # These come from the Poisson model's expected goals output.
            pred_home_goals = None
            pred_away_goals = None
            if prediction is not None:
                pred_home_goals = getattr(prediction, "predicted_home_goals", None)
                pred_away_goals = getattr(prediction, "predicted_away_goals", None)

            results.append({
                "match_id": match.id,
                "date": match.date,
                "kickoff": html_escape(match.kickoff_time or "TBD"),
                "home_team": html_escape(home_team.name),
                "away_team": html_escape(away_team.name),
                "league": html_escape(league.short_name),
                "league_name": html_escape(league.name),
                "has_value_bets": vb_count > 0,
                "value_bet_count": vb_count,
                "has_prediction": prediction is not None,
                "has_odds": odds_count > 0,
                "odds_count": odds_count,
                "market_edges": market_edges,
                "predicted_home_goals": pred_home_goals,
                "predicted_away_goals": pred_away_goals,
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


def get_top_picks(max_picks: int = 5) -> List[Dict]:
    """Fetch the highest-edge value bets across all upcoming fixtures.

    E26-03: Used for the Top Picks banner at the top of the Fixtures page.
    Groups by (match_id, market_type, selection) to avoid per-bookmaker
    duplication (same logic as picks.py E26-01).  Returns the top N picks
    sorted by edge descending.

    Parameters
    ----------
    max_picks : int
        Maximum number of top picks to return (default 5).

    Returns
    -------
    list[dict]
        Top value bet picks with team names, market, bookmaker, odds, edge.
    """
    HomeTeam = aliased(Team)
    AwayTeam = aliased(Team)
    today_str = date.today().isoformat()

    with get_session() as session:
        rows = (
            session.query(ValueBet, Match, League, HomeTeam.name, AwayTeam.name)
            .join(Match, ValueBet.match_id == Match.id)
            .join(League, Match.league_id == League.id)
            .join(HomeTeam, Match.home_team_id == HomeTeam.id)
            .join(AwayTeam, Match.away_team_id == AwayTeam.id)
            .filter(
                Match.status == "scheduled",
                Match.date >= today_str,
            )
            .order_by(ValueBet.edge.desc())
            .all()
        )

        # Group by (match_id, market_type, selection) — keep highest edge per group.
        # HTML-escape all string values that will be rendered in templates
        # (consistent with get_all_upcoming_fixtures escaping pattern).
        grouped: Dict[tuple, Dict] = {}
        for vb, match, league, home_name, away_name in rows:
            key = (vb.match_id, vb.market_type, vb.selection)
            if key not in grouped or vb.edge > grouped[key]["edge"]:
                grouped[key] = {
                    "match_id": vb.match_id,
                    "home_team": html_escape(home_name),
                    "away_team": html_escape(away_name),
                    "date": match.date,
                    "league": html_escape(league.short_name),
                    "market_type": html_escape(vb.market_type),
                    "selection": html_escape(vb.selection),
                    "bookmaker": html_escape(vb.bookmaker),
                    "bookmaker_odds": vb.bookmaker_odds,
                    "edge": vb.edge,
                    "confidence": vb.confidence,
                }

    # Sort by edge descending and take top N
    result = sorted(grouped.values(), key=lambda x: -x["edge"])
    return result[:max_picks]


# Market + selection display labels for the Top Picks banner
_SELECTION_LABELS = {
    ("1X2", "home"): "Home Win",
    ("1X2", "draw"): "Draw",
    ("1X2", "away"): "Away Win",
    ("OU25", "over"): "O2.5",
    ("OU25", "under"): "U2.5",
    ("OU15", "over"): "O1.5",
    ("OU15", "under"): "U1.5",
    ("OU35", "over"): "O3.5",
    ("OU35", "under"): "U3.5",
    ("BTTS", "yes"): "BTTS Y",
    ("BTTS", "no"): "BTTS N",
}


# ============================================================================
# Badge Rendering
# ============================================================================

def _render_market_badges(market_edges: Dict[Tuple[str, str], Optional[float]]) -> str:
    """Build HTML for the 9 color-coded market indicator badges.

    Each badge is a compact pill showing the selection label (H, D, A,
    O1.5, U1.5, O2.5, U2.5, BTTS Y, BTTS N) with a background colour
    indicating the model's edge.

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
    "All upcoming matches with predicted scores and color-coded model indicators"
    "</p>",
    unsafe_allow_html=True,
)

# ── E26-03: Top Picks Banner ─────────────────────────────────────────────
# Show the 3-5 highest-edge value bets as a compact banner at the top of
# the page.  This gives users an immediate view of the best opportunities.
with st.spinner("Loading top picks..."):
    top_picks = get_top_picks(max_picks=5)

if top_picks:
    st.markdown(
        f'<div style="font-family: Inter, sans-serif; font-size: 14px; '
        f'font-weight: 700; color: {COLOURS["green"]}; text-transform: uppercase; '
        f'letter-spacing: 0.5px; margin-bottom: 8px;">'
        f'Top Picks</div>',
        unsafe_allow_html=True,
    )

    # Render each top pick as a compact inline card
    picks_html_parts = []
    for pick in top_picks:
        sel_label = _SELECTION_LABELS.get(
            (pick["market_type"], pick["selection"]),
            f'{pick["market_type"]}/{pick["selection"]}',
        )
        edge_pct = pick["edge"] * 100
        # Green if edge is at least 2× the configured threshold (strong pick),
        # yellow otherwise (still a value bet, but less emphatic).
        # _edge_threshold is loaded from config at module level (e.g. 0.05 = 5%).
        _strong_edge_pct = _edge_threshold * 200  # 2× threshold as percentage
        edge_colour = COLOURS["green"] if edge_pct >= _strong_edge_pct else COLOURS["yellow"]
        conf_colour = (
            COLOURS["green"] if pick["confidence"] == "high"
            else COLOURS["yellow"] if pick["confidence"] == "medium"
            else COLOURS["grey"]
        )

        picks_html_parts.append(
            f'<div style="background-color: {COLOURS["surface"]}; '
            f'border: 1px solid {COLOURS["border"]}; border-radius: 8px; '
            f'padding: 10px 14px; flex: 1 1 220px; min-width: 220px;">'
            f'<div style="font-family: Inter, sans-serif; font-size: 13px; '
            f'font-weight: 600; color: {COLOURS["text"]}; margin-bottom: 4px;">'
            f'{pick["home_team"]} vs {pick["away_team"]}</div>'
            f'<div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">'
            f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
            f'color: {COLOURS["text_secondary"]};">{sel_label}</span>'
            f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
            f'color: {COLOURS["text"]};">{pick["bookmaker_odds"]:.2f}</span>'
            f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
            f'font-weight: 700; color: {edge_colour};">+{edge_pct:.1f}%</span>'
            f'<span style="font-family: Inter, sans-serif; font-size: 10px; '
            f'color: {COLOURS["text_secondary"]};">{pick["bookmaker"]}</span>'
            f'<span style="display: inline-block; width: 8px; height: 8px; '
            f'border-radius: 50%; background-color: {conf_colour};"></span>'
            f'</div>'
            f'</div>'
        )

    st.markdown(
        f'<div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px;">'
        f'{"".join(picks_html_parts)}'
        f'</div>',
        unsafe_allow_html=True,
    )
else:
    # Empty state: no value bets found across upcoming fixtures
    st.markdown(
        f'<div style="background-color: {COLOURS["surface"]}; '
        f'border: 1px solid {COLOURS["border"]}; border-radius: 8px; '
        f'padding: 14px 18px; margin-bottom: 16px; text-align: center;">'
        f'<span style="font-family: Inter, sans-serif; font-size: 13px; '
        f'color: {COLOURS["text_secondary"]};">'
        f'No value bets found across upcoming fixtures. '
        f'The pipeline will identify opportunities when odds are available.</span>'
        f'</div>',
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
    # ----------------------------------------------------------------
    # Pipeline Health Summary (E24-04)
    # Shows data coverage at a glance so the user knows if the pipeline
    # has run recently and which fixtures have full model + odds data.
    # ----------------------------------------------------------------
    total = len(fixtures)
    with_prediction = sum(1 for f in fixtures if f["has_prediction"])
    with_odds = sum(1 for f in fixtures if f["has_odds"])
    with_value = sum(1 for f in fixtures if f["has_value_bets"])
    # "Full data" means both prediction AND odds exist — edge computation possible
    full_data = sum(
        1 for f in fixtures if f["has_prediction"] and f["has_odds"]
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Upcoming Matches", total)
    with col2:
        st.metric("With Predictions", with_prediction)
    with col3:
        st.metric("With Odds", with_odds)
    with col4:
        st.metric("With Value Bets", with_value)

    # Pipeline health bar — shows how many fixtures have full model + odds data.
    # Green when most fixtures are covered, yellow when partial, red when sparse.
    if total > 0:
        coverage_pct = (full_data / total) * 100
        # Choose bar colour based on coverage percentage
        if coverage_pct >= 70:
            bar_colour = COLOURS["green"]
        elif coverage_pct >= 30:
            bar_colour = COLOURS["yellow"]
        else:
            bar_colour = COLOURS["red"]

        st.markdown(
            f'<div style="font-family: Inter, sans-serif; font-size: 12px; '
            f'color: {COLOURS["text_secondary"]}; margin: 8px 0 4px;">'
            f'Pipeline Coverage: <strong style="color: {COLOURS["text"]};">'
            f'{full_data}/{total}</strong> fixtures have full prediction + odds data'
            f'</div>'
            f'<div style="background-color: {COLOURS["border"]}; border-radius: 4px; '
            f'height: 6px; overflow: hidden; margin-bottom: 8px;">'
            f'<div style="width: {coverage_pct:.0f}%; height: 100%; '
            f'background-color: {bar_colour}; border-radius: 4px; '
            f'transition: width 0.3s ease;"></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Tip when coverage is low — explain why some fixtures lack odds
        if coverage_pct < 70:
            st.markdown(
                f'<div style="font-family: Inter, sans-serif; font-size: 11px; '
                f'color: {COLOURS["text_secondary"]}; margin-bottom: 12px; '
                f'padding: 6px 10px; border-left: 2px solid {COLOURS["blue"]}; '
                f'background-color: rgba(88, 166, 255, 0.05);">'
                f'💡 Bookmakers typically price matches 1–2 weeks ahead. '
                f'Fixtures further out show grey badges until odds become available. '
                f'The pipeline refreshes odds automatically each morning.'
                f'</div>',
                unsafe_allow_html=True,
            )

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
            # Green left border for matches with value bets,
            # blue for full data (prediction + odds) but no value bets yet
            if fix["has_value_bets"]:
                border_style = f"border-left: 3px solid {COLOURS['green']};"
            elif fix["has_prediction"] and fix["has_odds"]:
                border_style = f"border-left: 3px solid {COLOURS['blue']};"
            else:
                border_style = ""

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

            # --------------------------------------------------------
            # Diagnostic status badges (E24-04)
            # Show small status pills next to the league badge so the
            # user can immediately see which fixtures have full data,
            # which are missing odds, and which lack predictions.
            # --------------------------------------------------------
            diag_badges = []
            if not fix["has_prediction"]:
                # Red — model hasn't generated predictions for this match
                diag_badges.append(
                    f'<span title="No prediction available — the model has not '
                    f'generated probabilities for this match yet" style="'
                    f"display: inline-block; padding: 1px 5px; margin-left: 4px; "
                    f"border-radius: 3px; font-family: 'JetBrains Mono', monospace; "
                    f"font-size: 9px; font-weight: 600; color: {COLOURS['red']}; "
                    f'border: 1px solid {COLOURS["red"]}; cursor: help;">'
                    f"No pred</span>"
                )
            if not fix["has_odds"]:
                # Yellow — odds not yet loaded (bookmakers may not have priced it)
                diag_badges.append(
                    f'<span title="No odds loaded — bookmakers may not have '
                    f'priced this fixture yet (typically available 1–2 weeks out)" '
                    f'style="'
                    f"display: inline-block; padding: 1px 5px; margin-left: 4px; "
                    f"border-radius: 3px; font-family: 'JetBrains Mono', monospace; "
                    f"font-size: 9px; font-weight: 600; color: {COLOURS['yellow']}; "
                    f'border: 1px solid {COLOURS["yellow"]}; cursor: help;">'
                    f"No odds</span>"
                )
            if fix["has_prediction"] and fix["has_odds"]:
                # Green outline — full data, edge computation is live
                vb_label = (
                    f'{fix["value_bet_count"]} VB'
                    if fix["has_value_bets"]
                    else "Full data"
                )
                vb_title = (
                    f'{fix["value_bet_count"]} value bet(s) identified'
                    if fix["has_value_bets"]
                    else "Prediction + odds loaded — edge computation is live"
                )
                diag_badges.append(
                    f'<span title="{vb_title}" style="'
                    f"display: inline-block; padding: 1px 5px; margin-left: 4px; "
                    f"border-radius: 3px; font-family: 'JetBrains Mono', monospace; "
                    f"font-size: 9px; font-weight: 600; color: {COLOURS['green']}; "
                    f'border: 1px solid {COLOURS["green"]}; cursor: help;">'
                    f"{vb_label}</span>"
                )
            diag_html = "".join(diag_badges)

            # Market indicator badges — the 7 color-coded pills (E24-03)
            market_html = _render_market_badges(fix["market_edges"])

            # E26-03: Predicted score inline — "Model: 1.4 – 0.8"
            # Only shown when the prediction record has expected goals.
            pred_html = ""
            pred_h = fix.get("predicted_home_goals")
            pred_a = fix.get("predicted_away_goals")
            if pred_h is not None and pred_a is not None:
                pred_html = (
                    f'<span style="font-family: JetBrains Mono, monospace; '
                    f'font-size: 11px; color: {COLOURS["text_secondary"]}; '
                    f'margin-left: 12px;" '
                    f'title="Model predicted expected goals (xG-based)">'
                    f'Model: {pred_h:.1f} – {pred_a:.1f}</span>'
                )

            # Fixture card — three rows:
            # Row 1: Kickoff + Teams + Predicted Score + League badge + diagnostic badges
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
                f'{pred_html}'
                f'</div>'
                f'<div style="display: flex; align-items: center;">'
                f'{league_badge}{diag_html}'
                f'</div>'
                f'</div>'
                # Row 2: market badges
                f'<div style="display: flex; align-items: center; gap: 4px; '
                f'padding-left: 62px;">'
                f'{market_html}'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # "Deep Dive" button — navigates to Match Deep Dive with match_id.
            # E26-02: Use session_state to pass match_id across pages — query_params
            # set before st.switch_page() are lost in Streamlit 1.41.
            if st.button(
                "\U0001F50D Deep Dive",
                key=f"fixture_dive_{fix['match_id']}",
                type="secondary",
            ):
                st.session_state["deep_dive_match_id"] = fix["match_id"]
                st.switch_page("views/match_detail.py")

# ============================================================================
# Glossary — explains every term, badge, and indicator on this page (E27-03)
# ============================================================================
# The owner is learning (MP §12). This glossary defines every visible element
# so anyone can understand the fixtures overview without prior betting knowledge.

st.divider()
with st.expander("Glossary — What do these terms mean?", expanded=False):
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

    # --- Market Badges ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Market Badges</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">H / D / A</span>'
        '  <span class="gloss-def">Home Win / Draw / Away Win (1X2 match result market). '
        'The most common betting market — who wins the match.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">O1.5 / U1.5</span>'
        '  <span class="gloss-def">Over/Under 1.5 Goals. Over 1.5 means 2 or more goals total. '
        'Under 1.5 means 0 or 1 goals (rare, ~15-20% of EPL matches).</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">O2.5 / U2.5</span>'
        '  <span class="gloss-def">Over/Under 2.5 Goals. Over 2.5 means 3 or more goals total. '
        'The most popular goals line in betting (~50/50 split in the EPL).</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">BTTS Y / BTTS N</span>'
        '  <span class="gloss-def">Both Teams to Score — Yes or No. '
        'BTTS Yes means each team scores at least one goal.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Badge Colours ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Badge Colours</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #3FB950;">Green</span>'
        '  <span class="gloss-def">The model sees a strong edge — the bookmaker\'s odds are '
        'significantly more generous than the model thinks they should be.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #D29922;">Yellow</span>'
        '  <span class="gloss-def">Marginal edge — there\'s some value but the gap between '
        'model and bookmaker is small. Proceed with caution.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #F85149;">Red</span>'
        '  <span class="gloss-def">No edge — the bookmaker\'s price is equal to or below '
        'what the model thinks. Not a value bet.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #8B949E;">Grey</span>'
        '  <span class="gloss-def">No data — either the prediction hasn\'t been generated yet '
        'or odds haven\'t been loaded for this market.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Fixture Data ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Fixture Data</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Predicted Score</span>'
        '  <span class="gloss-def">The model\'s expected goals for each team '
        '(e.g. "Model: 1.4 – 0.8"). This is the Poisson model\'s lambda (\u03BB) — '
        'the average goals the model expects, not a specific scoreline prediction.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Edge (tooltip)</span>'
        '  <span class="gloss-def">Hover over any badge to see the exact edge percentage. '
        'E.g. "+8.2% edge" means the model thinks the outcome is 8.2 percentage points '
        'more likely than the bookmaker\'s odds imply.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Diagnostic Badges ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Diagnostic Badges</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">No pred</span>'
        '  <span class="gloss-def">The model hasn\'t generated a prediction for this match yet. '
        'Predictions run during the morning pipeline (6 AM).</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">No odds</span>'
        '  <span class="gloss-def">No bookmaker odds have been loaded. '
        'Odds are typically available 1-2 weeks before kickoff.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Full data</span>'
        '  <span class="gloss-def">Both prediction and odds exist — the model can compute edges '
        'and identify value bets for this match.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">X VB</span>'
        '  <span class="gloss-def">Number of value bets identified. A value bet is a selection '
        'where the model\'s probability exceeds the bookmaker\'s implied probability.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Top Picks ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Top Picks Banner</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Top Picks</span>'
        '  <span class="gloss-def">The 3\u20135 highest-edge value bets across all upcoming fixtures. '
        'Shows the best opportunities at a glance without scrolling through every match.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Best Bookmaker</span>'
        '  <span class="gloss-def">The bookmaker offering the best odds (highest edge) for each '
        'pick. Different bookmakers price the same outcome differently.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Pipeline Coverage</span>'
        '  <span class="gloss-def">How many upcoming fixtures have both model predictions and '
        'bookmaker odds loaded. Higher coverage means more fixtures can be analysed for value.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
