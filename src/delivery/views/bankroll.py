"""
BetVector — Bankroll Manager Page (E10-02)
============================================
Current bankroll, staking method display, bet history with filters,
safety alert status, bankroll chart, and monthly P&L breakdown.

Sections:
1. Key metrics — current bankroll, starting, peak, drawdown %
2. Staking method — current method with brief explanation
3. Safety status — traffic light indicators for each limit
4. Bankroll chart — Plotly line chart with peak annotated
5. Bet history — filterable, sortable table
6. Monthly P&L breakdown — table with bets, wins, losses, P&L, ROI

Master Plan refs: MP §3 Flow 4 (Bankroll Manager), MP §8 Design System
"""

from datetime import date
from typing import Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.database.db import get_session
from src.database.models import BetLog, User


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

# Human-readable staking method labels and explanations
STAKING_LABELS = {
    "flat": ("Flat Staking", "Fixed percentage of current bankroll on every bet."),
    "percentage": ("Percentage Staking", "Recalculated percentage of bankroll after each bet."),
    "kelly": ("Kelly Criterion", "Fractional Kelly — stake proportional to edge and odds."),
}

MARKET_LABELS = {
    "1X2": "Match Result",
    "OU25": "O/U 2.5",
    "OU15": "O/U 1.5",
    "OU35": "O/U 3.5",
    "BTTS": "BTTS",
}


# ============================================================================
# Data Loading
# ============================================================================

def load_user_data(user_id: int = 1) -> Optional[Dict]:
    """Load user's bankroll settings and current state.

    Returns a dict with bankroll amounts, staking config, and
    safety limit thresholds.  Returns None if user not found.
    """
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return None

        return {
            "id": user.id,
            "name": user.name,
            "current_bankroll": user.current_bankroll or 0.0,
            "starting_bankroll": user.starting_bankroll or 0.0,
            "staking_method": user.staking_method or "flat",
            "stake_percentage": user.stake_percentage or 0.02,
            "kelly_fraction": user.kelly_fraction or 0.25,
            "edge_threshold": user.edge_threshold or 0.05,
        }


def get_peak_bankroll(user_id: int = 1) -> float:
    """Get the all-time peak bankroll from bet history.

    The peak is the maximum of the starting bankroll and all
    historical bankroll_after values in the bet log.
    """
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        starting = user.starting_bankroll if user else 500.0

        from sqlalchemy import func
        max_after = (
            session.query(func.max(BetLog.bankroll_after))
            .filter(
                BetLog.user_id == user_id,
                BetLog.bankroll_after.isnot(None),
                BetLog.status.in_(["won", "lost"]),
            )
            .scalar()
        )

    return max(starting, max_after or 0.0)


def get_daily_losses(user_id: int = 1) -> float:
    """Get total losses for today (used for daily loss limit check)."""
    today = date.today().isoformat()
    with get_session() as session:
        from sqlalchemy import func
        total = (
            session.query(func.sum(BetLog.pnl))
            .filter(
                BetLog.user_id == user_id,
                BetLog.date == today,
                BetLog.status.in_(["lost", "half_lost"]),
            )
            .scalar()
        )
    return abs(total or 0.0)


