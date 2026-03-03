"""
BetVector — Performance Tracker Page (E9-03)
=============================================
Shows betting results, P&L charts, ROI, and win rates.

This is the evening review interface — the answer to "how am I doing?"
Displays:

- 4 metric cards: Total P&L, ROI %, Total Bets, Win Rate
- Cumulative P&L line chart (Plotly, dark theme)
- Monthly P&L bar chart (green for profit, red for loss)
- Recent bets table with result indicators
- Filters: date range, league, market type, bet type

P&L formula:
  Win:  stake × (odds - 1)
  Loss: -stake
  ROI:  total_pnl / total_staked × 100

Master Plan refs: MP §3 Flow 2 (Evening Results Review), MP §8 Design System
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import func

from src.database.db import get_session
from src.database.models import BetLog


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

def load_bet_data(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    league: Optional[str] = None,
    market_type: Optional[str] = None,
    bet_type: Optional[str] = None,
) -> pd.DataFrame:
    """Load resolved bet data from bet_log with optional filters.

    Returns a DataFrame with all columns needed for metrics, charts, and
    the bets table.  Only resolved bets (won/lost) are included — pending
    bets don't contribute to P&L.

    Parameters
    ----------
    date_from : str, optional
        ISO date string for start of range.
    date_to : str, optional
        ISO date string for end of range.
    league : str, optional
        Filter to a specific league.
    market_type : str, optional
        Filter to a specific market type (e.g., "1X2", "OU25").
    bet_type : str, optional
        Filter by bet type ("system_pick" or "user_placed").

    Returns
    -------
    pd.DataFrame
        Columns: date, league, home_team, away_team, market_type, selection,
        odds, stake, status, pnl, bet_type, edge
    """
    with get_session() as session:
        query = session.query(BetLog).filter(
            BetLog.status.in_(["won", "lost"])
        )

        if date_from:
            query = query.filter(BetLog.date >= date_from)
        if date_to:
            query = query.filter(BetLog.date <= date_to)
        if league:
            query = query.filter(BetLog.league == league)
        if market_type:
            query = query.filter(BetLog.market_type == market_type)
        if bet_type:
            query = query.filter(BetLog.bet_type == bet_type)

        rows = query.order_by(BetLog.date.asc()).all()

        if not rows:
            return pd.DataFrame()

        data = []
        for b in rows:
            # Use actual placement odds for user_placed, detection odds for system picks
            odds = b.odds_at_placement if b.odds_at_placement else b.odds_at_detection
            data.append({
                "date": b.date,
                "league": b.league,
                "home_team": b.home_team,
                "away_team": b.away_team,
                "market_type": b.market_type,
                "selection": b.selection,
                "odds": odds,
                "stake": b.stake,
                "status": b.status,
                "pnl": b.pnl or 0.0,
                "bet_type": b.bet_type,
                "edge": b.edge,
            })

    return pd.DataFrame(data)


def get_filter_options() -> Dict[str, List[str]]:
    """Get unique values for filter dropdowns from the database."""
    with get_session() as session:
        leagues = [
            r[0] for r in session.query(BetLog.league).distinct().all()
        ]
        markets = [
            r[0] for r in session.query(BetLog.market_type).distinct().all()
        ]

    return {"leagues": sorted(leagues), "markets": sorted(markets)}


# ============================================================================
# Metric Calculations
# ============================================================================

def calculate_metrics(df: pd.DataFrame) -> Dict:
    """Calculate summary metrics from resolved bet data.

    Returns
    -------
    dict
        total_pnl, roi_pct, total_bets, win_rate, total_staked, wins, losses
    """
    if df.empty:
        return {
            "total_pnl": 0.0,
            "roi_pct": 0.0,
            "total_bets": 0,
            "win_rate": 0.0,
            "total_staked": 0.0,
            "wins": 0,
            "losses": 0,
        }

    total_pnl = df["pnl"].sum()
    total_staked = df["stake"].sum()
    wins = (df["status"] == "won").sum()
    losses = (df["status"] == "lost").sum()
    total_bets = len(df)
    roi_pct = (total_pnl / total_staked * 100) if total_staked > 0 else 0.0
    win_rate = (wins / total_bets * 100) if total_bets > 0 else 0.0

    return {
        "total_pnl": total_pnl,
        "roi_pct": roi_pct,
        "total_bets": total_bets,
        "win_rate": win_rate,
        "total_staked": total_staked,
        "wins": wins,
        "losses": losses,
    }


# ============================================================================
# Charts
# ============================================================================

def create_cumulative_pnl_chart(df: pd.DataFrame) -> go.Figure:
    """Create a Plotly line chart of cumulative P&L over time.

    Groups P&L by date, calculates running total, and renders as a
    green line chart with dark theme styling per MP §8.
    """
    # Group by date and sum P&L per day
    daily = df.groupby("date")["pnl"].sum().reset_index()
    daily = daily.sort_values("date")
    daily["cumulative_pnl"] = daily["pnl"].cumsum()

    fig = go.Figure()

    # Fill area under the line — green above zero, red below
    fig.add_trace(go.Scatter(
        x=daily["date"],
        y=daily["cumulative_pnl"],
        mode="lines",
        name="Cumulative P&L",
        line=dict(color=COLOURS["green"], width=2),
        fill="tozeroy",
        fillcolor="rgba(63, 185, 80, 0.1)",
        hovertemplate="Date: %{x}<br>P&L: $%{y:.2f}<extra></extra>",
    ))

    # Zero line for reference
    fig.add_hline(
        y=0, line_dash="dash",
        line_color=COLOURS["border"], line_width=1,
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
            gridcolor=COLOURS["border"],
            showgrid=True,
            gridwidth=1,
            title="",
        ),
        yaxis=dict(
            gridcolor=COLOURS["border"],
            showgrid=True,
            gridwidth=1,
            title="P&L ($)",
            tickprefix="$",
        ),
        margin=dict(l=60, r=20, t=10, b=40),
        height=350,
        showlegend=False,
        hovermode="x",
    )

    return fig


def create_monthly_pnl_chart(df: pd.DataFrame) -> go.Figure:
    """Create a Plotly bar chart of monthly P&L.

    Green bars for profitable months, red bars for losing months.
    Dark theme styling per MP §8.
    """
    # Extract month from date string (YYYY-MM)
    df_copy = df.copy()
    df_copy["month"] = df_copy["date"].str[:7]

    monthly = df_copy.groupby("month")["pnl"].sum().reset_index()
    monthly = monthly.sort_values("month")

    # Colour each bar based on positive/negative P&L
    colours = [
        COLOURS["green"] if pnl >= 0 else COLOURS["red"]
        for pnl in monthly["pnl"]
    ]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=monthly["month"],
        y=monthly["pnl"],
        marker_color=colours,
        hovertemplate="Month: %{x}<br>P&L: $%{y:.2f}<extra></extra>",
    ))

    # Zero line
    fig.add_hline(
        y=0, line_dash="dash",
        line_color=COLOURS["border"], line_width=1,
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
            gridcolor=COLOURS["border"],
            showgrid=False,
            title="",
        ),
        yaxis=dict(
            gridcolor=COLOURS["border"],
            showgrid=True,
            gridwidth=1,
            title="P&L ($)",
            tickprefix="$",
        ),
        margin=dict(l=60, r=20, t=10, b=40),
        height=300,
        showlegend=False,
    )

    return fig


# ============================================================================
# Bets Table
# ============================================================================

MARKET_LABELS = {
    "1X2": "Match Result",
    "OU25": "O/U 2.5",
    "OU15": "O/U 1.5",
    "OU35": "O/U 3.5",
    "BTTS": "BTTS",
}


def create_bets_table(df: pd.DataFrame, limit: int = 50) -> pd.DataFrame:
    """Create a formatted DataFrame for the recent bets table.

    Most recent bets first, limited to `limit` rows.  Adds human-readable
    result indicators and formatted P&L values.
    """
    recent = df.sort_values("date", ascending=False).head(limit).copy()

    # Format columns for display
    recent["Match"] = recent["home_team"] + " vs " + recent["away_team"]
    recent["Market"] = recent["market_type"].map(MARKET_LABELS).fillna(recent["market_type"])
    recent["Odds"] = recent["odds"].apply(lambda x: f"{x:.2f}")
    recent["Stake"] = recent["stake"].apply(lambda x: f"${x:.2f}")
    recent["Result"] = recent["status"].map({"won": "✅ Won", "lost": "❌ Lost"})
    recent["P&L"] = recent["pnl"].apply(
        lambda x: f"+${x:.2f}" if x >= 0 else f"-${abs(x):.2f}"
    )
    recent["Date"] = recent["date"]

    return recent[["Date", "Match", "Market", "Odds", "Stake", "Result", "P&L"]]


# ============================================================================
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">Performance Tracker</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Betting results, P&L, and ROI analysis</p>',
    unsafe_allow_html=True,
)
st.divider()

# --- Filters ---
filter_options = get_filter_options()

filter_cols = st.columns(4)
with filter_cols[0]:
    date_range = st.date_input(
        "Date range",
        value=(date(2024, 8, 1), date.today()),
        key="perf_date_range",
        help="Filter bets by match date",
    )
with filter_cols[1]:
    league_filter = st.selectbox(
        "League",
        options=["All"] + filter_options["leagues"],
        key="perf_league",
    )
with filter_cols[2]:
    market_filter = st.selectbox(
        "Market",
        options=["All"] + filter_options["markets"],
        key="perf_market",
    )
with filter_cols[3]:
    bet_type_filter = st.selectbox(
        "Bet Type",
        options=["All", "system_pick", "user_placed"],
        key="perf_bet_type",
    )

# Parse filter values
date_from = date_range[0].isoformat() if isinstance(date_range, tuple) and len(date_range) >= 1 else None
date_to = date_range[1].isoformat() if isinstance(date_range, tuple) and len(date_range) >= 2 else None
league_val = league_filter if league_filter != "All" else None
market_val = market_filter if market_filter != "All" else None
bet_type_val = bet_type_filter if bet_type_filter != "All" else None

# --- Load Data ---
with st.spinner("Loading performance data..."):
    df = load_bet_data(
        date_from=date_from,
        date_to=date_to,
        league=league_val,
        market_type=market_val,
        bet_type=bet_type_val,
    )

if df.empty:
    # Empty state (MP §8)
    st.markdown(
        '<div class="bv-empty-state">'
        "No betting data yet. Run the morning pipeline to generate picks, "
        "then check back after matches are resolved."
        "</div>",
        unsafe_allow_html=True,
    )
else:
    metrics = calculate_metrics(df)

    # --- Metric Cards (4 columns) ---
    # P&L colour: green when positive, red when negative
    pnl_colour = COLOURS["green"] if metrics["total_pnl"] >= 0 else COLOURS["red"]
    pnl_sign = "+" if metrics["total_pnl"] >= 0 else ""

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        # Custom HTML for coloured P&L metric
        st.markdown(
            f'<div>'
            f'<span style="font-family: \'Inter\', sans-serif; font-size: 12px; color: #8B949E; '
            f'text-transform: uppercase; letter-spacing: 0.5px;">Total P&L</span><br>'
            f'<span style="font-family: \'JetBrains Mono\', monospace; font-size: 28px; font-weight: 700; '
            f'color: {pnl_colour};">{pnl_sign}${abs(metrics["total_pnl"]):.2f}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.metric("ROI", f"{metrics['roi_pct']:+.1f}%")
    with col3:
        st.metric("Total Bets", f"{metrics['total_bets']:,}")
    with col4:
        st.metric(
            "Win Rate",
            f"{metrics['win_rate']:.1f}%",
            delta=f"{metrics['wins']}W / {metrics['losses']}L",
        )

    st.divider()

    # --- Cumulative P&L Chart ---
    st.markdown(
        '<div class="bv-section-header">Cumulative P&L</div>',
        unsafe_allow_html=True,
    )
    fig_cumulative = create_cumulative_pnl_chart(df)
    st.plotly_chart(fig_cumulative, use_container_width=True, config={"displayModeBar": False})

    # --- Monthly P&L Chart ---
    st.markdown(
        '<div class="bv-section-header">Monthly P&L</div>',
        unsafe_allow_html=True,
    )
    fig_monthly = create_monthly_pnl_chart(df)
    st.plotly_chart(fig_monthly, use_container_width=True, config={"displayModeBar": False})

    st.divider()

    # --- Recent Bets Table ---
    st.markdown(
        '<div class="bv-section-header">Recent Bets</div>',
        unsafe_allow_html=True,
    )
    bets_table = create_bets_table(df)
    st.dataframe(
        bets_table,
        use_container_width=True,
        hide_index=True,
        height=400,
    )

# ============================================================================
# Glossary — explains every metric, chart, and term on this page (E27-03)
# ============================================================================
# The owner is learning (MP §12). This glossary defines every visible element
# so anyone can understand their betting performance at a glance.

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

    # --- Key Metrics ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Key Metrics</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Total P&amp;L</span>'
        '  <span class="gloss-def">Profit and Loss — total dollars gained or lost across '
        'all resolved bets. Positive (green) = net profit. Negative (red) = net loss.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">ROI %</span>'
        '  <span class="gloss-def">Return on Investment — profit divided by total amount staked, '
        'as a percentage. ROI of +5% means you earned $5 for every $100 wagered. '
        'Professional bettors target +2% to +5% long-term.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Win Rate</span>'
        '  <span class="gloss-def">Percentage of bets that won. Note: win rate alone '
        'doesn\'t indicate profitability — a 40% win rate at high odds can be profitable, '
        'while 60% at low odds might lose money.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Total Staked</span>'
        '  <span class="gloss-def">The sum of all stake amounts placed. '
        'Used as the denominator when calculating ROI.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Charts ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Charts</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Cumulative P&amp;L</span>'
        '  <span class="gloss-def">A running total of profit/loss over time. '
        'An upward trend = growing profits. A flat line = breakeven. '
        'Dips are normal — look at the overall trajectory, not individual swings.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Monthly P&amp;L</span>'
        '  <span class="gloss-def">Bar chart showing profit or loss per month. '
        'Green bars = profitable months, red bars = losing months. '
        'Even a profitable model will have red months.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Markets ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Market Types</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Match Result</span>'
        '  <span class="gloss-def">1X2 market: Home Win, Draw, or Away Win.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">O/U 1.5 / 2.5</span>'
        '  <span class="gloss-def">Over/Under goals markets. O/U 1.5 = will there be 2+ goals? '
        'O/U 2.5 = will there be 3+ goals?</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">BTTS</span>'
        '  <span class="gloss-def">Both Teams to Score — will each team net at least one goal?</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Bet Types & Outcomes ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Bet Types &amp; Outcomes</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">System Pick</span>'
        '  <span class="gloss-def">A bet automatically logged by the model when it finds value. '
        'Tracks model performance independently of whether you actually placed the bet.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">User Placed</span>'
        '  <span class="gloss-def">A bet you manually confirmed as placed on your sportsbook. '
        'Tracks your actual betting performance and bankroll.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Won / Lost</span>'
        '  <span class="gloss-def">Resolved outcomes. Won = P&amp;L is stake \u00D7 (odds \u2212 1). '
        'Lost = P&amp;L is \u2212stake.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Pending</span>'
        '  <span class="gloss-def">Match hasn\'t finished yet — result is not known.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
