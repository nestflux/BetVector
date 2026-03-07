"""
BetVector — My Bets Page (E35-01, E35-02, E35-04, E35-05)
==========================================================
Combined bet slip + fixture browser + slip builder.

E35-01: Manual bet entry form (original form — superseded by E35-04).
E35-02: Bet slip table above the form — view, edit, and void logged bets.
E35-04: Fixture browser replaces the old selectbox form.  Users browse
        upcoming fixtures and click market odds buttons to add selections
        to a pending slip stored in st.session_state["pending_slip"].
E35-05: Slip builder panel.  Selections accumulate as cards; user sets
        a global stake (pre-filled from bankroll settings) with per-row
        override, picks a bookmaker, then clicks "Log All Bets" to write
        all selections to the database at once.

Design:
- Bet slip (top): summary strip → status filter → paginated table with
  inline edit/void for pending bets.
- Fixture browser (middle): date tabs → fixtures grouped by date →
  clickable market odds buttons (toggle add/remove from slip).
- Slip panel (bottom): queued selections → global stake + per-row
  override → "Log All Bets" confirm → history refreshes.

Master Plan refs: MP §6 Schema (bet_log, odds tables), MP §8 Design System
"""

from datetime import date, datetime, timedelta
from itertools import groupby
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import aliased

from src.auth import get_session_user_id
from src.database.db import get_session
from src.database.models import BetLog, League, Match, Odds, Team, User


# ============================================================================
# Design tokens (MP §8)
# ============================================================================

COLOURS = {
    "bg":             "#0D1117",
    "surface":        "#161B22",
    "surface_hover":  "#1C2333",
    "border":         "#30363D",
    "text":           "#E6EDF3",
    "text_secondary": "#8B949E",
    "text_muted":     "#484F58",
    "green":          "#3FB950",
    "red":            "#F85149",
    "yellow":         "#D29922",
    "blue":           "#58A6FF",
    "purple":         "#BC8CFF",
}

# Markets shown in the legacy entry form (kept for backward compat with
# load_upcoming_fixtures / log_manual_bet callers).
_MARKETS = [
    "1X2", "Over 2.5", "Under 2.5", "BTTS Yes", "BTTS No",
    "Asian Handicap", "Other",
]
_AUTO_SELECTION: Dict[str, str] = {
    "Over 2.5": "Over", "Under 2.5": "Under",
    "BTTS Yes": "Yes",  "BTTS No":   "No",
}
_BOOKMAKERS = [
    "Pinnacle", "Bet365", "FanDuel", "DraftKings",
    "BetMGM", "Caesars", "Other",
]

# Markets shown in the fixture browser (E35-04).
# Each tuple: (db_market_type, db_selection,
#              betlog_market_type, betlog_selection, button_label)
#   db_*     — values stored in the Odds table
#   betlog_* — values stored in BetLog (human-readable)
#   label    — short label on the odds button
_BROWSER_MARKETS: List[Tuple[str, str, str, str, str]] = [
    ("1X2",  "home",  "1X2",       "Home",  "Home"),
    ("1X2",  "draw",  "1X2",       "Draw",  "Draw"),
    ("1X2",  "away",  "1X2",       "Away",  "Away"),
    ("OU25", "over",  "Over 2.5",  "Over",  "O2.5"),
    ("OU25", "under", "Under 2.5", "Under", "U2.5"),
    ("BTTS", "yes",   "BTTS Yes",  "Yes",   "BTTS Y"),
    ("BTTS", "no",    "BTTS No",   "No",    "BTTS N"),
]

# Rows per page in the bet slip table.
_ROWS_PER_PAGE = 20

# Status badge colours (pill style).
_STATUS_COLOURS = {
    "pending":   "#D29922",
    "won":       "#3FB950",
    "lost":      "#F85149",
    "void":      "#8B949E",
    "half_won":  "#3FB950",
    "half_lost": "#F85149",
}


# ============================================================================
# Helpers — slip key
# ============================================================================