def check_safety_limits(user_data: Dict, peak: float, daily_losses: float) -> List[Dict]:
    """Check all safety limits and return traffic light status for each.

    Safety limits from config (MP §6):
    - Daily loss limit: 10% of starting bankroll
    - Drawdown alert: 25% below all-time peak
    - Minimum bankroll: 50% of starting bankroll
    - Max bet cap: 5% of current bankroll (informational)
    """
    current = user_data["current_bankroll"]
    starting = user_data["starting_bankroll"]

    # Daily loss limit: 10% of starting
    daily_limit = starting * 0.10
    daily_pct = (daily_losses / daily_limit * 100) if daily_limit > 0 else 0
    if daily_losses >= daily_limit:
        daily_status = "red"
        daily_label = "TRIGGERED"
    elif daily_pct >= 70:
        daily_status = "yellow"
        daily_label = "APPROACHING"
    else:
        daily_status = "green"
        daily_label = "OK"

    # Drawdown alert: 25% below peak
    drawdown_pct = ((peak - current) / peak * 100) if peak > 0 else 0
    if drawdown_pct >= 25:
        dd_status = "red"
        dd_label = "TRIGGERED"
    elif drawdown_pct >= 15:
        dd_status = "yellow"
        dd_label = "APPROACHING"
    else:
        dd_status = "green"
        dd_label = "OK"

    # Minimum bankroll: 50% of starting
    min_threshold = starting * 0.50
    bankroll_pct = (current / starting * 100) if starting > 0 else 100
    if current <= min_threshold:
        min_status = "red"
        min_label = "TRIGGERED"
    elif bankroll_pct <= 65:
        min_status = "yellow"
        min_label = "APPROACHING"
    else:
        min_status = "green"
        min_label = "OK"

    return [
        {
            "name": "Daily Loss Limit",
            "detail": f"${daily_losses:.2f} / ${daily_limit:.2f}",
            "status": daily_status,
            "label": daily_label,
        },
        {
            "name": "Drawdown Alert",
            "detail": f"{drawdown_pct:.1f}% from peak",
            "status": dd_status,
            "label": dd_label,
        },
        {
            "name": "Minimum Bankroll",
            "detail": f"${current:.2f} / ${min_threshold:.2f} floor",
            "status": min_status,
            "label": min_label,
        },
    ]


def load_bet_history(
    user_id: int = 1,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    league: Optional[str] = None,
    market_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    bet_type: Optional[str] = None,
) -> pd.DataFrame:
    """Load bet history with optional filters for the bet history table."""
    with get_session() as session:
        query = session.query(BetLog).filter(BetLog.user_id == user_id)

        if date_from:
            query = query.filter(BetLog.date >= date_from)
        if date_to:
            query = query.filter(BetLog.date <= date_to)
        if league:
            query = query.filter(BetLog.league == league)
        if market_type:
            query = query.filter(BetLog.market_type == market_type)
        if status_filter:
            query = query.filter(BetLog.status == status_filter)
        if bet_type:
            query = query.filter(BetLog.bet_type == bet_type)

        rows = query.order_by(BetLog.date.desc()).all()

    if not rows:
        return pd.DataFrame()

    data = []
    for b in rows:
        odds = b.odds_at_placement if b.odds_at_placement else b.odds_at_detection
        data.append({
            "Date": b.date,
            "Match": f"{b.home_team} vs {b.away_team}",
            "Market": MARKET_LABELS.get(b.market_type, b.market_type),
            "Selection": b.selection,
            "Odds": f"{odds:.2f}" if odds else "—",
            "Stake": f"${b.stake:.2f}" if b.stake else "—",
            "Result": {"won": "✅ Won", "lost": "❌ Lost", "pending": "⏳ Pending",
                       "void": "⚪ Void", "half_won": "✅ Half", "half_lost": "❌ Half"
                       }.get(b.status, b.status),
            "P&L": f"+${b.pnl:.2f}" if b.pnl and b.pnl >= 0 else (
                f"-${abs(b.pnl):.2f}" if b.pnl else "—"
            ),
            "Type": b.bet_type,
        })

    return pd.DataFrame(data)


