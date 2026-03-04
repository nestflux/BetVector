"""
BetVector — Settings Page (E10-03, E29-04)
============================================
User preferences, league management, notification toggles, and user
management for the dashboard owner.

Sections:
1. User Preferences — staking method, stake %, Kelly fraction, edge threshold,
   starting bankroll, bankroll reset
2. League Management — enable/disable leagues from config
3. Notification Preferences — email address, morning/evening/weekly toggles
4. User Management (owner only) — list users, invite new viewer

E29-04: Added bankroll reset feature with two-step confirmation.
  Resets current_bankroll to starting_bankroll. Preserves all bet history.

Master Plan refs: MP §3 Flow 6 (First-Time Setup), MP §3 Flow 7 (Adding a
Friend), MP §8 Design System
"""

from datetime import datetime
from typing import Dict, List, Optional

import streamlit as st

from src.database.db import get_session
from src.database.models import InjuryFlag, League, Team, User


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
    "purple": "#BC8CFF",
}

# Staking method options with explanations (from MP §3 Flow 6)
STAKING_OPTIONS = {
    "flat": (
        "Flat Staking",
        "Bet a fixed percentage of your bankroll on every qualifying bet. "
        "Simple and safe — recommended for beginners.",
    ),
    "percentage": (
        "Percentage Staking",
        "Bet a recalculated percentage of your current bankroll. "
        "Adjusts automatically as your bankroll changes.",
    ),
    "kelly": (
        "Kelly Criterion",
        "Mathematically optimal staking based on your edge. "
        "Advanced — only recommended after 500+ bets with good calibration.",
    ),
}


# ============================================================================
# Data Loading
# ============================================================================

def load_current_user(user_id: int = 1) -> Optional[Dict]:
    """Load current user's settings from the database."""
    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            return None
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email or "",
            "role": user.role,
            "starting_bankroll": user.starting_bankroll,
            "current_bankroll": user.current_bankroll,
            "staking_method": user.staking_method,
            "stake_percentage": user.stake_percentage,
            "kelly_fraction": user.kelly_fraction,
            "edge_threshold": user.edge_threshold,
            "is_active": user.is_active,
        }


def load_all_users() -> List[Dict]:
    """Load all users for the user management section."""
    with get_session() as session:
        users = session.query(User).order_by(User.id).all()
        return [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email or "—",
                "role": u.role,
                "is_active": u.is_active,
                "created_at": u.created_at,
            }
            for u in users
        ]


def load_leagues() -> List[Dict]:
    """Load all leagues from the database with their active status."""
    with get_session() as session:
        leagues = session.query(League).order_by(League.name).all()
        return [
            {
                "id": lg.id,
                "name": lg.name,
                "short_name": lg.short_name,
                "country": lg.country,
                "is_active": bool(lg.is_active),
            }
            for lg in leagues
        ]


# ============================================================================
# Database Persistence
# ============================================================================

def save_user_setting(user_id: int, field: str, value) -> bool:
    """Save a single user setting to the database.

    Returns True on success, False on failure.
    Updates the updated_at timestamp alongside the field.
    """
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user:
                return False
            setattr(user, field, value)
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


def reset_bankroll(user_id: int) -> bool:
    """Reset the user's current bankroll to their starting bankroll.

    E29-04: This is a "fresh start" — the bankroll counter resets but all
    historical bet data (BetLog) is preserved.  This lets the user restart
    their bankroll tracking without losing performance history.

    Parameters
    ----------
    user_id : int
        The user's database ID.

    Returns
    -------
    bool
        True if the reset succeeded, False otherwise.
    """
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user:
                return False
            user.current_bankroll = user.starting_bankroll
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


def toggle_league_active(league_id: int, is_active: bool) -> bool:
    """Enable or disable a league in the database.

    Changes take effect on the next pipeline run.
    """
    try:
        with get_session() as session:
            league = session.get(League, league_id)
            if not league:
                return False
            league.is_active = 1 if is_active else 0
            session.commit()
        return True
    except Exception:
        return False