def _slip_key(match_id: int, db_market: str, db_selection: str) -> str:
    """Unique identifier for a slip entry.

    Uses the DB-layer market/selection values (e.g. '1X2'/'home') rather
    than the BetLog display values so the key is deterministic regardless
    of how the display label changes.
    """
    return f"{match_id}__{db_market}__{db_selection}"


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
    days_back : int
        How many days of history to load (default 90 days).

    Returns
    -------
    list of dict ordered by date DESC, created_at DESC.
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
            if status_filter != "All":
                q = q.filter(BetLog.status == status_filter.lower())

            bets = q.all()
            return [
                {
                    "id":               b.id,
                    "date":             b.date,
                    "home_team":        b.home_team,
                    "away_team":        b.away_team,
                    "league":           b.league,
                    "market_type":      b.market_type,
                    "selection":        b.selection,
                    "bookmaker":        b.bookmaker,
                    "odds_at_detection":  b.odds_at_detection,
                    "odds_at_placement":  b.odds_at_placement,
                    # Convenience: placement odds win if available.
                    "odds": b.odds_at_placement or b.odds_at_detection,
                    "stake":  b.stake,
                    "status": b.status,
                    "pnl":    b.pnl or 0.0,
                    # Estimated return for pending bets: (odds − 1) × stake.
                    # Explicit parentheses prevent operator-precedence pitfall.
                    "est_return": round(
                        ((b.odds_at_placement or b.odds_at_detection) - 1)
                        * b.stake,
                        2,
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
        open_today (int): pending bets placed today
        pnl_today (float): settled P&L for today
        pnl_week (float): settled P&L for the last 7 days
        pnl_alltime (float): all settled P&L
    """
    today  = date.today().isoformat()
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
            open_today  = sum(
                1 for b in user_bets
                if b.date == today and b.status == "pending"
            )
            pnl_today   = sum(
                (b.pnl or 0.0)
                for b in user_bets
                if b.date == today and b.status not in ("pending", "void")
            )
            pnl_week    = sum(
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
                "open_today":  open_today,
                "pnl_today":   round(pnl_today,   2),
                "pnl_week":    round(pnl_week,     2),
                "pnl_alltime": round(pnl_alltime,  2),
            }
    except Exception:
        return {"open_today": 0, "pnl_today": 0.0,
                "pnl_week": 0.0, "pnl_alltime": 0.0}


def update_bet(
    bet_id: int,
    user_id: int,
    stake: Optional[float] = None,
    odds_at_placement: Optional[float] = None,
    bookmaker: Optional[str] = None,
    selection: Optional[str] = None,
) -> bool:
    """Update editable fields on a pending user_placed bet.

    Only pending bets owned by the requesting user can be edited.
    match_id and market_type cannot be changed — log a new bet instead.

    Returns
    -------
    bool  True on success, False if not found / not pending / DB error.
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

    Voided bets have pnl=0.0 and are excluded from ROI calculations
    (Performance Tracker filters status NOT IN ('pending', 'void')).

    Returns
    -------
    bool  True on success, False if not found or DB error.
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
            bet.status     = "void"
            bet.pnl        = 0.0
            bet.updated_at = datetime.utcnow().isoformat()
            session.commit()
        return True
    except Exception:
        return False


# ============================================================================
# Data Functions — Entry Form + Slip Builder
# ============================================================================

def load_upcoming_fixtures(days: int = 7) -> List[Dict]:
    """Load scheduled matches from today through the next N days.

    Legacy helper retained for backward compatibility.  The fixture browser
    (E35-04) uses load_fixtures_with_odds() instead.

    Returns
    -------
    list of dict sorted by date then kickoff_time.
    """
    today_str  = date.today().isoformat()
    cutoff_str = (date.today() + timedelta(days=days)).isoformat()
    try:
        with get_session() as session:
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
                    "id":          match.id,
                    "date":        match.date,
                    "kickoff_time": match.kickoff_time or "TBC",
                    "home_team":   home.name,
                    "away_team":   away.name,
                    "league_id":   match.league_id,
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


def load_fixtures_with_odds(date_from: str, date_to: str) -> List[Dict]:
    """Load scheduled matches with the most recent available odds.

    Fetches all scheduled fixtures in [date_from, date_to] and joins the
    latest odds for seven markets: 1X2 home/draw/away, OU25 over/under,
    BTTS yes/no.  Any market with no odds row returns None — handled
    gracefully by showing '—' on the button and prompting manual entry.

    Temporal integrity: captured_at is always in the past (odds are
    fetched before kickoff), so no future-data risk here.

    Parameters
    ----------
    date_from, date_to : str
        Inclusive date range in YYYY-MM-DD format.

    Returns
    -------
    list of dict sorted by date ASC, kickoff_time ASC.
    Each dict: id, date, kickoff_time, home_team, away_team,
    league_short, league_name, odds (dict keyed by (db_mkt, db_sel)).
    """
    try:
        with get_session() as session:
            HomeTeam = aliased(Team, name="ht")  # noqa: N806
            AwayTeam = aliased(Team, name="at")  # noqa: N806

            match_rows = (
                session.query(Match, HomeTeam, AwayTeam, League)
                .join(HomeTeam, Match.home_team_id == HomeTeam.id)
                .join(AwayTeam, Match.away_team_id == AwayTeam.id)
                .join(League, Match.league_id == League.id)
                .filter(
                    Match.status == "scheduled",
                    Match.date >= date_from,
                    Match.date <= date_to,
                )
                .order_by(Match.date.asc(), Match.kickoff_time.asc())
                .all()
            )
            if not match_rows:
                return []

            match_ids = [m.id for m, _, _, _ in match_rows]

            # Subquery: latest captured_at per (match, market, selection).
            # Using MAX so we get the most recently fetched odds, not
            # opening odds or stale historical prices.
            latest_sq = (
                session.query(
                    Odds.match_id,
                    Odds.market_type,
                    Odds.selection,
                    sqlfunc.max(Odds.captured_at).label("latest"),
                )
                .filter(Odds.match_id.in_(match_ids))
                .group_by(Odds.match_id, Odds.market_type, Odds.selection)
                .subquery()
            )

            odds_rows = (
                session.query(Odds)
                .join(
                    latest_sq,
                    (Odds.match_id    == latest_sq.c.match_id)
                    & (Odds.market_type == latest_sq.c.market_type)
                    & (Odds.selection   == latest_sq.c.selection)
                    & (Odds.captured_at == latest_sq.c.latest),
                )
                .filter(Odds.match_id.in_(match_ids))
                .all()
            )

            # Build lookup: {match_id: {(market_type, selection): decimal}}
            odds_lut: Dict[int, Dict] = {}
            for o in odds_rows:
                odds_lut.setdefault(o.match_id, {})[
                    (o.market_type, o.selection)
                ] = o.odds_decimal

            result = []
            for match, home, away, league in match_rows:
                mo = odds_lut.get(match.id, {})
                result.append({
                    "id":           match.id,
                    "date":         match.date,
                    "kickoff_time": match.kickoff_time or "TBC",
                    "home_team":    home.name,
                    "away_team":    away.name,
                    "league_short": league.short_name,
                    "league_name":  league.name,
                    "odds": {
                        ("1X2",  "home"):  mo.get(("1X2",  "home")),
                        ("1X2",  "draw"):  mo.get(("1X2",  "draw")),
                        ("1X2",  "away"):  mo.get(("1X2",  "away")),
                        ("OU25", "over"):  mo.get(("OU25", "over")),
                        ("OU25", "under"): mo.get(("OU25", "under")),
                        ("BTTS", "yes"):   mo.get(("BTTS", "yes")),
                        ("BTTS", "no"):    mo.get(("BTTS", "no")),
                    },
                })
            return result
    except Exception:
        return []


def get_default_stake(user_id: int) -> float:
    """Return a sensible default stake pre-filled in the slip builder.

    flat / percentage: stake_percentage × current_bankroll
    kelly: kelly_fraction × current_bankroll × 0.05 (conservative)
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
    """Return True if user already has a pending bet for this market today."""
    today_str = date.today().isoformat()
    try:
        with get_session() as session:
            return (
                session.query(BetLog)
                .filter(
                    BetLog.user_id    == user_id,
                    BetLog.match_id   == match_id,
                    BetLog.market_type == market_type,
                    BetLog.selection   == selection,
                    BetLog.date        == today_str,
                    BetLog.bet_type    == "user_placed",
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
    """Write a single manual user_placed BetLog row.

    model_prob and edge are stored as 0.0 sentinels — stake_method="manual"
    identifies them so display code can hide model-specific columns
    gracefully.

    Returns new BetLog.id or None on failure.
    """
    implied_prob = round(1.0 / odds, 4)
    now_iso = datetime.utcnow().isoformat()
    try:
        with get_session() as session:
            bet = BetLog(
                user_id           = user_id,
                match_id          = match["id"],
                date              = match["date"],
                league            = match["league_short"],
                home_team         = match["home_team"],
                away_team         = match["away_team"],
                market_type       = market_type,
                selection         = selection,
                model_prob        = 0.0,   # sentinel — no model involved
                edge              = 0.0,   # sentinel — no edge estimate
                bookmaker         = bookmaker.strip(),
                odds_at_detection = odds,  # equals placement for manual bets
                odds_at_placement = odds,
                implied_prob      = implied_prob,
                stake             = stake,
                stake_method      = "manual",
                bet_type          = "user_placed",
                status            = "pending",
                created_at        = now_iso,
                updated_at        = now_iso,
            )
            session.add(bet)
            session.commit()
            session.refresh(bet)
            return bet.id
    except Exception:
        return None


def log_multiple_bets(
    user_id: int,
    selections: List[Dict],
) -> Tuple[List[int], List[str]]:
    """Write multiple user_placed BetLog rows from the slip builder (E35-05).

    Each selection dict must contain:
        match_id, date, home_team, away_team, league,
        market_type, selection, odds, stake, bookmaker.

    Runs check_duplicate_bet before each write — skips duplicates without
    raising.  One failure does not block the remaining selections.

    Returns
    -------
    tuple[list[int], list[str]]
        (logged_ids, skipped_reasons)
        logged_ids:       BetLog IDs successfully created.
        skipped_reasons:  Human-readable strings for each skipped bet.
    """
    logged:  List[int] = []
    skipped: List[str] = []

    for sel in selections:
        match_label = (
            f"{sel['home_team']} vs {sel['away_team']} · "
            f"{sel['market_type']} · {sel['selection']}"
        )
        # Duplicate guard — same match/market/selection already logged today.
        if check_duplicate_bet(
            user_id, sel["match_id"], sel["market_type"], sel["selection"],
        ):
            skipped.append(f"{match_label} — already logged today")
            continue

        odds = sel.get("odds")
        if not odds or odds < 1.01:
            skipped.append(f"{match_label} — invalid odds ({odds}), enter manually")
            continue

        stake = sel.get("stake", 0.0)
        if not stake or stake <= 0:
            skipped.append(f"{match_label} — invalid stake ({stake})")
            continue

        bet_id = log_manual_bet(
            user_id    = user_id,
            match      = {
                "id":           sel["match_id"],
                "date":         sel["date"],
                "home_team":    sel["home_team"],
                "away_team":    sel["away_team"],
                "league_short": sel["league"],
            },
            market_type = sel["market_type"],
            selection   = sel["selection"],
            bookmaker   = sel.get("bookmaker", "Unknown"),
            odds        = odds,
            stake       = stake,
        )
        if bet_id:
            logged.append(bet_id)
        else:
            skipped.append(f"{match_label} — database write failed")

    return logged, skipped


# ============================================================================
# UI Helpers
# ============================================================================

def _status_badge(status: str) -> str:
    """Return an inline HTML pill badge for a bet status."""
    colour = _STATUS_COLOURS.get(status, COLOURS["text_secondary"])
    label  = status.replace("_", " ").title()
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
    '<p class="text-muted">Browse fixtures, build your slip, and track every bet</p>',
    unsafe_allow_html=True,
)
st.divider()

user_id = get_session_user_id()

# ============================================================================
# Section 1 — Bet Slip (E35-02)  ← unchanged
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
status_options  = ["All", "Pending", "Won", "Lost", "Void"]
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
        'No bets logged yet. Browse fixtures below and add to your slip.'
        '</div>',
        unsafe_allow_html=True,
    )
else:
    # ---- Pagination ----
    total_pages = max(1, (len(bets) + _ROWS_PER_PAGE - 1) // _ROWS_PER_PAGE)

    if "my_bets_page" not in st.session_state:
        st.session_state["my_bets_page"] = 1

    # Reset to page 1 on filter change
    if st.session_state.get("_last_slip_filter") != selected_status:
        st.session_state["my_bets_page"] = 1
        st.session_state["_last_slip_filter"] = selected_status

    current_page = min(st.session_state["my_bets_page"], total_pages)
    page_start   = (current_page - 1) * _ROWS_PER_PAGE
    page_bets    = bets[page_start: page_start + _ROWS_PER_PAGE]

    # ---- Table header ----
    col_widths   = [1, 2.5, 1.2, 1.5, 1.2, 0.8, 0.8, 1.2, 1, 1.8]
    header_cols  = st.columns(col_widths)
    header_style = (
        f'font-family: Inter, sans-serif; font-size: 11px; font-weight: 600; '
        f'color: {COLOURS["text_secondary"]}; text-transform: uppercase; '
        f'letter-spacing: 0.4px;'
    )
    headers = [
        "Date", "Match", "Market", "Selection", "Bookmaker",
        "Odds", "Stake", "Return/P&L", "Status", "Actions",
    ]
    for col, hdr in zip(header_cols, headers):
        with col:
            st.markdown(
                f'<span style="{header_style}">{hdr}</span>',
                unsafe_allow_html=True,
            )

    st.markdown(
        f'<hr style="border-color: {COLOURS["border"]}; margin: 4px 0 8px 0;">',
        unsafe_allow_html=True,
    )

    # ---- Table rows ----
    for bet in page_bets:
        is_pending = (bet["status"] == "pending")

        if is_pending and bet["est_return"] is not None:
            return_label  = f'Est. +${bet["est_return"]:.2f}'
            return_colour = COLOURS["text_secondary"]
        else:
            pnl_val       = bet["pnl"]
            return_label  = f'{"+" if pnl_val >= 0 else ""}${pnl_val:.2f}'
            return_colour = _pnl_colour(pnl_val)

        home_short = (
            bet["home_team"][:13] + "…"
            if len(bet["home_team"]) > 14 else bet["home_team"]
        )
        away_short = (
            bet["away_team"][:13] + "…"
            if len(bet["away_team"]) > 14 else bet["away_team"]
        )

        row_cols = st.columns(col_widths)
        with row_cols[0]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 12px; color: {COLOURS["text_secondary"]};">'
                f'{bet["date"][-5:]}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[1]:
            st.markdown(
                f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text"]};">'
                f'{home_short} vs {away_short}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[2]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 11px; color: {COLOURS["blue"]};">'
                f'{bet["market_type"]}</span>',
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
                f'font-size: 12px; color: {COLOURS["text"]};">'
                f'{bet["odds"]:.2f}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[6]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 12px; color: {COLOURS["text"]};">'
                f'${bet["stake"]:.2f}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[7]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 12px; color: {return_colour};">'
                f'{return_label}</span>',
                unsafe_allow_html=True,
            )
        with row_cols[8]:
            st.markdown(_status_badge(bet["status"]), unsafe_allow_html=True)

        with row_cols[9]:
            if is_pending:
                edit_col, void_col = st.columns(2)
                with edit_col:
                    edit_clicked = st.button(
                        "✏️", key=f"edit_btn_{bet['id']}",
                        help="Edit this bet", use_container_width=True,
                    )
                with void_col:
                    void_clicked = st.button(
                        "🚫", key=f"void_btn_{bet['id']}",
                        help="Void this bet", use_container_width=True,
                    )

                # ---- Inline edit mini-form ----
                if edit_clicked:
                    edit_key = f"edit_open_{bet['id']}"
                    st.session_state[edit_key] = not st.session_state.get(
                        edit_key, False,
                    )

                if st.session_state.get(f"edit_open_{bet['id']}", False):
                    with st.expander(f"Edit Bet #{bet['id']}", expanded=True):
                        ef1, ef2, ef3, ef4 = st.columns(4)
                        with ef1:
                            new_stake = st.number_input(
                                "Stake ($)", value=float(bet["stake"]),
                                min_value=0.01, step=1.0, format="%.2f",
                                key=f"edit_stake_{bet['id']}",
                            )
                        with ef2:
                            edit_odds_default = float(
                                bet["odds_at_placement"] or bet["odds_at_detection"]
                            )
                            new_odds = st.number_input(
                                "Odds", value=edit_odds_default,
                                min_value=1.01, step=0.05, format="%.2f",
                                key=f"edit_odds_{bet['id']}",
                            )
                        with ef3:
                            new_bookmaker = st.text_input(
                                "Bookmaker", value=bet["bookmaker"],
                                key=f"edit_bk_{bet['id']}",
                            )
                        with ef4:
                            new_selection = st.text_input(
                                "Selection", value=bet["selection"],
                                key=f"edit_sel_{bet['id']}",
                            )
                        if st.button(
                            "Save Changes",
                            key=f"edit_save_{bet['id']}",
                            type="primary",
                        ):
                            ok = update_bet(
                                bet_id=bet["id"], user_id=user_id,
                                stake=new_stake,
                                odds_at_placement=new_odds,
                                bookmaker=new_bookmaker or None,
                                selection=new_selection or None,
                            )
                            if ok:
                                st.toast(
                                    f"Bet #{bet['id']} updated ✓", icon="✅",
                                )
                                st.session_state[f"edit_open_{bet['id']}"] = False
                                st.rerun()
                            else:
                                st.error(
                                    "Update failed — only pending bets can be edited.",
                                )

                # ---- Void confirmation ----
                if void_clicked:
                    void_key = f"void_open_{bet['id']}"
                    st.session_state[void_key] = not st.session_state.get(
                        void_key, False,
                    )

                if st.session_state.get(f"void_open_{bet['id']}", False):
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
# Section 2 — Fixture Browser (E35-04)
# ============================================================================

st.markdown(
    '<div class="bv-section-header">Browse Fixtures</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">'
    'Click any odds button to add it to your slip · click again to remove'
    '</p>',
    unsafe_allow_html=True,
)

# Initialise pending slip dict in session state.
# Dict key: slip_key (str).  Value: bet metadata dict.
if "pending_slip" not in st.session_state:
    st.session_state["pending_slip"] = {}

# ---- Date window selector ----
today_str    = date.today().isoformat()
tomorrow_str = (date.today() + timedelta(days=1)).isoformat()
day3_str     = (date.today() + timedelta(days=2)).isoformat()
day6_str     = (date.today() + timedelta(days=6)).isoformat()

_DATE_WINDOWS = {
    "Today":       (today_str,    today_str),
    "Tomorrow":    (tomorrow_str, tomorrow_str),
    "Next 3 Days": (today_str,    day3_str),
    "Next 7 Days": (today_str,    day6_str),
}

selected_window = st.radio(
    "Date window",
    options=list(_DATE_WINDOWS.keys()),
    horizontal=True,
    key="browser_date_window",
    label_visibility="collapsed",
)
date_from, date_to = _DATE_WINDOWS.get(
    selected_window if selected_window in _DATE_WINDOWS else "Today",
    _DATE_WINDOWS["Today"],
)

# ---- Load fixtures ----
fixtures = load_fixtures_with_odds(date_from, date_to)

if not fixtures:
    st.markdown(
        '<div class="bv-empty-state">'
        'No scheduled fixtures found in this window. '
        'Check back once the pipeline has loaded upcoming matches.'
        '</div>',
        unsafe_allow_html=True,
    )
else:
    # CSS: compact monospace market buttons for the browser grid.
    st.markdown(
        f"""
        <style>
        /* Market odds buttons in the fixture browser */
        div[data-testid="column"] button[kind="secondary"] {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            padding: 3px 4px;
            min-height: 30px;
            line-height: 1.2;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ---- Render fixtures grouped by date ----
    # groupby requires the list to be sorted by date (already is from query).
    for fixture_date, day_iter in groupby(fixtures, key=lambda f: f["date"]):
        # Format date heading: "Saturday 8 Mar" (no leading zero on day).
        try:
            d_obj        = datetime.strptime(fixture_date, "%Y-%m-%d")
            date_heading = f"{d_obj.strftime('%A')} {d_obj.day} {d_obj.strftime('%b')}"
        except ValueError:
            date_heading = fixture_date

        st.markdown(
            f'<div style="font-family: Inter, sans-serif; font-size: 12px; '
            f'font-weight: 600; color: {COLOURS["text_secondary"]}; '
            f'text-transform: uppercase; letter-spacing: 0.6px; '
            f'margin: 20px 0 8px 0; padding-bottom: 4px; '
            f'border-bottom: 1px solid {COLOURS["border"]};">'
            f'{date_heading}</div>',
            unsafe_allow_html=True,
        )

        for fx in day_iter:
            match_id    = fx["id"]
            home_short  = fx["home_team"][:20]
            away_short  = fx["away_team"][:20]

            # Fixture header: league badge · match · kickoff
            st.markdown(
                f'<div style="display: flex; align-items: center; gap: 8px; '
                f'margin-bottom: 4px;">'
                f'<span style="font-family: Inter, sans-serif; font-size: 10px; '
                f'font-weight: 700; color: {COLOURS["blue"]}; '
                f'background: rgba(88,166,255,0.12); '
                f'border: 1px solid rgba(88,166,255,0.4); '
                f'border-radius: 4px; padding: 1px 6px; white-space: nowrap;">'
                f'{fx["league_short"]}</span>'
                f'<span style="font-family: Inter, sans-serif; font-size: 14px; '
                f'font-weight: 600; color: {COLOURS["text"]};">'
                f'{home_short} vs {away_short}</span>'
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 11px; color: {COLOURS["text_secondary"]};">'
                f'{fx["kickoff_time"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # ---- 7 market buttons ----
            btn_cols = st.columns(7)
            pending  = st.session_state["pending_slip"]

            for col, (db_mkt, db_sel, bl_mkt, bl_sel, label) in zip(
                btn_cols, _BROWSER_MARKETS,
            ):
                skey       = _slip_key(match_id, db_mkt, db_sel)
                is_sel     = skey in pending
                raw_odds   = fx["odds"].get((db_mkt, db_sel))
                odds_str   = f"{raw_odds:.2f}" if raw_odds is not None else "—"
                # ✓ prefix when selected — provides a clear visual signal even
                # without custom CSS; the monospace font aligns columns cleanly.
                btn_label  = f"{'✓ ' if is_sel else ''}{label}\n{odds_str}"
                help_text  = (
                    f"{'Remove from' if is_sel else 'Add to'} slip: "
                    f"{fx['home_team']} vs {fx['away_team']} · "
                    f"{bl_mkt} · {bl_sel}"
                )

                with col:
                    if st.button(
                        btn_label,
                        key=f"mbtn_{skey}",
                        use_container_width=True,
                        help=help_text,
                    ):
                        if is_sel:
                            # Toggle off — remove from slip
                            del st.session_state["pending_slip"][skey]
                            # Clean up per-row input state when removed
                            st.session_state.pop(f"slip_odds_{skey}",  None)
                            st.session_state.pop(f"slip_stake_{skey}", None)
                        else:
                            # Toggle on — add to slip
                            st.session_state["pending_slip"][skey] = {
                                "match_id":    match_id,
                                "date":        fx["date"],
                                "home_team":   fx["home_team"],
                                "away_team":   fx["away_team"],
                                "league":      fx["league_short"],
                                "market_type": bl_mkt,
                                "selection":   bl_sel,
                                "odds":        raw_odds,   # None if no odds in DB
                                "label":       label,
                                "slip_key":    skey,
                            }
                        st.rerun()

            # Subtle separator between fixtures
            st.markdown(
                f'<div style="height: 6px;"></div>',
                unsafe_allow_html=True,
            )

st.divider()

# ============================================================================
# Section 3 — Pending Slip Builder (E35-05)
# ============================================================================

pending_slip: Dict[str, Dict] = st.session_state.get("pending_slip", {})

if not pending_slip:
    st.markdown(
        '<div class="bv-empty-state" style="text-align: center;">'
        '🎯 Your slip is empty — click odds buttons above to add selections.'
        '</div>',
        unsafe_allow_html=True,
    )
else:
    n_sel = len(pending_slip)
    st.markdown(
        f'<div class="bv-section-header">Pending Slip ({n_sel} bet'
        f'{"s" if n_sel != 1 else ""})</div>',
        unsafe_allow_html=True,
    )

    # ---- Global controls: bookmaker + default stake ----
    default_stake = get_default_stake(user_id)
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 1.5, 3])

    with ctrl_col1:
        bk_choice = st.selectbox(
            "Bookmaker (applies to all)",
            options=_BOOKMAKERS,
            key="slip_bookmaker_choice",
            help="The bookmaker you're placing these bets with.",
        )
        if bk_choice == "Other":
            bk_choice = st.text_input(
                "Bookmaker name",
                placeholder="e.g. William Hill",
                key="slip_bookmaker_custom",
            )

    with ctrl_col2:
        global_stake = st.number_input(
            "Default Stake ($)",
            min_value=0.01,
            max_value=100_000.0,
            value=float(default_stake),
            step=1.0,
            format="%.2f",
            key="slip_global_stake",
            help=(
                "Default stake applied to all rows. "
                "Override per-row in the table below."
            ),
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ---- Slip rows table ----
    # Column widths: Date | Match | Market | Sel | Odds | Stake | Est Return | ×
    slip_col_w = [0.8, 2.8, 1.2, 1.0, 1.0, 1.0, 1.0, 0.5]
    hdr_cols   = st.columns(slip_col_w)
    slip_hdrs  = ["Date", "Match", "Market", "Selection", "Odds", "Stake ($)",
                  "Est. Return", ""]
    hdr_style  = (
        f'font-family: Inter, sans-serif; font-size: 11px; font-weight: 600; '
        f'color: {COLOURS["text_secondary"]}; text-transform: uppercase; '
        f'letter-spacing: 0.4px;'
    )
    for col, hdr in zip(hdr_cols, slip_hdrs):
        with col:
            st.markdown(
                f'<span style="{hdr_style}">{hdr}</span>',
                unsafe_allow_html=True,
            )
    st.markdown(
        f'<hr style="border-color: {COLOURS["border"]}; margin: 4px 0 6px 0;">',
        unsafe_allow_html=True,
    )

    total_stake  = 0.0
    total_return = 0.0

    for skey, sel in list(pending_slip.items()):
        row_cols = st.columns(slip_col_w)

        # --- Date cell ---
        with row_cols[0]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 12px; color: {COLOURS["text_secondary"]};">'
                f'{sel["date"][-5:]}</span>',
                unsafe_allow_html=True,
            )

        # --- Match cell ---
        with row_cols[1]:
            home_s = sel["home_team"][:16] + "…" if len(sel["home_team"]) > 17 else sel["home_team"]
            away_s = sel["away_team"][:16] + "…" if len(sel["away_team"]) > 17 else sel["away_team"]
            st.markdown(
                f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text"]};">'
                f'{home_s} vs {away_s}</span>',
                unsafe_allow_html=True,
            )

        # --- Market cell ---
        with row_cols[2]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 11px; color: {COLOURS["blue"]};">'
                f'{sel["market_type"]}</span>',
                unsafe_allow_html=True,
            )

        # --- Selection cell ---
        with row_cols[3]:
            st.markdown(
                f'<span style="font-family: Inter, sans-serif; font-size: 12px; '
                f'color: {COLOURS["text"]};">{sel["selection"]}</span>',
                unsafe_allow_html=True,
            )

        # --- Odds cell: editable (user may have got a different price) ---
        with row_cols[4]:
            row_odds_default = float(sel["odds"]) if sel["odds"] else 2.00
            row_odds = st.number_input(
                "Odds",
                min_value=1.01,
                max_value=1000.0,
                value=row_odds_default,
                step=0.05,
                format="%.2f",
                key=f"slip_odds_{skey}",
                label_visibility="collapsed",
                help=(
                    "Adjust if the odds moved between detection and placement."
                    if sel["odds"] else
                    "No odds found in DB — enter the price you got."
                ),
            )

        # --- Stake cell: editable per-row; defaults to global stake ---
        with row_cols[5]:
            row_stake = st.number_input(
                "Stake",
                min_value=0.01,
                max_value=100_000.0,
                value=float(
                    st.session_state.get(f"slip_stake_{skey}", global_stake)
                ),
                step=1.0,
                format="%.2f",
                key=f"slip_stake_{skey}",
                label_visibility="collapsed",
            )

        # --- Est. Return cell ---
        est_return = round((row_odds - 1) * row_stake, 2)
        total_stake  += row_stake
        total_return += est_return
        with row_cols[6]:
            st.markdown(
                f'<span style="font-family: JetBrains Mono, monospace; '
                f'font-size: 12px; color: {COLOURS["green"]};">'
                f'+${est_return:.2f}</span>',
                unsafe_allow_html=True,
            )

        # --- Remove button ---
        with row_cols[7]:
            if st.button("×", key=f"rm_{skey}", help="Remove from slip"):
                del st.session_state["pending_slip"][skey]
                st.session_state.pop(f"slip_odds_{skey}",  None)
                st.session_state.pop(f"slip_stake_{skey}", None)
                st.rerun()

        st.markdown(
            f'<div style="border-bottom: 1px solid {COLOURS["border"]}; '
            f'margin: 2px 0 6px 0;"></div>',
            unsafe_allow_html=True,
        )

    # ---- Totals row ----
    st.markdown(
        f'<div style="display: flex; gap: 24px; padding: 8px 0 16px 0; '
        f'font-family: JetBrains Mono, monospace; font-size: 13px;">'
        f'<span style="color: {COLOURS["text_secondary"]};">Total Stake: '
        f'<strong style="color: {COLOURS["text"]};">${total_stake:.2f}</strong></span>'
        f'<span style="color: {COLOURS["text_secondary"]};">Total Est. Return: '
        f'<strong style="color: {COLOURS["green"]};">+${total_return:.2f}</strong></span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Log All Bets button ----
    bookmaker_name = (
        st.session_state.get("slip_bookmaker_custom", "").strip()
        if bk_choice == "Other"
        else bk_choice
    )

    log_col, clear_col = st.columns([4, 1])
    with log_col:
        if st.button(
            f"🎯 Log All {n_sel} Bet{'s' if n_sel != 1 else ''}",
            type="primary",
            use_container_width=True,
            disabled=not bookmaker_name,
            help="Enter a bookmaker name above to enable." if not bookmaker_name else "",
        ):
            # Enrich each selection with per-row odds/stake from session state.
            enriched = []
            for skey, sel in st.session_state["pending_slip"].items():
                enriched.append({
                    **sel,
                    "odds":      st.session_state.get(f"slip_odds_{skey}",  sel["odds"]),
                    "stake":     st.session_state.get(f"slip_stake_{skey}", global_stake),
                    "bookmaker": bookmaker_name,
                })

            logged_ids, skipped_reasons = log_multiple_bets(user_id, enriched)

            if logged_ids:
                st.toast(
                    f"✅ {len(logged_ids)} bet{'s' if len(logged_ids) != 1 else ''} "
                    f"logged successfully",
                    icon="🎯",
                )
                # Clear slip and per-row state after successful log.
                for skey in list(st.session_state["pending_slip"].keys()):
                    st.session_state.pop(f"slip_odds_{skey}",  None)
                    st.session_state.pop(f"slip_stake_{skey}", None)
                st.session_state["pending_slip"] = {}
                st.rerun()

            if skipped_reasons:
                for reason in skipped_reasons:
                    st.warning(f"⚠️ Skipped: {reason}")

    with clear_col:
        if st.button("Clear Slip", key="clear_slip", use_container_width=True):
            for skey in list(st.session_state["pending_slip"].keys()):
                st.session_state.pop(f"slip_odds_{skey}",  None)
                st.session_state.pop(f"slip_stake_{skey}", None)
            st.session_state["pending_slip"] = {}
            st.rerun()
