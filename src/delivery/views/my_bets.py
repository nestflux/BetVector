"""
BetVector — My Bets Page (E35-01, E35-02)
==========================================
Combined bet slip + manual entry form.

E35-01: Manual bet entry form — log any bet directly from the dashboard.
E35-02: Bet slip table above the form — view, edit, and void logged bets.

Design:
- Bet slip (top): summary strip → status filter → paginated table with
  inline edit/void actions for pending bets.
- Entry form (bottom): match selector → market → selection → bookmaker →
  odds → stake → "Log Bet" submit.
- model_prob and edge stored as 0.0 sentinels for manual bets (no schema
  migration needed; stake_method="manual" identifies them in display code).

Master Plan refs: MP §6 Schema (bet_log table), MP §8 Design System
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

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
_AUTO_SELECTION: Dict[str, str] = {
    "Over 2.5": "Over",
    "Under 2.5": "Under",
    "BTTS Yes": "Yes",
    "BTTS No": "No",
}

# Common bookmakers shown as quick suggestions.
_BOOKMAKERS = ["Pinnacle", "Bet365", "FanDuel", "DraftKings", "BetMGM", "Caesars", "Other"]

# Rows displayed per page in the bet slip table.
_ROWS_PER_PAGE = 20

# Status badge colours (pill style).
_STATUS_COLOURS = {
    "pending": "#D29922",   # amber
    "won":     "#3FB950",   # green
    "lost":    "#F85149",   # red
    "void":    "#8B949E",   # grey
    "half_won":  "#3FB950",
    "half_lost": "#F85149",
}


# ============================================================================
# Data Functions — Bet Slip (E35-02)
# ============================================================================

def load_user_bets(
    user_id: int,
    status_filter: str = "All",
    days_back: int = 90,
) -> List[Dict]:
    """Load user_placed BetLog rows for the logged-in user.

    Parameters
    ----------
    user_id : int
    status_filter : str
        "All" (default) or one of: "Pending", "Won", "Lost", "Void".
        Mapped to lowercase for the DB query.
    days_back : int
        How many days of history to load (default 90 days).

    Returns
    -------
    list of dict
        Ordered by date DESC, created_at DESC.  Each dict includes all
        fields needed to render the bet slip table and edit mini-forms.
    """
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    try:
        with get_session() as session:
            q = (
                session.query(BetLog)
                .filter(
                    BetLog.user_id == user_id,
                    BetLog.bet_type == "user_placed",
                    BetLog.date >= cutoff,
                )
                .order_by(BetLog.date.desc(), BetLog.created_at.desc())
            )
            # Apply optional status filter
            if status_filter != "All":
                q = q.filter(BetLog.status == status_filter.lower())

            bets = q.all()
            return [
                {
                    "id": b.id,
                    "date": b.date,
                    "home_team": b.home_team,
                    "away_team": b.away_team,
                    "league": b.league,
                    "market_type": b.market_type,
                    "selection": b.selection,
                    "bookmaker": b.bookmaker,
                    # Both raw odds fields preserved for CLV / edit-form display.
                    "odds_at_detection": b.odds_at_detection,
                    "odds_at_placement": b.odds_at_placement,
                    # Convenience: best available odds for display (placement wins).
                    "odds": b.odds_at_placement or b.odds_at_detection,
                    "stake": b.stake,
                    "status": b.status,
                    # BetLog has no separate 'result' column; status (won/lost/void)
                    # carries this information per MP §6 schema.
                    "pnl": b.pnl or 0.0,
                    # Estimated return for pending bets: (odds - 1) × stake.
                    # Explicit parentheses prevent operator-precedence pitfall:
                    #   'a or b - 1' parses as 'a or (b - 1)', not '(a or b) - 1'.
                    "est_return": round(
                        ((b.odds_at_placement or b.odds_at_detection) - 1) * b.stake, 2
                    )
                    if b.status == "pending"
                    else None,
                }
                for b in bets
            ]
    except Exception:
        return []


def load_summary_metrics(user_id: int) -> Dict[str, Any]:
    """Compute summary strip metrics for the bet slip header.

    Returns
    -------
    dict with keys:
        open_today (int): pending bets with today's date
        pnl_today (float): settled pnl for bets with today's date
        pnl_week (float): settled pnl for the last 7 days
        pnl_alltime (float): all settled pnl
    """
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    try:
        with get_session() as session:
            user_bets = (
                session.query(BetLog)
                .filter(
                    BetLog.user_id == user_id,
                    BetLog.bet_type == "user_placed",
                )
                .all()
            )
            open_today = sum(
                1 for b in user_bets if b.date == today and b.status == "pending"
            )
            pnl_today = sum(
                (b.pnl or 0.0)
                for b in user_bets
                if b.date == today and b.status not in ("pending", "void")
            )
            pnl_week = sum(
                (b.pnl or 0.0)
                for b in user_bets
                if b.date >= week_ago and b.status not in ("pending", "void")
            )
            pnl_alltime = sum(
                (b.pnl or 0.0)
                for b in user_bets
                if b.status not in ("pending", "void")
            )
            return {
                "open_today": open_today,
                "pnl_today": round(pnl_today, 2),
                "pnl_week": round(pnl_week, 2),
                "pnl_alltime": round(pnl_alltime, 2),
            }
    except Exception:
        return {"open_today": 0, "pnl_today": 0.0, "pnl_week": 0.0, "pnl_alltime": 0.0}


def update_bet(
    bet_id: int,
    user_id: int,
    stake: Optional[float] = None,
    odds_at_placement: Optional[float] = None,
    bookmaker: Optional[str] = None,
    selection: Optional[str] = None,
) -> bool:
    """Update editable fields on a pending user_placed bet.

    Only pending bets the requesting user owns can be edited.  market_type
    and match_id cannot be changed — log a new bet if those are wrong.

    Parameters
    ----------
    bet_id : int
    user_id : int
        Guards against editing another user's bet.
    stake, odds_at_placement, bookmaker, selection : optional
        Only supplied fields are updated.

    Returns
    -------
    bool
        True on success, False if bet not found, not pending, or DB error.
    """
    try:
        with get_session() as session:
            bet = (
                session.query(BetLog)
                .filter(
                    BetLog.id == bet_id,
                    BetLog.user_id == user_id,
                    BetLog.bet_type == "user_placed",
                    BetLog.status == "pending",
                )
                .first()
            )
            if not bet:
                return False

            if stake is not None:
                bet.stake = stake
            if odds_at_placement is not None:
                bet.odds_at_placement = odds_at_placement
                # Keep odds_at_detection unchanged (it was the original odds).
                # Recalculate implied_prob from the updated placement odds.
                bet.implied_prob = round(1.0 / odds_at_placement, 4)
            if bookmaker is not None:
                bet.bookmaker = bookmaker.strip()
            if selection is not None:
                bet.selection = selection.strip()

            bet.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


def void_bet(bet_id: int, user_id: int) -> bool:
    """Void a user_placed bet regardless of its current status.

    Voided bets have pnl=0.0 and are excluded from ROI calculations in
    the Performance Tracker (it filters status NOT IN ('pending', 'void')
    for P&L metrics).

    Parameters
    ----------
    bet_id : int
    user_id : int
        Guards against voiding another user's bet.

    Returns
    -------
    bool
        True on success, False if bet not found or DB error.
    """
    try:
        with get_session() as session:
            bet = (
                session.query(BetLog)
                .filter(
                    BetLog.id == bet_id,
                    BetLog.user_id == user_id,
                    BetLog.bet_type == "user_placed",
                )
                .first()
            )
            if not bet:
                return False
            bet.status = "void"
            bet.pnl = 0.0
            bet.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


# ============================================================================
# Data Functions — Entry Form (E35-01)
# ============================================================================

def load_upcoming_fixtures(days: int = 7) -> List[Dict]:
    """Load scheduled matches from today through the next N days.

    Parameters
    ----------
    days : int
        How many days ahead to include (default 7).

    Returns
    -------
    list of dict sorted by date then kickoff_time.
    Each dict: id, date, kickoff_time, home_team, away_team,
    league_id, league_short, display.
    """
    today_str = date.today().isoformat()
    cutoff_str = (date.today() + timedelta(days=days)).isoformat()

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

            return [
                {
                    "id": match.id,
                    "date": match.date,
                    "kickoff_time": match.kickoff_time or "TBC",
                    "home_team": home.name,
                    "away_team": away.name,
                    "league_id": match.league_id,
                    "league_short": league.short_name,
                    "display": (
                        f"{home.name} vs {away.name} "
                        f"— {match.kickoff_time or 'TBC'} ({match.date})"
                    ),
                }
                for match, home, away, league in rows
            ]
    except Exception:
        return []


def get_default_stake(user_id: int) -> float:
    """Return a sensible default stake pre-filled in the entry form.

    flat / percentage: stake_percentage × current_bankroll
    kelly: kelly_fraction × current_bankroll × 0.25 (conservative estimate)
    Falls back to $20 if user cannot be loaded.
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
                return max(1.0, round(br * (user.kelly_fraction or 0.25) * 0.05, 2))
    except Exception:
        return 20.0


