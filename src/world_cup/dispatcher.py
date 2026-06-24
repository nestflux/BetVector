"""
BetVector World Cup 2026 — Pre-Kickoff Dispatcher (WC-10-03)
============================================================
A schedule-proof trigger for per-match pre-kickoff runs. The morning pipeline
writes the day's fixtures to a LOCAL json cache; a launchd job runs this
dispatcher every ~15 min. When a match enters the pre-KO window (~40 min before
kickoff) and hasn't been prepped today, it fires the prematch run (WC-10-04) —
**exactly once** per match.

Free-tier discipline (WC-10-03): the idle heartbeat reads ONLY local json (the
fixture cache + the prepped-state file) — it never opens a Neon connection. Neon
is touched only when a prematch run actually fires, so the DB stays autosuspended
between kickoffs and we don't burn free-tier compute on 96 daily wake-ups.

Why dynamic (not a fixed schedule): WC matches span ~11 kickoff times (1–11 PM
ET), 2–8/day, reshuffling each round. A 15-min heartbeat that acts only when a
match is imminent adapts to any schedule with zero manual retuning.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WC_DIR = PROJECT_ROOT / "data" / "world_cup"
CACHE_PATH = _WC_DIR / "today_fixtures.json"
STATE_PATH = _WC_DIR / "dispatcher_state.json"

PREKO_WINDOW_MIN = 40    # fire the odds pull when within this many minutes before kickoff
LINEUP_WINDOW_MIN = 60   # check ESPN for the XI from this many minutes before kickoff
                         # (free / no quota, so retried each tick until the XI is out)


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------- cache writer
def write_fixture_cache(path: Path = CACHE_PATH) -> int:
    """Write upcoming WC fixtures (match_id, kickoff UTC, status, teams) to the
    local cache. Called by the morning run, which already holds a Neon
    connection — this is the one place the dispatcher pipeline touches Neon.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload
    from src.database.db import get_session
    from src.world_cup.models import WCMatch

    rows = []
    with get_session() as s:
        matches = s.execute(
            select(WCMatch)
            .where(WCMatch.status != "finished")
            .options(joinedload(WCMatch.home_team), joinedload(WCMatch.away_team))
            .order_by(WCMatch.date)
        ).unique().scalars().all()
        for m in matches:
            if not m.kickoff_time:
                continue
            # kickoff_time is stored UTC ("HH:MM"); build a full ISO instant.
            rows.append({
                "match_id": m.id,
                "kickoff_utc": f"{m.date}T{m.kickoff_time}:00+00:00",
                "status": m.status,
                "home": m.home_team.name if m.home_team else "?",
                "away": m.away_team.name if m.away_team else "?",
            })

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"written_at": _utcnow().isoformat(), "fixtures": rows}, indent=2))
    logger.info("Fixture cache written: %d upcoming fixtures → %s", len(rows), path)
    return len(rows)


# ----------------------------------------------------------- prepped-state
def _load_state(today: str) -> dict:
    """Prepped match_ids for today. Resets automatically when the date rolls over
    (so a stale file from a prior day never blocks today's matches)."""
    state = _load_json(STATE_PATH) or {}
    if state.get("date") != today:
        return {"date": today, "prepped": []}
    state.setdefault("prepped", [])   # defensive: tolerate a partial/corrupted same-day file
    return state


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


# --------------------------------------------------------------- heartbeat
def _fire_prematch(match_id: int) -> None:
    """Trigger the focused pre-kickoff odds run for one match. Lazily imported so
    the idle heartbeat never even imports the pipeline/DB layer."""
    from src.world_cup.pipeline import run_prematch
    run_prematch(match_id)


def _fetch_lineup(match_id: int) -> dict:
    """Fetch the ESPN lineup for one match (lazily imported; free, no quota)."""
    from src.world_cup.lineups import fetch_wc_lineup
    return fetch_wc_lineup(match_id)


def run_dispatcher(now: _dt.datetime | None = None,
                   window_min: int = PREKO_WINDOW_MIN,
                   lineup_window_min: int = LINEUP_WINDOW_MIN) -> dict:
    """Heartbeat tick. Two passes per match:

    * **Odds** — fire the focused prematch run exactly once when the match enters
      [KO − window_min, KO) (costs Odds-API credits, so once-only via prepped-state).
    * **Lineup** — from [KO − lineup_window_min, KO), check ESPN for the XI; ESPN is
      free, so this retries each tick until the XI is published (then marked done).

    The idle path (no match in either window) reads only the local cache + state
    files and opens **no** Neon connection.
    """
    now = now or _utcnow()
    today = now.date().isoformat()

    cache = _load_json(CACHE_PATH)
    if not cache or not cache.get("fixtures"):
        logger.info("Dispatcher: no fixture cache — nothing to do")
        return {"fired": 0, "lineups": 0, "checked": 0, "reason": "no_cache"}

    state = _load_state(today)
    prepped = set(state["prepped"])
    lineups_done = set(state.get("lineups", []))
    fired: list[int] = []
    lineups: list[int] = []

    for fx in cache["fixtures"]:
        mid = fx.get("match_id")
        if mid is None:
            continue
        try:
            ko = _dt.datetime.fromisoformat(fx["kickoff_utc"])
        except (ValueError, KeyError, TypeError):
            continue
        label = f'{fx.get("home", "?")} v {fx.get("away", "?")}'

        # Odds fire — once per match in [KO − window_min, KO).
        if mid not in prepped and ko - _dt.timedelta(minutes=window_min) <= now < ko:
            logger.info("Dispatcher: match %s (%s) in pre-KO window — firing prematch",
                        mid, label)
            try:
                _fire_prematch(mid)
                prepped.add(mid)
                fired.append(mid)
            except Exception:
                logger.exception("Dispatcher: prematch run failed for match %s — "
                                 "leaving unprepped to retry next tick", mid)

        # Lineup capture — retry each tick in [KO − lineup_window_min, KO) until out.
        if mid not in lineups_done and ko - _dt.timedelta(minutes=lineup_window_min) <= now < ko:
            try:
                res = _fetch_lineup(mid)
                if res.get("status") == "ok":
                    lineups_done.add(mid)
                    lineups.append(mid)
                    logger.info("Dispatcher: lineup captured for match %s (%s)", mid, label)
            except Exception:
                logger.exception("Dispatcher: lineup fetch failed for match %s", mid)

    if fired or lineups:
        state["prepped"] = sorted(prepped)
        state["lineups"] = sorted(lineups_done)
        _save_state(state)

    logger.info("Dispatcher tick: %d checked, %d odds-fired %s, %d lineups %s",
                len(cache["fixtures"]), len(fired), fired or "", len(lineups), lineups or "")
    return {"fired": len(fired), "lineups": len(lineups),
            "checked": len(cache["fixtures"]), "match_ids": fired}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_dispatcher()


if __name__ == "__main__":
    main()
