"""
BetVector — My Bets Page (E35-01)
==================================
Manual bet entry form that lets users log any bet directly from the
dashboard — not just system picks.  A companion slip table (E35-02) will
sit above this form once implemented.

Design:
- Match selector populated from scheduled fixtures in the DB (today + 7 days)
- Market selector drives the Selection field dynamically (outside the form
  so reruns update the selection widget before the user submits)
- On submit: dedup check → write BetLog row → success toast → form reset
- model_prob and edge stored as 0.0 (sentinel) for manual bets — the display
  layer checks stake_method="manual" to show "—" rather than false 0% values.
  This avoids a schema migration on bet_log (model_prob/edge are NOT NULL).

Master Plan refs: MP §6 Schema (bet_log table), MP §8 Betting Engine
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import streamlit as st

from src.auth import get_session_user_id
from src.database.db import get_session
from src.database.models import BetLog, League, Match, Team, User


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

# Markets supported by the manual entry form.
# The selection field adapts to the chosen market.
_MARKETS = [
    "1X2",
    "Over 2.5",
    "Under 2.5",
    "BTTS Yes",
    "BTTS No",
    "Asian Handicap",
    "Other",
]

# Markets where the selection is pre-determined by the market name itself.
# e.g. "Over 2.5" always means selection = "Over".
_AUTO_SELECTION: Dict[str, str] = {
    "Over 2.5": "Over",
    "Under 2.5": "Under",
    "BTTS Yes": "Yes",
    "BTTS No": "No",
}

# Common bookmakers shown as quick suggestions.
_BOOKMAKERS = ["Pinnacle", "Bet365", "FanDuel", "DraftKings", "BetMGM", "Caesars", "Other"]


# ============================================================================
# Data Functions
# ============================================================================

def load_upcoming_fixtures(days: int = 7) -> List[Dict]:
    """Load scheduled matches from today through the next N days.

    Used to populate the match selector in the bet entry form.
    A 7-day window ensures the form always has options even when there are
    no matches today (e.g. international break mid-week gaps).

    Parameters
    ----------
    days : int
        How many days ahead to include (default 7).

    Returns
    -------
    list of dict
        Sorted by date, then kickoff_time. Each dict includes:
        id, date, kickoff_time, home_team, away_team, league_short, display.
        ``display`` is the human-readable label for the selectbox.
    """
    today_str = date.today().isoformat()
    cutoff_str = (date.today() + timedelta(days=days)).isoformat()

    # Use explicit Team aliases to join home and away separately — same pattern
    # as fixtures.py to avoid ambiguous join errors with the double Team FK.
    try:
        with get_session() as session:
            from sqlalchemy.orm import aliased
            HomeTeam = aliased(Team, name="home_team")  # noqa: N806
            AwayTeam = aliased(Team, name="away_team")  # noqa: N806

            rows = (
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

            fixtures = []
            for match, home, away, league in rows:
                kickoff = match.kickoff_time or "TBC"
                # Format: "Arsenal vs Chelsea — 20:00 (2026-03-08)"
                display = (
                    f"{home.name} vs {away.name} — {kickoff} ({match.date})"
                )
                fixtures.append({
                    "id": match.id,
                    "date": match.date,
                    "kickoff_time": kickoff,
                    "home_team": home.name,
                    "away_team": away.name,
                    "league_id": match.league_id,
                    "league_short": league.short_name,
                    "display": display,
                })
            return fixtures
    except Exception:
        return []


def get_default_stake(user_id: int) -> float:
    """Return a sensible default stake for the bet entry form.

    Reads the user's configured staking method and bankroll from the DB:
    - flat / percentage: stake_percentage × current_bankroll
    - kelly: kelly_fraction × current_bankroll × 0.25 (conservative estimate)

    Falls back to $20 if the user cannot be loaded.

    Parameters
    ----------
    user_id : int
        The logged-in user's database ID.

    Returns
    -------
    float
        Suggested stake in the user's currency, rounded to 2 decimal places.
    """
    try:
        with get_session() as session:
            user = session.get(User, user_id)
            if not user or not user.current_bankroll:
                return 20.0
            br = user.current_bankroll
            if user.staking_method in ("flat", "percentage"):
                return max(1.0, round(br * (user.stake_percentage or 0.02), 2))
            else:
                # Kelly — quarter-Kelly on a conservative edge estimate (~5%)
                return max(1.0, round(br * (user.kelly_fraction or 0.25) * 0.05, 2))
    except Exception:
        return 20.0


def check_duplicate_bet(
    user_id: int,
    match_id: int,
    market_type: str,
    selection: str,
) -> bool:
    """Return True if the user already has a pending bet for this exact market today.

    Prevents accidental double-logging of the same bet.  Checks:
    - Same user
    - Same match
    - Same market_type
    - Same selection
    - Same date (today)
    - bet_type = 'user_placed'

    Parameters
    ----------
    user_id : int
    match_id : int
    market_type : str
    selection : str

    Returns
    -------
    bool
        True = duplicate exists, False = safe to log.
    """
    today_str = date.today().isoformat()
    try:
        with get_session() as session:
            existing = (
                session.query(BetLog)
                .filter(
                    BetLog.user_id == user_id,
                    BetLog.match_id == match_id,
                    BetLog.market_type == market_type,
                    BetLog.selection == selection,
                    BetLog.date == today_str,
                    BetLog.bet_type == "user_placed",
                )
                .first()
            )
            return existing is not None
    except Exception:
        return False


def log_manual_bet(
    user_id: int,
    match: Dict,
    market_type: str,
    selection: str,
    bookmaker: str,
    odds: float,
    stake: float,
) -> Optional[int]:
    """Write a manual user_placed BetLog row.

    Unlike system picks, manual bets have no model probability or edge
    estimate.  We store sentinel values (0.0) for model_prob and edge
    because the bet_log table has NOT NULL constraints on those columns
    (set from the initial schema — a schema migration would be needed to
    allow NULL).  The stake_method="manual" flag signals to all display
    code that these are placeholder zeros, not real model values.

    Parameters
    ----------
    user_id : int
    match : dict
        Row dict from load_upcoming_fixtures().
    market_type : str
    selection : str
    bookmaker : str
    odds : float
        Decimal odds as entered by the user.
    stake : float
        Stake amount in the user's currency.

    Returns
    -------
    int or None
        New BetLog.id on success, None on failure.
    """
    implied_prob = round(1.0 / odds, 4)
    now_iso = datetime.utcnow().isoformat()

    try:
        with get_session() as session:
            bet = BetLog(
                user_id=user_id,
                match_id=match["id"],
                date=match["date"],
                league=match["league_short"],
                home_team=match["home_team"],
                away_team=match["away_team"],
                market_type=market_type,
                selection=selection,
                # No model involved — sentinel 0.0 values.
                # Display code checks stake_method="manual" to show "—".
                model_prob=0.0,
                edge=0.0,
                bookmaker=bookmaker.strip(),
                # For manual bets the detection and placement odds are identical
                # (we only know the odds the user actually bet at).
                odds_at_detection=odds,
                odds_at_placement=odds,
                implied_prob=implied_prob,
                stake=stake,
                stake_method="manual",
                bet_type="user_placed",
                status="pending",
                created_at=now_iso,
                updated_at=now_iso,
            )
            session.add(bet)
            session.commit()
            session.refresh(bet)
            return bet.id
    except Exception:
        return None


# ============================================================================
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">My Bets</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Log any bet you place — model picks and your own selections</p>',
    unsafe_allow_html=True,
)
st.divider()

user_id = get_session_user_id()

# ---- Load upcoming fixtures ----
fixtures = load_upcoming_fixtures(days=7)

if not fixtures:
    st.markdown(
        f'<div class="bv-empty-state">'
        f'No scheduled fixtures found in the next 7 days. '
        f'Check back once the pipeline has loaded upcoming matches.'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.stop()

# Build lookup: display label → fixture dict
fixture_map: Dict[str, Dict] = {f["display"]: f for f in fixtures}
fixture_labels = list(fixture_map.keys())

# ---- Section header ----
st.markdown(
    '<div class="bv-section-header">Log a Bet</div>',
    unsafe_allow_html=True,
)

# ============================================================================
# Step 1 — Market selector (OUTSIDE the form so selection field updates live)
# A form rerun counter lets us reset the market selector after a successful
# submit (incrementing the key forces Streamlit to create a fresh widget).
# ============================================================================

if "bet_form_key" not in st.session_state:
    st.session_state["bet_form_key"] = 0

form_ver = st.session_state["bet_form_key"]

col_match, col_market = st.columns([3, 2])

with col_match:
    selected_fixture_label = st.selectbox(
        "Match",
        options=fixture_labels,
        key=f"bet_match_{form_ver}",
        help="Matches from today through the next 7 days, ordered by kickoff time.",
    )

with col_market:
    selected_market = st.selectbox(
        "Market",
        options=_MARKETS,
        key=f"bet_market_{form_ver}",
        help="1X2 = match result. BTTS = both teams score.",
    )

selected_fixture = fixture_map[selected_fixture_label]

# ============================================================================
# Step 2 — Selection field (dynamic based on market, also outside the form)
# ============================================================================

if selected_market == "1X2":
    selected_selection = st.selectbox(
        "Selection",
        options=["Home", "Draw", "Away"],
        key=f"bet_sel_1x2_{form_ver}",
    )
elif selected_market in _AUTO_SELECTION:
    # Pre-determined by market name — show as read-only info
    auto_val = _AUTO_SELECTION[selected_market]
    st.markdown(
        f'<div style="font-family: Inter, sans-serif; font-size: 13px; '
        f'color: {COLOURS["text_secondary"]}; margin-bottom: 4px;">Selection</div>'
        f'<div style="font-family: JetBrains Mono, monospace; font-size: 14px; '
        f'color: {COLOURS["blue"]}; padding: 8px 0;">{auto_val}</div>',
        unsafe_allow_html=True,
    )
    selected_selection = auto_val
else:
    # Asian Handicap / Other — free text entry
    selected_selection = st.text_input(
        "Selection",
        placeholder="e.g. Chelsea -0.5" if selected_market == "Asian Handicap" else "Describe your selection",
        key=f"bet_sel_text_{form_ver}",
    )

# ============================================================================
# Step 3 — Remaining fields inside the form (bookmaker, odds, stake)
# clear_on_submit=True resets these widgets automatically after submit.
# ============================================================================

default_stake = get_default_stake(user_id)

with st.form(f"bet_entry_form_{form_ver}", clear_on_submit=True):
    form_col1, form_col2, form_col3 = st.columns(3)

    with form_col1:
        bookmaker_choice = st.selectbox(
            "Bookmaker",
            options=_BOOKMAKERS,
            key=f"bet_bk_choice_{form_ver}",
        )
        # If "Other" is selected, offer a free-text input inside the form
        custom_bookmaker = ""
        if bookmaker_choice == "Other":
            custom_bookmaker = st.text_input(
                "Bookmaker name",
                placeholder="e.g. William Hill",
                key=f"bet_bk_custom_{form_ver}",
            )

    with form_col2:
        odds = st.number_input(
            "Decimal Odds",
            min_value=1.01,
            max_value=1000.0,
            value=2.00,
            step=0.05,
            format="%.2f",
            key=f"bet_odds_{form_ver}",
            help="Decimal odds (European format). e.g. 2.50 = 5/2 fractional = +150 American.",
        )

    with form_col3:
        stake = st.number_input(
            "Stake ($)",
            min_value=0.01,
            max_value=100_000.0,
            value=float(default_stake),
            step=1.0,
            format="%.2f",
            key=f"bet_stake_{form_ver}",
            help="How much you are staking on this bet.",
        )

    # --- Implied probability preview (calculated live from odds) ---
    implied = round(1.0 / odds * 100, 1)
    st.markdown(
        f'<div style="font-family: Inter, sans-serif; font-size: 12px; '
        f'color: {COLOURS["text_secondary"]}; margin-top: 8px;">'
        f'Implied probability at these odds: '
        f'<span style="color: {COLOURS["blue"]}; font-family: JetBrains Mono, monospace;">'
        f'{implied}%</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    submitted = st.form_submit_button(
        "🎯 Log Bet",
        type="primary",
        use_container_width=True,
    )

# ============================================================================
# Handle form submission (outside the form block so rerun works correctly)
# ============================================================================

if submitted:
    # Resolve bookmaker name
    bookmaker_name = (
        custom_bookmaker.strip() if bookmaker_choice == "Other" else bookmaker_choice
    )

    # --- Input validation ---
    if not bookmaker_name:
        st.warning("Please enter a bookmaker name.")
    elif selected_market in ("Asian Handicap", "Other") and not selected_selection.strip():
        st.warning("Please enter a selection description.")
    else:
        effective_selection = selected_selection.strip() if selected_selection else ""

        # --- Duplicate check ---
        if check_duplicate_bet(
            user_id, selected_fixture["id"], selected_market, effective_selection
        ):
            st.warning(
                f"⚠️ You already have a pending bet logged for "
                f"**{selected_fixture['home_team']} vs {selected_fixture['away_team']}** "
                f"· {selected_market} · {effective_selection} today. "
                f"Check your bet slip to avoid double-counting."
            )
        else:
            # --- Write to database ---
            bet_id = log_manual_bet(
                user_id=user_id,
                match=selected_fixture,
                market_type=selected_market,
                selection=effective_selection,
                bookmaker=bookmaker_name,
                odds=odds,
                stake=stake,
            )

            if bet_id:
                # Success — show toast and reset form by bumping the version key
                st.toast(
                    f"✅ Bet logged — "
                    f"{selected_fixture['home_team']} vs {selected_fixture['away_team']} "
                    f"· {selected_market} · {effective_selection} "
                    f"· ${stake:.2f} @ {odds:.2f}",
                    icon="🎯",
                )
                # Increment form_key to reset all keyed widgets (match, market,
                # selection, bookmaker, odds, stake all use form_ver in their key)
                st.session_state["bet_form_key"] += 1
                st.rerun()
            else:
                st.error(
                    "Failed to log the bet. Please try again. "
                    "If the problem persists, check your database connection."
                )
