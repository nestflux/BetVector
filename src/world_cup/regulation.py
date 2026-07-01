"""World Cup knockout 90-minute (regulation) score reconciliation — WC-ACC-02.

WHY THIS EXISTS
---------------
Bookmaker markets — Match Result (1X2), Over/Under, Both Teams To Score — settle on
the **90-minute** score. A knockout decided in extra time or on penalties is, for
these markets, settled as it stood at the end of regulation. Example: Germany 1-1
Paraguay after 90, Germany win on penalties → a "Germany win" bet is a LOSER (the
90-minute result was a draw), and the match was Under 2.5 / no BTTS-changing ET
goals on the 90-minute line.

ESPN's scoreboard stores only the FINAL (a.e.t.) score, so for a knockout that went
to extra time we reconstruct the regulation score from ESPN's ``keyEvents`` feed,
which carries a ``period`` on every goal (periods 1-2 = regulation halves, 3-4 =
extra time, 5 = shootout). We count the regulation goals, then SELF-CHECK the
all-periods count against the official final score per team. Only if that reconciles
do we trust the 90-minute split — otherwise (a renamed goal type, an own-goal
mis-attribution) we DEFER and store nothing, so a bet never settles on a guessed
score. Group matches always end at 90, so they are never touched here.

SCOPE: reads ESPN (free, key-less — the same feed used for lineups + results); writes
only ``wc_matches.{home_goals_reg, away_goals_reg, went_to_extra_time}``. Never writes
to the model / value / prediction path. Idempotent + pipeline-safe (never raises).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import requests
from sqlalchemy import select
from sqlalchemy.orm import aliased

from src.database.db import get_session
from src.world_cup.lineups import ESPN_BASE, _to_db_name
from src.world_cup.models import WCMatch, WCTeam
from src.world_cup.results_espn import fetch_espn_results_for_date

logger = logging.getLogger(__name__)

_TIMEOUT = 20

# A keyEvents entry counts as a goal when its type text starts with "goal"
# ("Goal", "Goal - Header", "Goal - Volley", ...), or is a scored penalty in open
# play, or an own goal — but never a disallowed/missed/saved effort or a shootout
# penalty. The self-check (all-periods count == official final score) catches any
# type this heuristic misses, so we defer rather than mis-settle.
_GOAL_EXCLUDE = ("disallow", "missed", "saved", "shootout", "penalties")


def _is_goal(type_text: str) -> bool:
    """True if an ESPN keyEvents type text denotes a goal that counts toward the score."""
    t = (type_text or "").lower().strip()
    if any(w in t for w in _GOAL_EXCLUDE):
        return False
    return t.startswith("goal") or t == "penalty - scored" or t.endswith("own goal")


def _detail_indicates_et(detail: str) -> bool:
    """True if ESPN's status detail ('FT-Pens', 'AET', ...) shows the match ran past
    90 minutes. 'FT' (regulation) → False."""
    d = (detail or "").lower()
    return ("pen" in d) or ("aet" in d) or ("a.e.t" in d) or ("extra" in d)


def _fetch_key_events(event_id) -> list:
    """ESPN keyEvents (goals, cards, subs, period markers) for one match. Empty list
    on any HTTP/parse failure — the caller then defers (never guesses)."""
    resp = requests.get(
        f"{ESPN_BASE}/summary", params={"event": event_id}, timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        logger.warning("ESPN summary event %s -> HTTP %d", event_id, resp.status_code)
        return []
    return resp.json().get("keyEvents") or []


def reconstruct_regulation_score(event_id, home_name, away_name,
                                 final_home, final_away):
    """The 90-MINUTE score for a knockout that went to extra time, reconstructed from
    ESPN keyEvents and self-checked against the official final (a.e.t.) score.

    ``home_name`` / ``away_name`` are the ESPN display names and ``final_home`` /
    ``final_away`` the ESPN final scores (all in ESPN's home/away orientation); the
    returned ``(reg_home, reg_away)`` is in that same orientation. Returns None when
    the reconstruction can't be trusted — a missed goal type, or (in nearly all cases)
    an own-goal mis-attribution, makes the per-team all-periods count disagree with the
    official final score, so we refuse to guess. Never raises."""
    try:
        events = _fetch_key_events(event_id)
    except Exception as e:  # noqa: BLE001 - resilience over correctness (Rule 6)
        logger.warning("keyEvents fetch failed for event %s: %s", event_id, e)
        return None

    reg_h = reg_a = all_h = all_a = 0
    for p in events:
        if not _is_goal((p.get("type") or {}).get("text")):
            continue
        period = (p.get("period") or {}).get("number")
        if period is None or period >= 5:
            continue  # shootout (period 5) or unknown period — not a match goal
        team = (p.get("team") or {}).get("displayName")
        h = 1 if team == home_name else 0
        a = 1 if team == away_name else 0
        all_h += h
        all_a += a
        if period <= 2:  # regulation (the two 45-minute halves)
            reg_h += h
            reg_a += a

    # Self-check: counting every non-shootout goal must reproduce the official final
    # score per team. If it doesn't, a goal type was missed or an own goal landed on
    # the wrong side — defer rather than settle a bet on a guessed 90-minute split.
    # (Catches a single mis-attributed own goal; only two own goals mis-filed in
    # OPPOSITE directions in one knockout could cancel in the totals — vanishingly rare.)
    if all_h != final_home or all_a != final_away:
        logger.warning(
            "Regulation self-check failed for event %s: counted %d-%d vs final %d-%d "
            "— deferring", event_id, all_h, all_a, final_home, final_away,
        )
        return None
    return (reg_h, reg_a)


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def reconcile_knockout_regulation(today: str | None = None,
                                  lookback_days: int = 21) -> dict:
    """Populate the 90-minute (regulation) score + extra-time flag on finished
    knockout matches so bets settle on the bookmaker's 90-minute convention.

    For each finished knockout match, find its ESPN event (by date + team pair). If
    the match went to extra time, reconstruct + self-check the 90-minute score and
    store it (mapping ESPN's orientation onto the stored row); if it can't be verified
    the flag is set but the regulation score stays NULL, so settlement defers. A
    regulation-time knockout is flagged ``went_to_extra_time = 0`` (its final score IS
    the 90-minute score). Group matches are never touched.

    Idempotent (re-asserts the same values) and pipeline-safe (never raises).
    Returns ``{'checked', 'extra_time', 'resolved', 'deferred'}``.
    """
    checked = extra_time = resolved = deferred = 0
    try:
        with get_session() as session:
            HomeTeam = aliased(WCTeam)
            AwayTeam = aliased(WCTeam)
            rows = session.execute(
                select(WCMatch, HomeTeam.name, AwayTeam.name)
                .join(HomeTeam, WCMatch.home_team_id == HomeTeam.id)
                .join(AwayTeam, WCMatch.away_team_id == AwayTeam.id)
                .where(
                    WCMatch.stage != "group",
                    WCMatch.status == "finished",
                    WCMatch.home_goals.isnot(None),
                    WCMatch.away_goals.isnot(None),
                )
            ).all()
            if not rows:
                return {"checked": 0, "extra_time": 0, "resolved": 0, "deferred": 0}

            # Fetch each needed ESPN date once, then match events to matches by pair.
            espn_by_date: dict[str, list] = {}
            for _match, _h, _a in rows:
                d = (_match.date or "")[:10]
                if d and d not in espn_by_date:
                    try:
                        dt = datetime.strptime(d, "%Y-%m-%d").date()
                        espn_by_date[d] = fetch_espn_results_for_date(dt)
                    except Exception as e:  # noqa: BLE001 - non-fatal (Rule 6)
                        logger.warning("ESPN fetch failed for %s: %s", d, e)
                        espn_by_date[d] = []

            for match, home_name, away_name in rows:
                d = (match.date or "")[:10]
                event = _find_espn_event(espn_by_date.get(d, []), home_name, away_name)
                if event is None:
                    continue  # no ESPN event to reconcile against — leave as-is
                checked += 1
                if not _detail_indicates_et(event.get("detail")):
                    # Decided in 90 — its stored final score IS the 90-minute score.
                    if match.went_to_extra_time:
                        match.went_to_extra_time = 0
                        match.home_goals_reg = None  # clear any stale regulation score
                        match.away_goals_reg = None
                        match.home_pens = None       # + stale shootout score (WC-QUAL)
                        match.away_pens = None
                    continue
                extra_time += 1
                match.went_to_extra_time = 1
                # WC-QUAL: capture the shootout score (for the "to qualify" market),
                # mapping ESPN's orientation onto the stored row. Independent of the
                # 90-minute reconstruction below — a qualify bet settles on the shootout
                # even if the regulation score can't be reconstructed.
                hp, ap = event.get("home_pens"), event.get("away_pens")
                if hp is not None and ap is not None:
                    if _to_db_name(event["home_name"]) == home_name:
                        match.home_pens, match.away_pens = hp, ap
                    else:
                        match.home_pens, match.away_pens = ap, hp
                # Self-check runs against the ESPN event's OWN final score (both come
                # from the same ESPN feed this run, so they're internally consistent) —
                # not the stored a.e.t. final.
                reg = reconstruct_regulation_score(
                    event.get("espn_event_id"), event["home_name"], event["away_name"],
                    event["home_goals"], event["away_goals"],
                )
                if reg is None:
                    match.home_goals_reg = None
                    match.away_goals_reg = None
                    deferred += 1
                    continue
                # Map ESPN's (home,away) orientation onto the stored row's orientation.
                if _to_db_name(event["home_name"]) == home_name:
                    match.home_goals_reg, match.away_goals_reg = reg[0], reg[1]
                else:
                    match.home_goals_reg, match.away_goals_reg = reg[1], reg[0]
                resolved += 1
            session.commit()
        logger.info(
            "WC regulation reconcile: %d checked, %d extra-time (%d resolved, "
            "%d deferred)", checked, extra_time, resolved, deferred,
        )
        return {"checked": checked, "extra_time": extra_time,
                "resolved": resolved, "deferred": deferred}
    except Exception as e:  # noqa: BLE001 - must never break the pipeline (Rule 6)
        logger.warning("WC regulation reconcile failed (non-fatal): %s", e)
        return {"checked": 0, "extra_time": 0, "resolved": 0, "deferred": 0}


def _find_espn_event(events: list, home_name: str, away_name: str):
    """The ESPN event whose team pair (mapped to our DB names) matches this match's
    unordered {home, away} pair. ESPN's home/away may be flipped vs our stored row, so
    we compare the unordered pair. Returns the event dict or None."""
    want = {home_name, away_name}
    for e in events:
        pair = {_to_db_name(e.get("home_name", "")), _to_db_name(e.get("away_name", ""))}
        if pair == want:
            return e
    return None
