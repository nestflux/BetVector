"""
BetVector — Onboarding Flow (E10-04)
======================================
Five-step wizard that guides new users through initial configuration.
Displayed only when the user hasn't completed onboarding (has_onboarded=0).

Steps (from MP §3 Flow 6):
1. Bankroll — "What's your starting bankroll?"
2. Staking — "How do you want to calculate stakes?"
3. Edge Threshold — minimum edge slider
4. Leagues — select which leagues to follow
5. Notifications — email address + morning/evening/weekly toggles

On completing step 5, sets has_onboarded=1 and redirects to Today's Picks.

Master Plan refs: MP §3 Flow 6 (First-Time Setup), MP §8 Design System
"""

from datetime import datetime

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
    "blue": "#58A6FF",
    "purple": "#BC8CFF",
}

# Staking method options with explanations (from MP §3 Flow 6)
STAKING_OPTIONS = [
    (
        "flat",
        "Flat Stakes (recommended for beginners)",
        "Bet 2% of your bankroll on every qualifying bet. Simple and safe.",
    ),
    (
        "percentage",
        "Percentage",
        "Bet a fixed percentage of your current bankroll. "
        "Adjusts automatically as your bankroll changes.",
    ),
    (
        "kelly",
        "Kelly Criterion",
        "Mathematically optimal staking based on your edge. "
        "Advanced — only recommended after 500+ bets with good calibration.",
    ),
]


# ============================================================================
# Data Helpers
# ============================================================================

def load_onboarding_user(user_id: int = 1) -> dict | None:
    """Load the user being onboarded."""
    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            return None
        return {
            "id": user.id,
            "name": user.name,
            "starting_bankroll": user.starting_bankroll,
            "staking_method": user.staking_method,
            "stake_percentage": user.stake_percentage,
            "kelly_fraction": user.kelly_fraction,
            "edge_threshold": user.edge_threshold,
            "email": user.email or "",
        }


def load_available_leagues() -> list[dict]:
    """Load all leagues from the database."""
    with get_session() as session:
        leagues = session.query(League).order_by(League.name).all()
        return [
            {
                "id": lg.id,
                "name": lg.name,
                "short_name": lg.short_name,
                "is_active": bool(lg.is_active),
            }
            for lg in leagues
        ]


def save_onboarding_settings(user_id: int, settings: dict) -> bool:
    """Persist all onboarding settings to the users table in one transaction."""
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user:
                return False

            user.starting_bankroll = settings.get(
                "starting_bankroll", user.starting_bankroll
            )
            user.current_bankroll = settings.get(
                "starting_bankroll", user.current_bankroll
            )
            user.staking_method = settings.get(
                "staking_method", user.staking_method
            )
            user.stake_percentage = settings.get(
                "stake_percentage", user.stake_percentage
            )
            user.kelly_fraction = settings.get(
                "kelly_fraction", user.kelly_fraction
            )
            user.edge_threshold = settings.get(
                "edge_threshold", user.edge_threshold
            )
            if settings.get("email"):
                user.email = settings["email"]
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


def save_league_selections(selections: dict[int, bool]) -> None:
    """Enable/disable leagues based on onboarding selections."""
    try:
        with get_session() as session:
            for league_id, is_active in selections.items():
                league = session.get(League, league_id)
                if league:
                    league.is_active = 1 if is_active else 0
            session.commit()
    except Exception:
        pass


def complete_onboarding(user_id: int) -> bool:
    """Set has_onboarded=1 for the user, marking onboarding as complete."""
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user:
                return False
            user.has_onboarded = 1
            user.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


# ============================================================================
# Progress Indicator
# ============================================================================

