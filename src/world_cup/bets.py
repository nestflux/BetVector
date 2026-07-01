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
from src.world_cup.models import WCAccaLeg, WCAccumulator, WCBetLog, WCMatch, WCTeam

# Markets this tracker accepts and the selections valid within each — matches the
# contract of _did_bet_win, so logged bets are always settleable.
WC_MARKETS = {
    "1X2": ("home", "draw", "away"),
    "OU15": ("over", "under"),
    "OU25": ("over", "under"),
    "OU35": ("over", "under"),
    "BTTS": ("yes", "no"),
    # WC-QUAL: knockout-tie "to qualify / to advance" — settles on WHO PROGRESSES
    # (a.e.t. + penalties), NOT via _did_bet_win. Knockout matches only; no draw.
    "QUALIFY": ("home", "away"),
}

# Friendly labels for display (the view can import these).
MARKET_LABELS = {
    "1X2": "Match result", "OU15": "Over/Under 1.5", "OU25": "Over/Under 2.5",
    "OU35": "Over/Under 3.5", "BTTS": "Both teams to score",
    "QUALIFY": "To qualify",
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


def settlement_score(match):
    """The score a WC bet settles against — the 90-MINUTE score (WC-ACC-02).

    Bookmaker markets (1X2 / Over-Under / BTTS) ignore extra time and penalties, so a
    knockout decided in ET/pens settles on the regulation (90-minute) score. Group
    matches and knockouts decided inside 90 minutes settle on their final score, which
    IS the 90-minute score. Returns ``(home, away)`` or ``None`` when the match isn't
    settleable yet — not scored, or a knockout that went to extra time whose
    regulation score hasn't been reconstructed (defer rather than settle on the
    a.e.t. score). ``getattr`` defaults keep this safe against older/mock rows that
    predate the WC-ACC-02 columns."""
    if getattr(match, "went_to_extra_time", 0):
        rh = getattr(match, "home_goals_reg", None)
        ra = getattr(match, "away_goals_reg", None)
        if rh is None or ra is None:
            return None  # extra time, but the 90-minute score isn't resolved yet
        return (int(rh), int(ra))
    if match.home_goals is None or match.away_goals is None:
        return None
    return (int(match.home_goals), int(match.away_goals))


def _did_qualify(match, selection) -> Optional[bool]:
    """Did ``selection`` (home/away) ADVANCE from this knockout tie? — the winner after
    90 min + extra time + penalties (WC-QUAL). Uses the a.e.t. score (home_goals /
    away_goals include extra time), tie-broken by the penalty shootout (home_pens /
    away_pens). Returns None (defer -> pending) until the advancer is resolved: a group
    match has no per-tie advancer; a level a.e.t. score needs the shootout captured.
    ``getattr`` defaults keep it safe on older/mock rows."""
    if getattr(match, "stage", None) == "group":
        return None
    if match.status != "finished" or match.home_goals is None \
            or match.away_goals is None:
        return None
    hg, ag = int(match.home_goals), int(match.away_goals)   # a.e.t. score (incl. ET)
    if hg != ag:
        winner = "home" if hg > ag else "away"
    else:
        hp = getattr(match, "home_pens", None)
        ap = getattr(match, "away_pens", None)
        if hp is None or ap is None or int(hp) == int(ap):
            return None  # level after ET, shootout not captured (or tied) -> defer
        winner = "home" if int(hp) > int(ap) else "away"
    return selection == winner


def bet_result(match, market_type, selection) -> str:
    """Settled status of a bet on ``match``: 'won' / 'lost' / 'void' / 'pending'. The
    single settlement entry point for singles AND accumulator legs. Routes by market:
    QUALIFY settles on WHO ADVANCED (a.e.t. + penalties); every other market settles on
    the 90-MINUTE score (WC-ACC-02). Returns 'pending' when not yet settleable."""
    if market_type == "QUALIFY":
        won = _did_qualify(match, selection)
        return "pending" if won is None else ("won" if won else "lost")
    score = settlement_score(match)
    if score is None:
        return "pending"
    won = _did_bet_win(market_type, selection, score[0], score[1])
    return "void" if won is None else ("won" if won else "lost")


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
            # Never log a bet against a non-existent match — a dangling row would
            # never display (load_wc_bets inner-joins WCMatch) nor settle. Postgres'
            # FK would reject it, but SQLite (local backup) doesn't enforce FKs, so
            # check explicitly.
            match = session.get(WCMatch, match_id)
            if match is None:
                return None
            # "To qualify" only makes sense for a knockout tie — reject it on a group
            # match (which has no single per-match advancer).
            if market_type == "QUALIFY" and getattr(match, "stage", None) == "group":
                return None
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
                status = bet_result(match, bet.market_type, bet.selection)
                if status == "pending":
                    continue  # not settleable yet (KO 90-min / qualify unresolved)
                bet.status = status
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
                # result immediately without writing. Settles on the 90-minute score
                # (WC-ACC-02) — a knockout awaiting ET reconstruction stays pending.
                if status == "pending" and match.status == "finished":
                    r = bet_result(match, bet.market_type, bet.selection)
                    if r != "pending":
                        status = r
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


# ===========================================================================
# Accumulators (parlays) — WC-ACC-01
# ===========================================================================
# An accumulator combines >= 2 legs into ONE bet: EVERY leg must win, and the
# payout MULTIPLIES (combined odds = product of the leg odds). A VOID leg (e.g.
# an abandoned match) drops out — it's removed from the multiplier and the
# remaining legs still all have to win. ONE losing leg loses the whole bet.
#
# The pure functions below hold the money math (fully unit-testable, no DB); the
# settle/log/load functions apply them over the wc_accumulator + wc_acca_leg
# tables. Leg settlement reuses the SAME _did_bet_win logic as singles, so an
# acca leg settles exactly like a single bet.

# Terminal match statuses with no result to settle against — such a leg is VOID
# (dropped from the accumulator), never scored. "postponed" stays PENDING (a
# postponed match is expected to be replayed), matching bookmaker practice.
_VOID_MATCH_STATUSES = ("void", "cancelled", "abandoned")


def accumulator_odds(leg_odds) -> float:
    """Combined decimal odds of an accumulator = the PRODUCT of the leg odds
    (payouts multiply because every leg must win). Empty -> 1.0 (neutral)."""
    combined = 1.0
    for o in leg_odds:
        combined *= float(o)
    return round(combined, 4)


def accumulator_status(leg_statuses) -> str:
    """Derive an accumulator's status from its leg statuses (each 'pending' /
    'won' / 'lost' / 'void'):

      * ANY leg lost      -> 'lost'    (one loss kills the whole bet — locked in even
                                        while other legs are still unresolved)
      * else ANY pending  -> 'pending' (can't pay out until every leg resolves)
      * else all void      -> 'void'   (nothing left to win — stake returned)
      * else               -> 'won'    (every non-void leg won; void legs dropped out)
    """
    statuses = list(leg_statuses)
    if not statuses:
        return "void"   # unreachable in practice (log enforces >= 2 legs); defensive
    if any(s == "lost" for s in statuses):
        return "lost"
    if any(s == "pending" for s in statuses):
        return "pending"
    if all(s == "void" for s in statuses):
        return "void"
    return "won"


def accumulator_effective_odds(leg_odds, leg_statuses) -> float:
    """Payout multiplier once settled = product of the odds of the legs that WON.
    Void legs drop out (excluded from the product); a fully-void slip -> 1.0."""
    eff = 1.0
    for o, s in zip(leg_odds, leg_statuses):
        if s == "won":
            eff *= float(o)
    return round(eff, 4)


def accumulator_pnl(status, stake, leg_odds, leg_statuses) -> float:
    """Profit/loss for a settled accumulator (profit only; stake returned separately
    on a win/void):

      * 'won'  -> stake * (effective_odds - 1), effective_odds EXCLUDES void legs
      * 'lost' -> -stake
      * 'void' / 'pending' -> 0
    """
    if status == "won":
        eff = accumulator_effective_odds(leg_odds, leg_statuses)
        return round(float(stake) * (eff - 1.0), 2)
    if status == "lost":
        return round(-float(stake), 2)
    return 0.0


def _leg_status(market_type, selection, match) -> str:
    """Settled status of a single leg given its match row: 'pending' until the match
    is finished + settleable, then 'won'/'lost' (via the same outcome logic as
    singles), or 'void' if the match was abandoned/cancelled (no result to settle
    against). Settles on the 90-minute score (WC-ACC-02) — a knockout that went to
    extra time settles on regulation, and stays 'pending' until that score is
    reconstructed."""
    if match is None:
        return "pending"
    if match.status in _VOID_MATCH_STATUSES:
        return "void"
    if match.status != "finished":
        return "pending"
    # Market-aware settlement (WC-QUAL): QUALIFY on advancement, else the 90-min score.
    return bet_result(match, market_type, selection)


def log_wc_accumulator(user_id: int, legs: list, stake: float, *,
                       source: str = "manual",
                       notes: Optional[str] = None) -> Optional[int]:
    """Log a personal accumulator (parlay). ``legs`` is a list of >= 2 dicts, each:
    ``{match_id, market_type, selection, odds, model_prob?, edge?}``. Validates the
    slip (>= 2 legs, stake > 0) and EVERY leg (valid market/selection, odds > 1, the
    match exists), freezes ``combined_odds`` = product of the leg odds, and inserts the
    parent + legs as 'pending'. All-or-nothing: one bad leg rejects the whole slip.
    Returns the new accumulator id, or None on bad input / DB error (never raises)."""
    try:
        stake = float(stake)
    except (TypeError, ValueError):
        return None
    if stake <= 0:
        return None
    if not legs or len(legs) < 2:
        return None

    # Validate every leg up front before touching the DB.
    clean = []
    for leg in legs:
        try:
            match_id = int(leg["match_id"])
            market_type = leg["market_type"]
            selection = leg["selection"]
            odds = float(leg["odds"])
        except (KeyError, TypeError, ValueError):
            return None
        if not is_valid_selection(market_type, selection) or odds <= 1.0:
            return None
        clean.append({
            "match_id": match_id, "market_type": market_type,
            "selection": selection, "odds": odds,
            "model_prob": leg.get("model_prob"), "edge": leg.get("edge"),
        })

    try:
        with get_session() as session:
            # Every leg's match must exist. Postgres' FK would reject a dangling row,
            # but SQLite (local backup) doesn't enforce FKs, so check explicitly — a
            # dangling leg would never settle and would break the display join.
            for leg in clean:
                m = session.get(WCMatch, leg["match_id"])
                if m is None:
                    return None
                # "To qualify" legs are knockout-only — reject the whole slip if one
                # lands on a group match.
                if leg["market_type"] == "QUALIFY" \
                        and getattr(m, "stage", None) == "group":
                    return None
            combined = accumulator_odds([leg["odds"] for leg in clean])
            acca = WCAccumulator(
                user_id=user_id, stake=stake, combined_odds=combined,
                source=source, notes=notes, status="pending",
            )
            for leg in clean:
                acca.legs.append(WCAccaLeg(
                    match_id=leg["match_id"], market_type=leg["market_type"],
                    selection=leg["selection"], odds=leg["odds"],
                    model_prob=leg["model_prob"], edge=leg["edge"], status="pending",
                ))
            session.add(acca)
            session.commit()
            session.refresh(acca)
            return acca.id
    except Exception:
        return None


def settle_wc_accumulators() -> int:
    """Settle pending accumulators whose legs have all resolved (or one has lost), in
    place (leg + parent status, parent pnl, settled_at). Idempotent + pipeline-safe:
    only touches status=='pending' parents; a still-open slip is left untouched;
    running it twice changes nothing. Never raises. Returns the count newly settled."""
    settled = 0
    try:
        with get_session() as session:
            accas = session.execute(
                select(WCAccumulator).where(WCAccumulator.status == "pending")
            ).scalars().all()
            if not accas:
                return 0
            # Bulk-load every match referenced by a pending leg (one query).
            match_ids = {leg.match_id for a in accas for leg in a.legs}
            matches = {}
            if match_ids:
                matches = {
                    m.id: m for m in session.execute(
                        select(WCMatch).where(WCMatch.id.in_(match_ids))
                    ).scalars().all()
                }
            now = datetime.utcnow().isoformat()
            for acca in accas:
                leg_statuses = [
                    _leg_status(leg.market_type, leg.selection,
                                matches.get(leg.match_id))
                    for leg in acca.legs
                ]
                parent_status = accumulator_status(leg_statuses)
                if parent_status == "pending":
                    continue  # not all legs resolved (and none lost) — leave it open
                for leg, st in zip(acca.legs, leg_statuses):
                    if leg.status != st:
                        leg.status = st
                        leg.settled_at = now
                acca.status = parent_status
                acca.pnl = accumulator_pnl(
                    parent_status, acca.stake,
                    [leg.odds for leg in acca.legs], leg_statuses,
                )
                acca.settled_at = now
                settled += 1
            if settled:
                session.commit()
        return settled
    except Exception:
        return 0


def load_wc_accumulators(user_id: int) -> list:
    """A user's accumulators, newest first, as plain dicts with READ-TIME settlement
    (leg statuses + parent status/pnl recomputed live from finished matches WITHOUT
    writing — so the display is correct even before settle_wc_accumulators has run).

    Each dict: id, stake, combined_odds, effective_odds, status, pnl, source, notes,
    placed_at, settled_at, n_legs, and 'legs' — each leg with match info + live status.
    Returns [] on error."""
    out = []
    try:
        with get_session() as session:
            accas = session.execute(
                select(WCAccumulator)
                .where(WCAccumulator.user_id == user_id)
                .order_by(WCAccumulator.placed_at.desc())
            ).scalars().all()
            if not accas:
                return []
            # Bulk-load matches + team names for every leg (one query).
            match_ids = {leg.match_id for a in accas for leg in a.legs}
            minfo = {}
            if match_ids:
                HomeTeam = aliased(WCTeam)
                AwayTeam = aliased(WCTeam)
                for m, home, away in session.execute(
                    select(WCMatch, HomeTeam.name, AwayTeam.name)
                    .join(HomeTeam, WCMatch.home_team_id == HomeTeam.id)
                    .join(AwayTeam, WCMatch.away_team_id == AwayTeam.id)
                    .where(WCMatch.id.in_(match_ids))
                ).all():
                    minfo[m.id] = (m, home, away)

            for acca in accas:
                legs_out, leg_statuses, leg_odds = [], [], []
                for leg in acca.legs:
                    m, home, away = minfo.get(leg.match_id, (None, None, None))
                    st = _leg_status(leg.market_type, leg.selection, m)
                    leg_statuses.append(st)
                    leg_odds.append(leg.odds)
                    legs_out.append({
                        "id": leg.id, "match_id": leg.match_id,
                        "date": m.date if m else None,
                        "home": home, "away": away,
                        "home_goals": m.home_goals if m else None,
                        "away_goals": m.away_goals if m else None,
                        "match_status": m.status if m else None,
                        "market_type": leg.market_type,
                        "market_label": MARKET_LABELS.get(leg.market_type,
                                                          leg.market_type),
                        "selection": leg.selection, "odds": leg.odds, "status": st,
                        "model_prob": leg.model_prob, "edge": leg.edge,
                    })
                status = accumulator_status(leg_statuses)
                out.append({
                    "id": acca.id, "stake": acca.stake,
                    "combined_odds": acca.combined_odds,
                    "effective_odds": accumulator_effective_odds(leg_odds,
                                                                 leg_statuses),
                    "status": status,
                    "pnl": accumulator_pnl(status, acca.stake, leg_odds, leg_statuses),
                    "source": acca.source, "notes": acca.notes,
                    "placed_at": acca.placed_at, "settled_at": acca.settled_at,
                    "n_legs": len(legs_out), "legs": legs_out,
                })
        return out
    except Exception:
        return []


def accumulator_slip_readout(legs) -> dict:
    """INFORMATIVE combined readout for a bet slip the user is building (WC-ACC-03).

    A CALCULATOR, not a recommender — it never suggests a combination, it only
    describes the one the user assembled:
      * combined_odds  — product of the leg odds (what the parlay pays per unit)
      * implied_prob   — 1 / combined_odds (the market's implied chance of it landing)
      * model_prob     — product of the per-leg model probabilities, but ONLY when
                         EVERY leg carries one (a missing leg makes the product
                         meaningless); None otherwise
      * edge           — model_prob − implied_prob (None if model_prob is None)
      * correlated     — same-match groups: any match with >1 leg on the slip

    The combined model prob / edge ASSUME the legs are independent (their joint
    probability is the product of the singles). That's why same-match legs are
    surfaced in ``correlated``: their outcomes are correlated, so multiplying their
    odds/probabilities is invalid and the combined numbers can't be trusted for them.
    Pure — takes the session-state slip, returns a dict; never raises."""
    legs = list(legs)
    combined = 1.0
    for lg in legs:
        combined *= float(lg["odds"])
    combined = round(combined, 4)
    implied = round(1.0 / combined, 4) if combined > 0 else None

    probs = [lg.get("model_prob") for lg in legs]
    model_prob = None
    if legs and all(p is not None for p in probs):
        mp = 1.0
        for p in probs:
            mp *= float(p)
        model_prob = round(mp, 4)
    edge = (round(model_prob - implied, 4)
            if (model_prob is not None and implied is not None) else None)

    # Same-match correlation — any match_id that appears on more than one leg.
    groups: dict = {}
    for lg in legs:
        groups.setdefault(lg.get("match_id"), []).append(lg)
    correlated = [
        {"match_id": mid,
         "label": f'{grp[0].get("home", "?")} v {grp[0].get("away", "?")}',
         "count": len(grp)}
        for mid, grp in groups.items() if len(grp) > 1
    ]

    return {
        "n_legs": len(legs), "combined_odds": combined, "implied_prob": implied,
        "model_prob": model_prob, "edge": edge, "correlated": correlated,
    }


# ---------------------------------------------------------------------------
# Combined singles + accumulators — scoreboard + timeline (WC-ACC-04)
# ---------------------------------------------------------------------------
# The My Bets scoreboard + cumulative-P&L chart cover BOTH single bets and
# accumulators, so a user sees one running P&L across everything they've staked.
# Each bet — single or accumulator — counts as ONE unit (one stake, one result).

def _bet_unit(b: dict) -> dict:
    """Normalise a single-bet dict (from load_wc_bets) to a P&L unit."""
    return {"date": b.get("date"), "status": b["status"], "stake": b["stake"],
            "pnl": b.get("pnl") or 0.0, "source": b.get("source") or "manual",
            "kind": "single", "id": b["id"]}


def _acca_unit(a: dict) -> dict:
    """Normalise an accumulator dict (from load_wc_accumulators) to a P&L unit. Its
    effective settle date is the LATEST leg date — an accumulator only resolves once
    its last leg's match has finished."""
    leg_dates = [lg.get("date") for lg in a.get("legs", []) if lg.get("date")]
    return {"date": max(leg_dates) if leg_dates else None, "status": a["status"],
            "stake": a["stake"], "pnl": a.get("pnl") or 0.0,
            "source": a.get("source") or "manual", "kind": "acca", "id": a["id"]}


def combined_bet_summary(singles: list, accas: list) -> dict:
    """Running-P&L scoreboard across BOTH singles and accumulators (WC-ACC-04). Takes
    the two already-loaded lists (read-time settled) so it needs no extra query; each
    bet counts once. Same shape as ``wc_bet_summary`` plus ``singles``/``accas``
    counts, so the existing scoreboard renderer works unchanged."""
    units = [_bet_unit(b) for b in singles] + [_acca_unit(a) for a in accas]
    settled = [u for u in units if u["status"] in ("won", "lost", "void")]
    won = [u for u in settled if u["status"] == "won"]
    staked_settled = sum(u["stake"] for u in settled)
    net = sum(u["pnl"] for u in settled)
    returned = sum((u["stake"] + u["pnl"]) for u in settled if u["status"] != "lost")
    advised = [u for u in settled if u["source"] != "manual"]
    advised_won = sum(1 for u in advised if u["status"] == "won")
    return {
        "total": len(units), "singles": len(singles), "accas": len(accas),
        "pending": sum(1 for u in units if u["status"] == "pending"),
        "settled": len(settled), "won": len(won),
        "lost": sum(1 for u in settled if u["status"] == "lost"),
        "void": sum(1 for u in settled if u["status"] == "void"),
        "staked_total": round(sum(u["stake"] for u in units), 2),
        "staked_settled": round(staked_settled, 2),
        "returned": round(returned, 2),
        "net_pnl": round(net, 2),
        "roi": round(net / staked_settled, 4) if staked_settled else None,
        "win_rate": round(len(won) / len(settled), 4) if settled else None,
        "advised_settled": len(advised), "advised_won": advised_won,
        "advised_win_rate": round(advised_won / len(advised), 4) if advised else None,
    }


def combined_pnl_timeline(singles: list, accas: list) -> list:
    """Cumulative net P&L across settled singles + accumulators, ordered by settle date
    (WC-ACC-04). Pure — takes the loaded lists. Each entry: {date, pnl, cumulative,
    kind}. [] if nothing is settled yet."""
    units = [_bet_unit(b) for b in singles] + [_acca_unit(a) for a in accas]
    settled = [u for u in units if u["status"] in ("won", "lost", "void")]
    settled.sort(key=lambda u: ((u.get("date") or ""), u["kind"], u["id"]))
    out, run = [], 0.0
    for u in settled:
        run += u["pnl"]
        out.append({"date": u.get("date"), "pnl": u["pnl"],
                    "cumulative": round(run, 2), "kind": u["kind"]})
    return out
