"""World Cup results backfill + self-heal from ESPN's free scoreboard API.

WHY THIS EXISTS
---------------
``scrape_wc_results()`` reads The Odds API ``/scores`` endpoint, which only reaches
back 3 days (``daysFrom`` is capped at 3). So any WC result older than that window —
or any match that finished while WC capture was offline — can never be ingested by
that path. When daily WC capture started (~23 Jun 2026), every match from the 11 Jun
opener through ~19 Jun fell outside the window and was simply never loaded, leaving
each team showing a single played match in the group standings.

ESPN's free, key-less scoreboard (the same feed we already use for lineups) serves
every completed match by date with NO lookback limit, so we use it to:
  (a) one-time backfill the matches missed before daily capture began, and
  (b) self-heal — each pipeline run sweeps a recent date window and fills any past
      GROUP match still missing a result, so a gap like this can't silently form
      again regardless of the Odds API's 3-day horizon.

SCOPE: results only. Fixtures and odds still come from the Odds API; this never
invents future matches, only records completed ones. Group stage only — cross-group
(knockout) results are left to the existing path and the bracket logic, so we never
guess at a knockout pairing here.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import requests
from sqlalchemy import select

from src.database.db import get_session
from src.world_cup.lineups import ESPN_BASE, _to_db_name
from src.world_cup.models import WCMatch, WCTeam

logger = logging.getLogger(__name__)

_TIMEOUT = 20


def _daterange(start: date, end: date):
    """Yield each date from start to end inclusive."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def fetch_espn_results_for_date(d: date) -> list[dict]:
    """Completed WC matches ESPN lists for a single date.

    Each dict: ``{home_name, away_name, home_goals, away_goals, date}`` with RAW
    (un-mapped) ESPN team display names. Network or parse failures return ``[]`` and
    never raise — a flaky ESPN response must not break the pipeline (Rule 6).
    """
    try:
        resp = requests.get(
            f"{ESPN_BASE}/scoreboard",
            params={"dates": d.strftime("%Y%m%d")},
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning("ESPN scoreboard %s -> HTTP %d", d, resp.status_code)
            return []
        events = resp.json().get("events", [])
    except Exception as e:  # noqa: BLE001 - resilience over correctness here (Rule 6)
        logger.warning("ESPN scoreboard request failed for %s: %s", d, e)
        return []

    out: list[dict] = []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        status_type = ((ev.get("status") or {}).get("type") or {})
        if not status_type.get("completed"):
            continue  # in-play or scheduled — only record settled results
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        try:
            home_goals = int(home.get("score"))
            away_goals = int(away.get("score"))
        except (TypeError, ValueError):
            continue  # malformed score — skip rather than store garbage
        ev_date = (ev.get("date") or "")[:10] or d.strftime("%Y-%m-%d")
        out.append({
            "home_name": (home.get("team") or {}).get("displayName", ""),
            "away_name": (away.get("team") or {}).get("displayName", ""),
            "home_goals": home_goals,
            "away_goals": away_goals,
            "date": ev_date,
            # WC-ACC-02: event id + status detail let the regulation reconciler pull
            # the match's keyEvents and tell a 90-minute finish ('FT') from one that
            # ran to extra time / penalties ('FT-Pens', 'AET'). Additive — existing
            # result callers ignore these keys.
            "espn_event_id": ev.get("id"),
            "detail": status_type.get("detail") or status_type.get("description"),
        })
    return out


def _resolve_team(session, espn_name: str) -> WCTeam | None:
    """Map an ESPN display name to our WCTeam (via the shared ESPN name map)."""
    db_name = _to_db_name(espn_name)
    return session.execute(
        select(WCTeam).where(WCTeam.name == db_name)
    ).scalar_one_or_none()


def _find_group_match(session, home: WCTeam, away: WCTeam) -> WCMatch | None:
    """Find the existing group match for this pair in EITHER orientation.

    The published schedule fixes which side is "home", which can differ from
    ESPN's designation, so we match the unordered pair. Group teams meet exactly
    once, so the first hit is unambiguous.
    """
    return session.execute(
        select(WCMatch).where(
            WCMatch.stage == "group",
            (
                (WCMatch.home_team_id == home.id) & (WCMatch.away_team_id == away.id)
            ) | (
                (WCMatch.home_team_id == away.id) & (WCMatch.away_team_id == home.id)
            ),
        )
    ).scalars().first()


def backfill_wc_results_espn(start_date: str, end_date: str) -> dict:
    """Idempotently record completed WC GROUP results from ESPN for an inclusive
    ``[start_date, end_date]`` window (both ``YYYY-MM-DD``).

    For each completed match ESPN reports: update the existing group match's score
    (mapping ESPN's home/away onto the stored orientation) or create the group match
    if it is absent. Cross-group (knockout) results are skipped — out of scope here.
    Returns counts plus any unmapped ESPN team names so the name map can be extended.
    Idempotent: re-running re-asserts the same finished scores, creating no duplicates.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    updated = created = skipped = 0
    unmapped: set[str] = set()

    with get_session() as session:
        for d in _daterange(start, end):
            for r in fetch_espn_results_for_date(d):
                home = _resolve_team(session, r["home_name"])
                away = _resolve_team(session, r["away_name"])
                if not home or not away:
                    if not home:
                        unmapped.add(r["home_name"])
                    if not away:
                        unmapped.add(r["away_name"])
                    skipped += 1
                    continue

                match = _find_group_match(session, home, away)
                if match:
                    # Map ESPN's home/away onto the row's stored orientation.
                    if match.home_team_id == home.id:
                        match.home_goals = r["home_goals"]
                        match.away_goals = r["away_goals"]
                    else:
                        match.home_goals = r["away_goals"]
                        match.away_goals = r["home_goals"]
                    if match.status != "finished":
                        match.status = "finished"
                    if not match.date:
                        match.date = r["date"]
                    updated += 1
                elif home.group_letter and home.group_letter == away.group_letter:
                    session.add(WCMatch(
                        group_letter=home.group_letter,
                        stage="group",
                        date=r["date"],
                        home_team_id=home.id,
                        away_team_id=away.id,
                        home_goals=r["home_goals"],
                        away_goals=r["away_goals"],
                        status="finished",
                    ))
                    created += 1
                else:
                    # Different groups => a knockout pairing; leave to the existing
                    # path + bracket logic rather than guess a fixture here.
                    skipped += 1

    if unmapped:
        logger.warning("ESPN results backfill: unmapped team names %s "
                       "(add to _ESPN_NAME_MAP)", sorted(unmapped))
    logger.info("ESPN results backfill %s..%s: %d updated, %d created, %d skipped",
                start_date, end_date, updated, created, skipped)
    return {
        "updated": updated,
        "created": created,
        "skipped": skipped,
        "unmapped": sorted(unmapped),
    }


def self_heal_wc_results(lookback_days: int = 7, today: str | None = None) -> dict:
    """Pipeline gap-filler: sweep the last ``lookback_days`` of ESPN results so any
    group match the Odds API's 3-day window missed still gets recorded.

    Safe to call from the pipeline: never raises (a bad ESPN response or parse error
    returns zero counts instead of breaking the run, per Rule 6). ``today`` is
    injectable for tests; otherwise the current date is used.
    """
    try:
        end = datetime.strptime(today, "%Y-%m-%d").date() if today else datetime.now().date()
        start = end - timedelta(days=max(0, lookback_days))
        return backfill_wc_results_espn(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    except Exception as e:  # noqa: BLE001 - must never break the pipeline (Rule 6)
        logger.warning("WC results self-heal failed (non-fatal): %s", e)
        return {"updated": 0, "created": 0, "skipped": 0, "unmapped": []}