def check_duplicate_bet(
    user_id: int, match_id: int, market_type: str, selection: str,
) -> bool:
    """Return True if user already has a pending bet for this market today.

    Prevents accidental double-logging on the same match/market/selection.
    """
    today_str = date.today().isoformat()
    try:
        with get_session() as session:
            return (
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
            ) is not None
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

    model_prob and edge are stored as 0.0 sentinels (bet_log NOT NULL
    constraints prevent NULL).  stake_method="manual" flags the row so
    all display and analytics code can exclude model metrics gracefully.

    Returns new BetLog.id or None on failure.
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
                model_prob=0.0,   # Sentinel — no model involved; display shows "—"
                edge=0.0,         # Sentinel — no edge estimate; display shows "—"
                bookmaker=bookmaker.strip(),
                odds_at_detection=odds,  # Equals placement odds for manual bets
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
# UI Helpers
# ============================================================================

def _status_badge(status: str) -> str:
    """Return an inline HTML pill badge for a bet status."""
    colour = _STATUS_COLOURS.get(status, COLOURS["text_secondary"])
    label = status.replace("_", " ").title()
    return (
        f'<span style="background: {colour}22; border: 1px solid {colour}; '
        f'color: {colour}; font-family: JetBrains Mono, monospace; '
        f'font-size: 11px; font-weight: 600; padding: 2px 8px; '
        f'border-radius: 10px; white-space: nowrap;">{label}</span>'
    )


