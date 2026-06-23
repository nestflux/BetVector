"""
BetVector World Cup 2026 — Eastern-time display (WC-08-02)
==========================================================
WC matches are stored with a UTC date (``YYYY-MM-DD``) and a UTC kickoff
(``HH:MM``, taken from the Odds API ``commence_time``). The owner wants
kickoffs shown in US Eastern so the next game's time is obvious at a glance.

We convert to ``America/New_York`` (which is correctly EDT in summer, EST in
winter) and always label the result "ET" so it's unambiguous across the clock
change. A near-midnight UTC kickoff can land on a different Eastern calendar
date, so ``eastern_date()`` is provided for date-based filtering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


def to_eastern(date_str: str | None, kickoff_utc: str | None) -> datetime | None:
    """Combine a UTC date (``YYYY-MM-DD``) and UTC kickoff (``HH:MM`` or
    ``HH:MM:SS``) into a timezone-aware US Eastern datetime.

    Returns ``None`` when either input is missing or unparseable — callers show
    a placeholder rather than crashing a dashboard row.
    """
    if not date_str or not kickoff_utc:
        return None
    try:
        parts = kickoff_utc.strip().split(":")
        hh, mm = int(parts[0]), int(parts[1])
        y, mo, d = (int(x) for x in date_str.strip().split("-"))
        dt_utc = datetime(y, mo, d, hh, mm, tzinfo=timezone.utc)
        return dt_utc.astimezone(EASTERN)
    except (ValueError, IndexError, AttributeError):
        return None


def format_kickoff_et(
    date_str: str | None,
    kickoff_utc: str | None,
    *,
    with_day: bool = True,
    placeholder: str = "TBD",
) -> str:
    """Format a UTC kickoff as US Eastern, e.g. ``"Wed 3:00 PM ET"``.

    ``with_day=False`` drops the weekday → ``"3:00 PM ET"``. Returns
    ``placeholder`` when the kickoff is missing/unparseable.
    """
    et = to_eastern(date_str, kickoff_utc)
    if et is None:
        return placeholder
    day = et.strftime("%a ") if with_day else ""
    # %I is zero-padded (e.g. "03:00 PM"); strip the single leading zero on the
    # hour for a natural "3:00 PM" without the non-portable %-I directive.
    clock = et.strftime("%I:%M %p").lstrip("0")
    return f"{day}{clock} ET"


def eastern_date(date_str: str | None, kickoff_utc: str | None) -> str | None:
    """US Eastern calendar date (``YYYY-MM-DD``) of a UTC kickoff.

    May differ from the stored UTC date for late-evening/early kickoffs — use
    this for "today / next N days" filtering so games land on the right local
    day. ``None`` when unparseable.
    """
    et = to_eastern(date_str, kickoff_utc)
    return et.strftime("%Y-%m-%d") if et else None