def load_bankroll_history(user_id: int = 1) -> pd.DataFrame:
    """Load bankroll over time for the bankroll chart.

    Uses bankroll_after from bet_log to track bankroll trajectory.
    """
    with get_session() as session:
        rows = (
            session.query(BetLog.date, BetLog.bankroll_after)
            .filter(
                BetLog.user_id == user_id,
                BetLog.bankroll_after.isnot(None),
                BetLog.status.in_(["won", "lost"]),
            )
            .order_by(BetLog.date.asc())
            .all()
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([{"date": r.date, "bankroll": r.bankroll_after} for r in rows])
    # Take the last bankroll value per day (if multiple bets per day)
    df = df.groupby("date")["bankroll"].last().reset_index()
    return df


def load_monthly_breakdown(user_id: int = 1) -> pd.DataFrame:
    """Calculate monthly P&L breakdown from bet_log."""
    with get_session() as session:
        rows = (
            session.query(BetLog)
            .filter(
                BetLog.user_id == user_id,
                BetLog.status.in_(["won", "lost"]),
            )
            .order_by(BetLog.date.asc())
            .all()
        )

    if not rows:
        return pd.DataFrame()

    data = []
    for b in rows:
        data.append({
            "month": b.date[:7],  # YYYY-MM
            "pnl": b.pnl or 0.0,
            "stake": b.stake or 0.0,
            "won": 1 if b.status == "won" else 0,
            "lost": 1 if b.status == "lost" else 0,
        })

    df = pd.DataFrame(data)
    monthly = df.groupby("month").agg(
        Bets=("pnl", "count"),
        Wins=("won", "sum"),
        Losses=("lost", "sum"),
        Staked=("stake", "sum"),
        PnL=("pnl", "sum"),
    ).reset_index()

    monthly.rename(columns={"month": "Month"}, inplace=True)
    monthly["ROI %"] = (monthly["PnL"] / monthly["Staked"] * 100).round(1)
    monthly["Staked"] = monthly["Staked"].apply(lambda x: f"${x:.2f}")
    monthly["PnL"] = monthly["PnL"].apply(
        lambda x: f"+${x:.2f}" if x >= 0 else f"-${abs(x):.2f}"
    )
    monthly["ROI %"] = monthly["ROI %"].apply(lambda x: f"{x:+.1f}%")

    return monthly


def get_filter_options(user_id: int = 1) -> Dict:
    """Get unique filter values from bet_log for dropdowns."""
    with get_session() as session:
        leagues = [
            r[0] for r in session.query(BetLog.league).filter_by(user_id=user_id).distinct().all()
        ]
        markets = [
            r[0] for r in session.query(BetLog.market_type).filter_by(user_id=user_id).distinct().all()
        ]
    return {"leagues": sorted(leagues), "markets": sorted(markets)}


# ============================================================================
# Charts
# ============================================================================

def create_bankroll_chart(df: pd.DataFrame, peak: float, starting: float) -> go.Figure:
    """Create a Plotly line chart of bankroll over time.

    Shows the bankroll trajectory with the peak annotated and
    a horizontal reference line at the starting bankroll.
    """
    fig = go.Figure()

    # Bankroll line
    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["bankroll"],
        mode="lines",
        line=dict(color=COLOURS["blue"], width=2),
        fill="tozeroy",
        fillcolor="rgba(88, 166, 255, 0.05)",
        hovertemplate="Date: %{x}<br>Bankroll: $%{y:.2f}<extra></extra>",
    ))

    # Starting bankroll reference line
    fig.add_hline(
        y=starting, line_dash="dash",
        line_color=COLOURS["border"], line_width=1,
        annotation_text=f"Starting (${starting:.0f})",
        annotation_position="top left",
        annotation_font=dict(color=COLOURS["text_secondary"], size=10),
    )

    # Peak annotation — arrow points at the chart's max point,
    # but the label shows the true all-time peak from the metric
    if not df.empty:
        peak_idx = df["bankroll"].idxmax()
        peak_date = df.loc[peak_idx, "date"]
        peak_val = df.loc[peak_idx, "bankroll"]
        fig.add_annotation(
            x=peak_date, y=peak_val,
            text=f"Peak: ${peak:.2f}",
            showarrow=True,
            arrowhead=2,
            arrowcolor=COLOURS["green"],
            font=dict(color=COLOURS["green"], size=11, family="JetBrains Mono, monospace"),
            bgcolor="rgba(0,0,0,0.6)",
            bordercolor=COLOURS["green"],
            borderwidth=1,
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
            title="",
        ),
        yaxis=dict(
            gridcolor=COLOURS["border"],
            showgrid=True,
            title="Bankroll ($)",
            tickprefix="$",
        ),
        margin=dict(l=60, r=20, t=10, b=40),
        height=350,
        showlegend=False,
    )

    return fig