def _pnl_colour(value: float) -> str:
    """Return a design-system colour for a P&L number."""
    if value > 0:
        return COLOURS["green"]
    if value < 0:
        return COLOURS["red"]
    return COLOURS["text_secondary"]


def _metric_tile(label: str, value: str, colour: str) -> str:
    """Return HTML for a summary strip metric tile."""
    return (
        f'<div style="background: {COLOURS["surface"]}; border: 1px solid '
        f'{COLOURS["border"]}; border-radius: 8px; padding: 12px 16px;">'
        f'<div style="font-family: Inter, sans-serif; font-size: 11px; '
        f'font-weight: 600; color: {COLOURS["text_secondary"]}; '
        f'text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">'
        f'{label}</div>'
        f'<div style="font-family: JetBrains Mono, monospace; font-size: 20px; '
        f'font-weight: 700; color: {colour};">{value}</div>'
        f'</div>'
    )


# ============================================================================
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">My Bets</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Track, edit, and void your manually logged bets</p>',
    unsafe_allow_html=True,
)
st.divider()

user_id = get_session_user_id()

# ============================================================================
# Section 1 — Bet Slip (E35-02)
# ============================================================================

st.markdown(
    '<div class="bv-section-header">Bet Slip</div>',
    unsafe_allow_html=True,
)

# ---- Summary strip ----
metrics = load_summary_metrics(user_id)
m1, m2, m3, m4 = st.columns(4)

with m1:
    st.markdown(
        _metric_tile("Open Today", str(metrics["open_today"]), COLOURS["blue"]),
        unsafe_allow_html=True,
    )
with m2:
    pnl_today = metrics["pnl_today"]
    st.markdown(
        _metric_tile(
            "Today's P&L",
            f'{"+" if pnl_today >= 0 else ""}${pnl_today:.2f}',
            _pnl_colour(pnl_today),
        ),
        unsafe_allow_html=True,
    )
with m3:
    pnl_week = metrics["pnl_week"]
    st.markdown(
        _metric_tile(
            "Week P&L",
            f'{"+" if pnl_week >= 0 else ""}${pnl_week:.2f}',
            _pnl_colour(pnl_week),
        ),
        unsafe_allow_html=True,
    )
