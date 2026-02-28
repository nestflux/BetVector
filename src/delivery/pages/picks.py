"""
BetVector — Today's Picks Page (E9-02)
=======================================
Displays value bets for today's matches, sorted by edge descending.

This is the primary daily interface — the answer to "what should I bet
on today?"  Each value bet is displayed as a card showing:

- Match info (teams, league, kickoff time)
- Market and selection (e.g. "1X2 → Home Win")
- Model probability vs bookmaker implied probability
- Edge (model_prob - implied_prob) and confidence badge
- Bookmaker odds (FanDuel highlighted if available)
- Suggested stake from the bankroll manager

Users can mark bets as placed, entering the actual odds and stake they
got from the bookmaker.  This creates a ``user_placed`` entry in bet_log
for tracking real-money performance.

Master Plan refs: MP §3 Flow 1 (Morning Picks Review), MP §8 Design System
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import streamlit as st

from src.database.db import get_session
from src.database.models import (
    BetLog,
    League,
    Match,
    Team,
    User,
    ValueBet,
)


# ============================================================================
# Human-readable display labels
# ============================================================================

MARKET_DISPLAY = {
    "1X2": "Match Result",
    "OU25": "Over/Under 2.5 Goals",
    "OU15": "Over/Under 1.5 Goals",
    "OU35": "Over/Under 3.5 Goals",
    "BTTS": "Both Teams To Score",
}

SELECTION_DISPLAY = {
    ("1X2", "home"): "Home Win",
    ("1X2", "draw"): "Draw",
    ("1X2", "away"): "Away Win",
    ("OU25", "over"): "Over 2.5 Goals",
    ("OU25", "under"): "Under 2.5 Goals",
    ("OU15", "over"): "Over 1.5 Goals",
    ("OU15", "under"): "Under 1.5 Goals",
    ("OU35", "over"): "Over 3.5 Goals",
    ("OU35", "under"): "Under 3.5 Goals",
    ("BTTS", "yes"): "BTTS Yes",
    ("BTTS", "no"): "BTTS No",
}

# Confidence badge colours (MP §8)
CONFIDENCE_COLOURS = {
    "high": "#3FB950",    # Green
    "medium": "#D29922",  # Yellow
    "low": "#484F58",     # Muted
}


# ============================================================================
# Data Loading
# ============================================================================

def get_todays_value_bets(edge_threshold: float = 0.0) -> List[Dict]:
    """Fetch today's value bets with match and team details.

    Queries the value_bets table joined with matches, teams, and leagues
    to build complete card data.  Falls back to showing all recent value
    bets if none exist for today (useful during development and backtesting).

    Parameters
    ----------
    edge_threshold : float
        Minimum edge to display (0.0 shows all).

    Returns
    -------
    list[dict]
        Value bet data enriched with team names, league, and kickoff.
    """
    with get_session() as session:
        today = date.today().isoformat()

        # Try today's matches first
        query = (
            session.query(ValueBet, Match, League)
            .join(Match, ValueBet.match_id == Match.id)
            .join(League, Match.league_id == League.id)
            .filter(Match.date == today)
        )

        if edge_threshold > 0:
            query = query.filter(ValueBet.edge >= edge_threshold)

        rows = query.order_by(ValueBet.edge.desc()).all()

        # If no today's picks, show recent value bets (last 7 days)
        # This ensures the page has content during development/backtesting
        if not rows:
            week_ago = (date.today() - timedelta(days=7)).isoformat()
            query = (
                session.query(ValueBet, Match, League)
                .join(Match, ValueBet.match_id == Match.id)
                .join(League, Match.league_id == League.id)
                .filter(Match.date >= week_ago)
            )
            if edge_threshold > 0:
                query = query.filter(ValueBet.edge >= edge_threshold)

            rows = query.order_by(ValueBet.edge.desc()).limit(50).all()

        # If still no picks (e.g., during development with only historical data),
        # show the most recent value bets regardless of date
        if not rows:
            query = (
                session.query(ValueBet, Match, League)
                .join(Match, ValueBet.match_id == Match.id)
                .join(League, Match.league_id == League.id)
            )
            if edge_threshold > 0:
                query = query.filter(ValueBet.edge >= edge_threshold)

            rows = query.order_by(ValueBet.edge.desc()).limit(50).all()

        # Enrich with team names
        results = []
        for vb, match, league in rows:
            home_team = session.query(Team).filter_by(id=match.home_team_id).first()
            away_team = session.query(Team).filter_by(id=match.away_team_id).first()

            results.append({
                "id": vb.id,
                "match_id": vb.match_id,
                "home_team": home_team.name if home_team else "Unknown",
                "away_team": away_team.name if away_team else "Unknown",
                "league": league.short_name,
                "date": match.date,
                "kickoff": match.kickoff_time or "TBD",
                "market_type": vb.market_type,
                "selection": vb.selection,
                "model_prob": vb.model_prob,
                "bookmaker": vb.bookmaker,
                "bookmaker_odds": vb.bookmaker_odds,
                "implied_prob": vb.implied_prob,
                "edge": vb.edge,
                "expected_value": vb.expected_value,
                "confidence": vb.confidence,
                "explanation": vb.explanation,
                "detected_at": vb.detected_at,
            })

    return results


def get_suggested_stake(model_prob: float, odds: float) -> float:
    """Calculate a suggested stake for display purposes.

    Uses the default user's bankroll settings. Falls back to a simple
    2% of £1000 if no user is configured.
    """
    try:
        from src.betting.bankroll import BankrollManager
        manager = BankrollManager()
        with get_session() as session:
            user = session.query(User).filter_by(role="owner").first()
            if user:
                result = manager.calculate_stake(user.id, model_prob, odds)
                return result.stake
    except Exception:
        pass

    # Fallback: 2% of £1000
    return 20.00


def get_default_user_id() -> Optional[int]:
    """Get the owner user ID for bet logging."""
    with get_session() as session:
        user = session.query(User).filter_by(role="owner").first()
        return user.id if user else None


# ============================================================================
# Card Rendering
# ============================================================================

def render_confidence_badge(confidence: str) -> str:
    """Return an HTML badge for the confidence level."""
    colour = CONFIDENCE_COLOURS.get(confidence, "#484F58")
    label = confidence.upper()
    return (
        f'<span class="bv-badge" style="background-color: {colour};">'
        f'{label}</span>'
    )


def render_value_bet_card(vb: Dict, idx: int) -> None:
    """Render a single value bet as a styled card.

    Shows match info, market details, edge, confidence badge, and
    a "Mark as Placed" button that expands into a form.
    """
    market_label = MARKET_DISPLAY.get(vb["market_type"], vb["market_type"])
    selection_label = SELECTION_DISPLAY.get(
        (vb["market_type"], vb["selection"]),
        f"{vb['market_type']}/{vb['selection']}",
    )
    confidence_badge = render_confidence_badge(vb["confidence"])
    suggested_stake = get_suggested_stake(vb["model_prob"], vb["bookmaker_odds"])

    # Highlight FanDuel bookmaker if available
    bookmaker_display = vb["bookmaker"]
    is_fanduel = "fanduel" in vb["bookmaker"].lower()
    if is_fanduel:
        bookmaker_display = f'<span style="color: #58A6FF; font-weight: 600;">{vb["bookmaker"]}</span>'

    # Edge colour
    edge_pct = vb["edge"] * 100
    edge_colour = "#3FB950" if edge_pct >= 10 else "#D29922" if edge_pct >= 5 else "#E6EDF3"

    # Card HTML
    st.markdown(f"""
    <div class="bv-card">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
            <div>
                <span style="font-family: 'Inter', sans-serif; font-size: 16px; font-weight: 600; color: #E6EDF3;">
                    {vb["home_team"]} vs {vb["away_team"]}
                </span>
                <br>
                <span style="font-family: 'Inter', sans-serif; font-size: 12px; color: #8B949E;">
                    {vb["league"]} &middot; {vb["date"]} &middot; {vb["kickoff"]}
                </span>
            </div>
            <div>{confidence_badge}</div>
        </div>
        <div style="display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 8px;">
            <div>
                <span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Market</span><br>
                <span style="font-family: 'Inter', sans-serif; font-size: 14px; color: #E6EDF3;">{selection_label}</span>
            </div>
            <div>
                <span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Model Prob</span><br>
                <span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #E6EDF3;">{vb["model_prob"]:.1%}</span>
            </div>
            <div>
                <span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Odds ({bookmaker_display})</span><br>
                <span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #E6EDF3;">{vb["bookmaker_odds"]:.2f}</span>
            </div>
            <div>
                <span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Edge</span><br>
                <span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700; color: {edge_colour};">+{edge_pct:.1f}%</span>
            </div>
            <div>
                <span style="font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 0.5px;">Suggested Stake</span><br>
                <span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #E6EDF3;">&pound;{suggested_stake:.2f}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # "Mark as Placed" expander
    with st.expander(f"Mark as Placed", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            actual_odds = st.number_input(
                "Actual odds",
                min_value=1.01,
                value=vb["bookmaker_odds"],
                step=0.01,
                format="%.2f",
                key=f"odds_{idx}",
            )
        with col2:
            actual_stake = st.number_input(
                "Actual stake (£)",
                min_value=0.01,
                value=suggested_stake,
                step=1.0,
                format="%.2f",
                key=f"stake_{idx}",
            )

        if st.button("Confirm Bet Placed", key=f"confirm_{idx}", type="primary"):
            user_id = get_default_user_id()
            if user_id is None:
                st.error("No user found. Run `python run_pipeline.py setup` first.")
            else:
                try:
                    from src.betting.tracker import log_user_bet
                    bet_id = log_user_bet(
                        value_bet_id=vb["id"],
                        user_id=user_id,
                        actual_odds=actual_odds,
                        actual_stake=actual_stake,
                    )
                    if bet_id:
                        st.success(
                            f"Bet logged (ID: {bet_id}). "
                            f"{vb['home_team']} vs {vb['away_team']} — "
                            f"{selection_label} @ {actual_odds:.2f}, "
                            f"£{actual_stake:.2f} staked."
                        )
                    else:
                        st.warning("Bet may already be logged (duplicate).")
                except Exception as e:
                    st.error(f"Failed to log bet: {e}")


# ============================================================================
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">Today\'s Picks</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Value bets for today\'s matches, sorted by edge</p>',
    unsafe_allow_html=True,
)
st.divider()

