"""
BetVector — Bet Tracker (E6-03)
================================
Logs system picks and user-placed bets, resolves them when match results
arrive, and provides filtered bet history.

Dual Bet Tracking (MP §3, §6)
-------------------------------
BetVector maintains **two kinds of bet entries** for every value bet:

1. **system_pick** — Auto-logged whenever the value finder detects a bet
   worth taking.  Uses the recommended stake from the bankroll manager.
   This tracks what the *model* would have done, regardless of whether
   the user actually placed the bet.

2. **user_placed** — Logged when the user confirms they placed the bet
   with a real bookmaker.  Records the *actual* odds and stake they got
   (which may differ from the model's recommendation).

This separation lets us answer a critical question: "Am I underperforming
because the model is wrong, or because I'm not following it?"

Bet Resolution
--------------
When match results are scraped, ``resolve_bets(match_id)`` automatically:
  1. Determines the actual outcome for each pending bet
  2. Calculates PnL: won → stake × (odds - 1), lost → -stake
  3. Updates the user's ``current_bankroll`` in the users table
  4. Calculates CLV if closing odds are available

CLV (Closing Line Value)
--------------------------
CLV measures whether you got better odds than the final "closing line"
(the last available odds before kickoff).  If you bet at 2.10 and the
line closed at 1.95, you got positive CLV.  CLV is the single best
predictor of long-term profitability in sports betting — even more
reliable than short-term PnL results, which are dominated by variance.

  clv = (1 / closing_odds) - (1 / odds_at_placement)

A negative CLV value means you got better odds than the market closed at
(which is good — you "beat the closing line").

Master Plan refs: MP §3 Flow 5, MP §4 Bet Tracking, MP §6 bet_log table
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_

from src.betting.bankroll import BankrollManager
from src.betting.value_finder import ValueBetResult
from src.database.db import get_session
from src.database.models import BetLog, League, Match, Team, User, ValueBet

logger = logging.getLogger(__name__)

# Bankroll manager instance for stake calculations
_bankroll_manager = BankrollManager()


# ============================================================================
# Log System Picks
# ============================================================================

def log_system_picks(
    value_bets: List[ValueBetResult],
    user_id: int,
) -> Dict[str, int]:
    """Auto-log all value bets as system_pick entries in the bet_log.

    For each value bet, calculates the recommended stake using the user's
    staking method and current bankroll.  Every value bet the model
    identifies gets logged here — this is how we track model performance
    independently of whether the user actually placed the bets.

    Parameters
    ----------
    value_bets : list[ValueBetResult]
        Value bets from the value finder.
    user_id : int
        Database ID of the user.

    Returns
    -------
    dict
        Summary with keys: ``"new"``, ``"skipped"``, ``"total"``.
    """
    new_count = 0
    skipped_count = 0

    for vb in value_bets:
        with get_session() as session:
            # Get match details for the bet_log entry (needed before stake calc
            # so we can pass league short_name for PC-25-09 stake multiplier)
            match_info = _get_match_info(session, vb.match_id)
            if match_info is None:
                logger.warning(
                    "log_system_picks: Match %d not found — skipping",
                    vb.match_id,
                )
                skipped_count += 1
                continue

            # PC-25-09: Calculate stake with league for multiplier lookup
            stake_result = _bankroll_manager.calculate_stake(
                user_id=user_id,
                model_prob=vb.model_prob,
                odds=vb.bookmaker_odds,
                league=match_info.get("league_short_name"),
            )

            # Get user's current bankroll for bankroll_before
            user = session.query(User).filter_by(id=user_id).first()
            if user is None:
                logger.warning("log_system_picks: User %d not found", user_id)
                skipped_count += 1
                continue

            # Check for existing system pick to avoid duplicates
            existing = session.query(BetLog).filter_by(
                user_id=user_id,
                match_id=vb.match_id,
                market_type=vb.market_type,
                selection=vb.selection,
                bookmaker=vb.bookmaker,
                bet_type="system_pick",
            ).first()

            if existing:
                skipped_count += 1
                continue

            # PC-11-03: Look up the actual ValueBet DB ID instead of
            # using vb.prediction_id (which is a predictions.id, wrong table).
            # BetLog.value_bet_id is an FK to value_bets.id.
            actual_vb = session.query(ValueBet).filter_by(
                match_id=vb.match_id,
                prediction_id=vb.prediction_id,
                market_type=vb.market_type,
                selection=vb.selection,
                bookmaker=vb.bookmaker,
            ).first()
            actual_vb_id = actual_vb.id if actual_vb else None

            entry = BetLog(
                user_id=user_id,
                value_bet_id=actual_vb_id,
                match_id=vb.match_id,
                date=match_info["date"],
                league=match_info["league"],
                home_team=match_info["home_team"],
                away_team=match_info["away_team"],
                market_type=vb.market_type,
                selection=vb.selection,
                model_prob=vb.model_prob,
                bookmaker=vb.bookmaker,
                odds_at_detection=vb.bookmaker_odds,
                implied_prob=vb.implied_prob,
                edge=vb.edge,
                stake=stake_result.stake,
                stake_method=stake_result.method,
                bet_type="system_pick",
                status="pending",
                bankroll_before=user.current_bankroll,
            )
            session.add(entry)
            new_count += 1

    summary = {"new": new_count, "skipped": skipped_count, "total": len(value_bets)}
    logger.info(
        "log_system_picks: Logged %d system picks (%d new, %d skipped)",
        summary["total"], summary["new"], summary["skipped"],
    )
    return summary


# ============================================================================
# Log User-Placed Bet
# ============================================================================

def log_user_bet(
    value_bet_id: int,
    user_id: int,
    actual_odds: float,
    actual_stake: float,
) -> Optional[int]:
    """Log a user-placed bet linked to a system pick.

    When the user confirms they placed a bet with a real bookmaker,
    this creates a separate ``user_placed`` entry with the actual odds
    and stake they got (which may differ from the model's recommendation).

    Parameters
    ----------
    value_bet_id : int
        Database ID of the value_bet this bet is based on.
    user_id : int
        Database ID of the user.
    actual_odds : float
        The actual decimal odds the user got from the bookmaker.
    actual_stake : float
        The actual stake amount the user placed.

    Returns
    -------
    int or None
        The bet_log ID of the new entry, or None if creation failed.
    """
    with get_session() as session:
        # Look up the value bet for match details
        vb = session.query(ValueBet).filter_by(id=value_bet_id).first()
        if vb is None:
            logger.warning(
                "log_user_bet: ValueBet %d not found", value_bet_id,
            )
            return None

        match_info = _get_match_info(session, vb.match_id)
        if match_info is None:
            logger.warning(
                "log_user_bet: Match %d not found", vb.match_id,
            )
            return None

        user = session.query(User).filter_by(id=user_id).first()
        if user is None:
            logger.warning("log_user_bet: User %d not found", user_id)
            return None

        entry = BetLog(
            user_id=user_id,
            value_bet_id=value_bet_id,
            match_id=vb.match_id,
            date=match_info["date"],
            league=match_info["league"],
            home_team=match_info["home_team"],
            away_team=match_info["away_team"],
            market_type=vb.market_type,
            selection=vb.selection,
            model_prob=vb.model_prob,
            bookmaker=vb.bookmaker,
            odds_at_detection=vb.bookmaker_odds,
            odds_at_placement=actual_odds,
            implied_prob=vb.implied_prob,
            edge=vb.edge,
            stake=actual_stake,
            stake_method=user.staking_method,
            bet_type="user_placed",
            status="pending",
            bankroll_before=user.current_bankroll,
        )
        session.add(entry)
        session.flush()
        bet_id = entry.id

    logger.info(
        "log_user_bet: Created user_placed bet %d (match=%d, %s/%s @ %.2f)",
        bet_id, vb.match_id, vb.market_type, vb.selection, actual_odds,
    )
    return bet_id


# ============================================================================
# Resolve Bets
# ============================================================================

def resolve_bets(match_id: int) -> Dict[str, int]:
    """Resolve all pending bets for a completed match.

    When match results are available, this function:
      1. Determines the actual outcome for each pending bet
      2. Updates status to 'won', 'lost', or 'void'
      3. Calculates PnL (profit/loss)
      4. Updates the user's current_bankroll
      5. Calculates CLV if closing odds are available

    Parameters
    ----------
    match_id : int
        Database ID of the match whose results just came in.

    Returns
    -------
    dict
        Summary with keys: ``"resolved"``, ``"won"``, ``"lost"``, ``"void"``.
    """
    won_count = 0
    lost_count = 0
    void_count = 0

    with get_session() as session:
        # Get the match result
        match = session.query(Match).filter_by(id=match_id).first()
        if match is None:
            logger.warning("resolve_bets: Match %d not found", match_id)
            return {"resolved": 0, "won": 0, "lost": 0, "void": 0}

        if match.status != "finished":
            logger.info(
                "resolve_bets: Match %d status is '%s', not finished — skipping",
                match_id, match.status,
            )
            return {"resolved": 0, "won": 0, "lost": 0, "void": 0}

        home_goals = match.home_goals
        away_goals = match.away_goals

        if home_goals is None or away_goals is None:
            logger.warning(
                "resolve_bets: Match %d has no goals recorded", match_id,
            )
            return {"resolved": 0, "won": 0, "lost": 0, "void": 0}

        # Get all pending bets for this match
        pending_bets = (
            session.query(BetLog)
            .filter_by(match_id=match_id, status="pending")
            .all()
        )

        if not pending_bets:
            logger.info(
                "resolve_bets: No pending bets for match %d", match_id,
            )
            return {"resolved": 0, "won": 0, "lost": 0, "void": 0}

        total_goals = home_goals + away_goals
        now = datetime.utcnow().isoformat()

        for bet in pending_bets:
            # Determine if this bet won or lost based on the actual result
            won = _did_bet_win(
                market_type=bet.market_type,
                selection=bet.selection,
                home_goals=home_goals,
                away_goals=away_goals,
            )

            if won is None:
                # Void (e.g., match postponed or market doesn't apply)
                bet.status = "void"
                bet.pnl = 0.0
                void_count += 1
            elif won:
                bet.status = "won"
                # PnL for a winning bet: stake × (odds - 1)
                # e.g., $20 at odds 2.10 → profit = 20 × 1.10 = $22.00
                odds_used = bet.odds_at_placement or bet.odds_at_detection
                bet.pnl = round(bet.stake * (odds_used - 1.0), 2)
                won_count += 1
            else:
                bet.status = "lost"
                # PnL for a losing bet: -stake (you lose your entire stake)
                bet.pnl = round(-bet.stake, 2)
                lost_count += 1

            # Update bankroll_after
            user = session.query(User).filter_by(id=bet.user_id).first()
            if user:
                user.current_bankroll = round(
                    user.current_bankroll + bet.pnl, 2,
                )
                bet.bankroll_after = user.current_bankroll

            # Calculate CLV (Closing Line Value) if closing odds available
            if bet.closing_odds and bet.odds_at_placement:
                # CLV = implied_prob(closing) - implied_prob(placement)
                # Negative CLV = you got better odds than closing (good!)
                bet.clv = round(
                    (1.0 / bet.closing_odds) - (1.0 / bet.odds_at_placement),
                    6,
                )

            bet.resolved_at = now

    total = won_count + lost_count + void_count
    summary = {
        "resolved": total,
        "won": won_count,
        "lost": lost_count,
        "void": void_count,
    }
    logger.info(
        "resolve_bets: Match %d — resolved %d bets (%d won, %d lost, %d void)",
        match_id, total, won_count, lost_count, void_count,
    )
    return summary


# ============================================================================
# Get Bet History
# ============================================================================

def get_bet_history(
    user_id: int,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    league: Optional[str] = None,
    market_type: Optional[str] = None,
    status: Optional[str] = None,
    bet_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve bet history with optional filters.

    Parameters
    ----------
    user_id : int
        Database ID of the user.
    date_from : str, optional
        Start date (inclusive) in ISO format.
    date_to : str, optional
        End date (inclusive) in ISO format.
    league : str, optional
        Filter by league name.
    market_type : str, optional
        Filter by market type (1X2, OU25, etc.).
    status : str, optional
        Filter by bet status (pending, won, lost, void).
    bet_type : str, optional
        Filter by bet type (system_pick, user_placed).

    Returns
    -------
    list[dict]
        List of bet entries as dicts, ordered by date descending.
    """
    with get_session() as session:
        query = session.query(BetLog).filter_by(user_id=user_id)

        if date_from:
            query = query.filter(BetLog.date >= date_from)
        if date_to:
            query = query.filter(BetLog.date <= date_to)
        if league:
            query = query.filter(BetLog.league == league)
        if market_type:
            query = query.filter(BetLog.market_type == market_type)
        if status:
            query = query.filter(BetLog.status == status)
        if bet_type:
            query = query.filter(BetLog.bet_type == bet_type)

        rows = query.order_by(BetLog.date.desc(), BetLog.id.desc()).all()

        # Convert to dicts while still in session context
        results = []
        for r in rows:
            results.append({
                "id": r.id,
                "user_id": r.user_id,
                "match_id": r.match_id,
                "date": r.date,
                "league": r.league,
                "home_team": r.home_team,
                "away_team": r.away_team,
                "market_type": r.market_type,
                "selection": r.selection,
                "model_prob": r.model_prob,
                "bookmaker": r.bookmaker,
                "odds_at_detection": r.odds_at_detection,
                "odds_at_placement": r.odds_at_placement,
                "implied_prob": r.implied_prob,
                "edge": r.edge,
                "stake": r.stake,
                "stake_method": r.stake_method,
                "bet_type": r.bet_type,
                "status": r.status,
                "pnl": r.pnl,
                "bankroll_before": r.bankroll_before,
                "bankroll_after": r.bankroll_after,
                "closing_odds": r.closing_odds,
                "clv": r.clv,
                "resolved_at": r.resolved_at,
                "created_at": r.created_at,
            })

    return results


# ============================================================================
# Internal Helpers
# ============================================================================

def _get_match_info(session, match_id: int) -> Optional[Dict]:
    """Fetch match details needed for the bet_log entry."""
    match = session.query(Match).filter_by(id=match_id).first()
    if match is None:
        return None

    home = session.query(Team).filter_by(id=match.home_team_id).first()
    away = session.query(Team).filter_by(id=match.away_team_id).first()
    league = session.query(League).filter_by(id=match.league_id).first()

    return {
        "date": match.date,
        "league": league.name if league else "Unknown",
        # PC-25-09: short_name used for stake multiplier lookup in config
        "league_short_name": league.short_name if league else None,
        "home_team": home.name if home else "Unknown",
        "away_team": away.name if away else "Unknown",
    }


def _did_bet_win(
    market_type: str,
    selection: str,
    home_goals: int,
    away_goals: int,
) -> Optional[bool]:
    """Determine if a bet won based on the match result.

    Parameters
    ----------
    market_type : str
        Market type (1X2, OU25, OU15, OU35, BTTS).
    selection : str
        Selection within the market (home, draw, away, over, under, yes, no).
    home_goals : int
        Actual home goals scored.
    away_goals : int
        Actual away goals scored.

    Returns
    -------
    bool or None
        True if the bet won, False if lost, None if void/unsupported.
    """
    total_goals = home_goals + away_goals

    if market_type == "1X2":
        if selection == "home":
            return home_goals > away_goals
        elif selection == "draw":
            return home_goals == away_goals
        elif selection == "away":
            return home_goals < away_goals

    elif market_type == "OU25":
        if selection == "over":
            return total_goals >= 3  # Over 2.5 = 3+ goals
        elif selection == "under":
            return total_goals <= 2  # Under 2.5 = 0, 1, or 2 goals

    elif market_type == "OU15":
        if selection == "over":
            return total_goals >= 2  # Over 1.5 = 2+ goals
        elif selection == "under":
            return total_goals <= 1  # Under 1.5 = 0 or 1 goal

    elif market_type == "OU35":
        if selection == "over":
            return total_goals >= 4  # Over 3.5 = 4+ goals
        elif selection == "under":
            return total_goals <= 3  # Under 3.5 = 0, 1, 2, or 3 goals

    elif market_type == "BTTS":
        if selection == "yes":
            return home_goals >= 1 and away_goals >= 1
        elif selection == "no":
            return home_goals == 0 or away_goals == 0

    # Unknown market/selection → void
    logger.warning(
        "_did_bet_win: Unknown market %s/%s — treating as void",
        market_type, selection,
    )
    return None