def create_viewer_user(name: str, email: str) -> Optional[int]:
    """Create a new user with role='viewer'.

    Returns the new user's ID on success, None on failure.
    This is triggered by the owner via the 'Invite User' button (MP §3 Flow 7).
    """
    try:
        with get_session() as session:
            new_user = User(
                name=name,
                email=email,
                role="viewer",
                starting_bankroll=500.0,
                current_bankroll=500.0,
                staking_method="flat",
                stake_percentage=0.02,
                kelly_fraction=0.25,
                edge_threshold=0.05,
                is_active=1,
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
            )
            session.add(new_user)
            session.commit()
            session.refresh(new_user)
            return new_user.id
    except Exception:
        return None


def deactivate_user(user_id: int) -> bool:
    """Deactivate a user (set is_active=0). Cannot deactivate the owner."""
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user or user.role == "owner":
                return False
            user.is_active = 0
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


def reactivate_user(user_id: int) -> bool:
    """Reactivate a previously deactivated user."""
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user:
                return False
            user.is_active = 1
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


# ============================================================================
# Injury Flags — Data Loading & CRUD (E22-02)
# ============================================================================

def load_teams() -> List[Dict]:
    """Load all teams for the injury flags team dropdown."""
    with get_session() as session:
        teams = session.query(Team).order_by(Team.name).all()
        return [
            {"id": t.id, "name": t.name}
            for t in teams
        ]


def load_injury_flags() -> List[Dict]:
    """Load all injury flags with team names for display."""
    with get_session() as session:
        flags = (
            session.query(InjuryFlag)
            .order_by(InjuryFlag.team_id, InjuryFlag.impact_rating.desc())
            .all()
        )
        results = []
        for f in flags:
            team = session.get(Team, f.team_id)
            results.append({
                "id": f.id,
                "team_id": f.team_id,
                "team_name": team.name if team else f"Team {f.team_id}",
                "player_name": f.player_name,
                "status": f.status,
                "estimated_return": f.estimated_return or "—",
                "impact_rating": f.impact_rating,
                "updated_at": f.updated_at,
            })
        return results


def create_injury_flag(
    team_id: int,
    player_name: str,
    status: str,
    impact_rating: float,
    estimated_return: Optional[str] = None,
) -> Optional[int]:
    """Create a new injury flag.  Returns the new flag's ID on success."""
    try:
        with get_session() as session:
            flag = InjuryFlag(
                team_id=team_id,
                player_name=player_name.strip(),
                status=status,
                impact_rating=round(impact_rating, 2),
                estimated_return=estimated_return.strip() if estimated_return else None,
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
            )
            session.add(flag)
            session.commit()
            session.refresh(flag)
            return flag.id
    except Exception:
        return None


def update_injury_flag(
    flag_id: int,
    status: Optional[str] = None,
    impact_rating: Optional[float] = None,
    estimated_return: Optional[str] = None,
) -> bool:
    """Update an existing injury flag.  Returns True on success."""
    try:
        with get_session() as session:
            flag = session.get(InjuryFlag, flag_id)
            if not flag:
                return False
            if status is not None:
                flag.status = status
            if impact_rating is not None:
                flag.impact_rating = round(impact_rating, 2)
            if estimated_return is not None:
                flag.estimated_return = estimated_return.strip() if estimated_return else None
            flag.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


def delete_injury_flag(flag_id: int) -> bool:
    """Delete an injury flag (player has returned).  Returns True on success."""
    try:
        with get_session() as session:
            flag = session.get(InjuryFlag, flag_id)
            if not flag:
                return False
            session.delete(flag)
            session.commit()
        return True
    except Exception:
        return False


# ============================================================================
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">Settings</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Configure staking, thresholds, notifications, and users</p>',
    unsafe_allow_html=True,
)
st.divider()

# --- Load current user ---
user_data = load_current_user()

if not user_data:
    st.markdown(
        '<div class="bv-empty-state">'
        "No user found. Run the setup pipeline first to create the owner account."
        "</div>",
        unsafe_allow_html=True,
    )
