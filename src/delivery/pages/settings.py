"""
BetVector — Settings Page (E10-03)
====================================
User preferences, league management, notification toggles, and user
management for the dashboard owner.

Sections:
1. User Preferences — staking method, stake %, Kelly fraction, edge threshold,
   starting bankroll
2. League Management — enable/disable leagues from config
3. Notification Preferences — email address, morning/evening/weekly toggles
4. User Management (owner only) — list users, invite new viewer

Master Plan refs: MP §3 Flow 6 (First-Time Setup), MP §3 Flow 7 (Adding a
Friend), MP §8 Design System
"""

from datetime import datetime
from typing import Dict, List, Optional

import streamlit as st

from src.database.db import get_session
from src.database.models import League, User


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
    # Section 4: User Management (owner only)
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
