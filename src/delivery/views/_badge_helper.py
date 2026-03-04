"""
BetVector — Team Badge Rendering Helper (E28-02)
==================================================
Shared helper for rendering team crest badges inline in Streamlit pages.

Loads badge images from ``data/badges/{team_id}.png``, base64-encodes them
for inline HTML rendering (Streamlit can't serve static files via
``unsafe_allow_html`` without base64), and caches loaded images in memory
to avoid re-reading files on every render cycle.

Design tokens (MP §8):
- Badge size: 20px height for inline, 28px for match headers
- ``vertical-align: middle`` to align with text baseline
- ``margin-right: 4px`` spacing between badge and name
- Graceful fallback to plain text if no badge file exists

Master Plan refs: MP §8 Design System
"""

from __future__ import annotations

import base64
import html as html_mod  # standard library HTML escaping (prevents XSS/entity issues)
import logging
from typing import Optional

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# Directory where badge images are cached (populated by backfill_team_logos.py)
BADGES_DIR = PROJECT_ROOT / "data" / "badges"

# In-memory cache: team_id → base64-encoded PNG string.
# Loaded once per session, avoids repeated disk reads on every render.
_badge_cache: dict[int, Optional[str]] = {}


def _load_badge_b64(team_id: int) -> Optional[str]:
    """Load a badge PNG file and return its base64-encoded string.

    Returns None if the badge file doesn't exist, is unreadable,
    or ``team_id`` is None.  Result is cached in ``_badge_cache``
    so subsequent calls for the same team_id are instant (no disk I/O).
    """
    if team_id is None:
        return None

    if team_id in _badge_cache:
        return _badge_cache[team_id]

    badge_path = BADGES_DIR / f"{team_id}.png"
    if not badge_path.exists():
        _badge_cache[team_id] = None
        return None

    try:
        raw = badge_path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        _badge_cache[team_id] = b64
        return b64
    except (OSError, IOError) as e:
        logger.warning("Failed to read badge for team %d: %s", team_id, e)
        _badge_cache[team_id] = None
        return None


def render_team_badge(
    team_id: int,
    team_name: str,
    size: int = 20,
    *,
    name_style: str = "",
) -> str:
    """Return HTML for a team badge + name, with graceful fallback.

    Parameters
    ----------
    team_id : int
        The local database Team.id — used to find the cached badge file.
    team_name : str
        The team's display name (shown after the badge, or alone if no badge).
        Automatically HTML-escaped to prevent entity issues (e.g. "&" in
        "Brighton & Hove Albion" becomes "&amp;").
    size : int
        Badge image height in pixels (default 20px for inline, use 28 for
        match headers).  Width is auto-scaled to maintain aspect ratio.
    name_style : str
        Optional inline CSS to apply to the team name ``<span>``.
        Example: ``"font-weight: 700; font-size: 24px;"``

    Returns
    -------
    str
        HTML fragment: ``<img ...> <span>Name</span>`` or just ``<span>Name</span>``
        if no badge is available.  Safe for use with ``st.markdown(...,
        unsafe_allow_html=True)``.
    """
    b64 = _load_badge_b64(team_id)

    # HTML-escape team name to prevent entity issues (e.g. "&" in
    # "Brighton & Hove Albion") and defend against injection.
    safe_name = html_mod.escape(team_name, quote=True)

    name_span = (
        f'<span style="{name_style}">{safe_name}</span>'
        if name_style
        else safe_name
    )

    if b64:
        return (
            f'<img src="data:image/png;base64,{b64}" '
            f'style="height: {size}px; vertical-align: middle; margin-right: 4px;" '
            f'alt="{safe_name}"> {name_span}'
        )
    # Graceful fallback: plain text, no broken image icon
    return name_span


def render_badge_only(team_id: int, team_name: str, size: int = 20) -> str:
    """Return HTML for just the badge image (no team name).

    Falls back to an empty string if no badge is available.
    Useful for compact layouts where the team name is rendered separately.
    """
    b64 = _load_badge_b64(team_id)
    if b64:
        safe_name = html_mod.escape(team_name, quote=True)
        return (
            f'<img src="data:image/png;base64,{b64}" '
            f'style="height: {size}px; vertical-align: middle;" '
            f'alt="{safe_name}">'
        )
    return ""