else:
    # ==================================================================
    # Section 1: User Preferences
    # ==================================================================
    st.markdown(
        '<div class="bv-section-header">User Preferences</div>',
        unsafe_allow_html=True,
    )

    # --- 1a: Staking Method Selector ---
    # Map internal keys to display labels and back
    method_keys = list(STAKING_OPTIONS.keys())
    method_labels = [STAKING_OPTIONS[k][0] for k in method_keys]
    current_method_idx = method_keys.index(user_data["staking_method"]) if user_data["staking_method"] in method_keys else 0

    selected_label = st.radio(
        "Staking Method",
        options=method_labels,
        index=current_method_idx,
        key="staking_method_radio",
        horizontal=True,
    )

    # Show explanation for the selected method
    selected_key = method_keys[method_labels.index(selected_label)]
    _, explanation = STAKING_OPTIONS[selected_key]
    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 13px; '
        f'color: {COLOURS["text_secondary"]}; margin-top: -8px;">{explanation}</p>',
        unsafe_allow_html=True,
    )

    # Save staking method if changed
    if selected_key != user_data["staking_method"]:
        if save_user_setting(user_data["id"], "staking_method", selected_key):
            st.toast(f"Staking method updated to {selected_label}", icon="✅")
            user_data["staking_method"] = selected_key

    # --- 1b: Stake Percentage & Kelly Fraction ---
    pref_cols = st.columns(2)
    with pref_cols[0]:
        # Stake percentage: 1% to 10% range
        new_stake_pct = st.slider(
            "Stake Percentage",
            min_value=1,
            max_value=10,
            value=int(user_data["stake_percentage"] * 100),
            step=1,
            format="%d%%",
            help="Percentage of your current bankroll to stake on each bet.",
            key="stake_pct_slider",
        )
        new_stake_decimal = new_stake_pct / 100.0
        if abs(new_stake_decimal - user_data["stake_percentage"]) > 0.001:
            if save_user_setting(user_data["id"], "stake_percentage", new_stake_decimal):
                st.toast(f"Stake percentage updated to {new_stake_pct}%", icon="✅")

    with pref_cols[1]:
        # Kelly fraction: 10% to 100% (quarter-Kelly = 25%)
        new_kelly = st.slider(
            "Kelly Fraction",
            min_value=10,
            max_value=100,
            value=int(user_data["kelly_fraction"] * 100),
            step=5,
            format="%d%%",
            help="Fraction of full Kelly to use. 25% (quarter-Kelly) is recommended "
                 "to reduce variance.",
            key="kelly_slider",
        )
        new_kelly_decimal = new_kelly / 100.0
        if abs(new_kelly_decimal - user_data["kelly_fraction"]) > 0.001:
            if save_user_setting(user_data["id"], "kelly_fraction", new_kelly_decimal):
                st.toast(f"Kelly fraction updated to {new_kelly}%", icon="✅")

    # --- 1c: Edge Threshold ---
    # AC2: slider from 1% to 15% with 1% increments
    new_edge = st.slider(
        "Edge Threshold",
        min_value=1,
        max_value=15,
        value=int(user_data["edge_threshold"] * 100),
        step=1,
        format="%d%%",
        help="BetVector only flags a bet when the model's probability exceeds the "
             "bookmaker's implied probability by at least this amount. "
             "Higher = fewer but stronger picks.",
        key="edge_slider",
    )
    new_edge_decimal = new_edge / 100.0
    if abs(new_edge_decimal - user_data["edge_threshold"]) > 0.001:
        if save_user_setting(user_data["id"], "edge_threshold", new_edge_decimal):
            st.toast(f"Edge threshold updated to {new_edge}%", icon="✅")

    # --- 1d: Starting Bankroll ---
    new_starting = st.number_input(
        "Starting Bankroll ($)",
        min_value=50.0,
        max_value=100000.0,
        value=user_data["starting_bankroll"],
        step=50.0,
        help="The total amount you've set aside for betting. Safety limits are "
             "calculated as percentages of this amount.",
        key="starting_bankroll_input",
    )
    if abs(new_starting - user_data["starting_bankroll"]) > 0.01:
        if save_user_setting(user_data["id"], "starting_bankroll", new_starting):
            st.toast(f"Starting bankroll updated to ${new_starting:.2f}", icon="✅")

    # --- 1e: Bankroll Management (E29-04) ---
    # Shows current vs starting bankroll comparison and a reset button
    # with two-step confirmation to prevent accidental resets.
    st.markdown(
        '<div style="margin-top: 20px; font-family: Inter, sans-serif; '
        f'font-size: 14px; font-weight: 600; color: {COLOURS["text"]};">'
        'Bankroll Management</div>',
        unsafe_allow_html=True,
    )

    # Current vs starting comparison
    current_br = user_data["current_bankroll"]
    starting_br = user_data["starting_bankroll"]
    diff = current_br - starting_br
    diff_colour = COLOURS["green"] if diff >= 0 else COLOURS["red"]
    diff_sign = "+" if diff >= 0 else ""

    st.markdown(
        f'<div style="display: flex; gap: 24px; align-items: center; '
        f'margin: 8px 0 12px 0; font-family: Inter, sans-serif; '
        f'font-size: 13px; color: {COLOURS["text_secondary"]};">'
        f'<span>Starting: <strong style="color: {COLOURS["text"]}; '
        f"font-family: 'JetBrains Mono', monospace;\">${starting_br:.2f}</strong></span>"
        f'<span>Current: <strong style="color: {diff_colour}; '
        f"font-family: 'JetBrains Mono', monospace;\">${current_br:.2f}</strong></span>"
        f'<span style="color: {diff_colour}; font-family: \'JetBrains Mono\', monospace; '
        f'font-size: 12px;">({diff_sign}${abs(diff):.2f})</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Two-step reset: first click shows warning + confirm button
    # Using session state to track confirmation step
    if "bankroll_reset_confirm" not in st.session_state:
        st.session_state.bankroll_reset_confirm = False

    if not st.session_state.bankroll_reset_confirm:
        # Step 1: Show the initial reset button
        if st.button(
            "🔄 Reset Bankroll",
            key="reset_bankroll_btn",
            help="Reset your current bankroll to the starting amount",
            type="secondary",
        ):
            st.session_state.bankroll_reset_confirm = True
            st.rerun()
    else:
        # Step 2: Show warning message and confirm/cancel buttons
        st.markdown(
            f'<div style="background-color: rgba(248, 81, 73, 0.1); '
            f'border: 1px solid {COLOURS["red"]}; border-radius: 6px; '
            f'padding: 12px; margin: 8px 0; font-family: Inter, sans-serif; '
            f'font-size: 13px; color: {COLOURS["text"]};">'
            f'⚠️ This will reset your current bankroll to '
            f'<strong>${starting_br:.2f}</strong>. '
            f'Existing bet history will be preserved.'
            f'</div>',
            unsafe_allow_html=True,
        )

        confirm_cols = st.columns([1, 1, 3])
        with confirm_cols[0]:
            if st.button(
                "✅ Confirm Reset",
                key="confirm_reset_btn",
                type="primary",
            ):
                if reset_bankroll(user_data["id"]):
                    st.session_state.bankroll_reset_confirm = False
                    st.toast(
                        f"Bankroll reset to ${starting_br:.2f}",
                        icon="✅",
                    )
                    # Update local state so the comparison refreshes
                    user_data["current_bankroll"] = starting_br
                    st.rerun()
                else:
                    st.error("Failed to reset bankroll. Please try again.")

        with confirm_cols[1]:
            if st.button(
                "Cancel",
                key="cancel_reset_btn",
                type="secondary",
            ):
                st.session_state.bankroll_reset_confirm = False
                st.rerun()

    st.divider()

    # ==================================================================
    # Section 2: League Management
    # ==================================================================
    st.markdown(
        '<div class="bv-section-header">League Management</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 13px; '
        f'color: {COLOURS["text_secondary"]}; margin-bottom: 12px;">'
        f'Enable or disable leagues. Changes take effect on the next pipeline run.'
        f'</p>',
        unsafe_allow_html=True,
    )

    leagues = load_leagues()

    if not leagues:
        st.markdown(
            '<div class="bv-empty-state">'
            "No leagues found in the database. Run the setup pipeline to seed leagues."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        for lg in leagues:
            league_col1, league_col2 = st.columns([3, 1])
            with league_col1:
                st.markdown(
                    f'<div style="padding: 8px 0;">'
                    f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'color: {COLOURS["text"]};">{lg["name"]}</span>'
                    f' <span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                    f'color: {COLOURS["text_secondary"]};">({lg["short_name"]})</span>'
                    f' <span style="font-family: Inter, sans-serif; font-size: 12px; '
                    f'color: {COLOURS["text_secondary"]};">— {lg["country"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with league_col2:
                new_active = st.toggle(
                    f'{lg["short_name"]}',
                    value=lg["is_active"],
                    key=f'league_toggle_{lg["id"]}',
                    label_visibility="collapsed",
                )
                if new_active != lg["is_active"]:
                    if toggle_league_active(lg["id"], new_active):
                        status = "enabled" if new_active else "disabled"
                        st.toast(f'{lg["name"]} {status}', icon="✅")

    st.divider()

    # ==================================================================
    # Section 3: Notification Preferences
    # ==================================================================
    st.markdown(
        '<div class="bv-section-header">Notification Preferences</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 13px; '
        f'color: {COLOURS["text_secondary"]}; margin-bottom: 12px;">'
        f'Email notification settings. Requires a valid email address and SMTP '
        f'credentials configured in .env.'
        f'</p>',
        unsafe_allow_html=True,
    )

    # Email address input
    new_email = st.text_input(
        "Email Address",
        value=user_data["email"],
        placeholder="your@email.com",
        help="Email address for receiving BetVector notifications.",
        key="email_input",
    )
    if new_email != user_data["email"]:
        if save_user_setting(user_data["id"], "email", new_email if new_email else None):
            st.toast("Email address updated", icon="✅")

    # Notification toggles — these are informational for now (E11 will
    # wire them to the actual email sender).  We store a simple note
    # that the UI is ready.
    notif_cols = st.columns(3)
    with notif_cols[0]:
        st.toggle(
            "Morning Picks",
            value=True,
            key="notif_morning",
            help="Daily email with today's value bets (sent at 06:00 UTC).",
        )
    with notif_cols[1]:
        st.toggle(
            "Evening Review",
            value=True,
            key="notif_evening",
            help="Daily email with results and P&L (sent at 22:00 UTC).",
        )
    with notif_cols[2]:
        st.toggle(
            "Weekly Summary",
            value=True,
            key="notif_weekly",
            help="Weekly performance summary (sent Sunday 20:00 UTC).",
        )

    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 12px; '
        f'color: {COLOURS["text_secondary"]}; margin-top: 4px;">'
        f'Email delivery will be configured in E11 (Email Notifications). '
        f'Toggles saved as defaults.'
        f'</p>',
        unsafe_allow_html=True,
    )

    st.divider()

    # ==================================================================
    # Section 4: Injury Flags (E22-02)
    # ==================================================================
    st.markdown(
        '<div class="bv-section-header">Injury Flags</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 13px; '
        f'color: {COLOURS["text_secondary"]}; margin-bottom: 12px;">'
        f'Flag injured, doubtful, or suspended players to adjust predictions. '
        f'Only "out" and "suspended" players affect the model. '
        f'Remove flags when players return to fitness.'
        f'</p>',
        unsafe_allow_html=True,
    )

    # Impact rating guidance
    st.markdown(
        f'<div style="background: {COLOURS["surface"]}; border: 1px solid {COLOURS["border"]}; '
        f'border-radius: 6px; padding: 12px; margin-bottom: 16px;">'
        f'<p style="font-family: Inter, sans-serif; font-size: 12px; '
        f'color: {COLOURS["text_secondary"]}; margin: 0;">'
        f'<b style="color: {COLOURS["text"]};">Impact Rating Guide:</b>&ensp;'
        f'<span style="color: {COLOURS["text_secondary"]};">0.1–0.3</span> Rotation player&ensp;·&ensp;'
        f'<span style="color: {COLOURS["yellow"]};">0.4–0.5</span> Regular starter&ensp;·&ensp;'
        f'<span style="color: {COLOURS["red"]};">0.6–0.7</span> Key player&ensp;·&ensp;'
        f'<span style="color: {COLOURS["red"]}; font-weight: 600;">0.8–1.0</span> Star player'
        f'</p></div>',
        unsafe_allow_html=True,
    )

    # --- Add new injury flag form ---
    teams = load_teams()
    team_names = [t["name"] for t in teams]
    team_id_map = {t["name"]: t["id"] for t in teams}

    with st.expander("Add Injury Flag", expanded=False):
        add_cols = st.columns([2, 2, 1, 1])
        with add_cols[0]:
            selected_team = st.selectbox(
                "Team",
                options=team_names,
                key="injury_team_select",
                placeholder="Select team...",
            )
        with add_cols[1]:
            player_name = st.text_input(
                "Player Name",
                placeholder="e.g., Erling Haaland",
                key="injury_player_input",
            )
        with add_cols[2]:
            injury_status = st.selectbox(
                "Status",
                options=["out", "doubt", "suspended"],
                key="injury_status_select",
                help="Only 'out' and 'suspended' affect predictions.",
            )
        with add_cols[3]:
            impact = st.slider(
                "Impact",
                min_value=0.1,
                max_value=1.0,
                value=0.5,
                step=0.1,
                key="injury_impact_slider",
                help="How important is this player to the team?",
            )

        est_return = st.text_input(
            "Estimated Return (optional)",
            placeholder="e.g., 2 weeks, after international break",
            key="injury_return_input",
        )

        if st.button("Add Injury Flag", key="add_injury_btn", type="primary"):
            if not player_name or not selected_team:
                st.warning("Please enter a team and player name.")
            else:
                team_id = team_id_map.get(selected_team)
                if team_id:
                    new_id = create_injury_flag(
                        team_id=team_id,
                        player_name=player_name,
                        status=injury_status,
                        impact_rating=impact,
                        estimated_return=est_return if est_return else None,
                    )
                    if new_id:
                        st.toast(
                            f"Added injury flag: {player_name} ({selected_team})",
                            icon="🏥",
                        )
                        st.rerun()
                    else:
                        st.error("Failed to create injury flag.")

    # --- Display current injury flags ---
    flags = load_injury_flags()

    if not flags:
        st.markdown(
            f'<div style="background: {COLOURS["surface"]}; border: 1px solid {COLOURS["border"]}; '
            f'border-radius: 6px; padding: 20px; text-align: center;">'
            f'<p style="font-family: Inter, sans-serif; font-size: 14px; '
            f'color: {COLOURS["text_secondary"]}; margin: 0;">'
            f'No injury flags set — all squads assumed fully fit.'
            f'</p></div>',
            unsafe_allow_html=True,
        )
    else:
        # Group flags by team for cleaner display
        teams_with_flags: Dict[str, List[Dict]] = {}
        for f in flags:
            team = f["team_name"]
            if team not in teams_with_flags:
                teams_with_flags[team] = []
            teams_with_flags[team].append(f)

        for team_name, team_flags in sorted(teams_with_flags.items()):
            # Team header with total impact
            total_impact = sum(
                f["impact_rating"] for f in team_flags
                if f["status"] in ("out", "suspended")
            )
            impact_colour = (
                COLOURS["red"] if total_impact >= 0.7
                else COLOURS["yellow"] if total_impact >= 0.3
                else COLOURS["text_secondary"]
            )
            st.markdown(
                f'<div style="margin-top: 8px; padding: 4px 0;">'
                f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                f'font-weight: 600; color: {COLOURS["text"]};">{team_name}</span>'
                f' <span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                f'color: {impact_colour};">impact: {total_impact:.1f}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            for f in team_flags:
                # Status colour coding
                status_colour = {
                    "out": COLOURS["red"],
                    "suspended": COLOURS["red"],
                    "doubt": COLOURS["yellow"],
                }.get(f["status"], COLOURS["text_secondary"])

                # Impact bar (visual indicator)
                bar_width = int(f["impact_rating"] * 100)
                bar_colour = (
                    COLOURS["red"] if f["impact_rating"] >= 0.7
                    else COLOURS["yellow"] if f["impact_rating"] >= 0.4
                    else COLOURS["text_secondary"]
                )

                flag_cols = st.columns([3, 1, 1, 1, 1])
                with flag_cols[0]:
                    st.markdown(
                        f'<div style="padding: 4px 0;">'
                        f'<span style="font-family: Inter, sans-serif; font-size: 13px; '
                        f'color: {COLOURS["text"]};">{f["player_name"]}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                with flag_cols[1]:
                    st.markdown(
                        f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                        f'color: {status_colour}; text-transform: uppercase;">{f["status"]}</span>',
                        unsafe_allow_html=True,
                    )
                with flag_cols[2]:
                    st.markdown(
                        f'<div style="padding: 4px 0;">'
                        f'<div style="background: {COLOURS["border"]}; border-radius: 3px; '
                        f'height: 8px; width: 100%; overflow: hidden;">'
                        f'<div style="background: {bar_colour}; width: {bar_width}%; '
                        f'height: 100%; border-radius: 3px;"></div></div>'
                        f'<span style="font-family: JetBrains Mono, monospace; font-size: 11px; '
                        f'color: {bar_colour};">{f["impact_rating"]:.1f}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                with flag_cols[3]:
                    st.markdown(
                        f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
                        f'color: {COLOURS["text_secondary"]};">{f["estimated_return"]}</span>',
                        unsafe_allow_html=True,
                    )
                with flag_cols[4]:
                    if st.button(
                        "Remove",
                        key=f"remove_injury_{f['id']}",
                        type="secondary",
                    ):
                        if delete_injury_flag(f["id"]):
                            st.toast(
                                f"Removed {f['player_name']}",
                                icon="✅",
                            )
                            st.rerun()

    st.divider()

    # ==================================================================
    # Section 5: User Management (owner only)
    # ==================================================================
    # AC5: Only visible to users with role='owner'
    if user_data["role"] == "owner":
        st.markdown(
            '<div class="bv-section-header">User Management</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<p style="font-family: Inter, sans-serif; font-size: 13px; '
            f'color: {COLOURS["text_secondary"]}; margin-bottom: 12px;">'
            f'Manage users who can access the BetVector dashboard. '
            f'Viewers see the same predictions but track their own bankroll.'
            f'</p>',
            unsafe_allow_html=True,
        )

        # --- Current users table ---
        all_users = load_all_users()

        for u in all_users:
            u_cols = st.columns([2, 2, 1, 1, 1])
            with u_cols[0]:
                name_colour = COLOURS["text"] if u["is_active"] else COLOURS["text_secondary"]
                st.markdown(
                    f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                    f'color: {name_colour};">{u["name"]}</span>',
                    unsafe_allow_html=True,
                )
            with u_cols[1]:
                st.markdown(
                    f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                    f'color: {COLOURS["text_secondary"]};">{u["email"]}</span>',
                    unsafe_allow_html=True,
                )
            with u_cols[2]:
                role_colour = COLOURS["purple"] if u["role"] == "owner" else COLOURS["blue"]
                st.markdown(
                    f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                    f'color: {role_colour};">{u["role"]}</span>',
                    unsafe_allow_html=True,
                )
            with u_cols[3]:
                active_colour = COLOURS["green"] if u["is_active"] else COLOURS["red"]
                active_label = "Active" if u["is_active"] else "Inactive"
                st.markdown(
                    f'<span style="font-family: JetBrains Mono, monospace; font-size: 12px; '
                    f'color: {active_colour};">{active_label}</span>',
                    unsafe_allow_html=True,
                )
            with u_cols[4]:
                # Owner cannot be deactivated; viewers can be toggled
                if u["role"] != "owner":
                    if u["is_active"]:
                        if st.button("Deactivate", key=f"deactivate_{u['id']}", type="secondary"):
                            if deactivate_user(u["id"]):
                                st.toast(f"Deactivated {u['name']}", icon="✅")
                                st.rerun()
                    else:
                        if st.button("Reactivate", key=f"reactivate_{u['id']}", type="secondary"):
                            if reactivate_user(u["id"]):
                                st.toast(f"Reactivated {u['name']}", icon="✅")
                                st.rerun()

        st.divider()

        # --- Invite User form ---
        # AC6: "Invite User" creates a new user with role='viewer'
        st.markdown(
            f'<p style="font-family: Inter, sans-serif; font-size: 14px; '
            f'font-weight: 600; color: {COLOURS["text"]}; margin-bottom: 8px;">'
            f'Invite New User</p>',
            unsafe_allow_html=True,
        )

        invite_cols = st.columns([2, 2, 1])
        with invite_cols[0]:
            invite_name = st.text_input(
                "Name",
                placeholder="Friend's name",
                key="invite_name",
                label_visibility="collapsed",
            )
        with invite_cols[1]:
            invite_email = st.text_input(
                "Email",
                placeholder="friend@email.com",
                key="invite_email",
                label_visibility="collapsed",
            )
        with invite_cols[2]:
            invite_clicked = st.button(
                "Invite User",
                key="invite_btn",
                type="primary",
                use_container_width=True,
            )

        if invite_clicked:
            if not invite_name or not invite_email:
                st.warning("Please enter both a name and email address.")
            else:
                new_id = create_viewer_user(invite_name.strip(), invite_email.strip())
                if new_id:
                    st.success(
                        f"Invited **{invite_name}** (ID: {new_id}) as a viewer. "
                        f"They can access the dashboard with their own bankroll."
                    )
                    st.rerun()
                else:
                    st.error(
                        "Failed to create user. The email may already be in use."
                    )