# Edge threshold slider — filters picks in real-time
# Default to 5% (standard edge threshold from config)
edge_threshold = st.slider(
    "Minimum edge threshold",
    min_value=0.0,
    max_value=20.0,
    value=5.0,
    step=0.5,
    format="%.1f%%",
    help="Filter picks by minimum edge. Higher = fewer but stronger picks.",
)
edge_threshold_decimal = edge_threshold / 100.0

# Load value bets
with st.spinner("Loading value bets..."):
    value_bets = get_todays_value_bets(edge_threshold=edge_threshold_decimal)

# Summary metrics
if value_bets:
    today_str = date.today().isoformat()
    is_today = any(vb["date"] == today_str for vb in value_bets)

    if not is_today:
        st.info(
            "No picks for today. Showing recent value bets for reference."
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Value Bets", len(value_bets))
    with col2:
        avg_edge = sum(vb["edge"] for vb in value_bets) / len(value_bets)
        st.metric("Avg Edge", f"{avg_edge:.1%}")
    with col3:
        high_conf = sum(1 for vb in value_bets if vb["confidence"] == "high")
        st.metric("High Confidence", high_conf)

    st.divider()

    # Render each value bet as a card
    for idx, vb in enumerate(value_bets):
        render_value_bet_card(vb, idx)

else:
    # Empty state (MP §8)
    st.markdown(
        '<div class="bv-empty-state">'
        "No value bets right now. Your bankroll thanks you for your patience."
        "</div>",
        unsafe_allow_html=True,
    )
