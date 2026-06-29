"""
BetVector World Cup — Personal Bet Tracker (WC-BET-01)
======================================================
A user's OWN World Cup bets: log a selection, track it, and have it settle to
won/lost off the final score with a running P&L. Completely separate from:

  * the model's shadow value picks (``wc_value_bets``), and
  * league bets (``bet_log``).

These are pure user data — this module NEVER writes to the model / value /
prediction path, so the World Cup model stays untouched.

Settlement reuses ``betting.tracker._did_bet_win`` so a WC bet settles by the
EXACT same proven logic as a league bet. Markets/selections are stored in that
function's canonical convention (1X2 / OU15 / OU25 / OU35 / BTTS).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import aliased

from src.betting.tracker import _did_bet_win  # reuse the proven league outcome logic
from src.database.db import get_session
from src.world_cup.models import WCBetLog, WCMatch, WCTeam

# Markets this tracker accepts and the selections valid within each — matches the
# contract of _did_bet_win, so logged bets are always settleable.
WC_MARKETS = {
    "1X2": ("home", "draw", "away"),
    "OU15": ("over", "under"),
    "OU25": ("over", "under"),
    "OU35": ("over", "under"),
    "BTTS": ("yes", "no"),
}

# Friendly labels for display (the view can import these).
MARKET_LABELS = {
    "1X2": "Match result", "OU15": "Over/Under 1.5", "OU25": "Over/Under 2.5",
    "OU35": "Over/Under 3.5", "BTTS": "Both teams to score",
}


def is_valid_selection(market_type: str, selection: str) -> bool:
    """True if (market_type, selection) is one this tracker can store + settle."""
    return market_type in WC_MARKETS and selection in WC_MARKETS[market_type]


def bet_outcome(market_type, selection, home_goals, away_goals) -> Optional[bool]:
    """won (True) / lost (False) / void (None) for a finished match — delegates to
    the league outcome logic. Returns None if the match isn't scored yet."""
    if home_goals is None or away_goals is None:
        return None
    return _did_bet_win(market_type, selection, int(home_goals), int(away_goals))


def bet_pnl(status: str, stake: float, odds: float) -> float:
    """Profit/loss for a settled bet: won -> stake*(odds-1); lost -> -stake;
    void/pending -> 0. Profit only (stake returned separately on a win)."""
    if status == "won":
        return round(stake * (odds - 1.0), 2)
    if status == "lost":
        return round(-stake, 2)
    return 0.0


def log_wc_bet(user_id: int, match_id: int, market_type: str, selection: str,
               odds: float, stake: float, *, bookmaker: Optional[str] = None,
               model_prob: Optional[float] = None, edge: Optional[float] = None,
               source: str = "manual", notes: Optional[str] = None) -> Optional[int]:
    """Insert a personal WC bet (status 'pending'). Validates the market/selection
    and that odds > 1 and stake > 0. Returns the new row id, or None on bad input
    or a DB error (never raises)."""
    if not is_valid_selection(market_type, selection):
        return None
    try:
        odds = float(odds)
        stake = float(stake)
    except (TypeError, ValueError):
        return None
    if odds <= 1.0 or stake <= 0:
        return None
    try:
        with get_session() as session:
            bet = WCBetLog(
                user_id=user_id, match_id=match_id, market_type=market_type,
                selection=selection, odds=odds, stake=stake, bookmaker=bookmaker,
                model_prob=model_prob, edge=edge, source=source, notes=notes,
                status="pending",
            )
            session.add(bet)
            session.commit()
            session.refresh(bet)
            return bet.id
    except Exception:
        return None


def settle_wc_bets() -> int:
    """Settle pending WC bets whose match has finished, in place (status + pnl +
    settled_at). Idempotent — only touches status=='pending' rows on finished,
    scored matches; running it twice changes nothing. Returns the count settled.
    Never raises (pipeline-safe)."""
    settled = 0
    try:
        with get_session() as session:
            rows = session.execute(
                select(WCBetLog, WCMatch)
                .join(WCMatch, WCBetLog.match_id == WCMatch.id)
                .where(WCBetLog.status == "pending", WCMatch.status == "finished")
            ).all()
            for bet, match in rows:
                if match.home_goals is None or match.away_goals is None:
                    continue  # finished but not scored yet — leave pending
                won = bet_outcome(bet.market_type, bet.selection,
                                  match.home_goals, match.away_goals)
                bet.status = "void" if won is None else ("won" if won else "lost")
                bet.pnl = bet_pnl(bet.status, bet.stake, bet.odds)
                bet.settled_at = datetime.utcnow().isoformat()
                settled += 1
            if settled:
                session.commit()
        return settled
    except Exception:
        return 0


