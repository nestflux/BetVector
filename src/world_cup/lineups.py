"""
BetVector World Cup 2026 — Lineup Capture from ESPN (WC-10-06)
=============================================================
Fetch the official starting XI for a WC match from ESPN's free, key-less JSON API
(``site.api.espn.com/.../soccer/fifa.world``). API-Football's free tier has no 2026
access; ESPN serves the full WC 2026 XI — formation, starters, positions, jerseys —
for free, JSON, requests-only (stack-compliant). Decision-support only: this feeds
the rotation/absence flag on the research card (WC-10-07); it never changes the
model or value bets.

ESPN publishes the XI ~1h before kickoff, so the dispatcher re-checks each tick
(free, no quota) until 11 starters appear. ``fetch_wc_lineup`` is a graceful no-op
until then.
"""

from __future__ import annotations

import datetime as _dt
import logging

import requests
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.database.db import get_session
from src.world_cup.models import WCMatch, WCLineup

logger = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"

# ESPN team display name → our WCTeam.name, only where they differ (extend as found).
_ESPN_NAME_MAP = {
    "Congo DR": "DR Congo",
    "United States": "USA",
}


def _to_db_name(name: str) -> str:
    return _ESPN_NAME_MAP.get(name, name)


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def fetch_wc_lineup(match_id: int) -> dict:
    """Fetch + store the starting XI for a WC match from ESPN. Idempotent upsert.
    Returns ``{"status": "ok", ...}`` once the XI (11 starters) is published;
    ``no_lineup_yet`` until then; or an error status. Never raises."""
    with get_session() as s:
        m = s.execute(
            select(WCMatch)
            .options(joinedload(WCMatch.home_team), joinedload(WCMatch.away_team))
            .where(WCMatch.id == match_id)
        ).unique().scalar_one_or_none()
        if not m or not m.home_team or not m.away_team:
            return {"status": "no_match", "match_id": match_id}
        home, away = m.home_team.name, m.away_team.name
        home_id, away_id = m.home_team_id, m.away_team_id
        date_compact = (m.date or "").replace("-", "")   # YYYYMMDD for the scoreboard

    # 1. Resolve the ESPN event id from the scoreboard for the match's date.
    try:
        sb = requests.get(f"{ESPN_BASE}/scoreboard",
                          params={"dates": date_compact}, timeout=30)
    except requests.RequestException as e:
        logger.warning("ESPN scoreboard request failed for match %d: %s", match_id, e)
        return {"status": "scoreboard_error", "match_id": match_id}
    if sb.status_code != 200:
        return {"status": "scoreboard_error", "match_id": match_id}

    event_id = None
    for e in sb.json().get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        names = {_to_db_name(t.get("team", {}).get("displayName", ""))
                 for t in comp.get("competitors", [])}
        if home in names and away in names:
            event_id = e.get("id")
            break
    if not event_id:
        return {"status": "no_event", "match_id": match_id}

    # 2. Pull the summary; rosters are populated once the XI is announced.
    try:
        sm = requests.get(f"{ESPN_BASE}/summary",
                          params={"event": event_id}, timeout=30)
    except requests.RequestException as e:
        logger.warning("ESPN summary request failed for match %d: %s", match_id, e)
        return {"status": "summary_error", "match_id": match_id, "event_id": event_id}
    rosters = sm.json().get("rosters") if sm.status_code == 200 else None
    if not rosters:
        return {"status": "no_lineup_yet", "match_id": match_id, "event_id": event_id}

    # Require BOTH XIs (11 each) before persisting — ESPN can publish one side
    # first, and a partial store the dispatcher then marks "done" would never
    # be re-fetched, leaving the other XI incomplete. Per-team guard, not a sum.
    per_team = [sum(1 for p in t.get("roster", []) if p.get("starter")) for t in rosters]
    if len(per_team) < 2 or min(per_team) < 11:
        return {"status": "no_lineup_yet", "match_id": match_id,
                "event_id": event_id, "starters": sum(per_team)}
    starters = sum(per_team)

    # 3. Upsert players (idempotent on match_id + team_id + player_name).
    stored = 0
    with get_session() as s:
        for team in rosters:
            espn_team = _to_db_name(team.get("team", {}).get("displayName", ""))
            team_id = home_id if espn_team == home else (away_id if espn_team == away else None)
            if team_id is None:
                continue
            formation = team.get("formation")
            for p in team.get("roster", []):
                ath = p.get("athlete", {})
                pname = ath.get("displayName") or ath.get("fullName")
                if not pname:
                    continue
                pos = p.get("position")
                pos = pos.get("abbreviation") if isinstance(pos, dict) else pos
                jersey = p.get("jersey")
                jersey = int(jersey) if jersey and str(jersey).isdigit() else None
                is_starter = 1 if p.get("starter") else 0

                existing = s.execute(
                    select(WCLineup).where(
                        WCLineup.match_id == match_id,
                        WCLineup.team_id == team_id,
                        WCLineup.player_name == pname,
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.is_starter = is_starter
                    existing.position = pos
                    existing.jersey = jersey
                    existing.formation = formation
                    existing.captured_at = _utc_now_iso()
                else:
                    s.add(WCLineup(match_id=match_id, team_id=team_id, player_name=pname,
                                   is_starter=is_starter, position=pos, jersey=jersey,
                                   formation=formation, captured_at=_utc_now_iso()))
                stored += 1
        s.commit()

    logger.info("ESPN lineup: match %d, event %s — %d players stored (%d starters)",
                match_id, event_id, stored, starters)
    return {"status": "ok", "match_id": match_id, "event_id": event_id,
            "players": stored, "starters": starters}