with m4:
    pnl_all = metrics["pnl_alltime"]
    st.markdown(
        _metric_tile(
            "All-Time P&L",
            f'{"+" if pnl_all >= 0 else ""}${pnl_all:.2f}',
            _pnl_colour(pnl_all),
        ),
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# ---- Status filter tabs ----
status_options = ["All", "Pending", "Won", "Lost", "Void"]
selected_status = st.radio(
    "Filter by status",
    options=status_options,
    horizontal=True,
    key="bet_slip_filter",
    label_visibility="collapsed",
)

# ---- Load bets ----
bets = load_user_bets(user_id, status_filter=selected_status, days_back=90)

st.markdown(
    f'<p style="font-family: Inter, sans-serif; font-size: 12px; '
    f'color: {COLOURS["text_secondary"]}; margin: 4px 0 12px 0;">'
    f'{len(bets)} bet(s) — last 90 days</p>',
    unsafe_allow_html=True,
)

if not bets:
    st.markdown(
        '<div class="bv-empty-state">'
        'No bets logged yet. Use the form below to record your first bet.'
        '</div>',
        unsafe_allow_html=True,
    )
else:
    # ---- Pagination ----
    total_pages = max(1, (len(bets) + _ROWS_PER_PAGE - 1) // _ROWS_PER_PAGE)

    if "my_bets_page" not in st.session_state:
        st.session_state["my_bets_page"] = 1

    # Reset to page 1 when filter changes (use filter as key check)
    filter_key = f"slip_filter_{selected_status}"
    if st.session_state.get("_last_slip_filter") != selected_status:
        st.session_state["my_bets_page"] = 1
        st.session_state["_last_slip_filter"] = selected_status

    current_page = min(st.session_state["my_bets_page"], total_pages)
    page_start = (current_page - 1) * _ROWS_PER_PAGE
    page_bets = bets[page_start: page_start + _ROWS_PER_PAGE]

    # ---- Table header ----
    col_widths = [1, 2.5, 1.2, 1.5, 1.2, 0.8, 0.8, 1.2, 1, 1.8]
    header_cols = st.columns(col_widths)
    header_style = (
        f'font-family: Inter, sans-serif; font-size: 11px; font-weight: 600; '
        f'color: {COLOURS["text_secondary"]}; text-transform: uppercase; letter-spacing: 0.4px;'
    )
    headers = ["Date", "Match", "Market", "Selection", "Bookmaker",
               "Odds", "Stake", "Return/P&L", "Status", "Actions"]
    for col, hdr in zip(header_cols, headers):
        with col:
            st.markdown(f'<span style="{header_style}">{hdr}</span>', unsafe_allow_html=True)

    st.markdown(
        f'<hr style="border-color: {COLOURS["border"]}; margin: 4px 0 8px 0;">',
        unsafe_allow_html=True,
    )

    # ---- Table rows ----
    for bet in page_bets:
        is_pending = (bet["status"] == "pending")

        # Return/P&L display
        if is_pending and bet["est_return"] is not None:
            return_label = f'Est. +${bet["est_return"]:.2f}'
            return_colour = COLOURS["text_secondary"]
        else:
            pnl_val = bet["pnl"]
            return_label = f'{"+" if pnl_val >= 0 else ""}${pnl_val:.2f}'
            return_colour = _pnl_colour(pnl_val)

        # Shorten team names for narrow columns (max 15 chars per team)
        home_short = bet["home_team"][:13] + "…" if len(bet["home_team"]) > 14 else bet["home_team"]
        away_short = bet["away_team"][:13] + "…" if len(bet["away_team"]) > 14 else bet["away_team"]

        row_cols = st.columns(col_widths)
        with row_cols[0]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 12px; color: {COLOURS["text_secondary"]};">'
                f'{bet["date"][-5:]}</span>',  # MM-DD display
                unsafe_allow_html=True,
            )
        with row_cols[1]:
            st.markdown(
                f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text"]};">{home_short} vs {away_short}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[2]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 11px; color: {COLOURS["blue"]};">{bet["market_type"]}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[3]:
            st.markdown(
                f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text"]};">{bet["selection"]}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[4]:
            st.markdown(
                f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text_secondary"]};">{bet["bookmaker"]}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[5]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 12px; color: {COLOURS["text"]};">{bet["odds"]:.2f}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[6]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 12px; color: {COLOURS["text"]};">${bet["stake"]:.2f}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[7]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 12px; color: {return_colour};">{return_label}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[8]:
            st.markdown(_status_badge(bet["status"]), unsafe_allow_html=True)

        with row_cols[9]:
            if is_pending:
                edit_col, void_col = st.columns(2)
                with edit_col:
                    edit_clicked = st.button(
                        "✏️",
                        key=f"edit_btn_{bet['id']}",
                        help="Edit this bet",
                        use_container_width=True,
                    )
                with void_col:
                    void_clicked = st.button(
                        "🚫",
                        key=f"void_btn_{bet['id']}",
                        help="Void this bet",
                        use_container_width=True,
                    )

                # ---- Inline edit mini-form ----
                if edit_clicked:
                    # Toggle edit panel in session state
                    edit_key = f"edit_open_{bet['id']}"
                    st.session_state[edit_key] = not st.session_state.get(edit_key, False)

                edit_open = st.session_state.get(f"edit_open_{bet['id']}", False)
                if edit_open:
                    with st.expander(f"Edit Bet #{bet['id']}", expanded=True):
                        ef1, ef2, ef3, ef4 = st.columns(4)
                        with ef1:
                            new_stake = st.number_input(
                                "Stake ($)",
                                value=float(bet["stake"]),
                                min_value=0.01,
                                step=1.0,
                                format="%.2f",
                                key=f"edit_stake_{bet['id']}",
                            )
                        with ef2:
                            # Pre-fill with placement odds (the odds the user actually
                            # got); falls back to detection odds if not set.
                            edit_odds_default = float(
                                bet["odds_at_placement"] or bet["odds_at_detection"]
                            )
                            new_odds = st.number_input(
                                "Odds",
                                value=edit_odds_default,
                                min_value=1.01,
                                step=0.05,
                                format="%.2f",
                                key=f"edit_odds_{bet['id']}",
                            )
                        with ef3:
                            new_bookmaker = st.text_input(
                                "Bookmaker",
                                value=bet["bookmaker"],
                                key=f"edit_bk_{bet['id']}",
                            )
                        with ef4:
                            new_selection = st.text_input(
                                "Selection",
                                value=bet["selection"],
                                key=f"edit_sel_{bet['id']}",
                            )
                        if st.button(
                            "Save Changes",
                            key=f"edit_save_{bet['id']}",
                            type="primary",
                        ):
                            ok = update_bet(
                                bet_id=bet["id"],
                                user_id=user_id,
                                stake=new_stake,
                                odds_at_placement=new_odds,
                                bookmaker=new_bookmaker or None,
                                selection=new_selection or None,
                            )
                            if ok:
                                st.toast(f"Bet #{bet['id']} updated ✓", icon="✅")
                                st.session_state[f"edit_open_{bet['id']}"] = False
                                st.rerun()
                            else:
                                st.error("Update failed — only pending bets can be edited.")

                # ---- Void confirmation ----
                if void_clicked:
                    void_key = f"void_open_{bet['id']}"
                    st.session_state[void_key] = not st.session_state.get(void_key, False)

                void_open = st.session_state.get(f"void_open_{bet['id']}", False)
                if void_open:
                    void_confirm = st.checkbox(
                        f"Confirm void bet #{bet['id']} — this cannot be undone",
                        key=f"void_confirm_{bet['id']}",
                    )
                    if st.button(
                        "Void Bet",
                        key=f"void_exec_{bet['id']}",
                        type="secondary",
                        disabled=not void_confirm,
                    ):
                        ok = void_bet(bet_id=bet["id"], user_id=user_id)
                        if ok:
                            st.toast(f"Bet #{bet['id']} voided", icon="🚫")
                            st.session_state[f"void_open_{bet['id']}"] = False
                            st.rerun()
                        else:
                            st.error("Void failed — please try again.")

        st.markdown(
            f'<div style="border-bottom: 1px solid {COLOURS["border"]}; '
            f'margin: 2px 0 8px 0;"></div>',
            unsafe_allow_html=True,
        )

    # ---- Pagination controls ----
    if total_pages > 1:
        st.markdown("<br>", unsafe_allow_html=True)
        pg_cols = st.columns([1, 2, 1])
        with pg_cols[0]:
            if current_page > 1:
                if st.button("← Previous", key="bets_prev"):
                    st.session_state["my_bets_page"] = current_page - 1
                    st.rerun()
        with pg_cols[1]:
            st.markdown(
                f'<div style="text-align: center; font-family: Inter, sans-serif; '
                f'font-size: 13px; color: {COLOURS["text_secondary"]}; padding-top: 6px;">'
                f'Page {current_page} of {total_pages}</div>',
                unsafe_allow_html=True,
            )
        with pg_cols[2]:
            if current_page < total_pages:
                if st.button("Next →", key="bets_next"):
                    st.session_state["my_bets_page"] = current_page + 1
                    st.rerun()

st.divider()

# ============================================================================
# Section 2 — Log a New Bet (E35-01 entry form)
# ============================================================================

st.markdown(
    '<div class="bv-section-header">Log a Bet</div>',
    unsafe_allow_html=True,
)

# ---- Load upcoming fixtures ----
fixtures = load_upcoming_fixtures(days=7)

if not fixtures:
    st.markdown(
        f'<div style="font-family: Inter, sans-serif; font-size: 13px; '
        f'color: {COLOURS["text_secondary"]}; padding: 16px 0;">'
        f'No scheduled fixtures found in the next 7 days. '
        f'Check back once the pipeline has loaded upcoming matches.</div>',
        unsafe_allow_html=True,
    )
else:
    fixture_map: Dict[str, Dict] = {f["display"]: f for f in fixtures}
    fixture_labels = list(fixture_map.keys())

    # Form version key for full reset after successful submit
    if "bet_form_key" not in st.session_state:
        st.session_state["bet_form_key"] = 0

    form_ver = st.session_state["bet_form_key"]

    # ---- Market selector (outside form for live reactivity) ----
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

    # ---- Selection field (dynamic based on market) ----
    if selected_market == "1X2":
        selected_selection = st.selectbox(
            "Selection",
            options=["Home", "Draw", "Away"],
            key=f"bet_sel_1x2_{form_ver}",
        )
    elif selected_market in _AUTO_SELECTION:
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
        selected_selection = st.text_input(
            "Selection",
            placeholder="e.g. Chelsea -0.5" if selected_market == "Asian Handicap"
            else "Describe your selection",
            key=f"bet_sel_text_{form_ver}",
        )

    # ---- Remaining fields inside form (auto-reset on submit) ----
    default_stake = get_default_stake(user_id)

    with st.form(f"bet_entry_form_{form_ver}", clear_on_submit=True):
        form_col1, form_col2, form_col3 = st.columns(3)

        with form_col1:
            bookmaker_choice = st.selectbox(
                "Bookmaker",
                options=_BOOKMAKERS,
                key=f"bet_bk_choice_{form_ver}",
            )
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
                help="Decimal odds. 2.50 = 5/2 fractional = +150 American.",
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
            )

        implied = round(1.0 / odds * 100, 1)
        st.markdown(
            f'<div style="font-family: Inter, sans-serif; font-size: 12px; '
            f'color: {COLOURS["text_secondary"]}; margin-top: 8px;">'
            f'Implied probability: '
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

    # ---- Handle submission ----
    if submitted:
        bookmaker_name = (
            custom_bookmaker.strip() if bookmaker_choice == "Other" else bookmaker_choice
        )
        if not bookmaker_name:
            st.warning("Please enter a bookmaker name.")
        elif selected_market in ("Asian Handicap", "Other") and not selected_selection.strip():
            st.warning("Please enter a selection description.")
        else:
            effective_selection = selected_selection.strip() if selected_selection else ""

            if check_duplicate_bet(
                user_id, selected_fixture["id"], selected_market, effective_selection
            ):
                st.warning(
                    f"⚠️ You already have a pending bet logged for "
                    f"**{selected_fixture['home_team']} vs {selected_fixture['away_team']}** "
                    f"· {selected_market} · {effective_selection} today."
                )
            else:
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
                    st.toast(
                        f"✅ Bet logged — "
                        f"{selected_fixture['home_team']} vs {selected_fixture['away_team']} "
                        f"· {selected_market} · {effective_selection} "
                        f"· ${stake:.2f} @ {odds:.2f}",
                        icon="🎯",
                    )
                    # Increment form_key to reset all keyed widgets
                    st.session_state["bet_form_key"] += 1
                    st.rerun()
                else:
                    st.error("Failed to log the bet. Please try again.")