def load_wc_bets(user_id: int) -> list:
    """A user's WC bets, newest first, as plain dicts with match info and a
    READ-TIME settled status (so the list is correct even before settle_wc_bets has
    run). Each dict: id, match_id, date, home, away, home_goals, away_goals,
    market_type, market_label, selection, odds, stake, bookmaker, status, pnl,
    model_prob, edge, source, placed_at. Returns [] on error."""
    out = []
    try:
        with get_session() as session:
            HomeTeam = aliased(WCTeam)
            AwayTeam = aliased(WCTeam)
            rows = session.execute(
                select(WCBetLog, WCMatch, HomeTeam.name, AwayTeam.name)
                .join(WCMatch, WCBetLog.match_id == WCMatch.id)
                .join(HomeTeam, WCMatch.home_team_id == HomeTeam.id)
                .join(AwayTeam, WCMatch.away_team_id == AwayTeam.id)
                .where(WCBetLog.user_id == user_id)
                .order_by(WCBetLog.placed_at.desc())
            ).all()
            for bet, match, home, away in rows:
                status, pnl = bet.status, (bet.pnl or 0.0)
                # Read-time settlement for display: the persisted settle step runs
                # in the pipeline and may lag a few hours, so reflect a finished
                # result immediately without writing.
                if status == "pending" and match.status == "finished" \
                        and match.home_goals is not None and match.away_goals is not None:
                    won = bet_outcome(bet.market_type, bet.selection,
                                      match.home_goals, match.away_goals)
                    status = "void" if won is None else ("won" if won else "lost")
                    pnl = bet_pnl(status, bet.stake, bet.odds)
                out.append({
                    "id": bet.id, "match_id": bet.match_id, "date": match.date,
                    "home": home, "away": away,
                    "home_goals": match.home_goals, "away_goals": match.away_goals,
                    "match_status": match.status,
                    "market_type": bet.market_type,
                    "market_label": MARKET_LABELS.get(bet.market_type, bet.market_type),
                    "selection": bet.selection, "odds": bet.odds, "stake": bet.stake,
                    "bookmaker": bet.bookmaker, "status": status, "pnl": pnl,
                    "model_prob": bet.model_prob, "edge": bet.edge,
                    "source": bet.source, "placed_at": bet.placed_at,
                })
        return out
    except Exception:
        return []


def wc_bet_summary(user_id: int) -> dict:
    """Running P&L scoreboard for a user's WC bets (read-time settled): counts,
    staked, returned, net pnl, roi, win rate — plus a 'model-advised' subset
    (bets logged from a tip, source != 'manual')."""
    bets = load_wc_bets(user_id)
    settled = [b for b in bets if b["status"] in ("won", "lost", "void")]
    won = [b for b in settled if b["status"] == "won"]
    staked_settled = sum(b["stake"] for b in settled)
    net = sum(b["pnl"] for b in settled)
    # returned = stake back + profit on wins (settled bets only)
    returned = sum((b["stake"] + b["pnl"]) for b in settled if b["status"] != "lost")

    advised = [b for b in settled if (b.get("source") or "manual") != "manual"]
    advised_won = sum(1 for b in advised if b["status"] == "won")

    return {
        "total": len(bets),
        "pending": sum(1 for b in bets if b["status"] == "pending"),
        "settled": len(settled),
        "won": len(won),
        "lost": sum(1 for b in settled if b["status"] == "lost"),
        "void": sum(1 for b in settled if b["status"] == "void"),
        "staked_total": round(sum(b["stake"] for b in bets), 2),
        "staked_settled": round(staked_settled, 2),
        "returned": round(returned, 2),
        "net_pnl": round(net, 2),
        "roi": round(net / staked_settled, 4) if staked_settled else None,
        "win_rate": round(len(won) / len(settled), 4) if settled else None,
        "advised_settled": len(advised),
        "advised_won": advised_won,
        "advised_win_rate": round(advised_won / len(advised), 4) if advised else None,
    }


def wc_pnl_timeline(bets: list) -> list:
    """Cumulative net P&L from a loaded bets list (settled bets only), ordered by
    match date then id, as [{date, pnl, cumulative}]. Pure — takes the list from
    load_wc_bets so it needs no extra query. [] if nothing is settled yet."""
    settled = [b for b in bets if b["status"] in ("won", "lost", "void")]
    settled.sort(key=lambda b: ((b.get("date") or ""), b["id"]))
    out, run = [], 0.0
    for b in settled:
        run += (b["pnl"] or 0.0)
        out.append({"date": b.get("date"), "pnl": b["pnl"],
                    "cumulative": round(run, 2)})
    return out