def render_progress(current_step: int, total_steps: int = 5) -> None:
    """Render a progress bar with step label.

    Shows "Step X of 5" and a visual progress indicator.
    """
    progress = current_step / total_steps
    st.markdown(
        f'<div style="text-align: center; margin-bottom: 8px;">'
        f'<span style="font-family: JetBrains Mono, monospace; font-size: 14px; '
        f'color: {COLOURS["blue"]};">Step {current_step} of {total_steps}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.progress(progress)


# ============================================================================
# Step Renderers
# ============================================================================

def render_step_1_bankroll() -> None:
    """Step 1 — Bankroll: 'What's your starting bankroll?'"""
    st.markdown(
        f'<div class="bv-section-header">What\'s your starting bankroll?</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 14px; '
        f'color: {COLOURS["text_secondary"]}; margin-bottom: 16px;">'
        f'This is the total amount you\'re setting aside for betting. '
        f'BetVector will calculate stakes as a percentage of this amount.</p>',
        unsafe_allow_html=True,
    )

    bankroll = st.number_input(
        "Starting Bankroll (£)",
        min_value=50.0,
        max_value=100000.0,
        value=st.session_state.get("ob_bankroll", 500.0),
        step=50.0,
        key="ob_bankroll_input",
    )
    st.session_state["ob_bankroll"] = bankroll


def render_step_2_staking() -> None:
    """Step 2 — Staking: 'How do you want to calculate stakes?'"""
    st.markdown(
        f'<div class="bv-section-header">How do you want to calculate stakes?</div>',
        unsafe_allow_html=True,
    )

    current_method = st.session_state.get("ob_staking_method", "flat")
    current_idx = next(
        (i for i, opt in enumerate(STAKING_OPTIONS) if opt[0] == current_method), 0
    )

    labels = [opt[1] for opt in STAKING_OPTIONS]
    selected_label = st.radio(
        "Staking Method",
        options=labels,
        index=current_idx,
        key="ob_staking_radio",
        label_visibility="collapsed",
    )
    selected_idx = labels.index(selected_label)
    selected_key = STAKING_OPTIONS[selected_idx][0]
    explanation = STAKING_OPTIONS[selected_idx][2]

    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 13px; '
        f'color: {COLOURS["text_secondary"]}; margin-top: -4px;">{explanation}</p>',
        unsafe_allow_html=True,
    )

    st.session_state["ob_staking_method"] = selected_key

    # Show stake percentage or Kelly fraction based on method
    if selected_key in ("flat", "percentage"):
        pct = st.slider(
            "Stake Percentage",
            min_value=1,
            max_value=10,
            value=int(st.session_state.get("ob_stake_pct", 2)),
            step=1,
            format="%d%%",
            help="Percentage of your bankroll to stake on each bet.",
            key="ob_stake_pct_slider",
        )
        st.session_state["ob_stake_pct"] = pct
    elif selected_key == "kelly":
        kelly = st.slider(
            "Kelly Fraction",
            min_value=10,
            max_value=100,
            value=int(st.session_state.get("ob_kelly", 25)),
            step=5,
            format="%d%%",
            help="Fraction of full Kelly. 25% (quarter-Kelly) is recommended.",
            key="ob_kelly_slider",
        )
        st.session_state["ob_kelly"] = kelly


def render_step_3_edge() -> None:
    """Step 3 — Edge Threshold: minimum edge slider."""
    st.markdown(
        f'<div class="bv-section-header">Set your edge threshold</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 14px; '
        f'color: {COLOURS["text_secondary"]}; margin-bottom: 16px;">'
        f'BetVector only flags a bet when the model\'s probability exceeds '
        f'the bookmaker\'s implied probability by at least this amount. '
        f'Higher = fewer but stronger picks.</p>',
        unsafe_allow_html=True,
    )

    edge = st.slider(
        "Edge Threshold",
        min_value=1,
        max_value=15,
        value=int(st.session_state.get("ob_edge", 5)),
        step=1,
        format="%d%%",
        key="ob_edge_slider",
    )
    st.session_state["ob_edge"] = edge


def render_step_4_leagues() -> None:
    """Step 4 — Leagues: checkboxes for available leagues."""
    st.markdown(
        f'<div class="bv-section-header">Choose your leagues</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 14px; '
        f'color: {COLOURS["text_secondary"]}; margin-bottom: 16px;">'
        f'You can add more leagues later. We recommend starting with 1–2.</p>',
        unsafe_allow_html=True,
    )

    leagues = load_available_leagues()
    if not leagues:
        st.info("No leagues configured yet. You can add them in Settings later.")
        return

    # Initialise league selections in session state
    if "ob_leagues" not in st.session_state:
        st.session_state["ob_leagues"] = {
            lg["id"]: lg["is_active"] for lg in leagues
        }

    for lg in leagues:
        checked = st.checkbox(
            f'{lg["name"]} ({lg["short_name"]})',
            value=st.session_state["ob_leagues"].get(lg["id"], False),
            key=f'ob_league_{lg["id"]}',
        )
        st.session_state["ob_leagues"][lg["id"]] = checked


