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

from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

EASTERN = ZoneInfo("America/New_York")

_WC_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "worldcup_2026.yaml"


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


# ============================================================================
# DF-02: Tournament window — drives the World Cup login landing page
# ============================================================================

def _as_date(v) -> date:
    """Coerce a YAML date / datetime / ISO string to a ``date``."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):           # bare YAML dates parse straight to date
        return v
    return date.fromisoformat(str(v).strip()[:10])


@lru_cache(maxsize=1)
def tournament_window() -> tuple[date, date] | None:
    """The WC 2026 ``[start_date, end_date]`` calendar window (inclusive) from
    ``worldcup_2026.yaml``'s ``tournament`` block, or ``None`` if it's unset or
    unparseable. Cached — a config date change takes effect on the next restart
    (Streamlit Cloud restarts on redeploy)."""
    try:
        with open(_WC_CONFIG_PATH) as f:
            t = (yaml.safe_load(f) or {}).get("tournament", {}) or {}
        start, end = t.get("start_date"), t.get("end_date")
        if not start or not end:
            return None
        return (_as_date(start), _as_date(end))
    except (FileNotFoundError, yaml.YAMLError, ValueError, TypeError):
        return None


def wc_window_active(today: date | None = None) -> bool:
    """True when ``today`` (default: the current US Eastern date) falls within the
    configured WC tournament window, inclusive. False when the window is unset or
    unparseable, so the dashboard keeps its normal landing page (Fixtures).

    The Eastern date is used for consistency with the WC kickoff display; the
    timezone only matters at the very first/last day of the window."""
    window = tournament_window()
    if window is None:
        return False
    if today is None:
        today = datetime.now(EASTERN).date()
    start, end = window
    return start <= today <= end


def days_to_final(today: date | None = None) -> int | None:
    """Whole days from ``today`` (default: the current US Eastern date) to the WC
    final — the configured tournament ``end_date`` (the final is the last match of
    the window). ``None`` when the window is unset/unparseable, and clamped at 0
    from the final onward.

    Deliberately counts to the CONFIGURED final date, not the latest fixture in
    the database: early in the tournament the Odds API has published only a
    rolling window of group fixtures (no knockout bracket yet), so the DB's max
    match date points at a group game weeks before the real final. The config
    (``worldcup_2026.yaml`` → ``tournament.end_date``) is the authoritative
    source."""
    window = tournament_window()
    if window is None:
        return None
    if today is None:
        today = datetime.now(EASTERN).date()
    _, end = window
    return max(0, (end - today).days)