# ============================================================================
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">Bankroll Manager</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Bankroll tracking, staking settings, and safety limits</p>',
    unsafe_allow_html=True,
)
st.divider()

# --- Load Data ---
user_data = load_user_data()

if not user_data:
    st.markdown(
        '<div class="bv-empty-state">'
        "No user found. Run the setup pipeline first to create the owner account."
        "</div>",
        unsafe_allow_html=True,
    )
else:
    peak = get_peak_bankroll(user_data["id"])
    daily_losses = get_daily_losses(user_data["id"])
    current = user_data["current_bankroll"]
    starting = user_data["starting_bankroll"]

    # Drawdown from peak
    drawdown_pct = ((peak - current) / peak * 100) if peak > 0 else 0.0

    # --- Section 1: Key Metrics ---
    bankroll_colour = COLOURS["green"] if current >= starting else COLOURS["red"]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f'<div>'
            f'<span style="font-family: \'Inter\', sans-serif; font-size: 12px; color: #8B949E; '
            f'text-transform: uppercase; letter-spacing: 0.5px;">Current Bankroll</span><br>'
            f'<span style="font-family: \'JetBrains Mono\', monospace; font-size: 28px; font-weight: 700; '
            f'color: {bankroll_colour};">${current:.2f}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.metric("Starting Bankroll", f"${starting:.2f}")
    with col3:
        st.metric("Peak Bankroll", f"${peak:.2f}")
    with col4:
        dd_colour = COLOURS["green"] if drawdown_pct < 15 else (
            COLOURS["yellow"] if drawdown_pct < 25 else COLOURS["red"]
        )
        st.markdown(
            f'<div>'
            f'<span style="font-family: \'Inter\', sans-serif; font-size: 12px; color: #8B949E; '
            f'text-transform: uppercase; letter-spacing: 0.5px;">Drawdown</span><br>'
            f'<span style="font-family: \'JetBrains Mono\', monospace; font-size: 28px; font-weight: 700; '
            f'color: {dd_colour};">{drawdown_pct:.1f}%</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Section 2: Staking Method ---
    method = user_data["staking_method"]
    method_label, method_desc = STAKING_LABELS.get(method, (method, ""))

    stake_detail = ""
    if method in ("flat", "percentage"):
        stake_detail = f" — {user_data['stake_percentage'] * 100:.0f}% per bet"
    elif method == "kelly":
        stake_detail = f" — {user_data['kelly_fraction'] * 100:.0f}% Kelly fraction"

    st.markdown(
        f'<div style="padding: 12px 0;">'
        f'<span style="font-family: Inter, sans-serif; font-size: 14px; color: {COLOURS["text"]};">'
        f'Staking Method: </span>'
        f'<span style="font-family: JetBrains Mono, monospace; font-size: 14px; font-weight: 700; '
        f'color: {COLOURS["blue"]};">{method_label}{stake_detail}</span>'
        f'<br><span style="font-family: Inter, sans-serif; font-size: 12px; '
        f'color: {COLOURS["text_secondary"]};">{method_desc}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.divider()

    # --- Section 3: Safety Status Indicators ---
    st.markdown(
        '<div class="bv-section-header">Safety Limits</div>',
        unsafe_allow_html=True,
    )

    limits = check_safety_limits(user_data, peak, daily_losses)

    limit_cols = st.columns(len(limits))
    for i, limit in enumerate(limits):
        status_colour = COLOURS.get(limit["status"], COLOURS["border"])
        with limit_cols[i]:
            st.markdown(
                f'<div class="bv-card" style="text-align: center; border-color: {status_colour};">'
                f'<div style="font-family: Inter, sans-serif; font-size: 12px; color: {COLOURS["text_secondary"]}; '
                f'text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">'
                f'{limit["name"]}</div>'
                f'<div style="font-family: JetBrains Mono, monospace; font-size: 18px; font-weight: 700; '
                f'color: {status_colour}; margin-bottom: 4px;">'
                f'{limit["label"]}</div>'
                f'<div style="font-family: JetBrains Mono, monospace; font-size: 11px; '
                f'color: {COLOURS["text_secondary"]};">'
                f'{limit["detail"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.divider()

    # --- Section 4: Bankroll Chart ---
    st.markdown(
        '<div class="bv-section-header">Bankroll History</div>',
        unsafe_allow_html=True,
    )

    bankroll_hist = load_bankroll_history(user_data["id"])
    if not bankroll_hist.empty:
        fig_bankroll = create_bankroll_chart(bankroll_hist, peak, starting)
        st.plotly_chart(fig_bankroll, use_container_width=True, config={"displayModeBar": False})
    else:
        st.markdown(
            '<div class="bv-empty-state">'
            "Bankroll history will appear here after bets are resolved. "
            "The chart tracks your bankroll over time with peak annotation."
            "</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Section 5: Bet History ---
    st.markdown(
        '<div class="bv-section-header">Bet History</div>',
        unsafe_allow_html=True,
    )

    filter_options = get_filter_options(user_data["id"])

    # Filters row
    f_cols = st.columns(5)
    with f_cols[0]:
        bh_date_range = st.date_input(
            "Date range",
            value=(date(2024, 8, 1), date.today()),
            key="bh_date_range",
        )
    with f_cols[1]:
        bh_league = st.selectbox(
            "League",
            options=["All"] + filter_options["leagues"],
            key="bh_league",
        )
    with f_cols[2]:
        bh_market = st.selectbox(
            "Market",
            options=["All"] + filter_options["markets"],
            key="bh_market",
        )
    with f_cols[3]:
        bh_status = st.selectbox(
            "Result",
            options=["All", "won", "lost", "pending", "void"],
            key="bh_status",
        )
    with f_cols[4]:
        bh_type = st.selectbox(
            "Bet Type",
            options=["All", "system_pick", "user_placed"],
            key="bh_type",
        )

    # Parse filters
    bh_from = bh_date_range[0].isoformat() if isinstance(bh_date_range, tuple) and len(bh_date_range) >= 1 else None
    bh_to = bh_date_range[1].isoformat() if isinstance(bh_date_range, tuple) and len(bh_date_range) >= 2 else None

    bet_hist = load_bet_history(
        user_id=user_data["id"],
        date_from=bh_from,
        date_to=bh_to,
        league=bh_league if bh_league != "All" else None,
        market_type=bh_market if bh_market != "All" else None,
        status_filter=bh_status if bh_status != "All" else None,
        bet_type=bh_type if bh_type != "All" else None,
    )

    if not bet_hist.empty:
        st.dataframe(
            bet_hist,
            use_container_width=True,
            hide_index=True,
            height=400,
        )
        st.markdown(
            f'<p style="font-family: Inter, sans-serif; font-size: 12px; '
            f'color: {COLOURS["text_secondary"]};">'
            f'Showing {len(bet_hist)} bets</p>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="bv-empty-state">'
            "No bets match the current filters."
            "</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Section 6: Monthly P&L Breakdown ---
    st.markdown(
        '<div class="bv-section-header">Monthly P&L Breakdown</div>',
        unsafe_allow_html=True,
    )

    monthly = load_monthly_breakdown(user_data["id"])
    if not monthly.empty:
        st.dataframe(
            monthly,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.markdown(
            '<div class="bv-empty-state">'
            "Monthly breakdown will appear after bets are resolved."
            "</div>",
            unsafe_allow_html=True,
        )

# ============================================================================
# Glossary — explains every bankroll and staking term on this page (E27-03)
# ============================================================================
# The owner is learning (MP §12). This glossary defines bankroll management
# concepts so anyone can understand their financial position and risk controls.

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

    # --- Bankroll Basics ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Bankroll Basics</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Current Bankroll</span>'
        '  <span class="gloss-def">Your total betting capital right now — starting amount '
        'plus all profits, minus all losses. This is the money available for future bets.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Starting Bankroll</span>'
        '  <span class="gloss-def">The initial capital you allocated to betting. '
        'Shown as a reference line on the bankroll chart.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Peak Bankroll</span>'
        '  <span class="gloss-def">The highest your bankroll has ever reached. '
        'Used to calculate drawdown (how far you\'ve fallen from the peak).</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Drawdown</span>'
        '  <span class="gloss-def">The percentage decline from your peak bankroll to current level. '
        'E.g. peak was $1,100, now $990 = 10% drawdown. '
        'Drawdowns of 10\u201320% are normal; above 30% triggers a safety alert.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Staking Methods ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Staking Methods</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Flat Staking</span>'
        '  <span class="gloss-def">Bet a fixed percentage of your starting bankroll on every bet, '
        'regardless of current bankroll. Simple and conservative. '
        'E.g. 2% of $1,000 = $20 per bet, always.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Percentage Staking</span>'
        '  <span class="gloss-def">Bet a fixed percentage of your current bankroll. '
        'Stakes grow when winning and shrink when losing — '
        'automatic bankroll protection.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Kelly Criterion</span>'
        '  <span class="gloss-def">A mathematical formula that sizes bets proportional to edge '
        'and odds. Maximises long-term growth but can be volatile. '
        'BetVector uses "fractional Kelly" (e.g. quarter-Kelly) for safety.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Stake %</span>'
        '  <span class="gloss-def">The percentage of your bankroll wagered per bet. '
        'Lower = more conservative. Professional bettors typically use 1\u20133%.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Safety Limits ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Safety Limits</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Daily Loss Limit</span>'
        '  <span class="gloss-def">Maximum amount you can lose in one day before the system '
        'stops suggesting bets. Prevents catastrophic single-day losses.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Drawdown Alert</span>'
        '  <span class="gloss-def">Warning triggered when your bankroll falls a certain '
        'percentage below its peak. A signal to review strategy or reduce stakes.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Minimum Bankroll</span>'
        '  <span class="gloss-def">The floor below which all betting stops. '
        'If your bankroll drops to this level, the system pauses until you add funds '
        'or reassess your strategy.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #3FB950;">OK</span>'
        '  <span class="gloss-def">Safety limit is not close to being triggered. '
        'Normal operation.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #D29922;">APPROACHING</span>'
        '  <span class="gloss-def">Safety limit is within range. '
        'Consider reducing stakes or pausing.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #F85149;">TRIGGERED</span>'
        '  <span class="gloss-def">Safety limit has been reached. '
        'Betting is paused until the condition clears.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Bet History ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Bet History</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Market Codes</span>'
        '  <span class="gloss-def">1X2 = Match Result, OU15 = O/U 1.5 Goals, '
        'OU25 = O/U 2.5 Goals, BTTS = Both Teams to Score.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">P&amp;L</span>'
        '  <span class="gloss-def">Profit/Loss for a single bet. '
        'Won: stake \u00D7 (odds \u2212 1). Lost: \u2212stake. '
        'E.g. $20 at 2.50 odds: Won = +$30, Lost = \u2212$20.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Monthly ROI</span>'
        '  <span class="gloss-def">Return on Investment for that calendar month. '
        'Profit divided by total staked in the month, as a percentage.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