def render_step_5_notifications() -> None:
    """Step 5 — Notifications: email address + toggles."""
    st.markdown(
        f'<div class="bv-section-header">Set up notifications</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 14px; '
        f'color: {COLOURS["text_secondary"]}; margin-bottom: 16px;">'
        f'Get daily picks and results delivered to your inbox.</p>',
        unsafe_allow_html=True,
    )

    email = st.text_input(
        "Email Address",
        value=st.session_state.get("ob_email", ""),
        placeholder="your@email.com",
        key="ob_email_input",
    )
    st.session_state["ob_email"] = email

    notif_cols = st.columns(3)
    with notif_cols[0]:
        st.toggle(
            "Morning Picks",
            value=True,
            key="ob_notif_morning",
            help="Daily email with today's value bets (06:00 UTC).",
        )
    with notif_cols[1]:
        st.toggle(
            "Evening Review",
            value=True,
            key="ob_notif_evening",
            help="Daily email with results and P&L (22:00 UTC).",
        )
    with notif_cols[2]:
        st.toggle(
            "Weekly Summary",
            value=True,
            key="ob_notif_weekly",
            help="Weekly performance summary (Sunday 20:00 UTC).",
        )


# ============================================================================
# Page Layout — Wizard Controller
# ============================================================================

# Map step numbers to renderers
STEP_RENDERERS = {
    1: render_step_1_bankroll,
    2: render_step_2_staking,
    3: render_step_3_edge,
    4: render_step_4_leagues,
    5: render_step_5_notifications,
}

STEP_TITLES = {
    1: "Bankroll",
    2: "Staking Method",
    3: "Edge Threshold",
    4: "Leagues",
    5: "Notifications",
}


def render_onboarding() -> None:
    """Render the onboarding wizard.

    Called from dashboard.py when the user hasn't completed onboarding.
    Manages step navigation and final completion.
    """
    # Welcome header
    st.markdown(
        '<div class="bv-page-title">Welcome to BetVector</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 16px; '
        f'color: {COLOURS["text_secondary"]};">'
        f'Let\'s get your system configured.</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    # Load user data for defaults on first visit
    user_data = load_onboarding_user()
    if not user_data:
        st.error("No user account found. Please run the setup pipeline first.")
        return

    # Initialise step and defaults in session state
    if "ob_step" not in st.session_state:
        st.session_state["ob_step"] = 1
        st.session_state["ob_bankroll"] = user_data["starting_bankroll"]
        st.session_state["ob_staking_method"] = user_data["staking_method"]
        st.session_state["ob_stake_pct"] = int(user_data["stake_percentage"] * 100)
        st.session_state["ob_kelly"] = int(user_data["kelly_fraction"] * 100)
        st.session_state["ob_edge"] = int(user_data["edge_threshold"] * 100)
        st.session_state["ob_email"] = user_data["email"]

    step = st.session_state["ob_step"]

    # Progress indicator
    render_progress(step)
    st.divider()

    # Render current step
    STEP_RENDERERS[step]()

    st.divider()

    # Navigation buttons
    btn_cols = st.columns([1, 1, 2, 1])
    with btn_cols[0]:
        if step > 1:
            if st.button("← Back", key="ob_back", use_container_width=True):
                st.session_state["ob_step"] = step - 1
                st.rerun()

    with btn_cols[3]:
        if step < 5:
            if st.button("Next →", key="ob_next", type="primary", use_container_width=True):
                st.session_state["ob_step"] = step + 1
                st.rerun()
        else:
            # Final step — "Start BetVector" button
            if st.button(
                "Start BetVector 🚀",
                key="ob_complete",
                type="primary",
                use_container_width=True,
            ):
                # Gather all settings from session state
                settings = {
                    "starting_bankroll": st.session_state.get("ob_bankroll", 500.0),
                    "staking_method": st.session_state.get("ob_staking_method", "flat"),
                    "stake_percentage": st.session_state.get("ob_stake_pct", 2) / 100.0,
                    "kelly_fraction": st.session_state.get("ob_kelly", 25) / 100.0,
                    "edge_threshold": st.session_state.get("ob_edge", 5) / 100.0,
                    "email": st.session_state.get("ob_email", ""),
                }

                # Save all settings to DB
                save_onboarding_settings(user_data["id"], settings)

                # Save league selections
                league_selections = st.session_state.get("ob_leagues", {})
                if league_selections:
                    save_league_selections(league_selections)

                # Mark onboarding complete
                complete_onboarding(user_data["id"])

                # Clear onboarding session state
                for key in list(st.session_state.keys()):
                    if key.startswith("ob_"):
                        del st.session_state[key]

                # Redirect to Today's Picks
                st.success("You're all set! Redirecting to Today's Picks...")
                st.rerun()
