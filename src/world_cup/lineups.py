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
from pathlib import Path

import requests
import yaml
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.database.db import get_session
from src.world_cup.models import WCMatch, WCLineup

logger = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "worldcup_2026.yaml"

# ESPN team display name → our WCTeam.name, only where they differ (extend as found).
_ESPN_NAME_MAP = {
    "Congo DR": "DR Congo",
    "United States": "USA",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Czechia": "Czech Republic",
    "Türkiye": "Turkey",
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
        # ESPN's scoreboard date can differ from ours by a day for late kickoffs
        # (date-boundary), so query a ±1-day window (ESPN accepts a YYYYMMDD-YYYYMMDD
        # range) and match on team names within it.
        try:
            _d = _dt.date.fromisoformat(m.date)
            date_range = f"{_d - _dt.timedelta(days=1):%Y%m%d}-{_d + _dt.timedelta(days=1):%Y%m%d}"
        except (ValueError, TypeError):
            date_range = (m.date or "").replace("-", "")

    # 1. Resolve the ESPN event id from the scoreboard for the match's date window.
    try:
        sb = requests.get(f"{ESPN_BASE}/scoreboard",
                          params={"dates": date_range}, timeout=30)
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
                # player_name stays the short displayName (the rotation signal +
                # existing rows key on it). full_name / espn_athlete_id (WC-11A-01)
                # are the fuller identity the player-rate join needs — the feed
                # carries both, and the short form alone zero-matches club datasets.
                pname = ath.get("displayName") or ath.get("fullName")
                if not pname:
                    continue
                full_name = ath.get("fullName") or ath.get("displayName")
                espn_id = ath.get("id")
                espn_id = str(espn_id) if espn_id is not None else None
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
                    existing.full_name = full_name
                    existing.espn_athlete_id = espn_id
                    existing.position = pos
                    existing.jersey = jersey
                    existing.formation = formation
                    existing.captured_at = _utc_now_iso()
                else:
                    s.add(WCLineup(match_id=match_id, team_id=team_id, player_name=pname,
                                   full_name=full_name, espn_athlete_id=espn_id,
                                   is_starter=is_starter, position=pos, jersey=jersey,
                                   formation=formation, captured_at=_utc_now_iso()))
                stored += 1
        s.commit()

    logger.info("ESPN lineup: match %d, event %s — %d players stored (%d starters)",
                match_id, event_id, stored, starters)
    return {"status": "ok", "match_id": match_id, "event_id": event_id,
            "players": stored, "starters": starters}


# ============================================================================
# WC-10-07: Rotation / absence signal for the research card (decision-support)
# ============================================================================

def _rotation_threshold() -> int:
    try:
        with open(_CONFIG_PATH) as f:
            data = (yaml.safe_load(f) or {}).get("lineups", {})
        return int(data.get("rotation_threshold", 5))
    except (FileNotFoundError, yaml.YAMLError, TypeError, ValueError):
        return 5


def _starter_rows(session, match_id: int, team_id: int) -> list[dict]:
    """Rich starter rows — ``name`` (ESPN short displayName), ``full_name`` and
    ``position`` — for a team's confirmed XI in a match. These are the identity
    columns the player-rate resolver needs (WC-11A); ``lineup_signal``'s name-only
    ``xi`` doesn't carry them. Read-only."""
    rows = session.execute(
        select(WCLineup.player_name, WCLineup.full_name, WCLineup.position)
        .where(WCLineup.match_id == match_id, WCLineup.team_id == team_id,
               WCLineup.is_starter == 1)
    ).all()
    return [{"name": n, "full_name": fn, "position": p} for n, fn, p in rows]


def _prior_starter_rows(session, team_id: int, before_date: str,
                        exclude_match_id: int) -> list[dict]:
    """Rich starter rows (name + full_name + position) for the team's most recent
    PRIOR captured XI — the baseline the lineup-impact what-if scales against
    (WC-11A-02) — or ``[]`` when there's no prior XI. Same selection as
    ``_prior_xi``, just carrying the resolver's identity columns."""
    rows = session.execute(
        select(WCLineup.player_name, WCLineup.full_name, WCLineup.position,
               WCLineup.match_id)
        .join(WCMatch, WCLineup.match_id == WCMatch.id)
        .where(WCLineup.team_id == team_id, WCLineup.is_starter == 1,
               WCMatch.date < before_date, WCLineup.match_id != exclude_match_id)
        .order_by(WCMatch.date.desc())
    ).all()
    if not rows:
        return []
    latest_mid = rows[0][3]                       # the most recent prior match
    return [{"name": n, "full_name": fn, "position": p}
            for n, fn, p, mid in rows if mid == latest_mid]


def _prior_xi(session, team_id: int, before_date: str, exclude_match_id: int) -> set | None:
    """The team's starting XI (player names) in its most recent match BEFORE
    before_date that has a captured lineup, or None when there's no prior XI."""
    rows = _prior_starter_rows(session, team_id, before_date, exclude_match_id)
    return {r["name"] for r in rows} if rows else None


def lineup_signal(match_id: int) -> dict | None:
    """Per-team confirmed XI + a rotation flag (changes vs the team's previous
    captured XI) for the research card (WC-10-07). **Decision-support only** — it
    never touches the model, predictions, or value bets. Returns None for an
    unknown match; each team's ``status`` covers the not-announced / no-prior cases.
    """
    threshold = _rotation_threshold()
    out: dict = {"match_id": match_id, "threshold": threshold, "teams": []}
    with get_session() as session:
        m = session.execute(
            select(WCMatch)
            .options(joinedload(WCMatch.home_team), joinedload(WCMatch.away_team))
            .where(WCMatch.id == match_id)
        ).unique().scalar_one_or_none()
        if not m:
            return None

        for team, tid in ((m.home_team, m.home_team_id), (m.away_team, m.away_team_id)):
            name = team.name if team else "?"
            xi = session.execute(
                select(WCLineup).where(
                    WCLineup.match_id == match_id,
                    WCLineup.team_id == tid,
                    WCLineup.is_starter == 1,
                )
            ).scalars().all()
            if not xi:
                out["teams"].append({"team": name, "status": "not_announced"})
                continue

            current = {p.player_name for p in xi}
            entry = {
                "team": name,
                "status": "announced",
                "formation": xi[0].formation,
                "xi": sorted(current),
                "changes": None,            # None = no prior XI to compare against
                "heavy_rotation": False,
            }
            prior = _prior_xi(session, tid, m.date, match_id)
            if prior:
                changed = len(current - prior)  # new starters vs the previous XI
                entry["changes"] = changed
                entry["heavy_rotation"] = changed >= threshold
            out["teams"].append(entry)
    return out
